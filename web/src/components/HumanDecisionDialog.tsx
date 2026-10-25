import { useT } from '../i18n';
import React, { useEffect, useState } from 'react';
import { X, AlertTriangle, Building2, Route } from 'lucide-react';
import { getActorSessionId } from '../utils/actorProvenance';
import type { Day1DecisionSummary } from '../types';
import './HumanDecisionDialog.css';

export interface HumanDecisionTarget {
  id: string;
  type: string;
  version: string;
  geometrySha256?: string;
  artifactSha256?: string;
  payloadDigest?: string;
}

export interface HumanDecisionSubmission {
  target_id: string;
  target_type: string;
  target_version: string;
  target_geometry_sha256?: string;
  target_artifact_sha256?: string;
  target_payload_digest?: string;
  action: string;
  status: string;
  reason: string;
  decision_key: string;
  actor_session_id: string;
}

interface HumanDecisionDialogProps {
  isOpen: boolean;
  target: HumanDecisionTarget;
  action: string;
  status: string;
  onClose: () => void;
  onSubmit: (decision: HumanDecisionSubmission) => Promise<void>;
  summary?: Day1DecisionSummary | null;
  reviewContent?: React.ReactNode;
  hasUnsavedChanges?: boolean;
}

export const HumanDecisionDialog: React.FC<HumanDecisionDialogProps> = ({
  isOpen,
  ...props
}) => {
  if (!isOpen) return null;
  const bindingKey = [
    props.target.id,
    props.target.version,
    props.target.geometrySha256 || props.target.artifactSha256 || props.target.payloadDigest || '',
    props.action,
    props.status,
  ].join(':');
  return <HumanDecisionDialogForm key={bindingKey} {...props} />;
};

const HumanDecisionDialogForm: React.FC<Omit<HumanDecisionDialogProps, 'isOpen'>> = ({
  target,
  action,
  status,
  onClose,
  onSubmit,
  summary,
  reviewContent,
  hasUnsavedChanges = false,
}) => {
  const t = useT();
  const [decisionKey, setDecisionKey] = useState('');
  const [reason, setReason] = useState(() =>
    target.type === 'WorkspaceRevision'
      ? t('第 1 天決策：確認設計範圍、建築與道路保留／可改處置，以及空間分區草稿。')
      : ''
  );
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const targetHash = target.geometrySha256 || target.artifactSha256 || target.payloadDigest;

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isSubmitting) {
        setDecisionKey('');
        setReason('');
        onClose();
      }
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [isSubmitting, onClose]);

  const closeDialog = () => {
    if (isSubmitting) return;
    setDecisionKey('');
    setReason('');
    setError(null);
    onClose();
  };

  const submitDecision = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting) return;
    if (hasUnsavedChanges) {
      setError(t("未保存的變更存在時不得送出決策"));
      return;
    }
    if (!targetHash) {
      setError(t("Missing hash — decision blocked"));
      return;
    }
    if (!reason.trim()) {
      setError(t("Please enter a decision reason."));
      return;
    }
    if (!decisionKey.trim()) {
      setError(t("Please enter the decision key."));
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      await onSubmit({
        target_id: target.id,
        target_type: target.type,
        target_version: target.version,
        ...(target.geometrySha256 ? { target_geometry_sha256: target.geometrySha256 } : {}),
        ...(target.artifactSha256 ? { target_artifact_sha256: target.artifactSha256 } : {}),
        ...(target.payloadDigest ? { target_payload_digest: target.payloadDigest } : {}),
        action,
        status,
        reason: reason.trim(),
        decision_key: decisionKey,
        actor_session_id: getActorSessionId(),
      });
      setDecisionKey('');
      setReason('');
      onClose();
    } catch (caught) {
      setDecisionKey('');
      setError(caught instanceof Error ? caught.message : 'The decision was rejected.');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="human-decision-backdrop">
      <section
        aria-labelledby="human-decision-title"
        aria-modal="true"
        className="human-decision-dialog"
        role="dialog"
      >
        <header className="human-decision-dialog__header">
          <div>
            <h2 id="human-decision-title">{t("Confirm human decision")}</h2>
            <p>{t("Target and revision to be recorded in the design ledger")}</p>
          </div>
          <button
            aria-label={t("Close decision dialog")}
            className="human-decision-dialog__close"
            disabled={isSubmitting}
            onClick={closeDialog}
            type="button"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <form onSubmit={submitDecision} noValidate>
          <div className="human-decision-dialog__body">
            <dl className="human-decision-dialog__target">
              <div><dt>{t("Target")}</dt><dd>{target.id}</dd></div>
              <div><dt>{t("Type")}</dt><dd>{target.type}</dd></div>
              <div><dt>{t("Version")}</dt><dd>{target.version}</dd></div>
              <div><dt>{t("Action")}</dt><dd>{t(action)}</dd></div>
              <div><dt>{t("Status")}</dt><dd>{action === "Reconsider" && status === "not_reviewed" ? t("Pending") : t(status)}</dd></div>
              <div><dt>{t("Target hash")}</dt><dd className="mono">{targetHash || t("Missing hash — decision blocked")}</dd></div>
            </dl>

            {reviewContent}
            {summary && (
              <div className="human-decision-dialog__summary" data-testid="d1-dialog-summary">
                <h3 className="human-decision-dialog__section-title">{t("第 1 天決策內容摘要")}</h3>

                {/* 1. Exploration Design Area */}
                <div className="human-decision-dialog__summary-card" data-testid="d1-dialog-eda-card">
                  <div className="human-decision-dialog__card-header">
                    <strong>{t("設計範圍 (Exploration Design Area)")}</strong>
                  </div>
                  {summary.exploration_design_area ? (
                    <div className="human-decision-dialog__card-content">
                      <div className="human-decision-dialog__stat-row">
                        {t("面積：")}<span className="human-decision-dialog__stat-value" data-testid="d1-dialog-eda-area">{summary.exploration_design_area.area_m2.toLocaleString()} {t("m²")}</span>
                      </div>
                      <div className="human-decision-dialog__hash-row">
                        {t("幾何 Hash：")} <span className="mono" data-testid="d1-dialog-eda-hash">
                          {summary.exploration_design_area.geometry_hash || target.geometrySha256 || t("無")}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="human-decision-dialog__empty-note" data-testid="d1-dialog-eda-empty">
                      {t("本版本未包含自訂設計範圍（使用全區 StudyArea）。")} </div>
                  )}
                </div>

                {/* 2. Feature Dispositions */}
                <div className="human-decision-dialog__summary-card" data-testid="d1-dialog-dispositions-card">
                  <div className="human-decision-dialog__card-header">
                    <strong>{t("要素處置 (Feature Dispositions)")}</strong>
                  </div>

                  {/* Buildings */}
                  <div className="human-decision-dialog__disposition-group" data-testid="d1-dialog-buildings-summary">
                    <div className="human-decision-dialog__group-title">
                      <Building2 size={14} /> {t("建築物處置 (")}{summary.dispositions.buildings.counts.total} {t("棟)")} </div>
                    <div className="human-decision-dialog__stat-chips">
                      <span className="chip chip--preserve">{t("保留:")} {summary.dispositions.buildings.counts.preserve}</span>
                      <span className="chip chip--editable">{t("可改:")} {summary.dispositions.buildings.counts.editable}</span>
                      <span className="chip chip--undecided">{t("未決:")} {summary.dispositions.buildings.counts.undecided}</span>
                    </div>

                    <div className="human-decision-dialog__details-container">
                      <details className="human-decision-dialog__details" data-testid="details-buildings-preserve">
                        <summary>{t("檢視保留建築清單 (")}{summary.dispositions.buildings.preserve.length})</summary>
                        <ul className="human-decision-dialog__id-list">
                          {summary.dispositions.buildings.preserve.length > 0 ? (
                            summary.dispositions.buildings.preserve.map(id => <li key={id}>{id}</li>)
                          ) : (
                            <li className="empty">{t("無")}</li>
                          )}
                        </ul>
                      </details>
                      <details className="human-decision-dialog__details" data-testid="details-buildings-editable">
                        <summary>{t("檢視可改建築清單 (")}{summary.dispositions.buildings.editable.length})</summary>
                        <ul className="human-decision-dialog__id-list">
                          {summary.dispositions.buildings.editable.length > 0 ? (
                            summary.dispositions.buildings.editable.map(id => <li key={id}>{id}</li>)
                          ) : (
                            <li className="empty">{t("無")}</li>
                          )}
                        </ul>
                      </details>
                      <details className="human-decision-dialog__details" data-testid="details-buildings-undecided">
                        <summary>{t("檢視未決建築清單 (")}{summary.dispositions.buildings.undecided.length})</summary>
                        <ul className="human-decision-dialog__id-list">
                          {summary.dispositions.buildings.undecided.length > 0 ? (
                            summary.dispositions.buildings.undecided.map(id => <li key={id}>{id}</li>)
                          ) : (
                            <li className="empty">{t("無")}</li>
                          )}
                        </ul>
                      </details>
                    </div>
                  </div>

                  {/* Roads */}
                  <div className="human-decision-dialog__disposition-group" data-testid="d1-dialog-roads-summary">
                    <div className="human-decision-dialog__group-title">
                      <Route size={14} /> {t("道路路段處置 (")}{summary.dispositions.roads.counts.total} {t("條)")} </div>
                    <div className="human-decision-dialog__stat-chips">
                      <span className="chip chip--preserve">{t("保留:")} {summary.dispositions.roads.counts.preserve}</span>
                      <span className="chip chip--editable">{t("可改:")} {summary.dispositions.roads.counts.editable}</span>
                      <span className="chip chip--undecided">{t("未決:")} {summary.dispositions.roads.counts.undecided}</span>
                    </div>

                    <div className="human-decision-dialog__details-container">
                      <details className="human-decision-dialog__details" data-testid="details-roads-preserve">
                        <summary>{t("檢視保留道路清單 (")}{summary.dispositions.roads.preserve.length})</summary>
                        <ul className="human-decision-dialog__id-list">
                          {summary.dispositions.roads.preserve.length > 0 ? (
                            summary.dispositions.roads.preserve.map(id => <li key={id}>{id}</li>)
                          ) : (
                            <li className="empty">{t("無")}</li>
                          )}
                        </ul>
                      </details>
                      <details className="human-decision-dialog__details" data-testid="details-roads-editable">
                        <summary>{t("檢視可改道路清單 (")}{summary.dispositions.roads.editable.length})</summary>
                        <ul className="human-decision-dialog__id-list">
                          {summary.dispositions.roads.editable.length > 0 ? (
                            summary.dispositions.roads.editable.map(id => <li key={id}>{id}</li>)
                          ) : (
                            <li className="empty">{t("無")}</li>
                          )}
                        </ul>
                      </details>
                      <details className="human-decision-dialog__details" data-testid="details-roads-undecided">
                        <summary>{t("檢視未決道路清單 (")}{summary.dispositions.roads.undecided.length})</summary>
                        <ul className="human-decision-dialog__id-list">
                          {summary.dispositions.roads.undecided.length > 0 ? (
                            summary.dispositions.roads.undecided.map(id => <li key={id}>{id}</li>)
                          ) : (
                            <li className="empty">{t("無")}</li>
                          )}
                        </ul>
                      </details>
                    </div>
                  </div>
                </div>

                {/* 3. Spatial Zones */}
                <div className="human-decision-dialog__summary-card" data-testid="d1-dialog-zones-summary">
                  <div className="human-decision-dialog__card-header">
                    <strong>{t("分區清單與條件 (Spatial Zones & Constraints)")}</strong>
                    <span className="badge">{summary.zones.length} {t("區")}</span>
                  </div>
                  {summary.zones.length > 0 ? (
                    <div className="human-decision-dialog__zones-list">
                      {summary.zones.map(zone => (
                        <div key={zone.zone_id} className="human-decision-dialog__zone-item" data-testid={`zone-item-${zone.zone_id}`}>
                          <div className="zone-item__header">
                            <span className="zone-item__name">{zone.name}</span>
                            <span className="zone-item__use">{t(zone.target_use)}</span>
                          </div>
                          {((zone.target_far !== null && zone.target_far !== undefined) || (zone.target_height_m !== null && zone.target_height_m !== undefined)) && (
                            <div className="zone-item__metrics">
                              {zone.target_far !== null && zone.target_far !== undefined && <span>{t("FAR:")} {zone.target_far}</span>}
                              {zone.target_height_m !== null && zone.target_height_m !== undefined && <span>{t("限高:")} {zone.target_height_m}{t("m")}</span>}
                            </div>
                          )}
                          <div className="zone-item__conditions">
                            <div className="condition-row">
                              <span className="condition-label">{t("硬性條件：")}</span>
                              {zone.draft_constraints && zone.draft_constraints.length > 0 ? (
                                <span className="condition-values">{zone.draft_constraints.join('；')}</span>
                              ) : (
                                <span className="condition-none">{t("無")}</span>
                              )}
                            </div>
                            <div className="condition-row">
                              <span className="condition-label">{t("偏好條件：")}</span>
                              {zone.draft_preferences && zone.draft_preferences.length > 0 ? (
                                <span className="condition-values">{zone.draft_preferences.join('；')}</span>
                              ) : (
                                <span className="condition-none">{t("無")}</span>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="human-decision-dialog__empty-note">{t("目前尚無定義空間分區。")}</div>
                  )}
                </div>
              </div>
            )}

            {/* Unsaved changes alert */}
            {hasUnsavedChanges && (
              <div
                className="human-decision-dialog__unsaved-warning"
                role="alert"
                data-testid="d1-dialog-unsaved-warning"
              >
                <AlertTriangle size={16} />
                <div>
                  <strong>{t("未保存的變更警告：")}</strong> {t("目前工作區存在未保存的草稿變更。必須先點擊「Sync Workspace」儲存為正式版本後，才能對該版本確認第 1 天決策。")} </div>
              </div>
            )}

            <label className="human-decision-dialog__field">
              <span>{t("Reason")}</span>
              <textarea
                autoComplete="off"
                maxLength={2000}
                minLength={1}
                onChange={event => {
                  setReason(event.target.value);
                  setError(null);
                }}
                required
                value={reason}
              />
            </label>
            <label className="human-decision-dialog__field">
              <span>{t("Decision key")}</span>
              <input
                autoComplete="new-password"
                autoFocus
                maxLength={4096}
                minLength={12}
                onChange={event => {
                  setDecisionKey(event.target.value);
                  setError(null);
                }}
                required
                type="password"
                value={decisionKey}
              />
            </label>
            <p className="human-decision-dialog__privacy">
              {t("The key is sent only with this decision and is not saved in browser storage.")} </p>
            {error && <p className="human-decision-dialog__error" role="alert">{t(error)}</p>}
          </div>

          <footer className="human-decision-dialog__footer">
            <button disabled={isSubmitting} onClick={closeDialog} type="button">{t("Cancel")}</button>
            <button
              disabled={isSubmitting || !targetHash || Boolean(hasUnsavedChanges)}
              type="submit"
              data-testid="d1-dialog-submit-btn"
              title={
                isSubmitting
                  ? t("Submitting…")
                  : hasUnsavedChanges
                  ? t("未保存的變更存在時不得送出決策")
                  : !targetHash
                  ? t("Missing hash — decision blocked")
                  : !reason.trim()
                  ? t("Please enter a decision reason.")
                  : !decisionKey.trim()
                  ? t("Please enter the decision key.")
                  : undefined
              }
            >
              {isSubmitting ? t("Submitting…") : t("Confirm decision")}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
};
