import { Fragment } from 'react';
import { useI18n, type Language } from '../i18n';
import type { FormalProposal } from './CompareWorkspace';
import './FormalProperties.css';

export interface ZoneUseItem {
  use: string;
  gfa_m2: number;
}

export interface ZoneSummary {
  zoneId: string;
  uses: ZoneUseItem[];
  zoneTotal: number;
}

export function parseZoneUses(raw: unknown): ZoneSummary[] {
  if (!raw) return [];
  if (Array.isArray(raw)) {
    const list: ZoneSummary[] = [];
    const flatGrouped = new Map<string, ZoneUseItem[]>();

    for (const item of raw) {
      if (!item || typeof item !== 'object') continue;
      const zoneId = String((item as Record<string, unknown>).zone_id ?? (item as Record<string, unknown>).zone ?? '—');
      const floorProgram = (item as Record<string, unknown>).floor_program_gfa_m2;
      const assignedTotal = typeof (item as Record<string, unknown>).assigned_new_gfa_m2 === 'number'
        ? (item as Record<string, unknown>).assigned_new_gfa_m2 as number
        : undefined;

      if (floorProgram && typeof floorProgram === 'object' && Object.keys(floorProgram).length > 0) {
        const uses: ZoneUseItem[] = Object.entries(floorProgram as Record<string, unknown>).map(([use, gfa]) => ({
          use,
          gfa_m2: Number(gfa) || 0,
        }));
        const sumGfa = uses.reduce((acc, u) => acc + u.gfa_m2, 0);
        list.push({
          zoneId,
          uses,
          zoneTotal: assignedTotal ?? sumGfa,
        });
      } else if ('use' in item && ('gfa_m2' in item || 'gfa' in item)) {
        const use = String((item as Record<string, unknown>).use);
        const gfa = Number((item as Record<string, unknown>).gfa_m2 ?? (item as Record<string, unknown>).gfa) || 0;
        if (!flatGrouped.has(zoneId)) flatGrouped.set(zoneId, []);
        flatGrouped.get(zoneId)!.push({ use, gfa_m2: gfa });
      } else if (assignedTotal !== undefined || (item as Record<string, unknown>).preferred_use) {
        const use = String((item as Record<string, unknown>).preferred_use ?? '—');
        const gfa = assignedTotal ?? 0;
        list.push({
          zoneId,
          uses: [{ use, gfa_m2: gfa }],
          zoneTotal: gfa,
        });
      }
    }

    if (flatGrouped.size > 0) {
      for (const [zoneId, uses] of flatGrouped.entries()) {
        const zoneTotal = uses.reduce((acc, u) => acc + u.gfa_m2, 0);
        list.push({ zoneId, uses, zoneTotal });
      }
    }

    return list;
  }

  if (typeof raw === 'object') {
    return Object.entries(raw as Record<string, unknown>).map(([zoneId, val]) => {
      if (val && typeof val === 'object' && !Array.isArray(val)) {
        const uses = Object.entries(val as Record<string, unknown>).map(([use, gfa]) => ({
          use,
          gfa_m2: Number(gfa) || 0,
        }));
        const zoneTotal = uses.reduce((acc, u) => acc + u.gfa_m2, 0);
        return { zoneId, uses, zoneTotal };
      }
      const gfa = Number(val) || 0;
      return { zoneId, uses: [{ use: '—', gfa_m2: gfa }], zoneTotal: gfa };
    });
  }

  return [];
}

export function formatMetricValue(key: string, val: unknown, zh: boolean): string {
  if (val === null || val === undefined || val === '') return '—';
  if (key === 'far') {
    const num = Number(val);
    return Number.isNaN(num) ? String(val) : num.toFixed(2);
  }
  if (key === 'far_denominator') {
    const s = String(val);
    if (zh) {
      if (s === 'land_area') return '基地面積';
      if (s === 'Exploration Design Area' || s === 'exploration_design_area') return '探索設計面積';
    }
    return s;
  }
  if (key.endsWith('_m2') || key.endsWith('_area')) {
    const num = Number(val);
    return Number.isNaN(num) ? String(val) : `${Math.round(num).toLocaleString()} m²`;
  }
  if (key.endsWith('_ratio') || key.endsWith('_share') || key === 'coverage') {
    const num = Number(val);
    if (Number.isNaN(num)) return String(val);
    const pct = num * 100;
    return `${pct.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 1 })}%`;
  }
  if (key.endsWith('_height_m')) {
    const num = Number(val);
    return Number.isNaN(num) ? String(val) : `${num.toFixed(1)} m`;
  }
  return String(val);
}

export function FormalProperties({ proposal, language }: { proposal: FormalProposal; language?: Language }) {
  const i18n = useI18n();
  const activeLanguage = language ?? i18n.language;
  const zh = activeLanguage === 'zh-TW';
  const fields = [
    ['far', 'FAR', 'FAR'],
    ['far_denominator', 'FAR denominator', 'FAR 分母'],
    ['far_denominator_m2', 'Denominator area (m²)', '分母面積（m²）'],
    ['coverage', 'Coverage ratio', '建蔽率'],
    ['highest_new_height_m', 'Highest new height (m)', '新建最高高度（m）'],
    ['open_space_ratio', 'Open space ratio', '開放空間比例'],
  ];

  const zones = parseZoneUses(proposal.metrics.zone_uses);

  return (
    <section className="formal-properties-panel">
      <dl className="formal-properties-metrics">
        {fields.map(([key, en, tw]) => (
          <div key={key} className="formal-metric-row">
            <dt className="formal-metric-label">{zh ? tw : en}</dt>
            <dd className="formal-metric-value">{formatMetricValue(key, proposal.metrics[key], zh)}</dd>
          </div>
        ))}
      </dl>
      <h3>{zh ? '各區用途與 GFA（m²）' : 'Zone uses and GFA (m²)'}</h3>
      {zones.length === 0 ? (
        <p className="formal-empty-text">{zh ? '無分區用途資料' : 'No zone use data available'}</p>
      ) : (
        <table className="formal-properties-table" aria-label={zh ? '各區用途與 GFA' : 'Zone uses and GFA'}>
          <thead>
            <tr>
              <th>{zh ? '用途' : 'Use'}</th>
              <th className="formal-num-cell">{zh ? 'GFA（m²）' : 'GFA (m²)'}</th>
            </tr>
          </thead>
          <tbody>
            {zones.map((zone) => (
              <Fragment key={zone.zoneId}>
                <tr className="formal-zone-group-row">
                  <th colSpan={2} className="formal-zone-group-header">
                    <span className="formal-zone-tag">{zh ? '分區' : 'Zone'}</span>{' '}
                    <span className="formal-zone-name">{zone.zoneId}</span>
                  </th>
                </tr>
                {zone.uses.map((u, idx) => (
                  <tr key={`${zone.zoneId}-${u.use}-${idx}`} className="formal-use-row">
                    <td className="formal-use-cell">{u.use}</td>
                    <td className="formal-num-cell">{Math.round(u.gfa_m2).toLocaleString()}</td>
                  </tr>
                ))}
                <tr className="formal-zone-total-row">
                  <td className="formal-total-label">
                    {zh ? `${zone.zoneId} 總計` : `${zone.zoneId} Total`}
                  </td>
                  <td className="formal-num-cell formal-total-value">
                    {Math.round(zone.zoneTotal).toLocaleString()}
                  </td>
                </tr>
              </Fragment>
            ))}
          </tbody>
        </table>
      )}
      <p className="formal-disclaimer-text">{zh ? '開放空間為幾何餘量，未證明公共可達性。' : 'Open space is geometric remainder; public accessibility is unverified.'}</p>
      <button disabled className="formal-action-button">{zh ? '決策三：選定／拒絕（由 Founder 操作）' : 'Decision 3: select / reject (Founder action)'}</button>
    </section>
  );
}
