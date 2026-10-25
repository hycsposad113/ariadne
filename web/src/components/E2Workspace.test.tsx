// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { E2Workspace } from './E2Workspace';
import { I18nProvider } from '../i18n';

// Real fixture from artifacts/w8/e2-formal/harbour-vs-mixed-result.json
const HARBOUR_VS_MIXED_FIXTURE = {
  job_id: '2ffdd4a43129495c81774419354db615',
  status: 'SUCCEEDED',
  evidence_validation_status: 'validated',
  plan_id: 'artifact-e2-experiment-plan-7edb13cb3b85171ef69d6ffb',
  plan_sha256: 'sha256:7edb13cb3b85171ef69d6ffb2e390e3a63f56feb3b590924c00b8c6392ab565f',
  weather_snapshot_id: 'snapshot-e2-weather-109b15ff7c739ceb92a161a5',
  direction_summary: {
    direction_agreement_by_offset: { '-1': true, '0': true, '1': true },
    explanation: '只比較各方法內的改善（入射輻射降低）／變差方向。篩選使用天空 patch 遮擋；驗證使用含反射的 Radiance 係數。方向一致不代表絕對值可互換。',
    methods: {
      honeybee_radiance: {
        directions: { '-1': 'DECREASED', '0': 'DECREASED', '1': 'DECREASED' },
        sensitivity_reversed: false,
      },
      ladybug_radiance: {
        directions: { '-1': 'DECREASED', '0': 'DECREASED', '1': 'DECREASED' },
        sensitivity_reversed: false,
      },
    },
    sensitivity_reversed: false,
  },
  limitations: [
    '累積入射輻射不代表熱舒適、耗能或材料蓄熱。',
    '公共開放空間為幾何分析範圍，不代表 legal right of way。',
    'Minute=0 視為 hour_end 是 PD-08 專案假設，非供應商證據。',
    'Ladybug 遮擋篩選不含建築表面多次反射；Honeybee 驗證採獨立反射 recipe。',
  ],
  comparisons: {
    ladybug_radiance: {
      '-1': {
        baseline_kwh_m2: 401.4637981639906,
        modified_kwh_m2: 357.95046117568336,
        delta_kwh_m2: -43.51333698830723,
        direction: 'DECREASED',
      },
      '0': {
        baseline_kwh_m2: 403.96414751269805,
        modified_kwh_m2: 359.9703478794829,
        delta_kwh_m2: -43.99379963321516,
        direction: 'DECREASED',
      },
      '1': {
        baseline_kwh_m2: 401.8152341029481,
        modified_kwh_m2: 358.3308918294719,
        delta_kwh_m2: -43.484342273476215,
        direction: 'DECREASED',
      },
    },
    honeybee_radiance: {
      '-1': {
        baseline_kwh_m2: 409.0521834584629,
        modified_kwh_m2: 372.11952256734025,
        delta_kwh_m2: -36.93266089112262,
        direction: 'DECREASED',
      },
      '0': {
        baseline_kwh_m2: 411.45545285251364,
        modified_kwh_m2: 374.1184674031733,
        delta_kwh_m2: -37.33698544934032,
        direction: 'DECREASED',
      },
      '1': {
        baseline_kwh_m2: 407.33061981951244,
        modified_kwh_m2: 370.3496314405478,
        delta_kwh_m2: -36.98098837896464,
        direction: 'DECREASED',
      },
    },
  },
};

const MOCK_PINS: Record<string, any> = {
  'formal-dict-3da03eb0172d-common-mixed-98854aff5f7b': {
    scenario_id: 'formal-dict-3da03eb0172d-common-mixed-98854aff5f7b',
    revision: 2,
    geometry_artifact_id: 'artifact-formal-dict-3da03eb0172d-common-mixed-98854aff5f7b',
    geometry_sha256: `sha256:${'1'.repeat(64)}`,
    environment_sha256: `sha256:${'2'.repeat(64)}`,
  },
  'formal-fabric-harbour-grain-88445febe1b6': {
    scenario_id: 'formal-fabric-harbour-grain-88445febe1b6',
    revision: 1,
    geometry_artifact_id: 'artifact-formal-fabric-harbour-grain-88445febe1b6',
    geometry_sha256: `sha256:${'3'.repeat(64)}`,
    environment_sha256: `sha256:${'4'.repeat(64)}`,
  },
};

describe('E2Workspace Component', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request) => {
      const urlStr = String(url);
      if (urlStr.includes('/weather/snapshots')) {
        return {
          ok: true,
          json: async () => [
            {
              id: 'snapshot-e2-weather-109b15ff7c739ceb92a161a5',
              snapshot_id: 'snapshot-e2-weather-109b15ff7c739ceb92a161a5',
              version: 'weather-derived-method-v1',
              payload_digest: `sha256:${'a'.repeat(64)}`,
              status: 'APPROVED',
              decision_id: 'decision-a5a80c573caa46b79b931d6efa044296',
              decision_target_type: 'DatasetSnapshot',
            },
          ],
        } as Response;
      }
      if (urlStr.includes('/plans')) {
        return {
          ok: true,
          json: async () => [
            {
              id: 'artifact-e2-experiment-plan-7edb13cb3b85171ef69d6ffb',
              plan_artifact_id: 'artifact-e2-experiment-plan-7edb13cb3b85171ef69d6ffb',
              sha256: `sha256:${'b'.repeat(64)}`,
              version: '1',
              status: 'APPROVED',
              decision_id: 'decision-5f52c0c2d7cd43bdbd86fc91a003cc5f',
              baseline: MOCK_PINS['formal-dict-3da03eb0172d-common-mixed-98854aff5f7b'],
              modified: MOCK_PINS['formal-fabric-harbour-grain-88445febe1b6'],
            },
          ],
        } as Response;
      }
      if (urlStr.includes('/jobs')) {
        return {
          ok: true,
          json: async () => [
            {
              id: '2ffdd4a43129495c81774419354db615',
              job_id: '2ffdd4a43129495c81774419354db615',
              status: 'READY',
              created_at: '2026-10-16T17:19:00Z',
              completed_at: '2026-10-16T17:32:27Z',
              updated_at: '2026-10-16T17:32:27Z',
              plan_id: 'artifact-e2-experiment-plan-7edb13cb3b85171ef69d6ffb',
              baseline_scenario_id: 'formal-dict-3da03eb0172d-common-mixed-98854aff5f7b',
              modified_scenario_id: 'formal-fabric-harbour-grain-88445febe1b6',
              validated: true,
            },
          ],
        } as Response;
      }
      if (urlStr.includes('/pin')) {
        for (const [id, pin] of Object.entries(MOCK_PINS)) {
          if (urlStr.includes(encodeURIComponent(id))) {
            return { ok: true, json: async () => pin } as Response;
          }
        }
        return { ok: true, json: async () => MOCK_PINS['formal-dict-3da03eb0172d-common-mixed-98854aff5f7b'] } as Response;
      }
      if (urlStr.includes('/readiness')) {
        return {
          ok: true,
          json: async () => ({
            dispatch_allowed: true,
            checks: [
              { name: 'Weather snapshot bound approval', status: 'PASS', passed: true },
              { name: 'Radiance runtime qualification', status: 'PASS', passed: true },
              { name: 'Scenario geometry & common overlap', status: 'PASS', passed: true },
            ],
          }),
        } as Response;
      }
      if (urlStr.includes('/results/')) {
        return {
          ok: true,
          json: async () => HARBOUR_VS_MIXED_FIXTURE,
        } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    }));
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('renders all 6 steps and derives status cleanly', async () => {
    render(
      <I18nProvider language="zh-TW">
        <E2Workspace apiBase="http://127.0.0.1:8795" />
      </I18nProvider>
    );

    // Check step titles
    expect(screen.getByText(/① 天氣快照/)).toBeTruthy();
    expect(screen.getByText(/② 方案（基準／比較）/)).toBeTruthy();
    expect(screen.getByText(/③ 實驗計畫/)).toBeTruthy();
    expect(screen.getByText(/④ 準備檢查/)).toBeTruthy();
    expect(screen.getByText(/⑤ 送出計算/)).toBeTruthy();
    expect(screen.getByText(/⑥ 結果與比較/)).toBeTruthy();

    // Check status badges derived
    await waitFor(() => {
      // Step 1: Weather snapshot is APPROVED -> COMPLETED ("已完成")
      // Step 2: Pins loaded -> COMPLETED ("已完成")
      // Step 3: Approved plan -> COMPLETED ("已完成")
      // Step 4: dispatch_allowed: true -> COMPLETED ("已完成")
      const completedBadges = screen.getAllByText('已完成');
      expect(completedBadges.length).toBeGreaterThanOrEqual(3);
    });
  });

  it('opens HumanDecisionDialog for proposed weather snapshot without prefilling secret, clears on submit', async () => {
    // Return a proposed weather snapshot
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request) => {
      const urlStr = String(url);
      if (urlStr.includes('/weather/snapshots')) {
        return {
          ok: true,
          json: async () => [
            {
              id: 'snapshot-e2-weather-prop1',
              snapshot_id: 'snapshot-e2-weather-prop1',
              version: 'weather-derived-method-v1',
              payload_digest: `sha256:${'9'.repeat(64)}`,
              status: 'PROPOSED',
              decision_target_type: 'DatasetSnapshot',
            },
          ],
        } as Response;
      }
      if (urlStr.includes('/decisions')) {
        return {
          ok: true,
          json: async () => ({ id: 'decision-new-1', status: 'approved' }),
        } as Response;
      }
      return { ok: true, json: async () => [] } as Response;
    }));

    render(
      <I18nProvider language="zh-TW">
        <E2Workspace apiBase="http://127.0.0.1:8795" />
      </I18nProvider>
    );

    // Look for the "批准（需你的決策密語）" button
    const approveBtn = await screen.findByRole('button', { name: /批准（需你的決策密語）/ });
    expect(approveBtn).toBeTruthy();

    // Click it to open dialog
    fireEvent.click(approveBtn);

    // Verify dialog opened
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeTruthy();

    // Verify decision key input is empty
    const keyInput = screen.getByLabelText(/決策金鑰|Decision key/i) as HTMLInputElement;
    expect(keyInput.value).toBe('');

    // Enter reason and secret
    const reasonInput = screen.getByLabelText(/理由|Reason/i) as HTMLInputElement;
    fireEvent.change(reasonInput, { target: { value: 'Approved candidate01 weather series' } });
    fireEvent.change(keyInput, { target: { value: 'founder-secret-key-123' } });

    // Submit
    const confirmBtn = screen.getByRole('button', { name: /確認決策|Confirm decision/i });
    fireEvent.click(confirmBtn);

    // Wait for submission
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining('/decisions'),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"decision_key":"founder-secret-key-123"'),
        })
      );
    });

    // Verify key was NOT stored in storage
    expect(sessionStorage.getItem('urban-design-decision-key')).toBeNull();
    expect(localStorage.getItem('urban-design-decision-key')).toBeNull();
  });

  it('generates idempotency key on simulate and disables button on outcome unknown', async () => {
    // Return outcome unknown on simulate
    vi.stubGlobal('fetch', vi.fn(async (url: string | URL | Request) => {
      const urlStr = String(url);
      if (urlStr.includes('/weather/snapshots')) {
        return {
          ok: true,
          json: async () => [
            {
              id: 'snap-1',
              snapshot_id: 'snap-1',
              version: 'v1',
              payload_digest: `sha256:${'a'.repeat(64)}`,
              status: 'APPROVED',
              decision_target_type: 'DatasetSnapshot',
            },
          ],
        } as Response;
      }
      if (urlStr.includes('/plans')) {
        return {
          ok: true,
          json: async () => [
            {
              id: 'plan-1',
              plan_artifact_id: 'plan-1',
              sha256: `sha256:${'b'.repeat(64)}`,
              version: '1',
              status: 'APPROVED',
              baseline: MOCK_PINS['formal-dict-3da03eb0172d-common-mixed-98854aff5f7b'],
              modified: MOCK_PINS['formal-fabric-harbour-grain-88445febe1b6'],
            },
          ],
        } as Response;
      }
      if (urlStr.includes('/readiness')) {
        return {
          ok: true,
          json: async () => ({ dispatch_allowed: true, checks: [] }),
        } as Response;
      }
      if (urlStr.includes('/pin')) {
        return { ok: true, json: async () => MOCK_PINS['formal-dict-3da03eb0172d-common-mixed-98854aff5f7b'] } as Response;
      }
      if (urlStr.includes('/simulate')) {
        // Return 409 OUTCOME_UNKNOWN
        return {
          ok: false,
          status: 409,
          json: async () => ({
            detail: { status: 'BLOCKED', reason: 'OUTCOME_UNKNOWN' },
          }),
        } as Response;
      }
      return { ok: true, json: async () => [] } as Response;
    }));

    render(
      <I18nProvider language="zh-TW">
        <E2Workspace apiBase="http://127.0.0.1:8795" />
      </I18nProvider>
    );

    const simulateBtn = await screen.findByRole('button', { name: /產生冪等金鑰並送出計算/ });
    expect(simulateBtn).toBeTruthy();

    // Button should become enabled after readiness checks pass
    await waitFor(() => {
      expect((simulateBtn as HTMLButtonElement).disabled).toBe(false);
    });

    // Re-query the button to ensure fresh reference and click
    const activeBtn = screen.getByRole('button', { name: /產生冪等金鑰並送出計算/ });
    fireEvent.click(activeBtn);

    // Verify error banner and button disabled
    await waitFor(() => {
      expect(screen.getAllByText(/結果未知，需管理者對帳，不可重送/).length).toBeGreaterThan(0);
      expect((activeBtn as HTMLButtonElement).disabled).toBe(true);
    });

    // Verify idempotency key was generated and displayed
    expect(screen.getByText(/founder-e2-/)).toBeTruthy();
  });

  it('renders real numbers fixture table, direction agreement, and warning notice', async () => {
    render(
      <I18nProvider language="zh-TW">
        <E2Workspace apiBase="http://127.0.0.1:8795" />
      </I18nProvider>
    );

    // Load the historical job result
    const loadResultBtn = await screen.findByRole('button', { name: /查看完整結果表/ });
    fireEvent.click(loadResultBtn);

    // Verify Ladybug numbers from fixture
    await waitFor(() => {
      // 403.964148 kWh/m²
      expect(screen.getByText(/403\.96/)).toBeTruthy();
      // 359.970348 kWh/m²
      expect(screen.getByText(/359\.97/)).toBeTruthy();
      // -43.993800 kWh/m²
      expect(screen.getByText(/-43\.99/)).toBeTruthy();
    });

    // Verify Honeybee numbers from fixture (411.455453, 374.118467, -37.336985)
    expect(screen.getByText(/411\.46 /)).toBeTruthy();
    expect(screen.getByText(/374\.12 /)).toBeTruthy();
    expect(screen.getByText(/-37\.34 /)).toBeTruthy();

    // Verify permanent warning notice
    expect(
      screen.getByText(/入射輻射降低不等於熱舒適改善；兩方法絕對值不可混用/)
    ).toBeTruthy();

    // Verify direction summary explanation from fixture
    expect(screen.getByText(/只比較各方法內的改善/)).toBeTruthy();
  });

  it('bilingual scanning: displays localized labels without unmapped status codes', async () => {
    const { rerender } = render(
      <I18nProvider language="zh-TW">
        <E2Workspace apiBase="http://127.0.0.1:8795" />
      </I18nProvider>
    );

    await screen.findByText(/① 天氣快照/);

    // In zh-TW: no raw 'NOT_STARTED', 'WAITING_DECISION', 'OUTCOME_UNKNOWN'
    const zhHtml = document.body.innerHTML;
    expect(zhHtml).not.toContain('>NOT_STARTED<');
    expect(zhHtml).not.toContain('>WAITING_DECISION<');
    expect(zhHtml).not.toContain('>OUTCOME_UNKNOWN<');

    // Switch to English
    rerender(
      <I18nProvider language="en">
        <E2Workspace apiBase="http://127.0.0.1:8795" />
      </I18nProvider>
    );

    await screen.findByText(/① Weather Snapshot/);
    const enHtml = document.body.innerHTML;
    expect(enHtml).not.toContain('>NOT_STARTED<');
    expect(enHtml).not.toContain('>WAITING_DECISION<');
    expect(enHtml).not.toContain('>OUTCOME_UNKNOWN<');
    expect(screen.getByText(/Important notice:/)).toBeTruthy();
  });
});


describe('E2 single dispatch per plan', () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
  it('keeps submit disabled and never calls simulate when the plan already has a job', async () => {
    const fetcher = vi.fn(async (url: string | URL | Request) => {
      const u = String(url);
      if (u.includes('/weather/snapshots')) return { ok: true, json: async () => [{ id: 'snap-1', snapshot_id: 'snap-1', version: 'v1', payload_digest: `sha256:${'a'.repeat(64)}`, status: 'APPROVED', decision_target_type: 'DatasetSnapshot' }] } as Response;
      if (u.includes('/e2/jobs')) return { ok: true, json: async () => [{ id: 'job-1', job_id: 'job-1', status: 'READY', created_at: '2026-10-17T00:00:00Z', updated_at: '2026-10-17T00:14:00Z', plan_id: 'plan-1', validated: true }] } as Response;
      if (u.includes('/plans')) return { ok: true, json: async () => [{ id: 'plan-1', plan_artifact_id: 'plan-1', sha256: `sha256:${'b'.repeat(64)}`, version: '1', status: 'APPROVED', baseline: MOCK_PINS['formal-dict-3da03eb0172d-common-mixed-98854aff5f7b'], modified: MOCK_PINS['formal-fabric-harbour-grain-88445febe1b6'] }] } as Response;
      if (u.includes('/readiness')) return { ok: true, json: async () => ({ dispatch_allowed: true, checks: [] }) } as Response;
      if (u.includes('/pin')) return { ok: true, json: async () => MOCK_PINS['formal-dict-3da03eb0172d-common-mixed-98854aff5f7b'] } as Response;
      return { ok: true, json: async () => [] } as Response;
    });
    vi.stubGlobal('fetch', fetcher);
    render(<I18nProvider language="zh-TW"><E2Workspace apiBase="http://127.0.0.1:8795" /></I18nProvider>);
    const button = await screen.findByRole('button', { name: /產生冪等金鑰並送出計算/ });
    await waitFor(() => expect(screen.getAllByText(/這份實驗計畫已經派送過/).length).toBeGreaterThan(0));
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(fetcher.mock.calls.some(([u]) => String(u).includes('/simulate'))).toBe(false);
  });
});
