import { useI18n } from '../i18n';

export type GenerationReadiness = {
  status: 'READY' | 'BLOCKED';
  blockers: string[];
  context_hash: string | null;
  context: { workspace_revision: number; far_denominator: { area_m2: number; scope: string; label?: string }; floor_estimates: unknown[] } | null;
};

/** Parent owns fetching/refresh; this panel never creates approvals or enables generation. */
export function GenerationReadinessPanel({ readiness }: { readiness: GenerationReadiness | null }) {
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  return <section className="generation-readiness-panel" style={{ padding: '14px 16px' }} aria-label={zh ? '生成準備狀態' : 'Generation readiness'}>
    <h2>{zh ? '生成準備狀態' : 'Generation readiness'}</h2>
    <p role="status">
      {readiness === null
        ? (zh ? '正在檢查生成準備度…' : 'Checking readiness…')
        : readiness.status === 'READY'
          ? (zh ? '已核對批准參照' : 'Approval references verified')
          : (zh ? '尚未就緒：正式生成受阻' : 'Not ready: formal generation blocked')}
    </p>
    <p>{zh ? '凍結摘要不代表人類決策或方案接受。' : 'A frozen manifest does not constitute a human decision or proposal acceptance.'}</p>
    {readiness?.status === 'BLOCKED' && <><p>{zh ? '伺服器診斷（原文）' : 'Server diagnostics (original text)'}</p><ul>{readiness.blockers.map((reason, i) => <li key={i}>{reason}</li>)}</ul></>}
    {readiness?.context && <><p>{zh ? '工作區版本' : 'Workspace revision'}: {readiness.context.workspace_revision}</p>
      <p>{zh ? `FAR 分母：${readiness.context.far_denominator.scope === 'LAND_AREA' ? '陸地（不含水面）' : '探索設計範圍'}${readiness.context.far_denominator.label?.startsWith('legacy/') ? '（legacy/unspecified）' : ''}` : `FAR denominator: ${readiness.context.far_denominator.scope === 'LAND_AREA' ? 'Land area (excluding water)' : 'Exploration Design Area'}${readiness.context.far_denominator.label?.startsWith('legacy/') ? ' (legacy/unspecified)' : ''}`}: {readiness.context.far_denominator.area_m2} m²</p>
      <p>{zh ? '層數估算保留未知值與範圍；不能當作實測樓層。' : 'Floor estimates retain unknowns and ranges; they are not observed storeys.'}</p>
      <code>{readiness.context_hash}</code></>}
  </section>;
}
