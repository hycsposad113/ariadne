// @vitest-environment jsdom
import { render, screen, cleanup } from '@testing-library/react';
import { describe, it, expect, afterEach } from 'vitest';
import { I18nProvider } from '../i18n';
import { MassingIntent } from './MassingIntent';

const intent = { reason_zh: '高整合節點保留廣場與相對地標', reason_en: 'Integrated node: plaza and relative landmark', rule_card_ids: ['SYN-003'], knowledge_unit_ids: ['KU-ARC-013'], syntax_nain: 1.2, syntax_percentile: 87, provenance: 'ASSUMED_COMMANDER' };
afterEach(cleanup);
describe('shared Compare/Refine design rationale', () => {
  it('shows Chinese rationale, recorded Syntax, cards and ground-floor colour', () => {
    render(<I18nProvider language="zh-TW"><MassingIntent intent={intent} height={17.5} active /></I18nProvider>);
    expect(screen.getByText(intent.reason_zh)).toBeTruthy();
    expect(screen.getByText(/KU-ARC-013/)).toBeTruthy();
    expect(screen.getByText(/87/)).toBeTruthy();
    expect(screen.getByText(/橙色/)).toBeTruthy();
  });
  it('shows English rationale and never invents absent intent', () => {
    const view = render(<I18nProvider language="en"><MassingIntent intent={intent} /></I18nProvider>);
    expect(screen.getByText(intent.reason_en)).toBeTruthy();
    view.rerender(<I18nProvider language="en"><MassingIntent /></I18nProvider>);
    expect(screen.getByText('No recorded design rationale')).toBeTruthy();
    expect(screen.queryByText(/NAIN:/)).toBeNull();
  });
});
