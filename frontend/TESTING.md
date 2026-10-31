# Manual acceptance checklist

Start backend and frontend as described in README. Open browser Network tools; filter `/tts`. Default mock returns silent audio, so success means a valid playable WAV/duration/history entry, not audible speech. Hosted provider audio quality is outside these mock checks.

## Scripts and generation

- [ ] Hindi: choose Hindi, select a voice, enter `नमस्ते! आज हम एक नई कहानी सुनेंगे।` Generate. Exactly one POST; pending state then player, WAV download and newest history item.
- [ ] English: switch language; verify a fresh `GET /voices?language=en`, English cards only, and a selected English voice. Use `Hello! This is a small idea with a big voice.` Generate and replay.
- [ ] Long text: repeat `यह एक लंबी कहानी का छोटा हिस्सा है। हम ध्यान से सुनते हैं और आगे बढ़ते हैं। ` twenty times (1,000+ characters). Keep it under 5,000. Pending copy explains several minutes; button/settings disabled. No automatic second POST, even if double-clicked. Hosted requests may take longer than mock ones.
- [ ] Numbers: try `Dr. Smith has 42 books and 007 labels.` and `डॉ. शर्मा के पास १२ किताबें हैं।` Confirm successful requests and unchanged original text in history. Number cleanup is backend behavior, not a frontend rewrite.
- [ ] Hinglish: Hindi language with `Namaste दोस्तों! Aaj hum 25 नए ideas discuss करेंगे।` Confirm request/error is displayed according to backend response. Frontend does not invent an unsupported Hinglish language code or promise mixed-language pronunciation.
- [ ] Empty/whitespace/punctuation-only text: Generate disabled. Paste more than 5,000 Unicode characters: limited to 5,000. Check counter including emoji and Hindi text.
- [ ] Speed: default 1.0×; test 0.5× and 2.0× and keyboard arrow steps. Request payload uses chosen speed.
- [ ] Voice previews: null `preview_url` means no play/preview control. When backend supplies a real preview URL, a labeled native player appears.

## Errors and retry

- [ ] Stop backend, refresh voices/history, then Generate with a previously loaded voice. See a clear connection message and Retry. Restart backend; click Retry. No background retries.
- [ ] For generation network/timeout Retry, confirm warning says to inspect history before a new generation; Cancel sends no new POST.
- [ ] Simulate 422 in browser request interception: display `detail` plus every `errors[].message`. 400/404/502/503/504 display backend detail and status-specific guidance.
- [ ] Throttle/delay `/tts`: request must remain pending for at least five minutes (configured timeout is ten). No duplicate POST during pending. On timeout, history-refresh guidance is visible.
- [ ] Block an audio request: player shows Retry audio; it does not regenerate text.

## History and downloads

- [ ] Reload browser: persisted generations appear newest first; native player replays, Download produces `.wav` using API origin rather than port 5173.
- [ ] More than 50 rows: Load older creations appends older records; Refresh returns to newest page.
- [ ] Delete: Cancel confirmation leaves row/audio intact. Confirm sends one DELETE; empty 204 creates no JSON parsing error. Row disappears, and matching current result clears.
- [ ] Delete error shows detail and Retry (with confirmation again). A 404 item is removed from stale UI.

## Accessibility and layout

- [ ] At 360px wide, dark and light themes: no horizontal page overflow; textarea, cards, slider, error text, players and history fit.
- [ ] Keyboard-only: Skip to studio, text entry, language select, radio arrows, slider arrows, Generate, playback/download, Retry and Delete are reachable with visible focus.
- [ ] Inputs have meaningful labels; pending/errors/success/deletion announce to assistive technology. Delete uses native browser confirmation.
- [ ] Theme persists after reload; disabled storage does not crash the app. Reduced motion disables spinner animation.

Automated commands: `npm test` and `npm run build`. These do not prove real hosted TTS quality or paid-provider availability.


## Live test (explicit, may spend provider credit)

- [ ] Run backend/frontend locally on the same computer. Open Settings; choose Replicate/fal. Enter your own API key in the password field and save. Verify Saved ••••last4, cleared password field, and no key in localStorage/sessionStorage/URL. Do not include keys in screenshots or bug reports.
- [ ] Confirm no synthesis call happens on drawer open/Save. Click Test connection once. Record provider/model, HTTP status, sanitized message, approximate elapsed time and duration. Check billing/credit in the provider dashboard if it fails. Never copy an Authorization header or raw provider body into a report.
- [ ] Add one recording you have permission to use (3–30 sec, under 10 MiB), exact transcript, language/gender/style and consent. Verify My voice badge and audible preview. Try unchecked consent/short/invalid file and confirm clear validation errors.
- [ ] Generate a short Hindi script and a short English script with matching-language voices. Use your custom entry for its language; upload a second language entry/reference if testing your own voice in both. Demos use model default voices. Listen for pronunciation, silence, clipping, voice similarity and duration; the mock provider remains intentionally silent.
- [ ] Try a 1,000+ character script. Keep tab open; expect chunk processing to take minutes. Verify one POST, no automatic retry, a downloadable WAV and persisted history. After a timeout, inspect history before manual Retry to avoid duplicate charges.
- [ ] Clear the saved key; GET settings should show no active key even if .env has one. Provider test should fail cleanly. Save a replacement, then switch to Mock and confirm the silent-audio banner.
- [ ] Delete custom voice with Cancel then Confirm. Preview/voice disappear only after Confirm; previous generations remain playable. Settings drawer keyboard focus stays inside and Escape closes it when idle.
- [ ] Log problems with app commit, provider/model, selected language, clip duration/format (not the private clip unless intended), script length, sanitized HTTP status/message, elapsed time, browser/OS and reproduction steps. Do not attach key files, runtime settings, request bodies containing keys, HAR files or private voice recordings unintentionally.

Live calls are not part of automated tests. Automated transport tests use generated ephemeral values and intercept all provider HTTP calls.
