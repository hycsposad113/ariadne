// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { GeometryPreview, MorphologyPreviewCatalog, projectPoint } from './MorphologyPreviewCatalog';

const card = (intensity: 'A' | 'B', index: number) => ({
  identity: {
    intensity,
    strategy_id: 'strategy_' + index,
    status: 'UNAPPROVED_PREVIEW',
    human_decision_created: false,
    generator_version: 'dictionary-generator-v4',
    run_created_at: null,
    generator_commit: null,
  },
  strategy_label: 'Strategy ' + index,
  limits: {
    intensity,
    far_upper_bound_land: intensity === 'A' ? 1.592296 : 2,
    coverage_upper_bound: intensity === 'A' ? null : 0.5,
    height_upper_bound_new_buildings_m: intensity === 'A' ? 20 : 40,
  },
  metrics: {
    building_count: 12,
    known_part_land_far: 1.25,
    coverage_ratio: 0.25,
    maximum_height_m: 20,
    open_space_ratio: 0.5,
    generator_valid: true,
    warnings: ['1 unknown retained floor estimate(s); known-part FAR is reported separately'],
  },
  retained_buildings: [{
    feature_id: 'retained-1', confidence: 'LOW', floor_estimate_status: 'UNKNOWN',
    floor_count: null, height_m: null,
  }],
  input_refs: [],
  limitations: ['Run creation time is UNKNOWN.'],
  verified_at_utc: '2026-09-30T10:15:00Z',
  source_reverified: false,
  assets: {
    plan: '/api/v1/morphology/previews/' + intensity + '/strategy_' + index + '/assets/plan',
    axonometric: '/api/v1/morphology/previews/' + intensity + '/strategy_' + index + '/assets/axonometric',
    geometry: '/api/v1/morphology/previews/' + intensity + '/strategy_' + index + '/assets/geometry',
  },
});

const catalog = {
  status: 'AVAILABLE',
  count: 10,
  previews: [...Array.from({ length: 5 }, (_, i) => card('A', i + 1)),
             ...Array.from({ length: 5 }, (_, i) => card('B', i + 1))],
  limits: [],
  manifest_sha256: 'a'.repeat(64),
  comparison_sha256: 'b'.repeat(64),
  input_refs: [],
  limitations: ['Run creation time is UNKNOWN.'],
  verified_at_utc: '2026-09-30T10:15:00Z',
  source_reverified: false,
  seed: 42,
};

const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
});

describe('MorphologyPreviewCatalog', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows all five A and five B previews with assumptions and unknown provenance', async () => {
    fetchMock.mockResolvedValue(response(catalog));
    render(<MorphologyPreviewCatalog apiBase="http://preview.test" />);

    expect(await screen.findByRole('heading', { name: 'Assumption set A (5 previews)' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Assumption set B (5 previews)' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open A: Strategy 1' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Open B: Strategy 5' })).toBeTruthy();
    expect(screen.getAllByText('UNAPPROVED_PREVIEW').length).toBeGreaterThan(1);
    expect(screen.getByText('Maximum known height')).toBeTruthy();
    expect(screen.getByText('Some retained-building heights are unknown')).toBeTruthy();
    expect(screen.getByText(/Confidence: LOW/)).toBeTruthy();
    expect(screen.getByText(/Floor estimate: UNKNOWN/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /accept|approve|edit|generate/i })).toBeNull();

    fireEvent.click(screen.getByText('Provenance and limitations'));
    expect(screen.getByText(/1 unknown retained floor estimate/)).toBeTruthy();
    expect(screen.getByText('Generator commit: UNKNOWN')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Open B: Strategy 1' }));
    expect(await screen.findByAltText('Plan image for B: Strategy 1')).toBeTruthy();
    expect(screen.getByText(/2\.00/)).toBeTruthy();
    expect(fetchMock.mock.calls.every(([, init]) => (init as RequestInit | undefined)?.method === 'GET')).toBe(true);
  });

  it('shows disabled and unavailable states without suggesting there are zero previews', async () => {
    fetchMock.mockResolvedValueOnce(response({ status: 'DISABLED', count: 0, previews: [] }));
    const disabled = render(<MorphologyPreviewCatalog apiBase="http://preview.test" />);
    const status = await screen.findByRole('status');
    expect(status.textContent?.toLowerCase().includes('disabled')).toBe(true);
    expect(screen.queryByText(/0 previews/i)).toBeNull();
    disabled.unmount();

    fetchMock.mockResolvedValueOnce(response({ detail: 'Configured morphology preview bundle is unavailable (category=hash_mismatch).' }, 503));
    render(<MorphologyPreviewCatalog apiBase="http://preview.test" />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent?.toLowerCase().includes('unavailable')).toBe(true);
    expect(alert.textContent).toContain('hash_mismatch');
    expect(screen.queryByText(/0 previews/i)).toBeNull();
  });

  it('shows the loading status while the catalog request is pending', () => {
    fetchMock.mockReturnValue(new Promise(() => {}));
    const { container } = render(<MorphologyPreviewCatalog apiBase="http://preview.test" />);

    expect(screen.getByRole('status').textContent).toContain('Loading existing previews…');
    expect(container.querySelector('section')?.getAttribute('aria-busy')).toBe('true');
  });

  it('shows an alert when a preview image fails to load', async () => {
    fetchMock.mockResolvedValue(response(catalog));
    render(<MorphologyPreviewCatalog apiBase="http://preview.test" />);

    const image = await screen.findByAltText('Plan image for A: Strategy 1');
    fireEvent.error(image);

    expect((await screen.findByRole('alert')).textContent).toContain('Preview image unavailable.');
  });

  it('shows startup-frozen source disclosure and explicit plan and axonometric downloads', async () => {
    fetchMock.mockResolvedValue(response(catalog));
    render(<MorphologyPreviewCatalog apiBase="http://preview.test" />);

    await screen.findByRole('heading', { name: 'Assumption set A (5 previews)' });
    expect(screen.getByText(/verified against the pinned manifest at service startup/i)).toBeTruthy();
    expect(screen.getByText(/disk changes after startup are not reflected/i)).toBeTruthy();
    expect(screen.getByText('Source verified at 2026-09-30T10:15:00Z; not reverified after startup.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download plan image' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download axonometric image' })).toBeTruthy();
  });

  it('includes strategy id and asset hash prefix in downloaded preview filenames', async () => {
    const assetHash = 'c'.repeat(64);
    fetchMock.mockImplementation((url: string) => {
      if (url.endsWith('/api/v1/morphology/previews')) return Promise.resolve(response(catalog));
      return Promise.resolve({
        ok: true,
        headers: { get: (name: string) => name.toLowerCase() === 'etag' ? `"${assetHash}"` : null },
        blob: async () => new Blob(['preview bytes']),
      });
    });
    const originalCreate = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
    const originalRevoke = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:preview-test') });
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
    const clickedDownloads: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clickedDownloads.push(this.download);
    });

    try {
      render(<MorphologyPreviewCatalog apiBase="http://preview.test" />);
      await screen.findByRole('heading', { name: 'Assumption set A (5 previews)' });
      fireEvent.click(screen.getByRole('button', { name: 'Download plan image' }));
      await vi.waitFor(() => expect(clickedDownloads.length).toBe(1));

      expect(clickedDownloads[0]).toBe('morphology-preview-A-strategy_1-' + assetHash.slice(0, 12) + '-plan.png');
    } finally {
      click.mockRestore();
      if (originalCreate) Object.defineProperty(URL, 'createObjectURL', originalCreate);
      else Reflect.deleteProperty(URL, 'createObjectURL');
      if (originalRevoke) Object.defineProperty(URL, 'revokeObjectURL', originalRevoke);
      else Reflect.deleteProperty(URL, 'revokeObjectURL');
    }
  });

  it('shows the unknown retained-building height hint only when warnings are present', async () => {
    const withoutWarnings = {
      ...catalog,
      previews: catalog.previews.map((preview) => ({
        ...preview,
        metrics: { ...preview.metrics, warnings: [] },
      })),
    };
    fetchMock.mockResolvedValue(response(withoutWarnings));
    render(<MorphologyPreviewCatalog apiBase="http://preview.test" />);

    await screen.findByRole('heading', { name: 'Assumption set A (5 previews)' });
    expect(screen.queryByText('Some retained-building heights are unknown')).toBeNull();
  });

  it('shows an unavailable state when the geometry GET fails', async () => {
    fetchMock.mockResolvedValueOnce(response(catalog));
    fetchMock.mockResolvedValueOnce(response({ detail: 'unavailable' }, 503));
    render(<MorphologyPreviewCatalog apiBase="http://preview.test" />);

    await screen.findByRole('heading', { name: 'Assumption set A (5 previews)' });
    fireEvent.click(screen.getByRole('button', { name: 'Geometry' }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Geometry preview unavailable.');
    expect(screen.queryByText('Loading EPSG:28992 geometry…')).toBeNull();
  });

  it('projects EPSG:28992 coordinates from their actual nonzero bounds', () => {
    expect(projectPoint(100, 100, [100, 100, 200, 200], 400, 300)).toEqual([16, 284]);
  });

  it('preserves polygon holes and multipolygon parts in the read-only geometry preview', () => {
    const geojson = {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', properties: { feature_kind: 'study_area' }, geometry: {
          type: 'Polygon', coordinates: [
            [[100, 100], [200, 100], [200, 200], [100, 200], [100, 100]],
            [[125, 125], [175, 125], [175, 175], [125, 175], [125, 125]],
          ],
        } },
        { type: 'Feature', properties: { feature_kind: 'generated_building' }, geometry: {
          type: 'MultiPolygon', coordinates: [
            [[[110, 110], [120, 110], [120, 120], [110, 120], [110, 110]]],
            [[[180, 180], [190, 180], [190, 190], [180, 190], [180, 180]]],
          ],
        } },
      ],
    } as const;
    const { container } = render(<GeometryPreview geojson={geojson} />);
    const paths = container.querySelectorAll('path');
    expect(paths).toHaveLength(2);
    expect(paths[0]?.getAttribute('fill-rule')).toBe('evenodd');
    expect(container.querySelector('svg')?.getAttribute('data-crs')).toBe('EPSG:28992');
  });
});
