import { useEffect, useRef, useState } from 'react';
import { localApi, errorMessage } from './api';
import type { KeyProvider, ProviderName, ProviderSettings } from './api';

export default function SettingsPanel({ onClose, onSaved }: { onClose: () => void; onSaved: (settings: ProviderSettings) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const lock = useRef(false);
  const [saved, setSaved] = useState<ProviderSettings | null>(null);
  const [provider, setProvider] = useState<ProviderName>('mock');
  const [keys, setKeys] = useState({ replicate: '', fal: '' }); // Memory only; cleared on submit/unmount.
  const [models, setModels] = useState({ replicate: '', fal: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const dirty = !saved || provider !== saved.provider || !!keys.replicate || !!keys.fal || models.replicate !== saved.providers.replicate.model || models.fal !== saved.providers.fal.model;
  function accept(settings: ProviderSettings) {
    setSaved(settings); setProvider(settings.provider);
    setModels({ replicate: settings.providers.replicate.model, fal: settings.providers.fal.model });
    onSaved(settings);
  }
  async function load() {
    setLoading(true); setError('');
    try { accept(await localApi.settings()); } catch (e) { setError(errorMessage(e)); }
    finally { setLoading(false); }
  }
  useEffect(() => { dialog.current?.showModal(); void load(); }, []);
  async function action(fn: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(''); setMessage('');
    try { await fn(); } catch (e) { setError(errorMessage(e)); }
    finally { lock.current = false; setBusy(false); }
  }
  async function save() {
    try {
      accept(await localApi.saveSettings({ provider, replicate_model: models.replicate, fal_model: models.fal,
        ...(keys.replicate ? { replicate_api_key: keys.replicate } : {}), ...(keys.fal ? { fal_api_key: keys.fal } : {}) }));
      setMessage('Settings saved. New requests will use them immediately.');
    } finally { setKeys({ replicate: '', fal: '' }); }
  }
  return <dialog className="local-dialog" ref={dialog} aria-labelledby="settings-heading" onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="section-heading"><h2 id="settings-heading">Provider settings</h2><button type="button" onClick={onClose} disabled={busy} aria-label="Close settings">✕</button></div>
    <p className="dialog-note">Key sirf tumhare local backend mein save hoti hai. It is never saved in browser storage.</p>
    {loading && <p role="status">Loading settings…</p>}
    {error && <div className="error-box" role="alert">{error}{!saved && <button type="button" onClick={() => void load()} disabled={loading}>Retry</button>}</div>}
    {saved && <form onSubmit={e => { e.preventDefault(); void action(save); }}>
      <fieldset disabled={busy || loading} className="dialog-fields"><label htmlFor="provider">Provider</label><select id="provider" value={provider} onChange={e => { setProvider(e.target.value as ProviderName); setMessage(''); }}><option value="mock">Mock (silent audio)</option><option value="replicate">Replicate</option><option value="fal">fal</option></select>
      {(['replicate', 'fal'] as KeyProvider[]).map(name => <section className="key-section" key={name}><h3>{name === 'fal' ? 'fal' : 'Replicate'}</h3><label htmlFor={`${name}-key`}>API key</label><input id={`${name}-key`} type="password" autoComplete="new-password" spellCheck={false} value={keys[name]} maxLength={4096} onChange={e => setKeys(k => ({ ...k, [name]: e.target.value }))} placeholder="Leave blank to keep saved key" />
        <div className="key-status"><span>{saved.providers[name].has_key ? `Saved ••••${saved.providers[name].key_hint}` : 'No key saved'}</span><button type="button" disabled={!saved.providers[name].has_key} onClick={() => void action(async () => { await localApi.clearKey(name); setKeys(k => ({ ...k, [name]: '' })); const updated = await localApi.settings(); setSaved(updated); onSaved(updated); setMessage('Key cleared, including environment fallback.'); })}>Clear key</button></div>
        <label htmlFor={`${name}-model`}>Model slug</label><input id={`${name}-model`} value={models[name]} maxLength={250} spellCheck={false} onChange={e => setModels(m => ({ ...m, [name]: e.target.value }))} /></section>)}
      <button className="generate-button" type="submit" disabled={!dirty}>Save settings</button></fieldset>
    </form>}
    <div className="connection-test"><button type="button" disabled={busy || loading || !saved || dirty} onClick={() => void action(async () => { const result = await localApi.testProvider(); setMessage(`${result.message} · ${result.duration_sec.toFixed(1)} sec`); })}>{busy ? 'Working…' : 'Test connection'}</button><p className="fineprint">Save changes before testing. This explicit test generates a short English line and may use provider credit. It never runs automatically.</p></div>
    {message && <p className="dialog-success" role="status">{message}</p>}
  </dialog>;
}
