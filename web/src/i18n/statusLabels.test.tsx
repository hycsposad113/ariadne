// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { STATUS_LABELS, StatusBadge, getStatusLabel } from './statusLabels';

const REQUIRED_USER_CODES = [
  'VERIFIED_SOURCE_RESULT_ALIGNMENT',
  'SOURCE_ALIGNED_COVERAGE_LIMITED',
  'VERIFIED_OBSERVATION',
  'OBSERVATIONAL_ONLY',
  'BLOCKED_BOUNDARY_STABILITY_UNASSESSED',
  'NOT_PUBLISHED',
  'EXPLORATORY_DRAFT',
  'FIXTURE_ONLY',
  'FORMAL_DRAFT',
  'APPROVED_INPUTS',
  'FABRIC_PLAN_E2_ONLY',
  'UNAPPROVED_PREVIEW',
  'READY_TO_START',
] as const;

const ALLOWED_CHINESE_LATIN_TOKENS = new Set([
  'AI', 'BAG', 'E1', 'E2', 'E3', 'E4', 'E5', 'EPSG', 'FAR', 'GFA', 'm', 'OSM', 'PDOK', 'UTCI',
  '2D', '3D',
]);

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe('status labels', () => {
  it('has explicit bilingual labels for every requested user status and approved decisions', () => {
    for (const code of [...REQUIRED_USER_CODES, 'approved']) {
      expect(STATUS_LABELS[code], `${code} should have an explicit label`).toBeDefined();
      expect(STATUS_LABELS[code].en).not.toMatch(/[A-Z0-9]+_[A-Z0-9_]+/);
      expect(STATUS_LABELS[code]['zh-TW']).not.toMatch(/[A-Z0-9]+_[A-Z0-9_]+/);
    }
  });

  it('renders every registered Traditional Chinese label without leaking English words or codes', () => {
    const { container } = render(
      <div>
        {Object.keys(STATUS_LABELS).map((status) => (
          <StatusBadge key={status} status={status} language="zh-TW" />
        ))}
      </div>,
    );

    const badges = [...container.querySelectorAll<HTMLElement>('.status-badge')];
    expect(badges).toHaveLength(Object.keys(STATUS_LABELS).length);
    for (const badge of badges) {
      expect(badge.textContent).not.toMatch(/[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+/);
      const latinTokens = badge.textContent?.match(/[A-Za-z][A-Za-z0-9-]*/g) ?? [];
      expect(latinTokens.filter((token) => !ALLOWED_CHINESE_LATIN_TOKENS.has(token))).toEqual([]);
    }
  });

  it('translates status-code tooltips in both zh-TW and en and keeps the raw code in data-status', () => {
    const testCodes: [string, { en: string; 'zh-TW': string }][] = [
      ['ACCEPTED', { en: 'Accepted', 'zh-TW': '已採納' }],
      ['APPROVED', { en: 'Approved', 'zh-TW': '已核准' }],
      ['COMPLETED', { en: 'Completed', 'zh-TW': '已完成' }],
      ['LOADING', { en: 'Loading…', 'zh-TW': '載入中…' }],
      [
        'BLOCKED_BOUNDARY_STABILITY_UNASSESSED',
        {
          en: 'Boundary stability unassessed (space syntax for reference only)',
          'zh-TW': '邊界穩定性尚未評估（空間語法僅供參考）',
        },
      ],
      ['EXPLORATORY', { en: 'Exploratory', 'zh-TW': '探索性' }],
      ['UNKNOWN', { en: 'Unknown', 'zh-TW': '未知狀態' }],
      ['proposed', { en: 'Proposed', 'zh-TW': '候選提案' }],
      ['rejected', { en: 'Rejected', 'zh-TW': '已駁回' }],
    ];

    for (const [code, expected] of testCodes) {
      for (const lang of ['zh-TW', 'en'] as const) {
        const { container } = render(<StatusBadge status={code} language={lang} />);
        const badge = container.querySelector<HTMLElement>('.status-badge');
        expect(badge, `badge for ${code} in ${lang}`).not.toBeNull();
        expect(badge).toHaveAttribute('title', expected[lang]);
        expect(badge).toHaveAttribute('data-status', code);
      }
    }
  });

  it('keeps an unknown raw code in data-status and uses a translated tooltip with Chinese fallback', () => {
    const { container } = render(<StatusBadge status="UNRECOGNIZED_WIRE_CODE" language="zh-TW" />);
    const badge = container.querySelector<HTMLElement>('.status-badge');

    expect(badge).toHaveAttribute('title', '狀態尚未翻譯');
    expect(badge?.textContent).toBe('狀態尚未翻譯');
    expect(badge).toHaveAttribute('data-status', 'UNRECOGNIZED_WIRE_CODE');
    expect(container.querySelector('.sr-only')).toBeNull();
  });

  it('formats unknown English codes in sentence case and warns once per code in development', () => {
    vi.stubEnv('DEV', true);
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});

    expect(getStatusLabel('UNKNOWN_WIRE_STATUS', 'en').label).toBe('Unknown wire status');
    expect(getStatusLabel('UNKNOWN_WIRE_STATUS', 'en').label).toBe('Unknown wire status');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(error).not.toHaveBeenCalled();
  });

  it('keeps every registered English label in sentence case', () => {
    const acronyms = new Set(['AI', 'BAG', 'E1', 'E2', 'E3', 'E4', 'E5', 'EPSG', 'FAR', 'GFA', 'OSM', 'PDOK', 'UTCI', '2D', '3D']);

    for (const [code, translation] of Object.entries(STATUS_LABELS)) {
      const words = translation.en.match(/[A-Za-z0-9]+/g) ?? [];
      for (const word of words.slice(1)) {
        if (!acronyms.has(word)) {
          expect(word, `${code} should use English sentence case`).toBe(word.toLowerCase());
        }
      }
    }
  });
});
