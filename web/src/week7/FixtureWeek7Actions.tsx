import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { Week7StatusBar } from './Week7StatusBar';

type Props = {
  apiBase: string;
  workspaceId: string | null;
  onChanged?: () => void;
};

const PROJECT_ID = 'rotterdam-m4h-pilot-project';

const SCHEMES = {
  B1: {
    project_id: PROJECT_ID,
    scenario_id: 'B1',
    revision: 'rev-b1',
    results: [{ kind: 'gfa_far', value: 1.1, unit: 'ratio', provenance: 'FIXTURE_ONLY' }],
    cards: [{
      evidence_id: 'card-b1-sun',
      source: 'fixture sun B1',
      formula: 'stored',
      unit: 'hour',
      version: 'rev-b1',
      limits: 'FIXTURE_ONLY',
      period: '2026-06-21',
      radius_family: 'accessibility',
      radius_m: 800,
      numbers: [1.1],
      provenance: 'FIXTURE_ONLY',
    }],
  },
  B2: {
    project_id: PROJECT_ID,
    scenario_id: 'B2',
    revision: 'rev-b2',
    results: [{ kind: 'gfa_far', value: 2.2, unit: 'ratio', provenance: 'FIXTURE_ONLY' }],
    cards: [{
      evidence_id: 'card-b2-sun',
      source: 'fixture sun B2',
      formula: 'stored',
      unit: 'hour',
      version: 'rev-b2',
      limits: 'FIXTURE_ONLY',
      period: '2026-06-21',
      radius_family: 'accessibility',
      radius_m: 800,
      numbers: [2.2],
      provenance: 'FIXTURE_ONLY',
      validation_status: 'invalid',
    }],
  },
} as const;

function operationPayload(kind: string, forkId: string): Record<string, unknown> {
  if (kind === 'inspect') return { evidence_id: 'card-b2-sun' };
  if (kind === 'challenge') return { target_revision: 'rev-b2', assumption: 'storey height is a project setting' };
  if (kind === 'modify') return { parameter: 'storey_height_m', proposed_value: 3.5 };
  if (kind === 'rerun') return { kind: 'gfa_far', logical_request: 'far-again', already_approved: false };
  if (kind === 'compare') {
    return {
      left: { unit: 'ratio', extent_id: 'site', method: 'far', method_version: '1', radius_family: 'accessibility' },
      right: { unit: 'm', extent_id: 'other', method: 'syntax', method_version: '2', radius_family: 'syntax' },
    };
  }
  if (kind === 'fork') return { branch_id: forkId };
  if (kind === 'reject') return { candidate_id: 'candidate-b0', reason: 'does not meet the brief' };
  return { kind: 'gfa_far', judgment: 'prefer the lower scheme', reason: 'open space' };
}

export function Week7Actions({ apiBase, workspaceId, onChanged }: Props) {
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  const [result, setResult] = useState('no operation yet');
  const [e3e4Label, setE3e4Label] = useState('E3/E4 NOT_ACCEPTED');
  const forkId = new URLSearchParams(window.location.search).get('week7Fork') || 'branch-b2';
  const base = apiBase.replace(/\/$/, '');

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${base}/api/v1/week7/e3e4`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json() as Promise<{ e3?: { status?: string }; e4?: { status?: string } }>;
      })
      .then((body) => {
        const e3 = body.e3?.status || 'NOT_ACCEPTED';
        const e4 = body.e4?.status || 'NOT_ACCEPTED';
        setE3e4Label(`E3 ${e3} / E4 ${e4}`);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setE3e4Label('E3/E4 NOT_ACCEPTED');
      });
    return () => controller.abort();
  }, [base]);

  async function send(path: string, body: unknown, label: string) {
    if (!workspaceId) {
      setResult(JSON.stringify({ code: 'workspace_missing' }));
      return;
    }
    const response = await fetch(`${base}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({ code: 'unreadable_response', http_status: response.status }));
    setResult(JSON.stringify({ action: label, http_status: response.status, payload }));
    onChanged?.();
  }

  const operations = ['inspect', 'challenge', 'modify', 'rerun', 'compare', 'fork', 'reject', 'override'] as const;

  return (
    <section
      aria-label={zh ? '第 7 週質疑與修改' : 'Week 7 contest actions'}
      data-testid="week7-actions"
      style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', padding: '6px 12px', background: '#1e293b', color: '#f8fafc', font: '13px/1.4 ui-sans-serif, system-ui, sans-serif' }}
    >
      <span>FIXTURE_ONLY actions · OFFLINE mock</span>
      <strong data-testid="week7-e3e4">{e3e4Label}</strong>
      {(['B1', 'B2'] as const).map((scenario) => (
        <button
          key={scenario}
          type="button"
          data-testid={`week7-switch-${scenario}`}
          onClick={() => void send(`/api/v1/week7/workspaces/${encodeURIComponent(workspaceId || '')}/switch`, SCHEMES[scenario], `switch-${scenario}`)}
        >
          Switch {scenario}
        </button>
      ))}
      {operations.map((kind) => (
        <button
          key={kind}
          type="button"
          data-testid={`week7-op-${kind}`}
          onClick={() => void send(
            `/api/v1/week7/workspaces/${encodeURIComponent(workspaceId || '')}/operations/${kind}`,
            { kind, payload: operationPayload(kind, forkId) },
            kind,
          )}
        >
          {kind}
        </button>
      ))}
      <pre data-testid="week7-op-result" style={{ flexBasis: '100%', whiteSpace: 'pre-wrap', margin: 0 }}>{result}</pre>
    </section>
  );
}

export function Week7Chrome({ apiBase, workspaceId }: { apiBase: string; workspaceId: string | null }) {
  const [nonce, setNonce] = useState(0);
  return (
    <>
      <Week7StatusBar key={`${workspaceId ?? 'none'}:${nonce}`} apiBase={apiBase} workspaceId={workspaceId} />
      <Week7Actions apiBase={apiBase} workspaceId={workspaceId} onChanged={() => setNonce((value) => value + 1)} />
    </>
  );
}
