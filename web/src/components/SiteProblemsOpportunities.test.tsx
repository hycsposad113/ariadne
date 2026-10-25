// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SiteProblemsOpportunities } from './SiteProblemsOpportunities';
import type { Opportunity } from './siteIntelligenceTypes';

const scopeRef = {
  id: 'scope-study-area-test',
  revision: 1,
  sha256: `sha256:${'a'.repeat(64)}`,
};

const mockOpportunities: Opportunity[] = [
  {
    id: 'opp-quay-park',
    origin: 'AI_SUGGESTED',
    statement: 'Explore a continuous waterfront promenade along Merwehaven quay.',
    kind: 'CONDITIONAL_HYPOTHESIS',
    evidence_refs: [],
    scope_ref: scopeRef,
    suggested_actions: ['CONNECT_WATERFRONT_PROMENADE'],
    counterexamples: ['Quay operations may require security fences.'],
    uncertainties: ['Public access rights pending confirmation.'],
  },
  {
    id: 'opp-cul-de-sac-reopen',
    origin: 'RULE_SUGGESTED',
    statement: 'Consider extending Keileweg to connect dead-end segments.',
    kind: 'DESIGN_PREFERENCE',
    evidence_refs: [],
    scope_ref: scopeRef,
    suggested_actions: ['IMPROVE_NETWORK_PERMEABILITY'],
    uncertainties: [],
  },
];

describe('SiteProblemsOpportunities', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('maps the persisted problem report fields and preserves Problem 6 limits', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        project_id: 'rotterdam-m4h-pilot-project',
        status: 'ANALYSIS_DEFINED',
        summary: { study_area_id: 'study-area-test' },
        statements: [
          {
            problem_id: 'prob-01-functional-monoculture',
            title_zh: 'BAG 建築用途標籤與登記狀態',
            severity_code: 'CRITICAL',
            status: 'CONFIRMED_BASELINE',
            evidence_summary_zh: 'BAG 登記用途標籤的計算摘要。',
            uncertainties_zh: ['BAG 登記用途不一定等於現況使用。'],
          },
          {
            problem_id: 'prob-06-unclassified-residual-ground',
            title_zh: '[AI候選·待設計者確認] 非建築／非水體幾何差額（Geometric Remainder）',
            severity_code: 'UNRATED',
            status: 'PENDING_DESIGNER_CONFIRMATION',
            evidence_summary_zh: '幾何差額觀察，不代表可開發土地。',
            uncertainties_zh: [
              '差額可能包含道路、廣場、庭院、作業空間、綠地及其他未輸入圖層。',
              '沒有土地所有權、租約、地籍、土壤污染或可開發性資料。',
            ],
          },
        ],
      }),
    }));

    render(
      <SiteProblemsOpportunities
        projectId="rotterdam-m4h-pilot-project"
        apiBase="/api"
        expectedStudyAreaId="study-area-test"
        opportunities={mockOpportunities}
        selectedOpportunityIds={[]}
        onSelectOpportunity={vi.fn()}
        onRejectOpportunity={vi.fn()}
      />,
    );

    expect(await screen.findByText(/BAG 建築用途標籤與登記狀態/)).toBeTruthy();
    expect(screen.getByText(/prob-06-unclassified-residual-ground/i)).toBeTruthy();
    expect(screen.getByText('Critical')).toBeTruthy();
    expect(screen.getByText('BAG 登記用途標籤的計算摘要。')).toBeTruthy();
    expect(screen.getByText('Pending designer confirmation')).toBeTruthy();
    expect(screen.getByText('Unrated')).toBeTruthy();
    expect(screen.getByText(/Geometric difference only/i)).toBeTruthy();
    expect(screen.getByText(/Not an approved vacancy or development zone/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /prob-06-unclassified-residual-ground/i }));
    expect(screen.getByText(/沒有土地所有權、租約、地籍/)).toBeTruthy();
  });

  it('shows NOT_READY instead of stale fallback claims when no problem report is available', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: 'Problem definition artifacts not found' }),
    }));

    render(
      <SiteProblemsOpportunities
        projectId="rotterdam-m4h-pilot-project"
        apiBase="/api"
        expectedStudyAreaId="study-area-test"
        opportunities={mockOpportunities}
        selectedOpportunityIds={[]}
        onSelectOpportunity={vi.fn()}
        onRejectOpportunity={vi.fn()}
      />,
    );

    expect(await screen.findByText(/NOT_READY/)).toBeTruthy();
    expect(screen.queryByText(/prob-01-functional-monoculture/i)).toBeNull();
    expect(screen.getByText(mockOpportunities[0].statement)).toBeTruthy();
  });

  it('allows selecting an opportunity and navigating to the design brief', () => {
    const onSelect = vi.fn();
    const onNavigate = vi.fn();

    render(
      <SiteProblemsOpportunities
        projectId="rotterdam-m4h-pilot-project"
        opportunities={mockOpportunities}
        selectedOpportunityIds={[]}
        onSelectOpportunity={onSelect}
        onRejectOpportunity={vi.fn()}
        onNavigateToBrief={onNavigate}
      />,
    );

    // Check opportunity statement is displayed
    expect(screen.getByText(mockOpportunities[0].statement)).toBeTruthy();

    // Click "Include in brief"
    fireEvent.click(screen.getByRole('button', { name: 'Include in brief: opp-quay-park' }));
    expect(onSelect).toHaveBeenCalledWith('opp-quay-park', true);

    // Click "Go to Design Brief"
    fireEvent.click(screen.getByRole('button', { name: /Go to Design Brief/i }));
    expect(onNavigate).toHaveBeenCalled();
  });

  it('allows rejecting an opportunity with a reason from the Site stage entrypoint', () => {
    const onReject = vi.fn();

    render(
      <SiteProblemsOpportunities
        projectId="rotterdam-m4h-pilot-project"
        opportunities={mockOpportunities}
        selectedOpportunityIds={[]}
        onSelectOpportunity={vi.fn()}
        onRejectOpportunity={onReject}
      />,
    );

    const input = screen.getByLabelText('Reason to reject opportunity: opp-cul-de-sac-reopen');
    fireEvent.change(input, {
      target: { value: 'Current cul-de-sac is needed for logistics turning radius.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reject suggestion: opp-cul-de-sac-reopen' }));

    expect(onReject).toHaveBeenCalledWith(
      'opp-cul-de-sac-reopen',
      'Current cul-de-sac is needed for logistics turning radius.',
    );
  });
});
