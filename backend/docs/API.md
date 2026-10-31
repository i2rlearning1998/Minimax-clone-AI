# Frontend API contract v1

Base URL: `http://localhost:8000`. JSON except audio download and 204 deletion. No auth in this local skeleton. Configure frontend origin in `CORS_ORIGINS`. IDs are UUID strings. All times are UTC ISO 8601. `audio_url` is **relative to the API origin**, not the frontend origin.

## POST /tts

Content-Type: application/json. Waits for all chunks; not a background job.

```json
{"text":"नमस्ते दुनिया।","language":"hi","voice_id":"hi-01","speed":1.0}
```

`text`: required string 1–5000 raw characters, must contain a letter/number. `language`: required `hi` or `en`. `voice_id`: required matching voice ID. `speed`: optional finite number 0.5–2.0, default 1. Unknown fields rejected. Basic speed resampling changes pitch.

201 response:

```json
{"id":"123e4567-e89b-42d3-a456-426614174000","audio_url":"/audio/123e4567-e89b-42d3-a456-426614174000.wav","duration_sec":1.2,"language":"hi","voice_id":"hi-01"}
```

400 invalid voice/language mismatch; 422 invalid input; 503 missing provider configuration; 502 provider failure/invalid audio; 504 timeout after three attempts; 500 storage/internal failure. Failed generations are not in history. Default mock output is silence.

## GET /audio/{id}.wav

No body. 200 `Content-Type: audio/wav`, PCM16 mono 24 kHz; standard FileResponse download/range behavior. 404 missing/deleted audio; 422 malformed UUID. Example: `/audio/123e4567-e89b-42d3-a456-426614174000.wav`.

## GET /voices?language=hi

Optional query `language=hi|en`; omit for all six. 200 JSON array of Voice objects; 422 unsupported language. Three voices per language.

```json
[{"id":"hi-01","name":"Asha (demo)","language":"hi","gender":"female","style":"calm","preview_url":null,"reference_clip":null,"reference_transcript":null,"consent_note":"Dummy metadata only; no recorded person or consent implied. Add authorized reference audio before using a real voice identity."}]
```

The example shows one item; actual Hindi results contain three. IDs: `hi-01`, `hi-02`, `hi-03`, `en-01`, `en-02`, `en-03`. All metadata fields shown are present. URL/transcript fields may be null. Do not render a play button when `preview_url` is null. Dummy labels do not correspond to real distinct speaker identities. Hosted providers fall back to their default language voice until authorized reference clips are configured.

## GET /voices/{id}

200 one Voice object (same fields as above, not wrapped in an array). 404 unknown voice ID. No body/query required.

## GET /history?limit=50&offset=0

200 array, newest first. `limit`: 1–100 (default 50). `offset`: nonnegative (default 0). 422 invalid pagination. Empty history is `[]`. Each item contains Generation fields plus original input `text`, `speed`, `created_at`:

```json
[{"id":"123e4567-e89b-42d3-a456-426614174000","audio_url":"/audio/123e4567-e89b-42d3-a456-426614174000.wav","duration_sec":1.2,"language":"hi","voice_id":"hi-01","text":"नमस्ते दुनिया।","speed":1.0,"created_at":"2026-10-31T01:00:00+00:00"}]
```

## DELETE /history/{id}

No request body. 204, **empty response body**: frontend must not call response.json(). Deletes database row and audio file. 404 missing/already deleted generation; 422 malformed UUID; 500 storage error.

## GET /health

No body. 200 `{"status":"ok"}` after local SQLite check. 500 local storage failure. This does not check remote provider credentials or network availability.

## Error formats

Business/provider errors: `{"detail":"Invalid voice_id"}` (message varies).

Validation errors (422):

```json
{"detail":"Invalid request","errors":[{"field":"body.speed","message":"Input should be less than or equal to 2"}]}
```

Messages may vary with validation library version; branch frontend behavior by HTTP status, display `detail`, and optionally each `errors[].message`. Upstream bodies, API keys and request input are not echoed in validation errors. Hosted requests may take several minutes for long texts; frontend should show a pending state and avoid automatic duplicate submissions.
