// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SyncModal } from './SyncModal';

describe('SyncModal commit controls', () => {
  afterEach(cleanup);

  it('keeps close and Cancel disabled while a sync is committing', () => {
    render(
      <SyncModal
        isOpen
        onClose={vi.fn()}
        onConfirmSync={vi.fn(async () => {})}
        isSyncing
        currentWorkspace={null}
        buildings={[]}
        roads={[]}
        spatialZones={[]}
        syncError={null}
      />,
    );

    expect((screen.getByRole('button', { name: 'Close synchronization dialog' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
