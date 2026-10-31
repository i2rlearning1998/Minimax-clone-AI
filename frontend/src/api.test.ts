import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, audioUrl, GENERATION_TIMEOUT_MS } from './api';

beforeEach(() => { vi.stubGlobal('fetch', vi.fn(() => { throw new Error('External network blocked in tests'); })); });
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

// Generated throwaway values exist only in memory. No live provider/network calls.
describe('local provider and custom voice API', () => {
  it('saves settings only in a JSON body and tests a connection only on explicit call', async () => {
    const { localApi } = await import('./api');
    const ephemeral = crypto.randomUUID();
    const mock = vi.fn().mockImplementation(async (_url, options) => {
      expect(String(_url)).not.toContain(ephemeral);
      expect(options.body).toContain(ephemeral);
      return new Response(JSON.stringify({ provider: 'replicate', providers: {} }));
    });
    vi.stubGlobal('fetch', mock);
    await localApi.saveSettings({ provider: 'replicate', replicate_api_key: ephemeral });
    expect(mock).toHaveBeenCalledTimes(1);
    expect(mock.mock.calls[0][1].method).toBe('PUT');
    mock.mockImplementation(async () => new Response(JSON.stringify({ ok: false, message: 'Provider test failed', duration_sec: 0 }), { status: 502 }));
    await expect(localApi.testProvider()).rejects.toMatchObject({ message: 'Provider test failed', status: 502 });
    expect(mock).toHaveBeenCalledTimes(2);
  });

  it('handles settings guard errors and both empty-204 key/voice deletes', async () => {
    const { localApi } = await import('./api');
    const mock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Loopback only' }), { status: 403 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 })).mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', mock);
    await expect(localApi.settings()).rejects.toMatchObject({ status: 403, message: 'Loopback only' });
    await expect(localApi.clearKey('fal')).resolves.toBeUndefined();
    await expect(localApi.deleteVoice('custom-id')).resolves.toBeUndefined();
    expect(mock).toHaveBeenCalledTimes(3);
  });

  it('uploads multipart without overriding its boundary and displays consent validation errors', async () => {
    const { localApi } = await import('./api');
    const body = new FormData(); body.set('consent', 'false'); body.set('clip', new Blob(['audio']), 'clip.wav');
    const mock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Permission must be confirmed' }), { status: 422 }));
    vi.stubGlobal('fetch', mock);
    await expect(localApi.uploadVoice(body)).rejects.toMatchObject({ status: 422, message: 'Permission must be confirmed' });
    expect(mock.mock.calls[0][1].body).toBe(body);
    expect(mock.mock.calls[0][1].headers).toBeUndefined();
  });
});
