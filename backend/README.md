# Local Voice Studio backend

FastAPI + SQLite, Python 3.11+. Personal use on the same computer as the browser. The default `mock` provider returns silent WAV. Use the UI Settings panel to save a provider key, then explicitly test real speech. There is no need to edit Python code or restart after changing provider settings.

## Setup

From the repository root:

```sh
python -m venv backend/venv
source backend/venv/bin/activate
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --log-level info
```

Windows PowerShell: activate with `backend\venv\Scripts\Activate.ps1`. The other Python commands are identical. Start the frontend using `frontend/README.md`, open http://localhost:5173, then Settings → choose Replicate/fal → enter key → Save settings → Test connection. A real provider account with credit is required. The explicit test synthesizes one English line; it is not a free credentials-only check. No test runs on Save/GET or automatically.

Optional configuration: copy `backend/.env.example` to `backend/.env`. Never commit it. API docs: http://localhost:8000/docs and [docs/API.md](docs/API.md).

## Provider settings and secrets

Precedence for each setting is **runtime settings > process environment > backend/.env > routing.json/defaults**. Provider, keys and model overrides are read for each synthesis/settings request. An in-flight generation keeps its starting snapshot. Process environment means values visible to this running process; modifying another shell's environment does not change the process. Paths/CORS are startup settings.

- GET/PUT `/settings/provider`, DELETE `/settings/provider/keys/{replicate|fal}`, POST `/settings/provider/test` accept only request client addresses `127.0.0.1` or `::1`; other clients get 403. An Origin header must match configured CORS origins. Use `--no-proxy-headers` and one worker. Do not put this unauthenticated local service behind a reverse proxy/public tunnel. Commercial use must replace the local guard with authenticated authorization.
- Keys are stored in ignored `backend/.runtime/settings.json`, atomically replaced with mode **0600**, in a directory set to 0700. POSIX permissions are enforced on POSIX systems; Windows permission semantics differ, so keep the project in your private user directory with appropriate NTFS ACLs.
- Responses expose only `has_key` and the last four characters in `key_hint` (empty for a key too short to mask safely). No full key is returned, logged, or included in errors. Settings responses use `Cache-Control: no-store`.
- Blank/missing key on Save retains its previous value. Clear key writes an empty override that suppresses environment/.env fallback too. It does not modify the environment or .env file. Save a new key to replace this override.
- The UI stores entered keys only in component memory, clears them after a save attempt, and discards them when the drawer closes. No localStorage/sessionStorage/URL key persistence. Runtime JSON is plaintext protected by local file permissions, not encrypted storage.

| Variable | Default / meaning |
| --- | --- |
| TTS_PROVIDER | mock, replicate or fal; defaults to mock |
| REPLICATE_API_TOKEN / FAL_KEY | Backend keys from environment/.env unless runtime overrides them |
| REPLICATE_MODEL / FAL_MODEL | Optional model overrides; otherwise routing.json |
| PROVIDER_TIMEOUT_SEC | 60 seconds per chunk attempt, including polling/download |
| CORS_ORIGINS | http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173 |
| OUTPUT_DIR / DATABASE_PATH | backend/outputs and its history.sqlite3 |
| RUNTIME_DIR | backend/.runtime |
| VOICE_CLIPS_DIR | backend/voices_data/clips |
| ROUTING_PATH | backend/config/routing.json |

`config/routing.json` has `hi`/`en` records and configurable model/input mappings. A runtime/global environment provider choice overrides language-specific configuration; absent an explicit choice, language routing applies. GET settings reports each provider's effective English model, while a saved model override applies to both languages. Bundled defaults use Chatterbox Multilingual on Replicate (pinned version) and fal. Changing model families may require adjusting input mappings and output parsing, not just the slug.

## Custom voices

Use Add voice in the UI. Required: name, language (hi/en), gender, style, exact transcript, checked permission consent, and a clip. The backend rejects false/missing consent, invalid audio, files over 10 MiB, durations outside 3–30 seconds, unsupported rates/channels, and blank metadata. It accepts soundfile-decodable formats; available codecs depend on libsndfile. MP3 is covered by tests using the installed soundfile wheel. No ffmpeg is required.

Clips are converted to mono 24 kHz PCM16 WAV in ignored `backend/voices_data/clips/<id>.wav`; metadata is persisted in `.runtime/voices.sqlite3`. Demo voices in voices.json remain read-only. Returned voice objects contain `is_custom`/`has_reference` and API-relative preview URLs, never filesystem paths. Deleting a custom voice deletes its reference and metadata; existing generated history/audio remains. Upload/delete are also loopback/origin guarded.

When generating with a custom voice, the adapter receives its transcript and a **base64 audio data URI** built from the stored WAV. No localhost URL or disk path is sent to a remote provider. Replicate uses `reference_audio`; fal multilingual uses `voice` plus `custom_audio_language`. These field names and fal base64-file support were checked against provider docs. The selected Chatterbox models do **not** define a transcript input: the adapter receives/preserves it, but does not invent an unsupported upstream parameter. A provider/model that accepts transcripts can map `reference_transcript` in `input_fields`. Local demo references should be uploaded as custom voices rather than added as local paths in demo JSON.

Reference audio is local until you explicitly use the voice with a hosted provider, at which point that provider receives the clip and synthesis text. The six demo entries do not represent six real speaker identities; hosted demos use each model's default language voice. Custom voice language must match synthesis language. To test your own voice in both languages, add an appropriate reference entry for each language.

## Pipeline, errors and persistence

- Text: 1–5000 raw characters, letters/numbers required; hi/en; matching voice; speed 0.5–2.0. NFKC/whitespace/abbreviation cleanup. English 0–999 becomes words; longer numbers and Hindi are digit-by-digit, not full currency/date grammar.
- Sentences packed into at most 250 characters, split on words when necessary. Sequential chunks, initial attempt plus two retries; no retry on configuration errors. Each attempt is bounded by PROVIDER_TIMEOUT_SEC. Remote jobs may continue after a timeout and retries can incur charges.
- Provider downloads: up to 25 MiB/chunk, at most 180 seconds, any format soundfile can decode (WAV/FLAC/OGG/MP3, etc.); decoded samples are validated. Delivery hosts restricted to provider-owned domains; auth headers are not sent to audio-download hosts.
- Mono 24 kHz resampling, 80 ms gap, RMS target -20 dBFS with peak cap 0.98. Not broadcast LUFS. Local speed resampling **changes pitch**. Output is always PCM16 WAV.
- Successful generations save WAV plus SQLite history. Failed generations leave no history/output. Newest-first pagination and confirmed deletion are available in the frontend.
- Errors expose sanitized messages. Logging excludes text, keys, reference data and upstream bodies. Do not enable HTTP wire/body tracing while using real keys.

## Curl and tests

```sh
curl http://localhost:8000/health
curl 'http://localhost:8000/voices?language=hi'
curl http://localhost:8000/settings/provider
curl -X POST http://localhost:8000/tts -H 'Content-Type: application/json' -d '{"text":"नमस्ते दुनिया।","language":"hi","voice_id":"hi-01","speed":1}'
curl http://localhost:8000/audio/REPLACE_WITH_ID.wav -o speech.wav
curl 'http://localhost:8000/history?limit=20&offset=0'
curl -X DELETE http://localhost:8000/history/REPLACE_WITH_ID
python -m pytest backend/tests -q
```

Tests use mock providers/httpx transports, generated in-memory throwaway values and temporary storage. No real API key or paid network call is used. Live provider availability, account billing and voice quality must be checked by the user via the explicit UI Live test checklist.

Verified provider references:
- https://replicate.com/docs/reference/http
- https://replicate.com/resemble-ai/chatterbox-multilingual/versions/9cfba4c265e685f840612be835424f8c33bdee685d7466ece7684b0d9d4c0b1c/api
- https://fal.ai/models/fal-ai/chatterbox/text-to-speech/multilingual/api
- https://fal.ai/docs/documentation/model-apis/inference/queue
