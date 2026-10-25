// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { FaceEditControls } from './FaceEditControls';
import { I18nProvider } from '../i18n';
afterEach(() => { cleanup(); localStorage.clear(); });
const selection = { id: 'face-1', floorId: 'floor-0', parentRevision: 3, kind: 'TOP' as const };
it('sends a formal draft command without calling the fixture preview label', () => {
  const onPreview = vi.fn(); render(<FaceEditControls selection={selection} fixtureOnly={false} formalDraft onPreview={onPreview} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '0,25\n20,25' } });
  fireEvent.click(screen.getByRole('button', { name: 'Apply formal face edit' }));
  expect(onPreview).toHaveBeenCalledWith(expect.objectContaining({ faceId: 'face-1', operation: 'SPLIT_LINE', parentRevision: 3 }));
  expect(screen.getByRole('status').textContent).toContain('FORMAL_DRAFT');
  expect(screen.getByRole('status').textContent).not.toContain('BLOCKED');
});
it('blocks formal editing without authorizing from a client selection', () => {
  const onPreview = vi.fn(); render(<FaceEditControls selection={selection} fixtureOnly={false} onPreview={onPreview} />);
  fireEvent.click(screen.getByRole('button')); expect(onPreview).not.toHaveBeenCalled(); expect(screen.getByRole('status').textContent).toContain('BLOCKED');
});
it('carries exact semantic identity, parent revision and local drawing coordinates', () => {
  const onPreview = vi.fn(); render(<FaceEditControls selection={selection} fixtureOnly onPreview={onPreview} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: '0,0\n10,0' } }); fireEvent.click(screen.getByRole('button'));
  expect(onPreview).toHaveBeenCalledWith(expect.objectContaining({ faceId: 'face-1', parentRevision: 3, points: [[0,0],[10,0]], semantics: 'NEW_USABLE_FLOORS_PROTOTYPE' }));
});
it('rejects fractional metre/storey steps', () => {
  const onPreview = vi.fn(); render(<FaceEditControls selection={selection} fixtureOnly onPreview={onPreview} />);
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '0.5' } }); fireEvent.click(screen.getByRole('button')); expect(onPreview).not.toHaveBeenCalled(); expect(screen.getByRole('alert')).toBeTruthy();
});
it('renders Traditional Chinese without promoting fixture state', () => {
  localStorage.setItem('urban-design-language', 'zh-TW'); render(<I18nProvider><FaceEditControls selection={null} fixtureOnly onPreview={vi.fn()} /></I18nProvider>);
  expect(screen.getByText('分面編輯（原型）')).toBeTruthy(); expect(screen.getByRole('status').textContent).toContain('FIXTURE_ONLY');
});
it('converts a drawing click to face-local metres and clears stale selection drawing', () => {
  const onPreview = vi.fn();
  const selected = { ...selection, localBounds: [0,0,10,10] as [number,number,number,number] };
  const view = render(<FaceEditControls selection={selected} fixtureOnly onPreview={onPreview} />);
  const canvas = screen.getByRole('img');
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left:0, top:0, width:300, height:200 } as DOMRect);
  fireEvent.click(canvas, { clientX:150, clientY:100 });
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('5,5');
  view.rerender(<FaceEditControls selection={{ ...selected, id:'new-face', parentRevision:4 }} fixtureOnly onPreview={onPreview} />);
  expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
});

import { faceLabel } from './FaceEditControls';
it('labels semantic faces readably without the geometry-hash prefix', () => {
  const h = 'f'.repeat(64);
  expect(faceLabel(`${h}|r0:common-mixed-cell-0-building-floor-0:side:2`)).toBe('1F side 3');
  expect(faceLabel(`${h}|r1:r0:common-mixed-cell-0-building-floor-4:top:part:0`, 'zh-TW')).toBe('5F 頂面 · 分割 1');
  expect(faceLabel(`${h}|r2:r2:new:0:top`, 'zh-TW')).toBe('新增層 1 頂面');
  expect(faceLabel('face-1')).toBe('face-1');
});
