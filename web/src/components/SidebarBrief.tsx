import { useT } from '../i18n';
import React, { useState } from 'react';
import type { BriefPolygonPurpose, DraftNumericInput, ExplorationDesignArea, SpatialZone, WorkspaceDecisionRecord } from '../types';
import { measurePolygonalAreaM2, preparePolygonWithinStudyArea } from '../utils/geometryScope';
import { DesignAreaClipPreview } from './DesignAreaClipPreview';
import { Plus, Trash2, AlertTriangle, Edit3, CheckCircle2 } from 'lucide-react';

interface SidebarBriefProps {
  zones: SpatialZone[];
  explorationDesignArea?: ExplorationDesignArea | null;
  isSyncing: boolean;
  activeDrawnCoords: [number, number][] | null;
  activeDrawnPurpose?: BriefPolygonPurpose | null;
  isDrawingZone: boolean;
  onStartDrawPolygon: (purpose?: BriefPolygonPurpose) => void;
  onClearDrawnPolygon: () => void;
  onAddZone: (zone: SpatialZone) => void;
  onRemoveZone: (zoneId: string) => void;
  onUpdateZone: (zone: SpatialZone) => void;
  onSetExplorationDesignArea?: (area: ExplorationDesignArea) => void;
  studyAreaGeometry: unknown;
  workspaceDecision?: WorkspaceDecisionRecord | null;
  isD1DecisionStale?: boolean;
}

const parseDraftItems = (text: string): string[] =>
  text.split(',').map(item => item.trim()).filter(Boolean);

const numericValue = (value: DraftNumericInput | undefined): number | undefined => {
  if (typeof value === 'number') return value;
  return value?.value;
};

const numericInputValue = (value: DraftNumericInput | undefined): string => {
  const resolved = numericValue(value);
  return resolved === undefined ? '' : String(resolved);
};

type ParsedDraftNumber =
  | { ok: true; value: number | undefined }
  | { ok: false; message: string };

const DECIMAL_NUMBER_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8789').replace(/\/$/, '');
const PROJECT_ID = 'rotterdam-m4h-pilot-project';

interface DesignAreaPreview {
  status: 'CLIPPED' | 'UNCHANGED' | 'EMPTY' | 'MULTIPLE_COMPONENTS';
  clipped: boolean;
  area_m2: number;
  component_count: number;
  geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: any } | null;
}

interface DesignAreaPreviewState {
  preview: DesignAreaPreview;
  candidateCoordinates: [number, number][];
  studyAreaGeometry: unknown;
}

const parseOptionalDraftNumber = (raw: string, label: string): ParsedDraftNumber => {
  const normalized = raw.trim();
  if (!normalized) return { ok: true, value: undefined };
  const value = Number(normalized);
  if (!DECIMAL_NUMBER_PATTERN.test(normalized) || !Number.isFinite(value) || value < 0) {
    return {
      ok: false,
      message: `${label} must be a finite non-negative number in decimal notation. Leave the field blank to unset this optional draft target.`,
    };
  }
  return { ok: true, value };
};

function polygonErrorMessage(reason: string): string {
  if (reason === 'STUDY_AREA_UNAVAILABLE') {
    return 'Rejected: Active StudyArea geometry is unavailable. Reload the verified site context before adding a zone.';
  }
  if (reason === 'INVALID_STUDY_AREA_GEOMETRY') {
    return 'Rejected: Active StudyArea geometry is invalid; no zone was added.';
  }
  if (reason === 'OUTSIDE_STUDY_AREA') {
    return 'Rejected: Polygon must be fully within one polygon component of the active StudyArea, including its boundary and holes.';
  }
  return 'Rejected: Polygon is empty, non-finite, self-intersecting, or has no positive area.';
}

export const SidebarBrief: React.FC<SidebarBriefProps> = ({
  zones,
  explorationDesignArea = null,
  isSyncing,
  activeDrawnCoords,
  activeDrawnPurpose = 'ZONE',
  isDrawingZone,
  onStartDrawPolygon,
  onClearDrawnPolygon,
  onAddZone,
  onRemoveZone,
  onUpdateZone,
  onSetExplorationDesignArea,
  studyAreaGeometry,
  workspaceDecision = null,
  isD1DecisionStale = false,
}) => {
  const t = useT();
  const [name, setName] = useState('');
  const [targetUse, setTargetUse] = useState('Mixed-Use Innovation Hub');
  const [programDemandsText, setProgramDemandsText] = useState('');
  const [openSpaceDemandsText, setOpenSpaceDemandsText] = useState('');
  const [author, setAuthor] = useState('designer');
  const [originalText, setOriginalText] = useState('');
  const [constraintsText, setConstraintsText] = useState('');
  const [preferencesText, setPreferencesText] = useState('');
  const [targetFar, setTargetFar] = useState('');
  const [targetHeight, setTargetHeight] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [editingZone, setEditingZone] = useState<SpatialZone | null>(null);
  const [designAreaPreviewState, setDesignAreaPreviewState] = useState<DesignAreaPreviewState | null>(null);
  const [isPreviewingDesignArea, setIsPreviewingDesignArea] = useState(false);
  const designAreaPreview = designAreaPreviewState
    && designAreaPreviewState.candidateCoordinates === activeDrawnCoords
    && designAreaPreviewState.studyAreaGeometry === studyAreaGeometry
    ? designAreaPreviewState.preview
    : null;

  const resetEditForm = () => {
    setEditingZone(null);
    setName('');
    setTargetUse('Mixed-Use Innovation Hub');
    setProgramDemandsText('');
    setOpenSpaceDemandsText('');
    setAuthor('designer');
    setOriginalText('');
    setConstraintsText('');
    setPreferencesText('');
    setTargetFar('');
    setTargetHeight('');
    setErrorMessage(null);
  };

  const handleEditZone = (zone: SpatialZone) => {
    if (isSyncing || editingZone) return;
    setEditingZone(zone);
    setName(zone.name);
    setTargetUse(zone.target_use);
    setProgramDemandsText((zone.program_demands ?? []).filter(item => item !== zone.target_use).join(', '));
    setOpenSpaceDemandsText((zone.open_space_demands ?? []).join(', '));
    setAuthor(zone.author || 'designer');
    setOriginalText(zone.original_text ?? zone.notes ?? '');
    setConstraintsText((zone.draft_constraints ?? []).join(', '));
    setPreferencesText((zone.draft_preferences ?? []).join(', '));
    setTargetFar(numericInputValue(zone.target_far));
    setTargetHeight(numericInputValue(zone.target_height_m));
    setErrorMessage(null);
  };

  const handleUsePreset = () => {
    if (isSyncing || editingZone) return;
    // Explicit preset option for quick testing in Keilehaven basin
    const presetCoords: [number, number][] = [
      [88900, 435700],
      [89250, 435700],
      [89250, 436000],
      [88900, 436000],
      [88900, 435700],
    ];
    const polygon = preparePolygonWithinStudyArea(presetCoords, studyAreaGeometry);
    if (!polygon.ok) {
      setErrorMessage(polygonErrorMessage(polygon.reason));
      return;
    }

    setName('Keilehaven Innovation Basin');
    setOriginalText('Waterfront mixed-use maker precinct preserving industrial heritage');
    setConstraintsText('Preserve quay access, Max 15m building height on water edge');
    setProgramDemandsText('');
    setOpenSpaceDemandsText('');
    setPreferencesText('');
    setTargetFar('2.5');
    setTargetHeight('24');
    onClearDrawnPolygon();
    // Use callback with preset
    const newZone: SpatialZone = {
      zone_id: `brief-zone-${Date.now().toString(36)}`,
      name: 'Keilehaven Innovation Basin',
      target_use: 'Mixed-Use Innovation Hub',
      program_demands: ['Mixed-Use Innovation Hub'],
      open_space_demands: [],
      target_far: 2.5,
      target_height_m: 24,
      geometry: {
        type: 'Polygon',
        coordinates: [polygon.closedRing],
      },
      status: 'DRAFT_PENDING_HUMAN_DECISION',
      author: 'designer',
      revision: 1,
      original_text: 'Waterfront mixed-use maker precinct preserving industrial heritage',
      draft_constraints: ['Preserve quay access', 'Max 15m building height on water edge'],
      draft_preferences: [],
      notes: 'Waterfront mixed-use maker precinct preserving industrial heritage',
    };
    onAddZone(newZone);
    setErrorMessage(null);
  };

  const handleCreateZone = (e: React.FormEvent) => {
    e.preventDefault();
    if (isSyncing) return;
    setErrorMessage(null);

    if (activeDrawnPurpose === 'EXPLORATION_DESIGN_AREA' && activeDrawnCoords) {
      setErrorMessage('This polygon is an Exploration Design Area. Save it in the separate conceptual-area control; it is not a demand zone.');
      return;
    }

    if (!name.trim()) {
      setErrorMessage('Zone name is required.');
      return;
    }

    const parsedFar = parseOptionalDraftNumber(targetFar, 'FAR');
    if (!parsedFar.ok) {
      setErrorMessage(parsedFar.message);
      return;
    }
    const parsedHeight = parseOptionalDraftNumber(targetHeight, 'Height');
    if (!parsedHeight.ok) {
      setErrorMessage(parsedHeight.message);
      return;
    }

    const programDemands = Array.from(new Set([targetUse.trim(), ...parseDraftItems(programDemandsText)]));
    const openSpaceDemands = parseDraftItems(openSpaceDemandsText);
    const constraints = parseDraftItems(constraintsText);
    const preferences = parseDraftItems(preferencesText);

    if (editingZone) {
      onUpdateZone({
        ...editingZone,
        name: name.trim(),
        target_use: targetUse,
        program_demands: programDemands,
        open_space_demands: openSpaceDemands,
        target_far: parsedFar.value,
        target_height_m: parsedHeight.value,
        status: 'DRAFT_PENDING_HUMAN_DECISION',
        author: author.trim() || 'designer',
        revision: (editingZone.revision ?? 0) + 1,
        original_text: originalText.trim(),
        draft_constraints: constraints,
        draft_preferences: preferences,
        notes: originalText.trim(),
      });
      resetEditForm();
      return;
    }

    // Must have drawn coordinates
    if (!activeDrawnCoords || activeDrawnCoords.length < 3) {
      setErrorMessage('Rejected: Empty polygon. Please draw a polygon on the 2D map first.');
      return;
    }

    const polygon = preparePolygonWithinStudyArea(activeDrawnCoords, studyAreaGeometry);
    if (!polygon.ok) {
      setErrorMessage(polygonErrorMessage(polygon.reason));
      return;
    }

    const newZone: SpatialZone = {
      zone_id: `brief-zone-${Date.now().toString(36)}`,
      name: name.trim(),
      target_use: targetUse,
      program_demands: programDemands,
      open_space_demands: openSpaceDemands,
      target_far: parsedFar.value,
      target_height_m: parsedHeight.value,
      geometry: {
        type: 'Polygon',
        coordinates: [polygon.closedRing],
      },
      status: 'DRAFT_PENDING_HUMAN_DECISION',
      author: author.trim() || 'designer',
      revision: 1,
      original_text: originalText.trim(),
      draft_constraints: constraints,
      draft_preferences: preferences,
      notes: originalText.trim(),
    };

    onAddZone(newZone);
    onClearDrawnPolygon();
    setName('');
    setOriginalText('');
    setProgramDemandsText('');
    setOpenSpaceDemandsText('');
    setConstraintsText('');
    setPreferencesText('');
    setTargetFar('');
    setTargetHeight('');
    setErrorMessage(null);
  };

  const handleSaveExplorationDesignArea = async () => {
    if (isSyncing) return;
    setErrorMessage(null);
    if (!activeDrawnCoords || activeDrawnCoords.length < 4 || activeDrawnPurpose !== 'EXPLORATION_DESIGN_AREA') {
      setErrorMessage('Draw and finish a separate Exploration Design Area polygon before saving it.');
      return;
    }
    if (!onSetExplorationDesignArea) {
      setErrorMessage('Exploration Design Area saving is unavailable in this workspace view.');
      return;
    }
    if (activeDrawnCoords.some(([x, y]) => !Number.isFinite(x) || !Number.isFinite(y))) {
      setErrorMessage('Rejected: drawn coordinates must be finite EPSG:28992 metres.');
      return;
    }
    setIsPreviewingDesignArea(true);
    setDesignAreaPreviewState(null);
    const candidateCoordinates = activeDrawnCoords;
    const previewStudyAreaGeometry = studyAreaGeometry;
    try {
      const response = await fetch(`${API_BASE}/api/v1/projects/${PROJECT_ID}/design-area/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          geometry: { type: 'Polygon', coordinates: [activeDrawnCoords] },
          horizontal_crs: 'EPSG:28992',
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(typeof body?.detail === 'string' ? body.detail : `Preview request failed (${response.status}).`);
      }
      const preview = body as DesignAreaPreview;
      setDesignAreaPreviewState({
        preview,
        candidateCoordinates,
        studyAreaGeometry: previewStudyAreaGeometry,
      });
      if (preview.status === 'EMPTY') {
        setErrorMessage('The StudyArea intersection is empty. Draw an area that overlaps the StudyArea.');
      } else if (preview.status === 'MULTIPLE_COMPONENTS') {
        setErrorMessage(`The StudyArea intersection creates ${preview.component_count} separate pieces. Redraw the outline so it clips to one connected area.`);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? `Could not preview the StudyArea intersection: ${error.message}` : 'Could not preview the StudyArea intersection.');
    } finally {
      setIsPreviewingDesignArea(false);
    }
  };

  const handleConfirmDesignArea = () => {
    if (isSyncing || !onSetExplorationDesignArea || !designAreaPreview?.geometry) return;
    if (!['CLIPPED', 'UNCHANGED'].includes(designAreaPreview.status) || designAreaPreview.component_count !== 1) return;
    onSetExplorationDesignArea({
      geometry: designAreaPreview.geometry,
      crs: 'EPSG:28992',
      area_m2: designAreaPreview.area_m2,
      scope: 'EXPLORATION_DESIGN_AREA',
      status: 'DRAFT_PENDING_HUMAN_DECISION',
      author: author.trim() || 'designer',
      revision: (explorationDesignArea?.revision ?? 0) + 1,
    });
    onClearDrawnPolygon();
    setDesignAreaPreviewState(null);
  };

  const handleUseEntireStudyArea = () => {
    if (isSyncing || !onSetExplorationDesignArea) return;
    const areaM2 = measurePolygonalAreaM2(studyAreaGeometry);
    if (areaM2 === null) {
      setErrorMessage('The active StudyArea geometry is unavailable or invalid. Reload the verified site context.');
      return;
    }
    setErrorMessage(null);
    setDesignAreaPreviewState(null);
    onSetExplorationDesignArea({
      geometry: studyAreaGeometry as ExplorationDesignArea['geometry'],
      crs: 'EPSG:28992',
      area_m2: areaM2,
      scope: 'EXPLORATION_DESIGN_AREA',
      status: 'DRAFT_PENDING_HUMAN_DECISION',
      author: author.trim() || 'designer',
      revision: (explorationDesignArea?.revision ?? 0) + 1,
    });
    onClearDrawnPolygon();
  };

  const calculatedArea = activeDrawnCoords && activeDrawnCoords.length >= 3
    ? Math.round(calculatePolygonArea(activeDrawnCoords))
    : 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '4px' }}>
          {t("Spatial Brief & Zoning (CP4-4)")} </div>
        <div style={{ fontSize: '10px', color: 'var(--text-dim)' }}>
          {t("Add program and open-space demands; classify hard constraints separately from preferences.")} </div>
      </div>

      {/* Human Decision Callout */}
      <div
        id="brief-decision-callout"
        data-testid="brief-decision-callout"
        style={{
          margin: '10px 14px',
          padding: '8px 10px',
          borderRadius: 'var(--radius-sm)',
          backgroundColor: !workspaceDecision
            ? 'rgba(245, 158, 11, 0.08)'
            : isD1DecisionStale
            ? 'rgba(245, 158, 11, 0.08)'
            : 'rgba(16, 185, 129, 0.08)',
          border: `1px solid ${
            !workspaceDecision
              ? 'rgba(245, 158, 11, 0.25)'
              : isD1DecisionStale
              ? 'rgba(245, 158, 11, 0.25)'
              : 'rgba(16, 185, 129, 0.25)'
          }`,
          display: 'flex',
          gap: '6px',
        }}
      >
        {!workspaceDecision ? (
          <>
            <AlertTriangle size={14} color="var(--accent-amber)" style={{ flexShrink: 0, marginTop: '2px' }} />
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', lineHeight: '1.4' }}>
              <strong style={{ color: 'var(--accent-amber)' }}>{t("Draft Status")}</strong>{t(": Program, open-space demands, hard constraints, and preferences remain non-binding until explicit Human Decision adoption.")} </div>
          </>
        ) : isD1DecisionStale ? (
          <>
            <AlertTriangle size={14} color="var(--accent-amber)" style={{ flexShrink: 0, marginTop: '2px' }} />
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', lineHeight: '1.4' }}>
              <strong style={{ color: 'var(--accent-amber)' }}>{t("對應舊版本")}</strong>{t(": 決策")} {workspaceDecision.id} {t("綁定於 revision")} {workspaceDecision.target_version}{t("。目前工作區存在新變更，請於調整完成並同步後重新確認決策。")} </div>
          </>
        ) : (
          <>
            <CheckCircle2 size={14} color="var(--accent-emerald)" style={{ flexShrink: 0, marginTop: '2px' }} />
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', lineHeight: '1.4' }}>
              <strong style={{ color: 'var(--accent-emerald)' }}>{t("決策已確認")}</strong>{t(": 第 1 天決策")} {workspaceDecision.id}（{t(workspaceDecision.status)}{t("）已綁定至此工作區版本。")} </div>
          </>
        )}
      </div>

      <section aria-label={t("Exploration Design Area")} style={{ margin: '0 14px 10px', padding: '9px 10px', border: '1px solid rgba(250, 204, 21, 0.4)', borderRadius: 'var(--radius-sm)', background: 'rgba(250, 204, 21, 0.06)' }}>
        <div style={{ fontSize: '11px', fontWeight: 700, color: '#facc15' }}>{t("Exploration Design Area")}</div>
        <div style={{ marginTop: '4px', fontSize: '10px', lineHeight: 1.4, color: 'var(--text-muted)' }}>
          {t("A separate conceptual denominator inside the exploratory StudyArea. This is not a legal design boundary, property limit, or zoning envelope.")} </div>
        {explorationDesignArea ? (
          <div id="saved-exploration-design-area" role="status" style={{ marginTop: '6px', fontSize: '10px', color: 'var(--text-main)' }}>
            {t("Draft ·")} {explorationDesignArea.area_m2.toLocaleString()} {t("m² ·")} {explorationDesignArea.crs} {t("· revision")} {explorationDesignArea.revision}
          </div>
        ) : (
          <div style={{ marginTop: '6px', fontSize: '10px', color: 'var(--text-dim)' }}>{t("No Exploration Design Area has been saved.")}</div>
        )}
        {activeDrawnCoords && activeDrawnPurpose === 'EXPLORATION_DESIGN_AREA' && (
          <div style={{ marginTop: '7px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
            <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{t("Finished polygon ·")} {calculatedArea.toLocaleString()} {t("m²")}</span>
            <button
              type="button"
              aria-label={t("Preview clipped design area")}
              disabled={isSyncing || isPreviewingDesignArea || !onSetExplorationDesignArea}
              onClick={handleSaveExplorationDesignArea}
              style={{ padding: '5px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid #facc15', background: 'rgba(250, 204, 21, 0.12)', color: '#facc15', fontSize: '10px', fontWeight: 600 }}
            >
              {isPreviewingDesignArea ? t("Preparing preview…") : t("Preview boundary")}
            </button>
          </div>
        )}
        {designAreaPreview?.geometry && activeDrawnCoords && (
          <DesignAreaClipPreview candidateRing={activeDrawnCoords} clippedGeometry={designAreaPreview.geometry} />
        )}
        {designAreaPreview && (
          <div role="status" style={{ marginTop: '6px', fontSize: '10px', color: 'var(--text-main)' }}>
            {designAreaPreview.status === 'CLIPPED' ? t("Clipped to StudyArea") : designAreaPreview.status === 'UNCHANGED' ? t("Inside StudyArea · unchanged") : designAreaPreview.status.replaceAll('_', ' ')}
            {designAreaPreview.status !== 'EMPTY' && t(' · Area after clipping: {0} m²', { 0: designAreaPreview.area_m2.toLocaleString(undefined, { maximumFractionDigits: 1 }) })}
          </div>
        )}
        {designAreaPreview?.geometry && designAreaPreview.component_count === 1 && ['CLIPPED', 'UNCHANGED'].includes(designAreaPreview.status) && (
          <div style={{ marginTop: '7px', display: 'flex', gap: '6px' }}>
            <button
              type="button"
              aria-label={t("Confirm and save design area")}
              disabled={isSyncing}
              onClick={handleConfirmDesignArea}
              style={{ flex: 1, padding: '5px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid #facc15', background: 'rgba(250, 204, 21, 0.18)', color: '#facc15', fontSize: '10px', fontWeight: 600 }}
            >
              {t("Confirm and save")} </button>
            <button
              type="button"
              aria-label={t("Cancel design area preview")}
              disabled={isSyncing}
              onClick={() => setDesignAreaPreviewState(null)}
              style={{ padding: '5px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', background: 'var(--bg-app)', color: 'var(--text-muted)', fontSize: '10px' }}
            >
              {t("Cancel")} </button>
          </div>
        )}
        {designAreaPreview && !['CLIPPED', 'UNCHANGED'].includes(designAreaPreview.status) && (
          <button
            type="button"
            aria-label={t("Cancel design area preview")}
            disabled={isSyncing}
            onClick={() => setDesignAreaPreviewState(null)}
            style={{ marginTop: '7px', padding: '5px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', background: 'var(--bg-app)', color: 'var(--text-muted)', fontSize: '10px' }}
          >
            {t("Cancel preview")} </button>
        )}
        <button
          type="button"
          aria-label={t("Use entire StudyArea")}
          disabled={isSyncing || !studyAreaGeometry || !onSetExplorationDesignArea}
          onClick={handleUseEntireStudyArea}
          style={{ marginTop: '7px', padding: '5px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', background: 'var(--bg-app)', color: '#facc15', fontSize: '10px' }}
        >
          {t("Use entire StudyArea")} </button>
        <button
          id="btn-draw-exploration-design-area"
          type="button"
          disabled={isSyncing || isDrawingZone || !studyAreaGeometry || Boolean(editingZone)}
          onClick={() => { setErrorMessage(null); onStartDrawPolygon('EXPLORATION_DESIGN_AREA'); }}
          style={{ marginTop: '7px', padding: '5px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)', background: 'var(--bg-app)', color: '#facc15', fontSize: '10px' }}
        >
          {explorationDesignArea ? t("Draw replacement outline") : t("Draw exploration design area")}
        </button>
      </section>

      {/* Error Callout */}
      {errorMessage && (
        <div
          id="brief-validation-error"
          role="alert"
          style={{
            margin: '0 14px 10px 14px',
            padding: '8px 10px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'rgba(244, 63, 94, 0.1)',
            border: '1px solid var(--accent-rose)',
            color: 'var(--accent-rose)',
            fontSize: '11px',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
          }}
        >
          <AlertTriangle size={14} style={{ flexShrink: 0 }} />
          <span>{t(errorMessage)}</span>
        </div>
      )}

      {/* Zone Creation Form */}
      <form onSubmit={handleCreateZone} style={{ padding: '0 14px 12px 14px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <fieldset disabled={isSyncing} style={{ border: 0, margin: 0, padding: 0, minWidth: 0, display: 'contents' }}>
        <input
          id="input-zone-name"
          type="text"
          placeholder={t("Zone Name (e.g. Keilehaven Maker Hub)")}
          value={name}
          onChange={e => setName(e.target.value)}
          style={{ width: '100%', fontSize: '12px' }}
        />

        <div style={{ display: 'flex', gap: '6px' }}>
          <select
            id="select-zone-use"
            value={targetUse}
            onChange={e => setTargetUse(e.target.value)}
            style={{ flex: 1, fontSize: '11px' }}
          >
            {!['Mixed-Use Innovation Hub', 'Creative Production / Maker', 'Harborfront Public Realm', 'Water-Sensitive Eco-Buffer', 'Circular Tech Incubator'].includes(targetUse) && (
              <option value={targetUse}>{t(targetUse)}</option>
            )}
            <option value="Mixed-Use Innovation Hub">{t("Mixed-Use Innovation Hub")}</option>
            <option value="Creative Production / Maker">{t("Creative Production / Maker")}</option>
            <option value="Harborfront Public Realm">{t("Harborfront Public Realm")}</option>
            <option value="Water-Sensitive Eco-Buffer">{t("Water-Sensitive Eco-Buffer")}</option>
            <option value="Circular Tech Incubator">{t("Circular Tech Incubator")}</option>
          </select>
          <input
            id="input-zone-author"
            type="text"
            placeholder={t("Author")}
            value={author}
            onChange={e => setAuthor(e.target.value)}
            style={{ width: '80px', fontSize: '11px' }}
          />
        </div>

        <input
          id="input-zone-notes"
          type="text"
          aria-label={t("Original design text or intention")}
          placeholder={t("Original design text / intention...")}
          value={originalText}
          onChange={e => setOriginalText(e.target.value)}
          style={{ width: '100%', fontSize: '11px' }}
        />

        <label htmlFor="input-zone-program-demands" style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '-6px' }}>
          {t("Additional program demands (draft; comma-separated)")} </label>
        <input
          id="input-zone-program-demands"
          type="text"
          placeholder={t("e.g. fabrication workshops, shared tool library")}
          value={programDemandsText}
          onChange={e => setProgramDemandsText(e.target.value)}
          style={{ width: '100%', fontSize: '11px' }}
        />

        <label htmlFor="input-zone-open-space-demands" style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '-6px' }}>
          {t("Open-space demands (draft; comma-separated)")} </label>
        <input
          id="input-zone-open-space-demands"
          type="text"
          placeholder={t("e.g. public courtyard, shaded route")}
          value={openSpaceDemandsText}
          onChange={e => setOpenSpaceDemandsText(e.target.value)}
          style={{ width: '100%', fontSize: '11px' }}
        />

        <label htmlFor="input-zone-constraints" style={{ fontSize: '10px', color: 'var(--accent-amber)', marginBottom: '-6px' }}>
          {t("Hard constraints (draft; not active)")} </label>
        <input
          id="input-zone-constraints"
          type="text"
          aria-label={t("Hard constraints, draft and not active")}
          placeholder={t("e.g. preserve tree row, keep quay access")}
          value={constraintsText}
          onChange={e => setConstraintsText(e.target.value)}
          style={{ width: '100%', fontSize: '11px' }}
        />

        <label htmlFor="input-zone-preferences" style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '-6px' }}>
          {t("Preferences (non-binding draft)")} </label>
        <input
          id="input-zone-preferences"
          type="text"
          placeholder={t("e.g. reuse existing structures, active ground floors")}
          value={preferencesText}
          onChange={e => setPreferencesText(e.target.value)}
          style={{ width: '100%', fontSize: '11px' }}
        />

        <div style={{ display: 'flex', gap: '6px' }}>
          <input
            id="input-zone-far"
            type="text"
            inputMode="decimal"
            aria-label={t("Target FAR (draft ratio)")}
            placeholder={t("Target FAR")}
            value={targetFar}
            onChange={e => setTargetFar(e.target.value)}
            style={{ flex: 1, fontSize: '11px' }}
          />
          <input
            id="input-zone-height"
            type="text"
            inputMode="decimal"
            aria-label={t("Maximum height (draft metres)")}
            placeholder={t("Max Height (m)")}
            value={targetHeight}
            onChange={e => setTargetHeight(e.target.value)}
            style={{ flex: 1, fontSize: '11px' }}
          />
        </div>
        <div style={{ fontSize: '9px', color: 'var(--text-dim)' }}>
          {t("FAR and height are non-binding draft targets; enter finite, non-negative numbers. Leave blank to unset an optional target.")} </div>

        {/* Keep the saved geometry fixed while editing text and draft parameters. */}
        {editingZone ? (
          <div role="status" style={{
            padding: '8px 10px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'var(--bg-app)',
            border: '1px solid var(--border-subtle)',
            color: 'var(--text-muted)',
            fontSize: '10px',
          }}>
            {t("Editing brief text and parameters only; the saved polygon boundary will be retained.")} </div>
        ) : (
        <div style={{
          padding: '8px 10px',
          borderRadius: 'var(--radius-sm)',
          backgroundColor: activeDrawnCoords && activeDrawnCoords.length >= 3 ? 'rgba(192, 132, 252, 0.12)' : 'var(--bg-app)',
          border: `1px dashed ${activeDrawnCoords && activeDrawnCoords.length >= 3 ? 'var(--accent-cyan)' : 'var(--border-subtle)'}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div>
            <div style={{ fontSize: '11px', fontWeight: 600, color: activeDrawnCoords && activeDrawnCoords.length >= 3 ? 'var(--accent-cyan)' : 'var(--text-dim)' }}>
              {activeDrawnCoords && activeDrawnCoords.length >= 3
                ? t("Polygon Sketched ({0} pts)", {"0": activeDrawnCoords.length})
                : isDrawingZone
                ? t("Click on map to place vertices...")
                : t("No polygon sketched yet")}
            </div>
            {calculatedArea > 0 && (
              <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                {t("Calculated Area:")} {calculatedArea.toLocaleString()} {t("m²")} </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: '4px' }}>
            {activeDrawnCoords && activeDrawnCoords.length > 0 ? (
              <button
                type="button"
                id="btn-clear-drawn-polygon"
                onClick={onClearDrawnPolygon}
                style={{ padding: '4px 8px', fontSize: '10px', color: 'var(--accent-rose)', backgroundColor: 'transparent', border: '1px solid rgba(244, 63, 94, 0.3)', borderRadius: 'var(--radius-sm)' }}
              >
                {t("Clear")} </button>
            ) : (
              <button
                type="button"
                id="btn-start-draw-zone"
                onClick={() => onStartDrawPolygon('ZONE')}
                style={{
                  padding: '4px 8px',
                  fontSize: '10px',
                  color: isDrawingZone ? '#090d16' : 'var(--accent-cyan)',
                  backgroundColor: isDrawingZone ? 'var(--accent-cyan)' : 'transparent',
                  border: '1px solid var(--accent-cyan)',
                  borderRadius: 'var(--radius-sm)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '3px',
                }}
              >
                <Edit3 size={11} /> {isDrawingZone ? t("Drawing...") : t("Draw on Map")}
              </button>
            )}
          </div>
        </div>
        )}

        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            id="btn-add-zone"
            type="submit"
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              backgroundColor: 'var(--bg-surface-elevated)',
              color: 'var(--accent-cyan)',
              border: '1px solid var(--border-focus)',
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '11px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <Plus size={13} /> {editingZone ? t("Save Draft Zone") : t("Add Draft Zone")}
          </button>
          {editingZone && (
            <button
              id="btn-cancel-zone-edit"
              type="button"
              aria-label={t("Cancel edit")}
              onClick={resetEditForm}
              style={{
                padding: '6px 8px',
                fontSize: '10px',
                color: 'var(--text-muted)',
                backgroundColor: 'var(--bg-app)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
              }}
            >
              {t("Cancel")} </button>
          )}
          <button
            id="btn-use-preset-polygon"
            type="button"
            onClick={handleUsePreset}
            disabled={editingZone !== null}
            title={t("Load Keilehaven preset boundary for testing")}
            style={{
              padding: '6px 8px',
              fontSize: '10px',
              color: 'var(--text-dim)',
              backgroundColor: 'var(--bg-app)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              cursor: editingZone ? 'not-allowed' : 'pointer',
            }}
          >
            {t("Preset")} </button>
        </div>
        </fieldset>
      </form>

      {/* Zone List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 14px' }}>
        {zones.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'var(--text-dim)', fontSize: '11px', marginTop: '16px' }}>
            {t("No draft spatial zones added yet.")} </div>
        ) : (
          zones.map(z => (
            <div
              key={z.zone_id}
              id={`brief-zone-card-${z.zone_id}`}
              style={{
                backgroundColor: 'var(--bg-surface-elevated)',
                borderRadius: 'var(--radius-sm)',
                padding: '10px',
                marginBottom: '8px',
                border: '1px solid var(--border-subtle)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '4px' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '12px', color: 'var(--text-main)' }}>
                    {z.name}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--accent-cyan)' }}>
                    {t(z.target_use)} {t("· author:")} {z.author || t("designer")}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: '4px' }}>
                  <button
                    id={`btn-edit-zone-${z.zone_id}`}
                    type="button"
                    aria-label={t("Edit zone {0}", {"0": z.name})}
                    onClick={() => handleEditZone(z)}
                    disabled={isSyncing || editingZone !== null}
                    style={{ color: 'var(--accent-cyan)', padding: '2px', backgroundColor: 'transparent' }}
                  >
                    <Edit3 size={13} />
                  </button>
                  <button
                    id={`btn-remove-zone-${z.zone_id}`}
                    type="button"
                    aria-label={t("Remove zone {0}", {"0": z.name})}
                    onClick={() => onRemoveZone(z.zone_id)}
                    disabled={isSyncing || editingZone !== null}
                    style={{ color: 'var(--accent-rose)', padding: '2px', backgroundColor: 'transparent' }}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>

              {z.original_text && (
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px', fontStyle: 'italic' }}>
                  "{z.original_text}"
                </div>
              )}

              {z.program_demands && z.program_demands.length > 0 && (
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  <strong>{t("Program demands (draft):")}</strong> {z.program_demands.join(' · ')}
                </div>
              )}

              {z.open_space_demands && z.open_space_demands.length > 0 && (
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  <strong>{t("Open-space demands (draft):")}</strong> {z.open_space_demands.join(' · ')}
                </div>
              )}

              {z.draft_constraints && z.draft_constraints.length > 0 && (
                <div style={{ marginTop: '5px' }}>
                  <div style={{ fontSize: '9px', color: 'var(--accent-amber)', marginBottom: '3px' }}>{t("Hard constraints (draft; inactive)")}</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px' }}>
                    {z.draft_constraints.map((c, idx) => (
                      <span
                        key={idx}
                        style={{
                          fontSize: '9px',
                          padding: '1px 5px',
                          backgroundColor: 'var(--bg-app)',
                          color: 'var(--accent-amber)',
                          borderRadius: '2px',
                          border: '1px solid rgba(245, 158, 11, 0.2)',
                        }}
                      >
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {z.draft_preferences && z.draft_preferences.length > 0 && (
                <div style={{ marginTop: '5px' }}>
                  <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginBottom: '3px' }}>{t("Preferences (non-binding draft)")}</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px' }}>
                    {z.draft_preferences.map((preference, idx) => (
                      <span
                        key={idx}
                        style={{
                          fontSize: '9px',
                          padding: '1px 5px',
                          backgroundColor: 'var(--bg-app)',
                          color: 'var(--accent-cyan)',
                          borderRadius: '2px',
                          border: '1px solid var(--border-subtle)',
                        }}
                      >
                        {preference}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '9px', fontFamily: 'var(--font-mono)', color: 'var(--text-dim)', marginTop: '6px' }}>
                <span>{t("FAR:")} {numericValue(z.target_far) ?? '—'} {t("| H:")} {numericValue(z.target_height_m) !== undefined ? t("{0}m", {"0": numericValue(z.target_height_m) ?? "—"}) : '—'}</span>
                <span style={{ color: 'var(--accent-amber)' }}>{t(z.status)}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

// Calculate polygon area (Shoelace formula)
function calculatePolygonArea(coords: [number, number][]): number {
  if (coords.length < 3 || coords.some(([x, y]) => !Number.isFinite(x) || !Number.isFinite(y))) return 0;
  const origin = coords[0];
  const closedCoords = coords[0][0] === coords[coords.length - 1][0]
    && coords[0][1] === coords[coords.length - 1][1]
    ? coords
    : [...coords, coords[0]];
  let area = 0;
  const n = closedCoords.length - 1;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    area += (closedCoords[i][0] - origin[0]) * (closedCoords[j][1] - origin[1]);
    area -= (closedCoords[j][0] - origin[0]) * (closedCoords[i][1] - origin[1]);
  }
  return Math.abs(area) / 2;
}
