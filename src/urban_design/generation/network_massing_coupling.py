"""J12c offline coupling, EPSG:28992 metres; no state or decision writes.

All added thresholds are the assigned J12c draft quality gates. The existing
J11 network cleaner and J12b measured validators retain their behaviour.
"""
from itertools import combinations
import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree
from . import multimodal_network as net
from .context_massing import syntax_inputs, scale_check, S6Rules
from .massing_revision import facade_segments, streetwall_continuity, revision_checks

VERSION='j12c-coupling-v1'
WALL_TYPES={'block.perimeter','building.courtyard_closed','building.l_block'}


class CouplingRules(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    crs: Literal['EPSG:28992']='EPSG:28992'
    bilateral_min: FiniteFloat=Field(default=.6,ge=.6,le=1)
    largest_park_min_m2: FiniteFloat=Field(default=20000,ge=20000)
    park_count_max: int=Field(default=6,ge=1,le=6)
    remnant_max_m2: FiniteFloat=Field(default=3000,ge=0,le=3000)
    usable_width_m: FiniteFloat=Field(default=12,ge=12)
    usable_area_m2: FiniteFloat=Field(default=200,ge=200)
    # Selection settings are declared draft assumptions, never planning rules.
    minimum_development_length_m: FiniteFloat=Field(default=20,gt=0)
    integration_percentile_min: FiniteFloat=Field(default=50,ge=0,le=100)
    cluster_budget_share: FiniteFloat=Field(default=.65,gt=0,le=1)


def parts(g):
    if g.geom_type=='Polygon':return [g]
    return [p for c in getattr(g,'geoms',[]) for p in parts(c)]


def connected_components(roads,mode):
    """Same-grade intersections only; grade-separated crossings cannot connect."""
    selected=[r for r in roads if mode in r.modes]
    gs=[LineString(r.coordinates) for r in selected]
    tree=STRtree(gs);unseen=set(range(len(gs)));components=[]
    while unseen:
        start=min(unseen);unseen.remove(start);component={start};pending=[start]
        while pending:
            i=pending.pop()
            linked={int(j) for j in tree.query(gs[i].buffer(1e-6)) if int(j) in unseen
                    and selected[i].layer==selected[int(j)].layer and gs[i].distance(gs[int(j)])<=1e-6}
            unseen-=linked;component|=linked;pending.extend(sorted(linked))
        components.append(component)
    return selected,gs,components


def transport_checks(roads,buildings,retained,entrances,external):
    """Fire facade proximity and actual same-grade car access from outside.

    Proximity is the inherited J11 proxy, not a verified entrance/fire licence.
    """
    checks={};metrics={}
    for mode in ('pedestrian','bicycle','motor_vehicle'):
        rs,gs,components=connected_components(roads,mode)
        metrics[mode+'_component_count']=len(components)
        checks[mode+'_connected']=len(components)==1
        if mode!='motor_vehicle':continue
        ext=[shape(f['geometry']) for f in external.get(mode,[]) if int(f.get('properties',{}).get('layer') or 0)==0 and shape(f['geometry']).difference(external['_site']).length>1e-6]
        ext_tree=STRtree(ext)
        reached=set()
        for component in components:
            if any(rs[i].layer==0 and any(gs[i].distance(ext[int(j)])<=1e-6 for j in ext_tree.query(gs[i].buffer(1e-6))) for i in component):reached|=component
        fire=unary_union([gs[i].buffer(rs[i].width_m/2) for i in reached])
        distances={name:net._distance(g.boundary,fire) for name,g in list(retained.items())+[(f'new:{i}',g) for i,g in enumerate(buildings)]}
        checks['fire_40m']=bool(buildings) and all(d is not None and d<=40 for d in distances.values())
        checks['motor_external_connected']=bool(gs) and len(reached)==len(gs)
        entries=[e for e in entrances if mode in e.modes]
        checks['motor_entrance_connected']=all(any(rs[i].layer==0 and gs[i].distance(Point(e.coordinates))<=1e-6 for i in reached) for e in entries)
        metrics['motor_entrance_count']=len(entries);metrics['fire_distances_m']=distances
    return checks,metrics


def _road_integration(road,document):
    line=LineString(road.coordinates);rows=document['after']['segments']
    matches=[r for r in rows if r.get('source_line_id','').removeprefix('proposal:').split(':part:')[0].removesuffix('_a').removesuffix('_b')==road.id]
    if not matches:
        matches=[r for r in rows if LineString(r['coordinates']).intersection(line.buffer(.001)).length>1e-3]
    weights=[LineString(r['coordinates']).intersection(line.buffer(.001)).length for r in matches]
    total=sum(weights)
    if total<=0:return None
    value=sum(r['nain']*w for r,w in zip(matches,weights))/total
    distribution=[r['nain'] for r in rows]
    return value,100*sum(v<=value for v in distribution)/len(distribution)


def ranked_development_roads(family,roads,pedestrian,bicycle,site,entrances,rules,network_rules):
    syntax_inputs(pedestrian,roads,network_rules,site)
    from urban_design.scenario_syntax import digest
    if bicycle.get('status')!='COMPUTED' or bicycle.get('mode')!='bicycle' or bicycle.get('radius_m')!=2000 or bicycle.get('site_sha256')!=digest(mapping(site)) or bicycle.get('road_input_sha256')!=digest([r.model_dump() for r in net.syntax_roads(roads,'bicycle',network_rules)]):
        raise ValueError('computed bicycle 2km source lineage required')
    for row in bicycle['after']['segments']:
        if isinstance(row['nain'],bool) or not math.isfinite(row['nain']) or row['nain']<0:raise ValueError('invalid bicycle integration')
    # External high integration entrance source IDs must have both mode evidence.
    qualified=[]
    for e in entrances:
        values=[]
        for mode,doc in [('pedestrian',pedestrian),('bicycle',bicycle)]:
            dist=[r['nain'] for r in doc['before']['segments']]
            vals=[r['nain'] for r in doc['before']['segments'] if r.get('source_line_id') in e.source_ids.get(mode,[])]
            values.append(max((100*sum(v<=x for v in dist)/len(dist) for x in vals),default=0))
        if min(values)>=rules.integration_percentile_min:qualified.append(e)
    rs,gs,components=connected_components(roads,'pedestrian')
    reachable={rs[i].id for component in components if any(gs[i].distance(Point(e.coordinates))<=1e-6 for i in component for e in qualified) for i in component}
    from .skeleton import _principal_angle
    principal=math.radians(_principal_angle(site))
    center=site.centroid;ranked=[]
    for road in roads:
        line=LineString(road.coordinates).intersection(site)
        if line.geom_type!='LineString' or not {'pedestrian','bicycle'}<=set(road.modes) or line.length<rules.minimum_development_length_m or road.id not in reachable:continue
        p=_road_integration(road,pedestrian);b=_road_integration(road,bicycle)
        if p is None or b is None or min(p[1],b[1])<rules.integration_percentile_min:continue
        cs=list(line.coords);angle=math.atan2(cs[-1][1]-cs[0][1],cs[-1][0]-cs[0][0])
        intent=1-line.distance(center)/max(math.sqrt(site.area),1) if family=='radial' else abs(math.cos(angle-principal)) if family in ('axial','grid') else float(road.hierarchy=='service')
        ranked.append(dict(road=road,development_geometry=mapping(line),pedestrian_nain=p[0],bicycle_nain=b[0],pedestrian_percentile=p[1],bicycle_percentile=b[1],score=.5*(p[1]+b[1])+20*intent,external_entry_ids=[e.id for e in qualified],intent_zh={'radial':'集中高整合中心','axial':'沿高整合主向軸線','grid':'兩至三條高整合平行街','green_service':'服務環路兩側集中量體'}[family]))
    return sorted(ranked,key=lambda r:(-r['score'],r['road'].id))


class ClusterSelector:
    """Budget whole paired envelopes first, then zone/type obligations nearby."""
    def __init__(self,ranked,roads,water,rules=None):
        self.ranked=ranked;self.roads=roads;self.water=water;self.rules=rules or CouplingRules();self.development=[];self.rejections=[]

    def __call__(self,groups,budget,coverage):
        selected=[];used=set();gfa=area=0.
        def fits(options):
            nonlocal gfa,area
            if gfa+sum(o['gfa'] for o in options)>budget+1e-6 or area+sum(o['profile'].geometry.area for o in options)>coverage+1e-6:return False
            all_options=selected+list(options)
            if len({o['block_index'] for o in all_options})!=len(all_options):return False
            slabs=[o for o in all_options if o['profile'].type_id=='building.i_slab']
            return all(a['profile'].geometry.distance(b['profile'].geometry)>=max(a['height'],b['height']) for a,b in combinations(slabs,2))
        def accept(options):
            nonlocal gfa,area
            selected.extend(options);used.update(o['block_index'] for o in options)
            gfa+=sum(o['gfa'] for o in options);area+=sum(o['profile'].geometry.area for o in options)
        def witness(o,road):
            return dict(type_id=o['profile'].type_id,facade_segments=facade_segments(o['profile'].geometry,[road],[]))
        for ranked in self.ranked:
            road=ranked['road'];line=shape(ranked['development_geometry']) if 'development_geometry' in ranked else LineString(road.coordinates)
            options=[o for group in groups for o in group if o['block_index'] not in used and o['profile'].type_id in WALL_TYPES and o['profile'].geometry.distance(line)<=18]
            # Preserve the cost/frontage trade-off, rather than only cheapest
            # profiles that can never cover this street. Measured frontage is
            # taken from the real exterior, not the authored wall_score.
            witnesses={id(o):witness(o,road) for o in options}
            frontage={id(o):streetwall_continuity([line],[witnesses[id(o)]]) for o in options}
            def total_front(o):
                m=frontage[id(o)];return m['left_streetwall_length_m']+m['right_streetwall_length_m']
            pool=[]
            for index in sorted({o['block_index'] for o in options}):
                members=[o for o in options if o['block_index']==index and total_front(o)>1e-6]
                if not members:continue
                chosen=[min(members,key=lambda o:(o['gfa'],-total_front(o))),max(members,key=lambda o:(total_front(o),-o['gfa'])),max(members,key=lambda o:(total_front(o)/o['gfa'],-o['gfa']))]
                for o in chosen:
                    if not any(o is present for present in pool):pool.append(o)
            # A development street may span several blocks. Greedily add whole
            # envelopes by bilateral gain, with one-sided coverage as the seed;
            # never demand that a single pair spans the entire street.
            cluster=[];cluster_blocks=set()
            existing=[o for o in selected if o['profile'].type_id in WALL_TYPES and o['profile'].geometry.distance(line)<=18]
            existing_witness=[witness(o,road) for o in existing]
            measure=streetwall_continuity([line],existing_witness)
            while measure['streetwall_continuity_ratio']<self.rules.bilateral_min:
                choices=[]
                current_cost=sum(v['gfa'] for v in cluster)
                for o in pool:
                    old=next((v for v in cluster if v['block_index']==o['block_index']),None)
                    if old is o:continue
                    trial_cluster=[v for v in cluster if v is not old]+[o]
                    if not fits(trial_cluster):continue
                    trial_cost=sum(v['gfa'] for v in trial_cluster)
                    if self.development and trial_cost+gfa>budget*self.rules.cluster_budget_share:continue
                    trial=streetwall_continuity([line],existing_witness+[witnesses[id(v)] for v in trial_cluster])
                    bilateral=trial['bilateral_streetwall_length_m']-measure['bilateral_streetwall_length_m']
                    frontage_gain=trial['left_streetwall_length_m']+trial['right_streetwall_length_m']-measure['left_streetwall_length_m']-measure['right_streetwall_length_m']
                    if bilateral< -1e-6 or frontage_gain<=1e-6:continue
                    choices.append(((bilateral+.1*frontage_gain)/max(trial_cost-current_cost,1),trial,o,trial_cluster))
                if not choices:break
                _,measure,o,cluster=max(choices,key=lambda item:(item[0],-item[2]['gfa'],-item[2]['block_index']))
                cluster_blocks={v['block_index'] for v in cluster}
            if measure['streetwall_continuity_ratio']<self.rules.bilateral_min:
                self.rejections.append(dict(road_id=road.id,reason_zh='完整尺度組團在保留分區／型態預算後無法達到雙側街牆',best_greedy_bilateral_ratio=measure['streetwall_continuity_ratio'],candidate_count=len(pool),trial_gfa_m2=sum(o['gfa'] for o in cluster)));continue
            cost=sum(o['gfa'] for o in cluster)
            accept(cluster);self.development.append({k:v for k,v in ranked.items() if k not in ('road','development_geometry')}|dict(road_id=road.id,geometry=mapping(line),length_m=line.length,pair_gfa_m2=cost,block_indices=[o['block_index'] for o in existing+cluster],source_origin=road.origin))
            if len(self.development)>=3:break
        # Inherited all-zone and four-type gates remain actual obligations.
        zone_ids=sorted({g[0]['zone_id'] for g in groups})
        for zone in zone_ids:
            if any(o['zone_id']==zone for o in selected):continue
            opts=[o for g in groups for o in g if o['zone_id']==zone and o['block_index'] not in used and fits([o])]
            if opts:
                # Maker concentrates at service/harbour; other zone anchors near cluster.
                service=unary_union([LineString(r.coordinates) for r in self.roads if r.hierarchy=='service'])
                anchor=unary_union([shape(s['geometry']) for s in self.development])
                opts.sort(key=lambda o:(o['profile'].geometry.distance(service)+o['profile'].geometry.distance(self.water) if o['use']=='Manufacturing' else o['profile'].geometry.distance(anchor) if not anchor.is_empty else 0,o['gfa'],o['block_index']))
                accept([opts[0]])
        for group in sorted(groups,key=lambda g:g[0]['block_index']):
            if len({o['profile'].type_id for o in selected})>=4:break
            options=[o for o in group if o['profile'].type_id not in {s['profile'].type_id for s in selected} and fits([o])]
            if options:accept([min(options,key=lambda o:o['gfa'])])
        anchor=unary_union([shape(s['geometry']) for s in self.development])
        groups=sorted(groups,key=lambda g:(min(o['profile'].geometry.distance(anchor) for o in g) if not anchor.is_empty else 0,g[0]['block_index']))
        for group in groups:
            if group[0]['block_index'] in used:continue
            options=[o for o in group if fits([o]) and (o['use']=='Manufacturing' or not anchor.is_empty and o['profile'].geometry.distance(anchor)<=60)]
            if options:
                accept([max(options,key=lambda o:(o['gfa'],o['wall_score'],-o['block_index']))])
        return selected


def downgrade_roads(roads,buildings,retained,entrances,external,network_rules,public_spaces=()):
    current=list(roads);trace=[]
    kept=unary_union(list(retained.values()));parks=unary_union(public_spaces)
    candidates=sorted(roads,key=lambda r:(-LineString(r.coordinates).intersection(parks).length,-min((LineString(r.coordinates).distance(g) for g in buildings),default=0),r.id))
    for road in candidates:
        if 'motor_vehicle' not in road.modes:continue
        line=LineString(road.coordinates)
        protected=road.origin=='retained' or not kept.is_empty and line.buffer(road.width_m/2).distance(kept)<=40
        if protected:
            trace.append(dict(road_id=road.id,action='protected',length_m=line.length,reason_zh='保留城市道路或保留建築40公尺服務範圍，不動'));continue
        replacement=net.NetworkRoad.model_validate({**road.model_dump(),'modes':['pedestrian','bicycle'],'width_m':min(road.width_m,network_rules.shared_width_m),'width_class':'shared','access':'public','park_shared':True,'semantics_provenance':road.semantics_provenance+'; J12c DRAFT downgrade, fire/connectivity checked'})
        trial=[replacement if r.id==road.id else r for r in current]
        duplicate=unary_union([LineString(r.coordinates) for r in current if r.id!=road.id and {'pedestrian','bicycle'}<=set(r.modes) and r.layer==road.layer])
        action='downgraded'
        if line.difference(duplicate.buffer(1e-6)).length<=1e-6:trial=[r for r in current if r.id!=road.id];action='removed_duplicate'
        checks,metrics=transport_checks(trial,buildings,retained,entrances,external)
        inherited=net.hard_checks(site=external['_site'],roads=trial,buildings=buildings,retained_before=retained,retained_after=retained,water=external['_water'],entrances=entrances,external=external,rules=network_rules,public_spaces=public_spaces)
        failures=[k for k,v in checks.items() if not v]+[k for k,v in inherited['checks'].items() if not v]
        if failures:action='reverted'
        else:current=trial
        trace.append(dict(road_id=road.id,action=action,length_m=line.length,reason_zh='回退：消防／運具連通／原有硬性檢查失敗' if failures else '消防40公尺、入口、各運具連通與原有硬性檢查皆通過',failed_checks=failures,checks=checks,metrics=metrics))
    return current,trace


def merged_open_spaces(site,water,roads,buildings,retained,rules=None):
    rules=rules or CouplingRules()
    # Shared park paths remain inside usable parks. Motor surfaces divide parks.
    motor=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads if 'motor_vehicle' in r.modes])
    ground=site.difference(unary_union([water,motor,*buildings,*retained.values()]))
    spaces=[];remnants=[]
    for p in sorted(parts(ground),key=lambda p:(-p.area,p.bounds)):
        core=p.buffer(-rules.usable_width_m/2,join_style=2).buffer(rules.usable_width_m/2,join_style=2).intersection(p)
        for usable in sorted(parts(core),key=lambda q:(-q.area,q.bounds)):
            if usable.area<rules.usable_area_m2:continue
            name='中央食物園' if not spaces else '潮汐水岸公園' if usable.distance(water)<=15 else '綠廊'
            spaces.append(dict(name_zh=name+(' '+str(len(spaces)+1) if spaces else ''),use_zh='社區種植與食物教育' if not spaces else '水岸滯留與生態休憩' if name=='潮汐水岸公園' else '日常通行、休憩與雨水花園',area_m2=usable.area,geometry=mapping(usable),rule_card_ids=['PUB-004','POR-017','POR-005'],status='DRAFT_USE_PROPOSAL'))
    assigned=unary_union([shape(s['geometry']) for s in spaces])
    for p in parts(ground.difference(assigned)):
        if p.area>1e-6:remnants.append(dict(area_m2=p.area,geometry=mapping(p),reason_zh='12公尺淨寬形態初篩或面積不足200平方公尺；未改名為公園'))
    return ground,spaces,remnants


def coupling_checks(row,development,roads,site,water,retained,entrances,external,rules=None):
    """Read-back geometry, not labels; missing inputs fail closed."""
    rules=rules or CouplingRules();buildings=[shape(f['geometry']) for f in row['features']]
    records=row['buildings'];by_id={r.id:r for r in roads}
    lines=[shape(s['geometry']) for s in development if s['road_id'] in by_id and shape(s['geometry']).difference(LineString(by_id[s['road_id']].coordinates).buffer(1e-6)).length<=1e-6 and site.buffer(1e-6).covers(shape(s['geometry']))]
    wall=streetwall_continuity(lines,records)
    ground,spaces,remnants=merged_open_spaces(site,water,roads,buildings,retained,rules)
    metrics={**wall,'largest_park_m2':max((s['area_m2'] for s in spaces),default=0),'park_count':len(spaces),'narrow_remnant_area_m2':sum(r['area_m2'] for r in remnants)}
    checks=dict(development_streets_present=bool(development) and len(lines)==len(development),development_bilateral_streetwall=bool(lines) and wall['streetwall_continuity_ratio']>=rules.bilateral_min,largest_park=metrics['largest_park_m2']>=rules.largest_park_min_m2,named_park_count=0<len(spaces)<=rules.park_count_max,remnant_area=metrics['narrow_remnant_area_m2']<=rules.remnant_max_m2,open_space_accounting=abs(sum(s['area_m2'] for s in spaces)+metrics['narrow_remnant_area_m2']-ground.area)<.01)
    rc,rm=revision_checks(records,row['metrics']);checks.update(rc);metrics.update(rm)
    tc,tm=transport_checks(roads,buildings,retained,entrances,external);checks.update(tc);metrics.update(tm)
    return checks,metrics,ground,spaces,remnants


def drawing_guard(row):
    """A VALID string or forged metrics never authorizes drawings."""
    if row.get('status')!='VALID' or row.get('version')!=VERSION or not row.get('coupling') or not row.get('buildings') or not row.get('checks') or not all(v is True for v in row['checks'].values()) or not row.get('network_hard_checks',{}).get('checks') or not all(v is True for v in row['network_hard_checks']['checks'].values()):
        raise ValueError('INVALID coupling: figure output prohibited')
    rules=CouplingRules.model_validate(row['coupling']['rules'])
    geometry=row['geometry']['features']
    site=shape(next(f['geometry'] for f in geometry if f['properties']['role']=='site_area'))
    water=unary_union([shape(f['geometry']) for f in geometry if f['properties']['role']=='water'])
    retained={f.get('id',str(i)):shape(f['geometry']) for i,f in enumerate(geometry) if f['properties']['role']=='retained'}
    roads=[net.NetworkRoad.model_validate(dict(id=f['properties']['road_id'],coordinates=f['geometry']['coordinates'],**{k:v for k,v in f['properties'].items() if k in net.NetworkRoad.model_fields and k!='id'})) for f in geometry if f['properties']['role']=='road']
    by_id={r.id:r for r in roads}
    development=row['coupling']['development_streets']
    if not development or any(d['road_id'] not in by_id or shape(d['geometry']).difference(LineString(by_id[d['road_id']].coordinates).buffer(1e-6)).length>1e-6 or not site.buffer(1e-6).covers(shape(d['geometry'])) for d in development):raise ValueError('INVALID development lineage: figure output prohibited')
    lines=[shape(d['geometry']) for d in development]
    actual=[];masses=[];new_gfa=0.
    for f,b in zip(row['features'],row['buildings']):
        g=shape(f['geometry']);masses.append(g)
        # Scale witness must agree with the actual footprint, not its labels.
        from types import SimpleNamespace
        unit_count=unit_frontage=None
        if b['type_id']=='building.rowhouse':
            from .type_registry import generate_block_profile
            measured=generate_block_profile(b['type_id'],g.minimum_rotated_rectangle,wing_depth_m=b['scale']['wing_depth_m'])
            unit_count=measured.unit_count;unit_frontage=measured.unit_frontage_m
        profile=SimpleNamespace(geometry=g,type_id=b['type_id'],wing_depth_m=b['scale']['wing_depth_m'],unit_count=unit_count,unit_frontage_m=unit_frontage)
        use='Manufacturing' if b['type_id']=='building.industrial_hall' else b['floors'][-1]['use']
        if not scale_check(profile,use)['valid']:raise ValueError('INVALID scale: figure output prohibited')
        h=sum(floor['floor_height_m'] for floor in b['floors'])
        if abs(h-b['height_m'])>1e-6 or len(b['floors'])!=b['floor_count'] or abs(g.area-b['footprint_area_m2'])>.01:raise ValueError('INVALID measured massing: figure output prohibited')
        if any(not g.covers(shape(floor['geometry'])) for floor in b['floors']):raise ValueError('INVALID floor containment: figure output prohibited')
        new_gfa+=sum(shape(floor['geometry']).area for floor in b['floors'])
        actual.append(dict(type_id=b['type_id'],facade_segments=facade_segments(g,roads,lines)))
    wall=streetwall_continuity(lines,actual)
    if wall['streetwall_continuity_ratio']<rules.bilateral_min:raise ValueError('INVALID bilateral wall: figure output prohibited')
    ground,spaces,remnants=merged_open_spaces(site,water,roads,masses,retained,rules)
    if max((s['area_m2'] for s in spaces),default=0)<rules.largest_park_min_m2 or len(spaces)>rules.park_count_max or sum(r['area_m2'] for r in remnants)>rules.remnant_max_m2:raise ValueError('INVALID parks: figure output prohibited')
    m=row['metrics'];denominator=m['far_denominator_m2']
    far=(new_gfa+m['retained_gfa_upper_m2'])/denominator
    coverage=unary_union(masses+list(retained.values())).intersection(site.difference(water)).area/denominator
    if abs(far-m['far'])>1e-7 or abs(coverage-m['coverage'])>1e-7 or not all(revision_checks(row['buildings'],dict(far=far,coverage=coverage))[0].values()):raise ValueError('INVALID density readback: figure output prohibited')
