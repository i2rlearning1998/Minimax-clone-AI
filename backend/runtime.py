"""Local runtime configuration. Never log this file or request bodies."""
from dataclasses import replace
from pathlib import Path
import json
import os
import re
import tempfile
import threading
from typing import Literal
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator


class ProviderUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['mock', 'replicate', 'fal']
    replicate_api_key: SecretStr | None = None
    fal_api_key: SecretStr | None = None
    replicate_model: str | None = None
    fal_model: str | None = None

    @field_validator('replicate_api_key', 'fal_api_key')
    @classmethod
    def valid_key(cls, value):
        if value is not None:
            key = value.get_secret_value().strip()
            if key and (len(key) < 8 or len(key) > 4096 or not key.isascii() or any(c.isspace() for c in key)):
                raise ValueError('Key must be 8–4096 ASCII characters without spaces')
            return SecretStr(key)
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
            for name in ('replicate', 'fal'):
                key = getattr(body, name + '_api_key')
                if key and key.get_secret_value():
                    data[name + '_api_key'] = key.get_secret_value()
                model = getattr(body, name + '_model')
                if model:
                    data[name + '_model'] = model
            self._write(data)

    def delete_key(self, name):
        with self.lock:
            data = self.read()
            # Tombstone suppresses .env/process fallback until a new key is saved.
            data[name + '_api_key'] = ''
            self._write(data)

    def effective(self, base):
        data = self.read()
        keys = dict(base.keys)
        models = dict(base.model_overrides)
        for name in ('replicate', 'fal'):
            if name + '_api_key' in data:
                keys[name] = data[name + '_api_key']
            if data.get(name + '_model'):
                models[name] = data[name + '_model']
        return replace(base, provider=data.get('provider', base.provider),
                       provider_explicit=('provider' in data) or base.provider_explicit,
                       keys=keys, model_overrides=models)


def public_settings(settings):
    info = {}
    for name in ('mock', 'replicate', 'fal'):
        key = settings.keys.get(name) or ''
        _, route = settings.route('en', provider_name=name)
        info[name] = {'has_key': bool(key), 'key_hint': key[-4:] if len(key) > 4 else '', 'model': route.get('model', '')}
    return {'provider': settings.route('en')[0], 'providers': info}
