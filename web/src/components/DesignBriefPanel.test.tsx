// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DesignBriefPanel } from './DesignBriefPanel';
import type { Opportunity } from './siteIntelligenceTypes';

const scopeRef = {
  id: 'scope-study-area',
  revision: 1,
  sha256: `sha256:${'a'.repeat(64)}`,
};
const workspaceRef = {
  id: 'workspace-design-brief-test',
  revision: 4,
  sha256: `sha256:${'b'.repeat(64)}`,
};
const analysisRef = {
  id: 'analysis-bundle-test',
  revision: 1,
  sha256: `sha256:${'c'.repeat(64)}`,
};
const inputHashes = {
  [workspaceRef.id]: workspaceRef.sha256,
  [analysisRef.id]: analysisRef.sha256,
};

const opportunities: Opportunity[] = [
  {
    id: 'opportunity-route',
    origin: 'AI_SUGGESTED',
    statement: 'Explore another connection through the local area.',
    kind: 'CONDITIONAL_HYPOTHESIS',
    evidence_refs: [],
    scope_ref: scopeRef,
    suggested_actions: ['TEST_HYPOTHESIS'],
    counterexamples: [],
    verification_metric_keys: [],
    uncertainties: ['Public access needs confirmation.'],
  },
  {
    id: 'opportunity-plaza',
    origin: 'RULE_SUGGESTED',
    statement: 'Consider a small plaza near the quay.',
    kind: 'DESIGN_PREFERENCE',
    evidence_refs: [],
    scope_ref: scopeRef,
    suggested_actions: ['REQUEST_DESIGNER_REVIEW'],
    counterexamples: [],
    verification_metric_keys: [],
    uncertainties: [],
  },
];

const createFetch = () => {
  let savedResponse: Record<string, unknown> | null = null;
  return vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
    if (init?.method === 'POST') {
      const request = JSON.parse(String(init.body));
      const brief = {
        id: request.brief_id,
        revision: 1,
        parent_ref: null,
        workspace_ref: workspaceRef,
        analysis_ref: analysisRef,
        intents: request.intents,
        selected_opportunity_ids: request.selected_opportunity_ids,
        assumption_refs: [],
        required_decision_refs: [],
      };
      const artifactRef = {
        id: 'design-brief-artifact-test',
        revision: 1,
        sha256: `sha256:${'d'.repeat(64)}`,
      };
      savedResponse = {
        status: 'DRAFT',
        brief,
        rejected_opportunities: request.rejected_opportunities,
        change_reason: request.change_reason,
        input_hashes: request.input_hashes,
        artifact_ref: artifactRef,
        idempotent_replay: false,
      };
      return { ok: true, status: 201, json: async () => ({ ...savedResponse }) } as Response;
    }
    return { ok: true, status: 200, json: async () => ({ ...(savedResponse ?? {}) }) } as Response;
  });
};

describe('DesignBriefPanel', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('saves and reloads a designer-authored intent with workspace and input preconditions', async () => {
    const fetchMock = createFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(
      <DesignBriefPanel
        projectId="design-brief-test"
        workspaceRevision={4}
        workspaceRef={workspaceRef}
        analysisRef={analysisRef}
        inputHashes={inputHashes}
        defaultScopeRef={scopeRef}
      />,
    );

    fireEvent.change(screen.getByLabelText('New design intent'), {
      target: { value: 'Keep a clear walking route through this area.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add designer intent' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save draft brief' }));

    await waitFor(() => expect(screen.getByText('Saved draft revision 1')).toBeTruthy());
    const postCall = fetchMock.mock.calls[0];
    const postBody = JSON.parse(String(postCall[1]?.body));
    expect(postBody.expected_workspace_revision).toBe(4);
    expect(postBody.input_hashes).toMatchObject({
      [workspaceRef.id]: workspaceRef.sha256,
      [analysisRef.id]: analysisRef.sha256,
      [scopeRef.id]: scopeRef.sha256,
    });
    expect(postBody.idempotency_key).toBeTruthy();
    expect(postBody.intents[0]).toMatchObject({
      text: 'Keep a clear walking route through this area.',
      origin: 'DESIGNER_AUTHORED',
      scope_ref: scopeRef,
    });
    expect(postBody).not.toHaveProperty('approved');
    expect(String(fetchMock.mock.calls[1][0])).toContain('/revisions/1');
  });

  it('saves a modified opportunity plus a rejected suggestion and reloads the draft', async () => {
    const fetchMock = createFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(
      <DesignBriefPanel
        projectId="design-brief-test"
        workspaceRevision={4}
        workspaceRef={workspaceRef}
        analysisRef={analysisRef}
        inputHashes={inputHashes}
        defaultScopeRef={scopeRef}
        opportunities={opportunities}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Include in brief: opportunity-route' }));
    fireEvent.change(screen.getByLabelText(/Intent text for .*opportunity-route/i), {
      target: { value: 'Edit the suggested route, then inspect its continuity.' },
    });
    fireEvent.change(screen.getByLabelText('Reason to reject opportunity: opportunity-plaza'), {
      target: { value: 'Keep the existing quay edge unobstructed.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reject suggestion: opportunity-plaza' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save draft brief' }));

    await waitFor(() => expect(screen.getByText('Saved draft revision 1')).toBeTruthy());
    const request = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(request.selected_opportunity_ids).toEqual(['opportunity-route']);
    expect(request.intents).toHaveLength(1);
    expect(request.intents[0]).toMatchObject({
      text: 'Edit the suggested route, then inspect its continuity.',
      origin: 'AI_SUGGESTED',
      source_opportunity_ids: ['opportunity-route'],
    });
    expect(request.rejected_opportunities).toEqual([
      { opportunity_id: 'opportunity-plaza', reason: 'Keep the existing quay edge unobstructed.' },
    ]);
    expect(screen.getByText('Edit the suggested route, then inspect its continuity.')).toBeTruthy();
    expect(screen.getByText(/Keep the existing quay edge unobstructed\./)).toBeTruthy();
  });

  it('lets the designer undo a rejection, reselect the suggestion, and save the changed intent', async () => {
    const fetchMock = createFetch();
    vi.stubGlobal('fetch', fetchMock);
    render(
      <DesignBriefPanel
        projectId="design-brief-test"
        workspaceRevision={4}
        workspaceRef={workspaceRef}
        analysisRef={analysisRef}
        inputHashes={inputHashes}
        defaultScopeRef={scopeRef}
        opportunities={opportunities}
      />,
    );

    fireEvent.change(screen.getByLabelText('Reason to reject opportunity: opportunity-plaza'), {
      target: { value: 'The plaza needs a different location.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reject suggestion: opportunity-plaza' }));
    expect(screen.getByText('Rejected in this draft')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Undo rejection: opportunity-plaza' }));
    fireEvent.click(screen.getByRole('button', { name: 'Include in brief: opportunity-plaza' }));
    fireEvent.change(screen.getByLabelText(/Intent text for intent-opportunity-plaza/i), {
      target: { value: 'Place a small plaza away from the quay edge.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save draft brief' }));

    await waitFor(() => expect(screen.getByText('Saved draft revision 1')).toBeTruthy());
    const request = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(request.selected_opportunity_ids).toEqual(['opportunity-plaza']);
    expect(request.rejected_opportunities).toEqual([]);
    expect(request.intents[0]).toMatchObject({
      text: 'Place a small plaza away from the quay edge.',
      origin: 'RULE_SUGGESTED',
      source_opportunity_ids: ['opportunity-plaza'],
    });
  });

  it('hydrates a loaded revision after mount and merges pending Site-stage choices', async () => {
    const savedDraft = {
      status: 'DRAFT' as const,
      brief: {
        id: 'brief-existing',
        revision: 2,
        parent_ref: null,
        workspace_ref: workspaceRef,
        analysis_ref: analysisRef,
        intents: [{
          id: 'intent-designer-authored',
          text: 'Keep the loading access clear.',
          scope_ref: scopeRef,
          kind: 'PREFERENCE' as const,
          source_opportunity_ids: [],
          origin: 'DESIGNER_AUTHORED' as const,
          priority: null,
          version: 1,
        }],
        selected_opportunity_ids: [],
        assumption_refs: [],
        required_decision_refs: [],
      },
      rejected_opportunities: [],
      input_hashes: inputHashes,
      artifact_ref: {
        id: 'design-brief-artifact-existing',
        revision: 1,
        sha256: `sha256:${'e'.repeat(64)}`,
      },
    };
    const { rerender } = render(
      <DesignBriefPanel
        projectId="design-brief-test"
        workspaceRevision={4}
        workspaceRef={workspaceRef}
        analysisRef={analysisRef}
        inputHashes={inputHashes}
        defaultScopeRef={scopeRef}
        opportunities={opportunities}
        initialDraft={null}
      />,
    );

    rerender(
      <DesignBriefPanel
        projectId="design-brief-test"
        workspaceRevision={4}
        workspaceRef={workspaceRef}
        analysisRef={analysisRef}
        inputHashes={inputHashes}
        defaultScopeRef={scopeRef}
        opportunities={opportunities}
        initialDraft={savedDraft}
        initialSelectedOpportunityIds={['opportunity-route']}
        initialRejectedOpportunities={[
          { opportunity_id: 'opportunity-plaza', reason: 'Keep quay operations open.' },
        ]}
      />,
    );

    expect(await screen.findByText('Saved draft revision 2')).toBeTruthy();
    expect(screen.getByDisplayValue('Keep the loading access clear.')).toBeTruthy();
    expect(screen.getByDisplayValue(opportunities[0].statement)).toBeTruthy();
    expect(screen.getByText('Rejected in this draft')).toBeTruthy();
    expect(screen.getByText(/Keep quay operations open\./)).toBeTruthy();
  });

  it('renders exactly one status notice when prerequisites are not ready', () => {
    render(
      <DesignBriefPanel
        projectId="design-brief-test"
        workspaceRevision={0}
        workspaceRef={null}
        analysisRef={null}
        inputHashes={{}}
        canPersist={false}
        readinessMessage="NOT_READY: Matching workspace, active StudyArea, and analysis references are required."
      />,
    );

    const statuses = screen.getAllByRole('status');
    expect(statuses).toHaveLength(1);
    expect(statuses[0].textContent).toContain('NOT_READY: Matching workspace, active StudyArea, and analysis references are required.');
  });
});
