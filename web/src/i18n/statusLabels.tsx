import React from 'react';
import type { Language } from '../i18n';

export interface StatusTranslation {
  en: string;
  'zh-TW': string;
}

const warnedUnknownStatusCodes = new Set<string>();
const ENGLISH_STATUS_ACRONYMS = new Set([
  'AI', 'BAG', 'E1', 'E2', 'E3', 'E4', 'E5', 'EPSG', 'FAR', 'GFA', 'OSM', 'PDOK', 'UTCI', '2D', '3D',
]);

function isStatusCode(raw: string): boolean {
  return /^[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*$/.test(raw);
}

function warnUnknownStatusCode(raw: string): void {
  if (!import.meta.env.DEV) return;
  const key = raw.toUpperCase();
  if (warnedUnknownStatusCodes.has(key)) return;
  warnedUnknownStatusCodes.add(key);
  console.warn(`[StatusBadge] Unknown status code: ${raw}`);
}

function sentenceCaseStatusCode(raw: string): string {
  return raw
    .replace(/[_-]+/g, ' ')
    .toLowerCase()
    .split(/\s+/)
    .map((word, index) => {
      const acronym = word.toUpperCase();
      if (ENGLISH_STATUS_ACRONYMS.has(acronym)) return acronym;
      return index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word;
    })
    .join(' ');
}

export const STATUS_LABELS: Record<string, StatusTranslation> = {
  REJECTED_BY_VALIDATOR: {en: 'Judgement did not pass evidence validation', 'zh-TW': '判讀未通過證據驗證'},
  VALIDATION_FAILED: {en: 'Judgement did not pass evidence validation', 'zh-TW': '判讀未通過證據驗證'},
  DRY_RUN_FAILED: {en: 'Dry run check failed', 'zh-TW': '試算檢查未通過'},
  APPROVED: {en: 'Approved', 'zh-TW': '已核准'},
  LOADING: {en: 'Loading…', 'zh-TW': '載入中…'},
  PROPOSAL_APPROVED: {en: 'Approved for recalculation', 'zh-TW': '已核准重算'},
  NESTED_FLOOR_STACK_VALIDATED: {en: 'Nested floor-stack validated', 'zh-TW': '樓層堆疊拓撲已驗證'},
  ASSUMED: {en: 'Assumed', 'zh-TW': '假設值'},
  DATA_GAP: {en: 'Data gap', 'zh-TW': '資料缺口'},
  AVAILABLE: {en: 'Available', 'zh-TW': '已取得資料'},
  REMOVE_TOP_FLOOR: {en: 'Remove top floor', 'zh-TW': '降層'},
  SETBACK_UPPER: {en: 'Upper floor setback', 'zh-TW': '上層退台'},
  MOVE: {en: 'Move', 'zh-TW': '平移'},
  ADD_FLOOR: {en: 'Add floor', 'zh-TW': '加層'},
  PLANTING_NOTE: {en: 'Planting note', 'zh-TW': '植栽註記'},
  RERUN: {en: 'Recalculate', 'zh-TW': '重算'},
  SOLAR_ENVELOPE: {en: 'Solar envelope', 'zh-TW': '日照包絡'},
  COURTYARD_WING_DEPTH: {en: 'Courtyard wing depth', 'zh-TW': '中庭翼進深'},
  ENVELOPE_UNREACHABLE: {en: 'Threshold unreachable', 'zh-TW': '未達包絡門檻'},
  MORPHOLOGY: {en: 'Morphology', 'zh-TW': '形態'},
  'J-MORPH': {en: 'Morphology judgement', 'zh-TW': '形態判讀'},
  BLOCKED_AI_AUTHORIZATION: {en: 'AI judgement is not enabled', 'zh-TW': '尚未啟用 AI 判讀'},
  // Boundary and syntax statuses
  BLOCKED_BOUNDARY_STABILITY_UNASSESSED: {
    en: 'Boundary stability unassessed (space syntax for reference only)',
    'zh-TW': '邊界穩定性尚未評估（空間語法僅供參考）',
  },
  BLOCKED_COVERAGE_EVIDENCE_ABSENT: {
    en: 'Coverage evidence absent (blocked)',
    'zh-TW': '覆蓋率證據缺失（已阻擋）',
  },
  BLOCKED_RUNTIME_BUDGET_ESTIMATE: {
    en: 'Runtime budget estimate (blocked)',
    'zh-TW': '運算時間超出預算（已阻擋）',
  },
  EXPLORATORY: {
    en: 'Exploratory',
    'zh-TW': '探索性',
  },
  EXPLORATORY_800M_ONLY_SOURCE_COVERAGE_INSUFFICIENT: {
    en: 'Exploratory (800 m only, coverage limited)',
    'zh-TW': '探索性（僅 800 m，覆蓋不足）',
  },

  // Scenario and preview statuses
  UNAPPROVED_PREVIEW: {
    en: 'Exploratory preview (unapproved)',
    'zh-TW': '探索草案預覽（未批准）',
  },
  EXPLORATORY_DRAFT: {
    en: 'Exploratory draft',
    'zh-TW': '探索草案（未接受）',
  },
  FIXTURE_ONLY: {
    en: 'Prototype fixture only',
    'zh-TW': '僅供測試原型',
  },
  FORMAL_DRAFT: {
    en: 'Formal draft',
    'zh-TW': '正式草案',
  },
  FABRIC_PLAN_E2_ONLY: {
    en: 'Fabric plan (E2 radiation analysis only)',
    'zh-TW': '紋理方案（僅供 E2 輻射分析）',
  },
  APPROVED_INPUTS: {
    en: 'Inputs approved',
    'zh-TW': '輸入條件已核准',
  },
  NOT_PUBLISHED: {
    en: 'Not published',
    'zh-TW': '尚未發布',
  },
  PUBLISHED: {
    en: 'Published',
    'zh-TW': '已發布',
  },

  // Evidence alignment statuses
  VERIFIED_SOURCE_RESULT_ALIGNMENT: {
    en: 'Source-to-result alignment verified',
    'zh-TW': '來源與結果對應已驗證',
  },
  SOURCE_ALIGNED_COVERAGE_LIMITED: {
    en: 'Source aligned (coverage limited)',
    'zh-TW': '來源已對應，但資料涵蓋範圍有限',
  },
  VERIFIED_OBSERVATION: {
    en: 'Verified observation',
    'zh-TW': '已驗證觀測',
  },
  OBSERVATIONAL_ONLY: {
    en: 'Observational only',
    'zh-TW': '僅供觀測',
  },

  // General decision & execution lifecycle
  NOT_READY: {
    en: 'Not ready',
    'zh-TW': '尚未就緒',
  },
  UNKNOWN: {
    en: 'Unknown',
    'zh-TW': '未知狀態',
  },
  ASSUMED_COMMANDER: {
    en: 'Assumed by commander',
    'zh-TW': '指揮官假設',
  },
  BLOCKED: {
    en: 'Blocked',
    'zh-TW': '已阻擋',
  },
  BLOCKED_PREVIEWS_ONLY: {
    en: 'Previews only (blocked)',
    'zh-TW': '僅有草案預覽（決策關閉）',
  },
  BLOCKED_VALIDATION_FAILED: {
    en: 'Validation failed (blocked)',
    'zh-TW': '驗證未通過（已阻擋）',
  },
  BLOCKED_BUDGET: {
    en: 'Budget exhausted (blocked)',
    'zh-TW': '運算額度用盡（已阻擋）',
  },
  BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED: {
    en: 'Live AI not enabled',
    'zh-TW': 'AI 目前未啟用',
  },
  BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED: {
    en: 'Live AI unauthorized',
    'zh-TW': '專案尚未授權 AI',
  },
  BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE: {
    en: 'Accounting unavailable (blocked)',
    'zh-TW': '調用計數無法使用（已阻擋）',
  },
  BLOCKED_ARIADNE_PROFILE_UNAVAILABLE: {
    en: 'Profile unavailable (blocked)',
    'zh-TW': 'AI 設定檔無法使用（已阻擋）',
  },

  // Decision outcomes
  accepted: {
    en: 'Accepted',
    'zh-TW': '已採納',
  },
  ACCEPTED: {
    en: 'Accepted',
    'zh-TW': '已採納',
  },
  proposed: {
    en: 'Proposed',
    'zh-TW': '候選提案',
  },
  PROPOSED: {
    en: 'Proposed',
    'zh-TW': '候選提案',
  },
  rejected: {
    en: 'Rejected',
    'zh-TW': '已駁回',
  },
  REJECTED: {
    en: 'Rejected',
    'zh-TW': '已駁回',
  },
  draft: {
    en: 'Draft',
    'zh-TW': '草案',
  },
  DRAFT: {
    en: 'Draft',
    'zh-TW': '草案',
  },
  DRAFT_PENDING_HUMAN_DECISION: {
    en: 'Draft (pending review)',
    'zh-TW': '草案（待人類審核）',
  },
  CONFIRMED_FOR_EXPLORATION: {
    en: 'Confirmed for exploration',
    'zh-TW': '已核准進入探索',
  },
  READY_FOR_DECISION: {
    en: 'Ready for decision',
    'zh-TW': '可進行決策',
  },
  BASELINE_SELECTED: {
    en: 'Baseline selected',
    'zh-TW': '已選定基準方案',
  },
  OUTCOME_UNKNOWN: {
    en: 'Outcome unknown (administrator reconciliation required before retry)',
    'zh-TW': '結果不明，需管理者對帳後才能重試',
  },
  COMPUTED: {
    en: 'Computed',
    'zh-TW': '已計算',
  },
  NOT_COMPUTED: {
    en: 'Not computed',
    'zh-TW': '未計算',
  },

  // Human review and decision states
  approved: {
    en: 'Approved',
    'zh-TW': '已核准',
  },
  not_reviewed: {
    en: 'Not reviewed',
    'zh-TW': '尚未審閱',
  },
  inspected: {
    en: 'Inspected',
    'zh-TW': '已檢視',
  },
  challenged: {
    en: 'Challenged',
    'zh-TW': '已提出質疑',
  },
  modified: {
    en: 'Modified',
    'zh-TW': '已修改',
  },
  overridden: {
    en: 'Overridden',
    'zh-TW': '已由人類決策覆蓋',
  },

  // Workflow and evidence lifecycle statuses rendered by the web UI
  READY_TO_START: {
    en: 'Ready to start',
    'zh-TW': '可開始流程',
  },
  READY_TO_RUN: {
    en: 'Ready to run',
    'zh-TW': '可執行',
  },
  PENDING: {
    en: 'Pending',
    'zh-TW': '待處理',
  },
  PENDING_APPROVAL: {
    en: 'Pending approval',
    'zh-TW': '待核准',
  },
  RUNNING: {
    en: 'Running',
    'zh-TW': '執行中',
  },
  SUCCEEDED: {
    en: 'Succeeded',
    'zh-TW': '已成功',
  },
  FAILED: {
    en: 'Failed',
    'zh-TW': '執行失敗',
  },
  STALE: {
    en: 'Stale',
    'zh-TW': '已過期',
  },
  COMPLETE_UNACCEPTED: {
    en: 'Complete, awaiting acceptance',
    'zh-TW': '已完成，尚待接受',
  },
  AWAITING_SELECTION: {
    en: 'Awaiting selection',
    'zh-TW': '待選擇',
  },
  CANCELLED: {
    en: 'Cancelled',
    'zh-TW': '已取消',
  },
  PREPARED: {
    en: 'Prepared',
    'zh-TW': '已準備',
  },
  READY: {
    en: 'Ready',
    'zh-TW': '就緒',
  },
  INTERRUPTED: {
    en: 'Interrupted',
    'zh-TW': '已中斷',
  },
  BLOCKED_COLLISION: {
    en: 'Blocked by concurrency collision',
    'zh-TW': '因並行衝突而阻擋',
  },
  DECREASED: {
    en: 'Decreased',
    'zh-TW': '降低',
  },
  INCREASED: {
    en: 'Increased',
    'zh-TW': '增加',
  },
  NO_CHANGE: {
    en: 'No change',
    'zh-TW': '無變化',
  },
  NOT_STARTED: {
    en: 'Not started',
    'zh-TW': '未開始',
  },
  WAITING_DECISION: {
    en: 'Waiting for your decision',
    'zh-TW': '等待你決策',
  },
  COMPLETED: {
    en: 'Completed',
    'zh-TW': '已完成',
  },
  DETERMINISTIC_METHOD: {
    en: 'Deterministic method',
    'zh-TW': '確定性方法',
  },
  STALE_FOR_CURRENT_CONTEXT: {
    en: 'Stale for current context',
    'zh-TW': '目前情境已變更，結果過期',
  },
  ERROR: {
    en: 'Error',
    'zh-TW': '錯誤',
  },
  PASS: {
    en: 'Pass',
    'zh-TW': '通過',
  },
  FAIL: {
    en: 'Fail',
    'zh-TW': '未通過',
  },
  SUCCESS: {
    en: 'Success',
    'zh-TW': '成功',
  },
  VALIDATED: {
    en: 'Validated',
    'zh-TW': '已驗證',
  },
  UNVERIFIED: {
    en: 'Unverified',
    'zh-TW': '未驗證',
  },
  INVALID: {
    en: 'Invalid',
    'zh-TW': '無效',
  },
  SUPERSEDED: {
    en: 'Superseded',
    'zh-TW': '已被新版本取代',
  },
  CONTESTED: {
    en: 'Contested',
    'zh-TW': '有爭議',
  },
  HIGH: {
    en: 'High',
    'zh-TW': '高',
  },
  MEDIUM: {
    en: 'Medium',
    'zh-TW': '中',
  },
  LOW: {
    en: 'Low',
    'zh-TW': '低',
  },
  NOT_COMPUTED_COVERAGE_BLOCKED: {
    en: 'Not computed (coverage blocked)',
    'zh-TW': '未計算（覆蓋受阻）',
  },
  NOT_COMPUTED_RUNTIME_BUDGET: {
    en: 'Not computed (runtime budget)',
    'zh-TW': '未計算（運算時間預算）',
  },
  BACKEND_CONFIRMED: {
    en: 'Backend confirmed',
    'zh-TW': '後端已確認',
  },
  COMPARABLE: {
    en: 'Comparable',
    'zh-TW': '可比較',
  },
  NOT_COMPARABLE: {
    en: 'Not comparable',
    'zh-TW': '不可比較',
  },
  UNAVAILABLE: {
    en: 'Unavailable',
    'zh-TW': '無法取得',
  },
  ANALYSIS_DEFINED: {
    en: 'Analysis defined',
    'zh-TW': '分析已定義',
  },
};

export interface StatusLabelInfo {
  label: string;
  tooltip: string;
  raw: string;
}

/**
 * Returns a localized label and translated tooltip.
 * Known NOT_READY* and BLOCKED* families retain their safe generic labels.
 */
export function getStatusLabel(
  rawStatus: string | null | undefined,
  language: Language = 'zh-TW'
): StatusLabelInfo {
  const raw = String(rawStatus ?? '').trim();
  if (!raw) {
    const fallback = language === 'zh-TW' ? '未知狀態' : 'Unknown';
    return {
      label: fallback,
      tooltip: fallback,
      raw: '',
    };
  }

  const upper = raw.toUpperCase();
  // Exact and case-insensitive match
  const translation = STATUS_LABELS[raw] ?? STATUS_LABELS[upper] ?? STATUS_LABELS[raw.toLowerCase()];
  if (translation) {
    return {
      label: translation[language] || translation['zh-TW'],
      tooltip: translation[language] || translation['zh-TW'],
      raw,
    };
  }

  const isCode = isStatusCode(raw);
  if (isCode) warnUnknownStatusCode(raw);

  // Prefix matching for NOT_READY*
  if (upper.startsWith('NOT_READY')) {
    const label = language === 'zh-TW' ? '尚未就緒' : 'Not ready';
    return {
      label,
      tooltip: label,
      raw,
    };
  }

  // Prefix matching for BLOCKED*
  if (upper.startsWith('BLOCKED')) {
    const label = language === 'zh-TW' ? '已阻擋' : 'Blocked';
    return {
      label,
      tooltip: label,
      raw,
    };
  }

  if (isCode) {
    const label = language === 'zh-TW' ? '狀態尚未翻譯' : sentenceCaseStatusCode(raw);
    return {
      label,
      tooltip: label,
      raw,
    };
  }

  const label = language === 'zh-TW' && !/[\u3400-\u9fff]/u.test(raw) ? '狀態尚未翻譯' : raw;
  return {
    label,
    tooltip: label,
    raw,
  };
}

/**
 * Clean React component for rendering human-readable status badge with tooltip.
 */
export const StatusBadge: React.FC<{
  status: string | null | undefined;
  className?: string;
  style?: React.CSSProperties;
  language?: Language;
  selected?: boolean;
  showRawSrOnly?: boolean;
}> = ({ status, className = '', style, language = 'zh-TW', selected = false }) => {
  const { label, tooltip, raw } = getStatusLabel(status, language);
  const isAccepted = String(status).toUpperCase() === 'ACCEPTED';
  const isSelected = selected || isAccepted;

  return (
    <span
      className={`status-badge ${isSelected ? 'status-badge--selected' : ''} ${className}`}
      title={tooltip}
      data-status={raw || undefined}
      style={style}
    >
      {selected ? (language === 'zh-TW' ? '選定 · ' : 'Selected · ') : ''}
      {label}
    </span>
  );
};
