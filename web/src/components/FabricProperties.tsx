import { useI18n, useT } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';
import type { FabricSelection } from './FabricCompare';
export function FabricProperties({ selection, apiBase }: { selection: FabricSelection; apiBase: string }) {
  const t = useT(); const { language } = useI18n();
  const format = (n: unknown) => typeof n === 'number' && Number.isFinite(n) ? n.toLocaleString(language, { maximumFractionDigits: 3 }) : '—';
  const plan = selection.plans[selection.selected];
  const metrics = [['FAR (new buildings)', 'new_far'], ['Coverage (new buildings)', 'gsi'], ['New buildings', 'new_building_count'], ['FSI', 'fsi'], ['L', 'L'], ['OSR', 'OSR'], ['New floor area (m²)', 'new_gfa_m2'], ['Land area (m²)', 'land_area_m2']];
  return <section data-testid="fabric-properties" data-fabric-id={selection.parallel ? 'all' : selection.selected}>
    {selection.error ? <p role="alert">{t('Fabric plans unavailable.')}</p> : !plan ? <p role="status">{t('Loading fabric plans…')}</p> : <>
      {selection.parallel ? <><h3>{t('Four-plan summary')}</h3><table className="fabric-land-table"><thead><tr><th>{t('Scheme')}</th><th>{t('FAR (new buildings)')}</th><th>{t('New floor area (m²)')}</th><th>{t('New buildings')}</th></tr></thead><tbody>{Object.values(selection.plans).map(item => <tr key={item.fabric_id}><td>{t(`fabric.${item.fabric_id}`)}</td><td>{format(item.metrics.new_far)}</td><td>{format(item.metrics.new_gfa_m2)}</td><td>{format(item.metrics.new_building_count)}</td></tr>)}</tbody></table></> : <><h3>{t(`fabric.${plan.fabric_id}`)}</h3><dl><dt>{t('Scheme ID')}</dt><dd>{plan.fabric_id}</dd></dl></>}
      <p><StatusBadge status="EXPLORATORY_DRAFT" language={language} /></p>
      {!selection.parallel && <><h3>{t('Metrics')}</h3><dl>{metrics.map(([label,key]) => <div key={key}><dt>{t(label)}</dt><dd>{format(plan.metrics[key])}</dd></div>)}</dl>
      <a href={`${apiBase.replace(/\/$/, '')}/api/v1/fabric-plans/${plan.fabric_id}/figures/plan`} download={`${plan.fabric_id}-plan-zh.png`}>{language === 'en' ? 'Download plan (Chinese annotations)' : '下載平面圖（中文標註）'}</a></>}
      <h3>{t('Comparison assumptions')}</h3><dl><dt>{t('New GFA cap (new buildings only)')}</dt><dd>{format(146873)} m² · ASSUMED</dd><dt>{t('Height cap')}</dt><dd>{format(20)} m</dd></dl>
    </>}
  </section>;
}
