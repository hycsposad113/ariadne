// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import App from './App';

vi.mock('./components/Viewport2D', () => ({
  Viewport2D: ({ figureContext }: { figureContext?: { workspace?: { revision?: number | string } | null } }) => (
    <div data-testid="plan-revision">{String(figureContext?.workspace?.revision ?? '')}</div>
  ),
}));
vi.mock('./components/Viewport3D', () => ({
  Viewport3D: ({ figureContext }: { figureContext?: { workspace?: { revision?: number | string } | null } }) => (
    <div data-testid="volume-revision">{String(figureContext?.workspace?.revision ?? '')}</div>
  ),
}));
vi.mock('./components/CompareWorkspace', () => ({
  CompareWorkspace: ({ boundRevision }: { boundRevision?: { label?: string } | null }) => (
    <div data-testid="compare-bound-revision">{boundRevision?.label ?? ''}</div>
  ),
}));

type Scheme = { scenarioId: string; revision: string; far: number; source: string; cardId: string };

let current: Scheme = { scenarioId: 'B2', revision: 'rev-b2', far: 2.2, source: 'fixture sun B2', cardId: 'card-b2-sun' };

function persistedView(scheme: Scheme) {
  const panel = {
    revision: scheme.revision,
    scenario_id: scheme.scenarioId,
    far: scheme.far,
    far_unit: 'ratio',
    evidence_ids: [scheme.cardId],
  };
  return {
    workspace_id: 'ws-w7',
    project_id: 'rotterdam-m4h-pilot-project',
    scenario_id: scheme.scenarioId,
    revision: scheme.revision,
    revision_label: `revision ${scheme.revision}`,
    freshness: 'stale',
    freshness_text: 'STALE 結果已過時',
    geometry_valid: true,
    human_status: 'not_reviewed',
    run_status: 'succeeded',
    evidence_status: 'UNVERIFIED',
    evidence_availability: 'complete',
    live_ai_label: 'OFFLINE mock — not a live model reply',
    shell: {
      authority_state: 'READY',
      study_area_id: 'study-area-rotterdam-m4h-pilot-project-v5',
      study_area_revision: 6,
      workspace_revision: scheme.revision,
    },
    map: {
      revision: scheme.revision,
      scenario_id: scheme.scenarioId,
      features: [{
        id: `${scheme.scenarioId}-${scheme.revision}-footprint`,
        scenario_id: scheme.scenarioId,
        revision: scheme.revision,
        kind: 'footprint',
        disposition: 'EDITABLE',
        geometry: { type: 'Polygon', coordinates: [[[89160, 435880], [89210, 435880], [89210, 435915], [89160, 435915], [89160, 435880]]] },
        provenance: 'FIXTURE_ONLY',
      }],
    },
    panels: {
      map: panel,
      model3d: { ...panel },
      dashboard: { ...panel },
      ai: { ...panel },
      chart: { ...panel },
      export: { ...panel },
    },
    cards: [{
      evidence_id: scheme.cardId,
      scenario_id: scheme.scenarioId,
      revision: scheme.revision,
      source: scheme.source,
      formula: 'stored',
      unit: 'hour',
      version: scheme.revision,
      limits: 'FIXTURE_ONLY',
      period: '2026-06-21',
      validation_status: 'invalid',
      numbers: [scheme.far],
      provenance: 'FIXTURE_ONLY',
    }],
  };
}

afterEach(() => {
  cleanup();
  window.history.pushState({}, '', '/');
  localStorage.clear();
  vi.restoreAllMocks();
});

test('week7 surfaces follow the persisted revision after switch and reload', async () => {
  window.history.pushState({}, '', '/?week7Workspace=ws-w7');
  current = { scenarioId: 'B2', revision: 'rev-b2', far: 2.2, source: 'fixture sun B2', cardId: 'card-b2-sun' };
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes('/operations/') || url.endsWith('/switch')) {
      if (init?.body && String(init.body).includes('rev-b1')) {
        current = { scenarioId: 'B1', revision: 'rev-b1', far: 1.1, source: 'fixture sun B1', cardId: 'card-b1-sun' };
      }
      if (init?.body && String(init.body).includes('rev-b2')) {
        current = { scenarioId: 'B2', revision: 'rev-b2', far: 2.2, source: 'fixture sun B2', cardId: 'card-b2-sun' };
      }
      return { ok: true, status: 200, json: async () => persistedView(current) };
    }
    if (url.includes('/api/v1/week7/workspaces/') && url.endsWith('/view')) {
      return { ok: true, status: 200, json: async () => persistedView(current) };
    }
    if (url.endsWith('/api/v1/week7/e3e4')) {
      return { ok: true, status: 200, json: async () => ({ e3: { status: 'NOT_ACCEPTED' }, e4: { status: 'NOT_ACCEPTED' } }) };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  }));

  const first = render(<App />);
  await screen.findByTestId('site-fact-card-card-b2-sun');
  expect(screen.queryByTestId('week7-bound-surfaces')).toBeNull();
  expect(screen.getByTestId('plan-revision').textContent).toBe('rev-b2');
  expect(screen.getByTestId('site-fact-card-card-b2-sun').textContent).toContain('fixture sun B2');
  expect(screen.getByTestId('site-fact-card-card-b2-sun').textContent).not.toContain('VERIFIED_OBSERVATION');
  fireEvent.click(screen.getByRole('button', { name: '3D' }));
  expect(screen.getByTestId('volume-revision').textContent).toBe('rev-b2');

  fireEvent.click(screen.getByTestId('week7-switch-B1'));
  await waitFor(() => {
    expect(screen.getByTestId('volume-revision').textContent).toBe('rev-b1');
  });
  expect(screen.getByTestId('volume-revision').textContent).toBe('rev-b1');
  expect(screen.getByTestId('site-fact-card-card-b1-sun').textContent).toContain('fixture sun B1');

  first.unmount();
  render(<App />);
  await screen.findByTestId('site-fact-card-card-b1-sun');
  expect(screen.queryByTestId('week7-bound-surfaces')).toBeNull();
  expect(screen.getByTestId('plan-revision').textContent).toBe('rev-b1');
  fireEvent.click(document.querySelector('#stage-compare') as HTMLButtonElement);
  expect(screen.getByTestId('compare-bound-revision').textContent).toContain('compare revision rev-b1');
});
