import './ScenarioSyntaxControls.css';
import { useEffect, useState } from 'react';
import { useT } from '../i18n';
import type { SyntaxContextMode, SyntaxContextMetric, SyntaxContextResponse } from '../utils/syntaxContext';
import { comparisonContext, type ComparisonView, type ScenarioSyntaxResult } from '../utils/scenarioSyntax';
import { ROAD_STYLES } from '../utils/proposalRoads';

export function ProposalRoadLegend() {
  const t = useT();
  return <div className="proposal-road-legend" aria-label={t('Proposal road legend')} data-testid="proposal-road-legend">
    {['shared', 'pedestrian', 'motor', 'bicycle'].map(key => {
      const style = ROAD_STYLES[key as keyof typeof ROAD_STYLES];
      return <span key={key} style={{ marginRight: 12 }}><i style={{ color: style.color }}>━ </i>{t(style.label)}</span>;
    })}<small>{t('Legacy road modes: planner assumed')}<span className="sr-only" style={{ display: 'none' }}>ASSUMED_COMMANDER</span></small>
  </div>;
}

export function ScenarioSyntaxControls({ apiBase, scenarioId, revision, onContext }: {
  apiBase: string; scenarioId: string; revision?: string | number;
  onContext: (value: SyntaxContextResponse | null) => void;
}) {
  const t = useT();
  const [mode, setMode] = useState<SyntaxContextMode>('pedestrian');
  const [metric, setMetric] = useState<SyntaxContextMetric>('nain');
  const [view, setView] = useState<ComparisonView>('after');
  const [reload, setReload] = useState(0);
  const requestKey = JSON.stringify([apiBase,scenarioId,revision,mode,reload]);
  const [state, setState] = useState<{key:string; result:ScenarioSyntaxResult | null; status:string} | null>(null);
  const result = state?.key === requestKey ? state.result : null;
  const status = state?.key === requestKey ? state.status : 'loading';
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = () => fetch(`${apiBase.replace(/\/$/, '')}/api/v1/scenarios/${encodeURIComponent(scenarioId)}/syntax?mode=${mode}`)
      .then(async r => { if (!r.ok) throw new Error(String(r.status)); return await r.json() as ScenarioSyntaxResult; })
      .then(data => { if (!active) return; setState({key:requestKey, result:data, status:data.status}); if (['pending','running'].includes(data.status)) timer = setTimeout(read, 1500); })
      .catch(() => { if (active) { setState({key:requestKey,result:null,status:'UNAVAILABLE'}); } });
    void read();
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [apiBase, scenarioId, mode, requestKey]);
  useEffect(() => { const value = comparisonContext(result, view); onContext(value ? {...value, comparison_metric:metric} : null); }, [result, view, metric, onContext]);
  const compute = async () => {
    setSubmitting(true); setState({key:requestKey,result:null,status:'pending'});
    try {
      const r = await fetch(`${apiBase.replace(/\/$/, '')}/api/v1/scenarios/${encodeURIComponent(scenarioId)}/syntax`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode }),
      });
      if (!r.ok) throw new Error(String(r.status));
      setReload(n => n+1);
    } catch { setState({key:requestKey,result:null,status:'BLOCKED'}); } finally { setSubmitting(false); }
  };
  return <div className="scenario-syntax-controls" aria-label={t('Scenario Space Syntax comparison')}>
    <label>{t('Transport mode')} <select aria-label={t('Transport mode')} value={mode} onChange={e => setMode(e.target.value as SyntaxContextMode)}>
      <option value="pedestrian">{t('Walk 800 m')}</option><option value="bicycle">{t('Bicycle 2 km')}</option><option value="motor_vehicle">{t('Car 10 km')}</option>
    </select></label>
    <label>{t('Syntax comparison view')} <select aria-label={t('Syntax comparison view')} value={view} onChange={e => setView(e.target.value as ComparisonView)}>
      <option value="before">{t('Existing network')}</option><option value="after">{t('Proposal network')}</option><option value="diff">{t('Difference')}</option>
    </select></label>
    <label>{t('Metric')} <select aria-label={t('Metric')} value={metric} onChange={e => setMetric(e.target.value as SyntaxContextMetric)}>
      <option value="nain">{t('Integration (NAIN)')}</option><option value="nach">{t('Choice (NACH)')}</option>
    </select></label>
    <button type="button" disabled={submitting || ['pending','running','OUTCOME_UNKNOWN'].includes(status)} onClick={() => void compute()}>{t('Recompute scenario Syntax')}</button>
    <span role="status">{t(status)}</span>
    {result?.status === 'COMPUTED' && view === 'diff' && <div data-testid="syntax-difference-legend">
      <span style={{ color: '#ef4444' }}>{t('Warmer')}</span> · <span style={{ color: '#3b82f6' }}>{t('Cooler')}</span> · {t('Unchanged')} · {t('No comparable segment')}
    </div>}
    {result?.status === 'COMPUTED' && <details><summary>{t('Site Syntax indicators')}</summary>
      {(['before','after'] as const).map(side => <div key={side}><b>{t(side === 'before' ? 'Existing network' : 'Proposal network')}</b>
        {['mean_integration_nain','high_segment_ratio','entrance_integration_nain','through_site_choice_nach'].map(key => <span key={key} style={{marginLeft:12}}>
          {t(key)}: {typeof result[side]?.metrics[key] === 'number' ? (result[side]!.metrics[key] as number).toFixed(4) : '—'}
        </span>)}
      </div>)}<small>{t('Syntax potential; not observed movement. Segment means depend on segmentation.')}</small>
    </details>}
    {result?.error && <span role="alert">{result.error}</span>}
    <ProposalRoadLegend />
  </div>;
}
