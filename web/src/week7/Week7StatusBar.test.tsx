// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { Week7StatusBar } from './Week7StatusBar';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const staleView = {
  revision_label: 'revision rev-b2',
  scenario_id: 'B2',
  freshness_text: 'STALE 結果已過時',
  geometry_valid: false,
  human_status: 'not_reviewed',
  run_status: 'SUCCEEDED',
  evidence_status: 'unverified',
  evidence_availability: 'complete',
  live_ai_label: 'OFFLINE mock — not a live model reply',
  panels: { ai: { evidence_ids: ['card-b2-sun'] } },
};

it('shows the server revision label and the word STALE as text', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(staleView), { status: 200 }));
  render(<Week7StatusBar apiBase="http://127.0.0.1:8901" workspaceId="ws-w7" />);
  expect(await screen.findByTestId('week7-revision')).toHaveTextContent('revision rev-b2');
  const freshness = screen.getByTestId('week7-freshness');
  expect(freshness).toHaveTextContent('STALE');
  expect(freshness).toHaveTextContent('結果已過時');
  expect(freshness).not.toHaveAttribute('style', expect.stringMatching(/color/));
  expect(screen.getByText('geometry false')).toBeInTheDocument();
  expect(screen.getByText('human not_reviewed')).toBeInTheDocument();
  expect(screen.getByText('run SUCCEEDED')).toBeInTheDocument();
  expect(screen.getByText('evidence unverified / complete')).toBeInTheDocument();
  expect(screen.getByTestId('week7-live-ai')).toHaveTextContent('Offline');
});

it.each([
  ['en', 'Offline'],
  ['zh-TW', '離線'],
] as const)('renders the localized OFFLINE label in %s', async (lang, expectedLabel) => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(staleView), { status: 200 }));
  render(
    <I18nProvider language={lang}>
      <Week7StatusBar apiBase="http://127.0.0.1:8901" workspaceId="ws-w7" />
    </I18nProvider>,
  );
  expect(await screen.findByTestId('week7-live-ai')).toHaveTextContent(expectedLabel);
});

it('does not invent a revision when the workspace is missing', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 409 }));
  render(<Week7StatusBar apiBase="http://127.0.0.1:8901" workspaceId="missing" />);
  expect(await screen.findByTestId('week7-revision')).toHaveTextContent('revision unavailable');
  expect(screen.queryByText(/revision rev-/)).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalled();
});

it('shows the persisted map revision and publishes the view for the shell', async () => {
  const seen: unknown[] = [];
  const onView = (event: Event) => seen.push((event as CustomEvent).detail);
  window.addEventListener('week7-persisted-view', onView);
  const view = {
    ...staleView,
    revision: 'rev-b2',
    shell: {
      authority_state: 'READY',
      study_area_id: 'study-area-rotterdam-m4h-pilot-project-v5',
      workspace_revision: 'rev-b2',
    },
    map: {
      revision: 'rev-b2',
      scenario_id: 'B2',
      features: [{
        id: 'B2-rev-b2-footprint',
        scenario_id: 'B2',
        revision: 'rev-b2',
        kind: 'footprint',
        disposition: 'EDITABLE',
        geometry: { type: 'Polygon', coordinates: [[[89160, 435880], [89210, 435880], [89210, 435915], [89160, 435915], [89160, 435880]]] },
        provenance: 'FIXTURE_ONLY',
      }],
    },
  };
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(view), { status: 200 }));
  render(<Week7StatusBar apiBase="http://127.0.0.1:8901" workspaceId="ws-w7" />);
  expect(await screen.findByTestId('week7-map-revision')).toHaveTextContent('map revision rev-b2 feature B2-rev-b2-footprint');
  expect(seen).toHaveLength(1);
  window.removeEventListener('week7-persisted-view', onView);
});

it('expands an evidence card from the persisted payload', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith('/view')) return new Response(JSON.stringify(staleView), { status: 200 });
    return new Response(JSON.stringify({
      evidence_id: 'card-b2-sun',
      source: 'fixture sun B2',
      formula: 'stored',
      unit: 'hour',
      version: 'rev-b2',
      limits: 'FIXTURE_ONLY',
    }), { status: 200 });
  });
  render(<Week7StatusBar apiBase="http://127.0.0.1:8901" workspaceId="ws-w7" />);
  await screen.findByText('Evidence (1)');
  expect(screen.queryByText('card-b2-sun')).not.toBeInTheDocument();
  expect(screen.getByText('Evidence (1)').closest('details')).not.toHaveAttribute('open');
  fireEvent.click(screen.getByText('Evidence (1)'));
  screen.getByText('Evidence (1)').closest('details')!.open = true;
  fireEvent.click(screen.getByRole('button', { name: 'Inspect evidence 1' }));
  expect(await screen.findByTestId('week7-card')).toHaveTextContent('fixture sun B2');
  expect(screen.getByText('stored')).toBeInTheDocument();
  expect(screen.getByText('hour')).toBeInTheDocument();
  expect(screen.getByText('rev-b2')).toBeInTheDocument();
  expect(screen.getByText('FIXTURE_ONLY')).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalled();
});
