"""J12b deterministic, copy-only design rules; no approval or state writes."""
import math
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.ops import unary_union, nearest_points
from shapely import affinity


def noon_sun_altitude(latitude=51.9, declination=0.):
    """Solar noon: altitude = 90 - |latitude - declination| (degrees)."""
    return 90 - abs(latitude-declination)


def dakpark_plates(footprint, floors, park, first, standard, park_height=10.):
    """Diagonal section envelope: each upper plate retreats from park edge.

    1m retreat per metre above the two-storey interface is a declared DRAFT
    design rule, not a sunlight guarantee. Actual noon shadow lengths are
    reported separately using the assumed park datum.
    """
    plates=[]
    for level in range(floors):
        retreat=max(0,level-1)*standard
        plate=footprint.difference(park.buffer(footprint.distance(park)+retreat,join_style=2)) if retreat else footprint
        if plate.is_empty or plate.area<120:raise ValueError('Dakpark retreat eliminates usable plate')
        plates.append(plate)
    height=first+(floors-1)*standard
    sunlight={}
    for name,dec in [('winter_solstice',-23.44),('equinox',0.)]:
        altitude=noon_sun_altitude(declination=dec)
        shadow=max(0,height-park_height)/math.tan(math.radians(altitude))
        # Only northward shadow can reach a park north of the mass. This
        # distance screening does not claim hourly/daylight compliance.
        north=footprint.centroid.y<park.centroid.y
        swept=[]
        for level,plate in enumerate(plates):
            h=first+level*standard
            dy=max(0,h-park_height)/math.tan(math.radians(altitude))
            # Polygon sweep north: shadow of an elevated plate at solar noon.
            for part in [plate] if plate.geom_type=='Polygon' else plate.geoms:
                moved=affinity.translate(part,yoff=dy)
                swept.extend([part,moved])
                for a,b in zip(part.exterior.coords,list(part.exterior.coords)[1:]):
                    if dy:swept.append(Polygon([a,b,(b[0],b[1]+dy),(a[0],a[1]+dy)]))
        overlap=unary_union(swept).intersection(park).area
        distance=footprint.distance(park)
        sunlight[name]=dict(altitude_deg=altitude,shadow_above_park_m=shadow,
            edge_distance_m=distance,northward_park=north,
            edge_reach_possible=overlap>1e-6,park_shadow_area_m2=overlap)
    return plates,dict(latitude_deg=51.9,park_datum_m=park_height,
        datum_status='ASSUMED_PORTFOLIO_P21',retreat_per_upper_floor_m=standard,
        method='solar noon altitude=90-|latitude-declination|; shadow=max(0,H-10)/tan(altitude); northward distance screen',
        results=sunlight,limitation='Two-date noon screening only; not E1 simulation or sunlight compliance.')


def facade_segments(geometry, roads, high_lines, plazas=(), entrances=()):
    """Split actual exterior edges into <=5m pieces; require outward facing support.

    The nearest public support must be within 18m and within 45 degrees of
    the outward normal. Courtyard edges and perpendicular end walls excluded.
    """
    road_support=unary_union([LineString(r.coordinates) for r in roads if 'pedestrian' in r.modes])
    high=unary_union(high_lines)
    public=unary_union(list(plazas)+[p.buffer(12) for p in entrances])
    if road_support.is_empty:return []
    edges=[]
    for poly in [geometry] if geometry.geom_type=='Polygon' else geometry.geoms:
        for a,b in zip(poly.exterior.coords,list(poly.exterior.coords)[1:]):
            whole=LineString([a,b]);n=max(1,math.ceil(whole.length/5))
            dx,dy=b[0]-a[0],b[1]-a[1];length=whole.length
            if length<1:continue
            nx,ny=-dy/length,dx/length
            midpoint=whole.interpolate(.5,normalized=True)
            from shapely.geometry import Point
            if poly.covers(Point(midpoint.x+nx*.1,midpoint.y+ny*.1)):nx,ny=-nx,-ny
            for i in range(n):
                edge=LineString([whole.interpolate(i/n,normalized=True),whole.interpolate((i+1)/n,normalized=True)])
                mid=edge.interpolate(.5,normalized=True)
                def facing(support,limit):
                    if support.is_empty:return False
                    target=nearest_points(mid,support)[1];vx,vy=target.x-mid.x,target.y-mid.y
                    dist=math.hypot(vx,vy)
                    return 0<dist<=limit and (vx*nx+vy*ny)/dist>=math.sqrt(.5)
                if not facing(road_support,18):continue
                active=facing(high,18) or facing(public,18)
                edges.append(dict(geometry=mapping(edge),length_m=edge.length,active=active,
                    reason_zh='朝向步行800公尺前30%路段／廣場／入口' if active else '沿街一般立面',
                    rule_card_ids=['SYN-002','PUB-004']))
    return edges


def streetwall_continuity(high_lines,buildings):
    """Projected frontage coverage on each side; only perimeter/L count.

    Denominator is total unique high-NAIN centreline length. Numerator is
    the intersection of left and right covered intervals, never one side.
    """
    left_total=right_total=both=length=0.
    support=unary_union(high_lines)
    lines=[support] if support.geom_type=='LineString' else getattr(support,'geoms',[])
    for line in lines:
        cs=list(line.coords)
        for a,b in zip(cs,cs[1:]):
            dx,dy=b[0]-a[0],b[1]-a[1];L=math.hypot(dx,dy)
            if not L:continue
            sides={-1:[],1:[]}
            for building in buildings:
                if building['type_id'] not in ('block.perimeter','building.courtyard_closed','building.l_block'):continue
                for edge in building.get('facade_segments',[]):
                    xy=shape(edge['geometry']);mid=xy.interpolate(.5,normalized=True)
                    side=(dx*(mid.y-a[1])-dy*(mid.x-a[0]))/L
                    if abs(side)>18 or abs(side)<.01:continue
                    points=list(xy.coords);ex,ey=points[-1][0]-points[0][0],points[-1][1]-points[0][1]
                    if abs(ex*dx+ey*dy)/(xy.length*L)<math.sqrt(.5):continue
                    projections=[((x-a[0])*dx+(y-a[1])*dy)/L for x,y in points]
                    lo=max(0,min(projections));hi=min(L,max(projections))
                    if hi>lo:sides[1 if side>0 else -1].append(LineString([(lo,0),(hi,0)]))
            l=unary_union(sides[1]);r=unary_union(sides[-1]);length+=L
            left_total+=l.length;right_total+=r.length;both+=l.intersection(r).length
    return dict(streetwall_continuity_ratio=both/length if length else 0.,high_integration_street_length_m=length,
        bilateral_streetwall_length_m=both,left_streetwall_length_m=left_total,right_streetwall_length_m=right_total,
        streetwall_method='perimeter/L exterior facade projected intervals within18m; BOTH sides intersection')


def named_open_spaces(open_space, water, high_nodes):
    """Disjoint named activity polygons; 12m morphological clearance screen.

    Water strip and 40m node squares are explicit programme assumptions.
    Narrow residuals include access corridors: reported, never hidden as parks.
    """
    def parts(g):
        if g.geom_type=='Polygon':return [g]
        return [p for p in getattr(g,'geoms',[]) if p.geom_type=='Polygon']
    usable=open_space.buffer(-6,join_style=2).buffer(6,join_style=2).intersection(open_space)
    remaining=usable;spaces=[]
    def assign(g,name,use):
        for poly in sorted(parts(g),key=lambda p:-p.area):
            if poly.area<200:continue
            spaces.append(dict(name_zh=name+' '+str(len(spaces)+1),use_zh=use,area_m2=poly.area,
                geometry=mapping(poly),rule_card_ids=['PUB-004','POR-017'],status='DRAFT_USE_PROPOSAL'))
    waterfront=remaining.intersection(water.buffer(40));assign(waterfront,'潮汐水岸公園','水岸步行、雨水滯留與生態緩衝')
    remaining=remaining.difference(waterfront)
    chosen=[]
    for p in sorted(high_nodes,key=lambda p:p.distance(open_space.centroid)):
        if all(p.distance(q)>=80 for q in chosen):chosen.append(p)
        if len(chosen)==3:break
    plazas=remaining.intersection(unary_union([p.buffer(20,cap_style=3) for p in chosen]))
    assign(plazas,'整合節點廣場','入口集散、市集與停留');remaining=remaining.difference(plazas)
    assign(remaining,'中央食物園','社區種植、休憩與食物教育')
    assigned=unary_union([shape(s['geometry']) for s in spaces])
    residual=open_space.difference(assigned)
    remnants=[dict(area_m2=p.area,geometry=mapping(p),reason_zh='未配置殘地（12公尺淨寬初篩或小於200平方公尺片段）；通路／維護用途待設計') for p in parts(residual) if p.area>1e-6]
    return spaces,remnants


def revision_checks(buildings, metrics, *, upper_far=.8, upper_coverage=.35, upper_height=20):
    """Independent measured checks, usable by generator and figure guard."""
    res=[b for b in buildings if b['floors'][-1]['use'] in ('Residential','Mixed')]
    area=sum(b['footprint_area_m2'] for b in res)
    avg=sum(sum(shape(f['geometry']).area for f in b['floors']) for b in res)/area if area else 0
    edges=[e for b in buildings for e in b.get('facade_segments',[])]
    street=sum(e['length_m'] for e in edges)
    active=sum(e['length_m'] for e in edges if e['active'])
    ratio=active/street if street else 0
    return dict(residential_mixed_average_floors=avg>=4-1e-8,
        low_floor_reasons=all(b['floor_count']>=4 or bool(b.get('low_floor_reason_zh')) and bool(b.get('low_floor_rule_card_ids')) for b in buildings),
        far_range=.70-1e-8<=metrics['far']<=min(.8,upper_far)+1e-8,
        coverage_upper=metrics['coverage']<=min(.35,upper_coverage)+1e-8,
        height_upper=all(b['height_m']<=min(20,upper_height)+1e-8 for b in buildings),
        active_frontage_limit=street>0 and ratio<=.5+1e-8),dict(
            residential_mixed_area_weighted_floors=avg,active_frontage_length_m=active,
            new_street_facade_length_m=street,active_frontage_ratio=ratio)
