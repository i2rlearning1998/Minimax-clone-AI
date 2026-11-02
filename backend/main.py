from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
import json
import logging
import sqlite3
import soundfile as sf
from fastapi import FastAPI, HTTPException, Query, Response, Request, UploadFile, File, Form
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool
from .audio import assemble
from .settings import Settings
from .runtime import RuntimeStore, ProviderUpdate, require_local, public_settings
from .voice_library import VoiceLibrary, MAX_CLIP_BYTES, convert_clip
from .storage import History
from .text import chunk_text, normalize_text
from .service import provider_for, generate_chunk
from .providers.base import ProviderError, ProviderTimeout, ProviderConfigurationError

log = logging.getLogger('tts')


class TTSRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=5000)
    language: Literal['hi', 'en']
    voice_id: str = Field(min_length=1, max_length=100)
    speed: float = Field(default=1.0, ge=0.5, le=2.0, allow_inf_nan=False)

    @field_validator('text')
    @classmethod
    def text_not_empty(cls, value):
        if not value.strip() or not any(c.isalnum() for c in value):
            raise ValueError('Text must contain letters or numbers')
        return value


class Generation(BaseModel):
    id: str
    audio_url: str
    duration_sec: float
    language: Literal['hi', 'en']
    voice_id: str


class HistoryEntry(Generation):
    text: str
    speed: float
    created_at: str


class Voice(BaseModel):
    id: str
    name: str
    language: Literal['hi', 'en']
    gender: str
    style: str
    preview_url: str | None
    reference_clip: str | None
    reference_transcript: str | None
    consent_note: str
    is_custom: bool = False
    has_reference: bool = False


def create_app(settings=None, provider=None):
    dynamic_environment = settings is None
    settings = settings or Settings.from_env()
    runtime = RuntimeStore(settings.runtime_dir)

    def current_settings():
        try:
            return runtime.effective(Settings.from_env() if dynamic_environment else settings)
        except (ValueError, OSError, TypeError):
            raise HTTPException(503, 'Could not read local provider settings') from None

    @asynccontextmanager
    async def lifespan(app):
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        app.state.history = History(settings.db_path)
        voices = json.loads(settings.voices_path.read_text(encoding='utf-8'))
        app.state.voices = {v.id: v.model_dump() for v in map(Voice.model_validate, voices)}
        app.state.library = VoiceLibrary(settings.runtime_dir, settings.clips_dir, app.state.voices)
        yield

    app = FastAPI(title='TTS platform', version='1.0.0', lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Content-Type'], allow_credentials=False)
    # httpx info/debug output can include signed delivery URLs; never log upstream bodies.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)

    @app.middleware('http')
    async def local_settings_guard(request, call_next):
        if request.url.path.startswith('/settings/provider'):
            try:
                require_local(request, settings.cors_origins)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail}, headers={'Cache-Control': 'no-store'})
        response = await call_next(request)
        if request.url.path.startswith('/settings/provider'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith('/settings/provider'):
            return JSONResponse(status_code=422, content={'detail': 'Invalid provider settings. Check provider, key length and model slug.'})
        return JSONResponse(status_code=422, content={'detail': 'Invalid request', 'errors': [
            {'field': '.'.join(str(x) for x in e['loc']), 'message': e['msg']} for e in exc.errors()]})

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        log.error('request_failed kind=%s', type(exc).__name__)
        return JSONResponse(status_code=500, content={'detail': 'Internal server error'})

    @app.get('/health')
    def health():
        with app.state.history.connection() as db:
            db.execute('SELECT 1')
        return {'status': 'ok'}

    @app.get('/voices', response_model=list[Voice])
    def voices(language: Literal['hi', 'en'] | None = None):
        return [app.state.library.public(v) for v in app.state.library.list() if language is None or v['language'] == language]

    @app.get('/voices/{voice_id}', response_model=Voice)
    def voice_detail(voice_id: str):
        voice = app.state.library.get(voice_id)
        if voice is None:
            raise HTTPException(404, 'Voice not found')
        return app.state.library.public(voice)

    @app.get('/settings/provider')
    def get_provider():
        return public_settings(current_settings())

    @app.put('/settings/provider')
    def put_provider(body: ProviderUpdate):
        try:
            runtime.update(body)
        except (OSError, ValueError):
            raise HTTPException(500, 'Could not save local provider settings') from None
        return public_settings(current_settings())

    @app.delete('/settings/provider/keys/{name}', status_code=204)
    def clear_provider_key(name: Literal['replicate', 'fal']):
        try:
            runtime.delete_key(name)
        except (OSError, ValueError):
            raise HTTPException(500, 'Could not clear provider key') from None
        return Response(status_code=204)

    @app.post('/settings/provider/test')
    async def test_provider():
        effective = current_settings()
        try:
            name, route = effective.route('en')
            selected = provider or provider_for(name, effective)
            clip = await generate_chunk(selected, 'Hello! Your voice studio is ready.', 'en', {}, route, effective)
            audio, rate = assemble([clip])
            return {'ok': True, 'message': 'Mock test succeeded (silent audio)' if name == 'mock' else 'Provider generated valid audio', 'duration_sec': round(len(audio) / rate, 6)}
        except Exception:
            # Never echo upstream exceptions, bodies, signed URLs or keys.
            return JSONResponse(status_code=502, content={'ok': False, 'message': 'Provider test failed. Check your saved key, model, credit balance and provider availability.', 'duration_sec': 0})

    @app.post('/voices', response_model=Voice, status_code=201)
    async def upload_voice(request: Request, name: str = Form(..., min_length=1, max_length=100),
                           language: Literal['hi', 'en'] = Form(...), gender: str = Form(..., min_length=1, max_length=50),
                           style: str = Form(..., min_length=1, max_length=100), transcript: str = Form(..., min_length=1, max_length=5000),
                           consent: bool = Form(...), clip: UploadFile = File(...)):
        require_local(request, settings.cors_origins)
        try:
            if not consent:
                raise HTTPException(422, 'Permission to use this voice must be confirmed')
            fields = {'name': name.strip(), 'language': language, 'gender': gender.strip(), 'style': style.strip(), 'transcript': transcript.strip()}
            if not all(fields.values()):
                raise HTTPException(422, 'Voice fields cannot be blank')
            payload = await clip.read(MAX_CLIP_BYTES + 1)
            wav = await run_in_threadpool(convert_clip, payload)
            voice = await run_in_threadpool(app.state.library.add, fields, wav)
            return app.state.library.public(voice)
        finally:
            await clip.close()

    @app.get('/voices/{voice_id}/clip')
    def voice_clip(voice_id: str):
        path = app.state.library.path(voice_id)
        if not path.is_file():
            raise HTTPException(404, 'Voice clip not found')
        return FileResponse(path, media_type='audio/wav')

    @app.delete('/voices/{voice_id}', status_code=204)
    def delete_voice(voice_id: str, request: Request):
        require_local(request, settings.cors_origins)
        app.state.library.delete(voice_id)
        return Response(status_code=204)

    @app.post('/tts', response_model=Generation, status_code=201)
    async def tts(body: TTSRequest):
        voice = app.state.library.get(body.voice_id)
        if voice is None:
            raise HTTPException(400, 'Invalid voice_id')
        if voice['language'] != body.language:
            raise HTTPException(400, 'Voice language does not match requested language')
        voice = app.state.library.for_provider(voice)
        effective = current_settings()
        try:
            name, route = effective.route(body.language)
            selected = provider or provider_for(name, effective)
        except (KeyError, ValueError, OSError, ProviderConfigurationError):
            raise HTTPException(503, 'TTS provider routing is not configured') from None
        normalized = normalize_text(body.text, body.language)
        identifier = str(uuid4())
        final = settings.output_dir / (identifier + '.wav')
        temporary = settings.output_dir / (identifier + '.tmp')
        saved = False
        try:
            chunks = []
            for text in chunk_text(normalized):
                chunks.append(await generate_chunk(selected, text, body.language, voice, route, effective))
            audio, rate = await run_in_threadpool(assemble, chunks, body.speed)
            await run_in_threadpool(sf.write, temporary, audio, rate, format='WAV', subtype='PCM_16')
            temporary.replace(final)
            result = {'id': identifier, 'audio_url': f'/audio/{identifier}.wav',
                      'duration_sec': round(len(audio) / rate, 6), 'language': body.language, 'voice_id': body.voice_id}
            await run_in_threadpool(app.state.history.add, dict(result, text=body.text, speed=body.speed, created_at=datetime.now(timezone.utc).isoformat()))
            saved = True
            log.info('generation_complete id=%s provider=%s chunks=%d', identifier, name, len(chunks))
            return result
        except ProviderConfigurationError:
            raise HTTPException(503, 'Provider API key or model is not configured') from None
        except ProviderTimeout:
            raise HTTPException(504, 'Speech provider timed out after 3 attempts') from None
        except ProviderError:
            raise HTTPException(502, 'Speech provider failed to generate valid audio') from None
        except (OSError, sqlite3.Error):
            raise HTTPException(500, 'Could not save generation') from None
        finally:
            temporary.unlink(missing_ok=True)
            # Do not leave audio behind when the SQLite insert fails.
            if final.exists() and not saved:
                final.unlink(missing_ok=True)

    @app.get('/audio/{identifier}.wav')
    def audio(identifier: UUID):
        path = settings.output_dir / (str(identifier) + '.wav')
        if not app.state.history.get(str(identifier)) or not path.is_file():
            raise HTTPException(404, 'Audio not found')
        return FileResponse(path, media_type='audio/wav', filename=path.name)

    @app.get('/history', response_model=list[HistoryEntry])
    def history(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        return app.state.history.list(limit, offset)

    @app.delete('/history/{identifier}', status_code=204)
    def delete(identifier: UUID):
        identifier = str(identifier)
        if not app.state.history.get(identifier):
            raise HTTPException(404, 'Generation not found')
        path = settings.output_dir / (identifier + '.wav')
        # Remove file first; failed deletion leaves a retriable history entry.
        path.unlink(missing_ok=True)
        app.state.history.delete(identifier)
        return Response(status_code=204)

    return app


app = create_app()
