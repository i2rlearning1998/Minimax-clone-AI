from abc import ABC, abstractmethod
from dataclasses import dataclass
import numpy as np


class ProviderError(Exception):
    """Sanitized provider failure; never expose upstream bodies or credentials."""


class ProviderTimeout(ProviderError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


@dataclass
class Audio:
    samples: np.ndarray
    sample_rate: int


class TTSProvider(ABC):
    @abstractmethod
    async def generate(self, text: str, language: str, voice: dict, route: dict) -> Audio:
        """Generate one chunk at normal speed. Service applies requested speed once."""
        raise NotImplementedError


CLOUDFLARE_HINDI_MESSAGE = 'Cloudflare MeloTTS Hindi support nahi karta. Hindi ke liye Edge ya fal chuno.'
NO_CLONE_MESSAGE = 'Ye provider voice clone nahi karta. Apni awaaz ke liye fal ya Replicate chuno.'
FREE_LIMIT_MESSAGE = 'Free daily limit shayad khatam ho gayi, kal try karo ya doosra provider chuno.'


class ProviderInputError(ProviderError):
    """Only application-defined capability messages, never upstream text."""


class ProviderLimitError(ProviderError):
    def __init__(self):
        super().__init__(FREE_LIMIT_MESSAGE)


def validate_capabilities(name, language, voice):
    if name in ('cloudflare', 'edge') and (voice.get('is_custom') or voice.get('reference_clip')):
        raise ProviderInputError(NO_CLONE_MESSAGE)
    if name == 'cloudflare' and language != 'en':
        raise ProviderInputError(CLOUDFLARE_HINDI_MESSAGE)
