// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
vi.mock('three', () => ({ WebGLRenderer: class { constructor() { throw new Error('no WebGL'); } } }));
import { FaceSelection3D } from './FaceSelection3D';
afterEach(cleanup);
it('retains exact face identity through the accessible WebGL fallback', () => {
  const face = { id: 'side-r4-f2', floorId: 'floor-2', parentRevision: 4, kind: 'SIDE' as const, triangles: [] };
  const onSelect = vi.fn(); render(<FaceSelection3D faces={[face]} selectedId={null} onSelect={onSelect} />);
  fireEvent.click(screen.getByRole('button', { name: face.id })); expect(onSelect).toHaveBeenCalledWith({ id: face.id, floorId: face.floorId, parentRevision: 4, kind: 'SIDE' });
});
