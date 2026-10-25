import { expect, it } from 'vitest';
import { surfacesFromWeek7View, type Week7SurfaceView } from './surfacesFromWeek7View';

function view(revision: string, scenarioId: string, far: number): Week7SurfaceView {
  const panel = {
    revision,
    scenario_id: scenarioId,
    far,
    far_unit: 'ratio',
    evidence_ids: [`card-${scenarioId.toLowerCase()}-sun`],
  };
  return {
    workspace_id: 'ws-w7',
    project_id: 'rotterdam-m4h-pilot-project',
    scenario_id: scenarioId,
    revision,
    freshness: 'stale',
    evidence_status: 'UNVERIFIED',
    shell: {
      study_area_id: 'study-area-rotterdam-m4h-pilot-project-v5',
      study_area_revision: 6,
      workspace_revision: revision,
    },
    map: { revision, scenario_id: scenarioId },
    panels: {
      map: panel,
      model3d: { ...panel },
      dashboard: { ...panel },
      ai: { ...panel },
      chart: { ...panel },
      export: { ...panel },
    },
    cards: [{
      evidence_id: panel.evidence_ids[0],
      scenario_id: scenarioId,
      revision,
      source: `fixture sun ${scenarioId}`,
      formula: 'stored',
      unit: 'hour',
      version: revision,
      limits: 'FIXTURE_ONLY',
      period: '2026-06-21',
      validation_status: 'invalid',
      numbers: [far],
      provenance: 'FIXTURE_ONLY',
    }],
  };
}

it('cites one persisted revision on dashboard, charts, ai, export, and compare', () => {
  const bound = surfacesFromWeek7View(view('rev-b2', 'B2', 2.2));
  expect(bound?.dashboardLabel).toBe('dashboard revision rev-b2 scenario B2 far 2.20 ratio card card-b2-sun');
  expect(bound?.chartsLabel).toContain('charts revision rev-b2');
  expect(bound?.aiLabel).toContain('ai revision rev-b2');
  expect(bound?.exportLabel).toContain('export revision rev-b2');
  expect(bound?.compareLabel).toContain('compare revision rev-b2');
  expect(bound?.figureCitation.revision).toBe('rev-b2');
  expect(bound?.figureCitation.status).toBe('STALE');
  expect(bound?.evidenceCards[0]?.status).toBe('invalid');
  expect(bound?.evidenceCards[0]?.metric_name).toBe('fixture sun B2');
  expect(bound?.evidenceCards[0]?.input_sha256).toBe('');
  expect(bound?.evidenceCards[0]?.limitations).toEqual(['FIXTURE_ONLY']);
});

it('refuses surfaces when a panel cites another revision', () => {
  const mixed = view('rev-b2', 'B2', 2.2);
  mixed.panels = { ...mixed.panels, ai: { ...mixed.panels?.ai, revision: 'rev-b0' } };
  expect(surfacesFromWeek7View(mixed)).toBeNull();
});

it('formats persisted FAR to two decimals without changing its measurement', () => {
 const bound = surfacesFromWeek7View(view('rev-b2', 'B2', 0.7644361027674244));
 expect(bound?.compareLabel).toContain('far 0.76 ratio');
 expect(bound?.far).toBe(0.7644361027674244);
});
