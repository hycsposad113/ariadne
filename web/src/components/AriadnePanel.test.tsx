// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
beforeEach(() => localStorage.setItem('urban-design-language', 'en'));
import { AriadnePanel, AriadneWorkspacePanel } from './AriadnePanel';
import { I18nProvider } from '../i18n';

describe('AriadnePanel', () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  const status = {
    mode: 'OFFLINE' as const,
    blockReason: 'Live AI is disabled by the server.',
  };

  it('renders the offline badge, current conversation, and decisions needed', () => {
    render(
      <AriadnePanel
        messages={[
          { id: 'message-1', role: 'assistant', content: 'Evidence is available.', evidenceRefs: ['card-site'], providerStatus: 'NON_AI: DETERMINISTIC_TEMPLATE' },
        ]}
        decisionsNeeded={[{ id: 'workspace-draft', title: 'Review workspace draft', sourceId: 'workspace-test' }]}
        status={status}
        onSendMessage={vi.fn()}
        onEvidenceClick={vi.fn()}
      />,
    );

    expect(screen.getByTestId('ariadne-status').textContent).toContain('Offline');
    expect(screen.getByText('Evidence is available.')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Decisions needed' })).toBeTruthy();
    expect(screen.getByText('Review workspace draft')).toBeTruthy();
  });

  it('emits a map-highlight event when an evidence citation is clicked', () => {
    const onEvidenceClick = vi.fn();
    render(
      <AriadnePanel
        messages={[
          { id: 'message-1', role: 'assistant', content: 'See the source.', evidenceRefs: ['card-site'], providerStatus: 'NON_AI: DETERMINISTIC_TEMPLATE' },
        ]}
        decisionsNeeded={[]}
        status={status}
        onSendMessage={vi.fn()}
        onEvidenceClick={onEvidenceClick}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Evidence card card-site' }));
    expect(onEvidenceClick).toHaveBeenCalledWith('card-site', 'unknown');
  });

  it('sends a designer question through the supplied handler', () => {
    const onSendMessage = vi.fn();
    render(
      <AriadnePanel
        messages={[]}
        decisionsNeeded={[]}
        status={status}
        onSendMessage={onSendMessage}
        onEvidenceClick={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole('textbox', { name: 'Ask Ariadne' }), { target: { value: 'What is still unknown?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(onSendMessage).toHaveBeenCalledWith('What is still unknown?');
  });

  it('submits with Enter and leaves Shift+Enter available for a newline', () => {
    const onSendMessage = vi.fn();
    render(
      <AriadnePanel
        messages={[]}
        decisionsNeeded={[]}
        status={status}
        onSendMessage={onSendMessage}
        onEvidenceClick={vi.fn()}
      />,
    );

    const input = screen.getByRole('textbox', { name: 'Ask Ariadne' });
    fireEvent.change(input, { target: { value: 'What is still unknown?' } });
    expect(fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })).toBe(false);
    expect(onSendMessage).toHaveBeenCalledWith('What is still unknown?');

    const onNewlineSend = vi.fn();
    cleanup();
    render(
      <AriadnePanel
        messages={[]}
        decisionsNeeded={[]}
        status={status}
        onSendMessage={onNewlineSend}
        onEvidenceClick={vi.fn()}
      />,
    );
    const multilineInput = screen.getByRole('textbox', { name: 'Ask Ariadne' });
    fireEvent.change(multilineInput, { target: { value: 'First line' } });
    expect(fireEvent.keyDown(multilineInput, { key: 'Enter', code: 'Enter', shiftKey: true })).toBe(true);
    fireEvent.change(multilineInput, { target: { value: 'First line\nSecond line' } });
    expect((multilineInput as HTMLTextAreaElement).value).toBe('First line\nSecond line');
    expect(onNewlineSend).not.toHaveBeenCalled();
  });

  it('does not submit Enter while an IME composition is active', () => {
    const onSendMessage = vi.fn();
    render(
      <AriadnePanel
        messages={[]}
        decisionsNeeded={[]}
        status={status}
        onSendMessage={onSendMessage}
        onEvidenceClick={vi.fn()}
      />,
    );

    const input = screen.getByRole('textbox', { name: 'Ask Ariadne' });
    fireEvent.change(input, { target: { value: '基地面積' } });
    expect(fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', isComposing: true })).toBe(true);
    expect(onSendMessage).not.toHaveBeenCalled();
    expect(fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 229 })).toBe(true);
    expect(onSendMessage).not.toHaveBeenCalled();
  });

  it('groups seven decision sources under one item and expands their source list', () => {
    const onEvidenceClick = vi.fn();
    const sourceIds = Array.from({ length: 7 }, (_item, index) => `card-legacy-${index + 1}`);
    render(
      <AriadnePanel
        messages={[]}
        decisionsNeeded={[{
          id: 'legacy-status-group',
          title: 'Confirm legacy status labels for 7 evidence cards',
          sourceId: sourceIds[0],
          sourceIds,
          sourceType: 'evidence_card',
          reason: 'Review every source card.',
        }]}
        status={status}
        onSendMessage={vi.fn()}
        onEvidenceClick={onEvidenceClick}
      />,
    );

    expect(screen.getByTestId('ariadne-decisions-count').textContent).toBe('1');
    const details = screen.getByText('View 7 source cards').closest('details');
    expect(details?.open).toBe(false);
    fireEvent.click(screen.getByText('View 7 source cards'));
    expect(details?.open).toBe(true);
    expect(screen.getByRole('button', { name: 'Open source card-legacy-7' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Open source card-legacy-7' }));
    expect(onEvidenceClick).toHaveBeenCalledWith('card-legacy-7', 'evidence_card');
  });

  it('hides the decision count while the list is loading', () => {
    render(
      <AriadnePanel
        messages={[]}
        decisionsNeeded={[]}
        decisionsLoading
        status={status}
        onSendMessage={vi.fn()}
        onEvidenceClick={vi.fn()}
      />,
    );

    expect(screen.getByText('Loading decisions…')).toBeTruthy();
    expect(screen.queryByTestId('ariadne-decisions-count')).toBeNull();
  });

  it('loads persisted messages and decisions, localizes the interface, and sends through the Ariadne API', async () => {
    const onEvidenceClick = vi.fn();
    const onDecisionsNeededChange = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/ariadne/status')) {
        return new Response(JSON.stringify({ mode: 'OFFLINE', block_reason: 'Live AI is disabled.', block_reason_code: 'BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED' }));
      }
      if (url.endsWith('/ariadne/decisions-needed')) {
        return new Response(JSON.stringify({ items: [{ id: 'decision-1', title: 'Confirm the workspace', source_id: 'workspace-1', source_type: 'workspace' }] }));
      }
      if (url.endsWith('/ariadne/messages') && init?.method === 'POST') {
        return new Response(JSON.stringify({
          user_message: { id: 'user-1', role: 'user', content: 'What is known?', evidence_refs: [] },
          assistant_message: { id: 'assistant-1', role: 'assistant', content: 'The evidence is retained [card-1].', evidence_refs: ['card-1'], evidence_sources: [{ evidence_id: 'card-1', source_type: 'evidence_card' }] },
        }));
      }
      return new Response(JSON.stringify({ messages: [{ id: 'assistant-0', role: 'assistant', content: 'Existing source [card-1].', evidence_refs: ['card-1'], evidence_sources: [{ evidence_id: 'card-1', source_type: 'evidence_card' }] }] }));
    });

    render(
      <I18nProvider>
        <AriadneWorkspacePanel
          apiBase="http://fixture.test"
          projectId="project-1"
          onEvidenceClick={onEvidenceClick}
          onDecisionsNeededChange={onDecisionsNeededChange}
        />
      </I18nProvider>,
    );

    expect(await screen.findByText('Existing source [card-1].')).toBeTruthy();
    expect(await screen.findByTestId('ariadne-decisions-count')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Evidence card card-1' }));
    expect(onEvidenceClick).toHaveBeenCalledWith('card-1', 'evidence_card');
    expect(onDecisionsNeededChange).toHaveBeenCalledWith(1);
    fireEvent.change(screen.getByRole('textbox', { name: 'Ask Ariadne' }), { target: { value: 'What is known?' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }));
    expect(await screen.findByText('The evidence is retained [card-1].')).toBeTruthy();
    expect(fetchSpy).toHaveBeenCalledWith('http://fixture.test/api/v1/projects/project-1/ariadne/messages', expect.objectContaining({ method: 'POST' }));
    expect(fetchSpy).toHaveBeenCalledWith('http://fixture.test/api/v1/projects/project-1/ariadne/decisions-needed', { headers: { 'Accept-Language': 'en' } });
    expect(fetchSpy).toHaveBeenCalledWith('http://fixture.test/api/v1/projects/project-1/ariadne/messages', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ content: 'What is known?', language: 'en' }),
    }));
  });

  it('sends the selected Traditional Chinese language to the messages API', async () => {
    localStorage.setItem('urban-design-language', 'zh-TW');
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/ariadne/status')) return new Response(JSON.stringify({ mode: 'OFFLINE' }));
      if (url.endsWith('/ariadne/decisions-needed')) return new Response(JSON.stringify({ items: [] }));
      if (url.endsWith('/ariadne/messages') && init?.method === 'POST') {
        return new Response(JSON.stringify({
          user_message: { id: 'user-zh', role: 'user', content: '水域面積？', evidence_refs: [] },
          assistant_message: { id: 'assistant-zh', role: 'assistant', content: '目前沒有相符項目。', evidence_refs: [] },
        }));
      }
      return new Response(JSON.stringify({ messages: [] }));
    });

    render(
      <I18nProvider>
        <AriadneWorkspacePanel apiBase="http://fixture.test" projectId="project-zh" onEvidenceClick={vi.fn()} />
      </I18nProvider>,
    );

    const input = await screen.findByRole('textbox', { name: '詢問 Ariadne' });
    fireEvent.change(input, { target: { value: '水域面積？' } });
    fireEvent.click(screen.getByRole('button', { name: '傳送訊息' }));
    expect(await screen.findByText('目前沒有相符項目。')).toBeTruthy();
    expect(fetchSpy).toHaveBeenCalledWith('http://fixture.test/api/v1/projects/project-zh/ariadne/messages', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ content: '水域面積？', language: 'zh-TW' }),
    }));
    expect(fetchSpy).toHaveBeenCalledWith('http://fixture.test/api/v1/projects/project-zh/ariadne/decisions-needed', { headers: { 'Accept-Language': 'zh-TW' } });
  });

  it('renders OFFLINE, LIVE, BLOCKED, and OUTCOME_UNKNOWN as distinct labels', async () => {
    const cases = [
      { body: { mode: 'OFFLINE' }, label: 'Offline', state: 'offline' },
      { body: { mode: 'LIVE', provider_status: 'LIVE_AI: CONFIGURED_NOT_CALLED' }, label: 'Live AI', state: 'live' },
      {
        body: {
          mode: 'OFFLINE',
          block_reason_code: 'BLOCKED_BUDGET',
          block_reason: 'The shared weekly ModelRun budget is exhausted; no provider request was sent.',
        },
        label: 'Blocked',
        state: 'blocked',
      },
      {
        body: {
          mode: 'OFFLINE',
          provider_status: 'LIVE_AI: OUTCOME_UNKNOWN',
          block_reason: 'Provider request outcome is unknown; reconcile before retrying.',
        },
        label: 'Outcome unknown',
        state: 'outcome_unknown',
      },
    ];

    for (const item of cases) {
      cleanup();
      vi.restoreAllMocks();
      vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
        const url = String(input);
        if (url.endsWith('/ariadne/status')) return new Response(JSON.stringify(item.body));
        if (url.endsWith('/ariadne/decisions-needed')) return new Response(JSON.stringify({ items: [] }));
        return new Response(JSON.stringify({ messages: [] }));
      });
      render(
        <I18nProvider>
          <AriadneWorkspacePanel apiBase="http://fixture.test" projectId={`project-${item.state}`} onEvidenceClick={vi.fn()} />
        </I18nProvider>,
      );
      const badge = await screen.findByTestId('ariadne-status');
      expect(badge.textContent).toContain(item.label);
      expect(badge.getAttribute('data-screen-state')).toBe(item.state);
    }
  });

  it('localizes BLOCKED and OUTCOME_UNKNOWN in Traditional Chinese', async () => {
    localStorage.setItem('urban-design-language', 'zh-TW');
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/ariadne/status')) {
        return new Response(JSON.stringify({
          mode: 'OFFLINE',
          provider_status: 'LIVE_AI: OUTCOME_UNKNOWN',
          block_reason: 'Provider request outcome is unknown; reconcile before retrying.',
        }));
      }
      if (url.endsWith('/ariadne/decisions-needed')) return new Response(JSON.stringify({ items: [] }));
      return new Response(JSON.stringify({ messages: [] }));
    });

    render(
      <I18nProvider>
        <AriadneWorkspacePanel apiBase="http://fixture.test" projectId="project-zh-status" onEvidenceClick={vi.fn()} />
      </I18nProvider>,
    );

    const badge = await screen.findByTestId('ariadne-status');
    expect(badge.textContent).toContain('結果未知');
    expect(badge.getAttribute('data-screen-state')).toBe('outcome_unknown');
  });
});
