"""J17 deterministic brief adapter. Draft geometry only; no persistence or APIs.

Stations use the frozen facts' declared station length, proportionally mapped
onto its measured axis. Brief targets remain targets and never replace results.
"""
from __future__ import annotations

from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import unary_union
from . import block_first as bf

VERSION = 'j17-brief-driven-v3'


def _helpers():
    # Reuse the renderer's exact parent/child semantics and station partition.
    from scripts.s6_brief import _brief_segment_rows, _load_render_geometries, _slice_strip_geometry
    return _brief_segment_rows, _load_render_geometries, _slice_strip_geometry


def typology_ids(labels):
    canonical={'courtyard':('building.courtyard_closed',),'point':('building.point_tower',),'perimeter':('block.perimeter',),'courtyard_closed':('building.courtyard_closed',),'courtyard_open':('building.l_block',),'l_block':('building.l_block',),'slab':('building.i_slab',),'rowhouse':('building.rowhouse',),'maker_hall':('building.industrial_hall',),'point_tower':('building.point_tower',),'podium_tower':('building.podium_tower',)}
    result=[]
    for label in labels:
        if label in ('park','retained_reuse'):continue
        if label not in canonical:raise ValueError(f'unmapped canonical brief typology: {label!r}')
        result.extend(k for k in canonical[label] if k not in result)
    if not result:raise ValueError('empty brief typologies')
    return tuple(result)


def build_brief_structure(*, brief, facts, family, site, water, retained, entrances, fixed_roads,
                          network_rules, block_rules=None, zones=(), gfa_budget=None, dakpark=None):
    rows_fn,load,slice_geometry=_helpers()
    geo=load(facts); rows=rows_fn(brief)
    if facts['geometry'].get('crs')!='EPSG:28992':raise ValueError('brief requires EPSG:28992')
    if not site.equals_exact(geo['site'],1e-5):raise ValueError('brief/site facts geometry mismatch')
    axes=[]; segments=[]; public=[]; park_records=[]; failures=[]
    from shapely.ops import substring
    selected=brief.get('development_streets',[])
    if not selected:raise ValueError('brief development streets required')
    rules=block_rules or bf.BlockFirstRules()
    for strip_id in sorted({r['strip_id'] for r in rows}):
        if strip_id not in geo['axes'] or strip_id not in geo['strip_lengths']:raise ValueError('missing frozen strip axis '+strip_id)
        axis=geo['axes'][strip_id]; length=geo['strip_lengths'][strip_id]
        if axis.geom_type!='LineString' or length<=0:raise ValueError('invalid frozen strip axis')
        for j,street in enumerate(r for r in selected if r['strip_id']==strip_id):
            start,end=street['segment_m']
            if not 0<=start<end<=length:raise ValueError('development station outside frozen axis')
            line=substring(axis,start/length,end/length,normalized=True)
            axes.append(dict(id=f'{strip_id}-development-{j}',strip_id=strip_id,role='main',geometry=line,width_m=15.,intent_zh=street.get('reason_zh',family)))
        for row in [r for r in rows if r['strip_id']==strip_id]:
            start,end=map(float,row.get('segment_m',[0,length]))
            if not 0<=start<end<=length+1e-3:raise ValueError('brief station interval outside frozen axis')
            boundaries={start,end}
            for low in brief.get('height_strategy',{}).get('low_zones',[]):
                if low['strip_id']==strip_id:
                    boundaries.update(v for v in low['segment_m'] if start<v<end)
            max_length=max(block_length_range(row))
            count=max(1,__import__('math').ceil((end-start)/max_length))
            boundaries.update(start+(end-start)*i/count for i in range(1,count))
            cuts=sorted(boundaries)
            for a,b in zip(cuts,cuts[1:]):
                if row.get('floors')==[0,0] or all(t in ('park','retained_reuse') for t in row['typologies']):continue
                cell=slice_geometry(axis,geo['strips'][strip_id],a,b,length)
                segments.append(({**row,'segment_m':[a,b]},cell))
    # Existing roads and preselected development streets are immutable obstacles
    # to the park reservation. Public-space carving precedes land subdivision.
    road_obstacles=unary_union([LineString(r.coordinates).buffer(r.width_m/2+.001) for r in fixed_roads if r.layer==0])
    for index,park in enumerate(brief.get('open_spaces',[])):
        strip_id=park['strip_id']; axis=geo['axes'][strip_id]; length=geo['strip_lengths'][strip_id]
        start,end=map(float,park['segment_m']); target=float(park['area_m2_target'])
        domain=slice_geometry(axis,geo['strips'][strip_id],start,end,length).difference(road_obstacles).difference(unary_union(public))
        candidates=bf.parts(domain)
        if not candidates:failures.append(f'park_{index}_no_road_free_polygon');continue
        available=max(candidates,key=lambda p:(p.area,p.wkb_hex))
        # Grow an axis-centred reservation on the selected connected side; bisection
        # measures GEOS area, rather than assuming width times station length.
        centre=available.representative_point(); spine=substring(axis,start/length,end/length,normalized=True); lo=0.;hi=max(available.bounds[2]-available.bounds[0],available.bounds[3]-available.bounds[1])*2
        for _ in range(50):
            mid=(lo+hi)/2; pieces=bf.parts(spine.buffer(mid,cap_style=2,join_style=2).intersection(available)); candidate=max(pieces,key=lambda p:p.area,default=Point())
            if candidate.area<target:lo=mid
            else:hi=mid
        polygon=max(bf.parts(spine.buffer(hi,cap_style=2,join_style=2).intersection(available)),key=lambda p:p.area,default=Point())
        valid=polygon.geom_type=='Polygon' and .85*target<=polygon.area<=1.15*target and polygon.intersection(road_obstacles).area<1e-6
        if not valid:failures.append(f'park_{index}_target_or_single_polygon')
        if polygon.geom_type=='Polygon':public.append(polygon)
        park_records.append(dict(name_zh=park.get('name_zh'),type=park.get('type','park' if target>=20000 else 'plaza'),target_area_m2=target,area_m2=polygon.area,valid=valid,geometry=mapping(polygon)))
    transformations=[];routed_axes=[];parks=unary_union(public)
    for axis in axes:
        line=axis['geometry'];strip=geo['strips'][axis['strip_id']]
        protected=strip.difference(parks.buffer(axis['width_m']/2+.01))
        if line.buffer(axis['width_m']/2,cap_style=2).intersection(parks).area<=1e-6:
            routed_axes.append(axis);continue
        candidates=[]
        for offset in range(1,151):
            for side in ('left','right'):
                shifted=line.parallel_offset(offset,side,join_style=2)
                for part in bf.line_parts(shifted):
                    if protected.buffer(1e-6).covers(part) and part.buffer(axis['width_m']/2,cap_style=2).difference(strip).area<=.01:
                        candidates.append((offset,part.length,side,part))
            if candidates:break
        # The authored spine remains a shared path through the park. Service
        # streets may shift inside the same strip, preserving frozen stations.
        routed_axes.append({**axis,'id':axis['id']+'-park-path','role':'path','width_m':3.})
        if candidates:
            offset,_,side,shifted=min(candidates,key=lambda r:(r[0],r[1],r[2],r[3].wkb_hex))
            routed_axes.append({**axis,'geometry':shifted,'source_axis_geometry':mapping(line),'park_offset_m':offset,'park_offset_side':side})
            transformations.append(dict(road_id=axis['id'],strip_id=axis['strip_id'],method='SAME_STRIP_PARK_PROTECTED_PARALLEL_OFFSET',offset_m=offset,side=side,source_geometry=mapping(line),actual_geometry=mapping(shifted),source='BRIEF_DEVELOPMENT_STREET_STATIONS',status='DRAFT'))
        else:
            failures.append('development_street_no_same_strip_park_free_offset:'+axis['id'])
            transformations.append(dict(road_id=axis['id'],strip_id=axis['strip_id'],method='PARK_SHARED_PATH_ONLY',source_geometry=mapping(line),status='FAILED_SERVICE_OFFSET'))
    axes=routed_axes
    roads,development,_,network_failures=bf.roads_from_structure(axes,[],site,water,retained,entrances,fixed_roads,network_rules,rules,family=family,meta={},repair_multimodal=True,reserved_parks=public)
    # Later generated service routes may invalidate a reserved park; never conceal it.
    motor=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads if 'motor_vehicle' in r.modes and r.layer==0])
    for record,p in zip(park_records,public):
        record['valid']=park_target_gate(p,record['target_area_m2'],roads)
    for i,p in enumerate(public):
        if p.intersection(motor).area>1e-5:failures.append(f'park_{i}_motor_road_overlap')
    blocks=bf.strip_land_blocks(axes,roads,site,water,retained,network_rules,zones=zones,public=public)
    assigned=[];small_pieces=[];merged_remnants=[]
    for block in blocks:
        # Split full land blocks along authored segment boundaries before J12b.
        for row,cell in segments:
            for polygon in bf.parts(block['geometry'].intersection(cell)):
                if polygon.area<600:
                    small_pieces.append((block['id'],polygon));continue
                item={**block,'id':block['id']+f'-brief-{len(assigned)}','geometry':polygon,'strip_id':row['strip_id'],'segment_m':row.get('segment_m'),'type_preferences':typology_ids(row['typologies']),'floors':row.get('floors'),'wing_depth_m':row.get('wing_depth_m'),'frontage':row.get('frontage'),'block_dimensions_m':list(block_length_range(row))}
                for low in brief.get('height_strategy',{}).get('low_zones',[]):
                    if low['strip_id']==row['strip_id'] and low['segment_m'][0]<=axis_to_station(geo['axes'][row['strip_id']],polygon.representative_point(),geo['strip_lengths'][row['strip_id']])<=low['segment_m'][1]:
                        item['floor_cap']=max(low['floors']) if isinstance(low['floors'],list) else int(low['floors']);item['low_reason_zh']=low.get('reason_zh','brief low zone')
                assigned.append(item)
    for landmark in brief.get('height_strategy',{}).get('landmarks',[]):
        candidates=[b for b in assigned if b['strip_id']==landmark['strip_id'] and abs(sum(b['segment_m'])/2-landmark['station_m'])<=40]
        if candidates:
            block=min(candidates,key=lambda b:abs(sum(b['segment_m'])/2-landmark['station_m']))
            block['landmark_height_m']=min(float(landmark['height_m']),20.)
            if float(landmark['height_m'])>20:failures.append('landmark_brief_height_exceeds20')
    for source_id,piece in small_pieces:
        candidates=[b for b in assigned if b['id'].startswith(source_id+'-brief-') and b['geometry'].distance(piece)<1e-6]
        merged=False
        for neighbour in sorted(candidates,key=lambda b:-b['geometry'].boundary.intersection(piece.boundary).length):
            union=neighbour['geometry'].union(piece)
            if union.geom_type=='Polygon' and union.is_valid:
                neighbour['geometry']=union;merged=True
                failures.append('sub600_fragment_crosses_authored_segment_requires_review')
                break
        merged_remnants.append(dict(area_m2=piece.area,merged=merged,source_id=source_id))
        if not merged:failures.append('unmerged_sub600_land_fragment')
    return dict(family=family,axes=axes,blocks=assigned,roads=roads,development=development,public=public,failures=failures+network_failures,meta=dict(development_transformations=transformations,small_fragment_merge=merged_remnants,brief_parks=park_records,station_axes='FROZEN_FACTS_PROPORTIONAL_STATION',subdivision_method='BRIEF_SEGMENT_LAND_MINUS_ROADS_AND_PARKS'),block_rules=rules,brief_driven=True)


def generate_brief_driven(*, brief, facts, placer='j12b', **kwargs):
    structure=kwargs.pop('structure',None) or build_brief_structure(brief=brief,facts=facts,**{k:v for k,v in kwargs.items() if k in ('family','site','water','retained','entrances','fixed_roads','network_rules','block_rules','zones','gfa_budget','dakpark')})
    targets={r['strip_id']:float(r['gfa_m2']) for r in brief.get('gfa_allocation',{}).get('by_strip',[])}
    if 'development' in structure and 'family' in kwargs:
        kwargs.setdefault('candidate_selector',BriefBudgetSelector(structure['development'],targets=targets,family=kwargs['family'],blocks=structure['blocks'],entrances=kwargs['entrances'],centre=kwargs['site'].centroid))
    selector=kwargs.get('candidate_selector')
    if isinstance(selector,BriefBudgetSelector):
        from shapely.ops import substring
        geo=_helpers()[1](facts)
        selector.scopes=[]
        for row in _helpers()[0](brief):
            if row.get('floors')==[0,0] or all(t in ('park','retained_reuse') for t in row['typologies']):continue
            axis=geo['axes'][row['strip_id']];length=geo['strip_lengths'][row['strip_id']]
            start,end=row.get('segment_m',[0,length])
            for line in _scope_streets(row,structure,geo):
                selector.scopes.append(dict(strip_id=row['strip_id'],segment_m=[start,end],frontage=normalize_frontage(row.get('frontage','')),line=line))
    if placer == 'frontage':
        from .frontage_massing import generate_frontage_massing
        result = generate_frontage_massing(structure=structure, brief=brief, facts=facts, **kwargs)
        result['brief_frontage_selection'] = []
    else:
        result=bf.generate_block_first(structure=structure,**kwargs)
        result['brief_frontage_selection']=selector.frontage_selection if isinstance(selector,BriefBudgetSelector) else []
    allocation=brief.get('gfa_allocation',{}); targets={r['strip_id']:float(r['gfa_m2']) for r in allocation.get('by_strip',[])}
    totals={key:0. for key in targets};binding_checks=[];type_checks=[];floor_checks=[];measured_scale_checks=[]
    for building,feature in zip(result['buildings'],result['features']):
        geom=shape(feature['geometry']);block=max(structure['blocks'],key=lambda b:b['geometry'].intersection(geom).area,default=None)
        from types import SimpleNamespace
        profile=SimpleNamespace(geometry=geom,type_id=building['type_id'],wing_depth_m=building['scale']['wing_depth_m'],unit_count=building['scale'].get('unit_count'),unit_frontage_m=building['scale'].get('unit_frontage_m'))
        use='Manufacturing' if building['type_id']=='building.industrial_hall' else building['floors'][-1]['use']
        measured_scale_checks.append(measured_scale_gate(profile,use))
        bound=bool(block and block['geometry'].intersection(geom).area>=geom.area-.01)
        binding_checks.append(bound)
        type_checks.append(bound and building['type_id'] in block.get('type_preferences',(building['type_id'],)))
        count=len(building['floors']);floor_range=block.get('floors') if block else None
        cap=block.get('floor_cap') if block else None
        is_landmark_building = bool(block and 'landmark_height_m' in block and abs(building['height_m'] - block['landmark_height_m']) <= 0.5)
        floor_checks.append(bound and (count<=cap if (cap is not None and not is_landmark_building) else not floor_range or floor_range[0]<=count<=floor_range[1]))
        if block and block['strip_id'] in totals:totals[block['strip_id']]+=sum(shape(f['geometry']).area for f in building['floors'])
    result['checks']['brief_building_block_bindings']=bool(binding_checks) and all(binding_checks)
    result['checks']['brief_typologies']=bool(type_checks) and all(type_checks)
    result['checks']['brief_floor_ranges_and_low_caps']=bool(floor_checks) and all(floor_checks)
    result['checks']['brief_measured_scale']=bool(measured_scale_checks) and all(measured_scale_checks)
    actual_far=(sum(totals.values())+result['metrics']['retained_gfa_upper_m2'])/result['metrics']['far_denominator_m2']
    result['checks']['brief_far_range']=.7-1e-6<=actual_far<=.8+1e-6
    result['brief_parameter_overrides']=[dict(block_id=b['id'],parameter='first_floor_height_m',basis='DRAFT_BRIEF_LANDMARK_HEIGHT',target_total_height_m=b['landmark_height_m'],status='DRAFT_UNAPPROVED',original_value=kwargs.get('parameters',{}).get('first_floor_height_m',{}).get('value')) for b in structure['blocks'] if 'landmark_height_m' in b]
    for override in result['brief_parameter_overrides']:
        block=next(b for b in structure['blocks'] if b['id']==override['block_id'])
        match=max(zip(result['buildings'],result['features']),key=lambda pair:block['geometry'].intersection(shape(pair[1]['geometry'])).area,default=None)
        override['actual_first_floor_height_m']=match[0]['first_floor_height_m'] if match and block['geometry'].intersection(shape(match[1]['geometry'])).area>0 else None
    result['brief_allocation']=dict(targets_m2=targets,actual_m2=totals)
    result['checks']['brief_strip_gfa']=bool(targets) and all(.85*t<=totals[k]<=1.15*t for k,t in targets.items())
    result['checks']['brief_global_gfa']=sum(totals.values())<=min(float(allocation.get('new_gfa_budget_m2',77965.18)),77965.18)+1e-6
    result['checks']['brief_scale_depth_upper']=all(b['scale']['wing_depth_m'] <= {'Residential':14,'Mixed':16,'Office':18,'Manufacturing':40}.get('Manufacturing' if b['type_id']=='building.industrial_hall' else b['floors'][-1]['use'],14)+1e-6 for b in result['buildings'])
    normal=[b for b in result['buildings'] if b['floors'][-1]['use'] in ('Residential','Mixed') and not b.get('low_floor_reason_zh')]
    result['checks']['brief_residential_mixed_average_floors']=bool(normal) and sum(b['floor_count'] for b in normal)/len(normal)>=4
    landmark_results=[]
    for landmark in brief.get('height_strategy',{}).get('landmarks',[]):
        axis=shape(next(r['axis'] for r in facts['geometry']['strips'] if r['id']==landmark['strip_id']))
        length=next(r['length_m'] for r in facts['buildable']['strips'] if r['id']==landmark['strip_id'])
        distances=[]
        for building,feature in zip(result['buildings'],result['features']):
            footprint=shape(feature['geometry'])
            assigned=max(structure['blocks'],key=lambda block:block['geometry'].intersection(footprint).area,default=None)
            if not assigned or assigned['strip_id']!=landmark['strip_id']:continue
            interval=assigned.get('segment_m')
            projections=[axis_to_station(axis,Point(v),length) for v in footprint.exterior.coords]
            if max(projections)-min(projections)>80:continue
            station=axis_to_station(axis,footprint.representative_point(),length)
            distances.append((abs(station-landmark['station_m']),building))
        match=min(distances,key=lambda r:r[0],default=None)
        landmark_results.append(dict(strip_id=landmark['strip_id'],station_m=landmark['station_m'],actual_station_difference_m=match[0] if match else None,target_height_m=landmark['height_m'],actual_height_m=match[1]['height_m'] if match else None,valid=bool(match and match[0]<=40 and float(landmark['height_m'])<=20 and abs(match[1]['height_m']-float(landmark['height_m']))<=.5)))
    result['brief_landmarks']=landmark_results
    result['checks']['brief_landmarks']=all(r['valid'] for r in landmark_results)
    frontage_results=[]
    from shapely.ops import substring
    geo=_helpers()[1](facts)
    building_geometries=[dict(type_id=b['type_id'],geometry=shape(f['geometry'])) for b,f in zip(result['buildings'],result['features'])]
    for segment in _helpers()[0](brief):
        if segment.get('floors')==[0,0] or all(t in ('park','retained_reuse') for t in segment['typologies']):continue
        axis=geo['axes'][segment['strip_id']];length=geo['strip_lengths'][segment['strip_id']]
        start,end=segment.get('segment_m',[0,length]);lines=_scope_streets(segment,structure,geo)
        frontage=normalize_frontage(segment.get('frontage',''))
        frontage_results.append(dict(strip_id=segment['strip_id'],segment_m=[start,end],**scoped_frontage_assessment(lines,building_geometries,geo['buildable'],frontage)))
    result['brief_frontage']=frontage_results
    result['checks']['brief_frontage']=bool(frontage_results) and all(r['brief_frontage_gate'] for r in frontage_results)
    replaced=('development_bilateral_streetwall','defining_edge')
    result['legacy_frontage_checks']={key:result['checks'].get(key) for key in replaced}
    bilateral_rows=[r for r in frontage_results if r['brief_frontage']=='both_sides']
    single_rows=[r for r in frontage_results if r['brief_frontage']!='both_sides']
    result['checks']['development_bilateral_streetwall']=all(r['brief_frontage_gate'] for r in bilateral_rows)
    result['checks']['defining_edge']=all(r['brief_frontage_gate'] for r in single_rows)
    result['failure_reasons']=[reason for reason in result['failure_reasons'] if reason not in replaced]
    result['legacy_named_open_spaces']=result.get('named_open_spaces',[])
    result['named_open_spaces']=[dict(id=f'brief-open-space-{i}',name_zh=p['name_zh'],type=p.get('type','park'),area_m2=shape(p['geometry']).area,geometry=p['geometry'],target_area_m2=p['target_area_m2'],validation_status='VALID' if p['valid'] else 'INVALID',source='DRAFT_BRIEF') for i,p in enumerate(structure['meta']['brief_parks']) if p.get('geometry')]
    result['metrics']['brief_named_open_space_area_m2']=sum(p['area_m2'] for p in result['named_open_spaces'])
    result['metrics']['legacy_named_open_space_area_m2']=result['metrics'].get('named_open_space_area_m2')
    result['metrics']['named_open_space_area_m2']=result['metrics']['brief_named_open_space_area_m2']
    result['checks']['brief_park_targets']=bool(structure['meta']['brief_parks']) and all(p['valid'] for p in structure['meta']['brief_parks'])
    failures=[k for k,v in result['checks'].items() if not v]
    result['failure_reasons']=sorted(set(result['failure_reasons']+failures));result['status']='INVALID' if result['failure_reasons'] else 'VALID'
    result['brief_version']=VERSION
    return finalize_brief_metrics(result,brief)


def station_to_axis(axis, station_m, station_length_m):
    if station_length_m<=0 or not 0<=station_m<=station_length_m:raise ValueError('invalid frozen station')
    return axis.interpolate(station_m/station_length_m,normalized=True)


def axis_to_station(axis, point, station_length_m):
    if axis.length<=0 or station_length_m<=0:raise ValueError('invalid frozen axis')
    return axis.project(point)/axis.length*station_length_m


def strip_gfa_gate(actual, target, tolerance=.15):
    if target<=0 or actual<0 or not 0<=tolerance<=.15:return False
    return (1-tolerance)*target-1e-6<=actual<=(1+tolerance)*target+1e-6


def brief_drawing_guard(row):
    if row.get('brief_version')!=VERSION or not row.get('buildings'):raise ValueError('missing brief massing')
    roads=row.get('roads',row['structure'].get('roads',[]))
    motor=unary_union([LineString(r['coordinates']).buffer(r['width_m']/2) for r in roads if 'motor_vehicle' in r.get('modes',[]) and r.get('layer',0)==0])
    for park in row['structure']['meta']['brief_parks']:
        polygon=shape(park['geometry'])
        if polygon.geom_type!='Polygon':raise ValueError('INVALID park geometry')
    actual={k:0. for k in row['brief_allocation']['targets_m2']}
    blocks=row['structure']['blocks']
    for building,feature in zip(row['buildings'],row['features']):
        g=shape(feature['geometry']);block=max(blocks,key=lambda b:shape(b['geometry']).intersection(g).area)
        if len(building['floors'])!=building['floor_count'] or abs(sum(f['floor_height_m'] for f in building['floors'])-building['height_m'])>1e-6:raise ValueError('INVALID measured floor count or building height')
        if any(not g.buffer(1e-7).covers(shape(f['geometry'])) for f in building['floors']):raise ValueError('INVALID floor plate outside footprint')
        measured=sum(shape(f['geometry']).area for f in building['floors'])
        actual[block['strip_id']]+=measured
        from .context_massing import scale_check
        from types import SimpleNamespace
        profile=SimpleNamespace(geometry=g,type_id=building['type_id'],wing_depth_m=building['scale']['wing_depth_m'],unit_count=building['scale'].get('unit_count'),unit_frontage_m=building['scale'].get('unit_frontage_m'))
        use='Manufacturing' if building['type_id']=='building.industrial_hall' else building['floors'][-1]['use']
        if not measured_scale_gate(profile,use):raise ValueError('INVALID measured brief scale')
        if abs(g.area-building['footprint_area_m2'])>.01 or sum(f['floor_height_m'] for f in building['floors'])>20+1e-6:raise ValueError('INVALID measured brief building')
    if sum(actual.values())>77965.18+1e-6:raise ValueError('INVALID measured brief GFA')
    normal=[b for b in row['buildings'] if b['floors'][-1]['use'] in ('Residential','Mixed') and not b.get('low_floor_reason_zh')]
    if normal and sum(len(b['floors']) for b in normal)/len(normal)<4:raise ValueError('INVALID measured average floors')
    if abs(row['metrics']['far_denominator_m2']-183591.3)>.001:raise ValueError('INVALID user FAR denominator')
    far=(sum(actual.values())+row['metrics']['retained_gfa_upper_m2'])/row['metrics']['far_denominator_m2']
    if not .7-1e-6<=far<=.8+1e-6:raise ValueError('INVALID measured brief FAR')


def park_target_gate(polygon, target, roads):
    motor=unary_union([LineString(r.coordinates if hasattr(r,'coordinates') else r['coordinates']).buffer((r.width_m if hasattr(r,'width_m') else r['width_m'])/2) for r in roads if 'motor_vehicle' in (r.modes if hasattr(r,'modes') else r.get('modes',[])) and (r.layer if hasattr(r,'layer') else r.get('layer',0))==0])
    return polygon.geom_type=='Polygon' and polygon.is_valid and strip_gfa_gate(polygon.area,target) and polygon.intersection(motor).area<=1e-6


def scoped_frontage_assessment(lines, buildings, domain, frontage, rules=None, road_half=7.5):
    rules=rules or bf.BlockFirstRules()
    assessment=bf.frontage_assessment(lines,buildings,domain,rules,road_half=road_half)
    bilateral=frontage=='both_sides'
    ratio=assessment['qualified_bilateral_ratio'] if bilateral else assessment['defining_edge_ratio']
    return {**assessment,'brief_frontage':frontage,'brief_frontage_ratio':ratio,'brief_frontage_gate':ratio>=(.6 if bilateral else .7)}


class BriefBudgetSelector(bf.FrontageSelector):
    """Bound each strip before selecting; unmet capacity remains an explicit failure."""
    def __init__(self, development, *, targets, **kwargs):
        super().__init__(development,**kwargs);self.targets=targets;self.scopes=[];self.frontage_selection=[]

    def __call__(self, groups, budget, coverage):
        proposed=super().__call__(groups,min(budget,77965.18),coverage)
        totals={k:0. for k in self.targets};selected=[];used=set();gfa=area=0.
        def fits(option):
            strip=self.blocks[option['block_index']]['strip_id']
            cost=sum(p.area for p in option['plates'])
            if option['block_index'] in used or strip not in totals:return False
            if totals[strip]+cost>1.15*self.targets[strip]+1e-6 or gfa+cost>min(budget,77965.18)+1e-6 or area+option['profile'].geometry.area>coverage+1e-6:return False
            if option['profile'].type_id=='building.i_slab':
                for other in selected:
                    if other['profile'].type_id=='building.i_slab' and option['profile'].geometry.distance(other['profile'].geometry)<max(option['height'],other['height'])-1e-6:return False
            return True
        def take(option):
            nonlocal gfa,area
            strip=self.blocks[option['block_index']]['strip_id'];cost=sum(p.area for p in option['plates'])
            selected.append(option);used.add(option['block_index']);totals[strip]+=cost;gfa+=cost;area+=option['profile'].geometry.area
        flat=[o for group in groups for o in group]
        for scope in self.scopes:
            line=scope['line'];bilateral=scope['frontage']=='both_sides'
            eligible=[o for o in flat if self.blocks[o['block_index']]['strip_id']==scope['strip_id'] and o['profile'].type_id in bf.FACADE_TYPES and o['profile'].geometry.distance(line)<=18]
            masks={id(o):_frontage_masks(line,o['profile'].geometry) for o in eligible}
            def measure(options):
                sides={side:unary_union([piece for o in options for piece in masks.get(id(o),{}).get(side,[])]) for side in (-1,1)}
                one=sides[-1].union(sides[1]).length
                both=sides[-1].intersection(sides[1]).length
                return both if bilateral else one,one
            value,one=measure(selected)
            target=(.6 if bilateral else .7)*line.length
            while value+1e-6<target:
                choices=[]
                for option in eligible:
                    if not fits(option):continue
                    nxt,seed=measure(selected+[option])
                    gain=nxt-value;seed_gain=seed-one
                    if gain>1e-6 or (bilateral and seed_gain>1e-6):choices.append((gain,seed_gain,-sum(p.area for p in option['plates']),-option['block_index'],option))
                if not choices:break
                option=max(choices,key=lambda row:row[:-1])[-1];take(option);value,one=measure(selected)
            self.frontage_selection.append(dict(strip_id=scope['strip_id'],segment_m=scope['segment_m'],frontage=scope['frontage'],measured_frontage_m=value,target_frontage_m=target,satisfied=value+1e-6>=target))
        for option in proposed:
            if fits(option):take(option)
        return selected


def _frontage_masks(line, geometry):
    """Measured exterior edges projected on the real authored street."""
    import math
    sides={-1:[],1:[]}
    for polygon in bf.parts(geometry):
        coords=list(polygon.exterior.coords)
        for a,b in zip(coords,coords[1:]):
            edge=LineString([a,b])
            if edge.length<1:continue
            mid=edge.interpolate(.5,normalized=True);station=line.project(mid)
            tangent,_=bf._frame(line,station);origin=line.interpolate(station)
            side=tangent[0]*(mid.y-origin.y)-tangent[1]*(mid.x-origin.x)
            if abs(side)<.01 or abs(side)>18:continue
            if abs((b[0]-a[0])*tangent[0]+(b[1]-a[1])*tangent[1])/edge.length<math.sqrt(.5):continue
            start,end=sorted((line.project(Point(a)),line.project(Point(b))))
            if end-start>1e-6:sides[1 if side>0 else -1].append(LineString([(start,0),(end,0)]))
    return sides


def measured_scale_gate(profile, use):
    from .context_massing import scale_check
    result=scale_check(profile,use)
    return bool(result['valid'] and result['wing_depth_m'] <= {'Residential':14,'Mixed':16,'Office':18,'Manufacturing':40}[use]+1e-6)


def block_length_range(row):
    """Explicit authored block-length range; dimension dicts are not lengths."""
    value=row.get('block_length_m')
    if value is None:
        value=row.get('block_dimensions_m')
        if isinstance(value,dict):value=value.get('module_range',value.get('radial_block_module_range'))
    if value is None:value=[60,90]
    if not isinstance(value,(list,tuple)) or len(value)!=2 or any(not isinstance(v,(int,float)) or isinstance(v,bool) for v in value):raise ValueError('invalid brief block length range')
    low,high=map(float,value)
    if not 0<low<=high:raise ValueError('invalid brief block length bounds')
    return low,high


def normalize_frontage(text):
    if text=='both_sides':return 'both_sides'
    if any(v in text for v in ('one_side','single','單側','一側')):return 'single_side'
    import re
    affirmative=re.sub(r'(?:不做|不設|不採|未達|避免|不能|不宜)[^，；。]*?(?:雙側|兩側)','',text)
    return 'both_sides' if any(v in affirmative for v in ('兩側','雙側')) else 'single_side'


def _scope_streets(row, structure, geo):
    """Actual transformed development streets restricted by frozen station cells."""
    axis=geo['axes'][row['strip_id']];length=geo['strip_lengths'][row['strip_id']]
    start,end=row.get('segment_m',[0,length])
    if 'axes' not in structure:
        from shapely.ops import substring
        return [substring(axis,start/length,end/length,normalized=True)]
    mask=_helpers()[2](axis,geo['strips'][row['strip_id']],start,end,length)
    return [part for road in structure['axes'] if road.get('strip_id')==row['strip_id'] and road['role'] in ('main','service') for part in bf.line_parts(road['geometry'].intersection(mask))]


def finalize_brief_metrics(result, brief):
    """Pure read-back of an existing artifact into a new v3 result.

    Geometry, roads, building plates and inherited remnant checks are preserved.
    Legacy partition measurements are explicit diagnostics. Shared non-motor
    road surfaces inside authored public spaces count as public open ground.
    """
    from copy import deepcopy
    from scripts.s6_brief import _park_named_space
    from .network_massing_coupling import CouplingRules
    row=deepcopy(result)
    metrics=row['metrics'];checks=row['checks']
    affected=('largest_park','named_park_count','open_space_accounting')
    row['legacy_open_space_checks']={key:checks.get(key) for key in affected}
    for key in ('park_count','largest_park_m2','named_open_space_area_m2'):
        metrics['legacy_'+key]=metrics.get(key)
    # Keep preserved diagnostics when converting a v2 artifact whose published
    # names already changed but whose common count/largest fields did not.
    spaces=row.get('named_open_spaces',[])
    actual=[]
    for space in spaces:
        geometry=shape(space['geometry'])
        copy={**space,'area_m2':geometry.area,'is_park':_park_named_space(space)}
        actual.append(copy)
    row['named_open_spaces']=actual
    geometries=[shape(p['geometry']) for p in actual]
    named_union=unary_union(geometries)
    if 'open_space' not in row:
        checks['brief_open_space_readback_available']=False
        row['failure_reasons']=sorted(set(row.get('failure_reasons',[])+['brief_open_space_readback_available']))
        row['status']='INVALID';row['brief_version']=VERSION;row['brief_metric_readback_version']=VERSION
        return row
    ground=shape(row['open_space'])
    row['legacy_open_space_geometry']=row.get('legacy_open_space_geometry',row['open_space'])
    roads=row.get('roads',[])
    shared=unary_union([LineString(r['coordinates']).buffer(r['width_m']/2).intersection(named_union) for r in roads if r.get('layer',0)==0 and 'motor_vehicle' not in r.get('modes',[]) and {'pedestrian','bicycle'}.intersection(r.get('modes',[]))])
    # Explicitly recover surfaces excluded by the older road-inclusive ground
    # mask; this is an accounting classification, never geometry generation.
    reference=ground.union(shared)
    unallocated=reference.difference(named_union)
    row['brief_open_space_reference']=mapping(reference)
    row['brief_shared_path_open_space']=mapping(shared.difference(ground))
    row['unallocated_open_geometry']=mapping(unallocated)
    metrics['named_open_space_count']=len(actual)
    metrics['park_count']=sum(bool(p['is_park']) for p in actual)
    metrics['largest_park_m2']=max((p['area_m2'] for p in actual if p['is_park']),default=0.)
    metrics['named_open_space_area_m2']=sum(p['area_m2'] for p in actual)
    metrics['named_open_space_union_area_m2']=named_union.area
    metrics['unallocated_open_area_m2']=unallocated.area
    metrics['brief_open_space_reference_area_m2']=reference.area
    metrics['brief_shared_path_reclassified_area_m2']=shared.difference(ground).area
    metrics['brief_open_space_overlap_area_m2']=sum(p.area for p in geometries)-named_union.area
    metrics['brief_open_space_outside_reference_area_m2']=named_union.difference(reference).area
    metrics['brief_open_space_accounting_error_m2']=abs(named_union.area+unallocated.area-reference.area)
    row['brief_metric_definitions']={
        'park_count':'Count of authored named open spaces classified by s6_brief._park_named_space; count.',
        'named_open_space_count':'Count of all authored named parks and plazas; count.',
        'largest_park_m2':'Largest actual authored park polygon area; square metres.',
        'named_open_space_area_m2':'Sum of actual authored named polygon areas; square metres; overlap is checked separately.',
        'unallocated_open_area_m2':'Open reference minus authored named polygons; square metres; never named a park.',
        'brief_open_space_reference_area_m2':'Legacy measured open ground plus non-motor shared path surfaces within authored named polygons; square metres.',
    }
    rules=CouplingRules.model_validate(row.get('coupling',{}).get('rules',{}))
    checks['largest_park']=metrics['largest_park_m2']>=rules.largest_park_min_m2
    checks['named_park_count']=2<=len(actual)<=5
    checks['brief_named_open_space_count_matches_target']=len(actual)==len(brief.get('open_spaces',[]))
    checks['brief_named_open_spaces_nonoverlap']=metrics['brief_open_space_overlap_area_m2']<.01
    checks['brief_named_open_spaces_within_open_reference']=metrics['brief_open_space_outside_reference_area_m2']<.01
    checks['open_space_accounting']=metrics['brief_open_space_accounting_error_m2']<.01 and checks['brief_named_open_spaces_nonoverlap'] and checks['brief_named_open_spaces_within_open_reference']
    records=row.get('buildings',[]);features=row.get('features',[])
    checks['brief_floor_geometry_readback']=bool(records) and len(records)==len(features) and all(
        len(b['floors'])==b['floor_count'] and abs(sum(f['floor_height_m'] for f in b['floors'])-b['height_m'])<=1e-6 and
        all(shape(feature['geometry']).buffer(1e-7).covers(shape(f['geometry'])) for f in b['floors'])
        for b,feature in zip(records,features))
    new_gfa=sum(shape(f['geometry']).area for b in records for f in b['floors'])
    metrics['brief_floor_plate_gfa_readback_m2']=new_gfa
    checks['brief_new_gfa_metric_readback']=abs(new_gfa-metrics.get('new_gfa_m2',new_gfa))<=.01
    checks['brief_user_far_denominator']=abs(metrics['far_denominator_m2']-183591.3)<=.001
    actual_far=(new_gfa+metrics['retained_gfa_upper_m2'])/metrics['far_denominator_m2']
    metrics['brief_far_readback']=actual_far
    checks['brief_far_metric_readback']=abs(actual_far-metrics['far'])<=1e-7
    row['failure_reasons']=[reason for reason in row.get('failure_reasons',[]) if reason not in affected]
    row['failure_reasons']=sorted(set(row['failure_reasons']+[key for key,value in checks.items() if value is not True]))
    row['status']='INVALID' if row['failure_reasons'] else 'VALID'
    row['brief_version']=VERSION
    row['brief_metric_readback_version']=VERSION
    return row
