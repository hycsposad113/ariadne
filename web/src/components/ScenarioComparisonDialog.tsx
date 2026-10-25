import React, { useEffect, useState } from 'react';
import { X, CheckCircle, Ban, AlertCircle } from 'lucide-react';
import { useT } from '../i18n';
import { getActorSessionId } from '../utils/actorProvenance';
import './HumanDecisionDialog.css';

export interface ComparisonScenarioInfo {
  scenario_id: string;
  strategy_label: string;
  revision: number;
  geometry_sha256?: string;
  status?: string;
  is_baseline?: boolean;
}

export interface ScenarioComparisonDialogProps {
  isOpen: boolean;
  projectId: string;
  allScenarios: ComparisonScenarioInfo[];
  acceptedScenario?: ComparisonScenarioInfo;
  initialSelectedId?: string;
  apiBase: string;
  onClose: () => void;
  onSuccess: (result: { baseline_scenario_id: string; message: string }) => void;
}

export const ScenarioComparisonDialog: React.FC<ScenarioComparisonDialogProps> = ({
  isOpen,
  projectId,
  allScenarios,
  acceptedScenario,
  initialSelectedId,
  apiBase,
  onClose,
  onSuccess,
}) => {
  if (!isOpen) return null;
  return (
    <ScenarioComparisonDialogForm
      projectId={projectId}
      allScenarios={allScenarios}
      acceptedScenario={acceptedScenario}
      initialSelectedId={initialSelectedId}
      apiBase={apiBase}
      onClose={onClose}
      onSuccess={onSuccess}
    />
  );
};

interface FieldErrors {
  baseline?: string;
  acceptanceReason?: string;
  rejectedReasons: Record<string, string>;
  decisionKey?: string;
  summary: string[];
}

const ScenarioComparisonDialogForm: React.FC<Omit<ScenarioComparisonDialogProps, 'isOpen'>> = ({
  projectId,
  allScenarios,
  acceptedScenario: _acceptedScenario,
  initialSelectedId: _initialSelectedId,
  apiBase,
  onClose,
  onSuccess,
}) => {
  const t = useT();
  // Item 1: No scheme may be preselected. Initial baseline selection = none.
  const [selectedBaselineId, setSelectedBaselineId] = useState<string>('');
  const [decisionKey, setDecisionKey] = useState('');
  const [acceptanceReason, setAcceptanceReason] = useState('');
  const [rejectedReasons, setRejectedReasons] = useState<Record<string, string>>({});
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({
    rejectedReasons: {},
    summary: [],
  });
  const [serverError, setServerError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const currentAccepted = selectedBaselineId
    ? (allScenarios.find(s => s.scenario_id === selectedBaselineId) ?? null)
    : null;
  const rejectedScenarios = selectedBaselineId
    ? allScenarios.filter(s => s.scenario_id !== selectedBaselineId)
    : [];

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isSubmitting) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isSubmitting, onClose]);

  const updateRejectionReason = (id: string, reason: string) => {
    setRejectedReasons(prev => ({ ...prev, [id]: reason }));
    if (reason.trim()) {
      setFieldErrors(prev => {
        const nextRej = { ...prev.rejectedReasons };
        delete nextRej[id];
        return {
          ...prev,
          rejectedReasons: nextRej,
          summary: prev.summary.filter(msg => !msg.includes(id)),
        };
      });
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setServerError(null);

    const errors: FieldErrors = {
      rejectedReasons: {},
      summary: [],
    };

    if (!selectedBaselineId) {
      const msg = t("Please select a baseline scheme.");
      errors.baseline = msg;
      errors.summary.push(msg);
    }

    if (!acceptanceReason.trim()) {
      const msg = t("Baseline acceptance reason is required.");
      errors.acceptanceReason = msg;
      errors.summary.push(msg);
    }

    if (selectedBaselineId) {
      for (const scen of rejectedScenarios) {
        const reason = (rejectedReasons[scen.scenario_id] || '').trim();
        if (!reason) {
          const msg = t("Rejection reason for {label} ({id}) is required.", {
            label: scen.strategy_label,
            id: scen.scenario_id,
          });
          errors.rejectedReasons[scen.scenario_id] = msg;
          errors.summary.push(msg);
        }
      }
    }

    if (!decisionKey.trim()) {
      const msg = t("Decision key is required.");
      errors.decisionKey = msg;
      errors.summary.push(msg);
    }

    if (errors.summary.length > 0) {
      setFieldErrors(errors);
      return;
    }

    setFieldErrors({ rejectedReasons: {}, summary: [] });
    setIsSubmitting(true);

    const base = apiBase.replace(/\/$/, '');
    try {
      const response = await fetch(`${base}/api/v1/scenarios/comparison/decision`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({
          project_id: projectId,
          scenario_ids: allScenarios.map(s => s.scenario_id),
          accepted_scenario_id: selectedBaselineId,
          acceptance_reason: acceptanceReason.trim(),
          rejected_reasons: rejectedReasons,
          decision_key: decisionKey,
          actor_session_id: getActorSessionId(),
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        let detail = errorData?.detail || response.statusText;
        if (typeof detail === 'object') {
          detail = JSON.stringify(detail);
        }
        if (!detail) {
          detail = `Decision submission failed (${response.status}).`;
        }
        setDecisionKey('');
        setServerError(detail);
        return;
      }

      const result = await response.json();
      setDecisionKey('');
      onSuccess(result);
      onClose();
    } catch (caught) {
      setDecisionKey('');
      setServerError(caught instanceof Error ? caught.message : t("The decision was rejected."));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="human-decision-backdrop">
      <section
        aria-labelledby="comparison-decision-title"
        aria-modal="true"
        className="human-decision-dialog"
        role="dialog"
      >
        <header className="human-decision-dialog__header">
          <div>
            <h2 id="comparison-decision-title">{t("Confirm baseline proposal & decisions")}</h2>
            <p>{t("Record immutable baseline and human decisions in design ledger")}</p>
          </div>
          <button
            aria-label={t("Close decision dialog")}
            className="human-decision-dialog__close"
            disabled={isSubmitting}
            onClick={onClose}
            type="button"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <form onSubmit={handleSubmit} noValidate>
          <div className="human-decision-dialog__body">
            {/* Baseline selection radio group */}
            <div className="human-decision-dialog__field">
              <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>
                {t("Choose baseline scheme:")} *
              </span>
              <div style={{ display: 'grid', gap: 6, marginTop: 4 }}>
                {allScenarios.map(s => (
                  <label
                    key={s.scenario_id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      padding: '8px 10px',
                      background: selectedBaselineId === s.scenario_id ? 'rgba(56, 189, 248, 0.15)' : 'var(--bg-surface-elevated)',
                      border: `1px solid ${selectedBaselineId === s.scenario_id ? 'var(--accent-cyan)' : 'var(--border-subtle)'}`,
                      borderRadius: 'var(--radius-sm)',
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      name="baseline-choice"
                      className="human-decision-dialog__radio"
                      value={s.scenario_id}
                      checked={selectedBaselineId === s.scenario_id}
                      onChange={() => {
                        setSelectedBaselineId(s.scenario_id);
                        setFieldErrors(prev => ({
                          ...prev,
                          baseline: undefined,
                          summary: prev.summary.filter(msg => msg !== t("Please select a baseline scheme.")),
                        }));
                      }}
                      disabled={isSubmitting}
                      style={{
                        width: 16,
                        minWidth: 16,
                        maxWidth: 16,
                        height: 16,
                        minHeight: 16,
                        maxHeight: 16,
                        margin: '0 4px 0 0',
                        padding: 0,
                        flexShrink: 0,
                        cursor: 'pointer',
                        accentColor: 'var(--accent-cyan, #0ea5e9)',
                      }}
                    />
                    <span style={{ fontWeight: 600, color: 'var(--text-main)', fontSize: 12 }}>
                      {s.strategy_label}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>({s.scenario_id})</span>
                  </label>
                ))}
              </div>
              {fieldErrors.baseline && (
                <div className="human-decision-dialog__field-error" role="alert" data-testid="error-baseline" style={{ color: 'var(--accent-rose, #f43f5e)', fontSize: 12, marginTop: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <AlertCircle size={14} />
                  <span>{fieldErrors.baseline}</span>
                </div>
              )}
            </div>

            {/* Adopted Baseline Summary Card (appears only after baseline radio chosen) */}
            {selectedBaselineId && currentAccepted && (
              <div className="human-decision-dialog__summary-card" data-testid="accepted-baseline-card">
                <div className="human-decision-dialog__card-header">
                  <strong style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--accent-emerald, #10b981)' }}>
                    <CheckCircle size={16} /> {t("Adopted baseline:")} {currentAccepted.strategy_label}
                  </strong>
                  <span className="chip chip--preserve">{t("Baseline")}</span>
                </div>
                <dl className="human-decision-dialog__target" style={{ margin: 0 }}>
                  <div><dt>{t("Scenario ID")}</dt><dd>{currentAccepted.scenario_id}</dd></div>
                  <div><dt>{t("Revision")}</dt><dd>{currentAccepted.revision}</dd></div>
                  <div style={{ gridColumn: 'span 2' }}>
                    <dt>{t("Geometry hash")}</dt>
                    <dd className="mono">{currentAccepted.geometry_sha256 || t("Missing hash — decision blocked")}</dd>
                  </div>
                </dl>
              </div>
            )}

            {/* Acceptance Reason Field */}
            <label className="human-decision-dialog__field">
              <span>{t("Baseline acceptance reason")} *</span>
              <textarea
                autoComplete="off"
                maxLength={2000}
                minLength={1}
                placeholder={t("Explain why this proposal is accepted as baseline (e.g., optimal FAR, superior open space, balanced height)…")}
                onChange={event => {
                  setAcceptanceReason(event.target.value);
                  if (event.target.value.trim()) {
                    setFieldErrors(prev => ({
                      ...prev,
                      acceptanceReason: undefined,
                      summary: prev.summary.filter(msg => msg !== t("Baseline acceptance reason is required.")),
                    }));
                  }
                }}
                required
                value={acceptanceReason}
              />
              {fieldErrors.acceptanceReason && (
                <div className="human-decision-dialog__field-error" role="alert" data-testid="error-acceptance-reason" style={{ color: 'var(--accent-rose, #f43f5e)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <AlertCircle size={14} />
                  <span>{fieldErrors.acceptanceReason}</span>
                </div>
              )}
            </label>

            {/* Rejection Reasons for unselected scenarios (appears only after baseline radio chosen) */}
            {selectedBaselineId && rejectedScenarios.length > 0 && (
              <div className="human-decision-dialog__summary-card" data-testid="rejected-proposals-section">
                <div className="human-decision-dialog__card-header">
                  <strong style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--accent-rose, #f43f5e)' }}>
                    <Ban size={16} /> {t("Rejection reasons for unselected proposals")}
                  </strong>
                  <span className="chip chip--undecided">{rejectedScenarios.length} {t("proposals")}</span>
                </div>
                <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
                  {t("Every unselected proposal requires an explicit human rejection reason to be recorded.")}
                </p>

                {rejectedScenarios.map(scenario => (
                  <label key={scenario.scenario_id} className="human-decision-dialog__field" style={{ marginTop: 8 }}>
                    <span>
                      {t("Rejection reason for {label} ({id})", {
                        label: scenario.strategy_label,
                        id: scenario.scenario_id,
                      })} *
                    </span>
                    <textarea
                      autoComplete="off"
                      maxLength={2000}
                      minLength={1}
                      placeholder={t("Explain why this proposal was not chosen (e.g., excessive height, insufficient open space)…")}
                      onChange={event => updateRejectionReason(scenario.scenario_id, event.target.value)}
                      required
                      value={rejectedReasons[scenario.scenario_id] || ''}
                    />
                    {fieldErrors.rejectedReasons[scenario.scenario_id] && (
                      <div className="human-decision-dialog__field-error" role="alert" data-testid={`error-rejection-${scenario.scenario_id}`} style={{ color: 'var(--accent-rose, #f43f5e)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                        <AlertCircle size={14} />
                        <span>{fieldErrors.rejectedReasons[scenario.scenario_id]}</span>
                      </div>
                    )}
                  </label>
                ))}
              </div>
            )}

            {/* Decision Key Field */}
            <label className="human-decision-dialog__field">
              <span>{t("Decision key")} *</span>
              <input
                autoComplete="new-password"
                maxLength={4096}
                minLength={1}
                placeholder={t("Enter private decision key")}
                onChange={event => {
                  setDecisionKey(event.target.value);
                  if (event.target.value.trim()) {
                    setFieldErrors(prev => ({
                      ...prev,
                      decisionKey: undefined,
                      summary: prev.summary.filter(msg => msg !== t("Decision key is required.")),
                    }));
                  }
                }}
                required
                type="password"
                value={decisionKey}
              />
              {fieldErrors.decisionKey && (
                <div className="human-decision-dialog__field-error" role="alert" data-testid="error-decision-key" style={{ color: 'var(--accent-rose, #f43f5e)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <AlertCircle size={14} />
                  <span>{fieldErrors.decisionKey}</span>
                </div>
              )}
            </label>
            <p className="human-decision-dialog__privacy">
              {t("The key is sent only with this decision and is not saved in browser storage.")}
            </p>

            {/* Error summary near button */}
            {(fieldErrors.summary.length > 0 || serverError) && (
              <div className="human-decision-dialog__error-summary" role="alert" data-testid="error-summary" style={{
                padding: '10px 14px',
                background: 'rgba(244, 63, 94, 0.1)',
                border: '1px solid var(--accent-rose, #f43f5e)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--accent-rose, #f43f5e)',
                fontSize: 12,
                display: 'grid',
                gap: 6,
              }}>
                {serverError && (
                  <div data-testid="server-error" style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                    <AlertCircle size={16} />
                    <span>{serverError}</span>
                  </div>
                )}
                {fieldErrors.summary.length > 0 && (
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, marginBottom: 4 }}>
                      <AlertCircle size={16} />
                      <span>{t("Please resolve the following before confirming decision:")}</span>
                    </div>
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {fieldErrors.summary.map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>

          <footer className="human-decision-dialog__footer">
            <button disabled={isSubmitting} onClick={onClose} type="button">
              {t("Cancel")}
            </button>
            <button
              disabled={isSubmitting}
              type="submit"
              data-testid="confirm-baseline-btn"
            >
              {isSubmitting ? t("Submitting…") : t("Confirm decision")}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
};
