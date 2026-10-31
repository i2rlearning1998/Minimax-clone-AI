import asyncio
import logging
import httpx
from .providers.base import ProviderError, ProviderTimeout, ProviderConfigurationError
from .providers.mock import MockProvider
from .providers.replicate import ReplicateProvider
from .providers.fal import FalProvider

log = logging.getLogger('tts')


def provider_for(name, settings):
    if name == 'mock':
        return MockProvider()
    if name == 'replicate':
        return ReplicateProvider(settings.keys.get(name), settings.timeout)
    if name == 'fal':
        return FalProvider(settings.keys.get(name), settings.timeout)
    raise ProviderConfigurationError('Unknown TTS provider')


async def generate_chunk(provider, text, language, voice, route, settings):
    # Initial attempt + two retries. Bound polling + download as one operation.
    for attempt in range(3):
        try:
            return await asyncio.wait_for(provider.generate(text, language, voice, route), timeout=settings.timeout)
        except ProviderConfigurationError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            error = ProviderTimeout('Speech provider timed out')
        except Exception:
            error = ProviderError('Speech provider failed')
        log.warning('provider_attempt_failed attempt=%d kind=%s', attempt + 1, type(error).__name__)
        if attempt < 2:
            await asyncio.sleep(settings.retry_delay * (attempt + 1))
    raise error from None
