#!/usr/bin/env python3
"""Independent offline geometry audit and exact candidate-hash replay check."""
import argparse
import hashlib
import json
from pathlib import Path

from shapely import affinity
from shapely.geometry import Point, shape
from shapely.ops import unary_union


def audit(first, second, output, database):
    from urban_design.store import ProjectStateStore
    from urban_design.approved_generation import _load_approved_inputs
    database=database.resolve(strict=True)
    if '.urban_design_runtime' in database.parts:
        raise ValueError('runtime databases prohibited')
    db_hash=hashlib.sha256(database.read_bytes()).hexdigest()
    with ProjectStateStore(database,read_only=True) as store:
        inputs=_load_approved_inputs(store,store.list_current('Project')[0].entity_id,site_generation=True)
        waterfront=inputs.water_geometry.buffer(15)
        land=inputs.design_area.difference(inputs.water_geometry)
    a, b = (json.loads(p.read_text()) for p in (first, second))
    replay = {c['recipe_id']:c['result_hash'] for c in a['candidates']} == {c['recipe_id']:c['result_hash'] for c in b['candidates']}
    rows = []
    for c in a['candidates']:
        features = c['geometry']['features']
        skeleton = c['stages']['skeleton']
        edges = skeleton['edges']
        nodes = {n['id']:Point(n['geometry']['coordinates']) for n in skeleton['nodes']}
        roads = unary_union([shape(e['geometry']).buffer(e['width_m']/2) for e in edges])
        buildings = [shape(f['geometry']) for f in features if f['properties']['role']=='new_building']
        distances = [max(p.distance(roads) for p in (g.geoms if g.geom_type=='MultiPolygon' else (g,))) for g in buildings]
        retained = unary_union([shape(f['geometry']).buffer(3) for f in features if f['properties']['role']=='retained'])
        spaces = unary_union([shape(s['geometry']) for s in skeleton['primary_open_spaces']])
        new = [e for e in edges if e['id'].startswith(('road:south_strip_collector:', 'road:south_strip_connector:'))]
        collector_surface = unary_union([shape(e['geometry']).buffer(e['width_m']/2) for e in new])
        # The row keeps the pre-fallback collector pieces, so inspect the full
        # undivided main section rather than a noded mid-edge fragment.
        main = [shape(p['geometry']) for p in c.get('south_strip_collector_paths', []) if p['role']=='south_strip_collector']
        aligned = all(abs(affinity.rotate(g, -c['orientation_deg'], origin=(0,0)).bounds[3] -
                          affinity.rotate(g, -c['orientation_deg'], origin=(0,0)).bounds[1]) < 1e-5 for g in main)
        adjacency = {}
        for e in edges:
            u,v = e['from_node_id'],e['to_node_id']
            adjacency.setdefault(u,set()).add(v); adjacency.setdefault(v,set()).add(u)
        original_nodes = {e[k] for e in edges if not e['id'].startswith(('road:south_strip_', 'road:access_lane:')) for k in ('from_node_id','to_node_id')}
        def reaches_original(start):
            visited=set(); pending=[start]
            while pending:
                node=pending.pop()
                if node in original_nodes: return True
                if node in visited: continue
                visited.add(node); pending.extend(adjacency.get(node,()))
            return False
        m=c['metrics']
        checks = dict(valid=c['status']=='VALID', access=bool(distances) and max(distances)<=40,
            far=.70<=m['far'], land_denominator=m['far_denominator']=='land_area',
            open_space=m['open_space_ratio']>=.4, types=len(m['dictionary_types'])>=4,
            zones=all(z['assigned_new_gfa_m2']>0 for z in m['zone_uses']),
            collector_present=c['family']=='CONNECTED_GRID' or bool(main), collector_aligned=aligned,
            collector_retained_clear=collector_surface.intersection(retained).area<1e-6,
            collector_primary_clear=collector_surface.intersection(spaces).area<1e-6,
            collector_waterfront_clear=collector_surface.intersection(waterfront).area<1e-6,
            collector_site_containment=collector_surface.difference(land).area<1e-6,
            collector_connected=all(reaches_original(e[k]) for e in new for k in ('from_node_id','to_node_id')),
            endpoint_nodes=all(Point(shape(e['geometry']).coords[index]).distance(nodes[e[k]])<1e-7
                for e in edges for index,k in ((0,'from_node_id'),(-1,'to_node_id'))),
            fallback_width=all(p['width_m']==4.5 for p in c.get('access_lane_paths',[])))
        rows.append(dict(recipe_id=c['recipe_id'],checks=checks,building_count=len(buildings),
            max_distance_m=max(distances),collector_length_m=sum(g.length for g in main),
            collector_and_connectors_length_m=sum(shape(e['geometry']).length for e in new),
            access_lane_length_m=sum(shape(p['geometry']).length for p in c.get('access_lane_paths',[]))))
    result=dict(status='PASS' if a['status']==b['status']=='READY' and replay and len(rows)==5 and all(all(r['checks'].values()) for r in rows) else 'FAIL',
        database=dict(path=str(database),access='READ_ONLY',sha256_before=db_hash,
            sha256_after=hashlib.sha256(database.read_bytes()).hexdigest()),
        replay_hashes_equal=replay, candidate_hashes={c['recipe_id']:c['result_hash'] for c in a['candidates']},
        sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (first,second)},rows=rows)
    with output.open('x') as stream:
        json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first',type=Path,required=True)
    parser.add_argument('--second',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--database',type=Path,required=True)
    args=parser.parse_args()
    raise SystemExit(audit(args.first,args.second,args.output,args.database))
