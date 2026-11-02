# Voice Studio frontend

Mobile-first Vite + React + TypeScript client. Devanagari fonts are bundled through @fontsource (no external font requests). Uses only the contract in `backend/docs/API.md`; backend code is unchanged. All network calls live in `src/api.ts`. Requires Node.js 22.12+ (or a compatible newer LTS) and npm.

## Install and configure

From the repository root:

```sh
cd frontend
npm install
cp .env.example .env
npm run dev -- --port 5173 --strictPort
```

PowerShell: use `Copy-Item .env.example .env` instead of `cp`. Open http://localhost:5173.

`VITE_API_URL=http://localhost:8000` is the default API origin. Change it in `.env` and restart Vite. Use an HTTP(S) origin, not an endpoint path. Vite environment variables are public build-time configuration: **never put an API key here**. The production build must be rebuilt if this origin changes.

## Start the backend

In a second terminal, **from the repository root**, use the commands from `backend/README.md`:

```sh
python -m venv backend/venv
source backend/venv/bin/activate
python -m pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level info
```

Windows PowerShell: activate with `backend\venv\Scripts\Activate.ps1`; copy with `Copy-Item backend/.env.example backend/.env`. Keep `http://localhost:5173` in backend `CORS_ORIGINS`. For a different port or a phone accessing the computer over LAN, configure the backend binding, API origin and CORS accordingly. `localhost` on a phone refers to the phone.

The default backend mock generates silent WAV. Dummy voice names are metadata, not distinct real speakers. Real provider configuration belongs only in backend `.env`.

## Tests and build

Inside `frontend/`:

```sh
npm test
npm run build
npm run preview -- --port 5173 --strictPort
```

Three Vitest tests cover HTTP detail/422 messages, network/ten-minute timeout with no retry, and bodyless 204 deletion plus API-relative audio URLs. The lockfile supports `npm ci` for repeat installs. See `TESTING.md` for the manual checklist.

## Behavior

- Language changes fetch the corresponding voice library and cancel stale voice requests. Native radio cards support keyboard selection. Null preview URLs render no preview control.
- Unicode character counter caps script length at 5,000. Empty/punctuation-only text or missing voices disables generation. Speed is 0.5–2.0, default 1.0; the backend's speed adjustment also changes pitch.
- One in-flight generation at a time, protected by a synchronous ref lock. POST requests are never automatically retried. The request waits **10 minutes**. A timeout/disconnection can leave the backend working: check/refresh history first; manual Retry asks before submitting another uncertain request.
- Results/history have native audio controls and blob-based WAV downloads (including cross-origin API hosting). Relative audio paths are resolved against `VITE_API_URL`.
- History is newest-first and paginated in groups of 50. Refresh replaces the current page; Load older adds pages. Successful generation/deletion refreshes history. Delete always asks for confirmation; 204 is never parsed as JSON.
- Backend `detail` is displayed verbatim as React text. HTTP status supplies contextual guidance; 422 also displays `errors[].message`. Retry buttons are manual. Audio-load errors have their own Retry control.
- Theme follows system preference initially and persists a user choice when localStorage is available. Layout supports 360px; labels, focus indicators, live statuses, native controls and reduced-motion preferences are included.

No authentication or API keys are added; the backend contract is a local single-user service. Keep it local until backend authentication/user isolation exists.
