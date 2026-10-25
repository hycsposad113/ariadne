"""S3/S4 deterministic DRAFT networks. Metres, EPSG:28992; no state writes.

Draft parameters are engineering hypotheses, not activated planning constraints.
Existing city roads are frozen; connectivity is planned before building placement.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
import math
import heapq
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from shapely import affinity
from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.ops import nearest_points, unary_union, snap, polygonize
from shapely.strtree import STRtree

from urban_design.scenario_syntax import ProposalRoad, digest, _parts

VERSION = 'formal-dictionary-v7-multimodal'
FAMILIES = ('radial', 'axial', 'grid', 'green_service')
CAR_HIGHWAYS = {'trunk','primary','secondary','tertiary','residential','unclassified','living_street'}


class NetworkRules(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    status: Literal['DRAFT'] = 'DRAFT'
    provenance: Literal['ASSUMED_COMMANDER'] = 'ASSUMED_COMMANDER'
    high_percentile: FiniteFloat = Field(default=80,gt=40,le=100)
    medium_percentile: FiniteFloat = Field(default=40,gt=0,lt=80)
    bicycle_distance_m: FiniteFloat = Field(default=25,gt=0)
    bicycle_adjacency_m: FiniteFloat = Field(default=8,ge=0)
    fire_distance_m: Literal[40] = 40
    shared_width_m: FiniteFloat = Field(default=4.5,gt=0)
    main_shared_width_m: FiniteFloat = Field(default=7.5,gt=0)
    service_width_m: FiniteFloat = Field(default=6,gt=0)
    retained_car_width_m: FiniteFloat = Field(default=10,gt=0)
    retained_cycle_width_m: FiniteFloat = Field(default=4.5,gt=0)
    retained_setback_m: FiniteFloat = Field(default=3,ge=0)
    waterfront_band_m: Literal[15] = 15
    block_min_m: FiniteFloat = Field(default=40,gt=0)
    block_max_m: FiniteFloat = Field(default=120,gt=40)
    residual_open_space_width_m: FiniteFloat = Field(default=12,gt=0)
    scope: Literal['new_and_junctions'] = 'new_and_junctions'
    minimum_turn_deg: FiniteFloat = Field(default=30,gt=0,lt=90)
    max_dead_ends: int = Field(default=12,ge=0)
    transform_dead_end_service: bool = False
    snap_tolerance_m: FiniteFloat = Field(default=1,gt=0)
    minimum_segment_m: FiniteFloat = Field(default=3,gt=0)
    small_loop_radius_m: FiniteFloat = Field(default=15,gt=0)
    core_radius_m: FiniteFloat = Field(default=25,gt=0)
    green_band_width_m: FiniteFloat = Field(default=18,gt=0)
    service_in_motor_syntax: bool = False
    parking_area_trigger_m2: FiniteFloat = Field(default=300000,gt=0)
    parking_office_share_trigger: FiniteFloat = Field(default=.5,ge=0,le=1)
    rule_card_ids: tuple[str,...] = ('SYN-011','MOB-001','MOB-002','MOB-003','MOB-004','MOB-005','MOB-006','MOB-007','MOB-008','MOB-009','MOB-010','MOB-015','MOR-002','MOR-011','MOR-012','POR-005','POR-006','J11B-NETWORK-GEOMETRY-DRAFT')


class NetworkRoad(ProposalRoad):
    hierarchy: Literal['main','branch','internal','service','retained']
    width_class: Literal['shared','main_shared','service','city','cycle']
    access: Literal['public','service_only'] = 'public'
    rule_card_ids: list[str] = Field(min_length=1)
    pedestrian_only_reason: str | None = None
    park_shared: bool = False
    active_frontage_candidate_sides: Literal['both'] | None = None


class Disposition(BaseModel):
    source_id: str
    disposition: Literal['retained','transformed','removed']
    reason: str
    rule_card_id: str
    highway: str | None = None
    through_city: bool
    dead_end_service: bool


class Entrance(BaseModel):
    id: str
    coordinates: tuple[FiniteFloat,FiniteFloat]
    modes: list[Literal['pedestrian','bicycle','motor_vehicle']]
    source_ids: dict[str,list[str]]
    weight: FiniteFloat = Field(ge=0)
    diagnosis_provenance: str = 'SYNTAX_ONLY; J9b_PENDING_INTEGRATION'


class Target(BaseModel):
    hierarchy: Literal['main','branch','internal']
    mode: Literal['pedestrian','bicycle']
    radius_m: Literal[800,2000]
    level: Literal['High','Medium','Low']
    rule_card_id: str = 'SYN-011'
    provenance: str = 'ASSUMED_COMMANDER'


class Variant(BaseModel):
    id: str
    family: Literal['radial','axial','grid','green_service']
    roads: list[NetworkRoad]
    parameters: dict


def classify_existing(features, site, rules, retained_buildings=(),destination_routes=()):
    """Frozen city through routes and public destinations survive local cleanup.

    Same-grade connections determine outside reach; explicit destination tags
    are the fallback when the J9b destination graph is unavailable. Proximity to
    a retained footprint protects service access conservatively, not a door claim.
    """
    geoms={f['id']:shape(f['geometry']) for f in features}
    city=[f for f in features if f.get('properties',{}).get('highway') in CAR_HIGHWAYS]
    city_lines=unary_union([geoms[f['id']] for f in city])
    public_routes=unary_union(destination_routes).buffer(rules.snap_tolerance_m)
    def grade(f):return int(f.get('properties',{}).get('layer') or 0)
    def connected(a,b):return grade(a)==grade(b) and geoms[a['id']].distance(geoms[b['id']])<=1e-6
    def outside_reachable(point, omitted):
        reached={f['id'] for f in city if f['id']!=omitted['id'] and grade(f)==grade(omitted) and point.distance(geoms[f['id']])<=1e-6}
        pending=list(reached)
        while pending:
            identity=pending.pop();f=next(f for f in city if f['id']==identity)
            if geoms[identity].difference(site).length>1e-6:return True
            for other in city:
                if other['id']!=omitted['id'] and other['id'] not in reached and connected(f,other):
                    reached.add(other['id']);pending.append(other['id'])
        return False
    # Polygonize the whole same-grade slow network: OSM closed spaces may be
    # split over several open ways. Do not infer a small ring from one way only.
    small_ids=set()
    for layer in {grade(f) for f in features}:
        slow=[f for f in features if grade(f)==layer and f.get('properties',{}).get('highway') in ('footway','cycleway','path','pedestrian')]
        cycles=polygonize(unary_union([geoms[f['id']].intersection(site) for f in slow]))
        for cycle in cycles:
            if max(cycle.bounds[2]-cycle.bounds[0],cycle.bounds[3]-cycle.bounds[1])/2<rules.small_loop_radius_m:
                for f in slow:
                    if geoms[f['id']].intersection(cycle.boundary).length>1e-6:
                        # Boundary-crossing destination links remain frozen;
                        # internal fragmented loop ways are replaced by S4.
                        if geoms[f['id']].difference(site).length<=1e-6:small_ids.add(f['id'])
    rows=[]
    for f in features:
        g=geoms[f['id']];p=f.get('properties',{})
        if g.intersection(site).length<=1e-6:continue
        highway=p.get('highway');ends=[Point(g.coords[0]),Point(g.coords[-1])]
        through=highway in CAR_HIGHWAYS and all(not site.contains(e) or outside_reachable(e,f) for e in ends)
        dead=highway=='service' and any(site.contains(e) and not any(other['id']!=f['id'] and connected(f,other) and e.distance(geoms[other['id']])<=1e-6 for other in features) for e in ends)
        small=f['id'] in small_ids or (g.is_ring and max(g.bounds[2]-g.bounds[0],g.bounds[3]-g.bounds[1])/2<rules.small_loop_radius_m)
        public=p.get('access') not in ('private','no')
        tagged_destination=any(p.get(k) for k in ('destination','destination:ref','route','network','ref')) and g.difference(site).length>1e-6
        matched_destination=highway in ('footway','cycleway','path','pedestrian') and g.intersection(public_routes).length>=rules.minimum_segment_m
        destination=public and not small and (tagged_destination or matched_destination)
        alongside=highway in ('cycleway','footway') and not city_lines.is_empty and g.intersection(site).difference(city_lines.buffer(rules.bicycle_adjacency_m)).length<=1e-6
        dependent=highway in ('service','living_street') and any(g.distance(b)<=rules.fire_distance_m for b in retained_buildings)
        if through:
            disposition='retained';reason='兩端接基地外城市網路，保留城市穿越功能與原幾何。'
        elif small:
            disposition='removed';reason='半徑小於15m的單一或複合內部小環；由乾淨共享走廊取代。'
        elif destination or alongside:
            disposition='retained';reason='公共目的地標籤／J9b transit 路徑幾何匹配，或沿城市道路慢行走廊；保留公共連續。'
        elif dependent:
            disposition='retained';reason='保留建築40m內既有服務路，缺實際門資料時保守保障服務入口。'
        elif small:
            disposition='removed';reason='半徑小於15m封閉小圈，DRAFT清理廣場輪廓或內圈。'
        elif highway in ('service','track','footway','path','cycleway','steps','pedestrian') or p.get('service')=='parking_aisle':
            disposition='transformed' if dead and rules.transform_dead_end_service else 'removed'
            reason='基地內工業支路／停車支道／零碎慢行路，無城市穿越或目的地證據；由連通共享路網取代。'
        else:
            disposition='retained';reason='無足夠分類證據，保留並列為待審；不推定通行權。'
        rows.append(Disposition(source_id=f['id'],disposition=disposition,reason=reason,rule_card_id='MOB-008',highway=highway,through_city=through,dead_end_service=dead))
    return rows


def percentile(value, sample):
    values=sorted(sample)
    if len(values)<2 or values[0]==values[-1]: return None
    return 100*(bisect_left(values,value)+bisect_right(values,value))/(2*len(values))


def strategy_targets(family,rules):
    levels={'radial':('High','Medium','Low'),'axial':('High','Medium','Low'),
            'grid':('Medium','Medium','Medium'),'green_service':('High','Medium','Low')}[family]
    return [Target(hierarchy=h,mode=m,radius_m=800 if m=='pedestrian' else 2000,level=level)
            for m in ('pedestrian','bicycle') for h,level in zip(('main','branch','internal'),levels)]


def diagnose_entrances(site, contexts, external, diagnosis_weights=None):
    """Use the frozen <=3km NAIN/NACH distribution; intersect exact source lines.

    Optional J9b weights must be explicit, finite, nonnegative. No station data
    are invented. Stored syntax geometry is rounded, so source intersections,
    not the rounded display coordinates, determine entrance locations.
    """
    result={};samples={}
    for mode,doc in contexts.items():
        rows=[r for r in doc['segments'] if r['distance_to_site_m']<=3000]
        samples[mode]=[r['nain'] for r in rows]
        by_source={}
        for r in rows:by_source.setdefault(r['source_line_id'],[]).append(r)
        for f in external[mode]:
            line=shape(f['geometry']);p=f.get('properties',{})
            if int(p.get('layer') or 0)!=0 or p.get('bridge') in ('yes',True) or p.get('tunnel') in ('yes',True):continue
            cross=line.intersection(site.boundary)
            points=[cross] if cross.geom_type=='Point' else [g for g in getattr(cross,'geoms',()) if g.geom_type=='Point']
            rs=by_source.get(f['id'],[])
            if not rs:continue
            # Nearest baseline segment at each exact contact, not whole-road mean.
            for point in points:
                r=min(rs,key=lambda r:LineString(r['coordinates']).distance(point))
                rank=percentile(r['nain'],samples[mode])
                weight=(rank or 0)/100+r['nach']
                if diagnosis_weights is not None:
                    extra=diagnosis_weights.get(f['id'],0)
                    if not math.isfinite(extra) or extra<0:raise ValueError('invalid J9b weight')
                    weight+=extra
                key=tuple(round(v,6) for v in point.coords[0]);row=result.setdefault(key,dict(id=f'entry-{len(result)}',coordinates=point.coords[0],modes=[],source_ids={},weight=0))
                if mode not in row['modes']:row['modes'].append(mode)
                row['source_ids'].setdefault(mode,[]).append(f['id']);row['weight']=max(row['weight'],weight)
    # Motor gates use exact source boundary crossings, independently of the
    # pedestrian/cycle Syntax context. Service circuits require these contacts.
    for f in external.get('motor_vehicle',[]):
        line=shape(f['geometry']);properties=f.get('properties',{})
        if int(properties.get('layer') or 0)!=0 or properties.get('bridge') in ('yes',True) or properties.get('tunnel') in ('yes',True):continue
        if line.difference(site).length<=1e-6:continue
        cross=line.intersection(site.boundary)
        points=[cross] if cross.geom_type=='Point' else [g for g in getattr(cross,'geoms',()) if g.geom_type=='Point']
        for point in points:
            key=tuple(round(v,6) for v in point.coords[0]);row=result.setdefault(key,dict(id=f'entry-{len(result)}',coordinates=point.coords[0],modes=[],source_ids={},weight=0))
            if 'motor_vehicle' not in row['modes']:row['modes'].append('motor_vehicle')
            row['source_ids'].setdefault('motor_vehicle',[]).append(f['id'])
    return sorted([Entrance(**r) for r in result.values()],key=lambda e:(-e.weight,e.id)),samples


def _road(line,id,rules,hierarchy='branch',service=False,park=False):
    return NetworkRoad(id=id,coordinates=list(line.coords),width_m=rules.service_width_m if service else rules.main_shared_width_m if hierarchy=='main' else rules.shared_width_m,
        modes=['pedestrian','bicycle','motor_vehicle'] if service else ['pedestrian','bicycle'],origin='new',
        semantics_provenance='ASSUMED_COMMANDER; DRAFT',hierarchy='service' if service else hierarchy,
        width_class='service' if service else 'main_shared' if hierarchy=='main' else 'shared',access='service_only' if service else 'public',
        rule_card_ids=['MOB-001','MOB-015','POR-006' if service else 'MOB-001'],park_shared=park,
        active_frontage_candidate_sides='both' if hierarchy=='main' and not service and not park else None)


class _VisibilityRouter:
    """Shortest visible polygon path. No road is cut into orphan fragments."""
    def __init__(self, domain):
        self.domain=domain
        self.cover=domain.buffer(1e-7)
        self.vertices=list(dict.fromkeys(tuple(c) for ring in [domain.exterior,*domain.interiors] for c in list(ring.coords)[:-1]))
        self.edges={i:[] for i in range(len(self.vertices))}
        for i,a in enumerate(self.vertices):
            for j in range(i):
                b=self.vertices[j]
                if self.cover.covers(LineString([a,b])):
                    d=math.dist(a,b);self.edges[i].append((j,d));self.edges[j].append((i,d))
    def route(self,a,b):
        a=tuple(a);b=tuple(b)
        if math.dist(a,b)<1e-6:return None
        if self.cover.covers(LineString([a,b])):return LineString([a,b])
        vs=[*self.vertices,a,b];start=len(vs)-2;end=start+1
        edges={k:list(v) for k,v in self.edges.items()};edges[start]=[];edges[end]=[]
        for i in (start,end):
            for j in range(i):
                if self.cover.covers(LineString([vs[i],vs[j]])):
                    d=math.dist(vs[i],vs[j]);edges[i].append((j,d));edges[j].append((i,d))
        distances={start:0};parents={};queue=[(0,start)]
        while queue:
            distance,i=heapq.heappop(queue)
            if distance!=distances[i]:continue
            if i==end:
                path=[end]
                while path[-1]!=start:path.append(parents[path[-1]])
                return LineString([vs[j] for j in reversed(path)])
            for j,d in edges[i]:
                if distance+d<distances.get(j,float('inf')):
                    distances[j]=distance+d;parents[j]=i;heapq.heappush(queue,(distance+d,j))
        raise ValueError('No obstacle-safe route between planned nodes')


@lru_cache(maxsize=16)
def _router(domain):
    return _VisibilityRouter(domain)


def clean_path(line,domain,rules):
    """Remove redundant vertices only when the replacement remains in free land."""
    coords=list(line.coords);cover=domain.buffer(1e-7)
    changed=True
    while changed and len(coords)>2:
        changed=False
        for i in range(1,len(coords)-1):
            a,b,c=coords[i-1:i+2];chord=LineString([a,c])
            if math.dist(a,c)<rules.minimum_segment_m:continue
            redundant=Point(b).distance(chord)<1e-7
            near=math.dist(a,b)<rules.minimum_segment_m or math.dist(b,c)<rules.minimum_segment_m
            if (redundant or near) and cover.covers(chord):
                coords.pop(i);changed=True;break
    return LineString(coords)


def reattach_fixed_junctions(roads,domain,rules):
    """Replace acute new/frozen crossings by same-grade perpendicular contacts.

    Both sides of the new path remain connected, including its original ends.
    Unsafe or too tightly spaced junctions are left unchanged and reported.
    """
    fixed_segments=[(r.layer,LineString([a,b])) for r in roads if r.origin=='retained' for a,b in zip(r.coordinates,r.coordinates[1:]) if math.dist(a,b)>1e-7]
    tree=STRtree([g for _,g in fixed_segments]);cover=domain.buffer(1e-7)
    repaired=[];rejected=[];result=[]
    offset=rules.minimum_segment_m*2
    for road in roads:
        if road.origin=='retained':continue
        coords=[road.coordinates[0]]
        for a,b in zip(road.coordinates,road.coordinates[1:]):
            segment=LineString([a,b]);changes=[]
            for index in tree.query(segment):
                layer,existing=fixed_segments[int(index)]
                if layer!=road.layer:continue
                crossing=segment.intersection(existing)
                if crossing.geom_type!='Point':continue
                c,d=existing.coords;ux,uy=b[0]-a[0],b[1]-a[1];vx,vy=d[0]-c[0],d[1]-c[1]
                denominator=math.hypot(ux,uy)*math.hypot(vx,vy)
                if not denominator:continue
                angle=math.degrees(math.acos(max(-1,min(1,abs((ux*vx+uy*vy)/denominator)))))
                if angle>=rules.minimum_turn_deg or angle<1e-5:continue
                distance=segment.project(crossing)
                before=distance;after=segment.length-distance
                if min(before,after)<offset*2:
                    rejected.append({'road_id':road.id,'coordinates':list(crossing.coords[0]),'angle_deg':angle,'reason':'insufficient_room_for_perpendicular_approach'});continue
                nx,ny=-vy/math.hypot(vx,vy),vx/math.hypot(vx,vy)
                sign=1 if (a[0]-crossing.x)*nx+(a[1]-crossing.y)*ny>=0 else -1
                p=(crossing.x+sign*offset*nx,crossing.y+sign*offset*ny)
                q=(crossing.x-sign*offset*nx,crossing.y-sign*offset*ny)
                left=segment.interpolate(distance-offset*2).coords[0];right=segment.interpolate(distance+offset*2).coords[0]
                path=LineString([left,p,crossing.coords[0],q,right])
                if not cover.covers(path) or not path.is_simple:
                    rejected.append({'road_id':road.id,'coordinates':list(crossing.coords[0]),'angle_deg':angle,'reason':'perpendicular_approach_leaves_free_land'});continue
                changes.append((distance,list(path.coords),crossing,angle))
            cursor=-float('inf')
            for distance,path,crossing,angle in sorted(changes,key=lambda c:c[0]):
                if distance-offset*2<cursor:continue
                coords.extend(path);cursor=distance+offset*2
                repaired.append({'road_id':road.id,'coordinates':list(crossing.coords[0]),'before_angle_deg':angle,'contact_angle_deg':90})
            coords.append(b)
        candidate=LineString(coords)
        if candidate.is_simple:
            result.append(road.model_copy(update={'coordinates':coords}))
        else:
            result.append(road)
            repaired=[r for r in repaired if r['road_id']!=road.id]
            rejected.append({'road_id':road.id,'reason':'reattachment_self_intersection'})
    return result,{'reattached_count':len(repaired),'reattached':repaired,'rejected':rejected,'scope':rules.scope}


def merge_junction_nodes(roads,domain,rules,anchors=()):
    """Node first, contract close planned junctions, then rebuild incident edges.

    Frozen source coordinates are never rewritten. A contraction is allowed only
    when every incident new edge stays in free land; its metadata and connected
    endpoints survive. A collapsed necessary link becomes a shared node, not an
    orphan deleted road. All unsuccessful contractions remain for strict checks.
    """
    fixed=[r for r in roads if r.origin=='retained']
    sources=[LineString(r.coordinates) for r in roads]
    tree=STRtree(sources)
    support=unary_union(sources)
    vertices={};positions=[];edges=[]
    def node(c):
        key=tuple(round(v,8) for v in c)
        if key not in vertices:
            vertices[key]=len(positions);positions.append(tuple(c))
        return vertices[key]
    for part in _parts(support):
        for a,b in zip(part.coords,part.coords[1:]):
            line=LineString([a,b]);mid=line.interpolate(.5,normalized=True)
            owners=[int(i) for i in tree.query(mid.buffer(1e-7)) if roads[int(i)].origin!='retained' and sources[int(i)].distance(mid)<=1e-7]
            if owners:edges.append([node(a),node(b),owners])
    parents=list(range(len(positions)))
    fixed_lines=unary_union([LineString(r.coordinates) for r in fixed])
    fixed_vertices=[Point(c) for r in fixed for c in r.coordinates]
    protected=[*fixed_vertices,*[Point(e.coordinates) for e in anchors]]
    def root(i):
        while parents[i]!=i:i=parents[i]
        return i
    cover=domain.buffer(1e-7);merges=[];rejected=[]
    pairs=[];points=[Point(c) for c in positions];point_tree=STRtree(points)
    for i,p in enumerate(points):
        for j in point_tree.query(p.buffer(rules.minimum_segment_m)):
            j=int(j)
            if j<i and p.distance(points[j])<rules.minimum_segment_m:pairs.append((p.distance(points[j]),j,i))
    for distance,i,j in sorted(pairs):
        i=root(i);j=root(j)
        if i==j:continue
        a,b=Point(positions[i]),Point(positions[j])
        distance=a.distance(b)
        if distance>=rules.minimum_segment_m:
            rejected.append({'coordinates':[positions[i],positions[j]],'distance_m':distance,'reason':'current_representatives_not_a_short_connection'});continue
        pa=any(a.distance(p)<1e-7 for p in protected);pb=any(b.distance(p)<1e-7 for p in protected)
        if pa and pb and a.distance(b)>1e-7:continue
        fa=not fixed_lines.is_empty and a.distance(fixed_lines)<1e-7
        fb=not fixed_lines.is_empty and b.distance(fixed_lines)<1e-7
        # Two distinct new contacts on the frozen alignment can share one
        # contact; an original fixed vertex or external entry takes priority.
        keep,drop=(i,j) if pa or (fa and not pb) or (not pb and not fb) else (j,i)
        replacement=positions[keep];safe=True
        for u,v,_ in edges:
            u=root(u);v=root(v)
            if drop not in (u,v):continue
            other=v if u==drop else u
            if other==keep:continue
            if not cover.covers(LineString([replacement,positions[other]])):safe=False;break
        if not safe:
            rejected.append({'coordinates':[positions[i],positions[j]],'distance_m':distance,'reason':'incident_edge_would_leave_free_land'});continue
        parents[drop]=keep
        merges.append({'from':positions[drop],'to':replacement,'distance_m':distance})
    grouped={};collapsed=[]
    for u,v,owners in edges:
        a,b=positions[root(u)],positions[root(v)]
        if a==b:
            collapsed.append({'road_ids':[roads[o].id for o in owners],'coordinates':a});continue
        for owner in owners:grouped.setdefault(owner,[]).append(LineString([a,b]))
    from shapely.ops import linemerge
    rebuilt=[]
    for owner,lines in grouped.items():
        union=unary_union(lines)
        geometry=linemerge(union) if union.geom_type=='MultiLineString' else union
        for i,line in enumerate(_parts(geometry)):
            rebuilt.append(roads[owner].model_copy(update={'id':roads[owner].id+(f':merged:{i}' if len(_parts(geometry))>1 else ''),'coordinates':list(line.coords)}))
    return rebuilt,{'merged_node_count':len(merges),'merges':merges,'collapsed_connections':collapsed,'rejected_merges':rejected,'scope':rules.scope}


def connect_support(lines,domain,rules):
    """Join complete components through free land, preserving frozen geometry."""
    domains=[g for g in getattr(domain,'geoms',(domain,)) if g.geom_type=='Polygon' and g.area>1e-6]
    bridges=[]
    for _ in range(len(lines)):
        parts=_parts(unary_union([*lines,*bridges]));tree=STRtree(parts)
        unseen=set(range(len(parts)));groups=[]
        while unseen:
            reached={min(unseen)};pending=list(reached)
            while pending:
                i=pending.pop()
                for j in tree.query(parts[i].buffer(1e-6)):
                    j=int(j)
                    if j in unseen and j not in reached and parts[i].distance(parts[j])<=1e-6:
                        reached.add(j);pending.append(j)
            unseen-=reached;groups.append(unary_union([parts[i] for i in reached]))
        if len(groups)<=1:return bridges,[]
        candidates=[]
        for d in domains:
            for i,a in enumerate(groups):
                aa=a.intersection(d)
                if aa.is_empty:continue
                for b in groups[:i]:
                    bb=b.intersection(d)
                    if bb.is_empty:continue
                    p,q=nearest_points(aa,bb)
                    if p.distance(q)<1e-6:continue
                    try:route=_router(d).route(p.coords[0],q.coords[0])
                    except ValueError:continue
                    if route is not None:candidates.append(route)
        if not candidates:return bridges,['disconnected_support_no_free_land_route']
        bridges.append(min(candidates,key=lambda g:(g.length,g.wkb_hex)))
    return bridges,['disconnected_support_iteration_limit']


def connect_modes(roads,domain,rules,identity):
    """Physical union connectivity cannot substitute for per-mode connectivity."""
    additions=[];failures=[]
    for mode in ('pedestrian','bicycle','motor_vehicle'):
        lines=[LineString(r.coordinates).intersection(domain.buffer(1e-7)) for r in [*roads,*additions] if mode in r.modes and r.layer==0]
        bridges,errors=connect_support(lines,domain,rules)
        failures.extend(mode+':'+e for e in errors)
        for i,bridge in enumerate(bridges):
            if mode=='motor_vehicle' and bridge.length>40:
                failures.append('motor_service_connector_over_40m:'+str(bridge.length))
                continue
            additions.append(_road(bridge,identity+f':mode-bridge:{mode}:{i}',rules,'branch',mode=='motor_vehicle'))
    return additions,failures


def generate_variants(site,retained,entrances,family,rules,*,angle=0,fixed_roads=()):
    """Construct connected outer circuits then anchored family paths in free space.

    Boundary rings and retained-building service rings are connected before
    any block/building exists. Chords route around obstacles instead of clipping.
    A disconnected land component remains explicit for the connectivity validator.
    """
    local=affinity.rotate(site,-angle,origin=(0,0))
    obstacles=unary_union([affinity.rotate(g,-angle,origin=(0,0)).buffer(rules.retained_setback_m+rules.service_width_m/2+.1,join_style=2) for g in retained])
    domain=local.buffer(-rules.service_width_m,join_style=2).difference(obstacles)
    components=[p for p in getattr(domain,'geoms',(domain,)) if p.geom_type=='Polygon']
    routers=[_router(p) for p in components]
    core_component=max(range(len(components)),key=lambda i:components[i].area) if components else None
    major_entries=[]
    for e in entrances:
        if not {'pedestrian','bicycle'}.intersection(e.modes):continue
        if all(Point(e.coordinates).distance(Point(o.coordinates))>=40 for o in major_entries):major_entries.append(e)
        if len(major_entries)==6:break
    variants=[]
    for index,(spacing,shift) in enumerate(((64.,0.),(80.,12.),(96.,-12.))):
        lines=[];cores=[];bands=[];failures=[];spoke_labels={}
        for ci,(poly,router) in enumerate(zip(components,routers)):
            outer=clean_path(LineString(poly.exterior.coords),poly,rules)
            # All later endpoints refer to this stable circuit.
            from shapely.geometry import Polygon
            poly=Polygon(outer.coords,[list(r.coords) for r in poly.interiors])
            router=_router(poly)
            outer=LineString(poly.exterior.coords);lines.append((outer,'service',True,False))
            # A single exterior circuit plus short straight service branches.
            # No per-building rings, and no routed zigzag spur after placement.
            for ring in poly.interiors:
                hole=LineString(ring.coords)
                p,q=nearest_points(outer,hole)
                distance=p.distance(q)
                if distance+rules.retained_setback_m<=rules.fire_distance_m:continue
                length=min(40.,max(rules.minimum_segment_m+.001,distance-rules.fire_distance_m+rules.retained_setback_m+rules.service_width_m+.1))
                if length>=distance:continue
                end=LineString([p,q]).interpolate(length)
                branch=LineString([p,end])
                if router.cover.covers(branch):lines.append((branch,'service',True,False))
                else:failures.append('straight_service_branch_unavailable')
            minx,miny,maxx,maxy=poly.bounds
            def chord(g,h,service=False,park=False):
                # The endpoints come from the outer circuit, even with holes.
                shell=poly.__class__(poly.exterior)
                for part in _parts(g.intersection(shell)):
                    a,b=part.coords[0],part.coords[-1]
                    try:lines.append((router.route(a,b),h,service,park))
                    except ValueError as exc:failures.append(str(exc))
            centre=poly.representative_point()
            # Use a public core that fits free space; bounded trial nodes are
            # selected geometrically, no invented destination/context values.
            from shapely.ops import polylabel
            clearance=polylabel(poly,tolerance=.5)
            lead=affinity.rotate(Point(major_entries[0].coordinates),-angle,origin=(0,0)) if major_entries else poly.centroid
            desired=Point(.75*poly.centroid.x+.25*lead.x+shift,.75*poly.centroid.y+.25*lead.y)
            candidates=[Point(x,y) for x in range(math.ceil(minx),math.floor(maxx),10) for y in range(math.ceil(miny),math.floor(maxy),10)]
            candidates=[p for p in candidates if poly.contains(p) and p.distance(poly.boundary)>rules.core_radius_m+.1]
            centre=min(candidates,key=lambda p:p.distance(desired)) if candidates else clearance
            core_radius=min(rules.core_radius_m,centre.distance(poly.boundary)-.1)
            if family=='radial' and ci==core_component:
                if core_radius<rules.shared_width_m:
                    failures.append('central_core_clearance_insufficient')
                else:
                    core=centre.buffer(core_radius,quad_segs=4)
                    cores.append(core);ring=LineString(core.exterior.coords)
                    lines.append((ring,'main',False,True))
                    access_domain=local.difference(obstacles)
                    radial_entries=[];bearings=[]
                    for e in entrances:
                        if not {'pedestrian','bicycle'}.intersection(e.modes):continue
                        point=affinity.rotate(Point(e.coordinates),-angle,origin=(0,0))
                        bearing=math.atan2(point.y-centre.y,point.x-centre.x)
                        if any(abs(math.atan2(math.sin(bearing-b),math.cos(bearing-b)))<math.radians(30) for b in bearings):continue
                        radial_entries.append(e);bearings.append(bearing)
                        if len(radial_entries)==6:break
                    for ei,e in enumerate(radial_entries):
                        anchor=affinity.rotate(Point(e.coordinates),-angle,origin=(0,0))
                        q=nearest_points(anchor,ring)[1]
                        paths=[g for g in getattr(access_domain,'geoms',(access_domain,)) if g.geom_type=='Polygon' and g.buffer(1e-7).covers(anchor) and g.buffer(1e-7).covers(q)]
                        if not paths:
                            failures.append('radial_spoke_unavailable:'+e.id);continue
                        route=_router(paths[0]).route(anchor.coords[0],q.coords[0])
                        lines.append((route,'main',False,False))
                        spoke_labels[id(route)]='radial-spoke:'+str(ei)
            elif family in ('axial','green_service'):
                # A continuous shared spine through the land, with an exact
                # northern source entrance and a central run, not a setback line.
                candidates=[e for e in major_entries if poly.distance(affinity.rotate(Point(e.coordinates),-angle,origin=(0,0)))<=rules.service_width_m+.01]
                lead=affinity.rotate(Point(candidates[0].coordinates),-angle,origin=(0,0)) if candidates else None
                y=poly.representative_point().y+shift
                axis=LineString([(minx-1,y),(maxx+1,y)])
                runs=_parts(axis.intersection(poly.__class__(poly.exterior)))
                if runs:
                    run=max(runs,key=lambda g:g.length)
                    a,b=map(Point,(run.coords[0],run.coords[-1]))
                    if lead is not None and lead.distance(a)>lead.distance(b):a,b=b,a
                    try:
                        trunk=router.route(a.coords[0],b.coords[0])
                        if lead is not None:
                            access=[p for p in getattr(local.difference(obstacles),'geoms',(local.difference(obstacles),)) if p.geom_type=='Polygon' and p.buffer(1e-7).covers(lead) and p.buffer(1e-7).covers(a)]
                            if not access:raise ValueError('major_entry_axis_connection_unavailable')
                            arrival=_router(access[0]).route(lead.coords[0],a.coords[0])
                            if arrival is not None:trunk=LineString([*arrival.coords,*list(trunk.coords)[1:]])
                        lines.append((trunk,'main',False,family=='green_service'))
                        if family=='green_service':
                            bands.append(trunk.buffer(rules.green_band_width_m/2).intersection(poly.buffer(-rules.service_width_m,join_style=2)))
                    except ValueError as exc:failures.append(str(exc))
            for i in range(1,math.ceil((maxx-minx)/spacing)) if family!='radial' else ():
                x=minx+i*spacing+shift
                if x>=maxx:continue
                chord(LineString([(x,miny-1),(x,maxy+1)]),'branch',service=family in ('grid','axial') and i%2==0,park=family=='green_service')
            if family=='grid':
                for j in range(1,math.ceil((maxy-miny)/spacing)):
                    y=miny+j*spacing+shift
                    if y<maxy:chord(LineString([(minx-1,y),(maxx+1,y)]),'internal',service=j%2==0)
        # Exact entry contacts bridge the setback gap to their preplanned circuit.
        for e in entrances:
            # Contacts already served by exact frozen modes need no nearly
            # parallel setback connector; component joining follows below.
            present={m for r in fixed_roads if LineString(r.coordinates).distance(Point(e.coordinates))<=1e-6 for m in r.modes}
            if set(e.modes)<=present:continue
            p=affinity.rotate(Point(e.coordinates),-angle,origin=(0,0))
            if not components:continue
            ci=min(range(len(components)),key=lambda i:components[i].distance(p))
            q=nearest_points(p,LineString(components[ci].exterior.coords))[1]
            access=local.difference(obstacles)
            domains=[g for g in getattr(access,'geoms',(access,)) if g.geom_type=='Polygon' and g.buffer(1e-7).covers(p) and g.buffer(1e-7).covers(q)]
            if not domains:failures.append('entry_route_unavailable:'+e.id);continue
            if p.distance(q)>1e-6:
                route=_router(domains[0]).route(p.coords[0],q.coords[0])
                lines.append((route,'main','motor_vehicle' in e.modes,False))
        # Connect whole support components; a retained route may already join
        # other retained ways, so nearest-point attachment per way is insufficient.
        support=[g for g,_,_,_ in lines if g is not None]
        support.extend(affinity.rotate(LineString(r.coordinates),-angle,origin=(0,0)).intersection(local) for r in fixed_roads)
        bridges,errors=connect_support(support,local.difference(obstacles),rules)
        failures.extend(errors)
        lines.extend((g,'branch',False,False) for g in bridges)
        # Merge exact duplicate geometric support, preserve priority of service
        # access. Near coincidences are diagnosed rather than shifting city roads.
        roads=[];covered=LineString()
        for j,(g,h,service,park) in enumerate(sorted(lines,key=lambda r:not r[2])):
            if g is None:continue
            safe_local=local.difference(obstacles)
            g_clean=g if g.is_ring and service else clean_path(g,safe_local,rules)
            world=affinity.rotate(g_clean,angle,origin=(0,0))
            if not covered.is_empty:
                snapped=snap(world,covered,rules.snap_tolerance_m)
                safe=site.difference(unary_union([b.buffer(rules.retained_setback_m+rules.service_width_m/2) for b in retained]))
                if safe.buffer(1e-7).covers(snapped):world=snapped
            remainder=world.difference(covered) if world.intersection(covered).length>1e-6 else world
            for k,part in enumerate(_parts(remainder)):
                if part.length>1e-6:roads.append(_road(part,f'{family}-{index}-{j}-{k}'+(':'+spoke_labels[id(g)] if id(g) in spoke_labels else ''),rules,h,service,park))
            covered=unary_union([covered,world])
        # Vertex cleanup may change junction support. Reconcile topology against
        # frozen roads after cleanup; never assert connected from a prior graph.
        final_lines=[affinity.rotate(LineString(r.coordinates),-angle,origin=(0,0)).intersection(local) for r in [*fixed_roads,*roads]]
        final_bridges,errors=connect_support(final_lines,local.difference(obstacles),rules)
        failures.extend(errors)
        for bi,bridge in enumerate(final_bridges):
            roads.append(_road(affinity.rotate(bridge,angle,origin=(0,0)),f'{family}-{index}:topology-bridge:{bi}',rules,'branch',False))
        mode_bridges,errors=connect_modes([*fixed_roads,*roads],site.difference(unary_union([b.buffer(rules.retained_setback_m+rules.service_width_m/2+.1,join_style=2) for b in retained])),rules,f'{family}-{index}')
        roads.extend(mode_bridges);failures.extend(errors)
        variants.append(Variant(id=f'{family}-{index}',family=family,roads=roads,parameters={
            'spacing_m':spacing,'axis_angle_deg':angle,'axis_shift_m':shift,'entry_connection':'visibility path to preplanned outer circuit',
            'service_loop':True,'central_core':[mapping(affinity.rotate(g,angle,origin=(0,0))) for g in cores],
            'green_band':[mapping(affinity.rotate(g,angle,origin=(0,0))) for g in bands],
            'construction_failures':failures,'provenance':'ASSUMED_COMMANDER','status':'DRAFT',
            'geometry_rules':rules.model_dump()}))
    return variants


def syntax_roads(roads,mode,rules=None):
    rules=rules or NetworkRules()
    return [ProposalRoad(**{k:v for k,v in r.model_dump().items() if k in ProposalRoad.model_fields}) for r in roads
            if mode in r.modes and not (mode=='motor_vehicle' and r.access=='service_only' and not rules.service_in_motor_syntax)]


def derive_blocks(site,roads,retained,water,rules,public_spaces=()):
    roads_surface=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads])
    exclusions=unary_union([roads_surface,*public_spaces,water.buffer(rules.waterfront_band_m),*[g.buffer(rules.retained_setback_m) for g in retained]])
    buildable=site.difference(exclusions)
    return sorted([g for g in (buildable.geoms if hasattr(buildable,'geoms') else (buildable,)) if g.geom_type=='Polygon' and g.area>1e-6],key=lambda g:(g.bounds,g.area))


def geometry_quality(site,roads,blocks,entrances,rules):
    fixed_by_source={source:r for r in roads if r.origin=='retained' for source in r.source_road_ids}
    inherited=[]
    for r in roads:
        if r.origin!='new' or not r.source_road_ids:continue
        matched=[fixed_by_source[k] for k in r.source_road_ids if k in fixed_by_source and fixed_by_source[k].layer==r.layer]
        if matched and len(matched)==len(r.source_road_ids):
            support=unary_union([LineString(f.coordinates) for f in matched])
            if LineString(r.coordinates).difference(support.buffer(1e-7)).length<=1e-7:inherited.append(r.id)
    new=[r for r in roads if r.origin=='new' and r.id not in inherited];dead=[];angles=[];angle_violations=[]
    support=unary_union([LineString(r.coordinates).intersection(site) for r in roads])
    parts=_parts(support);tree=STRtree(parts)
    source_lines=[LineString(r.coordinates) for r in roads]
    source_tree=STRtree(source_lines)
    junctions={};junction_sources={};ignored_retained_angles=[]
    def ray_sources(a,b):
        ray=LineString([a,b]);mid=ray.interpolate(min(ray.length/2,.01))
        return [int(i) for i in source_tree.query(mid.buffer(1e-7)) if source_lines[int(i)].distance(mid)<=1e-7]

    for line in parts:
        for coords,neighbour in ((line.coords[0],line.coords[1]),(line.coords[-1],line.coords[-2])):
            key=tuple(round(v,6) for v in coords)
            vector=(neighbour[0]-coords[0],neighbour[1]-coords[1])
            if math.hypot(*vector)>1e-6:
                junctions.setdefault(key,[]).append(vector)
                junction_sources.setdefault(key,[]).append(ray_sources(coords,neighbour))
    for position,vectors in junctions.items():
        for i,u in enumerate(vectors):
            for j,v in enumerate(vectors[:i]):
                owners=set(junction_sources[position][i]+junction_sources[position][j])
                angle=math.degrees(math.acos(max(-1,min(1,(u[0]*v[0]+u[1]*v[1])/(math.hypot(*u)*math.hypot(*v))))))
                if angle>1e-5:
                    detail={'coordinates':position,'angle_deg':angle,'deficit_deg':rules.minimum_turn_deg-angle,'road_ids':sorted(roads[k].id for k in owners)}
                    if owners and all(roads[k].origin=='retained' or roads[k].id in inherited for k in owners):
                        if angle<rules.minimum_turn_deg:ignored_retained_angles.append(detail)
                        continue
                    angles.append(angle)
                    if angle<rules.minimum_turn_deg:angle_violations.append(detail)
    short=[{'road_id':r.id,'coordinates':[a,b],'length_m':math.dist(a,b),'deficit_m':rules.minimum_segment_m-math.dist(a,b)} for r in new for a,b in zip(r.coordinates,r.coordinates[1:]) if math.dist(a,b)<rules.minimum_segment_m]
    # Junction noding creates physical segments too; a long source polyline
    # must not conceal a sub-3m fragment produced by a retained-road crossing.
    for part in parts:
        if 1e-9<part.length<rules.minimum_segment_m:
            ids=[r.id for r in new if part.difference(LineString(r.coordinates).buffer(1e-7)).length<=1e-7]
            if ids:short.append({'road_id':ids[0],'road_ids':ids,'coordinates':list(part.coords),'length_m':part.length,
                'deficit_m':rules.minimum_segment_m-part.length,'kind':'junction_fragment'})
    # Connectivity is a property of the whole road network: links via a retained
    # road just outside the land, or a bridge over the canal, are real. Count
    # components on unclipped road lines; clipping is kept for angles/dead ends.
    whole=_parts(unary_union([LineString(r.coordinates) for r in roads if r.layer==0]))
    whole_tree=STRtree(whole)
    components=[];unseen=set(range(len(whole)))
    while unseen:
        reached={min(unseen)};frontier=list(reached)
        while frontier:
            i=frontier.pop()
            for j in whole_tree.query(whole[i].buffer(1e-6)):
                j=int(j)
                if j in unseen and j not in reached and whole[i].distance(whole[j])<=1e-6:reached.add(j);frontier.append(j)
        unseen-=reached;components.append(sorted(reached))
    for r in new:
        line=LineString(r.coordinates)
        for c in (line.coords[0],line.coords[-1]):
            p=Point(c)
            if line.is_ring or any(p.distance(Point(e.coordinates))<1e-6 for e in entrances):continue
            if not any(o.id!=r.id and p.distance(LineString(o.coordinates))<1e-6 for o in roads):dead.append((r.id,c))
        cs=list(line.coords)
        for a,b,c in zip(cs,cs[1:],cs[2:]):
            u=(a[0]-b[0],a[1]-b[1]);v=(c[0]-b[0],c[1]-b[1]);den=math.hypot(*u)*math.hypot(*v)
            if den:angles.append(math.degrees(math.acos(max(-1,min(1,(u[0]*v[0]+u[1]*v[1])/den)))))
    total_dead=[]
    for coords,vectors in junctions.items():
        if len(vectors)!=1:continue
        point=Point(coords)
        if any(point.distance(Point(e.coordinates))<1e-6 for e in entrances):continue
        exterior_contact=point.distance(site.boundary)<=1e-6 and any(LineString(r.coordinates).distance(point)<=1e-6 and LineString(r.coordinates).difference(site).length>1e-6 for r in roads)
        if not exterior_contact:total_dead.append(coords)
    new_dead=dead
    dead=total_dead
    dimensions=[]
    residual=[]
    for block in blocks:
        # A remnant that cannot hold the narrowest building footprint (inscribed
        # width < residual_open_space_width_m) is a verge/green strip, not a block.
        # It is reported in full, never hidden (Commander 2026-10-08, DRAFT rule).
        if block.buffer(-rules.residual_open_space_width_m/2).is_empty:
            residual.append({'area_m2':block.area,'bounds':list(block.bounds),'centroid':list(block.centroid.coords[0])})
            continue
        cs=list(block.minimum_rotated_rectangle.exterior.coords)
        lengths=[math.dist(a,b) for a,b in zip(cs,cs[1:])]
        dimensions.append({'area_m2':block.area,'min_m':min(lengths),'max_m':max(lengths),
            'bounds':list(block.bounds),'centroid':list(block.centroid.coords[0]),'in_range':min(lengths)>=rules.block_min_m and max(lengths)<=rules.block_max_m})
    block_good=bool(dimensions) and all(d['in_range'] for d in dimensions)
    minimum=min(angles,default=180)
    valid=minimum>=rules.minimum_turn_deg and len(dead)<=rules.max_dead_ends and block_good and not short and len(components)==1
    score=(sum(d['in_range'] for d in dimensions)/len(dimensions) if dimensions else 0)+max(0,1-len(dead)/max(1,rules.max_dead_ends))
    return {'valid':valid,'scope':rules.scope,'ignored_retained_angles':ignored_retained_angles,'inherited_geometry_permission_overlays':inherited,'geometry_score':score/2,'dead_end_count':len(dead),'new_dead_end_count':len(new_dead),'minimum_turn_deg':minimum,
        'connected_component_count':len(components),'angle_violations':angle_violations,'short_segments':short,'minimum_segment_pass':not short,'dead_ends':dead,'block_dimensions':dimensions,'block_range_pass':block_good,'residual_open_space':residual,'residual_open_space_area_m2':sum(r['area_m2'] for r in residual),'rule_card_ids':['MOR-002'],'provenance':'ASSUMED_COMMANDER'}


def _distance(g,network):
    if network.is_empty:return None
    return max(p.distance(network) for p in (g.geoms if g.geom_type=='MultiPolygon' else (g,)))


def hard_checks(*,site,roads,buildings,retained_before,retained_after,water,entrances,external,rules,public_spaces=()):
    surfaces=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads])
    bicycle=unary_union([LineString(r.coordinates) for r in roads if 'bicycle' in r.modes])
    ped=unary_union([LineString(r.coordinates) for r in roads if 'pedestrian' in r.modes])
    fire=unary_union([LineString(r.coordinates).buffer(r.width_m/2) for r in roads if 'motor_vehicle' in r.modes])
    overlap=unary_union(buildings).intersection(surfaces).area
    adjacent_area=ped.buffer(rules.bicycle_adjacency_m)
    adjacency=all(not ped.is_empty and LineString(r.coordinates).intersection(site).difference(adjacent_area).length<=1e-6 for r in roads if 'bicycle' in r.modes)
    bike_dist=[_distance(g,bicycle) for g in buildings];fire_dist=[_distance(g,fire) for g in buildings]
    connected=True;entry_report=[]
    for mode in ('pedestrian','bicycle'):
        selected=[r for r in roads if mode in r.modes and r.layer==0]
        gs=[LineString(r.coordinates) for r in selected];reached=set()
        tree=STRtree(gs)
        for e in entrances:
            if mode not in e.modes:continue
            point=Point(e.coordinates)
            ext=[f for f in external.get(mode,[]) if f['id'] in e.source_ids.get(mode,[])]
            valid_ext=any(int(f.get('properties',{}).get('layer') or 0)==0 and shape(f['geometry']).distance(point)<=1e-6
                          and shape(f['geometry']).difference(site).length>1e-6 for f in ext)
            touching={i for i,g in enumerate(gs) if g.distance(point)<=1e-6}
            ok=bool(valid_ext and touching);connected &= ok
            if ok:reached.update(touching)
            entry_report.append({'entry_id':e.id,'mode':mode,'connected':ok})
        frontier=list(reached)
        while frontier:
            i=frontier.pop()
            neighbours={int(j) for j in tree.query(gs[i].buffer(1e-6)) if int(j) not in reached and gs[i].distance(gs[int(j)])<=1e-6}
            reached.update(neighbours);frontier.extend(neighbours)
        if len(reached)!=len(gs) or not gs:connected=False
    # Service-only streets still need real same-grade motor access from outside.
    motor_roads=[r for r in roads if 'motor_vehicle' in r.modes and r.layer==0]
    motor=[LineString(r.coordinates) for r in motor_roads]
    motor_external=[shape(f['geometry']) for f in external.get('motor_vehicle',[])
                    if int(f.get('properties',{}).get('layer') or 0)==0
                    and shape(f['geometry']).difference(site).length>1e-6]
    external_tree=STRtree(motor_external)
    motor_tree=STRtree(motor)
    reached_motor={i for i,g in enumerate(motor) if any(g.distance(motor_external[int(j)])<=1e-6 for j in external_tree.query(g.buffer(1e-6)))}
    pending=list(reached_motor)
    while pending:
        i=pending.pop()
        linked={int(j) for j in motor_tree.query(motor[i].buffer(1e-6)) if int(j) not in reached_motor and motor[i].distance(motor[int(j)])<=1e-6}
        reached_motor.update(linked);pending.extend(linked)
    connected_fire=unary_union([motor[i].buffer(motor_roads[i].width_m/2) for i in sorted(reached_motor)])
    fire_dist=[_distance(g,connected_fire) for g in buildings]
    retained_fire_dist={k:_distance(g,connected_fire) for k,g in retained_before.items()}
    unchanged=set(retained_before)==set(retained_after) and all(g.equals_exact(retained_after[k],1e-9) for k,g in retained_before.items())
    checks={'public_space_clear':all(not g.intersects(unary_union(public_spaces)) for g in buildings),'road_overlap':all(not g.intersects(surfaces) for g in buildings),'retained_intact':unchanged,'bicycle_adjacency':adjacency,
        'bicycle_distance':bool(buildings) and all(d is not None and d<=rules.bicycle_distance_m for d in bike_dist),
        'fire_service':bool(buildings) and all(d is not None and d<=40 for d in fire_dist),
        'retained_fire_service':all(d is not None and d<=40 for d in retained_fire_dist.values()),
        'entrance_connectivity':bool(entrances) and connected,
        'waterfront':all(not g.intersects(water.buffer(15)) for g in buildings),
        'site_containment':all(site.covers(g) for g in buildings),
        'retained_setback':all(not g.intersects(unary_union(list(retained_before.values())).buffer(rules.retained_setback_m)) for g in buildings)}
    return {'status':'VALID' if all(checks.values()) else 'INVALID','checks':checks,'road_overlap_area_m2':overlap,
        'bicycle_distances_m':bike_dist,'fire_distances_m':fire_dist,'retained_fire_distances_m':retained_fire_dist,'entrances':entry_report,
        'limitations':['Footprint/component proximity proxy, not verified doors, parking, legal access or fire compliance.'],
        'rule_card_ids':list(rules.rule_card_ids)}


def score_targets(targets,roads,results,samples,rules):
    report=[]
    road_lookup={r.id:r for r in roads}
    measured={}
    for mode,result in results.items():
        for row in (result.get('after') or {}).get('segments',[]):
            if not row.get('inside_site',True):continue
            source=row.get('source_line_id','')
            if not source.startswith('proposal:'):continue
            identity=source[len('proposal:'):].split(':part:')[0]
            if identity not in road_lookup and identity.endswith(('_a','_b')):identity=identity[:-2]
            parent=road_lookup.get(identity)
            if parent is None:raise ValueError('target segment parent road unavailable')
            line=LineString(row['coordinates'])
            # Numerical relationship tolerance follows PST's 1 mm input segment
            # identity grid; it is not a design-quality or target threshold.
            if line.difference(LineString(parent.coordinates).buffer(.001)).length>1e-6:
                raise ValueError('target source id and segment geometry disagree')
            measured.setdefault((mode,parent.hierarchy),[]).append(row['nain'])
    for target in targets:
        lines=unary_union([LineString(r.coordinates) for r in roads if r.hierarchy==target.hierarchy and target.mode in r.modes])
        rows=(results.get(target.mode,{}).get('after') or {}).get('segments',[])
        values=measured.get((target.mode,target.hierarchy),[])
        if not values and any('source_line_id' not in r for r in rows):
            values=[r['nain'] for r in rows if 'source_line_id' not in r and r.get('inside_site',True) and LineString(r['coordinates']).intersection(lines).length>1e-6]
        actual=sum(values)/len(values) if values else None
        rank=percentile(actual,samples[target.mode]) if actual is not None else None
        low,high={'High':(rules.high_percentile,100),'Medium':(rules.medium_percentile,rules.high_percentile),'Low':(0,rules.medium_percentile)}[target.level]
        attained=rank is not None and low<=rank and (rank<high or target.level=='High')
        distance=None if rank is None else max(low-rank,rank-high,0)
        report.append({**target.model_dump(),'actual_mean_nain':actual,'actual_percentile':rank,'segment_count':len(values),
            'status':'達成' if attained else '部分' if distance is not None and distance<=10 else '未達成',
            'score':1 if attained else max(0,1-distance/100) if distance is not None else 0})
    return report,sum(r['score'] for r in report)/len(report)


def select_variant(rows):
    eligible=[r for r in rows if r['quality']['valid']]
    return max(eligible,key=lambda r:(.7*r['target_score']+.3*r['geometry_score'],r['id'])) if eligible else None
