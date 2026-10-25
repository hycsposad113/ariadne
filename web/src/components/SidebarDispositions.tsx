import { useT } from '../i18n';
import React, { useLayoutEffect, useRef, useState } from 'react';
import type { Building, Segment, FeatureDispositionType, WorkspaceDecisionRecord } from '../types';
import { Lock, Unlock, HelpCircle, Building2, Route } from 'lucide-react';

interface SidebarDispositionsProps {
  buildings: Building[];
  roads: Segment[];
  selectedFeatureId: string | null;
  selectedFeatureIds: string[];
  isSyncing?: boolean;
  onSelectFeature: (id: string | null, type: 'building' | 'road') => void;
  onUpdateDisposition: (featureId: string, type: 'building' | 'road', disposition: FeatureDispositionType) => void;
  onUpdateAnnotation: (featureId: string, type: 'building' | 'road', annotation: string) => void;
  onBatchUpdate: (type: 'building' | 'road', disposition: FeatureDispositionType, featureIds?: string[]) => void;
  workspaceDecision?: WorkspaceDecisionRecord | null;
  isD1DecisionStale?: boolean;
}

type PendingUnlock =
  | { mode: 'single'; featureId: string; type: 'building' | 'road'; disposition: FeatureDispositionType }
  | { mode: 'batch'; type: 'building' | 'road'; disposition: FeatureDispositionType; featureIds?: string[]; lockedCount: number };

export const SidebarDispositions: React.FC<SidebarDispositionsProps> = ({
  buildings,
  roads,
  selectedFeatureId,
  selectedFeatureIds,
  isSyncing = false,
  onSelectFeature,
  onUpdateDisposition,
  onUpdateAnnotation,
  onBatchUpdate,
  workspaceDecision = null,
  isD1DecisionStale = false,
}) => {
  const t = useT();
  const [activeKind, setActiveKind] = useState<'building' | 'road'>('building');
  const [filter, setFilter] = useState<'ALL' | FeatureDispositionType>('ALL');
  const [pendingUnlock, setPendingUnlock] = useState<PendingUnlock | null>(null);
  const unlockDialogRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (!pendingUnlock) return;

    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = unlockDialogRef.current;
    const cancelButton = dialog?.querySelector<HTMLButtonElement>('[data-unlock-cancel]');
    cancelButton?.focus();

    const onDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setPendingUnlock(null);
        return;
      }
      if (event.key !== 'Tab' || !dialog) return;

      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }

      const activeIndex = focusable.indexOf(document.activeElement as HTMLElement);
      const nextIndex = event.shiftKey
        ? (activeIndex <= 0 ? focusable.length - 1 : activeIndex - 1)
        : (activeIndex < 0 || activeIndex === focusable.length - 1 ? 0 : activeIndex + 1);
      event.preventDefault();
      focusable[nextIndex].focus();
    };

    document.addEventListener('keydown', onDialogKeyDown);
    return () => {
      document.removeEventListener('keydown', onDialogKeyDown);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [pendingUnlock]);

  const items = activeKind === 'building' ? buildings : roads;
  const selectedIds = items.filter(item => selectedFeatureIds.includes(item.id)).map(item => item.id);
  const filteredItems = items.filter(item => {
    const disp = item.disposition || 'UNDECIDED';
    return filter === 'ALL' || disp === filter;
  });

  const counts = {
    ALL: items.length,
    PRESERVE: items.filter(i => i.disposition === 'PRESERVE').length,
    EDITABLE: items.filter(i => i.disposition === 'EDITABLE').length,
    UNDECIDED: items.filter(i => !i.disposition || i.disposition === 'UNDECIDED').length,
  };

  const requestSingleDisposition = (featureId: string, disposition: FeatureDispositionType) => {
    if (isSyncing) return;
    const item = items.find(candidate => candidate.id === featureId);
    if (item?.disposition === 'PRESERVE' && disposition !== 'PRESERVE') {
      setPendingUnlock({ mode: 'single', featureId, type: activeKind, disposition });
      return;
    }
    onUpdateDisposition(featureId, activeKind, disposition);
  };

  const requestBatchDisposition = (type: 'building' | 'road', disposition: FeatureDispositionType, featureIds?: string[]) => {
    if (isSyncing) return;
    if (featureIds && featureIds.length === 0) return;
    const targetItems = (type === 'building' ? buildings : roads)
      .filter(item => !featureIds || featureIds.includes(item.id));
    const lockedCount = targetItems.filter(item => item.disposition === 'PRESERVE').length;
    if (lockedCount > 0 && disposition !== 'PRESERVE') {
      setPendingUnlock({ mode: 'batch', type, disposition, featureIds: featureIds ? [...featureIds] : undefined, lockedCount });
      return;
    }
    if (featureIds) onBatchUpdate(type, disposition, featureIds);
    else onBatchUpdate(type, disposition);
  };

  const confirmUnlock = () => {
    if (!pendingUnlock || isSyncing) return;
    if (pendingUnlock.mode === 'single') {
      onUpdateDisposition(pendingUnlock.featureId, pendingUnlock.type, pendingUnlock.disposition);
    } else {
      if (pendingUnlock.featureIds) onBatchUpdate(pendingUnlock.type, pendingUnlock.disposition, pendingUnlock.featureIds);
      else onBatchUpdate(pendingUnlock.type, pendingUnlock.disposition);
    }
    setPendingUnlock(null);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Feature Kind Sub-tab Selector */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid var(--border-subtle)',
        backgroundColor: 'var(--bg-app)',
      }}>
        <button
          id="tab-disp-buildings"
          onClick={() => { setActiveKind('building'); setFilter('ALL'); }}
          style={{
            flex: 1,
            padding: '8px 4px',
            fontSize: '11px',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '5px',
            color: activeKind === 'building' ? 'var(--accent-cyan)' : 'var(--text-dim)',
            borderBottom: `2px solid ${activeKind === 'building' ? 'var(--accent-cyan)' : 'transparent'}`,
            backgroundColor: activeKind === 'building' ? 'var(--bg-surface)' : 'transparent',
          }}
        >
          <Building2 size={13} /> {t("Buildings (")}{buildings.length})
        </button>
        <button
          id="tab-disp-roads"
          onClick={() => { setActiveKind('road'); setFilter('ALL'); }}
          style={{
            flex: 1,
            padding: '8px 4px',
            fontSize: '11px',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '5px',
            color: activeKind === 'road' ? 'var(--accent-cyan)' : 'var(--text-dim)',
            borderBottom: `2px solid ${activeKind === 'road' ? 'var(--accent-cyan)' : 'transparent'}`,
            backgroundColor: activeKind === 'road' ? 'var(--bg-surface)' : 'transparent',
          }}
        >
          <Route size={13} /> {t("Roads (")}{roads.length})
        </button>
      </div>

      {/* Header & Filter Chips */}
      <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {activeKind === 'building' ? t("BAG Buildings Dispositions") : t("OSM Road Dispositions")}
          </span>
          <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
            {items.length} {t("Total")} </span>
        </div>

        {workspaceDecision && (
          <div
            id="disp-decision-status"
            data-testid="disp-decision-status"
            style={{
              marginBottom: '8px',
              padding: '5px 8px',
              borderRadius: 'var(--radius-sm)',
              fontSize: '10px',
              backgroundColor: isD1DecisionStale ? 'rgba(245, 158, 11, 0.08)' : 'rgba(16, 185, 129, 0.08)',
              border: `1px solid ${isD1DecisionStale ? 'rgba(245, 158, 11, 0.25)' : 'rgba(16, 185, 129, 0.25)'}`,
              color: isD1DecisionStale ? 'var(--accent-amber)' : 'var(--accent-emerald)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span>
              {isD1DecisionStale
                ? t("決策對應舊版本 (rev {0})", {"0": workspaceDecision.target_version})
                : t("第 1 天決策已確認 ({0})", {"0": workspaceDecision.id})}
            </span>
            <span style={{ fontWeight: 600 }}>{t(workspaceDecision.status)}</span>
          </div>
        )}

        {/* Filter buttons */}
        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
          {(['ALL', 'PRESERVE', 'EDITABLE', 'UNDECIDED'] as const).map(tab => (
            <button
              key={t(tab)}
              id={`filter-disp-${tab.toLowerCase()}`}
              onClick={() => setFilter(tab)}
              style={{
                fontSize: '10px',
                padding: '3px 7px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: filter === tab ? 'var(--bg-surface-elevated)' : 'transparent',
                color: filter === tab ? 'var(--text-main)' : 'var(--text-dim)',
                border: `1px solid ${filter === tab ? 'var(--border-focus)' : 'var(--border-subtle)'}`,
                display: 'flex',
                alignItems: 'center',
                gap: '3px',
              }}
            >
              <span>{t(tab)}</span>
              <span style={{ fontSize: '9px', opacity: 0.7 }}>({counts[tab]})</span>
            </button>
          ))}
        </div>
      </div>

      {/* Feature List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
        {filteredItems.map(item => {
          const isSelected = selectedFeatureId === item.id || selectedFeatureIds.includes(item.id);
          const disp = item.disposition || 'UNDECIDED';
          const isBuilding = activeKind === 'building';
          const subtext = isBuilding
            ? `BAG Pand · ${t(String((item as Building).properties?.gebruiksdoel || 'footprint'))}`
            : `OSM · ${t((item as Segment).highway || 'segment')} · ${Math.round((item as Segment).length_m)}m`;

          return (
            <div
              key={item.id}
              id={`disp-item-${item.id}`}
              onClick={() => onSelectFeature(item.id, activeKind)}
              style={{
                padding: '8px 10px',
                marginBottom: '4px',
                borderRadius: 'var(--radius-sm)',
                backgroundColor: isSelected ? 'rgba(56, 189, 248, 0.12)' : 'var(--bg-surface-elevated)',
                border: `1px solid ${isSelected ? 'var(--border-focus)' : 'transparent'}`,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'stretch',
                cursor: 'pointer',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                <div>
                  <div style={{
                    fontSize: '11px',
                    fontWeight: 600,
                    fontFamily: 'var(--font-mono)',
                    color: isSelected ? 'var(--accent-cyan)' : 'var(--text-main)',
                  }}>
                    {item.id.length > 22 ? item.id.substring(0, 20) + '...' : item.id}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--text-dim)' }}>
                    {subtext}
                  </div>
                </div>

                {/* Disposition Action Buttons */}
                <div style={{ display: 'flex', gap: '3px', flexShrink: 0 }} onClick={e => e.stopPropagation()}>
                  <button
                    id={`btn-preserve-${item.id}`}
                    title={t("Preserve (Lock feature)")}
                    disabled={isSyncing}
                    onClick={() => requestSingleDisposition(item.id, 'PRESERVE')}
                    style={{
                      padding: '4px 6px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: disp === 'PRESERVE' ? 'rgba(16, 185, 129, 0.25)' : 'var(--bg-app)',
                      color: disp === 'PRESERVE' ? 'var(--accent-emerald)' : 'var(--text-dim)',
                      border: `1px solid ${disp === 'PRESERVE' ? 'var(--accent-emerald)' : 'var(--border-subtle)'}`,
                    }}
                  >
                    <Lock size={12} />
                  </button>
                  <button
                    id={`btn-editable-${item.id}`}
                    title={t("Editable (Scenario overlay)")}
                    disabled={isSyncing}
                    onClick={() => requestSingleDisposition(item.id, 'EDITABLE')}
                    style={{
                      padding: '4px 6px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: disp === 'EDITABLE' ? 'rgba(56, 189, 248, 0.25)' : 'var(--bg-app)',
                      color: disp === 'EDITABLE' ? 'var(--accent-cyan)' : 'var(--text-dim)',
                      border: `1px solid ${disp === 'EDITABLE' ? 'var(--accent-cyan)' : 'var(--border-subtle)'}`,
                    }}
                  >
                    <Unlock size={12} />
                  </button>
                  <button
                    id={`btn-undecided-${item.id}`}
                    title={t("Undecided")}
                    disabled={isSyncing}
                    onClick={() => requestSingleDisposition(item.id, 'UNDECIDED')}
                    style={{
                      padding: '4px 6px',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: disp === 'UNDECIDED' ? 'rgba(100, 116, 139, 0.25)' : 'var(--bg-app)',
                      color: disp === 'UNDECIDED' ? 'var(--text-muted)' : 'var(--text-dim)',
                      border: `1px solid ${disp === 'UNDECIDED' ? 'var(--text-muted)' : 'var(--border-subtle)'}`,
                    }}
                  >
                    <HelpCircle size={12} />
                  </button>
                </div>
              </div>

              {isSelected && (
                <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '8px', cursor: 'text' }}>
                  <span style={{ fontSize: '10px', color: 'var(--text-dim)' }}>{t("Local annotation · draft only")}</span>
                  <textarea
                    aria-label={t("Annotation for {0}", {"0": item.id})}
                    maxLength={500}
                    disabled={isSyncing}
                    placeholder={t("Local note for this feature (draft only)")}
                    value={item.annotation || ''}
                    onClick={event => event.stopPropagation()}
                    onChange={event => onUpdateAnnotation(item.id, activeKind, event.target.value)}
                    rows={2}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      resize: 'vertical',
                      padding: '6px 8px',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--border-subtle)',
                      backgroundColor: 'var(--bg-app)',
                      color: 'var(--text-main)',
                      font: 'inherit',
                      fontSize: '11px',
                    }}
                  />
                </label>
              )}
            </div>
          );
        })}
      </div>

      {/* Batch Actions Footer */}
      <div style={{
        padding: '10px 14px',
        borderTop: '1px solid var(--border-subtle)',
        backgroundColor: 'var(--bg-surface-elevated)',
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
      }}>
        <div id="selected-disposition-count" style={{ fontSize: '11px', color: 'var(--text-dim)' }} aria-live="polite">
          {selectedIds.length} {activeKind === 'building' ? t("building") : t("road")} {t("feature")}{selectedIds.length === 1 ? '' : t("s")} {t("selected")} </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          {([
            ['PRESERVE', 'Preserve'],
            ['EDITABLE', 'Editable'],
            ['UNDECIDED', 'Reset'],
          ] as const).map(([disposition, label]) => (
            <button
              key={disposition}
              id={`btn-selected-${disposition.toLowerCase()}-${activeKind}`}
              disabled={selectedIds.length === 0 || isSyncing}
              onClick={() => requestBatchDisposition(activeKind, disposition, selectedIds)}
              style={{
                flex: 1,
                padding: '5px',
                fontSize: '11px',
                backgroundColor: 'var(--bg-app)',
                color: selectedIds.length ? 'var(--text-main)' : 'var(--text-dim)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                cursor: selectedIds.length ? 'pointer' : 'not-allowed',
                opacity: selectedIds.length ? 1 : 0.6,
              }}
            >
              {t("Selected")} {selectedIds.length} {t(label)}
            </button>
          ))}
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
          {t("Assign all")} {activeKind === 'building' ? t("buildings") : t("roads")}:
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            id={`btn-batch-preserve-${activeKind}`}
            disabled={isSyncing}
            onClick={() => requestBatchDisposition(activeKind, 'PRESERVE')}
            style={{
              flex: 1,
              padding: '5px',
              fontSize: '11px',
              backgroundColor: 'rgba(16, 185, 129, 0.15)',
              color: 'var(--accent-emerald)',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              borderRadius: 'var(--radius-sm)',
              fontWeight: 500,
            }}
          >
            {t("All Preserve")} </button>
          <button
            id={`btn-batch-editable-${activeKind}`}
            disabled={isSyncing}
            onClick={() => requestBatchDisposition(activeKind, 'EDITABLE')}
            style={{
              flex: 1,
              padding: '5px',
              fontSize: '11px',
              backgroundColor: 'rgba(56, 189, 248, 0.15)',
              color: 'var(--accent-cyan)',
              border: '1px solid rgba(56, 189, 248, 0.3)',
              borderRadius: 'var(--radius-sm)',
              fontWeight: 500,
            }}
          >
            {t("All Editable")} </button>
          <button
            id={`btn-batch-undecided-${activeKind}`}
            disabled={isSyncing}
            onClick={() => requestBatchDisposition(activeKind, 'UNDECIDED')}
            style={{
              flex: 1,
              padding: '5px',
              fontSize: '11px',
              backgroundColor: 'rgba(100, 116, 139, 0.15)',
              color: 'var(--text-muted)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              fontWeight: 500,
            }}
          >
            {t("Reset")} </button>
        </div>
      </div>

      {pendingUnlock && (
        <div
          ref={unlockDialogRef}
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="unlock-preserved-title"
          aria-describedby="unlock-preserved-description"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1000,
            display: 'grid',
            placeItems: 'center',
            padding: '20px',
            backgroundColor: 'rgba(2, 6, 23, 0.72)',
          }}
        >
          <div style={{ maxWidth: '440px', width: '100%', padding: '18px', borderRadius: 'var(--radius-md)', backgroundColor: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', boxShadow: '0 18px 50px rgba(0, 0, 0, 0.35)' }}>
            <h2 id="unlock-preserved-title" style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--text-main)' }}>
              {pendingUnlock.mode === 'single' ? t("Unlock preserved feature?") : t("Unlock preserved features?")}
            </h2>
            <p id="unlock-preserved-description" style={{ margin: '0 0 16px', fontSize: '12px', lineHeight: 1.5, color: 'var(--text-muted)' }}>
              {pendingUnlock.mode === 'single'
                ? t("This will change the feature to {0} in this draft.", {"0": t(pendingUnlock.disposition === 'EDITABLE' ? 'Editable' : 'Undecided')})
                : t("This will unlock {0} preserved feature{1} and apply the selected batch change in this draft.", {"0": pendingUnlock.lockedCount, "1": pendingUnlock.lockedCount === 1 ? '' : 's'})}
              {' '}{t("The source data remains unchanged.")} </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                data-unlock-cancel="true"
                type="button"
                onClick={() => setPendingUnlock(null)}
                onFocus={event => { event.currentTarget.style.outline = '3px solid #fbbf24'; }}
                onBlur={event => { event.currentTarget.style.outline = 'none'; }}
                style={{
                  minHeight: '38px',
                  padding: '8px 12px',
                  border: '1px solid #64748b',
                  borderRadius: '6px',
                  backgroundColor: '#1a2234',
                  color: '#f1f5f9',
                  fontSize: '12px',
                  fontWeight: 600,
                  whiteSpace: 'nowrap',
                }}
              >
                {t("Cancel")} </button>
              <button
                type="button"
                onClick={confirmUnlock}
                disabled={isSyncing}
                onFocus={event => { event.currentTarget.style.outline = '3px solid #fbbf24'; }}
                onBlur={event => { event.currentTarget.style.outline = 'none'; }}
                style={{
                  minHeight: '38px',
                  padding: '8px 12px',
                  border: '1px solid #38bdf8',
                  borderRadius: '6px',
                  backgroundColor: '#075985',
                  color: '#f0f9ff',
                  fontSize: '12px',
                  fontWeight: 700,
                  whiteSpace: 'nowrap',
                }}
              >
                {pendingUnlock.mode === 'single'
                  ? t("Unlock and set {0}", {"0": t(pendingUnlock.disposition === 'EDITABLE' ? 'Editable' : 'Undecided')})
                  : t("Unlock and continue")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
