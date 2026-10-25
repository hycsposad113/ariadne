import {useEffect, useState} from 'react';
import {useI18n} from '../i18n';
import {StatusBadge} from '../i18n/statusLabels';

type Dashboard = {
  provenance: string;
  metric_state: string;
  scenario_revision: number;
  selected_building: {gfa_m2: number | null};
  site: {far: number | null};
  land_basis?: {far: number | null; denominator_area_m2: number | null; floor_polygon_gfa_m2: number | null} | null;
};

/** Server projection stays separate from the locally calculated drag preview. */
export function ScenarioStudioDashboard({apiBase, scenarioId, buildingId, scenarioRevision}: {
  apiBase: string; scenarioId: string; buildingId: string; scenarioRevision: number;
}) {
  const {language} = useI18n();
  const [result, setResult] = useState<{key: string; dashboard: Dashboard} | null>(null);
  const key = `${scenarioId}/${buildingId}/${scenarioRevision}`;
  const dashboard = result?.key === key ? result.dashboard : null;
  const labels = language === 'zh-TW'
    ? {title: '後端草稿測量', gfa: '選取建築樓地板面積', far: '整體容積率', landFar: '陸地面積 FAR', unavailable: '無法提供'}
    : {title: 'Server draft measurements', gfa: 'Selected building GFA', far: 'Whole-site FAR', landFar: 'Land-area FAR', unavailable: 'Unavailable'};
  useEffect(() => {
    let current = true;
    fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(scenarioId)}/edits/dashboard?building_id=${encodeURIComponent(buildingId)}`)
      .then(async response => {
        if (!response.ok) throw new Error('NOT_READY');
        const value = await response.json() as Dashboard;
        if (value.scenario_revision !== scenarioRevision || !value.selected_building || !value.site) throw new Error('NOT_READY');
        if (current) setResult({key, dashboard: value});
      }).catch(() => { if (current) setResult(null); });
    return () => { current = false; };
  }, [apiBase, scenarioId, buildingId, scenarioRevision, key]);
  const number = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) ? String(value) : labels.unavailable;
  return <section className="scenario-dashboard" aria-label={labels.title}>
    <p
      role="status"
      title={`${dashboard?.provenance ?? 'NOT_READY'} · ${dashboard?.metric_state ?? ''}`.trim()}
    >
      {dashboard ? (
        <>
          <StatusBadge status={dashboard.provenance} language={language} showRawSrOnly={false} /> ·{' '}
          <StatusBadge status={dashboard.metric_state} language={language} showRawSrOnly={false} />
        </>
      ) : (
        <StatusBadge status="NOT_READY" language={language} showRawSrOnly={false} />
      )}
      <span className="sr-only" style={{ display: 'none' }}>
        {dashboard ? `${dashboard.provenance} · ${dashboard.metric_state}` : 'NOT_READY'}
      </span>
    </p>
    {dashboard && <dl>
      <dt>{labels.gfa}</dt><dd>{number(dashboard.selected_building.gfa_m2)} m²</dd>
      <dt>{labels.far}</dt><dd>{number(dashboard.site.far)}</dd>
      {dashboard.land_basis && <><dt>{labels.landFar}</dt><dd>{number(dashboard.land_basis.far)} <small>{dashboard.land_basis.denominator_area_m2} m²</small></dd></>}
    </dl>}
  </section>;
}
