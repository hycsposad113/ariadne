// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { I18nProvider, useI18n } from '../i18n';
import { resolveBuildingDisplayHeight, Viewport3D } from './Viewport3D';

const raycastState = vi.hoisted(() => ({
  points: [] as Array<{ x: number; y: number; z: number }>,
}));

vi.mock('three', async (importOriginal) => {
  const actual = await importOriginal<typeof import('three')>();
  return {
    ...actual,
    WebGLRenderer: class {
      domElement = document.createElement('canvas');
      shadowMap = { enabled: false };

      setSize() {}
      setPixelRatio() {}
      render() {}
      dispose() {}
    },
    Raycaster: class {
      params = { Line: { threshold: 0 } };

      setFromCamera() {}
      intersectObjects() {
        const point = raycastState.points.shift();
        return point ? [{ point }] : [];
      }
    },
  };
});

describe('Viewport3D measurements', () => {
  beforeEach(() => {
    raycastState.points = [];
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 800 });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true, get: () => 600 });
    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
    vi.stubGlobal('cancelAnimationFrame', vi.fn());
    vi.spyOn(HTMLCanvasElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 800, 600));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('measures horizontal distance, elevation difference, and slant between two schematic surfaces', () => {
    render(
      <Viewport3D
        studyAreaGeometry={null}
        buildings={[]}
        segments={[]}
        selectedFeatureId={null}
        onSelectFeature={vi.fn()}
        figureContext={{} as never}
        figureExportReady={false}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Measure 3D distance and height' }));
    expect(screen.getByRole('status', { name: '3D measurement status' })).toHaveTextContent('click two visible surfaces (0/2 points)');
    expect(screen.getByRole('status', { name: '3D measurement status' })).toHaveTextContent('not evidence');
    expect(screen.queryByTestId('scale-bar')).not.toBeInTheDocument();

    raycastState.points.push({ x: 0, y: 0, z: 0 }, { x: 3, y: 4, z: 6 });
    const canvas = document.querySelector('#viewport-3d-container canvas');
    expect(canvas).not.toBeNull();
    for (let index = 0; index < 2; index += 1) {
      fireEvent.mouseDown(canvas!, { button: 0, clientX: 400, clientY: 300 });
      fireEvent.mouseUp(window, { button: 0, clientX: 400, clientY: 300 });
    }

    const result = screen.getByRole('status', { name: '3D measurement status' });
    expect(result).toHaveTextContent('Horizontal: 5.00 m');
    expect(result).toHaveTextContent('Elevation difference: 6.00 m');
    expect(result).toHaveTextContent('Slant: 7.81 m');
    expect(result).toHaveTextContent('not EvidenceResult');
    expect(screen.getByRole('button', { name: 'Clear 3D measurement' })).toBeInTheDocument();
  });

  it('uses recorded feature heights or explicit floor assumptions and labels the display fallback UNKNOWN', () => {
    expect(resolveBuildingDisplayHeight({ height_m: 13.5, floor_count: 4 })).toEqual({
      heightM: 13.5,
      status: 'KNOWN',
      method: 'FEATURE_HEIGHT',
    });
    expect(resolveBuildingDisplayHeight({ floor_count: 4, first_floor_height_m: 4.5, standard_floor_height_m: 3.5 })).toEqual({
      heightM: 15,
      status: 'KNOWN',
      method: 'SCENARIO_ASSUMPTIONS',
    });
    expect(resolveBuildingDisplayHeight({ floor_count: 4 })).toEqual({
      heightM: 12,
      status: 'UNKNOWN',
      method: 'DISPLAY_DEFAULT',
    });
    expect(resolveBuildingDisplayHeight({})).toEqual({
      heightM: 3,
      status: 'UNKNOWN',
      method: 'DISPLAY_DEFAULT',
    });
  });

  it('publishes camera state when a Rhino view preset is selected', () => {
    const onCameraChange = vi.fn();
    render(
      <Viewport3D
        studyAreaGeometry={null}
        buildings={[]}
        segments={[]}
        selectedFeatureId={null}
        onSelectFeature={vi.fn()}
        onCameraChange={onCameraChange}
        figureContext={{} as never}
        figureExportReady={false}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Top' }));
    expect(onCameraChange).toHaveBeenCalledWith(expect.objectContaining({ phi: 0, theta: 0 }));
  });

  it('keeps 3D controls in a compact toolbar and collapses information and legends by default', () => {
    render(
      <Viewport3D
        studyAreaGeometry={null}
        buildings={[]}
        segments={[]}
        syntaxSegments={[{ id: 'syntax-1', geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, length_m: 1, layer: 0 }]}
        syntaxLegend={[{ label: 'Very Low (0-20%)', color: '#1d4ed8' }]}
        selectedFeatureId={null}
        onSelectFeature={vi.fn()}
        figureContext={{} as never}
        figureExportReady={false}
      />,
    );

    const toolbar = screen.getByTestId('viewport3d-navigation-toolbar');
    expect(within(toolbar).getByRole('button', { name: 'Measure 3D distance and height' })).toBeInTheDocument();
    expect(within(toolbar).getByRole('button', { name: 'Export 3D figure (PNG)' })).toBeInTheDocument();
    expect(screen.getByTestId('viewport3d-information')).not.toHaveAttribute('open');
    expect(screen.getByTestId('viewport3d-syntax-legend')).not.toHaveAttribute('open');
    expect(screen.getByTestId('surrounding-context-3d-attribution')).toBeInTheDocument();

    fireEvent.click(within(screen.getByTestId('viewport3d-information')).getByText('i'));
    expect(screen.getByText(/Building extrusions use recorded feature height/)).toBeVisible();
  });

  it('translates viewport controls and legends to Traditional Chinese', () => {
    function LanguageToggle() {
      const { setLanguage } = useI18n();
      return <button type="button" onClick={() => setLanguage('zh-TW')}>Switch language</button>;
    }

    render(
      <I18nProvider>
        <LanguageToggle />
        <Viewport3D
          studyAreaGeometry={null}
          buildings={[]}
          segments={[]}
          syntaxSegments={[{ id: 'syntax-1', geometry: { type: 'LineString', coordinates: [[0,0],[1,1]] }, length_m: 1, layer: 0 }]}
          syntaxSegmentValues={{ 'syntax-1': 1 }}
          syntaxLegend={[{ label: 'Very Low (0-20%)', color: '#1d4ed8' }]}
          selectedFeatureId={null}
          onSelectFeature={vi.fn()}
          figureContext={{} as never}
          figureExportReady={false}
        />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Switch language' }));
    expect(screen.getByRole('button', { name: '上視圖' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '量測 3D 距離與高度' })).toBeInTheDocument();
    expect(screen.getByTestId('viewport3d-syntax-legend')).toHaveAttribute('aria-label', '空間句法圖例');
  });
});
