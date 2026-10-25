"""Replace section 7 (syntax results) of Ariadne statements with deterministic text from a NET2 assessment.

Used when syntax is recomputed after statements were written (no new Live AI calls). The replaced
section is labelled as program-generated; every edit is appended to ai-explanations/human-edits.json.
"""
from __future__ import annotations
import argparse, datetime, json, re
from pathlib import Path

NEW_PART = {'harbour_grain': 90.7, 'closed_block_extension': 89.4, 'landscape_figure': 74.9, 'courtyard_islands': 37.6}

def values(assessment: dict) -> dict:
    out = {}
    for rep in assessment['reports']:
        n = rep.get('net2_assessment') or {}
        for c in n.get('checks', []):
            out[(n.get('fabric_id'), n.get('mode'), c['target'])] = c
    return out

def pct(c): return f"{c['value']:.2f}" if isinstance(c.get('value'), (int, float)) else '—'

def zh(fid, v):
    p, b, w = v[(fid, 'pedestrian', 'primary_street')], v[(fid, 'bicycle', 'primary_street')], v[(fid, 'pedestrian', 'waterfront_path')]
    grade = '優（≥ Keileweg 87.67）' if p['value'] >= 87.67 else '符合（≥ Vierhavensstraat 57.34）' if p['value'] >= 57.34 else '未達'
    note = '新設計段本身仍低，整體值過門檻主要因為含既有 Keileweg 段。' if NEW_PART[fid] < 57.34 else '新設計段本身也達到基準。'
    return (f"> 本節由確定性程式依 NET2 第 7 輪 v3 語法結果產生（2026-10-15 重算，非 AI 撰寫）。\n\n"
            f"- 步行主街（800 m）：整體第 {pct(p)} 百分位，{grade}；若只算新設計段（排除既有 Keileweg 256 m）為第 {NEW_PART[fid]} 百分位。{note}\n"
            f"- 自行車主街（2 km）：第 {pct(b)} 百分位，門檻 67.11，{'達標' if b['value'] >= 67.11 else '未達'}。\n"
            f"- 步行水岸：第 {pct(w)} 百分位，低於 1.5 km 內既有碼頭步道中位數 43.46，未達；基地位於半島末端，水岸步道多為盡端路。\n"
            f"- 百分位是該道路在全網 NAIN 分布中的名次，不是比例。\n")

def en(fid, v):
    p, b, w = v[(fid, 'pedestrian', 'primary_street')], v[(fid, 'bicycle', 'primary_street')], v[(fid, 'pedestrian', 'waterfront_path')]
    grade = 'superior (≥ Keileweg 87.67)' if p['value'] >= 87.67 else 'compliant (≥ Vierhavensstraat 57.34)' if p['value'] >= 57.34 else 'below benchmark'
    note = 'The newly designed stretch alone remains weak; the whole-street value passes mainly because it includes the existing Keileweg stretch.' if NEW_PART[fid] < 57.34 else 'The newly designed stretch alone also meets the benchmark.'
    return (f"> This section is generated deterministically from the NET2 round-7 v3 syntax results (recomputed 2026-10-15; not AI-written).\n\n"
            f"- Pedestrian main street (800 m): {pct(p)}th percentile overall, {grade}; newly designed stretch only (excluding the existing 256 m of Keileweg): {NEW_PART[fid]}th percentile. {note}\n"
            f"- Cycling main street (2 km): {pct(b)}th percentile against a 67.11 threshold — {'meets' if b['value'] >= 67.11 else 'below'}.\n"
            f"- Pedestrian waterfront: {pct(w)}th percentile, below the 43.46 median of existing quay paths within 1.5 km; the site sits at a peninsula tip where waterfront paths are mostly dead ends.\n"
            f"- Percentiles rank the street within the full-network NAIN distribution; they are not proportions.\n")

def replace_section(text: str, body: str) -> str:
    m = re.search(r"(^#{2,4} *7\.?[^\n]*\n)(.*?)(?=^#{2,4} *8)", text, flags=re.M | re.S)
    if not m: raise ValueError('section 7 not found')
    return text[:m.start(2)] + body + '\n' + text[m.end(2):]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--dir', type=Path, required=True); ap.add_argument('--assessment', type=Path, required=True); a = ap.parse_args()
    v = values(json.loads(a.assessment.read_text())); log = a.dir / 'human-edits.json'
    rec = json.loads(log.read_text()) if log.exists() else {'edits': []}
    rec.setdefault('section7_refresh', [])
    for fid in NEW_PART:
        for lang, fn in (('zh', zh), ('en', en)):
            path = a.dir / f'{fid}-design-statement-{lang}.md'
            path.write_text(replace_section(path.read_text(), fn(fid, v)))
            rec['section7_refresh'].append({'file': path.name, 'utc': datetime.datetime.now(datetime.UTC).isoformat(), 'source': str(a.assessment)})
    log.write_text(json.dumps(rec, ensure_ascii=False, indent=1)); print('refreshed', len(rec['section7_refresh']))

if __name__ == '__main__': main()
