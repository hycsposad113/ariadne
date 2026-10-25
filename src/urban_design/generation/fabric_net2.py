"""NET2 deterministic geometry experiment; shared validators retain their rules.

The optional primary reservation is supplied before existing cell search and massing.
The only shared validation change is the Founder-approved 85% GFA lower bound.
"""
from __future__ import annotations
import copy
import hashlib
import inspect
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import nearest_points, unary_union
from .fabric_network_finish import visible_route
from . import fabric_plan as base

SOURCE_IDS = ('way/7518596', 'way/888752939', 'way/888752938',
              'way/888752937', 'way/7518070', 'way/82806445')


def keileweg_alignment(features):
    by_id = {f['id']: f for f in features}
    coordinates = []
    for ident in SOURCE_IDS:
        row = by_id[ident]
        if str(row['properties'].get('name', '')).casefold() != 'keileweg':
            raise ValueError('NET2 source name drift')
        points = list(shape(row['geometry']).coords)
        if coordinates and coordinates[-1] != points[0]:
            raise ValueError('NET2 source topology drift')
        coordinates.extend(points if not coordinates else points[1:])
    line = LineString(coordinates)
    return line, {'source_ids': list(SOURCE_IDS), 'crs': 'EPSG:28992',
                  'length_m': line.length, 'method': 'exact frozen Keileweg coordinates; eastern branch to Vierhavensstraat junction'}


def transverse_reservations(land, waterfront, retained, external, junctions):
    """Reserve straight, full-width land routes; reject fixed building conflicts."""
    routes=[]; records=[]
    safe=land.buffer(-2.02,join_style=2)
    for coordinate in junctions:
        target=Point(coordinate)
        # Targets must be verified frozen external geometry, never invented nodes.
        if not any(shape(r['geometry']).distance(target)<1e-6 for r in external):
            raise ValueError('NET2_TRANSVERSE_TARGET_NOT_ON_EXTERNAL_NETWORK')
        shore=nearest_points(target,waterfront)[1]
        candidate=LineString([shore,target])
        parts=[g for g in base._parts(candidate.intersection(safe)) if g.geom_type=='LineString']
        if not parts:continue
        route=max(parts,key=lambda g:g.length)
        record={'external_target':list(coordinate),'geometry':mapping(route),'width_m':4.}
        if route.buffer(2,cap_style=2).intersects(retained.buffer(3)):
            record['status']='BLOCKED_RETAINED_BUILDING'
        else:
            routes.append(route);record['status']='RESERVED'
        records.append(record)
    return routes,records


def generate_net2_plan(facts, context, fabric, external, round_number=1):
    if round_number not in (1, 2, 3, 4, 5, 6, 7):
        raise ValueError('NET2 round must be 1..7')
    line, receipt = keileweg_alignment(external['motor_vehicle'])
    site=shape(facts['geometry']['site'])
    land=site.difference(site.intersection(shape(facts['geometry']['water'])))
    safe=land.buffer(-9.02,join_style=2)
    # First full-width safe frozen coordinate begins the Keileweg continuation.
    # The western approach is anchored to the previous legitimate site entry,
    # then joins the actual source bearing without a circuit around the site.
    axis=90-context['site']['principal_axis']['long_axis_azimuth_deg']
    origin=tuple(site.centroid.coords[0])
    local=base.rotate(land,-axis,origin=origin)
    corners=sorted(list(local.exterior.coords)[:-1],key=lambda q:q[1],reverse=True)[:2]
    corners.sort()
    old_start=base.rotate(base.Point(corners[0][0]+12,corners[0][1]-9.2),axis,origin=origin)
    western=base.nearest_points(old_start,safe)[1]
    coordinates=list(line.coords)
    first=next(i for i,c in enumerate(coordinates) if safe.covers(base.Point(c)))
    last=max(i for i,c in enumerate(coordinates) if safe.covers(base.Point(c)))
    spine=LineString([western.coords[0]]+coordinates[first:last+1])
    transverses=[]; transverse_receipt=[]
    if round_number>=4 and fabric['id'] in ('fabric.courtyard_islands','fabric.landscape_figure'):
        # One straight continuation replaces the old subtle sequence of bearings.
        if round_number==4:spine=LineString([western.coords[0],coordinates[last]])
        waterfront=shape(facts['geometry']['waterfront_band']).boundary
        if round_number>=5:waterfront=spine
        retained=unary_union([shape(r['geometry']) for r in facts['geometry']['retained_buildings']])
        junctions=[(88727.461,435787.776),(88846.973,435857.039),
                   (88967.075,435930.659),(89015.7,435961.083),
                   (89169.77,436053.843),(89274.247,436120.521),
                   (89385.326,436191.331)]
        if round_number>=5:
            # Additional actual Keileweg vertices give western parallel routes
            # direct access rather than the 170 degree western hairpin.
            junctions += [(88833.223,435850.311),(88923.862,435903.501),
                          (89056.369,435986.428),(89128.917,436031.704),
                          (89200.33,436074.047),(89337.942,436161.187)]
        transverses,transverse_receipt=transverse_reservations(land,waterfront,retained,external['motor_vehicle'],junctions)
    # The unchanged validator independently verifies the complete buffered ROW.
    intent={'block_long_m':130.0} if round_number==5 and fabric['id']=='fabric.courtyard_islands' else None
    plan=base.generate_plan(copy.deepcopy(facts),copy.deepcopy(context),copy.deepcopy(fabric),intent,
                            primary_geometry_override=spine, transverse_geometry_overrides=transverses)
    receipt['internal_primary']={'geometry':mapping(spine),'length_m':spine.length,
        'endpoints': [list(spine.coords[0]),list(spine.coords[-1])],
        'straight_line_ratio':base.Point(spine.coords[0]).distance(base.Point(spine.coords[-1]))/spine.length,
        'full_width_outside_land_m2':spine.buffer(9,cap_style=2,join_style=2).difference(land).area}
    # Exact external tail is preserved as a public approach, including the
    # actual frozen Keileweg junction. It is not silently counted as site land.
    outside = line.difference(spine.buffer(1e-7))
    for i, part in enumerate(base._parts(outside)):
        if part.geom_type == 'LineString' and part.length > .01:
            plan['roads'].append(base._feature(part, f'net2-city-tail-{i}', width_m=18., modes=list(base.MODES), role='city_connector', hierarchy=0, target_source_id=SOURCE_IDS[-1]))
    for i,record in enumerate(r for r in transverse_receipt if r['status']=='RESERVED'):
        route=shape(record['geometry']);target=Point(record['external_target'])
        end=min((Point(route.coords[0]),Point(route.coords[-1])),key=lambda p:p.distance(target))
        approach=LineString([end,target])
        if approach.length>.01:
            plan['roads'].append(base._feature(approach,f'net2-external-transverse-{i}',width_m=4.,modes=list(base.MODES),role='city_connector',hierarchy=1))
    plan['net2'] = {'round': round_number, 'alignment': receipt, 'transverse_reservations':transverse_receipt,
                    'generator_sha256': hashlib.sha256(inspect.getsource(base.generate_plan).encode()).hexdigest(),
                    'method': 'reserve Keileweg primary and verified transverse approaches before cell search; rebuild blocks and massing',
                    'formal_result_eligible': False,
                    'model_routing': 'Codex gpt-6.1-sol medium (user requested execution label)' if round_number>=4 else 'gpt-6.1-sol low; bounded coupled geometry/network replan'}
    return plan


def retain_and_connect_network(plan, parent):
    """Keep every original NET1 line verbatim and add explicit clear approaches."""
    preserved=copy.deepcopy(parent.get('net1',{}).get('added_roads',[]))
    generated_roads=list(plan['roads'])
    plan['roads'].extend(preserved)
    plan['net1']=copy.deepcopy(parent.get('net1',{}))
    mass=unary_union([shape(b['geometry']) for b in plan['buildings']])
    primary=unary_union([shape(r['geometry']) for r in plan['roads'] if r['properties']['role']=='primary_street'])
    waterfront=unary_union([shape(r['geometry']) for r in plan['roads'] if r['properties']['role']=='waterfront_path'])
    records=[];failed=[]
    land=shape(plan['site']).difference(shape(plan['water']))
    def connect(row,target,kind):
        a,b=nearest_points(shape(row['geometry']),target)
        if a.distance(b)<.01:return
        line=visible_route(a.coords[0],b.coords[0],mass,width=4)
        if line is None:
            failed.append({'id':row['id'],'kind':kind,'reason':'no footprint-clear bounded route'})
            return
        if line.buffer(2,cap_style=2,join_style=2).difference(land).area>.05:
            failed.append({'id':row['id'],'kind':kind,'reason':'new approach leaves full-width site land or crosses water'})
            return
        feature=base._feature(line,f'net2-join-{len(records)}',width_m=4.,modes=row['properties']['modes'],role='cross_street',hierarchy=1,net2_strategy=kind,source_road_id=row['id'],target_role='waterfront_path' if 'waterfront' in kind else ('primary_street' if 'primary' in kind else 'generated_same_mode_network'))
        plan['roads'].append(feature);records.append(feature)
    for row in preserved:
        modes=set(row['properties']['modes'])
        anchors=unary_union([shape(r['geometry']) for r in generated_roads if modes.intersection(r['properties']['modes'])])
        connect(row,anchors,'retained_net1_to_new_network')
    for row in generated_roads:
        if row['properties']['role']=='primary_street':connect(row,waterfront,'primary_to_waterfront')
    for row in list(plan['roads']):
        if row['properties']['role'] in ('block_edge_street','harbour_cross_lane'):
            connect(row,primary,'each_transverse_to_primary')
            connect(row,waterfront,'each_transverse_to_waterfront')
    collisions=[{'id':r['id'],'overlap_m2':shape(r['geometry']).buffer(r['properties']['width_m']/2,cap_style=2).intersection(mass).area}
                for r in preserved if shape(r['geometry']).buffer(r['properties']['width_m']/2,cap_style=2).intersection(mass).area>.05]
    plan['net2']['network_preservation']={'original_count':len(preserved),'geometry_changed_ids':[],
        'preserved_road_footprint_collisions':collisions,'new_links':records,'failed_links':failed}
    return plan


def enforce_five_storeys_and_fill(plan):
    """Real five-storey envelope; capacity additions require full geometric fit."""
    new=[b for b in plan['buildings'] if not b['properties'].get('retained')]
    for b in new:
        q=b['properties'];q['max_floors']=min(5,q.get('max_floors',5))
        q['floors']=min(5,q['floors']);q['standard_floor_height_m']=3.5
        q['height_m']=q['first_floor_height_m']+3.5*(q['floors']-1)
        q.pop('floor_height_assumption_version',None)
        if q.get('mezzanine_geometry') and (q['first_floor_height_m']<6 or not shape(b['geometry']).buffer(1e-6).covers(shape(q['mezzanine_geometry']))):
            for key in ('mezzanine_geometry','mezzanine_gfa_m2','mezzanine_level_m'):q.pop(key,None)
    plan['parameters'].pop('point_floor_height_assumption',None)
    def gfa():return sum(shape(b['geometry']).area*b['properties']['floors']+(shape(b['properties']['mezzanine_geometry']).area if b['properties'].get('mezzanine_geometry') else 0) for b in new)
    before=gfa(); additions=[]; raised=[]; expanded=[]
    if plan.get('net2',{}).get('round',0)>=5 and plan['fabric_id']=='fabric.courtyard_islands':
        # Use remaining authorised storeys before consuming more scarce land.
        for b in new:
            q=b['properties'];initial=q['floors']
            while q['floors']<min(5,q.get('max_floors',5)) and gfa()<132186 and gfa()+shape(b['geometry']).area<=146873:
                q['floors']+=1
            q['height_m']=q['first_floor_height_m']+3.5*(q['floors']-1)
            if q['floors']!=initial:raised.append(b['id'])
    if plan.get('net2',{}).get('round')==5 and plan['fabric_id']=='fabric.landscape_figure':
        # Preserve 20 m depth and a compact point form; enlarge the other edge
        # only inside its existing block/parcel and the actual clear buildable.
        roads=unary_union([shape(r['geometry']).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads']])
        courts=unary_union([shape(r['geometry']) for r in plan['courtyards']])
        buildable=shape(plan['buildable']).difference(roads).difference(courts)
        hosts={r['id']:shape(r['geometry']) for r in plan['blocks']+plan.get('boundary_parcels',[])}
        angle=90-plan['block_axis_azimuth_deg'];origin=tuple(shape(plan['site']).centroid.coords[0])
        for b in new:
            if gfa()>=132186:break
            q=b['properties']
            if q['building_type']!='building.point_array':continue
            host=hosts.get(q.get('parcel_id') or q.get('block_id'))
            if host is None:continue
            original=shape(b['geometry']);local=base.rotate(original,-angle,origin=origin)
            if abs(local.envelope.area-local.area)>.01:continue
            x0,y0,x1,y1=local.bounds
            others=unary_union([shape(other['geometry']) for other in plan['buildings'] if other is not b])
            domain=host.intersection(buildable).difference(others.buffer(.25))
            chosen=original
            for growth in range(1,7):
                for sign in (-1,1):
                    for direction in ('x','y'):
                        bounds=[x0,y0,x1,y1]
                        bounds[(0 if sign<0 else 2) if direction=='x' else (1 if sign<0 else 3)]+=growth*sign
                        candidate=base.rotate(base.box(*bounds),angle,origin=origin)
                        if candidate.area<=chosen.area or gfa()+(candidate.area-original.area)*q['floors']>146873:continue
                        if domain.buffer(1e-7).covers(candidate):chosen=candidate
            if chosen.area>original.area+.01:
                b['geometry']=mapping(chosen)
                expanded.append({'building_id':b['id'],'before_m2':original.area,'after_m2':chosen.area})

    rejected={"outside_buildable_or_host_or_hits_ROW_court":0,"mass_clearance":0,"no_frontage_within_3m":0,"exceeds_GFA_upper":0}
    if plan['fabric_id'] in ('fabric.landscape_figure','fabric.closed_block_extension') and before<132186:
        land=shape(plan['site']).difference(shape(plan['water']))
        buildable=shape(plan['buildable']).intersection(land)
        roads=unary_union([shape(r['geometry']).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads']])
        mass=unary_union([shape(b['geometry']) for b in plan['buildings']])
        courts=unary_union([shape(c['geometry']) for c in plan['courtyards']])
        point=plan['fabric_id']=='fabric.landscape_figure'
        width,depth=(20,20) if point else (20,12)
        kind='building.point_array' if point else 'building.courtyard_closed'
        template=next(b for b in new if b['properties']['building_type']==kind)
        origin=tuple(land.centroid.coords[0]);angle=90-plan['block_axis_azimuth_deg']
        hosts=plan['blocks']+(plan.get('boundary_parcels',[]) if point else [])
        for block in hosts:
            domain=shape(block['geometry']).intersection(buildable).difference(roads).difference(courts)
            local=base.rotate(domain,-angle,origin=origin)
            if local.is_empty:continue
            xmin,ymin,xmax,ymax=local.bounds
            for x in range(base.math.ceil(xmin),base.math.floor(xmax-width)+1,4):
                for y in range(base.math.ceil(ymin),base.math.floor(ymax-depth)+1,4):
                    if gfa()>=132186:break
                    candidate=base.rotate(base.box(x,y,x+width,y+depth),angle,origin=origin)
                    if not domain.buffer(1e-7).covers(candidate):
                        rejected['outside_buildable_or_host_or_hits_ROW_court']+=1;continue
                    if candidate.intersects(mass.buffer(.25)):
                        rejected['mass_clearance']+=1;continue
                    if candidate.distance(roads)>3.01:
                        rejected['no_frontage_within_3m']+=1;continue
                    floors=min(5,max(3,base.math.ceil((132186-gfa())/candidate.area)))
                    if gfa()+candidate.area*floors>146873:
                        rejected['exceeds_GFA_upper']+=1;continue
                    row=copy.deepcopy(template);row['id']=f'net2-capacity-{len(additions)}'
                    row['geometry']=mapping(candidate);q=row['properties'];q['id']=row['id'];q.pop('parcel_id',None);q.pop('block_id',None)
                    q['parcel_id' if block in plan.get('boundary_parcels',[]) else 'block_id']=block['id'];q['depth_m']=depth;q['floors']=floors;q['height_m']=q['first_floor_height_m']+3.5*(floors-1)
                    plan['buildings'].append(row);new.append(row);additions.append(row['id']);mass=mass.union(candidate)
                if gfa()>=132186:break
            if gfa()>=132186:break
    plan['net2']['five_storey_capacity']={'gfa_before_additions_m2':before,'raised_floor_buildings':raised,'expanded_point_footprints':expanded,'gfa_after_additions_m2':gfa(),'added_buildings':additions,'rejected_candidate_counts':rejected,
        'remaining_target_deficit_m2':max(0,132186-gfa()),'method':'actual 20x20m landscape points or 20x12m closed-block wings only inside existing buildable blocks; excludes ROW/courts/mass, requires street frontage <=3.01m; 4m deterministic search'}
    return plan


def fill_round6_points(plan):
    """Grow actual points within existing hosts; preserve the actual 20m depth."""
    if plan['fabric_id']!='fabric.landscape_figure':return plan
    target=base.NEW_GFA_MIN_M2
    def gfa():
        return sum(shape(b['geometry']).area*b['properties']['floors']+
                   (shape(b['properties']['mezzanine_geometry']).area if b['properties'].get('mezzanine_geometry') else 0)
                   for b in plan['buildings'] if not b['properties'].get('retained'))
    rows=[];hosts={r['id']:shape(r['geometry']) for r in plan['blocks']+plan.get('boundary_parcels',[])}
    roads=unary_union([shape(r['geometry']).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2) for r in plan['roads']])
    courts=unary_union([shape(r['geometry']) for r in plan['courtyards']])
    angle=90-plan['block_axis_azimuth_deg'];origin=tuple(shape(plan['site']).centroid.coords[0])
    for b in plan['buildings']:
        if gfa()>=target:break
        q=b['properties']
        if q.get('retained') or q.get('building_type')!='building.point_array':continue
        host=hosts.get(q.get('parcel_id') or q.get('block_id'))
        if host is None:continue
        original=shape(b['geometry']);local=base.rotate(original,-angle,origin=origin)
        if abs(local.envelope.area-local.area)>.01:continue
        x0,y0,x1,y1=local.bounds
        others=unary_union([shape(o['geometry']) for o in plan['buildings'] if o is not b])
        domain=host.intersection(shape(plan['buildable'])).difference(roads).difference(courts).difference(others.buffer(.25))
        chosen=original
        for growth in range(1,13):
            for side in range(4):
                bounds=[x0,y0,x1,y1];bounds[side]+=growth*(-1 if side<2 else 1)
                if abs(min(bounds[2]-bounds[0],bounds[3]-bounds[1])-20)>.001:continue
                # Compact point form, <=38m other edge, no speculative new host.
                if max(bounds[2]-bounds[0],bounds[3]-bounds[1])>38:continue
                candidate=base.rotate(base.box(*bounds),angle,origin=origin)
                if candidate.area<=chosen.area or gfa()+(candidate.area-original.area)*q['floors']>146873:continue
                if domain.buffer(1e-7).covers(candidate):chosen=candidate
        if chosen.area>original.area+.01:
            b['geometry']=mapping(chosen);rows.append({'building_id':b['id'],'before_m2':original.area,'after_m2':chosen.area})
    plan['net2']['round6_capacity']={'target_minimum_m2':target,'status':'ASSUMED','decision':'Founder 2026-10-15 85–100%', 'expanded_footprints':rows,'actual_gfa_m2':gfa(),'deficit_m2':max(0,target-gfa())}
    return plan


def direct_round6_links(plan, external):
    """Try straight actual main/external and transverse/waterfront links.

    No retained footprint, court or island may be cut. Actual new buildings can
    be omitted only within the 85% capacity budget, with surviving block mass.
    """
    primary=unary_union([shape(r['geometry']) for r in plan['roads'] if r['properties']['role']=='primary_street'])
    waterfront=unary_union([shape(r['geometry']) for r in plan['roads'] if r['properties']['role']=='waterfront_path'])
    land=shape(plan['site']).difference(shape(plan['water']))
    courts=unary_union([shape(r['geometry']) for r in plan['courtyards']])
    islands=unary_union([shape(r['geometry']) for r in plan['blocks']]) if plan['fabric_id']=='fabric.courtyard_islands' else base.Polygon()
    external_surface=unary_union([shape(r['geometry']).buffer(2.01,cap_style=2,join_style=2) for r in external])
    records=[];candidates=[]
    for r in external:
        if r['properties'].get('name','').casefold()=='keileweg':
            for c in shape(r['geometry']).coords:
                end=Point(c);start=nearest_points(primary,end)[0]
                if start.distance(end)>.01:candidates.append(('main_to_frozen_keileweg',r['id'],LineString([start,end]),True))
    for r in list(plan['roads']):
        if r['properties']['role'] in ('primary_street','cross_street','block_edge_street','harbour_cross_lane'):
            start,end=nearest_points(shape(r['geometry']),waterfront)
            if start.distance(end)>.01:candidates.append(('transverse_to_waterfront',r['id'],LineString([start,end]),False))
    baseline=base.validate_plan(plan)
    protected_passes={k for k,v in baseline['checks'].items() if v['passed']}
    def gfa(rows):
        return sum(shape(b['geometry']).area*b['properties']['floors']+(shape(b['properties']['mezzanine_geometry']).area if b['properties'].get('mezzanine_geometry') else 0) for b in rows if not b['properties'].get('retained'))
    # At most one identical geometric link; do not add redundant ID duplicates.
    seen=set()
    for kind,source,line,outside_allowed in sorted(candidates,key=lambda c:c[2].length):
        if line.wkb_hex in seen:continue
        seen.add(line.wkb_hex)
        record={'kind':kind,'source_id':source,'length_m':line.length,'geometry':mapping(line)}
        row=line.buffer(2,cap_style=2,join_style=2)
        if row.intersection(shape(plan['water'])).area>.05:reason='NO_NEW_WATER_CROSSING'
        elif row.difference(land.union(external_surface) if outside_allowed else land).area>.05:reason='FULL_WIDTH_LEAVES_LAND_OR_FROZEN_ROAD'
        elif row.intersection(courts).area>.01 or row.intersection(islands).area>.05:reason='COURT_OR_WHOLE_ISLAND_CONFLICT'
        else:reason=None
        hit=[b for b in plan['buildings'] if shape(b['geometry']).intersection(row).area>.01]
        if not reason and any(b['properties'].get('retained') for b in hit):reason='RETAINED_BUILDING_CONFLICT'
        remaining=[b for b in plan['buildings'] if b not in hit]
        if not reason and gfa(remaining)<base.NEW_GFA_MIN_M2:reason='GFA_85_PERCENT_BUDGET'
        if reason:record['status']=reason;records.append(record);continue
        if any(shape(r['geometry']).buffer(.0001).covers(line) for r in plan['roads']):
            record['status']='ALREADY_DIRECT';records.append(record);continue
        feature=base._feature(line,f'net2-r6-direct-{len(records)}',role='city_connector' if outside_allowed else 'cross_street',width_m=4.,modes=list(base.MODES),hierarchy=1,net2_strategy=kind,source_road_id=source)
        old_buildings=plan['buildings'];plan['buildings']=remaining;plan['roads'].append(feature)
        validation=base.validate_plan(plan)
        regressions=sorted(k for k in protected_passes if not validation['checks'][k]['passed'])
        if regressions:
            plan['roads'].pop();plan['buildings']=old_buildings;record.update(status='REJECTED_VALIDATOR_REGRESSION',failure_ids=regressions)
        else:record.update(status='ADDED',removed_building_ids=[b['id'] for b in hit])
        records.append(record)
    plan['net2']['direct_link_attempts']=records
    return plan


def repair_round7_links(plan, parent):
    """Withdraw r6 links that consume any unallocated new public ROW.

    Keep only complete ROW already inside BOTH the parent's public land
    allocation and actual road surface on dry site land. Historical r6 output
    remains immutable. Missing source mass is restored, never re-labelled.
    """
    land=shape(parent['site']).difference(shape(parent['water']))
    allocated=unary_union([shape(r['geometry']) for r in parent['land_use']
                          if r['properties']['category'] in ('roads','waterfront')])
    physical=unary_union([shape(r['geometry']).buffer(r['properties']['width_m']/2,cap_style=2,join_style=2)
                         for r in parent['roads']])
    allowed=land.intersection(allocated).intersection(physical)
    kept=[];records=[]
    for road in plan['roads']:
        if not road['id'].startswith('net2-r6-direct-'):
            kept.append(road);continue
        row=shape(road['geometry']).buffer(road['properties']['width_m']/2,cap_style=2,join_style=2)
        outside=row.difference(allowed).area
        retain=outside<=.01
        records.append({'road_id':road['id'],'status':'KEPT_IN_EXISTING_ALLOCATED_ROAD' if retain else 'WITHDRAWN_NEW_ROW_OR_EXTERNAL_ASSUMPTION',
                        'outside_existing_allocated_dry_road_m2':outside,'geometry':road['geometry']})
        if retain:kept.append(road)
    plan['roads']=kept
    ids={b['id'] for b in plan['buildings']};restored=[]
    for b in parent['buildings']:
        if b['id'] not in ids:
            plan['buildings'].append(copy.deepcopy(b));restored.append(b['id'])
    plan['net2']['round7_repair']={'method':'No new public ROW area; full dry-land geometry and existing allocation plus physical-road intersection; .01m2 geometric tolerance',
                                  'links':records,'restored_building_ids':restored}
    return plan
