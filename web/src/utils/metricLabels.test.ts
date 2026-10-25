import {describe, it, expect} from 'vitest';
import {formatMetricRef} from './metricLabels';
describe('formatMetricRef', () => {
 it.each([
  ['e1.harbour.courtyard.winter.mean_h','港埠線性紋理｜街廓中庭｜冬至平均日照'],
  ['utci.harbour.all.very_strong_pct','極強熱壓力比例'],
  ['e3.harbour.eui_kwh_m2','單位面積耗能'],
  ['e4.harbour.mass.overheat_h','重質構造｜過熱時數'],
  ['e4.harbour.light.winter_heating_kwh','輕質構造｜冬季暖房耗能'],
  ['e5.harbour.NW.mean_ratio','西北風｜平均風速比'],
  ['syntax.harbour.ped.main_street_pctl','步行｜主街百分位'],
  ['scheme.landscape.gsi','地景為圖｜建蔽率'],
  ['evidence_card:abc','證據卡'], ['designer.stance.courtyard_role','設計者立場｜中庭定位'],
  ['limit.e1','方法限制'], ['problem.foo.statement','設計問題'], ['unknown.raw.id','其他指標'],
 ])('translates %s', (id, label) => expect(formatMetricRef(id,null,null,'zh-TW')).toContain(label));
 it('formats English labels', () => expect(formatMetricRef('e1.harbour.courtyard.winter.mean_h',0.108,'h','en')).toBe('Harbour grain｜Block courtyard｜Winter solstice Mean sunlight 0.11 h'));
 it.each([['h',0.108,'0.11 小時'],['%',95.972103,'95.97 %'],['m²',44699.556694,'44,699.6 平方公尺'],['kWh',1234.5678,'1,234.6 度電'],['ratio',0.63364193,'0.634 比值']])('rounds %s', (unit,value,expected) => expect(formatMetricRef('unknown',value,unit,'zh-TW')).toBe(`其他指標 ${expected}`));
 it('keeps ratios at two to three decimals', () => expect(formatMetricRef('e5.harbour.NW.mean_ratio',1,'ratio','zh-TW')).toContain('1.00 比值'));
 it('supports structured source values without exposing codes', () => {
  expect(formatMetricRef('designer.stance.courtyard_role',{'zh-TW':'住戶停留','en':'Residents stay'},null,'zh-TW')).toContain('住戶停留');
  expect(formatMetricRef('check.harbour.failures',['RAW_CODE'],null,'zh-TW')).toBe('其他指標 1 項紀錄');
 });
 it('handles unavailable, nonfinite and numeric strings', () => {
  expect(formatMetricRef('unknown',null,null,'zh-TW')).toBe('其他指標');
  expect(formatMetricRef('unknown',NaN,'h','en')).toBe('Other metric Unavailable');
  expect(formatMetricRef('unknown','0.108','h','zh-TW')).toBe('其他指標 0.11 小時');
 });
});

describe('formatMetricRef previous-revision ids', () => {
  it('labels prev.* metrics as the previous revision in both languages', () => {
    expect(formatMetricRef('prev.e1.harbour.courtyard.winter.mean_h', null, null, 'zh-TW')).toContain('（上一版）');
    expect(formatMetricRef('prev.e1.harbour.courtyard.winter.mean_h', null, null, 'en')).toContain('(previous revision)');
    expect(formatMetricRef('prev.e1.harbour.courtyard.winter.mean_h', null, null, 'zh-TW')).not.toContain('prev.');
  });
});
