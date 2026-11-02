"""Local runtime configuration. Never log this file or request bodies."""
from dataclasses import replace
from pathlib import Path
import json
import os
import re
import tempfile
import threading
from typing import Literal
from .settings import valid_cloudflare_account
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator


KEY_FIELDS = {'replicate': 'replicate_api_key', 'fal': 'fal_api_key', 'cloudflare': 'cloudflare_api_token'}


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['mock', 'replicate', 'fal', 'cloudflare', 'edge', 'free']
    replicate_api_key: SecretStr | None = None
    fal_api_key: SecretStr | None = None
    cloudflare_api_token: SecretStr | None = None
    cloudflare_account_id: str | None = None
    replicate_model: str | None = None
    fal_model: str | None = None

    @field_validator('replicate_api_key', 'fal_api_key', 'cloudflare_api_token')
    @classmethod
    def valid_key(cls, value):
        if value is not None:
            key = value.get_secret_value().strip()
            if key and (len(key) < 8 or len(key) > 4096 or not key.isascii() or any(c.isspace() for c in key)):
                raise ValueError('Key must be 8–4096 ASCII characters without spaces')
            return SecretStr(key)
        return value

    @field_validator('cloudflare_account_id')
    @classmethod
    def valid_account(cls, value):
        if value is None or value == '':
            return None
        if not valid_cloudflare_account(value):
            raise ValueError('Cloudflare Account ID must be exactly 32 hexadecimal characters')
        return value

    @field_validator('replicate_model', 'fal_model')
    @classmethod
    def valid_model(cls, value):
        if value is None or not value.strip():
            return None
        value = value.strip()
        if len(value) > 250 or not re.fullmatch(r'[\w-]+/[\w/-]+(?::[a-fA-F0-9]{64})?', value, flags=re.ASCII):
            raise ValueError('Model must be an owner/model slug with optional version')
        return value


def require_local(request: Request, origins):
    # Personal/local guard only. Replace with authenticated authorization for commercial use.
    # Do not trust forwarded client headers; launch uvicorn with --no-proxy-headers.
    if request.client is None or request.client.host not in ('127.0.0.1', '::1'):
        raise HTTPException(403, 'Provider settings and voice changes are available only on this computer')
    origin = request.headers.get('origin')
    if origin is not None and origin not in origins:
        raise HTTPException(403, 'Origin is not permitted')


class RuntimeStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'settings.json'
        self.lock = threading.RLock()

    def read(self):
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('Invalid runtime configuration')
        return value

    def _write(self, data):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        fd, name = tempfile.mkstemp(dir=self.directory, prefix='.settings-')
        try:
            os.chmod(name, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def update(self, body):
        with self.lock:
            data = self.read()
            data['provider'] = body.provider
            for name, field in KEY_FIELDS.items():
                key = getattr(body, field)
                if key and key.get_secret_value():
                    data[field] = key.get_secret_value()
            for name in ('replicate', 'fal'):
                model = getattr(body, name + '_model')
                if model:
                    data[name + '_model'] = model
            if body.cloudflare_account_id:
                data['cloudflare_account_id'] = body.cloudflare_account_id
            self._write(data)

    def delete_key(self, name):
        with self.lock:
            data = self.read()
            # Tombstone suppresses .env/process fallback until a new key is saved.
            data[KEY_FIELDS[name]] = ''
            self._write(data)

    def delete_cloudflare_account(self):
        with self.lock:
            data = self.read()
            data['cloudflare_account_id'] = ''
            self._write(data)

    def effective(self, base):
        data = self.read()
        keys = dict(base.keys)
        models = dict(base.model_overrides)
        for name, field in KEY_FIELDS.items():
            if field in data:
                keys[name] = data[field]
        for name in ('replicate', 'fal'):
            if data.get(name + '_model'):
                models[name] = data[name + '_model']
        return replace(base, provider=data.get('provider', base.provider),
                       provider_explicit=('provider' in data) or base.provider_explicit,
                       keys=keys, model_overrides=models,
                       cloudflare_account_id=data.get('cloudflare_account_id', base.cloudflare_account_id))


def public_settings(settings):
    info = {}
    for name in ('mock', 'replicate', 'fal', 'cloudflare', 'edge', 'free'):
        key = settings.keys.get(name) or ''
        _, route = settings.route('en', provider_name=name)
        info[name] = {'has_key': bool(key), 'key_hint': key[-4:] if len(key) > 4 else '',
                      'model': route.get('model', '') if name != 'free' else '',
                      'requires_key': name in KEY_FIELDS}
        if name == 'cloudflare':
            account = settings.cloudflare_account_id
            info[name].update(has_account_id=valid_cloudflare_account(account),
                              account_id=account if valid_cloudflare_account(account) else '')
    return {'provider': settings.selected_provider(), 'providers': info,
            'resolved_providers': {language: settings.route(language)[0] for language in ('hi', 'en')}}
