// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HumanDecisionDialog } from './HumanDecisionDialog';

describe('HumanDecisionDialog', () => {
  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    localStorage.clear();
  });

  it('shows the exact target binding, submits a password, then clears it', async () => {
    const onSubmit = vi.fn(async () => {});
    const onClose = vi.fn();
    const key = 'fixture-' + 'x'.repeat(32);
    render(
      <HumanDecisionDialog
        isOpen
        target={{
          id: 'study-area-v5',
          type: 'StudyArea',
          version: 'v5',
          geometrySha256: `sha256:${'a'.repeat(64)}`,
        }}
        action="Approve"
        status="approved"
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByRole('dialog', { name: 'Confirm human decision' })).toBeTruthy();
    expect(screen.getByText('study-area-v5')).toBeTruthy();
    expect(screen.getByText('v5')).toBeTruthy();
    const keyInput = screen.getByLabelText('Decision key') as HTMLInputElement;
    expect(keyInput.type).toBe('password');
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Confirm this reviewed boundary.' } });
    fireEvent.change(keyInput, { target: { value: key } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm decision' }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      target_id: 'study-area-v5',
      target_type: 'StudyArea',
      target_version: 'v5',
      target_geometry_sha256: `sha256:${'a'.repeat(64)}`,
      action: 'Approve',
      status: 'approved',
      reason: 'Confirm this reviewed boundary.',
      decision_key: key,
      actor_session_id: expect.any(String),
    })));
    expect(onClose).toHaveBeenCalledOnce();
    expect(keyInput.value).toBe('');
    expect(sessionStorage.getItem('urban-design-decision-key')).toBeNull();
    expect(localStorage.getItem('urban-design-decision-key')).toBeNull();
    const storedValues = (storage: Storage) => Array.from({ length: storage.length }, (_, index) => {
      const storageKey = storage.key(index);
      return storageKey ? storage.getItem(storageKey) || '' : '';
    });
    expect([...storedValues(sessionStorage), ...storedValues(localStorage)].join('\n')).not.toContain(key);
  });

  it('binds a decision to a payload digest when the target has no geometry hash', async () => {
    const onSubmit = vi.fn(async () => {});
    const digest = `sha256:${'d'.repeat(64)}`;
    render(
      <HumanDecisionDialog
        isOpen
        target={{ id: 'constraint-set-1', type: 'ConstraintSet', version: 'v1', payloadDigest: digest }}
        action="Approve"
        status="approved"
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByText(digest)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Approve the reviewed constraint set.' } });
    fireEvent.change(screen.getByLabelText('Decision key'), { target: { value: 'fixture-' + 'd'.repeat(32) } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm decision' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      target_id: 'constraint-set-1',
      target_type: 'ConstraintSet',
      target_version: 'v1',
      target_payload_digest: digest,
      action: 'Approve',
      status: 'approved',
    })));
  });

  it('clears a typed key when the dialog closes without submitting', () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <HumanDecisionDialog
        isOpen
        target={{ id: 'scenario-b', type: 'Scenario', version: 'v3', artifactSha256: `sha256:${'b'.repeat(64)}` }}
        action="Reject"
        status="rejected"
        onClose={onClose}
        onSubmit={vi.fn(async () => {})}
      />,
    );
    const keyInput = screen.getByLabelText('Decision key') as HTMLInputElement;
    fireEvent.change(keyInput, { target: { value: 'fixture-' + 'y'.repeat(32) } });
    rerender(
      <HumanDecisionDialog
        isOpen={false}
        target={{ id: 'scenario-b', type: 'Scenario', version: 'v3', artifactSha256: `sha256:${'b'.repeat(64)}` }}
        action="Reject"
        status="rejected"
        onClose={onClose}
        onSubmit={vi.fn(async () => {})}
      />,
    );
    expect(screen.queryByRole('dialog')).toBeNull();
    rerender(
      <HumanDecisionDialog
        isOpen
        target={{ id: 'scenario-b', type: 'Scenario', version: 'v3', artifactSha256: `sha256:${'b'.repeat(64)}` }}
        action="Reject"
        status="rejected"
        onClose={onClose}
        onSubmit={vi.fn(async () => {})}
      />,
    );
    expect((screen.getByLabelText('Decision key') as HTMLInputElement).value).toBe('');
  });

  it('clears the decision key after a rejected submission', async () => {
    const key = 'fixture-' + 'z'.repeat(32);
    const onSubmit = vi.fn(async () => {
      throw new Error('Decision key is incorrect');
    });
    render(
      <HumanDecisionDialog
        isOpen
        target={{ id: 'scenario-c', type: 'Scenario', version: 'v1', artifactSha256: `sha256:${'c'.repeat(64)}` }}
        action="Inspect"
        status="inspected"
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );
    const keyInput = screen.getByLabelText('Decision key') as HTMLInputElement;
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Review current evidence.' } });
    fireEvent.change(keyInput, { target: { value: key } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm decision' }));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('incorrect'));
    expect(keyInput.value).toBe('');
    expect(sessionStorage.getItem('urban-design-decision-key')).toBeNull();
    expect(localStorage.getItem('urban-design-decision-key')).toBeNull();
  });

  it('renders Day 1 decision summary with EDA, dispositions breakdown, and spatial zones', () => {
    const summaryFixture = {
      workspace_id: 'workspace-rotterdam-m4h-pilot-project',
      project_id: 'rotterdam-m4h-pilot-project',
      revision: 1,
      payload_digest: `sha256:${'1'.repeat(64)}`,
      exploration_design_area: {
        area_m2: 45000,
        geometry_hash: `sha256:${'e'.repeat(64)}`,
      },
      dispositions: {
        buildings: {
          preserve: ['bldg-1', 'bldg-2'],
          editable: ['bldg-3'],
          undecided: ['bldg-4', 'bldg-5'],
          counts: { preserve: 2, editable: 1, undecided: 2, total: 5 },
        },
        roads: {
          preserve: ['road-1'],
          editable: ['road-2'],
          undecided: [],
          counts: { preserve: 1, editable: 1, undecided: 0, total: 2 },
        },
      },
      zones: [
        {
          zone_id: 'zone-north',
          name: 'North Innovation District',
          target_use: 'Mixed-Use',
          target_far: 2.5,
          target_height_m: 35,
          draft_constraints: ['Max FAR 2.5', 'Active ground floor'],
          draft_preferences: ['Solar orientation', 'Green courtyards'],
        },
      ],
    };

    render(
      <HumanDecisionDialog
        isOpen
        target={{
          id: 'workspace-rotterdam-m4h-pilot-project',
          type: 'WorkspaceRevision',
          version: '1',
          payloadDigest: `sha256:${'1'.repeat(64)}`,
          geometrySha256: `sha256:${'e'.repeat(64)}`,
        }}
        action="Approve"
        status="approved"
        summary={summaryFixture}
        onClose={vi.fn()}
        onSubmit={vi.fn(async () => {})}
      />,
    );

    // Summary container exists
    expect(screen.getByTestId('d1-dialog-summary')).toBeTruthy();

    // EDA stats
    expect(screen.getByTestId('d1-dialog-eda-area').textContent).toContain('45,000 m²');
    expect(screen.getByTestId('d1-dialog-eda-hash').textContent).toContain(`sha256:${'e'.repeat(64)}`);

    // Dispositions counts and expandable details
    expect(screen.getByTestId('details-buildings-preserve')).toBeTruthy();
    expect(screen.getByText('bldg-1')).toBeTruthy();
    expect(screen.getByText('bldg-2')).toBeTruthy();
    expect(screen.getByText('road-1')).toBeTruthy();

    // Spatial Zones
    expect(screen.getByText('North Innovation District')).toBeTruthy();
    expect(screen.getByText(/FAR: 2.5/)).toBeTruthy();
    expect(screen.getByText(/Height cap: 35m/)).toBeTruthy();
    expect(screen.getByText(/Max FAR 2.5/)).toBeTruthy();
    expect(screen.getByText(/Solar orientation/)).toBeTruthy();
  });

  it('displays unsaved changes warning and disables submit when hasUnsavedChanges is true', () => {
    render(
      <HumanDecisionDialog
        isOpen
        target={{
          id: 'workspace-rotterdam-m4h-pilot-project',
          type: 'WorkspaceRevision',
          version: '1',
          payloadDigest: `sha256:${'1'.repeat(64)}`,
        }}
        action="Approve"
        status="approved"
        hasUnsavedChanges={true}
        onClose={vi.fn()}
        onSubmit={vi.fn(async () => {})}
      />,
    );

    // Unsaved warning is present
    expect(screen.getByTestId('d1-dialog-unsaved-warning')).toBeTruthy();
    expect(screen.getByTestId('d1-dialog-unsaved-warning').textContent).toContain('Unsaved changes warning');

    // Submit button is disabled
    const submitBtn = screen.getByTestId('d1-dialog-submit-btn') as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);
  });

  it('submits WorkspaceRevision decision with bound geometry and payload hashes', async () => {
    const onSubmit = vi.fn(async () => {});
    const key = 'fixture-pass-' + 'a'.repeat(32);
    const edaHash = `sha256:${'e'.repeat(64)}`;
    const digest = `sha256:${'d'.repeat(64)}`;

    render(
      <HumanDecisionDialog
        isOpen
        target={{
          id: 'workspace-rotterdam-m4h-pilot-project',
          type: 'WorkspaceRevision',
          version: '2',
          geometrySha256: edaHash,
          payloadDigest: digest,
        }}
        action="Approve"
        status="approved"
        hasUnsavedChanges={false}
        onClose={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    const submitBtn = screen.getByTestId('d1-dialog-submit-btn') as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(false);

    fireEvent.change(screen.getByLabelText('Decision key'), { target: { value: key } });
    fireEvent.click(submitBtn);

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      target_id: 'workspace-rotterdam-m4h-pilot-project',
      target_type: 'WorkspaceRevision',
      target_version: '2',
      target_geometry_sha256: edaHash,
      target_payload_digest: digest,
      action: 'Approve',
      status: 'approved',
      reason: expect.stringMatching(/Day 1 decision|第 1 天決策/),
      decision_key: key,
    })));
  });

  it('initializes reason as empty string for ConstraintSet target, shows error on empty submission, and submits when filled', async () => {
    const onSubmit = vi.fn(async () => {});
    const onClose = vi.fn();
    const digest = `sha256:${'c'.repeat(64)}`;
    const key = 'fixture-key-' + 'k'.repeat(32);

    render(
      <HumanDecisionDialog
        isOpen
        target={{
          id: 'constraint-set-custom-v1',
          type: 'ConstraintSet',
          version: 'v1',
          payloadDigest: digest,
        }}
        action="Approve"
        status="approved"
        onClose={onClose}
        onSubmit={onSubmit}
      />,
    );

    const reasonInput = screen.getByLabelText('Reason') as HTMLTextAreaElement;
    // Must be empty string, NOT "s"
    expect(reasonInput.value).toBe('');

    const keyInput = screen.getByLabelText('Decision key') as HTMLInputElement;
    const submitBtn = screen.getByTestId('d1-dialog-submit-btn');

    // Attempting to submit with empty reason and empty key triggers validation error
    fireEvent.click(submitBtn);
    expect(onSubmit).not.toHaveBeenCalled();
    const alert1 = screen.getByRole('alert');
    expect(alert1.textContent).toMatch(/Please enter a decision reason|請輸入決策理由/);

    // Provide decision key only
    fireEvent.change(keyInput, { target: { value: key } });
    fireEvent.click(submitBtn);
    expect(onSubmit).not.toHaveBeenCalled();
    const alert2 = screen.getByRole('alert');
    expect(alert2.textContent).toMatch(/Please enter a decision reason|請輸入決策理由/);

    // Provide reason
    fireEvent.change(reasonInput, { target: { value: 'Valid operational constraints.' } });

    // Now submit succeeds
    fireEvent.click(submitBtn);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({
      target_id: 'constraint-set-custom-v1',
      target_type: 'ConstraintSet',
      target_version: 'v1',
      target_payload_digest: digest,
      action: 'Approve',
      status: 'approved',
      reason: 'Valid operational constraints.',
      decision_key: key,
    })));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('disables submit button and shows explanation title when target hash is missing', () => {
    render(
      <HumanDecisionDialog
        isOpen
        target={{
          id: 'unhashed-target',
          type: 'ConstraintSet',
          version: 'v0',
        }}
        action="Approve"
        status="approved"
        onClose={vi.fn()}
        onSubmit={vi.fn(async () => {})}
      />,
    );

    const submitBtn = screen.getByTestId('d1-dialog-submit-btn') as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(true);
    expect(submitBtn.title).toMatch(/Missing hash — decision blocked|缺少雜湊/);
  });
});
