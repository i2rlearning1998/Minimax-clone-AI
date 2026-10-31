import asyncio
import httpx
from .base import TTSProvider, ProviderError, ProviderConfigurationError
from .http import inputs, json_request, trusted_url, download


class ReplicateProvider(TTSProvider):
    def __init__(self, key, timeout=60, transport=None):
        self.key, self.timeout, self.transport = key, timeout, transport

    async def generate(self, text, language, voice, route):
        if not self.key or not route.get('model'):
            raise ProviderConfigurationError('Replicate key or model is missing')
        model = route['model']
        # Community models use a pinned version; official models accept owner/name.
        if ':' in model:
            url = 'https://api.replicate.com/v1/predictions'
            body = {'version': model.rsplit(':', 1)[1]}
        else:
            if len(model.split('/')) != 2 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_/' for c in model):
                raise ProviderConfigurationError('Invalid Replicate model')
            url = f'https://api.replicate.com/v1/models/{model}/predictions'
            body = {}
        body['input'] = inputs(text, language, voice, route)
        headers = {'Authorization': f'Bearer {self.key}'}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            result = await json_request(client, 'POST', url, headers=headers, json=body)
            while result['status'] not in ('succeeded', 'failed', 'canceled'):
                await asyncio.sleep(0.25)
                url = trusted_url(result['urls']['get'], 'api.replicate.com')
                result = await json_request(client, 'GET', url, headers=headers)
            if result['status'] != 'succeeded':
                raise ProviderError('Provider generation failed')
            output = result['output']
            if isinstance(output, list):
                output = output[0]
            return await download(client, output)
