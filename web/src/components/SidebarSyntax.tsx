import { useT } from '../i18n';
import React from 'react';
import type { SyntaxLayer, SyntaxLayerPlanEntry } from '../types';
import { CheckCircle, Info } from 'lucide-react';
import { buildSyntaxHeatmapClassification } from '../utils/syntaxHeatmap';

interface SidebarSyntaxProps {
  layers: SyntaxLayer[];
  activeLayer: SyntaxLayer | null;
  onSelectLayer: (layer: SyntaxLayer | null) => void;
  dataReadiness?: string;
  layerPlan?: SyntaxLayerPlanEntry[];
  exploratoryDownloadUrl?: string;
  layersSource?: 'persisted_database_record' | 'verified_file_fallback' | 'none';
}

const metricTitle = (metricKey: string): string => {
  if (metricKey.toLowerCase() === 'nain') return 'Angular integration (NAIN)';
  if (metricKey.toLowerCase() === 'nach') return 'Angular choice (NACH)';
  return `Unrecognized metric (${metricKey})`;
};

const formatAvailableValue = (value: number | undefined): string =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : 'unavailable';

type SyntaxNetworkMode = NonNullable<SyntaxLayer['network_mode']>;

const isSyntaxNetworkMode = (value: unknown): value is SyntaxNetworkMode =>
  value === 'pedestrian' || value === 'bicycle' || value === 'motor_vehicle';

const getNetworkModeLabel = (networkMode: SyntaxNetworkMode | undefined): string => {
  if (networkMode === 'pedestrian') return '行人路網';
  if (networkMode === 'bicycle') return '自行車路網';
  if (networkMode === 'motor_vehicle') return '汽車路網';
  return '網路模式未記錄／未知';
};

const resolveNetworkMode = (
  layer: SyntaxLayer,
  layerPlan: SyntaxLayerPlanEntry[],
): SyntaxNetworkMode | undefined => {
  const sameIdPlans = layerPlan.filter(plan => plan.layer_id === layer.layer_id);
  if (sameIdPlans.some(plan =>
    plan.radius_m !== layer.radius_m || plan.metric_key.toLowerCase() !== layer.metric_key.toLowerCase()
  )) return undefined;

  const plannedModes = new Set<unknown>(sameIdPlans
    .map(plan => plan.network_mode)
    .filter(mode => mode !== undefined && mode !== null));
  if (plannedModes.size > 1) return undefined;
  const [plannedMode] = plannedModes;
  if (plannedMode !== undefined && !isSyntaxNetworkMode(plannedMode)) return undefined;

  const layerMode: unknown = layer.network_mode;
  if (layerMode !== undefined && layerMode !== null) {
    if (!isSyntaxNetworkMode(layerMode)) return undefined;
    return plannedMode !== undefined && plannedMode !== layerMode ? undefined : layerMode;
  }
  return isSyntaxNetworkMode(plannedMode) ? plannedMode : undefined;
};

export const SidebarSyntax: React.FC<SidebarSyntaxProps> = ({
  layers,
  activeLayer,
  onSelectLayer,
  dataReadiness = 'UNKNOWN',
  layerPlan = [],
  exploratoryDownloadUrl,
  layersSource = 'none',
}) => {
  const t = useT();
  const resultById = new Map(layers.map(layer => [layer.layer_id, layer]));
  const plannedLayers = layerPlan.map(plan => {
    const result = resultById.get(plan.layer_id);
    const resultCount = result ? Object.keys(result.segment_values || {}).length : 0;
    const planCountMatches = !Number.isInteger(plan.segment_value_count)
      || resultCount === plan.segment_value_count;
    const optionalFlagsMatch = (typeof plan.formal_result_eligible !== 'boolean'
        || result?.formal_result_eligible === plan.formal_result_eligible)
      && (typeof plan.exploratory_only !== 'boolean'
        || result?.exploratory_only === plan.exploratory_only);
    const computed = plan.calculation_status === 'COMPUTED'
      && result?.calculation_status === 'COMPUTED'
      && result.radius_m === plan.radius_m
      && result.metric_key.toLowerCase() === plan.metric_key.toLowerCase()
      && optionalFlagsMatch
      && result.data_readiness === plan.data_readiness
      && planCountMatches
      && ((result.statistics?.count ?? 0) > 0 || resultCount > 0);
    let resultStatus: string;
    if (computed) {
      resultStatus = plan.formal_result_eligible
        ? 'Computed · review status applies'
        : 'Computed · exploratory';
    } else if (plan.calculation_status === 'COMPUTED') {
      resultStatus = 'Result unavailable · plan/result mismatch';
    } else if (plan.calculation_status === 'NOT_COMPUTED_COVERAGE_BLOCKED') {
      resultStatus = 'Not computed · coverage blocked';
    } else if (plan.calculation_status === 'NOT_COMPUTED_RUNTIME_BUDGET') {
      resultStatus = 'Not computed · runtime budget';
    } else {
      resultStatus = `Not computed · ${plan.calculation_status}`;
    }
    return { plan, result, resultCount, computed, resultStatus };
  });
  const activeLegendBreaks = (activeLayer?.legend_breaks || []).filter(value => Number.isFinite(value));
  const heatmap = React.useMemo(
    () => (activeLayer ? buildSyntaxHeatmapClassification(activeLayer.segment_values) : null),
    [activeLayer],
  );
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{ padding: '14px', borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
          <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {t("Space Syntax Layers")} </span>
          <span style={{
            fontSize: '10px',
            fontFamily: 'var(--font-mono)',
            padding: '2px 6px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'rgba(56, 189, 248, 0.1)',
            color: 'var(--accent-cyan)',
          }}>
            {layers.length > 0 ? t("EXPLORATORY OUTPUT") : t("NO COMPUTED RESULT")}
          </span>
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-dim)' }}>
          {layers.length > 0
            ? t("Computed outputs are exploratory. Each layer below shows its calculation status and source or method limitations.")
            : t("Unavailable: {0}. Planned layers do not supply values.", {"0": dataReadiness})}
        </div>
      </div>

      {layers.length > 0 && (
        <div id="syntax-layer-source" role="status" style={{ margin: '8px 14px 0', fontSize: '10px', color: 'var(--text-muted)' }}>
          {layersSource === 'verified_file_fallback'
            ? t("檔案回退：已驗證的候選檔，尚未持久化至資料庫。")
            : layersSource === 'persisted_database_record'
              ? t("資料來源：SQLite 持久化記錄。")
              : t("資料來源尚未標示。")}
        </div>
      )}

      {layers.length > 0 && (
        <div id="syntax-exploratory-warning" role="alert" style={{ margin: '10px 14px 0', padding: '11px', border: '1px solid #fb7185', borderRadius: 'var(--radius-sm)', color: '#fecdd3', background: 'rgba(159, 18, 57, 0.18)', fontSize: '11px', lineHeight: 1.45 }}>
          <strong>{t("EXPLORATORY ONLY.")}</strong> {t("Computed layers are not approved design conclusions. Layers without a completed calculation have no metric values; see their individual readiness and limitations below.")} {exploratoryDownloadUrl && (
            <div style={{ marginTop: '8px' }}>
              <a id="syntax-exploratory-download" href={exploratoryDownloadUrl} download style={{ color: '#fda4af', textDecoration: 'underline' }}>
                {t("Download explicitly exploratory 800 m figure (SVG)")} </a>
            </div>
          )}
        </div>
      )}

      {/* Layer List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 14px' }}>
        {layers.length === 0 && (
          <div id="syntax-blocked-status" role="status" style={{ padding: '12px', border: '1px solid var(--accent-amber)', borderRadius: 'var(--radius-sm)', color: 'var(--accent-amber)', fontSize: '11px' }}>
            {t("No Rotterdam Syntax layer is currently verified against the active spatial-r01 source package. Planned radii do not constitute computed or validated layers.")} </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {/* Option to turn off syntax overlay */}
          <div
            onClick={() => onSelectLayer(null)}
            style={{
              padding: '8px 12px',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: activeLayer === null ? 'rgba(56, 189, 248, 0.15)' : 'var(--bg-surface-elevated)',
              border: `1px solid ${activeLayer === null ? 'var(--border-focus)' : 'var(--border-subtle)'}`,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span style={{ fontSize: '12px', fontWeight: 500 }}>{t("None (Base Map Only)")}</span>
            {activeLayer === null && <CheckCircle size={14} color="var(--accent-cyan)" />}
          </div>

          {layers.map(layer => {
            const isSelected = activeLayer?.layer_id === layer.layer_id;
            const badgeColor = layer.formal_result_eligible ? 'var(--accent-emerald)' : 'var(--accent-amber)';
            const badgeBg = layer.formal_result_eligible ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)';

            return (
              <div
                key={layer.layer_id}
                id={`layer-${layer.layer_id}`}
                onClick={() => onSelectLayer(layer)}
                style={{
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: isSelected ? 'rgba(56, 189, 248, 0.12)' : 'var(--bg-surface-elevated)',
                  border: `1px solid ${isSelected ? 'var(--border-focus)' : 'var(--border-subtle)'}`,
                  cursor: 'pointer',
                  transition: 'all 0.15s ease',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '4px' }}>
                  <div style={{ fontWeight: 600, fontSize: '12px', color: isSelected ? 'var(--accent-cyan)' : 'var(--text-main)' }}>
                    {t(layer.title)}
                  </div>
                  {isSelected && <CheckCircle size={14} color="var(--accent-cyan)" />}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '6px' }}>
                  <span style={{
                    fontSize: '10px',
                    fontFamily: 'var(--font-mono)',
                    padding: '2px 5px',
                    borderRadius: '2px',
                    backgroundColor: badgeBg,
                    color: badgeColor,
                    border: `1px solid ${badgeColor}33`,
                  }}>
                  {t(layer.data_readiness)}
                  </span>
                  <span style={{ fontSize: '10px', color: 'var(--text-dim)' }}>
                    {t("R=")}{layer.radius_m}{t("m ·")} {layer.unit}
                  </span>
                  <span style={{
                    fontSize: '9px',
                    fontFamily: 'var(--font-mono)',
                    padding: '1px 5px',
                    borderRadius: '2px',
                    backgroundColor: 'rgba(56, 189, 248, 0.1)',
                    color: 'var(--accent-cyan)',
                    border: '1px solid rgba(56, 189, 248, 0.25)',
                  }}>
                    {t(getNetworkModeLabel(resolveNetworkMode(layer, layerPlan)))}
                  </span>
                </div>

                <div style={{ marginTop: '5px', fontSize: '10px', color: 'var(--text-dim)' }}>
                  {t("Status:")} {t(layer.calculation_status)}
                </div>
                <div style={{ marginTop: '5px', fontSize: '10px', color: 'var(--text-dim)' }}>
                  {layer.calculation_status === 'COMPUTED' && (layer.statistics?.count ?? Object.keys(layer.segment_values || {}).length) > 0
                    ? t("Computed summary covers {0} segments.", {"0": layer.statistics?.count ?? Object.keys(layer.segment_values || {}).length})
                    : t("No metric values available; missing is unavailable, not zero.")}
                </div>
                {layer.calculation_status === 'COMPUTED' && Object.keys(layer.segment_values || {}).length === 0 && (
                  <div style={{ marginTop: '5px', fontSize: '10px', color: 'var(--text-dim)' }}>
                    {t("Segment geometry is unavailable, so this result cannot be drawn as a map overlay.")} </div>
                )}
                <div style={{ marginTop: '5px', fontSize: '10px', color: 'var(--text-dim)', lineHeight: 1.4 }}>
                  {t(layer.limitations)}
                </div>
              </div>
            );
          })}
        </div>

        {layerPlan.length > 0 && (
          <section id="syntax-layer-plan" aria-label={t("Planned Syntax results")} style={{ marginTop: '10px', padding: '9px 10px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', fontSize: '10px', color: 'var(--text-muted)' }}>
            <strong>{t("Planned Syntax results")}</strong>
            <div role="list" aria-label={t("Planned Syntax result readiness")} style={{ display: 'flex', flexDirection: 'column', gap: '7px', marginTop: '7px' }}>
              {plannedLayers.map(({ plan, computed, result, resultStatus }) => (
                <div key={plan.layer_id} role="listitem" style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '6px' }}>
                  <div style={{ color: 'var(--text-main)', fontWeight: 600 }}>{plan.radius_m.toLocaleString()} {t("m ·")} {t(metricTitle(plan.metric_key))}</div>
                  <div>{t(resultStatus)}</div>
                  <div>{t(plan.data_readiness)}</div>
                  {computed
                    ? <div>{t("Verified result layer matched by its persisted layer ID, radius, and metric.")}</div>
                    : <div>{t("No metric values available; missing is unavailable, not zero.")}</div>}
                  {!result && <div>{t("Persisted result layer is missing.")}</div>}
                </div>
              ))}
            </div>
          </section>
        )}
      </div>

      {/* Dynamic Legend Panel when Layer is active */}
      {activeLayer && (
        <div style={{
          padding: '14px',
          borderTop: '1px solid var(--border-subtle)',
          backgroundColor: 'var(--bg-surface-elevated)',
        }}>
          <div role="region" aria-label={t("Metric legend for {0}", {"0": t(activeLayer.title)})}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '8px' }}>
            {t("METRIC LEGEND:")} {activeLayer.metric_key.toUpperCase()} · {activeLayer.radius_m.toLocaleString()} {t("m ·")} {activeLayer.unit}
          </div>

          {/* Five Quintile Classes & Uncomputed Style per PD-21 */}
          {heatmap?.hasData && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '8px' }}>
              {heatmap.ranges.map((range) => (
                <div key={range.rank} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ width: '12px', height: '12px', borderRadius: '2px', backgroundColor: range.color }} />
                    <span style={{ color: 'var(--text-main)', fontWeight: 500 }}>{t(range.label)}</span>
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                    {range.min.toFixed(2)} – {range.max.toFixed(2)} ({range.percentage.toFixed(0)}%)
                  </span>
                </div>
              ))}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '10px', marginTop: '3px', paddingTop: '3px', borderTop: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <span style={{ width: '12px', height: '0px', borderTop: '2px dashed #64748b' }} />
                  <span style={{ color: 'var(--text-dim)' }}>{t("Uncomputed / Excluded")}</span>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)', fontSize: '9px' }}>{t("gray dashed line")}</span>
              </div>
            </div>
          )}

          {/* Color bar */}
          <div style={{
            height: '8px',
            borderRadius: '3px',
            background: 'linear-gradient(to right, #1d4ed8, #06b6d4, #10b981, #f59e0b, #dc2626)',
            marginTop: '8px',
            marginBottom: '6px',
          }} />

          {/* Deterministic range values; absent values remain explicitly unavailable. */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: '10px',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-dim)',
          }}>
            <span>{t("Min:")} {t(formatAvailableValue(activeLayer.statistics?.min))}</span>
            <span>{t("Mean:")} {t(formatAvailableValue(activeLayer.statistics?.mean))}</span>
            <span>{t("Max:")} {t(formatAvailableValue(activeLayer.statistics?.max))}</span>
          </div>

          <div aria-label={t("Classifier breaks")} style={{ marginTop: '6px', display: 'flex', flexWrap: 'wrap', gap: '4px', fontSize: '9px', fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
            {activeLegendBreaks.length > 0
              ? activeLegendBreaks.map((value, index) => <span key={`${index}-${value}`}>{index === 0 ? t("Breaks: ") : '· '}{value.toFixed(2)}</span>)
              : <span>{t("Classifier breaks unavailable.")}</span>}
          </div>

          {/* Limitations Notice */}
          <div style={{
            marginTop: '10px',
            padding: '8px',
            borderRadius: 'var(--radius-sm)',
            backgroundColor: 'var(--bg-app)',
            fontSize: '10px',
            color: 'var(--text-dim)',
            lineHeight: '1.4',
            display: 'flex',
            gap: '6px',
          }}>
            <Info size={13} style={{ flexShrink: 0, marginTop: '1px' }} />
            <div>{t(activeLayer.limitations)}</div>
          </div>
          <div style={{ marginTop: '7px', fontSize: '9px', lineHeight: 1.4, color: 'var(--text-dim)', overflowWrap: 'anywhere' }}>
            {t("Formula:")} {activeLayer.formula_version || t("unrecorded")} {t("· Source manifest:")} {activeLayer.source_manifest_sha256 || t("unavailable")} {t("· Result:")} {activeLayer.syntax_result_sha256 || t("unavailable")}
          </div>
          </div>
        </div>
      )}
    </div>
  );
};
