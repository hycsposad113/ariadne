import React, { useEffect, useRef } from 'react';
import { ShieldCheck } from 'lucide-react';
import { useI18n, useT } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';
import type { EvidenceCard, EvidenceGap } from '../types';

const LEGACY_OBSERVATION_STATUS = 'VERIFIED_OBSERVATION';
const SOURCE_ALIGNED_COVERAGE_LIMITED_STATUS = 'SOURCE_ALIGNED_COVERAGE_LIMITED';

interface PanelEvidenceAndCriticProps {
  evidenceCards: EvidenceCard[];
  evidenceCardsStatus: string;
  evidenceGaps: EvidenceGap[];
  focusedCardId?: string | null;
}

export const PanelEvidenceAndCritic: React.FC<PanelEvidenceAndCriticProps> = ({
  evidenceCards,
  evidenceCardsStatus,
  evidenceGaps,
  focusedCardId = null,
}) => {
  const t = useT();
  const { language } = useI18n();
  const cardElements = useRef(new Map<string, HTMLElement>());

  useEffect(() => {
    if (!focusedCardId) return;
    const card = cardElements.current.get(focusedCardId);
    card?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
  }, [focusedCardId, evidenceCards]);

  return (
    <div className="site-facts-panel" style={{ display: 'flex', flexDirection: 'column', minHeight: '100%', backgroundColor: 'var(--bg-surface)' }}>
      <div className="site-facts-panel__heading" style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '10px', borderBottom: '1px solid var(--border-subtle)', backgroundColor: 'var(--bg-app)', color: 'var(--accent-cyan)', fontSize: '11px', fontWeight: 600 }}>
        <ShieldCheck size={14} aria-hidden="true" />
        <h2 style={{ margin: 0, fontSize: 'inherit', fontWeight: 'inherit' }}>{t('Site Facts')} ({evidenceCards.length})</h2>
      </div>
      <div data-testid="site-facts-status" role="status" style={{ padding: '6px 12px', borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-dim)', fontSize: '10px' }}>
        {t('Evidence status:')} <StatusBadge status={evidenceCardsStatus} language={language} />
      </div>
      <div className="site-facts-panel__cards" style={{ flex: 1, overflowY: 'auto', padding: '12px' }}>
        {evidenceGaps.length > 0 && (
          <div id="evidence-gaps" role="status" style={{ padding: '10px', marginBottom: '10px', border: '1px solid var(--accent-amber)', borderRadius: 'var(--radius-sm)', color: 'var(--accent-amber)', fontSize: '10px', lineHeight: 1.45 }}>
            <strong>{t('Known unknowns and blocked conclusions')}</strong>
            {evidenceGaps.map(gap => (
              <div key={gap.topic} style={{ marginTop: '5px' }}><b><StatusBadge status={gap.status} language={language} />: {t(gap.topic)}</b> — {t(gap.reason)}</div>
            ))}
          </div>
        )}
        <div style={{ marginBottom: '8px', color: 'var(--text-dim)', fontSize: '10px' }}>{t('Information')}</div>

        {evidenceCards.map(card => {
          const isUnavailable = ![
            LEGACY_OBSERVATION_STATUS,
            SOURCE_ALIGNED_COVERAGE_LIMITED_STATUS,
          ].includes(card.status);
          const isFocused = focusedCardId === card.card_id;

          return (
            <article
              key={card.card_id}
              id={`card-${card.card_id}`}
              data-testid={`site-fact-card-${card.card_id}`}
              data-ariadne-focused={isFocused ? 'true' : 'false'}
              ref={element => {
                if (element) cardElements.current.set(card.card_id, element);
                else cardElements.current.delete(card.card_id);
              }}
              style={{
                padding: '12px',
                marginBottom: '10px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: isFocused ? 'rgba(56, 189, 248, 0.08)' : 'var(--bg-surface-elevated)',
                border: `1px solid ${isFocused ? 'var(--accent-cyan)' : isUnavailable ? 'rgba(244, 63, 94, 0.3)' : 'var(--border-subtle)'}`,
                boxShadow: isFocused ? '0 0 0 2px rgba(56, 189, 248, 0.16)' : undefined,
                scrollMarginBlock: '16px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                <span style={{ fontWeight: 600, fontSize: '12px', color: 'var(--text-main)' }}>{t(card.metric_name)}</span>
                <span style={{
                  fontSize: '9px',
                  fontFamily: 'var(--font-mono)',
                  padding: '2px 5px',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: isUnavailable ? 'rgba(244, 63, 94, 0.15)' : 'rgba(16, 185, 129, 0.15)',
                  color: isUnavailable ? 'var(--accent-rose)' : 'var(--accent-emerald)',
                  border: `1px solid ${isUnavailable ? 'rgba(244, 63, 94, 0.3)' : 'rgba(16, 185, 129, 0.3)'}`,
                }}>
                  {typeof card.confidence === 'string'
                    ? <StatusBadge status={card.confidence} language={language} />
                    : (card.confidence as any)?.level
                      ? <StatusBadge status={(card.confidence as any).level} language={language} />
                      : t('Unknown')}
                </span>
              </div>

              <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{t(isUnavailable ? 'Needs your decision' : 'Information')}</div>
              <div style={{ fontSize: '17px', fontWeight: 700, fontFamily: 'var(--font-mono)', color: isUnavailable ? 'var(--accent-rose)' : 'var(--accent-cyan)', margin: '4px 0' }}>
                {typeof card.value === 'number' ? card.value.toLocaleString() : String(card.value)}
                <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: '4px', fontWeight: 400 }}>{t(card.unit)}</span>
              </div>
              <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px', lineHeight: 1.4 }}>
                {card.limitations.map(item => t(item)).join(' ')}
              </div>

              <details style={{ marginTop: '8px', fontSize: '9px', color: 'var(--text-dim)', lineHeight: 1.45 }}>
                <summary style={{ cursor: 'pointer' }}>{t('Source, method, scope and hashes')}</summary>
                <div style={{ marginTop: '5px', overflowWrap: 'anywhere' }}>
                  <div>{t('Status:')} <StatusBadge status={card.status} language={language} /> · {card.crs} · {card.study_area_id} {t('rev')} {card.study_area_revision} · {card.source_package_revision}</div>
                  <div>{t('Algorithm:')} {card.algorithm_version}</div>
                  {card.method_definition && <div>{t('Method definition:')} {t(card.method_definition)}</div>}
                  {card.method_diagnostics && <div>{t('Method diagnostics:')} {JSON.stringify(card.method_diagnostics)}</div>}
                  <div>{t('Query bounds:')} {card.query_bounds.map(bounds => JSON.stringify(bounds.projected_bounds || bounds.crs84_bounds || bounds)).join(' · ')}</div>
                  <div>{t('Feature IDs (')}{card.source_feature_ids.length}): {card.source_feature_ids.slice(0, 8).join(', ')}{card.source_feature_ids.length > 8 ? ', …' : ''}</div>
                  <div>{t('Artifacts:')} {card.source_artifact_ids.join(', ')}</div>
                  <div>{t('DatasetSnapshots:')} {card.dataset_snapshot_ids.join(', ')}</div>
                  <div>{t('Input SHA-256:')} {card.input_sha256}</div>
                  <div>{t('Output SHA-256:')} {card.output_sha256}</div>
                </div>
              </details>

              <div style={{ marginTop: '6px', fontSize: '9px', fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                {t('ID:')} {card.card_id}
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
};
