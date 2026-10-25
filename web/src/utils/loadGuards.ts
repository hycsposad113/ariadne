export interface LoadResponseGuardInput {
  requestId: number;
  latestRequestId: number;
  startedDraftGeneration: number;
  currentDraftGeneration: number;
  hasPendingReconciliation: boolean;
}

/**
 * A site-context response may update the UI only while it is the latest
 * request and it was not started against an older local draft. A pending
 * OUTCOME_UNKNOWN reconciliation is the explicit exception: it must be
 * allowed to inspect the server and reconcile its captured submission.
 */
export function canApplyLoadResponse(input: LoadResponseGuardInput): boolean {
  return input.requestId === input.latestRequestId
    && (input.hasPendingReconciliation
      || input.startedDraftGeneration === input.currentDraftGeneration);
}

export function shouldRetainNewerDraft(input: {
  submittedDraftGeneration: number;
  currentDraftGeneration: number;
}): boolean {
  return input.submittedDraftGeneration !== input.currentDraftGeneration;
}
