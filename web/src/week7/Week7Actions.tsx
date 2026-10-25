import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { HumanDecisionDialog, type HumanDecisionSubmission } from '../components/HumanDecisionDialog';
import './Week7.css';
import { Week7StatusBar } from './Week7StatusBar';

type Ref = { entity_id: string; revision: number };
function entityRef(ref: Ref): Ref { return { entity_id: ref.entity_id, revision: ref.revision }; }
type Scenario = Ref & { label: string; status: string; geometry_sha256?: string };
type View = { project_id: string; workspace_ref: Ref; scenario_ref: Ref; cards: Array<{ evidence_id: string; revision: number }>; runs: Array<Ref & { payload: { tool?: string; input_refs?: string[]; input_artifact_ids?: string[]; output_artifact_refs?: string[] } }> };
type PendingOverride = { projectId: string; scenarioId: string; revision: number; geometrySha256: string; eventId: string };
type Props = { apiBase: string; workspaceId: string | null; scenarioId?: string | null; onChanged?: () => void; expanded?: boolean; onExpandedChange?: (open: boolean) => void };

export function Week7Actions({ apiBase, workspaceId, scenarioId, onChanged, expanded, onExpandedChange }: Props) {
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  const descriptions: Record<string, [string, string]> = {
    inspect: ['Inspect the persisted evidence and scenario references.', '檢視已儲存的證據與方案參照。'],
    challenge: ['Record a challenge and preserve its versioned target.', '記錄質疑並保留其版本化目標。'],
    modify: ['Open the W6 formal draft editing workflow.', '開啟 W6 正式草稿編輯流程。'],
    rerun: ['Run the selected method with a currently approved plan and baseline.', '使用現行已批准計畫與基準方案執行所選方法。'],
    compare: ['Compare two persisted scenarios without declaring an overall winner.', '比較兩個已儲存方案，不宣告整體優勝者。'],
    fork: ['Create a new branch while retaining the original scenario.', '建立新分支並保留原始方案。'],
    reject: ['Record only a pending judgment; Founder decides through HumanDecision.', '只記錄待決判斷；Founder 透過 HumanDecision 決策。'],
    override: ['Record only a pending judgment; computed evidence remains unchanged.', '只記錄待決判斷；計算證據保持不變。'],
  };
  const [rows, setRows] = useState<Scenario[]>([]);
  const [view, setView] = useState<View | null>(null);
  const [selected, setSelected] = useState('');
  const [other, setOther] = useState('');
  const [reason, setReason] = useState('');
  const [branch, setBranch] = useState('');
  const [result, setResult] = useState('');
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [pendingOverride, setPendingOverride] = useState<PendingOverride | null>(null);
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [runId, setRunId] = useState('');
  const [planId, setPlanId] = useState('');
  const [rerunStage, setRerunStage] = useState<'E1' | 'E2'>('E1');
  const [rerunKey, setRerunKey] = useState('');
  const [syntaxLayer, setSyntaxLayer] = useState('syntax_local_800m_integration');
  const [figureKind, setFigureKind] = useState('plan');
  const [resultArtifacts, setResultArtifacts] = useState('');
  const [figureUrl, setFigureUrl] = useState('');
  const base = `${apiBase.replace(/\/$/, '')}/api/v1/week7`;
  const workspacePath = `${base}/workspaces/${encodeURIComponent(workspaceId || '')}`;
  useEffect(() => {
    setView(null); setRows([]);
    if (!workspaceId) return;
    const abort = new AbortController();
    Promise.all([
      fetch(`${workspacePath}/scenarios`, { signal: abort.signal }).then(async r => { if (!r.ok) throw Error('Scenario list unavailable'); return r.json(); }),
      fetch(`${workspacePath}/view${scenarioId ? `?scenario_id=${encodeURIComponent(scenarioId)}` : ''}`, { signal: abort.signal }).then(async r => { if (!r.ok) throw Error('Revision unavailable'); return r.json(); }),
    ]).then(([scenarios, body]: [Scenario[], View]) => {
      if (!Array.isArray(scenarios) || !body.scenario_ref) throw Error('Missing real references');
      setRows(scenarios); setView(body); setSelected(body.scenario_ref.entity_id);
    }).catch(error => { if (!abort.signal.aborted) setResult(String(error)); });
    return () => abort.abort();
  }, [workspaceId, scenarioId, workspacePath]);

  async function send(path: string, body: unknown) {
    if (busy || unknown) return;
    setBusy(true);
    try {
      const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const payload = await response.json();
      setResult(JSON.stringify({ http_status: response.status, payload }));
      if (payload.status === 'OUTCOME_UNKNOWN' || payload.detail?.code === 'OUTCOME_UNKNOWN' || payload.reconciliation_required) {
        setUnknown(true);
        return;
      }
      if (response.ok && payload.workspace_ref && payload.scenario_ref) window.dispatchEvent(new CustomEvent('week7-persisted-view', { detail: payload }));
      if (response.ok && payload.artifact_ref?.entity_id) setFigureUrl(`${base}/figures/${encodeURIComponent(payload.artifact_ref.entity_id)}`);
      if (response.ok && !path.endsWith('/figures')) onChanged?.();
    } catch {
      setUnknown(true);
      setResult('處置結果未知；請先核對伺服器狀態，系統不會自動重送。');
    } finally { setBusy(false); }
  }

  async function requestOverride() {
    if (!view || busy || unknown || pendingOverride) return;
    const scenario = rows.find(row => row.entity_id === view.scenario_ref.entity_id);
    const geometrySha256 = scenario?.geometry_sha256;
    if (!view.project_id || !scenario || scenario.status.toLowerCase() !== 'proposed'
      || !geometrySha256 || !/^sha256:[0-9a-f]{64}$/.test(geometrySha256)) {
      setResult(zh ? '此方案缺少有效的提案版本或幾何雜湊；無法建立覆寫待決事件。' : 'This scenario lacks a valid proposal revision or geometry hash; a pending override event cannot be created.');
      return;
    }
    setBusy(true);
    try {
      const response = await fetch(`${workspacePath}/operations/override`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target: entityRef(view.scenario_ref), reason }),
      });
      const payload = await response.json();
      if (!response.ok || payload.status !== 'PENDING_FOUNDER_DECISION' || !payload.event?.event_id) {
        if (payload.status === 'OUTCOME_UNKNOWN' || payload.detail?.code === 'OUTCOME_UNKNOWN') setUnknown(true);
        setResult(zh ? '覆寫待決事件未被接受；請檢查目標版本後再操作。' : 'The pending override event was not accepted; check the target revision before proceeding.');
        return;
      }
      setPendingOverride({ projectId: view.project_id, scenarioId: scenario.entity_id,
        revision: scenario.revision, geometrySha256, eventId: payload.event.event_id });
      setOverrideDialogOpen(true);
      setResult(zh ? `待決事件已記錄：${payload.event.event_id}。請由人類決策視窗提交。` : 'Pending event recorded for human review.');
    } catch {
      setUnknown(true);
      setResult(zh ? '覆寫事件結果未知；請先核對伺服器狀態，系統不會自動重送。' : 'The override event outcome is unknown; reconcile server state first. The system will not resend automatically.');
    } finally { setBusy(false); }
  }

  async function submitOverrideDecision(submission: HumanDecisionSubmission) {
    if (!pendingOverride) throw new Error(zh ? '待決事件已失效，請重新載入方案。' : 'The pending event is no longer valid; reload the scenario.');
    const response = await fetch(`${apiBase.replace(/\/$/, '')}/api/v1/projects/${encodeURIComponent(pendingOverride.projectId)}/decisions`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(submission),
    });
    if (!response.ok) {
      if (response.status === 409) throw new Error(zh ? '目標版本或幾何已變更；請重新載入後再決定。' : 'The target revision or geometry has changed; reload before deciding.');
      throw new Error(zh ? '人類決策未被接受；待決事件仍保留。' : 'The human decision was not accepted; the pending event is retained.');
    }
    setResult(zh ? `HumanDecision 已提交；待決事件：${pendingOverride.eventId}` : `HumanDecision submitted; pending event: ${pendingOverride.eventId}`);
    setPendingOverride(null);
    setOverrideDialogOpen(false);
    onChanged?.();
  }

  async function operate(kind: string) {
    if (!view) return;
    if (kind === 'override') { await requestOverride(); return; }
    const target = kind === 'inspect' && view.cards.length
      ? { entity_id: view.cards[0].evidence_id, revision: view.cards[0].revision }
      : entityRef(view.scenario_ref);
    const peer = rows.find(row => row.entity_id === other);
    if (kind === 'rerun') {
      const run = view.runs.find(row => row.entity_id === runId);
      if (!run || !planId || !peer) { setResult('Approved plan, original ToolExecution and baseline scenario required'); return; }
      const key = rerunKey || crypto.randomUUID(); setRerunKey(key);
      await send(`${workspacePath}/rerun`, { target: { entity_id: run.entity_id, revision: run.revision }, stage: rerunStage,
        plan_artifact_id: planId, baseline_scenario_id: peer.entity_id, modified_scenario_id: view.scenario_ref.entity_id, idempotency_key: key });
      return;
    }
    await send(`${workspacePath}/operations/${kind}`, {
      target, reason, branch_id: kind === 'fork' ? branch : null,
      compare_targets: kind === 'compare' && peer ? [entityRef(view.scenario_ref), { entity_id: peer.entity_id, revision: peer.revision }] : [],
    });
  }

  return <details open={expanded} onToggle={event => onExpandedChange?.(event.currentTarget.open)} className="week7-actions" aria-label={zh ? '第 7 週質疑與修改' : 'Week 7 contest actions'} data-testid="week7-actions"><summary>{zh ? '質疑與修改' : 'Challenge and modify'}</summary><div className="week7-fields">
    <span>{zh ? '真實方案與證據 · 正式決策待 Founder' : 'Real scenarios and evidence · Founder decision pending'}</span>
    <label>{zh ? '方案 ' : 'Scenario '}<select aria-label={zh ? 'W7 方案' : 'W7 scenario'} value={selected} onChange={e => setSelected(e.target.value)}>
      {rows.map(row => <option key={row.entity_id} value={row.entity_id}>{row.label} @{row.revision} · {row.status}</option>)}
    </select><small>{zh ? '選擇要檢視的已儲存方案。' : 'Choose a persisted scenario.'}</small></label>
    <button disabled={busy || unknown || overrideDialogOpen || !view || !rows.some(r => r.entity_id === selected)} onClick={() => {
      const row = rows.find(r => r.entity_id === selected);
      if (row && view) void send(`${workspacePath}/switch`, { target: { entity_id: row.entity_id, revision: row.revision }, workspace_revision: view.workspace_ref.revision });
    }}>{zh ? '切換方案' : 'Switch scenario'}</button>

    <label>{zh ? '理由／質疑 ' : 'Reason / challenge '}<input value={reason} onChange={e => setReason(e.target.value)} /><small>{zh ? '記錄可追溯的理由；不等於人類批准。' : 'Record a traceable reason; this is not human approval.'}</small></label>




    {['inspect', 'challenge', 'modify', 'rerun', 'compare', 'fork', 'reject', 'override'].map(kind =>
      <fieldset key={kind}><legend>{kind[0].toUpperCase() + kind.slice(1)}</legend>{kind === 'compare' && <><label>{zh ? '比較方案 ' : 'Compare scenario '}<select aria-label={zh ? 'W7 比較方案' : 'W7 compare scenario'} value={other} onChange={e => setOther(e.target.value)}>
      <option value="">{zh ? '選擇' : 'Select'}</option>{rows.filter(r => r.entity_id !== view?.scenario_ref.entity_id).map(r => <option key={r.entity_id} value={r.entity_id}>{r.label} @{r.revision}</option>)}
    </select><small>{zh ? '選擇比較基準；不宣告優勝者。' : 'Choose a baseline; no winner is declared.'}</small></label></>}{kind === 'fork' && <><label>{zh ? '新分支 ID ' : 'New branch ID '}<input value={branch} onChange={e => setBranch(e.target.value)} /><small>{zh ? '建立新分支，保留原方案。' : 'Create a new branch and preserve the original.'}</small></label></>}{kind === 'rerun' && <><label>{zh ? '原分析執行 ' : 'Original execution '}<select aria-label={zh ? 'W7 原始分析' : 'W7 execution'} value={runId} onChange={e => setRunId(e.target.value)}>
      <option value="">{zh ? '選擇' : 'Select'}</option>{view?.runs.map(r => <option key={r.entity_id} value={r.entity_id}>{r.entity_id} @{r.revision}</option>)}
    </select><small>{zh ? '選擇原始分析執行。' : 'Choose the original analysis execution.'}</small></label><label>{zh ? '已批准 Plan Artifact ID ' : 'Approved plan artifact ID '}<input value={planId} onChange={e => setPlanId(e.target.value)} /><small>{zh ? '輸入現行已批准計畫的 Artifact ID。' : 'Enter the currently approved plan artifact ID.'}</small></label><label>{zh ? '重跑方法' : 'Rerun method'}<select aria-label={zh ? 'W7 重跑方法' : 'W7 rerun method'} value={rerunStage} onChange={e => setRerunStage(e.target.value as 'E1' | 'E2')}><option>E1</option><option>E2</option></select><small>{zh ? '使用已批准的分析計畫。' : 'Use the approved analysis plan.'}</small></label></>}<p>{descriptions[kind][zh ? 1 : 0]}</p><button data-testid={`week7-op-${kind}`} disabled={!view || busy || unknown || overrideDialogOpen || (kind === 'override' && Boolean(pendingOverride)) || (['challenge', 'reject', 'override'].includes(kind) && !reason.trim()) || (kind === 'compare' && !other) || (kind === 'fork' && !branch.trim())}
        onClick={() => void operate(kind)}>{zh ? ({ inspect: '檢視', challenge: '質疑', modify: '修改', rerun: '重跑', compare: '比較', fork: '分支', reject: '拒絕（待 Founder 決策）', override: '覆寫（待 Founder 決策）' }[kind]) : (['reject', 'override'].includes(kind) ? `${kind} (Founder decision pending)` : kind)}</button></fieldset>)}
    <p>{zh ? 'Modify 開啟 W6 正式草稿；Rerun 需已批准 plan。Reject／Override 只記錄待決判斷，正式決策走 Founder 入口。' : 'Modify opens a W6 formal draft. Rerun requires an approved plan. Reject and Override record pending judgments for the Founder decision entrance.'}</p>
    <label>{zh ? '出圖 ' : 'Figure '}<select aria-label={zh ? 'W7 出圖' : 'W7 figure kind'} value={figureKind} onChange={e => setFigureKind(e.target.value)}>
      {['plan','perspective','axonometric','massing','site','syntax','e1','e2','comparison'].map(k => <option key={k}>{k}</option>)}
    </select><small>{zh ? '選擇匯出圖面類型。' : 'Choose the exported figure type.'}</small></label>
    {figureKind === 'syntax' && <label>{zh ? 'Syntax 圖層 ' : 'Syntax layer '}<input aria-label={zh ? 'W7 Syntax 圖層' : 'W7 syntax layer'} value={syntaxLayer} onChange={e => setSyntaxLayer(e.target.value)} /><small>{zh ? '指定分析使用的 Syntax 圖層。' : 'Specify the analysis Syntax layer.'}</small></label>}
    <label>{zh ? '分析結果 Artifact IDs ' : 'Result artifact IDs '}<input value={resultArtifacts} onChange={e => setResultArtifacts(e.target.value)} /><small>{zh ? '以逗號分隔已儲存的分析結果 ID。' : 'Separate persisted analysis artifact IDs with commas.'}</small></label>
    <button disabled={!view || busy || unknown} onClick={() => {
      if (!view) return;
      const peer = rows.find(r => r.entity_id === other);
      void send(`${workspacePath}/figures`, { kind: figureKind, targets: [entityRef(view.scenario_ref), ...(figureKind === 'comparison' && peer ? [{ entity_id: peer.entity_id, revision: peer.revision }] : [])],
        result_artifact_ids: resultArtifacts.split(',').map(v => v.trim()).filter(Boolean), syntax_layer_id: figureKind === 'syntax' ? syntaxLayer : null });
    }}>{zh ? '匯出真實場景' : 'Export real scene'}</button>
    {figureUrl && <a href={figureUrl} download>{zh ? '下載 PNG' : 'Download PNG'}</a>}
    {unknown && <p role="alert">{zh ? '處置結果未知；必須完成核對後才能再操作，系統不會重送。' : 'OUTCOME_UNKNOWN — reconciliation required; submission locked'}</p>}
    {pendingOverride && !overrideDialogOpen && <button type="button" data-testid="week7-continue-human-decision" onClick={() => setOverrideDialogOpen(true)}>{zh ? '繼續人類覆寫決策' : 'Continue human override decision'}</button>}
    <pre data-testid="week7-op-result">{result}</pre>
  </div>
  {pendingOverride && <HumanDecisionDialog
    isOpen={overrideDialogOpen}
    target={{ id: pendingOverride.scenarioId, type: 'DesignScenario', version: String(pendingOverride.revision), geometrySha256: pendingOverride.geometrySha256 }}
    action="Override" status="overridden"
    onClose={() => setOverrideDialogOpen(false)}
    onSubmit={submitOverrideDecision}
    reviewContent={<div>{zh ? `待決事件：${pendingOverride.eventId}。此操作不修改計算值；只有使用者輸入決策密語並提交後，既有 HumanDecision API 才會記錄人類決策。` : `Pending event: ${pendingOverride.eventId}. This operation does not change computed values. The existing HumanDecision API records the human decision only after the user enters the decision key and submits.`}</div>}
  />}
  </details>;
}

export function Week7Chrome({ apiBase, workspaceId, scenarioId }: Props) {
  const [nonce, setNonce] = useState(0);
  const [actionsExpanded, setActionsExpanded] = useState(false);
  return <><Week7StatusBar key={`week7-status-refresh:${nonce}`} apiBase={apiBase} workspaceId={workspaceId} scenarioId={scenarioId} />
    <Week7Actions key={`week7-actions-refresh:${nonce}`} apiBase={apiBase} workspaceId={workspaceId} scenarioId={scenarioId} expanded={actionsExpanded} onExpandedChange={setActionsExpanded} onChanged={() => setNonce(n => n + 1)} /></>;
}
