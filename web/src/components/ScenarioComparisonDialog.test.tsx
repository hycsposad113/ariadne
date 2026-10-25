// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ScenarioComparisonDialog } from './ScenarioComparisonDialog';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const mockScenarios = [
  {
    scenario_id: 'formal-scheme-a',
    strategy_label: 'Formal Strategy A',
    revision: 1,
    geometry_sha256: 'sha256:aaaa1111',
    status: 'PROPOSED',
  },
  {
    scenario_id: 'formal-scheme-b',
    strategy_label: 'Formal Strategy B',
    revision: 1,
    geometry_sha256: 'sha256:bbbb2222',
    status: 'PROPOSED',
  },
  {
    scenario_id: 'formal-scheme-c',
    strategy_label: 'Formal Strategy C',
    revision: 1,
    geometry_sha256: 'sha256:cccc3333',
    status: 'PROPOSED',
  },
];

describe('ScenarioComparisonDialog', () => {
  it('does not render when isOpen is false', () => {
    render(
      <ScenarioComparisonDialog
        isOpen={false}
        projectId="test-proj"
        allScenarios={mockScenarios}
        apiBase="http://api.test"
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('initial baseline selection is none; adopted baseline summary and rejection reasons appear only after picking a radio', async () => {
    render(
      <ScenarioComparisonDialog
        isOpen={true}
        projectId="test-proj"
        allScenarios={mockScenarios}
        initialSelectedId="formal-scheme-a"
        apiBase="http://api.test"
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    expect(screen.getByRole('dialog')).toBeTruthy();
    const radios = screen.getAllByRole('radio');
    expect(radios).toHaveLength(3);

    // Initial selected is NONE (item 1)
    expect((radios[0] as HTMLInputElement).checked).toBe(false);
    expect((radios[1] as HTMLInputElement).checked).toBe(false);
    expect((radios[2] as HTMLInputElement).checked).toBe(false);

    // Baseline card and rejection section do not appear yet
    expect(screen.queryByTestId('accepted-baseline-card')).toBeNull();
    expect(screen.queryByTestId('rejected-proposals-section')).toBeNull();

    // Select scheme A
    fireEvent.click(radios[0]);
    expect((radios[0] as HTMLInputElement).checked).toBe(true);
    expect((radios[1] as HTMLInputElement).checked).toBe(false);

    // Now baseline card and rejection section appear
    const baselineCard = screen.getByTestId('accepted-baseline-card');
    expect(baselineCard.textContent).toContain('Formal Strategy A');
    expect(screen.getByTestId('rejected-proposals-section')).toBeTruthy();

    // Switch selection to scheme B
    fireEvent.click(radios[1]);
    expect((radios[0] as HTMLInputElement).checked).toBe(false);
    expect((radios[1] as HTMLInputElement).checked).toBe(true);
    expect(screen.getByTestId('accepted-baseline-card').textContent).toContain('Formal Strategy B');
  });

  it('keeps submit button enabled on incomplete form, shows inline errors and summary on submit, and sends no request', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(
      <ScenarioComparisonDialog
        isOpen={true}
        projectId="test-proj"
        allScenarios={mockScenarios}
        apiBase="http://api.test"
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    const submitBtn = screen.getByTestId('confirm-baseline-btn');
    // Button is enabled (item 3: must NOT be disabled while form is incomplete)
    expect((submitBtn as HTMLButtonElement).disabled).toBe(false);

    // Submit empty form
    fireEvent.click(submitBtn);

    // No request sent when invalid
    expect(fetchSpy).not.toHaveBeenCalled();

    // Explicit inline errors shown
    expect(screen.getByTestId('error-baseline').textContent).toContain('Please select a baseline scheme.');
    expect(screen.getByTestId('error-acceptance-reason').textContent).toContain('Baseline acceptance reason is required.');
    expect(screen.getByTestId('error-decision-key').textContent).toContain('Decision key is required.');

    // Error summary near the button
    const summary = screen.getByTestId('error-summary');
    expect(summary.textContent).toContain('Please select a baseline scheme.');
    expect(summary.textContent).toContain('Baseline acceptance reason is required.');
    expect(summary.textContent).toContain('Decision key is required.');
  });

  it('shows rejection reason errors when baseline is chosen but rejection reasons are missing', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    render(
      <ScenarioComparisonDialog
        isOpen={true}
        projectId="test-proj"
        allScenarios={mockScenarios}
        apiBase="http://api.test"
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    // Select scheme A
    const radios = screen.getAllByRole('radio');
    fireEvent.click(radios[0]);

    // Fill acceptance reason and decision key, but leave rejection reasons empty
    const acceptanceTextarea = screen.getByPlaceholderText(
      'Explain why this proposal is accepted as baseline (e.g., optimal FAR, superior open space, balanced height)…'
    );
    fireEvent.change(acceptanceTextarea, { target: { value: 'Best density and layout.' } });

    const passwordInput = screen.getByPlaceholderText('Enter private decision key');
    fireEvent.change(passwordInput, { target: { value: 'secret-passphrase-123' } });

    const submitBtn = screen.getByTestId('confirm-baseline-btn');
    fireEvent.click(submitBtn);

    // No request sent
    expect(fetchSpy).not.toHaveBeenCalled();

    // Rejection reason inline errors
    expect(screen.getByTestId('error-rejection-formal-scheme-b')).toBeTruthy();
    expect(screen.getByTestId('error-rejection-formal-scheme-c')).toBeTruthy();

    const summary = screen.getByTestId('error-summary');
    expect(summary.textContent).toContain('Formal Strategy B');
    expect(summary.textContent).toContain('Formal Strategy C');
  });

  it('submits comparison decision payload to backend and invokes onSuccess when valid', async () => {
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          project_id: 'test-proj',
          baseline_scenario_id: 'formal-scheme-a',
          rejected_scenario_ids: ['formal-scheme-b', 'formal-scheme-c'],
          message: 'Baseline accepted and other scenarios rejected successfully',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      )
    );

    render(
      <ScenarioComparisonDialog
        isOpen={true}
        projectId="test-proj"
        allScenarios={mockScenarios}
        apiBase="http://api.test"
        onClose={onClose}
        onSuccess={onSuccess}
      />
    );

    // Pick scheme A
    const radios = screen.getAllByRole('radio');
    fireEvent.click(radios[0]);

    const acceptanceTextarea = screen.getByPlaceholderText(
      'Explain why this proposal is accepted as baseline (e.g., optimal FAR, superior open space, balanced height)…'
    );
    fireEvent.change(acceptanceTextarea, { target: { value: 'Selected due to balanced open space.' } });

    const rejectionTextareas = screen.getAllByPlaceholderText(
      'Explain why this proposal was not chosen (e.g., excessive height, insufficient open space)…'
    );
    expect(rejectionTextareas).toHaveLength(2);
    fireEvent.change(rejectionTextareas[0], { target: { value: 'Rejection reason B' } });
    fireEvent.change(rejectionTextareas[1], { target: { value: 'Rejection reason C' } });

    const passwordInput = screen.getByPlaceholderText('Enter private decision key');
    fireEvent.change(passwordInput, { target: { value: 'valid-test-key' } });

    const submitBtn = screen.getByTestId('confirm-baseline-btn');
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        'http://api.test/api/v1/scenarios/comparison/decision',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        })
      );
    });

    const callBody = JSON.parse((fetchSpy.mock.calls[0][1] as RequestInit).body as string);
    expect(callBody).toMatchObject({
      project_id: 'test-proj',
      scenario_ids: ['formal-scheme-a', 'formal-scheme-b', 'formal-scheme-c'],
      accepted_scenario_id: 'formal-scheme-a',
      acceptance_reason: 'Selected due to balanced open space.',
      rejected_reasons: {
        'formal-scheme-b': 'Rejection reason B',
        'formal-scheme-c': 'Rejection reason C',
      },
      decision_key: 'valid-test-key',
    });
    expect(typeof callBody.actor_session_id).toBe('string');

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith(
        expect.objectContaining({
          baseline_scenario_id: 'formal-scheme-a',
        })
      );
    });
  });

  it('displays error message when submission fails with 403 or 429', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: 'Decision key is incorrect',
        }),
        { status: 403, headers: { 'Content-Type': 'application/json' } }
      )
    );

    render(
      <ScenarioComparisonDialog
        isOpen={true}
        projectId="test-proj"
        allScenarios={mockScenarios}
        apiBase="http://api.test"
        onClose={vi.fn()}
        onSuccess={vi.fn()}
      />
    );

    // Pick scheme A
    const radios = screen.getAllByRole('radio');
    fireEvent.click(radios[0]);

    const acceptanceTextarea = screen.getByPlaceholderText(
      'Explain why this proposal is accepted as baseline (e.g., optimal FAR, superior open space, balanced height)…'
    );
    fireEvent.change(acceptanceTextarea, { target: { value: 'Accept A' } });

    const rejectionTextareas = screen.getAllByPlaceholderText(
      'Explain why this proposal was not chosen (e.g., excessive height, insufficient open space)…'
    );
    fireEvent.change(rejectionTextareas[0], { target: { value: 'Reject B' } });
    fireEvent.change(rejectionTextareas[1], { target: { value: 'Reject C' } });

    const passwordInput = screen.getByPlaceholderText('Enter private decision key');
    fireEvent.change(passwordInput, { target: { value: 'wrong-key' } });

    const submitBtn = screen.getByTestId('confirm-baseline-btn');
    fireEvent.click(submitBtn);

    const alert = await screen.findByTestId('server-error');
    expect(alert.textContent).toContain('Decision key is incorrect');
  });

  it('calls onClose when cancel button is clicked or Escape key pressed', () => {
    const onClose = vi.fn();
    render(
      <ScenarioComparisonDialog
        isOpen={true}
        projectId="test-proj"
        allScenarios={mockScenarios}
        apiBase="http://api.test"
        onClose={onClose}
        onSuccess={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
