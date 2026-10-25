"""Block-scaled S6 operators, using existing dictionary IDs; DRAFT assumptions.

No legacy preview geometry is changed. Dimensions are envelope measurements,
not usable internal clear dimensions or a building-code compliance assertion.
"""
from dataclasses import dataclass
import math
from shapely import affinity
from shapely.geometry import Polygon, box
from shapely.geometry.base import BaseGeometry

VERSION = 'j12-block-scale-v1'


@dataclass(frozen=True)
class BlockProfile:
    type_id: str
    geometry: BaseGeometry
    wing_depth_m: float
    courtyard_width_m: float | None = None
    unit_frontage_m: float | None = None
    unit_count: int | None = None
    podium_floors: int | None = None


def rectangular_size(geometry):
    c=geometry.centroid
    local=affinity.translate(geometry,-c.x,-c.y)
    ring = list(local.minimum_rotated_rectangle.exterior.coords)
    lengths = [math.dist(a, b) for a, b in zip(ring, ring[1:])]
    return min(lengths), max(lengths)


def convex_clear_width(geometry):
    """Minimum support-line distance, independent of a rotated bounding box."""
    c=geometry.centroid;g=affinity.translate(geometry,-c.x,-c.y)
    cs=list(g.convex_hull.exterior.coords);widths=[]
    for a,b in zip(cs,cs[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        projections=[(-dy*x+dx*y)/length for x,y in cs]
        widths.append(max(projections)-min(projections))
    return min(widths)


def streetwall_profile(block,*,wing_depth_m,setback_m=1):
    """Perimeter follows actual street-block boundary, minus explicit setback.

    Reject holes/multiple or nonconvex courtyards rather than hiding a narrow
    irregular court behind its bounding-box dimensions.
    """
    outer=block.buffer(-setback_m,join_style=2)
    if not isinstance(outer,Polygon) or outer.is_empty or outer.interiors:
        raise ValueError('single street block without internal obstacles required')
    inner=outer.buffer(-wing_depth_m,join_style=2)
    if not isinstance(inner,Polygon) or inner.is_empty or inner.interiors:
        raise ValueError('no complete courtyard fits street block')
    if inner.symmetric_difference(inner.convex_hull).area>1e-5 or convex_clear_width(inner)<20-1e-6:
        raise ValueError('courtyard clear width below20m or irregular unverified neck')
    if convex_clear_width(outer)<40-1e-6:raise ValueError('street block width below40m')
    return BlockProfile('block.perimeter',outer.difference(inner),wing_depth_m,convex_clear_width(inner))


def block_profile(type_id, envelope, *, wing_depth_m):
    """A complete contained envelope, never a clipped or shrunken thin template."""
    if not isinstance(envelope, Polygon) or envelope.is_empty or not envelope.is_valid or envelope.interiors:
        raise ValueError('complete rectangular envelope required')
    c=envelope.centroid
    centered=affinity.translate(envelope,-c.x,-c.y)
    rectangle = centered.minimum_rotated_rectangle
    if rectangle.symmetric_difference(centered).area > 1e-5:
        raise ValueError('complete rectangular envelope required')
    a, b = list(rectangle.exterior.coords)[:2]
    angle = math.degrees(math.atan2(b[1]-a[1], b[0]-a[0]))
    local = affinity.rotate(rectangle, -angle, origin=(0, 0))
    x0, y0, x1, y1 = local.bounds
    width, depth = x1-x0, y1-y0
    short, long = min(width, depth), max(width, depth)
    if not math.isfinite(wing_depth_m) or wing_depth_m <= 0:
        raise ValueError('positive finite wing depth required')
    courtyard = None; frontage = None; count = None; podium = None
    if type_id in ('block.perimeter', 'building.courtyard_closed'):
        courtyard = short - 2*wing_depth_m
        if short < 40 or courtyard < 20-1e-7:
            raise ValueError('courtyard envelope >=40m and clear courtyard >=20m required')
        geom = local.difference(box(x0+wing_depth_m,y0+wing_depth_m,x1-wing_depth_m,y1-wing_depth_m))
    elif type_id == 'building.l_block':
        if short < 2*wing_depth_m:
            raise ValueError('L envelope too small')
        geom = local.difference(box(x0+wing_depth_m,y0+wing_depth_m,x1+1,y1+1))
    elif type_id in ('building.i_slab', 'building.rowhouse', 'building.industrial_hall'):
        if abs(short-wing_depth_m)>1e-5:
            raise ValueError('bar depth must match envelope short dimension')
        geom = local
        if type_id == 'building.rowhouse':
            counts = [n for n in range(6,21) if 5.4 <= long/n <= 7.2]
            if not counts: raise ValueError('rowhouse requires 6-20 units at 5.4-7.2m frontage')
            count = min(counts, key=lambda n: abs(long/n-6.3)); frontage = long/count
    elif type_id in ('building.point_tower', 'building.podium_tower'):
        geom = local
        if type_id == 'building.podium_tower': podium = 2
    else:
        raise ValueError('no block-scaled operator for '+type_id)
    world = affinity.translate(affinity.rotate(geom,angle,origin=(0,0)),c.x,c.y)
    return BlockProfile(type_id,world,wing_depth_m,courtyard,frontage,count,podium)


def fit_envelopes(block, *, depth_m=None, max_length_m=100, min_length_m=30, accept=None):
    """Find large rectangles next to block boundaries, no plot-grid replication.

    Candidate axes come from the block's edges. For bars, fixed depth is never
    scaled down. For courts, both dimensions must leave a >=20m void.
    """
    if block.is_empty or not isinstance(block, Polygon): return []
    c=block.centroid
    centered=affinity.translate(block,-c.x,-c.y)
    coords=list(centered.minimum_rotated_rectangle.exterior.coords)
    angle=math.degrees(math.atan2(coords[1][1]-coords[0][1],coords[1][0]-coords[0][0]))
    angles=sorted({round(angle%180,6),round((angle+90)%180,6)})
    candidates=[]
    for theta in angles:
        local=affinity.rotate(centered,-theta,origin=(0,0))
        x0,y0,x1,y1=local.bounds
        if depth_m is None:
            dimensions=[(w,h) for w in range(44,int(min(x1-x0,max_length_m))+1,4)
                        for h in range(44,int(min(y1-y0,max_length_m))+1,4)]
        else:
            dimensions=[(float(w),depth_m) for w in range(min_length_m,int(min(x1-x0,max_length_m))+1,2)]
        # Discrete offsets are a placement search, never repeated buildings.
        for w,h in sorted(dimensions,key=lambda d:-d[0]*d[1]):
            if h>y1-y0+1e-7: continue
            for fx in (0,.25,.5,.75,1):
                for fy in (0,.25,.5,.75,1):
                    x=x0+fx*(x1-x0-w);y=y0+fy*(y1-y0-h)
                    raw=box(x,y,x+w,y+h)
                    if local.buffer(1e-8).covers(raw):
                        world=affinity.translate(affinity.rotate(raw,theta,origin=(0,0)),c.x,c.y)
                        if block.covers(world) and (accept is None or accept(world)): candidates.append(world)
            if candidates and depth_m is not None: break
            if len(candidates)>=12: break
    return sorted(candidates,key=lambda g:(-g.area,g.wkb_hex))[:12]
