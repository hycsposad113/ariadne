"""Authored geometric road proximity; not verified entrance/fire-route access."""
from shapely.geometry import shape
from shapely.ops import unary_union

ROAD_ACCESS_RULE_M = 40.0
ROAD_ACCESS_PROVENANCE = 'ASSUMED_COMMANDER'
ROAD_ACCESS_BASIS = 'Commander assumption inspired by Bouwbesluit 2012 fire-brigade entrance distance; footprint proximity proxy, not legal compliance'


def road_surface(edges):
    """Include each centreline's own half-width, including round end caps."""
    return unary_union([shape(e.geometry.model_dump()).buffer(e.width_m / 2) for e in edges])


def footprint_access_distance(footprint, roads):
    """Worst component proximity: every detached point-array member must pass."""
    parts = footprint.geoms if footprint.geom_type == 'MultiPolygon' else (footprint,)
    return max(part.distance(roads) for part in parts) if not roads.is_empty else float('inf')


def road_access_metrics(footprints, roads, rule_m=ROAD_ACCESS_RULE_M):
    distances = [footprint_access_distance(g, roads) for g in footprints]
    # Missing roads are a generation error, never serialise Infinity as a metric.
    if roads.is_empty:
        raise ValueError('road access cannot be measured: skeleton has no roads')
    return dict(accessible_count=sum(d <= rule_m for d in distances),
                total_new_buildings=len(distances), max_distance_m=max(distances, default=0.),
                rule_m=rule_m, provenance=ROAD_ACCESS_PROVENANCE)


ACCESS_LANE_WIDTH_M = 4.5


def aligned_access_paths(footprints, edges, *, angle, site, obstacles, width_m=ACCESS_LANE_WIDTH_M, first_only=False, halo_m=35.):
    """Shortest unobstructed axis-aligned one-bend options to placed footprints.

    Work in scheme coordinates. Edge intersections at the target's x/y provide
    exact mid-edge attachments; G2 subsequently nodes them on its 1 um grid.
    End at the nearest footprint-facing point of its 35 m buffer, leaving a
    margin below the 40 m rule after noding. No free-form obstacle detours.
    """
    from shapely import affinity
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points
    local_edges = [affinity.rotate(shape(e.geometry.model_dump()), -angle, origin=(0,0)) for e in edges]
    local_site = affinity.rotate(site, -angle, origin=(0,0))
    local_obstacles = affinity.rotate(obstacles, -angle, origin=(0,0))
    roads = road_surface(edges)
    safe=local_site.buffer(-(width_m/2+.25)).difference(local_obstacles.buffer(width_m/2+.250001))
    from shapely.prepared import prep
    prepared_safe=prep(safe)
    options = []
    for footprint in footprints:
        if footprint_access_distance(footprint, roads) <= ROAD_ACCESS_RULE_M:
            continue
        parts = footprint.geoms if footprint.geom_type == 'MultiPolygon' else (footprint,)
        for part in parts:
            if part.distance(roads) <= ROAD_ACCESS_RULE_M:
                continue
            part_options = []
            local_part=affinity.rotate(part, -angle, origin=(0,0))
            minx,miny,maxx,maxy=local_part.bounds
            targets=[local_part.representative_point(),local_part.centroid,
                     Point(minx,miny),Point(minx,maxy),Point(maxx,miny),Point(maxx,maxy)]
            halo=local_part.buffer(halo_m)
            boundary=list(halo.exterior.coords)
            if not first_only: targets.extend(Point(c) for c in boundary[::max(1,len(boundary)//16)])
            reachable_halo=halo.intersection(safe)
            if reachable_halo.is_empty: continue
            for region in (reachable_halo.geoms if hasattr(reachable_halo,'geoms') else (reachable_halo,)):
                if region.geom_type!='Polygon': continue
                targets.append(region.representative_point())
                boundary=list(region.exterior.coords)
                if not first_only: targets.extend(Point(c) for c in boundary[::max(1,len(boundary)//16)])
            targets.extend(nearest_points(edge,reachable_halo)[1] for edge in local_edges)
            targets=list({(round(p.x,6),round(p.y,6)):p for p in targets}.values())
            for target in targets:
                starts = []
                for edge in local_edges:
                    starts.extend(Point(c) for c in (edge.coords[0], edge.coords[-1]))
                    starts.append(nearest_points(edge, target)[0])
                    for axis in (LineString([(target.x,local_site.bounds[1]-1),(target.x,local_site.bounds[3]+1)]),
                                 LineString([(local_site.bounds[0]-1,target.y),(local_site.bounds[2]+1,target.y)])):
                        crossing = edge.intersection(axis)
                        if crossing.geom_type == 'Point': starts.append(crossing)
                        elif crossing.geom_type == 'MultiPoint': starts.extend(crossing.geoms)
                destination = halo
                starts=list({(round(p.x,6),round(p.y,6)):p for p in starts}.values())
                for start in starts:
                    for bend in ((target.x,start.y),(start.x,target.y)):
                        coords = [start.coords[0], bend, target.coords[0]]
                        coords = [c for i,c in enumerate(coords) if i == 0 or c != coords[i-1]]
                        if len(coords)<2: continue
                        distance=sum(abs(a[0]-b[0])+abs(a[1]-b[1]) for a,b in zip(coords,coords[1:]))
                        if len(part_options)>=5 and distance-(maxx-minx+maxy-miny+4*halo_m)>part_options[-1].length: continue
                        full = LineString(coords)
                        # Keep only the prefix up to the first entry into the access halo.
                        from shapely.ops import substring
                        hit = full.intersection(destination)
                        if hit.is_empty: continue
                        entry = min(full.project(Point(c)) for g in (hit.geoms if hasattr(hit,'geoms') else (hit,))
                                    for c in (list(g.coords) if hasattr(g,'coords') else []))
                        if entry < 1e-4: continue
                        path = substring(full, 0, entry)
                        if not prepared_safe.covers(path): continue
                        world = affinity.rotate(path, angle, origin=(0,0))
                        if first_only: return [world]
                        part_options.append(world)
                        part_options=sorted({p.wkb_hex:p for p in part_options}.values(),key=lambda p:(p.length,p.wkb_hex))[:5]
            options.extend(sorted(part_options,key=lambda p:(p.length,p.wkb_hex))[:5])
    unique = {p.wkb_hex:p for p in options}
    return sorted(unique.values(), key=lambda p:(p.length,p.wkb_hex))


def rebuild_access_skeleton(context, strategy, inputs, base, lanes):
    """Preserve original widths; G2 nodes mid-edge lane attachments cleanly."""
    from .skeleton import _RoadPath, _artifact
    local = context.method_parameters['road_local_width_m']
    paths = []
    for edge in base.edges:
        parameter = 'road_local_width_m' if edge.width_m == local else 'road_collector_width_m'
        identifier = getattr(edge, 'id', '').split(':')
        road_class = identifier[1].upper() if len(identifier) == 3 and identifier[0] == 'road' else ('LOCAL' if edge.width_m == local else 'CONNECTOR')
        paths.append(_RoadPath(shape(edge.geometry.model_dump()), road_class, parameter))
    paths.extend(_RoadPath(p, 'ACCESS_LANE', 'access_lane_width_m') for p in lanes)
    # Explicitly insert attachment vertices before fixed-precision union. A
    # rounded mid-edge point can otherwise sit just off a diagonal base edge.
    # Displacement is bounded by the existing 1 um endpoint/hash tolerance.
    from shapely.geometry import Point, LineString
    endpoints=[Point(c) for path in paths for c in (path.geometry.coords[0],path.geometry.coords[-1])]
    split=[]
    for path in paths:
        line=path.geometry
        marks=[(line.project(Point(c)),c) for c in line.coords]
        for point in endpoints:
            at=line.project(point)
            if point.distance(line)<=1e-6 and 1e-6<at<line.length-1e-6:
                marks.append((at,point.coords[0]))
        marks.sort(key=lambda item:(item[0],item[1]))
        coords=[]
        for _,coord in marks:
            if not coords or Point(coords[-1]).distance(Point(coord))>1e-6:
                coords.append(coord)
        split.append(_RoadPath(LineString(coords),path.road_class,path.width_parameter))
    paths=split
    return _artifact(context, strategy, inputs, paths,
                     tuple(shape(g.geometry.model_dump()) for g in base.primary_open_spaces),
                     timestamp=base.created_at,local_width_m=local,
                     collector_width_m=context.method_parameters['road_collector_width_m']).artifact


def prune_access_lanes(base_edges, lanes, footprints, *, validate=None):
    """Reverse-delete lanes that add no final-building accessibility."""
    from types import SimpleNamespace
    from shapely.geometry import mapping
    kept = list(lanes)
    for lane in reversed(lanes):
        trial = [p for p in kept if p is not lane]
        extra = [SimpleNamespace(geometry=SimpleNamespace(model_dump=lambda p=p: mapping(p)),width_m=ACCESS_LANE_WIDTH_M) for p in trial]
        roads = road_surface([*base_edges,*extra])
        if all(footprint_access_distance(g,roads)<=ROAD_ACCESS_RULE_M for g in footprints):
            if validate is not None:
                try:
                    validate(trial)
                except ValueError:
                    continue
            kept = trial
    return kept
