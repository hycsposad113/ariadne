// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FormalFaceEditor } from './FormalFaceEditor';
import type { FaceSelection } from './FaceEditControls';
vi.mock('./FaceSelection3D', () => ({ FaceSelection3D: ({ faces, onSelect }: { faces: FaceSelection[]; onSelect: (face: FaceSelection) => void }) => <button onClick={() => onSelect(faces[0])}>Select face</button> }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const body = (revision: number) => ({ scenario_revision: revision, face_revision: revision, geometry_hash: `hash-${revision}`, faces: [{ id: `face-${revision}`, floor_id: 'floor-0', floorId: 'floor-0', kind: 'TOP', parent_revision: revision, parentRevision: revision, triangles: [] }] });
it('uses the new semantic face revision after a successful edit', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => body(1) }).mockResolvedValueOnce({ ok: true, json: async () => body(2) }).mockResolvedValueOnce({ ok: true, json: async () => body(3) });
  vi.stubGlobal('fetch', fetchMock);
  render(<FormalFaceEditor apiBase="" scenarioId="scenario" buildingId="building" scenarioRevision={1} />);
  await screen.findByText('face-1 / r1');
  fireEvent.click(screen.getByText('Select face'));
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'TOP_EXTRUDE' } });
  fireEvent.click(screen.getByText('Apply formal face edit'));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  await screen.findByText('face-2 / r2');
  fireEvent.click(screen.getByText('Apply formal face edit'));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toMatchObject({ face_id: 'face-2', parent_revision: 2, expected_scenario_revision: 2 });
});
it('notifies its owner after a formal edit so authoritative geometry and metrics can reload', async () => {
  const onSaved = vi.fn();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: true, json: async () => body(1) }).mockResolvedValueOnce({ ok: true, json: async () => body(2) }));
  render(<FormalFaceEditor apiBase="" scenarioId="scenario" buildingId="building" scenarioRevision={1} onSaved={onSaved} />);
  await screen.findByText('face-1 / r1');
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'TOP_EXTRUDE' } });
  fireEvent.click(screen.getByText('Apply formal face edit'));
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
});
it('renders structured API validation errors as readable text', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: true, json: async () => body(1) }).mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ detail: [{ loc: ['body', 'steps'], msg: 'Input should be greater than 0' }] }) }));
  render(<FormalFaceEditor apiBase="" scenarioId="scenario" buildingId="building" scenarioRevision={1} />);
  await screen.findByText('face-1 / r1');
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'TOP_EXTRUDE' } });
  fireEvent.click(screen.getByText('Apply formal face edit'));
  expect(await screen.findByText(/body.steps: Input should be greater than 0/)).toBeTruthy();
});
it('explains unsupported courtyard faces and renders typed backend rejections', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce({ ok: true, json: async () => ({ ...body(1), inner_ring_editing_supported: false, inner_ring_faces: [{ id: 'inner-face', editable: false }] }) }).mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ detail: { code: 'INNER_RING_EDITING_UNSUPPORTED', message: 'inner ring face editing is unsupported' } }) }));
  render(<FormalFaceEditor apiBase="" scenarioId="scenario" buildingId="building" scenarioRevision={1} />);
  await screen.findByText(/Courtyard-side faces cannot be edited/);
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'TOP_EXTRUDE' } });
  fireEvent.click(screen.getByText('Apply formal face edit'));
  expect(await screen.findByText(/INNER_RING_EDITING_UNSUPPORTED.*inner ring face editing is unsupported/)).toBeTruthy();
});

it('reloads face identity, hash and revision after a massing revision changes', async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => body(1) }).mockResolvedValueOnce({ ok: true, json: async () => body(4) }).mockResolvedValueOnce({ ok: true, json: async () => body(5) });
  vi.stubGlobal('fetch', fetchMock);
  const view = render(<FormalFaceEditor apiBase="" scenarioId="scenario" buildingId="building" scenarioRevision={1} />);
  await screen.findByText('face-1 / r1');
  fireEvent.click(screen.getByText('Select face'));
  view.rerender(<FormalFaceEditor apiBase="" scenarioId="scenario" buildingId="building" scenarioRevision={4} />);
  await screen.findByText('face-4 / r4');
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'TOP_EXTRUDE' } });
  fireEvent.click(screen.getByText('Apply formal face edit'));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toMatchObject({ face_id: 'face-4', parent_revision: 4, expected_scenario_revision: 4, expected_geometry_hash: 'hash-4' });
});

it('keeps the idempotency key under the API 200-character limit for hash-prefixed face ids, deterministically', async () => {
  const longId = `${'a'.repeat(64)}|r0:common-mixed-cell-0-building-floor-4:top`;
  const longBody = { ...body(1), faces: [{ ...body(1).faces[0], id: longId }] };
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => longBody }).mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: 'stale' }) });
  vi.stubGlobal('fetch', fetchMock);
  render(<FormalFaceEditor apiBase="" scenarioId="scenario" buildingId="building" scenarioRevision={1} />);
  await screen.findByText('5F top / r1');
  expect(screen.queryByText(new RegExp('a{64}'))).toBeNull();
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'TOP_EXTRUDE' } });
  fireEvent.click(screen.getByText('Apply formal face edit'));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByText('Apply formal face edit'));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  const first = JSON.parse(fetchMock.mock.calls[1][1].body).idempotency_key as string;
  const second = JSON.parse(fetchMock.mock.calls[2][1].body).idempotency_key as string;
  expect(first.length).toBeLessThanOrEqual(200);
  expect(first).toMatch(/^formal-TOP_EXTRUDE-[0-9a-f]{64}$/);
  expect(second).toBe(first);
});
