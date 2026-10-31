export type Language = 'hi' | 'en';
export interface Voice {
  id: string; name: string; language: Language; gender: string; style: string;
  preview_url: string | null; reference_clip: string | null;
  reference_transcript: string | null; consent_note: string;
}
export interface Generation {
  id: string; audio_url: string; duration_sec: number; language: Language; voice_id: string;
}
export interface HistoryEntry extends Generation { text: string; speed: number; created_at: string }
export interface TTSInput { text: string; language: Language; voice_id: string; speed: number }

export const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
export const GENERATION_TIMEOUT_MS = 10 * 60 * 1000;
export class ApiError extends Error {
  constructor(message: string, public status: number | null = null,
    public kind: 'http' | 'network' | 'timeout' = 'http') { super(message); this.name = 'ApiError'; }
}
export function audioUrl(path: string): string {
  const url = new URL(path, API_URL + '/');
  if (url.protocol !== 'http:' && url.protocol !== 'https:') throw new Error('Invalid audio URL');
  return url.href;
}

async function request<T>(path: string, options: RequestInit = {}, timeout = 30_000, blob = false): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (options.signal?.aborted) controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
  try {
    const response = await fetch(audioUrl(path), { ...options, signal: controller.signal });
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      const detail = typeof data?.detail === 'string' ? data.detail : `Request failed (HTTP ${response.status})`;
      const extra = response.status === 422 && Array.isArray(data?.errors)
        ? data.errors.map((e: { message?: unknown }) => typeof e.message === 'string' ? e.message : '').filter(Boolean).join(' · ') : '';
      throw new ApiError(extra ? `${detail}: ${extra}` : detail, response.status);
    }
    if (response.status === 204) return undefined as T; // Deliberately no JSON parsing.
    return (blob ? await response.blob() : await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (timedOut) throw new ApiError('The request timed out. The backend may still be processing it.', null, 'timeout');
    if (options.signal?.aborted) throw error;
    throw new ApiError('Cannot reach the backend. Check that it is running and that its URL and CORS settings are correct.', null, 'network');
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}

export const api = {
  voices: (language: Language, signal?: AbortSignal) => request<Voice[]>(`/voices?language=${language}`, { signal }),
  generate: (input: TTSInput) => request<Generation>('/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input) }, GENERATION_TIMEOUT_MS),
  history: (offset = 0, signal?: AbortSignal) => request<HistoryEntry[]>(`/history?limit=50&offset=${offset}`, { signal }),
  deleteHistory: (id: string) => request<void>(`/history/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  download: (url: string) => request<Blob>(url, {}, 60_000, true),
};

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}
export function errorHint(error: unknown): string {
  if (!(error instanceof ApiError)) return '';
  if (error.kind === 'network') return 'Start the backend, then retry.';
  if (error.kind === 'timeout') return 'Refresh history before retrying a generation to avoid duplicates.';
  switch (error.status) {
    case 400: case 422: return 'Check your text, language, voice and speed.';
    case 404: return 'This item may have been deleted. Refresh history.';
    case 502: return 'The speech provider could not generate audio. Retry when ready.';
    case 503: return 'The backend provider needs configuration.';
    case 504: return 'The provider timed out. Check history before retrying.';
    default: return 'Please try again when the backend is available.';
  }
}
