# TTS backend

Python 3.11+ / FastAPI / SQLite. Default provider `mock` returns **silent WAV**, not speech. All six voices are dummy metadata, three Hindi and three English. Null previews/reference clips mean none have been recorded. Without a reference clip, hosted providers use their language's default voice; the dummy names/genders/styles do not select six real speakers.

## Setup and run

From the repository root (Linux/macOS):

```sh
python -m venv backend/venv
source backend/venv/bin/activate
python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level info
```

Windows PowerShell: activate with `backend\venv\Scripts\Activate.ps1`; copy with `Copy-Item backend/.env.example backend/.env`. All remaining Python commands are the same. Swagger UI: http://localhost:8000/docs.

Run tests from the repository root:

```sh
python -m pytest backend/tests -q
```

## Configuration

API credentials are read **only from `backend/.env`**, using python-dotenv. Never commit that file. `.env.example` contains empty credential placeholders. Non-secret settings can also be supplied as process environment variables (which take precedence over `.env`). No provider keys or upstream error bodies are logged or returned.

| Setting | Default / meaning |
| --- | --- |
| `TTS_PROVIDER` | `mock`; alternatively `replicate` or `fal` |
| `REPLICATE_API_TOKEN` | Empty; required for Replicate |
| `FAL_KEY` | Empty; required for fal.ai |
| `REPLICATE_MODEL`, `FAL_MODEL` | Optional overrides of the configured model |
| `PROVIDER_TIMEOUT_SEC` | 60 seconds per chunk attempt, including queue polling/download |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` (comma-separated origins) |
| `OUTPUT_DIR` | Absolute backend/outputs path by default |
| `DATABASE_PATH` | OUTPUT_DIR/history.sqlite3 |
| `ROUTING_PATH` | backend/config/routing.json |

`config/routing.json` has a record per language (`hi`, `en`). `provider: null` inherits `TTS_PROVIDER`; set a language-specific provider to override it. Each provider entry contains its model slug, input field mapping, language value and optional extra inputs. The bundled adapters target hosted open-source Chatterbox Multilingual. Replicate uses a pinned community version; fal uses its queue endpoint. Changing models may require matching input mappings/output adapter changes, not just swapping a slug. Model identifiers exist only in config/environment.

To enable hosted speech, choose the provider and place its API key in `.env`, then restart. Dummy entries work with the model's default language voice. To use an identifiable voice, set `reference_clip` to an authorized public HTTPS audio URL, record its transcript and consent in `voices.json`. Replicate forwards `reference_audio`; the configured fal adapter uses the reference URL as `voice` plus the configured language. Chatterbox does not consume `reference_transcript`; the field is retained for future providers. No reference audio is uploaded by this backend.

## Pipeline and limits

- Input: 1–5000 characters, `hi`/`en`, valid matching voice, finite speed 0.5–2.0.
- NFKC normalization, whitespace cleanup, common abbreviations, English integers 0–999 to words. Longer English numbers/leading-zero codes and Hindi numbers are spoken digit by digit. This is basic cleanup, not full currency/date/decimal linguistic normalization.
- Sentences packed into at most 250 characters; long sentences split on words, oversized single tokens hard-split. Small final chunks are allowed.
- Sequential chunk generation, initial attempt plus **two retries** with short backoff. Configuration errors do not retry. Each attempt has a whole-operation timeout; total latency grows with chunk count. A timed-out remote job may still run and incur charges; retries are not guaranteed idempotent by providers.
- Decode WAV only with soundfile; bounded downloads and chunk duration. Mono conversion and linear resampling to 24 kHz; 80 ms silence between chunks; RMS target -20 dBFS, peak cap 0.98. This is RMS normalization, not broadcast LUFS. Silence remains silence.
- Speed is applied once locally using resampling and **also changes pitch**; pitch-preserving time stretch is not implemented. No ffmpeg dependency.
- Save PCM16 WAV atomically, then SQLite metadata. History is newest first, with pagination. Delete removes its WAV and row. Failed generations create no history entry and clean temporary audio.

## Curl examples

```sh
curl http://localhost:8000/health
curl 'http://localhost:8000/voices?language=hi'
curl http://localhost:8000/voices/hi-01
curl -X POST http://localhost:8000/tts -H 'Content-Type: application/json' -d '{"text":"नमस्ते दुनिया।","language":"hi","voice_id":"hi-01","speed":1.0}'
curl http://localhost:8000/audio/REPLACE_WITH_RETURNED_ID.wav -o speech.wav
curl 'http://localhost:8000/history?limit=20&offset=0'
curl -X DELETE http://localhost:8000/history/REPLACE_WITH_RETURNED_ID
```

`audio_url` is relative to the API origin: frontend should prefix its configured API base URL. Full frontend contract: [docs/API.md](docs/API.md).

## Validation and scope

Tests use mock synthesis, temporary SQLite/filesystem storage and httpx MockTransport for hosted adapter contracts. They do not make paid/live provider calls. Real credentials, provider availability and live audio quality are not verified by these tests. No authentication/user isolation is implemented: history is shared, CORS is not authentication. Run as a local single-user service; add authentication, quotas and per-user storage before public deployment.

Provider references used for implementation:
- https://replicate.com/docs/reference/http
- https://replicate.com/resemble-ai/chatterbox-multilingual/versions/9cfba4c265e685f840612be835424f8c33bdee685d7466ece7684b0d9d4c0b1c/api
- https://fal.ai/docs/documentation/model-apis/inference/queue
- https://fal.ai/models/fal-ai/chatterbox/text-to-speech/multilingual/api
