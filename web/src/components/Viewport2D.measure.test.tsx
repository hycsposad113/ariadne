// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach } from 'vitest';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Viewport2D } from './Viewport2D';

function renderViewport() {
  return render(
    <Viewport2D
      studyAreaGeometry={null}
      buildings={[]}
      segments={[]}
      activeSyntaxLayer={null}
      spatialZones={[]}
      selectedFeatureId={null}
      onSelectFeature={vi.fn()}
      figureContext={{} as never}
      figureExportReady={false}
    />,
  );
}

function clickMap(x: number, y: number) {
  const canvas = screen.getByRole('img', { name: 'Map viewport' });
  fireEvent.mouseDown(canvas, { button: 0, clientX: x, clientY: y });
  fireEvent.mouseUp(canvas, { button: 0, clientX: x, clientY: y });
}

describe('Viewport2D measurements', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getBoundingClientRect').mockReturnValue(
      new DOMRect(0, 0, 800, 600),
    );
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });

  it('measures a known 100 m line in source coordinates at different zoom levels', () => {
    renderViewport();

    fireEvent.click(screen.getByRole('button', { name: 'Measure distance' }));
    clickMap(420, 380);
    clickMap(510, 380);
    fireEvent.click(screen.getByRole('button', { name: 'Finish measurement' }));
    expect(screen.getByRole('status', { name: /measurement result/i })).toHaveTextContent('Length: 100.00 m');

    fireEvent.click(screen.getByRole('button', { name: 'Measure distance' }));
    fireEvent.click(screen.getByTitle('Zoom In'));
    clickMap(420, 380);
    clickMap(532.5, 380);
    fireEvent.click(screen.getByRole('button', { name: 'Finish measurement' }));
    expect(screen.getByRole('status', { name: /measurement result/i })).toHaveTextContent('Length: 100.00 m');
  });

  it('measures a 20 by 50 metre polygon and rejects a self-intersection', () => {
    renderViewport();

    fireEvent.click(screen.getByRole('button', { name: 'Measure area' }));
    clickMap(420, 380);
    clickMap(438, 380);
    clickMap(438, 335);
    clickMap(420, 335);
    fireEvent.click(screen.getByRole('button', { name: 'Finish measurement' }));
    expect(screen.getByRole('status', { name: /measurement result/i })).toHaveTextContent('Area: 1,000.00 m²');
    expect(screen.getByRole('status', { name: /measurement result/i })).toHaveTextContent('Perimeter: 140.00 m');

    fireEvent.click(screen.getByRole('button', { name: 'Measure area' }));
    clickMap(420, 380);
    clickMap(438, 335);
    clickMap(420, 335);
    clickMap(438, 380);
    fireEvent.click(screen.getByRole('button', { name: 'Finish measurement' }));
    expect(screen.getByRole('status', { name: /measurement error/i })).toHaveTextContent(/self-intersect/i);
  });

  it('shows a 2D scale bar tied to the current EPSG:28992 transform and grid north', () => {
    renderViewport();

    const scaleBar = screen.getByTestId('scale-bar');
    expect(scaleBar).toHaveAttribute('aria-label', expect.stringContaining('1.11 m/px'));
    expect(screen.getByLabelText(/grid north/i)).toBeInTheDocument();

    fireEvent.click(screen.getByTitle('Zoom In'));
    expect(scaleBar).toHaveAttribute('aria-label', expect.stringContaining('0.89 m/px'));
  });

  it('keeps map context and Syntax legends collapsed to compact corner controls', () => {
    render(
      <Viewport2D
        studyAreaGeometry={null}
        buildings={[]}
        segments={[]}
        activeSyntaxLayer={{ layer_id: 'syntax-local', segment_values: {} } as never}
        syntaxLegend={[{ label: 'Very Low (0-20%)', color: '#1d4ed8' }]}
        spatialZones={[]}
        selectedFeatureId={null}
        onSelectFeature={vi.fn()}
        figureContext={{} as never}
        figureExportReady={false}
      />,
    );

    expect(screen.getByTestId('surrounding-context-legend').tagName).toBe('DETAILS');
    expect(screen.getByTestId('viewport2d-syntax-legend').tagName).toBe('DETAILS');
    expect(screen.getByTestId('surrounding-context-legend')).not.toHaveAttribute('open');
    expect(screen.getByTestId('viewport2d-syntax-legend')).not.toHaveAttribute('open');
  });
});

// Exercise Rhino Top gestures through component handlers, not measurement utilities.
describe('Rhino Top click-to-world regression', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(70, 30, 800, 600));
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
  });

  it('right-button pans, ctrl-right zooms and measures 100 metres with an offset canvas', () => {
    renderViewport();
    const canvas = screen.getByRole('img', { name: 'Map viewport' });
    fireEvent.mouseDown(canvas, {button: 2, clientX: 490, clientY: 410});
    fireEvent.mouseMove(canvas, {button: 2, clientX: 540, clientY: 390});
    fireEvent.mouseUp(canvas, {button: 2, clientX: 540, clientY: 390});
    // Zoom at the translated origin; exp(-dy * .01) doubles zoom.
    fireEvent.mouseDown(canvas, {button: 2, ctrlKey: true, clientX: 540, clientY: 390});
    fireEvent.mouseMove(canvas, {button: 2, ctrlKey: true, clientX: 540, clientY: 390 - Math.log(2) * 100});
    fireEvent.mouseUp(canvas, {button: 2, ctrlKey: true, clientX: 540, clientY: 390 - Math.log(2) * 100});
    fireEvent.click(screen.getByRole('button', {name: 'Measure distance'}));
    clickMap(540, 390); clickMap(720, 390);
    fireEvent.click(screen.getByRole('button', {name: 'Finish measurement'}));
    expect(screen.getByRole('status', {name: /measurement result/i})).toHaveTextContent('Length: 100.00 m');
    expect(screen.getByTestId('scale-bar')).toHaveAttribute('aria-label', expect.stringContaining('0.56 m/px'));
  });

  it('trackpad pan and pinch preserve a 20 x 50 metre area and reject crossing edges', () => {
    renderViewport();
    const canvas = screen.getByRole('img', {name: 'Map viewport'});
    fireEvent.wheel(canvas, {deltaMode: 0, deltaX: -20, deltaY: 10, clientX: 490, clientY: 410});
    fireEvent.wheel(canvas, {ctrlKey: true, deltaMode: 0, deltaY: -Math.log(2) * 100, clientX: 510, clientY: 400});
    fireEvent.click(screen.getByRole('button', {name: 'Measure area'}));
    clickMap(510, 400); clickMap(546, 400); clickMap(546, 310); clickMap(510, 310);
    fireEvent.click(screen.getByRole('button', {name: 'Finish measurement'}));
    expect(screen.getByRole('status', {name: /measurement result/i})).toHaveTextContent('Area: 1,000.00 m²');
    fireEvent.click(screen.getByRole('button', {name: 'Measure area'}));
    clickMap(510, 400); clickMap(546, 310); clickMap(510, 310); clickMap(546, 400);
    fireEvent.click(screen.getByRole('button', {name: 'Finish measurement'}));
    expect(screen.getByRole('status', {name: /measurement error/i})).toHaveTextContent(/self-intersect/i);
  });
});
