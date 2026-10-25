import { useEffect, useMemo, useState } from 'react';
import { useI18n, useT } from '../i18n';
import { SiteOpportunities } from './SiteOpportunities';
import type {
  DesignBriefRevision,
  DesignIntent,
  FrozenRef,
  Opportunity,
  OpportunityRejection,
  SavedBriefPayload,
} from './siteIntelligenceTypes';
import './DesignBriefPanel.css';

export interface DesignBriefPanelProps {
  projectId: string;
  workspaceRevision: number;
  workspaceRef: FrozenRef | null;
  analysisRef: FrozenRef | null;
  opportunityRef?: FrozenRef | null;
  inputHashes: Record<string, string>;
  defaultScopeRef?: FrozenRef | null;
  opportunities?: Opportunity[];
  apiBase?: string;
  canPersist?: boolean;
  readinessMessage?: string;
  initialSelectedOpportunityIds?: string[];
  initialRejectedOpportunities?: OpportunityRejection[];
  initialDraft?: SavedBriefPayload | null;
  sourceLimitations?: string[];
  onNavigateToSpatialZones?: () => void;
  onBriefSaved?: (saved: SavedBriefPayload) => void;
}

interface SavedBriefResponse {
  status: 'DRAFT';
  brief: DesignBriefRevision;
  rejected_opportunities: OpportunityRejection[];
  change_reason?: string;
  input_hashes: Record<string, string>;
  artifact_ref: FrozenRef;
  idempotent_replay?: boolean;
}

const createId = (prefix: string) => {
  const randomPart = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${randomPart}`;
};

const EMPTY_OPPORTUNITIES: Opportunity[] = [];

const restoreIntents = (
  savedIntents: DesignIntent[],
  selectedOpportunityIds: string[],
  opportunities: Opportunity[],
): DesignIntent[] => {
  const selectedIds = new Set(selectedOpportunityIds);
  const intents = savedIntents.filter((intent) =>
    intent.source_opportunity_ids.length === 0
    || intent.source_opportunity_ids.every((opportunityId) => selectedIds.has(opportunityId)));
  const restoredIds = new Set(intents.flatMap((intent) => intent.source_opportunity_ids));
  for (const opportunityId of selectedOpportunityIds) {
    if (restoredIds.has(opportunityId)) continue;
    const opportunity = opportunities.find((item) => item.id === opportunityId);
    if (!opportunity) continue;
    intents.push({
      id: `intent-${opportunity.id}`,
      text: opportunity.statement,
      scope_ref: opportunity.scope_ref,
      kind: 'PREFERENCE',
      source_opportunity_ids: [opportunity.id],
      origin: opportunity.origin,
      priority: null,
      version: 1,
    });
  }
  return intents;
};

export const DesignBriefPanel = ({
  projectId,
  workspaceRevision,
  workspaceRef,
  analysisRef,
  opportunityRef = null,
  inputHashes,
  defaultScopeRef,
  opportunities = EMPTY_OPPORTUNITIES,
  apiBase = '',
  canPersist,
  readinessMessage,
  initialSelectedOpportunityIds,
  initialRejectedOpportunities,
  initialDraft = null,
  sourceLimitations = [],
  onNavigateToSpatialZones,
  onBriefSaved,
}: DesignBriefPanelProps) => {
  const t = useT();
  const { language } = useI18n();
  const formatReadiness = (rawMessage: string | null | undefined) => {
    if (!rawMessage) return null;
    let human = t(rawMessage);
    if (human.startsWith('NOT_READY:')) {
      human = human.replace(/^NOT_READY:\s*/, language === 'zh-TW' ? '尚未就緒：' : 'Not ready: ');
    } else if (human.startsWith('BLOCKED:')) {
      human = human.replace(/^BLOCKED:\s*/, language === 'zh-TW' ? '已封鎖：' : 'Blocked: ');
    }
    return (
      <>
        {human}
        <span className="sr-only" style={{ display: 'none' }}>{rawMessage}</span>
      </>
    );
  };
  const selectedIdsForRestore = initialSelectedOpportunityIds
    ?? initialDraft?.brief?.selected_opportunity_ids
    ?? [];
  const rejectedForRestore = initialRejectedOpportunities
    ?? initialDraft?.rejected_opportunities
    ?? [];
  const hasMatchingRefs = Boolean(
    workspaceRef
    && analysisRef
    && defaultScopeRef
    && workspaceRef.revision === workspaceRevision
    && inputHashes[workspaceRef.id] === workspaceRef.sha256
    && inputHashes[analysisRef.id] === analysisRef.sha256,
  );
  const canSaveDraft = hasMatchingRefs && (canPersist ?? true);
  const selectedIdsKey = selectedIdsForRestore.join('\u001f');
  const rejectedKey = JSON.stringify(rejectedForRestore);
  const [newIntentText, setNewIntentText] = useState('');
  const [newIntentKind, setNewIntentKind] = useState<DesignIntent['kind']>('PREFERENCE');
  const [intents, setIntents] = useState<DesignIntent[]>(() => {
    return restoreIntents(initialDraft?.brief?.intents ?? [], selectedIdsForRestore, opportunities);
  });
  const [rejections, setRejections] = useState<OpportunityRejection[]>(() => {
    return rejectedForRestore;
  });
  const [changeReason, setChangeReason] = useState('Designer saved an editable draft brief.');
  const [briefId, setBriefId] = useState<string | null>(() => initialDraft?.brief?.id ?? null);
  const [parentRef, setParentRef] = useState<FrozenRef | null>(() => initialDraft?.artifact_ref ?? null);
  const [savedRevision, setSavedRevision] = useState<number | null>(() => initialDraft?.brief?.revision ?? null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveOutcomeUnknown, setSaveOutcomeUnknown] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pendingIdempotencyKey, setPendingIdempotencyKey] = useState<string | null>(null);
  const [pendingActorSessionId, setPendingActorSessionId] = useState<string | null>(null);

  useEffect(() => {
    if (!initialDraft) return;
    setBriefId(initialDraft.brief.id);
    setParentRef(initialDraft.artifact_ref);
    setSavedRevision(initialDraft.brief.revision);
    setIntents(restoreIntents(initialDraft.brief.intents, selectedIdsForRestore, opportunities));
    setRejections(rejectedForRestore);
    if (initialDraft.change_reason) setChangeReason(initialDraft.change_reason);
  }, [initialDraft?.artifact_ref.sha256, selectedIdsKey, rejectedKey, opportunityRef?.sha256]);

  // Attempt to restore latest draft on initial mount if not already populated
  useEffect(() => {
    if (initialDraft || briefId || !apiBase || !projectId) return;
    let cancelled = false;
    const fetchLatest = async () => {
      try {
        const res = await fetch(`${apiBase}/api/v1/projects/${encodeURIComponent(projectId)}/design-briefs/latest`);
        if (!res.ok) return;
        const data = await res.json() as SavedBriefPayload;
        if (!cancelled && data.brief) {
          setBriefId(data.brief.id);
          setParentRef(data.artifact_ref);
          setSavedRevision(data.brief.revision);
          setIntents(restoreIntents(
            data.brief.intents,
            initialSelectedOpportunityIds ?? data.brief.selected_opportunity_ids,
            opportunities,
          ));
          setRejections(initialRejectedOpportunities ?? data.rejected_opportunities);
          if (data.change_reason) setChangeReason(data.change_reason);
        }
      } catch {
        // network or not found; draft remains in fresh state
      }
    };
    void fetchLatest();
    return () => {
      cancelled = true;
    };
  }, [apiBase, projectId, initialDraft, briefId, selectedIdsKey, rejectedKey, opportunityRef?.sha256]);

  const selectedOpportunityIds = useMemo(
    () => Array.from(new Set(intents.flatMap((intent) => intent.source_opportunity_ids))),
    [intents],
  );
  const rejectedOpportunityIds = useMemo(
    () => rejections.map((rejection) => rejection.opportunity_id),
    [rejections],
  );
  const rejectedReasons = useMemo(
    () => Object.fromEntries(rejections.map((rejection) => [rejection.opportunity_id, rejection.reason])),
    [rejections],
  );

  const invalidatePendingKey = () => {
    setPendingIdempotencyKey(null);
    setPendingActorSessionId(null);
  };

  const addDesignerIntent = () => {
    const text = newIntentText.trim();
    if (!text) return;
    if (!defaultScopeRef) {
      setErrorMessage(t('Default StudyArea scope reference is not available. Please ensure StudyArea is loaded.'));
      return;
    }
    invalidatePendingKey();
    setIntents((current) => [
      ...current,
      {
        id: createId('intent'),
        text,
        scope_ref: defaultScopeRef,
        kind: newIntentKind,
        source_opportunity_ids: [],
        origin: 'DESIGNER_AUTHORED',
        priority: null,
        version: 1,
      },
    ]);
    setNewIntentText('');
  };

  const selectOpportunity = (opportunityId: string, selected: boolean) => {
    const opportunity = opportunities.find((item) => item.id === opportunityId);
    if (!opportunity) return;
    invalidatePendingKey();
    if (!selected) {
      setIntents((current) => current.filter((intent) => !intent.source_opportunity_ids.includes(opportunityId)));
      return;
    }
    setRejections((current) => current.filter((item) => item.opportunity_id !== opportunityId));
    setIntents((current) => {
      if (current.some((intent) => intent.source_opportunity_ids.includes(opportunityId))) return current;
      return [...current, {
        id: `intent-${opportunityId}`,
        text: opportunity.statement,
        scope_ref: opportunity.scope_ref,
        kind: 'PREFERENCE',
        source_opportunity_ids: [opportunityId],
        origin: opportunity.origin,
        priority: null,
        version: 1,
      }];
    });
  };

  const rejectOpportunity = (opportunityId: string, reason: string) => {
    invalidatePendingKey();
    setIntents((current) => current.filter((intent) => !intent.source_opportunity_ids.includes(opportunityId)));
    setRejections((current) => [
      ...current.filter((item) => item.opportunity_id !== opportunityId),
      { opportunity_id: opportunityId, reason },
    ]);
  };

  const undoRejection = (opportunityId: string) => {
    invalidatePendingKey();
    setRejections((current) => current.filter((item) => item.opportunity_id !== opportunityId));
  };

  const updateIntentText = (intentId: string, text: string) => {
    invalidatePendingKey();
    setIntents((current) => current.map((intent) => intent.id === intentId ? { ...intent, text } : intent));
  };

  const removeIntent = (intentId: string) => {
    invalidatePendingKey();
    setIntents((current) => current.filter((intent) => intent.id !== intentId));
  };

  const saveDraft = async () => {
    if (isSaving || !canSaveDraft || !workspaceRef || !analysisRef) return;
    setErrorMessage(null);
    setIsSaving(true);
    const nextBriefId = briefId ?? createId('brief');
    const nextIdempotencyKey = pendingIdempotencyKey ?? createId('brief-save');
    const nextActorSessionId = pendingActorSessionId ?? createId('design-brief-session');
    setBriefId(nextBriefId);
    setPendingIdempotencyKey(nextIdempotencyKey);
    setPendingActorSessionId(nextActorSessionId);
    const requestInputHashes = {
      ...inputHashes,
      [workspaceRef.id]: workspaceRef.sha256,
      [analysisRef.id]: analysisRef.sha256,
      ...Object.fromEntries(intents.map((intent) => [intent.scope_ref.id, intent.scope_ref.sha256])),
    };
    const body = {
      brief_id: nextBriefId,
      expected_workspace_revision: workspaceRevision,
      input_hashes: requestInputHashes,
      idempotency_key: nextIdempotencyKey,
      actor_session_id: nextActorSessionId,
      intents,
      selected_opportunity_ids: selectedOpportunityIds,
      rejected_opportunities: rejections,
      ...(parentRef ? { parent_ref: parentRef } : {}),
      change_reason: changeReason.trim() || 'Designer saved an editable draft brief.',
    };

    let confirmedSave = false;
    let definiteFailure = false;
    try {
      const response = await fetch(`${apiBase}/api/v1/projects/${encodeURIComponent(projectId)}/design-briefs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
      });
      const result = await response.json() as SavedBriefResponse & { detail?: string };
      if (!response.ok) {
        definiteFailure = true;
        throw new Error(result.detail || `Brief save failed with HTTP ${response.status}.`);
      }
      confirmedSave = true;
      const revision = result.brief.revision;
      setIntents(result.brief.intents);
      setRejections(result.rejected_opportunities);
      setParentRef(result.artifact_ref);
      setSavedRevision(revision);
      setPendingIdempotencyKey(null);
      setPendingActorSessionId(null);
      setSaveOutcomeUnknown(false);
      onBriefSaved?.(result);
      try {
        const reloadResponse = await fetch(
          `${apiBase}/api/v1/projects/${encodeURIComponent(projectId)}/design-briefs/${encodeURIComponent(result.brief.id)}/revisions/${revision}`,
          { headers: { Accept: 'application/json' } },
        );
        const reloaded = await reloadResponse.json() as SavedBriefResponse & { detail?: string };
        if (!reloadResponse.ok) throw new Error(reloaded.detail || String(reloadResponse.status));
        setIntents(reloaded.brief.intents);
        setRejections(reloaded.rejected_opportunities);
        setParentRef(reloaded.artifact_ref);
        setSavedRevision(reloaded.brief.revision);
      } catch (reloadError) {
        const detail = reloadError instanceof Error ? reloadError.message : 'unknown reload error';
        setErrorMessage(t('Draft revision {revision} was saved, but reload failed: {detail}', { revision, detail }));
      }
    } catch (error) {
      if (!confirmedSave && !definiteFailure) setSaveOutcomeUnknown(true);
      if (definiteFailure) {
        setPendingIdempotencyKey(null);
        setPendingActorSessionId(null);
      }
      setErrorMessage(error instanceof Error ? error.message : t('Brief save failed.'));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section aria-labelledby="design-brief-heading" className="design-brief-panel">
      <header>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 id="design-brief-heading">{t('Design brief · Draft')}</h2>
          {onNavigateToSpatialZones && (
            <button
              type="button"
              className="design-brief-nav-btn"
              onClick={onNavigateToSpatialZones}
            >
              {t('Spatial Zones')} →
            </button>
          )}
        </div>
        {workspaceRef && analysisRef ? (
          <>
            <p>
              {t('Bound to workspace revision {workspaceRevision} and analysis {analysisId}.', {
                workspaceRevision,
                analysisId: analysisRef.id,
              })}{' '}
              {t('Intent text is saved as a draft and does not activate a constraint.')}
            </p>
            {!canSaveDraft && readinessMessage && <p role="status">{formatReadiness(readinessMessage)}</p>}
          </>
        ) : (
          <p role="status">{formatReadiness(readinessMessage || 'NOT_READY: Matching workspace, persisted analysis, and StudyArea scope references are required.')}</p>
        )}
        {sourceLimitations.length > 0 && (
          <details>
            <summary>{t('Analysis limitations')}</summary>
            <ul>{sourceLimitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{t(limitation)}</li>)}</ul>
          </details>
        )}
      </header>

      <SiteOpportunities
        opportunities={opportunities}
        selectedOpportunityIds={selectedOpportunityIds}
        rejectedOpportunityIds={rejectedOpportunityIds}
        rejectedReasons={rejectedReasons}
        disabled={isSaving || saveOutcomeUnknown || !canSaveDraft}
        onSelect={selectOpportunity}
        onReject={rejectOpportunity}
        onUndoReject={undoRejection}
      />

      <section aria-labelledby="designer-intent-heading">
        <h3 id="designer-intent-heading">{t('Write an intent')}</h3>
        <label style={{ display: 'grid', gap: '5px' }}>
          <span>{t('New design intent')}</span>
          <textarea
            maxLength={2000}
            disabled={isSaving || saveOutcomeUnknown || !canSaveDraft}
            onChange={(event) => {
              invalidatePendingKey();
              setNewIntentText(event.target.value);
            }}
            value={newIntentText}
          />
        </label>
        <label style={{ display: 'grid', gap: '5px', marginTop: '8px' }}>
          <span>{t('Intent type')}</span>
          <select
            disabled={isSaving || saveOutcomeUnknown || !canSaveDraft}
            onChange={(event) => {
              invalidatePendingKey();
              setNewIntentKind(event.target.value as DesignIntent['kind']);
            }}
            value={newIntentKind}
          >
            <option value="PREFERENCE">{t('Preference')}</option>
            <option value="REQUIRED_FEATURE">{t('Required feature · draft')}</option>
            <option value="AVOID_FEATURE">{t('Avoid feature')}</option>
          </select>
        </label>
        <button
          type="button"
          disabled={isSaving || saveOutcomeUnknown || !canSaveDraft || !newIntentText.trim() || !defaultScopeRef}
          onClick={addDesignerIntent}
          style={{ marginTop: '8px' }}
        >
          {t('Add designer intent')}
        </button>
      </section>

      <section aria-labelledby="brief-intents-heading">
        <h3 id="brief-intents-heading">{t('Brief intents')}</h3>
        {intents.length === 0 && <p>{t('No intents in this draft yet.')}</p>}
        <ul style={{ display: 'grid', gap: '8px', listStyle: 'none', margin: 0, padding: 0 }}>
          {intents.map((intent) => (
            <li key={intent.id} style={{ borderLeft: '3px solid var(--accent-cyan, #22d3ee)', padding: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                <strong>{t(intent.kind.replaceAll('_', ' '))}</strong>
                <span>{t(intent.origin)}</span>
              </div>
              <label style={{ display: 'grid', gap: '5px', marginTop: '6px' }}>
                <span>{t('Intent text for {id}', { id: intent.id })}</span>
                <textarea
                  maxLength={2000}
                  disabled={isSaving || saveOutcomeUnknown || !canSaveDraft}
                  onChange={(event) => updateIntentText(intent.id, event.target.value)}
                  value={intent.text}
                />
              </label>
              <div style={{ color: 'var(--text-dim, #94a3b8)', fontSize: '11px', marginTop: '5px' }}>
                {t('Scope: {scopeId} · {sha256}', {
                  scopeId: intent.scope_ref.id,
                  sha256: intent.scope_ref.sha256,
                })}
              </div>
              <button
                type="button"
                disabled={isSaving || saveOutcomeUnknown || !canSaveDraft}
                onClick={() => removeIntent(intent.id)}
                style={{ marginTop: '6px' }}
              >
                {t('Remove intent from this draft')}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <label style={{ display: 'grid', gap: '5px' }}>
        <span>{t('Reason for this draft revision')}</span>
        <textarea
          maxLength={1000}
          disabled={isSaving || saveOutcomeUnknown || !canSaveDraft}
          onChange={(event) => {
            setPendingIdempotencyKey(null);
            setChangeReason(event.target.value);
          }}
          value={changeReason}
        />
      </label>

      {errorMessage && <p role="alert">{errorMessage}</p>}
      {savedRevision !== null && (
        <p aria-live="polite">{t('Saved draft revision {revision}', { revision: savedRevision })}</p>
      )}
      {saveOutcomeUnknown && (
        <p role="status">
          {t('Save outcome is unknown. Retry without editing so the server can reconcile this idempotency key.')}
        </p>
      )}
      <button
        type="button"
        disabled={isSaving || workspaceRevision < 1 || !canSaveDraft}
        onClick={() => void saveDraft()}
      >
        {isSaving
          ? t('Saving draft…')
          : saveOutcomeUnknown || pendingIdempotencyKey
          ? t('Retry draft save')
          : t('Save draft brief')}
      </button>
    </section>
  );
};
