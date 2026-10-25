// @vitest-environment jsdom
import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SidebarSyntax } from './SidebarSyntax';
import type { SyntaxLayer, SyntaxLayerPlanEntry } from '../types';

const sixLayerPlan: SyntaxLayerPlanEntry[] = [
  { layer_id: 'local-integration', radius_m: 800, metric_key: 'nain', calculation_status: 'COMPUTED', data_readiness: 'BLOCKED_COVERAGE_EVIDENCE_ABSENT', exploratory_only: true, formal_result_eligible: false, segment_value_count: 1 },
  { layer_id: 'local-choice', radius_m: 800, metric_key: 'nach', calculation_status: 'COMPUTED', data_readiness: 'BLOCKED_COVERAGE_EVIDENCE_ABSENT', exploratory_only: true, formal_result_eligible: false, segment_value_count: 2 },
  { layer_id: 'mid-integration', radius_m: 2000, metric_key: 'nain', calculation_status: 'NOT_COMPUTED_COVERAGE_BLOCKED', data_readiness: 'BLOCKED_COVERAGE_EVIDENCE_ABSENT', exploratory_only: false, formal_result_eligible: false, segment_value_count: 0 },
  { layer_id: 'mid-choice', radius_m: 2000, metric_key: 'nach', calculation_status: 'NOT_COMPUTED_COVERAGE_BLOCKED', data_readiness: 'BLOCKED_COVERAGE_EVIDENCE_ABSENT', exploratory_only: false, formal_result_eligible: false, segment_value_count: 0 },
  { layer_id: 'regional-integration', radius_m: 10000, metric_key: 'nain', calculation_status: 'NOT_COMPUTED_COVERAGE_BLOCKED', data_readiness: 'BLOCKED_COVERAGE_EVIDENCE_ABSENT', exploratory_only: false, formal_result_eligible: false, segment_value_count: 0 },
  { layer_id: 'regional-choice', radius_m: 10000, metric_key: 'nach', calculation_status: 'NOT_COMPUTED_COVERAGE_BLOCKED', data_readiness: 'BLOCKED_COVERAGE_EVIDENCE_ABSENT', exploratory_only: false, formal_result_eligible: false, segment_value_count: 0 },
];

const computedLayerWithoutStats: SyntaxLayer = {
  layer_id: 'local-integration',
  title: 'Local Scale (800m) Angular Integration',
  scale: 'local',
  radius_m: 800,
  metric_key: 'nain',
  unit: 'NAIN (normalized)',
  calculation_status: 'COMPUTED',
  data_readiness: 'BLOCKED_COVERAGE_EVIDENCE_ABSENT',
  exploratory_only: true,
  formal_result_eligible: false,
  limitations: 'Retained source subset only.',
  segment_values: { 'segment-1': 0.42 },
  statistics: undefined as unknown as SyntaxLayer['statistics'],
  legend_breaks: undefined as unknown as number[],
};

const computedChoiceLayer: SyntaxLayer = {
  ...computedLayerWithoutStats,
  layer_id: 'local-choice',
  title: 'Local Scale (800m) Angular Choice',
  metric_key: 'nach',
  statistics: { min: 0.1, mean: 0.4, max: 0.7, count: 2 },
  segment_values: { 'segment-1': 0.4, 'segment-2': 0.6 },
};

describe('SidebarSyntax result availability', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('shows each planned metric and distinguishes computed exploratory output from unavailable radii', () => {
    render(
      <SidebarSyntax
        layers={[computedLayerWithoutStats, computedChoiceLayer]}
        activeLayer={computedLayerWithoutStats}
        onSelectLayer={vi.fn()}
        layerPlan={sixLayerPlan}
      />,
    );

    const plan = screen.getByRole('list', { name: /planned syntax result readiness/i });
    expect(within(plan).getByText('800 m · Angular integration (NAIN)')).toBeTruthy();
    expect(within(plan).getByText('800 m · Angular choice (NACH)')).toBeTruthy();
    expect(within(plan).getByText('2,000 m · Angular integration (NAIN)')).toBeTruthy();
    expect(within(plan).getByText('2,000 m · Angular choice (NACH)')).toBeTruthy();
    expect(within(plan).getByText('10,000 m · Angular integration (NAIN)')).toBeTruthy();
    expect(within(plan).getByText('10,000 m · Angular choice (NACH)')).toBeTruthy();
    expect(within(plan).getAllByText(/computed · exploratory/i)).toHaveLength(2);
    expect(within(plan).getAllByText(/not computed · coverage blocked/i)).toHaveLength(4);
    expect(within(plan).getAllByText(/unavailable, not zero/i)).toHaveLength(4);
  });

  it('never substitutes zero-to-one legend values when the computed statistics are missing', () => {
    render(
      <SidebarSyntax
        layers={[computedLayerWithoutStats, computedChoiceLayer]}
        activeLayer={computedLayerWithoutStats}
        onSelectLayer={vi.fn()}
        layerPlan={sixLayerPlan}
      />,
    );

    const legend = screen.getByRole('region', { name: /metric legend/i });
    expect(within(legend).getByText('Min: unavailable')).toBeTruthy();
    expect(within(legend).getByText('Mean: unavailable')).toBeTruthy();
    expect(within(legend).getByText('Max: unavailable')).toBeTruthy();
    expect(within(legend).getByText(/classifier breaks unavailable/i)).toBeTruthy();
    expect(legend.textContent).not.toMatch(/(?:Min|Mean|Max): (?:0\.00|1\.00)/);
  });

  it('fails closed when a computed plan count does not match the loaded result layer', () => {
    const inconsistentPlan = sixLayerPlan.map(entry => entry.layer_id === 'local-integration'
      ? { ...entry, segment_value_count: 2 }
      : entry);
    render(
      <SidebarSyntax
        layers={[computedLayerWithoutStats, computedChoiceLayer]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={inconsistentPlan}
      />,
    );

    const plan = screen.getByRole('list', { name: /planned syntax result readiness/i });
    const mismatchRow = within(plan).getAllByRole('listitem')[0];
    expect(within(mismatchRow).getByText(/result unavailable · plan\/result mismatch/i)).toBeTruthy();
    expect(within(mismatchRow).getByText(/no metric values available; missing is unavailable, not zero/i)).toBeTruthy();
  });

  it.each([
    ['radius', { radius_m: 801 }],
    ['metric key', { metric_key: 'nach' }],
    ['formal eligibility', { formal_result_eligible: true }],
    ['exploratory flag', { exploratory_only: false }],
    ['data readiness', { data_readiness: 'READY' }],
  ] as Array<[string, Partial<SyntaxLayer>]>)('fails closed when result %s disagrees with its plan', (_label, resultChanges) => {
    const mismatchedResult = { ...computedLayerWithoutStats, ...resultChanges };
    render(
      <SidebarSyntax
        layers={[mismatchedResult]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={[sixLayerPlan[0]]}
      />,
    );

    const plan = screen.getByRole('list', { name: /planned syntax result readiness/i });
    const mismatchRow = within(plan).getByRole('listitem');
    expect(within(mismatchRow).getByText(/result unavailable · plan\/result mismatch/i)).toBeTruthy();
    expect(within(mismatchRow).getByText(/no metric values available; missing is unavailable, not zero/i)).toBeTruthy();
  });

  it('renders the persisted six-layer API contract without false mismatches or zero-valued gaps', () => {
    const persistedLayers = [
      ['syntax_local_800m_integration', 800, 'nain', 'COMPUTED', 'BLOCKED_BOUNDARY_STABILITY_UNASSESSED'],
      ['syntax_local_800m_choice', 800, 'nach', 'COMPUTED', 'BLOCKED_BOUNDARY_STABILITY_UNASSESSED'],
      ['syntax_mid_2000m_integration', 2000, 'nain', 'COMPUTED', 'EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY'],
      ['syntax_mid_2000m_choice', 2000, 'nach', 'COMPUTED', 'EXPLORATORY_ENVELOPE_AND_STABILITY_ONLY'],
      ['syntax_regional_10000m_integration', 10000, 'nain', 'NOT_COMPUTED_RUNTIME_BUDGET', 'BLOCKED_RUNTIME_BUDGET_ESTIMATE'],
      ['syntax_regional_10000m_choice', 10000, 'nach', 'NOT_COMPUTED_RUNTIME_BUDGET', 'BLOCKED_RUNTIME_BUDGET_ESTIMATE'],
    ].map(([layerId, radius, metric, status, readiness]) => ({
      layer_id: layerId,
      title: `${radius === 800 ? 'Local' : radius === 2000 ? 'Mid' : 'Regional'} Scale (${radius}m) Angular ${metric === 'nain' ? 'Integration' : 'Choice'}`,
      scale: radius === 800 ? 'local' : radius === 2000 ? 'mid' : 'regional',
      radius_m: radius,
      metric_key: metric,
      unit: metric === 'nain' ? 'NAIN (normalized)' : 'NACH (normalized)',
      calculation_status: status,
      data_readiness: readiness,
      limitations: status === 'NOT_COMPUTED_RUNTIME_BUDGET'
        ? '10km withheld because the screening estimate exceeds the two-hour run cap.'
        : 'Exploratory result; see its method and source limitations.',
      statistics: status === 'COMPUTED'
        ? { min: 0.1, mean: 0.5, max: 0.9, count: 514 }
        : null,
    })) as unknown as SyntaxLayer[];

    render(
      <SidebarSyntax
        layers={persistedLayers}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={persistedLayers as unknown as SyntaxLayerPlanEntry[]}
      />,
    );

    const plan = screen.getByRole('list', { name: /planned syntax result readiness/i });
    expect(within(plan).getAllByRole('listitem')).toHaveLength(6);
    expect(within(plan).getAllByText('Computed · exploratory')).toHaveLength(4);
    expect(within(plan).getAllByText('Not computed · runtime budget')).toHaveLength(2);
    expect(screen.queryByText(/plan\/result mismatch/i)).toBeNull();
    expect(screen.getAllByText(/summary covers 514 segments/i)).toHaveLength(4);
    expect(screen.getAllByText(/missing is unavailable, not zero/i)).toHaveLength(4);
    expect(screen.getAllByText(/10km withheld because the screening estimate exceeds the two-hour run cap/i)).toHaveLength(2);
    expect(screen.getAllByText('Network mode not recorded / unknown')).toHaveLength(6);
    expect(document.body.textContent).not.toMatch(/Pedestrian network|Bicycle network|Motor vehicle network/i);
    expect(document.body.textContent).not.toMatch(/walking|cycling|driving/i);
  });

  it('labels explicit network modes independently of radius and marks file fallback as non-persisted', () => {
    const pedestrian = { ...computedLayerWithoutStats, network_mode: 'pedestrian', radius_m: 2000 } as SyntaxLayer;
    const bicycle = { ...computedChoiceLayer, network_mode: 'bicycle', radius_m: 10000 } as SyntaxLayer;
    const motorVehicle = { ...computedChoiceLayer, layer_id: 'regional-choice', network_mode: 'motor_vehicle', radius_m: 800 } as SyntaxLayer;
    render(
      <SidebarSyntax
        layers={[pedestrian, bicycle, motorVehicle]}
        activeLayer={pedestrian}
        onSelectLayer={vi.fn()}
        layerPlan={[]}
        layersSource="verified_file_fallback"
      />,
    );

    expect(screen.getByText(/File fallback/i)).toBeTruthy();
    expect(screen.getByText(/Pedestrian network/i)).toBeTruthy();
    expect(screen.getByText(/Bicycle network/i)).toBeTruthy();
    expect(screen.getByText(/Motor vehicle network/i)).toBeTruthy();
    expect(screen.getByText(/R=2000m/i)).toBeTruthy();
    expect(screen.getByText(/R=10000m/i)).toBeTruthy();
    expect(screen.getByText(/R=800m/i)).toBeTruthy();
  });

  it('uses a network mode from the exact matching typed plan entry only', () => {
    const plannedPedestrian = { ...sixLayerPlan[0], network_mode: 'pedestrian' as const };
    render(
      <SidebarSyntax
        layers={[computedLayerWithoutStats]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={[plannedPedestrian]}
      />,
    );

    expect(screen.getByText('Pedestrian network')).toBeTruthy();
  });

  it.each([
    ['different layer ID', { layer_id: 'other-layer' }],
    ['different radius', { radius_m: 2000 }],
    ['different metric', { metric_key: 'nach' }],
  ] as Array<[string, Partial<SyntaxLayerPlanEntry>]>)('keeps network mode unknown for a plan with %s', (_label, planChanges) => {
    render(
      <SidebarSyntax
        layers={[computedLayerWithoutStats]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={[{ ...sixLayerPlan[0], network_mode: 'pedestrian', ...planChanges }]}
      />,
    );

    expect(screen.getByText('Network mode not recorded / unknown')).toBeTruthy();
  });

  it('keeps network mode unknown when the matching layer and plan disagree', () => {
    render(
      <SidebarSyntax
        layers={[{ ...computedLayerWithoutStats, network_mode: 'pedestrian' }]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={[{ ...sixLayerPlan[0], network_mode: 'bicycle' }]}
      />,
    );

    expect(screen.getByText('Network mode not recorded / unknown')).toBeTruthy();
  });

  it('uses the explicit layer mode when a matching plan leaves network mode null', () => {
    const matchingPlanWithNullMode = {
      ...sixLayerPlan[0],
      network_mode: null,
    } as unknown as SyntaxLayerPlanEntry;
    render(
      <SidebarSyntax
        layers={[{ ...computedLayerWithoutStats, network_mode: 'pedestrian' }]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={[matchingPlanWithNullMode]}
      />,
    );

    expect(screen.getByText('Pedestrian network')).toBeTruthy();
    expect(screen.queryByText('Network mode not recorded / unknown')).toBeNull();
  });

  it('shows unknown for an invalid runtime network mode on the result layer', () => {
    const invalidModeLayer = {
      ...computedLayerWithoutStats,
      network_mode: 'tram',
    } as unknown as SyntaxLayer;
    render(
      <SidebarSyntax
        layers={[invalidModeLayer]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
      />,
    );

    expect(screen.getByText('Network mode not recorded / unknown')).toBeTruthy();
  });

  it('shows unknown for duplicate matching plan rows with conflicting modes', () => {
    render(
      <SidebarSyntax
        layers={[computedLayerWithoutStats]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={[
          { ...sixLayerPlan[0], network_mode: 'pedestrian' },
          { ...sixLayerPlan[0], network_mode: 'bicycle' },
        ]}
      />,
    );

    expect(screen.getByText('Network mode not recorded / unknown')).toBeTruthy();
  });

  it('accepts duplicate matching plan rows when their explicit modes agree', () => {
    render(
      <SidebarSyntax
        layers={[computedLayerWithoutStats]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={[
          { ...sixLayerPlan[0], network_mode: 'pedestrian' },
          { ...sixLayerPlan[0], network_mode: 'pedestrian' },
        ]}
      />,
    );

    expect(screen.getByText('Pedestrian network')).toBeTruthy();
  });

  it('ignores null among duplicate matching plans when another row records a mode', () => {
    const nullModePlan = {
      ...sixLayerPlan[0],
      network_mode: null,
    } as unknown as SyntaxLayerPlanEntry;
    render(
      <SidebarSyntax
        layers={[computedLayerWithoutStats]}
        activeLayer={null}
        onSelectLayer={vi.fn()}
        layerPlan={[nullModePlan, { ...sixLayerPlan[0], network_mode: 'bicycle' }]}
      />,
    );

    expect(screen.getByText('Bicycle network')).toBeTruthy();
  });
});
