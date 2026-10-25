// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
beforeEach(() => localStorage.setItem('urban-design-language', 'en'));
import { EnvironmentPanel } from './EnvironmentPanel';
import { I18nProvider } from '../i18n';

const proposals = [
  { id: 'formal-baseline', strategy: 'Baseline', status: 'ACCEPTED' },
  { id: 'formal-proposal', strategy: 'Proposal A', status: 'PROPOSED' },
];

const draftPlan = {
  plan_id: 'e1-plan-rotterdam-draft-v1',
  status: 'DRAFT_UNAPPROVED',
  period: {
    dates: ['2026-03-21', '2026-06-21', '2026-12-21'],
    start_hour: 8,
    end_hour: 18,
    timestep: 4,
  },
  location: { latitude: 51.9, longitude: 4.45, timezone: 'Europe/Amsterdam' },
  grid_definition: { spacing_m: 5, crs: 'EPSG:28992' },
  true_north_offset_deg: -0.73916,
  comparison_domain: 'Per scheme: site land minus new and retained building footprints and water; streets and roads are included as public space. Paired delta uses the intersection of both domains.',
  notes: 'E1_PLAN: DRAFT_DOMAIN_FOUNDER_2026-10-04. Dates, time window, sensor grid, and resolution remain unapproved.',
};

const colormap = {
  min_value: 0,
  max_value: 30,
  unit: 'hours',
  palette_name: 'sunlight_amber_indigo',
  bins: [
    { min_hours: 0, max_hours: 6, color_hex: '#0d1b2a', label: '0-6 h' },
    { min_hours: 6, max_hours: 12, color_hex: '#1b4965', label: '6-12 h' },
    { min_hours: 12, max_hours: 18, color_hex: '#5fa8d3', label: '12-18 h' },
    { min_hours: 18, max_hours: 24, color_hex: '#f4a261', label: '18-24 h' },
    { min_hours: 24, max_hours: 30, color_hex: '#e76f51', label: '24-30 h' },
  ],
};

const result = {
  run_id: 'e1-run-test',
  status: 'SUCCESS',
  plan: draftPlan,
  method: 'ladybug_radiance',
  engine: 'ladybug-sunpath+ladybug-radiance',
  baseline_sunlight: {
    results: [
      { point_id: 'pt-a', coordinates: [0, 0, 0], status: 'VALID', sunlight_hours: 12, visible_samples: 48, total_daytime_samples: 120, direct_fraction: 0.4 },
      { point_id: 'pt-b', coordinates: [5, 0, 0], status: 'VALID', sunlight_hours: 18, visible_samples: 72, total_daytime_samples: 120, direct_fraction: 0.6 },
    ],
  },
  modified_sunlight: {
    results: [
      { point_id: 'pt-a', coordinates: [0, 0, 0], status: 'VALID', sunlight_hours: 6, visible_samples: 24, total_daytime_samples: 120, direct_fraction: 0.2 },
      { point_id: 'pt-b', coordinates: [5, 0, 0], status: 'VALID', sunlight_hours: 12, visible_samples: 48, total_daytime_samples: 120, direct_fraction: 0.4 },
    ],
  },
  comparison: {
    comparable: true,
    baseline_method: 'ladybug_radiance',
    modified_method: 'ladybug_radiance',
    grid_hash: 'sha256:grid',
    weather_hash: 'sha256:sun',
    baseline_mean: 15,
    modified_mean: 9,
    delta_mean: -6,
    direction_of_change: 'DECREASED',
    occupied_points: [],
    metadata: { paired_domain: 'COMMON_OVERLAP', paired_sensor_count: 2, paired_domain_area_m2: 175.0 },
  },
  baseline_march_21_statistics: { date: '2026-03-21', sensor_count: 2, mean_hours: 12, median_hours: 12, sensors_at_least_2_hours: 1, sensors_at_least_2_hours_pct: 50 },
  modified_march_21_statistics: { date: '2026-03-21', sensor_count: 2, mean_hours: 8, median_hours: 6, sensors_at_least_2_hours: 2, sensors_at_least_2_hours_pct: 100 },
  colormap_spec: colormap,
  tool_execution: { id: 'tool-exec-e1-test', status: 'SUCCEEDED' },
  artifact: { id: 'artifact-e1-test', sha256: 'sha256:artifact' },
  evidence_card: { id: 'evidence-e1-test', validation_status: 'unverified' },
  metadata: {
    E1_PLAN: 'DRAFT_DOMAIN_FOUNDER_2026-10-04',
    engine: 'ladybug-sunpath+ladybug-radiance',
    unit: 'hours',
    cross_check: {
      status: 'PASS',
      primary_engine: 'ladybug-sunpath+ladybug-radiance',
      cross_check_engine: 'ladybug-sunpath+python-raycast',
      tolerance_mean_absolute_delta_hours: 0.25,
      baseline: { status: 'PASS', sensor_count: 2, mean_absolute_delta_hours: 0.0 },
      modified: { status: 'PASS', sensor_count: 2, mean_absolute_delta_hours: 0.0 },
    },
  },
};

function installFetchMock() {
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('/api/projects/project-e1/formal-proposals')) {
      return new Response(JSON.stringify(proposals), { status: 200 });
    }
    if (url.endsWith('/api/environment/e1/plan')) {
      return new Response(JSON.stringify(draftPlan), { status: 200 });
    }
    if (url.endsWith('/api/environment/runtimes')) {
      return new Response(JSON.stringify({ radiance_available: true, radiance_version: '6.0.2', radiance_reason: null, ladybug_available: true, engine: 'ladybug-sunpath+ladybug-radiance', engine_available: true, fallback_reason: null, default_timezone: 'Europe/Amsterdam', grid_convergence_m4h_deg: -0.73916 }), { status: 200 });
    }
    if (url.endsWith('/api/environment/e1/simulate') && init?.method === 'POST') {
      return new Response(JSON.stringify(result), { status: 200 });
    }
    return new Response('not found', { status: 404 });
  });
  return fetchSpy;
}

describe('EnvironmentPanel', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sessionStorage.clear();
    localStorage.clear();
  });

  beforeEach(() => {
    installFetchMock();
  });

  it('defaults to a collapsed draft panel and reports the verified Radiance engine honestly', async () => {
    render(
      <I18nProvider>
        <EnvironmentPanel apiBase="http://127.0.0.1:8828" projectId="project-e1" />
      </I18nProvider>
    );

    const panelToggle = screen.getByRole('button', { name: 'E1 direct sunlight (draft)' });
    expect(panelToggle.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('heading', { name: 'E1 Direct Sunlight & Shadow Analysis' })).toBeNull();
    fireEvent.click(panelToggle);
    expect(panelToggle.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('E1 Direct Sunlight & Shadow Analysis')).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId('plan-status-badge').textContent).toContain('E1_PLAN: DRAFT_DOMAIN_FOUNDER_2026-10-04'));
    expect(screen.getByText('2026-03-21 · 2026-06-21 · 2026-12-21')).toBeTruthy();
    expect(screen.getByText('08:00–18:00 · Europe/Amsterdam')).toBeTruthy();
    expect(screen.getByText('51.90° N, 4.45° E · EPSG:28992')).toBeTruthy();
    expect(screen.getByText('Each scheme: site area minus new and retained building footprints and water; streets and roads are included. Paired delta uses the common overlap. This extent is a geometric analysis extent and is not a legal right of way.')).toBeTruthy();
    expect(screen.getByTestId('draft-plan-notice').textContent).toContain('Dates, time window, sensor grid, and resolution remain unapproved.');
    expect(screen.getByText('ladybug-sunpath+ladybug-radiance')).toBeTruthy();
    expect(screen.getByText('Radiance 6.0.2 verified · primary engine')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Run draft preview' })).toBeTruthy();
  });

  it('switches to Traditional Chinese (zh-TW) cleanly', async () => {
    localStorage.setItem('urban-design-language', 'zh-TW');
    render(
      <I18nProvider>
        <EnvironmentPanel apiBase="http://127.0.0.1:8828" projectId="project-e1" />
      </I18nProvider>
    );

    const panelToggle = screen.getByRole('button', { name: 'E1 直射日照（草案）' });
    expect(panelToggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(panelToggle);
    expect(screen.getByText('E1 日照與陰影端到端分析')).toBeTruthy();
    expect(screen.getByTestId('plan-status-badge').textContent).toContain('E1_PLAN：DRAFT_DOMAIN_FOUNDER_2026-10-04');
    expect(screen.getByText('各方案以基地範圍扣除新建與保留建築物占地及水域；街道與道路計入公共空間。配對差值以兩方案公共空間的共同重疊範圍計算。此範圍是幾何分析範圍，不是法律上的公共通行權。')).toBeTruthy();
    expect(screen.getByText('草案條件／真北')).toBeTruthy();
    await waitFor(() => expect(screen.getByText('ladybug-sunpath+ladybug-radiance')).toBeTruthy());
  });

  it('submits selected formal scenarios and renders paired maps on one shared hour scale', async () => {
    const fetchSpy = installFetchMock();
    render(
      <I18nProvider>
        <EnvironmentPanel
          apiBase="http://127.0.0.1:8828"
          projectId="project-e1"
          preferredModifiedScenarioId="formal-proposal"
        />
      </I18nProvider>
    );

    fireEvent.click(screen.getByRole('button', { name: 'E1 direct sunlight (draft)' }));
    await waitFor(() => expect(screen.getByLabelText('Baseline formal scenario')).toBeTruthy());
    expect((screen.getByLabelText('Baseline formal scenario') as HTMLSelectElement).value).toBe('formal-baseline');
    expect((screen.getByLabelText('Compared formal scenario') as HTMLSelectElement).value).toBe('formal-proposal');
    fireEvent.click(screen.getByRole('button', { name: 'Run draft preview' }));

    await waitFor(() => {
      expect(screen.getByTestId('results-section')).toBeTruthy();
    });

    const runRequest = fetchSpy.mock.calls.find(([url, init]) => String(url).endsWith('/api/environment/e1/simulate') && init?.method === 'POST');
    if (!runRequest) throw new Error('E1 simulate request was not sent');
    expect(JSON.parse(String((runRequest[1] as RequestInit).body))).toEqual({
      project_id: 'project-e1',
      baseline_scenario_id: 'formal-baseline',
      modified_scenario_id: 'formal-proposal',
    });
    expect(screen.getByTestId('e1-heatmap-baseline')).toBeTruthy();
    expect(screen.getByTestId('e1-heatmap-modified')).toBeTruthy();
    expect(screen.getByText('15.00 h')).toBeTruthy();
    expect(screen.getByText('9.00 h')).toBeTruthy();
    expect(screen.getByText('Informational per-scheme statistics · 21 Mar')).toBeTruthy();
    expect(screen.getByTestId('march-21-statistics').textContent).toContain('Mean: 12.00 h');
    expect(screen.getByTestId('march-21-statistics').textContent).toContain('Mean: 8.00 h');
    expect(screen.getByText('Common-overlap paired delta · 2 sensors')).toBeTruthy();
    expect(screen.getByText('Sensors ≥ 2 h: 1 · 50.0%')).toBeTruthy();
    expect(screen.getByText('Sensors ≥ 2 h: 2 · 100.0%')).toBeTruthy();
    expect(screen.getByText('Each map uses its scheme’s own public-space domain; paired delta uses the common overlap. Both maps share one color scale.')).toBeTruthy();
    expect(screen.getByText(/0\.0–30\.0 hours/)).toBeTruthy();
    expect(screen.getByText('tool-exec-e1-test')).toBeTruthy();
    expect(screen.getByText(/artifact-e1-test/)).toBeTruthy();
    expect(screen.getByTestId('e1-cross-check').textContent).toContain('Python raycast cross-check: PASS');
    expect(screen.getByTestId('e1-cross-check').textContent).toContain('mean |Δ| tolerance ≤ 0.25 h');
    expect(screen.getByTestId('plan-status-badge').textContent).toContain('E1_PLAN: DRAFT_DOMAIN_FOUNDER_2026-10-04');
  });
});
