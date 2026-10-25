import { JudgementPanel } from './JudgementCard';
import { useEffect, useState } from 'react';
import { useI18n, useT } from '../i18n';
import { FabricCompareMap } from './FabricCompareMap';
import { FabricSyntaxComparison } from './FabricSyntaxComparison';
import type { Segment, SyntaxLayer } from '../types';
import type { SyntaxContextResponse } from '../utils/syntaxContext';
import type { FabricLayers } from './FabricCompareMap';
import './FabricCompare.css';
export const FABRIC_IDS = ['harbour_grain', 'closed_block_extension', 'courtyard_islands', 'landscape_figure'] as const;
export type FabricPlan = { fabric_id: string; label_zh: string; status: string; output_crs: string; layers: FabricLayers; layers_projected: FabricLayers; projected_crs: string; metrics: Record<string, unknown>; land_use_table: { category: string; category_zh?: string; feature_id: string; area_m2: number | null; site_land_percent: number | null }[]; checks: { failure_ids?: string[] }; check_explanations_zh?: Record<string, string>; check_explanations_en?: Record<string, string>; syntax_summary: Record<string, unknown> | null; design_statement_markdown: string | null; limitations: string[] };
type Catalog = { plans: { fabric_id: string; label_zh: string }[] };
function number(value: unknown, language = 'zh-TW'): string { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString(language, { maximumFractionDigits: 3 }) : '—'; }
// Render a bounded Markdown subset as React text; source HTML and URLs never execute.
export function FabricStatement({ markdown }: { markdown: string }) {
  const t = useT();
  const lines = markdown.split('\n');
  let paragraphs = 0; let inParagraph = false; let cut = lines.length; let pendingHeading = -1;
  for (let i = 0; i < lines.length; i++) {
    const text = lines[i].trim();
    if (text.startsWith('#')) { pendingHeading = i; inParagraph = false; continue; }
    if (!text) { inParagraph = false; continue; }
    if (!inParagraph) { paragraphs++; inParagraph = true; }
    if (paragraphs > 2) { cut = pendingHeading >= 0 ? pendingHeading : i; break; }
    pendingHeading = -1;
  }
  const renderLines = (items: string[]) => items.map((line, index) => {
    if (line.startsWith('### ')) return <h4 key={index}>{line.slice(4)}</h4>;
    if (line.startsWith('## ')) return <h3 key={index}>{line.slice(3)}</h3>;
    if (line.startsWith('# ')) return <h3 key={index}>{line.slice(2)}</h3>;
    if (line.startsWith('- ')) return <p key={index}>• {line.slice(2)}</p>;
    return line ? <p key={index}>{line}</p> : null;
  });
  return <div className="fabric-statement"><details open><summary>{t('Design statement (first two paragraphs)')}</summary>{renderLines(lines.slice(0, cut))}</details>{cut < lines.length && <details><summary>{t('Expand remaining design statement')}</summary>{renderLines(lines.slice(cut))}</details>}</div>;
}

export type FabricSelection = { selected: string; plans: Record<string, FabricPlan>; parallel: boolean; error: boolean };
export function FabricCompare({ apiBase, projectId = 'rotterdam-m4h-pilot-project', mode = '2D', active = true, onSelection, syntaxContextData, syntaxContextStatus, syntaxContextError, syntaxSegments, syntaxLegend, activeSyntaxLayer, syntaxOverlayVisible, onSyntaxOverlayVisibilityChange }: { apiBase: string; projectId?: string; mode?: '2D' | '3D' | 'SPLIT'; active?: boolean; onSelection?: (selection: FabricSelection | null) => void; syntaxContextData?: SyntaxContextResponse | null; syntaxContextStatus?: 'idle' | 'loading' | 'success' | 'error'; syntaxContextError?: string | null; syntaxSegments?: Segment[]; syntaxLegend?: {label: string; color: string}[]; activeSyntaxLayer?: SyntaxLayer | null; syntaxOverlayVisible?: boolean; onSyntaxOverlayVisibilityChange?: (visible: boolean) => void }) {
  const t = useT(); const { language } = useI18n(); const format = (value: unknown) => number(value, language); const [catalog, setCatalog] = useState<Catalog | null>(null); const [plans, setPlans] = useState<Record<string, FabricPlan>>({}); const [error, setError] = useState(false); const [selected, setSelected] = useState<string>(FABRIC_IDS[0]); const [parallel, setParallel] = useState(false);
  const [refreshError, setRefreshError] = useState(false);
  const [loadedLanguage, setLoadedLanguage] = useState<string | null>(null);
  const localized = loadedLanguage === language;
  useEffect(() => { onSelection?.(active ? { selected, plans: localized ? plans : {}, parallel, error } : null); }, [onSelection, active, selected, plans, parallel, error, localized]);
  useEffect(() => {
    const controller = new AbortController(); const base = apiBase.replace(/\/$/, ''); setCatalog(null); setPlans({}); setError(false); setRefreshError(false);
    const read = async (path: string) => { const response = await fetch(`${base}/api/v1/fabric-plans${path}`, { signal: controller.signal }); if (!response.ok) throw new Error('unavailable'); return response.json(); };
    (async () => {
      const next = await read('') as Catalog; if (!Array.isArray(next.plans)) throw new Error('catalog');
      const details = await Promise.all(FABRIC_IDS.map(id => read(`/${id}?lang=${language === 'en' ? 'en' : 'zh'}`) as Promise<FabricPlan>));
      details.forEach((plan, index) => { if (plan.fabric_id !== FABRIC_IDS[index] || plan.output_crs !== 'EPSG:4326' || !plan.layers || plan.projected_crs !== 'EPSG:28992' || !plan.layers_projected || !Array.isArray(plan.checks?.failure_ids) || Object.values({ ...plan.layers, ...Object.fromEntries(Object.entries(plan.layers_projected).map(([key, layer]) => [`projected-${key}`, layer])) }).some(layer => layer.type !== 'FeatureCollection' || !Array.isArray(layer.features))) throw new Error('geometry'); });
      if (!controller.signal.aborted) { setLoadedLanguage(language); setCatalog(next); setPlans(Object.fromEntries(details.map(plan => [plan.fabric_id, plan]))); }
    })().catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [apiBase, language]);
  useEffect(() => {
    if (!FABRIC_IDS.every(id => plans[id]) || FABRIC_IDS.every(id => Number(plans[id].syntax_summary?.computed_count) >= 12)) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const summaries = await Promise.all(FABRIC_IDS.map(async id => {
          const response = await fetch(`${apiBase.replace(/\/$/, '')}/api/v1/fabric-plans/${id}?lang=${language === 'en' ? 'en' : 'zh'}`, { signal: controller.signal });
          if (!response.ok) throw new Error('unavailable');
          const detail = await response.json() as FabricPlan;
          if (detail.fabric_id !== id) throw new Error('identity');
          return detail.syntax_summary;
        }));
        if (!controller.signal.aborted) {
          setRefreshError(false);
          // Keep immutable geometry references so progress updates preserve map zoom.
          setPlans(current => Object.fromEntries(FABRIC_IDS.map((id, index) => [id, { ...current[id], syntax_summary: summaries[index] }])));
        }
      } catch {
        if (!controller.signal.aborted) {
          setRefreshError(true);
          setPlans(current => ({ ...current }));
        }
      }
    }, 10000);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [apiBase, plans, language]);
  const plan = localized ? plans[selected] : undefined;
  return <section className="fabric-compare" data-testid="fabric-compare" aria-label={t('Fabric plans (exploratory drafts)')}>
    <header><h2>{t('Fabric plans (exploratory drafts)')}</h2><p>{t('Drafts are not accepted designs.')}</p></header>
    {error ? <p role="alert">{t('Fabric plans unavailable.')}</p> : !catalog || !localized ? <p role="status">{t('Loading fabric plans…')}</p> : <>
      <nav className="fabric-switches" aria-label={t('Fabric plans (exploratory drafts)')}>{FABRIC_IDS.map(id => <button type="button" key={id} data-testid={`fabric-select-${id}`} aria-pressed={selected === id} onClick={() => setSelected(id)}>{t(`fabric.${id}`)}</button>)}<button type="button" data-testid="fabric-parallel-toggle" aria-pressed={parallel} onClick={() => setParallel(value => !value)}>{t(parallel ? 'Single map' : 'Four maps')}</button></nav>
      <div className="fabric-layout"><div><div className={`fabric-maps ${parallel ? 'is-parallel' : ''}`} data-testid="fabric-maps" id="compare-maps">{active && (parallel ? FABRIC_IDS : [selected]).map(id => <figure key={id}><figcaption>{t(`fabric.${id}`)} · <span title={language === 'zh-TW' ? '探索草案' : 'Exploratory draft'} data-status="EXPLORATORY_DRAFT">{language === 'zh-TW' ? '探索草案' : 'Exploratory draft'}<span className="sr-only" style={{ display: 'none' }}>EXPLORATORY_DRAFT</span></span></figcaption>{parallel ? <>{mode !== '3D' && <FabricCompareMap id={id} layers={plans[id].layers} mode="2D" />}{mode !== '2D' && <FabricCompareMap id={mode === 'SPLIT' ? `${id}-3d` : id} layers={plans[id].layers} mode="3D" />}</> : <FabricSyntaxComparison apiBase={apiBase} id={id} layers={plans[id].layers_projected} mode={mode} syntaxContextData={syntaxContextData} syntaxContextStatus={syntaxContextStatus} syntaxContextError={syntaxContextError} syntaxSegments={syntaxSegments} syntaxLegend={syntaxLegend} activeSyntaxLayer={activeSyntaxLayer} syntaxOverlayVisible={syntaxOverlayVisible} onSyntaxOverlayVisibilityChange={onSyntaxOverlayVisibilityChange} />}</figure>)}</div></div>
      {plan && <aside className="fabric-details" data-testid="fabric-details" id="compare-metrics" data-fabric-id={selected}>
        <h3>{t(`fabric.${plan.fabric_id}`)} · {t('Metrics')}</h3><dl>{[['FAR (new buildings)', 'new_far'], ['Coverage (new buildings)', 'gsi'], ['New buildings', 'new_building_count'], ['FSI', 'fsi'], ['L', 'L'], ['OSR', 'OSR'], ['New floor area (m²)', 'new_gfa_m2'], ['Land area (m²)', 'land_area_m2']].map(([label, key]) => <div key={key}><dt>{t(label)}</dt><dd>{format(plan.metrics[key])}</dd></div>)}</dl>
        <JudgementPanel key={parallel ? 'all' : selected} apiBase={apiBase} projectId={projectId} skillId="J-COMPARE" subjectIds={parallel ? [...FABRIC_IDS] : [selected]} />
        {!parallel && (
          <JudgementPanel key={`morph-${selected}`} apiBase={apiBase} projectId={projectId} skillId="J-MORPH" subjectIds={[selected]} />
        )}
        <h3>{t('Land use')}</h3><table className="fabric-land-table"><thead><tr><th>{t('Land use category')}</th><th>{t('Area (m²)')}</th><th>{t('Share of site land')}</th></tr></thead><tbody>{plan.land_use_table.map((row, index) => <tr key={`${row.feature_id}-${index}`}><td>{t(`land.${row.category}`)}</td><td>{format(row.area_m2)}</td><td>{format(row.site_land_percent)}%</td></tr>)}</tbody><tfoot><tr><th>{t('Total')}</th><td>{format(plan.land_use_table.reduce((sum, row) => sum + (row.area_m2 ?? 0), 0))}</td><td>{format(plan.land_use_table.reduce((sum, row) => sum + (row.site_land_percent ?? 0), 0))}%</td></tr></tfoot></table><p>{t('Shares use site land area; retained buildings and waterfront public space are aggregated separately.')}</p>
        <h3>{t('Design statement')}</h3>{plan.design_statement_markdown ? <FabricStatement markdown={plan.design_statement_markdown} /> : <p>{t(language === 'en' ? 'English design statement pending' : 'Design statement unavailable.')}</p>}
        <h3>{t('Failed checks')}</h3>{plan.checks.failure_ids?.length ? <ul>{plan.checks.failure_ids.map(id => <li key={id}>{(language === 'en' ? plan.check_explanations_en : plan.check_explanations_zh)?.[id] ?? t('Check failed; inspect the source check record.')}</li>)}</ul> : <p>{t('No failed checks recorded.')}</p>}
        <h3>{t('Syntax comparison')}</h3>{refreshError && <p role="status">{t('Progress refresh failed; retrying. Showing the last retrieved results.')}</p>}{plan.syntax_summary ? <FabricSyntax summary={plan.syntax_summary} /> : <p role="status">{t('Calculating ({count}/12)', { count: 0 })}</p>}
        <div id={`fabric-intent-sidebar-${selected}`} data-testid="fabric-intent-sidebar" />
        <h3>{t('Limitations')}</h3><ul>{plan.limitations.map((limit, index) => <li key={index}>{t(limit)}</li>)}</ul>
      </aside>}</div>
    </>}
  </section>;
}
type SyntaxPhase = { metrics?: { mean_integration_nain?: number | null; high_integration_length_m?: number | null } } | null;
type SyntaxResult = { mode?: string; status?: string; radius_m?: number; before?: SyntaxPhase; after?: SyntaxPhase; delta_mean_integration_nain?: number | null; reason_zh?: string; error_zh?: string; reason_en?: string; error_en?: string; error?: string; new_street_ranking?: { road_id: string; nain: number; nach: number; inside_length_m: number }[] };
export function FabricSyntax({ summary }: { summary: Record<string, unknown> }) {
  const t = useT(); const { language } = useI18n();
  const results = Array.isArray(summary.results) ? summary.results as SyntaxResult[] : [];
  const count = typeof summary.computed_count === 'number' ? summary.computed_count : results.filter(result => result.status === 'COMPUTED').length;
  const value = (n: unknown) => typeof n === 'number' && Number.isFinite(n) ? number(n, language) : t('Not available');
  return <div className="fabric-syntax">{count < 12 && <p role="status">{t('Calculating ({count}/12)', { count })}</p>}<p>{t('Analysis results: {count}', { count: results.length })}</p><p>{t(String(summary.status ?? 'Not available'))}</p>{results.map((result, index) => <section key={index}><h4>{t(result.mode ?? 'Not available')}</h4><p>{t('Analysis radius (m)')}: {value(result.radius_m)}</p><p>{t(result.status ?? 'Not available')}</p><dl>
    <div><dt>{t('Mean integration before (NAIN)')}</dt><dd>{value(result.before?.metrics?.mean_integration_nain)}</dd></div>
    <div><dt>{t('Mean integration after (NAIN)')}</dt><dd>{value(result.after?.metrics?.mean_integration_nain)}</dd></div>
    <div><dt>{t('Mean integration change (NAIN)')}</dt><dd>{value(result.delta_mean_integration_nain)}</dd></div>
    <div><dt>{t('High integration length before (m)')}</dt><dd>{value(result.before?.metrics?.high_integration_length_m)}</dd></div>
    <div><dt>{t('High integration length after (m)')}</dt><dd>{value(result.after?.metrics?.high_integration_length_m)}</dd></div>
    <div><dt>{t('High integration length change (m)')}</dt><dd>{typeof result.after?.metrics?.high_integration_length_m === 'number' && typeof result.before?.metrics?.high_integration_length_m === 'number' ? value(result.after.metrics.high_integration_length_m - result.before.metrics.high_integration_length_m) : value(null)}</dd></div>
  </dl>{(result.reason_zh || result.error_zh || result.error) && <div><p>{language === 'en' ? (result.reason_en || result.error_en || t('Syntax blocked; inspect the source error.')) : (result.reason_zh || result.error_zh || t('Syntax blocked; inspect the source error.'))}</p></div>}
  <details><summary>{t('All new street rankings')} ({number(result.new_street_ranking?.length ?? 0, language)})</summary>{result.new_street_ranking?.length ? <ol>{result.new_street_ranking.map(road => <li key={road.road_id}>{road.road_id} · {t('Integration (NAIN)')}: {value(road.nain)} · {t('Choice (NACH)')}: {value(road.nach)} · {t('Site length (m)')}: {value(road.inside_length_m)}</li>)}</ol> : <p>{t('Not available')}</p>}</details></section>)}</div>;
}
