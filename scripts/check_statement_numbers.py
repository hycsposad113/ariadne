"""Deterministic number trace for Ariadne design statements (run-8).

Every number in a zh statement must match a source value within 2-significant-figure rounding,
or appear in the knowledge pack / context summary text. Untraced numbers are reported, not fixed.
"""
from __future__ import annotations
import argparse, csv, json, math, re
from pathlib import Path

NUM = re.compile(r"(?<![A-Za-z0-9_.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)")

def numbers_in(obj, out):
    if isinstance(obj, bool): return
    if isinstance(obj, (int, float)) and math.isfinite(obj): out.add(float(obj)); return
    if isinstance(obj, dict): [numbers_in(v, out) for v in obj.values()]
    elif isinstance(obj, list): [numbers_in(v, out) for v in obj]
    elif isinstance(obj, str): out.update(float(m.replace(',', '')) for m in NUM.findall(obj))

def close(v, sources):
    for s in sources:
        for t in (s, s * 100, s / 100, s / 1000, s / 10000):
            if t == 0: continue
            if abs(v - t) <= max(abs(t) * 0.051, 0.051): return True
    return False

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--root', type=Path, required=True); ap.add_argument('--assessment', type=Path, required=True)
    ap.add_argument('--context', type=Path, required=True); ap.add_argument('--fabrics', type=Path, required=True); a = ap.parse_args()
    common = set(); numbers_in(json.loads(a.assessment.read_text()), common); numbers_in(a.context.read_text(), common)
    report = {}
    for zh in sorted((a.root / 'ai-explanations').glob('*-design-statement-zh.md')):
        fid = zh.name.split('-design-statement')[0]; src = set(common)
        numbers_in(json.loads((a.root / f'{fid}-plan.json').read_text()).get('metrics', {}), src)
        numbers_in(json.loads((a.root / f'{fid}-checks.json').read_text()), src)
        with open(a.root / f'{fid}-landuse.csv', encoding='utf-8-sig') as f: numbers_in([list(r.values()) for r in csv.DictReader(f)], src)
        numbers_in(json.loads((a.fabrics / f'fabric.{fid}.json').read_text()), src)
        text = zh.read_text(); found = [float(m.replace(',', '')) for m in NUM.findall(re.sub(r'^#+ *\d+', '', text, flags=re.M))]
        trivial = {v for v in found if v <= 12 and v == int(v)}  # section numbers, floors, counts
        untraced = sorted({v for v in found if v not in trivial and not close(v, src)})
        report[fid] = {'numbers': len(found), 'untraced': untraced}
    print(json.dumps(report, ensure_ascii=False, indent=1))

if __name__ == '__main__': main()
