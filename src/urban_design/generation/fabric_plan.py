"""Deterministic exploratory fabric plans. No persistence, I/O, or approval effects."""
from __future__ import annotations
import copy
import math
from shapely.geometry import shape, mapping, box, LineString, Point, Polygon
from shapely.ops import unary_union, nearest_points, polygonize, linemerge
from shapely.affinity import rotate, translate

# ASSUMED: Founder 2026-10-15, exact 85% of 146,873 m2.
NEW_GFA_MIN_M2 = 146873 * .85

MODES = ['pedestrian', 'bicycle', 'car', 'service', 'fire']
FABRICS = ('fabric.harbour_grain', 'fabric.closed_block_extension', 'fabric.courtyard_islands', 'fabric.landscape_figure')

def _feature(g, ident, **properties):
    return {'type': 'Feature', 'id': ident, 'geometry': mapping(g), 'properties': {'id': ident, **properties}}

def _parts(g):
    return list(g.geoms) if hasattr(g, 'geoms') else ([] if g.is_empty else [g])

def _geom(row):
    return shape(row['geometry'])

def _mean(v):
    return (v['minimum'] + v['maximum']) / 2

def generate_plan(facts: dict, context: dict, fabric: dict, intent: dict | None = None, *, primary_geometry_override: LineString | None = None, transverse_geometry_overrides: list[LineString] | None = None) -> dict:
    """Generate orthogonal street cells and templates without clipping massing.

    Search is deterministic in two dimensions; complete block cells share a
    common street grid reserved before building templates are placed.
    """
    if not isinstance(fabric, dict): raise ValueError('FABRIC_DICTIONARY_REQUIRED')
    fid=fabric['id']
    if fid not in FABRICS: raise ValueError('UNSUPPORTED_FABRIC')
    if facts['geometry']['crs']!='EPSG:28992' or context['horizontal_crs']!='EPSG:28992': raise ValueError('CRS_MISMATCH')
    intent=copy.deepcopy(intent or {})
    if not shape(facts['geometry']['waterfront_band']).is_empty and 'street_width_m' in intent and intent['street_width_m']!=18:raise ValueError('INTENT_OUT_OF_BOUNDS:street_width_m:本輪主街實際可用完整路幅為18m')
    hierarchy=fabric['street_network']['hierarchy']
    bounds={'block_long_m':fabric['blocks']['long_edge_m'],'block_short_m':fabric['blocks']['short_edge_m'],
            'street_width_m':hierarchy[0]['section_width_m'],'building_depth_m':{'minimum':12,'maximum':14},
            'target_gfa_m2':{'minimum':NEW_GFA_MIN_M2,'maximum':146873},'seam_width_m':{'minimum':20,'maximum':40}}
    base_orientation={'fabric.harbour_grain':context['site']['principal_axis']['long_axis_azimuth_deg'],
                      'fabric.closed_block_extension':137.,'fabric.courtyard_islands':context['site']['principal_axis']['long_axis_azimuth_deg'],
                      'fabric.landscape_figure':context['site']['principal_axis']['long_axis_azimuth_deg']}[fid]
    if set(intent)-set(bounds)-{'orientation_deg'}: raise ValueError('UNKNOWN_INTENT_PARAMETER:'+','.join(sorted(set(intent)-set(bounds)-{'orientation_deg'})))
    for k,v in intent.items():
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('INTENT_OUT_OF_BOUNDS:'+k)
        if k=='orientation_deg':
            if min(abs(v-base_orientation)%180,180-abs(v-base_orientation)%180)>5:raise ValueError('INTENT_OUT_OF_BOUNDS:'+k)
        elif not bounds[k]['minimum']<=v<=bounds[k]['maximum']:raise ValueError('INTENT_OUT_OF_BOUNDS:'+k)
    p={k:intent.get(k,v['minimum'] if k in ('block_long_m','block_short_m','seam_width_m') else _mean(v)) for k,v in bounds.items()}
    if fid=='fabric.courtyard_islands':
        p['block_short_m']=intent.get('block_short_m',75.)
        p['block_long_m']=intent.get('block_long_m',115.)
        p['building_depth_m']=intent.get('building_depth_m',14.)
    if fid=='fabric.landscape_figure':p['block_short_m']=intent.get('block_short_m',fabric['blocks']['short_edge_m']['maximum'])
    orientation=intent.get('orientation_deg',base_orientation)
    if not shape(facts['geometry']['waterfront_band']).is_empty:p['street_width_m']=18.
    angle=90-orientation+(90 if fid=='fabric.closed_block_extension' else 0)
    site=shape(facts['geometry']['site']);water=site.intersection(shape(facts['geometry']['water']));land=site.difference(water)
    origin=(site.centroid.x,site.centroid.y)
    local=lambda g:rotate(g,-angle,origin=origin);world=lambda g:rotate(g,angle,origin=origin)
    retained=copy.deepcopy(facts.get('retained_buildings',[]))
    retained_geoms=[shape(r['geometry']) for r in facts['geometry']['retained_buildings']]
    exclusions=unary_union([g.buffer(3,join_style=2) for g in retained_geoms])
    waterfront=shape(facts['geometry']['waterfront_band']).intersection(land)
    dakpark=shape(facts['geometry']['dakpark'])
    seam=land.intersection(dakpark.buffer(p['seam_width_m'])) if fid in ('fabric.closed_block_extension','fabric.landscape_figure') else Polygon()
    # A retained building is a fixed plot inside a street cell, not a veto on a
    # whole block. Footprint templates must fit actual supplied buildable geometry.
    planned_parks=[]
    if not waterfront.is_empty:
        long_angle=90-context['site']['principal_axis']['long_axis_azimuth_deg']
        sl=rotate(land,-long_angle,origin=origin);sx0,sy0,sx1,sy1=sl.bounds
        park_width=113 if fid=='fabric.landscape_figure' else (59 if fid=='fabric.closed_block_extension' else (55 if fid=='fabric.courtyard_islands' else 42))
        # Northeast southern flank is clear of the retained anchors. A long
        # rectangle is reserved first, with city streets serving its edge.
        park_start=sx1-(320 if fid=='fabric.landscape_figure' else 330)
        if fid=='fabric.landscape_figure':
            span=sx1-sx0
            green_y=sy0+145
            green_top=green_y+34
            bridge_x=sx0+.51*span
            northern_y=sy1-25
            east_x=sx1-65
            # A connected five-unit green axis, measured against the frozen
            # coast/buildings, reaches from the SW district towards Dakpark.
            # Every management unit is rectangular and has its own identity.
            proposals=[box(sx0+25,green_y,sx0+.58*span,green_top),
                       box(sx0+.56*span,sy0+120,sx0+.58*span,green_y+.2),
                       box(east_x,sy0+65-.2,sx1-45,green_top),
                       box(sx0+.68*span,sy0+30,sx1-45,sy0+65+.2)]
            # Dissolve the overlapping east park and its stem before allocation
            # so they retain one actual management boundary after road cuts.
            proposals[-2:]=[unary_union(proposals[-2:])]
            # Short management units preserve a real green connection without
            # creating a parallel vehicle street through the narrow green band.
            start=sx0+.56*span;end=sx1-45
            count=math.ceil((end-start)/90)
            for index in range(count):
                proposals.append(box(start+index*(end-start)/count-.1,sy0+120,start+(index+1)*(end-start)/count+.1,sy0+128))
        else:
            proposals=[box(park_start,sy0+18,sx1-45,sy0+18+park_width)]
        for proposal in proposals:
            pg=rotate(proposal,long_angle,origin=origin)
            if fid=='fabric.landscape_figure' or (land.covers(pg) and pg.intersection(exclusions).area<.01):
                rectangle=proposal;pieces=[rotate(pg.intersection(land).difference(exclusions),-long_angle,origin=origin)] if fid=='fabric.landscape_figure' else [rectangle]
                for rr in facts['geometry']['retained_roads']:
                    city_row=rotate(shape(rr['geometry']).buffer(float(rr.get('width_m',rr.get('properties',{}).get('width_m',6)))/2 if fid=='fabric.landscape_figure' else 4,cap_style=2),-long_angle,origin=origin)
                    if city_row.intersection(rectangle).area>.01:
                        ux0,uy0,ux1,uy1=city_row.bounds
                        strip=city_row if fid=='fabric.landscape_figure' else box(ux0,rectangle.bounds[1]-1,ux1,rectangle.bounds[3]+1)
                        pieces=[part for piece in pieces for part in _parts(piece.difference(strip)) if part.geom_type=='Polygon']
                planned_parks.extend(rotate(piece,long_angle,origin=origin) for piece in pieces if piece.area>=(1 if fid=='fabric.landscape_figure' else 1000))

    # Reserve the through street before searching for blocks. A later road
    # reservation would erase wings while leaving an artificially sparse block.
    axis_angle=90-context['site']['principal_axis']['long_axis_azimuth_deg']
    axis_land=rotate(land,-axis_angle,origin=origin)
    ax0,ay0,ax1,ay1=axis_land.bounds
    primary_geometry=LineString()
    if not waterfront.is_empty:
        corners=sorted(list(axis_land.exterior.coords)[:-1],key=lambda q:q[1],reverse=True)[:2]
        corners.sort()
        primary_geometry=rotate(LineString([(corners[0][0]+12,corners[0][1]-9.2),(corners[1][0]-12,corners[1][1]-9.2)]),axis_angle,origin=origin).intersection(land)
    if primary_geometry_override is not None:
        if primary_geometry_override.geom_type != 'LineString' or primary_geometry_override.is_empty or not primary_geometry_override.is_valid:
            raise ValueError('PRIMARY_GEOMETRY_OVERRIDE_INVALID')
        if primary_geometry_override.buffer(9,cap_style=2,join_style=2).difference(land).area > .05:
            raise ValueError('PRIMARY_GEOMETRY_OVERRIDE_FULL_WIDTH_OUTSIDE_LAND')
        primary_geometry=primary_geometry_override
    fixed_primary_row=primary_geometry.buffer(9,cap_style=2,join_style=2)
    transverse_geometry_overrides=transverse_geometry_overrides or []
    if transverse_geometry_overrides and fid not in ('fabric.courtyard_islands','fabric.landscape_figure'):
        raise ValueError('TRANSVERSE_OVERRIDE_FABRIC_NOT_AUTHORIZED')
    for route in transverse_geometry_overrides:
        if route.geom_type!='LineString' or route.is_empty or not route.is_valid or route.buffer(2,cap_style=2).difference(land).area>.05:
            raise ValueError('TRANSVERSE_OVERRIDE_INVALID')
    transverse_row=unary_union([g.buffer(2,cap_style=2) for g in transverse_geometry_overrides])
    island_secondary=LineString()
    if fid=='fabric.courtyard_islands' and not waterfront.is_empty:
        primary_local=rotate(primary_geometry,-axis_angle,origin=origin)
        secondary_x=ax0+.72*(ax1-ax0)
        city_end=nearest_points(Point(secondary_x,ay0+80),primary_local)[1]
        candidate=rotate(LineString([(secondary_x,ay0+80),city_end]),axis_angle,origin=origin)
        surface=candidate.buffer(8,cap_style=2,join_style=2)
        if land.buffer(1e-7).covers(surface) and surface.intersection(unary_union(retained_geoms)).area<.01:
            island_secondary=candidate
    if fid=='fabric.courtyard_islands' and not waterfront.is_empty:
        # Minimum-size islands reserve their shared grid first; coherent
        # public parks are fitted in the remaining actual land after streets.
        planned_parks=[];island_secondary=LineString()
        north_park=rotate(box(ax0+.23*(ax1-ax0),ay1-63,ax0+.38*(ax1-ax0),ay1-31),axis_angle,origin=origin)
        if land.buffer(1e-7).covers(north_park) and north_park.intersection(exclusions).area<=.01 and north_park.intersection(fixed_primary_row).area<=.01:planned_parks=[north_park]
    island_secondary_row=island_secondary.buffer(8,cap_style=2,join_style=2)
    park_reservation=unary_union(planned_parks)
    block_domain=land.difference(transverse_row).difference(waterfront).difference(seam).difference(park_reservation).difference(fixed_primary_row).difference(island_secondary_row)
    buildable=shape(facts['geometry']['buildable']).intersection(land).difference(exclusions)
    retained_roads=copy.deepcopy(facts['geometry']['retained_roads'])
    preserved_row=unary_union([shape(r['geometry']).buffer(3,cap_style=2) for r in retained_roads])
    buildable=buildable.difference(transverse_row).difference(preserved_row).difference(park_reservation).difference(fixed_primary_row).difference(island_secondary_row)
    a=local(block_domain);x0,y0,x1,y1=a.bounds
    w,h=p['block_long_m'],p['block_short_m'];gap=hierarchy[min(1,len(hierarchy)-1)]['section_width_m']['minimum']
    if fid=='fabric.landscape_figure':gap=max(gap,12)
    if fid=='fabric.harbour_grain':gap=float(hierarchy[2]['section_width_m']['maximum'])
    if fid=='fabric.courtyard_islands':gap=16.
    # Full rectangular street cells at a bounded 4 m two-dimensional lattice.
    # Evaluate four deterministic traversal orders, retain maximum covered area.
    def shared_cells(domain,frame_angle):
        domain=rotate(domain,-frame_angle,origin=origin)
        usable=rotate(buildable,-frame_angle,origin=origin)
        def capacity(cells):return sum(cell.difference(cell.buffer(-p['building_depth_m'],join_style=2)).intersection(usable).area for cell in cells)
        bx0,by0,bx1,by1=domain.bounds;chosen_best=[]
        best_capacity=-1.
        # One common x/y phase for the whole domain makes adjacent street-cell
        # edges genuinely shared, rather than independently sliding every row.
        for phase_y in range(0,math.ceil(h+gap),4):
            for phase_x in range(0,math.ceil(w+gap),4):
                chosen=[];yy=math.ceil(by0)+phase_y
                while yy+h<=by1:
                    xx=math.ceil(bx0)+phase_x
                    while xx+w<=bx1:
                        cell=box(xx,yy,xx+w,yy+h)
                        if domain.covers(cell):
                            if fid=='fabric.courtyard_islands':
                                court=box(xx+18,yy+24,xx+w-18,yy+h-18)
                                fixed=rotate(unary_union(retained_geoms+[preserved_row]),-frame_angle,origin=origin)
                                if court.intersection(fixed).area>.01 or rotate(court,frame_angle,origin=origin).intersection(fixed_primary_row).area>.01:
                                    xx+=w+gap;continue
                            chosen.append(cell)
                        xx+=w+gap
                    yy+=h+gap
                score=capacity(chosen)
                if score>best_capacity+1e-5:
                    chosen_best=chosen;best_capacity=score
        return [(cell,frame_angle) for cell in chosen_best]
    if fid=='fabric.closed_block_extension' and not waterfront.is_empty:
        long_angle=90-context['site']['principal_axis']['long_axis_azimuth_deg']
        ll=rotate(land,-long_angle,origin=origin);sx0,sy0,sx1,sy1=ll.bounds
        split_x=sx0+.62*(sx1-sx0)
        seam=rotate(box(split_x-p['seam_width_m']/2,sy0-20,split_x+p['seam_width_m']/2,sy1+20),long_angle,origin=origin).intersection(land)
        block_domain=block_domain.difference(seam)
        sw=rotate(box(sx0-100,sy0-100,split_x-p['seam_width_m']/2,sy1+100),long_angle,origin=origin)
        ne=rotate(box(split_x+p['seam_width_m']/2,sy0-100,sx1+100,sy1+100),long_angle,origin=origin)
        cells=shared_cells(block_domain.intersection(sw),long_angle)+shared_cells(block_domain.intersection(ne),angle)
    else:cells=shared_cells(block_domain,angle)
    if fid=='fabric.courtyard_islands' and not waterfront.is_empty and len(cells)<4:
        occupied_cells=unary_union([rotate(cell,frame,origin=origin) for cell,frame in cells])
        supplementary=shared_cells(block_domain.difference(occupied_cells.buffer(gap,join_style=2)),angle+90)
        for cell,frame in supplementary:
            world_cell=rotate(cell,frame,origin=origin)
            if all(world_cell.distance(rotate(other,other_frame,origin=origin))>=15-1e-6 for other,other_frame in cells):cells.append((cell,frame))
            if len(cells)>=4:break
    cells.sort(key=lambda pair:(pair[1],pair[0].bounds))
    best=[cell for cell,frame in cells];frames=[frame for cell,frame in cells]
    roads=[];blocks=[];buildings=[];courtyards=[];parcels=[]
    def road(g,width,role,modes=MODES,level=1):
        for part in _parts(g):
            if part.geom_type in ('LineString','LinearRing') and part.length>0.1:
                line=LineString(part.coords)
                roads.append(_feature(line,f'road-{len(roads)}',width_m=float(width),modes=list(modes),role=role,hierarchy=level))
    # The city-facing long street is fixed before massing and extends across
    # the complete site, rather than selecting a short residual after buildings.
    axis_angle=90-context['site']['principal_axis']['long_axis_azimuth_deg']
    axis_land=rotate(land,-axis_angle,origin=origin)
    ax0,ay0,ax1,ay1=axis_land.bounds
    if not waterfront.is_empty:
        road(primary_geometry,18,'primary_street',level=0)
        for route in transverse_geometry_overrides:road(route,4,'cross_street',level=1)
        if not island_secondary.is_empty:road(island_secondary,16,'secondary_street',level=1)
        if fid!='fabric.landscape_figure':
            for pg in planned_parks:
                park_street_width=5
                road(pg.buffer(park_street_width/2,join_style=2).exterior.intersection(land).difference(exclusions),park_street_width,'park_edge_street',level=1)
    if fid=='fabric.landscape_figure' and not waterfront.is_empty:
        for pg in planned_parks:
            pl=rotate(pg,-axis_angle,origin=origin);px0,py0,px1,py1=pl.bounds
            if px1-px0>=100:
                edge=LineString([(px0,py0-4),(px1,py0-4)])
            elif py1-py0>=100:
                edge=LineString([(px0-4,py0),(px0-4,py1)])
            else:continue
            edge=rotate(edge,axis_angle,origin=origin)
            row=edge.buffer(4,cap_style=2,join_style=2)
            if land.buffer(1e-7).covers(row) and row.intersection(exclusions).area<=.01:
                road(edge,8,'park_edge_street',level=1)
    # Construct, node and dissolve the public centreline grid first. Polygonise
    # its closed faces, then derive block interiors from those faces. Shared
    # neighbour edges exist once in the road array rather than as duplicate loops.
    skeleton=unary_union([rotate(r.buffer(gap/2,join_style=2).exterior,frames[i],origin=origin) for i,r in enumerate(best)])
    merged=linemerge(skeleton) if skeleton.geom_type!='LineString' else skeleton
    road(merged.intersection(land).difference(exclusions),gap,'block_edge_street',level=1)
    faces=list(polygonize(skeleton));derived=[]
    for i,reference in enumerate(best):
        reference_world=rotate(reference,frames[i],origin=origin)
        matching=[face for face in faces if face.covers(reference_world.centroid) and abs(face.area-(w+gap)*(h+gap))<.01]
        if not matching:continue
        interior=matching[0].buffer(-gap/2,join_style=2).simplify(1e-6)
        rectangle=rotate(interior,-frames[i],origin=origin).envelope
        if interior.symmetric_difference(rotate(rectangle,frames[i],origin=origin)).area>.01:continue
        derived.append((rectangle,frames[i]))
    best=[r for r,frame in derived];frames=[frame for r,frame in derived]
    for i,r in enumerate(best):
        blocks.append(_feature(rotate(r,frames[i],origin=origin),f'block-{i}',template='orthogonal_rectangle',short_m=h,long_m=w,axis_azimuth_deg=(90-frames[i])%180))
    for row in retained_roads:
        road(shape(row['geometry']),6,'retained_city_road',level=0)
        roads[-1]['properties']['source_id']=row['id']
    # External street continuity and hierarchy: primary local axis through the
    # free strip along the site edge; its actual geometry is clipped to land.
    for poly in _parts(land.difference(exclusions).buffer(-gap/2,join_style=2)):
        if poly.geom_type=='Polygon' and waterfront.is_empty:road(poly.exterior,gap,'boundary_connector',level=1)
    # Waterfront is a distinct walk/cycle path on the land side of each mapped
    # quay component. Its continuity is explicitly checked below.
    # Follow the full quay with a physical 10 m corridor. Coastal retained
    # footprints are fixed obstacles: the outward offset passes their landward
    # facades, rather than cutting the original band or deleting those buildings.
    coastal_fixed=[g for g in retained_geoms if g.distance(water)<=15]
    coast_obstacles=unary_union([water]+coastal_fixed)
    # Centreline feasibility is constructed before ROW generation. Do not clip
    # a delivered ROW to hide insufficient width at a quay or retained facade.
    coast_clear=land.buffer(-5.01,join_style=2).difference(unary_union(retained_geoms).buffer(5.01,join_style=2))
    coast_envelope=coast_obstacles.buffer(5.1,join_style=2)
    coast_lines=coast_envelope.boundary.intersection(coast_clear.buffer(1e-7))
    coast_parts=[g for g in _parts(coast_lines) if g.geom_type=='LineString' and g.length>.1]
    if coast_parts:
        connected=coast_parts[0]
        road(connected,10,'waterfront_path',['pedestrian','bicycle','service','fire'],2)
        for part in coast_parts[1:]:
            u,v=nearest_points(connected,part)
            link=_visible_route(u,v,coast_clear)
            if link is not None:
                road(link,10,'waterfront_path',['pedestrian','bicycle','service','fire'],2)
                connected=unary_union([connected,link,part])
            road(part,10,'waterfront_path',['pedestrian','bicycle','service','fire'],2)
        # Reserve genuinely available landward end/bypass edges as well. Some
        # frozen shoreline fragments may be physically inaccessible at 10 m;
        # validators retain that failure instead of inventing a narrow passage.
        edge=coast_clear.boundary.intersection(coast_obstacles.buffer(8,join_style=2)).difference(unary_union(coast_parts).buffer(.2))
        for part in _parts(edge):
            if part.geom_type=='LineString' and part.length>.1:
                u,v=nearest_points(connected,part)
                link=_visible_route(u,v,coast_clear)
                if link is not None:
                    road(link,10,'waterfront_path',['pedestrian','bicycle','service','fire'],2)
                    road(part,10,'waterfront_path',['pedestrian','bicycle','service','fire'],2)
                    connected=unary_union([connected,link,part])
    waterfront_detours=[]
    coastal_groups=_components([q for q in roads if q['properties']['role']=='waterfront_path'])
    coast_rows=[q for q in roads if q['properties']['role']=='waterfront_path']
    if len(coastal_groups)>1:
        detour_domain=land.buffer(-2.01,join_style=2).difference(unary_union(retained_geoms).buffer(2.01,join_style=2))
        candidates=[]
        for i,group in enumerate(coastal_groups):
            for other in coastal_groups[i+1:]:
                left=unary_union([_geom(coast_rows[j]) for j in group]);right=unary_union([_geom(coast_rows[j]) for j in other])
                u,v=nearest_points(left,right);link=_visible_route(u,v,detour_domain)
                if link is not None and link.length<=60:
                    surface=link.buffer(2,cap_style=2,join_style=2)
                    if land.buffer(1e-7).covers(surface) and surface.intersection(unary_union(retained_geoms)).area<=.01:candidates.append((link.length,link))
        for _,link in sorted(candidates,key=lambda row:row[0]):
            waterfront_detours.append(_feature(link,f'waterfront-detour-{len(waterfront_detours)}',purpose='component_connector',width_m=4.,length_m=link.length,name_zh='保留建築瓶頸替代步行路徑',role='waterfront_detour',modes=['pedestrian','bicycle'],reason_zh='10m公共水岸可行域於保留建築旁分離；採4m實體淨寬最短自由空間路徑，明示局部替代而非10m水岸'))
            road(link,4,'waterfront_detour',['pedestrian','bicycle'],2)
    if coast_parts:
        for width in (4.,2.):
            full_surface=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads if r['properties']['role']=='waterfront_path'])
            shoreline=water.boundary.intersection(waterfront.buffer(.05))
            served=full_surface.buffer(3.1).union(unary_union(coastal_fixed).buffer(15)).union(unary_union([_geom(d).buffer(d['properties']['width_m']/2,cap_style=2,join_style=2) for d in waterfront_detours]).buffer(3.1))
            local_gaps=shoreline.difference(served)
            detour_domain=land.buffer(-width/2-.01,join_style=2).difference(unary_union(retained_geoms).buffer(width/2+.01,join_style=2))
            local_coast=water.buffer(width/2+.1,join_style=2).boundary.intersection(detour_domain)
            public_coast=unary_union([_geom(r) for r in roads if r['properties']['role']=='waterfront_path'])
            for part in _parts(local_coast.intersection(local_gaps.buffer(10))):
                if part.geom_type!='LineString' or part.length<1 or part.distance(local_gaps)>5.1:continue
                first,last=Point(part.coords[0]),Point(part.coords[-1])
                start=nearest_points(first,public_coast)[1];end=nearest_points(last,public_coast)[1]
                incoming=_visible_route(start,first,detour_domain);outgoing=_visible_route(last,end,detour_domain)
                if incoming is None or outgoing is None:continue
                coords=list(incoming.coords)+list(part.coords)[1:]+list(outgoing.coords)[1:]
                route=LineString(coords);row=route.buffer(width/2,cap_style=2,join_style=2)
                served_gap=local_gaps.intersection(row.buffer(3.1)).length
                if route.length<=60 and served_gap>.1 and land.buffer(1e-7).covers(row) and row.intersection(unary_union(retained_geoms)).area<=.01:
                    waterfront_detours.append(_feature(route,f'waterfront-detour-{len(waterfront_detours)}',purpose='shoreline_bypass',width_m=width,length_m=route.length,name_zh=f'西南岸線局部替代步行路徑（淨寬{width:g}公尺）',role='waterfront_detour',modes=['pedestrian'] if width<4 else ['pedestrian','bicycle'],served_gap_geometry=mapping(local_gaps.intersection(row.buffer(3.1))),reason_zh='依保留建築及基地邊界的實體避障寬度配置局部步行通道，兩端接完整水岸，長度不超過60m；先試4m，幾何不容許時明示2m步行替代，不更改10m標準水岸要求',route_basis='shortest visibility connectors for fixed coast-offset segment endpoints'))
                    road(route,width,'waterfront_detour',['pedestrian'] if width<4 else ['pedestrian','bicycle'],2)
    primary_reservation=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads if r['properties']['role']=='primary_street'])
    buildable=buildable.difference(unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads]))
    for i,r in enumerate(best):
        world=lambda g:rotate(g,frames[i],origin=origin)
        local=lambda g:rotate(g,-frames[i],origin=origin)
        lx,ly,rx,ry=r.bounds;cell_w=rx-lx;cell_h=ry-ly;depth=p['building_depth_m'];bid=f'block-{i}'
        gate=world(box((lx+rx)/2-3,ly-gap/2,(lx+rx)/2+3,ly+depth+4)) if fid in ('fabric.closed_block_extension','fabric.courtyard_islands') else Polygon()
        if not gate.is_empty:road(world(LineString([((lx+rx)/2,ly-gap/2),((lx+rx)/2,ly+depth+4)])),6,'courtyard_service_gate',level=2)
        def building(rect,kind,depth_value,first=4.,max_floors=5):
            g=world(rect)
            if g.intersection(gate).area>1e-7:
                if kind in ('building.courtyard_closed','building.u_block','building.courtyard_open_corner','building.industrial_hall'):
                    for fragment in _parts(rect.difference(local(gate))):
                        if fragment.geom_type=='Polygon' and fragment.area>1 and abs(fragment.area-fragment.envelope.area)<1e-6:
                            building(fragment.envelope,kind,depth_value,first,max_floors)
                return
            if not buildable.buffer(1e-7).covers(g):
                ax,ay,bx,by=rect.bounds;replacement=None
                occupied=unary_union([_geom(q) for q in buildings])
                offsets=sorted([(dx,dy) for dx in range(-10,11,2) for dy in range(-10,11,2)],key=lambda q:(q[0]*q[0]+q[1]*q[1],q))
                for dx,dy in offsets:
                    candidate=box(ax+dx,ay+dy,bx+dx,by+dy);cg=world(candidate)
                    if r.covers(candidate) and buildable.buffer(1e-7).covers(cg) and cg.intersection(occupied).area<1e-7 and cg.intersection(gate).area<1e-7:
                        replacement=cg;break
                if replacement is None:return
                g=replacement
            if g.intersection(unary_union([_geom(q) for q in buildings])).area>1e-7:return
            buildings.append(_feature(g,f'new-{len(buildings)}',block_id=bid,retained=False,floors=3 if first==4 else 1,
                height_m=11. if first==4 else first,template='orthogonal_rectangle',building_type=kind,
                use='industrial' if first!=4 else 'residential',depth_m=depth_value,first_floor_height_m=first,
                standard_floor_height_m=3.5,max_floors=max_floors))
        if fid=='fabric.harbour_grain':
            # Fine-grain address rhythm on both long streets; occasional sheds
            # use the short frontage, with 24 m industrial depth.
            for y in (ly,ry-depth):
                n=max(1,math.floor(cell_w/6.5));front=cell_w/n
                for j in range(n):building(box(lx+j*front,y,lx+(j+1)*front,y+depth),'building.rowhouse',depth)
            road(world(LineString([(lx+24,ly-gap/2),(lx+24,ry+gap/2)])),6,'harbour_cross_lane',level=2)
            clear_short=cell_h-2*depth
            if clear_short>45:
                mid=(ly+ry)/2
                n=max(1,math.floor(cell_w/6.5));front=cell_w/n
                for j in range(n):building(box(lx+j*front,mid-depth/2,lx+(j+1)*front,mid+depth/2),'building.rowhouse',depth)
                court_parts=[box(lx+24,ly+depth,rx-24,mid-depth/2),box(lx+24,mid+depth/2,rx-24,ry-depth)]
            else:court_parts=[box(lx+24,ly+depth,rx-24,ry-depth)]
            for cp in court_parts:
                if not cp.is_empty:
                    cw=min(cp.bounds[2]-cp.bounds[0],cp.bounds[3]-cp.bounds[1])
                    courtyards.append(_feature(world(cp),f'courtyard-{len(courtyards)}',block_id=bid,clear_width_m=cw,label_zh='共用內院',dimension_label_zh=f'淨寬 {cw:.1f} 公尺',manager='街廓共用管理'))
            if cell_h-2*depth>=24:
                for x in (lx,rx-24):building(box(x,ly+depth,x+24,ry-depth),'building.industrial_hall',24,6.,3)
        elif fid=='fabric.landscape_figure':
            # Separate point buildings and short slabs form the landscape edge.
            for x in (lx,rx-20):
                building(box(x,ly,x+20,ly+20),'building.point_array',20)
                building(box(x,ry-20,x+20,ry),'building.point_array',20)
            if cell_w-40>=20:
                building(box(lx+20,ly,rx-20,ly+12),'building.i_slab',12)
                building(box(lx+20,ry-12,rx-20,ry),'building.i_slab',12)
        else:
            island_base=20. if fid=='fabric.courtyard_islands' else depth
            inner=box(lx+depth+4,ly+island_base+4,rx-depth-4,ry-depth-4)
            if cell_h-2*depth>45 and fid!='fabric.courtyard_islands':
                mid=(ly+ry)/2
                n_mid=math.ceil((cell_w-2*depth)/80);mid_module=(cell_w-2*depth)/n_mid
                for j in range(n_mid):building(box(lx+depth+j*mid_module,mid-depth/2,lx+depth+(j+1)*mid_module,mid+depth/2),'building.courtyard_closed',depth)
                inner_parts=[box(lx+depth,ly+depth,rx-depth,mid-depth/2),box(lx+depth,mid+depth/2,rx-depth,ry-depth)]
            else:inner_parts=[inner]
            for inner_part in inner_parts:
                if not inner_part.is_empty:
                    cs=list(inner_part.exterior.coords);clear_width=min(math.dist(cs[j],cs[j+1]) for j in range(2))
                    courtyards.append(_feature(world(inner_part),f'courtyard-{len(courtyards)}',block_id=bid,clear_width_m=clear_width,label_zh='共用內院',dimension_label_zh=f'淨寬 {clear_width:.1f} 公尺',manager='街廓共用管理'))
            fire_rectangle=box(lx+depth+2,ly+island_base+2,rx-depth-2,ry-depth-2)
            road(world(fire_rectangle.exterior),4,'courtyard_fire_lane',['pedestrian','bicycle','service','fire'],2)
            # Orthogonal ring or U; no inward offset from irregular residuals.
            kind='building.courtyard_closed' if fid in ('fabric.closed_block_extension','fabric.courtyard_islands') or i%3==0 else ('building.u_block' if i%3==1 else 'building.courtyard_open_corner')
            for y in (ly,ry-depth):
                if fid=='fabric.courtyard_islands' and y==ly:
                    n=math.ceil(cell_w/40);module=cell_w/n
                    for j in range(n):building(box(lx+j*module,y,lx+(j+1)*module,y+20),'building.industrial_hall',20,6.,3)
                    continue
                if fid=='fabric.closed_block_extension' and i%2:
                    n=math.floor(cell_w/6.5);front=cell_w/n
                    for j in range(n):building(box(lx+j*front,y,lx+(j+1)*front,y+depth),'building.terraced',depth)
                else:
                    n=math.ceil(cell_w/14);module=cell_w/n
                    for j in range(n):building(box(lx+j*module,y,lx+(j+1)*module,y+depth),kind,depth)
            n=math.ceil((cell_h-depth-island_base)/14);module=(cell_h-depth-island_base)/n
            for j in range(n):building(box(lx,ly+island_base+j*module,lx+depth,ly+island_base+(j+1)*module),kind,depth)
            if kind!='building.u_block':
                for j in range(n):
                    if kind=='building.courtyard_open_corner' and j==0:
                        if module>6:building(box(rx-depth,ly+island_base+6,rx,ly+island_base+module),kind,depth)
                        continue
                    building(box(rx-depth,ly+island_base+j*module,rx,ly+island_base+(j+1)*module),kind,depth)
    # Fill explicit vacant plot positions with separated point buildings in
    # the landscape fabric. Each is a real 20 m square and is checked against
    # all fixed ROWs, retained massing, previous buildings and the reserved park.
    if fid=='fabric.landscape_figure' and not waterfront.is_empty:
        axis_angle=90-context['site']['principal_axis']['long_axis_azimuth_deg']
        free_world=buildable.difference(unary_union([_geom(q) for q in buildings]+retained_geoms).buffer(4,join_style=2))
        fl=rotate(free_world,-axis_angle,origin=origin);fx0,fy0,fx1,fy1=fl.bounds
        slab_public=unary_union([_geom(q).buffer(q['properties']['width_m']/2,cap_style=2,join_style=2) for q in roads if q['properties']['role'] not in {'courtyard_fire_lane','courtyard_service_gate','retained_service_lane','boundary_plot_service_lane','south_quay_shared_alley'}])
        slab_forbidden=unary_union([_geom(q) for q in blocks]+retained_geoms+[park_reservation,slab_public]+[_geom(q).buffer(4,join_style=2) for q in parcels])
        slab_safe=fl.buffer(1e-7)
        slab_land_safe=land.buffer(1e-7)
        for length in (80.,60.,40.):
            for yy in range(math.ceil(fy0),math.floor(fy1-30),4):
                for xx in range(math.ceil(fx0),math.floor(fx1-length-10),4):
                    footprint=box(xx+5,yy+8,xx+5+length,yy+22)
                    plot=box(xx,yy,xx+length+10,yy+30)
                    g=rotate(footprint,axis_angle,origin=origin);pg=rotate(plot,axis_angle,origin=origin)
                    if not slab_land_safe.covers(pg) or not slab_safe.covers(footprint) or pg.intersection(slab_forbidden).area>.01:continue
                    bid=f'boundary-parcel-{len(parcels)}'
                    parcels.append(_feature(pg,bid,template='orthogonal_rectangle',short_m=30,long_m=length+10,role='綠軸邊板樓宗地',reason_zh='以14m深真實板樓與30m深管理宗地配置，沿公共綠軸提供住宅界面與私有服務院'))
                    buildings.append(_feature(g,f'new-{len(buildings)}',block_id=None,parcel_id=bid,retained=False,floors=3,height_m=11.,template='orthogonal_rectangle',building_type='building.i_slab',use='residential',depth_m=14.,first_floor_height_m=4.,standard_floor_height_m=3.5,max_floors=5))
                    road(pg.buffer(2,join_style=2).exterior,4,'boundary_plot_service_lane',level=2)
                    fl=fl.difference(plot.buffer(4,join_style=2));slab_safe=fl.buffer(1e-7)
                    slab_forbidden=slab_forbidden.union(pg.buffer(4,join_style=2))
        for xx in range(math.ceil(fx0),math.floor(fx1-20),4):
            for yy in range(math.ceil(fy0),math.floor(fy1-20),4):
                square=box(xx,yy,xx+20,yy+20);plot=box(xx-10,yy-10,xx+30,yy+30)
                g=rotate(square,axis_angle,origin=origin);pg=rotate(plot,axis_angle,origin=origin)
                if not fl.buffer(1e-7).covers(square) or not land.covers(pg):continue
                hosts=[b for b in blocks if _geom(b).buffer(1e-7).covers(g)]
                if hosts:bid=hosts[0]['id']
                else:
                    public_now=unary_union([_geom(q).buffer(q['properties']['width_m']/2,cap_style=2,join_style=2) for q in roads if q['properties']['role'] not in {'courtyard_fire_lane','courtyard_service_gate','retained_service_lane','boundary_plot_service_lane','south_quay_shared_alley'}])
                    forbidden=unary_union([_geom(q) for q in blocks]+retained_geoms+[park_reservation,public_now]+[_geom(q).buffer(4,join_style=2) for q in parcels])
                    fitted=None
                    for pw,ph in ((40,40),(50,30),(30,50)):
                        for shift in (0,-2,2,-4,4):
                            candidate=box(xx+10-pw/2,yy+10-ph/2+shift,xx+10+pw/2,yy+10+ph/2+shift)
                            pg=rotate(candidate,axis_angle,origin=origin)
                            if pg.buffer(1e-7).covers(g) and land.buffer(1e-7).covers(pg) and pg.intersection(forbidden).area<=.01:
                                fitted=candidate;break
                        if fitted is not None:break
                    if fitted is None:continue
                    plot=fitted;pg=rotate(plot,axis_angle,origin=origin)
                    bid=f'boundary-parcel-{len(parcels)}'
                    parcels.append(_feature(pg,bid,template='orthogonal_rectangle',short_m=min(pw,ph),long_m=max(pw,ph),role='地景邊界點式宗地',reason_zh='既有保留建築與公園之間的獨立20m點式宗地，採40×40或50×30m真實服務院配置；不冒充完整字典街廓'))
                buildings.append(_feature(g,f'new-{len(buildings)}',block_id=bid if hosts else None,parcel_id=None if hosts else bid,retained=False,floors=3,height_m=11.,template='orthogonal_rectangle',building_type='building.point_array',use='residential',depth_m=20.,first_floor_height_m=4.,standard_floor_height_m=3.5,max_floors=5))
                road(g.buffer(4,join_style=2).exterior,4,'boundary_plot_service_lane',level=2)
                for start_y,end_y in ((yy-4,plot.bounds[1]-2),(yy+24,plot.bounds[3]+2)):
                    road(rotate(LineString([(xx+10,start_y),(xx+10,end_y)]),axis_angle,origin=origin),4,'boundary_plot_service_lane',level=2)
                fl=fl.difference(square.buffer(6,join_style=2))
    # The south quay is narrower than the precedent block dictionary. Explicit
    # boundary plots retain their actual dimensions and therefore expose that
    # dictionary mismatch instead of pretending to be a full precedent block.
    if not waterfront.is_empty:
        axis_local=lambda g:rotate(g,-axis_angle,origin=origin)
        axis_world=lambda g:rotate(g,axis_angle,origin=origin)
        occupied=unary_union([_geom(b) for b in buildings]+retained_geoms)
        free=axis_local(buildable.difference(occupied.buffer(3,join_style=2)).difference(unary_union([_geom(b) for b in blocks])))
        yard_forbidden=unary_union([_geom(q) for q in blocks+parcels]+retained_geoms+[_geom(q).buffer(q['properties']['width_m']/2,cap_style=2,join_style=2) for q in roads if q['properties']['role'] not in {'courtyard_fire_lane','courtyard_service_gate','retained_service_lane','boundary_plot_service_lane','south_quay_shared_alley'}])
        boundary_candidates=[(xx,yy) for yy in range(math.ceil(ay0+22),math.floor(ay1-32),4) for xx in range(math.ceil(ax0+20),math.floor(ax1-40),4)]
        for xx,yy in boundary_candidates:
            footprint=box(xx,yy,xx+40,yy+24)
            parcel=box(xx-3,yy-5,xx+43,yy+29)
            if free.buffer(1e-7).covers(footprint) and axis_land.covers(parcel) and axis_world(parcel).intersection(yard_forbidden).area<=.01:
                g=axis_world(footprint);bid=f'boundary-parcel-{len(parcels)}'
                parcels.append(_feature(axis_world(parcel),bid,template='orthogonal_rectangle',short_m=34,long_m=46,role='南岸及東北 maker 獨立宗地',reason_zh='可建深度不足完整街廓，採40×24m maker廠房與四側服務院的46×34m獨立宗地；不計為合格字典街廓'))
                buildings.append(_feature(g,f'new-{len(buildings)}',block_id=None,parcel_id=bid,retained=False,floors=1,height_m=6.,template='orthogonal_rectangle',building_type='building.industrial_hall',use='industrial',depth_m=24.,first_floor_height_m=6.,standard_floor_height_m=3.5,max_floors=3))
                road(axis_world(parcel.buffer(2,join_style=2).exterior).intersection(land).difference(exclusions),4,'boundary_plot_service_lane',level=2)
                free=free.difference(footprint.buffer(8,join_style=2))
                yard_forbidden=yard_forbidden.union(axis_world(parcel).buffer(4,join_style=2))
    # Complete shallow boundary plots with real residential slabs. The 50×30m
    # managed plot includes an 8m service yard on both sides of the 14m wing;
    # it is not labelled as a dictionary-sized island or a residual plaza.
    if not waterfront.is_empty:
        fixed=unary_union([_geom(q) for q in blocks+parcels]+retained_geoms+[park_reservation]+[_geom(q).buffer(q['properties']['width_m']/2,cap_style=2,join_style=2) for q in roads if q['properties']['role'] not in {'courtyard_fire_lane','courtyard_service_gate','retained_service_lane','boundary_plot_service_lane','south_quay_shared_alley'}])
        free=rotate(buildable.difference(fixed),-axis_angle,origin=origin)
        safe=free.buffer(1e-7)
        for yy in range(math.ceil(ay0+10),math.floor(ay1-30),2):
            for xx in range(math.ceil(ax0+10),math.floor(ax1-50),2):
                plot=box(xx,yy,xx+50,yy+30)
                if not safe.covers(plot):continue
                pg=rotate(plot,axis_angle,origin=origin)
                g=rotate(box(xx+3,yy+8,xx+47,yy+22),axis_angle,origin=origin)
                # Separate slabs enough for the delivered five-storey height.
                if any(_geom(b).distance(g)<18-1e-6 for b in buildings if b['properties']['building_type']=='building.i_slab'):continue
                bid=f'boundary-parcel-{len(parcels)}'
                parcels.append(_feature(pg,bid,template='orthogonal_rectangle',short_m=30,long_m=50,role='邊界住宅板樓與服務院',reason_zh='沿實際街道配置44×14m板樓，50×30m宗地保留雙側服務院；擴充有建築邊界用地，不冒充大型院落島'))
                buildings.append(_feature(g,f'new-{len(buildings)}',block_id=None,parcel_id=bid,retained=False,floors=3,height_m=11.,template='orthogonal_rectangle',building_type='building.i_slab',use='residential',depth_m=14.,first_floor_height_m=4.,standard_floor_height_m=3.5,max_floors=5))
                road(pg.buffer(2,join_style=2).exterior,4,'boundary_plot_service_lane',level=2)
                free=free.difference(plot.buffer(4,join_style=2));safe=free.buffer(1e-7)
    south_quay_band=None
    if not waterfront.is_empty:
        quay_candidates=[rotate(_geom(b),-axis_angle,origin=origin) for b in buildings if rotate(_geom(b),-axis_angle,origin=origin).bounds[1]<=ay0+18]
        if quay_candidates:
            import statistics
            front_y=statistics.median(g.bounds[3] for g in quay_candidates)
            qx0=ax0+20;qx1=ax0+.62*(ax1-ax0)
            band_geometry=rotate(box(qx0,front_y-14,qx1,front_y),axis_angle,origin=origin).intersection(land)
            south_quay_band=_feature(band_geometry,'south-quay-band',frontage_axis_azimuth_deg=(90-axis_angle)%180,frontage_side='max_y',name_zh='南岸連續建築帶',role='south_quay_building_band',reason_zh='以基地長軸西南62%地帶的完整南岸跨度檢查正面連續率；不依現有新建量體裁窄分母，保留建築與道路缺口保留')
            alley=rotate(LineString([(qx0,front_y-18),(qx1,front_y-18)]),axis_angle,origin=origin)
            free_alley=land.buffer(-3.01,join_style=2).difference(unary_union([_geom(b) for b in buildings]+retained_geoms).buffer(3.01,join_style=2))
            road(alley.intersection(free_alley),6,'south_quay_shared_alley',MODES,2)
    if not waterfront.is_empty:
        quay_extent=rotate(box(ax0+20,ay0-1,ax0+.62*(ax1-ax0),ay0+110),axis_angle,origin=origin)
        actual_front=water.buffer(10.1,join_style=2).boundary.intersection(land).intersection(quay_extent)
        if south_quay_band is None:
            band=quay_extent.intersection(land).intersection(shape(facts['geometry']['buildable']))
            south_quay_band=_feature(band,'south-quay-band',frontage_axis_azimuth_deg=(90-axis_angle)%180,frontage_side='water_facing',name_zh='南岸完整候選碼頭建築帶',role='south_quay_building_band',reason_zh='以完整西南操作範圍的實際可建岸帶保留失敗，不依建築反推縮小分母')
        south_quay_band['properties']['frontage_geometry']=mapping(actual_front)
        south_quay_band['properties']['frontage_basis']='landward edge of deterministic10.1m mapped-water offset, complete southwest62percent scope; not selected from existing mass'
    world=lambda g:rotate(g,angle,origin=origin)
    local=lambda g:rotate(g,-angle,origin=origin)
    # Drop road pieces crossing fixed or new footprints, then connect surviving
    # components using visible straight paths inside the free land geometry.
    mass=unary_union([_geom(b) for b in buildings]+retained_geoms)
    clear=land.buffer(-1.99,join_style=2).difference(mass.buffer(1.99,join_style=2)).difference(unary_union([_geom(q) for q in parcels]).buffer(1.99,join_style=2))
    clean=[]
    for row in roads:
        if row['properties']['role']=='retained_city_road':clean.append(row);continue
        for part in _parts(_geom(row).difference(mass.buffer(max(0,row['properties']['width_m']/2-1e-5),join_style=1))):
            if part.geom_type=='LineString' and part.length>.1:clean.append(_feature(part,f'road-clean-{len(clean)}',**{k:v for k,v in row['properties'].items() if k!='id'}))
    roads=clean
    # Add frontage service courts around retained plots (not fabricated removal).
    for g in retained_geoms:
        road(g.buffer(5,join_style=2).exterior.intersection(clear),4,'retained_service_lane',level=2)
    for entry in facts['geometry']['entrances']:
        point=Point(entry['coordinates']);options=sorted([(point.distance(_geom(r)),nearest_points(point,_geom(r))[1]) for r in roads],key=lambda v:v[0])
        for _,near in options:
            line=LineString([point,near])
            if land.buffer(0.15).difference(mass.buffer(.05,join_style=2)).covers(line):
                road(line,4,'entrance_connector',level=2);break
    _join_roads(roads,clear,road,mode='car')
    _join_roads(roads,clear,road)
    # Real service spurs terminate 2 m outside a facade; buffers never claim
    # a road through the building merely to make frontage pass.
    for b in buildings:
        surface=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads])
        if _geom(b).distance(surface)>3.01:
            options=sorted([(_geom(b).distance(_geom(r)),r) for r in roads],key=lambda v:v[0])
            for _,r in options:
                u,v=nearest_points(_geom(b),_geom(r));distance=u.distance(v)
                if distance>2:
                    t=Point(u.x+(v.x-u.x)*2/distance,u.y+(v.y-u.y)*2/distance);line=LineString([v,t])
                    if land.buffer(.1).difference(mass.buffer(1.99,join_style=2)).covers(line):
                        road(line,4,'facade_service_spur',level=2);break
    _join_roads(roads,clear,road,mode='car');_join_roads(roads,clear,road)
    for b in buildings:
        if b['properties']['building_type']=='building.i_slab':
            others=[q for q in buildings if q is not b and q['properties']['building_type']=='building.i_slab']
            if others:
                distance=min(_geom(b).distance(_geom(q)) for q in others)
                b['properties']['max_floors']=min(5,max(3,math.floor((distance-4)/3.5)+1))
    street_surface=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads])
    rejected=[{'candidate_id':b['id'],'geometry':copy.deepcopy(b['geometry']),'properties':copy.deepcopy(b['properties']),'reason':'無可行臨街界面，轉為街廓內服務空間'} for b in buildings if _geom(b).distance(street_surface)>3.01 or _geom(b).intersection(street_surface).area>.05]
    buildings=[b for b in buildings if _geom(b).distance(street_surface)<=3.01 and _geom(b).intersection(street_surface).area<=.05]
    mass=unary_union([_geom(b) for b in buildings]+retained_geoms)
    current_surface=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads])
    density_min=fabric['density_targets']['GSI']['range']['minimum']
    # Continuous island perimeter wings need enough real footprint to close
    # secondary voids outside the reserved principal court. This is an
    # exploratory template target, not a change to the source GSI proxy.
    if fid=='fabric.courtyard_islands':
        p['island_perimeter_coverage_target']=.5
        density_min=max(density_min,p['island_perimeter_coverage_target'])
    floor_capacity=sum(_geom(b).area*(b['properties']['max_floors']+(.5 if b['properties']['use']=='industrial' else 0)) for b in buildings)
    if fid=='fabric.closed_block_extension' and floor_capacity<NEW_GFA_MIN_M2:
        density_min=min(fabric['density_targets']['GSI']['range']['maximum'],density_min+.2)
    density_court_reservations={}
    if fid=='fabric.closed_block_extension':
        for block in blocks:
            bg=_geom(block);frame=90-block['properties']['axis_azimuth_deg']
            safe=rotate(bg.difference(mass).difference(current_surface),-frame,origin=origin).buffer(1e-7)
            bx0,by0,bx1,by1=safe.bounds;reservation=None
            for xx in range(math.ceil(bx0),math.floor(bx1-20.2)+1,2):
                for yy in range(math.ceil(by0),math.floor(by1-20.2)+1,2):
                    candidate=box(xx,yy,xx+20.2,yy+20.2)
                    if safe.covers(candidate):reservation=rotate(candidate,frame,origin=origin);break
                if reservation is not None:break
            if reservation is not None:density_court_reservations[block['id']]=reservation
    for block in blocks:
        bg=_geom(block);frame=90-block['properties']['axis_azimuth_deg']
        coverage=bg.intersection(mass).area/bg.area
        if coverage+1e-6>=density_min:continue
        if fid=='fabric.landscape_figure':fw,fh,kind,depth_value=20.,20.,'building.point_array',20.
        elif fid=='fabric.harbour_grain':fw,fh,kind,depth_value=6.5,13.,'building.rowhouse',13.
        else:fw,fh,kind,depth_value=14.,12.,'building.courtyard_closed',12.
        bl=rotate(bg,-frame,origin=origin);bx0,by0,bx1,by1=bl.bounds
        for xx in range(math.ceil(bx0),math.floor(bx1-fw)+1,2):
            if coverage+1e-6>=density_min:break
            for yy in range(math.ceil(by0),math.floor(by1-fh)+1,2):
                if coverage+1e-6>=density_min:break
                g=rotate(box(xx,yy,xx+fw,yy+fh),frame,origin=origin)
                reserved_court=unary_union([_geom(c) for c in courtyards if c['properties']['block_id']==block['id']])
                if fid=='fabric.closed_block_extension':reserved_court=density_court_reservations.get(block['id'],reserved_court)
                if g.intersection(reserved_court).area>.01:continue
                if fid=='fabric.closed_block_extension' and (bg.intersection(mass).area+bg.intersection(g).area)/bg.area>fabric['density_targets']['GSI']['range']['maximum']+1e-6:continue
                if not bg.buffer(1e-7).covers(g) or not buildable.buffer(1e-7).covers(g) or g.intersection(mass).area>.01 or g.intersection(current_surface).area>.01 or g.distance(current_surface)>3.01:continue
                buildings.append(_feature(g,f'new-{len(buildings)+len(rejected)}',block_id=block['id'],retained=False,floors=3,height_m=11.,template='orthogonal_rectangle',building_type=kind,use='residential',depth_m=depth_value,first_floor_height_m=4.,standard_floor_height_m=3.5,max_floors=5,reason_zh='僅於真實空置臨街位置補足街廓足跡；不穿道路或保留建築'))
                mass=mass.union(g);coverage=bg.intersection(mass).area/bg.area
    if fid=='fabric.landscape_figure' and not waterfront.is_empty:
        # Infill evaluates actual free geometry, including genuine host plots;
        # reserved plot envelopes are not treated as occupied footprints.
        active_row=unary_union([_geom(q).buffer(q['properties']['width_m']/2,cap_style=2,join_style=2) for q in roads])
        free=rotate(buildable.difference(mass.buffer(4,join_style=2)).difference(active_row).difference(park_reservation),-axis_angle,origin=origin)
        from shapely.prepared import prep
        infill_safe=prep(free.buffer(1e-7))
        candidates=[]
        fx0,fy0,fx1,fy1=free.bounds
        for xx in range(math.ceil(fx0),math.floor(fx1-20)+1,1):
            for yy in range(math.ceil(fy0),math.floor(fy1-20)+1,1):
                square=box(xx,yy,xx+20,yy+20)
                if not infill_safe.covers(square):continue
                g=rotate(square,axis_angle,origin=origin)
                candidates.append((g.distance(active_row),xx,yy,g))
        for _,xx,yy,g in sorted(candidates,key=lambda q:q[:3]):
            if not buildable.buffer(1e-7).covers(g) or g.intersection(mass.buffer(4,join_style=2)).area>.01 or g.intersection(active_row).area>.01:continue
            hosts=[q for q in blocks+parcels if _geom(q).buffer(1e-7).covers(g)]
            new_parcel=None
            if hosts:
                host=hosts[0];bid=host['id'];is_block=host in blocks
            else:
                forbidden=unary_union([_geom(q) for q in blocks+parcels]+[public_row if 'public_row' in locals() else Polygon(),park_reservation]+retained_geoms)
                fitted=None
                for width,height in ((50,30),(30,50),(60,30),(30,60)):
                    candidate=rotate(box(xx+10-width/2,yy+10-height/2,xx+10+width/2,yy+10+height/2),axis_angle,origin=origin)
                    if land.buffer(1e-7).covers(candidate) and candidate.intersection(forbidden).area<=.01 and candidate.intersection(active_row).area<=.01:fitted=candidate;break
                if fitted is None:continue
                bid=f'boundary-parcel-{len(parcels)}';is_block=False
                new_parcel=_feature(fitted,bid,template='orthogonal_rectangle',short_m=min(width,height),long_m=max(width,height),role='臨街點式補充宗地',reason_zh='依實際空置可建地與道路配置20m點式建築，宗地保留完整服務院；非保留街廓範圍一律禁止的代理面積')
            route_domain=land.buffer(-2.01,join_style=2).difference(mass.union(g).buffer(2.01,join_style=2)).difference(park_reservation)
            options=sorted([(_geom(q).distance(g),q) for q in roads],key=lambda row:row[0]);chosen=None
            for _,q in options[:16]:
                near,facade=nearest_points(_geom(q),g);distance=near.distance(facade)
                if distance<2.1:continue
                endpoint=Point(facade.x+(near.x-facade.x)*2.1/distance,facade.y+(near.y-facade.y)*2.1/distance)
                route=_visible_route(near,endpoint,route_domain)
                if route is None:continue
                row=route.buffer(2,cap_style=2,join_style=2)
                if land.buffer(1e-7).covers(row) and row.intersection(mass.union(g)).area<=.01:chosen=route;break
            if chosen is None:continue
            if new_parcel:parcels.append(new_parcel)
            buildings.append(_feature(g,f'new-{len(buildings)+len(rejected)}',block_id=bid if is_block else None,parcel_id=None if is_block else bid,retained=False,floors=3,height_m=11.,template='orthogonal_rectangle',building_type='building.point_array',use='residential',depth_m=20.,first_floor_height_m=4.,standard_floor_height_m=3.5,max_floors=5,reason_zh='以完整實際20×20m足跡、真實服務接續補入既有街坊或宗地的可建空間'))
            road(chosen,4,'facade_service_spur',MODES,2)
            mass=mass.union(g);active_row=active_row.union(chosen.buffer(2,cap_style=2,join_style=2))
    if fid=='fabric.landscape_figure':
        p['point_floor_height_assumption']={'version':'fab1c-point-six-storey-v1','ground_floor_m':4.,'upper_floor_m':3.2,'maximum_floors':6,'maximum_height_m':20.,'basis':'explicit exploratory six-storey profile under20m; source fabric unchanged'}
        for b in buildings:
            if b['properties']['building_type']=='building.point_array':
                b['properties'].update(standard_floor_height_m=3.2,max_floors=6,floor_height_assumption_version='fab1c-point-six-storey-v1',height_m=10.4)
    target=p['target_gfa_m2'];gfa=sum(_geom(b).area*b['properties']['floors'] for b in buildings)
    # Spread floors in rounds so the height profile retains a readable range.
    for floor in range(1,6):
        for b in sorted(buildings,key=lambda b:(_geom(b).area,b['id'])):
            q=b['properties'];area=_geom(b).area
            if q['floors']<q['max_floors'] and q['first_floor_height_m']+q['standard_floor_height_m']*q['floors']<=20 and gfa+area<=target+1e-7:
                q['floors']+=1;q['height_m']=q['first_floor_height_m']+q['standard_floor_height_m']*(q['floors']-1);gfa+=area
    # A 3 m-high mezzanine fits within a 6 m industrial first floor. Its
    # actual orthogonal half-footprint is counted, never a fake full floor.
    for b in buildings:
        if b['properties']['use']=='industrial':
            cs=list(_geom(b).exterior.coords)[:-1]
            midpoint=lambda u,v:((u[0]+v[0])/2,(u[1]+v[1])/2)
            mezz=Polygon([cs[0],cs[1],midpoint(cs[1],cs[2]),midpoint(cs[0],cs[3])]);area=mezz.area
            if gfa+area<=target+1e-6:
                b['properties']['mezzanine_geometry']=mapping(mezz);b['properties']['mezzanine_gfa_m2']=area;b['properties']['mezzanine_level_m']=3.;gfa+=area
    for r in retained:
        row=_feature(shape(r['geometry']),r['id'],retained=True,source_record=copy.deepcopy(r),height_m=r['height_above_ground_m'],gfa_upper_m2=r['gfa_upper_m2']);row['geometry']=copy.deepcopy(r['geometry']);buildings.append(row)
    # A dictionary-width primary street joins two already connected skeleton
    # points through clear public land, preserving the orthogonal frame.
    if not any(r['properties']['role']=='primary_street' for r in roads):
        primary_width=p['street_width_m'];points=[]
        for row in roads:
            g=_geom(row)
            for fraction in (.0,.25,.5,.75,1.):
                q=g.interpolate(g.length*fraction)
                if q.distance(mass)>=primary_width/2 and q.distance(land.boundary)>=primary_width/2:points.append(q)
        primary_candidates=[]
        for i,u in enumerate(points):
            for v in points[i+1:]:
                length=u.distance(v)
                if not 60<=length<=240:continue
                az=math.degrees(math.atan2(v.x-u.x,v.y-u.y))%180;delta=(az-(90-angle))%90;delta=min(delta,90-delta)
                if delta>3:continue
                line=LineString([u,v]);surface=line.buffer(primary_width/2,cap_style=2,join_style=2)
                if surface.intersection(mass).area<.01 and land.buffer(.01).covers(surface):primary_candidates.append((length,line))
        if primary_candidates and not any(r['properties']['role']=='primary_street' for r in roads):road(max(primary_candidates,key=lambda row:row[0])[1],primary_width,'primary_street',level=0)
    internal_roles={'courtyard_fire_lane','courtyard_service_gate','facade_service_spur','retained_service_lane','boundary_plot_service_lane','south_quay_shared_alley'}
    public_row=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads if r['properties']['role'] not in internal_roles])
    fixed_blocks=unary_union([_geom(b) for b in blocks]+retained_geoms+[park_reservation])
    for parcel in parcels:
        children=unary_union([_geom(b) for b in buildings if b['properties'].get('parcel_id')==parcel['id']])
        others=unary_union([_geom(q) for q in parcels if q is not parcel])
        forbidden=public_row.union(fixed_blocks).union(others)
        current=_geom(parcel)
        offsets=sorted([(dx,dy) for dx in range(-10,11) for dy in range(-10,11)],key=lambda q:(q[0]*q[0]+q[1]*q[1],q))
        for dx,dy in offsets:
            candidate=translate(current,xoff=dx,yoff=dy)
            if candidate.buffer(1e-7).covers(children) and land.buffer(1e-7).covers(candidate) and candidate.intersection(forbidden).area<=.01:
                parcel['geometry']=mapping(candidate)
                parcel['properties']['yard_adjustment_m']=[dx,dy]
                break
    for parcel in parcels:
        children=unary_union([_geom(b) for b in buildings if b['properties'].get('parcel_id')==parcel['id']])
        if children.is_empty:continue
        others=unary_union([_geom(q) for q in parcels if q is not parcel])
        forbidden=public_row.union(fixed_blocks).union(others)
        child_local=rotate(children,-axis_angle,origin=origin)
        cx,cy=child_local.centroid.x,child_local.centroid.y
        chosen=_geom(parcel)
        minimum=fabric['density_targets']['GSI']['range']['minimum']
        for pw,ph in ((60,38),(54,40),(50,45),(50,40),(46,40)):
            if pw*ph<=chosen.area or children.area/(pw*ph)+1e-6<minimum:continue
            found=False
            for dx in range(-8,9,2):
                if found:break
                for dy in range(-8,9,2):
                    candidate=rotate(box(cx+dx-pw/2,cy+dy-ph/2,cx+dx+pw/2,cy+dy+ph/2),axis_angle,origin=origin)
                    if candidate.buffer(1e-7).covers(children) and land.buffer(1e-7).covers(candidate) and candidate.intersection(forbidden).area<=.01:
                        chosen=candidate;found=True;break
        if chosen.area>_geom(parcel).area+.01:
            parcel['geometry']=mapping(chosen)
            parcel['properties']['reason_zh']+='；服務院於保持足跡、GSI、道路與鄰地不重疊下納入實際相鄰空地。'
    road_area=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads if r['properties']['role'] not in internal_roles]).intersection(land).difference(mass)
    allocation=[];used=Polygon()
    actual_waterfront=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads if r['properties']['role']=='waterfront_path']).intersection(land).difference(mass)
    categories=[('retained_buildings',unary_union(retained_geoms)),('waterfront',actual_waterfront),('roads',road_area)]+[('parks' if pg.area>=1000 and not pg.buffer(-7.5,join_style=2).is_empty else 'service',pg) for pg in planned_parks]+[('service',seam),('service',exclusions.difference(unary_union(retained_geoms))),('blocks',unary_union([_geom(b) for b in blocks+parcels]))]
    for category,g in categories:
        g=g.intersection(land).difference(used)
        for part in _parts(g):
            if part.geom_type=='Polygon' and part.area>1e-8:
                actual_category='service' if category=='parks' and (part.area<1000 or part.buffer(-7.5,join_style=2).is_empty) else category
                metadata={'category':actual_category,'manager':'街廓管理' if actual_category=='blocks' else '公共空間管理'}
                if actual_category=='parks':metadata.update(role='完整管理公園單元',reason_zh='沿實際水岸、街道或Dakpark方向配置的可管理公園；道路路權先扣除，公園計淨面積')
                elif category=='parks':metadata.update(role='道路邊緣綠化維護帶',reason_zh='完整公共路權扣除後不足可用公園尺度的邊緣，保留綠化維護責任而不計公園')
                allocation.append(_feature(part,f'use-{len(allocation)}',**metadata));used=used.union(part)
    current_park_area=sum(_geom(row).area for row in allocation if row['properties']['category']=='parks')
    maximum_park=fabric['land_use_budget']['parks']['maximum']*land.area/100
    if fid=='fabric.landscape_figure':maximum_park=.25*land.area
    for frame in dict.fromkeys((axis_angle,angle)):
        park_domain=rotate(land.difference(used),-frame,origin=origin)
        if park_domain.is_empty:continue
        park_safe=park_domain.buffer(1e-7)
        px0,py0,px1,py1=park_domain.bounds
        for pw,ph in ((80,40),(60,40),(60,30),(40,30),(50,20)):
            for xx in range(math.ceil(px0),math.floor(px1-pw)+1,10):
                for yy in range(math.ceil(py0),math.floor(py1-ph)+1,10):
                    rectangle=box(xx,yy,xx+pw,yy+ph)
                    if current_park_area+rectangle.area>maximum_park+1e-6 or not park_safe.covers(rectangle):continue
                    pg=rotate(rectangle,frame,origin=origin)
                    if pg.boundary.distance(road_area)>3.01:continue
                    allocation.append(_feature(pg,f'use-{len(allocation)}',category='parks',manager='公共空間管理',role='完整矩形街坊公園',reason_zh='臨既有或新增公共街道的完整街坊公園，填補實際空地並保持字典公園預算'))
                    used=used.union(pg);park_domain=park_domain.difference(rectangle);park_safe=park_domain.buffer(1e-7);current_park_area+=rectangle.area
    for pg in sorted([g for g in _parts(land.difference(used)) if g.geom_type=='Polygon'],key=lambda g:g.area):
        core=pg.buffer(-7.5,join_style=2)
        core_parts=[g for g in _parts(core) if g.geom_type=='Polygon' and g.area>1e-6]
        if pg.area<1000 or current_park_area+pg.area>maximum_park+1e-6 or len(core_parts)!=1 or pg.boundary.distance(road_area)>3.01:continue
        allocation.append(_feature(pg,f'use-{len(allocation)}',category='parks',manager='公共空間管理',role='完整不規則街坊公園',reason_zh='將具15m可用核心、實際公共臨街及單一管理邊界的完整地塊規劃為公園；非殘地碎片'))
        used=used.union(pg);current_park_area+=pg.area
    # Explicitly assign every boundary fragment a plaza/service function; it is
    # never silently added to the park budget as if it were a coherent park.
    for part in _parts(land.difference(used)):
        if part.geom_type=='Polygon' and part.area>1e-8:
            allocation.append(_feature(part,f'use-{len(allocation)}',category='service',manager='公共空間管理',role='邊界服務與雨水維護帶',reason_zh='承接道路邊界、保留建築退縮及不規則基地邊界的維護責任；不列為廣場或公園'))
    # Adjacent residual land becomes part of the real built management plot.
    # Union preserves the whole boundary and does not split fragments to dodge
    # the 2000m2 check. Original dictionary-cell geometries remain inspectable.
    services=[r for r in allocation if r['properties']['category']=='service']
    hosts=[r for r in allocation if r['properties']['category']=='blocks' and _geom(r).intersection(mass).area>.01]
    for r in sorted(services,key=lambda q:-_geom(q).area):
        g=_geom(r);adjacent=[h for h in hosts if _geom(h).boundary.intersection(g.boundary.buffer(1e-6)).length>.1]
        if not adjacent:continue
        host=max(adjacent,key=lambda h:_geom(h).boundary.intersection(g.boundary).length)
        combined=_geom(host).union(g)
        if combined.geom_type!='Polygon':
            repaired=combined.buffer(1e-6,join_style=2).buffer(-1e-6,join_style=2)
            if repaired.geom_type!='Polygon' or repaired.symmetric_difference(combined).area>.001:continue
            combined=repaired
        host['geometry']=mapping(combined)
        host['properties'].update(role='有建築街坊完整管理地塊',reason_zh='合併實際共界的既有有建築用地及邊界維護空間，保留完整管理邊界，不以切碎殘地規避檢查',absorbed_allocation_ids=host['properties'].get('absorbed_allocation_ids',[])+[r['id']])
        allocation.remove(r)
    service_facilities=[]
    for r in allocation:
        q=r['properties']
        if q['category']=='parks':q['name_zh']='港灣綠軸公園 '+r['id'] if fid=='fabric.landscape_figure' else '街坊公共公園 '+r['id']
        if q['category']=='service' and 25<=_geom(r).area<=400 and not _geom(r).buffer(-1.5,join_style=2).is_empty and _geom(r).boundary.distance(public_row)<=3.01 and _geom(r).intersection(mass).area<=.01:
            q.update(function='equipment',name_zh='街坊設備院 '+r['id'],role='公共設備維修院',reason_zh='沿真實公共道路配置的獨立設備院；整個具體院落界面作為設備操作面')
            service_facilities.append(_feature(_geom(r),f'service-facility-{len(service_facilities)}',function='equipment',name_zh=q['name_zh'],serves_allocation_id=r['id']))
    for r in allocation:
        q=r['properties']
        if q['category']=='service' and not q.get('function') and _geom(r).area<=2000:
            q.update(category='blocks',manager='街坊共用管理',name_zh='街坊邊界綠化維護院 '+r['id'],role='街坊內部綠化及雨水維護空間',reason_zh='完整保留不足2000m2的街坊邊界維護單元，作為街坊管理用地；不計卸貨、垃圾、設備服務院或公共公園',management_basis='complete geometry; not a dictionary block or building parcel')
    block_land=unary_union([_geom(row) for row in allocation if row['properties']['category']=='blocks'])
    court_required={b['properties'].get('block_id') for b in buildings if not b['properties'].get('retained') and b['properties']['building_type'] in {'building.courtyard_closed','building.u_block','building.courtyard_open_corner','building.rowhouse','building.terraced'}}
    actual_courts=[]
    for block in blocks:
        if block['id'] not in court_required:continue
        frame=90-block['properties']['axis_azimuth_deg']
        domain=rotate(_geom(block).intersection(block_land).difference(mass).difference(street_surface),-frame,origin=origin)
        court_safe=domain.buffer(1e-7)
        previous=[q for q in courtyards if q['properties']['block_id']==block['id']]
        best_court=None
        for q in previous:
            rectangle=rotate(_geom(q),-frame,origin=origin)
            dims=(rectangle.bounds[2]-rectangle.bounds[0],rectangle.bounds[3]-rectangle.bounds[1])
            if 20-1e-6<=min(dims)<=45+1e-6 and court_safe.covers(rectangle):
                if best_court is None or rectangle.area>best_court.area:best_court=rectangle
        if best_court is None and not domain.is_empty:
            dx0,dy0,dx1,dy1=domain.bounds
            for xx in range(math.ceil(dx0),math.floor(dx1-20)+1,2):
                for yy in range(math.ceil(dy0),math.floor(dy1-20)+1,2):
                    rectangle=box(xx,yy,xx+20,yy+20)
                    if not court_safe.covers(rectangle):continue
                    ex=xx+20;ey=yy+20
                    while ex+2<=dx1 and court_safe.covers(box(xx,yy,ex+2,ey)):ex+=2
                    while ey+2<=dy1 and min(ex-xx,ey+2-yy)<=45 and court_safe.covers(box(xx,yy,ex,ey+2)):ey+=2
                    rectangle=box(xx,yy,ex,ey)
                    if best_court is None or rectangle.area>best_court.area:best_court=rectangle
        if best_court is not None:
            cw=min(best_court.bounds[2]-best_court.bounds[0],best_court.bounds[3]-best_court.bounds[1])
            actual_courts.append(_feature(rotate(best_court,frame,origin=origin),f'courtyard-{len(actual_courts)}',block_id=block['id'],clear_width_m=cw,label_zh='共用內院',dimension_label_zh=f'淨寬 {cw:.1f} 公尺',manager='街廓共用管理',selection_basis='largest feasible rectangular communal court; excludes all delivered footprints and ROW'))
    courtyards=actual_courts
    for row in roads:row['properties']['right_of_way']=mapping(_geom(row).buffer(row['properties']['width_m']/2,cap_style=2,join_style=2).intersection(land).difference(mass))
    plan={'schema_version':'fab1-plan-v1','crs':'EPSG:28992','fabric_id':fid,'orientation_deg':orientation,'block_axis_azimuth_deg':(90-angle)%180,
          'waterfront_detours':waterfront_detours,'service_facilities':service_facilities,'south_quay_band':south_quay_band,'parameters':p,'courtyards':courtyards,'roads':roads,'blocks':blocks,'boundary_parcels':parcels,'buildings':buildings,'land_use':allocation,'site':mapping(site),'water':mapping(water),
          'buildable':mapping(buildable),'waterfront_band':mapping(waterfront),'retained_inputs':retained,'entrances':copy.deepcopy(facts['geometry']['entrances']),
          'retained_road_inputs':retained_roads,'fabric_dictionary':copy.deepcopy(fabric),'green_axis_connectors':[_feature(pg,f'green-link-{i}',role='道路側綠軸接續帶',reason_zh='依保留道路交叉分段的狹幅綠化接續，不冒充可用公園',manager='公共空間管理') for i,pg in enumerate(planned_parks) if pg.area<1000 or pg.buffer(-7.5,join_style=2).is_empty] if fid=='fabric.landscape_figure' else [],'geometry_assumptions_version':'fab1d-actual-frontage-marked-detour-v1','context_reference':{'site':copy.deepcopy(context['site']),'boundary_and_alignments':copy.deepcopy(context.get('boundary_and_alignments',{}))},
          'rejected_building_candidates':rejected,'metrics':{},'limitations':['探索草稿，尚未經人類接受；公共通行權未核實。','保留建築 GFA 使用凍結來源的估計上限，非實測；陸地分母扣除映射水域。','接縫寬度為 Founder 10-11 指定假設；MOR-T07 條目未找到。','意圖介面目前支援有界尺度及主方向；街道選擇、公園地標位置與類型配比意圖尚未接入，輸入會拒絕。']}
    if fid=='fabric.landscape_figure' and not waterfront.is_empty:
        plan=_reconfigure_landscape_capacity(plan)
    from .fabric_finish_ne import finish_ne
    from .fabric_finish_green import finish_green
    plan=finish_green(finish_ne(plan))
    plan=_align_actual_public_frontage(plan)
    plan['geometry_assumptions_version']='fab1e-bounded-finish-v1'
    plan['validation']=validate_plan(plan);plan['metrics']=plan['validation']['metrics'];return plan



def _align_actual_public_frontage(plan):
    """Bounded footprint translations against actual public ROW, preserving GFA."""
    excluded={'courtyard_fire_lane','courtyard_service_gate','facade_service_spur','retained_service_lane','boundary_plot_service_lane','park_maintenance_path','south_quay_shared_alley'}
    public=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads'] if r['properties']['role'] not in excluded])
    all_rows=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads']])
    buildable=shape(plan['buildable']);land=shape(plan['site']).difference(shape(plan['water']))
    offsets=sorted([(dx,dy) for dx in range(-15,16) for dy in range(-15,16)],key=lambda q:(q[0]*q[0]+q[1]*q[1],q))
    attempts=[]
    for building in plan['buildings']:
        if building['properties'].get('retained'):continue
        g=_geom(building)
        if g.exterior.intersection(public.buffer(3.00001,join_style=2)).length>=1:continue
        bid=building['properties'].get('block_id') or building['properties'].get('parcel_id')
        parents=[r for r in plan['blocks']+plan['boundary_parcels'] if r['id']==bid]
        if not parents:continue
        parent=_geom(parents[0]);others=unary_union([_geom(b) for b in plan['buildings'] if b is not building])
        chosen=None
        u,v=nearest_points(g,public)
        distance=u.distance(v)
        exact=[]
        if distance>3:
            for setback in (2.5,1.,0.):
                factor=(distance-setback)/distance
                dx=(v.x-u.x)*factor;dy=(v.y-u.y)*factor
                if math.hypot(dx,dy)<=45:exact.append((dx,dy))
        for dx,dy in exact+offsets:
            candidate=translate(g,xoff=dx,yoff=dy)
            if not parent.buffer(1e-7).covers(candidate) or not buildable.buffer(1e-7).covers(candidate):continue
            if candidate.intersection(others).area>.01 or candidate.intersection(all_rows).area>.01:continue
            if candidate.exterior.intersection(public.buffer(3.00001,join_style=2)).length<1:continue
            chosen=(candidate,dx,dy);break
        attempts.append({'building_id':building['id'],'original_geometry':mapping(g),'public_frontage_distance_m':g.distance(public),'status':'MOVED' if chosen else 'NO_BOUNDED_FIT','search_translation_limit_m':45,'analytic_setbacks_m':[2.5,1.,0.]})
        if chosen:
            candidate,dx,dy=chosen;building['geometry']=mapping(candidate)
            if building['properties'].get('mezzanine_geometry'):
                building['properties']['mezzanine_geometry']=mapping(translate(shape(building['properties']['mezzanine_geometry']),xoff=dx,yoff=dy))
            building['properties']['public_frontage_translation_m']=[dx,dy]
            attempts[-1]['translation_m']=[dx,dy]
    plan['public_frontage_alignment_attempts']=attempts
    mass=unary_union([_geom(b) for b in plan['buildings']])
    for row in plan['roads']:
        row['properties']['right_of_way']=mapping(_geom(row).buffer(row['properties']['width_m']/2,cap_style=2,join_style=2).intersection(land).difference(mass))
    return plan


def _reconfigure_landscape_capacity(plan):
    """Repack real western plots with six-storey points; never inflate cached GFA."""
    p=copy.deepcopy(plan);origin=shape(p['site']).centroid;angle=90-p['context_reference']['site']['principal_axis']['long_axis_azimuth_deg']
    local=lambda g:rotate(g,-angle,origin=origin)
    world=lambda g:rotate(g,angle,origin=origin)
    geom=lambda r:shape(r['geometry'])
    new_points=[];removed=[]
    axis_land=local(shape(p['site']).difference(shape(p['water'])))
    west_limit=axis_land.bounds[0]+.6*(axis_land.bounds[2]-axis_land.bounds[0])
    # Merge the existing western point parcel with its contiguous, physically free management land.
    for parcel in p['boundary_parcels']:
     children=[b for b in p['buildings'] if b['properties'].get('parcel_id')==parcel['id']]
     if len(children)!=1 or children[0]['properties'].get('building_type')!='building.point_array' or local(geom(parcel)).centroid.x>=west_limit:continue
     g=local(geom(parcel));x0,y0,x1,y1=g.bounds
     protected=unary_union([geom(r) for r in p['land_use'] if r['properties']['category'] in {'waterfront','roads','service'}]+[geom(r) for r in p['blocks']]+[geom(r) for r in p['boundary_parcels'] if r is not parcel])
     for growth in [60,55,50,45,40,35,30,25,20]:
      candidate=world(box(x0-growth,y0-1,x1,y1-1))
      if shape(p['site']).difference(shape(p['water'])).buffer(1e-6).covers(candidate) and candidate.intersection(protected).area<=.01:
       management=[r for r in p['land_use'] if r['properties']['category']=='blocks' and geom(r).intersection(geom(parcel)).area>.01]
       if not management:continue
       allocation=copy.deepcopy(max(management,key=lambda r:geom(r).intersection(geom(parcel)).area));allocation['id']='west-expanded-management-'+parcel['id'];allocation['geometry']=mapping(geom(allocation).union(candidate));allocation['properties'].update(id=allocation['id'],name_zh='西側點樓完整矩形街坊管理用地',reason_zh='擴充真實宗地並配置實際點樓與服務連接')
       park_remaining=unary_union([geom(r) for r in p['land_use'] if r['properties']['category']=='parks']).difference(geom(allocation)).area
       if park_remaining/axis_land.area<.15-1e-8:continue
       parcel['geometry']=mapping(candidate)
       rows=[]
       for row in p['land_use']:
        remainder=geom(row).difference(geom(allocation))
        if not remainder.is_empty:
         row['geometry']=mapping(remainder);rows.append(row)
       p['land_use']=rows+[allocation]
       parcel['properties']['long_m']=x1-x0+growth;parcel['properties']['reason_zh']+='；西側連續管理空地納入同一矩形宗地，實際配置20m點樓與既有服務連接。';break
    # Reconfigure the existing western real parcels; retain every public / retained road.
    west=[]
    for r in p['boundary_parcels']:
     g=local(geom(r))
     if g.centroid.x<west_limit:west.append(r)
    for parcel in west:
     children=[b for b in p['buildings'] if b['properties'].get('parcel_id')==parcel['id']]
     if not children:continue
     g=local(geom(parcel));x0,y0,x1,y1=g.bounds
     obstacles=unary_union([geom(b) for b in p['buildings'] if b not in children])
     hard_roads=[r for r in p['roads'] if r['properties']['role']!='facade_service_spur']
     row=unary_union([geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in hard_roads])
     forbidden=local(obstacles.union(row));buildable=local(shape(p['buildable']))
     candidates=[]
     for y in [y0+i for i in range(0,round(y1-y0-20)+1)]:
      selected=[]
      for x in [x0+i for i in range(0,round(x1-x0-20)+1)]:
       b=box(x,y,x+20,y+20)
       if not g.buffer(1e-6).covers(b) or not buildable.buffer(1e-6).covers(b) or b.intersection(forbidden).area>.01:continue
       if any(b.distance(t)<1.99 for t in selected):continue
       selected.append(b)
      if len(selected)>len(candidates):candidates=selected
     old_gfa=sum(geom(b).area*b['properties']['floors'] for b in children)
     if len(candidates)*2400<=old_gfa:continue
     p['buildings']=[b for b in p['buildings'] if b not in children];removed.extend(b['id'] for b in children)
     for j,c in enumerate(candidates):
      b=copy.deepcopy(children[0]);b['id']=f'west-point-{parcel["id"]}-{j}';b['geometry']=mapping(world(c));q=b['properties'];q.update(id=b['id'],building_type='building.point_array',depth_m=20.,floors=6,height_m=20.,first_floor_height_m=4.,standard_floor_height_m=3.2,max_floors=6,floor_height_assumption_version='fab1c-point-six-storey-v1');p['buildings'].append(b);new_points.append(b['id'])
    # Remove terminal facade spurs that now physically collide and reconnect from actual nearest streets.
    mass=unary_union([geom(b) for b in p['buildings']]);p['roads']=[r for r in p['roads'] if r['properties']['role']!='facade_service_spur' or geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2).intersection(mass).area<=.05]
    for b in p['buildings']:
     if b['id'] not in new_points:continue
     street=unary_union([geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in p['roads']])
     if geom(b).distance(street)<=3.01:continue
     # connection ends 2m outside actual footprint and begins on a network centerline
     network=unary_union([geom(r) for r in p['roads']]);a,z=nearest_points(geom(b).buffer(2,join_style=2),network);line=LineString([a,z]);row=line.buffer(2,cap_style=2,join_style=2)
     if row.intersection(mass).area>.05:continue
     r=copy.deepcopy(p['roads'][-1]);r['id']=f'west-service-{b["id"]}';r['geometry']=mapping(line);r['properties'].update(id=r['id'],width_m=4.,role='facade_service_spur',modes=['pedestrian','bicycle','car','service','fire'],right_of_way=mapping(row));p['roads'].append(r)
    # Repacking must retain the real, shared management edge when an old
    # footprint moves away from a previously absorbed boundary strip.
    allocations=p['land_use']
    hosts=[r for r in allocations if r['properties']['category']=='blocks' and geom(r).intersection(mass).area>.01]
    for row in list(allocations):
     if row['properties']['category']!='blocks' or not any(part.geom_type=='Polygon' and part.area>2000 and part.intersection(mass).area<=.01 for part in _parts(geom(row))):continue
     adjoining=[h for h in hosts if h is not row and h in allocations and geom(h).boundary.intersection(geom(row).boundary.buffer(1e-6)).length>.1]
     if not adjoining:continue
     host=max(adjoining,key=lambda h:geom(h).boundary.intersection(geom(row).boundary.buffer(1e-6)).length)
     host['geometry']=mapping(geom(host).union(geom(row)))
     host['properties']['absorbed_allocation_ids']=host['properties'].get('absorbed_allocation_ids',[])+[row['id']]
     host['properties']['reason_zh']='重排足跡後依實際共同邊界保留街坊與邊緣綠化的完整管理單元；未拆分大型未建地塊。'
     allocations.remove(row)
    # Transfer the entire empty management component to its physically
    # adjoining park after repacking; preserve its full boundary and identity.
    for row in list(allocations):
     if row['properties']['category']!='blocks':continue
     components=[part for part in _parts(geom(row)) if part.geom_type=='Polygon' and part.area>2000 and part.intersection(mass).area<=.01]
     for component in components:
      adjacent=[park for park in allocations if park['properties']['category']=='parks' and component.boundary.intersection(geom(park).boundary.buffer(1e-6)).length>1]
      if not adjacent:continue
      park=max(adjacent,key=lambda r:component.boundary.intersection(geom(r).boundary.buffer(1e-6)).length)
      complete=geom(park).union(component)
      if complete.geom_type!='Polygon':
       complete=complete.buffer(1e-6,join_style=2).buffer(-1e-6,join_style=2)
      if complete.geom_type!='Polygon' or complete.intersection(mass).area>.01 or complete.buffer(-7.5,join_style=2).is_empty:continue
      park['geometry']=mapping(complete)
      park['properties'].update(name_zh='港灣綠軸完整鄰里公園 '+park['id'],role='完整管理公園單元',reason_zh='將重排後完整未建管理地塊沿實際共界併入既有公園，保留全塊幾何而不拆碎規避面積檢查',absorbed_allocation_ids=park['properties'].get('absorbed_allocation_ids',[])+[row['id']])
      remainder=geom(row).difference(component)
      if remainder.is_empty:
       allocations.remove(row);break
      row['geometry']=mapping(remainder)
    p['parameters']['landscape_capacity_reconfiguration']={'version':'fab1c-west-point-repacking-v1','western_domain_fraction':.6,'replaced_building_ids':removed,'new_point_building_ids':new_points,'basis':'actual1m search inside real parcels/buildable, six-storey20m points, actual service clearance; park minimum15%'}
    return p

def _components(roads):
    lines=[_geom(r) for r in roads];todo=set(range(len(lines)));groups=[]
    while todo:
        group={todo.pop()};stack=list(group)
        while stack:
            i=stack.pop();neighbors={j for j in todo if lines[i].distance(lines[j])<=.01};todo-=neighbors;group|=neighbors;stack.extend(neighbors)
        groups.append(group)
    return groups


def _visible_route(u,v,domain):
    """Shortest visibility route through actual polygonal free space."""
    import heapq
    from shapely.prepared import prep
    safe=domain.buffer(1e-7)
    prepared=prep(safe)
    direct=LineString([u,v])
    if prepared.covers(direct):return direct
    parts=[g for g in _parts(domain) if g.geom_type=='Polygon' and g.buffer(1e-7).covers(u) and g.buffer(1e-7).covers(v)]
    if not parts:return None
    polygon=parts[0]
    # Simplification only selects candidate bends; each whole edge is checked
    # against the original domain, never against the simplified approximation.
    reduced=polygon.simplify(.05,preserve_topology=True)
    coords=[(u.x,u.y),(v.x,v.y)]+list(reduced.exterior.coords)[:-1]
    for ring in reduced.interiors:coords.extend(list(ring.coords)[:-1])
    points=[Point(q) for q in coords];dist={0:0.};previous={};queue=[(u.distance(v),0.,0)];done=set()
    while queue:
        _,cost,i=heapq.heappop(queue)
        if i in done:continue
        if i==1:
            route=[1]
            while route[-1]!=0:route.append(previous[route[-1]])
            return LineString([coords[j] for j in reversed(route)])
        done.add(i)
        for j in range(len(points)):
            if j==i or j in done:continue
            length=points[i].distance(points[j]);candidate=cost+length
            if candidate>=dist.get(j,float('inf')):continue
            if prepared.covers(LineString([coords[i],coords[j]])):
                dist[j]=candidate;previous[j]=i;heapq.heappush(queue,(candidate+points[j].distance(v),candidate,j))
    return None

def _join_roads(roads,clear,add_road,mode=None):
    """Connect only geometrically visible paths; unknown access remains FAIL."""
    from shapely.prepared import prep
    clear_safe=clear.buffer(.02)
    prepared_clear=prep(clear_safe)
    local_cache={}
    for _ in range(len(roads)+10):
        eligible=[r for r in roads if mode is None or mode in r['properties']['modes']]
        groups=_components(eligible)
        if len(groups)<2:return
        eligible_geometries=[_geom(r) for r in eligible]
        options=[]
        for i,ga in enumerate(groups):
            a=unary_union([eligible_geometries[j] for j in ga]).intersection(clear_safe)
            if a.is_empty:continue
            for gb in groups[i+1:]:
                b=unary_union([eligible_geometries[j] for j in gb]).intersection(clear_safe)
                if b.is_empty:continue
                u,v=nearest_points(a,b)
                options.append((u.distance(v),u,v))
                for index in ga:
                    coordinates=list(eligible_geometries[index].coords)
                    for coord in coordinates[::max(1,len(coordinates)//8)]:
                        u=Point(coord);v=nearest_points(u,b)[1];options.append((u.distance(v),u,v))
        added=False
        primary=[r for r in eligible if r['properties']['role']=='primary_street']
        frame=0.
        if primary:
            cs=list(_geom(max(primary,key=lambda q:_geom(q).length)).coords)
            frame=math.degrees(math.atan2(cs[-1][1]-cs[0][1],cs[-1][0]-cs[0][0]))
        for angle in (frame,0.):
            if angle not in local_cache:local_cache[angle]=prep(rotate(clear_safe,-angle,origin=(0,0)))
        local_clear=local_cache
        for option_index,(_,u,v) in enumerate(sorted(options,key=lambda x:x[0])):
            candidates=[LineString([u,v])]
            # The road writer discards lines <= 0.1 m. Extend a genuine tiny
            # gap into one of its incident streets, rather than claiming that
            # a discarded connector changed network connectivity.
            distance=u.distance(v)
            if 0<distance<=.1:
                dx=(v.x-u.x)/distance;dy=(v.y-u.y)/distance
                candidates.extend([LineString([u,Point(v.x+.11*dx,v.y+.11*dy)]),
                                   LineString([Point(u.x-.11*dx,u.y-.11*dy),v])])
            # A straight visibility link can fail while a real orthogonal
            # two-leg street fits around a retained frontage or a courtyard wing.
            for angle in (frame,0.):
                lu=rotate(u,-angle,origin=(0,0));lv=rotate(v,-angle,origin=(0,0))
                for elbow in (Point(lu.x,lv.y),Point(lv.x,lu.y)):
                    middle=rotate(elbow,angle,origin=(0,0))
                    candidates.append(LineString([u,middle,v]))
                # Three-leg visibility paths can leave a private service gate
                # and skirt a complete retained plot without traversing its yard.
                for offset in ((-80.,-40.,-20.,-10.,10.,20.,40.,80.) if option_index<16 else ()):
                    for ab,cd in ((Point(lu.x,lu.y+offset),Point(lv.x,lu.y+offset)),(Point(lu.x+offset,lu.y),Point(lu.x+offset,lv.y))):
                        if local_clear[angle].covers(LineString([lu,ab,cd,lv])):
                            candidates.append(LineString([u,rotate(ab,angle,origin=(0,0)),rotate(cd,angle,origin=(0,0)),v]))
            for line in sorted(candidates,key=lambda g:g.length):
                if line.length>.1 and prepared_clear.covers(line):
                    count=len(roads)
                    add_road(line,4,'network_connector',level=2)
                    if len(roads)>count:added=True;break
            if added:break
        if not added:
            # Orthogonal heuristics cannot discover a multi-bend route around
            # several fixed plots. Use the actual free-space visibility graph.
            for _,u,v in sorted(options,key=lambda x:x[0])[:12]:
                line=_visible_route(u,v,clear_safe)
                if line is not None and line.length>.1:
                    add_road(line,4,'network_connector',level=2);added=True;break
        if not added:return

def _validate_second_round(plan, check):
    """FAB1b task checks, independently recomputed from delivered geometry."""
    land=shape(plan['site']).difference(shape(plan['water']))
    area=land.area
    allocations=plan['land_use']
    def category(name):
        return unary_union([_geom(r) for r in allocations if r['properties']['category']==name])
    waterfront=category('waterfront')
    # Courtyard access and plot service drives remain block/service land under
    # the FAB1b brief. Public streets, alleys and waterfront paths are measured
    # by their actual buffered geometry; record all circulation separately.
    internal_roles={'courtyard_fire_lane','courtyard_service_gate','facade_service_spur','retained_service_lane','boundary_plot_service_lane','park_maintenance_path','south_quay_shared_alley'}
    all_circulation=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads']]).intersection(land)
    street=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads'] if r['properties']['role'] not in internal_roles]).intersection(land)
    road_percent=100*street.difference(waterfront).area/area
    combined=100*street.union(waterfront).area/area
    check('ROAD_AREA_BUDGET',20-1e-6<=road_percent<=28+1e-6,percentage=road_percent,required_percent=[20,28],excluded_internal_roles=sorted(internal_roles),all_circulation_percent=100*all_circulation.area/area,failure_locations=[] if 20<=road_percent<=28 else [r['id'] for r in plan['roads']])
    check('ROAD_WATERFRONT_COMBINED_BUDGET',combined<=32+1e-6,percentage=combined,maximum_percent=32)
    if plan['fabric_id']=='fabric.landscape_figure':
        axis_features=[q for q in allocations if q['properties'].get('category')=='parks' and q['properties'].get('role')=='完整管理公園單元']+plan.get('green_axis_connectors',[])
        green=unary_union([_geom(q) for q in axis_features])
        green_parts=[g for g in _parts(green) if g.geom_type=='Polygon' and g.area>.01]
        adjacency={i:set() for i in range(len(green_parts))};crossings=[]
        public_roads=[q for q in plan['roads'] if q['properties']['role'] not in internal_roles and 0<q['properties']['width_m']<=22]
        public_surfaces=[(_geom(q).buffer(q['properties']['width_m']/2,cap_style=2,join_style=2),q) for q in public_roads]
        for i,g in enumerate(green_parts):
            for j,h in enumerate(green_parts[i+1:],i+1):
                u,v=nearest_points(g,h);bridge=LineString([u,v]);distance=u.distance(v)
                for row,q in public_surfaces:
                    if distance>.01 and distance<=q['properties']['width_m']+1e-5 and row.buffer(1e-5).covers(bridge):
                        adjacency[i].add(j);adjacency[j].add(i)
                        crossings.append({'road_id':q['id'],'green_components':[i,j],'gap_m':distance,'width_m':q['properties']['width_m']});break
        remaining=set(adjacency);groups=[]
        while remaining:
            group={remaining.pop()};stack=list(group)
            while stack:
                neighbors=adjacency[stack.pop()]&remaining;remaining-=neighbors;group|=neighbors;stack.extend(neighbors)
            groups.append(sorted(group))
        angle=90-plan['context_reference']['site']['principal_axis']['long_axis_azimuth_deg']
        oriented=rotate(green,-angle,origin=(land.centroid.x,land.centroid.y))
        span=0 if green.is_empty else oriented.bounds[2]-oriented.bounds[0]
        check('LANDSCAPE_GREEN_AXIS_CONTINUITY',bool(green_parts) and len(groups)==1,components_before_crossings=len(green_parts),components_after_crossings=len(groups),crossings=crossings,axis_span_m=span,failure_locations=[] if len(groups)==1 else groups,coverage_basis='actual managed green polygons; only a full public ROW crossing no longer than its physical width joins components; span alone is not continuity')
    paths=[r for r in plan['roads'] if r['properties']['role']=='waterfront_path']
    band=shape(plan['waterfront_band'])
    missing=band.difference(waterfront).area
    bad=[r['id'] for r in paths if not 10<=r['properties']['width_m']<=15]
    # The brief asks for a corridor along the full quay length, not ownership
    # of every square metre in the source's 15 m search band. Source-band area
    # remains reported. The delivered, un-clipped ROW must itself fit on land
    # and avoid every retained/new footprint; a declared width is insufficient.
    surface=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in paths])
    retained_mass=unary_union([_geom(b) for b in plan['buildings'] if b['properties'].get('retained')])
    water_geometry=shape(plan['water'])
    shoreline=LineString() if water_geometry.is_empty else water_geometry.boundary.intersection(band.buffer(.05))
    coastal_obstacles=unary_union([_geom(b) for b in plan['buildings'] if b['properties'].get('retained') and _geom(b).distance(shape(plan['water']))<=15])
    # A bypass may pass the landward side of fixed coastal buildings. Their
    # local frontage is excluded from direct shoreline proximity, while the
    # single connected corridor and full-width geometric clearance still apply.
    served_shore=surface.buffer(3.1).union(coastal_obstacles.buffer(15))
    unserved_shore=shoreline.difference(served_shore)
    unserved=[i for i,g in enumerate(_parts(shoreline)) if g.length>.1 and g.difference(served_shore).length>.1]
    obstructed=[]
    for r in paths:
        row=_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2)
        outside=row.difference(land).area
        overlaps=[{'building_id':b['id'],'overlap_m2':row.intersection(_geom(b)).area} for b in plan['buildings'] if row.intersection(_geom(b)).area>.01]
        if outside>.05 or overlaps:
            obstructed.append({'road_id':r['id'],'outside_land_m2':outside,'building_overlaps':overlaps})
    waterfront_components=len(_components(paths))
    feasible=land.buffer(-5,join_style=2).difference(retained_mass.buffer(5,join_style=2))
    feasible_parts=[g for g in _parts(feasible) if g.geom_type=='Polygon' and g.area>1]
    detour_checks={}
    _validate_third_round(plan,lambda ident,ok,**evidence:detour_checks.update({ident:{'passed':bool(ok),**evidence}}))
    detour_ok=detour_checks.get('WATERFRONT_DETOUR_GEOMETRY',{}).get('passed',False)
    detour_rows=plan.get('waterfront_detours',[]) if detour_ok else []
    local_surfaces=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in detour_rows if r['properties'].get('purpose')=='shoreline_bypass'])
    remaining_shore=unserved_shore.difference(local_surfaces.buffer(3.1))
    detour_applicable=len(feasible_parts)>1 and detour_ok and bool(detour_rows) and all(r['properties'].get('width_m',0)>=4 and _geom(r).length<=60 and r['properties'].get('name_zh') for r in detour_rows)
    check('WATERFRONT_PUBLIC_BAND',bool(paths) and (waterfront_components==1 or detour_applicable) and not bad and (remaining_shore.length<=.1 or detour_applicable) and not obstructed,failure_locations=bad+[{'geometry':mapping(g),'length_m':g.length} for g in _parts(remaining_shore) if g.length>.1]+obstructed,components=waterfront_components,remaining_unserved_shoreline_m=remaining_shore.length,explicit_detour_valid=detour_ok,founder_run4_exception_applied=bool(detour_applicable and remaining_shore.length>.1),exception_basis_zh='第四輪核准：完整合法且有標示的4公尺替代步行路徑長度不超過60公尺；未服務岸線另列，不聲稱已覆蓋',detour_geometry=detour_rows,uncovered_band_m2=missing,unserved_shoreline_m=unserved_shore.length,required_width_m=[10,15],right_of_way_obstructions=obstructed,minimum_width_feasible_domain_components=len(feasible_parts),minimum_width_feasible_domain_areas_m2=[g.area for g in feasible_parts],coverage_basis='full shoreline length, with continuous full-width retained-building bypasses; source-band area is not the corridor denominator')
    primary=[r for r in plan['roads'] if r['properties']['role']=='primary_street']
    axis=plan.get('context_reference',{}).get('site',{}).get('principal_axis',{})
    rect=land.minimum_rotated_rectangle;cs=list(rect.exterior.coords)
    length=axis.get('long_axis_length_m',max(math.dist(cs[i],cs[i+1]) for i in range(2)))
    az=axis.get('long_axis_azimuth_deg',plan.get('orientation_deg',90))
    ux,uy=math.sin(math.radians(az)),math.cos(math.radians(az))
    spans=[];lengths=[]
    for group in _components(primary):
        geom=unary_union([_geom(primary[i]) for i in group])
        values=[x*ux+y*uy for i in group for x,y in _geom(primary[i]).coords]
        spans.append(max(values)-min(values));lengths.append(geom.length)
    longest=max(spans,default=0)
    bad=[r['id'] for r in primary if not 18<=r['properties']['width_m']<=22 or not {'pedestrian','bicycle','car'}<=set(r['properties'].get('modes',[]))]
    primary_obstructions=[]
    mass=unary_union([_geom(b) for b in plan['buildings']])
    for r in primary:
        row=_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2)
        outside=row.difference(land).area;obstructed=row.intersection(mass).area
        if outside>.05 or obstructed>.05:
            bad.append(r['id']);primary_obstructions.append({'road_id':r['id'],'outside_land_m2':outside,'building_overlap_m2':obstructed})
    check('PRIMARY_STREET_THROUGH_SITE',bool(primary) and not bad and longest>=.8*length,connected_axis_span_m=longest,connected_lengths_m=lengths,required_span_m=.8*length,right_of_way_obstructions=primary_obstructions,failure_locations=bad or ([] if longest>=.8*length else ['主街未貫穿基地']))
    plazas=[r for r in allocations if r['properties']['category']=='plazas']
    invalid=[]
    for r in plazas:
        g=_geom(r);centered=translate(g,xoff=-g.centroid.x,yoff=-g.centroid.y)
        coords=list(centered.minimum_rotated_rectangle.exterior.coords)
        short=min(math.dist(coords[i],coords[i+1]) for i in range(2))
        if g.area<400-1e-6 or short<15-1e-6 or not r['properties'].get('reason_zh'):invalid.append(r['id'])
    plaza_percent=100*category('plazas').area/area
    check('PLAZA_BUDGET_AND_LOCATION',plaza_percent<=5+1e-6 and not invalid,percentage=plaza_percent,failure_locations=invalid)
    budget=plan['fabric_dictionary'].get('land_use_budget',{}).get('parks')
    limits=(15,25) if plan['fabric_id']=='fabric.landscape_figure' else ((budget['minimum'],budget['maximum']) if budget else None)
    park_percent=100*category('parks').area/area
    check('PARK_AREA_BUDGET',limits is not None and limits[0]-1e-6<=park_percent<=limits[1]+1e-6,percentage=park_percent,required_percent=limits,failure_locations=[] if limits and limits[0]<=park_percent<=limits[1] else ['公園面積不符指定範圍或字典範圍缺失'])
    lower=plan['fabric_dictionary'].get('density_targets',{}).get('GSI',{}).get('range',{}).get('minimum')
    upper=plan['fabric_dictionary']['density_targets']['GSI']['range'].get('maximum') if plan['fabric_id']=='fabric.closed_block_extension' else None
    buildings=[b for b in plan['buildings'] if not b['properties'].get('retained')]
    coverage=[];bad=[]
    for b in plan['blocks']:
        children=[q for q in plan['buildings'] if _geom(q).intersection(_geom(b)).area>.01]
        fraction=unary_union([_geom(q) for q in children]).intersection(_geom(b)).area/_geom(b).area
        coverage.append({'block_id':b['id'],'coverage':fraction,'building_count':len(children),'retained_coverage':unary_union([_geom(q) for q in children if q['properties'].get('retained')]).intersection(_geom(b)).area/_geom(b).area})
        if not children or lower is None or fraction+1e-6<lower or (upper is not None and fraction>upper+1e-6):bad.append(b['id'])
    check('EVERY_BLOCK_BUILT_COVERAGE',bool(plan['blocks']) and not bad,failure_locations=bad,coverage=coverage,minimum=lower,maximum=upper,basis_zh='街廓為分母，計入交集內全部新建與保留實際足跡；圍合採字典 .40–.60 淨GSI，其他類型保留字典研究窗先例下限作本輪代理檢查，並非街廓法規。')
    mass=unary_union([_geom(b) for b in plan['buildings']])
    empty=[]
    for r in allocations:
        if r['properties']['category'] in ('parks','plazas'):
            if _geom(r).area>2000 and not r['properties'].get('name_zh'):empty.append({'allocation_id':r['id'],'area_m2':_geom(r).area,'geometry':r['geometry'],'reason':'large public space lacks name'})
            continue
        if r['properties']['category'] in ('roads','waterfront'):continue
        for i,g in enumerate(_parts(_geom(r))):
            if g.area>2000 and g.intersection(mass).area<.01:empty.append({'allocation_id':r['id'],'part':i,'area_m2':g.area,'geometry':mapping(g)})
    check('NO_LARGE_UNBUILT_PLOT',not empty,failure_locations=empty,maximum_m2=2000)
    courts=plan.get('courtyards',[]);bad=[]
    for r in courts:
        g=_geom(r);centered=translate(g,xoff=-g.centroid.x,yoff=-g.centroid.y)
        coords=list(centered.minimum_rotated_rectangle.exterior.coords)
        short=min(math.dist(coords[i],coords[i+1]) for i in range(2))
        if not 20-1e-5<=short<=45+1e-5 or r['properties'].get('label_zh')!='共用內院' or g.difference(category('blocks')).area>.01 or g.intersection(unary_union([_geom(b) for b in plan['buildings']])).area>.01:bad.append(r['id'])
    courtyard_types={'building.courtyard_closed','building.u_block','building.courtyard_open_corner','building.rowhouse','building.terraced'}
    required={b['properties']['block_id'] for b in buildings if b['properties']['building_type'] in courtyard_types}
    marked={r['properties'].get('block_id') for r in courts}
    check('SHARED_COURTYARD_MARKED_WIDTH',not bad and required<=marked,failure_locations=bad+sorted(required-marked),required_width_m=[20,45])
    if plan['fabric_id']=='fabric.courtyard_islands':
        island_evidence=[];island_bad=[]
        footprints=unary_union([_geom(b) for b in plan['buildings']])
        for block in plan['blocks']:
            free=_geom(block).difference(footprints).difference(all_circulation)
            voids=[g for g in _parts(free) if g.geom_type=='Polygon' and not g.buffer(-10+1e-5,join_style=2).is_empty]
            assigned=[c for c in courts if c['properties'].get('block_id')==block['id']]
            widths=[];cores=[]
            for g in voids:
                centered=translate(g,xoff=-g.centroid.x,yoff=-g.centroid.y)
                cs=list(centered.minimum_rotated_rectangle.exterior.coords)
                widths.append(min(math.dist(cs[i],cs[i+1]) for i in range(2)))
                cores.append(len([h for h in _parts(g.buffer(-10+1e-5,join_style=2)) if h.geom_type=='Polygon']))
            valid=len(voids)==1 and len(assigned)==1 and 20-1e-5<=widths[0]<=45+1e-5 and cores[0]==1 and _geom(assigned[0]).difference(voids[0]).area<=.01
            if not valid:island_bad.append(block['id'])
            island_evidence.append({'block_id':block['id'],'marked_courtyard_count':len(assigned),'whole_useful_void_count':len(voids),'whole_void_widths_m':widths,'twenty_metre_core_components':cores,'whole_voids':[mapping(g) for g in voids]})
        check('COURTYARD_ISLAND_SINGLE_VOID',bool(plan['blocks']) and not island_bad,failure_locations=island_bad,islands=island_evidence,required_whole_void_width_m=[20,45],basis='entire actual free-space components after all delivered footprints and ROW; a selected rectangle cannot conceal an oversized or second useful court')
    return {'road_percent':road_percent,'all_circulation_percent':100*all_circulation.area/area,'road_waterfront_percent':combined,'park_percent':park_percent,'plaza_percent':plaza_percent,'primary_axis_span_m':longest}


def _validate_third_round(plan, check):
    """FAB1c geometry gates. Task thresholds are explicit exploratory inputs."""
    land=shape(plan['site']).difference(shape(plan['water']));area=land.area
    allocations=plan['land_use'];buildings=plan['buildings'];roads=plan['roads']
    def category(key):return unary_union([_geom(r) for r in allocations if r['properties'].get('category')==key]).intersection(land)
    service=category('service');blocks=category('blocks')
    gfa=sum(_geom(b).area*b['properties'].get('floors',0)+(shape(b['properties']['mezzanine_geometry']).area if b['properties'].get('mezzanine_geometry') else 0) for b in buildings if not b['properties'].get('retained'))
    check('FAB1C_NEW_GFA_TARGET',NEW_GFA_MIN_M2<=gfa<=146873,new_gfa_m2=gfa,required_m2=[NEW_GFA_MIN_M2,146873])
    service_percent=100*service.area/area;block_percent=100*blocks.area/area
    check('SERVICE_AREA_BUDGET',service_percent<=8+1e-6,percentage=service_percent,maximum_percent=8,failure_locations=[] if service_percent<=8 else [r['id'] for r in allocations if r['properties'].get('category')=='service'])
    minimum=38 if plan['fabric_id']=='fabric.landscape_figure' else 45
    check('BLOCK_LAND_BUDGET',block_percent>=minimum-1e-6,percentage=block_percent,minimum_percent=minimum,failure_locations=[] if block_percent>=minimum else [r['id'] for r in allocations if r['properties'].get('category')=='blocks'])
    public=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in roads if r['properties'].get('role') not in {'courtyard_fire_lane','courtyard_service_gate','facade_service_spur','retained_service_lane','boundary_plot_service_lane','park_maintenance_path','south_quay_shared_alley'}])
    mass=unary_union([_geom(b) for b in buildings]);bad=[];evidence=[]
    for r in allocations:
        if r['properties'].get('category')!='service':continue
        q=r['properties'];g=_geom(r);facilities=[f for f in plan.get('service_facilities',[]) if f['properties'].get('serves_allocation_id')==r['id']]
        valid=q.get('function') in {'loading','waste','equipment'} and bool(q.get('name_zh')) and bool(facilities) and not public.is_empty and g.boundary.distance(public)<=3.01
        facility_union=unary_union([_geom(f) for f in facilities])
        valid=valid and facility_union.difference(g.buffer(1e-7)).area<=.01 and facility_union.intersection(mass).area<=.01 and facility_union.area>=.8*g.area and all(f['properties'].get('name_zh') and f['properties'].get('function')==q.get('function') for f in facilities)
        if not valid:bad.append({'allocation_id':r['id'],'geometry':r['geometry']})
        evidence.append({'allocation_id':r['id'],'function':q.get('function'),'area_m2':g.area,'facility_area_m2':facility_union.area,'frontage_distance_m':None if public.is_empty else g.boundary.distance(public)})
    check('SERVICE_FUNCTION_FRONTAGE',not bad,failure_locations=bad,allocations=evidence,minimum_actual_facility_coverage=.8,allowed_functions=['loading','waste','equipment'])
    if plan['fabric_id']=='fabric.courtyard_islands':
        island_rows=plan.get('blocks',[]);bad=[];pairs=[];sizes=[]
        for r in island_rows:
            g=_geom(r);cs=list(g.minimum_rotated_rectangle.exterior.coords);dims=sorted(math.dist(cs[i],cs[i+1]) for i in range(2))
            sizes.append({'block_id':r['id'],'short_m':dims[0],'long_m':dims[1]})
            if not 75-1e-5<=dims[0]<=120+1e-5 or not 115-1e-5<=dims[1]<=200+1e-5:bad.append(r['id'])
        # Minimum spanning tree represents neighbouring islands, avoiding a
        # false upper-gap failure between non-neighbouring ends of the chain.
        joined={0} if island_rows else set()
        while len(joined)<len(island_rows):
            distance,i,j=min((_geom(island_rows[i]).distance(_geom(island_rows[j])),i,j) for i in joined for j in range(len(island_rows)) if j not in joined)
            u,v=nearest_points(_geom(island_rows[i]),_geom(island_rows[j]));gap=LineString([u,v])
            public_green=unary_union([_geom(q) for q in allocations if q['properties'].get('category')=='parks' and q['properties'].get('manager')=='公共空間管理' and q['properties'].get('name_zh')])
            separation_road=category('roads').union(public).union(public_green)
            crossed=gap.intersection(separation_road).length>=distance-.05
            pairs.append({'block_ids':[island_rows[i]['id'],island_rows[j]['id']],'distance_m':distance,'public_separation':crossed,'geometry':mapping(gap)})
            if not 15-1e-5<=distance<=25+1e-5 or not crossed:bad.append([island_rows[i]['id'],island_rows[j]['id']])
            joined.add(j)
        island_road_collisions=[]
        for r in island_rows:
            for road_row in roads:
                if road_row['properties'].get('role') in {'courtyard_fire_lane','courtyard_service_gate','facade_service_spur','retained_service_lane','boundary_plot_service_lane','park_maintenance_path','south_quay_shared_alley'}:continue
                physical_row=_geom(road_row).buffer(road_row['properties']['width_m']/2,cap_style=2,join_style=2)
                intersection=_geom(r).intersection(physical_row)
                if intersection.area>.05:island_road_collisions.append({'block_id':r['id'],'road_id':road_row['id'],'overlap_m2':intersection.area,'geometry':mapping(intersection)})
        check('COURTYARD_ISLAND_ROAD_CLEARANCE',not island_road_collisions,failure_locations=island_road_collisions,basis='net full island geometry excludes actual public ROW, not just building footprints')
        island_union=unary_union([_geom(r) for r in island_rows]);quay=plan.get('south_quay_band')
        accepted_parent=island_union.union(_geom(quay) if quay else Polygon())
        outside=[{'building_id':b['id'],'geometry':b['geometry'],'outside_islands_and_quay_m2':_geom(b).difference(accepted_parent).area} for b in buildings if not b['properties'].get('retained') and _geom(b).difference(accepted_parent).area>.01]
        check('COURTYARD_ISLAND_GLOBAL_MEMBERSHIP',not outside,failure_locations=outside,basis='every actual new footprint belongs wholly to a large island or complete marked south quay band; small boundary parcels cannot bypass island count')
        check('COURTYARD_ISLAND_COUNT_SPACING',4<=len(island_rows)<=7 and not bad and not outside,count=len(island_rows),required_count=[4,7],dimensions=sizes,adjacent_separations=pairs,required_separation_m=[15,25],failure_locations=bad+outside or ([] if 4<=len(island_rows)<=7 else [r['id'] for r in island_rows]))
    coastal=not shape(plan.get('waterfront_band',mapping(Polygon()))).is_empty
    if not coastal:
        for ident in ('SOUTH_QUAY_SHARED_ALLEY','SOUTH_QUAY_FACADE_CONTINUITY','NORTHEAST_REGULAR_BLOCKS','WATERFRONT_DETOUR_GEOMETRY'):check(ident,True,applicability='NOT_APPLICABLE',reason='no mapped waterfront')
        return {'service_percent':service_percent,'block_land_percent':block_percent}
    context=plan.get('context_reference',{}).get('site',{}).get('principal_axis',{})
    angle=90-context.get('long_axis_azimuth_deg',plan.get('orientation_deg',90));origin=(shape(plan['site']).centroid.x,shape(plan['site']).centroid.y)
    oriented=rotate(land,-angle,origin=origin);x0,y0,x1,y1=oriented.bounds
    northeast=[];irregular=[]
    for r in plan.get('blocks',[]):
        g=_geom(r);local=rotate(g,-angle,origin=origin)
        if local.centroid.x>=x0+.62*(x1-x0):
            northeast.append(r['id'])
            if g.geom_type!='Polygon' or len(g.exterior.coords)!=5 or abs(g.minimum_rotated_rectangle.area-g.area)>.01:irregular.append(r['id'])
    northeast_domain=rotate(box(x0+.62*(x1-x0),y0,x1,y1),angle,origin=origin)
    northeast_blocks=unary_union([_geom(r) for r in plan.get('blocks',[]) if r['id'] in northeast])
    fragment_buildings=[b['id'] for b in buildings if not b['properties'].get('retained') and _geom(b).intersection(northeast_domain).area>.01 and _geom(b).difference(northeast_blocks).area>.01]
    ne_range=[1,2] if plan['fabric_id']=='fabric.courtyard_islands' else [3,6]
    check('NORTHEAST_REGULAR_BLOCKS',ne_range[0]<=len(northeast)<=ne_range[1] and not irregular and not fragment_buildings,count=len(northeast),required_count=ne_range,block_ids=northeast,zone_geometry=mapping(rotate(box(x0+.62*(x1-x0),y0,x1,y1),angle,origin=origin)),failure_locations=irregular+fragment_buildings or ([] if ne_range[0]<=len(northeast)<=ne_range[1] else northeast))
    band=plan.get('south_quay_band');alleys=[r for r in roads if r['properties'].get('role')=='south_quay_shared_alley'];bad=[]
    for r in alleys:
        row=_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2)
        if not 6<=r['properties']['width_m']<=8 or not {'service','fire'}<=set(r['properties'].get('modes',[])) or row.difference(land).area>.05 or row.intersection(mass).area>.05 or (band and row.distance(_geom(band))>3.01):bad.append(r['id'])
    check('SOUTH_QUAY_SHARED_ALLEY',bool(band) and bool(alleys) and len(_components(alleys))==1 and not bad,required_width_m=[6,8],components=len(_components(alleys)),failure_locations=bad or ([] if alleys and band else ['missing south quay band or shared alley']))
    front, intervals=_south_quay_frontage(plan)
    denominator=front.length if front is not None else 0
    length=sum(hi-lo for lo,hi in intervals)
    coverage=length/denominator if denominator else 0
    check('SOUTH_QUAY_FACADE_CONTINUITY',coverage>=.6,percentage=100*coverage,minimum_percent=60,frontage_length_m=length,band_length_m=denominator,frontage_geometry=mapping(front) if front is not None else None,failure_locations=[] if coverage>=.6 else ([band['id']] if band else ['missing south quay band']))
    paths=[r for r in roads if r['properties'].get('role')=='waterfront_path'];groups=_components(paths);detours=plan.get('waterfront_detours',[]);bad=[];details=[]
    for r in detours:
        g=_geom(r);q=r['properties'];width=q.get('width_m',0);row=g.buffer(width/2,cap_style=2,join_style=2)
        endpoints=[Point(g.coords[0]),Point(g.coords[-1])];linked=[]
        for endpoint in endpoints:linked.append([i for i,group in enumerate(groups) if endpoint.distance(unary_union([_geom(paths[j]) for j in group]))<=.05])
        connector=q.get('purpose','component_connector')=='component_connector'
        local_shore=shape(plan['water']).boundary.intersection(shape(plan['waterfront_band']).buffer(.05))
        full_surface=unary_union([_geom(path).buffer(path['properties']['width_m']/2,cap_style=2,join_style=2) for path in paths])
        coastal_fixed=unary_union([_geom(b) for b in buildings if b['properties'].get('retained') and _geom(b).distance(shape(plan['water']))<=15])
        gap=local_shore.difference(full_surface.buffer(3.1).union(coastal_fixed.buffer(15)))
        local_coverage=gap.intersection(row.buffer(3.1)).length
        endpoint_rule=any(i!=j for i in linked[0] for j in linked[1]) if all(linked) and connector else all(linked) and local_coverage>.1
        valid=q.get('purpose','component_connector') in {'component_connector','shoreline_bypass'} and 0<width<10 and 0<g.length<=60+1e-6 and row.difference(land).area<=.05 and row.intersection(mass).area<=.05 and bool(q.get('name_zh')) and endpoint_rule
        if not valid:bad.append(r['id'])
        details.append({'detour_id':r['id'],'purpose':q.get('purpose','component_connector'),'served_local_gap_m':local_coverage,'length_m':g.length,'width_m':width,'endpoint_component_ids':linked,'outside_land_m2':row.difference(land).area,'building_overlap_m2':row.intersection(mass).area,'geometry':r['geometry']})
    all_paths=paths+detours;connected=len(_components(all_paths))==1
    check('WATERFRONT_DETOUR_GEOMETRY',bool(paths) and connected and not bad,maximum_length_m=60,detours=details,components_after_detours=len(_components(all_paths)),failure_locations=bad or ([] if connected else ['unconnected waterfront components']))
    return {'service_percent':service_percent,'block_land_percent':block_percent,'south_quay_facade_percent':100*coverage}


def _south_quay_frontage(plan):
    """Measured facade station intervals along the supplied public quay front."""
    band=plan.get('south_quay_band')
    if not band:return None, []
    q=band['properties'];bg=_geom(band)
    if q.get('frontage_geometry'):
        front=shape(q['frontage_geometry'])
        if front.geom_type not in {'LineString','MultiLineString'} or not front.is_valid:return None, []
    else:
        axis=plan.get('context_reference',{}).get('site',{}).get('principal_axis',{})
        angle=90-axis.get('long_axis_azimuth_deg',plan.get('orientation_deg',90))
        site=shape(plan['site']);origin=(site.centroid.x,site.centroid.y)
        local=rotate(bg,-angle,origin=origin);x0,y0,x1,y1=local.bounds
        y=y1 if q.get('frontage_side')=='max_y' else y0
        front=rotate(LineString([(x0,y),(x1,y)]),angle,origin=origin)
    waterfront=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads'] if r['properties'].get('role') in {'waterfront_path','waterfront_front_walk'}])
    if waterfront.is_empty:return front, []
    intervals=[]
    for b in plan['buildings']:
        if b['properties'].get('retained') or _geom(b).difference(bg.buffer(.01)).area>.05:continue
        for polygon in _parts(_geom(b)):
            if polygon.geom_type!='Polygon':continue
            coords=list(polygon.exterior.coords)
            for a,z in zip(coords,coords[1:]):
                edge=LineString([a,z])
                eligible=edge.intersection(front.buffer(3.00001,cap_style=2)).intersection(waterfront.buffer(3.00001))
                for part in _parts(eligible):
                    if part.geom_type!='LineString' or part.length<1:continue
                    stations=[front.project(Point(c)) for c in part.coords]
                    lo,hi=min(stations),max(stations)
                    if hi-lo>=1:intervals.append((lo,hi))
    merged=[]
    for lo,hi in sorted(intervals):
        if merged and lo<=merged[-1][1]+.01:merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
        else:merged.append((lo,hi))
    return front, merged


def _validate_fourth_round(plan,check):
    """第四輪新增實體幾何檢查；不採信快取數字或服務短支線。"""
    excluded={'facade_service_spur','retained_service_lane','boundary_plot_service_lane','courtyard_fire_lane','courtyard_service_gate','park_maintenance_path'}
    public=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads'] if r['properties'].get('role') not in excluded])
    bad=[];details=[]
    for b in plan['buildings']:
        if b['properties'].get('retained'):continue
        g=_geom(b);longest=0
        for poly in _parts(g):
            if poly.geom_type!='Polygon':continue
            cs=list(poly.exterior.coords)
            for a,z in zip(cs,cs[1:]):
                edge=LineString([a,z])
                longest=max(longest,edge.intersection(public.buffer(3.00001)).length if not public.is_empty else 0)
        distance=None if public.is_empty else g.boundary.distance(public)
        details.append({'building_id':b['id'],'street_distance_m':distance,'fronting_edge_length_m':longest})
        if longest<1 or distance is None or distance>3.00001:bad.append({'building_id':b['id'],'geometry':b['geometry'],'street_distance_m':distance})
    check('BUILDING_STREET_EDGE_3M',not bad,failure_locations=bad,buildings=details,maximum_setback_m=3,minimum_fronting_edge_m=1,excluded_roles=sorted(excluded))
    if not shape(plan.get('waterfront_band',mapping(Polygon()))).is_empty:
        land=shape(plan['site']).difference(shape(plan['water']))
        axis=plan.get('context_reference',{}).get('site',{}).get('principal_axis',{})
        angle=90-axis.get('long_axis_azimuth_deg',plan.get('orientation_deg',90));site=shape(plan['site']);origin=(site.centroid.x,site.centroid.y)
        local=rotate(land,-angle,origin=origin);x0,y0,x1,y1=local.bounds
        zone=rotate(box(x0+.62*(x1-x0),y0,x1,y1),angle,origin=origin)
        blocks=[r for r in plan.get('blocks',[]) if _geom(r).centroid.within(zone)]
        accepted=unary_union([_geom(r) for r in blocks if _geom(r).area>=1500])
        fragments=[{'block_id':r['id'],'area_m2':_geom(r).area,'geometry':r['geometry']} for r in blocks if _geom(r).area<1500 and any(not b['properties'].get('retained') and _geom(b).intersection(_geom(r)).area>.01 for b in plan['buildings'])]
        fragments.extend({'building_id':b['id'],'geometry':b['geometry'],'reason_zh':'東北建築未完整歸屬大於等於1500平方公尺街廓'} for b in plan['buildings'] if not b['properties'].get('retained') and _geom(b).intersection(zone).area>.01 and _geom(b).difference(accepted).area>.01)
        check('NORTHEAST_NO_SMALL_BUILDING_BLOCKS',not fragments,failure_locations=fragments,minimum_block_area_m2=1500,zone_geometry=mapping(zone))
        front,intervals=_south_quay_frontage(plan)
        gaps=[b[0]-a[1] for a,b in zip(intervals,intervals[1:])]
        max_gap=max(gaps,default=0)
        check('SOUTH_QUAY_MAX_GAP',bool(intervals) and max_gap<=12.00001,failure_locations=[] if intervals and max_gap<=12.00001 else [{'geometry':mapping(front) if front is not None else None,'reason_zh':'缺少實際臨水立面或相鄰立面間隙超過12公尺'}],maximum_gap_m=max_gap,allowed_gap_m=12,facade_station_intervals_m=intervals)
    else:
        for ident in ('NORTHEAST_NO_SMALL_BUILDING_BLOCKS','SOUTH_QUAY_MAX_GAP'):check(ident,True,applicability='NOT_APPLICABLE',reason='no mapped waterfront')


def validate_plan(plan: dict) -> dict:
    """Recompute geometry and quantities; reported metrics are never trusted."""
    if plan.get('schema_version') == 'fab2-intent-plan-v1':
        from .fabric_intent import validate_intent_plan
        return validate_intent_plan(plan)
    failures=[]; checks={}
    def check(ident, ok, **evidence):
        checks[ident]={'passed':bool(ok),'status':'PASS' if ok else 'FAIL',**evidence}
        if not ok:failures.append(ident)
    try:
        check('CRS',plan.get('crs')=='EPSG:28992')
        site=shape(plan['site']);water=shape(plan['water']);land=site.difference(water)
        rows=sum([plan[k] for k in ['roads','blocks','buildings','land_use']],[])
        check('GEOMETRY_VALID',all(not _geom(r).is_empty and _geom(r).is_valid for r in rows))
        allocations=[_geom(r) for r in plan['land_use']];u=unary_union(allocations)
        check('LAND_COVERAGE',u.symmetric_difference(land).area<0.01,unallocated_m2=land.difference(u).area)
        check('LAND_NO_OVERLAP',sum(g.area for g in allocations)-u.area<0.01)
        check('LAND_MANAGEMENT',all(r['properties'].get('category') and r['properties'].get('manager') for r in plan['land_use']))
        new=[b for b in plan['buildings'] if not b['properties'].get('retained')]
        retained=[b for b in plan['buildings'] if b['properties'].get('retained')]
        footprint=unary_union([_geom(b) for b in plan['buildings']])
        check('BUILDING_CONTAINMENT',all(land.covers(_geom(b)) for b in new))
        check('BUILDING_NO_OVERLAP',sum(_geom(b).area for b in plan['buildings'])-footprint.area<0.01)
        originals={r['id']:r for r in plan['retained_inputs']}
        check('RETAINED_UNCHANGED',len(retained)==len(originals) and all(b['id'] in originals and b['geometry']==originals[b['id']]['geometry'] and b['properties']['source_record']==originals[b['id']] for b in retained))
        check('HEIGHT_CAP',all(0<b['properties']['height_m']<=20 for b in new))
        floor_bad=[]
        for b in new:
            q=b['properties'];profile=plan.get('parameters',{}).get('point_floor_height_assumption',{})
            profile_ok=profile.get('version')=='fab1c-point-six-storey-v1' and profile.get('ground_floor_m')==4 and profile.get('upper_floor_m')==3.2 and profile.get('maximum_floors')==6 and profile.get('maximum_height_m')==20
            six=profile_ok and q.get('first_floor_height_m')==4 and q.get('floor_height_assumption_version')=='fab1c-point-six-storey-v1' and plan['fabric_id']=='fabric.landscape_figure' and q['building_type']=='building.point_array'
            standard=3.2 if six else 3.5;maximum=6 if six else 5
            if abs(q.get('standard_floor_height_m',standard)-standard)>1e-6 or abs(q['height_m']-(q['first_floor_height_m']+standard*(q['floors']-1)))>1e-5 or not (1<=q['floors']<=3 if q['use']=='industrial' else 3<=q['floors']<=maximum):floor_bad.append(b['id'])
        check('FLOOR_HEIGHT',not floor_bad,failure_locations=floor_bad,point_six_storey_assumption=plan.get('parameters',{}).get('point_floor_height_assumption'))
        gfa=sum(_geom(b).area*b['properties']['floors']+(shape(b['properties']['mezzanine_geometry']).area if b['properties'].get('mezzanine_geometry') else 0) for b in new)
        check('NEW_GFA_TARGET',NEW_GFA_MIN_M2<=gfa<=146873.0,new_gfa_m2=gfa)
        rectangular=True
        for row in plan['blocks']+new:
            g=_geom(row)
            rectangular &= g.geom_type=='Polygon' and len(g.exterior.coords)==5 and abs(g.minimum_rotated_rectangle.area-g.area)<0.01
        check('ORTHOGONAL_TEMPLATES',rectangular)
        block_sizes=[]
        for b in plan['blocks']:
            g=_geom(b);coords=list(g.exterior.coords);lengths=[math.dist(coords[i],coords[i+1]) for i in range(4)]
            block_sizes.append((g.area,min(lengths)))
        check('BLOCK_MINIMUM',bool(block_sizes) and all(a>=1500 and s>=30 for a,s in block_sizes))
        streets=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads']])
        check('STREET_FRONTAGE',all(_geom(b).distance(streets)<=3.01 for b in new),failure_locations=[b['id'] for b in new if _geom(b).distance(streets)>3.01])
        # Sample all exterior rings at <=1m; add 0.5m conservative covering radius.
        max_fire=0.0;fire_failures=[]
        fire=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads'] if 'fire' in r['properties'].get('modes',[])])
        for b in plan['buildings']:
            for polygon in _parts(_geom(b)):
                ring=polygon.exterior;n=max(1,math.ceil(ring.length))
                building_max=max(ring.interpolate(ring.length*i/n).distance(fire) for i in range(n+1))+0.5
                max_fire=max(max_fire,building_max)
                if building_max>40:fire_failures.append({'building_id':b['id'],'distance_upper_m':building_max})
        check('FIRE_ALL_EXTERIORS',not fire.is_empty and max_fire<=40,max_distance_upper_m=max_fire if not fire.is_empty else None,failure_locations=fire_failures if not fire.is_empty else [b['id'] for b in plan['buildings']])
        for mode in MODES:
            lines=[_geom(r) for r in plan['roads'] if mode in r['properties'].get('modes',[])]
            # A graph edge exists only on a real geometric intersection.
            todo=set(range(len(lines)));components=0
            while todo:
                components+=1;stack=[todo.pop()]
                while stack:
                    i=stack.pop();neighbors={j for j in todo if lines[i].distance(lines[j])<=0.01};todo-=neighbors;stack.extend(neighbors)
            check('CONNECTIVITY_'+mode.upper(),components==1,components=components)
        def located_check(key, invalid, **evidence):
            check(key,not invalid,failure_locations=invalid,**evidence)
        invalid=[b['id'] for b in new if _geom(b).intersection(streets).area>.05]
        located_check('BUILDING_ROAD_CLEARANCE',invalid)
        located_check('BLOCK_STREET_FRONTAGE',[b['id'] for b in plan['blocks'] if _geom(b).boundary.distance(streets)>3.01])
        located_check('BUILDING_BUILDABLE',[b['id'] for b in new if not shape(plan['buildable']).buffer(1e-6).covers(_geom(b))])
        dictionary=plan['fabric_dictionary'];br=dictionary['blocks'];out=[]
        for b in plan['blocks']:
            g=_geom(b);r=g.minimum_rotated_rectangle;cs=list(r.exterior.coords);dims=sorted([math.dist(cs[i],cs[i+1]) for i in range(2)])
            if not (br['short_edge_m']['minimum']-1e-5<=dims[0]<=br['short_edge_m']['maximum']+1e-5 and br['long_edge_m']['minimum']-1e-5<=dims[1]<=br['long_edge_m']['maximum']+1e-5):out.append(b['id'])
        located_check('BLOCK_DICTIONARY_DIMENSIONS',out)
        parcels=plan.get('boundary_parcels',[])
        parcel_ids={r['id']:r for r in parcels}
        blocks_by_id={r['id']:r for r in plan['blocks']}
        parcel_failures=[]
        for b in new:
            parent=b['properties'].get('block_id');pid=b['properties'].get('parcel_id')
            if pid:
                parcel=parcel_ids.get(pid)
                if parent is not None or parcel is None or not _geom(parcel).buffer(1e-6).covers(_geom(b)):
                    parcel_failures.append(b['id'])
            elif parent not in blocks_by_id or not _geom(blocks_by_id[parent]).buffer(1e-6).covers(_geom(b)):
                parcel_failures.append(b['id'])
        parcel_coverage=[]
        for parcel in parcels:
            children=[b for b in new if b['properties'].get('parcel_id')==parcel['id']]
            g=_geom(parcel);cs=list(g.minimum_rotated_rectangle.exterior.coords)
            short=min(math.dist(cs[i],cs[i+1]) for i in range(2))
            cover=unary_union([_geom(b) for b in children]).intersection(g).area/g.area
            parcel_coverage.append({'parcel_id':parcel['id'],'coverage':cover,'area_m2':g.area,'short_m':short})
            if not children or g.area<1500-1e-5 or short<30-1e-5 or not land.buffer(1e-6).covers(g) or not parcel['properties'].get('reason_zh') or g.boundary.distance(streets)>3.01 or cover+1e-6<dictionary['density_targets']['GSI']['range']['minimum']:
                parcel_failures.append(parcel['id'])
        public_roles={'courtyard_fire_lane','courtyard_service_gate','facade_service_spur','retained_service_lane','boundary_plot_service_lane','park_maintenance_path','south_quay_shared_alley'}
        public_row=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads'] if r['properties']['role'] not in public_roles])
        parcel_overlaps=[]
        for i,parcel in enumerate(parcels):
            for other in parcels[i+1:]+plan['blocks']:
                overlap=_geom(parcel).intersection(_geom(other)).area
                if overlap>.01:
                    parcel_failures.append(parcel['id']);parcel_overlaps.append({'parcel_id':parcel['id'],'other_id':other['id'],'overlap_m2':overlap})
            overlap=_geom(parcel).intersection(public_row).area
            if overlap>.01:
                parcel_failures.append(parcel['id']);parcel_overlaps.append({'parcel_id':parcel['id'],'other_id':'public_right_of_way','overlap_m2':overlap})
        located_check('BOUNDARY_PARCEL_SEMANTICS',sorted(set(parcel_failures)),coverage=parcel_coverage,overlaps=parcel_overlaps)

        angles=[]
        for b in new:
            coords=list(_geom(b).exterior.coords)[:-1]
            for i,v in enumerate(coords):
                aa=(coords[i-1][0]-v[0],coords[i-1][1]-v[1]);bb=(coords[(i+1)%len(coords)][0]-v[0],coords[(i+1)%len(coords)][1]-v[1]);den=math.hypot(*aa)*math.hypot(*bb)
                degree=math.degrees(math.acos(max(-1,min(1,(aa[0]*bb[0]+aa[1]*bb[1])/den)))) if den else 0
                if degree<80-1e-5:angles.append({'building_id':b['id'],'corner_index':i,'angle_deg':degree})
        located_check('MASSING_CORNERS',angles)
        bad_depth=[];bad_terrace=[];bad_slab=[];slabs=[]
        for b in new:
            q=b['properties'];coords=list(_geom(b).minimum_rotated_rectangle.exterior.coords);dims=sorted([math.dist(coords[i],coords[i+1]) for i in range(2)]);kind=q['building_type'];depth=q['depth_m']
            if kind=='building.industrial_hall':limits=(20,40)
            elif kind=='building.point_array':limits=(20,20)
            elif kind in ('building.rowhouse','building.terraced'):limits=(10,14)
            else:limits=(12,14)
            if not limits[0]-1e-6<=depth<=limits[1]+1e-6 or not any(abs(edge-depth)<.01 for edge in dims):bad_depth.append(b['id'])
            if kind in ('building.rowhouse','building.terraced'):
                front=next((edge for edge in dims if abs(edge-depth)>.01),dims[0])
                if not 5.4-1e-5<=front<=8+1e-5:bad_terrace.append(b['id'])
            if kind=='building.i_slab':
                slabs.append(b)
                if dims[1]>90+1e-5 or not 12-1e-5<=dims[0]<=14+1e-5:bad_slab.append(b['id'])
        located_check('WING_DEPTH',bad_depth);located_check('TERRACE_FRONTAGE',bad_terrace);located_check('SLAB_LENGTH_DEPTH',bad_slab)
        bad_spacing=[]
        for i,b in enumerate(slabs):
            for other in slabs[i+1:]:
                distance=_geom(b).distance(_geom(other));needed=max(b['properties']['height_m'],other['properties']['height_m'])
                if distance+1e-5<needed:bad_spacing.append({'buildings':[b['id'],other['id']],'distance_m':distance,'required_m':needed})
        located_check('SLAB_SPACING',bad_spacing)
        courtyard_blocks={b['properties']['block_id'] for b in new if b['properties']['building_type'] in ('building.courtyard_closed','building.u_block','building.courtyard_open_corner')}
        bad_courtyard=[]
        for b in plan['blocks']:
            if b['id'] in courtyard_blocks:
                children=[q for q in new if q['properties']['block_id']==b['id']];depth=max(q['properties']['depth_m'] for q in children)
                coords=list(_geom(b).minimum_rotated_rectangle.exterior.coords);short=min(math.dist(coords[i],coords[i+1]) for i in range(2));clear_width=short-2*depth
                if clear_width<20-1e-5:bad_courtyard.append({'block_id':b['id'],'clear_width_m':clear_width})
        located_check('COURTYARD_CLEAR_WIDTH',bad_courtyard)
        located_check('ALL_BUILDINGS_FRONTAGE',[b['id'] for b in plan['buildings'] if _geom(b).distance(streets)>3.01])
        for mode in ('pedestrian','bicycle','car'):
            network=unary_union([_geom(r) for r in plan['roads'] if mode in r['properties']['modes']])
            located_check('ENTRANCES_'+mode.upper(),[e['id'] for e in plan['entrances'] if Point(e['coordinates']).distance(network)>.05])
        retained_missing=[]
        for r in plan['retained_road_inputs']:
            actual=[_geom(q) for q in plan['roads'] if q['properties'].get('source_id')==r['id']]
            if not actual or _geom(r).difference(unary_union(actual).buffer(1e-5)).length>.01:retained_missing.append(r['id'])
        located_check('RETAINED_ROADS_PRESERVED',retained_missing)
        waterfront_lines=[_geom(r) for r in plan['roads'] if r['properties']['role']=='waterfront_path']
        waterfront_union=unary_union(waterfront_lines)
        waterfront_groups=_components([r for r in plan['roads'] if r['properties']['role']=='waterfront_path'])
        band=shape(plan['waterfront_band'])
        spans=[]
        for group in waterfront_groups:
            group_geom=unary_union([waterfront_lines[j] for j in group]);spans.append(group_geom.bounds[2]-group_geom.bounds[0])
        required_span=max(0,band.bounds[2]-band.bounds[0]-40) if not band.is_empty else 0
        check('WATERFRONT_CONTINUITY',bool(spans) and max(spans)>=required_span,components=len(waterfront_groups),length_m=waterfront_union.length,longest_connected_x_span_m=max(spans,default=0),shore_x_span_required_m=required_span)
        primary=[r for r in plan['roads'] if r['properties']['role']=='primary_street']
        check('PRIMARY_STREET_DICTIONARY',bool(primary) and all(dictionary['street_network']['hierarchy'][0]['section_width_m']['minimum']<=r['properties']['width_m']<=dictionary['street_network']['hierarchy'][0]['section_width_m']['maximum'] for r in primary),failure_locations=[] if primary else ['路網骨架未找到可容納字典主街路幅的對位走廊'])
        parks=[r for r in plan['land_use'] if r['properties']['category']=='parks']
        park_invalid=[];park_geometry=[]
        internal_park_roles={'courtyard_fire_lane','courtyard_service_gate','facade_service_spur','retained_service_lane','boundary_plot_service_lane','park_maintenance_path','south_quay_shared_alley'}
        park_streets=unary_union([_geom(r).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads'] if r['properties']['role'] not in internal_park_roles])
        for park in parks:
            pg=_geom(park);core=pg.buffer(-7.5,join_style=2)
            cores=[g for g in _parts(core) if g.geom_type=='Polygon' and g.area>1e-6]
            frontage=None if park_streets.is_empty else pg.boundary.distance(park_streets)
            park_geometry.append({'park_id':park['id'],'area_m2':pg.area,'eroded_components':len(cores),'eroded_area_m2':core.area,'frontage_distance_m':frontage})
            if pg.geom_type!='Polygon' or not pg.is_valid or pg.area<1000-1e-6 or len(cores)!=1 or frontage is None or not math.isfinite(frontage) or frontage>3.01 or not all(park['properties'].get(k) for k in ('manager','role','reason_zh')):park_invalid.append(park['id'])
        located_check('PARK_COHERENT_SHAPE',park_invalid,park_geometry=park_geometry,basis='complete managed single-polygon park >=1000m2, single useful 15m core, actual public frontage; rectangles are not mandatory')
        check('PARK_PRESENT',bool(parks),park_count=len(parks))
        known={'roads','blocks','parks','plazas','waterfront','service','retained_buildings','public_facilities'}
        located_check('LAND_USE_CATEGORIES',[r['id'] for r in plan['land_use'] if r['properties'].get('category') not in known])
        percent=100*u.intersection(land).area/land.area
        check('LAND_SUM_100_PERCENT',abs(percent-100)<=.5,percentage=percent)
        located_check('MEZZANINE_GEOMETRY',[b['id'] for b in new if b['properties'].get('mezzanine_geometry') and (b['properties']['use']!='industrial' or not _geom(b).buffer(1e-6).covers(shape(b['properties']['mezzanine_geometry'])) or b['properties']['first_floor_height_m']<6)])
        second_round_metrics=_validate_second_round(plan,check)
        second_round_metrics.update(_validate_third_round(plan,check))
        _validate_fourth_round(plan,check)
        metrics={**second_round_metrics,'new_gfa_m2':gfa,'retained_gfa_upper_m2':sum(b['properties']['gfa_upper_m2'] for b in retained),'land_area_m2':land.area,'water_area_m2':water.area,'denominator':'site minus mapped water; EPSG:28992 square metres','new_far':gfa/land.area,'gsi':footprint.area/land.area,'fsi':(gfa+sum(b['properties']['gfa_upper_m2'] for b in retained))/land.area,'L':(gfa+sum(b['properties']['gfa_upper_m2'] for b in retained))/footprint.area if footprint.area else None,'OSR':(land.area-footprint.area)/(gfa+sum(b['properties']['gfa_upper_m2'] for b in retained)) if gfa else None,'block_count':len(plan['blocks']),'new_building_count':len(new),'allocation_percent':100*u.intersection(land).area/land.area,'max_fire_distance_upper_m':max_fire if not fire.is_empty else None}
    except (KeyError,TypeError,ValueError,AttributeError) as exc:
        failures.append('MALFORMED_PLAN');checks['MALFORMED_PLAN']={'passed':False,'error':str(exc)};metrics={}
    return {'passed':not failures,'status':'PASS' if not failures else 'FAIL','failure_ids':failures,'checks':checks,'metrics':metrics}


def plan_from_intent(intent: dict, site_facts: dict, dictionary: dict) -> dict:
    """忠實執行指揮官框架；不改寫意圖或推定未授權的通行模式。"""
    from .fabric_intent import execute_intent
    return execute_intent(intent, site_facts, dictionary)

def compare_plans(plans: list[dict]) -> dict:
    """No winner; pairwise distinctness requires two measured dimensions.

    Explicit exploratory discrimination settings: orthogonal-frame direction
    >=10 degrees, median block area >=10% and footprint-mix TV >=20%.
    These are comparison assumptions, not planning regulations.
    """
    import statistics
    def road_frame(plan):
        # Four-angle circular mean folds perpendicular grid axes together.
        # Recompute from delivered street segments rather than block metadata.
        x=y=weight=0.
        for road in plan['roads']:
            if road['properties'].get('role') not in {'primary_street','block_edge_street'}:continue
            for line in _parts(_geom(road)):
                if line.geom_type!='LineString':continue
                cs=list(line.coords)
                for a,b in zip(cs,cs[1:]):
                    length=math.dist(a,b);angle=math.atan2(b[0]-a[0],b[1]-a[1])
                    x+=length*math.cos(4*angle);y+=length*math.sin(4*angle);weight+=length
        return math.degrees(math.atan2(y,x))/4%90 if weight and math.hypot(x,y)>1e-6 else None
    def mix(plan):
        values={}
        for b in plan['buildings']:
            if not b['properties'].get('retained'):
                kind=b['properties']['building_type'];values[kind]=values.get(kind,0)+_geom(b).area
        total=sum(values.values())
        return {k:v/total for k,v in values.items()} if total else {}
    rows=[{'fabric_id':p['fabric_id'],'orientation_deg':p['orientation_deg'],'validation':validate_plan(p)} for p in plans]
    pairs=[]
    for i,a in enumerate(plans):
        for b in plans[i+1:]:
            ra,rb=road_frame(a),road_frame(b)
            delta=None if ra is None or rb is None else abs(ra-rb)%90
            if delta is not None:delta=min(delta,90-delta)
            ma=statistics.median([_geom(r).area for r in a['blocks']]) if a['blocks'] else 0
            mb=statistics.median([_geom(r).area for r in b['blocks']]) if b['blocks'] else 0
            aa,bb=mix(a),mix(b);tv=sum(abs(aa.get(k,0)-bb.get(k,0)) for k in aa.keys()|bb.keys())/2
            flags={'road_direction':delta is not None and delta>=10,'block_size':abs(ma-mb)>=.1*max(ma,mb),'type_mix':tv>=.2}
            distinct=sum(flags.values())>=2
            pairs.append({'fabric_ids':[a['fabric_id'],b['fabric_id']],'direction_difference_deg':delta,'measured_road_frame_deg':[ra,rb],'road_direction_basis_zh':'實際主街與街廓邊街線段長加權四倍角圓平均，不使用街廓方向標籤','median_block_area_m2':[ma,mb],
                          'footprint_type_mix':[aa,bb],'mix_total_variation':tv,'dimensions_distinct':flags,'distinct_dimension_count':sum(flags.values()),
                          'distinct':distinct,'status':'PASS' if distinct else 'FAIL'})
    return {'plans':rows,'pairwise':pairs,'status':'PASS' if len(plans)==4 and all(p['distinct'] for p in pairs) else 'FAIL',
            'distinct_pair_count':sum(p['distinct'] for p in pairs),'winner':None,'decision_rule':'未制定整體排名規則；由人類決定。',
            'comparison_assumptions':{'direction_degrees':10,'median_block_area_fraction':.1,'footprint_mix_total_variation':.2}}
