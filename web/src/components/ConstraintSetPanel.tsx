import { useT } from '../i18n';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { HumanDecisionDialog } from './HumanDecisionDialog';
import type { HumanDecisionSubmission } from './HumanDecisionDialog';
import { getActorSessionId } from '../utils/actorProvenance';
import './ConstraintSetPanel.css';

export type ConstraintSetSummary = {
  id: string;
  version: string;
  status: string;
  notes?: string | null;
  allocation_policy?: string | null;
  revision: number;
  payload_digest: string;
  constraint_count?: number;
};

type Denominator = 'land_area' | 'exploration_design_area';
type Enforcement = 'HARD' | 'PREFERENCE';
type EnforcementChoice = Enforcement | '';
type ConstraintRow = {
  id: string;
  name: string;
  label: string;
  unit: string;
  scope: string;
  value: string;
  enforcement: EnforcementChoice;
  source_note?: string;
  denominator?: Denominator;
};
type ConstraintSetPayload = {
  id: string;
  project_id: string;
  version: string;
  status: string;
  allocation_policy: string | null;
  notes?: string | null;
  constraints: Array<{
    id: string;
    name: string;
    value: number;
    unit: string;
    scope: string;
    enforcement: Enforcement;
    status: string;
    source_refs: string[];
    source_note?: string | null;
    denominator?: Denominator | null;
  }>;
};
type ConstraintSetResponse = {
  constraint_set: ConstraintSetPayload;
  revision: number;
  payload_digest: string;
};

const initialRows: ConstraintRow[] = [
  { id: 'constraint-far-site', name: 'far_upper_limit', denominator: 'land_area', label: 'Overall FAR cap', unit: 'ratio', scope: 'whole_site', value: '', enforcement: '' },
  { id: 'constraint-coverage-site', name: 'coverage_upper_limit', label: 'Coverage ratio cap', unit: 'ratio', scope: 'whole_site', value: '', enforcement: '' },
  { id: 'constraint-height-site', name: 'height_upper_limit', label: 'Maximum height', unit: 'm', scope: 'whole_site', value: '', enforcement: '' },
  { id: 'constraint-first-floor', name: 'first_floor_height', label: 'First-floor height', unit: 'm', scope: 'whole_site', value: '', enforcement: '' },
  { id: 'constraint-standard-floor', name: 'standard_floor_height', label: 'Standard-floor height', unit: 'm', scope: 'whole_site', value: '', enforcement: '' },
  { id: 'constraint-rotation', name: 'rotation_step', label: 'Rotation step', unit: 'degree', scope: 'whole_site', value: '', enforcement: '' },
];

function requireEnforcement(value: EnforcementChoice): Enforcement {
  if (value !== 'HARD' && value !== 'PREFERENCE') throw new Error('Choose Hard or Preference for every constraint.');
  return value;
}

interface ConstraintSetPanelProps {
  apiBase: string;
  projectId: string;
  onSubmitDecision: (decision: HumanDecisionSubmission) => Promise<void>;
}

export const ConstraintSetPanel: React.FC<ConstraintSetPanelProps> = ({
  apiBase,
  projectId,
  onSubmitDecision,
}) => {
  const t = useT();
  const [rows, setRows] = useState(initialRows);
  const [zoneRows, setZoneRows] = useState<Array<{ id: string; zoneId: string; value: string; enforcement: EnforcementChoice; source_note?: string; denominator?: Denominator }>>([]);
  const [roadRows, setRoadRows] = useState<Array<{ id: string; hierarchy: string; value: string; enforcement: EnforcementChoice; source_note?: string }>>([
    { id: 'constraint-road-1', hierarchy: '', value: '', enforcement: '' },
  ]);
  const [notes, setNotes] = useState('');
  const [loadId, setLoadId] = useState('');
  const [allocationPolicy, setAllocationPolicy] = useState('');
  const [savedDraft, setSavedDraft] = useState<ConstraintSetResponse | null>(null);
  const [availableSets, setAvailableSets] = useState<ConstraintSetSummary[]>([]);
  const [isLoadingSets, setIsLoadingSets] = useState(false);
  const [isDecisionOpen, setIsDecisionOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const fetchAvailableSets = useCallback(async () => {
    if (!apiBase || !projectId) return;
    setIsLoadingSets(true);
    try {
      const response = await fetch(`${apiBase}/api/v1/projects/${projectId}/constraint-sets`);
      if (!response.ok) return;
      const data = await response.json().catch(() => null);
      const items: ConstraintSetSummary[] = Array.isArray(data) ? data : (data?.items || []);
      setAvailableSets(items);
    } catch {
      // Ignore network errors on initial list fetch
    } finally {
      setIsLoadingSets(false);
    }
  }, [apiBase, projectId]);

  useEffect(() => {
    void fetchAvailableSets();
  }, [fetchAvailableSets]);

  const constraints = useMemo(() => {
    const fixed = rows.map(row => ({
      id: row.id,
      name: row.name,
      value: Number(row.value),
      unit: row.unit,
      scope: row.scope,
      enforcement: row.enforcement,
      status: 'proposed',
      source_refs: [],
      source_note: row.source_note || null,
      ...(row.name === 'far_upper_limit' ? { denominator: row.denominator || 'land_area' } : {}),
    }));
    const roads = roadRows.map(row => ({
      id: row.id,
      name: 'road_width',
      value: Number(row.value),
      unit: 'm',
      scope: `road:${row.hierarchy.trim()}`,
      enforcement: row.enforcement,
      status: 'proposed',
      source_refs: [],
      source_note: row.source_note || null,
    }));
    const zones = zoneRows
      .filter(row => row.zoneId.trim() && row.value.trim())
      .map(row => ({
        id: row.id,
        name: 'zone_far_upper_limit',
        value: Number(row.value),
        unit: 'ratio',
        scope: `zone:${row.zoneId.trim()}`,
        enforcement: row.enforcement,
        status: 'proposed',
        source_refs: [],
        source_note: row.source_note || null,
        denominator: row.denominator || 'land_area',
      }));
    return [...fixed, ...roads, ...zones];
  }, [rows, roadRows, zoneRows]);

  const updateRow = (id: string, patch: Partial<ConstraintRow>) => {
    setRows(current => current.map(row => row.id === id ? { ...row, ...patch } : row));
  };

  const setRoad = (id: string, patch: Partial<(typeof roadRows)[number]>) => {
    setRoadRows(current => current.map(row => row.id === id ? { ...row, ...patch } : row));
  };

  const setZone = (id: string, patch: Partial<(typeof zoneRows)[number]>) => {
    setZoneRows(current => current.map(row => row.id === id ? { ...row, ...patch } : row));
  };

  const refreshDraft = async (constraintSetId: string) => {
    const response = await fetch(`${apiBase}/api/v1/projects/${projectId}/constraint-sets/${constraintSetId}`);
    const result = await response.json().catch(() => null);
    if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `ConstraintSet reload failed with HTTP ${response.status}.`);
    const loaded = result as ConstraintSetResponse;
    const items = loaded.constraint_set.constraints;
    setRows(items.filter(item => item.name !== 'road_width' && item.name !== 'zone_far_upper_limit').map(item => ({
      ...item, label: initialRows.find(row => row.name === item.name)?.label || item.name,
      value: String(item.value), source_note: item.source_note || '', denominator: item.denominator || undefined,
    })));
    setRoadRows(items.filter(item => item.name === 'road_width').map(item => ({
      id: item.id, hierarchy: item.scope.replace(/^road:/, ''), value: String(item.value),
      enforcement: item.enforcement, source_note: item.source_note || '',
    })));
    setZoneRows(items.filter(item => item.name === 'zone_far_upper_limit').map(item => ({
      id: item.id, zoneId: item.scope.replace(/^zone:/, ''), value: String(item.value),
      enforcement: item.enforcement, source_note: item.source_note || '', denominator: item.denominator || undefined,
    })));
    setNotes(loaded.constraint_set.notes || '');
    setSavedDraft(loaded);
  };

  const saveDraft = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSaving) return;
    setIsSaving(true);
    setError(null);
    setMessage(null);
    try {
      if (rows.some(row => !row.value.trim()) || roadRows.some(row => !row.hierarchy.trim() || !row.value.trim())) {
        throw new Error('Fill each required value and give every road width a designer-defined hierarchy label.');
      }
      [...rows, ...roadRows, ...zoneRows].forEach(row => requireEnforcement(row.enforcement));
      if ([...rows, ...roadRows].some(row => !Number.isFinite(Number(row.value)))) {
        throw new Error('Constraint values must be finite numbers.');
      }
      const response = await fetch(`${apiBase}/api/v1/projects/${projectId}/constraint-sets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          constraints,
          notes: notes || null,
          allocation_policy: allocationPolicy || null,
          actor_session_id: getActorSessionId(),
        }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof result?.detail === 'string' ? result.detail : `ConstraintSet save failed with HTTP ${response.status}.`);
      const saved = result as ConstraintSetResponse;
      await refreshDraft(saved.constraint_set.id);
      void fetchAvailableSets();
      setMessage('Draft saved. No constraint is active until the designer confirms it.');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'ConstraintSet draft could not be saved.');
    } finally {
      setIsSaving(false);
    }
  };

  const submitDecision = async (decision: HumanDecisionSubmission) => {
    await onSubmitDecision(decision);
    if (savedDraft) {
      try {
        await refreshDraft(savedDraft.constraint_set.id);
        void fetchAvailableSets();
        setMessage('Decision recorded. ConstraintSet state reloaded from the server.');
      } catch {
        setMessage('Decision recorded. Reload the ConstraintSet to confirm its latest state.');
      }
    }
  };

  const denominatorText = (value?: Denominator | null) => t(value === 'land_area' ? 'Denominator: land area' : value === 'exploration_design_area' ? 'Denominator: exploration design area' : 'Denominator: unspecified (legacy)');
  const denominatorControl = (id: string, value: Denominator | undefined, update: (value: Denominator) => void) => savedDraft
    ? <p>{denominatorText(savedDraft.constraint_set.constraints.find(item => item.id === id)?.denominator)}</p>
    : <select aria-label={t('FAR denominator {0}', { '0': id })} value={value || 'land_area'} onChange={event => update(event.target.value as Denominator)}>
        <option value="land_area">{t('Denominator: land area')}</option>
        <option value="exploration_design_area">{t('Denominator: exploration design area')}</option>
      </select>;
  const sourceControl = (id: string, value: string | undefined, update: (value: string) => void) => savedDraft
    ? <span><span>{savedDraft.constraint_set.constraints.find(item => item.id === id)?.source_note || t('Pending')}</span><br />{savedDraft.constraint_set.constraints.find(item => item.id === id)?.source_refs.join(', ') || t('Pending HumanDecision')}</span>
    : <input aria-label={t('Source note {0}', { '0': id })} value={value || ''} onChange={event => update(event.target.value)} />;

  return (
    <section className="constraint-set-panel" aria-labelledby="constraint-set-title">
      <header className="constraint-set-panel__header">
        <div>
          <h2 id="constraint-set-title">{t("Constraint set")}</h2>
          <p>{t("Values remain a draft until a designer approves this exact version and hash.")}</p>
        </div>
        {savedDraft && <span className={`constraint-set-panel__status constraint-set-panel__status--${savedDraft.constraint_set.status}`}>{t(savedDraft.constraint_set.status.toUpperCase())}</span>}
      </header>

      {!savedDraft && (
        <div className="constraint-set-panel__list-section" data-testid="constraint-set-list-section">
          <div className="constraint-set-panel__list-header">
            <h3>{t("Available constraint sets")}</h3>
            {isLoadingSets && <span className="constraint-set-panel__loading-hint">{t("Loading…")}</span>}
          </div>
          {availableSets.length > 0 ? (
            <div className="constraint-set-panel__card-list" role="list">
              {availableSets.map(item => {
                const isSelected = loadId === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="listitem"
                    className={`constraint-set-panel__card-item ${isSelected ? 'constraint-set-panel__card-item--selected' : ''}`}
                    onClick={() => {
                      setError(null);
                      setLoadId(item.id);
                      void refreshDraft(item.id).catch(caught => setError(caught instanceof Error ? caught.message : String(caught)));
                    }}
                    data-testid={`constraint-set-card-${item.id}`}
                  >
                    <div className="constraint-set-panel__card-row">
                      <span className="constraint-set-panel__card-id">{item.id}</span>
                      <span className={`constraint-set-panel__status constraint-set-panel__status--${item.status.toLowerCase()}`}>
                        {t(item.status.toUpperCase())}
                      </span>
                    </div>
                    <div className="constraint-set-panel__card-meta">
                      <span>{t("Version")} {item.version}</span>
                      {item.notes && <span className="constraint-set-panel__card-notes" title={item.notes}>{item.notes}</span>}
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            !isLoadingSets && <p className="constraint-set-panel__empty-hint">{t("No saved constraint sets found.")}</p>
          )}

          <details className="constraint-set-panel__manual-load" open={availableSets.length === 0}>
            <summary>{t("Manual ID lookup")}</summary>
            <div className="constraint-set-panel__manual-inputs">
              <label>
                {t('ConstraintSet ID')}{' '}
                <input
                  aria-label={t('ConstraintSet ID')}
                  placeholder="constraint-set-..."
                  value={loadId}
                  onChange={event => setLoadId(event.target.value)}
                />
              </label>
              <button
                type="button"
                disabled={!loadId.trim()}
                onClick={() => {
                  setError(null);
                  void refreshDraft(loadId.trim()).catch(caught => setError(caught instanceof Error ? caught.message : String(caught)));
                }}
              >
                {t('Load draft')}
              </button>
            </div>
          </details>
        </div>
      )}
      <form onSubmit={saveDraft}>
        <label>{t('Notes')} <textarea disabled={Boolean(savedDraft)} value={notes} onChange={event => setNotes(event.target.value)} /></label>
        <div className="constraint-set-panel__table-wrap">
          <table className="constraint-set-panel__table">
            <thead><tr><th>{t("Parameter")}</th><th>{t("Value")}</th><th>{t("Unit")}</th><th>{t("Scope")}</th><th>{t("Type")}</th><th>{t("Source")}</th></tr></thead>
            <tbody>
              {rows.map(row => (
                <tr key={row.id}>
                  <th scope="row">{t(row.label)}</th>
                  <td><input aria-label={row.name === 'far_upper_limit' ? t("Overall FAR cap") : row.name === 'coverage_upper_limit' ? t("Coverage ratio cap") : row.name === 'height_upper_limit' ? t("Maximum height (m)") : row.name === 'first_floor_height' ? t("First-floor height (m)") : row.name === 'standard_floor_height' ? t("Standard-floor height (m)") : t("Rotation step (degrees)")} disabled={Boolean(savedDraft)} inputMode="decimal" onChange={event => updateRow(row.id, { value: event.target.value })} type="number" value={row.value} /></td>
                  <td>{t(row.unit)}{row.name === 'far_upper_limit' && denominatorControl(row.id, row.denominator, denominator => updateRow(row.id, { denominator }))}</td><td>{t(row.scope)}</td>
                  <td><select aria-label={t("{0} type", {"0": t(row.label)})} disabled={Boolean(savedDraft)} onChange={event => updateRow(row.id, { enforcement: event.target.value as EnforcementChoice })} value={row.enforcement}><option value="">{t("Choose")}</option><option value="HARD">{t("Hard")}</option><option value="PREFERENCE">{t("Preference")}</option></select></td>
                  <td>{sourceControl(row.id, row.source_note, source_note => updateRow(row.id, { source_note }))}</td>
                </tr>
              ))}
              {roadRows.map((row, index) => (
                <tr key={row.id}>
                  <th scope="row">{t("Road width")} {index + 1}</th>
                  <td><div className="constraint-set-panel__road-inputs"><input aria-label={t("Road hierarchy")} disabled={Boolean(savedDraft)} onChange={event => setRoad(row.id, { hierarchy: event.target.value })} placeholder={t("Designer-defined label")} value={row.hierarchy} /><input aria-label={t("Road width (m)")} disabled={Boolean(savedDraft)} inputMode="decimal" onChange={event => setRoad(row.id, { value: event.target.value })} type="number" value={row.value} /></div></td>
                  <td>{t("m")}</td><td>{row.hierarchy.trim() ? t("road:{0}", {"0": row.hierarchy.trim()}) : t("road:<hierarchy>")}</td>
                  <td><select aria-label={t("Road width {0} type", {"0": index + 1})} disabled={Boolean(savedDraft)} onChange={event => setRoad(row.id, { enforcement: event.target.value as EnforcementChoice })} value={row.enforcement}><option value="">{t("Choose")}</option><option value="HARD">{t("Hard")}</option><option value="PREFERENCE">{t("Preference")}</option></select></td>
                  <td>{sourceControl(row.id, row.source_note, source_note => setRoad(row.id, { source_note }))}</td>
                </tr>
              ))}
              {zoneRows.map((row, index) => (
                <tr key={row.id}>
                  <th scope="row">{t("Zone FAR")} {index + 1}</th>
                  <td><div className="constraint-set-panel__road-inputs"><input aria-label={t("Zone ID")} disabled={Boolean(savedDraft)} onChange={event => setZone(row.id, { zoneId: event.target.value })} value={row.zoneId} /><input aria-label={t("Zone FAR cap")} disabled={Boolean(savedDraft)} inputMode="decimal" onChange={event => setZone(row.id, { value: event.target.value })} type="number" value={row.value} /></div></td>
                  <td>{t("ratio")}{denominatorControl(row.id, row.denominator, denominator => setZone(row.id, { denominator }))}</td><td>{row.zoneId.trim() ? t("zone:{0}", {"0": row.zoneId.trim()}) : t("zone:<id>")}</td>
                  <td><select aria-label={t("Zone FAR {0} type", {"0": index + 1})} disabled={Boolean(savedDraft)} onChange={event => setZone(row.id, { enforcement: event.target.value as EnforcementChoice })} value={row.enforcement}><option value="">{t("Choose")}</option><option value="HARD">{t("Hard")}</option><option value="PREFERENCE">{t("Preference")}</option></select></td>
                  <td>{sourceControl(row.id, row.source_note, source_note => setZone(row.id, { source_note }))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!savedDraft && (
          <div className="constraint-set-panel__controls">
            <label>{t("Zone allocation policy")} <select aria-label={t("Zone allocation policy")} onChange={event => setAllocationPolicy(event.target.value)} value={allocationPolicy}>
                <option value="">{t("No overlap rule")}</option>
                <option value="priority">{t("Priority (workspace zone order)")}</option>
              </select>
            </label>
            <button onClick={() => setRoadRows(current => [...current, { id: `constraint-road-${current.length + 1}`, hierarchy: '', value: '', enforcement: '' }])} type="button">{t("Add road hierarchy")}</button>
            <button onClick={() => setZoneRows(current => [...current, { id: `constraint-zone-far-${current.length + 1}`, zoneId: '', value: '', enforcement: '', denominator: 'land_area' }])} type="button">{t("Add zone FAR")}</button>
            <button disabled={isSaving} type="submit">{isSaving ? t("Saving…") : t("Save draft")}</button>
          </div>
        )}
      </form>

      {savedDraft && <div className="constraint-set-panel__saved">
        <p>{t("Version")} {savedDraft.constraint_set.version} {t("· revision")} {savedDraft.revision}</p>
        <p className="constraint-set-panel__digest">{t("Approval hash:")} {savedDraft.payload_digest}</p>
        {savedDraft.constraint_set.status === 'proposed' && <button className="constraint-set-panel__activate-btn" onClick={() => setIsDecisionOpen(true)} type="button">{t("Confirm and activate")}</button>}
      </div>}
      {message && <p role="status" className="constraint-set-panel__message">{t(message)}</p>}
      {error && <p role="alert" className="constraint-set-panel__error">{t(error)}</p>}

      {savedDraft && <HumanDecisionDialog
        isOpen={isDecisionOpen}
        target={{
          id: savedDraft.constraint_set.id,
          type: 'ConstraintSet',
          version: savedDraft.constraint_set.version,
          payloadDigest: savedDraft.payload_digest,
        }}
        reviewContent={<div>
          <p>{t('Notes')}: {savedDraft.constraint_set.notes || t('Pending')}</p>
          <ul>{savedDraft.constraint_set.constraints.map(item => <li key={item.id}>
            {item.name} ({item.scope}): {item.value} {item.unit} — {item.enforcement}
            {item.name.includes('far_upper_limit') && <p>{denominatorText(item.denominator)}</p>}
            <p>{t('Source note')}: {item.source_note || t('Pending')}</p>
          </li>)}</ul>
        </div>}
        action="Approve"
        status="approved"
        onClose={() => setIsDecisionOpen(false)}
        onSubmit={submitDecision}
      />}
    </section>
  );
};
