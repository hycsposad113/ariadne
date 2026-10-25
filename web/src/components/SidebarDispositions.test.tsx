// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SidebarDispositions } from './SidebarDispositions';
import type { Building, Segment } from '../types';

describe('SidebarDispositions selected feature actions', () => {
  afterEach(cleanup);

  const buildings: Building[] = [
    { id: 'bag:one', geometry: {}, disposition: 'UNDECIDED' },
    { id: 'bag:two', geometry: {}, disposition: 'UNDECIDED' },
  ];
  const roads: Segment[] = [
    { id: 'osm:one', geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, length_m: 1, layer: 0 },
  ];

  it('applies a disposition only to selected features of the active type', () => {
    const onBatchUpdate = vi.fn();
    render(
      <SidebarDispositions
        buildings={buildings}
        roads={roads}
        selectedFeatureId="bag:one"
        selectedFeatureIds={['bag:one', 'osm:one']}
        onSelectFeature={vi.fn()}
        onUpdateDisposition={vi.fn()}
        onUpdateAnnotation={vi.fn()}
        onBatchUpdate={onBatchUpdate}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Selected 1 Preserve' }));

    expect(onBatchUpdate).toHaveBeenCalledWith('building', 'PRESERVE', ['bag:one']);
  });

  it('disables selected disposition actions when nothing in the active type is selected', () => {
    render(
      <SidebarDispositions
        buildings={buildings}
        roads={roads}
        selectedFeatureId={null}
        selectedFeatureIds={[]}
        onSelectFeature={vi.fn()}
        onUpdateDisposition={vi.fn()}
        onUpdateAnnotation={vi.fn()}
        onBatchUpdate={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Selected 0 Preserve' })).toHaveProperty('disabled', true);
  });

  it('disables disposition and annotation edits while a workspace sync is in progress', () => {
    const onUpdateDisposition = vi.fn();
    const onUpdateAnnotation = vi.fn();
    const onBatchUpdate = vi.fn();
    render(
      <SidebarDispositions
        buildings={[{ ...buildings[0], annotation: 'Existing note' }, buildings[1]]}
        roads={roads}
        selectedFeatureId="bag:one"
        selectedFeatureIds={['bag:one']}
        onSelectFeature={vi.fn()}
        onUpdateDisposition={onUpdateDisposition}
        onUpdateAnnotation={onUpdateAnnotation}
        onBatchUpdate={onBatchUpdate}
        isSyncing
      />,
    );

    expect(screen.getAllByRole('button', { name: 'Preserve (Lock feature)' })[0]).toHaveProperty('disabled', true);
    expect(screen.getAllByRole('button', { name: 'Editable (Scenario overlay)' })[0]).toHaveProperty('disabled', true);
    expect(screen.getAllByRole('button', { name: 'Undecided' })[0]).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'Selected 1 Preserve' })).toHaveProperty('disabled', true);
    expect(screen.getByRole('button', { name: 'All Preserve' })).toHaveProperty('disabled', true);
    expect(screen.getByLabelText('Annotation for bag:one')).toHaveProperty('disabled', true);
  });

  it('edits a local annotation for the selected feature', () => {
    const onUpdateAnnotation = vi.fn();
    render(
      <SidebarDispositions
        buildings={[{ ...buildings[0], annotation: 'Existing note' }, buildings[1]]}
        roads={roads}
        selectedFeatureId="bag:one"
        selectedFeatureIds={['bag:one']}
        onSelectFeature={vi.fn()}
        onUpdateDisposition={vi.fn()}
        onUpdateAnnotation={onUpdateAnnotation}
        onBatchUpdate={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText('Annotation for bag:one'), { target: { value: 'Check access with the client.' } });

    expect(onUpdateAnnotation).toHaveBeenCalledWith('bag:one', 'building', 'Check access with the client.');
  });

  it('requires an explicit unlock confirmation before changing a preserved feature', () => {
    const onUpdateDisposition = vi.fn();
    render(
      <SidebarDispositions
        buildings={[{ ...buildings[0], disposition: 'PRESERVE' }, buildings[1]]}
        roads={roads}
        selectedFeatureId="bag:one"
        selectedFeatureIds={['bag:one']}
        onSelectFeature={vi.fn()}
        onUpdateDisposition={onUpdateDisposition}
        onUpdateAnnotation={vi.fn()}
        onBatchUpdate={vi.fn()}
      />,
    );

    fireEvent.click(screen.getAllByRole('button', { name: 'Editable (Scenario overlay)' })[0]);

    expect(onUpdateDisposition).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog', { name: 'Unlock preserved feature?' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onUpdateDisposition).not.toHaveBeenCalled();

    fireEvent.click(screen.getAllByRole('button', { name: 'Editable (Scenario overlay)' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Unlock and set Editable' }));
    expect(onUpdateDisposition).toHaveBeenCalledWith('bag:one', 'building', 'EDITABLE');
  });

  it('moves focus into the unlock dialog, traps it, and restores the trigger after Escape', () => {
    render(
      <SidebarDispositions
        buildings={[{ ...buildings[0], disposition: 'PRESERVE' }, buildings[1]]}
        roads={roads}
        selectedFeatureId="bag:one"
        selectedFeatureIds={['bag:one']}
        onSelectFeature={vi.fn()}
        onUpdateDisposition={vi.fn()}
        onUpdateAnnotation={vi.fn()}
        onBatchUpdate={vi.fn()}
      />,
    );

    const trigger = screen.getAllByRole('button', { name: 'Editable (Scenario overlay)' })[0];
    trigger.focus();
    fireEvent.click(trigger);

    const cancel = screen.getByRole('button', { name: 'Cancel' });
    const confirm = screen.getByRole('button', { name: 'Unlock and set Editable' });
    expect(document.activeElement).toBe(cancel);
    expect(cancel.style.outline).toContain('3px');

    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(confirm);
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(cancel);
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(confirm);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it('requires explicit confirmation before a batch action resets preserved selections', () => {
    const onBatchUpdate = vi.fn();
    render(
      <SidebarDispositions
        buildings={[{ ...buildings[0], disposition: 'PRESERVE' }, buildings[1]]}
        roads={roads}
        selectedFeatureId="bag:one"
        selectedFeatureIds={['bag:one', 'bag:two']}
        onSelectFeature={vi.fn()}
        onUpdateDisposition={vi.fn()}
        onUpdateAnnotation={vi.fn()}
        onBatchUpdate={onBatchUpdate}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Selected 2 Reset' }));

    expect(onBatchUpdate).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog', { name: 'Unlock preserved features?' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onBatchUpdate).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Selected 2 Reset' }));
    fireEvent.click(screen.getByRole('button', { name: 'Unlock and continue' }));
    expect(onBatchUpdate).toHaveBeenCalledWith('building', 'UNDECIDED', ['bag:one', 'bag:two']);
  });

  it('requires confirmation before an all-features batch action unlocks preserved items', () => {
    const onBatchUpdate = vi.fn();
    render(
      <SidebarDispositions
        buildings={[{ ...buildings[0], disposition: 'PRESERVE' }, buildings[1]]}
        roads={roads}
        selectedFeatureId={null}
        selectedFeatureIds={[]}
        onSelectFeature={vi.fn()}
        onUpdateDisposition={vi.fn()}
        onUpdateAnnotation={vi.fn()}
        onBatchUpdate={onBatchUpdate}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'All Editable' }));

    expect(onBatchUpdate).not.toHaveBeenCalled();
    expect(screen.getByRole('alertdialog', { name: 'Unlock preserved features?' })).toBeTruthy();
    expect(screen.getByText(/unlock 1 preserved feature and apply the selected batch change/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Unlock and continue' }));
    expect(onBatchUpdate).toHaveBeenCalledWith('building', 'EDITABLE');
  });
});
