import secrets
import asyncio
import io
import json
from dataclasses import replace
from uuid import uuid4
import numpy as np
import pytest
import soundfile as sf
import httpx
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.settings import Settings
from backend.text import normalize_text, chunk_text
from backend.audio import assemble
from backend.providers.base import Audio, ProviderError, ProviderTimeout
from backend.providers.mock import MockProvider
from backend.providers.replicate import ReplicateProvider
from backend.providers.fal import FalProvider
from backend.service import generate_chunk


@pytest.fixture
def settings(tmp_path):
    return Settings(output_dir=tmp_path / 'outputs', db_path=tmp_path / 'history.sqlite3', timeout=0.05, retry_delay=0, runtime_dir=tmp_path / 'runtime', clips_dir=tmp_path / 'clips')


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def request(**kwargs):
    return {'text': 'Hello world.', 'language': 'en', 'voice_id': 'en-01', **kwargs}


def test_generation_history_audio_delete_and_persistence(client, settings):
    response = client.post('/tts', json=request())
    assert response.status_code == 201
    generation = response.json()
    assert set(generation) == {'id', 'audio_url', 'duration_sec', 'language', 'voice_id'}
    wav = client.get(generation['audio_url'])
    assert wav.status_code == 200 and wav.headers['content-type'] == 'audio/wav'
    samples, rate = sf.read(io.BytesIO(wav.content))
    assert rate == 24000 and np.all(samples == 0)
    assert len(samples) / rate == pytest.approx(generation['duration_sec'], abs=1e-6)
    with TestClient(create_app(settings)) as reopened:
        history = reopened.get('/history').json()
        assert history[0]['id'] == generation['id']
        assert history[0]['text'] == 'Hello world.' and history[0]['speed'] == 1
        assert reopened.delete('/history/' + generation['id']).status_code == 204
    assert client.get(generation['audio_url']).status_code == 404
    assert client.get('/history').json() == []
    assert not list(settings.output_dir.glob('*.wav'))
    assert client.delete('/history/' + generation['id']).status_code == 404


def test_hindi_speed_and_cors(client):
    payload = request(text='नमस्ते दुनिया।', language='hi', voice_id='hi-01')
    normal = client.post('/tts', json=payload).json()
    faster = client.post('/tts', json={**payload, 'speed': 2}).json()
    assert faster['duration_sec'] == pytest.approx(normal['duration_sec'] / 2, abs=0.0001)
    response = client.options('/tts', headers={'Origin': 'http://localhost:3000', 'Access-Control-Request-Method': 'POST'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == 'http://localhost:3000'
    assert client.get('/health').json() == {'status': 'ok'}


def test_voices(client):
    voices = client.get('/voices').json()
    assert len(voices) == 6
    for language in ['hi', 'en']:
        filtered = client.get('/voices', params={'language': language}).json()
        assert len(filtered) == 3 and all(v['language'] == language for v in filtered)
    assert client.get('/voices/en-01').json() == voices[3]
    assert client.get('/voices/missing').status_code == 404
    assert client.get('/voices?language=fr').status_code == 422
    assert all(set(v) == {'id','name','language','gender','style','preview_url','reference_clip','reference_transcript','consent_note','is_custom','has_reference'} for v in voices)


@pytest.mark.parametrize('change,status', [({'text':''},422),({'text':'   '},422),({'text':'!!!'},422),({'text':'x'*5001},422),({'language':'fr'},422),({'voice_id':'unknown'},400),({'voice_id':'hi-01'},400),({'speed':0.49},422),({'speed':2.01},422),({'unexpected':'field'},422)])
def test_invalid_requests(client, change, status):
    response = client.post('/tts', json=request(**change))
    assert response.status_code == status and 'detail' in response.json()
    assert client.get('/history').json() == []


def test_missing_audio_and_id_validation(client):
    assert client.get(f'/audio/{uuid4()}.wav').status_code == 404
    assert client.get('/audio/not-a-uuid.wav').status_code == 422
    assert client.delete('/history/not-a-uuid').status_code == 422
    assert client.get('/history?limit=0').status_code == 422


def test_normalization_and_chunking():
    assert normalize_text('  Dr.  Smith has 42 cats. ', 'en') == 'Doctor Smith has forty two cats.'
    assert normalize_text('डॉ. शर्मा के १२ फल।', 'hi') == 'डॉक्टर शर्मा के एक दो फल।'
    assert normalize_text('Room 007', 'en') == 'Room zero zero seven'
    for text in ['Hello world. ' * 100, 'नमस्ते दुनिया। ' * 100, 'x' * 700, 'word ' * 200]:
        text = text.strip()
        chunks = chunk_text(text)
        assert len(chunks) > 1 and all(0 < len(c) <= 250 for c in chunks)
        assert ''.join(''.join(chunks).split()) == ''.join(text.split())
    assert chunk_text('') == []


def test_long_generation_is_chunked(client):
    response = client.post('/tts', json=request(text='Hello world. ' * 100))
    assert response.status_code == 201
    chunks = chunk_text(normalize_text('Hello world. ' * 100, 'en'))
    expected = sum(max(.2, len(c)/15) for c in chunks) + .08*(len(chunks)-1)
    assert response.json()['duration_sec'] == pytest.approx(expected, abs=.001)


def test_join_resample_speed_loudness_and_silence():
    chunk = Audio(np.ones((8000,2), dtype=np.float32)*.01, 8000)
    audio, rate = assemble([chunk, chunk], speed=2)
    assert rate == 24000 and len(audio) == 24000+1920
    assert np.all(audio[12000:13920] == 0)
    assert np.sqrt(np.mean(audio**2)) == pytest.approx(.1, rel=.001)
    assert np.max(np.abs(audio)) <= .98
    assert np.all(assemble([Audio(np.zeros(8000),8000)])[0] == 0)
    with pytest.raises(ProviderError):
        assemble([Audio(np.array([float('nan')]),24000)])


class FailingProvider(MockProvider):
    def __init__(self, failures=3, timeout=False):
        self.calls=0
        self.failures=failures
        self.timeout=timeout

    async def generate(self, *args):
        self.calls += 1
        if self.timeout:
            await asyncio.sleep(1)
        if self.calls <= self.failures:
            raise RuntimeError('SECRET should never reach logs or response')
        return await super().generate(*args)


@pytest.mark.parametrize('timeout,status', [(False,502),(True,504)])
def test_failures_timeout_retries_no_history(settings, caplog, timeout, status):
    provider=FailingProvider(timeout=timeout)
    with TestClient(create_app(settings,provider)) as client:
        result=client.post('/tts',json=request())
        assert result.status_code == status
        assert provider.calls == 3
        assert 'SECRET' not in result.text and 'SECRET' not in caplog.text
        assert client.get('/history').json() == []
        assert not list(settings.output_dir.iterdir())


def test_retry_recovers(settings):
    provider=FailingProvider(failures=2)
    with TestClient(create_app(settings,provider)) as client:
        assert client.post('/tts',json=request()).status_code == 201
        assert provider.calls == 3


def test_missing_key_and_bad_routing(settings):
    with TestClient(create_app(replace(settings,provider='replicate'))) as client:
        assert client.post('/tts',json=request()).status_code == 503
    with TestClient(create_app(replace(settings,provider='unknown'))) as client:
        assert client.post('/tts',json=request()).status_code == 503


def test_database_failure_cleans_files(settings, monkeypatch):
    import sqlite3
    app=create_app(settings)
    with TestClient(app) as client:
        def fail(item):
            raise sqlite3.OperationalError('cannot save')
        monkeypatch.setattr(app.state.history,'add',fail)
        assert client.post('/tts',json=request()).status_code == 500
        assert not list(settings.output_dir.iterdir())


def test_pagination(client):
    ids=[client.post('/tts',json=request(text=str(i))).json()['id'] for i in range(3)]
    assert [x['id'] for x in client.get('/history?limit=2&offset=1').json()] == ids[-2::-1]


def test_route_override(settings, tmp_path):
    routes=json.loads(settings.routing_path.read_text())
    routes['hi']['provider']='fal'
    path=tmp_path/'routing.json'; path.write_text(json.dumps(routes))
    custom=replace(settings,routing_path=path,model_overrides={'fal':'custom/model'})
    name,route=custom.route('hi')
    assert name=='fal' and route['model']=='custom/model'
    assert custom.route('en')[0]=='mock'


def test_environment_keys_override_dotenv(monkeypatch, tmp_path):
    import backend.settings as module
    monkeypatch.setattr(module,'ROOT',tmp_path)
    process_key, file_key, fal_key = (secrets.token_hex(24) for _ in range(3))
    monkeypatch.setenv('REPLICATE_API_TOKEN',process_key)
    (tmp_path/'.env').write_text(f'REPLICATE_API_TOKEN={file_key}\nFAL_KEY={fal_key}\n')
    settings=Settings.from_env()
    assert settings.keys=={'replicate':process_key,'fal':fal_key}
    assert process_key not in repr(settings)


@pytest.mark.parametrize('kind', ['replicate','fal'])
def test_hosted_adapter_contract(settings, kind):
    stream=io.BytesIO(); sf.write(stream,np.zeros(240),24000,format='WAV')
    seen=[]
    token=secrets.token_hex(24)
    def handler(req):
        seen.append(req)
        if req.url.host.endswith('delivery') or req.url.host.endswith('media'):
            assert 'authorization' not in req.headers
            return httpx.Response(200,content=stream.getvalue())
        assert req.headers['authorization'] == (('Bearer ' if kind=='replicate' else 'Key ') + token)
        if req.method=='POST':
            data=json.loads(req.content)
            if kind=='replicate':
                assert data['input']['text']=='Hello' and data['input']['language']=='en'
                assert len(data['version'])==64
                return httpx.Response(201,json={'status':'processing','urls':{'get':'https://api.replicate.com/v1/predictions/123'}})
            assert data['text']=='Hello' and data['voice']=='english'
            return httpx.Response(200,json={'status_url':'https://queue.fal.run/test/requests/123/status','response_url':'https://queue.fal.run/test/requests/123'})
        if kind=='replicate':
            return httpx.Response(200,json={'status':'succeeded','output':'https://replicate.delivery/test.wav'})
        if req.url.path.endswith('/status'):
            return httpx.Response(200,json={'status':'COMPLETED'})
        return httpx.Response(200,json={'audio':{'url':'https://v3.fal.media/test.wav'}})
    cls=ReplicateProvider if kind=='replicate' else FalProvider
    provider=cls(token,transport=httpx.MockTransport(handler))
    route=replace(settings,provider=kind).route('en')[1]
    result=asyncio.run(generate_chunk(provider,'Hello','en',{},route,replace(settings,timeout=2)))
    assert result.sample_rate==24000 and len(result.samples)==240
    assert len(seen)==(3 if kind=='replicate' else 4)


def test_upstream_auth_url_rejected():
    from backend.providers.http import trusted_url
    with pytest.raises(ProviderError):
        trusted_url('https://attacker.invalid/poll','api.replicate.com')
