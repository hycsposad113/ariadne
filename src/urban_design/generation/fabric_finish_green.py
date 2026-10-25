"""Geometry-only green-space finishing; no validator or road mutations."""
from __future__ import annotations

import copy
import math
from shapely.geometry import shape, mapping, LineString, Polygon
from shapely.ops import unary_union, split


def _parts(geometry):
    return list(geometry.geoms) if hasattr(geometry, 'geoms') else [geometry]


def _useful(geometry):
    cores = [p for p in _parts(geometry.buffer(-7.5, join_style=2))
             if p.geom_type == 'Polygon' and p.area > 1e-6]
    return geometry.geom_type == 'Polygon' and geometry.is_valid and geometry.area >= 1000 and len(cores) == 1


def finish_green(plan: dict) -> dict:
    """Return a copy with whole empty plots absorbed and road-defined park units.

    A park containing multiple useful cores is divided only by the extended
    alignment of an existing public road. Each resulting complete unit must
    independently satisfy the original area/core rule. The dissolved green
    footprint, roads, buildings and allocation coverage remain unchanged.
    """
    result = copy.deepcopy(plan)
    if result['fabric_id'] != 'fabric.landscape_figure':
        return result
    allocations = result['land_use']
    mass = unary_union([shape(row['geometry']) for row in result['buildings']])
    land = shape(result['site']).difference(shape(result['water']))
    records = []
    parks = [row for row in allocations if row['properties']['category'] == 'parks']
    park_area = sum(shape(row['geometry']).area for row in parks)
    removed = []
    # Whole connected empty allocations are eligible; never split occupied
    # management plots or rename arbitrary residual land to bypass the gate.
    for row in allocations:
        if row['properties']['category'] not in {'blocks', 'public_facilities', 'service'}:
            continue
        geometry = shape(row['geometry'])
        if geometry.geom_type != 'Polygon' or geometry.area <= 2000 or geometry.intersection(mass).area >= .01:
            continue
        if (park_area + geometry.area) / land.area > .25:
            continue
        for park in parks:
            old = shape(park['geometry'])
            if old.boundary.intersection(geometry.boundary).length <= .01:
                continue
            merged = old.union(geometry)
            if merged.geom_type != 'Polygon' or not merged.is_valid:
                continue
            park['geometry'] = mapping(merged)
            park['properties'].setdefault('absorbed_allocation_ids', []).append(row['id'])
            park['properties']['reason_zh'] = '依實際共界將完整未建管理地塊納入鄰里公園，保持全塊幾何與單一公共管理。'
            records.append({'action': 'absorb_complete_empty_plot', 'allocation_id': row['id'], 'park_id': park['id'], 'area_m2': geometry.area})
            removed.append(row)
            park_area += geometry.area
            break
    allocations[:] = [row for row in allocations if row not in removed]
    internal = {'courtyard_fire_lane', 'courtyard_service_gate', 'facade_service_spur', 'retained_service_lane', 'boundary_plot_service_lane', 'park_maintenance_path', 'south_quay_shared_alley'}
    additions = []
    for park in parks:
        geometry = shape(park['geometry'])
        if _useful(geometry):
            continue
        for road in result['roads']:
            properties = road['properties']
            line = shape(road['geometry'])
            if properties['role'] in internal or line.geom_type != 'LineString' or len(line.coords) != 2:
                continue
            a, b = line.coords
            dx, dy = b[0]-a[0], b[1]-a[1]
            length = math.hypot(dx, dy)
            if length == 0:
                continue
            # The road must actually cross the park's bounds, not an arbitrary
            # geometric alignment chosen solely to separate erosion islands.
            row = line.buffer(properties['width_m']/2, cap_style=2, join_style=2)
            if geometry.boundary.intersection(row).length <= .01:
                continue
            extension = max(land.bounds[2]-land.bounds[0], land.bounds[3]-land.bounds[1])*2/length
            divider = LineString([(a[0]-dx*extension,a[1]-dy*extension), (b[0]+dx*extension,b[1]+dy*extension)])
            pieces = [g for g in split(geometry, divider).geoms if g.area > .01]
            if len(pieces) < 2 or not all(_useful(g) for g in pieces):
                continue
            pieces.sort(key=lambda g: (-g.area, g.centroid.x, g.centroid.y))
            original_id = park['id']
            for index, piece in enumerate(pieces):
                target = park if index == 0 else copy.deepcopy(park)
                ident = original_id if index == 0 else f'{original_id}-road-unit-{index}'
                target['id'] = ident
                target['geometry'] = mapping(piece)
                target['properties'].update(id=ident, role='完整管理公園單元', manager='公共空間管理', name_zh=f'港灣綠軸道路分界鄰里公園 {ident}', reason_zh='依既有真實公共道路及其延伸管理界線分為完整公園單元；保留原連續綠地及正式道路跨越。', management_boundary_road_id=road['id'])
                if index:
                    additions.append(target)
            records.append({'action':'road_defined_complete_park_units', 'source_park_id':original_id, 'road_id':road['id'], 'unit_areas_m2':[g.area for g in pieces], 'dissolved_difference_m2':unary_union(pieces).symmetric_difference(geometry).area})
            break
    allocations.extend(additions)
    result['green_finish_evidence'] = records
    return result
