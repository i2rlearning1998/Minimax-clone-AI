import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { localApi, errorMessage } from './api';
import type { Language, Voice } from './api';

export default function AddVoice({ language, onClose, onAdded }: { language: Language; onClose: () => void; onAdded: (voice: Voice) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const lock = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (lock.current) return;
    const body = new FormData(event.currentTarget);
    const clip = body.get('clip') as File;
    if (clip.size > 10 * 1024 * 1024) { setError('Clip must be at most 10 MiB'); return; }
    lock.current = true; setPending(true); setError('');
    try { onAdded(await localApi.uploadVoice(body)); onClose(); }
    catch (e) { setError(errorMessage(e)); }
    finally { lock.current = false; setPending(false); }
  }
  return <dialog className="local-dialog" ref={dialog} aria-labelledby="add-voice-heading" onCancel={e => { e.preventDefault(); if (!pending) onClose(); }}>
    <div className="section-heading"><h2 id="add-voice-heading">Add your voice</h2><button type="button" disabled={pending} aria-label="Close add voice" onClick={onClose}>✕</button></div>
    <p className="dialog-note">Upload a clear 3–30 second recording (up to 10 MiB). It stays on your computer until you generate with a hosted provider; that provider then receives the reference audio and text.</p>
    <form onSubmit={e => void submit(e)}><fieldset disabled={pending} className="dialog-fields">
      <label htmlFor="voice-name">Name</label><input id="voice-name" name="name" required maxLength={100} />
      <label htmlFor="voice-language">Voice language</label><select id="voice-language" name="language" defaultValue={language}><option value="hi">Hindi</option><option value="en">English</option></select>
      <label htmlFor="voice-gender">Gender</label><select id="voice-gender" name="gender" defaultValue="neutral"><option value="neutral">Neutral</option><option value="female">Female</option><option value="male">Male</option></select>
      <label htmlFor="voice-style">Style</label><input id="voice-style" name="style" required maxLength={100} placeholder="e.g. calm, narration" />
      <label htmlFor="voice-clip">Reference audio</label><input id="voice-clip" name="clip" type="file" required accept="audio/*,.wav,.flac,.ogg,.mp3" />
      <label htmlFor="voice-transcript">Exact transcript of this recording</label><textarea id="voice-transcript" name="transcript" required maxLength={5000} />
      <label className="consent-label"><input type="checkbox" name="consent" value="true" required />Mere paas is awaaz ko use karne ki permission hai</label>
      <button className="generate-button" type="submit">{pending ? 'Adding voice…' : 'Add voice'}</button>
    </fieldset></form>
    {error && <div className="error-box" role="alert">{error}</div>}
  </dialog>;
}
