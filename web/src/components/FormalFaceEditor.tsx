import { useEffect, useState } from 'react';
import { useI18n } from '../i18n';
import { FaceEditControls, type FacePrototypeCommand, type FaceSelection } from './FaceEditControls';
import { FaceSelection3D } from './FaceSelection3D';

type FaceBody = {
  provenance?: string;
  scenario_revision: number;
  face_revision: number;
  geometry_hash: string;
  faces: { id: string; floor_id: string; kind: 'TOP' | 'SIDE'; parent_revision: number; triangles: [number, number, number][] }[];
  detail?: unknown;
  inner_ring_editing_supported?: boolean;
  inner_ring_faces?: { id: string; editable: boolean }[];
};

/** Loads server faces and posts one formal edit. It does not call the fixture preview route. */
export function FormalFaceEditor({ apiBase, scenarioId, buildingId, scenarioRevision, onSaved }: {
  apiBase: string; scenarioId: string; buildingId: string; scenarioRevision: number; onSaved?: () => void | Promise<void>;
}) {
  const { language } = useI18n();
  const errorText = (detail: unknown, status?: number): string => {
    const prefix = language === 'zh-TW' ? '分面編輯失敗' : 'Face edit failed';
    const typed = detail && typeof detail === 'object' && !Array.isArray(detail) ? detail as { code?: string; message?: string } : null;
    const reason = typed ? [typed.code, typed.message].filter(Boolean).join(': ') : typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(item => `${Array.isArray(item?.loc) ? item.loc.join('.') : ''}: ${item?.msg ?? ''}`).join('; ') : '';
    return `${prefix}${status ? ` (HTTP ${status})` : ''}${reason ? `: ${reason}` : ''}`;
  };
  const [state, setState] = useState<FaceBody | null>(null);
  const [selection, setSelection] = useState<FaceSelection | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    let current = true;
    setState(null);
    setSelection(null);
    setNotice(null);
    fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(scenarioId)}/editing/faces?building_id=${encodeURIComponent(buildingId)}`)
      .then(async response => { const body = await response.json(); if (!response.ok) throw new Error(errorText(body?.detail, response.status)); return body as FaceBody; })
      .then(body => { if (current) setState(body); })
      .catch(error => { if (current) { setState(null); setNotice(error instanceof Error ? error.message : errorText(null)); } });
    return () => { current = false; };
  }, [apiBase, scenarioId, buildingId, scenarioRevision]);
  async function apply(command: FacePrototypeCommand) {
    if (!state) return;
    try {
    // Same edit => same key, but semantic face ids carry a 64-hex geometry prefix, so hash to stay under the API's 200-char limit.
    const keySource = `${command.operation}|${command.faceId}|${command.parentRevision}|${command.steps}|${command.points.map(point => point.join(':')).join('_')}`;
    const idempotencyKey = `formal-${command.operation}-${await sha256Hex(keySource)}`;
    const response = await fetch(`${apiBase}/api/v1/scenarios/${encodeURIComponent(scenarioId)}/editing/faces`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        building_id: buildingId, operation: command.operation, face_id: command.faceId, points: command.points, steps: command.steps,
        parent_revision: command.parentRevision, expected_scenario_revision: state.scenario_revision, expected_geometry_hash: state.geometry_hash,
        idempotency_key: idempotencyKey,
      }),
    });
    const body = await response.json().catch(() => null) as FaceBody | null;
    if (!response.ok || !body) { setNotice(errorText(body?.detail, response.status)); return; }
    setState(body);
    setSelection(null);
    setNotice(language === 'zh-TW' ? '正式草稿已儲存。' : 'Formal draft saved.');
    await onSaved?.();
    } catch (error) { setNotice(error instanceof Error ? `${errorText(null)}: ${error.message}` : errorText(null)); }
  }
  const first = state?.faces[0];
  const active = selection ?? (first ? { id: first.id, floorId: first.floor_id, parentRevision: state?.face_revision ?? 0, kind: first.kind } : null);
  return <section aria-label="Formal face editing">
    {state?.inner_ring_editing_supported === false && !!state.inner_ring_faces?.length && <p role="status">{language === 'zh-TW' ? '中庭側分面目前不支援編輯；可編輯外環分面，內環保持不變。' : 'Courtyard-side faces cannot be edited. Outer-ring faces remain editable; inner rings are preserved.'}</p>}
    {notice && <p role="status">{notice}</p>}
    <FaceSelection3D faces={(state?.faces ?? []).map(face => ({ id: face.id, floorId: face.floor_id, parentRevision: face.parent_revision, kind: face.kind, triangles: face.triangles ?? [] }))} selectedId={selection?.id ?? null} onSelect={setSelection} />
    <FaceEditControls selection={active} fixtureOnly={false} formalDraft onPreview={command => void apply(command)} />
  </section>;
}

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
}
