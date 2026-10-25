// @vitest-environment jsdom
import { beforeEach, afterEach, expect, it } from 'vitest';
beforeEach(() => localStorage.setItem('urban-design-language', 'en'));
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { I18nProvider, useI18n } from '../i18n';
import { GenerationReadinessPanel } from './GenerationReadinessPanel';
afterEach(() => { cleanup(); localStorage.clear(); });
function Switch() { const { setLanguage } = useI18n(); return <button onClick={() => setLanguage('zh-TW')}>switch</button>; }
it('shows neutral checking readiness loading state in both languages when readiness is null', () => {
  render(<I18nProvider><Switch /><GenerationReadinessPanel readiness={null} /></I18nProvider>);
  expect(screen.getByRole('status').textContent).toContain('Checking readiness…');
  fireEvent.click(screen.getByText('switch'));
  expect(screen.getByRole('status').textContent).toContain('正在檢查生成準備度…');
  expect(screen.getAllByRole('button')).toHaveLength(1);
});
it('shows blocked state in both languages when readiness status is BLOCKED', () => {
  render(<I18nProvider><Switch /><GenerationReadinessPanel readiness={{status:'BLOCKED', blockers:['missing approval'], context_hash:null, context:null}} /></I18nProvider>);
  expect(screen.getByRole('status').textContent).toContain('Not ready');
  fireEvent.click(screen.getByText('switch'));
  expect(screen.getByRole('status').textContent).toContain('正式生成受阻');
});
it('displays server diagnostics without converting blocked into ready', () => {
  render(<I18nProvider><GenerationReadinessPanel readiness={{status:'BLOCKED', blockers:['missing approval'], context_hash:null, context:null}} /></I18nProvider>);
  expect(screen.getByText('missing approval')).toBeTruthy();
  expect(screen.getByRole('status').textContent).toContain('blocked');
});
it('shows conceptual denominator and unknown/range limitation', () => {
  render(<I18nProvider><GenerationReadinessPanel readiness={{status:'READY', blockers:[], context_hash:'fixture-hash', context:{workspace_revision:6,far_denominator:{area_m2:8000,scope:'EXPLORATION_DESIGN_AREA'},floor_estimates:[]}}} /></I18nProvider>);
  expect(screen.getByText(/FAR denominator/).textContent).toContain('8000');
  expect(screen.getByText(/Floor estimates/).textContent).toContain('unknowns and ranges');
});
