import { useEffect, useState } from 'react';

export type ContextLayerName = 'water' | 'green' | 'buildings' | 'roads';

export interface ContextFeature {
  type: 'Feature';
  id?: string;
  geometry: {
    type: string;
    coordinates: any;
  } | null;
  properties: Record<string, any>;
}

export interface ContextFeatureCollection {
  type: 'FeatureCollection';
  features: ContextFeature[];
}

export interface SurroundingContextResponse {
  metadata: {
    schema_version: string;
    project_id: string;
    study_area_id: string;
    study_area_version: string;
    study_area_geometry_sha256: string;
    crs: 'EPSG:28992';
    units: 'm';
    context_distance_m: number;
    source: 'OpenStreetMap';
    source_data_version: string;
    source_pbf_sha256: string;
    license: 'ODbL 1.0';
    attribution: string;
    tolerance_m: number;
    height_policy?: Record<string, unknown>;
    '3dbag'?: Record<string, unknown>;
  };
  layers: Record<ContextLayerName, ContextFeatureCollection>;
}

export interface ContextLayerStyle {
  fill: string;
  stroke: string;
  opacity: number;
  lineWidth: number;
}

export interface ContextLayerPlanEntry {
  name: ContextLayerName;
  features: ContextFeature[];
  style: ContextLayerStyle;
}

export const CONTEXT_LAYER_ORDER: ContextLayerName[] = ['water', 'green', 'buildings', 'roads'];

const CONTEXT_LAYER_STYLES: Record<ContextLayerName, ContextLayerStyle> = {
  water: { fill: 'rgba(56, 145, 196, 0.34)', stroke: 'rgba(99, 190, 226, 0.65)', opacity: 0.68, lineWidth: 0.75 },
  green: { fill: 'rgba(121, 166, 112, 0.22)', stroke: 'rgba(156, 197, 135, 0.34)', opacity: 0.52, lineWidth: 0.55 },
  buildings: { fill: 'rgba(184, 194, 202, 0.18)', stroke: 'rgba(208, 216, 222, 0.34)', opacity: 0.3, lineWidth: 0.45 },
  roads: { fill: 'transparent', stroke: 'rgba(184, 194, 202, 0.45)', opacity: 0.6, lineWidth: 0.55 },
};

export function buildContextLayerPlan(
  layers: Partial<Record<ContextLayerName, ContextFeatureCollection>>,
): ContextLayerPlanEntry[] {
  return CONTEXT_LAYER_ORDER.map((name) => ({
    name,
    features: layers[name]?.features ?? [],
    style: CONTEXT_LAYER_STYLES[name],
  }));
}

export function getContextToleranceMeters(mapZoom: number): number {
  const zoom = Number.isFinite(mapZoom) ? Math.max(0.05, mapZoom) : 0.05;
  return Math.min(20, Math.max(0, 0.8 / zoom));
}

export function getContextBuildingExtrusion(properties: Record<string, any>): { heightM: number; legend: string } | null {
  const heightM = properties.height_m;
  if (typeof heightM !== 'number' || !Number.isFinite(heightM) || heightM <= 0) return null;
  switch (properties.height_source) {
    case '3DBAG':
      return { heightM, legend: `3D BAG ${properties.height_source_version || 'height table'}` };
    case 'OSM_HEIGHT':
      return { heightM, legend: 'OSM height tag' };
    case 'OSM_BUILDING_LEVELS_DISPLAY_ASSUMPTION':
      return { heightM, legend: 'OSM levels × 3 m/storey display assumption' };
    default:
      return null;
  }
}

const API_BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8789').replace(/\/$/, '');
const PROJECT_ID = 'rotterdam-m4h-pilot-project';
const contextCache = new Map<number, SurroundingContextResponse>();
const contextPending = new Map<number, Promise<SurroundingContextResponse>>();

export async function fetchSurroundingContext(toleranceMeters: number): Promise<SurroundingContextResponse> {
  const tolerance = Math.round(Math.max(0, Math.min(50, toleranceMeters)) * 100) / 100;
  const cached = contextCache.get(tolerance);
  if (cached) return cached;
  const existing = contextPending.get(tolerance);
  if (existing) return existing;
  const request = fetch(
    `${API_BASE}/api/v1/projects/${PROJECT_ID}/surrounding-context?tolerance_m=${tolerance}`,
  ).then(async (response) => {
    if (!response.ok) throw new Error(`Surrounding context request failed (${response.status})`);
    const result = await response.json() as SurroundingContextResponse;
    contextCache.set(tolerance, result);
    return result;
  }).finally(() => {
    contextPending.delete(tolerance);
  });
  contextPending.set(tolerance, request);
  return request;
}

export type ContextLoadState = {
  data: SurroundingContextResponse | null;
  status: 'loading' | 'ready' | 'error';
};

export function useSurroundingContext(toleranceMeters: number): ContextLoadState {
  const tolerance = Math.round(Math.max(0, Math.min(50, toleranceMeters)) * 100) / 100;
  const [state, setState] = useState<ContextLoadState>({ data: null, status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      fetchSurroundingContext(tolerance).then((data) => {
        if (!cancelled) setState({ data, status: 'ready' });
      }).catch(() => {
        if (!cancelled) setState((current) => ({ data: current.data, status: 'error' }));
      });
    }, 100);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [tolerance]);

  return state;
}
