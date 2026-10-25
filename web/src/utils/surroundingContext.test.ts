import { describe, expect, it } from 'vitest';
import {
  buildContextLayerPlan,
  getContextBuildingExtrusion,
  getContextToleranceMeters,
} from './surroundingContext';

describe('surrounding context rendering', () => {
  it('draws water and green ground before faint buildings and roads', () => {
    const plan = buildContextLayerPlan({
      buildings: { type: 'FeatureCollection', features: [{ type: 'Feature', id: 'way/1', geometry: null, properties: {} }] },
      water: { type: 'FeatureCollection', features: [] },
      green: { type: 'FeatureCollection', features: [{ type: 'Feature', id: 'way/2', geometry: null, properties: {} }] },
      roads: { type: 'FeatureCollection', features: [] },
    });

    expect(plan.map(layer => layer.name)).toEqual(['water', 'green', 'buildings', 'roads']);
    expect(plan.find(layer => layer.name === 'water')?.style.fill).toMatch(/blue|rgba/i);
    expect(plan.find(layer => layer.name === 'green')?.style.fill).toMatch(/green|rgba/i);
    expect(plan.find(layer => layer.name === 'buildings')?.style.opacity).toBeLessThan(0.5);
    expect(plan.find(layer => layer.name === 'roads')?.style.lineWidth).toBeLessThan(1);
  });

  it('uses 3D BAG height before OSM height and marks level extrusion as an assumption', () => {
    expect(getContextBuildingExtrusion({
      height_m: 18.25,
      height_source: '3DBAG',
      height_source_version: 'v2025.09.03',
      osm_height_m: 22,
    })).toEqual({ heightM: 18.25, legend: '3D BAG v2025.09.03' });
    expect(getContextBuildingExtrusion({
      height_m: 9.5,
      height_source: 'OSM_HEIGHT',
    })).toEqual({ heightM: 9.5, legend: 'OSM height tag' });
    expect(getContextBuildingExtrusion({
      height_m: 6,
      height_source: 'OSM_BUILDING_LEVELS_DISPLAY_ASSUMPTION',
    })).toEqual({ heightM: 6, legend: 'OSM levels × 3 m/storey display assumption' });
    expect(getContextBuildingExtrusion({ height_source: 'FOOTPRINT_ONLY' })).toBeNull();
  });

  it('requests more geometry detail as the 2D view zooms in', () => {
    expect(getContextToleranceMeters(0.2)).toBeGreaterThan(getContextToleranceMeters(4));
    expect(getContextToleranceMeters(4)).toBeGreaterThanOrEqual(0);
    expect(getContextToleranceMeters(0.2)).toBeLessThanOrEqual(20);
  });
});
