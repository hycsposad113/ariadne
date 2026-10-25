import { useEffect, useState } from 'react';
import { useI18n, type Language } from '../i18n';
import './Week7.css';
import { shellFromWeek7View, type Week7PersistedView } from './shellFromWeek7View';

export function formatLiveAiLabel(raw: string | undefined | null, language: Language = 'zh-TW'): string {
  const zh = language === 'zh-TW';
  if (!raw) return zh ? 'AI 狀態不可用' : 'AI status unavailable';
  const upper = raw.toUpperCase();
  if (upper.includes('OFFLINE')) {
    return zh ? '離線' : 'Offline';
  }
  if (upper.includes('LIVE')) {
    return zh ? '即時 AI' : 'Live AI';
  }
  return zh ? '離線' : 'Offline';
}

export type Week7View = Week7PersistedView & {
  revision_label?: string;
  freshness_text?: string;
  geometry_valid?: boolean;
  human_status?: string;
  run_status?: string;
  evidence_status?: string;
  evidence_availability?: string;
  live_ai_label?: string;
  panels?: { ai?: { evidence_ids?: string[] } };
};

export type Week7Card = {
  evidence_id: string;
  source: string;
  formula: string;
  unit: string;
  version: string;
  limits: string;
};

type LoadState = 'loading' | 'ready' | 'unavailable';

export function Week7StatusBar({ apiBase, workspaceId, scenarioId }: { apiBase: string; workspaceId: string | null; scenarioId?: string | null }) {
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  const [state, setState] = useState<LoadState>(workspaceId ? 'loading' : 'unavailable');
  const [view, setView] = useState<Week7View | null>(null);
  const [openCard, setOpenCard] = useState<Week7Card | null>(null);

  useEffect(() => {
    setView(null); setOpenCard(null); setState(workspaceId ? 'loading' : 'unavailable');
    if (!workspaceId) return;
    const controller = new AbortController();
    const base = apiBase.replace(/\/$/, '');
    fetch(`${base}/api/v1/week7/workspaces/${encodeURIComponent(workspaceId)}/view${scenarioId ? `?scenario_id=${encodeURIComponent(scenarioId)}` : ''}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json() as Promise<Week7View>;
      })
      .then((body) => {
        if (!body.revision_label) throw new Error('missing revision');
        setView(body);
        setState('ready');
        window.dispatchEvent(new CustomEvent('week7-persisted-view', { detail: body }));
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setView(null);
        setState('unavailable');
      });
    return () => controller.abort();
  }, [apiBase, workspaceId, scenarioId]);

  const revisionText = state === 'ready' && view?.revision_label ? view.revision_label : 'revision unavailable';
  const freshnessText = state === 'ready' && view?.freshness_text ? view.freshness_text : 'freshness unavailable';
  const evidenceIds = [...new Set(view?.panels?.ai?.evidence_ids ?? [])];
  const mapLabel = state === 'ready' && view ? shellFromWeek7View(view)?.mapLabel : null;

  async function expand(evidenceId: string) {
    const base = apiBase.replace(/\/$/, '');
    const response = await fetch(`${base}/api/v1/week7/cards/${encodeURIComponent(evidenceId)}`);
    if (!response.ok) {
      setOpenCard(null);
      return;
    }
    setOpenCard(await response.json() as Week7Card);
  }

  return (
    <section
      aria-label={zh ? '第 7 週修訂' : 'Week 7 revision'}
      data-testid="week7-status"
      className="week7-status"
    >
      <strong data-testid="week7-revision">{revisionText}</strong>
      {mapLabel && <span data-testid="week7-map-revision">{mapLabel}</span>}
      <div className="week7-badges">
      <span data-testid="week7-freshness" title={zh ? '結果是否對應目前方案版本。' : 'Whether results match the current scenario revision.'}>{zh ? '時效' : 'freshness'} {freshnessText}</span>
      <span title={zh ? '確定性幾何驗證狀態。' : 'Deterministic geometry validation.'}>{zh ? '幾何' : 'geometry'} {state === 'ready' ? String(view?.geometry_valid) : (zh ? '不可用' : 'unavailable')}</span>
      <span title={zh ? '人類接受狀態；不是幾何有效性。' : 'Human acceptance, independent of geometry validity.'}>{zh ? '人類接受' : 'human'} {state === 'ready' ? view?.human_status : (zh ? '不可用' : 'unavailable')}</span>
      <span title={zh ? '原始工具執行狀態。' : 'Original tool execution status.'}>{zh ? '執行' : 'run'} {state === 'ready' ? view?.run_status : (zh ? '不可用' : 'unavailable')}</span>
      <span title={zh ? '證據驗證與可用性。' : 'Evidence validation and availability.'}>{zh ? '證據' : 'evidence'} {state === 'ready' ? `${view?.evidence_status} / ${view?.evidence_availability}` : (zh ? '不可用' : 'unavailable')}</span>
      </div>
      <span data-testid="week7-live-ai">{state === 'ready' ? formatLiveAiLabel(view?.live_ai_label, language) : (zh ? 'AI 狀態不可用' : 'AI status unavailable')}</span>
      <details className="week7-evidence"><summary>{zh ? '證據' : 'Evidence'} ({evidenceIds.length})</summary>
      {evidenceIds.map((evidenceId, index) => (
        <button key={evidenceId} type="button" onClick={() => void expand(evidenceId)}>
          {zh ? '檢視證據' : 'Inspect evidence'} {index + 1}
        </button>
      ))}
      {openCard && (
        <dl data-testid="week7-card">
          <dt>{zh ? '來源' : 'source'}</dt><dd>{openCard.source}</dd>
          <dt>{zh ? '公式' : 'formula'}</dt><dd>{openCard.formula}</dd>
          <dt>{zh ? '單位' : 'unit'}</dt><dd>{openCard.unit}</dd>
          <dt>{zh ? '版本' : 'version'}</dt><dd>{openCard.version}</dd>
          <dt>{zh ? '限制' : 'limits'}</dt><dd>{openCard.limits}</dd>
        </dl>
      )}
      </details>
    </section>
  );
}
