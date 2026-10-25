import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';

export type FaceSelection = { id: string; floorId: string; parentRevision: number; kind: 'TOP' | 'SIDE'; localBounds?: [number, number, number, number] };
export type FacePrototypeCommand = {
  faceId: string; parentRevision: number; operation: 'SPLIT_LINE' | 'SPLIT_CONTOUR' | 'SIDE_PUSH' | 'TOP_EXTRUDE' | 'SETBACK';
  points: [number, number][]; steps: number; semantics: 'NEW_USABLE_FLOORS_PROTOTYPE';
};
const copy = {
  en: { title: 'Face editing prototype', blocked: 'Blocked: approved baseline, bounds and floor semantics are required for formal editing.', fixture: 'Floor-aligned prototype; no acceptance or analysis eligibility.', formal: 'Unaccepted draft; not eligible for acceptance or analysis.', select: 'Select a semantic face in 3D.', operation: 'Operation', line: 'Cut line', contour: 'Closed contour', side: 'Side push (1 m steps)', top: 'Top extrusion (storeys)', setback: 'Upper two storeys setback (1 m steps)', steps: 'Integer steps', points: 'Face-local coordinates (metres): one x,y pair per line', draw: 'Draw in face-local metres', clear: 'Clear drawing', preview: 'Preview fixture command', apply: 'Apply formal face edit', error: 'Use finite coordinates and a nonzero integer step; line needs two points, contour needs three distinct points.', semantic: 'Founder decision pending: façade-only shaping versus usable floor creation.' },
  'zh-TW': { title: '分面編輯（原型）', blocked: '已封鎖：正式編輯需要批准基準方案、邊界與樓板語意。', fixture: '僅供測試原型 — 樓層對齊原型；不可接受或用於分析。', formal: '正式草案 — 未接受的草稿；不可接受，也不能拿去分析。', select: '請在 3D 或下方清單選取一個面。', operation: '操作', line: '切線', contour: '閉合輪廓', side: '側推（1 m 步進）', top: '頂部推拉（整層）', setback: '上兩層退台（1 m 步進）', steps: '整數步數', points: '面局部座標（公尺）：每行一組 x,y', draw: '以面局部公尺座標畫線／輪廓', clear: '清除繪圖', preview: '預覽 fixture 指令', apply: '套用正式分面', error: '座標須有限、步數須為非零整數；切線須兩點，輪廓須至少三個不同點。', semantic: 'Founder 待裁決：純立面造型與新增可用樓板的區別。' },
};
export function FaceEditControls({ selection, fixtureOnly, formalDraft = false, onPreview }: {
  selection: FaceSelection | null; fixtureOnly: boolean; formalDraft?: boolean; onPreview: (command: FacePrototypeCommand) => void;
}) {
  const { language } = useI18n(); const t = copy[language];
  const editable = fixtureOnly || formalDraft;
  const [operation, setOperation] = useState<FacePrototypeCommand['operation']>('SPLIT_LINE');
  const [steps, setSteps] = useState('1'); const [coordinates, setCoordinates] = useState(''); const [error, setError] = useState(false);
  useEffect(() => { setCoordinates(''); setError(false); }, [selection?.id, selection?.parentRevision]);
  function submit() {
    if (!editable || !selection) return;
    const points = coordinates.trim() ? coordinates.trim().split('\n').map(line => line.split(',').map(Number)) : [];
    const split = operation.startsWith('SPLIT');
    const validPoints = points.every(p => p.length === 2 && p.every(Number.isFinite));
    if (!validPoints || !Number.isSafeInteger(Number(steps)) || Number(steps) <= 0 || (split && (operation === 'SPLIT_LINE' ? points.length !== 2 : new Set(points.map(p => p.join(','))).size < 3))) { setError(true); return; }
    setError(false); onPreview({ faceId: selection.id, parentRevision: selection.parentRevision, operation, points: points as [number, number][], steps: Number(steps), semantics: 'NEW_USABLE_FLOORS_PROTOTYPE' });
  }
  return <section aria-label={t.title}>
    <h3>{t.title}</h3>
    <p role="status" title={fixtureOnly ? 'FIXTURE_ONLY' : formalDraft ? 'FORMAL_DRAFT' : 'BLOCKED'}>
      {fixtureOnly ? t.fixture : formalDraft ? t.formal : t.blocked}
      <span className="sr-only" style={{ display: 'none' }}>
        {fixtureOnly ? 'FIXTURE_ONLY' : formalDraft ? 'FORMAL_DRAFT' : 'BLOCKED'}
      </span>
    </p>
    <p>{t.semantic}</p>
    <p>{selection ? `${faceLabel(selection.id, language)} / r${selection.parentRevision}` : t.select}</p>
    <label>{t.operation}<select value={operation} onChange={e => setOperation(e.target.value as FacePrototypeCommand['operation'])}>
      {([['SPLIT_LINE', t.line], ['SPLIT_CONTOUR', t.contour], ['SIDE_PUSH', t.side], ['TOP_EXTRUDE', t.top], ['SETBACK', t.setback]] as const).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
    </select></label><label>{t.steps}<input type="number" step="1" value={steps} onChange={e => setSteps(e.target.value)} /></label>
    <label>{t.points}<textarea value={coordinates} onChange={e => setCoordinates(e.target.value)} /></label>
    {selection?.localBounds && <><svg role="img" aria-label={t.draw} width="300" height="200" viewBox="0 0 300 200" style={{ border: '1px solid currentColor', cursor: 'crosshair' }} onClick={event => {
      const bounds = selection.localBounds!; const rect = event.currentTarget.getBoundingClientRect(); if (!rect.width || !rect.height) return;
      const x = bounds[0] + (event.clientX - rect.left) / rect.width * (bounds[2] - bounds[0]);
      const y = bounds[3] - (event.clientY - rect.top) / rect.height * (bounds[3] - bounds[1]);
      setCoordinates(previous => `${previous}${previous ? '\n' : ''}${x},${y}`);
    }}><polyline fill="none" stroke="currentColor" points={coordinates.split('\n').map(line => { const [x,y] = line.split(',').map(Number); const b = selection.localBounds!; return `${(x-b[0])/(b[2]-b[0])*300},${(b[3]-y)/(b[3]-b[1])*200}`; }).join(' ')} /></svg><button onClick={() => setCoordinates('')}>{t.clear}</button></>}
    {error && <p role="alert">{t.error}</p>}<button disabled={!editable || !selection} onClick={submit}>{formalDraft && !fixtureOnly ? t.apply : t.preview}</button>
  </section>;
}

/** Readable label for a semantic face id ("<hash>|r1:r0:<building>-floor-4:top:part:0" -> "4F top · part 1").
 *  The raw id (with its geometry-hash prefix) stays the API identity; this is display only. */
export function faceLabel(id: string, language: 'en' | 'zh-TW' = 'en'): string {
  const raw = id.includes('|') ? id.slice(id.lastIndexOf('|') + 1) : id;
  const zh = language === 'zh-TW';
  const floor = /-floor-(\d+):(top|side:(\d+))/.exec(raw);
  const added = /:new:(\d+):(top|side:(\d+))/.exec(raw);
  const match = floor ?? added;
  if (!match) return raw;
  const storey = floor ? `${Number(floor[1]) + 1}F` : (zh ? `新增層 ${Number(added![1]) + 1}` : `added storey ${Number(added![1]) + 1}`);
  const surface = match[2] === 'top' ? (zh ? '頂面' : 'top') : (zh ? `側面 ${Number(match[3]) + 1}` : `side ${Number(match[3]) + 1}`);
  const parts = [...raw.matchAll(/:part:(\d+)/g)].map(m => Number(m[1]) + 1);
  const part = parts.length ? (zh ? ` · 分割 ${parts.join('-')}` : ` · part ${parts.join('-')}`) : '';
  return `${storey} ${surface}${part}`;
}
