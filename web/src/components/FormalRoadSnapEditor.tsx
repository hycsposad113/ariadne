import { useEffect, useState } from 'react';
import { isRoadNodeLocked, type RoadGraphRecord } from '../utils/scenarioEdits';
import { RoadSnapPanel, type RoadSnapLocale, type RoadSnapRequest, type ServerRoadSnapCandidate } from './RoadSnapPanel';

type CandidateResponse = { status: string; graph_hash: string; revision_id: number; candidates: ServerRoadSnapCandidate[] };
export function FormalRoadSnapEditor({ apiBase, scenarioId, graph, revision, onSaved, locale }: {
  apiBase: string; scenarioId: string; graph?: RoadGraphRecord; revision: number;
  onSaved: () => void | Promise<void>; locale: RoadSnapLocale;
}) {
  const zh = locale === 'zh-TW';
  const nodes = graph?.nodes.filter(node => !isRoadNodeLocked(graph, node.node_id)) ?? [];
  const [nodeId, setNodeId] = useState(nodes[0]?.node_id ?? '');
  const [x, setX] = useState(String(nodes[0]?.x_m ?? 0));
  const [y, setY] = useState(String(nodes[0]?.y_m ?? 0));
  const [anchor, setAnchor] = useState('');
  const [result, setResult] = useState<CandidateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  useEffect(() => { setResult(null); setError(null); }, [scenarioId, graph?.graph_hash, revision, nodeId, x, y, anchor]);
  useEffect(() => { const first = graph?.nodes.find(node => !isRoadNodeLocked(graph, node.node_id)); setNodeId(first?.node_id ?? ''); setX(String(first?.x_m ?? 0)); setY(String(first?.y_m ?? 0)); setAnchor(''); }, [scenarioId, graph?.graph_hash]);
  const url = `${apiBase}/api/v1/scenarios/${encodeURIComponent(scenarioId)}/road-nodes/${encodeURIComponent(nodeId)}`;
  const request = async (route: string, payload: unknown) => {
    const response = await fetch(`${url}/${route}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(`${zh ? '道路編輯失敗' : 'Road edit failed'} (HTTP ${response.status})${typeof body?.detail === 'string' ? `: ${body.detail}` : ''}`);
    return body;
  };
  const load = async () => {
    setPending(true); setError(null);
    try { setResult(await request('snap-candidates', { x_m: Number(x), y_m: Number(y), expected_revision: revision, expected_graph_hash: graph?.graph_hash, perpendicular_anchor_node_id: anchor || null })); }
    catch (caught) { setResult(null); setError(caught instanceof Error ? caught.message : String(caught)); }
    finally { setPending(false); }
  };
  const apply = async (selected: RoadSnapRequest) => {
    try {
      await request('move', { x_m: selected.x_m, y_m: selected.y_m, expected_revision: selected.expected_revision, expected_graph_hash: selected.graph_hash, snap_kind: selected.snap_kind, target_id: selected.target_id, perpendicular_anchor_node_id: selected.perpendicular_anchor_node_id ?? null, idempotency_key: globalThis.crypto?.randomUUID?.() ?? `road-snap-${Date.now()}` });
      await onSaved();
      return { status: 'DRAFT' };
    } catch (caught) { setError(caught instanceof Error ? caught.message : String(caught)); throw caught; }
  };
  return <section aria-label={zh ? '正式草稿道路吸附' : 'Formal draft road snapping'}>
    {!nodes.length && <p role="status">{zh ? '此草稿沒有可編輯道路節點；無法取得吸附目標。' : 'No editable road nodes are available in this draft; snap targets cannot be loaded.'}</p>}
    <label>{zh ? '道路節點' : 'Road node'}<select value={nodeId} onChange={event => { const node = nodes.find(item => item.node_id === event.target.value); setNodeId(event.target.value); setX(String(node?.x_m ?? 0)); setY(String(node?.y_m ?? 0)); }}>{nodes.map(node => <option key={node.node_id} value={node.node_id}>{node.node_id}</option>)}</select></label>
    <label>{zh ? '目標 X（公尺）' : 'Target X (metres)'}<input type="number" value={x} onChange={event => setX(event.target.value)} /></label>
    <label>{zh ? '目標 Y（公尺）' : 'Target Y (metres)'}<input type="number" value={y} onChange={event => setY(event.target.value)} /></label>
    <label>{zh ? '垂直投影固定錨點' : 'Fixed perpendicular anchor'}<select value={anchor} onChange={event => setAnchor(event.target.value)}><option value="">{zh ? '未選取' : 'None selected'}</option>{graph?.nodes.filter(node => node.node_id !== nodeId && graph.edges.some(edge => (edge.start_node_id === nodeId && edge.end_node_id === node.node_id) || (edge.end_node_id === nodeId && edge.start_node_id === node.node_id))).map(node => <option key={node.node_id} value={node.node_id}>{node.node_id}</option>)}</select></label>
    <button type="button" disabled={!nodeId || pending || !x.trim() || !y.trim() || !Number.isFinite(Number(x)) || !Number.isFinite(Number(y))} onClick={() => void load()}>{zh ? '載入吸附目標' : 'Load snap targets'}</button>
    {error && <p role="alert">{error}</p>}
    <RoadSnapPanel key={`${scenarioId}:${nodeId}:${x}:${y}:${anchor}`} locale={locale} readiness={!result || result.status === 'NOT_READY' ? 'BLOCKED' : 'DRAFT'} graphHash={graph?.graph_hash ?? ''} revision={revision} candidates={result?.candidates ?? []} candidatesGraphHash={result?.graph_hash ?? graph?.graph_hash ?? ''} candidatesRevision={result?.revision_id ?? revision} perpendicularAnchorNodeId={anchor || null} onPreview={async () => { const fresh = await request('snap-candidates', { x_m: Number(x), y_m: Number(y), expected_revision: revision, expected_graph_hash: graph?.graph_hash, perpendicular_anchor_node_id: anchor || null }); return { graph_hash: fresh.graph_hash, revision: fresh.revision_id }; }} onApply={apply} />
  </section>;
}
