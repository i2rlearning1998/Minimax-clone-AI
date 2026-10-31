import numpy as np
from .providers.base import ProviderError


def assemble(chunks, speed=1.0, sample_rate=24000, gap_sec=0.08):
    parts = []
    for chunk in chunks:
        samples = np.asarray(chunk.samples, dtype=np.float32)
        if samples.ndim == 2:
            samples = samples.mean(axis=1)
        if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all() or not 8000 <= chunk.sample_rate <= 192000 or len(samples) > chunk.sample_rate * 180:
            raise ProviderError('Invalid provider audio')
        n = max(1, round(len(samples) * sample_rate / chunk.sample_rate / speed))
        # Lightweight speed/resampling: changes pitch; no external ffmpeg required.
        samples = np.interp(np.arange(n) * len(samples) / n, np.arange(len(samples)), samples).astype(np.float32)
        if parts:
            parts.append(np.zeros(round(gap_sec * sample_rate), dtype=np.float32))
        parts.append(samples)
    if not parts:
        raise ProviderError('No audio chunks')
    audio = np.concatenate(parts)
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(audio)))
    if rms > 1e-8 and peak > 0:
        gain = min(10 ** (-20 / 20) / rms, 0.98 / peak)
        audio *= gain
    return audio, sample_rate
