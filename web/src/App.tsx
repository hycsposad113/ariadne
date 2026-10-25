import { formatFar, formatPercentage } from './utils/displayMetrics';
import { GenerationWorkflowPanel, type GenerationMode } from './components/GenerationWorkflowPanel';
import { GenerationReadinessPanel, type GenerationReadiness } from './components/GenerationReadinessPanel';
import { FabricProperties } from './components/FabricProperties';
import { FabricCompare } from './components/FabricCompare';
import type { FabricSelection } from './components/FabricCompare';
import { FormalProperties } from './components/FormalProperties';
import { fetchDedupedReadiness } from './utils/readinessClient';
import type { FormalProposal } from './components/CompareWorkspace';
import React, { useState, useEffect, useLayoutEffect, useCallback, useRef, useMemo } from 'react';
import { Viewport2D } from './components/Viewport2D';
import { Viewport3D } from './components/Viewport3D';
import { SidebarDispositions } from './components/SidebarDispositions';
import { SidebarBrief } from './components/SidebarBrief';
import { DesignBriefPanel } from './components/DesignBriefPanel';
import { SiteProblemsOpportunities } from './components/SiteProblemsOpportunities';
import type { SavedBriefPayload, SiteIntelligenceResponse } from './components/siteIntelligenceTypes';
import { SidebarSyntax } from './components/SidebarSyntax';
import { ConstraintSetPanel } from './components/ConstraintSetPanel';
import { PanelEvidenceAndCritic } from './components/PanelEvidenceAndCritic';
import { AriadneWorkspacePanel } from './components/AriadnePanel';
import type { AriadneSourceType } from './components/AriadnePanel';
import { CompareWorkspace } from './components/CompareWorkspace';
import { EnvironmentPanel } from './components/EnvironmentPanel';
import { ClimateExtrasPanel } from './components/ClimateExtrasPanel';
import { E2Workspace } from './components/E2Workspace';
import type { PreviewItem } from './components/MorphologyPreviewCatalog';
import { I18nProvider, useI18n, useT } from './i18n';
import { StatusBadge, getStatusLabel } from './i18n/statusLabels';
import './App.css';
import { SyncModal } from './components/SyncModal';
import { HumanDecisionDialog } from './components/HumanDecisionDialog';
import type { HumanDecisionSubmission } from './components/HumanDecisionDialog';
import { ModelProfileSettings } from './components/ModelProfileSettings';
import { Week7Chrome } from './week7/Week7Actions';
import { Week7Chrome as FixtureWeek7Chrome } from './week7/FixtureWeek7Actions';
import { shellFromWeek7View } from './week7/shellFromWeek7View';
import { surfacesFromWeek7View, type Week7BoundSurfaces, type Week7SurfaceView } from './week7/surfacesFromWeek7View';
import type {
  Building,
  Segment,
  SyntaxLayer,
  EvidenceCard,
  EvidenceGap,
  ExplorationDesignArea,
  BriefPolygonPurpose,
  SpatialZone,
  WorkspaceRevision,
  FeatureDispositionType,
  SourceAttribution,
  SyntaxLayerPlanEntry,
  WorkspaceDecisionRecord,
  Day1DecisionSummary,
} from './types';

import { canApplyLoadResponse, shouldRetainNewerDraft } from './utils/loadGuards';
import { resolveFeatureDisposition } from './utils/disposition';
import { actorKindFromEnvironment, getActorSessionId } from './utils/actorProvenance';
import { buildSyntaxHeatmapClassification, UNCOMPUTED_STYLE } from './utils/syntaxHeatmap';
import {
  type SyntaxContextResponse,
  type SyntaxContextMode,
  type SyntaxContextMetric,
  fetchSyntaxContext,
} from './utils/syntaxContext';
import {
  SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256,
  SYNTAX_CONTEXT_READINESS,
} from './utils/syntaxReadiness';

const SiteBasicAnalysis = React.lazy(() => import('./components/SiteBasicAnalysis').then(module => ({ default: module.SiteBasicAnalysis })));
const ExtentMap = React.lazy(() => import('./components/ExtentMap').then(module => ({ default: module.ExtentMap })));
const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8789').replace(/\/$/, '');
const PROJECT_ID = import.meta.env.VITE_PROJECT_ID || 'rotterdam-m4h-pilot-project';
const ACTOR_KIND = actorKindFromEnvironment(import.meta.env.VITE_URBAN_DESIGN_ACTOR_KIND);


const STAGES = ['Site', 'Conditions', 'Generate', 'Compare', 'Refine'] as const;
type Stage = typeof STAGES[number];
type BrowserTab = 'DISPOSITIONS' | 'BRIEF' | 'SYNTAX' | 'CONSTRAINTS' | 'SCENARIOS' | 'AI_SETTINGS' | 'FACTS' | 'OPPORTUNITIES' | 'SPATIAL_ZONES';
const stageTools: Record<Stage, [BrowserTab,string][]> = {
  Site: [['FACTS','Site Facts'],['OPPORTUNITIES','Site Opportunities'],['SYNTAX','Space Syntax']],
  Conditions: [['DISPOSITIONS','Dispositions'],['BRIEF','Design Brief'],['SPATIAL_ZONES','Spatial Zones'],['CONSTRAINTS','Constraints']],
  Generate: [], Compare: [], Refine: [],
};
const viewLabels = {'2D':'2D Plan','3D':'3D','SPLIT':'Split','COMPARE':'Compare Split'};
const hasSha256 = (value: string | undefined): boolean =>
  typeof value === 'string' && /^sha256:[0-9a-f]{64}$/.test(value);

type ServerLoadState = 'LOADING' | 'READY' | 'ERROR';
type ActiveStudyArea = {
  id: string;
  status: string;
  revision: number;
  version: string;
  geometrySha256?: string;
  artifactSha256?: string;
};

function PreviewProperties({ preview, apiBase }: { preview: PreviewItem; apiBase: string }) {
  const t = useT();
  const { language } = useI18n();
  const assetHref = (path: string) => new URL(path, `${apiBase.replace(/\/$/, '')}/`).toString();
  const format = (value: number) => value.toLocaleString('en-GB', { maximumFractionDigits: 3 });
  return <section className="scheme-preview-properties" aria-label={t('Preview metrics')}>
    <div className="scheme-preview-property-heading"><strong>{t(preview.strategy_label)}</strong><StatusBadge status="UNAPPROVED_PREVIEW" language={language} /></div>
    <div className="scheme-preview-images">
      <a href={assetHref(preview.assets.plan)} download aria-label={t('Download plan image')}>
        <img src={assetHref(preview.assets.plan)} alt={t('{strategy} plan preview', { strategy: t(preview.strategy_label) })} loading="lazy" />
        <span>{t('Download plan image')}</span>
      </a>
      <a href={assetHref(preview.assets.axonometric)} download aria-label={t('Download axonometric image')}>
        <img src={assetHref(preview.assets.axonometric)} alt={t('{strategy} axonometric preview', { strategy: t(preview.strategy_label) })} loading="lazy" />
        <span>{t('Download axonometric image')}</span>
      </a>
    </div>
    <h3>{t('Comparison assumptions')}</h3>
    <dl>
      <div><dt>{t('Land FAR upper bound:')}</dt><dd>{formatFar(preview.limits.far_upper_bound_land)}</dd></div>
      <div><dt>{t('Coverage upper bound:')}</dt><dd>{preview.limits.coverage_upper_bound === null ? t('not set') : formatPercentage(preview.limits.coverage_upper_bound)}</dd></div>
      <div><dt>{t('New-building height cap:')}</dt><dd>{format(preview.limits.height_upper_bound_new_buildings_m)} {t('m')}</dd></div>
    </dl>
    <h3>{t('Generator-reported values')}</h3>
    <dl>
      <div><dt>{t('Known-part land FAR')}</dt><dd>{formatFar(preview.metrics.known_part_land_far)}</dd></div>
      <div><dt>{t('Coverage ratio')}</dt><dd>{formatPercentage(preview.metrics.coverage_ratio)}</dd></div>
      <div><dt>{t('Maximum known height')}</dt><dd>{format(preview.metrics.maximum_height_m)} {t('m')}</dd></div>
      <div><dt>{t('Open-space ratio')}</dt><dd>{formatPercentage(preview.metrics.open_space_ratio)}</dd></div>
      <div><dt>{t('Buildings')}</dt><dd>{preview.metrics.building_count}</dd></div>
      <div><dt>{t('Generator validation')}</dt><dd>{preview.metrics.generator_valid ? t('Valid under recorded checks') : t('Invalid')}</dd></div>
    </dl>
    <p className="scheme-height-note">{t('Height display policy')}: {t('Recorded feature height')}; {t('Scenario floor assumptions')}; {t('UNKNOWN · 3 m/storey display default')}</p>
    <p className="scheme-preview-verified">{t('Source verified at {time}; not reverified after startup.', { time: preview.verified_at_utc })}</p>
    <details>
      <summary>{t('Provenance and limitations')}</summary>
      {preview.metrics.warnings.length > 0 && <section><h4>{t('Generator warnings')}</h4><ul>{preview.metrics.warnings.map(warning => <li key={warning}>{t(warning)}</li>)}</ul></section>}
      <h4>{t('Limitations')}</h4><ul>{preview.limitations.map(limitation => <li key={limitation}>{t(limitation)}</li>)}</ul>
      {preview.input_refs.length > 0 && <><h4>{t('Input references')}</h4><ul>{preview.input_refs.map(ref => <li key={ref.label + ref.sha256}>{ref.label}: <code>{ref.sha256}</code></li>)}</ul></>}
      <a href={assetHref(preview.assets.geometry)} download>{t('Download scenario geometry')}</a>
    </details>
  </section>;
}

const AppContent: React.FC = () => {
  const t = useT();
  const { language, setLanguage } = useI18n();
  const zh = language === 'zh-TW';
  const fixtureWeek7Workspace = import.meta.env.MODE === 'test' ? new URLSearchParams(window.location.search).get('week7Workspace') : null;
  const [stage, setStage] = useState<Stage>('Site');
  const [drawingExtent, setDrawingExtent] = useState(false);
  const [showingBasicAnalysis, setShowingBasicAnalysis] = useState(false);
  const [generationMode, setGenerationMode] = useState<GenerationMode>('FULL_SCHEME');
  const [generationReadiness, setGenerationReadiness] = useState<GenerationReadiness | null>(null);
  useEffect(() => {
    if (stage !== 'Conditions' && stage !== 'Generate') return;
    let active = true;
    setGenerationReadiness(null);
    fetchDedupedReadiness<GenerationReadiness>(`${API_BASE}/api/v1/projects/${PROJECT_ID}/generation-context/readiness`)
      .then(value => { if (active) setGenerationReadiness(value); })
      .catch(() => { if (active) setGenerationReadiness(null); });
    return () => { active = false; };
  }, [stage]);
  const [rightTab, setRightTab] = useState<'Properties' | 'Ariadne'>('Properties');
  const [syncedViews, setSyncedViews] = useState(false);
  const [climateSubTab, setClimateSubTab] = useState<'four_schemes' | 'formal_live' | 'e2_experiment'>('four_schemes');
  const [isAriadneExpanded, setIsAriadneExpanded] = useState(false);
  const [fabricSelection, setFabricSelection] = useState<FabricSelection | null>(null);
  const [selectedScheme, setSelectedScheme] = useState<{id:string;label:string;status:string;preview?:PreviewItem;formal?:FormalProposal}|null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceRevision | null>(null);
  const week7WorkspaceQuery = fixtureWeek7Workspace || workspace?.workspace_id || null;
  const [studyArea, setStudyArea] = useState<ActiveStudyArea | null>(null);
  const [serverLoadState, setServerLoadState] = useState<ServerLoadState>('LOADING');
  const [week7Shell, setWeek7Shell] = useState<{ studyAreaId: string | null; workspaceRevision: string } | null>(null);
  const [week7Surfaces, setWeek7Surfaces] = useState<Week7BoundSurfaces | null>(null);
  const [outcomeUnknown, setOutcomeUnknown] = useState(false);
  const [reconciliationMessage, setReconciliationMessage] = useState<string | null>(null);
  const [studyAreaGeometry, setStudyAreaGeometry] = useState<unknown | null>(null);
  const [sourceSnapshotIds, setSourceSnapshotIds] = useState<string[]>([]);
  const [sourceAttributions, setSourceAttributions] = useState<SourceAttribution[]>([]);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [roads, setRoads] = useState<Segment[]>([]);
  const [syntaxLayers, setSyntaxLayers] = useState<SyntaxLayer[]>([]);
  const [syntaxLayersSource, setSyntaxLayersSource] = useState<'persisted_database_record' | 'verified_file_fallback' | 'none'>('none');
  const [syntaxLayerPlan, setSyntaxLayerPlan] = useState<SyntaxLayerPlanEntry[]>([]);
  const [syntaxSegments, setSyntaxSegments] = useState<Segment[]>([]);
  const [syntaxDownloads, setSyntaxDownloads] = useState<Record<string, string>>({});
  const [activeSyntaxLayer, setActiveSyntaxLayer] = useState<SyntaxLayer | null>(null);
  const [syntaxOverlayVisible, setSyntaxOverlayVisible] = useState(true);
  const [syntaxMode, setSyntaxMode] = useState<SyntaxContextMode>('pedestrian');
  const [syntaxMetric, setSyntaxMetric] = useState<SyntaxContextMetric>('nain');
  const [syntaxDistanceKm, setSyntaxDistanceKm] = useState<number>(1.0);
  const [syntaxContextData, setSyntaxContextData] = useState<SyntaxContextResponse | null>(null);
  const [syntaxContextStatus, setSyntaxContextStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [syntaxContextError, setSyntaxContextError] = useState<string | null>(null);
  const [evidenceCards, setEvidenceCards] = useState<EvidenceCard[]>([]);
  const [evidenceCardsStatus, setEvidenceCardsStatus] = useState('UNKNOWN');
  const [evidenceGaps, setEvidenceGaps] = useState<EvidenceGap[]>([]);
  const [sourcePackageRevision, setSourcePackageRevision] = useState<string | null>(null);
  const [ariadneDecisionCount, setAriadneDecisionCount] = useState(0);
  const [selectedEvidenceCardId, setSelectedEvidenceCardId] = useState<string | null>(null);
  const [spatialZones, setSpatialZones] = useState<SpatialZone[]>([]);
  const [explorationDesignArea, setExplorationDesignArea] = useState<ExplorationDesignArea | null>(null);
  const syntaxLegend = useMemo(() => {
    if (!activeSyntaxLayer) return [];
    const classification = buildSyntaxHeatmapClassification(activeSyntaxLayer.segment_values ?? {});
    return [
      ...classification.ranges.map(range => ({ label: range.label, color: range.color })),
      { label: 'Uncomputed / Excluded', color: UNCOMPUTED_STYLE.color },
    ];
  }, [activeSyntaxLayer]);

  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);
  const [selectedFeatureIds, setSelectedFeatureIds] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<'2D' | '3D' | 'SPLIT' | 'COMPARE'>('2D');
  const [sidebarTab, setSidebarTab] = useState<BrowserTab>('FACTS');
  const [siteIntelligence, setSiteIntelligence] = useState<SiteIntelligenceResponse | null>(null);
  const [briefSelectedOpportunityIds, setBriefSelectedOpportunityIds] = useState<string[]>([]);
  const [briefRejectedOpportunityIds, setBriefRejectedOpportunityIds] = useState<string[]>([]);
  const [briefRejectedReasons, setBriefRejectedReasons] = useState<Record<string, string>>({});

  const handleSelectOpportunity = useCallback((opportunityId: string, selected: boolean) => {
    setBriefSelectedOpportunityIds((current) => {
      if (selected) {
        if (!current.includes(opportunityId)) return [...current, opportunityId];
        return current;
      }
      return current.filter((id) => id !== opportunityId);
    });
    if (selected) {
      setBriefRejectedOpportunityIds((current) => current.filter((id) => id !== opportunityId));
    }
  }, []);

  const handleRejectOpportunity = useCallback((opportunityId: string, reason: string) => {
    setBriefSelectedOpportunityIds((current) => current.filter((id) => id !== opportunityId));
    setBriefRejectedOpportunityIds((current) => {
      if (!current.includes(opportunityId)) return [...current, opportunityId];
      return current;
    });
    setBriefRejectedReasons((current) => ({ ...current, [opportunityId]: reason }));
  }, []);

  const handleUndoRejectOpportunity = useCallback((opportunityId: string) => {
    setBriefRejectedOpportunityIds((current) => current.filter((id) => id !== opportunityId));
  }, []);

  const handleBriefSaved = useCallback((saved: SavedBriefPayload) => {
    setSiteIntelligence((current) => current ? { ...current, latest_brief: saved } : current);
    setBriefSelectedOpportunityIds([...saved.brief.selected_opportunity_ids]);
    setBriefRejectedOpportunityIds(saved.rejected_opportunities.map((item) => item.opportunity_id));
    setBriefRejectedReasons(Object.fromEntries(
      saved.rejected_opportunities.map((item) => [item.opportunity_id, item.reason]),
    ));
  }, []);

  const briefReadiness = useMemo(() => {
    const notReady = (message: string) => ({ canPersist: false, message });
    if (!siteIntelligence || !workspace || !studyArea) {
      return notReady('NOT_READY: Matching workspace, active StudyArea, and analysis references are required.');
    }
    const workspaceRef = siteIntelligence.workspace_ref;
    if (
      workspace.workspace_id !== workspaceRef.id
      || workspace.revision !== workspaceRef.revision
      || siteIntelligence.input_hashes[workspaceRef.id] !== workspaceRef.sha256
      || !hasSha256(workspaceRef.sha256)
      || workspace.study_area_id !== studyArea.id
    ) {
      return notReady('BLOCKED: Workspace, StudyArea, or workspace reference does not match the current revision.');
    }
    const analysisRef = siteIntelligence.latest_bundle_ref;
    if (
      !siteIntelligence.bundle_persisted
      || !analysisRef
      || !['AVAILABLE', 'PARTIAL'].includes(siteIntelligence.analysis_status)
    ) {
      return notReady('NOT_READY: A persisted SiteAnalysisBundle matching this workspace is required.');
    }
    if (
      !hasSha256(analysisRef.sha256)
      || siteIntelligence.input_hashes[analysisRef.id] !== analysisRef.sha256
      || !siteIntelligence.default_scope_ref
      || !hasSha256(siteIntelligence.default_scope_ref.sha256)
    ) {
      return notReady('BLOCKED: Matching analysis and StudyArea scope references are unavailable.');
    }
    const opportunityRef = siteIntelligence.opportunity_ref;
    if (opportunityRef && (
      !hasSha256(opportunityRef.sha256)
      || siteIntelligence.input_hashes[opportunityRef.id] !== opportunityRef.sha256
    )) {
      return notReady('BLOCKED: Opportunity suggestions do not match the persisted analysis references.');
    }
    if (siteIntelligence.opportunities.length > 0 && !opportunityRef) {
      return notReady('BLOCKED: Opportunity suggestions have no matching persisted reference.');
    }
    return { canPersist: true, message: '' };
  }, [siteIntelligence, studyArea, workspace]);

  // Drawing mode for spatial brief zones
  const [isDrawingZone, setIsDrawingZone] = useState<boolean>(false);
  const [activeDrawnCoords, setActiveDrawnCoords] = useState<[number, number][] | null>(null);
  const [activeDrawnPurpose, setActiveDrawnPurpose] = useState<BriefPolygonPurpose | null>(null);

  const [isSyncModalOpen, setIsSyncModalOpen] = useState(false);
  const [isDecisionDialogOpen, setIsDecisionDialogOpen] = useState(false);
  const [isD1DecisionDialogOpen, setIsD1DecisionDialogOpen] = useState(false);
  const [workspaceDecision, setWorkspaceDecision] = useState<WorkspaceDecisionRecord | null>(null);
  const [d1DecisionSummary, setD1DecisionSummary] = useState<Day1DecisionSummary | null>(null);
  const [humanDecisionMessage, setHumanDecisionMessage] = useState<string | null>(null);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const hasUnsavedChangesRef = useRef(false);
  const isSyncingRef = useRef(false);
  const draftGenerationRef = useRef(0);
  const latestLoadRequestRef = useRef(0);
  const pendingSyncRef = useRef<{
    idempotencyKey: string;
    expectedRevision: number;
    submittedDraftGeneration: number;
    draftBuildings: Building[];
    draftRoads: Segment[];
    draftSpatialZones: SpatialZone[];
    draftExplorationDesignArea: ExplorationDesignArea | null;
  } | null>(null);

  const setDirtyState = (dirty: boolean) => {
    hasUnsavedChangesRef.current = dirty;
    setHasUnsavedChanges(dirty);
  };

  const markDraftEdited = () => {
    if (isSyncingRef.current) return false;
    draftGenerationRef.current += 1;
    setDirtyState(true);
    return true;
  };

  const editActionsBlocked = () => isSyncingRef.current;

  // 1. Fetch site context and restore server state
  const loadData = useCallback(async () => {
    if (import.meta.env.MODE === 'test' && new URLSearchParams(window.location.search).get('week7Workspace')) {
      return null;
    }
    const pendingAtStart = pendingSyncRef.current;
    if (hasUnsavedChangesRef.current && !pendingAtStart) return null;

    const requestId = latestLoadRequestRef.current + 1;
    latestLoadRequestRef.current = requestId;
    const startedDraftGeneration = draftGenerationRef.current;
    setServerLoadState('LOADING');
    try {
      const res = await fetch(`${API_BASE}/api/v1/projects/${PROJECT_ID}/site-context`);
      if (!res.ok) throw new Error(`[HTTP ${res.status}]: Failed to load site context`);
      const data = await res.json();

      if (requestId !== latestLoadRequestRef.current) return null;
      const pending = pendingSyncRef.current;
      const reconcilingPendingSync = Boolean(
        pendingAtStart
        && pending
        && pending.idempotencyKey === pendingAtStart.idempotencyKey,
      );
      const canApply = canApplyLoadResponse({
        requestId,
        latestRequestId: latestLoadRequestRef.current,
        startedDraftGeneration,
        currentDraftGeneration: draftGenerationRef.current,
        hasPendingReconciliation: reconcilingPendingSync,
      });
      if (!canApply) {
        // The response is still useful to its caller, but must not replace a
        // newer local draft or the state produced by a newer reload.
        setServerLoadState('READY');
        return data;
      }

      const bldgs: Building[] = data.buildings || [];
      const rds: Segment[] = data.roads || data.segments || [];
      const dispositionMap = new Map<string, WorkspaceRevision['feature_dispositions'][number]>(
        (data.current_workspace?.feature_dispositions || []).map(
          (d: WorkspaceRevision['feature_dispositions'][number]) => [d.feature_id, d],
        ),
      );
      const serverBuildings: Building[] = bldgs.map(b => ({
        ...b,
        disposition: resolveFeatureDisposition(dispositionMap.get(b.id)?.disposition, b.disposition),
        annotation: dispositionMap.get(b.id)?.annotation ?? b.annotation ?? '',
      }));
      const serverRoads: Segment[] = rds.map(r => ({
        ...r,
        disposition: resolveFeatureDisposition(dispositionMap.get(r.id)?.disposition, r.disposition),
        annotation: dispositionMap.get(r.id)?.annotation ?? r.annotation ?? '',
      }));
      const serverSpatialZones: SpatialZone[] = data.current_workspace?.spatial_brief?.zones || [];
      const serverExplorationDesignArea: ExplorationDesignArea | null =
        data.current_workspace?.spatial_brief?.exploration_design_area || null;
      const currentGeneration = draftGenerationRef.current;
      const newerLocalDraft = pending
        ? shouldRetainNewerDraft({
          submittedDraftGeneration: pending.submittedDraftGeneration,
          currentDraftGeneration: currentGeneration,
        })
        : currentGeneration !== startedDraftGeneration;

      // All network requests have completed before this single state-apply
      // phase begins. Critic status can no longer open a mutation window.
      setStudyArea(data.study_area ? {
        id: data.study_area.id,
        status: data.study_area.status,
        revision: data.study_area.revision,
        version: data.study_area.version,
        geometrySha256: data.study_area.geometry_sha256,
        artifactSha256: data.study_area.artifact_sha256,
      } : null);
      setStudyAreaGeometry(data.study_area?.geometry);
      setSourceSnapshotIds(data.source_snapshot_ids || []);
      setSourceAttributions(data.source_attributions || []);
      setSourcePackageRevision(data.source_package_revision || null);
      setSyntaxLayers(data.syntax_layers || []);
      setSyntaxLayersSource(data.syntax_layers_source || 'none');
      setSyntaxLayerPlan(data.syntax_layer_plan || []);
      setSyntaxSegments(data.syntax_segments || []);
      const downloads: Record<string, string> = data.syntax_figure_downloads || {};
      setSyntaxDownloads(Object.fromEntries(
        Object.entries(downloads).map(([format, url]) => [format, new URL(url, `${API_BASE}/`).toString()]),
      ));
      if (data.syntax_layers && data.syntax_layers.length > 0) {
        setActiveSyntaxLayer(data.syntax_layers[0]);
      }
      setEvidenceCards(data.evidence_cards || []);
      setEvidenceCardsStatus(data.evidence_cards_status || 'UNKNOWN');
      setEvidenceGaps(data.evidence_gaps || []);
      setWorkspace(data.current_workspace || null);
      setD1DecisionSummary(data.current_workspace?.decision_summary || null);
      setWorkspaceDecision(data.current_workspace?.workspace_decision || null);

      try {
        const intelRes = await fetch(`${API_BASE}/api/v1/projects/${PROJECT_ID}/site-intelligence`);
        if (intelRes.ok) {
          const intelData: SiteIntelligenceResponse = await intelRes.json();
          setSiteIntelligence(intelData);
          if (intelData.latest_brief?.brief?.selected_opportunity_ids) {
            setBriefSelectedOpportunityIds(Array.from(intelData.latest_brief.brief.selected_opportunity_ids));
          }
          if (intelData.latest_brief?.rejected_opportunities) {
            setBriefRejectedOpportunityIds(intelData.latest_brief.rejected_opportunities.map(r => r.opportunity_id));
            setBriefRejectedReasons(Object.fromEntries(intelData.latest_brief.rejected_opportunities.map(r => [r.opportunity_id, r.reason])));
          }
        }
      } catch (intelErr) {
        console.error('Failed to load site intelligence', intelErr);
      }

      let retainedUncommittedDraft = newerLocalDraft;
      if (reconcilingPendingSync && pending) {
        const current = data.current_workspace as WorkspaceRevision | null;
        if (current?.idempotency_key === pending.idempotencyKey) {
          setOutcomeUnknown(false);
          setReconciliationMessage(newerLocalDraft
            ? `Reconciled: request is persisted as revision ${current.revision}; newer local work remains unsaved.`
            : `Reconciled: request is persisted as revision ${current.revision}.`);
          setSyncError(null);
          setIsSyncModalOpen(false);
          if (!newerLocalDraft) {
            setBuildings(serverBuildings);
            setRoads(serverRoads);
            setSpatialZones(serverSpatialZones);
            setExplorationDesignArea(serverExplorationDesignArea);
          }
          pendingSyncRef.current = null;
        } else if ((current?.revision ?? 0) === pending.expectedRevision) {
          setOutcomeUnknown(false);
          setReconciliationMessage(newerLocalDraft
            ? 'Reconciled: no matching revision is present; newer local work remains unsaved. Review before syncing again.'
            : 'Reconciled: no matching revision is present. Draft retained; review before syncing again.');
          setSyncError(null);
          setIsSyncModalOpen(false);
          if (!newerLocalDraft) {
            setBuildings(pending.draftBuildings);
            setRoads(pending.draftRoads);
            setSpatialZones(pending.draftSpatialZones);
            setExplorationDesignArea(pending.draftExplorationDesignArea);
          }
          retainedUncommittedDraft = true;
          pendingSyncRef.current = null;
        } else {
          setOutcomeUnknown(false);
          setReconciliationMessage(newerLocalDraft
            ? 'Reconciled to a different server revision; newer local work remains unsaved. Review before syncing again.'
            : 'Reconciled to a different server revision. Draft retained for comparison; review before syncing again.');
          setSyncError(null);
          setIsSyncModalOpen(false);
          if (!newerLocalDraft) {
            setBuildings(pending.draftBuildings);
            setRoads(pending.draftRoads);
            setSpatialZones(pending.draftSpatialZones);
            setExplorationDesignArea(pending.draftExplorationDesignArea);
          }
          retainedUncommittedDraft = true;
          pendingSyncRef.current = null;
        }
      } else if (!newerLocalDraft) {
        setBuildings(serverBuildings);
        setRoads(serverRoads);
        setSpatialZones(serverSpatialZones);
        setExplorationDesignArea(serverExplorationDesignArea);
      } else {
        // Keep local arrays and dirty state intact when a reload races with an
        // authored edit. The response cannot become authoritative for them.
      }
      setServerLoadState('READY');
      setDirtyState(retainedUncommittedDraft);
      return data;
    } catch (err) {
      if (requestId !== latestLoadRequestRef.current) return null;
      setServerLoadState('ERROR');
      setSyncError(`Could not load authoritative site context: ${err instanceof Error ? err.message : String(err)}`);
      return null;
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useLayoutEffect(() => {
    if (!week7WorkspaceQuery) return;
    const onView = (event: Event) => {
      const detail = (event as CustomEvent<Week7SurfaceView>).detail;
      if (!detail || (detail.workspace_id && detail.workspace_id !== week7WorkspaceQuery)) return;
      const applied = fixtureWeek7Workspace ? shellFromWeek7View(detail) : null;
      if (applied) {
        setBuildings(applied.buildings);
        setWeek7Shell({
          studyAreaId: applied.studyAreaId,
          workspaceRevision: applied.workspaceRevision,
        });
        setServerLoadState(applied.authorityState);
      }
      const surfaces = surfacesFromWeek7View(detail);
      if (!surfaces) return;
      setWeek7Surfaces(surfaces);
      if (fixtureWeek7Workspace) {
        setEvidenceCards(surfaces.evidenceCards);
        setEvidenceCardsStatus(surfaces.evidenceStatus);
      }
    };
    window.addEventListener('week7-persisted-view', onView);
    return () => window.removeEventListener('week7-persisted-view', onView);
  }, [week7WorkspaceQuery, fixtureWeek7Workspace]);

  useEffect(() => {
    if (!syntaxOverlayVisible) return;
    let active = true;
    setSyntaxContextStatus('loading');
    setSyntaxContextError(null);
    const distanceM = Math.round(syntaxDistanceKm * 1000);
    fetchSyntaxContext(syntaxMode, distanceM, API_BASE)
      .then((data) => {
        if (!active) return;
        setSyntaxContextData(data);
        setSyntaxContextStatus('success');
      })
      .catch((err) => {
        if (!active) return;
        setSyntaxContextData(null);
        setSyntaxContextStatus('error');
        setSyntaxContextError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      active = false;
    };
  }, [syntaxOverlayVisible, syntaxMode, syntaxDistanceKm]);

  // Update a building or road disposition
  const handleUpdateDisposition = (featureId: string, type: 'building' | 'road', disposition: FeatureDispositionType) => {
    if (!markDraftEdited()) return;
    if (type === 'building') {
      setBuildings(prev => prev.map(b => b.id === featureId ? { ...b, disposition } : b));
    } else {
      setRoads(prev => prev.map(r => r.id === featureId ? { ...r, disposition } : r));
    }
  };

  const handleUpdateAnnotation = (featureId: string, type: 'building' | 'road', annotation: string) => {
    if (!markDraftEdited()) return;
    if (type === 'building') {
      setBuildings(prev => prev.map(b => b.id === featureId ? { ...b, annotation } : b));
    } else {
      setRoads(prev => prev.map(r => r.id === featureId ? { ...r, annotation } : r));
    }
  };

  const handleSelectFeature = (id: string | null, _type: 'building' | 'road') => {
    setSelectedFeatureId(id);
    setSelectedFeatureIds(id ? [id] : []);
  };

  const handleSelectFeatureIds = (ids: string[]) => {
    setSelectedFeatureIds(ids);
    setSelectedFeatureId(ids[0] ?? null);
    setSidebarTab('DISPOSITIONS');
  };

  const handleAriadneEvidenceClick = (sourceId: string, sourceType?: AriadneSourceType) => {
    setStage('Site');
    setSidebarTab('FACTS');
    const citedCard = evidenceCards.find(card => card.card_id === sourceId);
    setSelectedEvidenceCardId(citedCard?.card_id ?? null);

    if (sourceType === 'syntax_layer') {
      const layer = syntaxLayers.find(item => item.layer_id === sourceId);
      if (layer) {
        setActiveSyntaxLayer(layer);
        setSyntaxOverlayVisible(true);
      }
    }

    const referencedIds = new Set(citedCard?.source_feature_ids ?? [sourceId]);
    const matchingIds = [...buildings, ...roads]
      .filter(feature => referencedIds.has(feature.id) || (feature.source_feature_id && referencedIds.has(feature.source_feature_id)))
      .map(feature => feature.id);
    setSelectedFeatureIds(matchingIds);
    setSelectedFeatureId(matchingIds[0] ?? null);
  };

  // Batch update all visible features
  const handleBatchUpdate = (type: 'building' | 'road', disposition: FeatureDispositionType, featureIds?: string[]) => {
    if (featureIds && featureIds.length === 0) return;
    if (!markDraftEdited()) return;
    const selectedIds = featureIds ? new Set(featureIds) : null;
    if (type === 'building') {
      setBuildings(prev => prev.map(b => !selectedIds || selectedIds.has(b.id) ? { ...b, disposition } : b));
    } else {
      setRoads(prev => prev.map(r => !selectedIds || selectedIds.has(r.id) ? { ...r, disposition } : r));
    }
  };

  // Spatial Brief Zones
  const handleAddZone = (zone: SpatialZone) => {
    if (!markDraftEdited()) return;
    setSpatialZones(prev => [...prev, zone]);
  };

  const handleRemoveZone = (zoneId: string) => {
    if (!markDraftEdited()) return;
    setSpatialZones(prev => prev.filter(z => z.zone_id !== zoneId));
  };

  const handleUpdateZone = (zone: SpatialZone) => {
    if (!markDraftEdited()) return;
    setSpatialZones(prev => prev.map(z => z.zone_id === zone.zone_id ? zone : z));
  };

  const handleSetExplorationDesignArea = (area: ExplorationDesignArea) => {
    if (!markDraftEdited()) return;
    setExplorationDesignArea(area);
  };

  // Polygon Drawing callbacks
  const handleStartDrawZone = (purpose: BriefPolygonPurpose = 'ZONE') => {
    if (editActionsBlocked()) return;
    setIsDrawingZone(true);
    setActiveDrawnCoords(null);
    setActiveDrawnPurpose(purpose);
  };

  const handleCompleteDrawingZone = (coords: [number, number][]) => {
    if (editActionsBlocked()) return;
    setActiveDrawnCoords(coords);
    setIsDrawingZone(false);
    setSidebarTab('BRIEF');
  };

  const handleCancelDrawingZone = () => {
    if (editActionsBlocked()) return;
    setIsDrawingZone(false);
    setActiveDrawnCoords(null);
    setActiveDrawnPurpose(null);
  };

  const handleToggleDrawingZone = () => {
    if (editActionsBlocked()) return;
    if (isDrawingZone) {
      setIsDrawingZone(false);
      setActiveDrawnCoords(null);
      setActiveDrawnPurpose(null);
      return;
    }
    setActiveDrawnCoords(null);
    setActiveDrawnPurpose('ZONE');
    setIsDrawingZone(true);
  };

  // Handle Sync commit
  const handleConfirmSync = async () => {
    if (isSyncingRef.current) return;
    if (isDrawingZone) {
      setSyncError('Sync blocked: finish or cancel the active brief polygon before syncing.');
      return;
    }
    if (activeDrawnCoords) {
      setSyncError('Sync blocked: save the finished brief polygon as a zone or Exploration Design Area, or clear it before syncing.');
      return;
    }
    if (serverLoadState !== 'READY' || !studyArea || sourceSnapshotIds.length === 0) {
      setSyncError('Sync blocked: authoritative StudyArea and source snapshots are not loaded.');
      return;
    }
    if (outcomeUnknown) {
      setSyncError('Sync blocked: a prior request has OUTCOME_UNKNOWN. Reload server state before another write.');
      return;
    }
    const submittedDraftGeneration = draftGenerationRef.current;
    isSyncingRef.current = true;
    setIsSyncing(true);
    setSyncError(null);
    setReconciliationMessage(null);
    const idempotencyKey = `ui-sync-${crypto.randomUUID()}`;
    const expectedRevision = workspace?.revision ?? 0;

    const payload = {
      project_id: PROJECT_ID,
      study_area_id: studyArea.id,
      expected_workspace_revision: expectedRevision,
      actor_kind: ACTOR_KIND,
      actor_session_id: getActorSessionId(),
      source_snapshot_ids: sourceSnapshotIds,
      idempotency_key: idempotencyKey,
      feature_dispositions: [
        ...buildings.map(b => ({
          feature_id: b.id,
          feature_kind: 'building',
          disposition: (b.disposition || 'UNDECIDED').toLowerCase(),
          annotation: b.annotation || '',
          source_artifact_id: b.source_artifact_id,
          source_snapshot_id: b.source_snapshot_id,
          source_feature_id: b.source_feature_id,
        })),
        ...roads.map(r => ({
          feature_id: r.id,
          feature_kind: 'road',
          disposition: (r.disposition || 'UNDECIDED').toLowerCase(),
          annotation: r.annotation || '',
          source_artifact_id: r.source_artifact_id,
          source_snapshot_id: r.source_snapshot_id,
          source_feature_id: r.source_feature_id,
        })),
      ],
      spatial_brief: {
        zones: spatialZones,
        exploration_design_area: explorationDesignArea,
        status: 'DRAFT_PENDING_HUMAN_DECISION',
      },
    };

    let responseReceived = false;
    try {
      pendingSyncRef.current = {
        idempotencyKey,
        expectedRevision,
        submittedDraftGeneration,
        draftBuildings: buildings,
        draftRoads: roads,
        draftSpatialZones: spatialZones,
        draftExplorationDesignArea: explorationDesignArea,
      };
      const res = await fetch(`${API_BASE}/api/v1/workspaces/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        responseReceived = true;
        const errorText = await res.text();
        let detailMsg = errorText;
        try {
          const errJson = JSON.parse(errorText);
          detailMsg = errJson.detail || errorText;
        } catch {}
        throw new Error(`[HTTP ${res.status}]: ${detailMsg}`);
      }

      const resData = await res.json();
      responseReceived = true;
      setWorkspace(resData.workspace_revision);
      const newerLocalWork = shouldRetainNewerDraft({
        submittedDraftGeneration,
        currentDraftGeneration: draftGenerationRef.current,
      });
      setDirtyState(newerLocalWork);
      setOutcomeUnknown(false);
      setReconciliationMessage(newerLocalWork
        ? `Server persisted revision ${resData.workspace_revision.revision}; newer local work remains unsaved.`
        : `Server persisted revision ${resData.workspace_revision.revision}.`);
      pendingSyncRef.current = null;
      setIsSyncModalOpen(false);

      try {
        const sumRes = await fetch(`${API_BASE}/api/v1/workspaces/${resData.workspace_revision.workspace_id}/decision-summary?revision=${resData.workspace_revision.revision}`);
        if (sumRes.ok) {
          const sumData = await sumRes.json();
          setD1DecisionSummary(sumData);
          setWorkspaceDecision(sumData.latest_decision || null);
        }
      } catch {}
    } catch (err: any) {
      if (pendingSyncRef.current && !responseReceived) {
        setOutcomeUnknown(true);
        setSyncError(`OUTCOME_UNKNOWN: ${err.message || 'Connection lost after sync dispatch.'} Checking server state; no automatic retry will be sent.`);
        const reconciled = await loadData();
        if (!reconciled) {
          setSyncError('OUTCOME_UNKNOWN: request outcome could not be reconciled because site-context is unavailable. Do not retry until server state is reachable.');
        }
      } else {
        pendingSyncRef.current = null;
        setSyncError(err.message || 'Sync error');
      }
    } finally {
      isSyncingRef.current = false;
      setIsSyncing(false);
    }
  };

  const canRecordStudyAreaReview = Boolean(
    serverLoadState === 'READY'
    && studyArea?.status === 'CONFIRMED_FOR_EXPLORATION'
    && (studyArea.geometrySha256 || studyArea.artifactSha256)
    && !outcomeUnknown
    && !hasUnsavedChanges
    && !isSyncing
    && !isDrawingZone,
  );

  const isD1DecisionStale = Boolean(
    workspaceDecision && (
      String(workspace?.revision ?? '') !== String(workspaceDecision.target_version)
      || hasUnsavedChanges
    )
  );

  const canConfirmD1Decision = Boolean(
    serverLoadState === 'READY'
    && workspace !== null
    && !outcomeUnknown
    && !hasUnsavedChanges
    && !isSyncing
    && !isDrawingZone,
  );

  const handleOpenD1DecisionDialog = async () => {
    if (!workspace) return;
    try {
      const res = await fetch(`${API_BASE}/api/v1/workspaces/${workspace.workspace_id}/decision-summary?revision=${workspace.revision}`);
      if (res.ok) {
        const summary = await res.json();
        setD1DecisionSummary(summary);
        if (summary.latest_decision) {
          setWorkspaceDecision(summary.latest_decision);
        }
      }
    } catch (e) {
      console.error('Failed to fetch decision summary', e);
    }
    setIsD1DecisionDialogOpen(true);
  };

  const handleSubmitD1Decision = async (decision: HumanDecisionSubmission) => {
    const response = await fetch(`${API_BASE}/api/v1/projects/${PROJECT_ID}/decisions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(decision),
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(typeof result?.detail === 'string'
        ? result.detail
        : `Decision request failed with HTTP ${response.status}.`);
    }
    setHumanDecisionMessage(`Day 1 decision recorded: ${result.id} (${result.status})`);
    setWorkspaceDecision(result);
    setIsD1DecisionDialogOpen(false);
    if (workspace) {
      try {
        const sumRes = await fetch(`${API_BASE}/api/v1/workspaces/${workspace.workspace_id}/decision-summary?revision=${workspace.revision}`);
        if (sumRes.ok) {
          const sumData = await sumRes.json();
          setD1DecisionSummary(sumData);
        }
      } catch {}
    }
  };

  const handleSubmitHumanDecision = async (decision: HumanDecisionSubmission) => {
    const response = await fetch(`${API_BASE}/api/v1/projects/${PROJECT_ID}/decisions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(decision),
    });
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(typeof result?.detail === 'string'
        ? result.detail
        : `Decision request failed with HTTP ${response.status}.`);
    }
    setHumanDecisionMessage(`Review recorded: ${result.id}`);
    setIsDecisionDialogOpen(false);
  };

  const contextReadinessFor = (mode: SyntaxContextMode) => {
    const server = syntaxContextData?.readiness;
    if (server && server.mode === mode) return server;
    const contract = SYNTAX_CONTEXT_READINESS[mode];
    return {
      mode,
      status: contract.status,
      reason: contract.reason,
      manifest_sha256: SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256,
      formal_result: false,
    };
  };

  const figureWorkspace = fixtureWeek7Workspace ? (week7Surfaces?.figureCitation ?? null) : workspace;
  const figureStudyArea = fixtureWeek7Workspace ? (week7Surfaces?.figureStudyArea ?? null) : studyArea;
  const week7BoundRevision = week7WorkspaceQuery && week7Surfaces
    ? {
        scenarioId: week7Surfaces.scenarioId,
        fixtureOnly: Boolean(fixtureWeek7Workspace),
        revision: week7Surfaces.revision,
        far: week7Surfaces.far,
        unit: week7Surfaces.unit,
        label: week7Surfaces.compareLabel,
      }
    : undefined;

  return (
    <div className="design-shell" lang={language}>
      <div className="shell-titlebar"><img className="shell-titlebar__logo" src="/ariadne-brand.png" alt={t('Ariadne')} /><strong>Ariadne</strong><span>{t('Urban design workspace')}</span><span className="shell-project">Rotterdam M4H</span><button id="language-toggle" aria-label={t(language === 'en' ? 'Current language: English; click to switch language' : 'Current language: Traditional Chinese; click to switch language')} style={{ color: '#f8fafc', backgroundColor: '#1e293b' }} onClick={() => setLanguage(language === 'en' ? 'zh-TW' : 'en')}>{t(language === 'en' ? 'English' : 'Chinese')} ▾</button></div>
      {fixtureWeek7Workspace && <FixtureWeek7Chrome apiBase={API_BASE} workspaceId={fixtureWeek7Workspace} />}
      <nav className="stage-tabs" aria-label={t('Design stages')}>
        {STAGES.map(item => <button key={item} id={'stage-' + item.toLowerCase()} aria-current={stage === item ? 'step' : undefined} onClick={() => {if (item === stage) return; setStage(item); setSelectedScheme(null); setFabricSelection(null); setSidebarTab(item === 'Site' ? 'FACTS' : 'DISPOSITIONS'); if (item !== 'Compare' && viewMode === 'COMPARE') setViewMode('SPLIT');}}>{t('stage.' + item.toLowerCase())}</button>)}
      </nav>
      <div className="shell-ribbon">
        <div className="ribbon-group"><div className="ribbon-tools">{stageTools[stage].map(([key,label]) => <button key={key} aria-pressed={sidebarTab === key} onClick={() => setSidebarTab(key)}>{t(label)}</button>)}{stage === 'Generate' && (['SKELETON_FIRST','FULL_SCHEME','STEPWISE'] as const).map((mode, index) => <button key={mode} aria-pressed={generationMode === mode} onClick={() => setGenerationMode(mode)}>{t(['Skeleton first','Full scheme','Stepwise'][index])}</button>)}
          {stage === 'Compare' && <button onClick={() => {setStage('Refine');setSelectedScheme(null);}}>{t('Edit scheme')}</button>}
          {stage === 'Refine' && <span>{t('Floor steps · 1 m move · Road snapping')}</span>}
        </div><small>{t('stage.' + stage.toLowerCase())}</small></div>
        {stage === 'Site' && <div className="ribbon-group ribbon-actions"><div className="ribbon-tools"><button id="btn-draw-extent" onClick={() => { setShowingBasicAnalysis(false); setDrawingExtent(true); }}>{t('Draw extent')}</button><button id="btn-basic-site-analysis" onClick={() => { setDrawingExtent(false); setShowingBasicAnalysis(true); }}>{t('Basic site analysis')}</button><button id="btn-record-study-area-review" disabled={!canRecordStudyAreaReview} onClick={() => setIsDecisionDialogOpen(true)}>{t('Record Review')}</button></div><small>{t('Site actions')}</small></div>}
        {stage === 'Site' && (
          <div className="ribbon-group ribbon-syntax" data-testid="ribbon-syntax-group">
            <div className="ribbon-tools">
              <div role="group" aria-label={t('Syntax scale')} style={{ display: 'inline-flex', gap: '2px' }}>
                <button
                  id="syntax-scale-walk"
                  aria-label={t('Walk 800 m')}
                  aria-pressed={syntaxMode === 'pedestrian'}
                  onClick={() => setSyntaxMode('pedestrian')}
                >
                  <span>{t('Walk 800 m')}</span>
                  <span
                    id="syntax-readiness-walk"
                    data-readiness={contextReadinessFor('pedestrian').status}
                    data-formal-result="false"
                    data-manifest-sha256={contextReadinessFor('pedestrian').manifest_sha256}
                    className="readiness-badge readiness-badge--inline"
                    title={`${getStatusLabel(contextReadinessFor('pedestrian').status, language).label} · ${zh ? '清單' : 'manifest'} ${contextReadinessFor('pedestrian').manifest_sha256}`}
                  >
                    {t(contextReadinessFor('pedestrian').status.startsWith('BLOCKED') ? 'Blocked' : 'Exploratory')}
                  </span>
                </button>
                <button
                  id="syntax-scale-bike"
                  aria-label={t('Bicycle 2 km')}
                  aria-pressed={syntaxMode === 'bicycle'}
                  onClick={() => setSyntaxMode('bicycle')}
                >
                  <span>{t('Bicycle 2 km')}</span>
                  <span
                    id="syntax-readiness-bike"
                    data-readiness={contextReadinessFor('bicycle').status}
                    data-formal-result="false"
                    data-manifest-sha256={contextReadinessFor('bicycle').manifest_sha256}
                    className="readiness-badge readiness-badge--inline"
                    title={`${getStatusLabel(contextReadinessFor('bicycle').status, language).label} · ${zh ? '清單' : 'manifest'} ${contextReadinessFor('bicycle').manifest_sha256}`}
                  >
                    {t(contextReadinessFor('bicycle').status.startsWith('BLOCKED') ? 'Blocked' : 'Exploratory')}
                  </span>
                </button>
                <button
                  id="syntax-scale-car"
                  aria-label={t('Car 10 km')}
                  aria-pressed={syntaxMode === 'motor_vehicle'}
                  onClick={() => setSyntaxMode('motor_vehicle')}
                >
                  <span>{t('Car 10 km')}</span>
                  <span
                    id="syntax-readiness-car"
                    data-readiness={contextReadinessFor('motor_vehicle').status}
                    data-formal-result="false"
                    data-manifest-sha256={contextReadinessFor('motor_vehicle').manifest_sha256}
                    className="readiness-badge readiness-badge--inline"
                    title={`${getStatusLabel(contextReadinessFor('motor_vehicle').status, language).label} · ${zh ? '清單' : 'manifest'} ${contextReadinessFor('motor_vehicle').manifest_sha256}`}
                  >
                    {t(contextReadinessFor('motor_vehicle').status.startsWith('BLOCKED') ? 'Blocked' : 'Exploratory')}
                  </span>
                </button>
              </div>
              <div
                id="syntax-context-manifest"
                data-bound-manifest={SHIPPED_SYNTAX_CONTEXT_MANIFEST_SHA256}
                data-formal-result="false"
                className="readiness-badge"
                title={`${zh ? '清單' : 'manifest'} ${contextReadinessFor(syntaxMode).manifest_sha256} · ${getStatusLabel(contextReadinessFor(syntaxMode).status, language).label}`}
              >
                {t('Not a formal result')}
              </div>
              <div role="group" aria-label={t('Syntax metric')} style={{ display: 'inline-flex', gap: '2px' }}>
                <button
                  id="syntax-metric-nain"
                  aria-pressed={syntaxMetric === 'nain'}
                  onClick={() => setSyntaxMetric('nain')}
                >
                  {t('Integration (NAIN)')}
                </button>
                <button
                  id="syntax-metric-nach"
                  aria-pressed={syntaxMetric === 'nach'}
                  onClick={() => setSyntaxMetric('nach')}
                >
                  {t('Choice (NACH)')}
                </button>
              </div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '11px' }}>
                <label htmlFor="syntax-range-number">{t('Context range')}:</label>
                <input
                  id="syntax-range-number"
                  type="number"
                  min="0.5"
                  max="3"
                  step="0.5"
                  value={syntaxDistanceKm}
                  onChange={(e) => {
                    const val = parseFloat(e.target.value);
                    if (!Number.isNaN(val)) setSyntaxDistanceKm(Math.max(0.5, Math.min(3, val)));
                  }}
                  style={{ width: '45px', padding: '1px 3px' }}
                  aria-label={t('Context range')}
                />
                <input
                  id="syntax-range-slider"
                  type="range"
                  min="0.5"
                  max="3"
                  step="0.5"
                  value={syntaxDistanceKm}
                  onChange={(e) => setSyntaxDistanceKm(parseFloat(e.target.value))}
                  aria-label={t('Context range slider')}
                  style={{ width: '55px' }}
                />
                <span>km</span>
              </div>
            </div>
            <small>{t('Space Syntax')}</small>
          </div>
        )}
        {stage === 'Conditions' && <div className="ribbon-group ribbon-actions"><div className="ribbon-tools">
          <button id="btn-reload-workspace" disabled={serverLoadState === 'LOADING' || isSyncing} onClick={() => { void loadData(); }}>{t('Reload')}</button>
          <button id="btn-sync-workspace" disabled={serverLoadState !== 'READY' || isSyncing || outcomeUnknown} onClick={() => setIsSyncModalOpen(true)}>{t(isSyncing ? 'Syncing...' : 'Sync Workspace')}</button>
          <button id="btn-confirm-d1-decision" disabled={!canConfirmD1Decision} onClick={() => { void handleOpenD1DecisionDialog(); }}>{t('Confirm Day 1 decision')}</button>
        </div><small>{t('Conditions actions')}</small></div>}
        <div className="ribbon-group ribbon-view"><div className="ribbon-tools">{(['2D','3D','SPLIT','COMPARE'] as const).map(mode => <button key={mode} id={'shell-view-' + mode.toLowerCase()} aria-pressed={viewMode === mode} disabled={mode === 'COMPARE' && stage !== 'Compare'} onClick={() => setViewMode(mode)}>{t(viewLabels[mode])}</button>)}
          <button id="shell-view-syntax" aria-pressed={syntaxOverlayVisible} disabled={(!activeSyntaxLayer || syntaxSegments.length === 0) && (!syntaxContextData?.segments?.length)} onClick={() => setSyntaxOverlayVisible(value => !value)}>{t('Space Syntax')}: {t(syntaxOverlayVisible ? 'On' : 'Off')}</button>
        </div><small>{t('Views')}</small></div>
        <div className="ribbon-group"><button onClick={() => setSidebarTab('AI_SETTINGS')}>{t('AI model settings')}</button><small>{t('Settings')}</small></div>
      </div>
      {outcomeUnknown && <div className="shell-warning" role="status">{t('OUTCOME_UNKNOWN · Reconciliation required')}</div>}
      {((workspace?.unverified_disposition_count || 0) + (workspace?.unverified_spatial_zone_count || 0) + (workspace?.unverified_exploration_design_area_count || 0) > 0) && <div id="unverified-history-warning" className="shell-warning" role="status">{t('Prior DRAFT history is preserved but is not active input.')}</div>}
      <div className="shell-body">
        {((stage !== 'Compare' && stage !== 'Refine') || sidebarTab === 'AI_SETTINGS') && <aside className="shell-browser" aria-label={t('Project Browser')}><div className="panel-heading">{t('Project Browser')}</div><div className="browser-content">
          {stage === 'Site' && sidebarTab === 'FACTS' && <PanelEvidenceAndCritic evidenceCards={evidenceCards} evidenceCardsStatus={evidenceCardsStatus} evidenceGaps={evidenceGaps} focusedCardId={selectedEvidenceCardId} />}
          {stage === 'Site' && sidebarTab === 'OPPORTUNITIES' && (
            <SiteProblemsOpportunities
              projectId={PROJECT_ID}
              apiBase={API_BASE}
              expectedStudyAreaId={workspace?.study_area_id ?? studyArea?.id ?? null}
              opportunities={siteIntelligence?.opportunities ?? []}
              selectedOpportunityIds={briefSelectedOpportunityIds}
              rejectedOpportunityIds={briefRejectedOpportunityIds}
              rejectedReasons={briefRejectedReasons}
              disabled={isSyncing || !briefReadiness.canPersist}
              onSelectOpportunity={handleSelectOpportunity}
              onRejectOpportunity={handleRejectOpportunity}
              onUndoRejectOpportunity={handleUndoRejectOpportunity}
              onNavigateToBrief={() => {
                setStage('Conditions');
                setSidebarTab('BRIEF');
              }}
            />
          )}
          {stage === 'Conditions' && sidebarTab !== 'AI_SETTINGS' && <GenerationReadinessPanel readiness={generationReadiness} />}
          {stage === 'Generate' && sidebarTab !== 'AI_SETTINGS' && <><GenerationReadinessPanel readiness={generationReadiness} /><GenerationWorkflowPanel apiBase={API_BASE} projectId={PROJECT_ID} requestedMode={generationMode} onResults={() => setStage('Compare')} /></>}
          {stage !== 'Generate' && <>
            {sidebarTab === 'DISPOSITIONS' && (
              <SidebarDispositions
                buildings={buildings}
                roads={roads}
                selectedFeatureId={selectedFeatureId}
                selectedFeatureIds={selectedFeatureIds}
                isSyncing={isSyncing}
                onSelectFeature={handleSelectFeature}
                onUpdateDisposition={handleUpdateDisposition}
                onUpdateAnnotation={handleUpdateAnnotation}
                onBatchUpdate={handleBatchUpdate}
                workspaceDecision={workspaceDecision}
                isD1DecisionStale={isD1DecisionStale}
              />
            )}
            {sidebarTab === 'BRIEF' && (
              <DesignBriefPanel
                projectId={PROJECT_ID}
                workspaceRevision={workspace?.revision ?? 0}
                workspaceRef={siteIntelligence?.workspace_ref ?? null}
                analysisRef={siteIntelligence?.bundle_persisted ? siteIntelligence.latest_bundle_ref : null}
                opportunityRef={siteIntelligence?.opportunity_ref ?? null}
                inputHashes={siteIntelligence?.input_hashes ?? {}}
                defaultScopeRef={siteIntelligence?.default_scope_ref ?? null}
                opportunities={siteIntelligence?.opportunities ?? []}
                apiBase={API_BASE}
                canPersist={briefReadiness.canPersist}
                readinessMessage={briefReadiness.message}
                initialSelectedOpportunityIds={briefSelectedOpportunityIds}
                initialRejectedOpportunities={briefRejectedOpportunityIds.map(id => ({
                  opportunity_id: id,
                  reason: briefRejectedReasons[id] || '',
                }))}
                initialDraft={siteIntelligence?.latest_brief ?? null}
                sourceLimitations={siteIntelligence?.limitations ?? []}
                onNavigateToSpatialZones={() => setSidebarTab('SPATIAL_ZONES')}
                onBriefSaved={handleBriefSaved}
              />
            )}
            {sidebarTab === 'SPATIAL_ZONES' && (
              <SidebarBrief
                zones={spatialZones}
                explorationDesignArea={explorationDesignArea}
                isSyncing={isSyncing}
                activeDrawnCoords={activeDrawnCoords}
                activeDrawnPurpose={activeDrawnPurpose}
                isDrawingZone={isDrawingZone}
                onStartDrawPolygon={handleStartDrawZone}
                onClearDrawnPolygon={() => {
                  if (!editActionsBlocked()) {
                    setActiveDrawnCoords(null);
                    setActiveDrawnPurpose(null);
                  }
                }}
                onAddZone={handleAddZone}
                onRemoveZone={handleRemoveZone}
                onUpdateZone={handleUpdateZone}
                onSetExplorationDesignArea={handleSetExplorationDesignArea}
                studyAreaGeometry={studyAreaGeometry}
                workspaceDecision={workspaceDecision}
                isD1DecisionStale={isD1DecisionStale}
              />
            )}
            {sidebarTab === 'SYNTAX' && (
              <SidebarSyntax
                layers={syntaxLayers}
                layersSource={syntaxLayersSource}
                activeLayer={activeSyntaxLayer}
                onSelectLayer={(l) => setActiveSyntaxLayer(l)}
                layerPlan={syntaxLayerPlan}
                exploratoryDownloadUrl={syntaxDownloads.svg}
              />
            )}
            {sidebarTab === 'CONSTRAINTS' && (
              <ConstraintSetPanel
                apiBase={API_BASE}
                projectId={PROJECT_ID}
                onSubmitDecision={handleSubmitHumanDecision}
              />
            )}
            {sidebarTab === 'AI_SETTINGS' && <ModelProfileSettings apiBase={API_BASE} />}

          </>}
          {stage === 'Generate' && sidebarTab === 'AI_SETTINGS' && <ModelProfileSettings apiBase={API_BASE} />}
        </div></aside>}
        <main className="shell-view-area" aria-label={t('View area')}>
          <div className="view-tabbar"><span>{stage === 'Site' && showingBasicAnalysis ? t('Basic site analysis') : stage === 'Site' && drawingExtent ? t('Draw extent') : stage === 'Compare' ? t('Scheme comparison') : t(viewLabels[viewMode])}</span><span>{stage === 'Site' && (drawingExtent || showingBasicAnalysis) ? 'WGS84 · EPSG:3857' : 'EPSG:28992'}</span>{stage === 'Compare' && viewMode === 'COMPARE' && <label><input type="checkbox" checked={syncedViews} onChange={e => setSyncedViews(e.target.checked)} />{t('Synchronize views')}</label>}</div>
          <div className="shell-view-content">
            {stage === 'Site' && showingBasicAnalysis ? <React.Suspense fallback={<p>{t('Loading…')}</p>}><SiteBasicAnalysis apiBase={API_BASE} projectId={PROJECT_ID} onClose={() => setShowingBasicAnalysis(false)} /></React.Suspense> : stage === 'Site' && drawingExtent ? <React.Suspense fallback={<p>{t('Loading…')}</p>}><ExtentMap apiBase={API_BASE} projectId={PROJECT_ID} onClose={() => setDrawingExtent(false)} /></React.Suspense> : stage === 'Compare' ? (
              <div className="compare-e1-workbench">
                <nav className="compare-section-index" aria-label={language === 'zh-TW' ? '比較頁章節導覽' : 'Compare section index'}>
                  <button type="button" onClick={() => (document.getElementById('compare-maps') || document.getElementById('compare-maps-canvas'))?.scrollIntoView({ behavior: 'smooth' })}>
                    {language === 'zh-TW' ? '地圖' : 'Map'}
                  </button>
                  <button type="button" onClick={() => document.getElementById('compare-metrics')?.scrollIntoView({ behavior: 'smooth' })}>
                    {language === 'zh-TW' ? '方案指標' : 'Metrics'}
                  </button>
                  <button type="button" onClick={() => document.getElementById('compare-climate-environment')?.scrollIntoView({ behavior: 'smooth' })}>
                    {language === 'zh-TW' ? '氣候與環境' : 'Climate & Environment'}
                  </button>
                  <button type="button" onClick={() => document.getElementById('compare-scenario-operations')?.scrollIntoView({ behavior: 'smooth' })}>
                    {language === 'zh-TW' ? '方案操作' : 'Scenario Operations'}
                  </button>
                </nav>
                <div className="compare-e1-workbench__workspace">
                  <CompareWorkspace week7Chrome={fixtureWeek7Workspace ? null : <Week7Chrome apiBase={API_BASE} workspaceId={workspace?.workspace_id || null} scenarioId={selectedScheme && !selectedScheme.preview ? selectedScheme.id : null} />} projectId={PROJECT_ID} key={stage} apiBase={API_BASE} viewMode={viewMode} syncedViews={syncedViews} onSchemeSelection={setSelectedScheme} onFabricSelection={setFabricSelection} boundRevision={week7BoundRevision} syntaxContextData={syntaxOverlayVisible ? syntaxContextData : null} syntaxContextStatus={syntaxContextStatus} syntaxContextError={syntaxContextError} syntaxSegments={syntaxSegments} syntaxSegmentValues={activeSyntaxLayer?.segment_values ?? {}} syntaxLegend={syntaxLegend} activeSyntaxLayer={activeSyntaxLayer} syntaxOverlayVisible={syntaxOverlayVisible} onSyntaxOverlayVisibilityChange={setSyntaxOverlayVisible} />
                </div>
                <section id="compare-climate-environment" className="compare-climate-section" aria-label={language === 'zh-TW' ? '氣候與環境' : 'Climate & Environment'}>
                  <div className="compare-climate-header">
                    <h2>{language === 'zh-TW' ? '氣候與環境' : 'Climate & Environment'}</h2>
                    <div className="fabric-switches compare-climate-tabs" role="tablist">
                      <button
                        type="button"
                        role="tab"
                        aria-selected={climateSubTab === 'four_schemes'}
                        aria-pressed={climateSubTab === 'four_schemes'}
                        onClick={() => setClimateSubTab('four_schemes')}
                      >
                        {language === 'zh-TW' ? '四案對照（離線計算）' : 'Four Schemes (Offline)'}
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={climateSubTab === 'formal_live'}
                        aria-pressed={climateSubTab === 'formal_live'}
                        onClick={() => setClimateSubTab('formal_live')}
                      >
                        {language === 'zh-TW' ? '正式方案即時計算' : 'Formal Proposal (Live)'}
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={climateSubTab === 'e2_experiment'}
                        aria-pressed={climateSubTab === 'e2_experiment'}
                        onClick={() => setClimateSubTab('e2_experiment')}
                      >
                        {language === 'zh-TW' ? 'E2 夏季輻射實驗' : 'E2 Summer Radiation'}
                      </button>
                    </div>
                  </div>
                  <div className="compare-climate-source-notice" role="note">
                    {climateSubTab === 'four_schemes' ? (
                      <p>
                        <strong>{language === 'zh-TW' ? '資料來源：' : 'Data source: '}</strong>
                        {language === 'zh-TW'
                          ? '離線批次微氣候模擬（artifacts/w8/）· 涵蓋四個紋理探索草案之 E1 日照、風場、PET 舒適度及熱島指標對照。'
                          : 'Offline batch microclimate simulation (artifacts/w8/) · Covers four fabric exploratory drafts for E1 sunlight, wind, PET comfort, and heat island metrics.'}
                      </p>
                    ) : climateSubTab === 'formal_live' ? (
                      <p>
                        <strong>{language === 'zh-TW' ? '資料來源：' : 'Data source: '}</strong>
                        {language === 'zh-TW'
                          ? '平台即時計算（Radiance 6.0.2 / Python 光線投射回退）· 針對正式方案公共空間進行端到端日照與陰影即時分析。'
                          : 'Platform live calculation (Radiance 6.0.2 / Python raycast fallback) · End-to-end direct sunlight and shadow analysis for formal proposal public spaces.'}
                      </p>
                    ) : (
                      <p>
                        <strong>{language === 'zh-TW' ? '資料來源：' : 'Data source: '}</strong>
                        {language === 'zh-TW'
                          ? 'E2 夏季入射輻射實驗（Ladybug 篩檢＋Honeybee-Radiance 驗證）· 全年推導氣象 candidate-01、5 m 網格、±1 小時敏感度分析。'
                          : 'E2 summer incident radiation experiment (Ladybug screening + Honeybee-Radiance verification) · candidate-01 weather derivation, 5 m grid, ±1 h sensitivity analysis.'}
                      </p>
                    )}
                  </div>
                  <div style={{ display: climateSubTab === 'four_schemes' ? 'block' : 'none' }}>
                    <ClimateExtrasPanel projectId={PROJECT_ID} apiBase={API_BASE} className="climate-extras-panel--embedded" />
                  </div>
                  <div style={{ display: climateSubTab === 'formal_live' ? 'block' : 'none' }}>
                    <EnvironmentPanel apiBase={API_BASE} projectId={PROJECT_ID} preferredModifiedScenarioId={selectedScheme?.formal?.id} className="environment-panel--embedded" />
                  </div>
                  {/* Mounted only when opened: its reads re-verify large artifacts and would slow every Compare visit. */}
                  {climateSubTab === 'e2_experiment' && (
                    <div>
                      <E2Workspace apiBase={API_BASE} projectId={PROJECT_ID} />
                    </div>
                  )}
                </section>
              </div>
            ) : stage === 'Generate' ? (
              <FabricCompare projectId={PROJECT_ID} apiBase={API_BASE} mode={viewMode === 'COMPARE' ? 'SPLIT' : viewMode} onSelection={setFabricSelection} syntaxContextData={syntaxOverlayVisible ? syntaxContextData : null} syntaxContextStatus={syntaxContextStatus} syntaxContextError={syntaxContextError} syntaxSegments={syntaxOverlayVisible ? syntaxSegments : []} syntaxLegend={syntaxLegend} syntaxOverlayVisible={syntaxOverlayVisible} onSyntaxOverlayVisibilityChange={setSyntaxOverlayVisible} activeSyntaxLayer={syntaxOverlayVisible ? activeSyntaxLayer : null} />
            ) : stage === 'Refine' ? (
              <CompareWorkspace week7Chrome={fixtureWeek7Workspace ? null : <Week7Chrome apiBase={API_BASE} workspaceId={workspace?.workspace_id || null} scenarioId={selectedScheme && !selectedScheme.preview ? selectedScheme.id : null} />} projectId={PROJECT_ID} key={stage} startEditing apiBase={API_BASE} viewMode={viewMode} syncedViews={syncedViews} onSchemeSelection={setSelectedScheme} onFabricSelection={setFabricSelection} boundRevision={week7BoundRevision} syntaxContextData={syntaxOverlayVisible ? syntaxContextData : null} syntaxContextStatus={syntaxContextStatus} syntaxContextError={syntaxContextError} syntaxSegments={syntaxSegments} syntaxSegmentValues={activeSyntaxLayer?.segment_values ?? {}} syntaxLegend={syntaxLegend} activeSyntaxLayer={activeSyntaxLayer} syntaxOverlayVisible={syntaxOverlayVisible} onSyntaxOverlayVisibilityChange={setSyntaxOverlayVisible} />
            ) : <>
          {(viewMode === '2D' || viewMode === 'SPLIT') && (
            <div style={{ flex: 1, height: '100%', position: 'relative', borderRight: viewMode === 'SPLIT' ? '1px solid var(--border-subtle)' : 'none' }}>
              <Viewport2D
                studyAreaGeometry={studyAreaGeometry}
                buildings={buildings}
                segments={roads}
                syntaxSegments={syntaxSegments}
                syntaxLegend={syntaxLegend}
                activeSyntaxLayer={syntaxOverlayVisible ? activeSyntaxLayer : null}
                syntaxContextData={syntaxOverlayVisible ? syntaxContextData : null}
                syntaxContextStatus={syntaxContextStatus}
                syntaxContextError={syntaxContextError}
                syntaxMode={syntaxMode}
                syntaxMetric={syntaxMetric}
                syntaxDistanceKm={syntaxDistanceKm}
                spatialZones={spatialZones}
                explorationDesignArea={explorationDesignArea}
                selectedFeatureId={selectedFeatureId}
                selectedFeatureIds={selectedFeatureIds}
                onSelectFeature={handleSelectFeature}
                onSelectFeatureIds={handleSelectFeatureIds}
                isDrawingZone={isDrawingZone}
                onToggleDrawingZone={handleToggleDrawingZone}
                onCompleteDrawingZone={handleCompleteDrawingZone}
                onCancelDrawingZone={handleCancelDrawingZone}
                figureContext={{
                  projectId: PROJECT_ID,
                  workspace: figureWorkspace,
                  studyArea: figureStudyArea,
                  hasUnsavedChanges,
                  sourcePackageRevision,
                  sourceSnapshotIds,
                  sourceAttributions,
                  buildingCount: buildings.length,
                  roadCount: roads.length,
                  spatialZoneCount: spatialZones.length,
                  explorationDesignArea,
                  selectedFeatureIds,
                  activeSyntaxLayer,
                }}
                figureExportReady={serverLoadState === 'READY'}
              />
            </div>
          )}

          {(viewMode === '3D' || viewMode === 'SPLIT') && (
            <div style={{ flex: 1, height: '100%', position: 'relative' }}>
              <Viewport3D
                studyAreaGeometry={studyAreaGeometry}
                explorationDesignArea={explorationDesignArea}
                buildings={buildings}
                segments={roads}
                syntaxSegments={syntaxSegments}
                syntaxSegmentValues={activeSyntaxLayer?.segment_values ?? {}}
                syntaxLegend={syntaxLegend}
                syntaxOverlayVisible={syntaxOverlayVisible}
                onSyntaxOverlayVisibilityChange={setSyntaxOverlayVisible}
                syntaxContextData={syntaxOverlayVisible ? syntaxContextData : null}
                syntaxContextStatus={syntaxContextStatus}
                syntaxContextError={syntaxContextError}
                syntaxMode={syntaxMode}
                syntaxMetric={syntaxMetric}
                syntaxDistanceKm={syntaxDistanceKm}
                selectedFeatureId={selectedFeatureId}
                selectedFeatureIds={selectedFeatureIds}
                onSelectFeature={handleSelectFeature}
                figureContext={{
                  projectId: PROJECT_ID,
                  workspace: figureWorkspace,
                  studyArea: figureStudyArea,
                  hasUnsavedChanges,
                  sourcePackageRevision,
                  sourceSnapshotIds,
                  buildingCount: buildings.length,
                  roadCount: roads.length,
                  explorationDesignArea,
                  selectedFeatureIds,
                }}
                figureExportReady={serverLoadState === 'READY'}
              />
            </div>
          )}

            </>}
          </div>
        </main>
        <aside className={"shell-properties " + (isAriadneExpanded && rightTab === 'Ariadne' ? 'shell-properties--expanded' : '')}><div className="panel-tabs">{(['Properties','Ariadne'] as const).map(tab => <button key={tab} aria-label={t(tab)} aria-pressed={rightTab === tab} onClick={() => setRightTab(tab)}><span>{t(tab)}</span>{tab === 'Ariadne' && ariadneDecisionCount > 0 && <span className="panel-tab-count" data-testid="ariadne-decisions-badge">{ariadneDecisionCount}</span>}</button>)}</div>
          {rightTab === 'Ariadne' ? <AriadneWorkspacePanel apiBase={API_BASE} projectId={PROJECT_ID} evidenceCards={evidenceCards} onEvidenceClick={handleAriadneEvidenceClick} onDecisionsNeededChange={setAriadneDecisionCount} isExpanded={isAriadneExpanded} onToggleExpand={() => setIsAriadneExpanded(v => !v)} /> : <div className="shell-property-content"><h2>{t('Selection')}</h2>{(stage === 'Compare' || stage === 'Generate' || stage === 'Refine') && fabricSelection ? <FabricProperties selection={fabricSelection} apiBase={API_BASE} /> : <>{(stage === 'Compare' || stage === 'Refine') && selectedScheme && <><dl><dt>{t('Scheme')}</dt><dd>{t(selectedScheme.label)}</dd><dt>{t('Scheme ID')}</dt><dd>{selectedScheme.id}</dd><dt>{t('Status')}</dt><dd><StatusBadge status={selectedScheme.status} language={language} /></dd></dl>{selectedScheme.formal && <FormalProperties proposal={selectedScheme.formal} />}{selectedScheme.preview && <PreviewProperties preview={selectedScheme.preview} apiBase={API_BASE} />}</>}<dl><dt>{t('Selected features')}</dt><dd>{selectedFeatureIds.length}</dd><dt>{t('Feature ID')}</dt><dd>{selectedFeatureId ?? t('None')}</dd><dt>{t('Buildings')}</dt><dd>{buildings.length}</dd><dt>{t('Roads')}</dt><dd>{roads.length}</dd><dt>{t('Units')}</dt><dd>{t('metres')}</dd></dl>{selectedFeatureId && <dl><dt>{t('Disposition')}</dt><dd>{t([...buildings,...roads].find(f => f.id === selectedFeatureId)?.disposition ?? 'UNKNOWN')}</dd></dl>}</>}</div>}
        </aside>
      </div>
      <footer className="shell-statusbar"><span>{t('Project ID')}: {PROJECT_ID}</span><span>{t('StudyArea ID')}: {fixtureWeek7Workspace ? (week7Shell?.studyAreaId ?? t('Unavailable')) : (studyArea?.id ?? t('Unavailable'))}</span><span>{t('Workspace rev')}: {fixtureWeek7Workspace ? (week7Shell?.workspaceRevision ?? t('Unavailable')) : (workspace?.revision ?? t('Unavailable'))}</span><span>{t('Authority')}: {language === 'zh-TW' ? t(serverLoadState) : ({LOADING: 'Loading…', READY: 'Ready', ERROR: 'Error'} as Record<string, string>)[serverLoadState] ?? serverLoadState}</span>{outcomeUnknown && <span>{language === 'zh-TW' ? '結果未知 · 需要核對狀態' : 'Outcome unknown · reconciliation required'}</span>}{hasUnsavedChanges && <span>{t('Unsaved draft')}</span>}{reconciliationMessage && <span>{t(reconciliationMessage)}</span>}{humanDecisionMessage && <span>{t(humanDecisionMessage)}</span>}{workspaceDecision && <span><StatusBadge status={workspaceDecision.status} language={language} /> · {t('Day 1 decision')}</span>}</footer>
      {/* Sync / Version Diff Modal */}
      <SyncModal
        isOpen={isSyncModalOpen}
        onClose={() => {
          if (!isSyncingRef.current) setIsSyncModalOpen(false);
        }}
        onConfirmSync={handleConfirmSync}
        isSyncing={isSyncing}
        currentWorkspace={workspace}
        buildings={buildings}
        roads={roads}
        spatialZones={spatialZones}
        syncError={syncError ? t(syncError) : null}
        onReloadServerState={loadData}
      />
      {studyArea && (
        <HumanDecisionDialog
          isOpen={isDecisionDialogOpen}
          target={{
            id: studyArea.id,
            type: 'StudyArea',
            version: studyArea.version,
            geometrySha256: studyArea.geometrySha256,
            artifactSha256: studyArea.artifactSha256,
          }}
          action="Inspect"
          status="inspected"
          onClose={() => setIsDecisionDialogOpen(false)}
          onSubmit={handleSubmitHumanDecision}
        />
      )}
      {workspace && (
        <HumanDecisionDialog
          isOpen={isD1DecisionDialogOpen}
          target={{
            id: workspace.workspace_id,
            type: 'WorkspaceRevision',
            version: String(workspace.revision),
            payloadDigest: workspace.payload_digest || d1DecisionSummary?.payload_digest,
            geometrySha256: d1DecisionSummary?.exploration_design_area?.geometry_hash || undefined,
          }}
          action="Approve"
          status="approved"
          summary={d1DecisionSummary}
          hasUnsavedChanges={hasUnsavedChanges}
          onClose={() => setIsD1DecisionDialogOpen(false)}
          onSubmit={handleSubmitD1Decision}
        />
      )}

    </div>
  );
};
export const App: React.FC = () => <I18nProvider><AppContent /></I18nProvider>;
export default App;
