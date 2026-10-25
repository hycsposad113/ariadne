import type { ExplorationDesignArea, SourceAttribution, SyntaxLayer } from '../types';
import { screenToEpsg28992, type RenderTransform } from './geoTransform';
import type { FigureWorkspaceCitation, SchematicFigureStudyArea } from './schematicFigure';
import { buildSyntaxHeatmapClassification } from './syntaxHeatmap';

export interface MapFigureContext {
  projectId: string;
  workspace: FigureWorkspaceCitation | null;
  studyArea: SchematicFigureStudyArea | null;
  hasUnsavedChanges: boolean;
  sourcePackageRevision: string | null;
  sourceSnapshotIds: string[];
  sourceAttributions: SourceAttribution[];
  buildingCount: number;
  roadCount: number;
  spatialZoneCount: number;
  explorationDesignArea?: ExplorationDesignArea | null;
  selectedFeatureIds: string[];
  activeSyntaxLayer: SyntaxLayer | null;
  transform: RenderTransform;
  canvasWidth: number;
  canvasHeight: number;
  exportedAtUtc?: string;
}

export interface MapFigureAnalysisLayer {
  id: string;
  title: string;
  metricKey: string;
  radiusMeters: number;
  unit: string;
  calculationStatus: string;
  dataReadiness: string;
  resultStatus: 'NOT_COMPUTED' | 'COMPUTED_EXPLORATORY' | 'COMPUTED_REQUIRES_REVIEW';
  formulaVersion: string | null;
  sourceManifestSha256: string | null;
  resultSha256: string | null;
  limitations: string;
  networkMode?: string;
}

export interface MapFigureMetadata {
  figureVersion: 'week4-analysis-map-v1';
  projectId: string;
  workspace: { id: string; revision: number | string; status: string };
  studyArea: { id: string; revision: number; status: string };
  sourcePackageRevision: string | null;
  sourceSnapshotIds: string[];
  sourceAttributions: SourceAttribution[];
  crs: 'EPSG:28992';
  exportedAtUtc: string;
  featureCounts: { buildingsLoaded: number; roadsLoaded: number; spatialZones: number };
  explorationDesignArea: {
    scope: 'EXPLORATION_DESIGN_AREA';
    crs: 'EPSG:28992';
    areaM2: number;
    status: 'DRAFT_PENDING_HUMAN_DECISION';
    revision: number;
  } | null;
  selectedFeatureIds: string[];
  analysisLayer: MapFigureAnalysisLayer | null;
  mapExtent: { minEasting: number; minNorthing: number; maxEasting: number; maxNorthing: number };
  scaleBar: { distanceMeters: number; lengthPixels: number; metersPerPixel: number; unit: 'm' };
  legend: Array<{ label: string; color: string }>;
  limitations: string[];
}

const BASE_LEGEND = [
  { label: 'StudyArea outline', color: '#38bdf8' },
  { label: 'Preserved building', color: '#10b981' },
  { label: 'Editable building', color: '#38bdf8' },
  { label: 'Undecided building', color: '#64748b' },
  { label: 'Road segment', color: '#475569' },
  { label: 'Selected building', color: '#facc15' },
  { label: 'Selected road', color: '#ffffff' },
  { label: 'Draft brief zone', color: '#c084fc' },
  { label: 'Exploration Design Area (conceptual only)', color: '#facc15' },
] as const;

export function canExportMapFigure(
  context: Pick<MapFigureContext, 'projectId' | 'workspace' | 'studyArea' | 'hasUnsavedChanges'>,
): boolean {
  return Boolean(
    context.projectId.trim()
    && context.hasUnsavedChanges === false
    && context.workspace
    && context.studyArea
    && context.workspace.status !== 'STALE'
    && context.workspace.project_id === context.projectId
    && context.workspace.study_area_id === context.studyArea.id,
  );
}

export function selectMapScaleBar(input: {
  zoom: number;
  canvasWidth: number;
  sceneWidth: number;
}): { distanceMeters: number; lengthPixels: number; metersPerPixel: number; unit: 'm' } {
  if (!Number.isFinite(input.zoom) || input.zoom <= 0
      || !Number.isFinite(input.canvasWidth) || input.canvasWidth <= 0
      || !Number.isFinite(input.sceneWidth) || input.sceneWidth <= 0) {
    throw new Error('A positive metric map transform is required for a scale bar.');
  }

  const pixelsPerMeter = input.zoom * input.sceneWidth / input.canvasWidth;
  const candidates: number[] = [];
  for (let exponent = -3; exponent <= 9; exponent += 1) {
    for (const factor of [1, 2, 5]) candidates.push(factor * (10 ** exponent));
  }
  const distanceMeters = candidates
    .map((distance) => ({ distance, length: distance * pixelsPerMeter }))
    .filter(({ length }) => length >= 120 && length <= 260)
    .sort((a, b) => Math.abs(a.length - 180) - Math.abs(b.length - 180))[0]?.distance
    ?? candidates.sort((a, b) => Math.abs(a * pixelsPerMeter - 180) - Math.abs(b * pixelsPerMeter - 180))[0];

  return {
    distanceMeters,
    lengthPixels: distanceMeters * pixelsPerMeter,
    metersPerPixel: 1 / pixelsPerMeter,
    unit: 'm',
  };
}

export function buildMapFigureMetadata(context: MapFigureContext): MapFigureMetadata {
  if (context.hasUnsavedChanges) {
    throw new Error('Map figure export requires a synchronized workspace; unsaved workspace changes are present.');
  }
  if (!canExportMapFigure(context)) {
    throw new Error('A saved workspace for the active StudyArea is required for a provenance-linked map figure.');
  }
  if (context.canvasWidth <= 0 || context.canvasHeight <= 0) {
    throw new Error('The rendered 2D map viewport is empty.');
  }

  const workspace = context.workspace!;
  const studyArea = context.studyArea!;
  const sourceSnapshotIds = [...new Set(context.sourceSnapshotIds.map((id) => id.trim()).filter(Boolean))].sort();
  const selectedFeatureIds = [...new Set(context.selectedFeatureIds.map((id) => id.trim()).filter(Boolean))].sort();
  const lowerLeft = screenToEpsg28992(0, context.canvasHeight, context.transform);
  const upperRight = screenToEpsg28992(context.canvasWidth, 0, context.transform);
  const layer = context.activeSyntaxLayer;
  const getFigureModeLabel = (radiusM: number): string => {
    if (radiusM <= 800) return 'pedestrian (行人路網 800m)';
    if (radiusM <= 2000) return 'bicycle (自行車路網 2km RVV)';
    return 'motor_vehicle (汽車路網 10km)';
  };
  const analysisLayer: MapFigureAnalysisLayer | null = layer ? {
    id: layer.layer_id,
    title: layer.title,
    metricKey: layer.metric_key,
    radiusMeters: layer.radius_m,
    unit: layer.unit,
    calculationStatus: layer.calculation_status,
    dataReadiness: layer.data_readiness,
    resultStatus: layer.calculation_status !== 'COMPUTED'
      ? 'NOT_COMPUTED'
      : layer.exploratory_only || !layer.formal_result_eligible
        ? 'COMPUTED_EXPLORATORY'
        : 'COMPUTED_REQUIRES_REVIEW',
    formulaVersion: layer.formula_version ?? null,
    sourceManifestSha256: layer.source_manifest_sha256 ?? null,
    resultSha256: layer.syntax_result_sha256 ?? null,
    limitations: layer.limitations,
    networkMode: getFigureModeLabel(layer.radius_m),
  } : null;

  const syntaxLegendEntries: Array<{ label: string; color: string }> = [];
  if (layer && layer.segment_values && Object.keys(layer.segment_values).length > 0) {
    const classification = buildSyntaxHeatmapClassification(layer.segment_values);
    if (classification.hasData) {
      for (const range of classification.ranges) {
        syntaxLegendEntries.push({
          label: `${range.label}: ${range.min.toFixed(2)}–${range.max.toFixed(2)}`,
          color: range.color,
        });
      }
      syntaxLegendEntries.push({
        label: 'Uncomputed / Excluded segments',
        color: '#64748b',
      });
    }
  }

  const limitations = [
    'The StudyArea is confirmed for exploration only. This map does not establish legal boundaries, parcel ownership, zoning compliance, or legal buildability.',
    'The Exploration Design Area, when present, is a conceptual denominator inside the StudyArea and is not a legal design boundary.',
    'Unknown building heights, uses, road access, and source gaps remain unavailable; unknown values are not zero.',
    analysisLayer === null
      ? 'No active analysis result is displayed; this figure shows spatial context only and infers no metric value.'
      : analysisLayer.resultStatus === 'NOT_COMPUTED'
        ? `The selected layer is not computed (${analysisLayer.dataReadiness}); missing values are unavailable, not zero.`
        : analysisLayer.resultStatus === 'COMPUTED_EXPLORATORY'
          ? `The selected ${analysisLayer.radiusMeters} m ${analysisLayer.metricKey} layer is exploratory only; its source coverage is insufficient for a regional result.`
          : `The selected result is computed but requires source and method review before formal use: ${analysisLayer.dataReadiness}.`,
    sourceSnapshotIds.length === 0 || !context.sourcePackageRevision
      ? 'Source package or snapshot references are unavailable; source completeness must not be inferred from this view.'
      : 'Source completeness and attribute availability remain limited to the listed package and snapshots.',
    'Colors show the current rendered layer and selected features; they are not a design recommendation or planning approval.',
  ];

  return {
    figureVersion: 'week4-analysis-map-v1',
    projectId: context.projectId,
    workspace: { id: workspace.workspace_id, revision: workspace.revision, status: workspace.status },
    studyArea: { id: studyArea.id, revision: studyArea.revision, status: studyArea.status },
    sourcePackageRevision: context.sourcePackageRevision,
    sourceSnapshotIds,
    sourceAttributions: context.sourceAttributions
      .map((item) => ({
        publisher: item.publisher.trim() || 'UNAVAILABLE',
        license: item.license.trim() || 'UNAVAILABLE',
        dataset_snapshot_ids: [...new Set(item.dataset_snapshot_ids.map((id) => id.trim()).filter(Boolean))].sort(),
      }))
      .sort((a, b) => `${a.publisher}\u0000${a.license}`.localeCompare(`${b.publisher}\u0000${b.license}`)),
    crs: 'EPSG:28992',
    exportedAtUtc: context.exportedAtUtc ?? new Date().toISOString(),
    featureCounts: {
      buildingsLoaded: Math.max(0, Math.floor(context.buildingCount)),
      roadsLoaded: Math.max(0, Math.floor(context.roadCount)),
      spatialZones: Math.max(0, Math.floor(context.spatialZoneCount)),
    },
    explorationDesignArea: context.explorationDesignArea ? {
      scope: context.explorationDesignArea.scope,
      crs: context.explorationDesignArea.crs,
      areaM2: context.explorationDesignArea.area_m2,
      status: context.explorationDesignArea.status,
      revision: context.explorationDesignArea.revision,
    } : null,
    selectedFeatureIds,
    analysisLayer,
    mapExtent: {
      minEasting: Math.min(lowerLeft[0], upperRight[0]),
      minNorthing: Math.min(lowerLeft[1], upperRight[1]),
      maxEasting: Math.max(lowerLeft[0], upperRight[0]),
      maxNorthing: Math.max(lowerLeft[1], upperRight[1]),
    },
    scaleBar: selectMapScaleBar({
      zoom: context.transform.zoom,
      canvasWidth: context.canvasWidth,
      sceneWidth: Math.max(1440, context.canvasWidth) - 80,
    }),
    legend: [
      ...(context.explorationDesignArea
        ? [...BASE_LEGEND]
        : BASE_LEGEND.filter((item) => item.label !== 'Exploration Design Area (conceptual only)')),
      ...syntaxLegendEntries,
    ],
    limitations,
  };
}

function wrapText(context: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = '';
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (line && context.measureText(candidate).width > maxWidth) {
      lines.push(line);
      line = word;
    } else {
      line = candidate;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function drawParagraph(
  context: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
  color: string,
): number {
  const lines = wrapText(context, text, maxWidth);
  context.fillStyle = color;
  lines.forEach((line, index) => context.fillText(line, x, y + index * lineHeight));
  return y + lines.length * lineHeight;
}

function formatScaleDistance(meters: number): string {
  return Number.isInteger(meters) ? `${meters} m` : `${Number(meters.toFixed(3))} m`;
}

export function composeMapFigure(source: HTMLCanvasElement, metadata: MapFigureMetadata): HTMLCanvasElement {
  const sourceWidth = source.width;
  const sourceHeight = source.height;
  if (sourceWidth <= 0 || sourceHeight <= 0) throw new Error('The rendered 2D map viewport is empty.');

  const canvas = document.createElement('canvas');
  const width = Math.max(1440, sourceWidth);
  const margin = 40;
  const sceneWidth = width - margin * 2;
  const sceneScale = sceneWidth / sourceWidth;
  const sceneHeight = Math.round(sourceHeight * sceneScale);
  const headerHeight = 126;
  const sceneTop = headerHeight + 24;
  const footerTop = sceneTop + sceneHeight + 24;
  const panelGap = 28;
  const panelPadding = 24;
  const innerWidth = width - margin * 2 - panelGap;
  const leftWidth = Math.round(innerWidth * 0.53);
  const rightWidth = innerWidth - leftWidth;
  const leftTextWidth = leftWidth - panelPadding * 2;
  const rightTextWidth = rightWidth - panelPadding * 2;
  const bodySize = 15;
  const bodyLineHeight = 22;
  const metadataRows = [
    `Project: ${metadata.projectId}`,
    `Workspace: ${metadata.workspace.id} · revision ${metadata.workspace.revision} · ${metadata.workspace.status}`,
    `StudyArea: ${metadata.studyArea.id} · record revision ${metadata.studyArea.revision} · ${metadata.studyArea.status}`,
    `CRS: ${metadata.crs} · extent: ${metadata.mapExtent.minEasting.toFixed(1)}, ${metadata.mapExtent.minNorthing.toFixed(1)} to ${metadata.mapExtent.maxEasting.toFixed(1)}, ${metadata.mapExtent.maxNorthing.toFixed(1)}`,
    `Source package: ${metadata.sourcePackageRevision ?? 'UNAVAILABLE'}`,
    `Source attribution: ${metadata.sourceAttributions.length
      ? metadata.sourceAttributions.map((item) => `${item.publisher} — ${item.license}`).join('; ')
      : 'UNAVAILABLE'}`,
    `Source snapshot IDs: ${metadata.sourceSnapshotIds.length ? metadata.sourceSnapshotIds.join(', ') : 'UNAVAILABLE'}`,
    `Analysis layer: ${metadata.analysisLayer ? `${metadata.analysisLayer.title} · ${metadata.analysisLayer.metricKey} · ${metadata.analysisLayer.radiusMeters} m · ${metadata.analysisLayer.resultStatus}` : 'NO ACTIVE ANALYSIS RESULT'}`,
    `Network mode / Method: ${metadata.analysisLayer ? `${metadata.analysisLayer.networkMode ?? 'UNAVAILABLE'} · PST 3.3.1 Angular Segment` : 'UNAVAILABLE'}`,
    `Method/hash: ${metadata.analysisLayer?.formulaVersion ?? 'UNAVAILABLE'} · source ${metadata.analysisLayer?.sourceManifestSha256 ?? 'UNAVAILABLE'} · result ${metadata.analysisLayer?.resultSha256 ?? 'UNAVAILABLE'}`,
    `Loaded features: ${metadata.featureCounts.buildingsLoaded} buildings · ${metadata.featureCounts.roadsLoaded} roads · ${metadata.featureCounts.spatialZones} draft zones`,
    `Selected source feature IDs: ${metadata.selectedFeatureIds.length ? metadata.selectedFeatureIds.join(', ') : 'none'}`,
    `Exported UTC: ${metadata.exportedAtUtc}`,
  ];
  const measureCanvas = document.createElement('canvas').getContext('2d');
  if (!measureCanvas) throw new Error('Canvas text rendering is unavailable.');
  measureCanvas.font = `${bodySize}px Arial, sans-serif`;
  const leftLineCount = metadataRows.reduce((count, row) => count + wrapText(measureCanvas, row, leftTextWidth).length, 0);
  const rightLineCount = metadata.limitations.reduce((count, row) => count + wrapText(measureCanvas, row, rightTextWidth).length, 0);
  const legendRows = Math.ceil(metadata.legend.length / 2);
  const footerHeight = Math.max(
    430,
    panelPadding * 2 + 42 + leftLineCount * bodyLineHeight,
    panelPadding * 2 + 48 + legendRows * 30 + 44 + rightLineCount * 19,
  );
  canvas.width = width;
  canvas.height = footerTop + footerHeight + margin;

  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas composition is unavailable.');
  context.fillStyle = '#eef2f6';
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.fillStyle = '#102333';
  context.fillRect(0, 0, width, headerHeight);
  context.fillStyle = '#f8fafc';
  context.font = '700 30px Arial, sans-serif';
  context.fillText('ROTTERDAM M4H · ANALYSIS MAP', margin, 44);
  context.fillStyle = '#cbd5e1';
  context.font = '16px Arial, sans-serif';
  context.fillText(`${metadata.figureVersion} · ${metadata.analysisLayer?.resultStatus ?? 'NO_ACTIVE_ANALYSIS_LAYER'} · ${metadata.crs}`, margin, 77);
  context.fillText('Rendered from the current interactive 2D map viewport', margin, 104);

  context.fillStyle = '#0b0f17';
  context.fillRect(margin, sceneTop, sceneWidth, sceneHeight);
  context.drawImage(source, margin, sceneTop, sceneWidth, sceneHeight);

  const scaleLength = metadata.scaleBar.distanceMeters / metadata.scaleBar.metersPerPixel;
  const scaleX = margin + 34;
  const scaleY = sceneTop + sceneHeight - 34;
  context.fillStyle = 'rgba(8, 15, 25, 0.86)';
  context.fillRect(scaleX - 12, scaleY - 34, scaleLength + 64, 58);
  context.strokeStyle = '#ffffff';
  context.lineWidth = 4;
  context.beginPath();
  context.moveTo(scaleX, scaleY);
  context.lineTo(scaleX + scaleLength, scaleY);
  context.moveTo(scaleX, scaleY - 7);
  context.lineTo(scaleX, scaleY + 7);
  context.moveTo(scaleX + scaleLength, scaleY - 7);
  context.lineTo(scaleX + scaleLength, scaleY + 7);
  context.stroke();
  context.fillStyle = '#ffffff';
  context.font = '700 15px Arial, sans-serif';
  context.fillText(formatScaleDistance(metadata.scaleBar.distanceMeters), scaleX + scaleLength + 12, scaleY + 5);

  const northX = margin + sceneWidth - 52;
  const northY = sceneTop + 56;
  context.fillStyle = 'rgba(8, 15, 25, 0.86)';
  context.fillRect(northX - 27, northY - 35, 54, 76);
  context.strokeStyle = '#ffffff';
  context.fillStyle = '#ffffff';
  context.lineWidth = 3;
  context.beginPath();
  context.moveTo(northX, northY + 18);
  context.lineTo(northX, northY - 15);
  context.lineTo(northX - 8, northY - 3);
  context.moveTo(northX, northY - 15);
  context.lineTo(northX + 8, northY - 3);
  context.stroke();
  context.font = '700 13px Arial, sans-serif';
  context.fillText('N', northX - 5, northY - 22);

  context.fillStyle = '#ffffff';
  context.fillRect(margin, footerTop, innerWidth, footerHeight);
  context.strokeStyle = '#cbd5e1';
  context.lineWidth = 2;
  context.strokeRect(margin, footerTop, innerWidth, footerHeight);
  const rightX = margin + leftWidth + panelGap;
  context.strokeStyle = '#dbe3ea';
  context.beginPath();
  context.moveTo(margin + leftWidth + panelGap / 2, footerTop + panelPadding);
  context.lineTo(margin + leftWidth + panelGap / 2, footerTop + footerHeight - panelPadding);
  context.stroke();

  context.font = '700 18px Arial, sans-serif';
  context.fillStyle = '#102333';
  context.fillText('PROJECT AND RESULT PROVENANCE', margin + panelPadding, footerTop + 31);
  context.fillText('LEGEND AND LIMITATIONS', rightX + panelPadding, footerTop + 31);
  context.font = `${bodySize}px Arial, sans-serif`;
  let leftY = footerTop + 58;
  for (const row of metadataRows) {
    leftY = drawParagraph(context, row, margin + panelPadding, leftY, leftTextWidth, bodyLineHeight, '#263746') + 2;
  }

  const legendColumnWidth = (rightTextWidth - 14) / 2;
  metadata.legend.forEach((entry, index) => {
    const column = index % 2;
    const row = Math.floor(index / 2);
    const x = rightX + panelPadding + column * (legendColumnWidth + 14);
    const y = footerTop + 67 + row * 30;
    context.fillStyle = entry.color;
    context.fillRect(x, y - 12, 14, 14);
    context.font = '13px Arial, sans-serif';
    context.fillStyle = '#263746';
    context.fillText(entry.label, x + 22, y);
  });

  let limitationY = footerTop + 67 + legendRows * 30 + 8;
  context.font = '700 14px Arial, sans-serif';
  limitationY = drawParagraph(context, 'DATA LIMITATIONS', rightX + panelPadding, limitationY, rightTextWidth, 19, '#9a3412') + 3;
  context.font = '13px Arial, sans-serif';
  for (const limitation of metadata.limitations) {
    limitationY = drawParagraph(context, `• ${limitation}`, rightX + panelPadding, limitationY, rightTextWidth, 18, '#4b5563') + 2;
  }

  return canvas;
}
