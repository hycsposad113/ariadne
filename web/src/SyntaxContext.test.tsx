// @vitest-environment jsdom
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
beforeEach(() => localStorage.setItem('urban-design-language', 'en'));
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import App from './App';
import { translate } from './i18n';
import { buildClassificationFromBreaks, hexToRgba, syntaxContextBadgeStatus } from './utils/syntaxContext';

vi.mock('./components/Viewport2D', () => ({
  Viewport2D: (props: any) => (
    <div
      data-testid="viewport-2d"
      data-syntax-mode={props.syntaxMode}
      data-syntax-metric={props.syntaxMetric}
      data-syntax-segments={props.syntaxContextData?.segments?.length ?? 0}
    />
  ),
}));
vi.mock('./components/Viewport3D', () => ({ Viewport3D: () => <div data-testid="viewport-3d" /> }));
vi.mock('./components/CompareWorkspace', () => ({ CompareWorkspace: () => <div data-testid="compare" /> }));

describe('Space Syntax context controls & query trigger', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('triggers queries with correct mode and distance_m on ribbon interactions', async () => {
    const fetchedUrls: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        const url = String(input);
        fetchedUrls.push(url);
        if (url.includes('/syntax/context')) {
          const mode = url.includes('mode=bicycle')
            ? 'bicycle'
            : url.includes('mode=motor_vehicle')
              ? 'motor_vehicle'
              : 'pedestrian';
          const status = mode === 'pedestrian' ? 'BLOCKED_BOUNDARY_STABILITY_UNASSESSED' : 'EXPLORATORY';
          const radius = mode === 'pedestrian' ? 800 : mode === 'bicycle' ? 2000 : 10000;
          return {
            ok: true,
            json: async () => ({
              mode,
              radius_m: radius,
              readiness: {
                mode,
                radius_m: radius,
                status,
                reason: `Manifest a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1 ${status}`,
                manifest_sha256: 'a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1',
                formal_result: false,
                bound_manifest_sha256: 'a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1',
                manifest_binding: 'SHIPPED',
              },
              distance_m: 1000,
              reliable_within_m: 2200,
              evidence_level: 'EXPLORATORY',
              limitations: 'Test limitation',
              attribution: 'PST 3.3.1',
              segment_count: 2,
              legend_breaks: {
                nain: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
                nach: [0.05, 0.1, 0.15, 0.2, 0.25, 0.3],
              },
              segments: [
                {
                  id: 's1',
                  coordinates: [
                    [100, 200],
                    [150, 250],
                  ],
                  distance_to_site_m: 100,
                  inside_site: true,
                  boundary_effect_risk: false,
                  nain: 0.5,
                  nach: 0.2,
                },
                {
                  id: 's2',
                  coordinates: [
                    [200, 300],
                    [250, 350],
                  ],
                  distance_to_site_m: 500,
                  inside_site: false,
                  boundary_effect_risk: true,
                  nain: 0.3,
                  nach: 0.1,
                },
              ],
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            buildings: [],
            roads: [],
            evidence_cards: [],
            evidence_gaps: [],
            syntax_layers: [],
          }),
        };
      }),
    );

    render(<App />);

    // Initial query on mount with default pedestrian and 1000m
    await waitFor(() => {
      expect(fetchedUrls.some((u) => u.includes('/syntax/context?mode=pedestrian&distance_m=1000'))).toBe(true);
    });

    const walkReadiness = document.getElementById('syntax-readiness-walk');
    const bikeReadiness = document.getElementById('syntax-readiness-bike');
    const carReadiness = document.getElementById('syntax-readiness-car');
    expect(walkReadiness?.getAttribute('data-readiness')).toBe('BLOCKED_BOUNDARY_STABILITY_UNASSESSED');
    expect(walkReadiness?.getAttribute('title')).toContain('Boundary stability unassessed');
    expect(walkReadiness?.textContent).toBe('Blocked');
    expect(walkReadiness?.getAttribute('data-formal-result')).toBe('false');
    expect(bikeReadiness?.getAttribute('data-readiness')).toBe('EXPLORATORY');
    expect(bikeReadiness?.getAttribute('title')).toContain('Exploratory');
    expect(bikeReadiness?.textContent).toBe('Exploratory');
    expect(bikeReadiness?.getAttribute('data-formal-result')).toBe('false');
    expect(carReadiness?.getAttribute('data-readiness')).toBe('EXPLORATORY');
    expect(carReadiness?.getAttribute('title')).toContain('Exploratory');
    expect(carReadiness?.textContent).toBe('Exploratory');
    expect(carReadiness?.getAttribute('data-formal-result')).toBe('false');
    const manifest = document.getElementById('syntax-context-manifest');
    expect(manifest?.getAttribute('title')).toContain('a55bd6a2');
    expect(manifest?.textContent).toContain('Not a formal result');
    expect(manifest?.getAttribute('data-bound-manifest')).toBe(
      'a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1',
    );
    expect(manifest?.getAttribute('data-formal-result')).toBe('false');
    expect(document.body.textContent).not.toContain('EXPLORATORY_800M_ONLY_SOURCE_COVERAGE_INSUFFICIENT');

    // Switch to Bicycle scale (2 km)
    const bicycleBtn = screen.getByRole('button', { name: 'Bicycle 2 km' });
    fireEvent.click(bicycleBtn);

    await waitFor(() => {
      expect(fetchedUrls.some((u) => u.includes('/syntax/context?mode=bicycle&distance_m=1000'))).toBe(true);
    });

    // Switch to Car scale (10 km)
    const carBtn = screen.getByRole('button', { name: 'Car 10 km' });
    fireEvent.click(carBtn);

    await waitFor(() => {
      expect(fetchedUrls.some((u) => u.includes('/syntax/context?mode=motor_vehicle&distance_m=1000'))).toBe(true);
    });

    // Switch context range via slider
    const rangeSlider = screen.getByRole('slider', { name: 'Context range slider' });
    fireEvent.change(rangeSlider, { target: { value: '2.5' } });

    await waitFor(() => {
      expect(fetchedUrls.some((u) => u.includes('/syntax/context?mode=motor_vehicle&distance_m=2500'))).toBe(true);
    });

    // Switch metric to Choice (NACH)
    const choiceBtn = screen.getByRole('button', { name: 'Choice (NACH)' });
    fireEvent.click(choiceBtn);

    const viewport = screen.getByTestId('viewport-2d');
    expect(viewport.getAttribute('data-syntax-metric')).toBe('nach');
  });

  it('provides all required i18n translation pairs in en and zh-TW', () => {
    const requiredKeys: Array<[string, string]> = [
      ['Walk 800 m', '步行 800 公尺'],
      ['Bicycle 2 km', '腳踏車 2 公里'],
      ['Car 10 km', '開車 10 公里'],
      ['Integration (NAIN)', '整合度 NAIN'],
      ['Choice (NACH)', '選擇度 NACH'],
      ['Context range', '顯示範圍'],
      ['Context range slider', '顯示範圍滑桿'],
      ['Syntax scale', '句法尺度'],
      ['Syntax metric', '句法指標'],
      ['Faint dashed line = less than one radius to network boundary; boundary effect possible', '淡色虛線＝距路網邊界不足一個半徑，可能有邊界效應'],
      ['Surrounding Space Syntax unavailable; falling back to site-only layer.', '周邊空間句法無法取得；退回僅顯示基地內圖層。'],
      ['EXPLORATORY', 'EXPLORATORY'],
    ];

    for (const [en, zh] of requiredKeys) {
      expect(translate(en, 'zh-TW')).toBe(zh);
      expect(translate(zh, 'en')).toBe(en);
    }
  });

  it('switches Space Syntax ribbon UI text completely to Traditional Chinese without untranslated remnants', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          buildings: [],
          roads: [],
          evidence_cards: [],
          evidence_gaps: [],
          syntax_layers: [],
          segments: [],
        }),
      }),
    );

    const { container } = render(<App />);

    // Switch language to zh-TW
    const languageToggle = container.querySelector<HTMLButtonElement>('#language-toggle');
    expect(languageToggle).toBeTruthy();
    fireEvent.click(languageToggle!);

    expect(screen.getAllByText('空間句法').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '步行 800 公尺' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '腳踏車 2 公里' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '開車 10 公里' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '整合度 NAIN' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '選擇度 NACH' })).toBeTruthy();
    expect(screen.getByRole('slider', { name: '顯示範圍滑桿' })).toBeTruthy();
    expect(screen.getByRole('spinbutton', { name: '顯示範圍' })).toBeTruthy();
  });
});

describe('syntaxContext utility helpers', () => {
  it('buildClassificationFromBreaks builds step intervals and maps values', () => {
    const breaks = [0, 2, 4, 6, 8, 10];
    const classification = buildClassificationFromBreaks(breaks);
    expect(classification.ranges).toHaveLength(5);
    expect(classification.ranges[0].label).toBe('Very Low (0-20%)');
    expect(classification.ranges[4].label).toBe('Very High (80-100%)');

    expect(classification.classify(1).label).toBe('Very Low');
    expect(classification.classify(3).label).toBe('Low');
    expect(classification.classify(5).label).toBe('Medium');
    expect(classification.classify(7).label).toBe('High');
    expect(classification.classify(9).label).toBe('Very High');
    expect(classification.classify(undefined).isUncomputed).toBe(true);
  });

  it('badge status follows the response readiness and keeps 800 m blocked', () => {
    expect(syntaxContextBadgeStatus({
      evidence_level: 'EXPLORATORY',
      readiness: {
        mode: 'pedestrian',
        radius_m: 800,
        status: 'BLOCKED_BOUNDARY_STABILITY_UNASSESSED',
        reason: 'bound',
        manifest_sha256: 'a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1',
        formal_result: false,
        bound_manifest_sha256: 'a55bd6a27bdb942849691b342ed9b79f3477db2a66ea6e98d97ae2875d4868c1',
        manifest_binding: 'SHIPPED',
      },
    })).toBe('BLOCKED_BOUNDARY_STABILITY_UNASSESSED');
    expect(syntaxContextBadgeStatus({ evidence_level: 'EXPLORATORY' })).toBe('EXPLORATORY');
  });

  it('hexToRgba handles hex strings and alpha', () => {
    expect(hexToRgba('#ff0000', 0.5)).toBe('rgba(255, 0, 0, 0.5)');
    expect(hexToRgba('#00ff00', 1)).toBe('rgba(0, 255, 0, 1)');
    expect(hexToRgba('#invalid', 0.8)).toBe('#invalid');
  });
});
