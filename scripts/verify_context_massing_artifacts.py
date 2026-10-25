"""Recompute compact S6 artifact metrics from actual polygons and floor plates.

A readback witness, not a cross-provider review or design acceptance.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from shapely.geometry import shape
from shapely.ops import unary_union


def verify(root):
    results=[]
    for path in sorted(Path(root).glob('*-2.json')):
        row=json.loads(path.read_text());m=row['metrics'];buildings=row['buildings']
        gfa=sum(shape(f['geometry']).area for b in buildings for f in b['floors'])
        footprint=unary_union([shape(f['geometry']) for f in row['features']])
        far=(gfa+m['retained_gfa_upper_m2'])/m['far_denominator_m2']
        coverage=(footprint.area+m['retained_footprint_m2'])/m['far_denominator_m2']
        facades=[e for b in buildings for e in b['facade_segments']]
        street=sum(shape(e['geometry']).length for e in facades)
        active=sum(shape(e['geometry']).length for e in facades if e['active'])
        height=max(sum(f['floor_height_m'] for f in b['floors']) for b in buildings)
        housing=[b for b in buildings if b['floors'][-1]['use'] in ('Residential','Mixed')]
        average=sum(shape(f['geometry']).area for b in housing for f in b['floors'])/sum(shape(b['floors'][0]['geometry']).area for b in housing)
        named=unary_union([shape(s['geometry']) for s in row['named_open_spaces']])
        remnants=unary_union([shape(s['geometry']) for s in row['narrow_remnants']]);open_space=shape(row['open_space'])
        flags=dict(far_geometry=abs(far-m['far'])<1e-8,
            coverage_geometry=abs(coverage-m['coverage'])<1e-8,
            floor_average_geometry=abs(average-m['residential_mixed_area_weighted_floors'])<1e-8,
            active_actual_length=street>0 and abs(active/street-m['active_frontage_ratio'])<1e-8,
            height_geometry=height<=20,
            space_partition=named.intersection(remnants).area<.01 and named.union(remnants).symmetric_difference(open_space).area<.01,
            no_footprint_overlap=abs(footprint.area-sum(shape(f['geometry']).area for f in row['features']))<.01,
            plates_contained=all(shape(b['floors'][0]['geometry']).buffer(1e-7).covers(shape(f['geometry'])) for b in buildings for f in b['floors']),
            low_reasons=all(b['floor_count']>=4 or bool(b['low_floor_reason_zh']) and bool(b['low_floor_rule_card_ids']) for b in buildings),
            hard_bounds=.70<=far<=.80 and coverage<=.35 and average>=4 and active/street<=.5)
        results.append(dict(id=row['id'],checks=flags,far=far,coverage=coverage,average_floors=average,
            active_ratio=active/street,max_height=height,input_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return dict(status='PASS' if len(results)==4 and all(all(r['checks'].values()) for r in results) else 'FAIL',
        scope='Geometry readback only; no design or cross-provider acceptance',
        utc=subprocess.check_output(['date','-u','+%Y-%m-%dT%H:%M:%SZ'],text=True).strip(),results=results)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=verify(a.root);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(result['status'],len(result['results']))
    raise SystemExit(0 if result['status']=='PASS' else 1)
