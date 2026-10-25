import json,sys
sys.path.insert(0,'src')
from bisect import bisect_right
from shapely.geometry import shape,LineString
from urban_design.fabric_syntax_segments import lineage,authored
import os; R=os.environ.get('R','artifacts/net2/round-3')
for fab in ['harbour_grain','closed_block_extension','courtyard_islands','landscape_figure']:
  for mode in ['pedestrian','bicycle']:
    p=f'{R}/syntax/{fab}-{mode}.json'
    if not os.path.exists(p): continue
    compact=json.load(open(p))
    try: full,plan,_=lineage(compact)
    except Exception as e: print(fab,mode,'BLOCKED',e); continue
    site=shape(plan['site']); roads={str(r['id']):r for r in plan['roads']}
    rows=full['after']['segments']; pop=sorted(r['nain'] for r in rows)
    res=[]
    for role in ['primary_street','waterfront_path']:
      ids={k for k,r in roads.items() if r['properties'].get('role')==role}
      exp=sum(shape(roads[k]['geometry']).intersection(site).length for k in ids)
      L=W=0
      for r in rows:
        a=authored(r['source_line_id'],roads)
        if a in ids:
          g=LineString(r['coordinates']).intersection(site); l=g.length
          L+=l; W+=l*r['nain']
      if L: m=W/L; res.append(f'{role} pct={100*bisect_right(pop,m)/len(pop):.1f} cov={L/exp:.0%}')
      else: res.append(f'{role} none')
    print(fab,mode,' | '.join(res))
