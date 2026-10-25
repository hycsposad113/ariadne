import { JudgementPanel } from './JudgementCard';
import React, { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import './ClimateExtrasPanel.css';

export interface TableColumn {
  key: string;
  title_zh: string;
  title_en: string;
}

export interface TableData {
  columns: TableColumn[];
  rows: Record<string, any>[];
}

export interface FigureItem {
  path: string;
  path_en?: string;
  title_zh: string;
  title_en: string;
  caption_zh?: string;
  caption_en?: string;
  tag?: string;
  fabric?: string;
  season?: string;
}

export interface ClimateSection {
  id: string;
  title_zh: string;
  title_en: string;
  label_zh: string;
  label_en: string;
  status: 'OK' | 'MISSING' | string;
  missing_files: string[];
  figures: FigureItem[];
  table: TableData | null;
  limitations_zh: string;
  limitations_en: string;
  source_sha256: Record<string, string>;
}

export interface ClimateExtrasPanelProps {
  apiBase: string;
  projectId?: string;
  className?: string;
  initialCollapsed?: boolean;
}

export const ClimateExtrasPanel: React.FC<ClimateExtrasPanelProps> = ({
  apiBase,
  projectId = 'rotterdam-m4h-pilot-project',
  className = '',
  initialCollapsed = false,
}) => {
  const { language } = useI18n();
  const isZh = language === 'zh-TW';

  const [judgementScope, setJudgementScope] = useState('harbour_grain');
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [sections, setSections] = useState<ClimateSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // E1 active date switcher
  const [e1Date, setE1Date] = useState('2026-12-21');
  // UTCI active fabric switcher
  const [utciFabric, setUtciFabric] = useState('harbour_grain');
  // E5 active figure switcher
  const [e5FigIndex, setE5FigIndex] = useState(0);

  // Modal image state
  const [modalImage, setModalImage] = useState<{ src: string; title: string; caption?: string } | null>(null);

  useEffect(() => {
    let ignore = false;
    const fetchExtras = async () => {
      setLoading(true);
      setError(null);
      try {
        const resp = await fetch(`${apiBase}/api/v1/environment/climate-extras`);
        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }
        const data = await resp.json();
        if (!ignore) {
          setSections(Array.isArray(data) ? data : data.sections || []);
        }
      } catch (err: any) {
        if (!ignore) {
          setError(err?.message || 'Failed to fetch climate extras');
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    };

    fetchExtras();
    return () => {
      ignore = true;
    };
  }, [apiBase]);

  const getFileUrl = (relPath: string) => {
    return encodeURI(`${apiBase}/api/v1/environment/climate-extras/files/${relPath}`);
  };

  const getFigureUrl = (figure: FigureItem) => getFileUrl(!isZh && figure.path_en ? figure.path_en : figure.path);

  const renderCellContent = (colKey: string, row: Record<string, any>) => {
    const val = row[colKey];
    if (colKey === '紋理方案名稱' || colKey === 'scheme_name') {
      const name = isZh ? (row['紋理方案名稱'] || row['scheme_name'] || val) : (row['fabric_name_en'] || row['scheme_name_en'] || val);
      return (
        <span>
          {name}
          {row['is_selected'] && (
            <span className="climate-extras-panel__badge--selected">
              {isZh ? '選定' : 'Selected'}
            </span>
          )}
        </span>
      );
    }
    if (colKey === '開放空間類別' || colKey === 'category_name') {
      return isZh ? (row['開放空間類別'] || row['category_name'] || val) : (row['space_category_en'] || row['category_name_en'] || val);
    }
    if (colKey === 'metric_zh') {
      return isZh ? row['metric_zh'] : (row['metric_en'] || row['metric_zh']);
    }
    if (colKey === 'convergence') {
      return isZh ? row['convergence'] : (row['convergence_en'] || row['convergence']);
    }
    if (colKey === 'scope') {
      if (!isZh && typeof val === 'string') {
        return val.replace('全量', 'Full').replace('棟', ' bldgs');
      }
      return val;
    }
    return val !== undefined && val !== null ? String(val) : '';
  };

  return (
    <section
      className={`climate-extras-panel ${className}`}
      data-testid="climate-extras-panel"
      aria-label={isZh ? '附加氣候模擬（探索性）' : 'Additional Climate Simulations (Exploratory)'}
    >
      <div className="climate-extras-panel__header">
        <button
          type="button"
          className="climate-extras-panel__toggle"
          onClick={() => setCollapsed(!collapsed)}
          aria-expanded={!collapsed}
          data-testid="climate-extras-toggle"
        >
          <span className="climate-extras-panel__badge climate-extras-panel__badge--exploratory">
            {isZh ? '探索性，非認證' : 'Exploratory, not certification'}
          </span>
          <div className="climate-extras-panel__title-group">
            <h3 className="climate-extras-panel__title">
              {isZh ? '附加氣候模擬（探索性）' : 'Additional Climate Simulations (Exploratory)'}
            </h3>
            <p className="climate-extras-panel__subtitle">
              {isZh
                ? '既有離線模擬結果唯讀檢視（非認證、不寫入正式資料庫）'
                : 'Read-only viewer for offline simulation results (non-statutory, no database writes)'}
            </p>
          </div>
          <span className="climate-extras-panel__collapse-icon">{collapsed ? '▼' : '▲'}</span>
        </button>
      </div>

      {!collapsed && (
        <div className="climate-extras-panel__body">
          <label>{isZh ? '判讀範圍' : 'Judgement scope'}<select aria-label={isZh ? '判讀範圍' : 'Judgement scope'} value={judgementScope} onChange={event => setJudgementScope(event.target.value)}>
            <option value="all">{isZh ? '四案對照' : 'All four schemes'}</option>
            {['harbour_grain', 'closed_block_extension', 'courtyard_islands', 'landscape_figure'].map((id, i) => <option key={id} value={id}>{(isZh ? ['港埠紋理', '圍合街廓延伸', '院落島', '地景構形'] : ['Harbour grain', 'Closed-block extension', 'Courtyard islands', 'Landscape as figure'])[i]}</option>)}
          </select></label>
          <JudgementPanel key={judgementScope} apiBase={apiBase} projectId={projectId} skillId="J-CLIMATE" subjectIds={judgementScope === 'all' ? ['harbour_grain', 'closed_block_extension', 'courtyard_islands', 'landscape_figure'] : [judgementScope]} />
          {loading && (
            <p role="status">{isZh ? '載入附加氣候模擬資料中…' : 'Loading climate simulation data…'}</p>
          )}

          {error && (
            <div className="climate-extras-panel__missing-banner" role="alert">
              {isZh ? `無法載入附加氣候模擬：${error}` : `Failed to load climate extras: ${error}`}
            </div>
          )}

          {!loading && !error && sections.map((sec) => {
            const isMissing = sec.status === 'MISSING';

            return (
              <div
                key={sec.id}
                className="climate-extras-panel__section"
                data-testid={`climate-section-${sec.id}`}
              >
                <div className="climate-extras-panel__section-header">
                  <h4 className="climate-extras-panel__section-title">
                    {isZh ? sec.title_zh : sec.title_en}
                    {sec.id === 'e1-fabric' && (
                      <span className="climate-extras-panel__badge--selected">
                        {isZh ? '四案對比' : '4-Fabric Compare'}
                      </span>
                    )}
                  </h4>
                  <span
                    className={`climate-extras-panel__badge ${
                      isMissing
                        ? 'climate-extras-panel__badge--missing'
                        : 'climate-extras-panel__badge--exploratory'
                    }`}
                  >
                    {isMissing ? 'MISSING' : (isZh ? sec.label_zh : sec.label_en)}
                  </span>
                </div>

                {isMissing ? (
                  <div className="climate-extras-panel__missing-banner" role="status">
                    <p>
                      {isZh
                        ? '資料缺失 · 未取得此節離線產物'
                        : 'MISSING DATA · Offline simulation artifacts not available'}
                    </p>
                    {sec.missing_files && sec.missing_files.length > 0 && (
                      <div>
                        <strong>{isZh ? '缺少來源檔案：' : 'Missing source files:'}</strong>
                        <ul>
                          {sec.missing_files.map((f, i) => (
                            <li key={i}><code>{f}</code></li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ) : (
                  <>
                    {/* E1 Sunlight section controls & figure */}
                    {sec.id === 'e1-fabric' && (
                      <>
                        <div className="climate-extras-panel__controls">
                          <span className="climate-extras-panel__control-label">
                            {isZh ? '分析日期：' : 'Analysis Date:'}
                          </span>
                          <button
                            type="button"
                            className={`climate-extras-panel__tab-btn ${e1Date === '2026-12-21' ? 'climate-extras-panel__tab-btn--active' : ''}`}
                            onClick={() => setE1Date('2026-12-21')}
                          >
                            {isZh ? '冬至 (2026-12-21)' : 'Winter Solstice (2026-12-21)'}
                          </button>
                          <button
                            type="button"
                            className={`climate-extras-panel__tab-btn ${e1Date === '2026-03-21' ? 'climate-extras-panel__tab-btn--active' : ''}`}
                            onClick={() => setE1Date('2026-03-21')}
                          >
                            {isZh ? '春分 (2026-03-21)' : 'Spring Equinox (2026-03-21)'}
                          </button>
                          <button
                            type="button"
                            className={`climate-extras-panel__tab-btn ${e1Date === '2026-06-21' ? 'climate-extras-panel__tab-btn--active' : ''}`}
                            onClick={() => setE1Date('2026-06-21')}
                          >
                            {isZh ? '夏至 (2026-06-21)' : 'Summer Solstice (2026-06-21)'}
                          </button>
                        </div>

                        {(() => {
                          const activeFig = sec.figures.find(f => f.tag === e1Date) || sec.figures[0];
                          if (!activeFig) return null;
                          return (
                            <div className="climate-extras-panel__figure-container">
                              <div
                                className="climate-extras-panel__figure-img-wrap"
                                onClick={() => setModalImage({
                                  src: getFigureUrl(activeFig),
                                  title: isZh ? activeFig.title_zh : activeFig.title_en,
                                  caption: isZh ? activeFig.caption_zh : activeFig.caption_en,
                                })}
                                title={isZh ? '點擊可放大' : 'Click to enlarge'}
                              >
                                <img
                                  className="climate-extras-panel__figure-img"
                                  src={getFigureUrl(activeFig)}
                                  alt={isZh ? activeFig.title_zh : activeFig.title_en}
                                />
                                <span className="climate-extras-panel__zoom-hint">
                                  🔍 {isZh ? '點擊可放大' : 'Click to enlarge'}
                                </span>
                              </div>
                              <p className="climate-extras-panel__figure-caption">
                                {isZh ? (activeFig.caption_zh || activeFig.title_zh) : (activeFig.caption_en || activeFig.title_en)}
                              </p>
                            </div>
                          );
                        })()}
                      </>
                    )}

                    {/* UTCI section controls & figure */}
                    {sec.id === 'utci' && (
                      <>
                        <div className="climate-extras-panel__controls">
                          <span className="climate-extras-panel__control-label">
                            {isZh ? '紋理方案：' : 'Fabric Scheme:'}
                          </span>
                          <button
                            type="button"
                            className={`climate-extras-panel__tab-btn ${utciFabric === 'harbour_grain' ? 'climate-extras-panel__tab-btn--active' : ''}`}
                            onClick={() => setUtciFabric('harbour_grain')}
                          >
                            {isZh ? '港埠線性紋理（選定）' : 'Harbour grain (Selected)'}
                          </button>
                          <button
                            type="button"
                            className={`climate-extras-panel__tab-btn ${utciFabric === 'closed_block_extension' ? 'climate-extras-panel__tab-btn--active' : ''}`}
                            onClick={() => setUtciFabric('closed_block_extension')}
                          >
                            {isZh ? '圍合街廓延伸' : 'Closed-block extension'}
                          </button>
                          <button
                            type="button"
                            className={`climate-extras-panel__tab-btn ${utciFabric === 'courtyard_islands' ? 'climate-extras-panel__tab-btn--active' : ''}`}
                            onClick={() => setUtciFabric('courtyard_islands')}
                          >
                            {isZh ? '大型院落島' : 'Courtyard islands'}
                          </button>
                          <button
                            type="button"
                            className={`climate-extras-panel__tab-btn ${utciFabric === 'landscape_figure' ? 'climate-extras-panel__tab-btn--active' : ''}`}
                            onClick={() => setUtciFabric('landscape_figure')}
                          >
                            {isZh ? '地景為圖' : 'Landscape as figure'}
                          </button>
                        </div>

                        {(() => {
                          const activeFig = sec.figures.find(f => f.fabric === utciFabric) || sec.figures[0];
                          if (!activeFig) return null;
                          return (
                            <div className="climate-extras-panel__figure-container">
                              <div
                                className="climate-extras-panel__figure-img-wrap"
                                onClick={() => setModalImage({
                                  src: getFigureUrl(activeFig),
                                  title: isZh ? activeFig.title_zh : activeFig.title_en,
                                  caption: isZh ? activeFig.caption_zh : activeFig.caption_en,
                                })}
                                title={isZh ? '點擊可放大' : 'Click to enlarge'}
                              >
                                <img
                                  className="climate-extras-panel__figure-img"
                                  src={getFigureUrl(activeFig)}
                                  alt={isZh ? activeFig.title_zh : activeFig.title_en}
                                />
                                <span className="climate-extras-panel__zoom-hint">
                                  🔍 {isZh ? '點擊可放大' : 'Click to enlarge'}
                                </span>
                              </div>
                              <p className="climate-extras-panel__figure-caption">
                                {isZh ? (activeFig.caption_zh || activeFig.title_zh) : (activeFig.caption_en || activeFig.title_en)}
                              </p>
                            </div>
                          );
                        })()}
                      </>
                    )}

                    {/* E3 Energy section figure */}
                    {sec.id === 'e3-energy' && sec.figures.length > 0 && (
                      <div className="climate-extras-panel__figure-container">
                        <div
                          className="climate-extras-panel__figure-img-wrap"
                          onClick={() => setModalImage({
                            src: getFigureUrl(sec.figures[0]),
                            title: isZh ? sec.figures[0].title_zh : sec.figures[0].title_en,
                            caption: isZh ? sec.figures[0].caption_zh : sec.figures[0].caption_en,
                          })}
                          title={isZh ? '點擊可放大' : 'Click to enlarge'}
                        >
                          <img
                            className="climate-extras-panel__figure-img"
                            src={getFigureUrl(sec.figures[0])}
                            alt={isZh ? sec.figures[0].title_zh : sec.figures[0].title_en}
                          />
                          <span className="climate-extras-panel__zoom-hint">
                            🔍 {isZh ? '點擊可放大' : 'Click to enlarge'}
                          </span>
                        </div>
                        <p className="climate-extras-panel__figure-caption">
                          {isZh ? (sec.figures[0].caption_zh || sec.figures[0].title_zh) : (sec.figures[0].caption_en || sec.figures[0].title_en)}
                        </p>
                      </div>
                    )}

                    {/* E4 Thermal Mass section figure */}
                    {sec.id === 'e4-thermal-mass' && sec.figures.length > 0 && (
                      <div className="climate-extras-panel__figure-container">
                        <div
                          className="climate-extras-panel__figure-img-wrap"
                          onClick={() => setModalImage({
                            src: getFigureUrl(sec.figures[0]),
                            title: isZh ? sec.figures[0].title_zh : sec.figures[0].title_en,
                            caption: isZh ? sec.figures[0].caption_zh : sec.figures[0].caption_en,
                          })}
                          title={isZh ? '點擊可放大' : 'Click to enlarge'}
                        >
                          <img
                            className="climate-extras-panel__figure-img"
                            src={getFigureUrl(sec.figures[0])}
                            alt={isZh ? sec.figures[0].title_zh : sec.figures[0].title_en}
                          />
                          <span className="climate-extras-panel__zoom-hint">
                            🔍 {isZh ? '點擊可放大' : 'Click to enlarge'}
                          </span>
                        </div>
                        <p className="climate-extras-panel__figure-caption">
                          {isZh ? (sec.figures[0].caption_zh || sec.figures[0].title_zh) : (sec.figures[0].caption_en || sec.figures[0].title_en)}
                        </p>
                      </div>
                    )}

                    {/* E5 Pedestrian Wind section figure & controls */}
                    {sec.id === 'e5-cfd' && sec.figures.length > 0 && (
                      <>
                        <div className="climate-extras-panel__controls">
                          <span className="climate-extras-panel__control-label">
                            {isZh ? '風向／視角：' : 'Wind Direction / View:'}
                          </span>
                          {sec.figures.map((fig, idx) => (
                            <button
                              key={fig.path}
                              type="button"
                              className={`climate-extras-panel__tab-btn ${e5FigIndex === idx ? 'climate-extras-panel__tab-btn--active' : ''}`}
                              onClick={() => setE5FigIndex(idx)}
                            >
                              {isZh ? fig.title_zh : fig.title_en}
                            </button>
                          ))}
                        </div>

                        {(() => {
                          const activeFig = sec.figures[e5FigIndex] || sec.figures[0];
                          return (
                            <div className="climate-extras-panel__figure-container">
                              <div
                                className="climate-extras-panel__figure-img-wrap"
                                onClick={() => setModalImage({
                                  src: getFigureUrl(activeFig),
                                  title: isZh ? activeFig.title_zh : activeFig.title_en,
                                  caption: isZh ? activeFig.caption_zh : activeFig.caption_en,
                                })}
                                title={isZh ? '點擊可放大' : 'Click to enlarge'}
                              >
                                <img
                                  className="climate-extras-panel__figure-img"
                                  src={getFigureUrl(activeFig)}
                                  alt={isZh ? activeFig.title_zh : activeFig.title_en}
                                />
                                <span className="climate-extras-panel__zoom-hint">
                                  🔍 {isZh ? '點擊可放大' : 'Click to enlarge'}
                                </span>
                              </div>
                              <p className="climate-extras-panel__figure-caption">
                                {isZh ? (activeFig.caption_zh || activeFig.title_zh) : (activeFig.caption_en || activeFig.title_en)}
                              </p>
                            </div>
                          );
                        })()}
                      </>
                    )}

                    {/* Section Data Table */}
                    {sec.table && sec.table.columns && sec.table.rows && (
                      <div className="climate-extras-panel__table-container">
                        <table className="climate-extras-panel__table">
                          <thead>
                            <tr>
                              {sec.table.columns.map((col) => (
                                <th key={col.key}>
                                  {isZh ? col.title_zh : col.title_en}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {sec.table.rows.map((row, rIdx) => {
                              const isRowSelected = Boolean(row['is_selected']);
                              return (
                                <tr
                                  key={rIdx}
                                  className={isRowSelected ? 'selected-row' : ''}
                                >
                                  {sec.table!.columns.map((col) => (
                                    <td key={col.key}>
                                      {renderCellContent(col.key, row)}
                                    </td>
                                  ))}
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Section Limitations */}
                    <div className="climate-extras-panel__limitations">
                      <h5 className="climate-extras-panel__limitations-title">
                        {isZh ? '限制說明' : 'Limitations'}
                      </h5>
                      <p className="climate-extras-panel__limitations-text">
                        {isZh ? sec.limitations_zh : sec.limitations_en}
                      </p>
                    </div>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Lightbox Modal */}
      {modalImage && (
        <div
          className="climate-extras-modal"
          onClick={() => setModalImage(null)}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="climate-extras-modal__content"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              className="climate-extras-modal__close-btn"
              onClick={() => setModalImage(null)}
              aria-label={isZh ? '關閉' : 'Close'}
            >
              ✕
            </button>
            <img
              className="climate-extras-modal__img"
              src={modalImage.src}
              alt={modalImage.title}
            />
            <div className="climate-extras-modal__footer">
              <h4 className="climate-extras-modal__title">{modalImage.title}</h4>
              {modalImage.caption && (
                <p className="climate-extras-modal__caption">{modalImage.caption}</p>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
};
