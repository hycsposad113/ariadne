import pytest
from shapely.geometry import Polygon, LineString, box
from urban_design.editing.floors import BuildingMassing, FloorStorey
from urban_design.editing.faces import FaceEditError, FaceEditHistory, fixture_quantities


def stack(count=4, geometry=None):
    return BuildingMassing('fixture', tuple(FloorStorey(f'f{i}', i, box(0,0,10,10) if geometry is None else geometry) for i in range(count)), 4, 3)


def face(history, kind):
    return next(f for f in history.active.faces if f.kind == kind)


@pytest.mark.parametrize('closed', [False, True])
def test_subdivision_preserves_exact_geometry_and_quantities(closed):
    h = FaceEditHistory(stack())
    original = h.active.building
    target = face(h, 'TOP')
    cut = box(2,2,4,4) if closed else LineString([(-1,5),(11,5)])
    revision = h.subdivide(target.id, expected_revision=0, cutter=cut)
    assert revision.building is original
    assert fixture_quantities(revision.building) == (400,1300)
    assert revision.lineage[0][0] == target.id
    assert len(revision.lineage[0][1]) >= 2
    assert revision.production_status == 'BLOCKED'
    assert h.undo().building.geometry_hash() == original.geometry_hash()


def test_local_top_extrusion_and_undo():
    h = FaceEditHistory(stack())
    original = h.active.building
    h.subdivide(face(h,'TOP').id, expected_revision=0, cutter=LineString([(-1,5),(11,5)]))
    top = face(h,'TOP')
    h.extrude(top.id, expected_revision=1, steps=2, semantic_option='NEW_USABLE_FLOORS_PROTOTYPE')
    assert [f.geometry.area for f in h.active.building.floors] == [100]*4+[50]*2
    assert fixture_quantities(h.active.building) == (500,1600)
    h.undo()
    assert h.undo().building.geometry_hash() == original.geometry_hash()


def test_local_side_one_metre():
    h = FaceEditHistory(stack())
    target = face(h,'SIDE')
    length = target.geometry.bounds[2]
    h.subdivide(target.id, expected_revision=0, cutter=LineString([(length/2,-1),(length/2,5)]))
    side = next(f for f in h.active.faces if ':part:' in f.id)
    original = h.active.building
    h.extrude(side.id, expected_revision=1, steps=1, semantic_option='NEW_USABLE_FLOORS_PROTOTYPE')
    assert h.active.building.floor(side.floor_id).geometry.area == 105
    assert fixture_quantities(h.active.building)[0] == 405
    assert h.undo().building.geometry_hash() == original.geometry_hash()


def test_upper_two_only():
    h = FaceEditHistory(stack())
    before = h.active.building
    h.setback_upper_two(expected_revision=0, metres=1)
    assert [f.geometry.area for f in h.active.building.floors] == [100,100,64,64]
    assert h.active.building.floors[0].geometry.wkb == before.floors[0].geometry.wkb
    assert h.undo().building.geometry_hash() == before.geometry_hash()


@pytest.mark.parametrize('geometry', [Polygon([(0,0),(10,10),(0,10),(10,0)]), Polygon()])
def test_invalid_nonmanifold_rejected(geometry):
    with pytest.raises(FaceEditError):
        FaceEditHistory(stack(geometry=geometry))


def test_fail_closed_stale_steps_semantics_and_height():
    h = FaceEditHistory(stack())
    top = face(h,'TOP')
    for steps in [True, 0, -1, 1.2]:
        with pytest.raises(FaceEditError):
            h.extrude(top.id, expected_revision=0, steps=steps, semantic_option='NEW_USABLE_FLOORS_PROTOTYPE')
    with pytest.raises(FaceEditError):
        h.extrude(top.id, expected_revision=0, steps=1, semantic_option='APPROVED')
    side = face(h,'SIDE')
    h.subdivide(side.id, expected_revision=0, cutter=LineString([(-1,2),(11,2)]))
    partial = next(f for f in h.active.faces if ':part:' in f.id)
    with pytest.raises(FaceEditError, match='heights BLOCKED'):
        h.extrude(partial.id, expected_revision=1, steps=1, semantic_option='NEW_USABLE_FLOORS_PROTOTYPE')
    with pytest.raises(FaceEditError, match='stale parent'):
        h.subdivide(top.id, expected_revision=0, cutter=LineString([(-1,5),(11,5)]))
    with pytest.raises(FaceEditError, match='semantic face'):
        h.subdivide(side.id, expected_revision=1, cutter=LineString([(-1,5),(11,5)]))
    assert len(h.revisions) == 2


def test_invalid_cuts_and_collapsing_setback_leave_history_unchanged():
    h = FaceEditHistory(stack())
    top = face(h,'TOP')
    for cutter in [LineString([(20,20),(30,30)]), LineString([(0,0),(10,10),(0,10),(10,0)]), box(-1,-1,1,1)]:
        with pytest.raises(FaceEditError):
            h.subdivide(top.id, expected_revision=0, cutter=cutter)
    with pytest.raises(FaceEditError):
        h.setback_upper_two(expected_revision=0, metres=6)
    assert len(h.revisions) == 1


def test_unsupported_cantilever_stack():
    b = stack(2)
    from dataclasses import replace
    b = replace(b, floors=(b.floors[0], replace(b.floors[1], geometry=box(-1,0,10,10))))
    with pytest.raises(FaceEditError, match='cantilever'):
        FaceEditHistory(b)


def test_unrelated_partition_survives_and_invalidation_is_explicit():
    h = FaceEditHistory(stack())
    side = face(h, 'SIDE')
    h.subdivide(side.id, expected_revision=0, cutter=LineString([(5,-1),(5,5)]))
    parts = tuple(f for f in h.active.faces if ':part:' in f.id)
    top = face(h, 'TOP')
    r = h.extrude(top.id, expected_revision=1, steps=1, semantic_option='NEW_USABLE_FLOORS_PROTOTYPE')
    for part in parts:
        assert part in r.faces
        assert dict(r.lineage)[part.id] == (part.id,)
    assert dict(r.lineage)[top.id] == ()


@pytest.mark.parametrize('level,identifier', [(True,'f0'), (0,''), (0,' ')])
def test_invalid_floor_identity(level, identifier):
    b = BuildingMassing('fixture', (FloorStorey(identifier,level,box(0,0,10,10)),),4,3)
    with pytest.raises(FaceEditError):
        FaceEditHistory(b)


def test_setback_float_parent_rejected():
    h = FaceEditHistory(stack())
    with pytest.raises(FaceEditError):
        h.setback_upper_two(expected_revision=0.0,metres=1)


def test_courtyard_outer_side_can_be_edited_with_hole_preserved():
    geometry = Polygon([(0,0),(10,0),(10,10),(0,10)], [[(3,3),(7,3),(7,7),(3,7)]])
    h = FaceEditHistory(stack(1, geometry))
    assert len([f for f in h.active.faces if f.kind == 'SIDE']) == 4
    result = h.extrude(face(h, 'SIDE').id, expected_revision=0, steps=1, semantic_option='NEW_USABLE_FLOORS_PROTOTYPE')
    edited = result.building.floors[0].geometry
    assert edited.is_valid
    assert len(edited.interiors) == 1
    assert Polygon(edited.interiors[0]).equals(Polygon(geometry.interiors[0]))
    assert Polygon(edited.exterior).contains(Polygon(edited.interiors[0]))
    assert h.undo().building.floors[0].geometry.equals(geometry)


def test_hole_outside_shell_is_rejected_without_repair():
    geometry = Polygon([(0,0),(10,0),(10,10),(0,10)], [[(9,9),(11,9),(11,11),(9,11)]])
    with pytest.raises(FaceEditError):
        FaceEditHistory(stack(1, geometry))


def test_courtyard_top_partition_and_local_extrusion_never_fill_hole():
    from shapely.ops import unary_union
    geometry = Polygon([(0,0),(10,0),(10,10),(0,10)], [[(3,3),(7,3),(7,7),(3,7)]])
    courtyard = Polygon(geometry.interiors[0])
    history = FaceEditHistory(stack(1, geometry))
    top = face(history, 'TOP')
    revision = history.subdivide(top.id, expected_revision=0, cutter=LineString([(-1,5),(11,5)]))
    parts = [candidate for candidate in revision.faces if candidate.kind == 'TOP']
    assert len(parts) == 2
    assert unary_union([part.geometry for part in parts]).equals(geometry)
    assert sum(part.geometry.area for part in parts) == geometry.area
    assert all(part.geometry.is_valid and part.geometry.intersection(courtyard).area == 0 for part in parts)
    extruded = history.extrude(parts[0].id, expected_revision=1, steps=1, semantic_option='NEW_USABLE_FLOORS_PROTOTYPE')
    assert extruded.building.floors[0].geometry.equals(geometry)
    added = extruded.building.floors[-1].geometry
    assert added.equals(parts[0].geometry)
    assert added.is_valid
    assert geometry.covers(added)
    assert added.intersection(courtyard).area == 0


def test_courtyard_setback_rejects_inner_ring_mutation():
    geometry = Polygon([(0,0),(20,0),(20,20),(0,20)], [[(8,8),(12,8),(12,12),(8,12)]])
    history = FaceEditHistory(stack(2, geometry))
    original = history.active.building.geometry_hash()
    with pytest.raises(FaceEditError) as error:
        history.setback_upper_two(expected_revision=0, metres=1)
    assert error.value.code == 'INNER_RING_EDITING_UNSUPPORTED'
    assert history.active.building.geometry_hash() == original
    assert len(history.revisions) == 1


@pytest.mark.parametrize('parts', [
    [box(0, 0, 4.9, 10), box(5.1, 0, 10, 10)],
    [box(0, 0, 5.1, 10), box(4.9, 0, 10, 10)],
])
def test_partition_numerical_tolerance_rejects_real_gap_and_overlap(monkeypatch, parts):
    from types import SimpleNamespace
    monkeypatch.setattr('urban_design.editing.faces.split', lambda *_: SimpleNamespace(geoms=parts))
    history = FaceEditHistory(stack())
    with pytest.raises(FaceEditError, match='partition must cover'):
        history.subdivide(face(history, 'TOP').id, expected_revision=0, cutter=LineString([(5, -1), (5, 11)]))
    assert history.active_revision_id == 0


def test_stack_cover_tolerates_only_float_rounding_at_real_coordinates():
    # RD New-scale coordinates: an upper vertex a few ulps outside the lower plate (GEOS
    # rounding after rotate/split) must not read as a cantilever; a real 1 mm overhang must.
    x0, y0 = 88619.4845172335, 435694.45946021815
    lower = Polygon([(x0, y0), (x0 + 25.0, y0 + 25.0), (x0 + 50.0, y0), (x0 + 25.0, y0 - 25.0)])
    ulp_out = Polygon([(x0 - 2e-11, y0), (x0 + 25.0, y0 + 25.0), (x0 + 50.0, y0), (x0 + 25.0, y0 - 25.0)])
    assert not lower.covers(ulp_out)
    FaceEditHistory(BuildingMassing('fixture', (FloorStorey('f0', 0, lower), FloorStorey('f1', 1, ulp_out)), 4, 3))
    overhang = Polygon([(x0 - 1e-3, y0), (x0 + 25.0, y0 + 25.0), (x0 + 50.0, y0), (x0 + 25.0, y0 - 25.0)])
    with pytest.raises(FaceEditError, match='cantilever'):
        FaceEditHistory(BuildingMassing('fixture', (FloorStorey('f0', 0, lower), FloorStorey('f1', 1, overhang)), 4, 3))
