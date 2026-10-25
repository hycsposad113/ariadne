import React, { useEffect, useState } from 'react';
import { useI18n, useT } from '../i18n';
import { SiteOpportunities } from './SiteOpportunities';
import type { Opportunity } from './siteIntelligenceTypes';

export interface SpatialProblemItem {
  problem_id: string;
  title: string;
  severity: string;
  category: string;
  status?: string;
  claim?: string;
  evidence_summary?: string;
  limitations?: string[];
}

export interface SiteProblemsOpportunitiesProps {
  projectId: string;
  apiBase?: string;
  expectedStudyAreaId?: string | null;
  opportunities?: Opportunity[];
  selectedOpportunityIds?: string[];
  rejectedOpportunityIds?: string[];
  rejectedReasons?: Record<string, string>;
  disabled?: boolean;
  onSelectOpportunity: (opportunityId: string, selected: boolean) => void;
  onRejectOpportunity: (opportunityId: string, reason: string) => void;
  onUndoRejectOpportunity?: (opportunityId: string) => void;
  onNavigateToBrief?: () => void;
}

type ProblemReportStatement = {
  problem_id?: unknown;
  title_zh?: unknown;
  title?: unknown;
  severity_code?: unknown;
  status?: unknown;
  category?: unknown;
  summary_zh?: unknown;
  evidence_summary_zh?: unknown;
  claim?: unknown;
  statement?: unknown;
  limitations?: unknown;
  uncertainties_zh?: unknown;
};

type ProblemReportResponse = {
  summary?: { study_area_id?: unknown };
  statements?: unknown;
};

type ProblemReportState = 'LOADING' | 'ANALYSIS_DEFINED' | 'NOT_READY' | 'BLOCKED';

const asStringList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

export const SiteProblemsOpportunities: React.FC<SiteProblemsOpportunitiesProps> = ({
  projectId,
  apiBase = '',
  expectedStudyAreaId = null,
  opportunities = [],
  selectedOpportunityIds = [],
  rejectedOpportunityIds = [],
  rejectedReasons = {},
  disabled = false,
  onSelectOpportunity,
  onRejectOpportunity,
  onUndoRejectOpportunity,
  onNavigateToBrief,
}) => {
  const t = useT();
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  const [problems, setProblems] = useState<SpatialProblemItem[]>([]);
  const [problemReportState, setProblemReportState] = useState<ProblemReportState>('LOADING');
  const [expandedProblemId, setExpandedProblemId] = useState<string | null>(null);

  useEffect(() => {
    if (!apiBase || !projectId || !expectedStudyAreaId) {
      setProblems([]);
      setProblemReportState('NOT_READY');
      return;
    }
    let cancelled = false;
    setProblems([]);
    setProblemReportState('LOADING');
    const fetchProblems = async () => {
      try {
        const res = await fetch(`${apiBase}/api/v1/projects/${encodeURIComponent(projectId)}/problems`);
        if (!res.ok) {
          if (!cancelled) setProblemReportState('NOT_READY');
          return;
        }
        const data = await res.json() as ProblemReportResponse;
        if (data.summary?.study_area_id !== expectedStudyAreaId) {
          if (!cancelled) setProblemReportState(data.summary?.study_area_id ? 'BLOCKED' : 'NOT_READY');
          return;
        }
        if (!Array.isArray(data.statements) || data.statements.length === 0) {
          if (!cancelled) setProblemReportState('NOT_READY');
          return;
        }
        const loaded = data.statements
          .filter((value): value is ProblemReportStatement => Boolean(value) && typeof value === 'object')
          .map((statement) => {
            const problemId = typeof statement.problem_id === 'string' ? statement.problem_id : 'unknown-problem';
            const summary = [statement.summary_zh, statement.evidence_summary_zh, statement.claim, statement.statement]
              .find((value): value is string => typeof value === 'string' && value.length > 0);
            return {
              problem_id: problemId,
              title: typeof statement.title_zh === 'string'
                ? statement.title_zh
                : typeof statement.title === 'string' ? statement.title : problemId,
              severity: typeof statement.severity_code === 'string' ? statement.severity_code : 'UNRATED',
              category: typeof statement.category === 'string' ? statement.category : 'GENERAL',
              status: typeof statement.status === 'string' ? statement.status : 'ANALYSIS_DEFINED',
              claim: summary,
              evidence_summary: typeof statement.evidence_summary_zh === 'string'
                ? statement.evidence_summary_zh
                : undefined,
              limitations: [...asStringList(statement.limitations), ...asStringList(statement.uncertainties_zh)],
            };
          });
        if (!cancelled) {
          if (loaded.length === 0) {
            setProblemReportState('NOT_READY');
          } else {
            setProblems(loaded);
            setProblemReportState('ANALYSIS_DEFINED');
          }
        }
      } catch {
        if (!cancelled) setProblemReportState('NOT_READY');
      }
    };
    void fetchProblems();
    return () => {
      cancelled = true;
    };
  }, [apiBase, expectedStudyAreaId, projectId]);

  return (
    <section aria-labelledby="site-problems-opportunities-heading" className="site-problems-opportunities" style={{ display: 'grid', gap: '16px', padding: '12px' }}>
      <header style={{ borderBottom: '1px solid var(--border-subtle, #334155)', paddingBottom: '8px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 id="site-problems-opportunities-heading" style={{ margin: 0, fontSize: '15px', color: 'var(--accent-cyan, #22d3ee)' }}>
            {t('Site Problems & Opportunities')}
          </h2>
          {onNavigateToBrief && (
            <button
              type="button"
              className="design-brief-nav-btn"
              onClick={onNavigateToBrief}
              style={{
                background: 'var(--bg-hover, #1e293b)',
                border: '1px solid var(--border-subtle, #334155)',
                color: 'var(--accent-cyan, #22d3ee)',
                borderRadius: '4px',
                padding: '4px 8px',
                fontSize: '11px',
                cursor: 'pointer',
              }}
            >
              {t('Go to Design Brief')} →
            </button>
          )}
        </div>
        <p style={{ margin: '4px 0 0 0', fontSize: '11px', color: 'var(--text-dim, #94a3b8)', lineHeight: 1.4 }}>
          {t('Suggestions and problems are exploratory observations. Selecting an opportunity creates an editable draft intent in the Design Brief and does NOT activate a constraint.')}
        </p>
      </header>

      {/* Spatial Problems section */}
      <section aria-labelledby="defined-problems-heading">
        <h3 id="defined-problems-heading" style={{ margin: '0 0 8px 0', fontSize: '13px', color: 'var(--text-main, #f8fafc)' }}>
          {t('Defined Spatial Problems (Task S)')}
        </h3>
        {problemReportState !== 'ANALYSIS_DEFINED' && (
          <p role="status" style={{ fontSize: '11px', color: 'var(--text-dim, #94a3b8)' }}>
            {problemReportState === 'LOADING' ? (
              t('Loading the persisted problem report…')
            ) : problemReportState === 'BLOCKED' ? (
              <>
                {zh ? '已封鎖：問題報告與當前選取的基地範圍不相符。' : 'Blocked: The problem report does not match the active StudyArea.'}
                <span className="sr-only" style={{ display: 'none' }}>BLOCKED</span>
              </>
            ) : (
              <>
                {zh ? '尚未就緒：找不到相符的已留存問題報告。' : 'Not ready: A matching persisted problem report is unavailable.'}
                <span className="sr-only" style={{ display: 'none' }}>NOT_READY</span>
              </>
            )}
          </p>
        )}
        <ul style={{ display: 'grid', gap: '8px', listStyle: 'none', margin: 0, padding: 0 }}>
          {problems.map((prob) => {
            const isProb6 = prob.problem_id === 'prob-06-unclassified-residual-ground';
            const isExpanded = expandedProblemId === prob.problem_id;
            return (
              <li
                key={prob.problem_id}
                style={{
                  border: isProb6 ? '1px dashed #f59e0b' : '1px solid var(--border-subtle, #334155)',
                  borderRadius: '6px',
                  padding: '8px 10px',
                  background: isProb6 ? 'rgba(245, 158, 11, 0.05)' : 'var(--bg-app, #111827)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
                  <button
                    type="button"
                    onClick={() => setExpandedProblemId(isExpanded ? null : prob.problem_id)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: 'var(--text-main, #f8fafc)',
                      fontSize: '12px',
                      fontWeight: 600,
                      textAlign: 'left',
                      padding: 0,
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '4px',
                    }}
                  >
                    <span>{isExpanded ? '▾' : '▸'}</span>
                  <span>{prob.problem_id}: {t(prob.title)}</span>
                </button>
                  <div style={{ display: 'grid', justifyItems: 'end', gap: '3px' }}>
                    <span style={{
                      fontSize: '10px',
                      fontWeight: 600,
                      padding: '2px 6px',
                      borderRadius: '4px',
                      backgroundColor: isProb6 ? '#78350f' : '#1e3a8a',
                      color: isProb6 ? '#fef3c7' : '#ffffff',
                    }}>{t(prob.severity)}</span>
                    <span style={{ color: 'var(--text-dim, #94a3b8)', fontSize: '10px' }}>{t(prob.status || 'ANALYSIS_DEFINED')}</span>
                  </div>
                </div>
                {prob.claim && (
                  <p style={{ margin: '6px 0 0 0', fontSize: '11px', color: 'var(--text-dim, #94a3b8)', lineHeight: 1.4 }}>
                    {prob.claim}
                  </p>
                )}
                {prob.evidence_summary && prob.claim !== prob.evidence_summary && (
                  <p style={{ margin: '6px 0 0 0', fontSize: '11px', color: 'var(--text-dim, #94a3b8)', lineHeight: 1.4 }}>
                    {prob.evidence_summary}
                  </p>
                )}
                {isProb6 && (
                  <div
                    style={{
                      marginTop: '6px',
                      padding: '6px 8px',
                      background: 'rgba(245, 158, 11, 0.1)',
                      borderLeft: '3px solid #f59e0b',
                      fontSize: '11px',
                      color: '#fbbf24',
                    }}
                  >
                    <strong>{t('Limitation notice')}:</strong>{' '}
                    {t('Geometric difference only (StudyArea minus BGT water and BAG footprints). No surface material, canopy, vacancy, ownership, or land use data. Not an approved vacancy or development zone.')}
                  </div>
                )}
                {isExpanded && prob.limitations && prob.limitations.length > 0 && (
                  <ul style={{ margin: '6px 0 0 0', paddingLeft: '16px', fontSize: '11px', color: 'var(--text-dim, #94a3b8)' }}>
                    {prob.limitations.map((lim, idx) => (
                      <li key={idx}>{lim}</li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </section>

      {/* Candidate Opportunities (A3) */}
      <section aria-labelledby="site-candidate-opportunities-heading">
        <h3 id="site-candidate-opportunities-heading" style={{ margin: '0 0 8px 0', fontSize: '13px', color: 'var(--text-main, #f8fafc)' }}>
          {t('Candidate Opportunities (A3)')}
        </h3>
        <SiteOpportunities
          opportunities={opportunities}
          selectedOpportunityIds={selectedOpportunityIds}
          rejectedOpportunityIds={rejectedOpportunityIds}
          rejectedReasons={rejectedReasons}
          disabled={disabled}
          onSelect={onSelectOpportunity}
          onReject={onRejectOpportunity}
          onUndoReject={onUndoRejectOpportunity}
        />
      </section>
    </section>
  );
};
