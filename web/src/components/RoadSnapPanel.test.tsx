// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RoadSnapPanel, type RoadSnapPanelProps, type RoadSnapPreviewResult, type ServerRoadSnapCandidate } from './RoadSnapPanel';

const midpoint: ServerRoadSnapCandidate = {
  snap_kind: 'MIDPOINT',
  x_m: 5,
  y_m: 0,
  distance_m: 0.25,
  target_node_id: null,
  target_edge_ids: ['road-17'],
  position_semantics: 'midpoint of straight edge by length',
  target_length_m: 10,
  distance_along_m: 5,
  target_fraction: 0.5,
};

const baseProps = (overrides: Partial<RoadSnapPanelProps> = {}): RoadSnapPanelProps => ({
  locale: 'en',
  readiness: 'DRAFT',
  graphHash: 'graph-a',
  revision: 4,
  candidates: [midpoint],
  candidatesGraphHash: 'graph-a',
  candidatesRevision: 4,
  onPreview: vi.fn(),
  onApply: vi.fn(),
  ...overrides,
});

describe('RoadSnapPanel', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('localizes candidate details in Traditional Chinese and blocks all edits when readiness is BLOCKED', () => {
    const onPreview = vi.fn();
    const onApply = vi.fn();
    render(<RoadSnapPanel {...baseProps({ locale: 'zh-TW', readiness: 'BLOCKED', onPreview, onApply })} />);

    expect(screen.getByRole('heading', { name: '道路吸附' })).toBeTruthy();
    expect(screen.getByText('受阻')).toBeTruthy();
    expect(screen.getByRole('alert', { name: '' }).textContent).toContain('目前伺服器狀態禁止道路吸附。');
    expect(screen.getByRole('button', { name: /中點/ }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button', { name: '預覽所選目標' }).hasAttribute('disabled')).toBe(true);
    expect(screen.getByRole('button', { name: '套用吸附並存為草稿' }).hasAttribute('disabled')).toBe(true);
    expect(onPreview).not.toHaveBeenCalled();
    expect(onApply).not.toHaveBeenCalled();
  });

  it('previews current server candidates and applies the selected snap with graph identity and target', async () => {
    const onPreview = vi.fn(async (request) => ({
      graph_hash: request.graph_hash,
      revision: request.expected_revision,
      hints: ['Graph hash graph-a is current.'],
    } satisfies RoadSnapPreviewResult));
    const onApply = vi.fn(async () => ({ status: 'DRAFT' }));
    render(<RoadSnapPanel {...baseProps({ onPreview, onApply })} />);

    const candidateButton = screen.getByRole('button', { name: /Midpoint/ });
    expect(candidateButton.textContent).toContain('Coordinates: (5.00 m, 0.00 m)');
    expect(candidateButton.textContent).toContain('Distance from requested point: 0.25 m');
    expect(candidateButton.textContent).toContain('Along target edge: 5.00 m / 10.00 m (50.00%)');
    expect(candidateButton.textContent).toContain('Midpoint measured along the full straight target edge.');
    fireEvent.click(candidateButton);
    fireEvent.click(screen.getByRole('button', { name: 'Preview selected' }));

    expect(onPreview).toHaveBeenCalledWith(expect.objectContaining({
      snap_kind: 'MIDPOINT',
      target_id: 'road-17',
      target_edge_ids: ['road-17'],
      graph_hash: 'graph-a',
      expected_revision: 4,
    }));
    expect(await screen.findByText('Graph hash graph-a is current.')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Apply snap as draft' }));
    expect(await screen.findByText('Snap request completed.')).toBeTruthy();
    expect(onApply).toHaveBeenCalledWith(expect.objectContaining({
      snap_kind: 'MIDPOINT',
      target_id: 'road-17',
      graph_hash: 'graph-a',
      expected_revision: 4,
    }));
  });

  it('does not render an old asynchronous preview after graph hash or revision changes', async () => {
    let resolvePreview: ((value: RoadSnapPreviewResult) => void) | undefined;
    const deferred = new Promise<RoadSnapPreviewResult>((resolve) => { resolvePreview = resolve; });
    const onPreview = vi.fn(() => deferred);
    const props = baseProps({ onPreview });
    const { rerender } = render(<RoadSnapPanel {...props} />);

    fireEvent.click(screen.getByRole('button', { name: /Midpoint/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Preview selected' }));
    expect(onPreview).toHaveBeenCalledTimes(1);

    rerender(<RoadSnapPanel {...props} graphHash="graph-b" revision={5} candidatesGraphHash="graph-b" candidatesRevision={5} />);
    await act(async () => {
      resolvePreview?.({ graph_hash: 'graph-a', revision: 4, hints: ['old graph hint'] });
      await deferred;
    });

    expect(screen.queryByText('old graph hint')).toBeNull();
    expect(screen.queryByText('Preview is current for this graph revision.')).toBeNull();
    expect(screen.getByText('Graph')).toBeTruthy();
    expect(screen.getByText('graph-b')).toBeTruthy();
  });

  it('does not report completion when the server returns a blocked apply result', async () => {
    const onApply = vi.fn(async () => ({ status: 'BLOCKED' }));
    render(<RoadSnapPanel {...baseProps({ onApply })} />);
    fireEvent.click(screen.getByRole('button', { name: /Midpoint/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply snap as draft' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Snap could not be applied.');
    expect(screen.queryByText('Snap request completed.')).toBeNull();
  });

  it('rejects a candidate list bound to a different graph revision', () => {
    render(<RoadSnapPanel {...baseProps({ candidatesGraphHash: 'graph-old', candidatesRevision: 3 })} />);
    expect(screen.getByRole('alert').textContent).toContain('These candidates belong to a different graph hash or revision.');
    expect(screen.getByRole('button', { name: /Midpoint/ }).hasAttribute('disabled')).toBe(true);
  });
});
