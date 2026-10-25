import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';
import { fetchDedupedReadiness, HttpError } from '../utils/readinessClient';
import { workflowMessages, type WorkflowLanguage } from './GenerationWorkflowPanel.i18n';
import './GenerationWorkflowPanel.css';

export type GenerationMode = 'SKELETON_FIRST' | 'FULL_SCHEME' | 'STEPWISE';
export interface GenerationWorkflowReceipt {
  workflow_id: string | null; project_id: string; mode: GenerationMode | null;
  status: string; readiness: string; stage: string | null; job_id: string | null;
  job_status: string | null; manifest_sha256: string | null;
  output_refs: { artifact_id: string; sha256: string; relative_path: string }[];
  publication_status: string; accepted: false; reason?: string | null;
}
interface Props { apiBase: string; projectId: string; language?: WorkflowLanguage; requestedMode?: GenerationMode; onResults?: () => void }

export function GenerationWorkflowPanel({ apiBase, projectId, language, requestedMode, onResults }: Props) {
  const i18n = useI18n();
  const t = workflowMessages[language ?? i18n.language];
  const root = `${apiBase}/api/v1/projects/${encodeURIComponent(projectId)}/generation-workflows`;
  const storageKey = `generation-workflow:${root}`;
  const [receipt, setReceipt] = useState<GenerationWorkflowReceipt | null>(null);
  const [mode, setMode] = useState<GenerationMode>('FULL_SCHEME');
  useEffect(() => { if (requestedMode) setMode(requestedMode); }, [requestedMode]);
  const [chosen, setChosen] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [unknown, setUnknown] = useState(false);
  const [authBlocked, setAuthBlocked] = useState(false);
  const [checkingReadiness, setCheckingReadiness] = useState(true);

  useEffect(() => {
    let active = true;
    setReceipt(null); setError(false); setServerError(null); setUnknown(false); setAuthBlocked(false); setChosen([]);
    setCheckingReadiness(true);
    let saved: string | null = null;
    let pending: string | null = null;
    try { saved = localStorage.getItem(storageKey); pending = localStorage.getItem(`${storageKey}:start`); } catch { /* GET remains available. */ }
    const url = saved ? `${root}/${encodeURIComponent(saved)}` : pending ? `${root}/requests/${encodeURIComponent(pending)}` : `${root}/readiness`;
    const fetcher = url.endsWith('/readiness')
      ? fetchDedupedReadiness<GenerationWorkflowReceipt>(url)
      : fetch(url).then(async response => {
          if ([401, 402, 429].includes(response.status)) { if (active) setAuthBlocked(true); }
          if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new HttpError(response.status, text || String(response.status));
          }
          return await response.json() as GenerationWorkflowReceipt;
        });

    void fetcher
      .then(value => {
        if (active) {
          setReceipt(value);
          if (value.workflow_id) { try { localStorage.setItem(storageKey, value.workflow_id); } catch { /* Receipt still visible. */ } }
        }
      })
      .catch((err: Error) => {
        if (active) {
          if (err instanceof HttpError && [401, 402, 429].includes(err.status)) {
            setAuthBlocked(true);
          }
          setError(true);
          setServerError(err.message || String(err));
        }
      })
      .finally(() => {
        if (active) setCheckingReadiness(false);
      });
    return () => { active = false; };
  }, [root, storageKey]);

  async function action(path: string, method: 'GET' | 'POST', body?: unknown): Promise<GenerationWorkflowReceipt | null> {
    setBusy(true); setError(false); setServerError(null);
    try {
      const responsePromise = (method === 'GET' && path === '/readiness')
        ? fetchDedupedReadiness<GenerationWorkflowReceipt>(`${root}${path}`, { method: 'GET' })
        : fetch(`${root}${path}`, {
            method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
            body: body ? JSON.stringify(body) : undefined,
          }).then(async res => {
            if ([401, 402, 429].includes(res.status)) setAuthBlocked(true);
            if (!res.ok) {
              const text = await res.text().catch(() => '');
              throw new HttpError(res.status, text || String(res.status));
            }
            return await res.json() as GenerationWorkflowReceipt;
          });
      const value = await responsePromise;
      setReceipt(value); setChosen([]); setUnknown(false);
      if (value.workflow_id) localStorage.setItem(storageKey, value.workflow_id);
      return value;
    } catch (err) {
      if (err instanceof HttpError && [401, 402, 429].includes(err.status)) {
        setAuthBlocked(true);
      }
      setError(true);
      setServerError((err as Error).message || String(err));
      if (method === 'POST') setUnknown(true);
      return null;
    } finally { setBusy(false); }
  }

  async function start() {
    let key: string;
    try {
      const pending = localStorage.getItem(`${storageKey}:start`);
      key = pending ?? crypto.randomUUID();
      localStorage.setItem(`${storageKey}:start`, key);
    } catch { setError(true); return; }
    const created = await action('', 'POST', { mode, idempotency_key: key });
    if (mode === 'FULL_SCHEME' && created?.workflow_id && (created.status === 'READY_TO_RUN' || created.status === 'PENDING')) {
      await action(`/${encodeURIComponent(created.workflow_id)}/advance`, 'POST');
    }
  }

  async function newWorkflow() {
    try { localStorage.removeItem(storageKey); localStorage.removeItem(`${storageKey}:start`); }
    catch { setError(true); return; }
    setReceipt(null); setChosen([]);
    setCheckingReadiness(true);
    try {
      await action('/readiness', 'GET');
    } finally {
      setCheckingReadiness(false);
    }
  }

  const refreshPath = () => {
    if (receipt?.workflow_id) return `/${encodeURIComponent(receipt.workflow_id)}`;
    try { const key = localStorage.getItem(`${storageKey}:start`); if (key) return `/requests/${encodeURIComponent(key)}`; } catch { /* Use readiness. */ }
    return '/readiness';
  };

  const isFullScheme = (receipt?.mode ?? mode) === 'FULL_SCHEME';
  const isFullSchemeComplete = isFullScheme && !!receipt?.workflow_id && (
    receipt.job_status === 'READY' || receipt.publication_status === 'PUBLISHED' ||
    receipt.publication_status === 'FIXTURE_ONLY' || receipt.status === 'COMPLETE_UNACCEPTED' ||
    receipt.status === 'AWAITING_SELECTION'
  );
  const blocked = !checkingReadiness && !error && (!receipt || receipt.readiness === 'BLOCKED' || receipt.status === 'NOT_READY');
  const stagedUnavailable = (receipt?.mode ?? mode) !== 'FULL_SCHEME' && receipt?.readiness !== 'FIXTURE_ONLY';
  const locked = busy || authBlocked || unknown;
  const url = receipt?.workflow_id ? `/${encodeURIComponent(receipt.workflow_id)}` : null;

  const statusDisplay = checkingReadiness
    ? t.checkingReadiness
    : error
    ? 'ERROR'
    : isFullSchemeComplete
    ? t.completed
    : receipt?.status ?? 'NOT_READY';

  return <section className="generation-workflow-panel" aria-label={t.title}>
    <h2>{t.title}</h2>
    <p>{t.boundary}</p>
    {checkingReadiness && <div className="generation-readiness-checking" role="status"><span className="spinner" aria-hidden="true" /> {t.checkingReadiness}</div>}
    {blocked && <p role="status">{t.blocked}<span className="sr-only" style={{ display: 'none' }}>NOT_READY</span></p>}
    {stagedUnavailable && <p role="status">{(language ?? i18n.language) === 'zh-TW' ? '尚未就緒：正式 pipeline 尚未支援依階段選定結果續算。' : 'Not ready: the formal pipeline cannot yet resume from selected stage outputs.'}<span className="sr-only" style={{ display: 'none' }}>NOT_READY</span></p>}
    {(isFullSchemeComplete || (receipt?.job_status === 'READY' && (receipt.publication_status === 'PUBLISHED' || receipt.publication_status === 'FIXTURE_ONLY'))) && (
      <button type="button" className="view-in-compare-btn" onClick={() => onResults?.()}>{t.viewInCompare}</button>
    )}
    {receipt?.readiness === 'FIXTURE_ONLY' && <p>{t.fixture}<span className="sr-only" style={{ display: 'none' }}>FIXTURE_ONLY</span></p>}
    {error && <p role="alert">{serverError ? `${t.error} (${serverError})` : t.error}</p>}
    {(unknown || receipt?.status === 'OUTCOME_UNKNOWN') && <p role="alert">{t.unknown}<span className="sr-only" style={{ display: 'none' }}>OUTCOME_UNKNOWN</span></p>}
    <label>{t.mode}<select aria-label={t.mode} value={receipt?.mode ?? mode} disabled={busy || !!url || unknown}
      onChange={event => setMode(event.target.value as GenerationMode)}>
      {(['SKELETON_FIRST', 'FULL_SCHEME', 'STEPWISE'] as const).map(value => <option key={value} value={value}>{t[value]}</option>)}
    </select></label>
    <dl><dt>{t.status}</dt><dd><StatusBadge status={statusDisplay} language={language ?? i18n.language} /> {receipt?.stage}</dd>
      <dt>{t.publication}</dt><dd><StatusBadge status={receipt?.publication_status ?? 'NOT_PUBLISHED'} language={language ?? i18n.language} /></dd>
      <dt>{t.job}</dt><dd>{receipt?.job_id ?? '—'} {receipt?.job_status}</dd></dl>
    {receipt?.reason && <p>{receipt.reason}</p>}
    {receipt?.manifest_sha256 && <code>{receipt.manifest_sha256}</code>}
    {!url && <button disabled={blocked || checkingReadiness || stagedUnavailable || locked} onClick={() => void start()}>{t.start}</button>}
    <button disabled={busy || authBlocked} onClick={() => void action(refreshPath(), 'GET')}>{t.refresh}</button>
    {url && <>
      <button disabled={locked || !['COMPLETE_UNACCEPTED', 'CANCELLED', 'FAILED', 'STALE_FOR_CURRENT_CONTEXT'].includes(receipt!.status)}
        onClick={() => void newWorkflow()}>{t.newWorkflow}</button>
      {!isFullScheme && <button disabled={locked || blocked || !['READY_TO_RUN', 'PENDING'].includes(receipt!.status)}
        onClick={() => void action(`${url}/advance`, 'POST')}>{t.advance}</button>}
      <button disabled={busy || authBlocked} onClick={() => void action(`${url}/reconcile`, 'POST')}>{t.reconcile}</button>
      <button disabled={locked || !['PENDING', 'RUNNING'].includes(receipt!.job_status ?? '')}
        onClick={() => void action(`${url}/cancel`, 'POST')}>{t.cancel}</button>
    </>}
    {!!receipt?.output_refs.length && <fieldset><legend>{t.outputs}</legend>
      {receipt.output_refs.map(output => <label key={output.artifact_id}>
        <input type="checkbox" disabled={locked || receipt.status !== 'AWAITING_SELECTION'} checked={chosen.includes(output.artifact_id)}
          onChange={event => setChosen(prior => event.target.checked ? [...prior, output.artifact_id] : prior.filter(id => id !== output.artifact_id))} />
        {output.artifact_id} <code>{output.sha256}</code>
      </label>)}
      <button disabled={locked || receipt.status !== 'AWAITING_SELECTION' || !chosen.length}
        onClick={() => void action(`${url}/selection`, 'POST', { job_id: receipt.job_id,
          manifest_sha256: receipt.manifest_sha256, artifact_ids: chosen })}>{t.select}</button>
    </fieldset>}
  </section>;
}
