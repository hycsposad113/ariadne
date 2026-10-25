// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FormalRoadSnapEditor } from './FormalRoadSnapEditor';
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const graph = { graph_hash: 'hash', nodes: [{ node_id: 'node', x_m: 1, y_m: 2, layer: 0, bridge: false, tunnel: false, lineage_ids: [] }], edges: [] };
it('loads server candidates and applies a selected target with revision guards', async () => {
  const saved = vi.fn();
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ status: 'FORMAL_DRAFT', graph_hash: 'hash', revision_id: 2, candidates: [{ snap_kind: 'ENDPOINT', x_m: 2, y_m: 2, distance_m: 1, target_node_id: 'target', target_edge_ids: [], position_semantics: 'road node' }] }) }).mockResolvedValueOnce({ ok: true, json: async () => ({ revision_id: 3 }) });
  vi.stubGlobal('fetch', fetchMock);
  render(<FormalRoadSnapEditor apiBase="" scenarioId="scenario" graph={graph} revision={2} onSaved={saved} locale="en" />);
  fireEvent.click(screen.getByText('Load snap targets'));
  fireEvent.click(await screen.findByRole('button', { name: /Endpoint.*Target: target/ }));
  fireEvent.click(screen.getByText('Apply snap as draft'));
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
  expect(fetchMock.mock.calls[0][0]).toContain('/node/snap-candidates');
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ snap_kind: 'ENDPOINT', target_id: 'target', expected_revision: 2, expected_graph_hash: 'hash', x_m: 2, y_m: 2 });
});
it('explains when a formal draft has no editable road node', () => {
  render(<FormalRoadSnapEditor apiBase="" scenarioId="scenario" graph={{ ...graph, nodes: [] }} revision={2} onSaved={() => {}} locale="en" />);
  expect(screen.getByText(/No editable road nodes/)).toBeTruthy();
  expect(screen.getByText('Load snap targets').hasAttribute('disabled')).toBe(true);
});
