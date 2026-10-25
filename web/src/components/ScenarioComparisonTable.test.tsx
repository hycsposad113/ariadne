// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
beforeEach(() => localStorage.setItem('urban-design-language', 'en'));
import { I18nProvider, useI18n } from '../i18n';
import { ScenarioComparisonTable } from './ScenarioComparisonTable';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const makeMockComparison = (overrides?: Record<string, unknown>) => ({
  status: 'COMPARABLE',
  scenario_ids: ['prop-1', 'prop-2'],
  scenarios: [
    {
      scenario_id: 'prop-1',
      revision: 1,
      status: 'proposed',
      strategy_label: 'Formal Strategy 1',
      geometry_sha256: 'sha256:geom1',
      provenance: 'FORMAL_PROPOSAL',
      valid: true,
      failure_reasons: [],
      is_baseline: false,
    },
    {
      scenario_id: 'prop-2',
      revision: 1,
      status: 'proposed',
      strategy_label: 'Formal Strategy 2',
      geometry_sha256: 'sha256:geom2',
      provenance: 'FORMAL_PROPOSAL',
      valid: true,
      failure_reasons: [],
      is_baseline: false,
    },
  ],
  metrics: [
    {
      metric_id: 'far',
      label: 'FAR',
      unit: 'ratio',
      method: 'gfa/site-area',
      data_gaps: [],
      validation_status: { 'prop-1': 'VALIDATED', 'prop-2': 'VALIDATED' },
      status: 'COMPARABLE',
      values: { 'prop-1': 1.2, 'prop-2': 1.5 },
    },
    {
      metric_id: 'coverage_ratio',
      label: 'Coverage ratio',
      unit: 'ratio',
      method: 'footprint/site-area',
      data_gaps: [],
      validation_status: { 'prop-1': 'VALIDATED', 'prop-2': 'VALIDATED' },
      status: 'COMPARABLE',
      values: { 'prop-1': 0.25, 'prop-2': 0.35 },
    },
  ],
  incompatibility_reasons: [],
  eligibility_for_decision: {
    can_accept: true,
    status: 'READY_FOR_DECISION',
    reason: null,
    baseline_scenario_id: null,
  },
  ranking: null,
  overall_score: null,
  winner: null,
  ...overrides,
});

it('renders warning when fewer than 2 scenarios are provided', () => {
  render(<ScenarioComparisonTable apiBase="http://api.test" scenarioIds={['only-one']} />);
  expect(screen.getByText('Select at least two scenarios')).toBeTruthy();
});

it('renders formal comparison table without ranking or overall score', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    return new Response(JSON.stringify(makeMockComparison()), { status: 200 });
  });

  render(
    <ScenarioComparisonTable
      apiBase="http://api.test"
      scenarioIds={['prop-1', 'prop-2']}
    />
  );

  expect(await screen.findByText('Formal Strategy 1')).toBeTruthy();
  expect(screen.getByText('Formal Strategy 2')).toBeTruthy();
  expect(screen.getByTestId('comparison-status-badge').textContent).toContain('COMPARABLE');
  expect(screen.getAllByRole('button', { name: 'Accept as Baseline' })).toHaveLength(2);

  // Ensure no winner or ranking or overall score column/row is rendered
  expect(screen.queryByText(/^Winner$/i)).toBeNull();
  expect(screen.queryByText(/^Overall score$/i)).toBeNull();
  expect(screen.queryByText(/^Ranking$/i)).toBeNull();
});

it('disables acceptance entrance and displays warning banner when proposals are previews/fixtures', async () => {
  const previewComparison = makeMockComparison({
    scenarios: [
      {
        scenario_id: 'prev-1',
        revision: 1,
        status: 'proposed',
        strategy_label: 'Preview 1',
        geometry_sha256: 'sha256:prev1',
        provenance: 'UNAPPROVED_PREVIEW',
        valid: true,
        failure_reasons: [],
        is_baseline: false,
      },
      {
        scenario_id: 'prev-2',
        revision: 1,
        status: 'proposed',
        strategy_label: 'Preview 2',
        geometry_sha256: 'sha256:prev2',
        provenance: 'FIXTURE_ONLY',
        valid: true,
        failure_reasons: [],
        is_baseline: false,
      },
    ],
    eligibility_for_decision: {
      can_accept: false,
      status: 'BLOCKED_PREVIEWS_ONLY',
      reason: 'Formal proposals required; unapproved preview or fixture cannot be accepted as baseline.',
      baseline_scenario_id: null,
    },
  });

  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    return new Response(JSON.stringify(previewComparison), { status: 200 });
  });

  render(
    <ScenarioComparisonTable
      apiBase="http://api.test"
      scenarioIds={['prev-1', 'prev-2']}
    />
  );

  expect(await screen.findByTestId('preview-blocked-banner')).toBeTruthy();
  expect(screen.getByText('Acceptance entrance closed: Formal proposals required')).toBeTruthy();

  const acceptButtons = screen.getAllByRole('button', { name: 'Accept as Baseline' });
  expect(acceptButtons).toHaveLength(2);
  acceptButtons.forEach(btn => {
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });
});

it('shows incompatibility banner and closes acceptance entrance when comparison is NOT_COMPARABLE', async () => {
  const incompatibleComparison = makeMockComparison({
    status: 'NOT_COMPARABLE',
    incompatibility_reasons: ['Mismatched spatial denominator hashes (different site or design area boundaries)'],
    eligibility_for_decision: {
      can_accept: false,
      status: 'BLOCKED',
      reason: 'Comparison basis or metrics are not comparable; decision entrance is closed.',
      baseline_scenario_id: null,
    },
  });

  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    return new Response(JSON.stringify(incompatibleComparison), { status: 200 });
  });

  render(
    <ScenarioComparisonTable
      apiBase="http://api.test"
      scenarioIds={['prop-1', 'prop-2']}
    />
  );

  expect(await screen.findByTestId('incompatibility-banner')).toBeTruthy();
  expect(screen.getByTestId('comparison-status-badge').textContent).toContain('NOT_COMPARABLE');
  const acceptButtons = screen.getAllByRole('button', { name: 'Accept as Baseline' });
  acceptButtons.forEach(btn => {
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });
});

it('opens baseline acceptance dialog and submits decision with required rejection reasons and key', async () => {
  const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.endsWith('/scenarios/comparison/decision')) {
      const body = JSON.parse(String(init?.body));
      expect(body.accepted_scenario_id).toBe('prop-1');
      expect(body.acceptance_reason).toBe('Superior daylight and FAR.');
      expect(body.rejected_reasons['prop-2']).toBe('Excessive building height.');
      expect(body.decision_key).toBe('secret-passphrase-1234');
      return new Response(
        JSON.stringify({
          status: 'ACCEPTED',
          baseline_scenario_id: 'prop-1',
          baseline_decision_id: 'decision-123',
          message: 'Baseline scenario accepted.',
        }),
        { status: 201 }
      );
    }
    return new Response(JSON.stringify(makeMockComparison()), { status: 200 });
  });

  const onBaselineAccepted = vi.fn();
  render(
    <ScenarioComparisonTable
      apiBase="http://api.test"
      scenarioIds={['prop-1', 'prop-2']}
      onBaselineAccepted={onBaselineAccepted}
    />
  );

  const acceptBtn = (await screen.findAllByRole('button', { name: 'Accept as Baseline' }))[0]!;
  fireEvent.click(acceptBtn);

  // Dialog opens (initial baseline selection = none)
  expect(await screen.findByRole('dialog')).toBeTruthy();
  expect(screen.getByText('Confirm baseline proposal & decisions')).toBeTruthy();
  expect(screen.queryByTestId('accepted-baseline-card')).toBeNull();

  // Pick Formal Strategy 1
  fireEvent.click(screen.getAllByRole('radio')[0]!);
  expect(screen.getByTestId('accepted-baseline-card').textContent).toContain('Formal Strategy 1');

  // Fill acceptance reason
  const acceptanceTextarea = screen.getByPlaceholderText(
    'Explain why this proposal is accepted as baseline (e.g., optimal FAR, superior open space, balanced height)…'
  );
  fireEvent.change(acceptanceTextarea, { target: { value: 'Superior daylight and FAR.' } });

  // Fill rejection reason for prop-2
  const rejectionTextarea = screen.getByPlaceholderText(
    'Explain why this proposal was not chosen (e.g., excessive height, insufficient open space)…'
  );
  fireEvent.change(rejectionTextarea, { target: { value: 'Excessive building height.' } });

  // Fill decision key
  const keyInput = screen.getByPlaceholderText('Enter private decision key');
  fireEvent.change(keyInput, { target: { value: 'secret-passphrase-1234' } });

  // Submit
  const confirmBtn = screen.getByTestId('confirm-baseline-btn');
  expect((confirmBtn as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(confirmBtn);

  await waitFor(() => {
    expect(onBaselineAccepted).toHaveBeenCalledWith('prop-1');
  });
  expect(screen.queryByRole('dialog')).toBeNull();
  fetchSpy.mockRestore();
});

function LanguageToggle() {
  const { setLanguage } = useI18n();
  return <button onClick={() => setLanguage('zh-TW')}>Switch language</button>;
}

it('switches comparison table interface to Traditional Chinese immediately', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    return new Response(JSON.stringify(makeMockComparison()), { status: 200 });
  });

  render(
    <I18nProvider>
      <LanguageToggle />
      <ScenarioComparisonTable
        apiBase="http://api.test"
        scenarioIds={['prop-1', 'prop-2']}
      />
    </I18nProvider>
  );

  expect(await screen.findByText('Formal proposal comparison')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Switch language' }));

  expect(screen.getByText('正式方案比較')).toBeTruthy();
  expect(screen.getAllByRole('button', { name: '接受為基準方案' })).toHaveLength(2);
});
