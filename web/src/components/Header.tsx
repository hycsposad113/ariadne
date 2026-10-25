import { useT } from '../i18n';
import React from 'react';
import { Layers, Box, Columns, RefreshCw, CheckCircle2, AlertCircle, RotateCw, Eye } from 'lucide-react';
import type { WorkspaceRevision, WorkspaceDecisionRecord } from '../types';

interface HeaderProps {
  workspace: WorkspaceRevision | null;
  studyArea: { id: string; status: string; revision: number; version: string } | null;
  serverLoadState: 'LOADING' | 'READY' | 'ERROR';
  outcomeUnknown: boolean;
  reconciliationMessage: string | null;
  hasUnsavedChanges: boolean;
  hasActiveDrawing: boolean;
  canRecordStudyAreaReview: boolean;
  humanDecisionMessage: string | null;
  viewMode: '2D' | '3D' | 'SPLIT';
  setViewMode: (mode: '2D' | '3D' | 'SPLIT') => void;
  onRecordStudyAreaReview: () => void;
  onOpenSyncModal: () => void;
  onReload?: () => void;
  isSyncing: boolean;
  onConfirmD1Decision?: () => void;
  canConfirmD1Decision?: boolean;
  workspaceDecision?: WorkspaceDecisionRecord | null;
  isD1DecisionStale?: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  workspace,
  studyArea,
  serverLoadState,
  outcomeUnknown,
  reconciliationMessage,
  hasUnsavedChanges,
  hasActiveDrawing,
  canRecordStudyAreaReview,
  humanDecisionMessage,
  viewMode,
  setViewMode,
  onRecordStudyAreaReview,
  onOpenSyncModal,
  onReload,
  isSyncing,
  onConfirmD1Decision,
  canConfirmD1Decision = false,
  workspaceDecision = null,
  isD1DecisionStale = false,
}) => {
  const t = useT();
  return (
    <header className="app-header">
      <div className="app-header__identity" style={{ minWidth: '420px', flexShrink: 0 }}>
        <div className="app-header__brand">
          <img
            className="app-header__logo"
            src="/ariadne-brand.png"
            alt={t("Ariadne")}
          />
        </div>

        <div className="app-header__project">
          <div className="app-header__project-heading">
            <strong className="app-header__project-name">{t("Rotterdam M4H Pilot")}</strong>
            <span
              id="header-project-id"
              className="app-header__project-id"
              title={workspace?.project_id}
            >
              {t("Project ID:")} {workspace?.project_id || t("not loaded")}
            </span>
          </div>
          <div className="app-header__project-details">
            <span
              id="header-study-area-id"
              className="app-header__study-area-id"
              title={studyArea?.id}
            >
              {t("StudyArea ID:")} {studyArea?.id || t("not loaded")}
            </span>
            <span className="app-header__crs">{t("EPSG:28992")}</span>
            <span
              id="badge-revision"
              className="app-header__badge"
              style={{
                backgroundColor: workspace ? 'rgba(56, 189, 248, 0.12)' : 'rgba(245, 158, 11, 0.12)',
                color: workspace ? 'var(--accent-cyan)' : 'var(--accent-amber)',
                borderColor: workspace ? 'rgba(56, 189, 248, 0.25)' : 'rgba(245, 158, 11, 0.25)',
              }}
            >
              {t("Workspace rev")} {workspace?.revision ?? '—'}
            </span>
            <span className="app-header__badge app-header__badge--study-area-revision">
              {t("StudyArea rev")} {studyArea?.revision ?? '—'}
            </span>
            <span
              id="badge-study-area-status"
              className="app-header__badge"
              style={{
                backgroundColor: studyArea?.status === 'CONFIRMED_FOR_EXPLORATION' ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
                color: studyArea?.status === 'CONFIRMED_FOR_EXPLORATION' ? 'var(--accent-emerald)' : 'var(--accent-amber)',
                borderColor: studyArea?.status === 'CONFIRMED_FOR_EXPLORATION' ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)',
              }}
            >
              {t("StudyArea status:")} {t(studyArea?.status || (serverLoadState === 'ERROR' ? t("AUTHORITY_UNAVAILABLE") : t("CHECKING_AUTHORITY")))}
            </span>
            <span
              id="badge-d1-decision"
              data-testid="badge-d1-decision"
              className="app-header__badge"
              title={
                !workspaceDecision
                  ? t("第 1 天決策草稿尚未確認")
                  : isD1DecisionStale
                  ? t("決策 {0} 綁定於舊版本 rev {1}，目前工作區已有新變更。", {"0": workspaceDecision.id, "1": workspaceDecision.target_version})
                  : t("第 1 天決策 {0} 已核准並綁定於當前版本。", {"0": workspaceDecision.id})
              }
              style={{
                backgroundColor: !workspaceDecision
                  ? 'rgba(148, 163, 184, 0.12)'
                  : isD1DecisionStale
                  ? 'rgba(245, 158, 11, 0.12)'
                  : 'rgba(16, 185, 129, 0.12)',
                color: !workspaceDecision
                  ? 'var(--text-dim)'
                  : isD1DecisionStale
                  ? 'var(--accent-amber)'
                  : 'var(--accent-emerald)',
                borderColor: !workspaceDecision
                  ? 'rgba(148, 163, 184, 0.25)'
                  : isD1DecisionStale
                  ? 'rgba(245, 158, 11, 0.25)'
                  : 'rgba(16, 185, 129, 0.25)',
                maxWidth: '340px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {!workspaceDecision
                ? t("D1 決策：未確認 (DRAFT)")
                : isD1DecisionStale
                ? t("D1 決策：{0} (對應舊版本 rev {1})", {"0": workspaceDecision.id, "1": workspaceDecision.target_version})
                : t("D1 決策：{0} ({1})", {"0": workspaceDecision.id, "1": workspaceDecision.status})}
            </span>
          </div>
        </div>
      </div>

      {/* View Mode Switcher */}
      <div style={{
        gridArea: 'view-mode',
        display: 'flex',
        alignItems: 'center',
        backgroundColor: 'var(--bg-app)',
        padding: '3px',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)',
      }} className="app-header__view-switcher">
        <button
          id="btn-view-2d"
          onClick={() => setViewMode('2D')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '5px 12px',
            borderRadius: 'var(--radius-sm)',
            fontSize: '12px',
            fontWeight: 500,
            color: viewMode === '2D' ? 'var(--text-main)' : 'var(--text-muted)',
            backgroundColor: viewMode === '2D' ? 'var(--bg-surface-elevated)' : 'transparent',
            boxShadow: viewMode === '2D' ? 'var(--shadow-sm)' : 'none',
          }}
        >
          <Layers size={14} /> {t("2D Map")} </button>
        <button
          id="btn-view-3d"
          onClick={() => setViewMode('3D')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '5px 12px',
            borderRadius: 'var(--radius-sm)',
            fontSize: '12px',
            fontWeight: 500,
            color: viewMode === '3D' ? 'var(--text-main)' : 'var(--text-muted)',
            backgroundColor: viewMode === '3D' ? 'var(--bg-surface-elevated)' : 'transparent',
            boxShadow: viewMode === '3D' ? 'var(--shadow-sm)' : 'none',
          }}
        >
          <Box size={14} /> {t("3D Massing")} </button>
        <button
          id="btn-view-split"
          onClick={() => setViewMode('SPLIT')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '5px 12px',
            borderRadius: 'var(--radius-sm)',
            fontSize: '12px',
            fontWeight: 500,
            color: viewMode === 'SPLIT' ? 'var(--text-main)' : 'var(--text-muted)',
            backgroundColor: viewMode === 'SPLIT' ? 'var(--bg-surface-elevated)' : 'transparent',
            boxShadow: viewMode === 'SPLIT' ? 'var(--shadow-sm)' : 'none',
          }}
        >
          <Columns size={14} /> {t("Split View")} </button>
      </div>

      {/* Sync Status & Action Buttons */}
      <div className="app-header__sync-actions">
        <div
          id="status-authority"
          className="app-header__authority-status"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '12px',
            color: outcomeUnknown || serverLoadState !== 'READY' || !workspace
              ? 'var(--accent-amber)'
              : hasUnsavedChanges
              ? 'var(--accent-amber)'
              : 'var(--accent-emerald)',
            fontWeight: 500,
          }}
        >
          {outcomeUnknown ? (
            <><AlertCircle size={14} /><span>{t("OUTCOME_UNKNOWN · RECONCILIATION REQUIRED")}</span></>
          ) : serverLoadState === 'LOADING' ? (
            <><AlertCircle size={14} /><span>{t("Loading server authority…")}</span></>
          ) : serverLoadState === 'ERROR' ? (
            <><AlertCircle size={14} /><span>{t("SERVER AUTHORITY UNAVAILABLE")}</span></>
          ) : !workspace ? (
            <>
              <AlertCircle size={14} />
              <span>{hasUnsavedChanges ? t("Unsaved Draft Changes · NO SERVER REVISION") : t("NO SERVER REVISION")}</span>
            </>
          ) : hasUnsavedChanges ? (
            <>
              <AlertCircle size={14} />
              <span>{t("Unsaved Draft Changes")}</span>
            </>
          ) : (
            <>
              <CheckCircle2 size={14} />
              <span>{t("In Sync (Server Authority)")}</span>
            </>
          )}
        </div>

        {reconciliationMessage && (
          <span id="sync-reconciliation-status" role="status" className="app-header__reconciliation-status">
            {t(reconciliationMessage)}
          </span>
        )}

        {humanDecisionMessage && (
          <span
            id="human-decision-status"
            role="status"
            className="app-header__reconciliation-status"
            title={t(humanDecisionMessage)}
            style={{
              maxWidth: '240px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {t(humanDecisionMessage)}
          </span>
        )}

        <button
          id="btn-record-study-area-review"
          onClick={onRecordStudyAreaReview}
          disabled={!canRecordStudyAreaReview}
          title={canRecordStudyAreaReview
            ? t("Record an inspection of the current active StudyArea")
            : t("A current confirmed StudyArea with no unsaved workspace edits is required.")}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            backgroundColor: 'var(--bg-surface-elevated)',
            color: 'var(--text-main)',
            border: '1px solid var(--border-subtle)',
            padding: '7px 12px',
            borderRadius: 'var(--radius-md)',
            fontWeight: 500,
            fontSize: '12px',
            cursor: canRecordStudyAreaReview ? 'pointer' : 'not-allowed',
            opacity: canRecordStudyAreaReview ? 1 : 0.55,
          }}
        >
          <Eye size={13} />
          <span>{t("Record Review")}</span>
        </button>

        {onReload && (
          <button
            id="btn-reload-workspace"
            title={t("Reload state from server")}
            onClick={onReload}
            disabled={isSyncing || hasUnsavedChanges}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: 'var(--bg-surface-elevated)',
              color: 'var(--text-main)',
              border: '1px solid var(--border-subtle)',
              padding: '7px 12px',
              borderRadius: 'var(--radius-md)',
              fontWeight: 500,
              fontSize: '12px',
              cursor: isSyncing || hasUnsavedChanges ? 'not-allowed' : 'pointer',
              opacity: isSyncing || hasUnsavedChanges ? 0.55 : 1,
            }}
          >
            <RotateCw size={13} />
            <span>{t("Reload")}</span>
          </button>
        )}

        <button
          id="btn-sync-workspace"
          onClick={onOpenSyncModal}
          disabled={isSyncing || outcomeUnknown || serverLoadState !== 'READY' || !studyArea || hasActiveDrawing}
          title={hasActiveDrawing ? t("Finish or cancel polygon drawing before syncing.") : undefined}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            backgroundColor: hasUnsavedChanges || !workspace ? 'var(--accent-cyan)' : 'var(--bg-surface-elevated)',
            color: hasUnsavedChanges || !workspace ? '#090d16' : 'var(--text-main)',
            border: `1px solid ${hasUnsavedChanges || !workspace ? 'var(--accent-cyan)' : 'var(--border-subtle)'}`,
            padding: '7px 14px',
            borderRadius: 'var(--radius-md)',
            fontWeight: 600,
            fontSize: '12px',
            cursor: 'pointer',
            boxShadow: hasUnsavedChanges || !workspace ? '0 0 12px rgba(56, 189, 248, 0.4)' : 'none',
          }}
        >
          <RefreshCw size={14} className={isSyncing ? 'spin' : ''} />
          <span>{isSyncing ? t("Syncing...") : t("Sync Workspace")}</span>
        </button>

        {onConfirmD1Decision && (
          <button
            id="btn-confirm-d1-decision"
            data-testid="btn-confirm-d1-decision"
            onClick={onConfirmD1Decision}
            disabled={!canConfirmD1Decision}
            title={
              hasUnsavedChanges
                ? t("未保存的變更存在時不得送出決策，請先點擊 Sync Workspace。")
                : !canConfirmD1Decision
                ? t("需要已儲存且無未保存變更的工作區版本。")
                : t("確認第 1 天決策（綁定目前 WorkspaceRevision）")
            }
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: canConfirmD1Decision ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-surface-elevated)',
              color: canConfirmD1Decision ? 'var(--accent-emerald)' : 'var(--text-muted)',
              border: `1px solid ${canConfirmD1Decision ? 'rgba(16, 185, 129, 0.4)' : 'var(--border-subtle)'}`,
              padding: '7px 12px',
              borderRadius: 'var(--radius-md)',
              fontWeight: 600,
              fontSize: '12px',
              cursor: canConfirmD1Decision ? 'pointer' : 'not-allowed',
              opacity: canConfirmD1Decision ? 1 : 0.55,
            }}
          >
            <CheckCircle2 size={13} />
            <span>{t("確認第 1 天決策")}</span>
          </button>
        )}
      </div>
    </header>
  );
};
