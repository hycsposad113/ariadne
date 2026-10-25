import React, { useEffect, useState, useCallback } from 'react';
import {
  CheckCircle,
  AlertTriangle,
  ShieldAlert,
  Scale,
  RefreshCw,
} from 'lucide-react';
import { useI18n, useT } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';
import {
  ScenarioComparisonDialog,
  type ComparisonScenarioInfo,
} from './ScenarioComparisonDialog';
import './ScenarioComparisonTable.css';

export interface ComparisonMetricRow {
  metric_id: string;
  label: string;
  unit: string;
  method?: string | null;
  data_gaps: string[];
  validation_status: Record<string, string>;
  status: 'COMPARABLE' | 'NOT_COMPARABLE';
  incompatibility_reasons?: string[];
  values: Record<string, number | null>;
}

export interface ScenarioDetailSummary {
  scenario_id: string;
  revision: number;
  status: string;
  strategy_id?: string;
  strategy_label: string;
  geometry_sha256?: string;
  provenance: string;
  valid: boolean;
  failure_reasons: string[];
  constraint_set_id?: string;
  is_baseline: boolean;
}

export interface ScenarioComparisonResult {
  status: 'COMPARABLE' | 'NOT_COMPARABLE';
  scenario_ids: string[];
  scenarios: ScenarioDetailSummary[];
  metrics: ComparisonMetricRow[];
  incompatibility_reasons: string[];
  eligibility_for_decision: {
    can_accept: boolean;
    status: 'READY_FOR_DECISION' | 'BLOCKED' | 'BLOCKED_PREVIEWS_ONLY' | 'BLOCKED_VALIDATION_FAILED' | 'BASELINE_SELECTED';
    reason: string | null;
    baseline_scenario_id: string | null;
  };
  ranking: null;
  overall_score: null;
  winner: null;
}

export interface ScenarioComparisonTableProps {
  apiBase: string;
  projectId?: string;
  scenarioIds: string[];
  onSelectScenarioForInspection?: (scenarioId: string) => void;
  onBaselineAccepted?: (baselineId: string) => void;
}

function formatMetricValue(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—';
  }
  if (unit === 'ratio') {
    return value.toFixed(2);
  }
  if (unit === 'm') {
    return `${value.toFixed(1)} m`;
  }
  if (unit === 'm2' || unit === 'm²') {
    return `${Math.round(value).toLocaleString()} m²`;
  }
  return String(value);
}

export const ScenarioComparisonTable: React.FC<ScenarioComparisonTableProps> = ({
  apiBase,
  projectId = 'rotterdam-m4h',
  scenarioIds,
  onSelectScenarioForInspection,
  onBaselineAccepted,
}) => {
  const t = useT();
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ScenarioComparisonResult | null>(null);
  const [dialogTarget, setDialogTarget] = useState<ComparisonScenarioInfo | null>(null);

  const fetchComparison = useCallback(async () => {
    if (scenarioIds.length < 2) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    const base = apiBase.replace(/\/$/, '');
    try {
      const response = await fetch(`${base}/api/v1/scenarios/comparison`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ scenario_ids: scenarioIds }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        throw new Error(errorData?.detail || `HTTP ${response.status}`);
      }
      const json: ScenarioComparisonResult = await response.json();
      setData(json);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Comparison failed to load');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase, scenarioIds]);

  useEffect(() => {
    fetchComparison();
  }, [fetchComparison]);

  if (scenarioIds.length < 2) {
    return (
      <div className="scenario-comparison-table-container">
        <div className="scenario-comparison-banner is-blocked">
          <AlertTriangle size={16} />
          <div>
            <h4>{t("Select at least two scenarios")}</h4>
            <p style={{ margin: 0 }}>
              {t("Formal comparison requires at least two scenarios sharing the same spatial denominator and measurement rules.")}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const eligibility = data?.eligibility_for_decision;
  const isComparable = data?.status === 'COMPARABLE';

  return (
    <div className="scenario-comparison-table-container" data-testid="scenario-comparison-table-container">
      {/* Header bar */}
      <header className="scenario-comparison-header">
        <div>
          <h2>
            <Scale size={18} />
            {t("Formal proposal comparison")}
          </h2>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {t("Strict comparison contract: identical denominator and methods without ranking or winner")}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {data && (
            <span
              className={`scenario-comparison-status-badge ${
                isComparable ? 'is-comparable' : 'is-not-comparable'
              }`}
              data-testid="comparison-status-badge"
            >
              {isComparable ? (
                <>
                  <CheckCircle size={14} />
                  {t("COMPARABLE · Same denominator & rules")}
                </>
              ) : (
                <>
                  <AlertTriangle size={14} />
                  {t("NOT_COMPARABLE · Basis or method mismatch")}
                </>
              )}
            </span>
          )}
          <button
            type="button"
            className="scenario-accept-btn"
            style={{ marginTop: 0 }}
            onClick={fetchComparison}
            disabled={loading}
            aria-label={t("Refresh comparison")}
          >
            <RefreshCw size={13} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </header>

      {/* Loading & Error States */}
      {loading && <p role="status">{t("Loading comparison table…")}</p>}
      {error && (
        <div className="scenario-comparison-banner is-not-comparable" role="alert">
          <AlertTriangle size={16} />
          <div>
            <h4>{t("Comparison error")}</h4>
            <p style={{ margin: 0 }}>{error}</p>
          </div>
        </div>
      )}

      {/* Stop Loss / Eligibility Banners */}
      {data && (
        <>
          {eligibility?.status === 'BLOCKED_PREVIEWS_ONLY' && (
            <div className="scenario-comparison-banner is-blocked" data-testid="preview-blocked-banner">
              <ShieldAlert size={18} style={{ color: 'var(--accent-amber, #f59e0b)', flexShrink: 0 }} />
              <div>
                <h4>{t("Acceptance entrance closed: Formal proposals required")}</h4>
                <p style={{ margin: 0 }}>
                  {zh
                    ? '目前方案為未批准之探索預覽或測試資料。預覽不可接受為正式基準方案。正式提案將由 W6-6 產出。'
                    : 'The current scenarios are unapproved exploratory previews or test fixtures. Previews cannot be accepted as formal baseline. Formal proposals are generated in W6-6.'}
                </p>
              </div>
            </div>
          )}

          {eligibility?.status === 'BASELINE_SELECTED' && (
            <div className="scenario-comparison-banner is-baseline-selected" data-testid="baseline-selected-banner">
              <CheckCircle size={18} style={{ color: 'var(--accent-emerald, #10b981)', flexShrink: 0 }} />
              <div>
                <h4>
                  {t("Project baseline adopted: {id}", { id: eligibility.baseline_scenario_id || '' })}
                </h4>
                <p style={{ margin: 0 }}>
                  {t("An immutable baseline design has been confirmed by HumanDecision. Other proposals remain in the ledger as rejected.")}
                </p>
              </div>
            </div>
          )}

          {!isComparable && data.incompatibility_reasons.length > 0 && (
            <div className="scenario-comparison-banner is-not-comparable" data-testid="incompatibility-banner">
              <AlertTriangle size={18} style={{ color: 'var(--accent-rose, #f43f5e)', flexShrink: 0 }} />
              <div>
                <h4>{t("Inconsistent comparison basis — decision entrance closed")}</h4>
                <p style={{ margin: 0 }}>
                  {t("Scenarios cannot be fairly compared because of underlying basis or method divergence:")}
                </p>
                <ul>
                  {data.incompatibility_reasons.map((reason, index) => (
                    <li key={index}>{t(reason)}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </>
      )}

      {/* Main Table */}
      {data && (
        <div className="scenario-table-wrapper">
          <table className="scenario-comparison-table" aria-label={t("Proposal comparison table")}>
            <thead>
              <tr>
                <th style={{ width: '22%' }}>{t("Metric & Method")}</th>
                <th style={{ width: '12%' }}>{t("Unit")}</th>
                {data.scenarios.map(scen => {
                  const isAccepted = scen.is_baseline || scen.status === 'accepted';
                  const isRejected = scen.status === 'rejected';
                  const isFormal = scen.provenance === 'FORMAL_PROPOSAL';

                  return (
                    <th key={scen.scenario_id} style={{ minWidth: 160 }}>
                      <div className="scenario-col-header">
                        <div className="scenario-col-title">
                          {t(scen.strategy_label)}
                        </div>
                        <div className="scenario-col-id">
                          {scen.scenario_id} · rev {scen.revision}
                        </div>

                        <div className="scenario-col-chips">
                          {isAccepted && (
                            <span className="chip chip--preserve" data-testid={`chip-baseline-${scen.scenario_id}`}>
                              {zh ? '基準' : 'Baseline'}
                            </span>
                          )}
                          {isRejected && (
                            <span className="chip chip--undecided" data-testid={`chip-rejected-${scen.scenario_id}`} title={scen.failure_reasons.join('; ')}>
                              {zh ? '已駁回' : 'Rejected'}
                            </span>
                          )}
                          {!isAccepted && !isRejected && isFormal && (
                            <span className="chip chip--editable">
                              {zh ? '正式提案' : 'Formal proposal'}
                            </span>
                          )}
                          {!isFormal && (
                            <StatusBadge status={scen.provenance} language={language} className="chip chip--undecided" />
                          )}
                        </div>

                        {/* Acceptance Entrance Button */}
                        {!isAccepted && !isRejected && (
                          <button
                            type="button"
                            className="scenario-accept-btn"
                            disabled={!eligibility?.can_accept}
                            title={
                              !eligibility?.can_accept
                                ? t(eligibility?.reason || "Decision entrance is closed")
                                : t("Select this proposal as official project baseline")
                            }
                            onClick={() => {
                              setDialogTarget({
                                scenario_id: scen.scenario_id,
                                strategy_label: scen.strategy_label,
                                revision: scen.revision,
                                geometry_sha256: scen.geometry_sha256,
                                status: scen.status,
                                is_baseline: scen.is_baseline,
                              });
                            }}
                            data-testid={`btn-accept-${scen.scenario_id}`}
                          >
                            {t("Accept as Baseline")}
                          </button>
                        )}

                        {onSelectScenarioForInspection && (
                          <button
                            type="button"
                            style={{
                              marginTop: 4,
                              background: 'transparent',
                              border: 'none',
                              color: 'var(--accent-cyan)',
                              fontSize: 11,
                              cursor: 'pointer',
                              textAlign: 'left',
                              padding: 0,
                            }}
                            onClick={() => onSelectScenarioForInspection(scen.scenario_id)}
                          >
                            {t("Inspect 2D/3D")}
                          </button>
                        )}
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {data.metrics.map(metric => (
                <tr key={metric.metric_id} data-testid={`metric-row-${metric.metric_id}`}>
                  <th scope="row">
                    <div style={{ fontWeight: 650, color: 'var(--text-main)' }}>
                      {t(metric.label)}
                    </div>
                    {metric.method && (
                      <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 2 }}>
                        {t(metric.method)}
                      </div>
                    )}
                    {metric.data_gaps.length > 0 && (
                      <div className="scenario-metric-gaps">
                        {metric.data_gaps.join('；')}
                      </div>
                    )}
                  </th>
                  <td>
                    <span>{metric.unit}</span>
                    <br />
                    <small style={{ color: metric.status === 'COMPARABLE' ? 'var(--accent-emerald)' : 'var(--accent-rose)', fontSize: 10 }}>
                      {metric.status}
                    </small>
                  </td>
                  {data.scenarios.map(scen => {
                    const val = metric.values[scen.scenario_id];
                    const valStatus = (metric.validation_status[scen.scenario_id] || 'UNKNOWN').toLowerCase();
                    return (
                      <td key={scen.scenario_id}>
                        <div className="scenario-metric-cell">
                          <span className="scenario-metric-value">
                            {formatMetricValue(val, metric.unit)}
                          </span>
                          <span
                            className={`scenario-validation-badge is-${valStatus}`}
                            title={`${t("Validation:")} ${valStatus}`}
                          >
                            {valStatus}
                          </span>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer / Core Law Compliance */}
      <footer className="scenario-comparison-footer-notice">
        <span>
          <strong>{t("Core Law:")}</strong> {t("Deterministic tools calculate · Validators verify · Humans decide")}
        </span>
        <span style={{ color: 'var(--text-dim)' }}>
          {t("No automated ranking · No overall score · Designer retains final decision authority")}
        </span>
      </footer>

      {/* Decision Dialog Modal */}
      {dialogTarget && data && (
        <ScenarioComparisonDialog
          isOpen={Boolean(dialogTarget)}
          projectId={projectId}
          allScenarios={data.scenarios.map(s => ({
            scenario_id: s.scenario_id,
            strategy_label: s.strategy_label,
            revision: s.revision,
            geometry_sha256: s.geometry_sha256,
            status: s.status,
            is_baseline: s.is_baseline,
          }))}
          acceptedScenario={dialogTarget}
          apiBase={apiBase}
          onClose={() => setDialogTarget(null)}
          onSuccess={result => {
            setDialogTarget(null);
            onBaselineAccepted?.(result.baseline_scenario_id);
            fetchComparison();
          }}
        />
      )}
    </div>
  );
};
