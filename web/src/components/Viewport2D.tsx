import React, { useRef, useState, useEffect, useCallback } from 'react';
import { lineTouchesStudyArea } from '../utils/geometryScope';
import { landColor } from './fabricPalette';
import { proposalRoadStyle, outsideRoadParts } from '../utils/proposalRoads';
import { useI18n, useT } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';
import type { Building, ExplorationDesignArea, Segment, SyntaxLayer, SpatialZone } from '../types';
import {
  type RenderTransform,
  DEFAULT_TRANSFORM,
  epsg28992ToScreen,
  panByWheelDelta,
  screenToEpsg28992,
  zoomAtPoint,
} from '../utils/geoTransform';
import { buildSyntaxHeatmapClassification } from '../utils/syntaxHeatmap';
import {
  type SyntaxContextResponse,
  type SyntaxContextMode,
  type SyntaxContextMetric,
  buildClassificationFromBreaks,
  classifyContextValue,
  hexToRgba,
  syntaxContextBadgeStatus,
} from '../utils/syntaxContext';
import { selectFeaturesIntersectingExtent } from '../utils/featureSelection';
import { ZoomIn, ZoomOut, RotateCcw, Edit3, Check, X, Download, Ruler, Square } from 'lucide-react';
import {
  buildMapFigureMetadata,
  canExportMapFigure,
  composeMapFigure,
  type MapFigureContext,
  selectMapScaleBar,
} from '../utils/mapFigure';
import {
  measurePolygon,
  measurePolylineLength,
  type DistanceMeasurement,
  type MetricPoint2D,
  type PolygonMeasurement,
} from '../utils/measure';
import './Viewport2D.measure.css';
import {
  buildContextLayerPlan,
  getContextToleranceMeters,
  useSurroundingContext,
} from '../utils/surroundingContext';
import { get2DNavigationAction } from './viewport3d/navigation';

type MeasurementMode = 'distance' | 'area';
type MeasurementResult =
  | { mode: 'distance'; value: DistanceMeasurement }
  | { mode: 'area'; value: PolygonMeasurement };

interface Viewport2DProps {
  viewTransform?: RenderTransform;
  onTransformChange?: (transform: RenderTransform) => void;
  studyAreaGeometry: any;
  buildings: Building[];
  segments: Segment[];
  scenarioAreas?: Array<{ id: string; geometry: { type: string; coordinates: unknown }; kind: string }>;
  syntaxSegments?: Segment[];
  syntaxLegend?: Array<{ label: string; color: string }>;
  activeSyntaxLayer: SyntaxLayer | null;
  spatialZones: SpatialZone[];
  explorationDesignArea?: ExplorationDesignArea | null;
  selectedFeatureId: string | null;
  selectedFeatureIds?: string[];
  onSelectFeature: (id: string | null, type: 'building' | 'road') => void;
  onSelectFeatureIds?: (ids: string[]) => void;
  isDrawingZone?: boolean;
  onToggleDrawingZone?: () => void;
  onCompleteDrawingZone?: (coords: [number, number][]) => void;
  onCancelDrawingZone?: () => void;
  figureContext: Omit<MapFigureContext, 'transform' | 'canvasWidth' | 'canvasHeight' | 'exportedAtUtc'>;
  figureExportReady: boolean;
  syntaxContextData?: SyntaxContextResponse | null;
  syntaxContextStatus?: 'idle' | 'loading' | 'success' | 'error';
  syntaxContextError?: string | null;
  syntaxMode?: SyntaxContextMode;
  syntaxMetric?: SyntaxContextMetric;
  syntaxDistanceKm?: number;
}

export const Viewport2D: React.FC<Viewport2DProps> = ({
  viewTransform,
  onTransformChange,
  studyAreaGeometry,
  buildings,
  segments,
  scenarioAreas = [],
  syntaxSegments = [],
  syntaxLegend = [],
  activeSyntaxLayer,
  spatialZones,
  explorationDesignArea = null,
  selectedFeatureId,
  selectedFeatureIds = [],
  onSelectFeature,
  onSelectFeatureIds,
  isDrawingZone = false,
  onToggleDrawingZone,
  onCompleteDrawingZone,
  onCancelDrawingZone,
  figureContext,
  figureExportReady,
  syntaxContextData = null,
  syntaxContextStatus = 'idle',
  syntaxContextError = null,
  syntaxMode = 'pedestrian',
  syntaxMetric = 'nain',
  syntaxDistanceKm = 1.0,
}) => {
  const t = useT();
  const { language } = useI18n();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [isExportingFigure, setIsExportingFigure] = useState(false);
  const [figureExportMessage, setFigureExportMessage] = useState('');
  const [localTransform, setLocalTransform] = useState<RenderTransform>({
    ...DEFAULT_TRANSFORM,
    panX: 420,
    panY: 380,
    zoom: 0.9,
  });
  const transform = viewTransform ?? localTransform;
  const transformRef = useRef(transform);
  useEffect(() => { transformRef.current = transform; }, [transform]);
  const changeRef = useRef(onTransformChange);
  useEffect(() => { changeRef.current = onTransformChange; }, [onTransformChange]);
  const setTransform = useCallback((update: React.SetStateAction<RenderTransform>) => {
    const next = typeof update === 'function' ? update(transformRef.current) : update;
    transformRef.current = next;
    setLocalTransform(next);
    changeRef.current?.(next);
  }, []);
  const surroundingContext = useSurroundingContext(getContextToleranceMeters(transform.zoom));

  const [mouseCoord, setMouseCoord] = useState<[number, number]>([DEFAULT_TRANSFORM.originX, DEFAULT_TRANSFORM.originY]);
  const [drawVertices, setDrawVertices] = useState<[number, number][]>([]);
  const [isBoxSelecting, setIsBoxSelecting] = useState(false);
  const [selectionRect, setSelectionRect] = useState<{ startX: number; startY: number; endX: number; endY: number } | null>(null);
  const [measurementMode, setMeasurementMode] = useState<MeasurementMode | null>(null);
  const [measurementPoints, setMeasurementPoints] = useState<MetricPoint2D[]>([]);
  const [measurementResult, setMeasurementResult] = useState<MeasurementResult | null>(null);
  const [measurementError, setMeasurementError] = useState('');
  const isDraggingRef = useRef(false);
  const dragModeRef = useRef<'navigation-pan' | 'navigation-zoom' | 'map-pan' | 'box-select' | null>(null);
  const dragStartRef = useRef<{ x: number; y: number; canvasX: number; canvasY: number; panX: number; panY: number; button: number; transform: RenderTransform }>({
    x: 0, y: 0, canvasX: 0, canvasY: 0, panX: 0, panY: 0, button: 0, transform: DEFAULT_TRANSFORM,
  });

  // Clear drawn vertices when drawing mode turned off
  useEffect(() => {
    if (!isDrawingZone) {
      setDrawVertices([]);
    } else {
      setIsBoxSelecting(false);
      setSelectionRect(null);
    }
  }, [isDrawingZone]);

  const handleFinish = useCallback(() => {
    if (drawVertices.length >= 3 && onCompleteDrawingZone) {
      // Close the ring if not closed
      const first = drawVertices[0];
      const last = drawVertices[drawVertices.length - 1];
      const closed: [number, number][] = (first[0] === last[0] && first[1] === last[1])
        ? drawVertices
        : [...drawVertices, [first[0], first[1]]];
      onCompleteDrawingZone(closed);
      setDrawVertices([]);
    }
  }, [drawVertices, onCompleteDrawingZone]);

  const handleCancel = useCallback(() => {
    setDrawVertices([]);
    if (onCancelDrawingZone) {
      onCancelDrawingZone();
    }
  }, [onCancelDrawingZone]);

  const startMeasurement = (mode: MeasurementMode) => {
    if (isDrawingZone) return;
    setIsBoxSelecting(false);
    setSelectionRect(null);
    setMeasurementMode(mode);
    setMeasurementPoints([]);
    setMeasurementResult(null);
    setMeasurementError('');
  };

  const cancelMeasurement = () => {
    setMeasurementMode(null);
    setMeasurementPoints([]);
    setMeasurementResult(null);
    setMeasurementError('');
  };

  const finishMeasurement = () => {
    if (!measurementMode) return;
    try {
      if (measurementMode === 'distance') {
        setMeasurementResult({ mode: 'distance', value: measurePolylineLength(measurementPoints) });
      } else {
        setMeasurementResult({ mode: 'area', value: measurePolygon(measurementPoints) });
      }
      setMeasurementError('');
      setMeasurementMode(null);
    } catch (error) {
      setMeasurementError(error instanceof Error ? error.message : "Measurement is invalid.");
    }
  };

  const renderCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;

    // Clear background
    ctx.fillStyle = '#0b0f17';
    ctx.fillRect(0, 0, width, height);

    // Grid pattern in EPSG:28992 meters (100m grid)
    ctx.strokeStyle = 'rgba(51, 65, 85, 0.25)';
    ctx.lineWidth = 1;
    const gridSize = 100; // 100m
    const minCorner = screenToEpsg28992(0, height, transform);
    const maxCorner = screenToEpsg28992(width, 0, transform);

    const startX = Math.floor(minCorner[0] / gridSize) * gridSize;
    const endX = Math.ceil(maxCorner[0] / gridSize) * gridSize;
    const startY = Math.floor(minCorner[1] / gridSize) * gridSize;
    const endY = Math.ceil(maxCorner[1] / gridSize) * gridSize;

    ctx.beginPath();
    for (let x = startX; x <= endX; x += gridSize) {
      const [px1, py1] = epsg28992ToScreen(x, startY, transform);
      const [, py2] = epsg28992ToScreen(x, endY, transform);
      ctx.moveTo(px1, py1);
      ctx.lineTo(px1, py2);
    }
    for (let y = startY; y <= endY; y += gridSize) {
      const [px1, py1] = epsg28992ToScreen(startX, y, transform);
      const [px2] = epsg28992ToScreen(endX, y, transform);
      ctx.moveTo(px1, py1);
      ctx.lineTo(px2, py1);
    }
    ctx.stroke();

    // OSM context is a muted background. Syntax and StudyArea layers are drawn
    // after it so the existing Syntax colour scale and site boundary stay clear.
    const viewBounds = [minCorner[0], minCorner[1], maxCorner[0], maxCorner[1]];
    const contextLayers = buildContextLayerPlan(surroundingContext.data?.layers ?? {});
    for (const layer of contextLayers) {
      for (const feature of layer.features) {
        if (!feature.geometry) continue;
        if (layer.name === 'buildings' && feature.properties?.inside_study_area) continue;
        const bounds = feature.properties?.bounds_m;
        if (Array.isArray(bounds) && bounds.length === 4
          && (bounds[2] < viewBounds[0] || bounds[0] > viewBounds[2]
            || bounds[3] < viewBounds[1] || bounds[1] > viewBounds[3])) continue;
        const geometry = feature.geometry;
        if (geometry.type === 'Polygon' || geometry.type === 'MultiPolygon') {
          const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
          ctx.fillStyle = layer.style.fill;
          ctx.strokeStyle = layer.style.stroke;
          ctx.lineWidth = layer.style.lineWidth;
          for (const polygon of polygons) {
            if (!Array.isArray(polygon) || polygon.length === 0) continue;
            ctx.beginPath();
            for (const ring of polygon) {
              if (!Array.isArray(ring) || ring.length < 3) continue;
              const [firstX, firstY] = epsg28992ToScreen(ring[0][0], ring[0][1], transform);
              ctx.moveTo(firstX, firstY);
              for (let index = 1; index < ring.length; index += 1) {
                const [x, y] = epsg28992ToScreen(ring[index][0], ring[index][1], transform);
                ctx.lineTo(x, y);
              }
              ctx.closePath();
            }
            ctx.fill('evenodd');
            ctx.stroke();
          }
        } else if (geometry.type === 'LineString' || geometry.type === 'MultiLineString') {
          const rawLines = geometry.type === 'LineString' ? [geometry.coordinates] : geometry.coordinates;
          const lines = layer.name === 'roads' && segments.some(s => s.origin)
            ? rawLines.flatMap((line: number[][]) => outsideRoadParts(line, studyAreaGeometry)) : rawLines;
          ctx.strokeStyle = layer.style.stroke;
          ctx.lineWidth = layer.style.lineWidth;
          ctx.lineCap = 'round';
          ctx.beginPath();
          for (const line of lines) {
            if (!Array.isArray(line) || line.length < 2) continue;
            const [startX, startY] = epsg28992ToScreen(line[0][0], line[0][1], transform);
            ctx.moveTo(startX, startY);
            for (let index = 1; index < line.length; index += 1) {
              const [x, y] = epsg28992ToScreen(line[index][0], line[index][1], transform);
              ctx.lineTo(x, y);
            }
          }
          ctx.stroke();
        }
      }
    }

    // 1. Render Study Area Boundary
    if (studyAreaGeometry) {
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 3]);
      ctx.fillStyle = 'rgba(56, 189, 248, 0.04)';

      const rings = studyAreaGeometry.coordinates ?? [];
      for (const ring of rings) {
        if (ring.length < 3) continue;
        ctx.beginPath();
        const [p0x, p0y] = epsg28992ToScreen(ring[0][0], ring[0][1], transform);
        ctx.moveTo(p0x, p0y);
        for (let i = 1; i < ring.length; i++) {
          const [px, py] = epsg28992ToScreen(ring[i][0], ring[i][1], transform);
          ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    // 2. Render the separate, non-legal Exploration Design Area.
    if (explorationDesignArea?.geometry?.coordinates) {
      const polygons = explorationDesignArea.geometry.type === 'MultiPolygon'
        ? explorationDesignArea.geometry.coordinates
        : [explorationDesignArea.geometry.coordinates];
      ctx.fillStyle = 'rgba(250, 204, 21, 0.05)';
      ctx.strokeStyle = '#facc15';
      ctx.lineWidth = 2;
      ctx.setLineDash([10, 4]);
      for (const rings of polygons) {
        for (const ring of rings) {
          if (ring.length < 3) continue;
          ctx.beginPath();
          const [p0x, p0y] = epsg28992ToScreen(ring[0][0], ring[0][1], transform);
          ctx.moveTo(p0x, p0y);
          for (let i = 1; i < ring.length; i++) {
            const [px, py] = epsg28992ToScreen(ring[i][0], ring[i][1], transform);
            ctx.lineTo(px, py);
          }
          ctx.closePath();
          ctx.fill();
          ctx.stroke();
        }
      }
      ctx.setLineDash([]);
    }

    // 3. Render Draft Spatial Zones
    for (const zone of spatialZones) {
      if (!zone.geometry || !zone.geometry.coordinates) continue;
      const rings = zone.geometry.coordinates;
      ctx.fillStyle = 'rgba(168, 85, 247, 0.15)';
      ctx.strokeStyle = '#c084fc';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 2]);

      for (const ring of rings) {
        if (ring.length < 3) continue;
        ctx.beginPath();
        const [p0x, p0y] = epsg28992ToScreen(ring[0][0], ring[0][1], transform);
        ctx.moveTo(p0x, p0y);
        for (let i = 1; i < ring.length; i++) {
          const [px, py] = epsg28992ToScreen(ring[i][0], ring[i][1], transform);
          ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    // Scenario polygons come from the selected, hash-verified preview GeoJSON.
    // Context and the study-area boundary remain visible underneath them.
    for (const area of scenarioAreas) {
      const geometry = area.geometry;
      if (!geometry || !['Polygon', 'MultiPolygon'].includes(geometry.type)) continue;
      const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates as unknown[];
      const style = area.kind.startsWith('fabric:') ? { fill: landColor(area.kind.slice(7)), stroke: landColor(area.kind.slice(7)) } : area.kind === 'water'
        ? { fill: 'rgba(40, 124, 162, 0.30)', stroke: '#287ca2' }
        : area.kind === 'waterfront_building_no_build_band'
          ? { fill: 'rgba(244, 114, 182, 0.11)', stroke: '#f472b6' }
          : area.kind === 'street_block'
            ? { fill: 'rgba(148, 163, 184, 0.08)', stroke: 'rgba(148, 163, 184, 0.42)' }
            : { fill: 'rgba(102, 139, 91, 0.22)', stroke: '#86a875' };
      ctx.fillStyle = style.fill;
      ctx.strokeStyle = style.stroke;
      ctx.lineWidth = 1;
      for (const polygon of polygons) {
        if (!Array.isArray(polygon)) continue;
        ctx.beginPath();
        for (const ring of polygon) {
          if (!Array.isArray(ring) || ring.length < 3) continue;
          const [firstX, firstY] = epsg28992ToScreen(ring[0][0], ring[0][1], transform);
          ctx.moveTo(firstX, firstY);
          for (let index = 1; index < ring.length; index += 1) {
            const [x, y] = epsg28992ToScreen(ring[index][0], ring[index][1], transform);
            ctx.lineTo(x, y);
          }
          ctx.closePath();
        }
        ctx.fill('evenodd');
        ctx.stroke();
      }
    }

    // 3. Render Street Segments (Space Syntax)
    const segValues = activeSyntaxLayer?.segment_values ?? {};
    const heatmapClassification = activeSyntaxLayer
      ? buildSyntaxHeatmapClassification(activeSyntaxLayer.segment_values)
      : null;

    for (const seg of segments) {
      const coords = seg.geometry?.coordinates;
      if (!coords || coords.length < 2) continue;

      const isSelected = selectedFeatureId === seg.id || selectedFeatureIds.includes(seg.id);
      const val = segValues[seg.id];

      if (isSelected) {
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 4;
        ctx.setLineDash([]);
      } else if (heatmapClassification) {
        const style = heatmapClassification.classify(val);
        ctx.strokeStyle = style.strokeColor;
        ctx.lineWidth = style.lineWidth;
        ctx.setLineDash(style.lineDash);
      } else {
        const roadStyle = { ...proposalRoadStyle(seg) };
        const fabric = seg as Segment & { fabric_color?: string; fabric_width?: number };
        if (fabric.fabric_color) { roadStyle.color = fabric.fabric_color; }
        ctx.strokeStyle = roadStyle.color;
        ctx.lineWidth = fabric.fabric_width ?? (seg.modes ? 3 : 1.5);
        ctx.setLineDash(roadStyle.dash);
      }
      ctx.lineCap = 'round';

      ctx.beginPath();
      const [p0x, p0y] = epsg28992ToScreen(coords[0][0], coords[0][1], transform);
      ctx.moveTo(p0x, p0y);
      for (let i = 1; i < coords.length; i++) {
        const [px, py] = epsg28992ToScreen(coords[i][0], coords[i][1], transform);
        ctx.lineTo(px, py);
      }
      ctx.stroke();
    }
    ctx.setLineDash([]);

    // Overlay the exact split segments used by the calculation. Raw OSM
    // way IDs cannot be joined to Syntax values because the engine splits ways
    // at vertices and same-layer junctions.
    if (activeSyntaxLayer || syntaxContextData) {
      if (
        syntaxContextData &&
        Array.isArray(syntaxContextData.segments) &&
        syntaxContextData.segments.length > 0 &&
        syntaxContextData.legend_breaks &&
        syntaxContextData.legend_breaks[syntaxMetric]
      ) {

        for (const seg of syntaxContextData.segments) {
          const coords = seg.coordinates;
          if (buildings.some(b => b.properties?.fabric_display === true) && !syntaxContextData?.comparison_view && (seg.inside_site || lineTouchesStudyArea(seg.coordinates, studyAreaGeometry))) continue;
          if (!coords || coords.length < 2) continue;
          const val = syntaxMetric === 'nain' ? seg.nain : seg.nach;
          const style = classifyContextValue(syntaxContextData, syntaxMetric, val);
          if (seg.boundary_effect_risk) {
            ctx.strokeStyle = hexToRgba(style.strokeColor, 0.45);
            ctx.setLineDash([4, 4]);
          } else {
            ctx.strokeStyle = style.strokeColor;
            ctx.setLineDash(style.lineDash);
          }
          ctx.lineWidth = seg.inside_site ? 3.0 : 1.5;
          ctx.lineCap = 'round';
          ctx.beginPath();
          const [startX, startY] = epsg28992ToScreen(coords[0][0], coords[0][1], transform);
          ctx.moveTo(startX, startY);
          for (let i = 1; i < coords.length; i++) {
            const [x, y] = epsg28992ToScreen(coords[i][0], coords[i][1], transform);
            ctx.lineTo(x, y);
          }
          ctx.stroke();
        }
        ctx.setLineDash([]);
      } else if (heatmapClassification) {
        for (const seg of syntaxSegments) {
          const coords = seg.geometry?.coordinates;
          if (buildings.some(b => b.properties?.fabric_display === true) && lineTouchesStudyArea(seg.geometry?.coordinates ?? [], studyAreaGeometry)) continue;
          if (!coords || coords.length < 2) continue;
          const val = segValues[seg.id];
          const style = heatmapClassification.classify(val);
          ctx.strokeStyle = style.strokeColor;
          ctx.lineWidth = style.lineWidth;
          ctx.setLineDash(style.lineDash);
          ctx.lineCap = 'round';
          ctx.beginPath();
          const [startX, startY] = epsg28992ToScreen(coords[0][0], coords[0][1], transform);
          ctx.moveTo(startX, startY);
          for (let i = 1; i < coords.length; i++) {
            const [x, y] = epsg28992ToScreen(coords[i][0], coords[i][1], transform);
            ctx.lineTo(x, y);
          }
          ctx.stroke();
        }
        ctx.setLineDash([]);
      }
    }

    canvas.dataset.syntaxView = syntaxContextData?.comparison_view ?? 'context';
    canvas.dataset.syntaxMetric = syntaxMetric;
    canvas.dataset.syntaxSegmentCount = String(syntaxContextData?.segments.length ?? 0);

    // 4. Render Buildings
    for (const b of buildings) {
      const geom = b.geometry;
      if (!geom || !geom.coordinates) continue;

      const isSelected = selectedFeatureId === b.id || selectedFeatureIds.includes(b.id);
      let strokeColor = '#475569';
      let fillColor = 'rgba(71, 85, 105, 0.4)';

      if (b.disposition === 'PRESERVE') {
        strokeColor = '#10b981';
        fillColor = 'rgba(16, 185, 129, 0.35)';
      } else if (b.disposition === 'EDITABLE') {
        strokeColor = '#38bdf8';
        fillColor = 'rgba(56, 189, 248, 0.35)';
      }

      if (b.properties?.fabric_display === true) { fillColor = b.properties.fabric_color; strokeColor = '#594d43'; }
      if (isSelected) {
        strokeColor = '#facc15';
        fillColor = 'rgba(250, 204, 21, 0.5)';
      }

      ctx.strokeStyle = strokeColor;
      ctx.fillStyle = fillColor;
      ctx.lineWidth = isSelected ? 2.5 : 1.2;

      const rings = geom.type === 'MultiPolygon' ? geom.coordinates[0] : geom.coordinates;
      for (const ring of rings) {
        if (!ring || ring.length < 3) continue;
        ctx.beginPath();
        const [p0x, p0y] = epsg28992ToScreen(ring[0][0], ring[0][1], transform);
        ctx.moveTo(p0x, p0y);
        for (let i = 1; i < ring.length; i++) {
          const [px, py] = epsg28992ToScreen(ring[i][0], ring[i][1], transform);
          ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      }
    }

    // Fabric allocations can reach the boundary: draw the outline last so it
    // remains visible in both languages and at fractional canvas pixel scales.
    if (studyAreaGeometry && buildings.some(b => b.properties?.fabric_display === true)) {
      const polygons = studyAreaGeometry.type === 'MultiPolygon' ? studyAreaGeometry.coordinates : [studyAreaGeometry.coordinates];
      ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 2; ctx.setLineDash([6, 3]);
      for (const rings of polygons) for (const ring of rings) {
        if (!ring.length) continue;
        ctx.beginPath();
        ring.forEach(([x,y]: number[], index: number) => {
          const [px,py] = epsg28992ToScreen(x,y,transform);
          if (index === 0) ctx.moveTo(px,py); else ctx.lineTo(px,py);
        });
        ctx.closePath(); ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    // 5. Render Active Interactive Drawing Polygon
    if (isDrawingZone && drawVertices.length > 0) {
      ctx.strokeStyle = '#c084fc';
      ctx.lineWidth = 2.5;
      ctx.setLineDash([5, 3]);

      ctx.beginPath();
      const [firstX, firstY] = epsg28992ToScreen(drawVertices[0][0], drawVertices[0][1], transform);
      ctx.moveTo(firstX, firstY);

      for (let i = 1; i < drawVertices.length; i++) {
        const [vx, vy] = epsg28992ToScreen(drawVertices[i][0], drawVertices[i][1], transform);
        ctx.lineTo(vx, vy);
      }

      // Rubberband line to mouse coordinate
      const [curX, curY] = epsg28992ToScreen(mouseCoord[0], mouseCoord[1], transform);
      ctx.lineTo(curX, curY);

      ctx.stroke();
      ctx.setLineDash([]);

      // Fill preview
      if (drawVertices.length >= 2) {
        ctx.fillStyle = 'rgba(192, 132, 252, 0.18)';
        ctx.fill();
      }

      // Render vertex points
      for (let i = 0; i < drawVertices.length; i++) {
        const [vx, vy] = epsg28992ToScreen(drawVertices[i][0], drawVertices[i][1], transform);
        const isStart = i === 0;

        ctx.beginPath();
        ctx.arc(vx, vy, isStart && drawVertices.length >= 3 ? 8 : 5, 0, Math.PI * 2);
        ctx.fillStyle = isStart ? '#38bdf8' : '#c084fc';
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.stroke();

        // Vertex index label
        ctx.fillStyle = '#ffffff';
        ctx.font = '10px monospace';
        ctx.fillText(`${i + 1}`, vx + 8, vy - 6);
      }
    }

    if (selectionRect) {
      const left = Math.min(selectionRect.startX, selectionRect.endX);
      const top = Math.min(selectionRect.startY, selectionRect.endY);
      const width = Math.abs(selectionRect.endX - selectionRect.startX);
      const height = Math.abs(selectionRect.endY - selectionRect.startY);
      ctx.fillStyle = 'rgba(56, 189, 248, 0.12)';
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 3]);
      ctx.fillRect(left, top, width, height);
      ctx.strokeRect(left, top, width, height);
      ctx.setLineDash([]);
    }
  }, [
    studyAreaGeometry,
    buildings,
    segments,
    scenarioAreas,
    syntaxSegments,
    activeSyntaxLayer,
    spatialZones,
    explorationDesignArea,
    selectedFeatureId,
    selectedFeatureIds,
    transform,
    isDrawingZone,
    drawVertices,
    mouseCoord,
    selectionRect,
    surroundingContext.data,
    syntaxContextData,
    syntaxMetric,
  ]);

  useEffect(() => {
    // Size the bitmap to the canvas' own box (the grid excludes the tool rail), and follow
    // container resizes, not only window resizes, so drawing and fit share one frame.
    const handleResize = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const width = canvas.clientWidth || canvas.parentElement?.clientWidth || 0;
      const height = canvas.clientHeight || canvas.parentElement?.clientHeight || 0;
      if (canvas.width !== width) canvas.width = width;
      if (canvas.height !== height) canvas.height = height;
      renderCanvas();
    };

    handleResize();
    window.addEventListener('resize', handleResize);
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(handleResize) : null;
    if (canvasRef.current) observer?.observe(canvasRef.current);
    return () => {
      window.removeEventListener('resize', handleResize);
      observer?.disconnect();
    };
  }, [renderCanvas]);

  useEffect(() => {
    renderCanvas();
  }, [renderCanvas]);

  // Mouse interaction
  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const navigationAction = get2DNavigationAction({
      type: 'pointer',
      button: e.button,
      ctrlKey: e.ctrlKey,
      shiftKey: e.shiftKey,
    });
    const isNavigationGesture = navigationAction !== 'none';
    if (!isNavigationGesture && e.button !== 0) return;

    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const canvasX = e.clientX - rect.left;
    const canvasY = e.clientY - rect.top;
    const dragMode = navigationAction === 'zoom'
      ? 'navigation-zoom'
      : navigationAction === 'pan'
        ? 'navigation-pan'
        : isBoxSelecting && !isDrawingZone
          ? 'box-select'
          : 'map-pan';

    isDraggingRef.current = true;
    dragModeRef.current = dragMode;
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      canvasX,
      canvasY,
      panX: transform.panX,
      panY: transform.panY,
      button: e.button,
      transform,
    };
    if (dragMode === 'box-select') {
      setSelectionRect({ startX: canvasX, startY: canvasY, endX: canvasX, endY: canvasY });
    }
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const [wx, wy] = screenToEpsg28992(mouseX, mouseY, transform);
    setMouseCoord([Math.round(wx), Math.round(wy)]);

    if (isDraggingRef.current) {
      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;
      const dragMode = dragModeRef.current;
      if (dragMode === 'box-select') {
        setSelectionRect({
          startX: dragStartRef.current.canvasX,
          startY: dragStartRef.current.canvasY,
          endX: mouseX,
          endY: mouseY,
        });
      } else if (dragMode === 'navigation-zoom') {
        setTransform(zoomAtPoint(
          dragStartRef.current.transform,
          Math.exp(-dy * 0.01),
          dragStartRef.current.canvasX,
          dragStartRef.current.canvasY,
        ));
      } else {
        setTransform(prev => ({
          ...prev,
          panX: dragStartRef.current.panX + dx,
          panY: dragStartRef.current.panY + dy,
        }));
      }
    }
  };

  const handleMouseUp = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (isDraggingRef.current) {
      const dist = Math.hypot(e.clientX - dragStartRef.current.x, e.clientY - dragStartRef.current.y);
      const dragMode = dragModeRef.current;
      isDraggingRef.current = false;
      dragModeRef.current = null;

      if (dragMode === 'navigation-zoom'
        || (dragMode === 'navigation-pan' && !(dragStartRef.current.button === 0 && dist < 5))) {
        setSelectionRect(null);
        return;
      }

      if (dragMode === 'box-select' && dist >= 5) {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const endX = e.clientX - rect.left;
        const endY = e.clientY - rect.top;
        const start = screenToEpsg28992(dragStartRef.current.canvasX, dragStartRef.current.canvasY, transform);
        const end = screenToEpsg28992(endX, endY, transform);
        const result = selectFeaturesIntersectingExtent(buildings, segments, {
          minX: Math.min(start[0], end[0]),
          minY: Math.min(start[1], end[1]),
          maxX: Math.max(start[0], end[0]),
          maxY: Math.max(start[1], end[1]),
        });
        onSelectFeatureIds?.([...result.buildingIds, ...result.roadIds]);
        setSelectionRect(null);
        return;
      }
      setSelectionRect(null);

      // Click event if mouse didn't drag far
      if (dist < 5) {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const clickY = e.clientY - rect.top;
        const [wx, wy] = screenToEpsg28992(clickX, clickY, transform);

        // If in Drawing Mode: add vertex or close polygon
        if (isDrawingZone) {
          if (drawVertices.length >= 3) {
            const [p0x, p0y] = epsg28992ToScreen(drawVertices[0][0], drawVertices[0][1], transform);
            const distPx = Math.hypot(clickX - p0x, clickY - p0y);
            if (distPx < 18) {
              // Clicked near start vertex -> finish polygon
              handleFinish();
              return;
            }
          }
          setDrawVertices(prev => [...prev, [Math.round(wx), Math.round(wy)]]);
          return;
        }

        if (measurementMode) {
          setMeasurementPoints((previous) => [...previous, [wx, wy]]);
          setMeasurementResult(null);
          setMeasurementError('');
          return;
        }

        // Check if clicked inside a building
        for (const b of buildings) {
          const geom = b.geometry;
          if (!geom || !geom.coordinates) continue;
          const rings = geom.type === 'MultiPolygon' ? geom.coordinates[0] : geom.coordinates;
          const outer = rings[0];
          if (outer && pointInPolygon([wx, wy], outer)) {
            onSelectFeature(b.id, 'building');
            return;
          }
        }

        // Check closest segment within 15 meters
        let closestSeg: Segment | null = null;
        let minDist = 15.0; // 15m tolerance
        for (const seg of segments) {
          const coords = seg.geometry?.coordinates;
          if (buildings.some(b => b.properties?.fabric_display === true) && lineTouchesStudyArea(seg.geometry?.coordinates ?? [], studyAreaGeometry)) continue;
          if (!coords || coords.length < 2) continue;
          const d = pointToSegmentDist([wx, wy], coords[0], coords[1]);
          if (d < minDist) {
            minDist = d;
            closestSeg = seg;
          }
        }
        if (closestSeg) {
          onSelectFeature(closestSeg.id, 'road');
          return;
        }

        onSelectFeature(null, 'building');
      }
    }
  };

  const handleWheel = useCallback((e: WheelEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const navigationAction = get2DNavigationAction({
      type: 'wheel',
      deltaMode: e.deltaMode,
      deltaX: e.deltaX,
      deltaY: e.deltaY,
      wheelDeltaY: (e as WheelEvent & { wheelDeltaY?: number }).wheelDeltaY,
      ctrlKey: e.ctrlKey,
      shiftKey: e.shiftKey,
    });
    if (navigationAction === 'none') return;

    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    if (navigationAction === 'pan') {
      setTransform(prev => panByWheelDelta(prev, e.deltaX, e.deltaY));
    } else {
      const deltaYInPixels = e.deltaMode === 1
        ? e.deltaY * 40
        : e.deltaMode === 2
          ? e.deltaY * (canvas.height || rect.height)
          : e.deltaY;
      // Pinch (ctrlKey) streams small deltas; mouse-wheel notches are ~100 px.
      const sensitivity = e.ctrlKey ? 0.01 : 0.002;
      setTransform(prev => zoomAtPoint(prev, Math.exp(-deltaYInPixels * sensitivity), px, py));
    }
  }, [setTransform]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', handleWheel);
  }, [handleWheel]);

  const zoomAtCanvasCenter = (factor: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const width = canvas.width || rect.width;
    const height = canvas.height || rect.height;
    setTransform(prev => zoomAtPoint(prev, factor, width / 2, height / 2));
  };

  const zoomIn = () => zoomAtCanvasCenter(1.25);
  const zoomOut = () => zoomAtCanvasCenter(0.8);
  const resetView = () => setTransform({ ...DEFAULT_TRANSFORM, panX: 420, panY: 380, zoom: 0.9 });

  useEffect(() => {
    if (!buildings.some(b => b.properties?.fabric_display === true)) return;
    const fit = () => {
      const canvas = canvasRef.current; if (!canvas) return;
      const points: number[][] = [];
      const collect = (v: unknown) => { if (!Array.isArray(v)) return; if (typeof v[0] === 'number' && typeof v[1] === 'number') points.push(v); else v.forEach(collect); };
      collect(studyAreaGeometry?.coordinates); if (!points.length) return;
      const minX=Math.min(...points.map(p=>p[0])),maxX=Math.max(...points.map(p=>p[0]));
      const minY=Math.min(...points.map(p=>p[1])),maxY=Math.max(...points.map(p=>p[1]));
      const w=canvas.clientWidth,h=canvas.clientHeight;
      if(!w||!h||maxX<=minX||maxY<=minY) return;
      const zoom=Math.min(w*.9/(maxX-minX),h*.9/(maxY-minY));
      setTransform(prev=>({...prev,zoom,panX:w/2-((minX+maxX)/2-prev.originX)*zoom,panY:h/2+((minY+maxY)/2-prev.originY)*zoom}));
    };
    fit(); const observer=typeof ResizeObserver!=='undefined'?new ResizeObserver(fit):null;
    if(canvasRef.current) observer?.observe(canvasRef.current);
    return ()=>observer?.disconnect();
  }, [buildings, studyAreaGeometry, setTransform]);

  const handleDoubleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    if (isDrawingZone || measurementMode) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickY = e.clientY - rect.top;
    const [worldX, worldY] = screenToEpsg28992(clickX, clickY, transform);

    const hitsBuilding = buildings.some(building => {
      const geometry = building.geometry;
      if (!geometry?.coordinates) return false;
      const polygons = geometry.type === 'MultiPolygon' ? geometry.coordinates : [geometry.coordinates];
      return polygons.some((rings: number[][][]) => rings[0] && pointInPolygon([worldX, worldY], rings[0]));
    });
    const hitsRoad = segments.some(segment => {
      const coordinates = segment.geometry?.coordinates;
      return Boolean(coordinates && coordinates.length >= 2
        && pointToSegmentDist([worldX, worldY], coordinates[0], coordinates[1]) <= 15);
    });
    if (hitsBuilding || hitsRoad) return;

    const geometry = studyAreaGeometry?.type === 'Feature'
      ? studyAreaGeometry.geometry
      : studyAreaGeometry;
    const positions: [number, number][] = [];
    const collectPositions = (value: unknown) => {
      if (!Array.isArray(value)) return;
      if (typeof value[0] === 'number' && typeof value[1] === 'number') {
        if (Number.isFinite(value[0]) && Number.isFinite(value[1])) positions.push([value[0], value[1]]);
        return;
      }
      value.forEach(collectPositions);
    };
    collectPositions(geometry?.coordinates);
    if (positions.length === 0) {
      resetView();
      return;
    }

    const minX = Math.min(...positions.map(([x]) => x));
    const maxX = Math.max(...positions.map(([x]) => x));
    const minY = Math.min(...positions.map(([, y]) => y));
    const maxY = Math.max(...positions.map(([, y]) => y));
    const canvasWidth = canvas.width || rect.width;
    const canvasHeight = canvas.height || rect.height;
    const padding = 40;
    const zoom = Math.max(0.2, Math.min(6, Math.min(
      Math.max(1, canvasWidth - padding * 2) / Math.max(1e-9, maxX - minX),
      Math.max(1, canvasHeight - padding * 2) / Math.max(1e-9, maxY - minY),
    )));
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    setTransform(prev => ({
      ...prev,
      zoom,
      panX: canvasWidth / 2 - (centerX - prev.originX) * zoom,
      panY: canvasHeight / 2 + (centerY - prev.originY) * zoom,
    }));
  };

  const toggleBoxSelection = () => {
    if (measurementMode) return;
    setSelectionRect(null);
    setIsBoxSelecting(prev => !prev);
  };

  const exportCurrentMapFigure = async () => {
    const mapCanvas = canvasRef.current;
    if (!mapCanvas || mapCanvas.width <= 0 || mapCanvas.height <= 0) {
      setFigureExportMessage("The 2D map viewport is not ready for export.");
      return;
    }
    if (isDrawingZone || isBoxSelecting || measurementMode) {
      setFigureExportMessage("Finish or cancel the active drawing, selection, or measurement tool before exporting.");
      return;
    }
    if (!figureExportReady || !canExportMapFigure(figureContext)) {
      setFigureExportMessage(figureContext.hasUnsavedChanges
        ? "Save or discard local design changes before exporting."
        : "Save and reload a workspace for the active StudyArea before exporting.");
      return;
    }

    setIsExportingFigure(true);
    setFigureExportMessage("Preparing PNG\u2026");
    try {
      const selectedIds = [...new Set([...selectedFeatureIds, ...(selectedFeatureId ? [selectedFeatureId] : [])])];
      const metadata = buildMapFigureMetadata({
        ...figureContext,
        selectedFeatureIds: selectedIds,
        transform,
        canvasWidth: mapCanvas.width,
        canvasHeight: mapCanvas.height,
        exportedAtUtc: new Date().toISOString(),
      });
      const figure = composeMapFigure(mapCanvas, metadata);
      const blob = await new Promise<Blob>((resolve, reject) => {
        figure.toBlob((value) => value ? resolve(value) : reject(new Error('PNG encoding failed.')), 'image/png');
      });
      const downloadUrl = URL.createObjectURL(blob);
      const download = document.createElement('a');
      download.href = downloadUrl;
      const safeStudyAreaId = metadata.studyArea.id.replace(/[^a-zA-Z0-9-]/g, '-');
      download.download = `rotterdam-m4h-${metadata.figureVersion}-workspace-r${metadata.workspace.revision}-${safeStudyAreaId}.png`;
      document.body.appendChild(download);
      download.click();
      download.remove();
      window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1_000);
      setFigureExportMessage(`PNG downloaded · ${metadata.workspace.id} r${metadata.workspace.revision} · ${metadata.analysisLayer?.resultStatus ?? 'spatial context only'}.`);
    } catch (error) {
      setFigureExportMessage(error instanceof Error ? `PNG export failed: ${error.message}` : "PNG export failed.");
    } finally {
      setIsExportingFigure(false);
    }
  };

  const mapExportDisabledReason = figureContext.hasUnsavedChanges
    ? t("Save or discard local design changes before exporting.")
    : figureContext.workspace?.status === 'STALE'
      ? t("Reload the current server workspace before exporting.")
    : isDrawingZone || isBoxSelecting || measurementMode
      ? t("Finish or cancel the active drawing, selection, or measurement tool before exporting.")
        : isExportingFigure
          ? t("The map figure is being prepared.")
      : t("Save and reload a workspace for the active StudyArea before exporting.");
  const mapExportDisabled = !figureExportReady
    || !canExportMapFigure(figureContext)
    || isDrawingZone
    || isBoxSelecting
    || Boolean(measurementMode)
    || isExportingFigure;

  const scaleBar = selectMapScaleBar({
    zoom: transform.zoom,
    // geoTransform.zoom is directly CSS pixels per EPSG:28992 metre.
    canvasWidth: 1,
    sceneWidth: 1,
  });
  const overlayPoints = measurementPoints.map(([x, y]) => epsg28992ToScreen(x, y, transform));
  const overlayMode = measurementMode ?? measurementResult?.mode ?? null;

  return (
    <div className="viewport2d-layout" style={{ width: '100%', height: '100%', overflow: 'hidden' }}>
      <details
        data-testid="surrounding-context-legend"
        aria-label={t("Surrounding context legend")}
        className="viewport2d-context-legend"
      >
        <summary title={t("Surrounding context legend")}>{t("Context")}</summary>
        <div className="viewport2d-context-legend__body">
          <span><span style={{ color: '#74b9dc' }}>■</span>{t("Water")}</span>
          <span><span style={{ color: '#99bd86' }}>■</span>{t("Green space")}</span>
          <span><span style={{ color: '#c4cdd3' }}>■</span>{t("Surrounding buildings")}</span>
          <span><span style={{ color: '#b8c2ca' }}>━</span>{t("Roads")}</span>
          {surroundingContext.data ? (
            <span>{(surroundingContext.data.metadata.context_distance_m / 1000).toFixed(0)}{t("km context ·")} {surroundingContext.data.metadata.source} · {surroundingContext.data.metadata.attribution} · {surroundingContext.data.metadata.license}</span>
          ) : (
            <span>{surroundingContext.status === 'error' ? t("OSM context unavailable") : t("Loading OSM context\u2026")}</span>
          )}
        </div>
      </details>

      {(activeSyntaxLayer || syntaxContextData) && (
        <details className="viewport2d-syntax-legend" aria-label={t('Space Syntax legend')} data-testid="viewport2d-syntax-legend">
          <summary title={t('Space Syntax legend')}>
            <span>{t('Space Syntax')}</span>
            {syntaxContextData && syntaxContextStatus === 'success' && (
              <span className="badge-exploratory" data-formal-result={syntaxContextData.readiness ? 'false' : undefined} style={{ marginLeft: '6px', fontSize: '9px', background: '#3b82f6', color: '#fff', padding: '1px 4px', borderRadius: '2px', fontWeight: 'bold' }}>
                <StatusBadge status={syntaxContextBadgeStatus(syntaxContextData)} language={language} />
              </span>
            )}
            {syntaxContextData?.readiness && syntaxContextData.readiness.formal_result !== true && syntaxContextStatus === 'success' && (
              <span data-testid="syntax-context-not-formal">{t('Not a formal result')}</span>
            )}
          </summary>
          <div className="viewport2d-syntax-legend__body">
            {syntaxContextData && syntaxContextStatus === 'success' && syntaxContextData.comparison_view !== 'diff' && syntaxContextData.legend_breaks && syntaxContextData.legend_breaks[syntaxMetric] ? (
              <>
                <div style={{ fontSize: '10px', color: '#94a3b8', marginBottom: '4px', display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  <span>{t('Scale: {scale}', { scale: syntaxMode === 'pedestrian' ? t('Walk 800 m') : syntaxMode === 'bicycle' ? t('Bicycle 2 km') : t('Car 10 km') })}</span>
                  <span>{t('Radius: {radius} m', { radius: syntaxContextData.radius_m })}</span>
                  <span>{t('Range: {range} km', { range: ((syntaxContextData?.distance_m ? syntaxContextData.distance_m / 1000 : syntaxDistanceKm)).toFixed(1) })}</span>
                  <span>{t('Metric: {metric}', { metric: syntaxMetric === 'nain' ? t('Integration (NAIN)') : t('Choice (NACH)') })}</span>
                </div>
                {buildClassificationFromBreaks(syntaxContextData.legend_breaks[syntaxMetric]).ranges.map((entry, index) => (
                  <span key={`${entry.label}-${index}`}>
                    <i aria-hidden="true" style={{ backgroundColor: entry.color }} />
                    {t(entry.label)}: {entry.min.toFixed(2)} - {entry.max.toFixed(2)}
                  </span>
                ))}
                <div style={{ fontSize: '10px', color: '#94a3b8', marginTop: '4px', borderTop: '1px solid rgba(148, 163, 184, 0.2)', paddingTop: '4px' }}>
                  {t('Faint dashed line = less than one radius to network boundary; boundary effect possible')}
                </div>
              </>
            ) : (
              <>
                {syntaxContextStatus === 'error' && (
                  <div style={{ color: '#f87171', fontSize: '10px', marginBottom: '4px' }}>
                    {t('Surrounding Space Syntax unavailable; falling back to site-only layer.')}
                    {syntaxContextError ? ` (${t(syntaxContextError)})` : ''}
                  </div>
                )}
                {syntaxLegend.map((entry, index) => (
                  <span key={`${entry.label}-${index}`}>
                    <i aria-hidden="true" style={{ backgroundColor: entry.color }} />{t(entry.label)}
                  </span>
                ))}
              </>
            )}
          </div>
        </details>
      )}
      <canvas
        ref={canvasRef}
        id="canvas-viewport-2d"
        data-render-transform={JSON.stringify(transform)}
        role="img"
        aria-label={t("Map viewport")}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => {
          if (isDraggingRef.current) {
            isDraggingRef.current = false;
            dragModeRef.current = null;
            setSelectionRect(null);
          }
        }}
        onDoubleClick={handleDoubleClick}
        onContextMenu={event => event.preventDefault()}
        style={{ width: '100%', height: '100%', display: 'block', cursor: isDrawingZone || isBoxSelecting || measurementMode ? 'crosshair' : 'grab' }}
      />

      {measurementPoints.length > 0 && overlayMode && (
        <svg
          className="viewport2d-measure-overlay"
          data-testid="measurement-overlay"
          aria-hidden="true"
        >
          {overlayMode === 'area' && measurementResult?.mode === 'area' && overlayPoints.length >= 3 ? (
            <polygon points={overlayPoints.map(([x, y]) => `${x},${y}`).join(' ')} />
          ) : overlayPoints.length >= 2 ? (
            <polyline points={overlayPoints.map(([x, y]) => `${x},${y}`).join(' ')} />
          ) : null}
          {overlayPoints.map(([x, y], index) => (
            <circle key={`${x}-${y}-${index}`} cx={x} cy={y} r="4" />
          ))}
        </svg>
      )}

      {selectedFeatureId && (
        <div id="selected-feature-2d" role="status" aria-live="polite" style={{ position: 'absolute', top: '52px', left: '16px', zIndex: 5, padding: '6px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface-glass)', border: '1px solid var(--accent-cyan)', color: 'var(--accent-cyan)', fontSize: '11px', overflowWrap: 'anywhere' }}>{t("Selected source feature:")} <code>{selectedFeatureId}</code>
          {selectedFeatureIds.length > 1 ? ` · ${selectedFeatureIds.length} ${t("selected")}` : ''}
        </div>
      )}

      {isBoxSelecting && !isDrawingZone && (
        <div role="status" style={{ position: 'absolute', top: '16px', left: '16px', zIndex: 5, padding: '7px 11px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-surface-glass)', border: '1px solid var(--accent-cyan)', color: 'var(--accent-cyan)', fontSize: '11px' }}>{t("Drag a map rectangle to select intersecting source features.")}
        </div>
      )}

      {/* Floating Drawing Status Banner */}
      {isDrawingZone && (
        <div style={{
          position: 'absolute',
          top: '16px',
          left: '50%',
          transform: 'translateX(-50%)',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          backgroundColor: 'rgba(24, 24, 27, 0.94)',
          padding: '8px 16px',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--accent-cyan)',
          backdropFilter: 'blur(8px)',
          zIndex: 10,
          boxShadow: 'var(--shadow-lg)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--accent-cyan)', fontSize: '12px', fontWeight: 600 }}>
            <Edit3 size={15} />
            <span>{t("Drawing Zone:")} {drawVertices.length}{t("vertices")}</span>
          </div>
          <button
            id="btn-finish-drawing"
            disabled={drawVertices.length < 3}
            onClick={handleFinish}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              backgroundColor: drawVertices.length >= 3 ? 'var(--accent-emerald)' : 'var(--bg-app)',
              color: drawVertices.length >= 3 ? '#ffffff' : 'var(--text-dim)',
              padding: '4px 10px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '11px',
              fontWeight: 600,
              cursor: drawVertices.length >= 3 ? 'pointer' : 'not-allowed',
            }}
          >
            <Check size={13} />{t("Finish Polygon")}
          </button>
          <button
            id="btn-cancel-drawing"
            onClick={handleCancel}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              backgroundColor: 'var(--bg-app)',
              color: 'var(--text-muted)',
              padding: '4px 10px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '11px',
              cursor: 'pointer',
            }}
          >
            <X size={13} />{t("Cancel")}
          </button>
        </div>
      )}

      {measurementMode && (
        <div className="viewport2d-measure-banner" role="region" aria-label={t("Measurement controls")}>
          <strong>{measurementMode === 'distance' ? t("Measure distance / length") : t("Measure polygon area")}</strong>
          <span>{measurementPoints.length}{t("points · EPSG:28992 metres")}</span>
          <button
            type="button"
            aria-label={t("Finish measurement")}
            disabled={measurementPoints.length < (measurementMode === 'distance' ? 2 : 3)}
            onClick={finishMeasurement}
          >
            <Check size={13} />{t("Finish")}
          </button>
          <button type="button" aria-label={t("Cancel measurement")} onClick={cancelMeasurement}>
            <X size={13} />{t("Cancel")}
          </button>
          {measurementError && <span role="status" aria-label={t("Measurement error")}>{t(measurementError)}</span>}
        </div>
      )}

      {(measurementResult || measurementError) && !measurementMode && (
        <div className="viewport2d-measure-result" role="status" aria-label={t("Measurement result")}>
          {measurementResult?.mode === 'distance' && (
            <span>{t("Length:")} {formatMeasureValue(measurementResult.value.value)}{' '}{t("m")}</span>
          )}
          {measurementResult?.mode === 'area' && (
            <>
              <span>{t("Area:")} {formatMeasureValue(measurementResult.value.area.value)}{' '}{t("m²")}</span>
              <span>{t("Perimeter:")} {formatMeasureValue(measurementResult.value.perimeter.value)}{' '}{t("m")}</span>
            </>
          )}
          {measurementError && <span role="status" aria-label={t("Measurement error")}>{t(measurementError)}</span>}
          <span className="viewport2d-measure-note">{t("Local measurement only · excluded from evidence and exports")}</span>
          <button type="button" aria-label={t("Clear measurement")} onClick={cancelMeasurement}>{t("Clear")}</button>
        </div>
      )}

      <div className="viewport2d-tool-rail" role="toolbar" aria-label={t('Map tools')}>
        <button
          id="btn-export-map-figure"
          type="button"
          aria-label={t("Export analysis map figure (PNG)")}
          title={t("Export analysis map figure (PNG)")}
          aria-describedby="status-map-figure-export"
          disabled={mapExportDisabled}
          onClick={exportCurrentMapFigure}
        >
          <Download size={16} />
        </button>
        <span id="status-map-figure-export" role="status" aria-live="polite" className="visually-hidden">
          {t(mapExportDisabled ? mapExportDisabledReason : figureExportMessage)}
        </span>
        <span className="viewport2d-tool-divider" />
        <button
          id="btn-toggle-box-select"
          type="button"
          aria-label={t("Box select")}
          title={t("Drag a rectangle to select intersecting source features")}
          aria-pressed={isBoxSelecting}
          disabled={isDrawingZone || Boolean(measurementMode)}
          onClick={toggleBoxSelection}
        ><Square size={16} />
        </button>
        <button
          id="btn-measure-distance"
          type="button"
          aria-label={t("Measure distance")}
          title={t("Measure distance")}
          aria-pressed={measurementMode === 'distance'}
          disabled={isDrawingZone}
          onClick={() => startMeasurement('distance')}
        >
          <Ruler size={16} />
        </button>
        <button
          id="btn-measure-area"
          type="button"
          aria-label={t("Measure area")}
          title={t("Measure area")}
          aria-pressed={measurementMode === 'area'}
          disabled={isDrawingZone}
          onClick={() => startMeasurement('area')}
        >
          <Square size={16} />
        </button>
        {onToggleDrawingZone && (
          <button
            id="btn-toggle-draw-polygon"
            aria-label={isDrawingZone ? t("Cancel Drawing") : t("Draw Brief Zone Polygon")}
            title={isDrawingZone ? t("Cancel Drawing") : t("Draw Brief Zone Polygon")}
            onClick={onToggleDrawingZone}
            disabled={Boolean(measurementMode)}
            style={{
              padding: '6px',
              color: isDrawingZone ? '#090d16' : 'var(--accent-cyan)',
              backgroundColor: isDrawingZone ? 'var(--accent-cyan)' : 'transparent',
              borderRadius: 'var(--radius-sm)',
              border: `1px solid ${isDrawingZone ? 'var(--accent-cyan)' : 'var(--border-subtle)'}`,
            }}
          >
            <Edit3 size={16} />
          </button>
        )}
        <span className="viewport2d-tool-divider" />
        <button
          aria-label={t("Zoom In")}
          title={t("Zoom In")}
          onClick={zoomIn}
          style={{ padding: '6px', color: 'var(--text-main)', borderRadius: 'var(--radius-sm)' }}
        >
          <ZoomIn size={16} />
        </button>
        <button
          aria-label={t("Zoom Out")}
          title={t("Zoom Out")}
          onClick={zoomOut}
          style={{ padding: '6px', color: 'var(--text-main)', borderRadius: 'var(--radius-sm)' }}
        >
          <ZoomOut size={16} />
        </button>
        <button
          aria-label={t("Reset View")}
          title={t("Reset View")}
          onClick={resetView}
          style={{ padding: '6px', color: 'var(--text-main)', borderRadius: 'var(--radius-sm)' }}
        >
          <RotateCcw size={16} />
        </button>
      </div>

      <div className="viewport2d-map-decoration">
        <div className="viewport2d-north" role="img" aria-label={t("Grid north indicator")}>
          <span aria-hidden="true">↑</span>
          <span>{t("Grid north")}</span>
        </div>
        <div
          className="viewport2d-scale"
          data-testid="scale-bar"
          data-meters-per-pixel={scaleBar.metersPerPixel.toFixed(6)}
          aria-label={`${t("Scale bar")} ${formatScaleDistance(scaleBar.distanceMeters)}; ${scaleBar.metersPerPixel.toFixed(2)} m/px`}
        >
          <span className="viewport2d-scale-line" style={{ width: `${scaleBar.lengthPixels}px` }} />
          <span>{formatScaleDistance(scaleBar.distanceMeters)}</span>
        </div>
      </div>

      {/* Coordinate & view scale */}
      <div style={{
        position: 'absolute',
        bottom: '12px',
        left: '16px',
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        fontSize: '11px',
        fontFamily: 'var(--font-mono)',
        color: 'var(--text-muted)',
        backgroundColor: 'var(--bg-surface-glass)',
        padding: '4px 10px',
        borderRadius: 'var(--radius-sm)',
        border: '1px solid var(--border-subtle)',
        backdropFilter: 'blur(6px)',
      }}>
        <span>{t("X:")} {mouseCoord[0]}{t("m")}</span>
        <span>{t("Y:")} {mouseCoord[1]}{t("m")}</span>
        <span style={{ color: 'var(--text-dim)' }}>|</span>
        <span>{t("EPSG:28992 (RD New)")}</span>
        <span style={{ color: 'var(--text-dim)' }}>|</span>
        <span>{t("Zoom:")} {Math.round(transform.zoom * 100)}%</span>
      </div>
    </div>
  );
};

function formatMeasureValue(value: number): string {
  return value.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatScaleDistance(value: number): string {
  if (value >= 1000) {
    return `${(value / 1000).toLocaleString('en-GB', { maximumFractionDigits: 2 })} km`;
  }
  return `${value.toLocaleString('en-GB', { maximumFractionDigits: value < 1 ? 2 : 0 })} m`;
}

// Simple point in polygon test
function pointInPolygon(pt: [number, number], ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    const intersect = ((yi > pt[1]) !== (yj > pt[1])) && (pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function pointToSegmentDist(p: [number, number], v: number[], w: number[]): number {
  const l2 = (w[0] - v[0]) ** 2 + (w[1] - v[1]) ** 2;
  if (l2 === 0) return Math.hypot(p[0] - v[0], p[1] - v[1]);
  let t = ((p[0] - v[0]) * (w[0] - v[0]) + (p[1] - v[1]) * (w[1] - v[1])) / l2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p[0] - (v[0] + t * (w[0] - v[0])), p[1] - (v[1] + t * (w[1] - v[1])));
}
