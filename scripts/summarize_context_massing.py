"""Write compact Chinese comparison/scale CSVs from an offline S6 batch."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def summarize(root):
    root=Path(root)
    rows=[json.loads(p.read_text()) for p in sorted(root.glob('*-2.json'))]
    names={'radial':'向心型','axial':'軸線型','grid':'網格型','green_service':'綠廊服務型'}
    columns=['策略','來源變體','狀態','FAR','建蔽率','住宅混合平均層數','新建棟數','高度分布','具名開放空間平方公尺','未配置殘地平方公尺','雙側街牆連續比例','活躍首層比例','不合格項目']
    with (root/'comparison-zh.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(columns)
        for row in rows:
            m=row['metrics'];hist={}
            for b in row['buildings']:hist[b['height_m']]=hist.get(b['height_m'],0)+1
            w.writerow([names[row['family']],row['id'],row['status'],m['far'],m['coverage'],m['residential_mixed_area_weighted_floors'],len(row['buildings']),'; '.join(f'{h:g}公尺×{n}' for h,n in sorted(hist.items())),m['named_open_space_area_m2'],m['narrow_remnant_area_m2'],m['streetwall_continuity_ratio'],m['active_frontage_ratio'],';'.join(row['failure_reasons'])])
    for row in rows:
        with (root/(row['id']+'-scale-statistics-zh.csv')).open('w',newline='') as f:
            w=csv.writer(f);w.writerow(['建築','街廓','類型','底面積平方公尺','GFA平方公尺','樓層數','高度公尺','翼深公尺','中庭淨寬公尺','低層理由','規則卡','公園距離或來源回應'])
            for b in row['buildings']:
                w.writerow([b['building_id'],b['block_id'],b['type_id'],b['footprint_area_m2'],b['new_gfa_m2'],b['floor_count'],b['height_m'],b['scale']['wing_depth_m'],b['scale'].get('courtyard_width_m'),b['low_floor_reason_zh'],';'.join(b['design_intent']['rule_card_ids']),';'.join(b['design_intent']['context_response'])])
        with (root/(row['id']+'-open-spaces-zh.csv')).open('w',newline='') as f:
            w=csv.writer(f);w.writerow(['名稱','用途','面積平方公尺','狀態'])
            for s in row['named_open_spaces']:w.writerow([s['name_zh'],s['use_zh'],s['area_m2'],s['status']])
            for i,s in enumerate(row['narrow_remnants']):w.writerow(['未配置殘地 '+str(i+1),s['reason_zh'],s['area_m2'],'UNASSIGNED'])
    manifest={str(p):dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size_bytes=p.stat().st_size) for p in sorted(root.glob('*')) if p.is_file() and p.suffix in ('.csv','.png')}
    (root/'deliverable-hashes.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    return rows


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();summarize(a.root)
