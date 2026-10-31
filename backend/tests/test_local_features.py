import asyncio
import base64
import io
import json
import os
import secrets
import stat
from dataclasses import replace
import httpx
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.settings import Settings
from backend.providers.http import download
from backend.providers.mock import MockProvider
from backend.providers.replicate import ReplicateProvider
from backend.providers.fal import FalProvider
from backend.service import generate_chunk


@pytest.fixture
def settings(tmp_path):
    return Settings(output_dir=tmp_path/'outputs', db_path=tmp_path/'history.sqlite3',
                    runtime_dir=tmp_path/'runtime', clips_dir=tmp_path/'clips', timeout=1, retry_delay=0)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), client=('127.0.0.1', 12345)) as client:
        yield client


def wav(seconds=3, rate=16000, channels=2, format='WAV'):
    buffer=io.BytesIO()
    x=.1*np.sin(2*np.pi*220*np.arange(round(seconds*rate))/rate)
    sf.write(buffer, np.repeat(x[:,None],channels,axis=1),rate,format=format)
    return buffer.getvalue()


def upload(client, audio=None, **changes):
    fields={'name':'My recording','language':'hi','gender':'neutral','style':'calm','transcript':'नमस्ते दुनिया।','consent':'true',**changes}
    return client.post('/voices',data=fields,files={'clip':('recording.wav',audio if audio is not None else wav(),'audio/wav')})


def test_keys_masked_atomic_permissions_and_clear(settings, caplog):
    token=secrets.token_hex(32)
    with TestClient(create_app(replace(settings,keys={'replicate':token})),client=('127.0.0.1',1)) as client:
        result=client.get('/settings/provider')
        assert result.status_code==200 and token not in result.text
        assert result.json()['providers']['replicate']=={'has_key':True,'key_hint':token[-4:],'model':settings.route('en','replicate')[1]['model']}
        saved=client.put('/settings/provider',json={'provider':'replicate','replicate_api_key':token})
        assert saved.status_code==200 and token not in saved.text and token not in caplog.text
        assert saved.headers['cache-control']=='no-store'
        assert stat.S_IMODE((settings.runtime_dir/'settings.json').stat().st_mode)==0o600
        assert client.put('/settings/provider',json={'provider':'mock','replicate_api_key':''}).status_code==200
        assert client.get('/settings/provider').json()['providers']['replicate']['has_key']
        result=client.delete('/settings/provider/keys/replicate')
        assert result.status_code==204 and result.content==b''
        assert not client.get('/settings/provider').json()['providers']['replicate']['has_key']
    # Restart retains tombstone and does not restore an environment/.env fallback.
    with TestClient(create_app(replace(settings,keys={'replicate':token})),client=('::1',1)) as restarted:
        assert not restarted.get('/settings/provider').json()['providers']['replicate']['has_key']


@pytest.mark.parametrize('host',['192.168.1.2','8.8.8.8','127.0.0.2','testclient'])
def test_loopback_only_guard_before_validation(settings,host):
    with TestClient(create_app(settings),client=(host,1234)) as client:
        for method,path in [('GET','/settings/provider'),('PUT','/settings/provider'),('DELETE','/settings/provider/keys/fal'),('POST','/settings/provider/test')]:
            response=client.request(method,path,headers={'X-Forwarded-For':'127.0.0.1'})
            assert response.status_code==403
        assert not (settings.runtime_dir/'settings.json').exists()


def test_untrusted_origin_blocked_and_cors_allowed(client):
    assert client.get('/settings/provider',headers={'Origin':'https://evil.invalid'}).status_code==403
    preflight=client.options('/settings/provider',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'PUT','Access-Control-Request-Headers':'content-type'})
    assert preflight.status_code==200
    assert preflight.headers['access-control-allow-origin']=='http://localhost:5173'


def test_invalid_settings_never_echo_key(client,caplog):
    token=secrets.token_hex(30)
    response=client.put('/settings/provider',json={'provider':token,'replicate_api_key':token})
    assert response.status_code==422 and token not in response.text and token not in caplog.text
    assert client.put('/settings/provider',json={'provider':'fal','fal_model':'invalid'}).status_code==422


def test_settings_apply_without_restart_and_test_is_explicit(settings,monkeypatch):
    calls=[]
    class Recording(MockProvider):
        async def generate(self,*args):
            calls.append(args)
            return await super().generate(*args)
    seen=[]
    def factory(name,effective):
        seen.append((name,effective.keys.get(name)))
        return Recording()
    monkeypatch.setattr('backend.main.provider_for',factory)
    with TestClient(create_app(settings),client=('127.0.0.1',1)) as client:
        assert client.get('/settings/provider').status_code==200
        token=secrets.token_hex(24)
        assert client.put('/settings/provider',json={'provider':'fal','fal_api_key':token,'fal_model':'custom/model'}).status_code==200
        assert calls==[] and seen==[]
        response=client.post('/settings/provider/test')
        assert response.status_code==200 and response.json()['ok']
        assert response.json()['duration_sec']>0
        assert seen==[('fal',token)] and calls[0][3]['model']=='custom/model'
        assert client.get('/history').json()==[]
        client.put('/settings/provider',json={'provider':'mock'})
        assert client.post('/tts',json={'text':'Hello','language':'en','voice_id':'en-01'}).status_code==201
        assert seen[-1][0]=='mock'


def test_test_endpoint_sanitizes_upstream_failure(settings,caplog):
    token=secrets.token_hex(30)
    class Failing(MockProvider):
        async def generate(self,*args):
            raise RuntimeError(token)
    with TestClient(create_app(settings,Failing()),client=('127.0.0.1',1)) as client:
        result=client.post('/settings/provider/test')
        assert result.status_code==502 and result.json()['ok'] is False
        assert token not in result.text and token not in caplog.text


def test_custom_upload_preview_tts_and_delete(settings):
    captured=[]
    class Recording(MockProvider):
        async def generate(self,*args):
            captured.append(args)
            return await super().generate(*args)
    with TestClient(create_app(settings,Recording()),client=('127.0.0.1',1)) as client:
        result=upload(client)
        assert result.status_code==201
        voice=result.json(); identifier=voice['id']
        assert voice['is_custom'] and voice['has_reference']
        assert str(settings.clips_dir) not in result.text
        assert voice['preview_url']==f'/voices/{identifier}/clip'
        clip=client.get(voice['preview_url'])
        data,rate=sf.read(io.BytesIO(clip.content),always_2d=True)
        assert rate==24000 and data.shape==(72000,1)
        assert sf.info(io.BytesIO(clip.content)).subtype=='PCM_16'
        assert len(client.get('/voices?language=hi').json())==4
        assert client.get(f'/voices/{identifier}').json()==voice
        result=client.post('/tts',json={'text':'नमस्ते','language':'hi','voice_id':identifier})
        assert result.status_code==201
        reference=captured[0][2]
        assert reference['reference_clip'].startswith('data:audio/wav;base64,')
        assert base64.b64decode(reference['reference_clip'].split(',',1)[1])==clip.content
        assert reference['reference_transcript']=='नमस्ते दुनिया।'
        assert client.delete('/voices/hi-01').status_code==403
        assert client.delete(f'/voices/{identifier}').status_code==204
        assert client.get(voice['preview_url']).status_code==404
        assert client.get(f'/voices/{identifier}').status_code==404
        assert not list(settings.clips_dir.iterdir())
        assert len(client.get('/history').json())==1


@pytest.mark.parametrize('seconds,status',[(2.9,422),(30.1,422),(3,201),(30,201)])
def test_clip_duration(client,seconds,status):
    assert upload(client,wav(seconds)).status_code==status


@pytest.mark.parametrize('change',[{'consent':'false'},{'name':'   '},{'transcript':''},{'language':'fr'}])
def test_upload_invalid_fields(client,change):
    assert upload(client,**change).status_code==422
    assert len(client.get('/voices').json())==6


def test_upload_bad_audio_and_size(client):
    assert upload(client,b'not audio').status_code==422
    assert upload(client,b'x'*(10*1024*1024+1)).status_code==413
    assert client.get('/voices/not-a-path/clip').status_code==404


def test_upload_metadata_survives_restart(client,settings):
    voice=upload(client).json()
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get('/voices/'+voice['id']).json()==voice


def test_mp3_provider_output_is_decoded_offline():
    encoded=wav(3,format='MP3')
    assert not encoded.startswith(b'RIFF')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=encoded))) as client:
            return await download(client,'https://v3.fal.media/output.mp3')
    audio=asyncio.run(run())
    assert audio.sample_rate==16000 and len(audio.samples)>=48000
    assert np.isfinite(audio.samples).all()


@pytest.mark.parametrize('kind',['replicate','fal'])
def test_reference_data_uri_provider_fields(settings,kind):
    token=secrets.token_hex(24)
    data_uri='data:audio/wav;base64,'+base64.b64encode(wav()).decode()
    voice={'reference_clip':data_uri,'reference_transcript':'An exact transcript.'}
    def handler(request):
        if request.method=='POST':
            payload=json.loads(request.content)
            if kind=='replicate':
                assert payload['input']['reference_audio']==data_uri
                assert payload['input']['language']=='hi'
                return httpx.Response(201,json={'status':'succeeded','output':'https://replicate.delivery/audio.wav'})
            assert payload['voice']==data_uri and payload['custom_audio_language']=='hindi'
            return httpx.Response(200,json={'status_url':'https://queue.fal.run/job/status','response_url':'https://queue.fal.run/job/result'})
        if request.url.host=='queue.fal.run':
            return httpx.Response(200,json={'status':'COMPLETED'} if request.url.path.endswith('status') else {'audio':{'url':'https://v3.fal.media/audio.wav'}})
        assert 'authorization' not in request.headers
        return httpx.Response(200,content=wav())
    cls=ReplicateProvider if kind=='replicate' else FalProvider
    route=settings.route('hi',provider_name=kind)[1]
    audio=asyncio.run(generate_chunk(cls(token,transport=httpx.MockTransport(handler)),'नमस्ते','hi',voice,route,settings))
    assert len(audio.samples)>0


def test_short_fallback_key_is_not_returned(settings):
    token=secrets.token_hex(2)
    with TestClient(create_app(replace(settings,keys={'fal':token})),client=('127.0.0.1',1)) as client:
        info=client.get('/settings/provider').json()['providers']['fal']
        assert info['has_key'] and info['key_hint']==''


def test_demo_local_preview_path_is_not_exposed(client):
    client.app.state.library.demos['hi-01']['preview_url']='/private/recording.wav'
    client.app.state.library.demos['hi-01']['reference_clip']='/private/reference.wav'
    voice=client.get('/voices/hi-01').json()
    assert voice['preview_url'] is None and voice['reference_clip'] is None
