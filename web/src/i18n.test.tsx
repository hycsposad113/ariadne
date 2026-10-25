// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { I18nProvider, translate, useI18n, useT } from './i18n';
import { SidebarDispositions } from './components/SidebarDispositions';
import { ConstraintSetPanel } from './components/ConstraintSetPanel';
function Controls() {
  const { language, setLanguage } = useI18n();
  const t = useT();
  return <><button onClick={() => setLanguage(language === 'en' ? 'zh-TW' : 'en')}>{language}</button><p>{t('Confirm decision')}</p></>;
}
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });
describe('shell i18n', () => {
  it('defaults to Traditional Chinese, switches immediately, persists and restores the language', () => {
    const first = render(<I18nProvider><Controls /></I18nProvider>);
    expect(screen.getByText('確認決策')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'zh-TW' }));
    expect(screen.getByText('Confirm decision')).toBeTruthy();
    expect(localStorage.getItem('urban-design-language')).toBe('en');
    first.unmount();
    render(<I18nProvider><Controls /></I18nProvider>);
    expect(screen.getByRole('button', { name: 'en' })).toBeTruthy();
  });
  it('switches even when browser storage rejects reads and writes', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('unavailable'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('unavailable'); });
    render(<I18nProvider><Controls /></I18nProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'zh-TW' }));
    expect(screen.getByText('Confirm decision')).toBeTruthy();
  });
  it('translates legacy Chinese sources and interpolates without translating record identifiers', () => {
    expect(translate('確認第 1 天決策', 'en')).toBe('Confirm Day 1 decision');
    expect(translate('Revision {0}', 'zh-TW', { 0: 42 })).toBe('版本 42');
    expect(translate('Revision 42', 'zh-TW')).toBe('版本 42');
    expect(translate('building-source-42', 'zh-TW')).toBe('building-source-42');
  });
  it('keeps Conditions chrome in one language when switching both ways', () => {
    const { container } = render(<I18nProvider language="en"><Controls /><SidebarDispositions buildings={[]} roads={[]} selectedFeatureId={null} selectedFeatureIds={[]} onSelectFeature={() => {}} onUpdateDisposition={() => {}} onUpdateAnnotation={() => {}} onBatchUpdate={() => {}} /><ConstraintSetPanel apiBase="http://fixture.invalid" projectId="fixture" onSubmitDecision={async () => {}} /></I18nProvider>);
    expect(container.textContent).not.toMatch(/[\u3400-\u9fff]/u);
    fireEvent.click(screen.getByRole('button', { name: 'en' }));
    const withoutProperNames = (container.textContent || '').replaceAll(/zh-TW|BAG|OSM|FAR|AI/g, '');
    expect(withoutProperNames).not.toMatch(/[A-Za-z]{2,}/u);
    fireEvent.click(screen.getByRole('button', { name: 'zh-TW' }));
    expect(container.textContent).not.toMatch(/[\u3400-\u9fff]/u);
  });
});

it('translates messages retained from the previous language', () => { expect(translate(translate('Properties', 'zh-TW'), 'en')).toBe('Properties'); });

it('translates the 2D context control and remaining shell labels in Traditional Chinese', () => {
  expect(translate('Context', 'zh-TW')).toBe('周邊環境');
  expect(translate('Evidence status:', 'zh-TW')).toBe('證據狀態：');
  expect(translate('GFA', 'zh-TW')).toBe('總樓地板面積');
  expect(translate('Download scenario geometry', 'zh-TW')).toBe('下載方案幾何');
});

it('translates empty string to empty string in both languages', () => {
  expect(translate('', 'en')).toBe('');
  expect(translate('', 'zh-TW')).toBe('');
});

