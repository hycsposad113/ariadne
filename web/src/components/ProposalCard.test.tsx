/// <reference types="node" />
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { I18nProvider } from '../i18n';
import { ProposalCard } from './ProposalCard';
import { JudgementPanel, type JudgementRecord } from './JudgementCard';
import type { ProposalRecord, ProposalOperation } from '../utils/proposalUtils';
import { formatProposalOperation, humanizeAriadneText } from '../utils/proposalUtils';

function wrap(node: React.ReactNode, language: 'en' | 'zh-TW' = 'zh-TW') {
  return render(<I18nProvider language={language}>{node}</I18nProvider>);
}

function jsonResponse(data: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: async () => data,
  } as Response);
}

const validatedProposalFixture = JSON.parse(
  readFileSync(
    `${process.cwd()}/../artifacts/w8/rehearsal/p3-proposals/samples/proposal-validated.json`,
    'utf8',
  ),
) as ProposalRecord;

const rerunProposalFixture = JSON.parse(
  readFileSync(
    `${process.cwd()}/../artifacts/w8/rehearsal/p3-proposals/samples/proposal-after-rerun.json`,
    'utf8',
  ),
) as ProposalRecord;

const baseJudgementRecord: JudgementRecord = {
  id: 'judgement-test-1',
  status: 'VALIDATED',
  round: 1,
  created_at: '2026-10-17T12:00:00Z',
  card: {
    skill_id: 'J-CLIMATE',
    skill_version: '1.1.0',
    stage: 'climate',
    subject: { kind: 'scheme', ids: ['harbour_grain'] },
    judgement: { stance: 'CONCERN', headline: '中庭冬季日照需修正' },
    observations: [],
    reasoning: [],
    confidence: { level: 'medium', why: 'method limitations' },
    revision_directions: [],
    counterpoints: [],
    limitations: [],
    questions_for_designer: [],
  },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('ProposalCard and Operation Human Translations', () => {
  it('translates all 6 operation types into human-friendly Chinese and English', () => {
    // 1. REMOVE_TOP_FLOOR
    const op1: ProposalOperation = {
      op: 'REMOVE_TOP_FLOOR',
      building_ids: ['new-7', 'new-8'],
      floors: 1,
    };
    expect(formatProposalOperation(op1, 'zh-TW')).toBe('new-7、new-8 各降 1 層');
    expect(formatProposalOperation(op1, 'en')).toBe('Lower new-7, new-8 by 1 floor each');

    // 2. SETBACK_UPPER
    const op2: ProposalOperation = {
      op: 'SETBACK_UPPER',
      building_ids: ['new-7'],
      distance_m: 3,
      floors: 2,
    };
    expect(formatProposalOperation(op2, 'zh-TW')).toBe('new-7 上2層退台 3 公尺');
    expect(formatProposalOperation(op2, 'en')).toBe('new-7 Upper 2 floors setback by 3 metres');

    // 3. MOVE
    const op3: ProposalOperation = {
      op: 'MOVE',
      building_ids: ['new-8'],
      dx: 2,
      dy: 4,
    };
    expect(formatProposalOperation(op3, 'zh-TW')).toBe('new-8 平移 2, 4 公尺');
    expect(formatProposalOperation(op3, 'en')).toBe('new-8 Move by 2, 4 metres');

    // 4. ADD_FLOOR
    const op4: ProposalOperation = {
      op: 'ADD_FLOOR',
      building_ids: ['new-9'],
      floors: 2,
    };
    expect(formatProposalOperation(op4, 'zh-TW')).toBe('new-9 加 2 層');
    expect(formatProposalOperation(op4, 'en')).toBe('new-9 Add 2 floors');

    // 5. PLANTING_NOTE
    const op5: ProposalOperation = {
      op: 'PLANTING_NOTE',
      target: 'courtyard-0',
      kind: 'both',
    };
    expect(formatProposalOperation(op5, 'zh-TW')).toBe(
      'courtyard-0：落葉喬木＋棚架（設計註記，未納入模擬）',
    );
    expect(formatProposalOperation(op5, 'en')).toBe(
      'courtyard-0: Deciduous trees + trellis (design note, not included in simulation)',
    );

    // 6. RERUN
    const op6: ProposalOperation = {
      op: 'RERUN',
      analyses: ['E1', 'UTCI'],
    };
    expect(formatProposalOperation(op6, 'zh-TW')).toBe('重算：冬至日照 E1、夏季熱舒適 UTCI');
    expect(formatProposalOperation(op6, 'en')).toBe(
      'Recalculate: Winter solstice sunlight E1, summer thermal comfort UTCI',
    );
  });

  it('renders GFA calculation with thousand separator and "平方公尺" (never m² superscript in zh)', () => {
    wrap(<ProposalCard record={validatedProposalFixture} apiBase="http://test" projectId="p" />, 'zh-TW');

    expect(screen.getByText(/138,617 平方公尺 → 138,443 平方公尺/)).toBeTruthy();
    expect(screen.getByText(/85% 下限：124,842 平方公尺（假設值）/)).toBeTruthy();
    expect(screen.getByText('符合下限')).toBeTruthy();
  });

  it('renders failed or unknown runs (null proposal and dry run) without crashing and without approval', () => {
    const failed: ProposalRecord = {...validatedProposalFixture, status: 'VALIDATION_FAILED', proposal: null, dry_run: null};
    wrap(<ProposalCard record={failed} apiBase="http://test" projectId="p" />, 'zh-TW');
    expect(screen.getByText(/沒有產生可顯示的內容/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: '核准重算' })).toBeNull();
    cleanup();
    wrap(<ProposalCard record={{...failed, status: 'OUTCOME_UNKNOWN'}} apiBase="http://test" projectId="p" />, 'en');
    expect(screen.getByText(/produced no displayable proposal/)).toBeTruthy();
  });

  it('disables approval button when dry run fails and shows errors', () => {
    const failedDryRunRecord: ProposalRecord = {
      ...validatedProposalFixture,
      dry_run: {
        ...validatedProposalFixture.dry_run!,
        valid: false,
        errors: ['GFA falls below minimum floor 124,842 m²'],
      },
    };

    wrap(<ProposalCard record={failedDryRunRecord} apiBase="http://test" projectId="p" />, 'zh-TW');

    const approveBtn = screen.getByRole('button', { name: '核准重算' }) as HTMLButtonElement;
    expect(approveBtn.disabled).toBe(true);
    expect(screen.getByText('GFA falls below minimum floor 124,842 m²')).toBeTruthy();
  });

  it('renders solar access check warning when warning is true without blocking approval', () => {
    const warningProposal: ProposalRecord = {
      ...validatedProposalFixture,
      dry_run: {
        ...validatedProposalFixture.dry_run!,
        solar_access_check: {
          courtyards: [{ courtyard_id: 'courtyard-0', south_height_after_m: 14.5 }],
          claims_courtyard_winter_sun: true,
          warning: true,
        },
      },
    };

    wrap(<ProposalCard record={warningProposal} apiBase="http://test" projectId="p" />, 'zh-TW');

    expect(
      screen.getByText(/依冬至正午太陽高度（約 14.7°）幾何判斷，修改後南側量體仍會遮住中庭/),
    ).toBeTruthy();
    const approveBtn = screen.getByRole('button', { name: '核准重算' }) as HTMLButtonElement;
    expect(approveBtn.disabled).toBe(false);
  });

  it('shows confirmation dialog containing "不是正式接受" and posts note on approval', async () => {
    const fetcher = vi.fn((_url: string, options?: RequestInit) => {
      if (options?.method === 'POST') {
        return jsonResponse({
          ...validatedProposalFixture,
          status: 'APPROVED',
          approval: {
            created_at: '2026-10-18T00:00:00Z',
            note: '測試核准備註',
            is_human_decision: false,
          },
          job: {
            id: 'job-1',
            status: 'RUNNING',
            analyses: ['E1', 'UTCI'],
            created_at: new Date().toISOString(),
          },
        });
      }
      return jsonResponse(validatedProposalFixture);
    });
    vi.stubGlobal('fetch', fetcher);

    wrap(<ProposalCard record={validatedProposalFixture} apiBase="http://test" projectId="p" />, 'zh-TW');

    fireEvent.click(screen.getByRole('button', { name: '核准重算' }));

    // Confirm dialog appears
    const explainer = screen.getByText(/套用到正式草稿新版本並重算 E1/);
    expect(explainer.textContent).toContain('這不是正式接受方案，正式接受仍需決策密語');

    const textarea = screen.getByRole('textbox');
    fireEvent.change(textarea, { target: { value: '測試核准備註' } });

    fireEvent.click(screen.getByRole('button', { name: '確認核准重算' }));

    await waitFor(() => {
      expect(fetcher).toHaveBeenCalledWith(
        'http://test/api/v1/projects/p/ariadne/proposals/proposal-5265c929f96448249dc25df57879fe1d/approve',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ note: '測試核准備註' }),
        }),
      );
    });
  });

  it('handles 409 conflict error with "草稿已有新版本，請重新請 Ariadne 提案"', async () => {
    const fetcher = vi.fn((_url: string, options?: RequestInit) => {
      if (options?.method === 'POST') {
        return jsonResponse({ detail: 'Draft revision conflict' }, false, 409);
      }
      return jsonResponse(validatedProposalFixture);
    });
    vi.stubGlobal('fetch', fetcher);

    wrap(<ProposalCard record={validatedProposalFixture} apiBase="http://test" projectId="p" />, 'zh-TW');

    fireEvent.click(screen.getByRole('button', { name: '核准重算' }));
    fireEvent.click(screen.getByRole('button', { name: '確認核准重算' }));

    await screen.findByText('草稿已有新版本，請重新請 Ariadne 提案');
  });

  it('polls running job every 15s and stops polling when succeeded', async () => {
    vi.useFakeTimers();

    const runningRecord: ProposalRecord = {
      ...validatedProposalFixture,
      status: 'APPROVED',
      job: {
        id: 'job-123',
        status: 'RUNNING',
        analyses: ['E1', 'UTCI'],
        created_at: new Date(Date.now() - 30000).toISOString(),
        started_at: new Date(Date.now() - 30000).toISOString(),
      },
    };

    const succeededRecord: ProposalRecord = {
      ...rerunProposalFixture,
      job: {
        ...rerunProposalFixture.job!,
        status: 'SUCCEEDED',
      },
    };

    let fetchCount = 0;
    const fetcher = vi.fn(() => {
      fetchCount += 1;
      return jsonResponse(fetchCount >= 2 ? succeededRecord : runningRecord);
    });
    vi.stubGlobal('fetch', fetcher);

    wrap(<ProposalCard record={runningRecord} apiBase="http://test" projectId="p" />, 'zh-TW');

    expect(screen.getByText(/重算進行中（約 10 分鐘）/)).toBeTruthy();

    // Advance 15s -> triggers poll 1
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);

    // Advance another 15s -> triggers poll 2 (succeeded)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);

    // After success, advance 30s more -> no more fetch calls
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('displays comparison table with 3 decimal precision for winter mean, signs, colors, and DATA_GAP', () => {
    wrap(<ProposalCard record={rerunProposalFixture} apiBase="http://test" projectId="p" />, 'zh-TW');

    expect(screen.getByText('前後指標對照')).toBeTruthy();
    expect(screen.getByText('中庭冬至平均日照')).toBeTruthy();

    // Courtyard winter mean: 0.108 -> 0.109, delta +0.001 小時（幾乎無變化）
    expect(screen.getByText(/0.108 小時/)).toBeTruthy();
    expect(screen.getByText(/0.109 小時/)).toBeTruthy();
    const deltaCell = screen.getByText(/\+0.001 小時（幾乎無變化）/);
    expect(deltaCell).toBeTruthy();
    expect(deltaCell.className).toContain('proposal-card__delta--improvement');

    // Switch round button
    expect(screen.getByRole('button', { name: '看重算後的新判讀' })).toBeTruthy();
  });

  it('displays DATA_GAP row cleanly in comparison table', () => {
    wrap(<ProposalCard record={validatedProposalFixture} apiBase="http://test" projectId="p" />, 'zh-TW');

    expect(screen.getAllByText('資料缺口').length).toBeGreaterThan(0);
  });

  it('never renders unlocalized raw status codes in Chinese and English', () => {
    // Chinese render
    const { container: zhContainer } = wrap(<ProposalCard record={validatedProposalFixture} apiBase="http://test" projectId="p" />, 'zh-TW');
    const zhText = zhContainer.textContent || '';
    expect(zhText).not.toMatch(/\bVALIDATED\b/);
    expect(zhText).not.toMatch(/\bDRY_RUN_FAILED\b/);
    expect(zhText).not.toMatch(/\bOUTCOME_UNKNOWN\b/);
    expect(zhText).not.toMatch(/\bREMOVE_TOP_FLOOR\b/);
    expect(zhText).not.toMatch(/\bPLANTING_NOTE\b/);

    // English render
    cleanup();
    const { container: enContainer } = wrap(<ProposalCard record={validatedProposalFixture} apiBase="http://test" projectId="p" />, 'en');
    const enText = enContainer.textContent || '';
    expect(enText).not.toMatch(/\bVALIDATED\b/);
    expect(enText).not.toMatch(/\bDRY_RUN_FAILED\b/);
    expect(enText).not.toMatch(/\bOUTCOME_UNKNOWN\b/);
    expect(enText).not.toMatch(/\bREMOVE_TOP_FLOOR\b/);
    expect(enText).not.toMatch(/\bPLANTING_NOTE\b/);
  });
});

describe('JudgementPanel Entry Button for Ariadne Proposals', () => {
  it('renders "請 Ariadne 提出修正方案" on J-CLIMATE and J-COMPARE validated cards, but NOT on J-SITE', async () => {
    const fetcher = vi.fn((url: string) => {
      if (url.includes('/ariadne/proposals')) {
        return jsonResponse({ proposals: [] });
      }
      if (url.includes('/ariadne/dialogue')) {
        return jsonResponse({ events: [] });
      }
      return jsonResponse({ cards: [baseJudgementRecord], usage: { calls: 2, limit: 30 } });
    });
    vi.stubGlobal('fetch', fetcher);

    // 1. J-CLIMATE shows button
    const { unmount: unmount1 } = wrap(
      <JudgementPanel apiBase="http://test" projectId="p" skillId="J-CLIMATE" />,
      'zh-TW',
    );
    await screen.findByRole('button', { name: '請 Ariadne 提出修正方案' });
    unmount1();

    // 2. J-COMPARE shows button
    const { unmount: unmount2 } = wrap(
      <JudgementPanel apiBase="http://test" projectId="p" skillId="J-COMPARE" />,
      'zh-TW',
    );
    await screen.findByRole('button', { name: '請 Ariadne 提出修正方案' });
    unmount2();

    // 3. J-SITE does NOT show button
    wrap(<JudgementPanel apiBase="http://test" projectId="p" skillId="J-SITE" />, 'zh-TW');
    await screen.findByRole('button', { name: '重新判讀' });
    expect(screen.queryByRole('button', { name: '請 Ariadne 提出修正方案' })).toBeNull();
  });
});


describe('Ariadne text humanising', () => {
  it('replaces metric, response, stance ids and status words in both languages', () => {
    const raw = '判讀卡觀察 `e1.harbour.courtyard.winter.mean_h` 與設計者回應 `jr-e0d38f020d66465a93be7597534439ff`、立場 `seed-season_priority`；GFA 下限 ASSUMED。';
    const zh = humanizeAriadneText(raw, 'zh-TW');
    expect(zh).not.toMatch(/`|jr-|seed-|e1\.|ASSUMED/);
    expect(zh).toContain('你先前的回應');
    expect(zh).toContain('你的設計立場（季節優先）');
    expect(zh).toContain('假設值');
    const en = humanizeAriadneText(raw, 'en');
    expect(en).not.toMatch(/`|jr-|seed-|e1\.|ASSUMED/);
  });
});


describe('Solar warning variants', () => {
  it('names the local sun pocket when only part of the south edge is lowered', () => {
    const record: ProposalRecord = {...validatedProposalFixture, dry_run: {...validatedProposalFixture.dry_run!, solar_access_check: {warning: true, local_only: true, claims_courtyard_winter_sun: true, courtyards: [{courtyard_id: 'courtyard-0', south_height_after_m: 18, h_north_edge_m: 12.97, reaches_north_edge: false, local_sun_pockets: [{building_id: 'new-5', height_after_m: 11, frontage_m: 24.3}]}]}}};
    wrap(<ProposalCard record={record} apiBase="http://test" projectId="p" />, 'zh-TW');
    expect(screen.getByText(/只會在 new-5 後方形成約 24 公尺寬的局部日照帶/)).toBeTruthy();
  });
});


describe('Failed recalculation', () => {
  it('offers a manual rerun and posts to the rerun endpoint', async () => {
    const failedJob = {...validatedProposalFixture, status: 'APPROVED', approval: {draft_revision: 3}, job: {id: 'job-1', status: 'FAILED', analyses: ['E1'], errors: ['CalledProcessError: octree stale'], started_at: '2026-10-17T17:02:55Z', ended_at: '2026-10-17T17:12:51Z', outputs: []}, comparison: null} as unknown as ProposalRecord;
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({...failedJob, job: {...failedJob.job, id: 'job-2', status: 'PENDING', errors: []}}), {status: 200}));
    vi.stubGlobal('fetch', fetchMock);
    wrap(<ProposalCard record={failedJob} apiBase="http://test" projectId="p" />, 'zh-TW');
    expect(screen.getByText(/系統不會自動重試/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', {name: '重新執行重算'}));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toMatch(/\/proposals\/.+\/rerun$/);
    vi.unstubAllGlobals();
  });
});


describe('Proposal request without a formal draft', () => {
  it('tells the designer to open the harbour formal draft first', async () => {
    const fetcher = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/ariadne/proposals') && init?.method === 'POST') {
        return Promise.resolve(new Response(JSON.stringify({detail: 'R-PROPOSE currently requires the harbour formal draft'}), {status: 422}));
      }
      if (url.includes('/ariadne/proposals')) return jsonResponse({ proposals: [] });
      if (url.includes('/ariadne/dialogue')) return jsonResponse({ events: [] });
      return jsonResponse({ cards: [baseJudgementRecord], usage: { calls: 2, limit: 30 } });
    });
    vi.stubGlobal('fetch', fetcher);
    wrap(<JudgementPanel apiBase="http://test" projectId="p" skillId="J-CLIMATE" />, 'zh-TW');
    fireEvent.click(await screen.findByRole('button', { name: '請 Ariadne 提出修正方案' }));
    expect(await screen.findByText(/請先到「細修」頁開啟港埠正式草稿/)).toBeTruthy();
    vi.unstubAllGlobals();
  });
});
