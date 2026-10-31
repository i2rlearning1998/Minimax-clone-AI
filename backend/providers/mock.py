import numpy as np
from .base import Audio, TTSProvider


class MockProvider(TTSProvider):
    async def generate(self, text, language, voice, route):
        duration = max(0.2, len(text) / 15)
        return Audio(np.zeros(round(duration * 24000), dtype=np.float32), 24000)
