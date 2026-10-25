import { useT } from '../i18n';
import type { ReactNode } from 'react';
import { useEffect, useMemo, useState } from 'react';
import './MorphologyPreviewCatalog.css';

type Intensity = 'A' | 'B';
type PreviewIdentity = {
  intensity: Intensity;
  strategy_id: string;
  status: 'UNAPPROVED_PREVIEW';
  human_decision_created: false;
  generator_version: string;
  run_created_at: string | null;
  generator_commit: string | null;
};
type PreviewLimits = {
  intensity: Intensity;
  far_upper_bound_land: number;
  coverage_upper_bound: number | null;
  height_upper_bound_new_buildings_m: number;
};
export type PreviewItem = {
  verified_at_utc: string;
  source_reverified: false;
  identity: PreviewIdentity;
  strategy_label: string;
  limits: PreviewLimits;
  metrics: {
    building_count: number;
    known_part_land_far: number;
    coverage_ratio: number;
    maximum_height_m: number;
    open_space_ratio: number;
    generator_valid: boolean;
    warnings: string[];
  };
  retained_buildings: Array<{
    feature_id: string | number | null;
    confidence: 'LOW' | 'MEDIUM' | 'HIGH';
    floor_estimate_status: string;
    floor_count: number | null;
    height_m: number | null;
  }>;
  input_refs: Array<{ label: string; sha256: string }>;
  limitations: string[];
  assets: { plan: string; axonometric: string; geometry: string };
};
type CatalogResponse = {
  status: 'DISABLED' | 'AVAILABLE';
  verified_at_utc: string | null;
  source_reverified: false;
  count: number;
  previews: PreviewItem[];
  limits: PreviewLimits[];
  manifest_sha256?: string | null;
  comparison_sha256?: string | null;
  input_refs?: Array<{ label: string; sha256: string }>;
  limitations?: string[];
  seed?: number | null;
};

type Position = readonly [number, number, ...number[]];
type GeoJsonGeometry = { type: string; coordinates: unknown };
type GeoJsonFeature = {
  type: string;
  geometry: GeoJsonGeometry | null;
  properties?: Record<string, unknown> | null;
};
export type PreviewGeoJson = {
  type: string;
  features: readonly GeoJsonFeature[];
};

type Bounds = [number, number, number, number];
type GeometryLoadState =
  | { key: string; status: 'loading' }
  | { key: string; status: 'ready'; geojson: PreviewGeoJson }
  | { key: string; status: 'error' };

export function projectPoint(
  x: number,
  y: number,
  bounds: Bounds,
  width: number,
  height: number,
): [number, number] {
  const [minX, minY, maxX, maxY] = bounds;
  const scale = Math.min(
    (width - 32) / Math.max(maxX - minX, 1),
    (height - 32) / Math.max(maxY - minY, 1),
  );
  return [16 + (x - minX) * scale, height - 16 - (y - minY) * scale];
}

function collectPositions(value: unknown, into: Position[]): void {
  if (!Array.isArray(value)) return;
  if (
    value.length >= 2 &&
    typeof value[0] === 'number' &&
    typeof value[1] === 'number' &&
    Number.isFinite(value[0]) &&
    Number.isFinite(value[1])
  ) {
    into.push([value[0], value[1]]);
    return;
  }
  value.forEach((child) => collectPositions(child, into));
}

function getBounds(geojson: PreviewGeoJson): Bounds | null {
  const positions: Position[] = [];
  geojson.features.forEach((feature) => {
    if (feature.geometry) collectPositions(feature.geometry.coordinates, positions);
  });
  if (positions.length === 0) return null;
  const xs = positions.map(([x]) => x);
  const ys = positions.map(([, y]) => y);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

function pathForLine(positions: readonly Position[], bounds: Bounds, width: number, height: number, close: boolean): string {
  const points = positions.map(([x, y]) => projectPoint(x, y, bounds, width, height));
  if (points.length < 2) return '';
  return points.map(([x, y], index) => (index === 0 ? 'M' : 'L') + x.toFixed(2) + ',' + y.toFixed(2)).join(' ')
    + (close ? ' Z' : '');
}

function pathsForGeometry(
  geometry: GeoJsonGeometry,
  bounds: Bounds,
  width: number,
  height: number,
): string[] {
  const coordinates = geometry.coordinates;
  if (geometry.type === 'Polygon' && Array.isArray(coordinates)) {
    const rings = coordinates as Position[][];
    const path = rings.map((ring) => pathForLine(ring, bounds, width, height, true)).filter(Boolean).join(' ');
    return path ? [path] : [];
  }
  if (geometry.type === 'MultiPolygon' && Array.isArray(coordinates)) {
    const polygons = coordinates as Position[][][];
    const path = polygons.flatMap((polygon) => polygon.map((ring) => pathForLine(ring, bounds, width, height, true)))
      .filter(Boolean).join(' ');
    return path ? [path] : [];
  }
  if (geometry.type === 'LineString' && Array.isArray(coordinates)) {
    const path = pathForLine(coordinates as Position[], bounds, width, height, false);
    return path ? [path] : [];
  }
  if (geometry.type === 'MultiLineString' && Array.isArray(coordinates)) {
    const path = (coordinates as Position[][]).map((line) => pathForLine(line, bounds, width, height, false))
      .filter(Boolean).join(' ');
    return path ? [path] : [];
  }
  return [];
}

export function GeometryPreview({ geojson }: { geojson: PreviewGeoJson }) {
  const t = useT();
  const width = 480;
  const height = 320;
  const bounds = getBounds(geojson);
  if (!bounds) return <p role="status">{t("No finite geometry is available in this preview.")}</p>;

  return (
    <svg
      className="morphology-preview-map"
      role="img"
      aria-label={t("Preview geometry in EPSG:28992")}
      data-crs="EPSG:28992"
      viewBox={'0 0 ' + width + ' ' + height}
      preserveAspectRatio="xMidYMid meet"
    >
      <rect x="0" y="0" width={width} height={height} className="morphology-preview-map__background" />
      {geojson.features.map((feature, index) => {
        if (!feature.geometry) return null;
        const kind = String(feature.properties?.feature_kind ?? 'geometry').replace(/[^a-zA-Z0-9_-]/g, '');
        const paths = pathsForGeometry(feature.geometry, bounds, width, height);
        return paths.map((d, pathIndex) => (
          <path
            key={String(index) + '-' + pathIndex}
            d={d}
            className={'morphology-preview-map__feature morphology-preview-map__feature--' + kind}
            fillRule="evenodd"
            strokeLinejoin="round"
          />
        ));
      })}
      <text x="16" y="20" className="morphology-preview-map__crs">{t("EPSG:28992 · metres")}</text>
    </svg>
  );
}

function absoluteApiUrl(apiBase: string, path: string): string {
  try {
    const base = apiBase.endsWith('/') ? apiBase : apiBase + '/';
    return new URL(path, base).toString();
  } catch {
    return path;
  }
}

function formatNumber(value: number): string {
  return value.toFixed(2);
}

async function unavailableMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json() as { detail?: unknown };
    const detail = typeof body.detail === 'string' ? body.detail : '';
    const category = detail.match(/\(category=([a-z0-9_]+)\)/i)?.[1];
    return category ? `category=${category}` : fallback;
  } catch {
    return fallback;
  }
}

type ViewKind = 'plan' | 'axonometric' | 'geometry';
type LoadState =
  | { status: 'loading' }
  | { status: 'disabled' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: CatalogResponse };

export function MorphologyPreviewCatalog({ apiBase, sidebarExtra, selectedEditable, onSelectPreview, renderPreview }: { apiBase: string; sidebarExtra?: ReactNode; selectedEditable?: ReactNode; onSelectPreview?: (preview: PreviewItem) => void; renderPreview?: (preview: PreviewItem, previews: PreviewItem[]) => ReactNode }) {
  const t = useT();
  const [loadState, setLoadState] = useState<LoadState>({ status: 'loading' });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [view, setView] = useState<ViewKind>('plan');
  const [imageErrorKey, setImageErrorKey] = useState<string | null>(null);
  const [geometryState, setGeometryState] = useState<GeometryLoadState | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const cleanBase = apiBase.replace(/\/+$/, '');

  useEffect(() => {
    let current = true;
    setLoadState({ status: 'loading' });
    fetch(cleanBase + '/api/v1/morphology/previews', { method: 'GET', headers: { Accept: 'application/json' } })
      .then(async (response) => {
        if (!response.ok) throw new Error(await unavailableMessage(response, 'Preview catalog is unavailable'));
        return (await response.json()) as CatalogResponse;
      })
      .then((data) => {
        if (!current) return;
        if (data.status === 'DISABLED') {
          setLoadState({ status: 'disabled' });
          return;
        }
        if (
          data.status !== 'AVAILABLE' ||
          !Array.isArray(data.previews) ||
          data.previews.length === 0 ||
          data.count !== data.previews.length ||
          !data.previews.some((item) => item.identity.intensity === 'A') ||
          !data.previews.some((item) => item.identity.intensity === 'B')
        ) {
          throw new Error('Preview catalog returned an incomplete response.');
        }
        setLoadState({ status: 'ready', data });
        const initial = data.previews.find((item) => item.identity.intensity === 'A') ?? data.previews[0];
        setSelectedKey(initial.identity.intensity + '/' + initial.identity.strategy_id);
      })
      .catch((error: unknown) => {
        if (current) {
          setLoadState({
            status: 'error',
            message: error instanceof Error ? error.message : 'Preview catalog is unavailable.',
          });
        }
      });
    return () => {
      current = false;
    };
  }, [cleanBase]);

  const previews = loadState.status === 'ready' ? loadState.data.previews : [];
  const grouped = useMemo(
    () => ({
      A: previews.filter((item) => item.identity.intensity === 'A'),
      B: previews.filter((item) => item.identity.intensity === 'B'),
    }),
    [previews],
  );
  const selected = previews.find(
    (item) => item.identity.intensity + '/' + item.identity.strategy_id === selectedKey,
  );
  useEffect(() => { if (selected) onSelectPreview?.(selected); }, [selected, onSelectPreview]);
  const selectedImageKey = selected && view !== 'geometry'
    ? selected.identity.intensity + '/' + selected.identity.strategy_id + '/' + view
    : null;

  const downloadImage = async (kind: 'plan' | 'axonometric') => {
    if (!selected) return;
    setDownloadError(null);
    try {
      const response = await fetch(absoluteApiUrl(cleanBase, selected.assets[kind]), {
        method: 'GET',
        headers: { Accept: 'image/png' },
      });
      if (!response.ok) throw new Error('Preview image is unavailable.');
      const assetHash = response.headers.get('ETag')?.trim().replace(/^"|"$/g, '') ?? '';
      if (!/^[0-9a-f]{64}$/.test(assetHash)) throw new Error('Preview image hash is unavailable.');
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = 'morphology-preview-' + selected.identity.intensity + '-' + selected.identity.strategy_id + '-' + assetHash.slice(0, 12) + '-' + kind + '.png';
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch {
      setDownloadError('Preview image download unavailable.');
    }
  };

  useEffect(() => {
    if (!selected || view !== 'geometry') return;
    const key = selected.identity.intensity + '/' + selected.identity.strategy_id;
    let current = true;
    setGeometryState({ key, status: 'loading' });
    fetch(absoluteApiUrl(cleanBase, selected.assets.geometry), {
      method: 'GET',
      headers: { Accept: 'application/geo+json' },
    })
      .then(async (response) => {
        if (!response.ok) throw new Error('Preview geometry is unavailable.');
        return (await response.json()) as PreviewGeoJson;
      })
      .then((geojson) => {
        if (current) setGeometryState({ key, status: 'ready', geojson });
      })
      .catch(() => {
        if (current) setGeometryState({ key, status: 'error' });
      });
    return () => {
      current = false;
    };
  }, [cleanBase, selected, view]);

  const catalogFallback = (message: ReactNode) => <section className="morphology-preview" aria-busy={loadState.status === 'loading' || undefined}><div className="morphology-preview__layout"><aside>{sidebarExtra}</aside><article>{message}{selectedEditable}</article></div></section>;
  if (loadState.status === 'loading') {
    return catalogFallback(<p role="status" aria-busy="true">{t("Loading existing previews…")}</p>);
  }
  if (loadState.status === 'disabled') {
    return catalogFallback(<p role="status">{t("Preview catalog disabled.")}</p>);
  }
  if (loadState.status === 'error') {
    return catalogFallback(<p role="alert">{t("Preview catalog unavailable:")}{t(loadState.message)}</p>);
  }

  return (
    <section className="morphology-preview" aria-labelledby="morphology-preview-title">
      <header className="morphology-preview__header">
        <div>
          <p className="morphology-preview__eyebrow">{t("Read-only catalog")}</p>
          <h1 id="morphology-preview-title">{t("Existing morphology previews")}</h1>
          <p>{t("These generated outputs are unapproved previews. They do not create editable scenarios or a design decision.")}</p>
          <p className="morphology-preview__source-note">{t("Assets are verified against the pinned manifest at service startup and served as frozen bytes; disk changes after startup are not reflected.")}</p>
          {loadState.data.verified_at_utc && (
            <p className="morphology-preview__source-note">
              {loadState.data.source_reverified
                ? t('Source verified at {time}; source reverified.', { time: loadState.data.verified_at_utc })
                : t('Source verified at {time}; not reverified after startup.', { time: loadState.data.verified_at_utc })}
            </p>
          )}
        </div>
        <div className="morphology-preview__run-meta">
          <span>{loadState.data.count}{t("previews")}</span>
          <span>{t("Seed")}{' '}{loadState.data.seed ?? 'UNKNOWN'}</span>
          <span>{t("Generator")}{' '}{previews[0]?.identity.generator_version ?? 'UNKNOWN'}</span>
        </div>
      </header>

      <div className="morphology-preview__layout">
        <aside className="morphology-preview__catalog" aria-label={t("Preview alternatives")}>
          {(['A', 'B'] as const).map((intensity) => {
            const items = grouped[intensity];
            const limits = items[0]?.limits;
            return (
              <section className="morphology-preview__group" key={intensity} aria-label={intensity === 'A' ? t('Assumption set A') : intensity === 'B' ? t('Assumption set B') : t('Assumption set {set}', { set: intensity })}>
                <h2>{t("Assumption set {set} ({count} previews)", { set: intensity, count: items.length })}</h2>
                {limits && (
                  <div className="morphology-preview__assumptions">
                    <p>{t("Comparison assumptions")}</p>
                    <span>{t("Land FAR upper bound:")}{' '}{formatNumber(limits.far_upper_bound_land)}</span>
                    <span>{t("Coverage upper bound:")}{' '}{limits.coverage_upper_bound === null ? t("not set") : formatNumber(limits.coverage_upper_bound)}</span>
                    <span>{t("New-building height cap:")}{' '}{formatNumber(limits.height_upper_bound_new_buildings_m)}{t("m")}</span>
                  </div>
                )}
                <ul>
                  {items.map((item) => {
                    const key = intensity + '/' + item.identity.strategy_id;
                    return (
                      <li key={key}>
                        <button
                          type="button"
                          className={'morphology-preview__candidate' + (selectedKey === key ? ' is-selected' : '')}
                          aria-pressed={selectedKey === key}
                          aria-label={t('Open') + ' ' + intensity + ': ' + t(item.strategy_label)}
                          onClick={() => {
                            setSelectedKey(key);

                            setView('plan');
                          }}
                        >
                          <span>{t("Open")}{' '}{intensity}: {t(item.strategy_label)}</span>
                          <small>{item.identity.status}</small>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
          {sidebarExtra}
        </aside>

        {selectedEditable ?? (selected ? (
          <article className="morphology-preview__detail" aria-label={selected.identity.intensity + ': ' + t(selected.strategy_label)}>
            <div className="morphology-preview__detail-header">
              <div>
                <p className="morphology-preview__eyebrow">{t("Exploratory candidate ·")}{selected.identity.intensity}</p>
                <h2>{t(selected.strategy_label)}</h2>
              </div>
              <span className="morphology-preview__badge">{selected.identity.status}</span>
            </div>
            <p className="morphology-preview__decision">{t("Human decision created: No")}</p>
            <div className="morphology-preview__view-switch" role="group" aria-label={t("Preview artifact")}>
              <button type="button" aria-pressed={view === 'plan'} onClick={() => setView('plan')}>{t("Plan image")}</button>
              <button type="button" aria-pressed={view === 'axonometric'} onClick={() => setView('axonometric')}>{t("Axonometric image")}</button>
              <button type="button" aria-pressed={view === 'geometry'} onClick={() => setView('geometry')}>{t("Geometry")}</button>
            </div>
            <div className="morphology-preview__downloads" role="group" aria-label={t("Download preview images")}>
              <button type="button" onClick={() => void downloadImage('plan')}>{t("Download plan image")}</button>
              <button type="button" onClick={() => void downloadImage('axonometric')}>{t("Download axonometric image")}</button>
            </div>
            {downloadError && <p role="alert">{t(downloadError)}</p>}
            <div className="morphology-preview__viewer">
              {renderPreview ? renderPreview(selected, previews) : view === 'geometry' ? (
                geometryState?.key !== selectedKey || geometryState.status === 'loading'
                  ? <p role="status">{t("Loading EPSG:28992 geometry…")}</p>
                  : geometryState.status === 'error'
                    ? <p role="alert">{t("Geometry preview unavailable.")}</p>
                    : <GeometryPreview geojson={geometryState.geojson} />
              ) : (
                imageErrorKey === selectedImageKey ? (
                  <p role="alert">{t("Preview image unavailable.")}</p>
                ) : (
                  <img
                    src={absoluteApiUrl(cleanBase, selected.assets[view])}
                    alt={(view === 'plan' ? 'Plan' : 'Axonometric') + ' image for ' + selected.identity.intensity + ': ' + selected.strategy_label}
                    onError={() => setImageErrorKey(selectedImageKey)}
                  />
                )
              )}
            </div>

            <section className="morphology-preview__metrics" aria-label={t("Preview metrics")}>
              <h3>{t("Generator-reported values")}</h3>
              <dl>
                <div><dt>{t("Known-part land FAR")}</dt><dd>{formatNumber(selected.metrics.known_part_land_far)}</dd></div>
                <div><dt>{t("Coverage ratio")}</dt><dd>{formatNumber(selected.metrics.coverage_ratio)}</dd></div>
                <div>
                  <dt>{t("Maximum known height")}</dt>
                  <dd>
                    {formatNumber(selected.metrics.maximum_height_m)}{t("m")}{selected.metrics.warnings.length > 0 && <> · <small>{t("Some retained-building heights are unknown")}</small></>}
                  </dd>
                </div>
                <div><dt>{t("Open-space ratio")}</dt><dd>{formatNumber(selected.metrics.open_space_ratio)}</dd></div>
                <div><dt>{t("Buildings")}</dt><dd>{selected.metrics.building_count}</dd></div>
                <div><dt>{t("Generator validation")}</dt><dd>{selected.metrics.generator_valid ? t("Valid under recorded checks") : t("Invalid")}</dd></div>
              </dl>
            </section>

            <section className="morphology-preview__retained" aria-label={t("Retained-building context")}>
              <h3>{t("Retained-building context")}</h3>
              <p>{t("Preview context only; these features are not approved preservation decisions.")}</p>
              <ul>
                {selected.retained_buildings.map((building, index) => (
                  <li key={building.feature_id ?? index}>{t("Confidence:")}{' '}{t(building.confidence)}{' '}{t('· Floor estimate:')}{' '}{t(building.floor_estimate_status)}
                    {building.floor_count === null ? t("· Floor count: UNKNOWN") : t("· Floor count:") + building.floor_count}
                  </li>
                ))}
              </ul>
            </section>

            <details className="morphology-preview__provenance">
              <summary>{t("Provenance and limitations")}</summary>
              <p>{t("Run created:")}{' '}{selected.identity.run_created_at ?? 'UNKNOWN'}</p>
              <p>{t("Generator commit:")}{' '}{selected.identity.generator_commit ?? 'UNKNOWN'}</p>
              <p>{t("Manifest SHA-256:")}{' '}{loadState.data.manifest_sha256 ?? 'UNKNOWN'}</p>
              <p>{t("Comparison SHA-256:")}{' '}{loadState.data.comparison_sha256 ?? 'UNKNOWN'}</p>
              {selected.metrics.warnings.length > 0 && (
                <div>
                  <h3>{t("Generator warnings")}</h3>
                  <ul>{selected.metrics.warnings.map((warning) => <li key={t(warning)}>{t(warning)}</li>)}</ul>
                </div>
              )}
              <ul>{selected.limitations.map((limitation) => <li key={t(limitation)}>{t(limitation)}</li>)}</ul>
              {selected.input_refs.length > 0 && (
                <ul className="morphology-preview__hashes">
                  {selected.input_refs.map((ref) => <li key={ref.label + ':' + ref.sha256}>{ref.label}: <code>{ref.sha256}</code></li>)}
                </ul>
              )}
            </details>
          </article>
        ) : (
          <div className="morphology-preview__empty" role="status">{t("Select a preview to inspect its artifacts.")}</div>
        ))}
      </div>
    </section>
  );
}
