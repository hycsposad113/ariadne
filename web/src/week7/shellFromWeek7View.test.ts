import { expect, it } from 'vitest';
import { shellFromWeek7View, type Week7PersistedView } from './shellFromWeek7View';

const aligned: Week7PersistedView = {
  revision: 'rev-b2',
  scenario_id: 'B2',
  shell: {
    authority_state: 'READY',
    study_area_id: 'study-area-rotterdam-m4h-pilot-project-v5',
    workspace_revision: 'rev-b2',
  },
  map: {
    revision: 'rev-b2',
    scenario_id: 'B2',
    features: [
      {
        id: 'B2-rev-b2-footprint',
        scenario_id: 'B2',
        revision: 'rev-b2',
        kind: 'footprint',
        disposition: 'EDITABLE',
        geometry: { type: 'Polygon', coordinates: [[[89160, 435880], [89210, 435880], [89210, 435915], [89160, 435915], [89160, 435880]]] },
        provenance: 'FIXTURE_ONLY',
      },
      {
        id: 'B1-rev-b1-footprint',
        scenario_id: 'B1',
        revision: 'rev-b1',
        disposition: 'EDITABLE',
        geometry: { type: 'Polygon', coordinates: [[[89080, 435880], [89130, 435880], [89130, 435915], [89080, 435915], [89080, 435880]]] },
        provenance: 'FIXTURE_ONLY',
      },
    ],
  },
};

it('keeps only the current head footprint and marks the shell ready', () => {
  const applied = shellFromWeek7View(aligned);
  expect(applied?.authorityState).toBe('READY');
  expect(applied?.studyAreaId).toBe('study-area-rotterdam-m4h-pilot-project-v5');
  expect(applied?.workspaceRevision).toBe('rev-b2');
  expect(applied?.buildings.map(building => building.id)).toEqual(['B2-rev-b2-footprint']);
  expect(applied?.mapLabel).toBe('map revision rev-b2 feature B2-rev-b2-footprint');
});

it('refuses a map whose revision is not the head revision', () => {
  const mismatched: Week7PersistedView = {
    ...aligned,
    map: { ...aligned.map, revision: 'rev-b1', features: aligned.map?.features },
  };
  expect(shellFromWeek7View(mismatched)).toBeNull();
});

it('refuses a shell that is not READY', () => {
  const loading: Week7PersistedView = {
    ...aligned,
    shell: { ...aligned.shell, authority_state: 'LOADING' },
  };
  expect(shellFromWeek7View(loading)).toBeNull();
});
