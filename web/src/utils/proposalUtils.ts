import type { Language } from '../i18n';
import { formatMetricRef } from './metricLabels';

export interface ProposalOperation {
  op: string;
  building_ids?: string[];
  building_id?: string;
  courtyard_ids?: string[];
  courtyard_id?: string;
  floors?: number;
  distance_m?: number;
  depth_m?: number;
  side?: string;
  redistribute?: boolean;
  dx?: number;
  dy?: number;
  target?: string;
  kind?: string;
  analyses?: string[];
  [k: string]: unknown;
}

export type SolarAccessCourtyard = {
  courtyard_id: string;
  south_height_after_m: number;
  h_north_edge_m?: number;
  reaches_north_edge?: boolean;
  local_sun_pockets?: {building_id: string; height_after_m: number; frontage_m: number | null}[];
};

export type SolarAccessCheck = {
  courtyards?: SolarAccessCourtyard[];
  claims_courtyard_winter_sun?: boolean;
  warning?: boolean;
  local_only?: boolean;
};

export type DryRunAffectedBuilding = {
  building_id: string;
  block_id?: string;
  floors_after?: number;
  footprint?: {
    type: string;
    coordinates: number[][][];
  };
};

export interface StrategyBuildingChange {
  building_id: string;
  floors?: number;
  floors_removed?: number;
  floors_added?: number;
  gfa_m2: number;
  is_north_of_courtyard?: boolean;
  north_side_is_street?: boolean | null;
}

export interface StrategyReportItem {
  op: string;
  operation_index?: number;
  removed_gfa_m2: number;
  added_gfa_m2: number;
  gfa_shortfall_m2: number;
  envelope_success?: boolean | null;
  envelope_unreachable?: unknown[];
  envelope_unreachable_ids?: string[];
  removed?: StrategyBuildingChange[];
  removed_buildings?: StrategyBuildingChange[];
  added?: StrategyBuildingChange[];
  added_buildings?: StrategyBuildingChange[];
  solar_access_check?: SolarAccessCheck;
}

export interface StrategyTradeOffCheck {
  north_street_shadow_addressed?: boolean;
  gfa_floor_relationship_addressed?: boolean;
  [k: string]: unknown;
}

export type ProposalDryRun = {
  valid: boolean;
  errors: string[];
  gfa_before_m2: number;
  gfa_after_m2: number;
  gfa_floor_m2: number;
  below_gfa_floor?: boolean;
  affected_building_ids: string[];
  affected_buildings?: DryRunAffectedBuilding[];
  limitations?: string[];
  requires_designer_gfa_decision?: boolean;
  topology_status?: string;
  solar_access_check?: SolarAccessCheck;
  strategy_report?: StrategyReportItem[];
  strategy_trade_off_check?: StrategyTradeOffCheck;
};

export type ProposalApproval = {
  below_gfa_floor?: boolean;
  created_at?: string;
  draft_revision?: number;
  is_human_decision?: boolean;
  note?: string;
  proposal_id?: string;
  requires_designer_gfa_decision?: boolean;
};

export type ProposalJobOutput = {
  path: string;
  sha256?: string;
};

export type ProposalJob = {
  id: string;
  analyses: string[];
  created_at?: string;
  started_at?: string;
  ended_at?: string;
  status: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | string;
  errors?: string[];
  outputs?: ProposalJobOutput[];
  draft_id?: string;
  draft_revision?: number;
  previous_revision?: number;
  judgement_id?: string;
  judgement_status?: string;
  retry_allowed?: boolean;
};

export type MetricDelta = {
  before: number | null;
  after: number | null;
  delta?: number | null;
  unit: string;
  status: 'AVAILABLE' | 'DATA_GAP' | string;
};

export type GfaComparison = {
  before: number;
  after: number;
  floor_m2: number;
  floor_fraction?: number;
  floor_status?: string;
  before_meets_floor?: boolean;
  after_meets_floor?: boolean;
  unit?: string;
};

export type ProposalComparison = {
  courtyard_winter_mean_h?: MetricDelta;
  all_winter_mean_h?: MetricDelta;
  all_winter_ge2h_pct?: MetricDelta;
  street_winter_mean_h?: MetricDelta;
  utci_very_strong_pct?: MetricDelta;
  gfa_m2?: GfaComparison;
  affected_building_count?: number;
  errors?: string[];
};

export type ProposalDetail = {
  summary: string;
  operations: ProposalOperation[];
  rationale: string[];
  expected_effects: string[];
  trade_offs: string[];
  risks: string[];
  not_simulated: string[];
  questions_for_designer: string[];
  proposal_id?: string;
  responds_to?: {
    card_id: string;
    response_ids?: string[];
  };
};

export type ProposalRecord = {
  id: string;
  card_id: string;
  draft_id?: string;
  draft_revision?: number;
  created_at: string;
  language?: string;
  model?: string;
  project_id?: string;
  status: 'VALIDATED' | 'VALIDATION_FAILED' | 'DRY_RUN_FAILED' | 'OUTCOME_UNKNOWN' | 'APPROVED' | string;
  proposal: ProposalDetail | null;
  dry_run: ProposalDryRun | null;
  approval?: ProposalApproval | null;
  job?: ProposalJob | null;
  comparison?: ProposalComparison | null;
  post_judgement_id?: string | null;
  validation_errors?: string[];
};

export type DialogueEvent =
  | {
      kind: 'judgement';
      id: string;
      created_at: string;
      round?: number;
      status: string;
      judgement: {
        id: string;
        round?: number;
        status?: string;
        card?: {
          judgement?: { stance: string; headline: string };
          confidence?: { level: string; why: string };
          [k: string]: unknown;
        } | null;
        [k: string]: unknown;
      };
    }
  | {
      kind: 'designer_response' | 'agent_response';
      id: string;
      created_at: string;
      text: string;
      response_kind?: 'agree' | 'contest' | 'challenge' | 'supplement' | string;
      language?: 'zh-TW' | 'en';
      actor_kind?: 'DESIGNER' | 'AGENT';
      actor_id?: string | null;
      judgement_id?: string;
      is_human_decision?: boolean;
    }
  | {
      kind: 'proposal';
      id: string;
      created_at: string;
      status: string;
      proposal: ProposalRecord;
    }
  | {
      kind: 'approval';
      id: string;
      created_at: string;
      note?: string;
      proposal_id?: string;
      draft_revision?: number;
      below_gfa_floor?: boolean;
      is_human_decision?: boolean;
    }
  | {
      kind: 'rerun';
      id: string;
      created_at: string;
      job: ProposalJob;
    };

export type DesignDialogueData = {
  subject: string;
  events: DialogueEvent[];
  is_human_decision: false;
};

/**
 * Formats a proposal operation into natural human language in Chinese or English.
 */
export function formatProposalOperation(op: ProposalOperation, language: Language): string {
  const zh = language === 'zh-TW';
  switch (op.op) {
    case 'REMOVE_TOP_FLOOR': {
      const bldgsZh = op.building_ids?.join('、') ?? '指定建築';
      const bldgsEn = op.building_ids?.join(', ') ?? 'selected buildings';
      const floors = op.floors ?? 1;
      const count = op.building_ids?.length ?? 1;
      if (zh) {
        return count > 1 ? `${bldgsZh} 各降 ${floors} 層` : `${bldgsZh} 降 ${floors} 層`;
      }
      return count > 1
        ? `Lower ${bldgsEn} by ${floors} floor${floors > 1 ? 's' : ''} each`
        : `Lower ${bldgsEn} by ${floors} floor${floors > 1 ? 's' : ''}`;
    }
    case 'SETBACK_UPPER': {
      const bldgsZh = op.building_ids?.length ? `${op.building_ids.join('、')} ` : '';
      const bldgsEn = op.building_ids?.length ? `${op.building_ids.join(', ')} ` : '';
      const dist = Number((op as { distance_m?: number }).distance_m ?? 0);
      const floors = Number(op.floors ?? 2);
      return zh
        ? `${bldgsZh}上${floors > 1 ? `${floors}層` : '層'}退台 ${dist} 公尺`
        : `${bldgsEn}Upper ${floors} floor${floors > 1 ? 's' : ''} setback by ${dist} metres`;
    }
    case 'MOVE': {
      const bldgsZh = op.building_ids?.length ? `${op.building_ids.join('、')} ` : '';
      const bldgsEn = op.building_ids?.length ? `${op.building_ids.join(', ')} ` : '';
      const dx = Number((op as { dx?: number }).dx ?? 0);
      const dy = Number((op as { dy?: number }).dy ?? 0);
      return zh
        ? `${bldgsZh}平移 ${dx}, ${dy} 公尺`
        : `${bldgsEn}Move by ${dx}, ${dy} metres`;
    }
    case 'ADD_FLOOR': {
      const bldgsZh = op.building_ids?.length ? `${op.building_ids.join('、')} ` : '';
      const bldgsEn = op.building_ids?.length ? `${op.building_ids.join(', ')} ` : '';
      const floors = Number(op.floors ?? 1);
      return zh
        ? `${bldgsZh}加 ${floors} 層`
        : `${bldgsEn}Add ${floors} floor${floors > 1 ? 's' : ''}`;
    }
    case 'PLANTING_NOTE': {
      const target = (op as { target?: string }).target ?? (zh ? '中庭' : 'Courtyard');
      const kind = (op as { kind?: string }).kind;
      const noteZh = kind === 'trees' ? '落葉喬木' : kind === 'trellis' ? '棚架' : '落葉喬木＋棚架';
      const noteEn = kind === 'trees' ? 'Deciduous trees' : kind === 'trellis' ? 'Trellis' : 'Deciduous trees + trellis';
      return zh
        ? `${target}：${noteZh}（設計註記，未納入模擬）`
        : `${target}: ${noteEn} (design note, not included in simulation)`;
    }
    case 'RERUN': {
      const analyses = (op as { analyses?: string[] }).analyses ?? [];
      const analysisLabels = analyses.map((a) => {
        if (a === 'E1') return zh ? '冬至日照 E1' : 'Winter solstice sunlight E1';
        if (a === 'UTCI') return zh ? '夏季熱舒適 UTCI' : 'summer thermal comfort UTCI';
        return a;
      });
      const joined = zh ? analysisLabels.join('、') : analysisLabels.join(', ');
      return zh ? `重算：${joined}` : `Recalculate: ${joined}`;
    }
    case 'SOLAR_ENVELOPE': {
      const courts = op.courtyard_ids?.length
        ? op.courtyard_ids
        : op.courtyard_id
        ? [op.courtyard_id]
        : [];
      const courtsZh = courts.length ? courts.join('、') : '中庭';
      const courtsEn = courts.length ? courts.join(', ') : 'Courtyard';
      const isNorthEdge = op.target !== 'half_depth';
      const targetZh = isNorthEdge ? '到中庭北緣' : '到中庭一半深度';
      const targetEn = isNorthEdge ? 'to courtyard north edge' : 'to courtyard half depth';
      const redistribute = op.redistribute !== false;
      const redistZh = redistribute ? '減少的樓地板移到同街廓其他棟' : '不移轉樓地板';
      const redistEn = redistribute
        ? 'redistribute reduced floor area to other buildings in the block'
        : 'no floor area redistribution';
      return zh
        ? `${courtsZh} 南側日照包絡（${targetZh}），${redistZh}`
        : `${courtsEn}: south-side solar envelope (${targetEn}), ${redistEn}`;
    }
    case 'COURTYARD_WING_DEPTH': {
      const court = op.courtyard_id ?? (zh ? '中庭' : 'Courtyard');
      const side = (op as { side?: string }).side ?? 'south';
      const sideZh = side === 'north' ? '北' : side === 'east' ? '東' : side === 'west' ? '西' : '南';
      const sideEn = side;
      const depth = Number((op as { depth_m?: number }).depth_m ?? 10);
      return zh
        ? `${court} ${sideZh}側翼進深縮為 ${depth} 公尺（加寬中庭）`
        : `${court}: reduce ${sideEn} wing depth to ${depth} metres (widening courtyard)`;
    }
    default: {
      return zh ? `操作：${op.op}` : `Operation: ${op.op}`;
    }
  }
}

/**
 * Formats GFA square metres into human readable text with thousands separator.
 * Explicit requirement: 平方公尺寫「平方公尺」不要用 m² 上標字元 in Chinese.
 */
export function formatGfa(m2: number | null | undefined, language: Language): string {
  const zh = language === 'zh-TW';
  if (typeof m2 !== 'number' || !Number.isFinite(m2)) {
    return zh ? '未提供' : 'Unavailable';
  }
  const rounded = Math.round(m2);
  const formatted = new Intl.NumberFormat(zh ? 'zh-TW' : 'en-GB').format(rounded);
  return `${formatted} ${zh ? '平方公尺' : 'sq m'}`;
}

/**
 * Format comparison delta value with 3 decimal precision where appropriate.
 * Highlights "幾乎無變化" (virtually unchanged) when delta is small but non-zero.
 */
export function formatMetricDelta(
  delta: number | null | undefined,
  unit: string,
  metricKey: string,
  language: Language,
): { text: string; evaluation: 'improvement' | 'worsened' | 'neutral' | 'gap'; nearZero: boolean } {
  const zh = language === 'zh-TW';
  if (typeof delta !== 'number' || !Number.isFinite(delta)) {
    return { text: '—', evaluation: 'neutral', nearZero: false };
  }

  const isSunlight = metricKey.includes('winter') || metricKey.includes('sun');
  const isUtci = metricKey.includes('utci');

  // Precision: up to 3 decimal places for hours
  const digits = unit === 'h' ? 3 : unit === '%' ? 2 : 1;
  const absDelta = Math.abs(delta);
  const isZero = absDelta < 0.0001;
  const isNearZero = !isZero && absDelta < 0.005;

  let evaluation: 'improvement' | 'worsened' | 'neutral' = 'neutral';
  if (!isZero) {
    if (isSunlight) {
      evaluation = delta > 0 ? 'improvement' : 'worsened';
    } else if (isUtci) {
      // Lower heat stress ratio is improvement
      evaluation = delta < 0 ? 'improvement' : 'worsened';
    }
  }

  const sign = delta > 0 ? '+' : delta < 0 ? '-' : '';
  const formattedNumber = new Intl.NumberFormat(zh ? 'zh-TW' : 'en-GB', {
    minimumFractionDigits: unit === 'h' ? 3 : 0,
    maximumFractionDigits: digits,
  }).format(absDelta);

  const unitDisplay = unit === 'h' ? (zh ? '小時' : 'h') : unit;
  let text = `${sign}${formattedNumber} ${unitDisplay}`.trim();
  if (isNearZero) {
    text += zh ? '（幾乎無變化）' : ' (virtually unchanged)';
  }

  return { text, evaluation, nearZero: isNearZero };
}


const STANCE_LABELS: Record<string, [string, string]> = {
  courtyard_role: ['你的設計立場（中庭定位）', 'your design stance (courtyard role)'],
  season_priority: ['你的設計立場（季節優先）', 'your design stance (seasonal priority)'],
};

const LIMITATION_LABELS: Record<string, [string, string]> = {
  'Nested floor-stack topology checked; no independent 3D shell/manifold verification.': ['已檢查樓層堆疊拓撲；未另做獨立的 3D 外殼驗證。', 'Nested floor-stack topology checked; no independent 3D shell/manifold verification.'],
  'Design-area containment not assessed: geometry unavailable.': ['未檢查是否位於設計範圍內：缺少範圍幾何。', 'Design-area containment not assessed: geometry unavailable.'],
  'Retained-building overlap not assessed: geometry unavailable.': ['未檢查與保留建築的重疊：缺少保留建築幾何。', 'Retained-building overlap not assessed: geometry unavailable.'],
};

export const MORPH_FAILURE_LABELS: Record<string, [string, string]> = {
  ROAD_WATERFRONT_COMBINED_BUDGET: ['道路與水岸合計面積預算', 'combined road and waterfront area budget'],
  SOUTH_QUAY_SHARED_ALLEY: ['南碼頭共用巷', 'south quay shared alley'],
  SOUTH_QUAY_FACADE_CONTINUITY: ['南碼頭立面連續性', 'south quay facade continuity'],
  BUILDING_STREET_EDGE_3M: ['建築臨街三公尺界面', '3 m building street edge'],
  SOUTH_QUAY_MAX_GAP: ['南碼頭最大立面間隙', 'south quay maximum facade gap'],
  BOUNDARY_PARCEL_SEMANTICS: ['邊界地塊語意', 'boundary parcel semantics'],
  NO_LARGE_UNBUILT_PLOT: ['不留大塊未配置土地', 'no large unassigned plot'],
  BLOCK_LAND_BUDGET: ['街廓用地預算', 'block land budget'],
  SERVICE_FUNCTION_FRONTAGE: ['服務機能臨街面', 'service-function frontage'],
  NORTHEAST_REGULAR_BLOCKS: ['東北區規則街廓', 'regular north-east blocks'],
  PARK_AREA_BUDGET: ['公園面積預算', 'park area budget'],
  COURTYARD_ISLAND_ROAD_CLEARANCE: ['院落島道路淨距', 'courtyard-island road clearance'],
  COURTYARD_ISLAND_GLOBAL_MEMBERSHIP: ['院落島整體歸屬', 'courtyard-island global membership'],
  COURTYARD_ISLAND_COUNT_SPACING: ['院落島數量與間距', 'courtyard-island count and spacing'],
};

const GAP_FAMILIES: Record<string, [string, string]> = {
  e1: ['E1 日照', 'E1 sunlight'], e2: ['E2 輻射', 'E2 radiation'], e3: ['E3 耗能', 'E3 energy'], e4: ['E4 蓄熱', 'E4 thermal mass'],
  e5: ['E5 風場', 'E5 wind'], utci: ['UTCI 熱舒適', 'UTCI thermal comfort'], syntax: ['空間語法', 'space syntax'],
};

/** "DATA_GAP:e5.*" → "資料缺口（E5 風場）"; the validator requires the literal token, the reader gets words. */
export function humanizeDataGaps(text: string, language: Language): string {
  const zh = language === 'zh-TW';
  return text.replace(/DATA_GAP:([A-Za-z0-9_]+)[A-Za-z0-9_.*]*/g, (_m: string, family: string) => {
    const pair = GAP_FAMILIES[family.toLowerCase()];
    const name = pair ? pair[zh ? 0 : 1] : (zh ? '部分資料' : 'some data');
    return zh ? `資料缺口（${name}）` : `data gap (${name})`;
  }).replace(/\bDATA_GAP\b/g, zh ? '資料缺口' : 'data gap');
}

const FIELD_LABELS: Record<string, [string, string]> = {
  floors_to_remove_for_north_edge: ['讓陽光到北緣需移除的層數', 'floors to remove for sun at the north edge'],
  depth_along_sun_m: ['沿太陽方向的中庭淨深', 'courtyard depth along the sun'],
  south_edge_height_max_m: ['南側最高高度', 'maximum south-edge height'],
  south_edge_height_median_m: ['南側高度中位數', 'median south-edge height'],
  feasible_within_catalogue: ['在操作範圍內可行', 'feasible within the operation catalogue'],
  south_building_ids: ['南側建築', 'south-edge buildings'],
  north_building_ids: ['北側建築', 'north-edge buildings'],
  sun_side_building_ids: ['向陽側建築', 'sun-side buildings'],
  winter_mean_h: ['冬至平均日照', 'winter mean sunlight'],
  h_half_m: ['陽光到中庭一半深度的高度門檻', 'height threshold for sun at half depth'],
  h_north_edge_equinox_m: ['春秋分北緣高度門檻', 'equinox north-edge height threshold'],
  winter_noon_sun_altitude_deg: ['冬至正午太陽高度角', 'winter-solstice noon sun altitude'],
  clear_width_m: ['中庭淨寬', 'courtyard clear width'],
  local_sun_pockets: ['局部日照帶', 'local sun pockets'],
  reaches_north_edge: ['陽光可到北緣', 'sun reaches the north edge'],
  solar_access_check: ['日照檢查', 'solar access check'],
  strategy_report: ['策略試算', 'strategy report'],
};

/** Turn Ariadne's machine references (metric ids, response / stance ids, status words) into reader-facing words. */
export function humanizeAriadneText(text: string, language: Language): string {
  const zh = language === 'zh-TW';
  return humanizeDataGaps(text, language)
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\b(?:e[1-5]|utci|syntax|scheme)\.[a-z0-9_]+(?:\.[a-z0-9_]+)+/g, id => formatMetricRef(id, null, null, language))
    .replace(/\bseed-([a-z_]+)\b/g, (_, key: string) => (STANCE_LABELS[key] ?? [zh ? '你的設計立場' : 'your design stance', 'your design stance'])[zh ? 0 : 1])
    .replace(/\bjr-[0-9a-f]{8,}\b/g, zh ? '你先前的回應' : 'your earlier response')
    .replace(/\bjudgement-[0-9a-f]{8,}\b/g, zh ? '判讀卡' : 'the judgement card')
    .replace(/\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+){1,}\b/g, (code: string) => (MORPH_FAILURE_LABELS[code] ? MORPH_FAILURE_LABELS[code][zh ? 0 : 1] : code))
    .replace(/\bASSUMED\b/g, zh ? '假設值' : 'assumed')
    .replace(/\bSOLAR_ENVELOPE\b/g, zh ? '日照包絡' : 'solar envelope')
    .replace(/\bCOURTYARD_WING_DEPTH\b/g, zh ? '中庭翼進深' : 'courtyard wing depth')
    .replace(/\bPLANTING_NOTE\b/g, zh ? '植栽註記' : 'planting note')
    .replace(/\b(?:floors_to_remove_for_north_edge|depth_along_sun_m|south_edge_height_max_m|south_edge_height_median_m|feasible_within_catalogue|south_building_ids|north_building_ids|sun_side_building_ids|winter_mean_h|h_half_m|h_north_edge_equinox_m|winter_noon_sun_altitude_deg|clear_width_m|local_sun_pockets|reaches_north_edge|solar_access_check|strategy_report)\b/g, (field: string) => (FIELD_LABELS[field] ?? [field, field])[zh ? 0 : 1])
    .replace(/\bh_north_edge_m\b/g, zh ? '北緣高度' : 'north edge height')
    .replace(/\bnorth_edge\b/g, zh ? '中庭北緣' : 'courtyard north edge')
    .replace(/\bhalf_depth\b/g, zh ? '中庭一半深度' : 'courtyard half depth')
    .replace(/\bremoved_gfa_m2\b/g, zh ? '移除樓地板' : 'removed floor area')
    .replace(/\badded_gfa_m2\b/g, zh ? '移入樓地板' : 'added floor area')
    .replace(/\bgfa_shortfall_m2\b/g, zh ? '樓地板短缺' : 'floor area shortfall')
    .replace(/\bsolar_geometry\b/g, zh ? '日照幾何' : 'solar geometry')
    .replace(/\bwinter_mean_h\b/g, zh ? '冬至平均日照' : 'winter mean sunlight')
    .replace(/\bstreet_add_remove\b/g, zh ? '街道增減' : 'street connections')
    .replace(/\bopen_space_allocation\b/g, zh ? '開放空間配置' : 'open space allocation')
    .replace(/\bcourtyard_width\b/g, zh ? '中庭寬度' : 'courtyard width')
    .replace(/\banalysis_needed\b/g, zh ? '補充分析' : 'further analysis')
    .replace(/\bJ-MORPH\b/g, zh ? '形態判讀' : 'morphology judgement');
}

export function humanizeLimitation(text: string, language: Language): string {
  const pair = LIMITATION_LABELS[text];
  return pair ? pair[language === 'zh-TW' ? 0 : 1] : humanizeAriadneText(text, language);
}
