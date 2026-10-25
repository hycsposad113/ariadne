import { describe, expect, it } from 'vitest';
import {
  canApplyLoadResponse,
  shouldRetainNewerDraft,
  type LoadResponseGuardInput,
} from './loadGuards';

const current: LoadResponseGuardInput = {
  requestId: 2,
  latestRequestId: 2,
  startedDraftGeneration: 4,
  currentDraftGeneration: 4,
  hasPendingReconciliation: false,
};

describe('workspace load and sync race guards', () => {
  it('rejects a response superseded by a later reload', () => {
    expect(canApplyLoadResponse({ ...current, requestId: 1 })).toBe(false);
  });

  it('rejects a response started before a newer local draft generation unless reconciling a pending sync', () => {
    expect(canApplyLoadResponse({
      ...current,
      startedDraftGeneration: 4,
      currentDraftGeneration: 5,
    })).toBe(false);
    expect(canApplyLoadResponse({
      ...current,
      startedDraftGeneration: 4,
      currentDraftGeneration: 5,
      hasPendingReconciliation: true,
    })).toBe(true);
  });

  it('retains local work when the submitted generation is older than the current one', () => {
    expect(shouldRetainNewerDraft({ submittedDraftGeneration: 4, currentDraftGeneration: 5 })).toBe(true);
    expect(shouldRetainNewerDraft({ submittedDraftGeneration: 5, currentDraftGeneration: 5 })).toBe(false);
  });
});
