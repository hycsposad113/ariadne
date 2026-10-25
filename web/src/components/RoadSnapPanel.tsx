import { useEffect, useMemo, useRef, useState } from 'react';
import type { RoadSnapKind } from '../utils/scenarioEdits';
import './RoadSnapPanel.css';

export type RoadSnapReadiness = 'BLOCKED' | 'FIXTURE_ONLY' | 'DRAFT';
export type RoadSnapLocale = 'en' | 'zh-TW';

/** Candidate values are returned by the server and bound to one graph revision. */
export type ServerRoadSnapCandidate = {
  snap_kind: RoadSnapKind;
  x_m: number;
  y_m: number;
  distance_m: number;
  target_node_id: string | null;
  target_edge_ids: readonly string[];
  position_semantics: string;
  target_length_m?: number | null;
  distance_along_m?: number | null;
  target_fraction?: number | null;
  candidate_id?: string;
};

export type RoadSnapRequest = {
  snap_kind: RoadSnapKind;
  target_id: string;
  target_node_id: string | null;
  target_edge_ids: readonly string[];
  x_m: number;
  y_m: number;
  distance_m: number;
  position_semantics: string;
  graph_hash: string;
  expected_revision: number;
  perpendicular_anchor_node_id?: string | null;
};

export type RoadSnapPreviewResult = {
  graph_hash: string;
  revision: number;
  hints?: readonly string[];
  message?: string;
};

export type RoadSnapApplyResult = {
  status?: string;
  graph_hash?: string;
  revision?: number;
  message?: string;
};

export type RoadSnapPanelProps = {
  locale: RoadSnapLocale;
  readiness: RoadSnapReadiness;
  graphHash: string;
  revision: number;
  candidates: readonly ServerRoadSnapCandidate[];
  /** Identity returned with the candidate response; required to reject late candidate lists. */
  candidatesGraphHash: string;
  candidatesRevision: number;
  perpendicularAnchorNodeId?: string | null;
  onPreview: (request: RoadSnapRequest) => RoadSnapPreviewResult | void | Promise<RoadSnapPreviewResult | void>;
  onApply: (request: RoadSnapRequest) => RoadSnapApplyResult | void | Promise<RoadSnapApplyResult | void>;
};

type Copy = {
  heading: string;
  explanation: string;
  readiness: Record<RoadSnapReadiness, string>;
  graph: string;
  revision: string;
  candidates: string;
  noCandidates: string;
  staleCandidates: string;
  blocked: string;
  fixtureNote: string;
  selected: string;
  preview: string;
  apply: string;
  previewing: string;
  applying: string;
  previewSubmitted: string;
  previewStale: string;
  previewFailed: string;
  applyFailed: string;
  applied: string;
  position: string;
  coords: string;
  distance: string;
  along: string;
  target: string;
  previewHints: string;
  kinds: Record<RoadSnapKind, string>;
  semantics: Record<RoadSnapKind, string>;
};

const COPY: Record<RoadSnapLocale, Copy> = {
  en: {
    heading: 'Road snap',
    explanation: 'Choose a server-calculated target. Distances and coordinates use ground metres.',
    readiness: { BLOCKED: 'Blocked', FIXTURE_ONLY: 'Fixture only', DRAFT: 'Draft ready' },
    graph: 'Graph',
    revision: 'Revision',
    candidates: 'Snap candidates',
    noCandidates: 'No valid candidates are available for this graph revision.',
    staleCandidates: 'These candidates belong to a different graph hash or revision. Refresh them before continuing.',
    blocked: 'Road snapping is blocked by the current server readiness state.',
    fixtureNote: 'Fixture candidates can be previewed and saved as a draft; they are not approved design evidence.',
    selected: 'Selected target',
    preview: 'Preview selected',
    apply: 'Apply snap as draft',
    previewing: 'Requesting preview…',
    applying: 'Applying snap…',
    previewSubmitted: 'Preview is current for this graph revision.',
    previewStale: 'The server returned a preview for another graph revision. It was ignored.',
    previewFailed: 'Preview request failed.',
    applyFailed: 'Snap could not be applied.',
    applied: 'Snap request completed.',
    position: 'Position',
    coords: 'Coordinates',
    distance: 'Distance from requested point',
    along: 'Along target edge',
    target: 'Target',
    previewHints: 'Current graph hints',
    kinds: {
      ENDPOINT: 'Endpoint',
      NEAREST_POINT: 'Nearest point',
      MIDPOINT: 'Midpoint',
      INTERSECTION: 'Intersection',
      PERPENDICULAR: 'Perpendicular',
      QUARTER: 'Quarter point',
      THREE_QUARTER: 'Three-quarter point',
    },
    semantics: {
      ENDPOINT: 'Existing connected road node.',
      NEAREST_POINT: 'Closest point on a finite straight road segment.',
      MIDPOINT: 'Midpoint measured along the full straight target edge.',
      INTERSECTION: 'At-grade crossing of compatible straight road edges.',
      PERPENDICULAR: 'Perpendicular projection from the selected fixed incident anchor onto the target segment.',
      QUARTER: 'One-quarter of the full straight target-edge length.',
      THREE_QUARTER: 'Three-quarters of the full straight target-edge length.',
    },
  },
  'zh-TW': {
    heading: '道路吸附',
    explanation: '選擇伺服器計算的目標；座標與距離均以地面公尺表示。',
    readiness: { BLOCKED: '受阻', FIXTURE_ONLY: '僅測試資料', DRAFT: '草稿可編輯' },
    graph: '路網',
    revision: '版本',
    candidates: '吸附候選',
    noCandidates: '此路網版本沒有有效候選。',
    staleCandidates: '候選屬於其他路網雜湊或版本；請更新後再操作。',
    blocked: '目前伺服器狀態禁止道路吸附。',
    fixtureNote: '測試候選可預覽並存為草稿，不代表已核准的設計證據。',
    selected: '已選目標',
    preview: '預覽所選目標',
    apply: '套用吸附並存為草稿',
    previewing: '正在請求預覽…',
    applying: '正在套用吸附…',
    previewSubmitted: '預覽對應目前路網版本。',
    previewStale: '伺服器回傳其他路網版本的預覽，已忽略。',
    previewFailed: '預覽請求失敗。',
    applyFailed: '無法套用吸附。',
    applied: '吸附請求已完成。',
    position: '位置語義',
    coords: '座標',
    distance: '距離拖曳位置',
    along: '沿目標道路長度',
    target: '目標',
    previewHints: '目前路網提示',
    kinds: {
      ENDPOINT: '端點',
      NEAREST_POINT: '最近點',
      MIDPOINT: '中點',
      INTERSECTION: '交點',
      PERPENDICULAR: '垂直投影點',
      QUARTER: '四分之一點',
      THREE_QUARTER: '四分之三點',
    },
    semantics: {
      ENDPOINT: '既有且連接於道路的節點。',
      NEAREST_POINT: '投影至有限範圍內的直線道路段。',
      MIDPOINT: '沿完整目標直線路段長度計算的中點。',
      INTERSECTION: '符合相同道路層級的直線路段平面交點。',
      PERPENDICULAR: '從選定且固定的相連錨點，垂直投影至目標路段。',
      QUARTER: '沿完整目標直線路段長度的四分之一位置。',
      THREE_QUARTER: '沿完整目標直線路段長度的四分之三位置。',
    },
  },
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function candidateKey(candidate: ServerRoadSnapCandidate): string {
  return candidate.candidate_id ?? [
    candidate.snap_kind,
    candidate.target_node_id ?? '',
    candidate.target_edge_ids.join(','),
    candidate.x_m,
    candidate.y_m,
  ].join(':');
}

function targetFor(candidate: ServerRoadSnapCandidate): string | null {
  if (candidate.snap_kind === 'ENDPOINT') return candidate.target_node_id ?? null;
  return candidate.target_edge_ids[0] ?? candidate.target_node_id ?? null;
}

function formatMetres(value: number, locale: RoadSnapLocale): string {
  return new Intl.NumberFormat(locale === 'zh-TW' ? 'zh-TW' : 'en', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 3,
  }).format(value);
}

function positionText(candidate: ServerRoadSnapCandidate, copy: Copy, perpendicularAnchorNodeId?: string | null): string {
  const raw = candidate.position_semantics.trim().toLowerCase();
  if (candidate.snap_kind === 'PERPENDICULAR') {
    const anchor = raw.match(/(?:anchor|node)\s+([^\s,]+?)(?:\s+onto|\s+to|\s+along|$)/)?.[1] ?? perpendicularAnchorNodeId;
    if (anchor) return copy === COPY.en
      ? `Perpendicular projection from fixed anchor node ${anchor} onto the target segment.`
      : `從固定錨點節點 ${anchor} 垂直投影至目標路段。`;
  }
  if (raw.includes('intersection') || raw.includes('crossing')) return copy.semantics.INTERSECTION;
  if (raw.includes('perpendicular') || raw.includes('orthogonal')) return copy.semantics.PERPENDICULAR;
  if (raw.includes('nearest') || raw.includes('projection')) return candidate.snap_kind === 'PERPENDICULAR'
    ? copy.semantics.PERPENDICULAR
    : copy.semantics.NEAREST_POINT;
  if (raw.includes('endpoint') || raw.includes('road node')) return copy.semantics.ENDPOINT;
  if (raw.includes('length') || raw.includes('straight')) return copy.semantics[candidate.snap_kind];
  return raw ? `${copy.semantics[candidate.snap_kind]} ${candidate.position_semantics}` : copy.semantics[candidate.snap_kind];
}

function requestFor(
  candidate: ServerRoadSnapCandidate,
  graphHash: string,
  revision: number,
  perpendicularAnchorNodeId: string | null | undefined,
): RoadSnapRequest | null {
  const targetId = targetFor(candidate);
  if (!targetId) return null;
  return {
    snap_kind: candidate.snap_kind,
    target_id: targetId,
    target_node_id: candidate.target_node_id,
    target_edge_ids: candidate.target_edge_ids,
    x_m: candidate.x_m,
    y_m: candidate.y_m,
    distance_m: candidate.distance_m,
    position_semantics: candidate.position_semantics,
    graph_hash: graphHash,
    expected_revision: revision,
    ...(candidate.snap_kind === 'PERPENDICULAR' ? { perpendicular_anchor_node_id: perpendicularAnchorNodeId ?? null } : {}),
  };
}

export function RoadSnapPanel({
  locale,
  readiness,
  graphHash,
  revision,
  candidates,
  candidatesGraphHash,
  candidatesRevision,
  perpendicularAnchorNodeId,
  onPreview,
  onApply,
}: RoadSnapPanelProps) {
  const copy = COPY[locale];
  const graphKey = `${graphHash}\u0000${revision}`;
  const graphContextRef = useRef(graphKey);
  graphContextRef.current = graphKey;
  const previewSequence = useRef(0);
  const [selection, setSelection] = useState<{ graphKey: string; key: string } | null>(null);
  const selectedKey = selection?.graphKey === graphKey ? selection.key : null;
  const [previewState, setPreviewState] = useState<
    | { status: 'loading' }
    | { status: 'ready'; hints: readonly string[]; message?: string }
    | { status: 'stale' }
    | { status: 'error'; message: string }
    | null
  >(null);
  const [previewGraphKey, setPreviewGraphKey] = useState<string | null>(null);
  const [applyState, setApplyState] = useState<'idle' | 'loading' | 'done' | 'error'>('idle');

  useEffect(() => {
    previewSequence.current += 1;
    setSelection(null);
    setPreviewState(null);
    setPreviewGraphKey(null);
    setApplyState('idle');
  }, [graphKey]);

  const candidateSetIsCurrent = candidatesGraphHash === graphHash && candidatesRevision === revision;
  const validCandidates = useMemo(() => candidates.filter((candidate) =>
    isFiniteNumber(candidate.x_m)
    && isFiniteNumber(candidate.y_m)
    && isFiniteNumber(candidate.distance_m)
    && candidate.distance_m >= 0
    && typeof candidate.position_semantics === 'string'
    && candidate.position_semantics.trim().length > 0
    && Array.isArray(candidate.target_edge_ids)
    && targetFor(candidate) !== null,
  ), [candidates]);
  const selected = validCandidates.find((candidate) => candidateKey(candidate) === selectedKey) ?? null;
  const selectedRequest = selected ? requestFor(selected, graphHash, revision, perpendicularAnchorNodeId) : null;
  const blocked = readiness === 'BLOCKED' || !candidateSetIsCurrent;
  const visiblePreviewState = previewGraphKey === graphKey ? previewState : null;
  const pending = visiblePreviewState?.status === 'loading' || applyState === 'loading';

  const chooseCandidate = (candidate: ServerRoadSnapCandidate) => {
    previewSequence.current += 1;
    setPreviewState(null);
    setPreviewGraphKey(null);
    setApplyState('idle');
    setSelection({ graphKey, key: candidateKey(candidate) });
  };

  const previewSelected = async () => {
    if (blocked || !selected || !selectedRequest) return;
    const requestGraphKey = graphKey;
    const requestSequence = ++previewSequence.current;
    setPreviewGraphKey(requestGraphKey);
    setPreviewState({ status: 'loading' });
    setApplyState('idle');
    try {
      const result = await onPreview(selectedRequest);
      if (requestSequence !== previewSequence.current || graphContextRef.current !== requestGraphKey) return;
      if (result && (result.graph_hash !== graphHash || result.revision !== revision)) {
        setPreviewState({ status: 'stale' });
        return;
      }
      setPreviewState({ status: 'ready', hints: result?.hints ?? [], ...(result?.message ? { message: result.message } : {}) });
    } catch (error) {
      if (requestSequence !== previewSequence.current || graphContextRef.current !== requestGraphKey) return;
      setPreviewState({ status: 'error', message: error instanceof Error ? error.message : copy.previewFailed });
    }
  };

  const applySelected = async () => {
    if (blocked || !selectedRequest || applyState === 'loading') return;
    const requestGraphKey = graphKey;
    setApplyState('loading');
    try {
      const result = await onApply(selectedRequest);
      if (result?.status && !['DRAFT', 'FIXTURE_ONLY'].includes(result.status.toUpperCase())) {
        throw new Error(copy.applyFailed);
      }
      if (graphContextRef.current === requestGraphKey) setApplyState('done');
    } catch {
      if (graphContextRef.current === requestGraphKey) setApplyState('error');
    }
  };

  return (
    <section className="road-snap-panel" aria-labelledby="road-snap-panel-title">
      <header className="road-snap-panel__header">
        <div>
          <h2 id="road-snap-panel-title">{copy.heading}</h2>
          <p>{copy.explanation}</p>
        </div>
        <span className={`road-snap-panel__readiness road-snap-panel__readiness--${readiness.toLowerCase()}`} role="status">
          {copy.readiness[readiness]}
        </span>
      </header>

      <dl className="road-snap-panel__context">
        <div><dt>{copy.graph}</dt><dd title={graphHash}>{graphHash || '—'}</dd></div>
        <div><dt>{copy.revision}</dt><dd>{revision}</dd></div>
      </dl>

      {readiness === 'BLOCKED' && <p className="road-snap-panel__notice" role="alert">{copy.blocked}</p>}
      {readiness === 'FIXTURE_ONLY' && <p className="road-snap-panel__notice" role="status">{copy.fixtureNote}</p>}
      {!candidateSetIsCurrent && <p className="road-snap-panel__notice" role="alert">{copy.staleCandidates}</p>}

      <div className="road-snap-panel__list" aria-label={copy.candidates}>
        <h3>{copy.candidates}</h3>
        {validCandidates.length === 0 ? <p className="road-snap-panel__empty">{copy.noCandidates}</p> : (
          <ul>
            {validCandidates.map((candidate) => {
              const key = candidateKey(candidate);
              const target = targetFor(candidate);
              const isSelected = key === selectedKey;
              const along = isFiniteNumber(candidate.distance_along_m) && isFiniteNumber(candidate.target_length_m)
                ? `${copy.along}: ${formatMetres(candidate.distance_along_m, locale)} m / ${formatMetres(candidate.target_length_m, locale)} m${isFiniteNumber(candidate.target_fraction) ? ` (${formatMetres(candidate.target_fraction * 100, locale)}%)` : ''}`
                : null;
              return (
                <li key={key}>
                  <button
                    className={`road-snap-panel__candidate${isSelected ? ' is-selected' : ''}`}
                    type="button"
                    aria-pressed={isSelected}
                    disabled={blocked}
                    onClick={() => chooseCandidate(candidate)}
                  >
                    <span className="road-snap-panel__candidate-heading">
                      <strong>{copy.kinds[candidate.snap_kind]}</strong>
                      <span>{copy.target}: {target}</span>
                    </span>
                    <span>{copy.coords}: ({formatMetres(candidate.x_m, locale)} m, {formatMetres(candidate.y_m, locale)} m)</span>
                    <span>{copy.distance}: {formatMetres(candidate.distance_m, locale)} m</span>
                    {along && <span>{along}</span>}
                    <span className="road-snap-panel__semantics" data-position-semantics={candidate.position_semantics}>
                      {copy.position}: {positionText(candidate, copy, perpendicularAnchorNodeId)}
                    </span>
                    {candidate.target_edge_ids.length > 1 && (
                      <span>{copy.target}: {candidate.target_edge_ids.join(' · ')}</span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="road-snap-panel__actions">
        <p className="road-snap-panel__selected">
          {copy.selected}: {selected ? `${copy.kinds[selected.snap_kind]} · ${targetFor(selected)}` : '—'}
        </p>
        <div>
          <button type="button" className="road-snap-panel__secondary" disabled={blocked || !selectedRequest || pending} onClick={() => void previewSelected()}>
      {visiblePreviewState?.status === 'loading' ? copy.previewing : copy.preview}
          </button>
          <button type="button" className="road-snap-panel__primary" disabled={blocked || !selectedRequest || pending} onClick={() => void applySelected()}>
            {applyState === 'loading' ? copy.applying : copy.apply}
          </button>
        </div>
      </div>

      {visiblePreviewState?.status === 'ready' && (
        <div className="road-snap-panel__result" role="status" data-graph-hash={graphHash} data-revision={revision}>
          <p>{visiblePreviewState.message ?? copy.previewSubmitted}</p>
          {visiblePreviewState.hints.length > 0 && (
            <div>
              <strong>{copy.previewHints}</strong>
              <ul>{visiblePreviewState.hints.map((hint, index) => <li key={`${index}-${hint}`}>{hint}</li>)}</ul>
            </div>
          )}
        </div>
      )}
      {visiblePreviewState?.status === 'stale' && <p className="road-snap-panel__notice" role="status">{copy.previewStale}</p>}
      {visiblePreviewState?.status === 'error' && <p className="road-snap-panel__notice" role="alert">{visiblePreviewState.message || copy.previewFailed}</p>}
      {applyState === 'done' && <p className="road-snap-panel__result" role="status">{copy.applied}</p>}
      {applyState === 'error' && <p className="road-snap-panel__notice" role="alert">{copy.applyFailed}</p>}
    </section>
  );
}
