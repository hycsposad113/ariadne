import { ScenarioSyntaxControls } from './ScenarioSyntaxControls';
import { proposalRoadMetadata, proposalRoadStyle } from '../utils/proposalRoads';
import { classifyContextValue, type SyntaxContextResponse } from '../utils/syntaxContext';
import { useI18n, useT } from '../i18n';
import { StatusBadge, getStatusLabel } from '../i18n/statusLabels';
import { ScenarioStudioDashboard } from './ScenarioStudioDashboard';
import { FormalRoadSnapEditor } from './FormalRoadSnapEditor';
import { FormalFaceEditor } from './FormalFaceEditor';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ScenarioModel3D } from './ScenarioModel3D';
import { MassingIntent, type MassingIntentRecord } from './MassingIntent';
import { MorphologyPreviewCatalog } from './MorphologyPreviewCatalog';
import { findRoadSnapCandidates, isRoadNodeLocked, oneMetreMove, rotationStep, type EditableFloor, type MassingCommand, type RoadGraphRecord } from '../utils/scenarioEdits';
import './ScenarioStudio.css';

type Metric = {
  value?: number | null;
  range?: unknown;
  unit?: string;
  method?: string;
  validation_status?: string;
  data_gaps?: string[];
};
type ScenarioSummary = {
  scenario_id: string;
  status: string;
  provenance: string;
  valid: boolean;
  failure_reasons: string[];
  strategy_label: string;
  strategy_explanation_status: string;
  strategy_explanation: string;
  metrics: Record<string, Metric>;
};
type GeometryFeature = {
  id?: string;
  type: string;
  geometry: { type: string; coordinates: unknown };
  properties: Record<string, unknown>;
};
type EditableFloorRecord = EditableFloor & { geometry: { type: string; coordinates: number[][][] | number[][][][] } };
type EditableBuilding = {
  building_id: string;
  floors: EditableFloorRecord[];
  first_floor_height_m: number;
  standard_floor_height_m: number;
  geometry_hash?: string;
  use_label?: string;
  active_frontage?: boolean;
  design_intent?: MassingIntentRecord;
};
type ScenarioDetail = ScenarioSummary & {
  revision: number;
  geometry: { type: string; features: GeometryFeature[] };
  editor: {
    provenance: string;
    design_area_m2: number;
    limits: Record<string, number | null>;
    editable_buildings: EditableBuilding[];
    active_buildings: Record<string, EditableBuilding>;
    active_edit_revision_id: number;
    road_graph?: RoadGraphRecord;
    road_edit_revision_id?: number;
    road_snap_tolerance_m?: number | null;
    road_edit_policy_version?: string | null;
    syntax_result_ids?: string[];
    syntax_statuses?: Record<string, string>;
    accessibility_result_ids?: string[];
    accessibility_statuses?: Record<string, string>;
    e1_result_ids?: string[];
    e1_statuses?: Record<string, string>;
  };
};
type Comparison = {
  status: string;
  scenario_ids: string[];
  metrics: Array<{
    denominators?: Record<string, { label: string; area_m2?: number | null }>;
    metric_id: string;
    label: string;
    unit: string;
    method: string | null;
    data_gaps: string[];
    validation_status: Record<string, string>;
    status: string;
    values: Record<string, number | null>;
  }>;
};
type ViewMode = '2D' | '3D' | 'SPLIT' | 'COMPARE';
type StudioTab = 'editable' | 'previews';



function formatValue(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Unavailable';
  return Number(value.toFixed(3)).toString();
}

function polygonArea(geometry: EditableBuilding['floors'][number]['geometry']): number {
  const ringArea = (ring: number[][]) => Math.abs(ring.reduce((sum, current, index) => {
    const next = ring[(index + 1) % ring.length];
    return next ? sum + current[0] * next[1] - next[0] * current[1] : sum;
  }, 0)) / 2;
  const polygon = (rings: number[][][]) => rings.length ? ringArea(rings[0]) - rings.slice(1).reduce((sum, ring) => sum + ringArea(ring), 0) : 0;
  if (geometry.type === 'Polygon') return polygon(geometry.coordinates as number[][][]);
  if (geometry.type === 'MultiPolygon') return (geometry.coordinates as number[][][][]).reduce((sum, rings) => sum + polygon(rings), 0);
  return 0;
}

function allCoordinates(geometry: GeometryFeature['geometry']): number[][] {
  if (geometry.type === 'Polygon') return (geometry.coordinates as number[][][]).flat();
  if (geometry.type === 'MultiPolygon') return (geometry.coordinates as number[][][][]).flat(2);
  if (geometry.type === 'LineString') return geometry.coordinates as number[][];
  if (geometry.type === 'MultiLineString') return (geometry.coordinates as number[][][]).flat();
  return [];
}

type MapBounds = { minX: number; maxX: number; minY: number; maxY: number };

/** One metre-per-pixel scale for both axes (no distortion), centred in the 528×328 drawing area. */
function svgFrame(bounds: MapBounds) {
  const spanX = Math.max(bounds.maxX - bounds.minX, 1);
  const spanY = Math.max(bounds.maxY - bounds.minY, 1);
  const scale = Math.min(528 / spanX, 328 / spanY);
  return { scale, left: 36 + (528 - spanX * scale) / 2, top: 36 + (328 - spanY * scale) / 2 };
}

function projectToSvg(point: number[], bounds: MapBounds): [number, number] {
  const { scale, left, top } = svgFrame(bounds);
  return [left + (point[0] - bounds.minX) * scale, top + (bounds.maxY - point[1]) * scale];
}

function featurePath(feature: GeometryFeature, bounds: { minX: number; maxX: number; minY: number; maxY: number }): string {
  const geometry = feature.geometry;
  const paths: number[][][] = geometry.type === 'Polygon'
    ? (geometry.coordinates as number[][][])
    : geometry.type === 'MultiPolygon'
      ? (geometry.coordinates as number[][][][]).flat()
      : geometry.type === 'LineString'
        ? [geometry.coordinates as number[][]]
        : geometry.type === 'MultiLineString'
          ? geometry.coordinates as number[][][]
          : [];
  return paths.map((ring) => ring.map((point, index) => {
    const [x, y] = projectToSvg(point, bounds);
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(' ') + (geometry.type.includes('Polygon') ? ' Z' : '')).join(' ');
}

type RoadDragPreview = {
  nodeId: string;
  x_m: number;
  y_m: number;
  candidates: ReturnType<typeof findRoadSnapCandidates>;
};

const EMPTY_ROAD_GRAPH: RoadGraphRecord = { graph_hash: '', nodes: [], edges: [] };

function ScenarioMap({ detail, selectedBuildingId, highlightBuildingIds = [], onSelectBuilding, onRoadNodeMove, disabled, syntaxContext }: {
  detail: ScenarioDetail;
  syntaxContext?: SyntaxContextResponse | null;
  selectedBuildingId: string;
  highlightBuildingIds?: string[];
  onSelectBuilding: (id: string) => void;
  onRoadNodeMove: (nodeId: string, x_m: number, y_m: number) => void;
  disabled: boolean;
}) {
  const t = useT();
  const { language } = useI18n();
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ nodeId: string; startX: number; startY: number } | null>(null);
  const [dragPreview, setDragPreview] = useState<RoadDragPreview | null>(null);
  const features = detail.geometry.features;
  const roadGraph = detail.editor.road_graph ?? EMPTY_ROAD_GRAPH;
  const points = [
    ...features.flatMap((feature) => allCoordinates(feature.geometry)),
    ...roadGraph.nodes.map((node) => [node.x_m, node.y_m]),
  ];
  // Fit to the geometry itself. Anchoring at (0,0) only worked for local fixture
  // coordinates and collapsed real EPSG:28992 drafts (x≈88 km, y≈435 km) into a dot.
  const xs = points.map((point) => point[0]).filter(Number.isFinite);
  const ys = points.map((point) => point[1]).filter(Number.isFinite);
  const bounds = xs.length && ys.length
    ? { minX: Math.min(...xs), maxX: Math.max(...xs, Math.min(...xs) + 1), minY: Math.min(...ys), maxY: Math.max(...ys, Math.min(...ys) + 1) }
    : { minX: 0, maxX: 1, minY: 0, maxY: 1 };
  const pointForEvent = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    const width = Math.max(rect?.width ?? 0, 1);
    const height = Math.max(rect?.height ?? 0, 1);
    const left = rect?.left ?? 0;
    const top = rect?.top ?? 0;
    const scale = Math.min(width / 600, height / 400);
    const offsetX = (width - scale * 600) / 2;
    const offsetY = (height - scale * 400) / 2;
    const svgX = (event.clientX - left - offsetX) / scale;
    const svgY = (event.clientY - top - offsetY) / scale;
    const frame = svgFrame(bounds);
    return {
      x_m: bounds.minX + (svgX - frame.left) / frame.scale,
      y_m: bounds.maxY - (svgY - frame.top) / frame.scale,
    };
  };
  const updateDragPreview = (event: React.PointerEvent<SVGSVGElement>) => {
    const active = dragRef.current;
    const tolerance = detail.editor.road_snap_tolerance_m ?? 0;
    if (!active || disabled || tolerance <= 0) return;
    const point = pointForEvent(event);
    setDragPreview({
      nodeId: active.nodeId,
      ...point,
      candidates: findRoadSnapCandidates(roadGraph, active.nodeId, point.x_m, point.y_m, tolerance),
    });
  };
  const finishRoadDrag = (event: React.PointerEvent<SVGSVGElement>) => {
    const active = dragRef.current;
    if (!active) return;
    const point = pointForEvent(event);
    dragRef.current = null;
    setDragPreview(null);
    if (!disabled && (point.x_m !== active.startX || point.y_m !== active.startY)) {
      onRoadNodeMove(active.nodeId, point.x_m, point.y_m);
    }
  };
  const bestPreviewCandidate = dragPreview?.candidates.slice().sort((left, right) =>
    left.distance_m - right.distance_m || (left.kind === 'ENDPOINT' ? -1 : 1),
  )[0];
  return (
    <div className="scenario-map-wrap">
      <svg
        ref={svgRef}
        className="scenario-map"
        viewBox="0 0 600 400"
        role="group"
        aria-label={t("Scenario EPSG:28992 plan and road-node editor")}
        onPointerMove={updateDragPreview}
        onPointerUp={finishRoadDrag}
        onPointerCancel={() => { dragRef.current = null; setDragPreview(null); }}
      >
        <rect x="0" y="0" width="600" height="400" fill="#101826" />
        {features.map((feature, index) => {
          const kind = String(feature.properties.feature_kind ?? feature.properties.role ?? '');
          const buildingId = String(feature.properties.building_id ?? feature.id ?? '');
          const selected = buildingId === selectedBuildingId;
          const isHighlighted = highlightBuildingIds.includes(buildingId);
          const roadStyle = proposalRoadStyle(proposalRoadMetadata(feature.properties, feature.id));
          const color = kind.includes('road')
            ? roadStyle.color
            : kind.includes('open_space')
            ? '#21463f'
            : kind.includes('parcel')
            ? '#29364a'
            : isHighlighted
            ? '#f59e0b'
            : selected
            ? '#50d5b5'
            : '#66829a';
          const line = kind.includes('road') && feature.geometry.type.includes('LineString');
          return (
            <path
              key={`${feature.id ?? kind}-${index}`}
              d={featurePath(feature, bounds)}
              fill={line ? 'none' : color}
              fillOpacity={kind === 'building_floor' || kind === 'building' ? (isHighlighted ? 0.95 : 0.82) : 0.5}
              stroke={isHighlighted ? '#fbbf24' : color}
              strokeWidth={line ? 3 : isHighlighted ? 3 : 1}
              strokeDasharray={line ? roadStyle.dash.join(" ") : undefined}
              data-road-modes={line ? proposalRoadMetadata(feature.properties, feature.id).modes.join(",") : undefined}
              data-highlighted={isHighlighted ? 'true' : undefined}
              data-building-id={buildingId || undefined}
              role={kind === 'building' || kind === 'building_floor' ? 'button' : undefined}
              tabIndex={kind === 'building' || kind === 'building_floor' ? 0 : undefined}
              aria-label={kind.includes('building') ? `Select building ${buildingId}` : undefined}
              onClick={kind.includes('building') ? () => onSelectBuilding(buildingId) : undefined}
              onKeyDown={kind.includes('building') ? (event) => {
                if (event.key === 'Enter' || event.key === ' ') onSelectBuilding(buildingId);
              } : undefined}
            />
          );
        })}
        {syntaxContext?.segments.map(segment => <path key={`syntax-${segment.id}`} data-testid="refine-syntax-road"
          d={featurePath({ type: 'Feature', geometry: { type: 'LineString', coordinates: segment.coordinates }, properties: {} }, bounds)}
          fill="none" stroke={classifyContextValue(syntaxContext, syntaxContext.comparison_metric ?? 'nain', segment[syntaxContext.comparison_metric ?? 'nain']).strokeColor} strokeWidth={3}
          strokeDasharray={classifyContextValue(syntaxContext, syntaxContext.comparison_metric ?? 'nain', segment[syntaxContext.comparison_metric ?? 'nain']).lineDash.join(' ')} />)}
        {dragPreview?.candidates.map((candidate) => {
          const [x, y] = projectToSvg([candidate.x_m, candidate.y_m], bounds);
          return candidate.kind === 'ENDPOINT'
            ? <circle key={`snap-${candidate.kind}-${candidate.target_id}`} className="scenario-snap-endpoint" cx={x} cy={y} r="9" aria-hidden="true" />
            : <rect key={`snap-${candidate.kind}-${candidate.target_id}`} className="scenario-snap-nearest" x={x - 6} y={y - 6} width="12" height="12" transform={`rotate(45 ${x} ${y})`} aria-hidden="true" />;
        })}
        {roadGraph.nodes.map((node) => {
          const isDragging = dragPreview?.nodeId === node.node_id;
          const point = isDragging && dragPreview ? [dragPreview.x_m, dragPreview.y_m] : [node.x_m, node.y_m];
          const [x, y] = projectToSvg(point, bounds);
          const locked = isRoadNodeLocked(roadGraph, node.node_id);
          return (
            <circle
              key={node.node_id}
              className={`scenario-road-node${locked ? ' is-locked' : ''}${isDragging ? ' is-dragging' : ''}`}
              cx={x}
              cy={y}
              r="5"
              role="button"
              tabIndex={locked || disabled ? -1 : 0}
              aria-disabled={locked || disabled}
              aria-label={`Road node ${node.node_id}${locked ? ' · locked' : ' · draggable'}`}
              onPointerDown={(event) => {
                if (locked || disabled || (detail.editor.road_snap_tolerance_m ?? 0) <= 0) return;
                event.preventDefault();
                dragRef.current = { nodeId: node.node_id, startX: node.x_m, startY: node.y_m };
                if (Number.isInteger(event.pointerId) && typeof event.currentTarget.setPointerCapture === 'function') {
                  event.currentTarget.setPointerCapture(event.pointerId);
                }
              }}
            />
          );
        })}
        {dragPreview && (
          <circle
            className={`scenario-road-preview${bestPreviewCandidate ? ` snap-${bestPreviewCandidate.kind.toLowerCase()}` : ''}`}
            cx={projectToSvg([bestPreviewCandidate?.x_m ?? dragPreview.x_m, bestPreviewCandidate?.y_m ?? dragPreview.y_m], bounds)[0]}
            cy={projectToSvg([bestPreviewCandidate?.x_m ?? dragPreview.x_m, bestPreviewCandidate?.y_m ?? dragPreview.y_m], bounds)[1]}
            r="7"
            aria-hidden="true"
          />
        )}
        <text x="18" y="24" fill="#a9bdcf" fontSize="12">{t("EPSG:28992 ·")} {getStatusLabel(detail.provenance, language).label}</text>
      </svg>
      {dragPreview && (
        <p className="scenario-road-snap-preview" role="status">{t("Snap candidates:")}{dragPreview.candidates.length === 0 ? t("None") : dragPreview.candidates.map((candidate) =>
            `${candidate.kind === 'ENDPOINT' ? t("Endpoint") : t("Nearest point")} ${candidate.target_id}（${candidate.distance_m.toFixed(2)} m）`,
          ).join('；')}
          {bestPreviewCandidate && `${t('Expected snap:')} ${bestPreviewCandidate.kind === 'ENDPOINT' ? t("Endpoint snap") : t("Nearest-point snap")}`}
        </p>
      )}
    </div>
  );
}

function initialDashboard(detail: ScenarioDetail, building: EditableBuilding | undefined) {
  const floors = building?.floors ?? [];
  const gfa = floors.reduce((total, floor) => total + polygonArea(floor.geometry), 0);
  const height = building
    ? building.first_floor_height_m + Math.max(0, floors.length - 1) * building.standard_floor_height_m
    : null;
  const siteArea = detail.editor.design_area_m2;
  const far = detail.metrics.far?.value ?? null;
  const coverage = detail.metrics.coverage_ratio?.value ?? null;
  const limits = detail.editor.limits;
  return {
    selected: { floorCount: floors.length, gfa, height },
    site: {
      far,
      coverage,
      farLimit: limits.far_upper_bound,
      farRemaining: limits.far_upper_bound == null || far == null ? null : limits.far_upper_bound - far,
      coverageLimit: limits.max_coverage_ratio,
      coverageRemaining: limits.max_coverage_ratio == null || coverage == null ? null : limits.max_coverage_ratio - coverage,
      heightLimit: limits.max_height_m,
      area: siteArea,
    },
  };
}

export const ScenarioStudio: React.FC<{
  apiBase: string;
  scenarioId?: string;
  shellViewMode?: '2D' | '3D' | 'SPLIT' | 'COMPARE';
  highlightBuildingIds?: string[];
}> = ({ apiBase, scenarioId, shellViewMode, highlightBuildingIds: propHighlightBuildingIds }) => {
  const t = useT();
  const { language } = useI18n();
  const [eventHighlightIds, setEventHighlightIds] = useState<string[]>([]);
  useEffect(() => {
    const handler = (event: Event) => {
      const customEvent = event as CustomEvent<string[]>;
      if (Array.isArray(customEvent.detail)) {
        setEventHighlightIds(customEvent.detail);
      }
    };
    window.addEventListener('ariadne:highlight_buildings', handler);
    return () => window.removeEventListener('ariadne:highlight_buildings', handler);
  }, []);
  const effectiveHighlightIds = propHighlightBuildingIds ?? eventHighlightIds;
  const [activeTab, setActiveTab] = useState<StudioTab>('editable');
  const editableTabRef = useRef<HTMLButtonElement>(null);
  const previewTabRef = useRef<HTMLButtonElement>(null);
  const inFlightLoads = useRef<Map<string, Promise<ScenarioDetail>>>(new Map());
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [detail, setDetail] = useState<ScenarioDetail | null>(null);
  const [scenarioSyntaxContext, setScenarioSyntaxContext] = useState<SyntaxContextResponse | null>(null);
  const [selectedBuildingId, setSelectedBuildingId] = useState('');
  const [checkedScenarioIds, setCheckedScenarioIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('2D');
  const [previewLabel, setPreviewLabel] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [moveX, setMoveX] = useState('1');
  const [moveY, setMoveY] = useState('0');
  const [loading, setLoading] = useState(false);

  const loadScenarios = useCallback(async () => {
    const response = await fetch(`${apiBase}/api/v1/scenarios`);
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `Scenario list failed (HTTP ${response.status}).`);
    setScenarios((result?.scenarios ?? []) as ScenarioSummary[]);
  }, [apiBase]);

  const loadDetail = useCallback(async (scenarioId: string) => {
    if (inFlightLoads.current.has(scenarioId)) {
      return inFlightLoads.current.get(scenarioId)!;
    }
    const loadPromise = (async () => {
      const opensHarbourDraft = scenarioId === 'formal-fabric-harbour-grain-88445febe1b6';
      const response = opensHarbourDraft
        ? await fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(scenarioId)}/formal-draft`, { method: 'POST' })
        : await fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(scenarioId)}`);
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `Scenario load failed (HTTP ${response.status}).`);
      let next = result as ScenarioDetail;
      if (next.status.toLowerCase() === 'accepted' && next.provenance !== 'FIXTURE_ONLY' && next.editor.editable_buildings.length === 0) {
        try {
          const openedResponse = await fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(scenarioId)}/formal-draft`, { method: 'POST' });
          const opened = await openedResponse.json().catch(() => null);
          if (openedResponse.ok && opened) {
            next = opened as ScenarioDetail;
          } else {
            const listResp = await fetch(`${apiBase}/api/v1/scenarios`).catch(() => null);
            const listData = listResp?.ok ? await listResp.json().catch(() => null) : null;
            const matched = (listData?.scenarios ?? []).find((s: any) =>
              s.scenario_id === `formal-draft-${scenarioId}` || s.parent_scenario_id === scenarioId || s.scenario_id.startsWith(`formal-draft-${scenarioId}`)
            );
            if (matched) {
              const draftResp = await fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(matched.scenario_id)}`);
              if (draftResp.ok) {
                next = (await draftResp.json()) as ScenarioDetail;
              }
            } else {
              throw new Error(typeof opened?.detail === 'string' ? opened.detail : `Formal draft failed (HTTP ${openedResponse.status}).`);
            }
          }
        } catch (fetchErr) {
          const listResp = await fetch(`${apiBase}/api/v1/scenarios`).catch(() => null);
          const listData = listResp?.ok ? await listResp.json().catch(() => null) : null;
          const matched = (listData?.scenarios ?? []).find((s: any) =>
            s.scenario_id === `formal-draft-${scenarioId}` || s.parent_scenario_id === scenarioId || s.scenario_id.startsWith(`formal-draft-${scenarioId}`)
          );
          if (matched) {
            const draftResp = await fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(matched.scenario_id)}`);
            if (draftResp.ok) {
              next = (await draftResp.json()) as ScenarioDetail;
            }
          } else {
            throw fetchErr;
          }
        }
      }
      setDetail(next);
      setSelectedBuildingId((current) => current && next.editor.editable_buildings.some((building) => building.building_id === current)
        ? current
        : next.editor.editable_buildings[0]?.building_id ?? '');
      return next;
    })();

    inFlightLoads.current.set(scenarioId, loadPromise);
    try {
      return await loadPromise;
    } finally {
      inFlightLoads.current.delete(scenarioId);
    }
  }, [apiBase]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    loadScenarios()
      .catch((caught: unknown) => { if (!cancelled) setError(caught instanceof Error ? caught.message : t("Scenario list unavailable.")); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [loadScenarios]);

  useEffect(() => { if (scenarioId) void loadDetail(scenarioId).catch((caught: unknown) => setError(caught instanceof Error ? caught.message : t("Scenario unavailable."))); }, [scenarioId, loadDetail]);
  useEffect(() => { if (shellViewMode) setViewMode(shellViewMode); }, [shellViewMode]);

  const selectScenario = async (scenarioId: string) => {
    setError(null);
    setMessage(null);
    setComparison(null);
    try {
      await loadDetail(scenarioId);

    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Scenario unavailable."));
    }
  };

  const createFixture = async () => {
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(`${apiBase}/api/v1/scenarios/fixtures`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fixture_id: 'synthetic-rectangle-v1', seed: 1 }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `Synthetic generation failed (HTTP ${response.status}).`);
      await loadScenarios();
      const first = (result?.scenarios as ScenarioSummary[] | undefined)?.[0];
      if (first) await loadDetail(first.scenario_id);
      setMessage(t("Synthetic candidates saved for interface verification; designer adoption is pending."));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Synthetic scenario creation failed."));
    } finally {
      setLoading(false);
    }
  };

  const activeBuildings = detail?.editor.active_buildings ?? {};
  const editableBuildings = useMemo(() => detail?.editor.editable_buildings.map((base) => activeBuildings[base.building_id] ?? base) ?? [], [activeBuildings, detail]);
  const selectedBuilding = editableBuildings.find((building) => building.building_id === selectedBuildingId);

  const submitEdit = useCallback(async (buildingId: string, command: MassingCommand) => {
    if (!detail) return;
    setPreviewLabel(null);
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(detail.scenario_id)}/edits`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          building_id: buildingId,
          command,
          expected_revision: detail.editor.active_edit_revision_id,
          idempotency_key: globalThis.crypto?.randomUUID?.() ?? `scenario-edit-${Date.now()}`,
        }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `Massing draft save failed (HTTP ${response.status}).`);
      await loadDetail(detail.scenario_id);
      await loadScenarios();
      setMessage(t("Server confirmed DRAFT revision saved. This draft cannot be accepted or used as analysis input."));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Massing draft save failed."));
    } finally {
      setLoading(false);
    }
  }, [apiBase, detail, loadDetail, loadScenarios]);

  const submitRoadNodeMove = useCallback(async (nodeId: string, x_m: number, y_m: number) => {
    if (!detail) return;
    setLoading(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(detail.scenario_id)}/road-nodes/${encodeURIComponent(nodeId)}/move`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          x_m,
          y_m,
          expected_revision: detail.editor.road_edit_revision_id ?? 0,
          idempotency_key: globalThis.crypto?.randomUUID?.() ?? `road-edit-${Date.now()}`,
        }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `Road edit failed (HTTP ${response.status}).`);
      await loadDetail(detail.scenario_id);
      await loadScenarios();
      const snapLabel = result.snap_kind === 'ENDPOINT' ? `${t('Endpoint')} ${result.snapped_to_node_id}`
        : result.snap_kind === 'NEAREST_POINT' ? `${t('Nearest point')} ${result.snapped_to_edge_id}` : t("Not snapped");
      const staleIds = Array.isArray(result.stale_syntax_result_ids) ? result.stale_syntax_result_ids.join('、') : '';
      setMessage(`${t('Road-node DRAFT revision')} ${result.revision_id} ${t('saved.')} ${snapLabel}; ${t('Validation')} ${result.validation?.status ?? 'UNKNOWN'}. Graph hash ${result.graph_hash_before} → ${result.graph_hash_after}. ${staleIds ? t('Dependent Syntax {ids} marked STALE.', { ids: staleIds }) : t("No dependent Syntax results.")}`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Road-node edit failed."));
    } finally {
      setLoading(false);
    }
  }, [apiBase, detail, loadDetail, loadScenarios]);

  const movePointer = async (direction: 'undo' | 'redo') => {
    if (!detail) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(detail.scenario_id)}/edits/${direction}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expected_revision: detail.editor.active_edit_revision_id }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `${direction} failed (HTTP ${response.status}).`);
      await loadDetail(detail.scenario_id);
      setMessage(direction === 'undo' ? t("Moved to previous DRAFT revision.") : t("Moved to next DRAFT revision."));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Revision pointer move failed."));
    } finally {
      setLoading(false);
    }
  };

  const submitComparison = async () => {
    setError(null);
    setComparison(null);
    try {
      const response = await fetch(`${apiBase}/api/v1/scenarios/comparison`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_ids: checkedScenarioIds }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `Comparison failed (HTTP ${response.status}).`);
      setComparison(result as Comparison);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("Comparison unavailable."));
    }
  };

  const toggleComparisonScenario = (scenarioId: string) => {
    setCheckedScenarioIds((current) => current.includes(scenarioId)
      ? current.filter((item) => item !== scenarioId)
      : [...current, scenarioId]);
  };

  const onDragEdit = useCallback((buildingId: string, command: MassingCommand) => submitEdit(buildingId, command), [submitEdit]);
  const onStudioTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    let nextTab: StudioTab | null = null;
    if (event.key === 'ArrowRight') nextTab = activeTab === 'editable' ? 'previews' : 'editable';
    if (event.key === 'ArrowLeft') nextTab = activeTab === 'editable' ? 'previews' : 'editable';
    if (event.key === 'Home') nextTab = 'editable';
    if (event.key === 'End') nextTab = 'previews';
    if (!nextTab) return;
    event.preventDefault();
    setActiveTab(nextTab);
    (nextTab === 'editable' ? editableTabRef : previewTabRef).current?.focus();
  };
  const dashboard = detail && selectedBuilding ? initialDashboard(detail, selectedBuilding) : null;
  const topFloor = selectedBuilding?.floors.slice().sort((left, right) => right.level - left.level)[0];

  const isHistoricalScenario = (s: ScenarioSummary) => {
    const id = s.scenario_id.toLowerCase();
    const st = (s.strategy_label || '').toLowerCase();
    return id.includes('common-') || id.includes('grid-') || id.includes('spine-') ||
           id.includes('formal-dict-') ||
           st.includes('common') || st.includes('grid') || st.includes('spine');
  };

  const isHarbourScenario = (s: ScenarioSummary) => {
    const id = s.scenario_id.toLowerCase();
    return id === 'formal-fabric-harbour-grain-88445febe1b6' || id.includes('harbour-grain') || id.includes('harbour_grain');
  };

  const mainlineScenarios = scenarios.filter(s => !isHistoricalScenario(s)).sort((a, b) => {
    const aHarbour = isHarbourScenario(a) || a.status.toLowerCase() === 'accepted';
    const bHarbour = isHarbourScenario(b) || b.status.toLowerCase() === 'accepted';
    if (aHarbour && !bHarbour) return -1;
    if (!aHarbour && bHarbour) return 1;
    return 0;
  });

  const historicalScenarios = scenarios.filter(isHistoricalScenario);

  const renderScenarioCard = (scenario: ScenarioSummary) => {
    const isHarbour = isHarbourScenario(scenario);
    const isSelected = detail?.scenario_id === scenario.scenario_id;
    return (
      <article key={scenario.scenario_id} className={`scenario-card ${isSelected ? 'is-selected' : ''}`} data-testid={`scenario-card-${scenario.scenario_id}`}>
        <button type="button" className="scenario-card-open" onClick={() => void selectScenario(scenario.scenario_id)} aria-label={t('Inspect {label}', { label: t(scenario.strategy_label) })}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '4px' }}>
            <strong>{t(scenario.strategy_label)}</strong>
            {isHarbour && (
              <span className="status-badge--selected" style={{ fontSize: '10px', padding: '1px 5px', borderRadius: '3px' }}>
                {language === 'zh-TW' ? '選定' : 'Selected'}
              </span>
            )}
          </div>
          <span>
            <StatusBadge status={scenario.status} language={language} selected={isHarbour} /> · <StatusBadge status={scenario.provenance} language={language} />
          </span>
          <small>{scenario.valid ? t("Validation passed") : t('Candidate failed: {reason}', { reason: scenario.failure_reasons.map(reason => t(reason)).join('; ') || t('Reason unknown') })}</small>
        </button>
        <label className="scenario-compare-check">
          <input type="checkbox" checked={checkedScenarioIds.includes(scenario.scenario_id)} onChange={() => toggleComparisonScenario(scenario.scenario_id)} />{t("Compare")}</label>
      </article>
    );
  };

  return (
    <section className="scenario-studio" aria-label={t("Scenario viewing, comparison and editing")}>
      <header className="scenario-studio-header">
        <div>
          <h1>{activeTab === 'editable' ? t("Scenario studio") : t("Existing exploratory previews")}</h1>
          <p>
            {activeTab === 'editable'
              ? (language === 'zh-TW'
                  ? '候選方案以合成輸入示範；為測試資料狀態，非正式方案。'
                  : 'Candidates demonstrate synthetic inputs; test fixture status, not formal scenarios.')
              : t("Existing morphology outputs are read-only unapproved previews, unavailable as formal analysis inputs.")}
          </p>
        </div>
        <div className="scenario-header-controls">
          <nav className="scenario-studio-tabs" role="tablist" aria-label={t("Scenario studio tabs")} aria-orientation="horizontal">
            <button
              ref={editableTabRef}
              id="scenario-studio-tab-editable"
              type="button"
              role="tab"
              aria-controls="scenario-studio-panel-editable"
              aria-selected={activeTab === 'editable'}
              tabIndex={activeTab === 'editable' ? 0 : -1}
              onKeyDown={onStudioTabKeyDown}
              className={`scenario-studio-tab ${activeTab === 'editable' ? 'is-active' : ''}`}
              onClick={() => setActiveTab('editable')}
            >{t("Editable scenarios")}</button>
            <button
              ref={previewTabRef}
              id="scenario-studio-tab-previews"
              type="button"
              role="tab"
              aria-controls="scenario-studio-panel-previews"
              aria-selected={activeTab === 'previews'}
              tabIndex={activeTab === 'previews' ? 0 : -1}
              onKeyDown={onStudioTabKeyDown}
              className={`scenario-studio-tab ${activeTab === 'previews' ? 'is-active' : ''}`}
              onClick={() => setActiveTab('previews')}
            >{t("Existing exploratory previews")}</button>
          </nav>
          {activeTab === 'editable' && (
            <button type="button" className="scenario-primary-button" onClick={createFixture} disabled={loading}>
              {loading ? t("Working…") : t("Create synthetic candidates")}
            </button>
          )}
        </div>
      </header>

      {activeTab === 'editable' ? (
        <div
          id="scenario-studio-panel-editable"
          className="scenario-studio-body"
          role="tabpanel"
          aria-labelledby="scenario-studio-tab-editable"
          tabIndex={0}
        >
        <aside className="scenario-catalog" aria-label={t("Scenario list and comparison selection")}>
          <div className="scenario-section-heading">
            <h2>{t("Saved scenarios")}</h2>
            <span>{scenarios.length}</span>
          </div>
          {loading && scenarios.length === 0 && <p className="scenario-muted">{t("Loading scenarios…")}</p>}
          {mainlineScenarios.map(renderScenarioCard)}
          {historicalScenarios.length > 0 && (
            <details className="scenario-catalog-historical" data-testid="scenario-catalog-historical" style={{ marginTop: '12px', borderTop: '1px solid var(--border-subtle, #334155)', paddingTop: '8px' }}>
              <summary style={{ cursor: 'pointer', padding: '6px 8px', fontSize: '12px', color: '#94a3b8', fontWeight: 600 }}>
                {language === 'zh-TW' ? '歷史方案' : 'Historical scenarios'} ({historicalScenarios.length})
              </summary>
              <div style={{ marginTop: '8px' }}>
                {historicalScenarios.map(renderScenarioCard)}
              </div>
            </details>
          )}
          {scenarios.length === 0 && !loading && <p className="scenario-muted">{t("No scenarios yet. Create synthetic candidates to inspect and compare.")}</p>}
          <button type="button" className="scenario-secondary-button" disabled={checkedScenarioIds.length < 2} onClick={() => void submitComparison()}>{t("Compare selected scenarios (")}{checkedScenarioIds.length})
          </button>
        </aside>

        <div className="scenario-workspace">
          {error && <p className="scenario-message is-error" role="alert">{t(error)}</p>}
          {message && <p className="scenario-message" role="status">{t(message)}</p>}
          {comparison && (
            <section className="scenario-comparison" aria-label={t("Scenario comparison table")}>
              <div className="scenario-section-heading">
                <h2>{t("Scenario comparison")}</h2>
                <span className={comparison.status === 'COMPARABLE' ? 'status-good' : 'status-warning'}>{comparison.status === 'COMPARABLE' ? t("Matching denominators and rules") : t("Not comparable: denominators or rule versions differ")}</span>
              </div>
              <div className="scenario-table-scroll">
                <table>
                  <thead><tr><th>{t("Metric")}</th><th>{t("Unit")}</th>{comparison.scenario_ids.map((id) => <th key={id}>{id}</th>)}</tr></thead>
                  <tbody>{comparison.metrics.map((metric) => (
                    <tr key={metric.metric_id}>
                      <th scope="row">{t(metric.label)}<small>{metric.method ?? t("Method versions differ")}</small><small>{metric.data_gaps.join('；') || t("No data gaps recorded")}</small></th>
                      <td>{metric.unit}<small><StatusBadge status={metric.status} language={language} /></small></td>
                      {comparison.scenario_ids.map((id) => <td key={id}>{formatValue(metric.values[id])}{metric.metric_id === 'far' && <small>{t("Denominator")}: {metric.denominators?.[id]?.label === 'land_area' ? t("Land area (excluding water)") : metric.denominators?.[id]?.label === 'exploration_design_area' ? t("Exploration Design Area") : 'legacy/unspecified'} · {formatValue(metric.denominators?.[id]?.area_m2)} m²</small>}<small><StatusBadge status={metric.validation_status[id] ?? 'UNKNOWN'} language={language} /></small></td>)}
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </section>
          )}

          {detail ? (
            <>
              <section className="scenario-detail-heading">
                <div>
                  <h2>{t(detail.strategy_label)}</h2>
                  <p>{detail.scenario_id} · <StatusBadge status={detail.status} language={language} /> · <StatusBadge status={detail.provenance} language={language} /> {t("· EPSG:28992")}</p>
                </div>
                <span className={detail.valid ? 'scenario-valid' : 'scenario-invalid'}>{detail.valid ? t("Validation passed") : t("Invalid candidate retained")}</span>
              </section>
              <p className="scenario-explanation"><strong>{t(detail.strategy_explanation_status)}</strong>　{t(detail.strategy_explanation)}</p>
              {detail.failure_reasons.length > 0 && <p className="scenario-failure">{t("Failure reasons:")}{detail.failure_reasons.join('；')}</p>}

              <div className="scenario-view-switch" role="group" aria-label={t("Scenario view mode")}>
                <button type="button" aria-pressed={viewMode === '2D'} onClick={() => setViewMode('2D')}>{t("2D")}</button>
                <button type="button" aria-pressed={viewMode === '3D'} onClick={() => setViewMode('3D')}>{t("3D")}</button>
                <label>{t("Select building")}<select aria-label={t("Select building")} value={selectedBuildingId} onChange={(event) => setSelectedBuildingId(event.target.value)}>
                    {editableBuildings.map((building) => <option value={building.building_id} key={building.building_id}>{building.building_id}</option>)}
                  </select>
                </label>
              </div>

              {detail.provenance === 'FORMAL_DRAFT'
                ? <p className="scenario-syntax-draft-note" role="status">{t('Space Syntax is computed after the draft is proposed.')}</p>
                : <ScenarioSyntaxControls apiBase={apiBase} scenarioId={detail.scenario_id} revision={detail.revision} onContext={setScenarioSyntaxContext} />}
              <div className="scenario-viewer">
                {(viewMode === '2D' || viewMode === 'SPLIT' || viewMode === 'COMPARE') && (
                  <ScenarioMap
                    detail={detail}
                    selectedBuildingId={selectedBuildingId}
                    highlightBuildingIds={effectiveHighlightIds}
                    onSelectBuilding={setSelectedBuildingId}
                    onRoadNodeMove={submitRoadNodeMove}
                    disabled={loading}
                    syntaxContext={scenarioSyntaxContext}
                  />
                )}
                {(viewMode === '3D' || viewMode === 'SPLIT') && <ScenarioModel3D roadFeatures={detail.geometry.features} syntaxContext={scenarioSyntaxContext} buildings={editableBuildings.map(b => ({ ...b, facade_segments: detail.geometry.features.find(f => String(f.properties.building_id ?? f.id) === b.building_id)?.properties.facade_segments, active_frontage: Boolean(detail.geometry.features.find(f => String(f.properties.building_id ?? f.id) === b.building_id)?.properties.active_frontage ?? b.active_frontage) }))} selectedBuildingId={selectedBuildingId} onSelectBuilding={setSelectedBuildingId} onPreview={setPreviewLabel} onEdit={onDragEdit} />}
                {previewLabel && <div className="scenario-preview-badge" role="status">{previewLabel}</div>}
              </div>

              <section className="scenario-road-status" aria-label={t("Road-node edit status")}>
                <div className="scenario-section-heading"><h2>{t("Road nodes")}</h2><span>{t('DRAFT revision')}{' '}{detail.editor.road_edit_revision_id ?? 0}</span></div>
                <p>{t("Snap tolerance:")}{formatValue(detail.editor.road_snap_tolerance_m)}{t('m · Policy')}{detail.editor.road_edit_policy_version ?? t("Not provided")}</p>
                <p>{t("Graph hash：")}<code>{detail.editor.road_graph?.graph_hash || t("Unavailable")}</code></p>
                <div className="scenario-syntax-statuses" aria-label={t("Dependent Syntax status")}>
                  {(detail.editor.syntax_result_ids ?? []).map((resultId) => {
                    const status = detail.editor.syntax_statuses?.[resultId] ?? 'UNKNOWN';
                    return <span className={status === 'STALE' ? 'is-stale' : undefined} key={resultId}>{resultId} · {status}</span>;
                  })}
                  {(detail.editor.accessibility_result_ids ?? []).map((resultId) => {
                    const status = detail.editor.accessibility_statuses?.[resultId] ?? 'UNKNOWN';
                    return <span className={status === 'STALE' ? 'is-stale' : undefined} key={resultId}>{resultId} · {status}</span>;
                  })}
                  {(detail.editor.e1_result_ids ?? []).map((resultId) => {
                    const status = detail.editor.e1_statuses?.[resultId] ?? 'UNKNOWN';
                    return <span className={status === 'STALE' ? 'is-stale' : undefined} key={resultId}>{resultId} · {status}</span>;
                  })}
                  {(detail.editor.syntax_result_ids ?? []).length === 0 && <span>{t("No dependent Syntax results")}</span>}
                </div>
                <p className="scenario-editor-note">{t("Drag unlocked nodes in EPSG:28992 ground metres. On release, the server snaps and validates topology; Syntax is not automatically recalculated.")}</p>
              </section>

              <section className="scenario-editor-tools" aria-label={t("Massing editing tools")}>
                <div className="scenario-section-heading"><h2>{t("Massing editing")}</h2><span>{t('DRAFT revision')}{' '}{detail.editor.active_edit_revision_id}</span></div>
                <div className="scenario-edit-buttons">
                  <button type="button" disabled={!selectedBuilding || loading} onClick={() => selectedBuilding && void submitEdit(selectedBuilding.building_id, { type: 'add_floor', new_floor_id: `${selectedBuilding.building_id}-floor-${Math.max(-1, ...selectedBuilding.floors.map((floor) => floor.level)) + 2}` })}>{t("Add one floor")}</button>
                  <button type="button" disabled={!selectedBuilding || !topFloor || selectedBuilding.floors.length <= 1 || loading} onClick={() => selectedBuilding && topFloor && void submitEdit(selectedBuilding.building_id, { type: 'remove_floor', floor_id: topFloor.floor_id })}>{t("Remove top floor")}</button>
                  <button type="button" disabled={!selectedBuilding || loading} onClick={() => selectedBuilding && void submitEdit(selectedBuilding.building_id, oneMetreMove(1, 0))}>{t("Move +1 m")}</button>
                  <label>{language === 'zh-TW' ? '東西位移 dx（公尺）' : 'Move dx (metres)'}<input type="number" step="1" value={moveX} onChange={event => setMoveX(event.target.value)} /></label>
                  <label>{language === 'zh-TW' ? '南北位移 dy（公尺）' : 'Move dy (metres)'}<input type="number" step="1" value={moveY} onChange={event => setMoveY(event.target.value)} /></label>
                  <button type="button" disabled={!selectedBuilding || loading || !moveX.trim() || !moveY.trim() || !Number.isSafeInteger(Number(moveX)) || !Number.isSafeInteger(Number(moveY)) || (Number(moveX) === 0 && Number(moveY) === 0)} onClick={() => selectedBuilding && void submitEdit(selectedBuilding.building_id, oneMetreMove(Number(moveX), Number(moveY)))}>{language === 'zh-TW' ? '套用位移' : 'Apply move'}</button>
                  <button type="button" disabled={!selectedBuilding || loading} onClick={() => selectedBuilding && void submitEdit(selectedBuilding.building_id, rotationStep(15))}>{t("Rotate +15°")}</button>
                  <button type="button" disabled={detail.editor.active_edit_revision_id === 0 || loading} onClick={() => void movePointer('undo')}>{t("Undo")}</button>
                  <button type="button" disabled={loading} onClick={() => void movePointer('redo')}>{t("Redo")}</button>
                </div>
                <p className="scenario-editor-note">{t("Preserved buildings are locked; coordinates retain original precision. Invalid drafts remain visible with reasons and cannot be accepted or analyzed.")}</p>
              </section>

              {detail.provenance === 'FORMAL_DRAFT' && <FormalRoadSnapEditor apiBase={apiBase} scenarioId={detail.scenario_id} graph={detail.editor.road_graph} revision={detail.editor.road_edit_revision_id ?? 0} locale={language} onSaved={async () => { await loadDetail(detail.scenario_id); await loadScenarios(); }} />}
              {detail.provenance === 'FORMAL_DRAFT' && selectedBuilding && <FormalFaceEditor apiBase={apiBase} scenarioId={detail.scenario_id} buildingId={selectedBuilding.building_id} scenarioRevision={detail.revision} onSaved={async () => { await loadDetail(detail.scenario_id); await loadScenarios(); }} />}
              {selectedBuilding && <MassingIntent
                intent={(detail.geometry.features.find(f => String(f.properties.building_id ?? f.id) === selectedBuilding.building_id)?.properties.design_intent ?? selectedBuilding.design_intent) as MassingIntentRecord | undefined}
                active={(detail.geometry.features.find(f => String(f.properties.building_id ?? f.id) === selectedBuilding.building_id)?.properties.active_frontage ?? selectedBuilding.active_frontage) as boolean | undefined}
                height={selectedBuilding.first_floor_height_m + Math.max(0, selectedBuilding.floors.length - 1) * selectedBuilding.standard_floor_height_m}
              />}
              {selectedBuilding && <ScenarioStudioDashboard apiBase={apiBase} scenarioId={detail.scenario_id} buildingId={selectedBuilding.building_id} scenarioRevision={detail.revision} />}
              {dashboard && (
                <section className="scenario-dashboard" aria-label={t("Massing metrics dashboard")}>
                  <div className="scenario-section-heading"><h2>{t("Massing dashboard")}</h2><span>{language === 'zh-TW' ? '本機預覽 · 不是後端測量' : 'Local preview · not server measurements'}</span></div>
                  <div className="scenario-dashboard-grid">
                    <article><h3>{t("Selected building")}</h3><dl><dt>{t("Floors")}</dt><dd>{dashboard.selected.floorCount}</dd><dt>{t("Height")}</dt><dd>{formatValue(dashboard.selected.height)}{t("m")}</dd><dt>{t("GFA")}</dt><dd>{formatValue(dashboard.selected.gfa)}{t("m²")}</dd></dl></article>
                    <article><h3>{t("Site total")}</h3><dl><dt>{t("FAR")}</dt><dd>{formatValue(dashboard.site.far)} <small>legacy/unspecified · {formatValue(detail?.editor.design_area_m2)} m²</small><small>{t("Limit")}{formatValue(dashboard.site.farLimit)}{t('· Remaining')}{formatValue(dashboard.site.farRemaining)}</small></dd><dt>{t("Coverage")}</dt><dd>{formatValue(dashboard.site.coverage)} <small>{t("Limit")}{formatValue(dashboard.site.coverageLimit)}{t('· Remaining')}{formatValue(dashboard.site.coverageRemaining)}</small></dd><dt>{t("Height limit")}</dt><dd>{formatValue(dashboard.site.heightLimit)}{t("m")}</dd></dl></article>
                    <article><h3>{t("Zones")}</h3><p>{t("Synthetic zone boundaries unavailable; zone FAR and coverage have not been evaluated.")}</p></article>
                  </div>
                </section>
              )}
            </>
          ) : (
            <div className="scenario-empty-state"><h2>{t("No scenario selected")}</h2><p>{t("Open a scenario from the list or create synthetic candidates to view 2D/3D, edit massing and inspect metrics.")}</p></div>
          )}
        </div>
      </div>
      ) : (
        <div
          id="scenario-studio-panel-previews"
          className="scenario-preview-tab-wrapper"
          role="tabpanel"
          aria-labelledby="scenario-studio-tab-previews"
          tabIndex={0}
        >
          <MorphologyPreviewCatalog apiBase={apiBase} />
        </div>
      )}
    </section>
  );
};
