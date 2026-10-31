"""Custom voice metadata and clips; file paths stay private to the backend."""
from contextlib import closing
import base64
import io
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
import numpy as np
import soundfile as sf
from fastapi import HTTPException

MAX_CLIP_BYTES = 10 * 1024 * 1024


def convert_clip(payload):
    if len(payload) > MAX_CLIP_BYTES:
        raise HTTPException(413, 'Clip must be at most 10 MiB')
    try:
        with sf.SoundFile(io.BytesIO(payload)) as source:
            duration = source.frames / source.samplerate
            if not 3 <= duration <= 30:
                raise HTTPException(422, 'Clip must be 3–30 seconds long')
            if not 8000 <= source.samplerate <= 192000 or not 1 <= source.channels <= 8:
                raise HTTPException(422, 'Unsupported clip sample rate or channel count')
            audio = source.read(dtype='float32', always_2d=True).mean(axis=1)
            if not np.isfinite(audio).all():
                raise HTTPException(422, 'Clip contains invalid samples')
            count = round(len(audio) * 24000 / source.samplerate)
            audio = np.interp(np.arange(count) * len(audio) / count, np.arange(len(audio)), audio)
            output = io.BytesIO()
            sf.write(output, np.clip(audio, -1, 1), 24000, format='WAV', subtype='PCM_16')
            return output.getvalue()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, 'Clip is not a supported decodable audio file') from None


class VoiceLibrary:
    def __init__(self, runtime_dir, clips_dir, demos):
        self.clips_dir = Path(clips_dir)
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(runtime_dir) / 'voices.sqlite3'
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.demos = demos
        with closing(self.connection()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS voices (id TEXT PRIMARY KEY, metadata TEXT NOT NULL)')

    def connection(self):
        # Caller closes using the contextlib.closing wrapper below where needed.
        return sqlite3.connect(self.db_path, timeout=10)

    def list(self):
        from contextlib import closing
        with closing(self.connection()) as db:
            custom = [json.loads(row[0]) for row in db.execute('SELECT metadata FROM voices ORDER BY rowid DESC')]
        return list(self.demos.values()) + custom

    def get(self, identifier):
        return next((v for v in self.list() if v['id'] == identifier), None)

    def path(self, identifier):
        # Only stored generated UUIDs may select a local file.
        voice = self.get(identifier)
        if voice is None or not voice.get('is_custom'):
            raise HTTPException(404, 'Custom voice not found')
        return self.clips_dir / (voice['id'] + '.wav')

    def public(self, voice):
        result = dict(voice)
        custom = bool(result.get('is_custom'))
        result.update(is_custom=custom, has_reference=bool(result.get('reference_clip')))
        # Never expose local paths/data URIs, even if configured in demo metadata.
        if not custom and result.get('preview_url') and not result['preview_url'].startswith(('https://', 'http://')):
            result['preview_url'] = None
        result['reference_clip'] = f"/voices/{result['id']}/clip" if custom else None
        return result

    def for_provider(self, voice):
        result = dict(voice)
        if result.get('is_custom'):
            try:
                data = self.path(voice['id']).read_bytes()
            except OSError:
                raise HTTPException(422, 'Reference clip is unavailable; upload the voice again') from None
            result['reference_clip'] = 'data:audio/wav;base64,' + base64.b64encode(data).decode('ascii')
        elif result.get('reference_clip'):
            # Demo fixtures are read-only; real references belong in uploaded custom voices.
            raise HTTPException(422, 'Upload this reference as a custom voice first')
        return result

    def add(self, fields, wav):
        from contextlib import closing
        identifier = str(uuid4())
        url = f'/voices/{identifier}/clip'
        voice = dict(id=identifier, name=fields['name'], language=fields['language'], gender=fields['gender'],
                     style=fields['style'], reference_transcript=fields['transcript'],
                     consent_note='User explicitly confirmed permission to use this voice.',
                     preview_url=url, reference_clip=url, is_custom=True, has_reference=True)
        path = self.clips_dir / (identifier + '.wav')
        try:
            with path.open('xb') as stream:
                stream.write(wav)
            with closing(self.connection()) as db, db:
                db.execute('INSERT INTO voices VALUES (?, ?)', (identifier, json.dumps(voice)))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return voice

    def delete(self, identifier):
        from contextlib import closing
        voice = self.get(identifier)
        if voice is None:
            raise HTTPException(404, 'Voice not found')
        if not voice.get('is_custom'):
            raise HTTPException(403, 'Demo voices are read-only')
        self.path(identifier).unlink(missing_ok=True)
        with closing(self.connection()) as db, db:
            db.execute('DELETE FROM voices WHERE id=?', (identifier,))
