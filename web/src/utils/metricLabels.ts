import type {Language} from '../i18n';
type Pair = [string, string];
const schemes: Record<string, Pair> = {
  harbour: ['港埠線性紋理', 'Harbour grain'], closed: ['封閉街廓延伸', 'Closed block extension'], courtyard: ['中庭群島', 'Courtyard islands'], landscape: ['地景為圖', 'Landscape figure'], baseline: ['基準方案', 'Baseline'], context: ['基地周邊', 'Site context'],
};
schemes.harbour_grain = schemes.harbour;
schemes.closed_block_extension = schemes.closed;
schemes.courtyard_islands = schemes.courtyard;
schemes.landscape_figure = schemes.landscape;
const categories: Record<string, Pair> = {
  all: ['全體開放空間', 'All open spaces'], courtyard: ['街廓中庭', 'Block courtyard'], street: ['街道', 'Street'], park: ['街坊公園', 'Neighbourhood park'], waterfront: ['水岸公共帶', 'Public waterfront'], block_other: ['其他街廓空間', 'Other block space'], utility: ['服務空間', 'Utility space'],
  mass: ['重質構造', 'Heavyweight construction'], light: ['輕質構造', 'Lightweight construction'], ped: ['步行', 'Walking'], bike: ['自行車', 'Cycling'], car: ['汽車', 'Driving'], NW: ['西北風', 'Northwest wind'], S: ['南風', 'South wind'], SW: ['西南風', 'Southwest wind'], W: ['西風', 'West wind'], N: ['北風', 'North wind'], E: ['東風', 'East wind'], NE: ['東北風', 'Northeast wind'], SE: ['東南風', 'Southeast wind'],
};
const seasons: Record<string, Pair> = {winter: ['冬至', 'Winter solstice'], summer: ['夏至', 'Summer solstice'], spring: ['春分', 'Spring equinox'], autumn: ['秋分', 'Autumn equinox']};
const fields: Record<string, Pair> = {
  mean_h: ['平均日照', 'Mean sunlight'], area_m2: ['面積', 'Area'], ge2h_pct: ['至少兩小時日照比例', 'At least two hours sunlight'], mean_c: ['平均熱氣候指數', 'Mean UTCI'], mean_mrt_c: ['平均輻射溫度', 'Mean radiant temperature'], mean_svf: ['平均天空可視率', 'Mean sky view factor'], very_strong_pct: ['極強熱壓力比例', 'Very strong heat stress'], strong_plus_pct: ['強熱壓力以上比例', 'Strong or greater heat stress'], eui_kwh_m2: ['單位面積耗能', 'Energy use intensity'], cooling_kwh: ['冷房耗能', 'Cooling energy'], heating_kwh: ['暖房耗能', 'Heating energy'], winter_heating_kwh: ['冬季暖房耗能', 'Winter heating energy'], peak_cooling_kw: ['冷房尖峰負載', 'Peak cooling load'], peak_heating_kw: ['暖房尖峰負載', 'Peak heating load'], overheat_h: ['過熱時數', 'Overheating hours'], freq_pct: ['風向頻率', 'Wind frequency'], gt12_area_m2: ['風速比超過 1.2 的面積', 'Area with wind speed ratio above 1.2'], mean_ratio: ['平均風速比', 'Mean wind speed ratio'], max_ratio: ['最大風速比', 'Maximum wind speed ratio'], fsi: ['容積率', 'Floor space index'], gsi: ['建蔽率', 'Ground space index'], osr: ['開放空間比', 'Open space ratio'], l: ['平均層數', 'Mean storeys'], new_gfa_m2: ['新增總樓地板面積', 'New gross floor area'], building_count: ['建築數量', 'Building count'], main_street_pctl: ['主街百分位', 'Main street percentile'], new_segments_pctl: ['新設計路段百分位', 'New segment percentile'], waterfront_pctl: ['水岸百分位', 'Waterfront percentile'], courtyard_role: ['中庭定位', 'Courtyard role'], season_priority: ['季節優先順序', 'Seasonal priority'],
};
/** Human-readable reference label; callers retain the immutable ID in title. */
export function formatMetricRef(id: string, value: unknown, unit: string | null | undefined, language: Language): string {
  if (id.startsWith('prev.')) return formatMetricRef(id.slice(5), value, unit, language).replace(/^([^ ]+)/, (label) => label + (language === 'zh-TW' ? '（上一版）' : ' (previous revision)'));
  const zh = language === 'zh-TW'; const pick = (pair?: Pair) => pair?.[zh ? 0 : 1];
  const parts = id.split('.'); let label: string | undefined;
  const scheme = pick(schemes[parts[1]]);
  const field = pick(fields[parts.at(-1) ?? '']);
  if (scheme && field) {
    if (parts[0] === 'e1' && (parts.length === 5 || parts.length === 4)) {
      const season = pick(seasons[parts.at(-2)!]); const category = parts.length === 5 ? pick(categories[parts[2]]) : undefined;
      if (season && (parts.length === 4 || category)) label = [scheme, category, zh ? `${season}${field}` : `${season} ${field}`].filter(Boolean).join('｜');
    } else if (['utci', 'e4', 'e5', 'syntax'].includes(parts[0]) && parts.length === 4 && categories[parts[2]]) label = [scheme, pick(categories[parts[2]]), field].join('｜');
    else if (['e3', 'scheme'].includes(parts[0]) && parts.length === 3) label = `${scheme}｜${field}`;
  }
  if (/^evidence_card:.+/.test(id) || /^card-r\d+-/.test(id)) label = zh ? '證據卡' : 'Evidence card';
  if (/^designer\.stance\.[^.]+$/.test(id)) label = [zh ? '設計者立場' : 'Designer stance', field].filter(Boolean).join('｜');
  if (/^limit\.[^.]+$/.test(id)) label = zh ? '方法限制' : 'Method limitation';
  if (/^problem\.[^.]+\.statement$/.test(id)) label = zh ? '設計問題' : 'Design problem';
  label ??= zh ? '其他指標' : 'Other metric';
  if (value == null || value === '') return label;
  if (typeof value === 'object') {
    if (Array.isArray(value)) return `${label} ${value.length} ${zh ? '項紀錄' : 'records'}`;
    const localized = (value as Record<string, unknown>)[language];
    return typeof localized === 'string' ? `${label} ${localized}` : `${label} ${zh ? '詳細資料見來源' : 'See source for details'}`;
  }
  if (typeof value === 'boolean') return `${label} ${value ? (zh ? '是' : 'Yes') : (zh ? '否' : 'No')}`;
  const rawValue = String(value);
  const numeric = typeof value === 'number' ? value : /^-?\d+(\.\d+)?$/.test(rawValue.trim()) ? Number(rawValue) : null;
  let formatted: string;
  if (numeric !== null) {
    if (!Number.isFinite(numeric)) return `${label} ${zh ? '未提供' : 'Unavailable'}`;
    const digits = unit === 'ratio' ? 3 : /m²|m2|kwh|kw/i.test(unit ?? '') ? 1 : 2;
    formatted = new Intl.NumberFormat(zh ? 'zh-TW' : 'en-GB', {maximumFractionDigits: digits, minimumFractionDigits: unit === 'ratio' ? 2 : 0}).format(numeric);
  } else formatted = rawValue.replace(/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g, zh ? '未提供' : 'Unavailable');
  const units: Record<string, Pair> = {h: ['小時', 'h'], ratio: ['比值', 'ratio'], '%': ['%', '%'], 'm²': ['平方公尺', 'm²'], m2: ['平方公尺', 'm²'], kWh: ['度電', 'kWh'], 'kWh/m²': ['度電／平方公尺', 'kWh/m²'], 'kWh/m²/year': ['度電／平方公尺／年', 'kWh/m²/year'], kW: ['千瓦', 'kW'], '°C': ['°C', '°C']};
  const unitLabel = unit ? pick(units[unit]) ?? (zh ? '' : unit) : '';
  return `${label} ${formatted}${unitLabel ? ` ${unitLabel}` : ''}`;
}
