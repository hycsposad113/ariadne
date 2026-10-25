"""Explicit FAB road semantics and compact exploratory PST evidence."""
from shapely.geometry import LineString, Point, shape
from shapely.ops import substring
from . import scenario_syntax as ss

MODE_MAPPING = {'pedestrian':'pedestrian', 'bicycle':'bicycle', 'car':'motor_vehicle'}

RETAINED_SUPPORT_TOLERANCE_M = 0.001

def positive_support_diff(before, after, epsilon=1e-6):
    """NET1 postprocessor: sub-epsilon support has no comparable baseline.

    PST metrics and topology are unchanged. Keep the short rows and null delta;
    do not divide by zero or imply matched support where no overlap exists.
    """
    substantial = [r for r in after if LineString(r['coordinates']).length > epsilon]
    result = ss.segment_diff(before, substantial, epsilon)
    for row in after:
        if LineString(row['coordinates']).length <= epsilon:
            result.append({**row, 'before': None, 'after': {k: row[k] for k in ('nain', 'nach')},
                           'delta': None, 'comparison_status': 'NEW_OR_CHANGED_GEOMETRY'})
    return result

def proposal_roads(plan, external, *, mode=None, receipts=None):
    if plan.get('crs') != 'EPSG:28992':
        raise ValueError('BLOCKED: FAB CRS must be EPSG:28992')
    roads=[]
    for f in plan['roads']:
        p=f['properties']; modes=p.get('modes')
        if not modes or set(modes)-set(MODE_MAPPING)-{'service','fire'}:
            raise ValueError('BLOCKED: missing or unsupported explicit FAB modes')
        roads.append(ss.ProposalRoad(id=f['id'], coordinates=f['geometry']['coordinates'], width_m=p['width_m'],
          modes=[MODE_MAPPING[m] for m in modes if m in MODE_MAPPING], origin='new',
          semantics_provenance='FAB1 explicit modes; car=motor_vehicle; service/fire not evaluated'))
    for f in plan['retained_road_inputs']:
        modes=[m for m,features in external.items() if any(x['id']==f['id'] for x in features)]
        if not modes: raise ValueError('BLOCKED: retained source missing from mode extracts: '+f['id'])
        if mode is not None and mode not in modes: continue
        selected_modes=[mode] if mode else modes
        sources=[]
        authored=shape(f['geometry'])
        for m in selected_modes:
            source=next(x for x in external[m] if x['id']==f['id'])
            verified=shape(source['geometry'])
            # FAB roads may be clipped portions of an OSM way. Test the whole
            # authored support, not symmetric distance to the uncut source.
            supported=verified.buffer(RETAINED_SUPPORT_TOLERANCE_M).covers(authored)
            record={'source_road_id':f['id'],'mode':m,'tolerance_m':RETAINED_SUPPORT_TOLERANCE_M,
                'plan_length_m':authored.length,'source_length_m':verified.length,
                'hausdorff_distance_m':authored.hausdorff_distance(verified),
                'max_vertex_distance_m':max(verified.distance(Point(c)) for c in authored.coords),
                'corresponding_source_interval_length_m':substring(verified,verified.project(Point(authored.coords[0])),verified.project(Point(authored.coords[-1]))).length,
                'corresponding_interval_hausdorff_distance_m':authored.hausdorff_distance(substring(verified,verified.project(Point(authored.coords[0])),verified.project(Point(authored.coords[-1])))),
                'outside_tolerance_support_length_m':authored.difference(verified.buffer(RETAINED_SUPPORT_TOLERANCE_M)).length,
                'supported':supported,'action':'SNAP_TO_VERIFIED_SOURCE' if supported else 'BLOCKED',
                'plan_geometry_sha256':ss.digest(f['geometry']),'source_geometry_sha256':ss.digest(source['geometry'])}
            if receipts is not None: receipts.append(record)
            if not supported: raise ValueError('BLOCKED: retained geometry mismatch: '+f['id'])
            sources.append(source)
        # Different mode extracts can clip a way differently; callers must select
        # a mode in that case rather than invent one shared retained geometry.
        source=sources[0]
        if any(not shape(x['geometry']).equals_exact(shape(source['geometry']),1e-6) for x in sources[1:]):
            raise ValueError('BLOCKED: retained sources differ across modes; select mode')
        roads.append(ss.ProposalRoad(id='existing:'+f['id'],coordinates=source['geometry']['coordinates'],
          width_m=10 if 'motor_vehicle' in modes else 4.5,modes=selected_modes,origin='retained',source_road_ids=[f['id']],
          layer=int(source['properties'].get('layer') or 0),
          semantics_provenance='MODE_EXTRACT_SOURCE; whole authored support verified within 0.001m then snapped to immutable source; clipped source ID retains full source context; J17 width assumption, not used by PST'))
    return roads

def compact_result(result, site, roads=()):
    compact={k:v for k,v in result.items() if k not in ('before','after','diff','merge')}
    compact['merge']={k:v for k,v in result.get('merge',{}).items() if k not in ('removed','snaps','connection_points')}
    for phase in ('before','after'):
        data=result.get(phase)
        if data is None: compact[phase]=None;continue
        metrics=dict(data['metrics']); threshold=metrics['high_threshold_nain']
        metrics['high_integration_length_m']=sum(LineString(r['coordinates']).intersection(site).length for r in data['segments'] if r['nain']>threshold)
        metrics['high_integration_length_scope']='Site-clipped segment length above fixed baseline context q60 NAIN; metres, not whole-context length'
        compact[phase]={'metrics':metrics}
    b,a=compact.get('before'),compact.get('after')
    bm=b['metrics']['mean_integration_nain'] if b else None; am=a['metrics']['mean_integration_nain'] if a else None
    compact['delta_mean_integration_nain']=am-bm if am is not None and bm is not None else None
    # Exact authored IDs are the authority for newness; transformed retained
    # geometry also has a proposal prefix after merging and must be excluded.
    new_ids={r.id for r in roads if r.origin=='new'}
    groups={}
    for row in (result.get('after') or {}).get('segments',[]):
        identifier=row['source_line_id']
        if not identifier.startswith('proposal:') or not row['inside_site']: continue
        authored=identifier.removeprefix('proposal:')
        matches=[identity for identity in new_ids if authored in (identity,identity+'_a',identity+'_b') or authored.startswith(identity+':part:') or authored.startswith(identity+':uncovered:')]
        if not matches: continue
        identity=max(matches,key=len)
        length=LineString(row['coordinates']).intersection(site).length
        if length<=1e-6: continue
        group=groups.setdefault(identity,{'road_id':identity,'nain_weighted':0.,'nach_weighted':0.,'inside_length_m':0.,'segment_count':0})
        group['nain_weighted']+=row['nain']*length;group['nach_weighted']+=row['nach']*length
        group['inside_length_m']+=length;group['segment_count']+=1
    ranked=[dict(road_id=g['road_id'],nain=g['nain_weighted']/g['inside_length_m'],nach=g['nach_weighted']/g['inside_length_m'],inside_length_m=g['inside_length_m'],segment_count=g['segment_count']) for g in groups.values()]
    compact['new_street_ranking']=sorted(ranked,key=lambda r:(-r['nain'],r['road_id']))
    compact['new_street_ranking_method']='All genuinely new authored streets with measured interior support; site-length-weighted NAIN/NACH across split source lines; no truncation'
    compact['new_street_ranking_count']=len(ranked)
    compact['new_street_ranking_truncated']=False
    return compact
