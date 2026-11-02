import asyncio
import base64
import json
import secrets
from dataclasses import replace
import httpx
import pytest
from fastapi.testclient import TestClient
from backend.main import create_app
from backend.providers.cloudflare import CloudflareProvider
from backend.providers.edge import EdgeProvider
from backend.providers.base import ProviderInputError, ProviderLimitError, ProviderConfigurationError, CLOUDFLARE_HINDI_MESSAGE, NO_CLONE_MESSAGE, FREE_LIMIT_MESSAGE
from backend.providers.mock import MockProvider
from backend.service import generate_chunk
from backend.runtime import RuntimeStore
from backend.tests.test_local_features import settings, client, wav, upload


@pytest.mark.parametrize('kind', ['base64', 'data_uri', 'mp3', 'url'])
def test_cloudflare_format_and_decode(settings, kind):
    token, account = secrets.token_hex(24), secrets.token_hex(16)
    audio = wav(format='MP3' if kind == 'mp3' else 'WAV')
    def handler(request):
        if request.method == 'GET':
            assert 'authorization' not in request.headers
            return httpx.Response(200, content=audio)
        assert str(request.url) == f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/myshell-ai/melotts'
        assert request.headers['authorization'] == 'Bearer ' + token
        assert json.loads(request.content) == {'prompt': 'Hello', 'lang': 'en'}
        if kind == 'mp3':
            return httpx.Response(200, content=audio, headers={'content-type': 'audio/mpeg'})
        value = base64.b64encode(audio).decode()
        if kind == 'data_uri': value = 'data:audio/wav;base64,' + value
        if kind == 'url': value = 'https://audio.r2.dev/test.wav'
        return httpx.Response(200, json={'success': True, 'result': {'audio': value}})
    provider = CloudflareProvider(token, account, transport=httpx.MockTransport(handler))
    result = asyncio.run(provider.generate('Hello', 'en', {}, settings.route('en', 'cloudflare')[1]))
    assert result.sample_rate == 16000 and len(result.samples) >= 48000


@pytest.mark.parametrize('account', ['../escape', 'a'*31, 'g'*32, 'a'*33, ' ' + 'a'*32])
def test_invalid_account(client, settings, account):
    response = client.put('/settings/provider', json={'provider': 'cloudflare', 'cloudflare_account_id': account})
    assert response.status_code == 422
    provider = CloudflareProvider(secrets.token_hex(24), account)
    with pytest.raises(ProviderConfigurationError):
        asyncio.run(provider.generate('Hello', 'en', {}, settings.route('en', 'cloudflare')[1]))


def test_cloudflare_hindi(client):
    client.put('/settings/provider', json={'provider':'cloudflare'})
    response = client.post('/tts', json={'text':'नमस्ते', 'language':'hi', 'voice_id':'hi-01'})
    assert response.status_code == 422 and response.json()['detail'] == CLOUDFLARE_HINDI_MESSAGE


@pytest.mark.parametrize('voice,expected', [('hi-01','hi-IN-SwaraNeural'),('hi-02','hi-IN-MadhurNeural'),('hi-03','hi-IN-SwaraNeural'),('en-01','en-US-JennyNeural'),('en-02','en-US-GuyNeural'),('en-03','en-US-AriaNeural')])
def test_edge_mapping_mp3(settings, monkeypatch, voice, expected):
    encoded = wav(format='MP3')
    class Communicate:
        def __init__(self, text, voice):
            assert text == 'Test' and voice == expected
        async def stream(self):
            yield {'type':'WordBoundary', 'text':'Test'}
            yield {'type':'audio', 'data':encoded[:100]}
            yield {'type':'audio', 'data':encoded[100:]}
    monkeypatch.setattr('backend.providers.edge.edge_tts.Communicate', Communicate)
    language = voice[:2]
    result = asyncio.run(EdgeProvider().generate('Test', language, {'id':voice}, settings.route(language, 'edge')[1]))
    assert result.sample_rate == 16000 and len(result.samples) >= 48000


@pytest.mark.parametrize('has_token,account_ok,expected', [(False,False,'edge'),(True,False,'edge'),(False,True,'edge'),(True,True,'cloudflare')])
def test_free_routing(settings, has_token, account_ok, expected):
    effective = replace(settings, provider='free', provider_explicit=True,
                        keys={'cloudflare':secrets.token_hex(24) if has_token else ''},
                        cloudflare_account_id=secrets.token_hex(16) if account_ok else '')
    assert effective.route('hi')[0] == 'edge'
    assert effective.route('en')[0] == expected
    assert effective.selected_provider() == 'free'


@pytest.mark.parametrize('provider', ['edge','cloudflare','free'])
def test_custom_voice_rejected(client, provider):
    voice = upload(client, language='en', transcript='Hello there').json()
    client.put('/settings/provider', json={'provider':provider})
    response = client.post('/tts', json={'text':'Hello', 'language':'en', 'voice_id':voice['id']})
    assert response.status_code == 422 and response.json()['detail'] == NO_CLONE_MESSAGE
    assert client.get('/history').json() == []


def test_cloudflare_settings_mask_clear_runtime_priority(settings, caplog):
    token, old, account = secrets.token_hex(24), secrets.token_hex(24), secrets.token_hex(16)
    base = replace(settings, keys={'cloudflare':old}, cloudflare_account_id=account)
    with TestClient(create_app(base), client=('127.0.0.1',1)) as client:
        response = client.put('/settings/provider', json={'provider':'free','cloudflare_api_token':token,'cloudflare_account_id':account})
        assert response.status_code == 200 and token not in response.text and old not in response.text
        data = response.json()
        assert data['provider'] == 'free' and data['resolved_providers'] == {'hi':'edge','en':'cloudflare'}
        assert data['providers']['cloudflare']['key_hint'] == token[-4:]
        assert data['providers']['cloudflare']['has_account_id']
        assert not data['providers']['edge']['requires_key']
        assert client.put('/settings/provider', json={'provider':'free','cloudflare_api_token':''}).status_code == 200
        assert RuntimeStore(settings.runtime_dir).effective(base).keys['cloudflare'] == token
        assert (settings.runtime_dir/'settings.json').stat().st_mode & 0o777 == 0o600
        assert client.delete('/settings/provider/keys/cloudflare').status_code == 204
        assert client.get('/settings/provider').json()['resolved_providers']['en'] == 'edge'
        assert client.delete('/settings/provider/cloudflare/account').status_code == 204
        effective = RuntimeStore(settings.runtime_dir).effective(base)
        assert effective.keys['cloudflare'] == '' and effective.cloudflare_account_id == ''
        assert token not in caplog.text


def test_env_cloudflare(settings, monkeypatch):
    from backend.settings import Settings
    token, account = secrets.token_hex(24), secrets.token_hex(16)
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN',token)
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID',account)
    base = Settings.from_env()
    assert base.keys['cloudflare'] == token and base.cloudflare_account_id == account


@pytest.mark.parametrize('status', [429, 200])
def test_quota_sanitized_retries(settings, caplog, status):
    token, account = secrets.token_hex(24), secrets.token_hex(16)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'success':False,'errors':[{'message':'Daily limit '+token}]})
    provider = CloudflareProvider(token,account,transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderLimitError, match=FREE_LIMIT_MESSAGE):
        asyncio.run(generate_chunk(provider,'Hello','en',{},settings.route('en','cloudflare')[1],settings))
    assert len(calls) == 3 and token not in caplog.text


@pytest.mark.parametrize('provider', ['edge','cloudflare','free'])
def test_connection_new_providers(client, monkeypatch, provider):
    seen=[]
    monkeypatch.setattr('backend.main.provider_for',lambda name, effective: (seen.append(name) or MockProvider()))
    client.put('/settings/provider',json={'provider':provider})
    assert seen == []
    response = client.post('/settings/provider/test')
    assert response.status_code == 200 and response.json()['ok']
    assert seen == ['edge' if provider == 'free' else provider]


def test_new_settings_loopback(settings):
    with TestClient(create_app(settings),client=('192.168.1.1',1)) as client:
        assert client.delete('/settings/provider/cloudflare/account').status_code == 403
        assert client.delete('/settings/provider/keys/cloudflare').status_code == 403
