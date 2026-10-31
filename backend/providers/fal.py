import asyncio
import httpx
from .base import TTSProvider, ProviderError, ProviderConfigurationError
from .http import inputs, json_request, trusted_url, download


class FalProvider(TTSProvider):
    def __init__(self, key, timeout=60, transport=None):
        self.key, self.timeout, self.transport = key, timeout, transport

    async def generate(self, text, language, voice, route):
        model = route.get('model', '')
        if not self.key or not model:
            raise ProviderConfigurationError('fal key or model is missing')
        if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/' for c in model) or len(model.split('/')) < 2:
            raise ProviderConfigurationError('Invalid fal model')
        headers = {'Authorization': f'Key {self.key}'}
        body = inputs(text, language, voice, route)
        # Multilingual Chatterbox accepts a language name or reference URL as voice.
        if route.get('reference_voice_field') and voice.get('reference_clip'):
            body[route['reference_voice_field']] = voice['reference_clip']
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            job = await json_request(client, 'POST', f'https://queue.fal.run/{model}', headers=headers, json=body)
            status_url = trusted_url(job['status_url'], 'queue.fal.run')
            result_url = trusted_url(job['response_url'], 'queue.fal.run')
            while True:
                result = await json_request(client, 'GET', status_url, headers=headers)
                if result['status'] == 'COMPLETED':
                    break
                if result['status'] not in ('IN_QUEUE', 'IN_PROGRESS'):
                    raise ProviderError('Provider generation failed')
                await asyncio.sleep(0.25)
            result = await json_request(client, 'GET', result_url, headers=headers)
            return await download(client, result['audio']['url'])
