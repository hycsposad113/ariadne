import { useI18n } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';

export type MassingIntentRecord = {
  reason_zh?: string; reason_en?: string; rule_card_ids?: string[];
  knowledge_unit_ids?: string[]; syntax_nain?: number; syntax_percentile?: number;
  provenance?: string;
};

/** Shared Compare/Refine property panel; absent intent remains absent. */
export function MassingIntent({ intent, height, active }: { intent?: MassingIntentRecord; height?: number; active?: boolean }) {
  const { language } = useI18n(); const zh = language === 'zh-TW';
  return <section aria-label={zh ? '量體設計意圖' : 'Massing design intent'} className="massing-intent">
    <h3>{zh ? '量體設計意圖' : 'Massing design intent'}</h3>
    {typeof height === 'number' && <p>{zh ? '高度' : 'Height'}: {height} m</p>}
    {typeof active === 'boolean' && <p>{zh ? '首層活躍立面候選' : 'Active ground-floor candidate'}: {active ? (zh ? '是（橙色）' : 'Yes (orange)') : (zh ? '否' : 'No')}</p>}
    <p>{intent ? (zh ? intent.reason_zh : intent.reason_en) : (zh ? '尚無已記錄的設計理由' : 'No recorded design rationale')}</p>
    {intent && <>
      <p>NAIN: {intent.syntax_nain ?? (zh ? '未知' : 'Unknown')} · {zh ? '百分位' : 'Percentile'}: {intent.syntax_percentile ?? (zh ? '未知' : 'Unknown')}</p>
      <p>{zh ? '規則卡' : 'Rule cards'}: {(intent.rule_card_ids ?? []).join(', ')}</p>
      <p>{zh ? '知識單元' : 'Knowledge units'}: {(intent.knowledge_unit_ids ?? []).join(', ')}</p>
      <p><StatusBadge status={intent.provenance ?? 'DRAFT'} language={language} /></p>
    </>}
  </section>;
}
