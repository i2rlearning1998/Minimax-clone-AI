"""Cloudflare Workers AI MeloTTS. Request names live in routing.json."""
import asyncio
import base64
import json
import re
import httpx
from .base import TTSProvider, ProviderError, ProviderConfigurationError, ProviderLimitError, validate_capabilities
from .http import inputs, download, decode_audio, MAX_AUDIO_BYTES
from ..settings import valid_cloudflare_account


class CloudflareProvider(TTSProvider):
    def __init__(self, key, account_id, timeout=60, transport=None):
        self.key, self.account_id, self.timeout, self.transport = key, account_id, timeout, transport

    async def generate(self, text, language, voice, route):
        validate_capabilities('cloudflare', language, voice)
        if not self.key or not valid_cloudflare_account(self.account_id):
            raise ProviderConfigurationError('Cloudflare token and a valid Account ID are required')
        model = route.get('model', '')
        if not re.fullmatch(r'@cf/[\w-]+/[\w-]+', model, flags=re.ASCII):
            raise ProviderConfigurationError('Invalid Cloudflare model configuration')
        url = f'https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run/{model}'
        headers = {'Authorization': f'Bearer {self.key}'}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            async with client.stream('POST', url, headers=headers, json=inputs(text, language, voice, route)) as response:
                if response.status_code in (402, 429):
                    raise ProviderLimitError()
                payload = bytearray()
                async for block in response.aiter_bytes():
                    payload.extend(block)
                    if len(payload) > MAX_AUDIO_BYTES * 4 // 3 + 4096:
                        raise ProviderError('Provider response too large')
                content_type = response.headers.get('content-type', '')
                if content_type.startswith('audio/') or 'octet-stream' in content_type:
                    response.raise_for_status()
                    return await asyncio.to_thread(decode_audio, bytes(payload))
                try:
                    data = json.loads(payload)
                except (ValueError, UnicodeError):
                    raise ProviderError('Invalid Cloudflare response') from None
                if isinstance(data, dict) and (data.get('success') is False or response.is_error):
                    # Classify quota errors locally; never return/log upstream error text.
                    errors = str(data.get('errors', '')).lower()
                    if any(word in errors for word in ('quota', 'daily limit', 'rate limit', 'free allocation', 'usage limit', 'neuron limit')):
                        raise ProviderLimitError()
                    raise ProviderError('Cloudflare generation failed')
                response.raise_for_status()
            result = data.get('result', data) if isinstance(data, dict) else data
            if isinstance(result, dict):
                result = next((result.get(field) for field in route.get('audio_fields', ['audio', 'audio_url']) if result.get(field)), None)
            if isinstance(result, dict):
                result = result.get('url')
            if not isinstance(result, str) or not result:
                raise ProviderError('Cloudflare audio is missing')
            if result.startswith(('https://', 'http://')):
                # No authorization header, no redirects, only configured delivery domains.
                return await download(client, result, allowed=tuple(route.get('audio_url_hosts', [])))
            if result.startswith('data:'):
                header, _, result = result.partition(',')
                if ';base64' not in header:
                    raise ProviderError('Invalid Cloudflare audio encoding')
            try:
                audio = base64.b64decode(result, validate=True)
            except (ValueError, TypeError):
                raise ProviderError('Invalid Cloudflare audio encoding') from None
            return await asyncio.to_thread(decode_audio, audio)
