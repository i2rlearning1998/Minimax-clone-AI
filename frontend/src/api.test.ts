import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, audioUrl, GENERATION_TIMEOUT_MS } from './api';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('API contract', () => {
  it('keeps HTTP statuses and displays detail plus 422 validation messages', async () => {
    const mock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Invalid request', errors: [{ message: 'Speed must be at most 2' }] }), { status: 422 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Provider API key or model is not configured' }), { status: 503 }));
    vi.stubGlobal('fetch', mock);
    await expect(api.generate({ text: 'Hello', language: 'en', voice_id: 'en-01', speed: 3 })).rejects.toMatchObject({ status: 422, message: 'Invalid request: Speed must be at most 2' });
    await expect(api.voices('hi')).rejects.toMatchObject({ status: 503, message: 'Provider API key or model is not configured' });
    expect(mock).toHaveBeenCalledTimes(2); // No automatic retries.
  });

  it('reports network failure and waits ten minutes before timing out without retrying POST', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(api.history()).rejects.toMatchObject({ kind: 'network', status: null });
    vi.useFakeTimers();
    const mock = vi.fn((_url, options: RequestInit) => new Promise((_resolve, reject) => {
      options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    vi.stubGlobal('fetch', mock);
    const promise = api.generate({ text: 'Hello', language: 'en', voice_id: 'en-01', speed: 1 }).catch(error => error);
    expect(GENERATION_TIMEOUT_MS).toBeGreaterThanOrEqual(300_000);
    await vi.advanceTimersByTimeAsync(GENERATION_TIMEOUT_MS - 1);
    expect((mock.mock.calls[0][1].signal as AbortSignal).aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    const error = await promise;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.kind).toBe('timeout');
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it('accepts empty 204 delete without calling json and resolves audio against the API', async () => {
    const response = new Response(null, { status: 204 });
    const json = vi.spyOn(response, 'json');
    const mock = vi.fn().mockResolvedValue(response);
    vi.stubGlobal('fetch', mock);
    await expect(api.deleteHistory('example-id')).resolves.toBeUndefined();
    expect(json).not.toHaveBeenCalled();
    expect(mock.mock.calls[0][0]).toBe('http://localhost:8000/history/example-id');
    expect(mock.mock.calls[0][1].method).toBe('DELETE');
    expect(audioUrl('/audio/example-id.wav')).toBe('http://localhost:8000/audio/example-id.wav');
  });
});
