"""Deterministic complete-envelope packing and preference-led floor programme."""
import math
from collections import defaultdict, deque
from shapely import affinity
from shapely.geometry import box, shape
from urban_design.generation.block_program import geometry_value
from urban_design.generation.contracts import ProgramBlock, ProgramZone, ProgramAllocation, FixtureDictionaryRecipe, FrozenRef
from urban_design.generation.hashing import semantic_digest
from urban_design.generation.legacy_profile_adapter import generate_legacy_profile

TYPES = ('building.courtyard_closed', 'building.l_block', 'building.i_slab', 'building.point_array')
from .road_access import ROAD_ACCESS_RULE_M, road_surface, footprint_access_distance

VERSION = 'formal-envelope-program-v5-required-types'


def place_program(blocks, *, angle, zones, recipe_id, seed, target_gfa_m2, floor_count=5, road_edges, road_access_rule_m=ROAD_ACCESS_RULE_M, minimum_types=4, preferred_cells=(), profile_filter=None, road_distance=None):
    """Round-robin five zone preferences before filling remaining capacity.

    Uncovered cells inherit the nearest approved preference, explicitly labelled
    ASSUMED_FROM_PORTFOLIO. This proposes uses; it does not change zone geometry.
    Profiles and budgets are measured before selection; partial profiles are not
    scaled or clipped to force the target.
    """
    preferred_cells=set(preferred_cells)
    zone_shapes = [(z, shape(z['geometry'])) for z in zones]
    if not zone_shapes:
        raise ValueError('BLOCKED: no approved zone preferences')
    available = defaultdict(list)
    profile_areas = {}
    profiles = {}
    roads = road_surface(road_edges)
    for block in blocks.blocks:
        geometry = shape(block.geometry.model_dump())
        local = affinity.rotate(geometry, -angle, origin=(0, 0))
        minx, miny, maxx, maxy = local.bounds
        for width, depth, pitch, types in ((56.,56.,8.,('building.point_array',)),(40.,40.,8.,('building.courtyard_closed',)),(32.,32.,8.,('building.l_block',)),(40.,24.,8.,('building.i_slab',))):
            for x in range(math.ceil(minx/pitch), math.floor(maxx/pitch)+1):
                for y in range(math.ceil(miny/pitch), math.floor(maxy/pitch)+1):
                    raw = box(x*pitch-width/2, y*pitch-depth/2, x*pitch+width/2, y*pitch+depth/2)
                    cell = affinity.rotate(raw, angle, origin=(0, 0))
                    if not geometry.covers(cell):
                        continue
                    matching = [(z, g) for z, g in zone_shapes if g.covers(cell.centroid)]
                    z, _ = matching[0] if matching else min(zone_shapes, key=lambda zg: (zg[1].distance(cell.centroid), zg[0]['zone_id']))
                    type_id = types[(x+y+seed) % len(types)]
                    if type_id not in profile_areas:
                        profiles[type_id] = generate_legacy_profile(type_id, box(-width/2,-depth/2,width/2,depth/2), {'rotation_deg':0}, crs='EPSG:28992', coordinate_unit='m').geometry
                        profile_areas[type_id] = profiles[type_id].area
                    profile = affinity.translate(affinity.rotate(profiles[type_id], angle, origin=(0, 0)), cell.centroid.x, cell.centroid.y)
                    distance=road_distance(profile) if road_distance is not None else footprint_access_distance(profile, roads)
                    if distance > road_access_rule_m:
                        continue
                    if profile_filter is not None and not profile_filter(profile,cell,z,distance):
                        continue
                    available[z['zone_id']].append((cell, z, type_id, profile_areas[type_id]*floor_count, bool(matching),distance,raw.bounds))
    # Compare deterministic accessible reselections before requesting roads.
    # All envelopes share an angle, so overlap is measured exactly in their
    # local rectangular frame (rotation preserves area).
    selection_zones=sorted(zone_shapes,key=lambda zg:(len(available[zg[0]['zone_id']]),zg[0]['zone_id']))
    best=None
    for sx,sy in ((1,1),(-1,1),(1,-1),(-1,-1)):
        queues={key:deque(sorted(values,key=lambda v:(v[0].wkb_hex not in preferred_cells,v[5] if road_access_rule_m>ROAD_ACCESS_RULE_M else 0,
                    -v[3]/v[0].area,sx*v[6][0],sy*v[6][1],TYPES.index(v[2])))) for key,values in available.items()}
        selected=[]; occupied=[]; total=0.; selected_types=set()
        while any(queues.values()):
            progressed=False
            for z, _ in selection_zones:
                queue=queues[z['zone_id']]
                if len(selected_types)<minimum_types:
                    # Required type coverage precedes trial preferences. A
                    # preferred slab must not consume the budget repeatedly
                    # before a missing courtyard or point array is selected.
                    queue=deque(sorted(queue,key=lambda v:(v[2] in selected_types,v[0].wkb_hex not in preferred_cells,TYPES.index(v[2]))))
                    queues[z['zone_id']]=queue
                while queue:
                    item=queue.popleft(); cell, _, type_id, gfa, _, _, bounds=item
                    if total+gfa>target_gfa_m2+1e-6:
                        continue
                    if any(max(0,min(bounds[2],b[2])-max(bounds[0],b[0]))*
                           max(0,min(bounds[3],b[3])-max(bounds[1],b[1]))>1e-6 for b in occupied):
                        continue
                    selected.append(item); selected_types.add(type_id); occupied.append(bounds); total+=gfa; progressed=True
                    break
            if not progressed: break
        rank=(len({v[1]['zone_id'] for v in selected}),min(len(selected_types),minimum_types),total)
        if best is None or rank>best[0]: best=(rank,selected)
    selected=best[1]
    if not selected:
        raise ValueError('no complete road-accessible dictionary envelopes fit G2 blocks')
    result=[]; programs=[]; allocations=[]; recipes={}; assignments={}
    for i,(cell,z,type_id,gfa,direct,_,_) in enumerate(selected):
        id=f'{recipe_id}-cell-{i}'
        use=z['target_use']
        result.append(ProgramBlock(id=id,geometry=geometry_value(cell)))
        programs.append(ProgramZone(id=id,geometry=geometry_value(cell),use=use))
        allocations.append(ProgramAllocation(zone_id=id,use=use,area_m2=cell.area,source_refs=blocks.input_refs))
        # Portfolio proportions are reference preferences, not enforceable rules.
        lower=use.casefold()
        if 'residential' in lower:
            floor_uses=('Facilities',)+tuple('Residential' for _ in range(floor_count-1))
        elif 'maker' in lower or 'recycle' in lower:
            floor_uses=tuple('Manufacturing / Recycle' for _ in range(floor_count-1))+('Office',)
        elif 'energy' in lower:
            floor_uses=tuple('Energy Hub' for _ in range(floor_count-1))+('Office',)
        else:
            floor_uses=tuple('Art / Recreation' for _ in range(floor_count-1))+('Facilities',)
        spec=dict(type_id=type_id,geometry_parameters={'rotation_deg':angle},floor_uses=floor_uses)
        recipes[id]=FixtureDictionaryRecipe(recipe_id=recipe_id,version=VERSION,source_ref=FrozenRef(id=id+'-recipe',sha256=semantic_digest(spec),kind='AUTHORED_RECIPE'),**spec)
        assignments[id]=dict(zone_id=z['zone_id'],preferred_use=use,allocation_basis='APPROVED_ZONE' if direct else 'ASSUMED_FROM_PORTFOLIO_NEAREST_ZONE',new_gfa_m2=gfa)
    artifact=blocks.model_copy(update={'blocks':tuple(result),'zones':tuple(programs),'program_allocations':tuple(allocations),'algorithm_version':VERSION})
    return artifact, recipes, assignments
