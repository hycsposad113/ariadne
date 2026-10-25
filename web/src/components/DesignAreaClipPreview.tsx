import { useT } from '../i18n';
import React from 'react';

type Position = [number, number];

interface PolygonalGeometry {
  type: 'Polygon' | 'MultiPolygon';
  coordinates: any;
}

interface DesignAreaClipPreviewProps {
  candidateRing: Position[];
  clippedGeometry: PolygonalGeometry;
}

function geometryRings(geometry: PolygonalGeometry): Position[][][] {
  if (geometry.type === 'Polygon') return [geometry.coordinates as Position[][]];
  return geometry.coordinates as Position[][][];
}

function pathFromRings(rings: Position[][], project: (position: Position) => Position): string {
  return rings.map((ring) => {
    if (!Array.isArray(ring) || ring.length < 3) return '';
    const commands = ring.map((position, index) => {
      const [x, y] = project(position);
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    });
    return `${commands.join(' ')} Z`;
  }).filter(Boolean).join(' ');
}

export const DesignAreaClipPreview: React.FC<DesignAreaClipPreviewProps> = ({ candidateRing, clippedGeometry }) => {
  const t = useT();
  const polygons = geometryRings(clippedGeometry);
  const clippedRings = polygons.flatMap(polygon => polygon);
  const allPoints = [...candidateRing, ...clippedRings.flatMap(ring => ring)]
    .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (allPoints.length < 3) return null;
  const xs = allPoints.map(([x]) => x);
  const ys = allPoints.map(([, y]) => y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const width = Math.max(maxX - minX, 1);
  const height = Math.max(maxY - minY, 1);
  const scale = Math.min(180 / width, 94 / height);
  const project = ([x, y]: Position): Position => [10 + (x - minX) * scale, 10 + (maxY - y) * scale];
  const candidatePath = pathFromRings([candidateRing], project);
  const clippedPath = pathFromRings(clippedRings, project);

  return (
    <div style={{ marginTop: '8px', padding: '7px', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)', background: 'rgba(15, 23, 42, 0.55)' }}>
      <svg
        role="img"
        aria-label={t("Design area clipping preview")}
        viewBox="0 0 200 114"
        preserveAspectRatio="xMidYMid meet"
        style={{ display: 'block', width: '100%', maxHeight: '120px' }}
      >
        <rect x="0" y="0" width="200" height="114" rx="5" fill="rgba(2, 6, 23, 0.28)" />
        {clippedPath && <path d={clippedPath} fill="rgba(250, 204, 21, 0.4)" stroke="#facc15" strokeWidth="1.5" fillRule="evenodd" />}
        {candidatePath && <path d={candidatePath} fill="none" stroke="#fb7185" strokeWidth="1.3" strokeDasharray="4 3" />}
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', marginTop: '4px', fontSize: '9px', color: 'var(--text-muted)' }}>
        <span><span style={{ color: '#fb7185' }}>┄</span>{t("Drawn outline")}</span>
        <span><span style={{ color: '#facc15' }}>■</span>{t("StudyArea intersection")}</span>
      </div>
    </div>
  );
};
