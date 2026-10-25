import { useState } from 'react';
import { useT } from '../i18n';
import type { Opportunity } from './siteIntelligenceTypes';

interface SiteOpportunitiesProps {
  opportunities: Opportunity[];
  selectedOpportunityIds: string[];
  rejectedOpportunityIds?: string[];
  rejectedReasons?: Record<string, string>;
  disabled?: boolean;
  onSelect: (opportunityId: string, selected: boolean) => void;
  onReject: (opportunityId: string, reason: string) => void;
  onUndoReject?: (opportunityId: string) => void;
}

export const SiteOpportunities = ({
  opportunities,
  selectedOpportunityIds,
  rejectedOpportunityIds = [],
  rejectedReasons = {},
  disabled = false,
  onSelect,
  onReject,
  onUndoReject,
}: SiteOpportunitiesProps) => {
  const t = useT();
  const [rejectionReasons, setRejectionReasons] = useState<Record<string, string>>({});

  if (opportunities.length === 0) {
    return (
      <section aria-labelledby="site-opportunities-heading" className="site-opportunities">
        <h3 id="site-opportunities-heading">{t('Site opportunities')}</h3>
        <p>{t('No persisted suggestions are available. A self-authored intent can be saved when matching references are ready.')}</p>
      </section>
    );
  }

  return (
    <section aria-labelledby="site-opportunities-heading" className="site-opportunities">
      <h3 id="site-opportunities-heading">{t('Site opportunities')}</h3>
      <p>{t('Suggestions are drafts. Selecting one adds an editable intent to this brief.')}</p>
      <ul style={{ display: 'grid', gap: '10px', listStyle: 'none', margin: 0, padding: 0 }}>
        {opportunities.map((opportunity) => {
          const isSelected = selectedOpportunityIds.includes(opportunity.id);
          const isRejected = rejectedOpportunityIds.includes(opportunity.id);
          const reason = rejectionReasons[opportunity.id] ?? '';
          return (
            <li
              key={opportunity.id}
              style={{
                border: '1px solid var(--border-subtle, #334155)',
                borderRadius: '8px',
                padding: '10px',
                background: 'var(--bg-app, #111827)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                <strong>{t(opportunity.kind.replaceAll('_', ' '))}</strong>
                <span style={{ color: 'var(--text-dim, #94a3b8)', fontSize: '11px' }}>{t(opportunity.origin)}</span>
              </div>
              <p style={{ margin: '8px 0' }}>{opportunity.statement}</p>
              {(opportunity.suggested_actions?.length ?? 0) > 0 && (
                <div>
                  <strong>{t('Possible measures')}</strong>
                  <ul>
                    {opportunity.suggested_actions?.map((action) => <li key={action}>{t(action.replaceAll('_', ' '))}</li>)}
                  </ul>
                </div>
              )}
              {(opportunity.uncertainties?.length ?? 0) > 0 && (
                <div>
                  <strong>{t('Needs validation')}</strong>
                  <ul>
                    {opportunity.uncertainties?.map((uncertainty) => <li key={uncertainty}>{t(uncertainty)}</li>)}
                  </ul>
                </div>
              )}
              {(opportunity.counterexamples?.length ?? 0) > 0 && (
                <details>
                  <summary>{t('Conditions and counterexamples')}</summary>
                  <ul>
                    {opportunity.counterexamples?.map((counterexample) => <li key={counterexample}>{t(counterexample)}</li>)}
                  </ul>
                </details>
              )}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '10px' }}>
                {isRejected ? (
                  <>
                    <span aria-live="polite">{t('Rejected in this draft')}</span>
                    {rejectedReasons[opportunity.id] && (
                      <span>{t('Rejection reason: {reason}', { reason: rejectedReasons[opportunity.id] })}</span>
                    )}
                    {onUndoReject && (
                      <button type="button" disabled={disabled} onClick={() => onUndoReject(opportunity.id)}>
                        {t('Undo rejection: {id}', { id: opportunity.id })}
                      </button>
                    )}
                  </>
                ) : (
                  <>
                    <button
                      type="button"
                      disabled={disabled}
                      aria-pressed={isSelected}
                      onClick={() => onSelect(opportunity.id, !isSelected)}
                    >
                      {isSelected
                        ? t('Remove from brief: {id}', { id: opportunity.id })
                        : t('Include in brief: {id}', { id: opportunity.id })}
                    </button>
                    <label style={{ display: 'grid', gap: '4px', flex: '1 1 180px' }}>
                      <span>{t('Reason to reject opportunity: {id}', { id: opportunity.id })}</span>
                      <input
                        maxLength={1000}
                        disabled={disabled}
                        onChange={(event) => setRejectionReasons((current) => ({
                          ...current,
                          [opportunity.id]: event.target.value,
                        }))}
                        value={reason}
                      />
                    </label>
                    <button
                      type="button"
                      disabled={disabled || !reason.trim()}
                      onClick={() => {
                        onReject(opportunity.id, reason.trim());
                        setRejectionReasons((current) => ({ ...current, [opportunity.id]: '' }));
                      }}
                    >
                      {t('Reject suggestion: {id}', { id: opportunity.id })}
                    </button>
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
};
