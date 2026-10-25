// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SiteOpportunities } from './SiteOpportunities';
import type { Opportunity } from './siteIntelligenceTypes';

const scopeRef = {
  id: 'scope-north',
  revision: 1,
  sha256: `sha256:${'a'.repeat(64)}`,
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
    counterexamples: ['The route may conflict with retained structures.'],
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

describe('SiteOpportunities', () => {
  afterEach(cleanup);

  it('lets the designer include an opportunity in the editable brief', () => {
    const onSelect = vi.fn();
    render(
      <SiteOpportunities
        opportunities={opportunities}
        selectedOpportunityIds={[]}
        onSelect={onSelect}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByText(opportunities[0].statement)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Include in brief: opportunity-route' }));

    expect(onSelect).toHaveBeenCalledWith('opportunity-route', true);
    expect(screen.getByText(/The route may conflict with retained structures/i)).toBeTruthy();
  });

  it('records a reason when the designer rejects an opportunity', () => {
    const onReject = vi.fn();
    render(
      <SiteOpportunities
        opportunities={opportunities}
        selectedOpportunityIds={[]}
        onSelect={vi.fn()}
        onReject={onReject}
      />,
    );

    fireEvent.change(screen.getByLabelText('Reason to reject opportunity: opportunity-plaza'), {
      target: { value: 'Keep the existing quay edge unobstructed.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reject suggestion: opportunity-plaza' }));

    expect(onReject).toHaveBeenCalledWith(
      'opportunity-plaza',
      'Keep the existing quay edge unobstructed.',
    );
  });
});
