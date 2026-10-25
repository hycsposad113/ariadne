import { MORPH_FAILURE_LABELS, humanizeDataGaps } from '../utils/proposalUtils';
import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import './JudgementCard.css';
import {formatMetricRef} from '../utils/metricLabels';
import {getStatusLabel} from '../i18n/statusLabels';
import { ProposalCard } from './ProposalCard';
import { DesignDialogueTimeline } from './DesignDialogueTimeline';
import type { ProposalRecord } from '../utils/proposalUtils';

export type JudgementSkill = 'J-SITE' | 'J-COMPARE' | 'J-CLIMATE' | 'J-MORPH';
type Ref = {kind: 'evidence_card' | 'metric' | 'artifact'; id: string; value?: unknown; unit?: string | null};
export type Judgement = {
  skill_id: JudgementSkill; skill_version: string; stage: string; subject: {kind: string; ids: string[]};
  observations: {text: string; refs: Ref[]}[];
  judgement: {stance: string; headline: string};
  reasoning: {lens: string; text: string; knowledge_refs: string[]}[];
  confidence: {level: string; why: string};
  revision_directions: {action: string; target: string; parameter_family: string; expected_effect: string; trade_off: string}[];
  data_gaps?: string[]; counterpoints: string[]; limitations: string[]; questions_for_designer: string[];
};
export type JudgementRecord = {
  language?: string;
  skill_id?: JudgementSkill;
  id: string; card: Judgement | null; status: string; round: number; created_at: string;
  provider_profile_id?: string;
  metrics?: Record<string, {value: unknown; unit: string | null; source_path?: string; source_sha256?: string}>;
  model?: string | {model?: string; provider?: string};
  knowledge_units?: {id: string; title?: string; title_zh?: string; title_en?: string; summary_zh?: string; summary_en?: string}[];
  responses?: {kind: string; text: string; created_at?: string}[];
};
const labels: Record<string, [string, string]> = {
  SUPPORT: ['支持', 'Support'], SUPPORT_WITH_CONDITIONS: ['有條件支持', 'Support with conditions'], CONCERN: ['有所顧慮', 'Concern'], OPPOSE: ['反對', 'Oppose'], INSUFFICIENT_EVIDENCE: ['證據不足', 'Insufficient evidence'],
  high: ['高', 'High'], medium: ['中', 'Medium'], low: ['低', 'Low'],
  height: ['建築高度', 'Building height'], setback: ['退縮', 'Setback'], courtyard_width: ['中庭寬度', 'Courtyard width'], block_subdivision: ['街廓細分', 'Block subdivision'], street_add_remove: ['街道增減', 'Street connections'], street_section: ['街道斷面', 'Street section'], open_space_allocation: ['開放空間配置', 'Open space allocation'], land_use: ['土地使用', 'Land use'], intensity: ['開發強度', 'Development intensity'], retention: ['既有元素保留', 'Retention'], planting_shade: ['植栽遮蔭', 'Planting and shade'], orientation: ['朝向', 'Orientation'], analysis_needed: ['補充分析', 'Further analysis'],
  agree: ['同意', 'Agree'], challenge: ['質疑', 'Contest'], contest: ['質疑', 'Contest'], supplement: ['補充', 'Supplement'],
  morphology: ['形態', 'Morphology'], 'J-MORPH': ['形態判讀', 'Morphology judgement'],
};
function useCopy() {
  const {language} = useI18n(); const zh = language === 'zh-TW';
  return {language, zh, say: (cn: string, en: string) => zh ? cn : en, label: (key: string) => labels[key]?.[zh ? 0 : 1] ?? (zh ? '未提供' : 'Unavailable')};
}
export function JudgementCard({record, onRespond, onReference}: {record: JudgementRecord; onRespond?: (kind: string, text: string) => Promise<void>; onReference?: (ref: Ref) => void}) {
  const {say, label, zh, language} = useCopy(); const [kind, setKind] = useState('agree'); const [text, setText] = useState(''); const [busy, setBusy] = useState(false); const [sent, setSent] = useState(false); const [error, setError] = useState('');
  const [responding, setResponding] = useState(false); const [expanded, setExpanded] = useState(false);
  const [reference, setReference] = useState<Ref | null>(null);
  const card = record.card;
  if (!card) {
    return <p role="status" title={record.status}>{getStatusLabel(record.status, language).label}</p>;
  }
  // Display-only formatting: stored prose, references and submitted responses stay intact.
  const display = (text: string) => humanizeDataGaps(text, language)
    .replace(/\b(?:prev\.)?(?:e[1-5]|utci|syntax|scheme|designer|limit|problem)\.[A-Za-z0-9_.]+|evidence_card:[A-Za-z0-9_-]+/g, id => formatMetricRef(id, null, null, language))
    .replace(/\bKU-[A-Z]+-\d+\b/g, id => {const unit = record.knowledge_units?.find(unit => unit.id === id); return (zh ? unit?.title_zh : unit?.title_en) || say('知識單元', 'Knowledge unit');})
    .replace(/\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+){1,}\b/g, code => (MORPH_FAILURE_LABELS[code] ? MORPH_FAILURE_LABELS[code][zh ? 0 : 1] : code))
    .replace(/\bh_north_edge(?:_m)?\b/g, zh ? '北緣高度' : 'north edge height')
    .replace(/\bsouth_edge_height_max(?:_m)?\b/g, zh ? '南側最高高度' : 'south edge max height')
    .replace(/\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b/g, () => say('未翻譯項目（詳見來源）', 'Untranslated item (see source)'))
    .replace(/-?\d[\d,]*\.\d{2,}/g, (number, offset: number, full: string) => {
      const following = full.slice(offset + number.length);
      const digits = /^\s*(?:m²|m2|kWh|kW)/i.test(following) ? 1 : /^\s*(?:h\b|小時|%)/.test(following) ? 2 : 3;
      if (number.split('.')[1].length <= digits) return number;
      return new Intl.NumberFormat(zh ? 'zh-TW' : 'en-GB', {maximumFractionDigits:digits}).format(Number(number.replaceAll(',', '')));
    });
  // Ariadne-generated prose keeps the language it was written in (lang attribute), separate from the UI language.
  const contentLang = record.language ?? 'zh-TW';
  const gen = (text: string) => <span lang={contentLang}>{display(text)}</span>;
  const list = (title: string, entries: string[]) => <section><h4>{title}</h4><ul>{entries.map((entry, index) => <li key={index}>{gen(entry)}</li>)}</ul></section>;
  async function submit() {
    if ((kind !== 'agree' && !text.trim()) || text.length > 1000 || !onRespond || busy) return;
    setBusy(true); setError('');
    try { await onRespond(kind, text.trim()); setSent(true); setText(''); } catch { setError(say('回應未儲存，請稍後重試。', 'Response could not be saved. Please retry.')); } finally { setBusy(false); }
  }
  const metricLabel = (ref: Ref) => display(formatMetricRef(ref.id, ref.value, ref.unit, language));
  const date = new Date(record.created_at);
  const dateLabel = Number.isNaN(date.getTime()) ? say('時間未提供', 'Time unavailable') : new Intl.DateTimeFormat(language === 'zh-TW' ? 'zh-TW' : 'en-GB', {month:'long', day:'numeric', hour:'2-digit', minute:'2-digit', hour12:false}).format(date);
  return <article className="judgement-card" aria-label={say('Ariadne 判讀卡', 'Ariadne judgement card')}>
    <div className="judgement-card__overview">
    <header><span className={`judgement-card__stance judgement-card__stance--${card.judgement.stance.toLowerCase()}`}>{label(card.judgement.stance)}</span><small>{say(`第 ${record.round} 輪`, `Round ${record.round}`)} · <time dateTime={record.created_at}>{dateLabel}</time></small><h3>{gen(card.judgement.headline)}</h3></header>
    <section><h4>{say('我建議下一輪', 'I suggest for the next round')}</h4><ul className="judgement-card__directions">{card.revision_directions.map((revision, i) => <li key={i}><strong>{label(revision.parameter_family)}</strong>：{gen(revision.action)}<small>{gen(revision.trade_off)}</small></li>)}</ul></section>
    {list(say('想問你', 'Questions for you'), card.questions_for_designer)}
    <div role="group" aria-label={say('你的回應', 'Your response')}>{['agree', 'contest', 'supplement'].map(value => <button type="button" disabled={!onRespond || busy} aria-pressed={kind === value} key={value} onClick={() => {setKind(value); setResponding(true);}}>{label(value)}</button>)}</div>
    <p className="judgement-card__confidence"><strong>{say('信心', 'Confidence')}: {label(card.confidence.level)}</strong><span title={display(card.confidence.why)}> · {gen(card.confidence.why)}</span></p>
    </div>
    <details open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}><summary>{say('看依據與推理', 'View evidence and reasoning')}</summary>{expanded && <>
    <section><h4>{say('觀察與依據', 'Observations and references')}</h4><ol>{card.observations.map((observation, i) => <li key={i}>{gen(observation.text)}<ul className="judgement-card__refs">{observation.refs.map((original, j) => { const metric = record.metrics?.[original.id]; const ref = {...original, ...(metric ? {value: metric.value, unit: metric.unit} : {})}; return <li key={j}><button type="button" onClick={() => { if (onReference) onReference(ref); else { setReference(ref); document.getElementById(ref.kind === 'metric' ? 'compare-metrics' : ref.kind === 'evidence_card' ? `card-${ref.id.replace(/^evidence_card:/, '')}` : `artifact-${ref.id}`)?.scrollIntoView?.({behavior: 'smooth'}); } }} title={ref.id}>{metricLabel(ref)}</button></li>; })}</ul></li>)}</ol></section>
    {reference && <aside role="note"><strong>{say('引用資料', 'Reference')}</strong><p title={reference.id}>{metricLabel(reference)}</p><button type="button" onClick={() => setReference(null)}>{say('關閉', 'Close')}</button></aside>}
    <section><h4>{say('判讀理由', 'Rationale')}</h4>{card.reasoning.map((reason, i) => <div key={i}><h5>{({
      'J-SITE': [say('結構與尺度', 'Structure and scale'), say('移動潛力', 'Movement potential'), say('既有元素', 'Existing elements'), say('水與邊緣', 'Water and edges'), say('資料缺口', 'Data gaps')],
      'J-COMPARE': [say('設計邏輯', 'Design logic'), say('移動與連結', 'Movement and connections'), say('形態與強度', 'Form and intensity'), say('公共空間品質', 'Public space quality'), say('優先順序與取捨', 'Priorities and trade-offs'), say('下一輪修正', 'Next revision')],
      'J-CLIMATE': [say('季節取捨', 'Seasonal trade-offs'), say('空間分類', 'Spatial categories'), say('夏季熱壓力', 'Summer heat stress'), say('建築耗能', 'Building energy'), say('風環境', 'Wind conditions'), say('結論可信度', 'Confidence in conclusions')],
      'J-MORPH': [say('生成邏輯', 'Generation logic'), say('街廓與中庭尺度', 'Block and courtyard scale'), say('高度與密度分布', 'Height and density distribution'), say('檢核失敗與修補', 'Failed checks and remediation'), say('資料缺口', 'Data gaps')],
    }[card.skill_id]?.[Number(reason.lens.match(/^L(\d+)/)?.[1]) - 1]) ?? say('判讀視角', 'Interpretation lens')}</h5><p>{gen(reason.text)}</p>{reason.knowledge_refs.map(id => {
      const unit = record.knowledge_units?.find(item => item.id === id); const title = zh ? unit?.title_zh ?? unit?.title : unit?.title_en ?? unit?.title; const summary = zh ? unit?.summary_zh : unit?.summary_en;
      return <abbr key={id} tabIndex={0} title={[id, summary].filter(Boolean).join(' — ')}>{display(title || say('知識單元', 'Knowledge unit'))}</abbr>;
    })}</div>)}</section>
    {list(say('反例與不同觀點', 'Counterpoints'), card.counterpoints)}{list(say('限制', 'Limitations'), card.limitations)}
    {list(say('資料缺口', 'Data gaps'), card.data_gaps?.length ? card.data_gaps : [say('未另列資料缺口；請參閱限制與設計問題。', 'No separate data gaps were supplied; see limitations and design questions.')])}
    <section><h4>{say('修正補充資訊', 'Revision details')}</h4>{card.revision_directions.map((revision, i) => <p key={i}>{gen(revision.target)} · {gen(revision.expected_effect)}</p>)}</section>
    <footer>{say('模型', 'Model')}: {typeof record.model === 'string' ? record.model : [record.model?.provider, record.model?.model].filter(Boolean).join(' / ') || '—'} · {say('判讀框架版本', 'Skill version')}: {card.skill_version} · {say(`由 ${record.provider_profile_id || 'codex-cli'} 產生`, `Generated by ${record.provider_profile_id || 'codex-cli'}`)}</footer>
    </>}</details>
    {record.responses?.length ? <section><h4>{say('已記錄的設計者回應', 'Recorded designer responses')}</h4>{record.responses.map((response, i) => <p key={i}><strong>{label(response.kind)}</strong>: {gen(response.text)}</p>)}</section> : null}
    {onRespond && responding && <form onSubmit={event => {event.preventDefault(); void submit();}}><label>{kind === 'agree' ? say('回應內容（選填，最多 1000 字）', 'Response text (optional, up to 1000 characters)') : say('回應內容（必填，最多 1000 字）', 'Response text (required, up to 1000 characters)')}<textarea value={text} onChange={event => setText(event.target.value)} aria-invalid={text.length > 1000} /></label><small>{text.length}/1000</small><button disabled={busy || (kind !== 'agree' && !text.trim()) || text.length > 1000}>{busy ? say('儲存中…', 'Saving…') : say('記錄回應', 'Record response')}</button>{error && <p role="alert">{error}</p>}{sent && <p role="status">{say('回應已記錄，會納入下一輪判讀；按重新判讀繼續。', 'Response recorded for the next round. Request a new judgement to continue.')}</p>}</form>}
  </article>;
}

export function JudgementPanel({
  apiBase,
  projectId,
  skillId,
  subjectIds = [],
  onHighlightBuildings,
}: {
  apiBase: string;
  projectId: string;
  skillId: JudgementSkill;
  subjectIds?: string[];
  onHighlightBuildings?: (buildingIds: string[]) => void;
}) {
  const { say, language } = useCopy();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [records, setRecords] = useState<JudgementRecord[]>([]);
  // A judgement of another skill opened from this panel (e.g. the J-CLIMATE re-judgement after a recalculation).
  const [linked, setLinked] = useState<JudgementRecord | null>(null);
  const [usage, setUsage] = useState<{ calls: number; limit: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState(false);

  // Proposal states
  const [proposals, setProposals] = useState<ProposalRecord[]>([]);
  const [proposalBusy, setProposalBusy] = useState(false);
  const [proposalError, setProposalError] = useState('');

  const subject = subjectIds.join(',');
  const url = `${apiBase.replace(/\/$/, '')}/api/v1/projects/${encodeURIComponent(projectId)}/ariadne/judgements`;
  const query = new URLSearchParams({ skill_id: skillId, ...(subject ? { subject } : {}) }).toString();

  const loadCards = () => {
    fetch(`${url}?${query}`)
      .then(async (response) => {
        if (!response.ok) throw new Error();
        return response.json();
      })
      .then((data) => {
        setRecords(Array.isArray(data.cards) ? data.cards : []);
        setUsage(data.usage ?? null);
      })
      .catch(() => {
        setHistoryError(true);
      });
  };

  useEffect(() => {
    let active = true;
    setSelectedId(null);
    setRecords([]);
    setLinked(null);
    setUsage(null);
    setError('');
    setHistoryError(false);
    fetch(`${url}?${query}`)
      .then(async (response) => {
        if (!response.ok) throw new Error();
        return response.json();
      })
      .then((data) => {
        if (active) {
          setRecords(Array.isArray(data.cards) ? data.cards : []);
          setUsage(data.usage ?? null);
        }
      })
      .catch(() => {
        if (active) setHistoryError(true);
      });
    return () => {
      active = false;
    };
  }, [url, query]);

  async function request(langOverride?: string) {
    if (busy) return;
    setBusy(true);
    setError('');
    const targetLanguage = langOverride ?? language;
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          skill_id: skillId,
          subject_ids: subject ? subject.split(',') : [],
          language: targetLanguage,
          force: records.length > 0,
        }),
      });
      if (!response.ok) throw new Error();
      const record = (await response.json()) as JudgementRecord;
      setSelectedId(record.id);
      setRecords((previous) => [record, ...previous.filter((item) => item.id !== record.id)]);
      setHistoryError(false);
      void fetch(`${url}?${query}`)
        .then(async (result) => (result.ok ? result.json() : null))
        .then((data) => {
          if (data?.usage) setUsage(data.usage);
        })
        .catch(() => {});
    } catch {
      setError(
        say(
          '判讀暫時無法完成，請檢查資料、使用額度與模型設定。',
          'Judgement could not be completed. Check data, usage allowance, and model settings.',
        ),
      );
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    setSelectedId(null);
  }, [language]);

  const getRecordLanguage = (record: JudgementRecord): string => {
    return record.language ?? language;
  };

  const currentLangRecords = records.filter(
    (record) => getRecordLanguage(record) === language
  );
  const latestCurrentLang = currentLangRecords[0];
  const lastValidatedCurrentLang = currentLangRecords.find(
    (record) => record.status === 'VALIDATED' && record.card
  );
  const defaultCurrentLangCard = lastValidatedCurrentLang ?? latestCurrentLang ?? null;

  const selected = selectedId
    ? records.find((record) => record.id === selectedId) ?? null
    : defaultCurrentLangCard;

  const latest = records[0];
  const latestFailedNote = !selectedId && selected && latestCurrentLang && latestCurrentLang !== selected && latestCurrentLang.status !== 'VALIDATED';

  // Load proposals for selected card
  useEffect(() => {
    if (!selected || skillId === 'J-SITE') {
      setProposals([]);
      return;
    }
    let active = true;
    const propUrl = `${apiBase.replace(/\/$/, '')}/api/v1/projects/${encodeURIComponent(
      projectId,
    )}/ariadne/proposals?card_id=${encodeURIComponent(selected.id)}`;

    fetch(propUrl)
      .then(async (res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data && Array.isArray(data.proposals)) {
          setProposals(data.proposals);
        }
      })
      .catch(() => {});

    return () => {
      active = false;
    };
  }, [apiBase, projectId, selected?.id, skillId]);

  async function requestProposal() {
    if (proposalBusy || !selected) return;
    setProposalBusy(true);
    setProposalError('');
    try {
      const postUrl = `${apiBase.replace(/\/$/, '')}/api/v1/projects/${encodeURIComponent(
        projectId,
      )}/ariadne/proposals`;
      const response = await fetch(postUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          card_id: selected.id,
          language,
          force: proposals.length > 0,
        }),
      });
      if (!response.ok) {
        const detail = String((await response.json().catch(() => ({})) as {detail?: unknown}).detail ?? '');
        if (/formal draft/i.test(detail)) {
          setProposalError(say(
            '還沒有港埠的正式草稿：請先到「細修」頁開啟港埠正式草稿（只需一次），再請 Ariadne 提出修正方案。',
            'No harbour formal draft yet: open the harbour formal draft on the Refine page once, then ask Ariadne for a revision proposal.',
          ));
          return;
        }
        throw new Error();
      }
      const newProp = (await response.json()) as ProposalRecord;
      setProposals((prev) => [newProp, ...prev.filter((p) => p.id !== newProp.id)]);
    } catch {
      setProposalError(
        say(
          '提案暫時無法完成，請檢查資料與模型設定。',
          'Proposal could not be completed. Check data and model settings.',
        ),
      );
    } finally {
      setProposalBusy(false);
    }
  }

  const canRequestProposal =
    (skillId === 'J-CLIMATE' || skillId === 'J-COMPARE' || skillId === 'J-MORPH') && selected?.status === 'VALIDATED';

  const handleSelectJudgement = (id: string) => {
    if (records.some((r) => r.id === id)) {
      setSelectedId(id);
      return;
    }
    fetch(`${url}/${encodeURIComponent(id)}`)
      .then(async (response) => {
        if (!response.ok) throw new Error();
        return response.json();
      })
      .then((record: JudgementRecord) => {
        if (record.skill_id === skillId) {
          loadCards();
          setSelectedId(id);
        } else {
          setLinked(record);
        }
      })
      .catch(() => setHistoryError(true));
  };

  const panelTitle =
    skillId === 'J-MORPH'
      ? say('Ariadne 形態判讀', 'Ariadne morphology judgement')
      : say('Ariadne 設計判讀', 'Ariadne design judgement');

  return (
    <section className="judgement-panel" aria-label={panelTitle}>
      <h3>{panelTitle}</h3>
      <p>{say('由你主動請求判讀；回應與歷史輪次會保留。', 'Request a judgement when ready. Responses and earlier rounds are preserved.')}</p>
      {usage && (
        <p>
          {say('本週使用量', 'Weekly usage')}: {usage.calls} / {usage.limit}
        </p>
      )}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
        <button type="button" disabled={busy} onClick={() => void request()}>
          {busy
            ? say('判讀中…', 'Preparing judgement…')
            : latest
            ? say('重新判讀', 'Request new round')
            : skillId === 'J-SITE'
            ? say('請 Ariadne 判讀基地', 'Ask Ariadne to interpret the site')
            : skillId === 'J-MORPH'
            ? say('請 Ariadne 判讀形態', 'Ask Ariadne to read the morphology')
            : say('請 Ariadne 判讀', 'Ask Ariadne for a judgement')}
        </button>

        {canRequestProposal && (
          <button
            type="button"
            disabled={proposalBusy}
            onClick={() => void requestProposal()}
            style={{ background: '#0284c7', borderColor: '#38bdf8', color: '#f0f9ff' }}
          >
            {proposalBusy
              ? say('Ariadne 正在擬提案…（約 1 分鐘）', 'Ariadne is preparing a proposal… (approx. 1 min)')
              : say('請 Ariadne 提出修正方案', 'Ask Ariadne for a revision proposal')}
          </button>
        )}
      </div>

      {historyError && (
        <p role="status">{say('歷史判讀暫時無法載入。', 'Judgement history is temporarily unavailable.')}</p>
      )}
      {error && <p role="alert">{error}</p>}
      {proposalError && <p role="alert">{proposalError}</p>}

      {(records.length > 1 || (!selected && records.length > 0)) && (
        <nav aria-label={say('歷史判讀輪次', 'Earlier judgement rounds')}>
          {records.map((record) => (
            <button
              type="button"
              key={record.id}
              aria-pressed={selected?.id === record.id}
              onClick={() => setSelectedId(record.id)}
            >
              {say(`第 ${record.round} 輪`, `Round ${record.round}`)}
            </button>
          ))}
        </nav>
      )}

      {!selected && currentLangRecords.length === 0 && records.length > 0 && (
        <div className="judgement-panel__lang-notice" data-testid="judgement-lang-notice" style={{ padding: '12px', margin: '8px 0', border: '1px dashed var(--border-subtle, #334155)', borderRadius: '6px' }}>
          <p role="status">
            {say('目前尚無中文判讀卡。', 'No English judgement card is available yet.')}
          </p>
          <button
            type="button"
            disabled={busy}
            onClick={() => void request(language)}
            style={{ marginTop: '8px' }}
          >
            {say('以中文產生', 'Generate in English')}
          </button>
        </div>
      )}

      {latestFailedNote && (
        <p role="status" className="judgement-panel__note">
          {say(
            `最新一輪（第 ${latest.round} 輪）未通過驗證，以下顯示最近一輪通過驗證的判讀。`,
            `The latest round (${latest.round}) failed validation; showing the most recent validated judgement.`,
          )}
        </p>
      )}

      {selected && (
        <JudgementCard
          key={selected.id}
          record={selected}
          onRespond={async (kind, text) => {
            const response = await fetch(`${url}/${encodeURIComponent(selected.id)}/responses`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ kind, text }),
            });
            if (!response.ok) throw new Error();
            const saved = await response.json();
            setRecords((previous) =>
              previous.map((record) =>
                record.id === selected.id
                  ? { ...record, responses: [...(record.responses ?? []), saved] }
                  : record,
              ),
            );
          }}
        />
      )}

      {/* Proposals section */}
      {proposals.length > 0 && (
        <section className="judgement-panel__proposals" aria-label={say('Ariadne 提案列表', 'Ariadne Proposals')}>
          {proposals.map((proposal) => (
            <ProposalCard
              key={proposal.id}
              record={proposal}
              apiBase={apiBase}
              projectId={projectId}
              onHighlightBuildings={onHighlightBuildings}
              onProposalUpdate={(updated) => {
                setProposals((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
              }}
              onSelectJudgement={handleSelectJudgement}
            />
          ))}
        </section>
      )}

      {linked && (
        <section className="judgement-panel__linked" aria-label={say('重算後的新判讀', 'Recalculation judgement')}>
          <h4>{say('重算後的新判讀', 'Recalculation judgement')}</h4>
          <JudgementCard
            key={linked.id}
            record={linked}
            onRespond={async (kind, text) => {
              const response = await fetch(`${url}/${encodeURIComponent(linked.id)}/responses`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ kind, text }),
              });
              if (!response.ok) throw new Error();
              const saved = await response.json();
              setLinked((previous) =>
                previous && previous.id === linked.id
                  ? { ...previous, responses: [...(previous.responses ?? []), saved] }
                  : previous,
              );
            }}
          />
        </section>
      )}

      {/* Design Dialogue Timeline */}
      <DesignDialogueTimeline
        apiBase={apiBase}
        projectId={projectId}
        subject={subject || 'harbour_grain'}
        onSelectJudgement={handleSelectJudgement}
      />
    </section>
  );
}
