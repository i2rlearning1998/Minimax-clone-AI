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
