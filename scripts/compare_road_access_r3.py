#!/usr/bin/env python3
"""Offline geometry-only before/r1/r3 comparison; no project state access."""
import argparse
import hashlib
import json
from pathlib import Path
from shapely.geometry import shape
from shapely.ops import unary_union


def compare(paths, output):
    output.mkdir(parents=True,exist_ok=False)
    versions={name:json.loads(path.read_text()) for name,path in paths.items()}
    rows=[]
    for version,report in versions.items():
        for candidate in report['candidates']:
            features=candidate['geometry']['features']
            edges=[(shape(f['geometry']),f['properties']['width_m']) for f in features if f['properties']['role']=='road']
            roads=unary_union([g.buffer(w/2) for g,w in edges])
            footprints=[shape(f['geometry']) for f in features if f['properties']['role']=='new_building']
            distances=[max(p.distance(roads) for p in (g.geoms if g.geom_type=='MultiPolygon' else (g,))) for g in footprints]
            metrics=candidate.get('metrics',{})
            baseline=next(c for c in versions['before']['candidates'] if c['recipe_id']==candidate['recipe_id'])
            original=sum(shape(f['geometry']).length for f in baseline['geometry']['features'] if f['properties']['role']=='road')
            length=sum(g.length for g,w in edges)
            rows.append(dict(version=version,scheme=candidate['recipe_id'],status=candidate['status'],
                inaccessible_count=sum(d>40 for d in distances),building_count=len(distances),max_distance_m=max(distances,default=None),
                road_length_m=length,added_length_m=length-original,added_length_ratio=(length-original)/original,
                far=metrics.get('far'),new_gfa_m2=metrics.get('new_gfa_m2'),total_gfa_upper_m2=metrics.get('total_gfa_upper_m2'),
                dictionary_type_count=len(metrics.get('dictionary_types',[])),
                represented_zone_count=sum(z['assigned_new_gfa_m2']>0 for z in metrics.get('zone_uses',[])),
                approved_zone_count=len(metrics.get('zone_uses',[])),
                failure_reasons=candidate.get('failure_reasons',[]),
                coverage=metrics.get('coverage'),open_space=metrics.get('open_space_ratio'),
                open_space_drop_points=None if not metrics else 100*(baseline['metrics']['open_space_ratio']-metrics['open_space_ratio'])))
    manifest={name:dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for name,path in paths.items()}
    (output/'comparison.json').write_text(json.dumps(dict(sources=manifest,rows=rows),indent=2,allow_nan=False)+'\n')
    lines=['# W6 road access before / r1 / r3','',
           '| Scheme | Run | Status | Types | Zones | Unreachable | Road m | Added m | Added % | FAR | New GFA m² | Total GFA upper m² | Coverage % | Open space % | Drop points |',
           '|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    def number(v,d=2): return 'N/A' if v is None else f'{v:.{d}f}'
    for scheme in [c['recipe_id'] for c in versions['before']['candidates']]:
        for row in [r for r in rows if r['scheme']==scheme]:
            lines.append('| '+ ' | '.join([scheme,row['version'],row['status'],str(row['dictionary_type_count']),f"{row['represented_zone_count']}/{row['approved_zone_count']}",str(row['inaccessible_count']),number(row['road_length_m']),number(row['added_length_m']),number(100*row['added_length_ratio']),number(row['far'],6),number(row['new_gfa_m2']),number(row['total_gfa_upper_m2']),number(None if row['coverage'] is None else 100*row['coverage']),number(None if row['open_space'] is None else 100*row['open_space']),number(row['open_space_drop_points'])])+' |')
    lines+=['','Distances and road lengths independently recomputed from GeoJSON, in EPSG:28992 metres. GFA/coverage/open space use deterministic pipeline metrics; GFA includes an upper retained estimate, not an observation. No overall winner.']
    (output/'comparison.md').write_text('\n'.join(lines)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    schemes=[c['recipe_id'] for c in versions['before']['candidates']]
    fig,axes=plt.subplots(3,len(schemes),figsize=(24,12),squeeze=False)
    colors={'street_block':'#eeeeee','retained':'#aaa9a4','primary_open_space':'#59ad68','new_building':'#477bca'}
    for i,(version,report) in enumerate(versions.items()):
        for j,scheme in enumerate(schemes):
            ax=axes[i,j]
            candidate=next(c for c in report['candidates'] if c['recipe_id']==scheme)
            for role in ('street_block','retained','primary_open_space','new_building','road'):
                for feature in candidate['geometry']['features']:
                    if feature['properties']['role']!=role: continue
                    g=shape(feature['geometry'])
                    if role=='road':
                        for line in (g.geoms if g.geom_type=='MultiLineString' else (g,)):
                            x,y=line.xy
                            ax.plot(x,y,color='#ef4a50' if feature['properties']['width_m']!=4.5 else '#b73190',lw=1.1 if feature['properties']['width_m']==4.5 else 1.8,zorder=5)
                        continue
                    for polygon in (g.geoms if g.geom_type=='MultiPolygon' else (g,)):
                        ax.add_patch(Polygon(list(polygon.exterior.coords),facecolor=colors[role],edgecolor='white',lw=.3))
                        for hole in polygon.interiors:
                            ax.add_patch(Polygon(list(hole.coords),facecolor='white',edgecolor='none'))
            row=next(r for r in rows if r['version']==version and r['scheme']==scheme)
            ax.set_title(f"{scheme} / {version} / {row['status']}\nroads {row['road_length_m']:.0f} m; added {row['added_length_m']:.0f} m; inaccessible {row['inaccessible_count']}",fontsize=9)
            ax.autoscale(); ax.set_aspect('equal'); ax.axis('off')
    fig.suptitle('W6 road access: original / round 1 / round 3\nRed = original roads; magenta = 4.5 m access lanes; blue = new buildings; green = primary open space',fontsize=13)
    fig.tight_layout(rect=(0,0,1,.95));fig.savefig(output/'comparison.png',dpi=180);plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--r1',type=Path,required=True)
    parser.add_argument('--r3',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    compare(dict(before=args.before,r1=args.r1,r3=args.r3),args.output)
