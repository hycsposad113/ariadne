import React, { useEffect, useState, useMemo } from 'react';
import { useI18n } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';
import {
  type ProposalDetail,
  type ProposalDryRun,
  type ProposalRecord,
  formatProposalOperation,
  formatGfa,
  formatMetricDelta,
  humanizeAriadneText,
  humanizeLimitation,
} from '../utils/proposalUtils';
import './ProposalCard.css';

export interface ProposalCardProps {
  record: ProposalRecord;
  apiBase: string;
  projectId: string;
  onProposalUpdate?: (updated: ProposalRecord) => void;
  onHighlightBuildings?: (buildingIds: string[]) => void;
  onSelectJudgement?: (judgementId: string) => void;
}

// Failed / unknown runs have no proposal or dry run; render them without touching those fields.
const EMPTY_PROPOSAL: ProposalDetail = {summary: '', operations: [], rationale: [], expected_effects: [], trade_offs: [], risks: [], not_simulated: [], questions_for_designer: []};
const EMPTY_DRY_RUN: ProposalDryRun = {valid: false, errors: [], gfa_before_m2: 0, gfa_after_m2: 0, gfa_floor_m2: 124842, affected_building_ids: []};

function useCopy() {
  const { language } = useI18n();
  const zh = language === 'zh-TW';
  return {
    language,
    zh,
    say: (cn: string, en: string) => (zh ? cn : en),
  };
}

export const ProposalCard: React.FC<ProposalCardProps> = ({
  record: initialRecord,
  apiBase,
  projectId,
  onProposalUpdate,
  onHighlightBuildings,
  onSelectJudgement,
}) => {
  const { say, zh, language } = useCopy();
  const [record, setRecord] = useState<ProposalRecord>(initialRecord);
  const [confirmModalOpen, setConfirmModalOpen] = useState(false);
  const [approvalNote, setApprovalNote] = useState('');
  const [approving, setApproving] = useState(false);
  const [conflictError, setConflictError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [showAllAffected, setShowAllAffected] = useState(false);

  useEffect(() => {
    setRecord(initialRecord);
  }, [initialRecord]);

  const proposal = record.proposal ?? EMPTY_PROPOSAL;
  const dryRun = record.dry_run ?? EMPTY_DRY_RUN;
  const hasProposal = !!record.proposal && !!record.dry_run;
  const job = record.job;
  const comparison = record.comparison;

  // Poll job status every 15 seconds if RUNNING or PENDING
  const isJobRunning = job?.status === 'RUNNING' || job?.status === 'PENDING';

  useEffect(() => {
    if (!isJobRunning) return;

    const timer = setInterval(async () => {
      try {
        const url = `${apiBase.replace(/\/$/, '')}/api/v1/projects/${encodeURIComponent(
          projectId,
        )}/ariadne/proposals/${encodeURIComponent(record.id)}`;
        const response = await fetch(url);
        if (!response.ok) return;
        const updated = (await response.json()) as ProposalRecord;
        setRecord(updated);
        onProposalUpdate?.(updated);
      } catch {
        // network error, continue polling
      }
    }, 15000);

    return () => clearInterval(timer);
  }, [apiBase, isJobRunning, projectId, record.id, onProposalUpdate]);

  // Timer for elapsed time counter when job is running
  useEffect(() => {
    if (!isJobRunning) return;
    const ticker = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(ticker);
  }, [isJobRunning]);

  const [rerunning, setRerunning] = useState(false);
  const handleRerun = async () => {
    setRerunning(true);
    setConflictError(null);
    try {
      const url = `${apiBase.replace(/\/$/, '')}/api/v1/projects/${encodeURIComponent(projectId)}/ariadne/proposals/${encodeURIComponent(record.id)}/rerun`;
      const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({note: 'designer manual rerun'})});
      if (response.status === 409) {
        setConflictError(say('草稿已有新版本，請重新請 Ariadne 提案', 'Draft revision has changed; please ask Ariadne for a new proposal.'));
        return;
      }
      if (!response.ok) throw new Error(String(response.status));
      const updated = (await response.json()) as ProposalRecord;
      setRecord(updated);
      onProposalUpdate?.(updated);
    } catch {
      setConflictError(say('重新執行失敗，請稍後再試。', 'Could not start the recalculation again. Please retry later.'));
    } finally {
      setRerunning(false);
    }
  };

  const handleApprove = async () => {
    setApproving(true);
    setConflictError(null);
    try {
      const url = `${apiBase.replace(/\/$/, '')}/api/v1/projects/${encodeURIComponent(
        projectId,
      )}/ariadne/proposals/${encodeURIComponent(record.id)}/approve`;
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: approvalNote.trim() || undefined }),
      });

      if (response.status === 409) {
        setConflictError(
          say('草稿已有新版本，請重新請 Ariadne 提案', 'Draft revision has changed; please ask Ariadne for a new proposal.'),
        );
        return;
      }

      if (!response.ok) {
        throw new Error(`Approval failed with status ${response.status}`);
      }

      const updated = (await response.json()) as ProposalRecord;
      setRecord(updated);
      onProposalUpdate?.(updated);
      setConfirmModalOpen(false);
    } catch {
      setConflictError(say('核准失敗，請稍後重試。', 'Approval failed. Please retry.'));
    } finally {
      setApproving(false);
    }
  };

  const handleViewOnMap = () => {
    const ids = dryRun.affected_building_ids ?? [];
    onHighlightBuildings?.(ids);
    if (typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent('ariadne:highlight_buildings', { detail: ids }),
      );
    }
  };

  // Mini SVG map calculation if affected_buildings has footprints
  const miniMap = useMemo(() => {
    const bldgs = dryRun.affected_buildings ?? [];
    const validBldgs = bldgs.filter((b) => b.footprint?.coordinates?.[0]?.length);
    if (!validBldgs.length) return null;

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;

    validBldgs.forEach((b) => {
      b.footprint?.coordinates[0].forEach(([x, y]) => {
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
      });
    });

    const pad = 10;
    const width = Math.max(maxX - minX + pad * 2, 20);
    const height = Math.max(maxY - minY + pad * 2, 20);

    const projectedPolygons = validBldgs.map((b) => {
      const pts = (b.footprint?.coordinates[0] ?? []).map(([x, y]) => {
        const svgX = x - minX + pad;
        const svgY = maxY - y + pad; // flip Y for SVG
        return `${svgX.toFixed(1)},${svgY.toFixed(1)}`;
      });
      return {
        id: b.building_id,
        points: pts.join(' '),
      };
    });

    return {
      viewBox: `0 0 ${width.toFixed(1)} ${height.toFixed(1)}`,
      polygons: projectedPolygons,
    };
  }, [dryRun.affected_buildings]);

  // Date label
  const dateObj = new Date(record.created_at);
  const dateLabel = Number.isNaN(dateObj.getTime())
    ? say('時間未提供', 'Time unavailable')
    : new Intl.DateTimeFormat(zh ? 'zh-TW' : 'en-GB', {
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }).format(dateObj);

  // Job elapsed calculation
  const jobStartTime = job?.started_at ? Date.parse(job.started_at) : job?.created_at ? Date.parse(job.created_at) : 0;
  const elapsedSeconds = jobStartTime > 0 ? Math.max(0, Math.floor((now - jobStartTime) / 1000)) : 0;
  const elapsedMinutes = Math.floor(elapsedSeconds / 60);
  const elapsedRemainderSeconds = elapsedSeconds % 60;
  const elapsedText = zh
    ? `${elapsedMinutes} 分 ${elapsedRemainderSeconds} 秒`
    : `${elapsedMinutes}m ${elapsedRemainderSeconds}s`;

  const canApprove = hasProposal && record.status === 'VALIDATED' && !record.approval && !isJobRunning;
  const showSolarWarning = !!dryRun.solar_access_check?.warning;

  if (!hasProposal) {
    return (
      <article className="proposal-card proposal-card--failed" aria-label={say('Ariadne 修正提案卡', 'Ariadne revision proposal card')}>
        <header className="proposal-card__header">
          <div className="proposal-card__title-group">
            <h3 className="proposal-card__title">{say('Ariadne 修正提案', 'Ariadne Revision Proposal')}</h3>
            <StatusBadge status={record.status === 'APPROVED' ? 'PROPOSAL_APPROVED' : record.status} language={language} />
          </div>
          <small className="proposal-card__time">
            <time dateTime={record.created_at}>{dateLabel}</time>
          </small>
        </header>
        <p className="proposal-card__summary">
          {say('這次提案沒有產生可顯示的內容（未通過驗證或結果未知），不能核准；可以再請 Ariadne 提一次。', 'This run produced no displayable proposal (failed validation or unknown outcome) and cannot be approved. You can ask Ariadne again.')}
        </p>
      </article>
    );
  }

  return (
    <article className="proposal-card" aria-label={say('Ariadne 修正提案卡', 'Ariadne revision proposal card')}>
      <header className="proposal-card__header">
        <div className="proposal-card__title-group">
          <h3 className="proposal-card__title">{say('Ariadne 修正提案', 'Ariadne Revision Proposal')}</h3>
          <StatusBadge status={record.status === 'APPROVED' ? 'PROPOSAL_APPROVED' : record.status} language={language} />
        </div>
        <small className="proposal-card__time">
          <time dateTime={record.created_at}>{dateLabel}</time>
        </small>
      </header>

      {/* Summary */}
      <p className="proposal-card__summary"><span lang={record.language ?? 'zh-TW'}>{humanizeAriadneText(proposal.summary, language)}</span></p>

      {/* Layer 1: Operations */}
      <section className="proposal-card__section">
        <h4>{say('操作清單', 'Operations')}</h4>
        <ul className="proposal-card__ops">
          {proposal.operations.map((op, i) => (
            <li key={i}>{formatProposalOperation(op, language)}</li>
          ))}
        </ul>
      </section>

      {/* Layer 1: GFA Dry Run */}
      <section className="proposal-card__section">
        <h4>{say('總樓地板面積試算', 'Gross Floor Area Calculation')}</h4>
        <div className="proposal-card__gfa-box">
          <div className="proposal-card__gfa-change">
            <span>{say('GFA 變更：', 'GFA change: ')}</span>
            <strong>
              {formatGfa(dryRun.gfa_before_m2, language)} → {formatGfa(dryRun.gfa_after_m2, language)}
            </strong>
          </div>
          <div className="proposal-card__gfa-floor">
            <span>
              {say(
                `85% 下限：${formatGfa(dryRun.gfa_floor_m2, language)}（假設值）`,
                `85% floor: ${formatGfa(dryRun.gfa_floor_m2, language)} (Assumed)`,
              )}
            </span>
            <span>·</span>
            <span style={{ color: dryRun.below_gfa_floor ? '#f87171' : '#34d399' }}>
              {dryRun.below_gfa_floor
                ? say('低於下限', 'Below floor')
                : say('符合下限', 'Meets floor requirement')}
            </span>
          </div>
          {dryRun.limitations?.length ? (
            <small style={{ color: 'var(--text-secondary, #94a3b8)' }}>
              {dryRun.limitations.map(item => humanizeLimitation(item, language)).join(' ')}
            </small>
          ) : null}
        </div>

        {!dryRun.valid && dryRun.errors?.length ? (
          <div className="proposal-card__error-alert" role="alert">
            <strong>{say('乾跑檢查未通過：', 'Dry run check failed: ')}</strong>
            <ul>
              {dryRun.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {/* Affected buildings and Map view */}
        <div className="proposal-card__buildings-bar">
          <span>
            {say('受影響建築：', 'Affected buildings: ')}
            <strong>
              {dryRun.affected_building_ids?.length ? (
                <>
                  {((!showAllAffected && dryRun.affected_building_ids.length > 10)
                    ? dryRun.affected_building_ids.slice(0, 10)
                    : dryRun.affected_building_ids
                  ).join(zh ? '、' : ', ')}
                  {dryRun.affected_building_ids.length > 10 && !showAllAffected && (
                    <button
                      type="button"
                      className="proposal-card__fold-btn"
                      onClick={() => setShowAllAffected(true)}
                    >
                      {say(`另 ${dryRun.affected_building_ids.length - 10} 棟`, `and ${dryRun.affected_building_ids.length - 10} more`)}
                    </button>
                  )}
                  {dryRun.affected_building_ids.length > 10 && showAllAffected && (
                    <button
                      type="button"
                      className="proposal-card__fold-btn"
                      onClick={() => setShowAllAffected(false)}
                    >
                      {say('（收起）', ' (collapse)')}
                    </button>
                  )}
                </>
              ) : (
                zh ? '無' : 'None'
              )}
            </strong>
          </span>
          <button type="button" className="proposal-card__btn-map" onClick={handleViewOnMap}>
            {say('在地圖上看', 'View on map')}
          </button>
        </div>

        {miniMap && (
          <div className="proposal-card__minimap" aria-label={say('受影響建築平面圖', 'Affected buildings footprint map')}>
            <svg viewBox={miniMap.viewBox} width="220" height="120">
              {miniMap.polygons.map((poly) => (
                <polygon
                  key={poly.id}
                  points={poly.points}
                  fill="#f59e0b"
                  stroke="#d97706"
                  strokeWidth="1.5"
                  opacity="0.85"
                >
                  <title>{poly.id}</title>
                </polygon>
              ))}
            </svg>
          </div>
        )}
      </section>

      {/* Layer 1: Massing Strategy Calculation */}
      {dryRun.strategy_report && dryRun.strategy_report.length > 0 && (
        <section className="proposal-card__section proposal-card__strategy-section" data-testid="strategy-report-section">
          <h4>{say('量體策略試算', 'Massing Strategy Calculation')}</h4>
          <div className="proposal-card__strategy-list">
            {dryRun.strategy_report.map((report, idx) => {
              const shortfall = Math.round(report.gfa_shortfall_m2 ?? 0);
              const removedGfa = Math.round(report.removed_gfa_m2 ?? 0);
              const addedGfa = Math.round(report.added_gfa_m2 ?? 0);
              const removedBldgs = report.removed_buildings ?? report.removed ?? [];
              const addedBldgs = report.added_buildings ?? report.added ?? [];
              const unreachable = report.envelope_unreachable_ids ??
                report.envelope_unreachable?.map((u: any) => typeof u === 'string' ? u : u.building_id) ?? [];
              const courtyards = report.solar_access_check?.courtyards ?? [];

              const strategyName = report.op === 'SOLAR_ENVELOPE'
                ? say('日照包絡策略', 'Solar envelope strategy')
                : report.op === 'COURTYARD_WING_DEPTH'
                ? say('中庭翼進深策略', 'Courtyard wing depth strategy')
                : say('量體策略', 'Massing strategy');

              return (
                <div key={idx} className="proposal-card__strategy-item">
                  <div className="proposal-card__strategy-header">
                    <strong>{strategyName}</strong>
                  </div>
                  <div className="proposal-card__strategy-grid">
                    <div>
                      <span>{say('移除樓地板：', 'Removed floor area: ')}</span>
                      <strong>{removedGfa.toLocaleString(zh ? 'zh-TW' : 'en-GB')} {say('平方公尺', 'sq m')}</strong>
                    </div>
                    <div>
                      <span>{say('移入樓地板：', 'Added floor area: ')}</span>
                      <strong>{addedGfa.toLocaleString(zh ? 'zh-TW' : 'en-GB')} {say('平方公尺', 'sq m')}</strong>
                    </div>
                    <div style={shortfall > 0 ? { color: '#f59e0b', fontWeight: 600 } : undefined}>
                      <span>{say('短缺：', 'Shortfall: ')}</span>
                      <strong>{shortfall.toLocaleString(zh ? 'zh-TW' : 'en-GB')} {say('平方公尺', 'sq m')}</strong>
                      {shortfall > 0 && (
                        <span>
                          {' '}
                          {dryRun.below_gfa_floor
                            ? say('（低於 85% 下限）', ' (below 85% floor)')
                            : say('（仍高於 85% 下限）', ' (remains above 85% floor)')}
                        </span>
                      )}
                    </div>
                    <div>
                      <span>{say('包絡結果：', 'Envelope result: ')}</span>
                      {courtyards.length > 0 ? (
                        <span>
                          {courtyards.map((c, cIdx) => (
                            <span key={c.courtyard_id} style={{ marginRight: 8 }}>
                              {c.courtyard_id} {say('陽光可到北緣：', 'sunlight reaches north edge: ')}
                              {c.reaches_north_edge ? say('是', 'Yes') : say('否', 'No')}
                              {cIdx < courtyards.length - 1 ? ' · ' : ''}
                            </span>
                          ))}
                        </span>
                      ) : (
                        <span>{say('無中庭包絡檢核', 'No courtyard envelope check')}</span>
                      )}
                    </div>
                    {unreachable.length > 0 && (
                      <div style={{ color: '#f87171' }}>
                        <span>{say('無法達到門檻建築：', 'Buildings unable to meet threshold: ')}</span>
                        <strong>{unreachable.join(zh ? '、' : ', ')}</strong>
                      </div>
                    )}
                  </div>

                  {/* Expandable details for removed and added buildings */}
                  {(removedBldgs.length > 0 || addedBldgs.length > 0) && (
                    <details className="proposal-card__strategy-details" style={{ marginTop: '8px' }}>
                      <summary>{say('查看棟別變更明細', 'View building change details')}</summary>
                      <div style={{ padding: '8px 0', fontSize: '12px' }}>
                        {removedBldgs.length > 0 && (
                          <div style={{ marginBottom: '6px' }}>
                            <span style={{ fontWeight: 600 }}>{say('移除棟清單：', 'Removed buildings: ')}</span>
                            <span>
                              {removedBldgs.map((b, bIdx) => (
                                <span key={b.building_id}>
                                  {b.building_id}（{say(`減 ${b.floors_removed ?? b.floors ?? 1} 層`, `-${b.floors_removed ?? b.floors ?? 1} floors`)}）
                                  {bIdx < removedBldgs.length - 1 ? (zh ? '、' : ', ') : ''}
                                </span>
                              ))}
                            </span>
                          </div>
                        )}
                        {addedBldgs.length > 0 && (
                          <div>
                            <span style={{ fontWeight: 600 }}>{say('移入棟清單：', 'Added buildings: ')}</span>
                            <span>
                              {addedBldgs.map((b, bIdx) => (
                                <span key={b.building_id}>
                                  {b.building_id}（
                                  {say(`加 ${b.floors_added ?? b.floors ?? 1} 層`, `+${b.floors_added ?? b.floors ?? 1} floors`)}
                                  {b.is_north_of_courtyard
                                    ? say('，在中庭北側', ', north of courtyard')
                                    : say('，非中庭北側', ', not north of courtyard')}
                                  ）
                                  {bIdx < addedBldgs.length - 1 ? (zh ? '、' : ', ') : ''}
                                </span>
                              ))}
                            </span>
                          </div>
                        )}
                      </div>
                    </details>
                  )}
                </div>
              );
            })}
          </div>

          {/* Trade-off reminders */}
          {dryRun.strategy_trade_off_check && (
            <aside className="proposal-card__trade-off-alert" role="note" style={{ marginTop: '10px' }}>
              <strong>{say('取捨提醒：', 'Trade-off notes: ')}</strong>
              <ul style={{ margin: '4px 0 0 0', paddingLeft: '18px', fontSize: '12px' }}>
                {dryRun.strategy_trade_off_check.north_street_shadow_addressed !== undefined && (
                  <li>
                    {say(
                      '移入棟北側為街道時，北側街道冬季日照可能下降。',
                      'Winter sunlight on northern streets may decrease if added buildings face a street to the north.'
                    )}
                  </li>
                )}
                {dryRun.strategy_trade_off_check.gfa_floor_relationship_addressed !== undefined && (
                  <li>
                    {say(
                      '樓地板短缺與 85% GFA 下限之取捨關係已納入考量。',
                      'Trade-off between floor area shortfall and the 85% GFA floor has been addressed.'
                    )}
                  </li>
                )}
              </ul>
            </aside>
          )}
        </section>
      )}

      {/* Layer 2: Expandable Details */}
      <details className="proposal-card__details">
        <summary>{say('看設計推理與取捨', 'View reasoning and trade-offs')}</summary>
        <div className="proposal-card__details-content">
          {proposal.rationale?.length ? (
            <section>
              <h5>{say('為什麼（理由依據）', 'Rationale')}</h5>
              <ul>
                {proposal.rationale.map((r, i) => (
                  <li key={i}><span lang={record.language ?? 'zh-TW'}>{humanizeAriadneText(r, language)}</span></li>
                ))}
              </ul>
            </section>
          ) : null}

          {proposal.expected_effects?.length ? (
            <section>
              <h5>{say('預期方向（未經模擬）', 'Expected effects (not simulated)')}</h5>
              <ul>
                {proposal.expected_effects.map((e, i) => (
                  <li key={i}><span lang={record.language ?? 'zh-TW'}>{humanizeAriadneText(e, language)}</span></li>
                ))}
              </ul>
            </section>
          ) : null}

          {proposal.trade_offs?.length ? (
            <section>
              <h5>{say('取捨', 'Trade-offs')}</h5>
              <ul>
                {proposal.trade_offs.map((t, i) => (
                  <li key={i}><span lang={record.language ?? 'zh-TW'}>{humanizeAriadneText(t, language)}</span></li>
                ))}
              </ul>
            </section>
          ) : null}

          {proposal.risks?.length ? (
            <section>
              <h5>{say('風險', 'Risks')}</h5>
              <ul>
                {proposal.risks.map((rk, i) => (
                  <li key={i}><span lang={record.language ?? 'zh-TW'}>{humanizeAriadneText(rk, language)}</span></li>
                ))}
              </ul>
            </section>
          ) : null}

          {proposal.not_simulated?.length ? (
            <section className="proposal-card__not-simulated">
              <h5>{say('未模擬項目', 'Not simulated items')}</h5>
              <ul>
                {proposal.not_simulated.map((ns, i) => (
                  <li key={i}><span lang={record.language ?? 'zh-TW'}>{humanizeAriadneText(ns, language)}</span></li>
                ))}
              </ul>
            </section>
          ) : null}

          {proposal.questions_for_designer?.length ? (
            <section>
              <h5>{say('給設計者的問題', 'Questions for designer')}</h5>
              <ul>
                {proposal.questions_for_designer.map((q, i) => (
                  <li key={i}><span lang={record.language ?? 'zh-TW'}>{humanizeAriadneText(q, language)}</span></li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </details>

      {/* Solar access check warning (Yellow box, does NOT block approve) */}
      {showSolarWarning && (
        <aside className="proposal-card__solar-warning" role="note">
          {(() => {
            const pockets = (dryRun.solar_access_check?.courtyards ?? []).flatMap(court => court.local_sun_pockets ?? []);
            if (dryRun.solar_access_check?.local_only && pockets.length) {
              const names = pockets.map(p => p.building_id).join(zh ? '、' : ', ');
              const width = pockets.reduce((sum, p) => sum + (p.frontage_m ?? 0), 0);
              const widthText = width > 0 ? (zh ? `約 ${Math.round(width)} 公尺寬的` : `an approx. ${Math.round(width)} m wide `) : '';
              return say(
                `依冬至正午太陽高度（約 14.7°）幾何判斷，這個修改只會在 ${names} 後方形成${widthText}局部日照帶（可作冬季停留邊）；中庭其餘南側量體仍會遮蔭，中庭整體冬至日照預期改善有限。仍可核准重算以驗證。`,
                `Based on winter-noon solar geometry (approx. 14.7°), this change only creates ${widthText}local sun pocket behind ${names} (usable as a winter sitting edge); the rest of the southern massing still shades the courtyard, so courtyard-wide winter sunlight should improve only slightly. You may still approve recalculation for verification.`,
              );
            }
            return say(
              '依冬至正午太陽高度（約 14.7°）幾何判斷，修改後南側量體仍會遮住中庭，冬至日照預期不會明顯改善。仍可核准重算以驗證。',
              'Based on solar geometry at winter noon (approx. 14.7°), the adjusted southern massing will still shade the courtyard; winter sunlight is not expected to improve significantly. You may still approve recalculation for verification.',
            );
          })()}
        </aside>
      )}

      {/* Conflict error */}
      {conflictError && (
        <div className="proposal-card__error-alert" role="alert">
          {conflictError}
        </div>
      )}

      {/* Actions / Approve Button */}
      <div className="proposal-card__actions">
        {canApprove && (
          <button
            type="button"
            className="proposal-card__btn-approve"
            disabled={!dryRun.valid || approving}
            onClick={() => {
              setConflictError(null);
              setConfirmModalOpen(true);
            }}
          >
            {say('核准重算', 'Approve recalculation')}
          </button>
        )}
      </div>

      {/* Approval Confirmation Dialog */}
      {confirmModalOpen && (
        <div className="proposal-card__modal-overlay" role="dialog" aria-modal="true" aria-labelledby="confirm-approve-title">
          <div className="proposal-card__modal">
            <h3 id="confirm-approve-title">{say('核准重算確認', 'Confirm Approval for Recalculation')}</h3>
            <p className="proposal-card__modal-explainer">
              {say(
                '套用到正式草稿新版本並重算 E1（約 10 分鐘）與 UTCI；這不是正式接受方案，正式接受仍需決策密語',
                'Apply to new revision of formal draft and recalculate E1 (approx. 10 min) and UTCI. This is not formal acceptance of the proposal; formal acceptance still requires a decision passphrase.',
              )}
            </p>
            <label>
              {say('核准備註（選填）：', 'Approval note (optional):')}
              <textarea
                value={approvalNote}
                onChange={(e) => setApprovalNote(e.target.value)}
                placeholder={say('請填寫備註…', 'Enter note…')}
              />
            </label>
            <div className="proposal-card__modal-buttons">
              <button
                type="button"
                className="proposal-card__btn-map"
                disabled={approving}
                onClick={() => setConfirmModalOpen(false)}
              >
                {say('取消', 'Cancel')}
              </button>
              <button
                type="button"
                className="proposal-card__btn-approve"
                disabled={approving}
                onClick={() => void handleApprove()}
              >
                {approving ? say('處理中…', 'Processing…') : say('確認核准重算', 'Confirm approval')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Recalculation Job Progress */}
      {job && (
        <section className="proposal-card__job-box" aria-label={say('重算進度', 'Recalculation progress')}>
          <div className="proposal-card__job-header">
            <h4>{say('重算任務狀態', 'Recalculation Job Status')}</h4>
            <StatusBadge status={job.status} language={language} />
          </div>

          {isJobRunning && (
            <div className="proposal-card__job-running">
              <span>{say('重算進行中（約 10 分鐘）…', 'Recalculation in progress (approx. 10 min)…')}</span>
              <span>·</span>
              <span>
                {say('已用時間：', 'Elapsed: ')}
                <strong>{elapsedText}</strong>
              </span>
            </div>
          )}

          {job.status === 'FAILED' && (
            <div className="proposal-card__job-failed" role="alert">
              <strong>{say('重算失敗，系統不會自動重試；草稿維持已套用的版本。', 'Recalculation failed and will not retry automatically; the draft keeps the applied revision.')}</strong>
              {job.errors?.length ? (
                <details>
                  <summary>{say('技術細節', 'Technical details')}</summary>
                  <ul>
                    {job.errors.map((err, i) => (
                      <li key={i}><code>{err}</code></li>
                    ))}
                  </ul>
                </details>
              ) : null}
              <button type="button" className="proposal-card__btn" disabled={rerunning} onClick={() => void handleRerun()}>
                {rerunning ? say('送出中…', 'Sending…') : say('重新執行重算', 'Run the recalculation again')}
              </button>
            </div>
          )}
        </section>
      )}

      {/* Comparison Table (前後對照表) */}
      {comparison && (
        <section className="proposal-card__comparison-wrap" aria-label={say('重算前後對照表', 'Before and after recalculation comparison')}>
          <h4>{say('前後指標對照', 'Before and After Metric Comparison')}</h4>
          <table className="proposal-card__comparison-table">
            <thead>
              <tr>
                <th>{say('指標項目', 'Metric')}</th>
                <th>{say('重算前', 'Before')}</th>
                <th>{say('重算後', 'After')}</th>
                <th>{say('差值', 'Delta')}</th>
              </tr>
            </thead>
            <tbody>
              {/* 1. Courtyard winter mean */}
              {renderComparisonRow(
                say('中庭冬至平均日照', 'Block courtyard winter mean sunlight'),
                comparison.courtyard_winter_mean_h,
                'h',
                'courtyard_winter_mean_h',
                language,
              )}

              {/* 2. All winter mean */}
              {renderComparisonRow(
                say('全體冬至平均日照', 'All open space winter mean sunlight'),
                comparison.all_winter_mean_h,
                'h',
                'all_winter_mean_h',
                language,
              )}

              {/* 3. All winter >= 2h pct */}
              {renderComparisonRow(
                say('全體冬至 ≥2 小時比例', 'All open space winter >= 2h pct'),
                comparison.all_winter_ge2h_pct,
                '%',
                'all_winter_ge2h_pct',
                language,
              )}

              {/* 4. Street winter mean */}
              {renderComparisonRow(
                say('街道冬至平均日照', 'Street winter mean sunlight'),
                comparison.street_winter_mean_h,
                'h',
                'street_winter_mean_h',
                language,
              )}

              {/* 5. UTCI very strong stress pct */}
              {renderComparisonRow(
                say('UTCI 非常強烈熱壓力比例', 'UTCI very strong heat stress pct'),
                comparison.utci_very_strong_pct,
                '%',
                'utci_very_strong_pct',
                language,
              )}

              {/* 6. GFA */}
              {comparison.gfa_m2 && (
                <tr>
                  <td>{say('總樓地板面積 (GFA)', 'Gross Floor Area (GFA)')}</td>
                  <td>{formatGfa(comparison.gfa_m2.before, language)}</td>
                  <td>{formatGfa(comparison.gfa_m2.after, language)}</td>
                  <td>
                    {formatGfa(
                      comparison.gfa_m2.after - comparison.gfa_m2.before,
                      language,
                    )}
                  </td>
                </tr>
              )}

              {/* 7. Affected buildings count */}
              {comparison.affected_building_count !== undefined && (
                <tr>
                  <td>{say('受影響建築棟數', 'Affected building count')}</td>
                  <td>—</td>
                  <td>
                    {comparison.affected_building_count} {zh ? '棟' : 'buildings'}
                  </td>
                  <td>—</td>
                </tr>
              )}
            </tbody>
          </table>

          {/* Link to post judgement */}
          {record.post_judgement_id && (
            <button
              type="button"
              className="proposal-card__post-judgement-btn"
              onClick={() => onSelectJudgement?.(record.post_judgement_id!)}
            >
              {say('看重算後的新判讀', 'View recalculation judgement')}
            </button>
          )}
        </section>
      )}
    </article>
  );
};

function renderComparisonRow(
  label: string,
  metric: { before: number | null; after: number | null; delta?: number | null; unit: string; status: string } | undefined,
  unit: string,
  metricKey: string,
  language: 'zh-TW' | 'en',
) {
  const zh = language === 'zh-TW';
  if (!metric) return null;

  if (metric.status === 'DATA_GAP') {
    return (
      <tr key={metricKey}>
        <td>{label}</td>
        <td>{metric.before !== null ? `${metric.before} ${unit === 'h' ? (zh ? '小時' : 'h') : unit}` : '—'}</td>
        <td style={{ color: '#f59e0b' }}>{zh ? '資料缺口' : 'Data gap'}</td>
        <td>—</td>
      </tr>
    );
  }

  const digits = unit === 'h' ? 3 : unit === '%' ? 2 : 1;
  const beforeFormatted =
    metric.before !== null
      ? `${new Intl.NumberFormat(zh ? 'zh-TW' : 'en-GB', {
          minimumFractionDigits: unit === 'h' ? 3 : 0,
          maximumFractionDigits: digits,
        }).format(metric.before)} ${unit === 'h' ? (zh ? '小時' : 'h') : unit}`
      : '—';

  const afterFormatted =
    metric.after !== null
      ? `${new Intl.NumberFormat(zh ? 'zh-TW' : 'en-GB', {
          minimumFractionDigits: unit === 'h' ? 3 : 0,
          maximumFractionDigits: digits,
        }).format(metric.after)} ${unit === 'h' ? (zh ? '小時' : 'h') : unit}`
      : '—';

  const deltaInfo = formatMetricDelta(metric.delta, unit, metricKey, language);

  const deltaClass =
    deltaInfo.evaluation === 'improvement'
      ? 'proposal-card__delta--improvement'
      : deltaInfo.evaluation === 'worsened'
      ? 'proposal-card__delta--worsened'
      : 'proposal-card__delta--neutral';

  return (
    <tr key={metricKey}>
      <td>{label}</td>
      <td>{beforeFormatted}</td>
      <td>{afterFormatted}</td>
      <td className={deltaClass}>{deltaInfo.text}</td>
    </tr>
  );
}

export default ProposalCard;
