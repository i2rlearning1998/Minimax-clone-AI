import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import SettingsPanel from './SettingsPanel';
import AddVoice from './AddVoice';
import { localApi, api, ApiError, audioUrl, errorHint, errorMessage } from './api';
import type { Generation, HistoryEntry, Language, Voice, ProviderSettings } from './api';

function ErrorNotice({ error, onRetry, retryLabel = 'Retry', disabled = false }: {
  error: unknown; onRetry: () => void; retryLabel?: string; disabled?: boolean;
}) {
  if (!error) return null;
  return <div className="error-box" role="alert"><div><strong>{errorMessage(error)}</strong>
    <p>{errorHint(error)}</p></div><button type="button" onClick={onRetry} disabled={disabled}>{retryLabel}</button></div>;
}

function Wave({ small = false }: { small?: boolean }) {
  return <div className={`wave ${small ? 'small' : ''}`} aria-hidden="true">{[12, 23, 36, 19, 49, 64, 35, 52, 78, 48, 28, 58, 35, 18, 27, 12].map((h, i) => <i key={i} style={{ height: `${h}%` }} />)}</div>;
}

function Player({ url, label }: { url: string; label: string }) {
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { setFailed(false); }, [url]);
  return <div className="player"><audio key={`${url}-${attempt}`} controls preload="none" src={audioUrl(url)} aria-label={label} onError={() => setFailed(true)} />
    {failed && <div className="audio-error" role="alert">Audio unavailable. Check the backend or refresh history.
      <button type="button" onClick={() => { setFailed(false); setAttempt(n => n + 1); }}>Retry audio</button></div>}</div>;
}

function initialTheme(): 'light' | 'dark' {
  try { const saved = localStorage.getItem('voice-studio-theme'); if (saved === 'light' || saved === 'dark') return saved; } catch { /* Storage can be disabled. */ }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}
function duration(seconds: number) { return `${seconds.toFixed(1)} sec`; }

export default function App() {
  const [showSettings, setShowSettings] = useState(false);
  const [showAddVoice, setShowAddVoice] = useState(false);
  const [providerSettings, setProviderSettings] = useState<ProviderSettings | null>(null);
  const [settingsError, setSettingsError] = useState<unknown>(null);
  const [voiceDeleteError, setVoiceDeleteError] = useState<unknown>(null);
  const [voiceDeleting, setVoiceDeleting] = useState(false);
  const voiceDeleteLock = useRef(false);
  async function refreshSettings() {
    setSettingsError(null);
    try { setProviderSettings(await localApi.settings()); } catch (e) { setSettingsError(e); }
  }
  useEffect(() => { void refreshSettings(); }, []);
  async function deleteVoice(id: string) {
    if (voiceDeleteLock.current || !window.confirm('Delete this custom voice and its reference clip? Existing generations will stay in history.')) return;
    voiceDeleteLock.current = true; setVoiceDeleting(true); setVoiceDeleteError(null);
    try { await localApi.deleteVoice(id); setVoiceReload(v => v + 1); }
    catch(e) { setVoiceDeleteError(e); }
    finally { voiceDeleteLock.current = false; setVoiceDeleting(false); }
  }
  const [theme, setTheme] = useState(initialTheme);
  const [text, setText] = useState('');
  const [language, setLanguage] = useState<Language>('hi');
  const [speed, setSpeed] = useState(1);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [voiceId, setVoiceId] = useState('');
  const [voicesLoading, setVoicesLoading] = useState(true);
  const [voicesError, setVoicesError] = useState<unknown>(null);
  const [voiceReload, setVoiceReload] = useState(0);
  const [pending, setPending] = useState(false);
  const generationLock = useRef(false);
  const [generationError, setGenerationError] = useState<unknown>(null);
  const [result, setResult] = useState<Generation | null>(null);
  const resultRef = useRef<HTMLElement>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<unknown>(null);
  const [hasMore, setHasMore] = useState(false);
  const historyVersion = useRef(0);
  const [deleting, setDeleting] = useState<string | null>(null);
  const deleteLock = useRef(false);
  const [deleteError, setDeleteError] = useState<{ id: string; error: unknown } | null>(null);
  const [downloadError, setDownloadError] = useState<{ item: Generation; error: unknown } | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const downloadLock = useRef(false);
  const [announcement, setAnnouncement] = useState('');
  const count = Array.from(text).length;
  const valid = /[\p{L}\p{N}]/u.test(text) && count <= 5000 && voices.some(v => v.id === voiceId && v.language === language);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('voice-studio-theme', theme); } catch { /* Optional persistence. */ }
  }, [theme]);

  useEffect(() => {
    const controller = new AbortController();
    setVoicesLoading(true); setVoicesError(null); setVoices([]); setVoiceId('');
    api.voices(language, controller.signal).then(items => {
      if (controller.signal.aborted) return;
      setVoices(items); setVoiceId(items[0]?.id || '');
    }).catch(error => { if (!controller.signal.aborted) setVoicesError(error); })
      .finally(() => { if (!controller.signal.aborted) setVoicesLoading(false); });
    return () => controller.abort();
  }, [language, voiceReload]);

  async function loadHistory(append = false) {
    const version = ++historyVersion.current;
    setHistoryLoading(true); setHistoryError(null);
    try {
      const items = await api.history(append ? history.length : 0);
      if (version !== historyVersion.current) return;
      setHistory(old => append ? [...old, ...items.filter(item => !old.some(v => v.id === item.id))] : items);
      setHasMore(items.length === 50);
    } catch (error) { if (version === historyVersion.current) setHistoryError(error); }
    finally { if (version === historyVersion.current) setHistoryLoading(false); }
  }
  useEffect(() => { void loadHistory(); }, []);

  async function generate() {
    if (generationLock.current || !valid || voicesLoading) return;
    generationLock.current = true; setPending(true); setGenerationError(null); setAnnouncement('');
    // Snapshot form values. Never automatically retry this POST.
    const input = { text, language, voice_id: voiceId, speed };
    try {
      const item = await api.generate(input);
      setResult(item); setAnnouncement('Your audio is ready.');
      void loadHistory();
      requestAnimationFrame(() => resultRef.current?.focus());
    } catch (error) { setGenerationError(error); }
    finally { generationLock.current = false; setPending(false); }
  }
  function retryGeneration() {
    if (generationError instanceof ApiError && (generationError.kind === 'timeout' || generationError.kind === 'network' || generationError.status === 504)) {
      if (!window.confirm('The previous request may still complete. Refresh history first to avoid duplicates. Start a new generation anyway?')) return;
    }
    void generate();
  }
  function submit(event: FormEvent) { event.preventDefault(); void generate(); }

  async function remove(itemId: string) {
    if (deleteLock.current || !window.confirm('Delete this generation and its audio? This cannot be undone.')) return;
    deleteLock.current = true; setDeleting(itemId); setDeleteError(null);
    try {
      await api.deleteHistory(itemId);
      setHistory(items => items.filter(item => item.id !== itemId));
      setResult(item => item?.id === itemId ? null : item);
      setAnnouncement('Generation deleted.');
      void loadHistory();
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        setHistory(items => items.filter(item => item.id !== itemId));
        setResult(item => item?.id === itemId ? null : item);
      }
      setDeleteError({ id: itemId, error });
    } finally { deleteLock.current = false; setDeleting(null); }
  }

  async function download(item: Generation) {
    if (downloadLock.current) return;
    downloadLock.current = true; setDownloading(item.id); setDownloadError(null);
    try {
      const blob = await api.download(item.audio_url);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = `voice-${item.language}-${item.id}.wav`;
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (error) { setDownloadError({ item, error }); }
    finally { downloadLock.current = false; setDownloading(null); }
  }

  return <><a className="skip-link" href="#studio">Skip to studio</a>
    <header className="site-header"><a className="brand" href="#studio" aria-label="Voice Studio home"><span className="brand-mark" aria-hidden="true">◖</span>voice<span className="brand-light">studio</span><span className="beta">BETA</span></a>
      <div className="header-actions"><button type="button" onClick={() => setShowSettings(true)} disabled={pending} aria-label="Open provider settings">⚙ <span>Settings</span></button><button className="theme-button" type="button" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}><span aria-hidden="true">{theme === 'dark' ? '☼' : '☾'}</span><span>{theme === 'dark' ? 'Light' : 'Dark'} mode</span></button></div></header>
    {showSettings && <SettingsPanel onClose={() => setShowSettings(false)} onSaved={value => { setProviderSettings(value); setSettingsError(null); }} />}
    {showAddVoice && <AddVoice language={language} onClose={() => setShowAddVoice(false)} onAdded={voice => { setLanguage(voice.language); setVoiceReload(v => v + 1); }} />}
    <main id="studio">
      <div className="hero"><div><p className="eyebrow"><span />YOUR WORDS. A NEW VOICE.</p><h1>Make yourself<br /><em>heard.</em></h1><p className="intro">Turn a thought into a voice.<br className="mobile-break" /> Create in Hindi or English.</p></div><div className="hero-art"><Wave /><span>FROM TEXT TO POSSIBILITY</span></div></div>
      <div className="workspace"><div className="creation-column"><form className="panel editor-panel" onSubmit={submit} aria-busy={pending}>
        <div className="section-heading"><h2><span className="step">01</span>Write your script</h2><span className="pill">Text to speech</span></div>
        <label className="sr-only" htmlFor="script">Your script</label>
        <textarea id="script" value={text} onChange={e => setText(Array.from(e.target.value).slice(0, 5000).join(''))} disabled={pending} placeholder={"A story, an idea, a simple hello…\nअपनी कहानी यहाँ लिखें।"} aria-describedby="script-help character-count" />
        <div className="editor-meta"><span id="script-help">A little punctuation goes a long way.</span><span id="character-count" className={count >= 4900 ? 'near-limit' : ''}>{count.toLocaleString()} <span>/ 5,000</span></span></div>
        <div className="voice-section"><div className="section-heading"><h2><span className="step">02</span>Find your voice</h2><div className="language-field"><label className="sr-only" htmlFor="language">Language</label><select id="language" value={language} disabled={pending} onChange={e => { setLanguage(e.target.value as Language); setVoices([]); setVoiceId(''); }}><option value="hi">Hindi · हिन्दी</option><option value="en">English</option></select></div></div>
          <div className="voice-toolbar"><span className="fineprint">Demo library & your recordings</span><button type="button" disabled={pending || voiceDeleting} onClick={() => setShowAddVoice(true)}>+ Add voice</button></div>
          <fieldset className="voice-grid" disabled={pending || voicesLoading || voiceDeleting}><legend className="sr-only">Choose a voice</legend>
            {voices.map((voice, index) => <div className={`voice-card ${voiceId === voice.id ? 'selected' : ''} ${voice.preview_url ? 'with-preview' : ''}`} key={voice.id}><label><input type="radio" name="voice" value={voice.id} checked={voiceId === voice.id} onChange={() => setVoiceId(voice.id)} /><span className={`avatar avatar-${index % 3}`} aria-hidden="true">{voice.name.slice(0, 1)}</span><span className="voice-badge">{voice.is_custom ? "My voice" : "Demo"}</span><strong>{voice.name}</strong><span className="voice-meta">{voice.gender} · {voice.style}</span></label>
              {voice.preview_url && <Player url={voice.preview_url} label={`Preview ${voice.name}`} />}{voice.is_custom && <button className="custom-delete" type="button" disabled={pending || voiceDeleting} onClick={() => void deleteVoice(voice.id)} aria-label={`Delete voice ${voice.name}`}>Delete voice</button>}</div>)}
          </fieldset>
          {voicesLoading && <p className="muted" role="status">Loading voices…</p>}
          {!voicesLoading && !voicesError && voices.length === 0 && <p role="status">No voices available for this language.</p>}
          <ErrorNotice error={voicesError} onRetry={() => setVoiceReload(v => v + 1)} disabled={voicesLoading} />
          <ErrorNotice error={voiceDeleteError} onRetry={() => { setVoiceDeleteError(null); setVoiceReload(v => v + 1); }} retryLabel="Refresh voices" />
          <p className="fineprint">Demo voices are placeholders. Preview appears when audio is available.</p>
        </div>
        <div className="speed-section"><div><label htmlFor="speed">Speaking speed</label><output htmlFor="speed">{speed.toFixed(2).replace(/0$/, '')}×</output></div><input id="speed" type="range" min="0.5" max="2" step="0.05" value={speed} disabled={pending} onChange={e => setSpeed(Number(e.target.value))} aria-valuetext={`${speed} times speed`} /><div className="speed-scale"><span>0.5× · Slower</span><span>2× · Faster</span></div><p className="fineprint">Speed adjustment also changes pitch.</p></div>
        {providerSettings?.provider === "mock" && <div className="mock-banner" role="status">Mock mode: audio silent hai. Settings mein provider chuno.</div>}
        <ErrorNotice error={settingsError} onRetry={() => void refreshSettings()} />
        <button className="generate-button" type="submit" disabled={!valid || pending || voicesLoading}>{pending ? <><span className="spinner" />Creating your audio…</> : <>Generate speech <span aria-hidden="true">↗</span></>}</button>
        <p className="generation-note" role={pending ? 'status' : undefined}>{pending ? 'Long scripts can take several minutes. Keep this tab open — your request will wait up to 10 minutes.' : 'Hindi & English · WAV audio · Up to 5,000 characters'}</p>
        <ErrorNotice error={generationError} onRetry={retryGeneration} disabled={!valid || pending} />
      </form>
      <section className={`panel result-panel ${result ? 'has-result' : ''}`} aria-labelledby="result-title" tabIndex={-1} ref={resultRef}><div className="section-heading"><h2 id="result-title">Your audio</h2>{result && <span className="ready-pill">Ready to listen</span>}</div>
        {result ? <><div className="result-info"><Wave small /><div><strong>{result.language === 'hi' ? 'Hindi' : 'English'} generation</strong><span>{duration(result.duration_sec)} · WAV</span></div><button type="button" className="download-button" disabled={downloading !== null} onClick={() => void download(result)}>{downloading === result.id ? 'Downloading…' : '↓ Download'}</button></div><Player url={result.audio_url} label="Generated speech" /></> : <div className="empty-result"><span aria-hidden="true">♫</span><p>A voice is waiting in your words.<br /><span>Your generated audio will appear here.</span></p></div>}
      </section><ErrorNotice error={downloadError?.error} onRetry={() => downloadError && void download(downloadError.item)} disabled={downloading !== null} /></div>
      <aside className="panel history-panel" aria-labelledby="history-title"><div className="section-heading"><h2 id="history-title">Recent creations</h2><button className="text-button" type="button" disabled={historyLoading || deleting !== null} onClick={() => void loadHistory()} aria-label="Refresh history">↻ Refresh</button></div><p className="history-subtitle">Your words, collected. Newest first.</p>
        <ErrorNotice error={historyError} onRetry={() => void loadHistory()} disabled={historyLoading} />
        <ErrorNotice error={deleteError?.error} onRetry={() => deleteError && void remove(deleteError.id)} disabled={deleting !== null} />
        {historyLoading && <p className="muted" role="status">Loading history…</p>}
        {!historyLoading && !historyError && history.length === 0 && <div className="history-empty"><div className="empty-circle" aria-hidden="true">◷</div><h3>A fresh start.</h3><p>Your creations will live here.<br />Write something worth hearing.</p><span className="dotted-line" /></div>}
        <ul className="history-list">{history.map(item => <li key={item.id}><div className="history-top"><span className="language-badge">{item.language.toUpperCase()}</span><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</time></div><p className="history-script" title={item.text}>{item.text}</p><div className="history-metadata">{item.voice_id} · {item.speed}× · {duration(item.duration_sec)}</div><Player url={item.audio_url} label={`Replay ${item.text.slice(0, 40)}`} /><div className="history-actions"><button type="button" disabled={downloading !== null} onClick={() => void download(item)} aria-label={`Download generation ${item.id}`}>{downloading === item.id ? 'Downloading…' : '↓ Download'}</button><button type="button" className="delete-button" disabled={deleting !== null} onClick={() => void remove(item.id)} aria-label={`Delete generation ${item.id}`}>{deleting === item.id ? 'Deleting…' : 'Delete'}</button></div></li>)}</ul>
        {hasMore && <button className="load-more" type="button" disabled={historyLoading || deleting !== null} onClick={() => void loadHistory(true)}>Load older creations</button>}
        <div className="studio-note"><span aria-hidden="true">✳</span><p><strong>Start small. Say more.</strong><br />Try a sentence first to find your pace. The backend’s default mock provider produces silent audio.</p></div>
      </aside></div>
      <div className="sr-only" role="status" aria-live="polite">{announcement}</div>
    </main><footer><span>voice studio</span><p>A little space for your next big idea.</p><span>HI / EN</span></footer>
  </>;
}
