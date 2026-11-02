import io
from urllib.parse import urlparse
import httpx
import soundfile as sf
from .base import Audio, ProviderError


def trusted_url(url, host):
    parsed = urlparse(str(url))
    if parsed.scheme != 'https' or parsed.hostname != host or parsed.username or parsed.password:
        raise ProviderError('Invalid provider URL')
    return url


def inputs(text, language, voice, route):
    values = {'text': text, 'language': route.get('language', language),
              'reference_clip': voice.get('reference_clip'),
              'reference_transcript': voice.get('reference_transcript')}
    result = dict(route.get('extra_input', {}))
    for source, target in route['input_fields'].items():
        if values.get(source) is not None:
            result[target] = values[source]
    return result


async def json_request(client, method, url, **kwargs):
    response = await client.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()


async def download(client, url):
    parsed = urlparse(str(url))
    # Only provider-owned delivery hosts; no arbitrary URLs or credential forwarding.
    host = parsed.hostname or ''
    allowed = ('replicate.delivery', 'fal.media')
    if parsed.scheme != 'https' or parsed.username or parsed.password or not any(host == d or host.endswith('.' + d) for d in allowed):
        raise ProviderError('Invalid audio delivery URL')
    payload = bytearray()
    async with client.stream('GET', url) as response:
        response.raise_for_status()
        async for block in response.aiter_bytes():
            payload.extend(block)
            if len(payload) > 25 * 1024 * 1024:
                raise ProviderError('Provider audio too large')
    with sf.SoundFile(io.BytesIO(payload)) as audio:
        if audio.frames <= 0 or audio.frames > audio.samplerate * 180 or not 8000 <= audio.samplerate <= 192000 or not 1 <= audio.channels <= 8:
            raise ProviderError('Provider must return decodable audio under 180 seconds')
        return Audio(audio.read(dtype='float32', always_2d=True), audio.samplerate)
