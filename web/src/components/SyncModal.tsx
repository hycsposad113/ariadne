import { useT } from '../i18n';
import React from 'react';
import type { WorkspaceRevision, Building, Segment, SpatialZone } from '../types';
import { RefreshCw, X, AlertTriangle, ArrowRight, RotateCw } from 'lucide-react';

interface SyncModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirmSync: () => Promise<void>;
  isSyncing: boolean;
  currentWorkspace: WorkspaceRevision | null;
  buildings: Building[];
  roads: Segment[];
  spatialZones: SpatialZone[];
  syncError: string | null;
  onReloadServerState?: () => void;
}

export const SyncModal: React.FC<SyncModalProps> = ({
  isOpen,
  onClose,
  onConfirmSync,
  isSyncing,
  currentWorkspace,
  buildings,
  roads,
  spatialZones,
  syncError,
  onReloadServerState,
}) => {
  const t = useT();
  if (!isOpen) return null;

  // Calculate changed dispositions compared to currentWorkspace
  const prevDispMap = new Map<string, string>();
  if (currentWorkspace?.feature_dispositions) {
    for (const d of currentWorkspace.feature_dispositions) {
      prevDispMap.set(d.feature_id, (d.disposition || 'UNDECIDED').toUpperCase());
    }
  }

  const modifiedBuildings = buildings.filter(b => {
    const prev = prevDispMap.get(b.id) ?? 'UNDECIDED';
    return prev !== (b.disposition || 'UNDECIDED');
  });

  const modifiedRoads = roads.filter(r => {
    const prev = prevDispMap.get(r.id) ?? 'UNDECIDED';
    return prev !== (r.disposition || 'UNDECIDED');
  });

  const totalModifications = modifiedBuildings.length + modifiedRoads.length;
  const expectedRevision = currentWorkspace?.revision ?? 0;
  const nextRevision = expectedRevision + 1;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      width: '100vw',
      height: '100vh',
      backgroundColor: 'rgba(9, 13, 22, 0.82)',
      backdropFilter: 'blur(6px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 100,
    }}>
      <div style={{
        width: '580px',
        backgroundColor: 'var(--bg-surface)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-subtle)',
        boxShadow: 'var(--shadow-lg)',
        display: 'flex',
        flexDirection: 'column',
        maxHeight: '88vh',
        overflow: 'hidden',
      }}>
        {/* Modal Header */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px 20px',
          borderBottom: '1px solid var(--border-subtle)',
        }}>
          <div>
            <div style={{ fontSize: '15px', fontWeight: 700, color: 'var(--text-main)' }}>
              {t("Workspace Synchronization & Audit Diff")} </div>
            <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
              {t("Target:")} <span className="mono">{t("POST /api/v1/workspaces/sync")}</span>
            </div>
          </div>
          <button
            aria-label={t("Close synchronization dialog")}
            onClick={onClose}
            disabled={isSyncing}
            style={{
              color: 'var(--text-dim)',
              padding: '4px',
              backgroundColor: 'transparent',
              cursor: isSyncing ? 'not-allowed' : 'pointer',
              opacity: isSyncing ? 0.5 : 1,
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Modal Body */}
        <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1 }}>
          {/* Revision Banner */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 16px',
            backgroundColor: 'var(--bg-surface-elevated)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-subtle)',
            marginBottom: '14px',
          }}>
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>{t("Current State")}</div>
              <div style={{ fontSize: '13px', fontWeight: 600, color: currentWorkspace ? 'var(--text-main)' : 'var(--accent-amber)', fontFamily: 'var(--font-mono)' }}>
                {currentWorkspace ? t("Revision {0}", {"0": expectedRevision}) : t("NO SERVER REVISION")}
              </div>
            </div>
            <ArrowRight size={18} color="var(--accent-cyan)" />
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-dim)', textTransform: 'uppercase' }}>{t("Target Commit")}</div>
              <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--accent-cyan)', fontFamily: 'var(--font-mono)' }}>
                {t("Revision")} {nextRevision}
              </div>
            </div>
          </div>

          {/* Real HTTP Error Callout */}
          {syncError && (
            <div
              id="sync-error-banner"
              style={{
                padding: '12px',
                backgroundColor: 'rgba(244, 63, 94, 0.1)',
                border: '1px solid var(--accent-rose)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--accent-rose)',
                fontSize: '12px',
                marginBottom: '14px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}
            >
              <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                <div>
                  <strong>{t("Server Synchronization Failed")}</strong>
                  <div style={{ marginTop: '2px', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
                    {t(syncError)}
                  </div>
                </div>
              </div>
              {onReloadServerState && (syncError.includes('409') || syncError.includes('Conflict')) && (
                <button
                  id="btn-modal-reload-state"
                  onClick={() => { onReloadServerState(); onClose(); }}
                  disabled={isSyncing}
                  style={{
                    alignSelf: 'flex-start',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    padding: '4px 10px',
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor: 'var(--accent-rose)',
                    color: '#ffffff',
                    fontSize: '11px',
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  <RotateCw size={12} /> {t("Reload Server State")} </button>
              )}
            </div>
          )}

          {/* Diffs List: Buildings */}
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
              {t("Building Disposition Changes (")}{modifiedBuildings.length})
            </div>
            {modifiedBuildings.length === 0 ? (
              <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontStyle: 'italic', padding: '4px 0' }}>
                {t("No building disposition modifications.")} </div>
            ) : (
              <div style={{
                maxHeight: '130px',
                overflowY: 'auto',
                backgroundColor: 'var(--bg-app)',
                borderRadius: 'var(--radius-sm)',
                padding: '6px 10px',
                border: '1px solid var(--border-subtle)',
              }}>
                {modifiedBuildings.map(b => {
                  const prev = prevDispMap.get(b.id) ?? 'UNDECIDED';
                  return (
                    <div key={b.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', padding: '3px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                      <span className="mono" style={{ color: 'var(--text-muted)' }}>{b.id.length > 25 ? b.id.slice(0, 23) + '...' : b.id}</span>
                      <span>
                        <span style={{ color: 'var(--text-dim)' }}>{t(prev)}</span>
                        <span style={{ margin: '0 5px', color: 'var(--accent-cyan)' }}>→</span>
                        <strong style={{ color: b.disposition === 'PRESERVE' ? 'var(--accent-emerald)' : 'var(--accent-cyan)' }}>
                          {t(b.disposition || '')}
                        </strong>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Diffs List: Roads */}
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
              {t("Road Disposition Changes (")}{modifiedRoads.length})
            </div>
            {modifiedRoads.length === 0 ? (
              <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontStyle: 'italic', padding: '4px 0' }}>
                {t("No road disposition modifications.")} </div>
            ) : (
              <div style={{
                maxHeight: '130px',
                overflowY: 'auto',
                backgroundColor: 'var(--bg-app)',
                borderRadius: 'var(--radius-sm)',
                padding: '6px 10px',
                border: '1px solid var(--border-subtle)',
              }}>
                {modifiedRoads.map(r => {
                  const prev = prevDispMap.get(r.id) ?? 'UNDECIDED';
                  return (
                    <div key={r.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', padding: '3px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                      <span className="mono" style={{ color: 'var(--text-muted)' }}>{r.id}</span>
                      <span>
                        <span style={{ color: 'var(--text-dim)' }}>{t(prev)}</span>
                        <span style={{ margin: '0 5px', color: 'var(--accent-cyan)' }}>→</span>
                        <strong style={{ color: r.disposition === 'PRESERVE' ? 'var(--accent-emerald)' : 'var(--accent-cyan)' }}>
                          {t(r.disposition || '')}
                        </strong>
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Spatial Brief Diffs */}
          <div>
            <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '6px' }}>
              {t("Spatial Brief Draft Zones (")}{spatialZones.length})
            </div>
            {spatialZones.length === 0 ? (
              <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontStyle: 'italic' }}>
                {t("No active brief zones configured.")} </div>
            ) : (
              <div style={{
                backgroundColor: 'var(--bg-app)',
                borderRadius: 'var(--radius-sm)',
                padding: '6px 10px',
                border: '1px solid var(--border-subtle)',
              }}>
                {spatialZones.map(z => (
                  <div key={z.zone_id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', padding: '4px 0' }}>
                    <div>
                      <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>{z.name}</span>
                      <span style={{ fontSize: '10px', color: 'var(--text-dim)', marginLeft: '6px' }}>
                        ({t(z.target_use)} {t("· author:")} {z.author || t("designer")})
                      </span>
                    </div>
                    <span style={{ color: 'var(--accent-amber)', fontSize: '10px' }}>{t(z.status)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Modal Footer */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '12px 20px',
          borderTop: '1px solid var(--border-subtle)',
          backgroundColor: 'var(--bg-surface-elevated)',
        }}>
          <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
            {totalModifications} {t("disposition diffs ·")} {spatialZones.length} {t("zones")} </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              id="btn-cancel-sync-modal"
              onClick={onClose}
              disabled={isSyncing}
              style={{
                padding: '7px 14px',
                borderRadius: 'var(--radius-md)',
                fontSize: '12px',
                color: 'var(--text-muted)',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'transparent',
                cursor: isSyncing ? 'not-allowed' : 'pointer',
                opacity: isSyncing ? 0.55 : 1,
              }}
            >
              {t("Cancel")} </button>

            <button
              id="btn-confirm-sync-modal"
              onClick={onConfirmSync}
              disabled={isSyncing}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '7px 16px',
                borderRadius: 'var(--radius-md)',
                fontSize: '12px',
                fontWeight: 600,
                backgroundColor: 'var(--accent-cyan)',
                color: '#090d16',
                cursor: isSyncing ? 'not-allowed' : 'pointer',
              }}
            >
              <RefreshCw size={13} className={isSyncing ? 'spin' : ''} />
              <span>{isSyncing ? t("Committing...") : t("Commit & Sync")}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
