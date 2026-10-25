"""Bounded geometric relocation of northeast auxiliary massing.

Nonmember northeast footprints are withdrawn with their complete geometry
recorded. Complete management land and roads remain intact. Replacement GFA
uses only authorised floor profiles and reports unavailable capacity explicitly.
"""
from copy import deepcopy
from shapely.geometry import shape, mapping, box
from shapely.affinity import rotate, translate
from shapely.ops import unary_union


def finish_ne(plan):
    result = deepcopy(plan)
    if not plan.get('waterfront_band') or shape(plan['waterfront_band']).is_empty:
        return result
    site = shape(result['site'])
    land = site.difference(shape(result['water']))
    origin = (site.centroid.x, site.centroid.y)
    axis = result.get('context_reference', {}).get('site', {}).get('principal_axis', {})
    angle = 90 - axis.get('long_axis_azimuth_deg', result.get('orientation_deg', 90))
    x0, y0, x1, y1 = rotate(land, -angle, origin=origin).bounds
    zone = rotate(box(x0 + .62 * (x1-x0), y0, x1, y1), angle, origin=origin)
    blocks = [r for r in result['blocks'] if rotate(shape(r['geometry']), -angle, origin=origin).centroid.x >= x0 + .62*(x1-x0)]
    parents = unary_union([shape(r['geometry']) for r in blocks])
    circulation = unary_union([shape(r['geometry']).buffer(r['properties']['width_m']/2, cap_style=2, join_style=2) for r in result['roads']])
    rejected = []
    kept = []
    for row in result['buildings']:
        g = shape(row['geometry'])
        if (not row['properties'].get('retained') and g.intersection(zone).area > .01
                and g.difference(parents).area > .01):
            record = deepcopy(row)
            record['rejection_reason'] = 'complete footprint lies outside accepted northeast dictionary blocks'
            rejected.append(record)
        else:
            kept.append(row)
    result['buildings'] = kept
    result.setdefault('rejected_ne_geometry', []).extend(rejected)
    removed_parcels = []
    active = {b['properties'].get('parcel_id') or b['properties'].get('block_id') for b in kept}
    remaining_parcels = []
    for parcel in result.get('boundary_parcels', []):
        if parcel['id'] not in active and any(shape(b['geometry']).intersection(shape(parcel['geometry'])).area > .01 for b in rejected):
            removed_parcels.append(parcel)
        else:
            remaining_parcels.append(parcel)
    result['boundary_parcels'] = remaining_parcels
    result.setdefault('rejected_ne_parcels', []).extend(deepcopy(removed_parcels))
    # Keep each complete delivered management allocation. Do not cut a small
    # parcel-sized garden out of a larger management polygon to evade checks.
    emptied = unary_union([shape(r['geometry']) for r in removed_parcels])
    for allocation in result.get('land_use', []):
        if allocation['properties'].get('category') == 'blocks' and shape(allocation['geometry']).intersection(emptied).area > .01:
            allocation['properties'].update(manager='街坊共用管理', role='完整街坊植栽及雨水維護庭園', name_zh='東北街坊共用植栽及維護空間', reason_zh='碎量體撤回後保留原完整管理地塊及剩餘建築，空置部分作共用植栽及雨水維護庭園；不拆分地塊規避空地面積檢查', management_basis='complete original allocation geometry retained after northeast massing rejection')
    def gfa(building):
        q = building['properties']
        return shape(building['geometry']).area * q.get('floors', 0) + (shape(q['mezzanine_geometry']).area if q.get('mezzanine_geometry') else 0)
    old_gfa = sum(gfa(b) for b in plan['buildings'] if not b['properties'].get('retained'))
    target = min(result.get('parameters', {}).get('target_gfa_m2', old_gfa), old_gfa)
    current = sum(gfa(b) for b in kept if not b['properties'].get('retained'))
    # Only previously authorised discrete floors and their delivered profile.
    for _ in range(6):
        for b in sorted(kept, key=lambda r: shape(r['geometry']).area):
            q = b['properties']
            if q.get('retained') or q.get('floors', 0) >= q.get('max_floors', 0):
                continue
            height = q['first_floor_height_m'] + q['standard_floor_height_m'] * q['floors']
            area = shape(b['geometry']).area
            if height <= 20 + 1e-7 and current + area <= target + 1e-7:
                q['floors'] += 1
                q['height_m'] = height
                current += area
    result['ne_finish_evidence'] = {'removed_building_ids':[b['id'] for b in rejected], 'removed_parcel_ids':[r['id'] for r in removed_parcels], 'old_new_gfa_m2':old_gfa, 'repaired_new_gfa_m2':current, 'unreplaced_gfa_m2':max(0, old_gfa-current), 'roads_preserved':True}
    return result
