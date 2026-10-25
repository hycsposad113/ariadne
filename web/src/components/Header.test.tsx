// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Header } from './Header';

describe('Header human review action', () => {
  afterEach(cleanup);

  it('opens the review flow only when the caller confirms the StudyArea is current', () => {
    const onRecordStudyAreaReview = vi.fn();
    const props = {
      workspace: null,
      studyArea: {
        id: 'study-area-v5',
        status: 'CONFIRMED_FOR_EXPLORATION',
        revision: 1,
        version: 'v5',
      },
      serverLoadState: 'READY' as const,
      outcomeUnknown: false,
      reconciliationMessage: null,
      humanDecisionMessage: null,
      hasUnsavedChanges: false,
      hasActiveDrawing: false,
      canRecordStudyAreaReview: true,
      viewMode: '2D' as const,
      setViewMode: vi.fn(),
      onRecordStudyAreaReview,
      onOpenSyncModal: vi.fn(),
      onReload: vi.fn(),
      isSyncing: false,
    };

    const { rerender } = render(<Header {...props} />);
    const reviewButton = screen.getByRole('button', { name: 'Record Review' });
    expect((reviewButton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(reviewButton);
    expect(onRecordStudyAreaReview).toHaveBeenCalledOnce();

    rerender(<Header {...props} canRecordStudyAreaReview={false} />);
    expect((screen.getByRole('button', { name: 'Record Review' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('renders Day 1 decision badge and handles confirm button states', () => {
    const onConfirmD1Decision = vi.fn();
    const props = {
      workspace: null,
      studyArea: {
        id: 'study-area-v5',
        status: 'CONFIRMED_FOR_EXPLORATION',
        revision: 1,
        version: 'v5',
      },
      serverLoadState: 'READY' as const,
      outcomeUnknown: false,
      reconciliationMessage: null,
      humanDecisionMessage: null,
      hasUnsavedChanges: false,
      hasActiveDrawing: false,
      canRecordStudyAreaReview: false,
      viewMode: '2D' as const,
      setViewMode: vi.fn(),
      onRecordStudyAreaReview: vi.fn(),
      onOpenSyncModal: vi.fn(),
      onReload: vi.fn(),
      isSyncing: false,
      onConfirmD1Decision,
      canConfirmD1Decision: true,
      workspaceDecision: null,
      isD1DecisionStale: false,
    };

    const { rerender } = render(<Header {...props} />);
    // Badge reports unconfirmed draft
    const badge = screen.getByTestId('badge-d1-decision');
    expect(badge.textContent).toContain('D1 decision: unconfirmed (DRAFT)');

    // Button is enabled and clickable
    const confirmBtn = screen.getByRole('button', { name: /Confirm Day 1 decision/ });
    expect((confirmBtn as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(confirmBtn);
    expect(onConfirmD1Decision).toHaveBeenCalledOnce();

    // When canConfirmD1Decision is false, button is disabled
    rerender(<Header {...props} canConfirmD1Decision={false} />);
    expect((screen.getByRole('button', { name: /Confirm Day 1 decision/ }) as HTMLButtonElement).disabled).toBe(true);

    // When decision exists and is current
    const decisionFixture = {
      id: 'decision-d1-test-1',
      project_id: 'rotterdam-m4h-pilot-project',
      target_id: 'workspace-rotterdam-m4h-pilot-project',
      target_type: 'WorkspaceRevision',
      target_version: '1',
      action: 'Approve',
      status: 'approved',
      actor: 'designer',
      actor_kind: 'HUMAN_UI',
      reason: 'Approved Day 1 layout',
      timestamp: '2026-09-27T12:00:00Z',
    };

    rerender(<Header {...props} workspaceDecision={decisionFixture} isD1DecisionStale={false} />);
    expect(screen.getByTestId('badge-d1-decision').textContent).toContain('decision-d1-test-1');
    expect(screen.getByTestId('badge-d1-decision').textContent).toContain('(approved)');

    // When workspace is modified or stale
    rerender(<Header {...props} workspaceDecision={decisionFixture} isD1DecisionStale={true} />);
    expect(screen.getByTestId('badge-d1-decision').textContent).toContain('earlier revision 1');
  });
});
