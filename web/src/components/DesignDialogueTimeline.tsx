import React, { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';
import type { DesignDialogueData, DialogueEvent } from '../utils/proposalUtils';
import { humanizeAriadneText } from '../utils/proposalUtils';
import './DesignDialogueTimeline.css';

export interface DesignDialogueTimelineProps {
  apiBase: string;
  projectId: string;
  subject?: string;
  onSelectJudgement?: (judgementId: string) => void;
  onSelectProposal?: (proposalId: string) => void;
}

function useCopy() {
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  return {
    language,
    zh,
    say: (cn: string, en: string) => (zh ? cn : en),
  };
}

export const DesignDialogueTimeline: React.FC<DesignDialogueTimelineProps> = ({
  apiBase,
  projectId,
  subject = 'harbour_grain',
  onSelectJudgement,
  onSelectProposal,
}) => {
  const { say, zh, language } = useCopy();
  const [data, setData] = useState<DesignDialogueData | null>(null);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setHasError(false);

    const url = `${apiBase.replace(/\/$/, '')}/api/v1/projects/${encodeURIComponent(
      projectId,
    )}/ariadne/dialogue?subject=${encodeURIComponent(subject)}`;

    fetch(url)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((resData: DesignDialogueData) => {
        if (active) {
          setData(resData);
        }
      })
      .catch(() => {
        if (active) {
          setHasError(true);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [apiBase, projectId, subject]);

  const formatDate = (isoString?: string) => {
    if (!isoString) return say('時間未提供', 'Time unavailable');
    const date = new Date(isoString);
    if (Number.isNaN(date.getTime())) return say('時間未提供', 'Time unavailable');
    return new Intl.DateTimeFormat(zh ? 'zh-TW' : 'en-GB', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date);
  };

  const sortedEvents: DialogueEvent[] = (data?.events ?? []).slice().sort((a, b) => {
    const timeA = Date.parse(a.created_at || '') || 0;
    const timeB = Date.parse(b.created_at || '') || 0;
    return timeA - timeB;
  });

  return (
    <details
      className="design-dialogue-timeline"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
      aria-label={say('設計對話時間軸', 'Design dialogue timeline')}
    >
      <summary>{say('設計對話紀錄', 'Design dialogue history')}</summary>

      {loading && <p className="design-dialogue-timeline__empty">{say('載入中…', 'Loading…')}</p>}
      {hasError && (
        <p className="design-dialogue-timeline__empty" role="alert">
          {say('設計對話紀錄載入失敗', 'Failed to load design dialogue history')}
        </p>
      )}

      {!loading && !hasError && sortedEvents.length === 0 && (
        <p className="design-dialogue-timeline__empty">{say('尚無對話紀錄', 'No dialogue history yet')}</p>
      )}

      {!loading && sortedEvents.length > 0 && (
        <div className="design-dialogue-timeline__list">
          {sortedEvents.map((event, idx) => (
            <div key={`${event.kind}-${event.id || idx}`} className="design-dialogue-timeline__item">
              <span
                className={`design-dialogue-timeline__dot design-dialogue-timeline__dot--${event.kind}`}
                aria-hidden="true"
              />

              {/* Event Content based on kind */}
              {renderDialogueEvent(event, language, formatDate, onSelectJudgement, onSelectProposal)}
            </div>
          ))}
        </div>
      )}
    </details>
  );
};

function renderDialogueEvent(
  event: DialogueEvent,
  language: 'zh-TW' | 'en',
  formatDate: (iso?: string) => string,
  onSelectJudgement?: (id: string) => void,
  onSelectProposal?: (id: string) => void,
) {
  const zh = language === 'zh-TW';

  switch (event.kind) {
    case 'judgement': {
      const judgementRecord = event.judgement as { skill_id?: string; subject?: { ids?: string[] }; language?: string } | undefined;
      const cardLanguage = judgementRecord?.language ?? 'zh-TW';
      const otherLanguage = cardLanguage !== language;
      const rawHeadline = event.judgement?.card?.judgement?.headline;
      const headline = rawHeadline && otherLanguage
        ? (zh ? '（此輪判讀以英文撰寫，點擊查看）' : '(This round was written in Chinese — open it to read)')
        : rawHeadline || (zh ? '（這一輪沒有產生可顯示的判讀內容）' : '(No displayable judgement in this round)');
      const headlineLang = rawHeadline && !otherLanguage ? cardLanguage : language;
      const skillLabels: Record<string, [string, string]> = {
        'J-CLIMATE': ['氣候判讀', 'Climate judgement'],
        'J-COMPARE': ['方案比較判讀', 'Comparison judgement'],
        'J-SITE': ['基地判讀', 'Site judgement'],
      };
      const skillPair = skillLabels[judgementRecord?.skill_id ?? ''] ?? ['判讀', 'Judgement'];
      const draftRevision = (judgementRecord?.subject?.ids ?? []).map(id => /@draft-r(\d+)$/.exec(id)?.[1]).find(Boolean);
      const draftLabel = draftRevision ? (zh ? `（草稿第 ${draftRevision} 版）` : ` (draft revision ${draftRevision})`) : '';
      return (
        <>
          <div className="design-dialogue-timeline__header">
            <span className="design-dialogue-timeline__title">
              {zh ? `${skillPair[0]}第 ${event.round ?? 1} 輪${draftLabel}` : `${skillPair[1]}, round ${event.round ?? 1}${draftLabel}`}
            </span>
            <StatusBadge status={event.status} language={language} />
            <time className="design-dialogue-timeline__time" dateTime={event.created_at}>
              {formatDate(event.created_at)}
            </time>
          </div>
          <div className="design-dialogue-timeline__body">
            {onSelectJudgement ? (
              <button
                type="button"
                className="design-dialogue-timeline__action-btn"
                onClick={() => onSelectJudgement(event.id)}
              >
                <span lang={headlineLang}>{headline}</span>
              </button>
            ) : (
              <span lang={headlineLang}>{headline}</span>
            )}
          </div>
        </>
      );
    }

    case 'designer_response':
    case 'agent_response': {
      const isAgent = event.kind === 'agent_response';
      const kindLabel =
        event.response_kind === 'agree'
          ? zh
            ? '同意'
            : 'Agree'
          : event.response_kind === 'contest' || event.response_kind === 'challenge'
          ? zh
            ? '質疑'
            : 'Contest'
          : event.response_kind === 'supplement'
          ? zh
            ? '補充'
            : 'Supplement'
          : zh
          ? '回應'
          : 'Response';

      return (
        <>
          <div className="design-dialogue-timeline__header">
            <span className="design-dialogue-timeline__title">
              {isAgent
                ? zh ? `AI 代理回應（${kindLabel}）` : `AI Agent Response (${kindLabel})`
                : zh ? `設計者回應（${kindLabel}）` : `Designer Response (${kindLabel})`}
            </span>
            <time className="design-dialogue-timeline__time" dateTime={event.created_at}>
              {formatDate(event.created_at)}
            </time>
          </div>
          <div className="design-dialogue-timeline__body">
            <p style={{ margin: 0 }} lang={event.language || 'zh-TW'}>{event.text}</p>
          </div>
        </>
      );
    }

    case 'proposal': {
      const summary = humanizeAriadneText(event.proposal?.proposal?.summary || '', language);
      return (
        <>
          <div className="design-dialogue-timeline__header">
            <span className="design-dialogue-timeline__title">
              {zh ? 'Ariadne 修正提案' : 'Ariadne Revision Proposal'}
            </span>
            <StatusBadge status={event.status === 'APPROVED' ? 'PROPOSAL_APPROVED' : event.status} language={language} />
            <time className="design-dialogue-timeline__time" dateTime={event.created_at}>
              {formatDate(event.created_at)}
            </time>
          </div>
          <div className="design-dialogue-timeline__body">
            {onSelectProposal ? (
              <button
                type="button"
                className="design-dialogue-timeline__action-btn"
                onClick={() => onSelectProposal(event.id)}
              >
                <span lang="zh-TW">{summary}</span>
              </button>
            ) : (
              <span lang="zh-TW">{summary}</span>
            )}
          </div>
        </>
      );
    }

    case 'approval': {
      return (
        <>
          <div className="design-dialogue-timeline__header">
            <span className="design-dialogue-timeline__title">
              {zh ? '核准重算' : 'Recalculation Approved'}
            </span>
            <span className="design-dialogue-timeline__tag">
              {zh ? '非正式決策' : 'Informal decision'}
            </span>
            <time className="design-dialogue-timeline__time" dateTime={event.created_at}>
              {formatDate(event.created_at)}
            </time>
          </div>
          {event.note && (
            <div className="design-dialogue-timeline__body">
              <p style={{ margin: 0, fontStyle: 'italic' }}>
                {zh ? `備註：${event.note}` : `Note: ${event.note}`}
              </p>
            </div>
          )}
        </>
      );
    }

    case 'rerun': {
      const analyses = event.job?.analyses?.join(', ') || '';
      return (
        <>
          <div className="design-dialogue-timeline__header">
            <span className="design-dialogue-timeline__title">
              {zh ? `重算執行（${analyses}）` : `Recalculation (${analyses})`}
            </span>
            {event.job?.status && <StatusBadge status={event.job.status} language={language} />}
            <time className="design-dialogue-timeline__time" dateTime={event.created_at}>
              {formatDate(event.created_at)}
            </time>
          </div>
        </>
      );
    }

    default:
      return null;
  }
}

export default DesignDialogueTimeline;
