"""NET2 measurements against the complete same-mode before empirical CDF.

No reference percentages are constants. Source support remains receipt verified
by the segment builder. Water coverage must be explicitly demonstrated.
"""
from __future__ import annotations
from bisect import bisect_right
from statistics import median
import json
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree
from .fabric_syntax_segments import authored, verify

METHOD = ('Full same-mode before NAIN empirical CDF (right-inclusive, unweighted segment population). '
          'Named road NAIN is length weighted before CDF; alternative segment-percentile weighted mean retained. '
          'Proposal role groups use authored plus existing collinear after support (0.5m, 15 degrees; minimum coverage 0.90; conflicting overlaps locally averaged) with site-clipped role length-weighted NAIN then complete after CDF; original INT3 partial attribution retained diagnostically; reference and proposal are relative ranks in their respective complete mode networks. '
          'Water threshold is unweighted median of individual selected pedestrian before segment percentiles; '
          'segment distance to site <=1500m and to water <=20m. No winner or formal acceptance.')

def source_id(value):
    return value.removeprefix('proposal:existing:').split(':part:')[0].split(':uncovered:')[0]

def water_sample(full, plan, water):
    """A verified coverage polygon must cover the complete sampling envelope."""
    if not water:
        return [], 'No frozen water dataset with verified 1500m coverage supplied.'
    document=json.loads(verify(water['dataset']).read_text())
    coverage=json.loads(verify(water['coverage']).read_text())
    if document.get('crs',{}).get('properties',{}).get('name')!='EPSG:28992':
        raise ValueError('BLOCKED: water CRS must be EPSG:28992')
    coverage_crs=coverage.get('crs')
    if isinstance(coverage_crs,dict): coverage_crs=coverage_crs.get('properties',{}).get('name')
    if coverage_crs!='EPSG:28992':
        raise ValueError('BLOCKED: water coverage CRS must be EPSG:28992')
    area=shape(coverage['geometry'])
    site=shape(plan['site'])
    if not area.covers(site.buffer(1520)):
        return [], 'Frozen water acquisition coverage does not cover site buffer 1520m (1500m plus 20m search).'
    geometries=[shape(f['geometry']) for f in document['features']]
    if any(g.is_empty or not g.is_valid for g in geometries):
        raise ValueError('BLOCKED: invalid water geometry')
    water_geometry=unary_union(geometries)
    return [r for r in full['before']['segments']
            if LineString(r['coordinates']).distance(site)<=1500
            and LineString(r['coordinates']).distance(water_geometry)<=20], None

def baselines(full, plan, network, water=None):
    rows=full['before']['segments']; population=sorted(r['nain'] for r in rows)
    cdf=lambda value:100*bisect_right(population,value)/len(population) if population else None
    names={str(f['id']):str(f['properties'].get('name','')).casefold() for f in network['features']}
    result={}
    for key,name in [('primary_meets','Vierhavensstraat'),('primary_excellent','Keileweg')]:
        sample=[r for r in rows if names.get(source_id(r['source_line_id']))==name.casefold()]
        length=sum(LineString(r['coordinates']).length for r in sample)
        nain=sum(r['nain']*LineString(r['coordinates']).length for r in sample)/length if length else None
        result[key]={'reference':name,'percentile':cdf(nain) if nain is not None else None,
                     'nain':nain,'sample_count':len(sample),'length_m':length,'population_count':len(rows),
                     'alternative_length_weighted_segment_percentile':sum(cdf(r['nain'])*LineString(r['coordinates']).length for r in sample)/length if length else None,
                     'method':'length_weighted_named_road_nain_then_before_cdf',
                     'reason':None if sample else 'Named road absent from same-mode before network.'}
    sample,reason=water_sample(full,plan,water)
    result['waterfront_meets']={'reference':'OSM pedestrian before segments near frozen water','percentile':median([cdf(r['nain']) for r in sample]) if sample else None,
        'sample_count':len(sample),'population_count':len(rows),'method':'unweighted_median_before_segment_percentile','reason':reason or (None if sample else 'No segments satisfy 1500m site and 20m water filters.'),'source_receipts':water or {}}
    return result

def coextensive_support(target, line, distance_m=.001, angle_degrees=None):
    """Project positive parallel support; defaults retain the legacy 1mm check."""
    import math
    targets=[target] if target.geom_type=='LineString' else [g for g in getattr(target,'geoms',[]) if g.geom_type=='LineString']
    pieces=[]; offset=0.
    for part in targets:
        for a,b in zip(part.coords,list(part.coords)[1:]):
            dx=b[0]-a[0]; dy=b[1]-a[1]; length=math.hypot(dx,dy)
            if length<=1e-6: continue
            ux=dx/length; uy=dy/length
            for c,d in zip(line.coords,list(line.coords)[1:]):
                vx=d[0]-c[0]; vy=d[1]-c[1]; other=math.hypot(vx,vy)
                if other<=1e-6: continue
                cross=abs(ux*vy-uy*vx)
                if angle_degrees is None:
                    if cross>.001: continue
                elif cross/other>math.sin(math.radians(angle_degrees))+1e-12:
                    continue
                projections=[(p[0]-a[0])*ux+(p[1]-a[1])*uy for p in (c,d)]
                lateral=[(p[0]-a[0])*uy-(p[1]-a[1])*ux for p in (c,d)]
                t=sorted(projections)
                lo=max(0.,t[0]); hi=min(length,t[1])
                if angle_degrees is None:
                    if max(abs(v) for v in lateral)>distance_m+1e-9: continue
                elif hi>lo:
                    # Clip to the lateral distance band locally, rather than
                    # rejecting valid overlap because far endpoints drift away.
                    slope=(lateral[1]-lateral[0])/(projections[1]-projections[0])
                    if abs(slope)<1e-12:
                        if abs(lateral[0])>distance_m+1e-9: continue
                    else:
                        band=sorted(projections[0]+(v-lateral[0])/slope for v in (-distance_m,distance_m))
                        lo=max(lo,band[0]); hi=min(hi,band[1])
                if hi-lo>1e-6: pieces.append((offset+lo,offset+hi))
            offset+=length
    return pieces

def physical_role_score(full, plan, role):
    """Union authored support and existing parallel support on site-clipped roads.

    Each elementary overlap interval contributes its length once, with the mean
    of its active NAIN values (equal local support lengths). Road NAIN enters
    the full after CDF after pooling the supported lengths of the role.
    """
    rows=full.get('after',{}).get('segments',[])
    population=sorted(r['nain'] for r in rows)
    lines=[LineString(r['coordinates']) for r in rows]
    tree=STRtree(lines) if lines else None
    road_map={str(r['id']):r for r in plan.get('roads',[])}
    owners=[authored(r.get('source_line_id',''),road_map) for r in rows]
    site=shape(plan['site']); roads=[]; weighted_nain=0.; total=0.; supported=0.; errors=[]
    conflict_count=0
    method=('Authored source_line_id attribution plus existing collinear after segments '
            '(distance <=0.5m, direction difference <=15 degrees); site-clipped role union coverage >=0.90; '
            'overlap intervals use local length-weighted mean NAIN; pool role supported lengths '
            'for length-weighted NAIN then full after CDF (bisect_right).')
    for road in plan.get('roads',[]):
        if road['properties'].get('role')!=role: continue
        road_id=str(road['id'])
        target=shape(road['geometry']).intersection(site)
        length=target.length
        if length<=1e-6: continue
        pieces=[]
        candidates=set(int(i) for i in tree.query(target.buffer(.5),predicate='intersects')) if tree is not None else set()
        candidates.update(i for i,owner in enumerate(owners) if owner==road_id)
        for index in sorted(candidates):
            if owners[index]==road_id:
                # Provenance survives endpoint welding; project the authored
                # site's surviving pieces back to their own road chainage.
                clipped=lines[index].intersection(site).intersection(target.buffer(.5))
                parts=[clipped] if clipped.geom_type=='LineString' else [g for g in getattr(clipped,'geoms',[]) if g.geom_type=='LineString']
                intervals=[]
                for part in parts:
                    for a,b in zip(part.coords,list(part.coords)[1:]):
                        lo,hi=sorted((target.project(Point(a)),target.project(Point(b))))
                        if hi-lo>1e-6: intervals.append((lo,hi))
            elif (owners[index] is None
                  or road_map[owners[index]]['properties'].get('role')==role
                  or road_map[owners[index]]['properties'].get('source_id')
                  or road_map[owners[index]]['properties'].get('role','').startswith('retained_')):
                intervals=coextensive_support(target,lines[index],distance_m=.5,angle_degrees=15)
            else:
                continue
            # Union a segment's projected intervals so extra vertices cannot
            # give the same measurement extra weight on an overlap.
            merged=[]
            for lo,hi in sorted(intervals):
                if merged and lo<=merged[-1][1]+1e-9:
                    merged[-1]=(merged[-1][0],max(merged[-1][1],hi))
                else: merged.append((lo,hi))
            pieces.extend((lo,hi,rows[index]['nain'],rows[index].get('id',str(index))) for lo,hi in merged)
        cuts=sorted(set(x for lo,hi,_,_ in pieces for x in (lo,hi)))
        support_length=0.; nain_sum=0.; conflicts=set(); road_conflicts=0
        for lo,hi in zip(cuts,cuts[1:]):
            middle=(lo+hi)/2
            active=[(nain,ident) for a,b,nain,ident in pieces if a<middle<b]
            if active:
                support_length+=hi-lo
                nain_sum+=(hi-lo)*sum(n for n,_ in active)/len(active)
                if len(set(n for n,_ in active))>1:
                    road_conflicts+=1
                    conflicts.update(ident for _,ident in active)
        missing=max(0.,length-support_length)
        coverage=min(1.,support_length/length)
        valid=coverage>=.90 and support_length>1e-6 and bool(population)
        nain=nain_sum/support_length if support_length>1e-6 else None
        percentile=100*bisect_right(population,nain)/len(population) if valid else None
        reason=method if valid else f'Role road coverage {coverage:.6f} below required 0.90, or no after population/support.'
        roads.append({'road_id':road_id,'expected_length_m':length,'support_length_m':support_length,
                      'missing_length_m':missing,'coverage':coverage,'nain':nain,
                      'percentile':percentile,'support_segment_ids':sorted(set(i for _,_,_,i in pieces)),
                      'conflicting_segment_ids':sorted(conflicts),'conflict_interval_count':road_conflicts,
                      'reason':reason,'status':'COMPUTED' if valid else 'UNAVAILABLE'})
        total+=length; supported+=support_length; conflict_count+=road_conflicts
        weighted_nain+=nain_sum
        if not valid: errors.append(road_id)
    coverage=min(1.,supported/total) if total else None
    valid=coverage is not None and coverage>=.90 and supported>1e-6 and bool(population)
    nain=weighted_nain/supported if supported>1e-6 else None
    return {'percentile':100*bisect_right(population,nain)/len(population) if valid else None,
            'nain':nain,
            'status':'COMPUTED' if valid else 'UNAVAILABLE',
            'expected_length_m':total,'support_length_m':supported,'coverage':coverage,
            'conflict_interval_count':conflict_count,'roads':roads,'unavailable_road_ids':errors,
            'reason':method if valid else (f'Whole-role attribution unavailable: coverage {coverage:.6f}; '
                      'required role coverage >=0.90 and nonempty after population/support; see road reasons.' if total else 'Whole-role attribution unavailable: no site-clipped role geometry; coverage unavailable.')}

def assess(full,plan,network,report,joins=None,water=None,added_road_ids=None):
    mode=report['mode']; baseline=baselines(full,plan,network,water if mode=='pedestrian' else None)
    def score(role):
        intent=next((r for r in report['intents'] if r['intent_en']==role),{})
        return intent.get('percentile')
    checks=[]
    for role,key in ([('primary_street','primary_meets')]+([('waterfront_path','waterfront_meets')] if mode=='pedestrian' else [])) if mode in ('pedestrian','bicycle') else []:
        attribution=physical_role_score(full,plan,role)
        value=attribution['percentile']; threshold=baseline[key]['percentile']; excellent=baseline['primary_excellent']['percentile'] if role=='primary_street' else None
        unavailable=value is None or threshold is None
        checks.append({'target':role,'metric':'whole_physical_role_group_after_cdf_percentile','value':value,'minimum':threshold,'excellent_minimum':excellent,
            'status':'UNAVAILABLE' if unavailable else 'PASS' if value>=threshold else 'FAIL',
            'grade':None if unavailable else '優' if excellent is not None and value>=excellent else '符合' if value>=threshold else '不符合',
            'diagnostic_int3_percentile':score(role),'physical_role_support':attribution,
            'reason':attribution['reason']+' '+(baseline[key].get('reason') or '')})
    if mode in ('pedestrian','bicycle'):
        for target in ('connection Keileweg','connection Dakpark'):
            intent=next((r for r in report['intents'] if r['intent_en']==target),{})
            ids=intent.get('direct_join_road_ids',[])
            if added_road_ids is not None: ids=[i for i in ids if i in added_road_ids]
            unavailable=not intent or intent.get('status')=='unavailable'
            checks.append({'target':target,'metric':'direct_join_road_count','value':None if unavailable else len(ids),'minimum':1,'direct_join_road_ids':ids,'status':'UNAVAILABLE' if unavailable else 'PASS' if ids else 'FAIL'})
        checks.append({'target':'waterfront multiple joins','metric':'unique_geometric_same_mode_junction_count','value':len(joins or []),'minimum':2,'status':'PASS' if len(joins or [])>=2 else 'FAIL','coordinates_rd_m':joins or []})
    status='DESCRIPTIVE_ONLY' if not checks else 'UNAVAILABLE' if any(c['status']=='UNAVAILABLE' for c in checks) else 'PASS' if all(c['status']=='PASS' for c in checks) else 'FAIL'
    return {'schema_version':'net2-assessment-v1','fabric_id':report['fabric_id'],'mode':mode,'baselines':baseline,'checks':checks,'status':status,'hard_targets_pass':all(c['status']=='PASS' for c in checks) if checks else None,'descriptive_intents':report['intents'],'method':METHOD,'formal_result_eligible':False}
