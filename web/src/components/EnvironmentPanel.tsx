import React, { useEffect, useMemo, useState } from 'react';
import { useI18n, type Language } from '../i18n';
import './EnvironmentPanel.css';

export interface ColormapBin {
  min_hours: number;
  max_hours: number;
  color_hex: string;
  label: string;
}

export interface ColormapSpec {
  min_value: number;
  max_value: number;
  unit: string;
  bins: ColormapBin[];
  palette_name: string;
}

export interface SensorResult {
  point_id: string;
  coordinates: [number, number, number];
  status: string;
  sunlight_hours: number;
}

interface March21Statistics {
  date: string;
  sensor_count: number;
  mean_hours: number;
  median_hours: number;
  sensors_at_least_2_hours: number;
  sensors_at_least_2_hours_pct: number;
  domain_area_m2: number;
}

export interface EnvironmentSimulationResult {
  run_id: string;
  status: 'SUCCESS' | 'BLOCKED' | 'FAIL' | 'NOT_READY';
  blocked_reason?: string;
  plan: {
    status: string;
    period: { dates?: string[]; start_date?: string; end_date?: string; start_hour: number; end_hour: number; timestep: number };
    location: { latitude: number; longitude: number; timezone: string };
    grid_definition: { spacing_m: number; crs: string };
    true_north_offset_deg: number;
    comparison_domain: string;
  };
  engine: string;
  baseline_sunlight?: { results: SensorResult[] };
  modified_sunlight?: { results: SensorResult[] };
  baseline_march_21_statistics?: March21Statistics | null;
  modified_march_21_statistics?: March21Statistics | null;
  comparison?: {
    baseline_mean?: number;
    modified_mean?: number;
    delta_mean?: number;
    direction_of_change?: 'INCREASED' | 'DECREASED' | 'UNCHANGED' | 'INCOMPARABLE';
    occupied_points?: string[];
    metadata?: {
      paired_domain?: string;
      paired_sensor_count?: number;
      paired_domain_area_m2?: number;
    };
  };
  colormap_spec?: ColormapSpec;
  tool_execution?: { id: string; status?: string };
  artifact?: { id: string; sha256: string };
  evidence_card?: { id: string; validation_status?: string };
  metadata?: Record<string, unknown> & {
    cross_check?: CrossCheckSummary;
    engine_selection?: { fallback_reason?: string | null };
  };
}

interface FormalScenarioOption {
  id: string;
  strategy: string;
  status: string;
}

interface E1Plan {
  plan_id: string;
  status: string;
  period: { dates?: string[]; start_date?: string; end_date?: string; start_hour: number; end_hour: number; timestep: number };
  location: { latitude: number; longitude: number; timezone: string };
  grid_definition: { spacing_m: number; crs: string };
  true_north_offset_deg: number;
  comparison_domain: string;
  notes: string;
}

interface RuntimeInfo {
  radiance_available: boolean;
  radiance_version?: string | null;
  radiance_reason?: string | null;
  engine: string;
  engine_available: boolean;
  fallback_reason?: string | null;
}

interface CrossCheckSummary {
  status: string;
  primary_engine: string;
  cross_check_engine: string;
  tolerance_mean_absolute_delta_hours: number;
  baseline?: { status: string; sensor_count: number; mean_absolute_delta_hours?: number; reason?: string };
  modified?: { status: string; sensor_count: number; mean_absolute_delta_hours?: number; reason?: string };
  reason?: string;
}

export interface EnvironmentPanelProps {
  apiBase: string;
  projectId: string;
  preferredModifiedScenarioId?: string;
  className?: string;
}

const UI_TEXT = {
  panelToggle: { en: 'E1 direct sunlight (draft)', 'zh-TW': 'E1 直射日照（草案）' },
  title: { en: 'E1 Direct Sunlight & Shadow Analysis', 'zh-TW': 'E1 日照與陰影端到端分析' },
  subtitle: { en: 'Radiance direct-sun screening with an independent Python raycast cross-check', 'zh-TW': 'Radiance 直射日照篩選，並以獨立 Python 光線投射交叉檢查' },
  planDraftHuman: { en: 'E1 Plan: Draft Domain Founder (2026-10-04) · Unapproved', 'zh-TW': 'E1 計畫：Founder 範圍草案 (2026-10-04) · 尚未批准' },
  planDraft: { en: 'E1_PLAN: DRAFT_DOMAIN_FOUNDER_2026-10-04 · DRAFT_UNAPPROVED', 'zh-TW': 'E1_PLAN：DRAFT_DOMAIN_FOUNDER_2026-10-04 · 尚未批准' },
  draftNotice: { en: 'Founder selected the public-space comparison domain. Dates, time window, sensor grid, and resolution remain unapproved.', 'zh-TW': 'Founder 已選定公共空間比較範圍；日期、時段、感測網格與解析度仍未批准。' },
  parameters: { en: 'Draft conditions / True North', 'zh-TW': '草案條件／真北' },
  dates: { en: 'Analysis dates', 'zh-TW': '分析日期' },
  timeWindow: { en: 'Time window / timezone', 'zh-TW': '分析時段／時區' },
  location: { en: 'Location / CRS', 'zh-TW': '位置／座標系' },
  trueNorth: { en: 'Grid convergence to True North', 'zh-TW': '網格至真北收斂角' },
  sensorGrid: { en: 'Ground sensor grid', 'zh-TW': '地面感測網格' },
  comparisonDomain: { en: 'Public-space domain', 'zh-TW': '公共空間範圍' },
  domainDefinition: { en: 'Each scheme: site area minus new and retained building footprints and water; streets and roads are included. Paired delta uses the common overlap. This extent is a geometric analysis extent and is not a legal right of way.', 'zh-TW': '各方案以基地範圍扣除新建與保留建築物占地及水域；街道與道路計入公共空間。配對差值以兩方案公共空間的共同重疊範圍計算。此範圍是幾何分析範圍，不是法律上的公共通行權。' },
  runtime: { en: 'Calculation engine', 'zh-TW': '計算引擎' },
  runtimeChecking: { en: 'Checking Radiance runtime…', 'zh-TW': '正在核對 Radiance 執行環境…' },
  radianceUnavailable: { en: 'Radiance unavailable · this run uses the headless Python engine', 'zh-TW': 'Radiance 不可用 · 本次使用無頭式 Python 引擎' },
  radianceSelected: { en: 'Radiance 6.0.2 verified · primary engine', 'zh-TW': 'Radiance 6.0.2 已核實 · 預設引擎' },
  engineUsed: { en: 'Engine used for this run', 'zh-TW': '本次執行引擎' },
  engineFallback: { en: 'Radiance fallback reason', 'zh-TW': 'Radiance 回退原因' },
  crossCheck: { en: 'Python raycast cross-check', 'zh-TW': 'Python 光線投射交叉檢查' },
  baselineCrossCheck: { en: 'Baseline', 'zh-TW': '基準方案' },
  comparedCrossCheck: { en: 'Compared', 'zh-TW': '比較方案' },
  crossCheckPass: { en: 'PASS', 'zh-TW': '通過' },
  crossCheckDisagreement: { en: 'DISAGREEMENT', 'zh-TW': '不一致' },
  crossCheckUnavailable: { en: 'UNAVAILABLE', 'zh-TW': '無法比對' },
  crossCheckReason: { en: 'Reason', 'zh-TW': '原因' },
  scenarios: { en: 'Formal scenarios for analysis', 'zh-TW': '供分析的正式方案' },
  baseline: { en: 'Baseline formal scenario', 'zh-TW': '基準正式方案' },
  compared: { en: 'Compared formal scenario', 'zh-TW': '比較正式方案' },
  noScenarios: { en: 'At least two eligible formal proposals are required.', 'zh-TW': '至少需要兩個可用的正式提案。' },
  loadError: { en: 'E1 plan or formal proposals could not be loaded.', 'zh-TW': '無法載入 E1 計畫或正式提案。' },
  runDraft: { en: 'Run draft preview', 'zh-TW': '執行草案預覽' },
  running: { en: 'Running…', 'zh-TW': '執行中…' },
  runError: { en: 'Draft preview failed.', 'zh-TW': '草案預覽失敗。' },
  results: { en: 'Draft sunlight results', 'zh-TW': '草案日照結果' },
  baselineMap: { en: 'Baseline · sunlight hours', 'zh-TW': '基準方案 · 日照時數' },
  modifiedMap: { en: 'Compared scheme · sunlight hours', 'zh-TW': '比較方案 · 日照時數' },
  baselineMean: { en: 'Baseline mean · common overlap', 'zh-TW': '基準方案均值 · 共同重疊範圍' },
  modifiedMean: { en: 'Compared mean · common overlap', 'zh-TW': '比較方案均值 · 共同重疊範圍' },
  delta: { en: 'Paired change · common overlap', 'zh-TW': '配對變化量 · 共同重疊範圍' },
  pairedCount: { en: 'Common-overlap paired delta', 'zh-TW': '共同重疊範圍配對差值' },
  informationalStats: { en: 'Informational per-scheme statistics · 21 Mar', 'zh-TW': '各方案資訊性統計 · 3 月 21 日' },
  statsMean: { en: 'Mean', 'zh-TW': '平均值' },
  statsMedian: { en: 'Median', 'zh-TW': '中位數' },
  statsAtLeast2: { en: 'Sensors ≥ 2 h', 'zh-TW': '感測點 ≥ 2 小時' },
  sharedScale: { en: 'Shared color scale', 'zh-TW': '共用色階' },
  sameDomainNotice: { en: 'Each map uses its scheme’s own public-space domain; paired delta uses the common overlap. Both maps share one color scale.', 'zh-TW': '每張圖呈現各自方案的公共空間範圍；配對差值使用共同重疊範圍。兩張圖共用同一色階。' },
  toolExecution: { en: 'ToolExecution', 'zh-TW': '工具執行' },
  artifact: { en: 'Artifact', 'zh-TW': '產物' },
  evidenceStatus: { en: 'Evidence status', 'zh-TW': '證據狀態' },
  provisional: { en: 'UNVERIFIED · plan remains unapproved', 'zh-TW': '未驗證 · 計畫仍未批准' },
  directOnly: { en: 'Direct sun only; diffuse radiation, weather, terrain, and materials are not modelled.', 'zh-TW': '僅計算直射日照；未模擬散射輻射、天氣、地形與材料。' },
  noMap: { en: 'No sensor results', 'zh-TW': '沒有感測結果' },
};

function t(key: keyof typeof UI_TEXT, lang: Language): string {
  return UI_TEXT[key][lang] ?? UI_TEXT[key].en;
}

function apiRoot(apiBase: string): string {
  return apiBase.replace(/\/$/, '');
}

function formatHour(hour: number): string {
  const wholeHour = Math.floor(hour);
  const minutes = Math.round((hour - wholeHour) * 60);
  return `${String(wholeHour).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
}

function formatValue(value: number | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} h` : '—';
}

function formatPercent(value: number | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '—';
}

function binColor(value: number, spec: ColormapSpec): string {
  const last = spec.bins.length - 1;
  const bin = spec.bins.find((item, index) => value >= item.min_hours && (value < item.max_hours || index === last));
  return bin?.color_hex ?? '#475569';
}

function SensorMap({ points, spec, label, testId }: { points: SensorResult[]; spec: ColormapSpec; label: string; testId: string }) {
  const width = 280;
  const height = 164;
  const padding = 14;
  const xs = points.map(point => point.coordinates[0]);
  const ys = points.map(point => point.coordinates[1]);
  const minX = xs.length ? Math.min(...xs) : 0;
  const maxX = xs.length ? Math.max(...xs, minX + 1) : 1;
  const minY = ys.length ? Math.min(...ys) : 0;
  const maxY = ys.length ? Math.max(...ys, minY + 1) : 1;
  const toX = (x: number) => padding + ((x - minX) / (maxX - minX)) * (width - 2 * padding);
  const toY = (y: number) => height - padding - ((y - minY) / (maxY - minY)) * (height - 2 * padding);

  return (
    <figure className="environment-panel__map-figure">
      <figcaption>{label}</figcaption>
      {points.length === 0 ? <p>{t('noMap', 'en')}</p> : (
        <svg className="environment-panel__sensor-map" data-testid={testId} role="img" aria-label={label} viewBox={`0 0 ${width} ${height}`}>
          <rect x="0" y="0" width={width} height={height} fill="#0b1220" />
          {points.map(point => (
            <circle key={point.point_id} cx={toX(point.coordinates[0])} cy={toY(point.coordinates[1])} r="5" fill={binColor(point.sunlight_hours, spec)} stroke="#e2e8f0" strokeWidth="0.6">
              <title>{`${point.point_id}: ${point.sunlight_hours.toFixed(2)} h`}</title>
            </circle>
          ))}
        </svg>
      )}
    </figure>
  );
}

export const EnvironmentPanel: React.FC<EnvironmentPanelProps> = ({
  apiBase,
  projectId,
  preferredModifiedScenarioId,
  className = '',
}) => {
  const { language } = useI18n();
  const [plan, setPlan] = useState<E1Plan | null>(null);
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [proposals, setProposals] = useState<FormalScenarioOption[]>([]);
  const [baselineId, setBaselineId] = useState('');
  const [modifiedId, setModifiedId] = useState('');
  const [loadError, setLoadError] = useState(false);
  const [runError, setRunError] = useState('');
  const [result, setResult] = useState<EnvironmentSimulationResult | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(true);

  useEffect(() => {
    let active = true;
    const root = apiRoot(apiBase);
    Promise.all([
      fetch(`${root}/api/projects/${encodeURIComponent(projectId)}/formal-proposals`, { headers: { Accept: 'application/json' } }),
      fetch(`${root}/api/environment/e1/plan`, { headers: { Accept: 'application/json' } }),
      fetch(`${root}/api/environment/runtimes`, { headers: { Accept: 'application/json' } }),
    ]).then(async ([proposalResponse, planResponse, runtimeResponse]) => {
      if (!proposalResponse.ok || !planResponse.ok || !runtimeResponse.ok) throw new Error('E1 inputs unavailable');
      const [rows, planData, runtimeData] = await Promise.all([
        proposalResponse.json() as Promise<FormalScenarioOption[]>,
        planResponse.json() as Promise<E1Plan>,
        runtimeResponse.json() as Promise<RuntimeInfo>,
      ]);
      if (!active) return;
      const eligible = rows.filter(row => !['REJECTED', 'STALE', 'BLOCKED'].includes(row.status.toUpperCase()));
      setProposals(eligible);
      setPlan(planData);
      setRuntime(runtimeData);
      const accepted = eligible.find(row => row.status.toUpperCase() === 'ACCEPTED');
      const initialBaseline = accepted ?? eligible[0];
      const preferred = eligible.find(row => row.id === preferredModifiedScenarioId && row.id !== initialBaseline?.id);
      const initialModified = preferred ?? eligible.find(row => row.id !== initialBaseline?.id);
      setBaselineId(initialBaseline?.id ?? '');
      setModifiedId(initialModified?.id ?? '');
      setLoadError(false);
    }).catch(() => {
      if (active) setLoadError(true);
    });
    return () => { active = false; };
  }, [apiBase, projectId, preferredModifiedScenarioId]);

  const dates = plan?.period.dates?.join(' · ') ?? (plan?.period.start_date && plan.period.end_date ? `${plan.period.start_date} – ${plan.period.end_date}` : '—');
  const timeWindow = plan ? `${formatHour(plan.period.start_hour)}–${formatHour(plan.period.end_hour)} · ${plan.location.timezone}` : '—';
  const colormap = result?.colormap_spec;
  const canRun = Boolean(plan && baselineId && modifiedId && baselineId !== modifiedId && !isRunning);
  const titleText = useMemo(() => (key: keyof typeof UI_TEXT) => t(key, language), [language]);
  const runtimeNote = runtime
    ? runtime.radiance_available
      ? titleText('radianceSelected')
      : `${titleText('radianceUnavailable')}${runtime.fallback_reason ? ` · ${runtime.fallback_reason}` : ''}`
    : titleText('runtimeChecking');

  const handleRun = async () => {
    if (!canRun) return;
    setIsRunning(true);
    setRunError('');
    try {
      const response = await fetch(`${apiRoot(apiBase)}/api/environment/e1/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          baseline_scenario_id: baselineId,
          modified_scenario_id: modifiedId,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : titleText('runError'));
      setResult(payload as EnvironmentSimulationResult);
    } catch (error) {
      setRunError(error instanceof Error ? error.message : titleText('runError'));
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <section className={`environment-panel ${className}`} data-testid="environment-panel" data-collapsed={isCollapsed}>
      <div className="environment-panel__header">
        <button
          type="button"
          className="environment-panel__collapse-toggle"
          aria-expanded={!isCollapsed}
          aria-controls="environment-panel-content"
          onClick={() => setIsCollapsed(collapsed => !collapsed)}
        >
          <span className="environment-panel__collapse-icon" aria-hidden="true">{isCollapsed ? '▸' : '▾'}</span>
          {titleText('panelToggle')}
        </button>
        <div className="environment-panel__badge environment-panel__badge--draft" data-testid="plan-status-badge" title={titleText('planDraft')}>
          <span style={{ display: 'none' }} className="sr-only">{titleText('planDraft')}</span>
          {titleText('planDraftHuman')}
        </div>
      </div>

      <div id="environment-panel-content" className="environment-panel__content" hidden={isCollapsed}>
        <div className="environment-panel__title-group">
          <h2>{titleText('title')}</h2>
          <p className="environment-panel__subtitle">{titleText('subtitle')}</p>
        </div>
        <div className="environment-panel__disclaimer" data-testid="draft-plan-notice">{titleText('draftNotice')}</div>
        {loadError && <p role="alert">{titleText('loadError')}</p>}

      <section className="environment-panel__section">
        <h3 className="environment-panel__section-title">{titleText('parameters')}</h3>
        <div className="environment-panel__param-grid">
          <div className="environment-panel__param-item"><span className="environment-panel__param-label">{titleText('dates')}</span><span className="environment-panel__param-value">{dates}</span></div>
          <div className="environment-panel__param-item"><span className="environment-panel__param-label">{titleText('timeWindow')}</span><span className="environment-panel__param-value">{timeWindow}</span></div>
          <div className="environment-panel__param-item"><span className="environment-panel__param-label">{titleText('location')}</span><span className="environment-panel__param-value">{plan ? `${plan.location.latitude.toFixed(2)}° N, ${plan.location.longitude.toFixed(2)}° E · ${plan.grid_definition.crs}` : '—'}</span></div>
          <div className="environment-panel__param-item"><span className="environment-panel__param-label">{titleText('trueNorth')}</span><span className="environment-panel__param-value">{plan ? `${plan.true_north_offset_deg.toFixed(3)}°` : '—'}</span></div>
          <div className="environment-panel__param-item"><span className="environment-panel__param-label">{titleText('sensorGrid')}</span><span className="environment-panel__param-value">{plan ? `${plan.grid_definition.spacing_m.toFixed(1)} m · EPSG:28992` : '—'}</span></div>
          <div className="environment-panel__param-item"><span className="environment-panel__param-label">{titleText('comparisonDomain')}</span><span className="environment-panel__param-value">{titleText('domainDefinition')}</span></div>
        </div>
      </section>

      <section className="environment-panel__section">
        <h3 className="environment-panel__section-title">{titleText('runtime')}</h3>
        <div className="environment-panel__runtime-row">
          <div className="environment-panel__runtime-tag"><span className="environment-panel__runtime-dot" />{runtime?.engine ?? titleText('runtimeChecking')}</div>
          <p className="environment-panel__runtime-note">{runtimeNote}</p>
        </div>
      </section>

      <section className="environment-panel__section">
        <h3 className="environment-panel__section-title">{titleText('scenarios')}</h3>
        {proposals.length < 2 && !loadError ? <p>{titleText('noScenarios')}</p> : (
          <div className="environment-panel__scenario-pair">
            <label>{titleText('baseline')}
              <select aria-label={titleText('baseline')} value={baselineId} onChange={event => {
                const next = event.target.value;
                setBaselineId(next);
                if (next === modifiedId) setModifiedId(proposals.find(row => row.id !== next)?.id ?? '');
              }}>
                {proposals.map(row => <option key={row.id} value={row.id}>{row.strategy} · {row.status}</option>)}
              </select>
            </label>
            <label>{titleText('compared')}
              <select aria-label={titleText('compared')} value={modifiedId} onChange={event => {
                const next = event.target.value;
                setModifiedId(next);
                if (next === baselineId) setBaselineId(proposals.find(row => row.id !== next)?.id ?? '');
              }}>
                {proposals.filter(row => row.id !== baselineId).map(row => <option key={row.id} value={row.id}>{row.strategy} · {row.status}</option>)}
              </select>
            </label>
          </div>
        )}
        <div className="environment-panel__actions">
          <button type="button" className="environment-panel__button environment-panel__button--primary" onClick={handleRun} disabled={!canRun}>
            {isRunning ? titleText('running') : titleText('runDraft')}
          </button>
        </div>
        {runError && <p role="alert" className="environment-panel__error">{titleText('runError')} {runError}</p>}
      </section>

      {result && (
        <section className="environment-panel__section" data-testid="results-section">
          <h3 className="environment-panel__section-title">{titleText('results')} · {titleText('planDraft')}</h3>
          <p className="environment-panel__runtime-note">{titleText('engineUsed')}: {result.engine}</p>
          {result.metadata?.engine_selection?.fallback_reason && (
            <p role="status" className="environment-panel__runtime-note">
              {titleText('engineFallback')}: {result.metadata.engine_selection.fallback_reason}
            </p>
          )}
          {result.status !== 'SUCCESS' && <p role="status">{result.status}{result.blocked_reason ? ` · ${result.blocked_reason}` : ''}</p>}
          {result.status === 'SUCCESS' && result.comparison && colormap && (
            <>
              <div className="environment-panel__summary-cards">
                <div className="environment-panel__card"><span>{titleText('baselineMean')}</span><strong>{formatValue(result.comparison.baseline_mean)}</strong></div>
                <div className="environment-panel__card"><span>{titleText('modifiedMean')}</span><strong>{formatValue(result.comparison.modified_mean)}</strong></div>
                <div className="environment-panel__card"><span>{titleText('delta')}</span><strong>{formatValue(result.comparison.delta_mean)}</strong></div>
              </div>
              <p className="environment-panel__runtime-note" data-testid="paired-domain-summary">
                {titleText('pairedCount')} · {result.comparison.metadata?.paired_sensor_count ?? 0} sensors
              </p>
              <div className="environment-panel__statistics" data-testid="march-21-statistics">
                <h4>{titleText('informationalStats')}</h4>
                {([
                  ['baseline', result.baseline_march_21_statistics],
                  ['modified', result.modified_march_21_statistics],
                ] as const).map(([scheme, stats]) => stats && (
                  <div className="environment-panel__statistics-row" key={scheme}>
                    <strong>{scheme === 'baseline' ? titleText('baselineCrossCheck') : titleText('comparedCrossCheck')} · {stats.sensor_count} sensors</strong>
                    <span>{titleText('statsMean')}: {formatValue(stats.mean_hours)}</span>
                    <span>{titleText('statsMedian')}: {formatValue(stats.median_hours)}</span>
                    <span>{titleText('statsAtLeast2')}: {stats.sensors_at_least_2_hours} · {formatPercent(stats.sensors_at_least_2_hours_pct)}</span>
                  </div>
                ))}
              </div>
              {result.metadata?.cross_check && (
                <div className="environment-panel__cross-check" data-testid="e1-cross-check" role="status">
                  <strong>{titleText('crossCheck')}: {titleText(result.metadata.cross_check.status === 'PASS' ? 'crossCheckPass' : result.metadata.cross_check.status === 'DISAGREEMENT' ? 'crossCheckDisagreement' : 'crossCheckUnavailable')}</strong>
                  <span>{titleText('baselineCrossCheck')}: {result.metadata.cross_check.baseline?.sensor_count ?? 0} sensors · mean |Δ| {formatValue(result.metadata.cross_check.baseline?.mean_absolute_delta_hours)}</span>
                  <span>{titleText('comparedCrossCheck')}: {result.metadata.cross_check.modified?.sensor_count ?? 0} sensors · mean |Δ| {formatValue(result.metadata.cross_check.modified?.mean_absolute_delta_hours)}</span>
                  {result.metadata.cross_check.reason && <span>{titleText('crossCheckReason')}: {result.metadata.cross_check.reason}</span>}
                  {result.metadata.cross_check.baseline?.reason && <span>{titleText('baselineCrossCheck')} · {titleText('crossCheckReason')}: {result.metadata.cross_check.baseline.reason}</span>}
                  {result.metadata.cross_check.modified?.reason && <span>{titleText('comparedCrossCheck')} · {titleText('crossCheckReason')}: {result.metadata.cross_check.modified.reason}</span>}
                  <small>mean |Δ| tolerance ≤ {result.metadata.cross_check.tolerance_mean_absolute_delta_hours.toFixed(2)} h</small>
                </div>
              )}
              <div className="environment-panel__maps">
                <SensorMap points={result.baseline_sunlight?.results ?? []} spec={colormap} label={titleText('baselineMap')} testId="e1-heatmap-baseline" />
                <SensorMap points={result.modified_sunlight?.results ?? []} spec={colormap} label={titleText('modifiedMap')} testId="e1-heatmap-modified" />
              </div>
              <div className="environment-panel__colormap-bar">
                <strong>{titleText('sharedScale')}: {colormap.min_value.toFixed(1)}–{colormap.max_value.toFixed(1)} {colormap.unit}</strong>
                <div className="environment-panel__colormap-ramp">
                  {colormap.bins.map(bin => <span key={bin.label} style={{ backgroundColor: bin.color_hex }} title={bin.label} />)}
                </div>
                <small>{titleText('sameDomainNotice')}</small>
              </div>
              <p className="environment-panel__limitation">{titleText('directOnly')}</p>
              <dl className="environment-panel__audit">
                <dt>{titleText('toolExecution')}</dt><dd>{result.tool_execution?.id ?? '—'}</dd>
                <dt>{titleText('artifact')}</dt><dd>{result.artifact?.id ?? '—'} · {result.artifact?.sha256 ?? '—'}</dd>
                <dt>{titleText('evidenceStatus')}</dt><dd>{titleText('provisional')}</dd>
              </dl>
            </>
          )}
        </section>
      )}
      </div>
    </section>
  );
};
