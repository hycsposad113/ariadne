"""Copy-only S6 context massing. DRAFT cards are not activated constraints."""
from itertools import combinations
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator
from shapely.geometry import LineString, Point, Polygon, shape, mapping, box
from shapely.ops import unary_union, nearest_points
from .type_registry import generate_block_profile, generate_streetwall_profile, block_scale_capabilities
from urban_design.morphology.block_massing import fit_envelopes, rectangular_size, convex_clear_width

VERSION = 'j12b-height-first-v2'
FAMILIES = ('radial','axial','grid','green_service')


class S6Rules(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    status: Literal['DRAFT']='DRAFT'
    provenance: Literal['ASSUMED_COMMANDER']='ASSUMED_COMMANDER'
    residential_depth_m: FiniteFloat=Field(default=12,ge=10,le=14)
    mixed_depth_m: FiniteFloat=Field(default=14,ge=12,le=16)
    office_depth_m: FiniteFloat=Field(default=16,ge=14,le=18)
    maker_depth_m: FiniteFloat=Field(default=24,ge=20,le=40)
    courtyard_min_m: FiniteFloat=Field(default=20,ge=20)
    node_radius_m: FiniteFloat=Field(default=35,gt=0)
    context_radius_m: FiniteFloat=Field(default=40,gt=0)
    dakpark_radius_m: FiniteFloat=Field(default=100,gt=0)
    street_setback_m: FiniteFloat=Field(default=1,ge=.25)
    height_tv_min: FiniteFloat=Field(default=.08,ge=0,le=1)
    open_space_difference_min: FiniteFloat=Field(default=.08,ge=0,le=1)
    ground_use_difference_min: FiniteFloat=Field(default=.08,ge=0,le=1)


class ContextEdge(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    kind: Literal['dakpark','waterfront','transit']
    geometry: dict
    crs: Literal['EPSG:28992']='EPSG:28992'
    source_ref: str=Field(min_length=1)
    elevation_difference_m: FiniteFloat | None=None

    @field_validator('geometry')
    @classmethod
    def valid_geometry(cls,value):
        import shapely
        g=shape(value)
        if g.is_empty or not g.is_valid or any(not math.isfinite(v) for xy in shapely.get_coordinates(g) for v in xy):
            raise ValueError('context geometry must be finite, valid and nonempty')
        return value


class BuildingIntent(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    rule_card_ids: tuple[str,...]
    knowledge_unit_ids: tuple[str,...]
    syntax_nain: FiniteFloat=Field(ge=0)
    syntax_percentile: FiniteFloat=Field(ge=0,le=100)
    syntax_segment_ids: tuple[str,...]
    syntax_mode: Literal['pedestrian']='pedestrian'
    syntax_radius_m: Literal[800]=800
    node_distance_m: FiniteFloat | None=None
    entrance_distance_m: FiniteFloat | None=None
    context_response: tuple[str,...]=()
    reason_zh: str
    reason_en: str
    provenance: Literal['ASSUMED_COMMANDER']='ASSUMED_COMMANDER'


def depth_minimum(use):
    return {'Residential':10.,'Mixed':12.,'Office':14.,'Manufacturing':20.}[use]


def scale_check(profile,use):
    """Measure geometry independently of authored depth/area labels."""
    g=profile.geometry;short,long=rectangular_size(g)
    measured=short;court=None
    if profile.type_id in ('block.perimeter','building.courtyard_closed'):
        if not isinstance(g,Polygon) or len(g.interiors)!=1:
            return {'valid':False,'failures':['court_missing'],'wing_depth_m':None,'area_m2':g.area}
        inner=Polygon(g.interiors[0]);court=convex_clear_width(inner)
        measured=g.exterior.distance(inner.exterior)
    elif profile.type_id=='building.l_block':
        # For orthogonal L polygons, shortest edge is an independently measured wing.
        cs=list(g.exterior.coords);measured=min(math.dist(a,b) for a,b in zip(cs,cs[1:]))
    minimum={'block.perimeter':1200.,'building.courtyard_closed':1200.,'building.l_block':600.,
             'building.i_slab':300.,'building.rowhouse':324.,'building.point_tower':400.,
             'building.podium_tower':400.,'building.industrial_hall':600.}[profile.type_id]
    failures=[]
    if not g.is_valid or g.is_empty:failures.append('invalid_geometry')
    if measured < depth_minimum(use)-1e-6:failures.append('wing_depth')
    if abs(measured-profile.wing_depth_m)>1e-5:failures.append('declared_depth_mismatch')
    if g.area<minimum-1e-6:failures.append('type_area_minimum')
    if profile.type_id in ('block.perimeter','building.courtyard_closed') and (short<40-1e-6 or court<20-1e-6):failures.append('courtyard_size')
    if profile.type_id=='building.i_slab' and not 30-1e-6<=long<=80+1e-6:failures.append('slab_length')
    if profile.type_id in ('building.point_tower','building.podium_tower') and g.area>900+1e-6:failures.append('point_area_maximum')
    if profile.type_id=='building.rowhouse' and (profile.unit_count is None or not 6<=profile.unit_count<=20 or not 5.4<=profile.unit_frontage_m<=7.2 or not 10-1e-6<=measured<=12+1e-6):failures.append('rowhouse_dimensions')
    return dict(valid=not failures,failures=failures,wing_depth_m=measured,area_m2=g.area,
                area_minimum_m2=minimum,depth_minimum_m=depth_minimum(use),courtyard_width_m=court,outer_short_m=short,outer_long_m=long)


def syntax_inputs(document,roads,rules,site):
    from . import multimodal_network as net
    from urban_design.scenario_syntax import digest
    if document.get('status')!='COMPUTED' or document.get('mode')!='pedestrian' or document.get('radius_m')!=800:
        raise ValueError('computed pedestrian 800m Syntax required')
    if document.get('road_input_sha256')!=digest([r.model_dump() for r in net.syntax_roads(roads,'pedestrian',rules)]):
        raise ValueError('Syntax road hash mismatch')
    if document.get('site_sha256')!=digest(mapping(site)):
        raise ValueError('Syntax site hash mismatch')
    rows=document['after']['segments']
    # Same J11 strict source-ID/geometry relationship tolerance (1mm).
    lookup={r.id:r for r in roads}
    for row in rows:
        value=row['nain']
        if isinstance(value,bool) or not math.isfinite(value) or value<0:raise ValueError('invalid Syntax value')
        source=row.get('source_line_id','')
        if source.startswith('proposal:'):
            identity=source[9:].split(':part:')[0]
            if identity not in lookup and identity.endswith(('_a','_b')):identity=identity[:-2]
            parent=lookup.get(identity)
            if parent is None or LineString(row['coordinates']).difference(LineString(parent.coordinates).buffer(.001)).length>1e-6:
                raise ValueError('Syntax source/geometry mismatch')
    inside=[r for r in rows if r['inside_site']]
    if not inside:raise ValueError('no site Syntax segments')
    return inside,sorted(r['nain'] for r in rows)


def local_syntax(geometry,rows,distribution):
    distances=[(LineString(r['coordinates']).distance(geometry),r) for r in rows]
    nearest=min(d for d,r in distances)
    selected=[r for d,r in distances if d<=min(nearest+3,25)+1e-6]
    if not selected:raise ValueError('building has no adjacent Syntax within25m')
    weights=[LineString(r['coordinates']).length for r in selected]
    value=sum(r['nain']*w for r,w in zip(selected,weights))/sum(weights)
    rank=100*sum(v<=value for v in distribution)/len(distribution)
    return value,rank,tuple(r['id'] for r in selected)


def context_floors(family,rank,node_distance,use,context_kinds,*,node_radius_m=35):
    node=node_distance is not None and node_distance<=node_radius_m
    if use=='Manufacturing':return 1
    if 'dakpark' in context_kinds:return 3
    # Height first. Quiet interior still has four floors; no low-Syntax excuse
    # for two-storey residential massing. Landmarks use relative height.
    if family=='radial':return 5 if node or rank>=70 else 4
    if family=='axial':return 5 if rank>=65 or 'transit' in context_kinds else 4
    if family=='grid':return 5 if rank>=50 else 4
    return 5 if rank>=70 else 4


def proposals_for_block(block,use,family,rules,*,accessible=None):
    """Single building/group per block; large blocks get enlarged courts."""
    domain=block.buffer(-rules.street_setback_m,join_style=2)
    if domain.geom_type!='Polygon':return []
    depth={'Residential':rules.residential_depth_m,'Mixed':rules.mixed_depth_m,'Office':rules.office_depth_m,'Manufacturing':rules.maker_depth_m}[use]
    options=[]
    if use!='Manufacturing':
        try:options.append(generate_streetwall_profile(block,wing_depth_m=depth,setback_m=rules.street_setback_m))
        except ValueError:pass
    if use!='Manufacturing':
        for envelope in fit_envelopes(domain,accept=accessible):
            type_id='block.perimeter' if family in ('axial','grid') else 'building.courtyard_closed'
            try:
                options.append(generate_block_profile(type_id,envelope,wing_depth_m=depth))
                options.append(generate_block_profile('building.l_block',envelope,wing_depth_m=depth))
            except ValueError: pass
    type_id='building.industrial_hall' if use=='Manufacturing' else 'building.rowhouse' if family=='green_service' and use=='Residential' else 'building.i_slab'
    bar_depth=min(depth,12) if type_id=='building.rowhouse' else depth
    depths=(bar_depth,20.) if use=='Manufacturing' and bar_depth!=20 else (bar_depth,)
    for actual_depth in depths:
        for envelope in fit_envelopes(domain,depth_m=actual_depth,max_length_m=80,accept=accessible):
            try:options.append(generate_block_profile(type_id,envelope,wing_depth_m=actual_depth))
            except ValueError:pass
    # Mid-rise point and podium types retain the 400-900m2 footprint envelope.
    if use!='Manufacturing':
        for envelope in fit_envelopes(domain,depth_m=20,max_length_m=44,min_length_m=20,accept=accessible):
            try:options.append(generate_block_profile('building.point_tower' if family!='axial' else 'building.podium_tower',envelope,wing_depth_m=20))
            except ValueError:pass
    return [p for p in options if scale_check(p,use)['valid']]


def generate_massing(*,family,blocks,roads,syntax_document,network_rules,site,water,retained,
                     zones,entrances,denominator,retained_gfa,parameters,context_edges=(),rules=None,candidate_selector=None,profiles_by_block=None,block_metadata=None):
    if family not in FAMILIES:raise ValueError('unknown S6 strategy')
    rules=rules or S6Rules()
    rows,distribution=syntax_inputs(syntax_document,roads,network_rules,site)
    # Only noded pedestrian junctions of degree >=3 are gathering-node candidates.
    # A PST split endpoint on a straight street is not a plaza node.
    from collections import Counter
    from .multimodal_network import _parts
    support=unary_union([LineString(r.coordinates) for r in roads if 'pedestrian' in r.modes])
    degree=Counter(tuple(round(v,3) for v in p) for line in _parts(support) for p in (line.coords[0],line.coords[-1]))
    high_lines=[LineString(r['coordinates']) for r in rows if 100*sum(v<=r['nain'] for v in distribution)/len(distribution)>=70]
    high_support=unary_union(high_lines)
    high_nodes=[Point(p) for p,d in degree.items() if d>=3 and Point(p).distance(high_support)<=.001]
    land=site.difference(water);surface=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads])
    bike=unary_union([LineString(r.coordinates) for r in roads if 'bicycle' in r.modes])
    service=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads if 'motor_vehicle' in r.modes])
    first=parameters['first_floor_height_m']['value'];standard=parameters['standard_floor_height_m']['value']
    upper_height=parameters['height_upper_bound_m']['value']
    upper_far=parameters['far_upper_bound']['value'];upper_coverage=parameters['coverage_upper_bound']['value']
    kept=unary_union(list(retained.values()));retained_area=kept.intersection(land).area
    target_new=upper_coverage*denominator-retained_area
    budget=upper_far*denominator-retained_gfa
    candidate_groups=[];rejections=[]
    for index,block in enumerate(blocks):
        matches=[z for z in zones if shape(z['geometry']).covers(block.representative_point())]
        zone=matches[0] if matches else min(zones,key=lambda z:(shape(z['geometry']).distance(block.representative_point()),z['zone_id']))
        label=zone['target_use'].lower()
        use='Manufacturing' if any(v in label for v in ('maker','recycle','energy')) else 'Residential' if 'residential' in label else 'Office' if 'office' in label else 'Mixed'
        metadata = block_metadata[index] if block_metadata is not None else {}
        options=[]
        def accessible(g):return g.distance(bike)<=network_rules.bicycle_distance_m and g.distance(service)<=40
        prepared=None if profiles_by_block is None else profiles_by_block.get(index)
        for profile in (prepared if prepared is not None else proposals_for_block(block,use,family,rules,accessible=accessible)):
            if prepared is not None and not scale_check(profile,use)['valid']:continue
            if block_metadata is not None and profile.wing_depth_m > {'Residential':14,'Mixed':16,'Office':18,'Manufacturing':40}[use]+1e-6:continue
            if metadata.get('type_preferences') and profile.type_id not in metadata['type_preferences']:continue
            if metadata.get('wing_depth_m') and not metadata['wing_depth_m'][0]-1e-6 <= profile.wing_depth_m <= metadata['wing_depth_m'][1]+1e-6:continue
            g=profile.geometry
            if g.intersects(surface) or g.intersects(kept.buffer(network_rules.retained_setback_m)) or g.intersects(water.buffer(15)) or not site.covers(g):continue
            if g.distance(bike)>network_rules.bicycle_distance_m or g.distance(service)>40:continue
            try:nain,rank,ids=local_syntax(g,rows,distribution)
            except ValueError:continue
            nd=min((g.distance(p) for p in high_nodes),default=None)
            ed=min((g.distance(Point(e.coordinates)) for e in entrances),default=None)
            responses=[];kinds=[]
            for edge in context_edges:
                edge=ContextEdge.model_validate(edge)
                if g.distance(shape(edge.geometry))<=(rules.dakpark_radius_m if edge.kind=='dakpark' else rules.context_radius_m):
                    kinds.append(edge.kind);responses.append(edge.kind+': '+edge.source_ref)
            if g.distance(water)<=40:kinds.append('waterfront');responses.append('waterfront: approved frozen water geometry; 15m setback')
            low_reason='maker廠房單層挑高7公尺，GFA只計一塊樓板' if use=='Manufacturing' else 'Dakpark高差介面採三層，上層向公園側退台（100公尺回應範圍草案）' if 'dakpark' in kinds else ''
            building_first=7. if use=='Manufacturing' else 4.5 if (nd is not None and nd<=rules.node_radius_m and family in ('radial','axial')) else first
            floors=context_floors(family,rank,nd,use,kinds,node_radius_m=rules.node_radius_m)
            if block_metadata is not None and use!='Manufacturing':low_reason=''
            if metadata.get('floors'):
                floors=max(int(metadata['floors'][0]),min(floors,int(metadata['floors'][1])))
            if metadata.get('floor_cap') is not None:
                floors=min(floors,int(metadata['floor_cap']))
                low_reason=metadata.get('low_reason_zh','brief low zone')
            while building_first+(floors-1)*standard>upper_height and floors>0:floors-=1
            if floors<1:continue
            if metadata.get('landmark_height_m') is not None:
                target=float(metadata['landmark_height_m'])
                desired_first=target-(floors-1)*standard
                if desired_first<3 or target>20:continue
                building_first=desired_first
            active=rank>=70 or ('transit' in kinds)
            ground='Shared workshop' if active and use=='Manufacturing' else 'Public facilities' if active and family in ('radial','green_service') else 'Active mixed use' if active else use
            ids_cards=['MOR-001','MOR-010','MOR-013','SYN-002' if active else 'SYN-005','SYN-003']
            ids_cards.append({'block.perimeter':'MOR-003','building.courtyard_closed':'MOR-004','building.l_block':'MOR-003','building.i_slab':'MOR-005','building.rowhouse':'MOR-007','building.point_tower':'MOR-006','building.podium_tower':'MOR-008','building.industrial_hall':'POR-001'}[profile.type_id])
            if kinds:ids_cards.append('POR-017' if 'dakpark' in kinds else 'PUB-004')
            kus=('KU-ARC-034','KU-ARC-035','KU-ARC-036') if use=='Manufacturing' else ('KU-ARC-012','KU-ARC-013','KU-ARC-049','KU-ARC-050','KU-ARC-051','KU-ARC-052')
            if profile.type_id=='building.rowhouse':kus+=('KU-ARC-021','KU-ARC-022')
            reason=f'步行800m整合度 {nain:.4f}（第 {rank:.1f} 百分位），高整合節點距離 {nd if nd is not None else "未知"} m；{family} 策略採 {profile.type_id}，進深 {profile.wing_depth_m:g} m、{floors} 層，'+('一樓配置活躍用途候選；' if active else '一樓保留較安靜用途；')+'依街廓尺度沿街配置，避免小模板重複填塞。'+('回應 '+'; '.join(responses) if responses else '不在已綁定context的40公尺回應範圍內。')
            intent=BuildingIntent(rule_card_ids=tuple(ids_cards),knowledge_unit_ids=kus,syntax_nain=nain,syntax_percentile=rank,
                syntax_segment_ids=ids,node_distance_m=nd,entrance_distance_m=ed,context_response=tuple(responses),
                reason_zh=reason,reason_en=f'Pedestrian800m NAIN {nain:.4f}, percentile {rank:.1f}; {family}: {profile.type_id}, {profile.wing_depth_m:g}m depth, {floors} floors. '+('Active ground-floor candidate. ' if active else 'Quiet ground-floor use. ')+('Context: '+'; '.join(responses) if responses else 'Dakpark geometry unavailable; no daylight claim.'))
            # Podium retains two full plates, upper volume is independently bounded.
            upper=g
            if profile.podium_floors and floors>2:
                upper=g.buffer(-3,join_style=2)
                if upper.is_empty or upper.area<400:continue
            plates=[g if level<2 or not profile.podium_floors else upper for level in range(floors)]
            sunlight=None
            park=next((shape(e['geometry'] if isinstance(e,dict) else e.geometry) for e in context_edges if (e['kind'] if isinstance(e,dict) else e.kind)=='dakpark'),None)
            if 'dakpark' in kinds:
                from .massing_revision import dakpark_plates
                try:plates,sunlight=dakpark_plates(g,floors,park,building_first,standard)
                except ValueError:continue
            gfa=sum(p.area for p in plates)
            wall_score=g.boundary.intersection(high_support.buffer(18)).length if profile.type_id in ('block.perimeter','building.courtyard_closed','building.l_block') else 0
            options.append(dict(wall_score=wall_score,block_index=index,zone_id=zone['zone_id'],profile=profile,use=use,floors=floors,
                height=building_first+(floors-1)*standard,first=building_first,low_reason=low_reason,sunlight=sunlight,active=active,ground=ground,intent=intent,plates=plates,gfa=gfa,
                allocation_basis='APPROVED_ZONE' if matches else 'ASSUMED_NEAREST_APPROVED_ZONE'))
        if options:
            options.sort(key=lambda o:(-o['wall_score'],-o['profile'].geometry.area,o['profile'].type_id,o['profile'].geometry.wkb_hex))
            candidate_groups.append(options)
        else:rejections.append(dict(block_index=index,reason='no complete scale-valid, road-accessible envelope'))
    # Small zone capacity first; cycle zones before filling. No post-placement roads.
    zone_ids=sorted({o[0]['zone_id'] for o in candidate_groups},key=lambda z:sum(o[0]['zone_id']==z for o in candidate_groups))
    groups=[]
    queues={z:sorted([o for o in candidate_groups if o[0]['zone_id']==z],key=lambda o:-o[0]['profile'].geometry.area) for z in zone_ids}
    while any(queues.values()):
        for z in zone_ids:
            if queues[z]:groups.append(queues[z].pop(0))
    groups.sort(key=lambda options:(-options[0]['wall_score'], -options[0]['profile'].geometry.area))
    anchors=[]
    park_options=[group for group in groups if group[0]['use']!='Manufacturing' and any(v.startswith('dakpark:') for v in group[0]['intent'].context_response)]
    if park_options:anchors.append(min(park_options,key=lambda group:group[0]['profile'].geometry.distance(park)))
    for z in zone_ids:
        anchor=next((group for group in groups if group[0]['zone_id']==z),None)
        if anchor is not None and not any(anchor is x for x in anchors):anchors.append(anchor)
    # Preserve the inherited four-type gate by reserving complete envelopes,
    # never by relabelling or suppressing its assertion.
    represented={group[0]['profile'].type_id for group in anchors}
    for group in groups:
        if len(represented)>=4:break
        if any(group is x for x in anchors):continue
        option=next((o for o in group if o['profile'].type_id not in represented),None)
        if option is not None:
            group.remove(option);group.insert(0,option);anchors.append(group)
            represented.add(option['profile'].type_id)
    groups=anchors+[group for group in groups if not any(group is anchor for anchor in anchors)]
    selected=[];gfa=0;area=0
    for options in groups:
        choice=next((o for o in options if area+o['profile'].geometry.area<=target_new+1e-6 and gfa+o['gfa']<=budget+1e-6 and (o['profile'].type_id!='building.i_slab' or all(o['profile'].geometry.distance(b['profile'].geometry)>=max(o['height'],b['height']) for b in selected if b['profile'].type_id=='building.i_slab'))),None)
        if choice:
            selected.append(choice);gfa+=choice['gfa'];area+=choice['profile'].geometry.area
        else:rejections.append(dict(block_index=options[0]['block_index'],reason='D2 GFA/coverage upper budget; no thin scaling'))
    if candidate_selector is not None:
        # Opt-in J12c: the historical selector above remains the default.
        # Candidates have already passed actual geometry/access/scale checks.
        selected=candidate_selector(candidate_groups,budget,target_new)
        gfa=sum(o['gfa'] for o in selected)
        area=sum(o['profile'].geometry.area for o in selected)
    features=[];records=[]
    for i,o in enumerate(selected):
        p=o['profile'];g=p.geometry;id=family+f'-s6-building-{i}'
        check=scale_check(p,o['use'])
        floors=[dict(level=level,geometry=mapping(plate),floor_height_m=o['first'] if level==0 else standard,use=o['ground'] if level==0 else o['use']) for level,plate in enumerate(o['plates'])]
        props=dict(role='new_building',building_id=id,type_id=p.type_id,variant_id=VERSION,block_id=o['block_index'],
            zone_id=o['zone_id'],allocation_basis=o['allocation_basis'],height_m=o['height'],floor_count=o['floors'],
            first_floor_height_m=o['first'],standard_floor_height_m=standard,ground_use=o['ground'],active_frontage=o['active'],
            low_floor_reason_zh=o['low_reason'],low_floor_rule_card_ids=['POR-017'] if o['low_reason'] and o['use']!='Manufacturing' else ['POR-001'] if o['low_reason'] else [],sunlight_screen=o['sunlight'],
            floors=floors,design_intent=o['intent'].model_dump(mode='json'),scale=check,
            spacematrix=dict(FSI=o['gfa']/blocks[o['block_index']].area,GSI=g.area/blocks[o['block_index']].area,L=o['gfa']/g.area))
        from .massing_revision import facade_segments
        props['facade_segments']=facade_segments(g,roads,high_lines,entrances=[Point(e.coordinates) for e in entrances])
        features.append(dict(type='Feature',id=id,geometry=mapping(g),properties=props))
        records.append(dict(**props,footprint_area_m2=g.area,new_gfa_m2=o['gfa']))
    footprint=unary_union([o['profile'].geometry for o in selected])
    open_space=land.difference(unary_union([footprint,kept,surface]))
    metrics=dict(far=(gfa+retained_gfa)/denominator,coverage=(area+retained_area)/denominator,new_gfa_m2=gfa,
        retained_gfa_upper_m2=retained_gfa,retained_footprint_m2=retained_area,far_denominator_m2=denominator,
        open_space_ratio=open_space.area/denominator,new_building_count=len(records),heights_m=sorted({o['height'] for o in selected}),
        dictionary_types=sorted({o['profile'].type_id for o in selected}),L=(gfa+retained_gfa)/(area+retained_area),
        coverage_policy='RESULT_ONLY_UPPER_BOUND',active_footprint_m2=sum(o['profile'].geometry.area for o in selected if o['active']))
    checks=dict(height=all(o['height']<=upper_height for o in selected),far_upper=metrics['far']<=upper_far,
        coverage=metrics['coverage']<=upper_coverage,scale=bool(records) and all(r['scale']['valid'] for r in records),
        quality_far_minimum=metrics['far']>=.70,open_space_minimum=metrics['open_space_ratio']>=.4,
        four_types=len(metrics['dictionary_types'])>=4,all_zones=all(any(r['zone_id']==z['zone_id'] for r in records) for z in zones),
        height_variation=len(metrics['heights_m'])>=2)
    from .massing_revision import revision_checks,named_open_spaces
    spaces,remnants=named_open_spaces(open_space,water,high_nodes)
    plazas=[shape(s['geometry']) for s in spaces if s['name_zh'].startswith('整合節點廣場')]
    for f,r in zip(features,records):
        r['facade_segments']=facade_segments(shape(f['geometry']),roads,high_lines,plazas=plazas,entrances=[Point(e.coordinates) for e in entrances])
        f['properties']['facade_segments']=r['facade_segments']
    # Select eligible facade edges by building integration, never invent a
    # location to fill the allowance. Limit denotes programme budget.
    all_edges=[(r['design_intent']['syntax_nain'],r['building_id'],e) for r in records for e in r['facade_segments']]
    allowance=.5*sum(e['length_m'] for _,_,e in all_edges);used=0
    for _,_,edge in sorted(all_edges,key=lambda item:(-item[0],item[1],str(item[2]['geometry']))):
        if edge['active']:
            if used+edge['length_m']<=allowance:used+=edge['length_m']
            else:edge['active']=False;edge['reason_zh']='具活躍潛力但超出首層用途預算，維持一般立面'
    for f,r in zip(features,records):f['properties']['active_frontage']=r['active_frontage']=any(e['active'] for e in r['facade_segments'])
    revision,measured=revision_checks(records,metrics,upper_far=upper_far,upper_coverage=upper_coverage,upper_height=upper_height)
    checks.update(revision);metrics.update(measured)
    metrics['named_open_space_area_m2']=sum(s['area_m2'] for s in spaces)
    metrics['narrow_remnant_area_m2']=sum(s['area_m2'] for s in remnants)
    metrics['narrow_remnant_count']=len(remnants)
    checks['open_space_accounting']=abs(sum(s['area_m2'] for s in spaces)+sum(s['area_m2'] for s in remnants)-open_space.area)<.01
    from .massing_revision import streetwall_continuity
    metrics.update(streetwall_continuity(high_lines,records))
    # Slab spacing >= tallest member height is a hard new S6 geometry check.
    slabs=[o for o in selected if o['profile'].type_id=='building.i_slab']
    checks['slab_spacing']=all(a['profile'].geometry.distance(b['profile'].geometry)>=max(a['height'],b['height']) for a,b in combinations(slabs,2))
    return dict(features=features,buildings=records,metrics=metrics,checks=checks,rejections=rejections,
        open_space=mapping(open_space),named_open_spaces=spaces,narrow_remnants=remnants,context_edges=[e if isinstance(e,dict) else e.model_dump() for e in context_edges],rules=rules.model_dump(mode='json'),version=VERSION,
        type_capabilities=[c.model_dump(mode='json') for c in block_scale_capabilities()],
        limitations=['ASSUMED_COMMANDER DRAFT; no HumanDecision or formal publication.','Footprint wing dimensions are gross envelope dimensions; cores and net room plans unverified.',
        'Syntax is a configurational indicator, not observed footfall.','Dakpark datum assumed from portfolio p21; two-date noon screen is not E1 acceptance.','Box-in-box awaits surveyed internal clear space; retained shells untouched.'])


def difference_metrics(a,b,rules=None):
    rules=rules or S6Rules()
    def histogram(row):
        hist={};total=sum(r['footprint_area_m2'] for r in row['buildings'])
        for r in row['buildings']:hist[r['height_m']]=hist.get(r['height_m'],0)+r['footprint_area_m2']/total
        return hist
    ha,hb=histogram(a),histogram(b)
    height=.5*sum(abs(ha.get(h,0)-hb.get(h,0)) for h in set(ha)|set(hb))
    oa,ob=shape(a['open_space']),shape(b['open_space']);open_diff=oa.symmetric_difference(ob).area/max(oa.union(ob).area,1e-12)
    uses=set(r['ground_use'] for r in a['buildings']+b['buildings'])
    different=0;union=unary_union([shape(f['geometry']) for row in (a,b) for f in row['features']])
    for use in uses:
        ga=unary_union([shape(f['geometry']) for f in a['features'] if f['properties']['ground_use']==use])
        gb=unary_union([shape(f['geometry']) for f in b['features'] if f['properties']['ground_use']==use])
        different+=ga.symmetric_difference(gb).area
    ground=min(1,different/max(union.area,1e-12))
    flags=dict(height=height>=rules.height_tv_min,open_space=open_diff>=rules.open_space_difference_min,ground_use=ground>=rules.ground_use_difference_min)
    return dict(height_area_weighted_total_variation=height,open_space_jaccard_distance=open_diff,
        ground_use_spatial_difference=ground,checks=flags,distinct=all(flags.values()),thresholds=dict(height=rules.height_tv_min,open_space=rules.open_space_difference_min,ground_use=rules.ground_use_difference_min),provenance='ASSUMED_COMMANDER DRAFT')
