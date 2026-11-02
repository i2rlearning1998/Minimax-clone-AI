# Frontend API contract v1.2 — free providers, local settings and custom voices

Base URL: `http://localhost:8000`. JSON except audio download and 204 deletion. No commercial authentication. Settings and voice mutations require loopback clients and an allowed Origin when provided. Configure frontend origin in `CORS_ORIGINS`. IDs are UUID strings. All times are UTC ISO 8601. `audio_url` is **relative to the API origin**, not the frontend origin.

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

Optional query `language=hi|en`; omit for demo + custom voices. 200 JSON array of Voice objects; 422 unsupported language. Three read-only demo voices per language, plus any custom voices.

```json
[{"id":"hi-01","name":"Asha (demo)","language":"hi","gender":"female","style":"calm","preview_url":null,"reference_clip":null,"reference_transcript":null,"is_custom":false,"has_reference":false,"consent_note":"Dummy metadata only; no recorded person or consent implied. Add authorized reference audio before using a real voice identity."}]
```

The example shows one item; actual Hindi results contain three demos plus custom Hindi entries. Demo IDs: `hi-01`, `hi-02`, `hi-03`, `en-01`, `en-02`, `en-03`. All metadata fields shown are present. URL/transcript fields may be null. Do not render a play button when `preview_url` is null. Dummy labels do not correspond to real distinct speaker identities. Hosted providers fall back to their default language voice until authorized reference clips are configured.

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

Provider-test failures instead use the message shape documented below. Messages may vary with validation library version; branch frontend behavior by HTTP status, display `detail`, and optionally each `errors[].message`. Upstream bodies, API keys and request input are not echoed in validation errors. Hosted requests may take several minutes for long texts; frontend should show a pending state and avoid automatic duplicate submissions.


## Local access and key handling

Settings endpoints below allow only client `127.0.0.1` or `::1`, otherwise 403. Origin, when present, must be in CORS_ORIGINS. Launch with `--no-proxy-headers`; do not trust X-Forwarded-For. Commercial deployments need authentication. Settings responses are non-cacheable. Full keys must never be returned or logged, nor stored in frontend localStorage/sessionStorage/URLs. API validation on settings returns a generic 422 without echoing input.

## GET /settings/provider

200:

```json
{
  "provider": "mock",
  "providers": {
    "mock": {
      "has_key": false,
      "key_hint": "",
      "model": "",
      "requires_key": false
    },
    "free": {
      "has_key": false,
      "key_hint": "",
      "model": "",
      "requires_key": false
    },
    "cloudflare": {
      "has_key": false,
      "key_hint": "",
      "model": "@cf/myshell-ai/melotts",
      "requires_key": true,
      "has_account_id": false,
      "account_id": ""
    },
    "edge": {
      "has_key": false,
      "key_hint": "",
      "model": "",
      "requires_key": false
    },
    "replicate": {
      "has_key": false,
      "key_hint": "",
      "model": "owner/model:VERSION",
      "requires_key": true
    },
    "fal": {
      "has_key": false,
      "key_hint": "",
      "model": "owner/model",
      "requires_key": true
    }
  },
  "resolved_providers": {
    "hi": "mock",
    "en": "mock"
  }
}
```

Model values above illustrate the shape; GET returns actual configured defaults. key_hint contains only the last four characters; if a key has four or fewer characters the hint is empty to avoid returning the full key. No key input should be prefilled from this response. Models reflect English routing unless a global override is saved. Each saved model override applies to both languages. 403 remote/origin rejection; 503 unreadable settings.

## PUT /settings/provider

JSON object:

- `provider` (required): mock | free | cloudflare | edge | replicate | fal.
- `replicate_api_key`, `fal_api_key`, `cloudflare_api_token` (optional): password strings; missing/empty/whitespace retains existing key. A nonblank new key must be 8–4096 ASCII characters without spaces.
- `cloudflare_account_id` (optional): exactly 32 hexadecimal characters; missing/empty preserves the saved account. Account IDs are not secret and GET returns the valid ID for prefilling, plus `has_account_id`.
- `replicate_model`, `fal_model` (optional): owner/model slug, optional version; missing/blank preserves existing override. No arbitrary URLs.

200 returns the same masked object as GET. No synthesis occurs. 422 invalid input, 403 denied, 500 save failure. Runtime overrides take precedence over process environment, .env, and routing defaults. Applied to subsequent requests without restart.

## DELETE /settings/provider/keys/{replicate|fal|cloudflare}

204 empty body; do not parse JSON. Writes an empty runtime override, suppressing any environment/.env key as well. 403 denied, 422 unknown provider, 500 storage error. Subsequent GET has_key=false. Saving a new key re-enables it.

## POST /settings/provider/test

No body. Uses the **saved** effective provider/model to synthesize one short English line. Only call after explicit user action; may spend provider credit. Does not create history or save output. 200:

```json
{"ok":true,"message":"Provider generated valid audio","duration_sec":2.4}
```

502 failure:

```json
{"ok":false,"message":"Provider test failed. Check your saved key, model, credit balance and provider availability.","duration_sec":0}
```

403 denied; 503 unreadable local settings. Upstream error body/key is never echoed. UI should display message, not require detail for this endpoint. No automatic retries by frontend; backend uses its existing two retries per generation chunk.

## Voice object additions

Every voice includes `is_custom: boolean` and `has_reference: boolean`. Custom IDs are UUID strings; demo IDs are unchanged. Custom responses use API-relative preview_url and reference_clip, both `/voices/{id}/clip`; local disk paths and data URIs are not exposed.

```json
{"id":"123e4567-e89b-42d3-a456-426614174000","name":"My voice","language":"hi","gender":"neutral","style":"calm","preview_url":"/voices/123e4567-e89b-42d3-a456-426614174000/clip","reference_clip":"/voices/123e4567-e89b-42d3-a456-426614174000/clip","reference_transcript":"नमस्ते दुनिया।","consent_note":"User explicitly confirmed permission to use this voice.","is_custom":true,"has_reference":true}
```

## POST /voices

Loopback/origin guarded. multipart/form-data (let browser FormData set Content-Type/boundary):

| Field | Required value |
| --- | --- |
| name | Nonblank string, max 100 |
| language | hi or en |
| gender | Nonblank string, max 50 |
| style | Nonblank string, max 100 |
| transcript | Exact reference transcript, nonblank, max 5000 |
| consent | true; false/missing rejected with 422 |
| clip | Decodable audio file, 3–30 sec inclusive, max 10 MiB |

201 returns one custom Voice object above. Uploaded audio converts to mono 24 kHz PCM16 WAV; accepted codecs depend on soundfile/libsndfile. Sample rates 8–192 kHz, 1–8 channels. 422 invalid fields/audio/duration; 413 size; 403 denied; 500 storage failure. Refresh GET /voices for its language after success. Upload itself does not contact a remote provider.

## GET /voices/{id}/clip

200 audio/wav reference preview for custom voices. No body. 404 missing/non-custom voice or missing clip. Resolve URL against API origin. This preview endpoint shares the service's local unauthenticated read scope.

## DELETE /voices/{id}

Loopback/origin guarded. Confirm in UI. 204 empty body; 403 demo voice (read-only) or remote/origin denial; 404 missing; 500 storage failure. Removes metadata/reference file, preserves generation history. Refresh picker and clear obsolete selection.

## Custom voices in POST /tts

Use a returned custom voice_id and its matching language. The backend passes the stored reference as base64 data URI and its transcript into the provider adapter; no local path/localhost URL goes upstream. Bundled Chatterbox schemas use the audio reference but do not define a transcript parameter. Transcript is available to configurable input mappings for other models. There is no new TTS request field; all existing result/history formats remain unchanged.

## Free provider behavior and additions

GET `/settings/provider` always includes six providers. `requires_key` is false for mock, edge and free; `has_key:false` on Edge does not mean unavailable. Cloudflare requires both `has_key` and `has_account_id`. `resolved_providers` maps hi/en to the actual provider. Saving `free` leaves the selected provider `free`: Hindi → Edge; English → Cloudflare when token/account are configured, otherwise Edge. Routing is defined in routing.json, not hardcoded in the client. POST test uses the resolved English provider and creates no history. No hosted call happens on GET/PUT.

DELETE `/settings/provider/cloudflare/account`: no body, 204 empty response. Clears the account and suppresses environment/.env fallback. Same 403 loopback/origin, 500 storage error behavior as key deletion. Cloudflare token clear uses DELETE `/settings/provider/keys/cloudflare` and preserves the account; account clear preserves the token. PUT may include either or both, with the standard required provider field. Full tokens are never returned; `key_hint` is at most the last four characters.

POST `/tts` additional errors (`{"detail":"..."}`):

- 422 Cloudflare Hindi: `Cloudflare MeloTTS Hindi support nahi karta. Hindi ke liye Edge ya fal chuno.`
- 422 custom voice with Edge/Cloudflare (also after Free resolves): `Ye provider voice clone nahi karta. Apni awaaz ke liye fal ya Replicate chuno.` No synthesis or history is created.
- 429 Cloudflare quota/rate limit: `Free daily limit shayad khatam ho gayi, kal try karo ya doosra provider chuno.`

POST `/settings/provider/test` uses the same quota message with HTTP 429 and `{ok:false,message,duration_sec:0}`. Other test failures remain sanitized 502. Frontend shows the response message and never retries automatically. Backend retains its bounded two retries; Free does not switch providers after a quota/failure response.

Edge stock-voice IDs map through routing.json; custom voices are not supported by Edge or Cloudflare. Existing voices, history, audio URLs, delete-204 and cloning providers keep their contracts.
