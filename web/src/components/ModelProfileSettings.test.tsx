// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ModelProfileSettings } from './ModelProfileSettings';

const profileResponse = {
  active_profile_id: 'codex-cli',
  weekly_call_limit: 200,
  weekly_calls_used: 0,
  live_dispatch_enabled: false,
  dispatch_block_reason: 'BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE',
  profiles: [
    {
      id: 'openai-gpt-4o',
      provider: 'openai',
      model: 'gpt-4o',
      status: 'MISSING_KEY',
      enabled: true,
      active: false,
      supports_json_schema: true,
      egress: 'cloud',
    },
    {
      id: 'hermes-urban-critic',
      provider: 'hermes',
      model: '',
      status: 'DISABLED',
      enabled: false,
      active: false,
      supports_json_schema: false,
      egress: 'hermes',
    },
    {
      id: 'codex-cli',
      provider: 'codex-cli',
      model: 'gpt-6-luna',
      status: 'AVAILABLE',
      status_detail: 'Configured for structured output.',
      enabled: true,
      active: true,
      supports_json_schema: true,
      egress: 'cloud',
    },
  ],
};

describe('ModelProfileSettings', () => {
  it('shows provider status without exposing key fields and saves a selected profile', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => profileResponse })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ...profileResponse, active_profile_id: 'openai-gpt-4o' }),
      });
    vi.stubGlobal('fetch', fetchMock);

    render(<ModelProfileSettings apiBase="http://127.0.0.1:8789" />);

    expect(await screen.findByText('Missing Keychain key')).toBeInTheDocument();
    expect(screen.getByText('Disabled')).toBeInTheDocument();
    expect(screen.getByText('Ariadne currently uses: codex-cli')).toBeInTheDocument();
    expect(screen.getByText(/Preferences only; model calls/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/key|密鑰/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Active profile'), { target: { value: 'openai-gpt-4o' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save profile' }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe('http://127.0.0.1:8789/api/v1/model-profiles/active');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile_id: 'openai-gpt-4o' }),
    });
    expect(await screen.findByText('Profile selection saved.')).toBeInTheDocument();
  });

  it('renders NOT_LOGGED_IN status in English and disables selection', async () => {
    const notLoggedInResponse = {
      active_profile_id: 'codex-cli',
      weekly_call_limit: 200,
      weekly_calls_used: 0,
      live_dispatch_enabled: false,
      dispatch_block_reason: 'BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE',
      profiles: [
        {
          id: 'claude-cli',
          provider: 'claude-cli',
          model: 'default',
          status: 'NOT_LOGGED_IN',
          status_detail: 'CLI 尚未登入；請在終端機執行 claude 並使用 /login（或 codex login）後重新整理。',
          enabled: true,
          active: false,
          supports_json_schema: true,
          egress: 'cloud',
        },
      ],
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => notLoggedInResponse }));

    render(<ModelProfileSettings apiBase="http://127.0.0.1:8789" />);

    expect(await screen.findByText('Not logged in')).toBeInTheDocument();
    expect(screen.getByText(/CLI is not logged in/)).toBeInTheDocument();

    const option = screen.getByRole('option', { name: 'claude-cli' }) as HTMLOptionElement;
    expect(option.disabled).toBe(true);
  });
});
