// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {ScenarioStudioDashboard} from './ScenarioStudioDashboard';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('renders only server metrics and keeps unavailable site totals explicit', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    provenance: 'FORMAL_DRAFT', metric_state: 'NOT_READY', scenario_revision: 2,
    selected_building: {gfa_m2: 1000}, site: {far: null},
  }), {status: 200}));
  render(<ScenarioStudioDashboard apiBase="" scenarioId="synthetic" buildingId="building" scenarioRevision={2} />);
  expect(await screen.findByText(/FORMAL_DRAFT/)).toHaveTextContent('NOT_READY');
  expect(screen.getByText('1000 m²')).toBeInTheDocument();
  expect(screen.getByText('Unavailable')).toBeInTheDocument();
});
it('rejects a stale server revision instead of showing it as current', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    provenance: 'FIXTURE_ONLY', metric_state: 'BACKEND_CONFIRMED', scenario_revision: 1,
    selected_building: {gfa_m2: 1000}, site: {far: 1},
  }), {status: 200}));
  render(<ScenarioStudioDashboard apiBase="" scenarioId="synthetic" buildingId="building" scenarioRevision={2} />);
  expect(await screen.findByText('NOT_READY')).toBeInTheDocument();
  expect(screen.queryByText('1000 m²')).not.toBeInTheDocument();
});
