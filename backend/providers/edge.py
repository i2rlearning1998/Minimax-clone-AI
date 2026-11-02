"""Unofficial Edge online TTS: personal testing only, no cloning or API key."""
import asyncio
import edge_tts
from .base import TTSProvider, ProviderError, ProviderConfigurationError, validate_capabilities
from .http import decode_audio, MAX_AUDIO_BYTES


class EdgeProvider(TTSProvider):
    async def generate(self, text, language, voice, route):
        validate_capabilities('edge', language, voice)
        identifier = voice.get('id') or route.get('default_voice_id')
        selected = route.get('voice_map', {}).get(identifier)
        if not selected:
            raise ProviderConfigurationError('Edge voice mapping is missing')
        audio = bytearray()
        # Network iteration is async; CPU/native decoding is off the event loop.
        communicator = edge_tts.Communicate(text=text, voice=selected)
        async for event in communicator.stream():
            if event['type'] == 'audio':
                audio.extend(event['data'])
                if len(audio) > MAX_AUDIO_BYTES:
                    raise ProviderError('Provider audio too large')
        return await asyncio.to_thread(decode_audio, bytes(audio))
