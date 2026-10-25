/// <reference types="node" />
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { I18nProvider } from '../i18n';
import { JudgementCard, JudgementPanel, type JudgementRecord } from './JudgementCard';
import { ProposalCard } from './ProposalCard';
import { E2Workspace } from './E2Workspace';
import { FabricCompare, FABRIC_IDS } from './FabricCompare';
import {
  formatProposalOperation,
  type ProposalOperation,
  type ProposalRecord,
} from '../utils/proposalUtils';

// Read real sample fixtures
const morphJudgementFixture = JSON.parse(
  readFileSync(
    `${process.cwd()}/../artifacts/w8/rehearsal/p4a-morph/samples/judgement-morph.json`,
    'utf8',
  ),
) as JudgementRecord;

const envelopeProposalFixture = JSON.parse(
  readFileSync(
    `${process.cwd()}/../artifacts/w8/rehearsal/p4a-morph/samples/proposal-envelope.json`,
    'utf8',
  ),
) as ProposalRecord;

const localPocketProposalFixture = JSON.parse(
  readFileSync(
    `${process.cwd()}/../artifacts/w8/rehearsal/p4a-morph/samples/proposal-local-pocket.json`,
    'utf8',
  ),
) as ProposalRecord;

const E2_FIXTURE = {
  job_id: '2ffdd4a43129495c81774419354db615',
  status: 'SUCCEEDED',
  evidence_validation_status: 'VALIDATED',
  direction_summary: {
    direction_agreement_by_offset: { '-1': true, '0': true, '1': true },
    explanation:
      '只比較各方法內的改善（入射輻射降低）／變差方向。篩選使用天空 patch 遮擋；驗證使用含反射的 Radiance 係數。方向一致不代表絕對值可互換。',
  },
  limitations: [
    '累積入射輻射不代表熱舒適、耗能或材料蓄熱。',
    '公共開放空間為幾何分析範圍，不代表 legal right of way。',
  ],
  comparisons: {
    ladybug_radiance: {
      '0': {
        baseline_kwh_m2: 403.96,
        modified_kwh_m2: 359.97,
        delta_kwh_m2: -43.99,
        direction: 'DECREASED',
      },
    },
    honeybee_radiance: {
      '0': {
        baseline_kwh_m2: 411.45,
        modified_kwh_m2: 374.12,
        delta_kwh_m2: -37.34,
        direction: 'DECREASED',
      },
    },
  },
};

function wrap(node: React.ReactNode, language: 'en' | 'zh-TW' = 'zh-TW') {
  return render(<I18nProvider language={language}>{node}</I18nProvider>);
}

function jsonResponse(data: unknown, ok = true) {
  return Promise.resolve({
    ok,
    json: async () => data,
  } as Response);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('Task P4a Frontend Requirements', () => {
  // 1. J-MORPH entrance & JudgementPanel / JudgementCard
  describe('1. J-MORPH Entrance and Card Support', () => {
    it('shows J-MORPH panel in single-scheme view and hides in parallel view', async () => {
      const layers = Object.fromEntries(
        ['roads', 'blocks', 'buildings', 'land_use', 'parks', 'site'].map((key) => [
          key,
          { type: 'FeatureCollection', features: [] },
        ]),
      );
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          const urlStr = String(url);
          if (urlStr.endsWith('fabric-plans')) {
            return jsonResponse({
              plans: FABRIC_IDS.map((id) => ({ fabric_id: id, label_zh: id })),
            });
          }
          if (urlStr.includes('/fabric-plans/')) {
            const fabric_id = urlStr.split('?')[0].split('/').at(-1);
            return jsonResponse({
              fabric_id,
              label_zh: fabric_id,
              output_crs: 'EPSG:4326',
              projected_crs: 'EPSG:28992',
              layers,
              layers_projected: layers,
              metrics: { new_far: 0.8 },
              land_use_table: [],
              checks: { failure_ids: [] },
              syntax_summary: null,
              design_statement_markdown: '# Statement\nContent',
              limitations: [],
            });
          }
          if (urlStr.includes('/ariadne/judgements')) {
            return jsonResponse({ cards: [], usage: { calls: 1, limit: 30 } });
          }
          return jsonResponse({});
        }),
      );

      wrap(<FabricCompare apiBase="http://test" />);
      await screen.findByTestId('fabric-select-harbour_grain');

      // In single scheme view: both J-COMPARE (設計判讀) and J-MORPH (形態判讀) panels exist
      expect(screen.getByText('Ariadne 形態判讀')).toBeTruthy();
      expect(screen.getByRole('button', { name: '請 Ariadne 判讀形態' })).toBeTruthy();
      expect(screen.getByText('Ariadne 設計判讀')).toBeTruthy();

      // Switch to parallel four-map view
      fireEvent.click(screen.getByTestId('fabric-parallel-toggle'));

      // In parallel view: J-MORPH panel is not displayed
      expect(screen.queryByText('Ariadne 形態判讀')).toBeNull();
      expect(screen.queryByRole('button', { name: '請 Ariadne 判讀形態' })).toBeNull();
      // J-COMPARE panel remains
      expect(screen.getByText('Ariadne 設計判讀')).toBeTruthy();
    });

    it('renders VALIDATED J-MORPH card with proposal request button in zh-TW and en', async () => {
      // zh-TW
      const fetcherZh = vi.fn(async (url: string) => {
        const urlStr = String(url);
        if (urlStr.includes('/ariadne/judgements')) {
          return jsonResponse({ cards: [morphJudgementFixture], usage: { calls: 2, limit: 30 } });
        }
        if (urlStr.includes('/ariadne/proposals')) {
          return jsonResponse({ proposals: [] });
        }
        return jsonResponse({});
      });
      vi.stubGlobal('fetch', fetcherZh);

      wrap(
        <JudgementPanel
          apiBase="http://test"
          projectId="test-proj"
          skillId="J-MORPH"
          subjectIds={['harbour_grain']}
        />,
        'zh-TW',
      );

      await screen.findByText('Ariadne 形態判讀');
      // Should show proposal request button for VALIDATED J-MORPH card
      expect(screen.getByRole('button', { name: '請 Ariadne 提出修正方案' })).toBeTruthy();
      expect(screen.getByRole('button', { name: '重新判讀' })).toBeTruthy();

      // Check card headline & parameter family labels
      expect(screen.getByText(/固定68.6 m街廓短邊/)).toBeTruthy();
      expect(screen.getByText('街道增減')).toBeTruthy();
      expect(screen.getByText('中庭寬度')).toBeTruthy();
      expect(screen.getByText('補充分析')).toBeTruthy();
      expect(screen.getByText('建築高度')).toBeTruthy();

      // Check reasoning lenses
      const detailsZh = screen.getByText('看依據與推理').closest('details')!;
      detailsZh.open = true;
      fireEvent(detailsZh, new Event('toggle'));
      expect(screen.getByRole('heading', { level: 5, name: '生成邏輯' })).toBeTruthy();
      expect(screen.getByRole('heading', { level: 5, name: '街廓與中庭尺度' })).toBeTruthy();
      expect(screen.getByRole('heading', { level: 5, name: '高度與密度分布' })).toBeTruthy();
      expect(screen.getByRole('heading', { level: 5, name: '檢核失敗與修補' })).toBeTruthy();
      expect(screen.getByRole('heading', { level: 5, name: '資料缺口' })).toBeTruthy();

      // English
      cleanup();
      const morphJudgementFixtureEn = { ...morphJudgementFixture, language: 'en' };
      vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        const urlStr = String(url);
        if (urlStr.includes('/ariadne/judgements')) {
          return jsonResponse({ cards: [morphJudgementFixtureEn], usage: { calls: 2, limit: 30 } });
        }
        if (urlStr.includes('/ariadne/proposals')) {
          return jsonResponse({ proposals: [] });
        }
        return jsonResponse({});
      }));
      wrap(
        <JudgementPanel
          apiBase="http://test"
          projectId="test-proj"
          skillId="J-MORPH"
          subjectIds={['harbour_grain']}
        />,
        'en',
      );

      await screen.findByText('Ariadne morphology judgement');
      expect(screen.getByRole('button', { name: 'Ask Ariadne for a revision proposal' })).toBeTruthy();
      expect(screen.getByRole('button', { name: 'Request new round' })).toBeTruthy();
      expect(screen.getByText('Street connections')).toBeTruthy();
      expect(screen.getByText('Courtyard width')).toBeTruthy();
      expect(screen.getByText('Further analysis')).toBeTruthy();
      expect(screen.getByText('Building height')).toBeTruthy();

      const detailsEn = screen.getByText('View evidence and reasoning').closest('details')!;
      detailsEn.open = true;
      fireEvent(detailsEn, new Event('toggle'));
      expect(screen.getByRole('heading', { level: 5, name: 'Generation logic' })).toBeTruthy();
      expect(screen.getByRole('heading', { level: 5, name: 'Block and courtyard scale' })).toBeTruthy();
      expect(screen.getByRole('heading', { level: 5, name: 'Height and density distribution' })).toBeTruthy();
      expect(screen.getByRole('heading', { level: 5, name: 'Failed checks and remediation' })).toBeTruthy();
      expect(screen.getByRole('heading', { level: 5, name: 'Data gaps' })).toBeTruthy();
    });
  });

  // 2. Strategy operations formatting
  describe('2. Strategy Operations Human Translation', () => {
    it('formats SOLAR_ENVELOPE with north_edge and half_depth, redistribute true and false', () => {
      // north_edge, redistribute = true
      const opEnvelope1: ProposalOperation = {
        op: 'SOLAR_ENVELOPE',
        courtyard_ids: ['courtyard-0', 'courtyard-1'],
        target: 'north_edge',
        redistribute: true,
      };
      expect(formatProposalOperation(opEnvelope1, 'zh-TW')).toBe(
        'courtyard-0、courtyard-1 南側日照包絡（到中庭北緣），減少的樓地板移到同街廓其他棟',
      );
      expect(formatProposalOperation(opEnvelope1, 'en')).toBe(
        'courtyard-0, courtyard-1: south-side solar envelope (to courtyard north edge), redistribute reduced floor area to other buildings in the block',
      );

      // half_depth, redistribute = false
      const opEnvelope2: ProposalOperation = {
        op: 'SOLAR_ENVELOPE',
        courtyard_ids: ['courtyard-0', 'courtyard-1'],
        target: 'half_depth',
        redistribute: false,
      };
      expect(formatProposalOperation(opEnvelope2, 'zh-TW')).toBe(
        'courtyard-0、courtyard-1 南側日照包絡（到中庭一半深度），不移轉樓地板',
      );
      expect(formatProposalOperation(opEnvelope2, 'en')).toBe(
        'courtyard-0, courtyard-1: south-side solar envelope (to courtyard half depth), no floor area redistribution',
      );
    });

    it('formats COURTYARD_WING_DEPTH correctly in zh-TW and en', () => {
      const opDepth: ProposalOperation = {
        op: 'COURTYARD_WING_DEPTH',
        courtyard_id: 'courtyard-0',
        side: 'south',
        depth_m: 10,
      };
      expect(formatProposalOperation(opDepth, 'zh-TW')).toBe(
        'courtyard-0 南側翼進深縮為 10 公尺（加寬中庭）',
      );
      expect(formatProposalOperation(opDepth, 'en')).toBe(
        'courtyard-0: reduce south wing depth to 10 metres (widening courtyard)',
      );
    });
  });

  // 3. Strategy report with proposal-envelope.json
  describe('3. Strategy Report Calculation & Trade-off Display', () => {
    it('displays rounded thousand-separated values 4,010, 3,067, 943, courtyard north edge, and orange shortfall', () => {
      wrap(
        <ProposalCard
          record={envelopeProposalFixture}
          apiBase="http://test"
          projectId="test-proj"
        />,
        'zh-TW',
      );

      // Check section title
      expect(screen.getByText('量體策略試算')).toBeTruthy();
      expect(screen.getByText('日照包絡策略')).toBeTruthy();

      // Check values
      // 4009.747... -> 4,010 平方公尺
      expect(screen.getByText('4,010 平方公尺')).toBeTruthy();
      // 3067.2 -> 3,067 平方公尺
      expect(screen.getByText('3,067 平方公尺')).toBeTruthy();
      // 942.547... -> 943 平方公尺
      const shortfallEl = screen.getByText('943 平方公尺');
      expect(shortfallEl).toBeTruthy();
      // Shortfall > 0 has orange color
      const shortfallContainer = shortfallEl.closest('div');
      expect(shortfallContainer?.getAttribute('style')).toContain('color: rgb(245, 158, 11)');
      expect(screen.getByText('（仍高於 85% 下限）')).toBeTruthy();

      // Courtyard envelope reaches north edge: both courtyard-0 and courtyard-1
      expect(screen.getByText(/courtyard-0 陽光可到北緣：是/)).toBeTruthy();
      expect(screen.getByText(/courtyard-1 陽光可到北緣：是/)).toBeTruthy();

      // Trade-off check reminders
      expect(screen.getByText('移入棟北側為街道時，北側街道冬季日照可能下降。')).toBeTruthy();
      expect(screen.getByText('樓地板短缺與 85% GFA 下限之取捨關係已納入考量。')).toBeTruthy();
    });

    it('does not display orange color when shortfall is 0', () => {
      const zeroShortfallRecord: ProposalRecord = {
        ...envelopeProposalFixture,
        dry_run: {
          ...envelopeProposalFixture.dry_run!,
          strategy_report: [
            {
              ...envelopeProposalFixture.dry_run!.strategy_report![0],
              gfa_shortfall_m2: 0,
            },
          ],
        },
      };

      wrap(
        <ProposalCard
          record={zeroShortfallRecord}
          apiBase="http://test"
          projectId="test-proj"
        />,
        'zh-TW',
      );

      const zeroEl = screen.getByText('0 平方公尺');
      expect(zeroEl).toBeTruthy();
      const container = zeroEl.closest('div');
      expect(container?.getAttribute('style')).toBeNull();
      expect(screen.queryByText('（仍高於 85% 下限）')).toBeNull();
    });
  });

  // 4. Long list folding
  describe('4. Affected Buildings List Folding', () => {
    it('folds list longer than 10 buildings and toggles on click', () => {
      // envelopeProposalFixture has 26 affected buildings
      wrap(
        <ProposalCard
          record={envelopeProposalFixture}
          apiBase="http://test"
          projectId="test-proj"
        />,
        'zh-TW',
      );

      // Initially shows first 10 buildings and "另 16 棟"
      const expandBtn = screen.getByRole('button', { name: '另 16 棟' });
      expect(expandBtn).toBeTruthy();
      expect(screen.getByText(/new-1、new-10/)).toBeTruthy();
      // The 11th building new-44 should not be in the visible bar yet
      const buildingsBar = expandBtn.closest('.proposal-card__buildings-bar');
      expect(buildingsBar?.textContent).not.toContain('new-44');

      // Click to expand
      fireEvent.click(expandBtn);
      expect(buildingsBar?.textContent).toContain('new-44');
      const collapseBtn = screen.getByRole('button', { name: '（收起）' });
      expect(collapseBtn).toBeTruthy();

      // Click to collapse
      fireEvent.click(collapseBtn);
      expect(screen.getByRole('button', { name: '另 16 棟' })).toBeTruthy();
      expect(buildingsBar?.textContent).not.toContain('new-44');
    });
  });

  // 5. E2 English explanation and limitations
  describe('5. E2 English Description & Limitations', () => {
    it('shows English explanation in en and original Chinese in zh-TW', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: string) => {
          const urlStr = String(url);
          if (urlStr.includes('/results/')) {
            return jsonResponse(E2_FIXTURE);
          }
          if (urlStr.includes('/snapshots')) {
            return jsonResponse([]);
          }
          if (urlStr.includes('/plans')) {
            return jsonResponse([]);
          }
          if (urlStr.includes('/jobs')) {
            return jsonResponse([
              {
                id: '2ffdd4a43129495c81774419354db615',
                job_id: '2ffdd4a43129495c81774419354db615',
                status: 'SUCCEEDED',
                created_at: '2026-10-18T00:00:00Z',
                updated_at: '2026-10-18T00:00:00Z',
                validated: true,
              },
            ]);
          }
          return jsonResponse({});
        }),
      );

      // zh-TW view
      wrap(<E2Workspace apiBase="http://test" />, 'zh-TW');

      // Click on view full table for the job
      const viewBtn = await screen.findByRole('button', { name: '查看完整結果表' });
      fireEvent.click(viewBtn);

      await screen.findByText('方向一致性摘要');
      expect(
        screen.getByText(
          '只比較各方法內的改善（入射輻射降低）／變差方向。篩選使用天空 patch 遮擋；驗證使用含反射的 Radiance 係數。方向一致不代表絕對值可互換。',
        ),
      ).toBeTruthy();

      expect(screen.getByText('累積入射輻射不代表熱舒適、耗能或材料蓄熱。')).toBeTruthy();
      expect(screen.queryByText(/\(Source note in Chinese\)/)).toBeNull();

      // English view
      cleanup();
      wrap(<E2Workspace apiBase="http://test" />, 'en');

      const viewBtnEn = await screen.findByRole('button', { name: 'View Full Table' });
      fireEvent.click(viewBtnEn);

      await screen.findByText('Direction Agreement Summary');
      expect(
        screen.getByText(
          'Only the improvement (lower incident radiation) or worsening direction within each method is compared. Screening uses sky-patch obstruction; verification uses Radiance coefficients with reflections. Agreement in direction does not make absolute values interchangeable.',
        ),
      ).toBeTruthy();

      expect(
        screen.getByText(
          '(Source note in Chinese) 累積入射輻射不代表熱舒適、耗能或材料蓄熱。',
        ),
      ).toBeTruthy();
    });
  });

  // 6. No raw codes leaked
  describe('6. Zero Raw Codes Scan', () => {
    it('does not display raw codes in JudgementCard or ProposalCard in zh or en', () => {
      const FORBIDDEN_CODES = [
        'SOLAR_ENVELOPE',
        'COURTYARD_WING_DEPTH',
        'north_edge',
        'half_depth',
        'street_add_remove',
        'open_space_allocation',
      ];

      // Test ProposalCard with envelope proposal
      const { container: propZh } = wrap(
        <ProposalCard
          record={envelopeProposalFixture}
          apiBase="http://test"
          projectId="test-proj"
        />,
        'zh-TW',
      );
      for (const code of FORBIDDEN_CODES) {
        expect(propZh.textContent).not.toContain(code);
      }

      const { container: propEn } = wrap(
        <ProposalCard
          record={envelopeProposalFixture}
          apiBase="http://test"
          projectId="test-proj"
        />,
        'en',
      );
      for (const code of FORBIDDEN_CODES) {
        expect(propEn.textContent).not.toContain(code);
      }

      // Test ProposalCard with local pocket proposal fixture
      const { container: pocketZh } = wrap(
        <ProposalCard
          record={localPocketProposalFixture}
          apiBase="http://test"
          projectId="test-proj"
        />,
        'zh-TW',
      );
      for (const code of FORBIDDEN_CODES) {
        expect(pocketZh.textContent).not.toContain(code);
      }
      expect(pocketZh.textContent).not.toContain('PLANTING_NOTE');
      expect(pocketZh.textContent).not.toContain('h_north_edge_m');

      // Test JudgementCard with morph judgement
      const { container: jZh } = wrap(<JudgementCard record={morphJudgementFixture} />, 'zh-TW');
      for (const code of FORBIDDEN_CODES) {
        expect(jZh.textContent).not.toContain(code);
      }
      expect(jZh.textContent).not.toMatch(/\bmorphology\b/);

      const { container: jEn } = wrap(<JudgementCard record={morphJudgementFixture} />, 'en');
      for (const code of FORBIDDEN_CODES) {
        expect(jEn.textContent).not.toContain(code);
      }
    });
  });
});

describe('Recalculation judgement link', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
  it('opens a judgement of another skill below the panel instead of reloading the same skill', async () => {
    const climate = { ...morphJudgementFixture, id: 'judgement-climate-post', skill_id: 'J-CLIMATE', round: 2, responses: [] } as JudgementRecord;
    const proposal = { ...envelopeProposalFixture, post_judgement_id: 'judgement-climate-post' } as ProposalRecord;
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: string) => {
      calls.push(String(input));
      const body = String(input).includes('/judgements/judgement-climate-post') ? climate
        : String(input).includes('/proposals') ? { proposals: [proposal] }
        : { cards: [morphJudgementFixture], usage: { calls: 1, limit: 200 } };
      return new Response(JSON.stringify(body), { status: 200 });
    }));
    render(<I18nProvider><JudgementPanel apiBase="http://api" projectId="p" skillId="J-MORPH" subjectIds={['harbour_grain']} /></I18nProvider>);
    const button = await screen.findByText(/看重算後的新判讀|View recalculation judgement/);
    fireEvent.click(button);
    expect(await screen.findByRole('region', { name: /重算後的新判讀|Recalculation judgement/ })).toBeTruthy();
    expect(calls.some((c) => c.endsWith('/judgements/judgement-climate-post'))).toBe(true);
  });
});
