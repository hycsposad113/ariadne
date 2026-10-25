// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { I18nProvider } from '../i18n';
import { FormalProperties } from './FormalProperties';
import type { FormalProposal } from './CompareWorkspace';

afterEach(() => {
  cleanup();
});

const mockProposal: FormalProposal = {
  id: 'proposal-1',
  strategy: 'STRAT_A',
  status: 'PROPOSED',
  geometry: { type: 'FeatureCollection', features: [] },
  metrics: {
    far: 2.1543,
    far_denominator: 'land_area',
    far_denominator_m2: 12345.67,
    coverage: 0.355,
    highest_new_height_m: 24.52,
    open_space_ratio: 0.42,
    zone_uses: [
      {
        zone_id: 'Zone A',
        preferred_use: 'residential',
        assigned_new_gfa_m2: 5000,
        floor_program_gfa_m2: {
          housing: 3500.4,
          retail: 1499.6,
        },
      },
      {
        zone_id: 'Zone B',
        preferred_use: 'commercial',
        assigned_new_gfa_m2: 8000,
        floor_program_gfa_m2: {
          office: 8000,
        },
      },
    ],
  },
};

describe('FormalProperties', () => {
  it('renders readable table replacing raw pre and rounds metrics correctly in English', () => {
    const { container } = render(
      <I18nProvider language="en">
        <FormalProperties proposal={mockProposal} />
      </I18nProvider>
    );

    // 1. Verify raw pre is not present
    expect(container.querySelector('pre')).toBeNull();

    // 2. Verify table exists
    const table = screen.getByRole('table', { name: /zone uses and gfa/i });
    expect(table).not.toBeNull();

    // Columns and zone group headers
    expect(screen.getAllByText('Zone').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Use')).not.toBeNull();
    expect(screen.getByText('GFA (m²)')).not.toBeNull();

    // Uses and formatted GFA (thousands separator, 0 decimals)
    expect(screen.getByText('Zone A')).not.toBeNull();
    expect(screen.getByText('housing')).not.toBeNull();
    expect(screen.getByText('3,500')).not.toBeNull();
    expect(screen.getByText('retail')).not.toBeNull();
    expect(screen.getByText('1,500')).not.toBeNull();
    expect(screen.getByText('Zone A Total')).not.toBeNull();
    expect(screen.getByText('5,000')).not.toBeNull();

    expect(screen.getByText('Zone B')).not.toBeNull();
    expect(screen.getByText('office')).not.toBeNull();
    expect(screen.getByText('Zone B Total')).not.toBeNull();
    expect(screen.getAllByText('8,000').length).toBeGreaterThanOrEqual(1);

    // 3. Metric rounding
    // FAR 2 decimals
    expect(screen.getByText('2.15')).not.toBeNull();
    // Coverage ratio as % with 0-1 decimals
    expect(screen.getByText('35.5%')).not.toBeNull();
    // Open space ratio as %
    expect(screen.getByText('42%')).not.toBeNull();
    // Highest new height 1 decimal m
    expect(screen.getByText('24.5 m')).not.toBeNull();
    // Denominator area integer m² with separators
    expect(screen.getByText('12,346 m²')).not.toBeNull();
  });

  it('renders readable table and rounds metrics correctly in zh-TW', () => {
    const { container } = render(
      <I18nProvider language="zh-TW">
        <FormalProperties proposal={mockProposal} />
      </I18nProvider>
    );

    expect(container.querySelector('pre')).toBeNull();

    // Columns and zone group headers in zh-TW
    expect(screen.getAllByText('分區').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('用途')).not.toBeNull();
    expect(screen.getByText('GFA（m²）')).not.toBeNull();

    // Zone totals in zh-TW
    expect(screen.getByText('Zone A 總計')).not.toBeNull();
    expect(screen.getByText('Zone B 總計')).not.toBeNull();

    // Metrics labels in zh-TW
    expect(screen.getByText('建蔽率')).not.toBeNull();
    expect(screen.getByText('新建最高高度（m）')).not.toBeNull();
    expect(screen.getByText('開放空間比例')).not.toBeNull();
    expect(screen.getByText('基地面積')).not.toBeNull();

    // Values
    expect(screen.getByText('2.15')).not.toBeNull();
    expect(screen.getByText('35.5%')).not.toBeNull();
    expect(screen.getByText('24.5 m')).not.toBeNull();
    expect(screen.getByText('12,346 m²')).not.toBeNull();
  });

  it('handles empty zone uses gracefully', () => {
    const emptyProposal: FormalProposal = {
      ...mockProposal,
      metrics: {
        ...mockProposal.metrics,
        zone_uses: [],
      },
    };

    render(
      <I18nProvider language="en">
        <FormalProperties proposal={emptyProposal} />
      </I18nProvider>
    );

    expect(screen.getByText('No zone use data available')).not.toBeNull();
  });

  it('renders 2-column metrics list and compact table with group header rows', () => {
    const { container } = render(
      <I18nProvider language="en">
        <FormalProperties proposal={mockProposal} />
      </I18nProvider>
    );

    // Each metric row has label and value
    const metricRows = container.querySelectorAll('.formal-metric-row');
    expect(metricRows.length).toBe(6);
    metricRows.forEach((row) => {
      expect(row.querySelector('.formal-metric-label')).not.toBeNull();
      expect(row.querySelector('.formal-metric-value')).not.toBeNull();
    });

    // Group header rows span 2 columns
    const groupHeaders = container.querySelectorAll('.formal-zone-group-header');
    expect(groupHeaders.length).toBe(2);
    groupHeaders.forEach((th) => {
      expect(th.getAttribute('colspan')).toBe('2');
    });

    // Numeric cells have formal-num-cell class
    const numCells = container.querySelectorAll('.formal-num-cell');
    expect(numCells.length).toBeGreaterThan(0);
  });
});

