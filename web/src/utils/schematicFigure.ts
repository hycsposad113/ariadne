import type { ExplorationDesignArea, WorkspaceRevision } from '../types';

export type FigureWorkspaceCitation = {
  workspace_id: string;
  revision: number | string;
  project_id: string;
  study_area_id: string;
  status: string;
  feature_dispositions?: WorkspaceRevision['feature_dispositions'];
};

export const MAX_RENDERED_ROAD_SEGMENTS = 500;

export interface SchematicFigureStudyArea {
  id: string;
  status: string;
  revision: number;
}

export interface SchematicFigureContext {
  projectId: string;
  workspace: FigureWorkspaceCitation | null;
  studyArea: SchematicFigureStudyArea | null;
  hasUnsavedChanges: boolean;
  sourcePackageRevision: string | null;
  sourceSnapshotIds: string[];
  buildingCount: number;
  roadCount: number;
  explorationDesignArea?: ExplorationDesignArea | null;
  renderedRoadCount?: number;
  selectedFeatureIds: string[];
  exportedAtUtc?: string;
}

export interface Schematic3DFigureMetadata {
  figureVersion: 'week4-schematic-3d-v1';
  projectId: string;
  workspace: { id: string; revision: number | string; status: string };
  studyArea: { id: string; revision: number; status: string };
  sourcePackageRevision: string | null;
  sourceSnapshotIds: string[];
  crs: 'EPSG:28992';
  exportedAtUtc: string;
  featureCounts: { buildingsLoaded: number; roadsLoaded: number; roadsRendered: number };
  explorationDesignArea: {
    scope: 'EXPLORATION_DESIGN_AREA';
    crs: 'EPSG:28992';
    areaM2: number;
    status: 'DRAFT_PENDING_HUMAN_DECISION';
    revision: number;
  } | null;
  selectedFeatureIds: string[];
  legend: Array<{ label: string; color: string }>;
  limitations: string[];
}

const FIGURE_LEGEND = [
  { label: 'StudyArea outline', color: '#38bdf8' },
  { label: 'Preserved building', color: '#10b981' },
  { label: 'Editable building', color: '#38bdf8' },
  { label: 'Undecided building', color: '#64748b' },
  { label: 'Road segment', color: '#475569' },
  { label: 'Current selection', color: '#facc15' },
  { label: 'Exploration Design Area (conceptual only)', color: '#facc15' },
] as const;

export function canExportSchematic3DFigure(context: Pick<SchematicFigureContext, 'projectId' | 'workspace' | 'studyArea' | 'hasUnsavedChanges'>): boolean {
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

export function buildSchematic3DFigureMetadata(context: SchematicFigureContext): Schematic3DFigureMetadata {
  if (context.hasUnsavedChanges) {
    throw new Error('3D figure export requires a synchronized workspace; unsaved workspace changes are present.');
  }
  if (!canExportSchematic3DFigure(context)) {
    throw new Error('A saved workspace for the active StudyArea is required for a provenance-linked 3D figure.');
  }

  const workspace = context.workspace!;
  const studyArea = context.studyArea!;
  const buildingsLoaded = Math.max(0, Math.floor(context.buildingCount));
  const roadsLoaded = Math.max(0, Math.floor(context.roadCount));
  const roadsRendered = Math.min(
    roadsLoaded,
    MAX_RENDERED_ROAD_SEGMENTS,
    Math.max(0, Math.floor(context.renderedRoadCount ?? roadsLoaded)),
  );
  const sourceSnapshotIds = [...new Set(context.sourceSnapshotIds.map((id) => id.trim()).filter(Boolean))].sort();
  const selectedFeatureIds = [...new Set(context.selectedFeatureIds.map((id) => id.trim()).filter(Boolean))].sort();
  const limitations = [
    'Building extrusions use a fixed schematic 14 m height for illustration; source building heights and storey counts are unavailable.',
    `The 3D renderer shows at most ${MAX_RENDERED_ROAD_SEGMENTS} road segments; ${roadsRendered} of ${roadsLoaded} loaded road features have a rendered line.`,
    'The StudyArea is confirmed for exploration only. This exploratory image does not establish legal boundaries, parcel ownership, zoning compliance, buildability, FAR, or shadow performance.',
    'The Exploration Design Area, when present, is a conceptual denominator inside the StudyArea and is not a legal design boundary.',
    sourceSnapshotIds.length === 0 || !context.sourcePackageRevision
      ? 'Source package or snapshot references are unavailable; source completeness must not be inferred from this view.'
      : 'Source completeness and attribute availability remain limited to the listed package and snapshots; unknown values are not zero.',
  ];

  return {
    figureVersion: 'week4-schematic-3d-v1',
    projectId: context.projectId,
    workspace: { id: workspace.workspace_id, revision: workspace.revision, status: workspace.status },
    studyArea: { id: studyArea.id, revision: studyArea.revision, status: studyArea.status },
    sourcePackageRevision: context.sourcePackageRevision,
    sourceSnapshotIds,
    crs: 'EPSG:28992',
    exportedAtUtc: context.exportedAtUtc ?? new Date().toISOString(),
    featureCounts: { buildingsLoaded, roadsLoaded, roadsRendered },
    explorationDesignArea: context.explorationDesignArea ? {
      scope: context.explorationDesignArea.scope,
      crs: context.explorationDesignArea.crs,
      areaM2: context.explorationDesignArea.area_m2,
      status: context.explorationDesignArea.status,
      revision: context.explorationDesignArea.revision,
    } : null,
    selectedFeatureIds,
    legend: context.explorationDesignArea
      ? [...FIGURE_LEGEND]
      : FIGURE_LEGEND.filter((item) => item.label !== 'Exploration Design Area (conceptual only)'),
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

export function layoutSchematicLegend(entryCount: number): {
  legendRows: number;
  legendStartY: number;
  limitationsStartY: number;
} {
  const legendRows = Math.ceil(Math.max(0, entryCount) / 2);
  const legendStartY = 76;
  return {
    legendRows,
    legendStartY,
    limitationsStartY: legendStartY + legendRows * 36 + 6,
  };
}

export function composeSchematic3DFigure(source: HTMLImageElement, metadata: Schematic3DFigureMetadata): HTMLCanvasElement {
  const sourceWidth = source.naturalWidth || source.width;
  const sourceHeight = source.naturalHeight || source.height;
  if (sourceWidth <= 0 || sourceHeight <= 0) throw new Error('The rendered 3D viewport is empty.');

  const canvas = document.createElement('canvas');
  const width = Math.max(1440, sourceWidth);
  const scale = width / sourceWidth;
  const sceneHeight = Math.round(sourceHeight * scale);
  const margin = 40;
  const headerHeight = 132;
  const sceneTop = headerHeight + 24;
  const sceneWidth = width - margin * 2;
  const sceneTopInset = 24;
  const panelGap = 28;
  const panelPadding = 24;
  const innerWidth = width - margin * 2 - panelGap;
  const leftWidth = Math.round(innerWidth * 0.57);
  const rightWidth = innerWidth - leftWidth;
  const leftTextWidth = leftWidth - panelPadding * 2;
  const rightTextWidth = rightWidth - panelPadding * 2;
  const bodySize = 17;
  const bodyLineHeight = 25;
  const legendLayout = layoutSchematicLegend(metadata.legend.length);
  const legendRowHeight = 36;

  const metadataRows = [
    `Project: ${metadata.projectId}`,
    `Workspace: ${metadata.workspace.id} · revision ${metadata.workspace.revision} · ${metadata.workspace.status}`,
    `StudyArea: ${metadata.studyArea.id} · record revision ${metadata.studyArea.revision} · ${metadata.studyArea.status}`,
    `CRS: ${metadata.crs}`,
    `Source package revision: ${metadata.sourcePackageRevision ?? 'UNAVAILABLE'}`,
    `Source snapshot IDs: ${metadata.sourceSnapshotIds.length ? metadata.sourceSnapshotIds.join(', ') : 'UNAVAILABLE'}`,
    `Loaded features: ${metadata.featureCounts.buildingsLoaded} buildings · ${metadata.featureCounts.roadsLoaded} roads (${metadata.featureCounts.roadsRendered} road segments rendered)`,
    `Selected feature IDs: ${metadata.selectedFeatureIds.length ? metadata.selectedFeatureIds.join(', ') : 'none'}`,
    `Exported UTC: ${metadata.exportedAtUtc}`,
  ];
  const footerProbe = document.createElement('canvas').getContext('2d');
  if (!footerProbe) throw new Error('Canvas text rendering is unavailable.');
  footerProbe.font = `${bodySize}px Arial, sans-serif`;
  const leftLineCount = metadataRows.reduce((count, row) => count + wrapText(footerProbe, row, leftTextWidth).length, 0);
  const rightLimitLines = metadata.limitations.reduce((count, row) => count + wrapText(footerProbe, row, rightTextWidth).length, 0);
  const footerHeight = Math.max(
    340,
    panelPadding * 2 + 42 + leftLineCount * bodyLineHeight,
    panelPadding * 2 + 42 + legendLayout.legendRows * legendRowHeight + rightLimitLines * 22 + 22,
  );
  canvas.width = width;
  canvas.height = sceneTop + sceneHeight + sceneTopInset + footerHeight + margin;

  const context = canvas.getContext('2d');
  if (!context) throw new Error('Canvas composition is unavailable.');
  context.fillStyle = '#eef2f6';
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.fillStyle = '#102333';
  context.fillRect(0, 0, width, headerHeight);
  context.fillStyle = '#f8fafc';
  context.font = '700 32px Arial, sans-serif';
  context.fillText('ROTTERDAM M4H · SCHEMATIC 3D SITE PREVIEW', margin, 48);
  context.fillStyle = '#cbd5e1';
  context.font = '17px Arial, sans-serif';
  context.fillText(`${metadata.figureVersion} · exploratory view · ${metadata.crs}`, margin, 82);
  context.fillText('Rendered from the current interactive 3D viewport', margin, 108);

  context.fillStyle = '#0b0f17';
  context.fillRect(margin, sceneTop, sceneWidth, sceneHeight);
  context.drawImage(source, margin, sceneTop, sceneWidth, sceneHeight);

  const footerTop = sceneTop + sceneHeight + sceneTopInset;
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

  context.font = '700 19px Arial, sans-serif';
  context.fillStyle = '#102333';
  context.fillText('PROJECT AND SOURCE', margin + panelPadding, footerTop + 32);
  context.fillText('LEGEND AND LIMITATIONS', rightX + panelPadding, footerTop + 32);
  context.font = `${bodySize}px Arial, sans-serif`;
  let leftY = footerTop + 64;
  for (const row of metadataRows) {
    leftY = drawParagraph(context, row, margin + panelPadding, leftY, leftTextWidth, bodyLineHeight, '#263746') + 3;
  }

  const legendColumnWidth = (rightTextWidth - 16) / 2;
  metadata.legend.forEach((entry, index) => {
    const column = index % 2;
    const row = Math.floor(index / 2);
    const x = rightX + panelPadding + column * (legendColumnWidth + 16);
    const y = footerTop + legendLayout.legendStartY + row * legendRowHeight;
    context.fillStyle = entry.color;
    context.beginPath();
    context.arc(x + 8, y - 6, 8, 0, Math.PI * 2);
    context.fill();
    context.font = '15px Arial, sans-serif';
    context.fillStyle = '#263746';
    context.fillText(entry.label, x + 22, y);
  });

  let limitationY = footerTop + legendLayout.limitationsStartY;
  context.font = '700 16px Arial, sans-serif';
  limitationY = drawParagraph(context, 'DATA LIMITATIONS', rightX + panelPadding, limitationY, rightTextWidth, 22, '#9a3412') + 5;
  context.font = '15px Arial, sans-serif';
  for (const limitation of metadata.limitations) {
    limitationY = drawParagraph(context, `• ${limitation}`, rightX + panelPadding, limitationY, rightTextWidth, 21, '#4b5563') + 2;
  }

  return canvas;
}
