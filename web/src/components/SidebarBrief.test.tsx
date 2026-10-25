// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SidebarBrief } from './SidebarBrief';
import type { SpatialZone } from '../types';

const commonProps = {
  zones: [],
  isSyncing: false,
  activeDrawnCoords: null,
  isDrawingZone: false,
  onStartDrawPolygon: vi.fn(),
  onClearDrawnPolygon: vi.fn(),
  onAddZone: vi.fn(),
  onRemoveZone: vi.fn(),
  onUpdateZone: vi.fn(),
};

const savedZone: SpatialZone = {
  zone_id: 'brief-zone-existing',
  name: 'Existing waterfront draft',
  target_use: 'Harborfront Public Realm',
  target_far: { value: 1.2, unit: 'ratio', status: 'DRAFT_PENDING_HUMAN_DECISION' },
  target_height_m: { value: 18, unit: 'm', status: 'DRAFT_PENDING_HUMAN_DECISION' },
  geometry: {
    type: 'Polygon',
    coordinates: [[[10, 10], [20, 10], [20, 20], [10, 20], [10, 10]]],
  },
  status: 'DRAFT_PENDING_HUMAN_DECISION',
  author: 'designer',
  revision: 4,
  original_text: 'Keep access to the quay.',
  program_demands: ['Harborfront Public Realm', 'Maker space'],
  open_space_demands: ['Shaded public route'],
  draft_constraints: ['Keep quay access'],
  draft_preferences: ['Reuse existing structures'],
  notes: 'Keep access to the quay.',
};

describe('SidebarBrief StudyArea scope', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it('rejects the preset before creating a zone when it is outside the active StudyArea', () => {
    render(
      <SidebarBrief
        {...commonProps}
        studyAreaGeometry={{
          type: 'Polygon',
          coordinates: [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
        }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Preset' }));

    expect(commonProps.onAddZone).not.toHaveBeenCalled();
    expect(screen.getByText(/fully within one polygon component of the active StudyArea/i)).toBeTruthy();
  });

  it('keeps accepted presets as non-binding human-review drafts', () => {
    render(
      <SidebarBrief
        {...commonProps}
        studyAreaGeometry={{
          type: 'Polygon',
          coordinates: [[[88000, 435000], [90000, 435000], [90000, 437000], [88000, 437000], [88000, 435000]]],
        }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Preset' }));

    expect(commonProps.onAddZone).toHaveBeenCalledWith(expect.objectContaining({
      status: 'DRAFT_PENDING_HUMAN_DECISION',
    }));
  });

  it('previews the StudyArea intersection and saves only after explicit confirmation', async () => {
    const onSetExplorationDesignArea = vi.fn();
    const coords: [number, number][] = [[-10, 20], [30, 20], [30, 40], [-10, 40], [-10, 20]];
    const clippedGeometry = {
      type: 'Polygon',
      coordinates: [[[0, 20], [30, 20], [30, 40], [0, 40], [0, 20]]],
    };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: 'CLIPPED',
        clipped: true,
        area_m2: 600,
        component_count: 1,
        geometry: clippedGeometry,
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    render(
      <SidebarBrief
        {...commonProps}
        activeDrawnCoords={coords}
        activeDrawnPurpose="EXPLORATION_DESIGN_AREA"
        onSetExplorationDesignArea={onSetExplorationDesignArea}
        studyAreaGeometry={{
          type: 'Polygon',
          coordinates: [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
        }}
      />,
    );

    expect(screen.getByText(/not a legal design boundary/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Preview clipped design area' }));

    await waitFor(() => expect(screen.getByRole('img', { name: 'Design area clipping preview' })).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/projects/rotterdam-m4h-pilot-project/design-area/preview'),
      expect.objectContaining({ method: 'POST' }),
    );
    expect(onSetExplorationDesignArea).not.toHaveBeenCalled();
    expect(screen.getByText(/Area after clipping: 600 m²/i)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm and save design area' }));

    expect(onSetExplorationDesignArea).toHaveBeenCalledWith(expect.objectContaining({
      geometry: clippedGeometry,
      area_m2: 600,
      crs: 'EPSG:28992',
      scope: 'EXPLORATION_DESIGN_AREA',
      status: 'DRAFT_PENDING_HUMAN_DECISION',
    }));
  });

  it('uses the entire StudyArea in one explicit action', () => {
    const onSetExplorationDesignArea = vi.fn();
    const studyAreaGeometry = {
      type: 'Polygon',
      coordinates: [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
    };
    render(
      <SidebarBrief
        {...commonProps}
        onSetExplorationDesignArea={onSetExplorationDesignArea}
        studyAreaGeometry={studyAreaGeometry}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Use entire StudyArea' }));

    expect(onSetExplorationDesignArea).toHaveBeenCalledWith(expect.objectContaining({
      geometry: studyAreaGeometry,
      area_m2: 10000,
      crs: 'EPSG:28992',
      scope: 'EXPLORATION_DESIGN_AREA',
    }));
  });

  it('blocks a clipped design area made of multiple pieces', async () => {
    const onSetExplorationDesignArea = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: 'MULTIPLE_COMPONENTS',
        clipped: true,
        area_m2: 80,
        component_count: 2,
        geometry: {
          type: 'MultiPolygon',
          coordinates: [
            [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
            [[[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]],
          ],
        },
      }),
    }));
    render(
      <SidebarBrief
        {...commonProps}
        activeDrawnCoords={[[ -5, 0], [35, 0], [35, 10], [-5, 10], [-5, 0]]}
        activeDrawnPurpose="EXPLORATION_DESIGN_AREA"
        onSetExplorationDesignArea={onSetExplorationDesignArea}
        studyAreaGeometry={{
          type: 'MultiPolygon',
          coordinates: [
            [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
            [[[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]],
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Preview clipped design area' }));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/2 separate pieces/i));
    expect(screen.queryByRole('button', { name: 'Confirm and save design area' })).toBeNull();
    expect(onSetExplorationDesignArea).not.toHaveBeenCalled();
  });

  it('clearly reports an empty StudyArea intersection and does not offer confirmation', async () => {
    const onSetExplorationDesignArea = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: 'EMPTY',
        clipped: true,
        area_m2: 0,
        component_count: 0,
        geometry: null,
      }),
    }));
    render(
      <SidebarBrief
        {...commonProps}
        activeDrawnCoords={[[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]}
        activeDrawnPurpose="EXPLORATION_DESIGN_AREA"
        onSetExplorationDesignArea={onSetExplorationDesignArea}
        studyAreaGeometry={{
          type: 'Polygon',
          coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        }}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Preview clipped design area' }));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/intersection is empty/i));
    expect(screen.queryByRole('button', { name: 'Confirm and save design area' })).toBeNull();
    expect(onSetExplorationDesignArea).not.toHaveBeenCalled();
  });

  it('disables brief edits during sync and preserves typed content if submit is dispatched', () => {
    const props = {
      ...commonProps,
      isSyncing: false,
      activeDrawnCoords: [[10, 10], [20, 10], [20, 20], [10, 20]] as [number, number][],
      studyAreaGeometry: {
        type: 'Polygon',
        coordinates: [[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]],
      },
    };
    const { rerender } = render(
      <SidebarBrief
        {...props}
      />,
    );

    const nameInput = screen.getByPlaceholderText('Zone Name (e.g. Keilehaven Maker Hub)') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'Keep this draft' } });
    rerender(<SidebarBrief {...props} isSyncing />);

    expect(nameInput.matches(':disabled')).toBe(true);
    expect(screen.getByRole('button', { name: 'Add Draft Zone' }).matches(':disabled')).toBe(true);
    fireEvent.submit(nameInput.closest('form')!);

    expect(commonProps.onAddZone).not.toHaveBeenCalled();
    expect(nameInput.value).toBe('Keep this draft');
  });

  it('edits a saved zone without redrawing or changing its identity, geometry, or draft status', () => {
    const onUpdateZone = vi.fn();
    const onAddZone = vi.fn();
    render(
      <SidebarBrief
        {...commonProps}
        zones={[savedZone]}
        onUpdateZone={onUpdateZone}
        onAddZone={onAddZone}
        studyAreaGeometry={null}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit zone/i }));
    const nameInput = screen.getByPlaceholderText('Zone Name (e.g. Keilehaven Maker Hub)') as HTMLInputElement;
    expect(nameInput.value).toBe(savedZone.name);
    expect((screen.getByPlaceholderText('Target FAR') as HTMLInputElement).value).toBe('1.2');
    expect((screen.getByPlaceholderText('Max Height (m)') as HTMLInputElement).value).toBe('18');

    fireEvent.change(nameInput, { target: { value: 'Revised waterfront draft' } });
    fireEvent.change(screen.getByLabelText('Additional program demands (draft; comma-separated)'), {
      target: { value: 'Maker space, public workshop' },
    });
    fireEvent.change(screen.getByPlaceholderText('Target FAR'), { target: { value: '1.8' } });
    fireEvent.submit(nameInput.closest('form')!);

    expect(onAddZone).not.toHaveBeenCalled();
    expect(onUpdateZone).toHaveBeenCalledWith(expect.objectContaining({
      zone_id: savedZone.zone_id,
      name: 'Revised waterfront draft',
      geometry: savedZone.geometry,
      status: 'DRAFT_PENDING_HUMAN_DECISION',
      revision: 5,
      target_far: 1.8,
      program_demands: ['Harborfront Public Realm', 'Maker space', 'public workshop'],
    }));
  });

  it('renders API draft numeric values by value and unit instead of as objects', () => {
    render(
      <SidebarBrief
        {...commonProps}
        zones={[savedZone]}
        studyAreaGeometry={null}
      />,
    );

    expect(screen.getByText('FAR: 1.2 | H: 18m')).toBeTruthy();
  });

  it('cancels editing a saved zone without changing the zone or adding a new one', () => {
    const onUpdateZone = vi.fn();
    const onAddZone = vi.fn();
    render(
      <SidebarBrief
        {...commonProps}
        zones={[savedZone]}
        onUpdateZone={onUpdateZone}
        onAddZone={onAddZone}
        studyAreaGeometry={null}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit zone/i }));
    const nameInput = screen.getByPlaceholderText('Zone Name (e.g. Keilehaven Maker Hub)') as HTMLInputElement;
    fireEvent.change(nameInput, { target: { value: 'Unsaved change' } });
    fireEvent.click(screen.getByRole('button', { name: /cancel edit/i }));

    expect(nameInput.value).toBe('');
    expect(screen.getByRole('button', { name: 'Add Draft Zone' })).toBeTruthy();
    expect(onUpdateZone).not.toHaveBeenCalled();
    expect(onAddZone).not.toHaveBeenCalled();
  });

  it('rejects a negative draft target before updating a saved zone', () => {
    const onUpdateZone = vi.fn();
    render(
      <SidebarBrief
        {...commonProps}
        zones={[savedZone]}
        onUpdateZone={onUpdateZone}
        studyAreaGeometry={null}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit zone/i }));
    const form = screen.getByPlaceholderText('Zone Name (e.g. Keilehaven Maker Hub)').closest('form')!;
    fireEvent.change(screen.getByPlaceholderText('Target FAR'), { target: { value: '-0.1' } });
    fireEvent.submit(form);

    expect(onUpdateZone).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toMatch(/FAR.*finite non-negative number/i);
  });

  it('rejects an overflowing draft target before updating a saved zone', () => {
    const onUpdateZone = vi.fn();
    render(
      <SidebarBrief
        {...commonProps}
        zones={[savedZone]}
        onUpdateZone={onUpdateZone}
        studyAreaGeometry={null}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit zone/i }));
    const form = screen.getByPlaceholderText('Zone Name (e.g. Keilehaven Maker Hub)').closest('form')!;
    fireEvent.change(screen.getByPlaceholderText('Max Height (m)'), { target: { value: '1e999' } });
    fireEvent.submit(form);

    expect(onUpdateZone).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toMatch(/height.*finite non-negative number/i);
  });

  it('rejects trailing text in a draft target instead of accepting a numeric prefix', () => {
    const onUpdateZone = vi.fn();
    render(
      <SidebarBrief
        {...commonProps}
        zones={[savedZone]}
        onUpdateZone={onUpdateZone}
        studyAreaGeometry={null}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit zone/i }));
    const form = screen.getByPlaceholderText('Zone Name (e.g. Keilehaven Maker Hub)').closest('form')!;
    fireEvent.change(screen.getByPlaceholderText('Target FAR'), { target: { value: '1.2ratio' } });
    fireEvent.submit(form);

    expect(onUpdateZone).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toMatch(/FAR.*finite non-negative number/i);
  });

  it('rejects non-decimal numeric syntax instead of coercing it to a value', () => {
    const onUpdateZone = vi.fn();
    render(
      <SidebarBrief
        {...commonProps}
        zones={[savedZone]}
        onUpdateZone={onUpdateZone}
        studyAreaGeometry={null}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit zone/i }));
    const form = screen.getByPlaceholderText('Zone Name (e.g. Keilehaven Maker Hub)').closest('form')!;
    fireEvent.change(screen.getByPlaceholderText('Target FAR'), { target: { value: '0x10' } });
    fireEvent.submit(form);

    expect(onUpdateZone).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toMatch(/FAR.*finite non-negative number/i);
  });

  it('clears an optional saved target when the field is explicitly left blank', () => {
    const onUpdateZone = vi.fn();
    render(
      <SidebarBrief
        {...commonProps}
        zones={[savedZone]}
        onUpdateZone={onUpdateZone}
        studyAreaGeometry={null}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /edit zone/i }));
    expect(screen.getByText(/Leave blank to unset an optional target/i)).toBeTruthy();
    const form = screen.getByPlaceholderText('Zone Name (e.g. Keilehaven Maker Hub)').closest('form')!;
    fireEvent.change(screen.getByPlaceholderText('Target FAR'), { target: { value: '' } });
    fireEvent.submit(form);

    expect(onUpdateZone).toHaveBeenCalledWith(expect.objectContaining({
      zone_id: savedZone.zone_id,
      target_far: undefined,
      target_height_m: 18,
      status: 'DRAFT_PENDING_HUMAN_DECISION',
    }));
  });
});
