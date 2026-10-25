/// <reference types="node" />
// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { I18nProvider } from '../i18n';
import { DesignDialogueTimeline } from './DesignDialogueTimeline';
import type { DesignDialogueData, DialogueEvent } from '../utils/proposalUtils';

function wrap(node: React.ReactNode, language: 'en' | 'zh-TW' = 'zh-TW') {
  return render(<I18nProvider language={language}>{node}</I18nProvider>);
}

function jsonResponse(data: unknown, ok = true) {
  return Promise.resolve({
    ok,
    status: 200,
    json: async () => data,
  } as Response);
}

const dialogueFixture = JSON.parse(
  readFileSync(
    `${process.cwd()}/../artifacts/w8/rehearsal/p3-proposals/samples/dialogue.json`,
    'utf8',
  ),
) as DesignDialogueData;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('DesignDialogueTimeline', () => {
  it('loads and orders events chronologically, rendering correct labels for each kind', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse(dialogueFixture)));

    const onSelectJudgement = vi.fn();
    const onSelectProposal = vi.fn();

    wrap(
      <DesignDialogueTimeline
        apiBase="http://test"
        projectId="rotterdam-m4h-pilot-project"
        onSelectJudgement={onSelectJudgement}
        onSelectProposal={onSelectProposal}
      />,
      'zh-TW',
    );

    // Summary button
    const summary = screen.getByText('設計對話紀錄');
    fireEvent.click(summary);

    // Wait for events to load and render
    await screen.findAllByText('氣候判讀第 1 輪');
    expect(screen.getAllByText('方案比較判讀第 3 輪').length).toBeGreaterThan(0);
    expect(screen.getByText('氣候判讀第 4 輪（草稿第 2 版）')).toBeTruthy();
    expect(screen.queryByText(/^judgement-[0-9a-f]+$/)).toBeNull();
    expect(screen.getByText('設計者回應（質疑）')).toBeTruthy();
    expect(screen.getByText(/降低南側量體我可以接受，但不希望把港埠長向街牆整段打斷/)).toBeTruthy();

    expect(screen.getAllByText('Ariadne 修正提案').length).toBeGreaterThan(0);
    expect(screen.getByText('核准重算')).toBeTruthy();
    expect(screen.getByText('非正式決策')).toBeTruthy();
    expect(screen.getByText(/重算執行（E1, UTCI）/)).toBeTruthy();

    // Click judgement headline
    const judgementBtn = screen.getByRole('button', {
      name: /我認為港埠方案的住戶中庭冬季日照是需要優先修正的實質弱點/,
    });
    fireEvent.click(judgementBtn);
    expect(onSelectJudgement).toHaveBeenCalled();

    // Click proposal summary
    const proposalBtn = screen.getByRole('button', {
      name: /我提議先局部降低 courtyard-0 南側相鄰的兩棟量體/,
    });
    fireEvent.click(proposalBtn);
    expect(onSelectProposal).toHaveBeenCalled();
  });

  it('renders correctly in English without unlocalized status codes', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse(dialogueFixture)));

    const { container } = wrap(
      <DesignDialogueTimeline
        apiBase="http://test"
        projectId="rotterdam-m4h-pilot-project"
      />,
      'en',
    );

    fireEvent.click(screen.getByText('Design dialogue history'));
    await screen.findByText('Designer Response (Contest)');
    expect(screen.getByText('Recalculation Approved')).toBeTruthy();
    expect(screen.getByText('Informal decision')).toBeTruthy();

    const text = container.textContent || '';
    expect(text).not.toMatch(/\bVALIDATED\b/);
    expect(text).not.toMatch(/\bDRY_RUN_FAILED\b/);
    expect(text).not.toMatch(/\bOUTCOME_UNKNOWN\b/);
  });

  it('labels agent responses separately from designer responses', async () => {
    const agentEvent: DialogueEvent = {
      kind: 'agent_response',
      id: 'agent-response-1',
      created_at: '2026-10-17T00:00:01.1+00:00',
      text: 'Please check the evidence coverage.',
      response_kind: 'supplement',
      language: 'en',
      actor_kind: 'AGENT',
    };
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({
      ...dialogueFixture,
      events: [...dialogueFixture.events, agentEvent],
    })));

    wrap(
      <DesignDialogueTimeline
        apiBase="http://test"
        projectId="rotterdam-m4h-pilot-project"
      />,
      'en',
    );

    fireEvent.click(screen.getByText('Design dialogue history'));
    expect(await screen.findByText('AI Agent Response (Supplement)')).toBeTruthy();
    expect(screen.getByText('Please check the evidence coverage.').getAttribute('lang')).toBe('en');
    expect(screen.queryByText('Designer Response (Supplement)')).toBeNull();
  });

  it('does not show another language\'s judgement headline in the English timeline', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse(dialogueFixture)));
    wrap(<DesignDialogueTimeline apiBase="http://test" projectId="rotterdam-m4h-pilot-project" />, 'en');
    fireEvent.click(screen.getByText(/design dialogue/i));
    await screen.findAllByText(/Climate judgement, round 1/);
    expect(screen.queryByText(/我認為港埠方案的住戶中庭冬季日照/)).toBeNull();
    expect(screen.getAllByText('(This round was written in Chinese — open it to read)').length).toBeGreaterThan(0);
  });
});
