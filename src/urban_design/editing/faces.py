"""Floor-aligned, fixture-only face editing; production semantics remain BLOCKED.

Faces use metres in a local planar coordinate system. Side u follows a footprint
edge and v is elevation above the selected storey base. No geometry is repaired.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Literal

from shapely.geometry import LineString, Polygon
from shapely.ops import split, triangulate, unary_union

from urban_design.editing.floors import BuildingMassing, FloorStorey


class FaceEditError(ValueError):
    """Rejected geometry operation, safe to expose as a machine-readable 422."""

    def __init__(self, message: str, *, code: str = "FACE_EDIT_REJECTED"):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Face:
    id: str
    floor_id: str
    kind: Literal['SIDE', 'TOP']
    geometry: Polygon
    edge_index: int | None = None


@dataclass(frozen=True)
class FaceRevision:
    revision_id: int
    parent_revision_id: int | None
    building: BuildingMassing
    faces: tuple[Face, ...]
    lineage: tuple[tuple[str, tuple[str, ...]], ...] = ()
    provenance: Literal['FIXTURE_ONLY'] = 'FIXTURE_ONLY'
    production_status: Literal['BLOCKED'] = 'BLOCKED'
    semantic_option: Literal['NEW_USABLE_FLOORS_PROTOTYPE'] = 'NEW_USABLE_FLOORS_PROTOTYPE'


def _polygon(p: Polygon) -> None:
    if not isinstance(p, Polygon) or p.is_empty or not p.is_valid or p.area <= 0:
        raise FaceEditError('invalid/self-intersecting/nonmanifold polygon')
    if p.has_z or any(not math.isfinite(v) for ring in (p.exterior, *p.interiors) for xy in ring.coords for v in xy):
        raise FaceEditError('only finite planar coordinates are supported')


def _building(b: BuildingMassing) -> None:
    if b.provenance != 'FIXTURE_ONLY' or not b.floors:
        raise FaceEditError('only nonempty FIXTURE_ONLY stacks are supported')
    if any(isinstance(f.level, bool) or not isinstance(f.level, int) or not isinstance(f.id, str) or not f.id.strip() for f in b.floors):
        raise FaceEditError('integer levels and nonempty floor IDs required')
    floors = sorted(b.floors, key=lambda f: f.level)
    if [f.level for f in floors] != list(range(len(floors))):
        raise FaceEditError('storeys must be contiguous from level zero')
    if len({f.id for f in floors}) != len(floors):
        raise FaceEditError('duplicate floor IDs')
    for height in (b.first_floor_height_m, b.standard_floor_height_m):
        if isinstance(height, bool) or not isinstance(height, (int, float)) or not math.isfinite(height) or height <= 0:
            raise FaceEditError('positive finite storey heights required')
    for f in floors:
        _polygon(f.geometry)
    for lower, upper in zip(floors, floors[1:]):
        if not _covers_within_rounding(lower.geometry, upper.geometry):
            raise FaceEditError('unsupported cantilever/nonmanifold stack')


def _covers_within_rounding(lower: Polygon, upper: Polygon) -> bool:
    """Exact cover, or an uncovered area no larger than coordinate float rounding.

    Rotated/split plates at RD New coordinates can sit a few ulps outside the plate
    below. Same bound as the partition check; geometry is never snapped or repaired.
    """
    if lower.covers(upper):
        return True
    scale = max(1.0, *(abs(value) for value in upper.bounds))
    return upper.difference(lower).area <= 32 * math.ulp(scale) * upper.length


def _faces(b: BuildingMassing, revision: int) -> tuple[Face, ...]:
    result = []
    for f in sorted(b.floors, key=lambda f: f.level):
        height = b.first_floor_height_m if f.level == 0 else b.standard_floor_height_m
        coords = list(f.geometry.exterior.coords)
        for index, (a, c) in enumerate(zip(coords, coords[1:])):
            length = math.dist(a, c)
            result.append(Face(f'r{revision}:{f.id}:side:{index}', f.id, 'SIDE', Polygon([(0, 0), (length, 0), (length, height), (0, height)]), index))
        if f.level == len(b.floors) - 1:
            result.append(Face(f'r{revision}:{f.id}:top', f.id, 'TOP', f.geometry))
    return tuple(result)


def fixture_quantities(b: BuildingMassing) -> tuple[float, float]:
    """Return GFA m² and floor-stack volume m³, without approval claims."""
    _building(b)
    return (math.fsum(f.geometry.area for f in b.floors), math.fsum(f.geometry.area * (b.first_floor_height_m if f.level == 0 else b.standard_floor_height_m) for f in b.floors))


class FaceEditHistory:
    def __init__(self, initial: BuildingMassing):
        _building(initial)
        self._revisions = [FaceRevision(0, None, initial, _faces(initial, 0))]
        self.active_revision_id = 0
        self.baseline_geometry_hash = initial.geometry_hash()

    @property
    def active(self) -> FaceRevision:
        return self._revisions[self.active_revision_id]

    @property
    def revisions(self) -> tuple[FaceRevision, ...]:
        return tuple(self._revisions)

    def _target(self, face_id: str, expected_revision: int) -> Face:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision != self.active_revision_id:
            raise FaceEditError('stale parent revision')
        matches = [f for f in self.active.faces if f.id == face_id]
        if len(matches) != 1:
            raise FaceEditError('unknown/stale semantic face ID')
        return matches[0]

    def _record(self, b: BuildingMassing, faces: tuple[Face, ...], lineage: tuple[tuple[str, tuple[str, ...]], ...]) -> FaceRevision:
        _building(b)
        r = FaceRevision(len(self._revisions), self.active_revision_id, b, faces, lineage)
        self._revisions.append(r)
        self.active_revision_id = r.revision_id
        return r

    def subdivide(self, face_id: str, *, expected_revision: int, cutter: LineString | Polygon) -> FaceRevision:
        face = self._target(face_id, expected_revision)
        _polygon(face.geometry)
        if isinstance(cutter, LineString):
            if cutter.is_empty or not cutter.is_simple or cutter.has_z or any(not math.isfinite(v) for xy in cutter.coords for v in xy):
                raise FaceEditError('invalid cutting line')
            parts = list(split(face.geometry, cutter).geoms)
        elif isinstance(cutter, Polygon):
            _polygon(cutter)
            if not face.geometry.contains(cutter) or face.geometry.boundary.intersects(cutter.boundary):
                raise FaceEditError('closed contour must lie strictly inside face')
            remainder = face.geometry.difference(cutter)
            # Explicit planar partition into triangles: no buffer/repair and no holes.
            parts = [cutter]
            for triangle in triangulate(remainder):
                clipped = triangle.intersection(remainder)
                parts.extend([clipped] if isinstance(clipped, Polygon) else [g for g in clipped.geoms if isinstance(g, Polygon)])
        else:
            raise FaceEditError('typed line or closed polygon required')
        if len(parts) < 2:
            raise FaceEditError('cutter did not subdivide face')
        for part in parts:
            _polygon(part)
        combined = unary_union(parts)
        # GEOS intersections can round rotated/projected coordinates by a few
        # floating-point units. Bound that numerical area error by coordinate
        # precision and perimeter; never repair or snap the partition geometry.
        scale = max(1.0, *(abs(value) for value in face.geometry.bounds))
        area_tolerance = 32 * math.ulp(scale) * face.geometry.length
        if (combined.symmetric_difference(face.geometry).area > area_tolerance
                or abs(sum(p.area for p in parts) - combined.area) > area_tolerance):
            raise FaceEditError('partition must cover face exactly without overlap')
        revision = len(self._revisions)
        children = tuple(replace(face, id=f'r{revision}:{face.id}:part:{i}', geometry=p) for i, p in enumerate(parts))
        remaining = tuple(f for f in self.active.faces if f.id != face_id)
        return self._record(self.active.building, remaining + children, ((face_id, tuple(f.id for f in children)),))

    def _geometry_record(self, edited: BuildingMassing) -> FaceRevision:
        """Preserve unaffected partitions; empty successors explicitly invalidate.

        Changed surfaces require reselection. No all-to-all side correspondence
        is claimed when footprint topology changes.
        """
        previous = self.active
        old_floors = {f.id: f for f in previous.building.floors}
        new_floors = {f.id: f for f in edited.floors}
        changed = {fid for fid, f in old_floors.items() if fid not in new_floors or f.geometry.wkb != new_floors[fid].geometry.wkb}
        old_top = max(previous.building.floors, key=lambda f: f.level).id
        new_top = max(edited.floors, key=lambda f: f.level).id
        preserved = tuple(f for f in previous.faces if f.floor_id not in changed and (f.kind != 'TOP' or old_top == new_top))
        preserved_keys = {(f.floor_id, f.kind) for f in preserved}
        generated = tuple(f for f in _faces(edited, len(self._revisions)) if (f.floor_id, f.kind) not in preserved_keys)
        preserved_ids = {f.id for f in preserved}
        lineage = tuple((f.id, (f.id,) if f.id in preserved_ids else ()) for f in previous.faces)
        return self._record(edited, preserved + generated, lineage)

    def extrude(self, face_id: str, *, expected_revision: int, steps: int, semantic_option: str) -> FaceRevision:
        face = self._target(face_id, expected_revision)
        if semantic_option != 'NEW_USABLE_FLOORS_PROTOTYPE':
            raise FaceEditError('Founder floor semantics unresolved: production BLOCKED')
        if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
            raise FaceEditError('positive integer metre/storey steps required')
        b = self.active.building
        floor = b.floor(face.floor_id)
        if face.kind == 'TOP':
            floors = b.floors + tuple(FloorStorey(f'r{len(self._revisions)}:new:{i}', len(b.floors) + i, face.geometry) for i in range(steps))
        else:
            height = b.first_floor_height_m if floor.level == 0 else b.standard_floor_height_m
            u0, v0, u1, v1 = face.geometry.bounds
            rectangle = Polygon([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
            if v0 != 0 or v1 != height or not rectangle.equals(face.geometry):
                raise FaceEditError('arbitrary facade heights BLOCKED; full-storey rectangular faces only')
            coords = list(floor.geometry.exterior.coords)
            a, c = coords[face.edge_index], coords[face.edge_index + 1]
            length = math.dist(a, c)
            dx, dy = (c[0]-a[0])/length, (c[1]-a[1])/length
            sign = 1 if floor.geometry.exterior.is_ccw else -1
            nx, ny = sign*dy, -sign*dx
            p, q = (a[0]+dx*u0, a[1]+dy*u0), (a[0]+dx*u1, a[1]+dy*u1)
            swept = Polygon([p, q, (q[0]+nx*steps, q[1]+ny*steps), (p[0]+nx*steps, p[1]+ny*steps)])
            geom = floor.geometry.union(swept)
            _polygon(geom)
            if not unary_union([Polygon(r) for r in geom.interiors]).equals(unary_union([Polygon(r) for r in floor.geometry.interiors])):
                raise FaceEditError('outer side edit must preserve inner rings; inner ring editing is unsupported')
            floors = tuple(replace(f, geometry=geom) if f.id == floor.id else f for f in b.floors)
        edited = replace(b, floors=floors)
        _building(edited)
        return self._geometry_record(edited)

    def setback_upper_two(self, *, expected_revision: int, metres: int) -> FaceRevision:
        if expected_revision != self.active_revision_id or isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise FaceEditError('stale parent revision')
        if isinstance(metres, bool) or not isinstance(metres, int) or metres <= 0:
            raise FaceEditError('positive integer setback metres required')
        b = self.active.building
        if len(b.floors) < 2:
            raise FaceEditError('two storeys required')
        levels = sorted(f.level for f in b.floors)[-2:]
        if any(f.geometry.interiors for f in b.floors if f.level in levels):
            raise FaceEditError("setback would change inner rings; inner ring editing is unsupported", code="INNER_RING_EDITING_UNSUPPORTED")
        floors = []
        for f in b.floors:
            # Explicit requested inset operation, never validity repair.
            geom = f.geometry.buffer(-metres, join_style=2) if f.level in levels else f.geometry
            _polygon(geom)
            if len(geom.exterior.coords) != len(f.geometry.exterior.coords):
                raise FaceEditError('setback changes footprint topology; explicit Founder review required')
            floors.append(replace(f, geometry=geom))
        edited = replace(b, floors=tuple(floors))
        return self._geometry_record(edited)

    def undo(self) -> FaceRevision:
        parent = self.active.parent_revision_id
        if parent is None:
            raise FaceEditError('no revision to undo')
        self.active_revision_id = parent
        return self.active
