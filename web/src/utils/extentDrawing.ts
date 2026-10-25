import type { StyleSpecification } from 'maplibre-gl';
export type Point = [number, number];
export const extentCopy = {
  en: { title: 'Draw extent', warning: 'This is a data acquisition extent, not the formal site.',
    instruction: 'Click to add vertices, double-click to finish. Drag to pan.', clear: 'Clear and redraw',
    submit: 'Save extent and fetch data', area: 'Approximate area', basemap: 'Basemap', error: 'Map unavailable. Check your network or WebGL support.',
    pending: 'Fetching sources…', unavailable: 'Request outcome unknown. Inspect saved extents before retrying.',
    close: 'Return to Site views', status: 'Acquisition status', list: 'Saved extents', loading: 'Loading saved extents…', listError: 'Could not load saved extents.' },
  'zh-TW': { title: '畫範圍', warning: '這是資料抓取範圍，不是正式基地。',
    instruction: '點擊加點，雙擊完成；拖曳移動地圖。', clear: '清除重畫', submit: '儲存範圍並抓取資料',
    area: '概略面積', basemap: '底圖', error: '無法顯示地圖，請檢查網路或 WebGL 支援。',
    pending: '正在抓取來源…', unavailable: '請求結果未知，重試前請先查閱已存範圍。',
    close: '返回基地檢視', status: '抓取狀態', list: '已儲存範圍', loading: '正在讀取已儲存範圍…', listError: '無法讀取已儲存範圍。' },
};
export function finishedExtent(points: Point[]) {
  const unique = points.filter((point, index) => index === 0 || point[0] !== points[index - 1][0] || point[1] !== points[index - 1][1]);
  if (unique.length > 1 && unique[0][0] === unique.at(-1)![0] && unique[0][1] === unique.at(-1)![1]) unique.pop();
  if (unique.length < 3 || unique.some(([lon, lat]) => !Number.isFinite(lon) || !Number.isFinite(lat) || Math.abs(lon) > 180 || Math.abs(lat) > 85)) return null;
  const ring = [...unique, unique[0]];
  // Spherical preview only; the backend validates geometry and recomputes metric area.
  const radians = Math.PI / 180;
  let sum = 0;
  for (let index = 0; index < ring.length - 1; index++) {
    sum += (ring[index + 1][0] - ring[index][0]) * radians * (2 + Math.sin(ring[index][1] * radians) + Math.sin(ring[index + 1][1] * radians));
  }
  const areaM2 = Math.abs(sum) * 6371008.8 ** 2 / 2;
  if (areaM2 <= 0) return null;
  return { geometry: { type: 'Polygon' as const, coordinates: [ring] }, areaM2 };
}
export function extentBasemap(kind: 'OSM' | 'PDOK'): StyleSpecification {
  const source = kind === 'OSM' ? { tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> (ODbL)' }
    : { tiles: ['https://service.pdok.nl/brt/achtergrondkaart/wmts/v2_0/standaard/EPSG:3857/{z}/{x}/{y}.png'], attribution: '© <a href="https://www.pdok.nl/">Kadaster / PDOK</a> BRT (CC BY 4.0)' };
  return { version: 8, sources: { basemap: { type: 'raster', tileSize: 256, ...source } }, layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }] };
}
