import React, { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useI18n, useT } from '../i18n';
import './AriadnePanel.css';

export type AriadneSourceType = 'evidence_card' | 'problem' | 'syntax_layer' | 'workspace' | 'unknown';

export interface AriadnePanelMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  evidenceRefs: string[];
  evidenceSourceTypes?: Record<string, AriadneSourceType>;
  providerStatus?: string | null;
}

export interface AriadneDecisionNeeded {
  id: string;
  title: string;
  sourceId: string;
  sourceType?: AriadneSourceType;
  sourceIds?: string[];
  reason?: string;
}

export type AriadneScreenState = 'OFFLINE' | 'LIVE' | 'BLOCKED' | 'OUTCOME_UNKNOWN';

export interface AriadnePanelStatus {
  mode: 'LIVE' | 'OFFLINE';
  screenState?: AriadneScreenState;
  blockReason?: string | null;
  weeklyCallsUsed?: number | null;
  weeklyCallLimit?: number | null;
}

export interface AriadnePanelLabels {
  title: string;
  liveBadge: string;
  offlineBadge: string;
  blockedBadge: string;
  outcomeUnknownBadge: string;
  decisionHeading: string;
  noDecisions: string;
  loadingDecisions: string;
  viewSources: string;
  conversationHeading: string;
  emptyConversation: string;
  userRole: string;
  assistantRole: string;
  askPlaceholder: string;
  askLabel: string;
  send: string;
  sending: string;
  evidenceCard: string;
  problem: string;
  syntaxLayer: string;
  openSource: string;
  weeklyUsage: string;
  submitError: string;
}

const DEFAULT_LABELS: AriadnePanelLabels = {
  title: 'Ariadne',
  liveBadge: 'Live AI',
  offlineBadge: 'Offline',
  blockedBadge: 'Blocked',
  outcomeUnknownBadge: 'Outcome unknown',
  decisionHeading: 'Decisions needed',
  noDecisions: 'No pending decisions.',
  loadingDecisions: 'Loading decisions…',
  viewSources: 'View {count} source cards',
  conversationHeading: 'Conversation',
  emptyConversation: 'Ask a question about the current evidence.',
  userRole: 'You',
  assistantRole: 'Ariadne',
  askPlaceholder: 'Ask Ariadne about the evidence…',
  askLabel: 'Ask Ariadne',
  send: 'Send message',
  sending: 'Sending…',
  evidenceCard: 'Evidence card',
  problem: 'Problem',
  syntaxLayer: 'Syntax layer',
  openSource: 'Open source',
  weeklyUsage: 'Weekly ModelRun usage: {used} / {limit}',
  submitError: 'The message could not be sent.',
};

export interface AriadnePanelProps {
  messages: AriadnePanelMessage[];
  evidenceCardLabels?: Record<string, { source: string; localized: string }>;
  decisionsNeeded: AriadneDecisionNeeded[];
  status: AriadnePanelStatus;
  onSendMessage: (message: string) => void | Promise<void>;
  onEvidenceClick: (evidenceId: string, sourceType?: AriadneSourceType) => void;
  labels?: Partial<AriadnePanelLabels>;
  sending?: boolean;
  decisionsLoading?: boolean;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
}

function localizeOfflineEvidenceCardNames(
  message: AriadnePanelMessage,
  labels: Record<string, { source: string; localized: string }>,
): string {
  const providerStatus = message.providerStatus ?? '';
  const isOfflineTemplate = providerStatus === 'NON_AI: DETERMINISTIC_TEMPLATE'
    || providerStatus.startsWith('LIVE_AI:') && providerStatus !== 'LIVE_AI: ACTIVE';
  if (message.role !== 'assistant' || !isOfflineTemplate) return message.content;

  let content = message.content;
  for (const evidenceId of message.evidenceRefs) {
    if (message.evidenceSourceTypes?.[evidenceId] !== 'evidence_card') continue;
    const label = labels[evidenceId];
    if (!label || !label.source || label.source === label.localized) continue;

    const citationIndex = content.indexOf(`[${evidenceId}]`);
    if (citationIndex < 0) continue;
    const lineStart = content.lastIndexOf('\n', citationIndex - 1) + 1;
    const nextLineBreak = content.indexOf('\n', citationIndex);
    const lineEnd = nextLineBreak < 0 ? content.length : nextLineBreak;
    const line = content.slice(lineStart, lineEnd);
    if (!line.startsWith(`${label.source}:`) && !line.startsWith(`${label.source}：`)) continue;

    content = `${content.slice(0, lineStart)}${label.localized}${line.slice(label.source.length)}${content.slice(lineEnd)}`;
  }
  return content;
}

export const AriadnePanel: React.FC<AriadnePanelProps> = ({
  messages,
  evidenceCardLabels = {},
  decisionsNeeded,
  status,
  onSendMessage,
  onEvidenceClick,
  labels,
  sending = false,
  decisionsLoading = false,
  isExpanded = false,
  onToggleExpand,
}) => {
  const copy = { ...DEFAULT_LABELS, ...labels };
  const t = useT();
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  const screenState: AriadneScreenState = status.screenState ?? (status.mode === 'LIVE' ? 'LIVE' : 'OFFLINE');
  const statusLabel = screenState === 'LIVE'
    ? copy.liveBadge
    : screenState === 'BLOCKED'
      ? copy.blockedBadge
      : screenState === 'OUTCOME_UNKNOWN'
        ? copy.outcomeUnknownBadge
        : copy.offlineBadge;
  const [draft, setDraft] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [submitError, setSubmitError] = useState('');

  const submitMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const message = draft.trim();
    if (!message || sending || isSending) return;
    setIsSending(true);
    try {
      await onSendMessage(message);
      setDraft('');
      setSubmitError('');
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : copy.submitError);
    } finally {
      setIsSending(false);
    }
  };

  return (
    <section className="ariadne-panel" aria-label={copy.title}>
      <header className="ariadne-panel__header">
        <div className="ariadne-panel__identity">
          <span className="ariadne-panel__mark" aria-hidden="true">A</span>
          <h2>{copy.title}</h2>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {onToggleExpand && (
            <button
              type="button"
              className="ariadne-panel__expand-toggle"
              data-testid="ariadne-expand-toggle"
              aria-label={isExpanded ? (zh ? '收合面板' : 'Collapse panel') : (zh ? '展開面板' : 'Expand panel')}
              onClick={onToggleExpand}
            >
              {isExpanded
                ? (zh ? '⤡ 收合' : '⤡ 260px')
                : (zh ? '⤢ 展開' : '⤢ 520px')}
            </button>
          )}
          <span
            className={`ariadne-panel__status ariadne-panel__status--${screenState === 'LIVE' ? 'live' : 'offline'}`}
            data-testid="ariadne-status"
            data-screen-state={screenState.toLowerCase()}
            role="status"
          >
            <span className="ariadne-panel__status-dot" aria-hidden="true" />
            {statusLabel}
          </span>
        </div>
      </header>

      {screenState !== 'LIVE' && status.blockReason && (
        <p className="ariadne-panel__offline-reason">{status.blockReason}</p>
      )}
      {typeof status.weeklyCallsUsed === 'number' && typeof status.weeklyCallLimit === 'number' && (
        <p className="ariadne-panel__weekly-usage">
          {copy.weeklyUsage.replace('{used}', String(status.weeklyCallsUsed)).replace('{limit}', String(status.weeklyCallLimit))}
        </p>
      )}

      <section className="ariadne-panel__decisions" aria-labelledby="ariadne-decisions-heading">
        <div className="ariadne-panel__section-heading">
          <h3 id="ariadne-decisions-heading">{copy.decisionHeading}</h3>
          {!decisionsLoading && <span className="ariadne-panel__count" data-testid="ariadne-decisions-count">{decisionsNeeded.length}</span>}
        </div>
        {decisionsLoading ? (
          <p className="ariadne-panel__empty">{copy.loadingDecisions}</p>
        ) : decisionsNeeded.length === 0 ? (
          <p className="ariadne-panel__empty">{copy.noDecisions}</p>
        ) : (
          <ul>
            {decisionsNeeded.map((item) => (
              <li key={item.id} className="ariadne-panel__decision">
                <div>
                  <strong>{t(item.title)}</strong>
                  {item.reason && <p>{t(item.reason)}</p>}
                </div>
                {(item.sourceIds?.length ?? 0) > 1 ? (
                  <details>
                    <summary>{copy.viewSources.replace('{count}', String(item.sourceIds?.length))}</summary>
                    <ul>
                      {item.sourceIds?.map((sourceId) => (
                        <li key={sourceId}>
                          <button
                            type="button"
                            className="ariadne-panel__source"
                            aria-label={`${copy.openSource} ${sourceId}`}
                            onClick={() => onEvidenceClick(sourceId, item.sourceType)}
                          >
                            {sourceId}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : (
                  <button
                    type="button"
                    className="ariadne-panel__source"
                    aria-label={`${copy.openSource} ${item.sourceId}`}
                    onClick={() => onEvidenceClick(item.sourceId, item.sourceType)}
                  >
                    {item.sourceId}
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="ariadne-panel__conversation" aria-labelledby="ariadne-conversation-heading">
        <div className="ariadne-panel__section-heading">
          <h3 id="ariadne-conversation-heading">{copy.conversationHeading}</h3>
        </div>
        <div className="ariadne-panel__messages" aria-live="polite">
          {messages.length === 0 ? (
            <p className="ariadne-panel__empty">{copy.emptyConversation}</p>
          ) : messages.map((message) => (
            <article key={message.id} className={`ariadne-panel__message ariadne-panel__message--${message.role}`}>
              <div className="ariadne-panel__message-role">
                {message.role === 'user' ? copy.userRole : copy.assistantRole}
              </div>
              <p className="ariadne-panel__message-content">{localizeOfflineEvidenceCardNames(message, evidenceCardLabels)}</p>
              {message.evidenceRefs.length > 0 && (
                <div className="ariadne-panel__citations" aria-label={copy.evidenceCard}>
                  {message.evidenceRefs.map((evidenceId) => (
                    <button
                      key={evidenceId}
                      type="button"
                      className="ariadne-panel__citation"
                      aria-label={`${message.evidenceSourceTypes?.[evidenceId] === 'problem'
                        ? copy.problem
                        : message.evidenceSourceTypes?.[evidenceId] === 'syntax_layer'
                          ? copy.syntaxLayer
                          : copy.evidenceCard} ${evidenceId}`}
                      onClick={() => onEvidenceClick(evidenceId, message.evidenceSourceTypes?.[evidenceId] ?? 'unknown')}
                    >
                      {evidenceId}
                    </button>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      </section>

      <form className="ariadne-panel__composer" onSubmit={submitMessage}>
        <label className="ariadne-panel__sr-only" htmlFor="ariadne-message-input">{copy.askLabel}</label>
        <textarea
          id="ariadne-message-input"
          aria-label={copy.askLabel}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return;
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }}
          placeholder={copy.askPlaceholder}
          rows={3}
        />
        <button type="submit" disabled={!draft.trim() || sending || isSending}>
          {sending || isSending ? copy.sending : copy.send}
        </button>
      </form>
      {submitError && <p className="ariadne-panel__error" role="alert">{submitError}</p>}
    </section>
  );
};

type AriadneApiMessage = {
  id?: unknown;
  role?: unknown;
  content?: unknown;
  evidence_refs?: unknown;
  evidence_sources?: unknown;
  provider_status?: unknown;
};

type AriadneApiDecision = {
  id?: unknown;
  title?: unknown;
  source_id?: unknown;
  source_ids?: unknown;
  source_type?: unknown;
  reason?: unknown;
};

interface AriadneWorkspacePanelProps {
  apiBase: string;
  projectId: string;
  evidenceCards?: Array<{ card_id: string; metric_name: string }>;
  onEvidenceClick: (evidenceId: string, sourceType?: AriadneSourceType) => void;
  onDecisionsNeededChange?: (count: number) => void;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
}

function sourceType(value: unknown): AriadneSourceType {
  return value === 'evidence_card' || value === 'problem' || value === 'syntax_layer' || value === 'workspace'
    ? value
    : 'unknown';
}

function mapMessage(raw: AriadneApiMessage | null | undefined, index: number): AriadnePanelMessage | null {
  if (!raw) return null;
  if ((raw.role !== 'user' && raw.role !== 'assistant') || typeof raw.content !== 'string') return null;
  const refs = Array.isArray(raw.evidence_refs) ? raw.evidence_refs.filter((item): item is string => typeof item === 'string') : [];
  const sources = Array.isArray(raw.evidence_sources) ? raw.evidence_sources as Array<Record<string, unknown>> : [];
  const evidenceSourceTypes = Object.fromEntries(sources.flatMap(source =>
    typeof source.evidence_id === 'string'
      ? [[source.evidence_id, sourceType(source.source_type)] as const]
      : [],
  ));
  return {
    id: typeof raw.id === 'string' ? raw.id : `ariadne-message-${index}`,
    role: raw.role,
    content: raw.content,
    evidenceRefs: refs,
    evidenceSourceTypes,
    providerStatus: typeof raw.provider_status === 'string' ? raw.provider_status : null,
  };
}

function mapDecision(raw: AriadneApiDecision, index: number): AriadneDecisionNeeded | null {
  if (typeof raw.source_id !== 'string') return null;
  return {
    id: typeof raw.id === 'string' ? raw.id : `decision-${index}`,
    title: typeof raw.title === 'string' ? raw.title : raw.source_id,
    sourceId: raw.source_id,
    sourceIds: Array.isArray(raw.source_ids)
      ? Array.from(new Set([raw.source_id, ...raw.source_ids.filter((item): item is string => typeof item === 'string')]))
      : [raw.source_id],
    sourceType: sourceType(raw.source_type),
    reason: typeof raw.reason === 'string' ? raw.reason : undefined,
  };
}

function localizedBlockReason(code: string | undefined, fallback: string | undefined, t: (source: string) => string, zh: boolean): string | undefined {
  const messages: Record<string, { en: string; 'zh-TW': string }> = {
    BLOCKED_ARIADNE_LIVE_FLAG_REQUIRED: {
      en: 'AI assistant is currently not enabled. Please contact the administrator.',
      'zh-TW': 'AI 目前未啟用，請聯絡管理者。',
    },
    BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED: {
      en: 'Project is not authorized for Live AI. Please contact the administrator.',
      'zh-TW': '專案尚未授權啟用 AI，請聯絡管理者。',
    },
    BLOCKED_BUDGET: {
      en: 'The shared weekly ModelRun budget is exhausted; no provider request was sent.',
      'zh-TW': '每週模型運算額度已用盡，未送出請求。',
    },
    BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE: {
      en: 'Live AI is blocked because shared weekly ModelRun accounting is unavailable.',
      'zh-TW': '因調用計數系統不可用，AI 已暫停。',
    },
    BLOCKED_ARIADNE_PROFILE_UNAVAILABLE: {
      en: 'The Ariadne persona profile could not be initialized; no provider request was sent.',
      'zh-TW': 'AI 設定檔無法初始化，未送出請求。',
    },
  };
  if (code && messages[code]) {
    return zh ? messages[code]['zh-TW'] : messages[code].en;
  }
  return fallback ? t(fallback) : undefined;
}

function screenStateFrom(raw: Record<string, unknown>): AriadneScreenState {
  const provider = typeof raw.provider_status === 'string' ? raw.provider_status : '';
  const code = typeof raw.block_reason_code === 'string' ? raw.block_reason_code : '';
  if (provider.includes('OUTCOME_UNKNOWN') || code.includes('OUTCOME_UNKNOWN')) return 'OUTCOME_UNKNOWN';
  if (
    code.startsWith('BLOCKED')
    || provider.startsWith('BLOCKED')
    || provider.includes('BLOCKED_')
    || provider === 'LIVE_AI: REQUEST_REJECTED'
    || provider === 'LIVE_AI: MODEL_LIST_FAILED'
    || provider === 'LIVE_AI: CONNECTION_FAILED'
  ) return 'BLOCKED';
  return raw.mode === 'LIVE' ? 'LIVE' : 'OFFLINE';
}

function mapStatus(raw: Record<string, unknown>, t: (source: string) => string, zh = false): AriadnePanelStatus {
  const code = typeof raw.block_reason_code === 'string' ? raw.block_reason_code : undefined;
  const screenState = screenStateFrom(raw);
  return {
    mode: screenState === 'LIVE' ? 'LIVE' : 'OFFLINE',
    screenState,
    blockReason: localizedBlockReason(code, typeof raw.block_reason === 'string' ? raw.block_reason : undefined, t, zh),
    weeklyCallsUsed: typeof raw.weekly_calls_used === 'number' ? raw.weekly_calls_used : null,
    weeklyCallLimit: typeof raw.weekly_call_limit === 'number' ? raw.weekly_call_limit : null,
  };
}

export const AriadneWorkspacePanel: React.FC<AriadneWorkspacePanelProps> = ({
  apiBase,
  projectId,
  evidenceCards = [],
  onEvidenceClick,
  onDecisionsNeededChange,
  isExpanded = false,
  onToggleExpand,
}) => {
  const t = useT();
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  const baseUrl = `${apiBase.replace(/\/$/, '')}/api/v1/projects/${encodeURIComponent(projectId)}/ariadne`;
  const [messages, setMessages] = useState<AriadnePanelMessage[]>([]);
  const [decisionsNeeded, setDecisionsNeeded] = useState<AriadneDecisionNeeded[]>([]);
  const [decisionsLoading, setDecisionsLoading] = useState(true);
  const [status, setStatus] = useState<AriadnePanelStatus>({ mode: 'OFFLINE', blockReason: t('Checking Ariadne availability…') });
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let current = true;
    setDecisionsNeeded([]);
    setDecisionsLoading(true);
    onDecisionsNeededChange?.(0);
    const getJson = async (path: string, options?: RequestInit) => {
      const response = await fetch(`${baseUrl}/${path}`, options);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json() as Record<string, unknown>;
    };

    void getJson('status').then(data => {
      if (current) setStatus(mapStatus(data, t, zh));
    }).catch(() => {
      if (current) setStatus({ mode: 'OFFLINE', blockReason: t('Ariadne service is unavailable.') });
    });
    void getJson('messages').then(data => {
      const records = Array.isArray(data.messages) ? data.messages as AriadneApiMessage[] : [];
      if (current) setMessages(records.map(mapMessage).filter((item): item is AriadnePanelMessage => item !== null));
    }).catch(() => {
      if (current) setMessages([]);
    });
    void getJson('decisions-needed', { headers: { 'Accept-Language': language } }).then(data => {
      const records = Array.isArray(data.items) ? data.items as AriadneApiDecision[] : [];
      if (current) setDecisionsNeeded(records.map(mapDecision).filter((item): item is AriadneDecisionNeeded => item !== null));
    }).catch(() => {
      if (current) setDecisionsNeeded([]);
    }).finally(() => {
      if (current) setDecisionsLoading(false);
    });

    return () => { current = false; };
  }, [baseUrl, language, onDecisionsNeededChange, t]);

  useEffect(() => {
    onDecisionsNeededChange?.(decisionsLoading ? 0 : decisionsNeeded.length);
  }, [decisionsLoading, decisionsNeeded.length, onDecisionsNeededChange]);

  const sendMessage = useCallback(async (content: string) => {
    setSending(true);
    try {
      const response = await fetch(`${baseUrl}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, language }),
      });
      const data = await response.json().catch(() => null) as Record<string, unknown> | null;
      if (!response.ok) {
        throw new Error(typeof data?.detail === 'string' ? data.detail : t('Ariadne message failed with HTTP {status}.').replace('{status}', String(response.status)));
      }
      const appended = [mapMessage(data?.user_message as AriadneApiMessage, messages.length), mapMessage(data?.assistant_message as AriadneApiMessage, messages.length + 1)]
        .filter((item): item is AriadnePanelMessage => item !== null);
      setMessages(current => [...current, ...appended]);
      if (data?.status && typeof data.status === 'object') setStatus(mapStatus(data.status as Record<string, unknown>, t));
      const statusResponse = await fetch(`${baseUrl}/status`);
      if (statusResponse.ok) setStatus(mapStatus(await statusResponse.json() as Record<string, unknown>, t));
    } finally {
      setSending(false);
    }
  }, [baseUrl, language, messages.length, t]);

  const labels: AriadnePanelLabels = {
    title: t('Ariadne'),
    liveBadge: t('Live AI'),
    offlineBadge: t('Offline'),
    blockedBadge: t('Blocked'),
    outcomeUnknownBadge: t('Outcome unknown'),
    decisionHeading: t('Decisions needed'),
    noDecisions: t('No pending decisions.'),
    loadingDecisions: t('Loading decisions…'),
    viewSources: t('View {count} source cards'),
    conversationHeading: t('Conversation'),
    emptyConversation: t('Ask a question about the current evidence.'),
    userRole: t('You'),
    assistantRole: t('Ariadne'),
    askPlaceholder: t('Ask Ariadne about the evidence…'),
    askLabel: t('Ask Ariadne'),
    send: t('Send message'),
    sending: t('Sending…'),
    evidenceCard: t('Evidence card'),
    problem: t('Problem'),
    syntaxLayer: t('Syntax layer'),
    openSource: t('Open source'),
    weeklyUsage: t('Weekly ModelRun usage: {used} / {limit}'),
    submitError: t('The message could not be sent.'),
  };
  const evidenceCardLabels = Object.fromEntries(evidenceCards.map(card => [card.card_id, {
    source: card.metric_name,
    localized: t(card.metric_name),
  }]));

  return (
    <AriadnePanel
      messages={messages}
      evidenceCardLabels={evidenceCardLabels}
      decisionsNeeded={decisionsNeeded}
      status={status}
      onSendMessage={sendMessage}
      onEvidenceClick={onEvidenceClick}
      labels={labels}
      sending={sending}
      decisionsLoading={decisionsLoading}
      isExpanded={isExpanded}
      onToggleExpand={onToggleExpand}
    />
  );
};

export default AriadnePanel;
