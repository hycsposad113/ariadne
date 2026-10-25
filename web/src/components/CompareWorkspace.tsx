import { currentFormalProposals } from '../utils/currentFormalGenerator';
import { proposalRoadMetadata } from '../utils/proposalRoads';
import { ScenarioSyntaxControls, ProposalRoadLegend } from './ScenarioSyntaxControls';
import type { SyntaxContextResponse } from '../utils/syntaxContext';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useI18n, useT } from '../i18n';
import type { Building, Segment, SyntaxLayer, SpatialZone } from '../types';
import type { PreviewGeoJson, PreviewItem } from './MorphologyPreviewCatalog';
import { ScenarioStudio } from './ScenarioStudio';
import { HumanDecisionDialog } from './HumanDecisionDialog';
import { ScenarioComparisonDialog } from './ScenarioComparisonDialog';
import { Viewport2D } from './Viewport2D';
import { Viewport3D } from './Viewport3D';
import type { Viewport3DCameraState, Viewport3DSyntaxLegendEntry } from './Viewport3D';
import './CompareWorkspace.css';
import { FABRIC_IDS, FabricCompare, type FabricSelection } from './FabricCompare';
import { StatusBadge, getStatusLabel } from '../i18n/statusLabels';

type Mode = '2D' | '3D' | 'SPLIT' | 'COMPARE';
type ScenarioArea = { id: string; geometry: { type: string; coordinates: unknown }; kind: string };
type PreviewFeature = PreviewGeoJson['features'][number] & { id?: string | number };
export type FormalProposal = {
  generator_version?: string;
  revision?: number;
  id: string;
  strategy: string;
  status: string;
  metrics: Record<string, unknown>;
  geometry: PreviewGeoJson;
  rejection_reason?: string | null;
  baseline_reason?: string | null;
  geometry_sha256?: string | null;
  geometry_artifact_id?: string;
  geometry_path?: string;
};
type SchemeSelection = { id: string; label: string; status: string; preview?: PreviewItem; formal?: FormalProposal };

type CatalogResponse = {
  status: 'AVAILABLE' | 'DISABLED';
  count: number;
  previews: PreviewItem[];
};

function previewKey(preview: PreviewItem): string {
  return `${preview.identity.intensity}/${preview.identity.strategy_id}`;
}

function geometryLines(geometry: { type: string; coordinates: unknown } | null | undefined): number[][][] {
  if (!geometry) return [];
  if (geometry.type === 'LineString' && Array.isArray(geometry.coordinates)) {
    return [geometry.coordinates as number[][]];
  }
  if (geometry.type === 'MultiLineString' && Array.isArray(geometry.coordinates)) {
    return geometry.coordinates as number[][][];
  }
  return [];
}

function lineLength(lines: number[][][]): number {
  return lines.reduce((total, line) => total + line.slice(1).reduce((partial, point, index) => {
    const previous = line[index];
    if (!previous || typeof point[0] !== 'number' || typeof point[1] !== 'number') return partial;
    return partial + Math.hypot(point[0] - previous[0], point[1] - previous[1]);
  }, 0), 0);
}

function PreviewViews({
  enabled = true,
  apiBase,
  preview,
  formal,
  viewMode,
  selectedFeatureId,
  onSelectedFeatureChange,
  syntaxSegments,
  syntaxSegmentValues,
  syntaxLegend,
  activeSyntaxLayer,
  syntaxOverlayVisible,
  syntaxContextData,
  syntaxContextStatus,
  syntaxContextError,
  onSyntaxOverlayVisibilityChange,
  cameraState,
  onCameraChange,
}: {
  apiBase: string;
  enabled?: boolean;
  preview?: PreviewItem;
  formal?: FormalProposal;
  viewMode: '2D' | '3D' | 'SPLIT';
  selectedFeatureId: string | null;
  onSelectedFeatureChange: (id: string | null, type: 'building' | 'road') => void;
  syntaxSegments: Segment[];
  syntaxSegmentValues: Record<string, number>;
  syntaxLegend: Viewport3DSyntaxLegendEntry[];
  activeSyntaxLayer: SyntaxLayer | null;
  syntaxOverlayVisible: boolean;
  syntaxContextData?: SyntaxContextResponse | null;
  syntaxContextStatus?: 'idle' | 'loading' | 'success' | 'error';
  syntaxContextError?: string | null;
  onSyntaxOverlayVisibilityChange?: (visible: boolean) => void;
  cameraState?: Viewport3DCameraState;
  onCameraChange?: (state: Viewport3DCameraState) => void;
}) {
  const t = useT();
  const key = formal?.id ?? (preview ? previewKey(preview) : '');
  const [geometryState, setGeometryState] = useState<{ key: string; status: 'loading' | 'ready' | 'error'; value?: PreviewGeoJson }>({ key, status: 'loading' });

  useEffect(() => {
    if (!enabled) return;
    let current = true;
    if (formal) {
      setGeometryState({ key, status: 'ready', value: formal.geometry });
      return () => { current = false; };
    }
    if (!preview) return;
    const base = apiBase.endsWith('/') ? apiBase : `${apiBase}/`;
    fetch(new URL(preview.assets.geometry, base), { method: 'GET', headers: { Accept: 'application/geo+json, application/json' } })
      .then(async response => {
        if (!response.ok) throw new Error('Unavailable');
        return await response.json() as PreviewGeoJson;
      })
      .then(value => { if (current) setGeometryState({ key, status: 'ready', value }); })
      .catch(() => { if (current) setGeometryState({ key, status: 'error' }); });
    return () => { current = false; };
  }, [apiBase, key, preview?.assets.geometry, formal, enabled]);

  const [scenarioContext, setScenarioContext] = useState<SyntaxContextResponse | null>(null);
  const geometry = geometryState.key === key && geometryState.status === 'ready' ? geometryState.value : null;
  const scenario = useMemo(() => {
    const features = (geometry?.features ?? []) as readonly PreviewFeature[];
    const buildings: Building[] = features
      .filter(feature => feature.geometry && (['generated_building', 'preserved_building'].includes(String(feature.properties?.feature_kind)) || ['new_building', 'retained'].includes(String(feature.properties?.role))))
      .map((feature, index) => ({
        id: String(feature.properties?.building_id ?? feature.properties?.feature_id ?? feature.id ?? index),
        geometry: feature.geometry,
        properties: { ...(feature.properties ?? {}) },
        disposition: (feature.properties?.feature_kind === 'preserved_building' || feature.properties?.role === 'retained') ? 'PRESERVE' : 'EDITABLE',
      }));
    const segments: Segment[] = features
      .filter(feature => feature.geometry && (feature.properties?.feature_kind === 'road_segment' || feature.properties?.role === 'road'))
      .flatMap((feature, index) => {
        const lines = geometryLines(feature.geometry);
        if (lines.length === 0) return [];
        return [{
          id: String(feature.properties?.segment_id ?? feature.id ?? `road-${index + 1}`),
          geometry: feature.geometry as Segment['geometry'],
          length_m: lineLength(lines),
          layer: 0,
          feature_kind: 'road',
          ...proposalRoadMetadata(feature.properties ?? {}, String(feature.id ?? '')),
        }];
      });
    const areaKinds = new Set([
      'water', 'waterfront_building_no_build_band', 'preference_open_space', 'strategy_open_space',
      'residual_open_space', 'street_block', 'open_space_block', 'primary_open_space',
    ]);
    const scenarioAreas: ScenarioArea[] = features
      .filter(feature => feature.geometry && areaKinds.has(String(feature.properties?.feature_kind ?? feature.properties?.role)))
      .map((feature, index) => ({
        id: String(feature.id ?? feature.properties?.block_id ?? `scenario-area-${index + 1}`),
        geometry: feature.geometry!,
        kind: String(feature.properties?.feature_kind ?? feature.properties?.role),
      }));
    return {
      studyAreaGeometry: features.find(feature => (feature.properties?.feature_kind === 'study_area' || feature.properties?.role === 'site_area'))?.geometry ?? null,
      buildings,
      segments,
      scenarioAreas,
    };
  }, [geometry]);

  const context = useMemo(() => ({
    projectId: formal?.id ?? 'UNAPPROVED_PREVIEW',
    workspace: null,
    studyArea: null,
    hasUnsavedChanges: false,
    sourcePackageRevision: null,
    sourceSnapshotIds: [],
    buildingCount: scenario.buildings.length,
    roadCount: scenario.segments.length,
    spatialZoneCount: 0,
    selectedFeatureIds: selectedFeatureId ? [selectedFeatureId] : [],
    activeSyntaxLayer: syntaxOverlayVisible ? activeSyntaxLayer : null,
  }), [scenario.buildings.length, scenario.segments.length, selectedFeatureId, syntaxOverlayVisible, activeSyntaxLayer]);

  if (!enabled) return null;
  if (geometryState.key !== key || geometryState.status === 'loading') return <p className="compare-geometry-state" role="status">{t('Loading EPSG:28992 geometry…')}</p>;
  if (geometryState.status === 'error' || !geometry) return <p className="compare-geometry-state" role="alert">{t('Geometry preview unavailable.')}</p>;

  const displayContext = formal ? scenarioContext : syntaxContextData;
  const displayStatus = formal ? (scenarioContext ? 'success' : 'idle') : syntaxContextStatus;
  const displaySyntaxSegments = formal ? [] : syntaxSegments;
  const viewport2D = viewMode !== '3D' ? (
    <div className="compare-plan" aria-label={t('2D Plan')}>
      <Viewport2D
        studyAreaGeometry={scenario.studyAreaGeometry}
        buildings={scenario.buildings}
        segments={scenario.segments}
        scenarioAreas={scenario.scenarioAreas}
        syntaxSegments={displaySyntaxSegments}
        syntaxLegend={syntaxLegend}
        activeSyntaxLayer={syntaxOverlayVisible && !formal ? activeSyntaxLayer : null}
        spatialZones={[] as SpatialZone[]}
        syntaxContextData={syntaxOverlayVisible ? displayContext : null}
        syntaxContextStatus={displayStatus}
        syntaxMode={displayContext?.mode}
        syntaxMetric={displayContext?.comparison_metric}
        syntaxContextError={syntaxContextError}
        selectedFeatureId={selectedFeatureId}
        onSelectFeature={onSelectedFeatureChange}
        figureContext={{ ...context, sourceAttributions: [], spatialZoneCount: 0 }}
        figureExportReady={false}
      />
    </div>
  ) : null;
  const viewport3D = viewMode === '3D' || viewMode === 'SPLIT' ? (
    <div className="compare-3d" aria-label={t('3D')}>
      <Viewport3D
        studyAreaGeometry={scenario.studyAreaGeometry}
        buildings={scenario.buildings}
        segments={scenario.segments}
        scenarioAreas={scenario.scenarioAreas}
        syntaxSegments={displaySyntaxSegments}
        syntaxSegmentValues={formal ? {} : syntaxSegmentValues}
        syntaxLegend={syntaxLegend}
        syntaxOverlayVisible={syntaxOverlayVisible}
        onSyntaxOverlayVisibilityChange={onSyntaxOverlayVisibilityChange}
        syntaxContextData={syntaxOverlayVisible ? displayContext : null}
        syntaxContextStatus={displayStatus}
        syntaxMode={displayContext?.mode}
        syntaxMetric={displayContext?.comparison_metric}
        syntaxContextError={syntaxContextError}
        selectedFeatureId={selectedFeatureId}
        onSelectFeature={onSelectedFeatureChange}
        cameraState={cameraState}
        onCameraChange={onCameraChange}
        figureContext={context}
        figureExportReady={false}
      />
    </div>
  ) : null;

  return <div className={`compare-preview-views mode-${viewMode}`}>
    {formal && formal.status.toUpperCase() !== 'DRAFT' ? <ScenarioSyntaxControls apiBase={apiBase} scenarioId={formal.id} revision={formal.geometry_sha256 ?? undefined} onContext={setScenarioContext} /> : <ProposalRoadLegend />}
    {viewport2D}{viewport3D}</div>;
}

function formatProposalReason(raw: string | undefined | null, zh: boolean): string {
  if (!raw) return '';
  if (raw.startsWith('compare ') && raw.includes(' · ')) {
    const parts = raw.split(' · ');
    const statusPart = parts[1];
    const statusLabel = getStatusLabel(statusPart, zh ? 'zh-TW' : 'en').label;
    const prefix = zh ? '比較 ' : 'Compare ';
    const core = parts[0].replace(/^compare\s+/, '').replace(/\s+ratio$/, zh ? ' 比值' : ' ratio');
    return `${prefix}${core} · ${statusLabel}`;
  }
  return raw;
}

export function CompareWorkspace({
  apiBase,
  viewMode,
  syncedViews,
  onSchemeSelection,
  onFabricSelection,
  startEditing = false,
  initialWorkspace,
  projectId = 'rotterdam-m4h-pilot-project',
  syntaxSegments = [],
  syntaxSegmentValues = {},
  syntaxLegend = [],
  activeSyntaxLayer = null,
  syntaxContextData = null,
  syntaxContextStatus = 'idle',
  syntaxContextError = null,
  syntaxOverlayVisible = true,
  onSyntaxOverlayVisibilityChange,
  boundRevision = null,
  week7Chrome,
}: {
  week7Chrome?: import('react').ReactNode;
  apiBase: string;
  viewMode: Mode;
  syncedViews: boolean;
  startEditing?: boolean;
  initialWorkspace?: 'fabric' | 'legacy';
  projectId?: string;
  syntaxSegments?: Segment[];
  syntaxSegmentValues?: Record<string, number>;
  syntaxLegend?: Viewport3DSyntaxLegendEntry[];
  activeSyntaxLayer?: SyntaxLayer | null;
  syntaxOverlayVisible?: boolean;
  syntaxContextData?: SyntaxContextResponse | null;
  syntaxContextStatus?: 'idle' | 'loading' | 'success' | 'error';
  syntaxContextError?: string | null;
  onSyntaxOverlayVisibilityChange?: (visible: boolean) => void;
  onFabricSelection?: (selection: FabricSelection | null) => void;
  onSchemeSelection?: (scheme: SchemeSelection | null) => void;
  boundRevision?: {
    fixtureOnly?: boolean;
    scenarioId: string;
    revision: string;
    far: number | null;
    unit: string;
    label: string;
  } | null;
}) {
  const t = useT();
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  const [fabricActive, setFabricActive] = useState(initialWorkspace ? initialWorkspace === 'fabric' : !startEditing);
  const [formal, setFormal] = useState<FormalProposal[]>([]);
  const [formalError, setFormalError] = useState(false);
  const [formalId, setFormalId] = useState<string | null>(null);
  const [rightFormalId, setRightFormalId] = useState<string | null>(null);
  const [isBaselineDialogOpen, setIsBaselineDialogOpen] = useState(false);
  const [reconsiderTarget, setReconsiderTarget] = useState<FormalProposal | null>(null);

  const loadFormalProposals = useCallback(() => {
    let active = true;
    const base = apiBase.replace(/\/$/, '');
    fetch(`${base}/api/v1/projects/${encodeURIComponent(projectId)}/formal-proposals`)
      .then(async response => {
        if (!response.ok) throw new Error();
        return (await response.json()) as FormalProposal[];
      })
      .then(rows => {
        if (active && Array.isArray(rows)) {
          setFormal(currentFormalProposals(rows));
          setFormalError(false);
        }
      })
      .catch(() => {
        if (active) setFormalError(true);
      });
    return () => {
      active = false;
    };
  }, [apiBase, projectId]);

  useEffect(() => {
    if (boundRevision?.fixtureOnly) return;
    return loadFormalProposals();
  }, [boundRevision?.fixtureOnly, loadFormalProposals]);
  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [catalogError, setCatalogError] = useState(false);
  const [scenarios, setScenarios] = useState<Array<{ scenario_id: string; strategy_label: string; status: string }>>([]);
  const [editableId, setEditableId] = useState<string | null>(startEditing ? '' : null);
  useEffect(() => {
    if (!boundRevision || boundRevision.fixtureOnly) return;
    const real = formal.find(row => row.id === boundRevision.scenarioId);
    if (real) { setFormalId(real.id); setEditableId(null); onSchemeSelection?.({ id: real.id, label: real.strategy, status: real.status, formal: real }); }
  }, [boundRevision?.scenarioId, formal]);
  const [selectedKey, setSelectedKey] = useState('');
  const [rightKey, setRightKey] = useState('');
  const [leftFeature, setLeftFeature] = useState<string | null>(null);
  const [rightFeature, setRightFeature] = useState<string | null>(null);
  const [sharedCameraState, setSharedCameraState] = useState<Viewport3DCameraState | undefined>();
  const [scenarioError, setScenarioError] = useState(false);

  useEffect(() => {
    if (boundRevision?.fixtureOnly) return;
    let current = true;
    fetch(`${apiBase.replace(/\/$/, '')}/api/v1/morphology/previews`, { method: 'GET', headers: { Accept: 'application/json' } })
      .then(async response => {
        if (!response.ok) throw new Error('Unavailable');
        return await response.json() as CatalogResponse;
      })
      .then(data => {
        if (!current) return;
        if (data.status === 'DISABLED') {
          setCatalog(data);
          return;
        }
        if (data.status !== 'AVAILABLE' || !Array.isArray(data.previews) || data.count !== data.previews.length) throw new Error('Incomplete catalog');
        setCatalog(data);
        const initial = data.previews.find(item => item.identity.intensity === 'A') ?? data.previews[0];
        if (initial) {
          setSelectedKey(previewKey(initial));
          setRightKey(currentRight => currentRight || previewKey(data.previews.find(item => item !== initial) ?? initial));
        }
      })
      .catch(() => { if (current) setCatalogError(true); });
    return () => { current = false; };
  }, [apiBase, boundRevision?.fixtureOnly]);

  useEffect(() => {
    if (boundRevision?.fixtureOnly) return;
    let current = true;
    fetch(`${apiBase.replace(/\/$/, '')}/api/v1/scenarios`, { method: 'GET', headers: { Accept: 'application/json' } })
      .then(async response => {
        if (!response.ok) throw new Error('Unavailable');
        return await response.json();
      })
      .then(data => { if (current) setScenarios(data.scenarios ?? []); })
      .catch(() => { if (current) setScenarioError(true); });
    return () => { current = false; };
  }, [apiBase, boundRevision?.fixtureOnly]);

  const previews = catalog?.status === 'AVAILABLE' ? catalog.previews : [];
  const selectedPreview = previews.find(item => previewKey(item) === selectedKey) ?? previews[0];
  const rightPreview = previews.find(item => previewKey(item) === rightKey && item !== selectedPreview)
    ?? previews.find(item => item !== selectedPreview);

  useEffect(() => {
    if (editableId !== null || formalId !== null) return;
    if (!selectedPreview) {
      onSchemeSelection?.(null);
      return;
    }
    onSchemeSelection?.({
      id: previewKey(selectedPreview),
      label: selectedPreview.strategy_label,
      status: selectedPreview.identity.status,
      preview: selectedPreview,
    });
  }, [editableId, formalId, onSchemeSelection, selectedPreview]);

  const choosePreview = useCallback((preview: PreviewItem) => {
    setFormalId(null);
    setSelectedKey(previewKey(preview));
    setEditableId(null);
    setLeftFeature(null);
    setRightFeature(null);
  }, []);

  const chooseRightPreview = useCallback((preview: PreviewItem) => {
    setRightKey(previewKey(preview));
    setRightFeature(null);
    onSchemeSelection?.({
      id: previewKey(preview),
      label: preview.strategy_label,
      status: preview.identity.status,
      preview,
    });
  }, [onSchemeSelection]);

  const chooseEditable = (scenario: { scenario_id: string; strategy_label: string; status: string }) => {
    setFormalId(null);
    setEditableId(scenario.scenario_id);
    onSchemeSelection?.({ id: scenario.scenario_id, label: scenario.strategy_label, status: scenario.status });
  };

  const leftSelection = (id: string | null) => setLeftFeature(id);
  const rightSelection = (id: string | null) => setRightFeature(id);
  const HARBOUR_GRAIN_FORMAL_ID = 'formal-fabric-harbour-grain-88445febe1b6';
  const harbourScenario = scenarios.find(
    s => s.scenario_id === HARBOUR_GRAIN_FORMAL_ID || (s.scenario_id.includes('harbour') && s.status.toLowerCase() === 'accepted')
  );
  const harbourFormal = formal.find(
    f => f.id === HARBOUR_GRAIN_FORMAL_ID || (f.id.includes('harbour') && f.status.toUpperCase() === 'ACCEPTED')
  );
  const rawHarbourLabel = harbourScenario?.strategy_label || harbourFormal?.strategy;
  const harbourLabel = rawHarbourLabel
    ? (rawHarbourLabel === 'harbour_grain' || rawHarbourLabel === HARBOUR_GRAIN_FORMAL_ID
        ? (zh ? '港埠線性紋理' : 'Harbour grain')
        : t(rawHarbourLabel))
    : (zh ? '港埠紋理正式方案' : 'Harbour Grain formal proposal');

  const isHistoricalProposal = (item: { id: string; strategy?: string }) => {
    const id = item.id.toLowerCase();
    const st = (item.strategy || '').toLowerCase();
    return id.includes('common-') || id.includes('grid-') || id.includes('spine-') || id.includes('formal-dict-') ||
           st.includes('common') || st.includes('grid') || st.includes('spine');
  };
  // Only the pinned formal harbour and the four fabric choices belong to the mainline.
  const historicalFormal = formal.filter(item => item.id !== HARBOUR_GRAIN_FORMAL_ID);
  const historicalScenarios = scenarios.filter(item => isHistoricalProposal({id: item.scenario_id, strategy: item.strategy_label}));
  const currentScenarios = scenarios.filter(item => !historicalScenarios.includes(item));

  const renderFormalItem = (item: FormalProposal) => {
    const st = item.status.toUpperCase();
    const isSelected = formalId === item.id;
    return (
      <button
        key={item.id}
        type="button"
        className={`compare-formal-item-btn status-${st.toLowerCase()}`}
        aria-pressed={isSelected}
        aria-label={zh ? `${item.strategy} · ${getStatusLabel(st, 'zh-TW').label}` : `${item.strategy} · ${st}`}
        onClick={() => {
          setFormalId(item.id);
          setEditableId(null);
          setLeftFeature(null);
          setRightFeature(null);
          setRightFormalId(formal.find(other => other.id !== item.id)?.id ?? null);
          onSchemeSelection?.({ id: item.id, label: item.strategy, status: item.status, formal: item });
        }}
      >
        <div className="compare-formal-item-header">
          <span style={{ fontWeight: 600 }}>{item.strategy}</span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            {st === 'ACCEPTED' && (
              <span className="status-badge--selected" style={{ fontSize: '10px', padding: '1px 5px', borderRadius: '3px' }}>
                {zh ? '選定' : 'Selected'}
              </span>
            )}
            <span
              className={`chip chip--${st === 'ACCEPTED' ? 'preserve' : st === 'REJECTED' ? 'undecided' : 'editable'}`}
              title={getStatusLabel(st, language).label}
              data-status={st}
            >
              {zh ? (st === 'ACCEPTED' ? '已採納' : st === 'REJECTED' ? '已拒絕' : '候選提案') : (st === 'ACCEPTED' ? 'Accepted' : st === 'REJECTED' ? 'Rejected' : 'Proposed')}
              <span className="sr-only" style={{ display: 'none' }}>{st}</span>
            </span>
          </span>
        </div>
        {st === 'ACCEPTED' && item.baseline_reason && (
          <div className="compare-formal-item-reason accepted-reason" title={zh ? '已採納理由' : 'Accepted reason'}>
            {zh ? '採納理由：' : 'Baseline reason: '} {formatProposalReason(item.baseline_reason, zh)}
          </div>
        )}
        {st === 'REJECTED' && item.rejection_reason && (
          <div className="compare-formal-item-reason rejection-reason" title={zh ? '已拒絕理由' : 'Rejection reason'}>
            {zh ? '拒絕理由：' : 'Rejection reason: '} {formatProposalReason(item.rejection_reason, zh)}
          </div>
        )}
      </button>
    );
  };

  const schemeList = (side: 'left' | 'right') => (
    <div className="compare-scheme-list" aria-label={zh ? '方案清單' : 'Scenario list'}>
      <section className="compare-mainline-proposals" data-testid="compare-mainline-proposals">
        <h2>{zh ? '主線方案' : 'Mainline proposals'}</h2>
        {formalError && <p role="alert">{zh ? '正式方案清單無法載入' : 'Formal proposal list unavailable'}</p>}
        {/* 1. Formal registered Harbour scheme: pinned at top, marked '選定' */}
        <div className="compare-harbour-mainline-card" data-testid="harbour-mainline-card" style={{ marginBottom: '8px' }}>
          <button
            type="button"
            className={`compare-formal-item-btn status-accepted ${editableId === HARBOUR_GRAIN_FORMAL_ID || formalId === HARBOUR_GRAIN_FORMAL_ID ? 'is-selected' : ''}`}
            data-testid="harbour-mainline-btn"
            aria-pressed={editableId === HARBOUR_GRAIN_FORMAL_ID || formalId === HARBOUR_GRAIN_FORMAL_ID}
            aria-label={zh ? `${harbourLabel} · 已採納` : `${harbourLabel} · ACCEPTED`}
            onClick={() => {
              setFabricActive(false);
              setFormalId(harbourFormal?.id ?? HARBOUR_GRAIN_FORMAL_ID);
              setEditableId(null);
              onSchemeSelection?.({
                id: harbourFormal?.id ?? HARBOUR_GRAIN_FORMAL_ID,
                label: harbourLabel,
                status: 'accepted',
                formal: harbourFormal,
              });
            }}
          >
            <div className="compare-formal-item-header">
              <span style={{ fontWeight: 600 }}>{harbourLabel}</span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <span className="status-badge--selected" style={{ fontSize: '10px', padding: '1px 5px', borderRadius: '3px' }}>
                  {zh ? '選定' : 'Selected'}
                </span>
                <span className="chip chip--preserve" title={getStatusLabel('ACCEPTED', language).label} data-status="ACCEPTED">
                  {zh ? '已採納' : 'Accepted'}
                  <span className="sr-only" style={{ display: 'none' }}>ACCEPTED</span>
                </span>
              </span>
            </div>
            <div className="compare-formal-item-reason accepted-reason" title={zh ? `正式方案 ID：${HARBOUR_GRAIN_FORMAL_ID}` : `Formal proposal ID: ${HARBOUR_GRAIN_FORMAL_ID}`}>
              {HARBOUR_GRAIN_FORMAL_ID}
            </div>
          </button>
        </div>

        {/* 2. Four fabric schemes */}
        <div className="compare-fabric-mainline-list" data-testid="fabric-mainline-list" style={{ marginTop: '8px', marginBottom: '8px' }}>
          <h3 style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#94a3b8', margin: '4px 0', fontWeight: 600 }}>
            {zh ? '四個紋理方案' : 'Four fabric schemes'}
          </h3>
          {FABRIC_IDS.map((fabricId) => (
            <button
              key={`mainline-fabric-${fabricId}`}
              type="button"
              className="compare-formal-item-btn status-exploratory"
              data-testid={`mainline-fabric-${fabricId}`}
              onClick={() => {
                setFabricActive(true);
                setFormalId(null);
                setEditableId(null);
              }}
            >
              <div className="compare-formal-item-header">
                <span style={{ fontWeight: 600 }}>{t(`fabric.${fabricId}`)}</span>
                <StatusBadge status="EXPLORATORY_DRAFT" language={language} />
              </div>
            </button>
          ))}
        </div>
      </section>

      {side === 'left' && (
        <section className="compare-editable-list" data-testid="compare-editable-list">
          <h3>{t('Editable scenarios')}</h3>
          {scenarioError && <p role="alert">{t('Scenario list unavailable.')}</p>}
          {scenarios.length === 0 && !scenarioError && <p>{t('No saved editable scenarios.')}</p>}
          {currentScenarios.map(scenario => (
            <button
              key={scenario.scenario_id}
              type="button"
              aria-pressed={editableId === scenario.scenario_id}
              onClick={() => chooseEditable(scenario)}
            >
              <span>{t(scenario.strategy_label)}</span>
              <StatusBadge status={scenario.status} language={language} />
            </button>
          ))}
          <button
            type="button"
            className="compare-open-editor-btn"
            data-testid="open-scenario-editing-btn"
            style={{
              width: '100%',
              marginTop: '4px',
              padding: '6px 12px',
              fontSize: '12px',
              cursor: 'pointer',
              borderRadius: '4px',
              background: 'var(--accent-primary, #2563eb)',
              color: '#ffffff',
              border: 'none',
              fontWeight: 500,
            }}
            onClick={() => {
              setFabricActive(false);
              const targetFormalId = formalId || (editableId && editableId !== '' ? editableId : HARBOUR_GRAIN_FORMAL_ID);
              // Resolve the accepted harbour through the server's idempotent authority endpoint.
              setEditableId(targetFormalId);
              setFormalId(null);
            }}
          >
            {t('Open scenario editing tools')}
          </button>
        </section>
      )}

      <details className="compare-historical-scenarios" data-testid="compare-historical-scenarios">
        <summary>{zh ? '歷史方案' : 'Historical scenarios'}</summary>
        {formal.length > 0 && (
          <button
            type="button"
            className="compare-select-baseline-btn"
            data-testid="select-baseline-btn"
            disabled={
              formal.filter(item => item.status.toUpperCase() === 'PROPOSED').length < 2 ||
              formal.some(item => item.status.toUpperCase() === 'ACCEPTED')
            }
            onClick={() => setIsBaselineDialogOpen(true)}
          >
            {zh ? '選定基準方案' : 'Select baseline'}
          </button>
        )}
        {formal.filter(item => ['ACCEPTED', 'REJECTED'].includes(item.status.toUpperCase())).map(item => (
          <button key={`reconsider-${item.id}`} type="button" onClick={() => setReconsiderTarget(item)}>
            {t('Reconsider')} · {item.strategy}
          </button>
        ))}

        {side === 'left' && historicalScenarios.map(scenario => (
          <button key={scenario.scenario_id} type="button" aria-pressed={editableId === scenario.scenario_id}
            onClick={() => chooseEditable(scenario)}>
            <span>{t(scenario.strategy_label)}</span><StatusBadge status={scenario.status} language={language} />
          </button>
        ))}
        {historicalFormal.length > 0 && (
          <section className="compare-historical-formal">
            <h3>{zh ? '歷史正式提案' : 'Historical formal proposals'}</h3>
            {historicalFormal.map(renderFormalItem)}
          </section>
        )}

        <h2>{t(side === 'left' ? 'Available preview scenarios' : 'Right scenario')}</h2>
        {previews.filter(item => item.identity.intensity === 'A').length > 0 && (
          <section aria-label={t('Assumption set A')}>
            <h3>{t('Assumption set {set} ({count} previews)', { set: 'A', count: previews.filter(item => item.identity.intensity === 'A').length })}</h3>
            {previews.filter(item => item.identity.intensity === 'A').map(item => (
              <button key={previewKey(item)} type="button" aria-label={t('Open {intensity}: {strategy}', { intensity: 'A', strategy: t(item.strategy_label) })} aria-pressed={side === 'left' ? selectedPreview === item : rightPreview === item}
                onClick={() => side === 'left' ? choosePreview(item) : setRightKey(previewKey(item))}>
                <span>{t(item.strategy_label)}</span><small title={getStatusLabel('UNAPPROVED_PREVIEW', language).label} data-status="UNAPPROVED_PREVIEW">{zh ? '探索草案預覽（未批准）' : 'Exploratory preview'}</small>
              </button>
            ))}
          </section>
        )}
        {previews.filter(item => item.identity.intensity === 'B').length > 0 && (
          <section aria-label={t('Assumption set B')}>
            <h3>{t('Assumption set {set} ({count} previews)', { set: 'B', count: previews.filter(item => item.identity.intensity === 'B').length })}</h3>
            {previews.filter(item => item.identity.intensity === 'B').map(item => (
              <button key={previewKey(item)} type="button" aria-label={t('Open {intensity}: {strategy}', { intensity: 'B', strategy: t(item.strategy_label) })} aria-pressed={side === 'left' ? selectedPreview === item : rightPreview === item}
                onClick={() => side === 'left' ? choosePreview(item) : setRightKey(previewKey(item))}>
                <span>{t(item.strategy_label)}</span><small title={getStatusLabel('UNAPPROVED_PREVIEW', language).label} data-status="UNAPPROVED_PREVIEW">{zh ? '探索草案預覽（未批准）' : 'Exploratory preview'}</small>
              </button>
            ))}
          </section>
        )}
      </details>
    </div>
  );

  const commonViewportProps = {
    apiBase,
    syntaxSegments,
    syntaxSegmentValues,
    syntaxLegend,
    activeSyntaxLayer,
    syntaxOverlayVisible,
  syntaxContextData,
  syntaxContextStatus,
  syntaxContextError,
    onSyntaxOverlayVisibilityChange,
  };

  return <div className={`compare-workspace ${viewMode === 'COMPARE' ? 'is-compare-split' : ''}`}>
    {week7Chrome && (
      <details className="compare-week7" id="compare-scenario-operations">
        <summary>{language === 'zh-TW' ? '方案操作（檢視／質疑／修改／分支／駁回／覆寫）' : 'Scenario operations (View / Challenge / Modify / Fork / Reject / Override)'}</summary>
        {week7Chrome}
      </details>
    )}
    {!boundRevision?.fixtureOnly && (
      <nav className="fabric-switches compare-workspace-switch" aria-label={t('Workspace')}>
        <button type="button" aria-pressed={fabricActive} onClick={() => setFabricActive(true)}>
          {t('Fabric plans (exploratory drafts)')}
        </button>
        <button type="button" data-testid="legacy-preview-toggle" aria-pressed={!fabricActive} onClick={() => setFabricActive(false)}>
          {zh ? '歷史形態預覽' : 'Historical morphology preview'}
        </button>
      </nav>
    )}
    {!boundRevision?.fixtureOnly && <div hidden={!fabricActive} onClickCapture={() => setFabricActive(true)} onFocusCapture={() => setFabricActive(true)}><FabricCompare projectId={projectId} apiBase={apiBase} mode={viewMode === 'COMPARE' ? 'SPLIT' : viewMode} syntaxContextData={syntaxOverlayVisible ? syntaxContextData : null} syntaxContextStatus={syntaxContextStatus} syntaxContextError={syntaxContextError} syntaxSegments={syntaxOverlayVisible ? syntaxSegments : []} syntaxLegend={syntaxLegend} syntaxOverlayVisible={syntaxOverlayVisible} onSyntaxOverlayVisibilityChange={onSyntaxOverlayVisibilityChange} activeSyntaxLayer={syntaxOverlayVisible ? activeSyntaxLayer : null} active={fabricActive} onSelection={onFabricSelection} /></div>}
    <div hidden={fabricActive && !boundRevision?.fixtureOnly} className="compare-existing" onClickCapture={() => setFabricActive(false)} onFocusCapture={() => setFabricActive(false)}>
    {formalId ? <>
      <aside className="compare-browser">{schemeList('left')}{boundRevision && <details className="compare-revision"><summary title={formatProposalReason(boundRevision.label, zh)}>{t('Workspace rev')}: {boundRevision.revision}</summary><p data-testid="compare-bound-revision">{formatProposalReason(boundRevision.label, zh)}</p></details>}</aside>
      <main className={`compare-canvas ${viewMode === 'COMPARE' ? 'compare-two-scenarios' : ''}`}>
        {formal.filter(item => item.id === formalId).map(item => <section className="compare-scenario-pane" key={item.id}><h2>{item.strategy} · <StatusBadge status={item.status} language={language} /></h2><PreviewViews enabled={!fabricActive || !!boundRevision?.fixtureOnly} {...commonViewportProps} formal={item} viewMode={viewMode === 'COMPARE' ? '3D' : viewMode} selectedFeatureId={leftFeature} onSelectedFeatureChange={leftSelection} cameraState={syncedViews ? sharedCameraState : undefined} onCameraChange={syncedViews ? setSharedCameraState : undefined} /></section>)}
        {viewMode === 'COMPARE' && <section className="compare-scenario-pane"><label className="compare-right-scenario-select">{t('Right scenario')}<select value={rightFormalId ?? ''} onChange={event => setRightFormalId(event.target.value)}>{formal.filter(item => item.id !== formalId).map(item => <option key={item.id} value={item.id}>{item.strategy}</option>)}</select></label>
          {formal.filter(item => item.id === rightFormalId && item.id !== formalId).map(item => <PreviewViews enabled={!fabricActive || !!boundRevision?.fixtureOnly} key={item.id} {...commonViewportProps} formal={item} viewMode="3D" selectedFeatureId={rightFeature} onSelectedFeatureChange={rightSelection} cameraState={syncedViews ? sharedCameraState : undefined} onCameraChange={syncedViews ? setSharedCameraState : undefined} />)}
        </section>}
      </main>
    </> : viewMode === 'COMPARE' ? <>
      <aside className="compare-browser compare-browser--split">{schemeList('left')}{boundRevision && <details className="compare-revision"><summary title={formatProposalReason(boundRevision.label, zh)}>{t('Workspace rev')}: {boundRevision.revision}</summary><p data-testid="compare-bound-revision">{formatProposalReason(boundRevision.label, zh)}</p></details>}</aside>
      <main className="compare-canvas compare-two-scenarios">
        {(selectedPreview || editableId !== null) && <section className="compare-scenario-pane" aria-label={t('Left scenario')}>
          {editableId === null && selectedPreview && <h2>{t(selectedPreview.strategy_label)} · <StatusBadge status="UNAPPROVED_PREVIEW" language={language} /></h2>}
          {editableId !== null ? <ScenarioStudio apiBase={apiBase} scenarioId={editableId || undefined} shellViewMode="3D" /> : <PreviewViews enabled={!fabricActive || !!boundRevision?.fixtureOnly} {...commonViewportProps} preview={selectedPreview} viewMode="3D" selectedFeatureId={leftFeature} onSelectedFeatureChange={leftSelection} cameraState={syncedViews ? sharedCameraState : undefined} onCameraChange={syncedViews ? setSharedCameraState : undefined} />}
        </section>}
        {rightPreview && <section className="compare-scenario-pane" aria-label={t('Right scenario')}>
          <label className="compare-right-scenario-select">{t('Right scenario')}
            <select value={previewKey(rightPreview)} aria-label={t('Right scenario')} onChange={event => {
              const nextPreview = previews.find(item => previewKey(item) === event.target.value);
              if (nextPreview) chooseRightPreview(nextPreview);
            }}>
              {previews.map(item => <option key={previewKey(item)} value={previewKey(item)}>{item.identity.intensity}: {t(item.strategy_label)}</option>)}
            </select>
          </label>
          <h2>{t(rightPreview.strategy_label)} · <StatusBadge status="UNAPPROVED_PREVIEW" language={language} /></h2>
          <PreviewViews enabled={!fabricActive || !!boundRevision?.fixtureOnly} {...commonViewportProps} preview={rightPreview} viewMode="3D" selectedFeatureId={rightFeature} onSelectedFeatureChange={rightSelection} cameraState={syncedViews ? sharedCameraState : undefined} onCameraChange={syncedViews ? setSharedCameraState : undefined} />
        </section>}
      </main>
    </> : <>
      <aside className="compare-browser">{schemeList('left')}{boundRevision && <details className="compare-revision"><summary title={formatProposalReason(boundRevision.label, zh)}>{t('Workspace rev')}: {boundRevision.revision}</summary><p data-testid="compare-bound-revision">{formatProposalReason(boundRevision.label, zh)}</p></details>}</aside>
      <main className="compare-canvas">
        {editableId === null && catalogError && <p role="alert">{t('Preview catalog unavailable.')}</p>}
        {editableId === null && !catalogError && catalog === null && <p role="status">{t('Loading preview scenarios…')}</p>}
        {editableId === null && catalog?.status === 'DISABLED' && <p role="status">{t('Preview catalog disabled.')}</p>}
        {editableId === null && selectedPreview && <div className="compare-selected-heading">{t(selectedPreview.strategy_label)} <StatusBadge status="UNAPPROVED_PREVIEW" language={language} /></div>}
        <div className="compare-main-viewport">
          {editableId !== null
            ? <ScenarioStudio apiBase={apiBase} scenarioId={editableId || undefined} shellViewMode={viewMode} />
            : selectedPreview && <PreviewViews enabled={!fabricActive || !!boundRevision?.fixtureOnly} {...commonViewportProps} preview={selectedPreview} viewMode={viewMode} selectedFeatureId={leftFeature} onSelectedFeatureChange={leftSelection} />}
        </div>
      </main>
    </>}
    </div>
    {reconsiderTarget && <HumanDecisionDialog
      isOpen={true}
      target={{ id: reconsiderTarget.id, type: 'DesignScenario',
        version: String(reconsiderTarget.revision ?? ''), geometrySha256: reconsiderTarget.geometry_sha256 ?? undefined }}
      action="Reconsider" status="not_reviewed"
      reviewContent={<p>{t('Return this scenario to proposed. A new decision is required to accept it again.')}</p>}
      onClose={() => setReconsiderTarget(null)}
      onSubmit={async decision => {
        const response = await fetch(`${apiBase.replace(/\/$/, '')}/api/v1/scenarios/reconsider`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: projectId, scenario_id: decision.target_id,
            target_version: decision.target_version, target_geometry_sha256: decision.target_geometry_sha256,
            reason: decision.reason, decision_key: decision.decision_key, actor_session_id: decision.actor_session_id }),
        });
        if (!response.ok) throw new Error(t('The decision was rejected.'));
        loadFormalProposals();
      }}
    />}
    {isBaselineDialogOpen && (
      <ScenarioComparisonDialog
        isOpen={isBaselineDialogOpen}
        projectId={projectId}
        allScenarios={formal
          .filter(item => item.status.toUpperCase() === 'PROPOSED')
          .map(item => ({
            scenario_id: item.id,
            strategy_label: item.strategy,
            revision: item.revision ?? 1,
            geometry_sha256: item.geometry_sha256 || undefined,
            status: item.status,
          }))}
        initialSelectedId={formalId || undefined}
        apiBase={apiBase}
        onClose={() => setIsBaselineDialogOpen(false)}
        onSuccess={() => {
          loadFormalProposals();
          setIsBaselineDialogOpen(false);
        }}
      />
    )}
  </div>;
}
