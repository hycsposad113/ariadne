from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, Polygon, box, shape

from urban_design.generation.contracts import (
    AssumptionSpec,
    AssumptionSourceKind,
    FrozenRef as GenerationRef,
    GenerationClass,
    GenerationContext,
    StageStatus,
    StrategySpec,
)
from urban_design.generation.hashing import stage_artifact_digest
from urban_design.generation.skeleton import (
    SkeletonBuildError,
    SkeletonEntry,
    SkeletonInputs,
    build_skeleton,
    skeleton_geometry_digest,
)
from urban_design.generation.strategy_catalog import build_strategy_catalog
from urban_design.morphology.contracts import RoadSegment
from urban_design.morphology.streets import count_road_components
from urban_design.site_intelligence.contracts import (
    DesignBriefRevision,
    DesignIntent,
    FrozenRef as A2Ref,
)


_PARAMETERS = {
    "road_local_width_m": 4.0,
    "road_collector_width_m": 6.0,
    "road_clearance_m": 1.0,
    "grid_spacing_m": 30.0,
    "grid_open_space_diameter_m": 12.0,
    "central_common_diameter_m": 20.0,
    "linear_open_space_width_m": 8.0,
}


def _gref(name: str, digit: str = "1") -> GenerationRef:
    return GenerationRef(id=name, sha256=f"sha256:{digit * 64}", kind="SYNTHETIC_FIXTURE")


def _a2ref(name: str, digit: str = "1") -> A2Ref:
    return A2Ref(id=name, revision=1, sha256=f"sha256:{digit * 64}")


def _context(*, seed: int = 17, extra_parameters: dict | None = None) -> GenerationContext:
    assumptions = tuple(
        AssumptionSpec(
            id=parameter,
            statement=f"Synthetic fixture parameter {parameter}",
            source_kind=AssumptionSourceKind.ILLUSTRATIVE_FIXTURE,
        )
        for parameter in _PARAMETERS
    )
    parameters = {**_PARAMETERS, **(extra_parameters or {})}
    if extra_parameters:
        assumptions += tuple(
            AssumptionSpec(
                id=parameter,
                statement=f"Synthetic fixture parameter {parameter}",
                source_kind=AssumptionSourceKind.ILLUSTRATIVE_FIXTURE,
            )
            for parameter in extra_parameters
        )
    return GenerationContext(
        workspace_ref=_gref("workspace-fixture", "1"),
        analysis_ref=_gref("analysis-fixture", "2"),
        brief_ref=_gref("brief-fixture", "3"),
        source_refs=(_gref("site-fixture", "4"), _gref("network-fixture", "5")),
        crs="EPSG:28992",
        coordinate_unit="m",
        seed=seed,
        method_parameters=parameters,
        assumptions=assumptions,
        generation_class=GenerationClass.EXPLORATORY,
    )


def _brief(*intents: DesignIntent) -> DesignBriefRevision:
    return DesignBriefRevision(
        id="brief-fixture",
        revision=1,
        workspace_ref=_a2ref("workspace-fixture"),
        analysis_ref=_a2ref("analysis-fixture", "2"),
        intents=tuple(intents),
    )


def _intent(intent_id: str, kind: str, text: str | None = None) -> DesignIntent:
    return DesignIntent(
        id=intent_id,
        text=text or intent_id,
        scope_ref=_a2ref("site-fixture", "4"),
        kind=kind,
        origin="DESIGNER_AUTHORED",
        version=1,
    )


def _entry(entry_id: str, x: float, y: float, *, level: int | None = 0) -> SkeletonEntry:
    return SkeletonEntry(
        id=entry_id,
        point=Point(x, y),
        level=level,
        source_refs=(_gref(f"entry-{entry_id}", "6"),),
    )


def _inputs(
    site,
    *,
    entries: tuple[SkeletonEntry, ...] | None = None,
    water: tuple = (),
    retained: tuple = (),
    spine_entry_id: str | None = None,
    spine_target: Point | None = None,
):
    if entries is None:
        entries = (_entry("west", *site.exterior.coords[0]), _entry("east", *site.exterior.coords[2]))
    return SkeletonInputs(
        site_geometry=site,
        entry_contacts=entries,
        water_geometries=water,
        retained_geometries=retained,
        source_refs=(_gref("site-fixture", "4"), _gref("network-fixture", "5")),
        retained_geometry_refs=tuple(_gref(f"retained-{index}", "7") for index, _ in enumerate(retained)),
        spine_entry_id=spine_entry_id or (entries[0].id if entries else None),
        spine_target=spine_target,
        spine_target_ref=_gref("spine-target-fixture", "8") if spine_target is not None else None,
    )


def _catalog(*intents: DesignIntent):
    result = build_strategy_catalog(_brief(*intents))
    return result


def _strategy(catalog, family: str) -> StrategySpec:
    return next(item for item in catalog.strategies if item.topology_family == family)


def test_three_registered_skeleton_families_are_replayable_and_geometrically_distinct():
    site = box(0, 0, 120, 90)
    inputs = _inputs(
        site,
        entries=(_entry("west", 0, 45), _entry("east", 120, 45)),
        spine_entry_id="west",
        spine_target=Point(120, 45),
    )
    context = _context()
    catalog = _catalog()
    families = {item.topology_family for item in catalog.strategies}

    assert families == {"CONNECTED_GRID", "CENTRAL_COMMON", "LINEAR_SPINE"}

    results = {
        family: build_skeleton(context, _strategy(catalog, family), inputs)
        for family in sorted(families)
    }
    replayed = {
        family: build_skeleton(context, _strategy(catalog, family), inputs)
        for family in sorted(families)
    }

    assert all(result.status == "READY" for result in results.values())
    assert {
        family: stage_artifact_digest(result.artifact)
        for family, result in results.items()
    } == {
        family: stage_artifact_digest(result.artifact)
        for family, result in replayed.items()
    }
    assert len({skeleton_geometry_digest(result.artifact) for result in results.values()}) == 3
    for result in results.values():
        assert result.artifact.validation.geometry_status is StageStatus.PASS
        assert result.artifact.validation.topology_status is StageStatus.PASS
        assert result.artifact.primary_open_spaces
        assert all(space.access_policy.status.value == "UNKNOWN" for space in result.artifact.primary_open_spaces)


def test_a2_required_and_avoid_intents_filter_only_registered_topology_families():
    avoid_grid = _intent("topology:avoid:CONNECTED_GRID", "AVOID_FEATURE")
    catalog = _catalog(avoid_grid)

    assert {item.topology_family for item in catalog.strategies} == {"CENTRAL_COMMON", "LINEAR_SPINE"}
    assert "CONNECTED_GRID" in catalog.excluded_families

    require_central = _intent("topology:require:CENTRAL_COMMON", "REQUIRED_FEATURE")
    required_catalog = _catalog(require_central)
    assert {item.topology_family for item in required_catalog.strategies} == {"CENTRAL_COMMON"}


def test_unregistered_or_mistyped_intents_are_reported_without_text_inference():
    unknown = _intent("designer-note-7", "PREFERENCE", "Avoid every grid even though the id is unregistered")
    catalog = _catalog(unknown)

    assert {item.topology_family for item in catalog.strategies} == {
        "CONNECTED_GRID",
        "CENTRAL_COMMON",
        "LINEAR_SPINE",
    }
    assert catalog.unsupported_intent_ids == ("designer-note-7",)

    mistyped = _intent("topology:require:CONNECTED_GRID", "PREFERENCE")
    assert _catalog(mistyped).strategies == ()


def test_frozen_water_and_retained_buildings_change_routes_and_remain_obstacles():
    site = box(0, 0, 100, 100)
    entries = (_entry("west", 0, 50), _entry("east", 100, 50))
    context = _context()
    strategy = _strategy(_catalog(), "CENTRAL_COMMON")
    baseline = build_skeleton(context, strategy, _inputs(site, entries=entries))
    water = box(38, 30, 62, 70)
    retained = box(42, 42, 58, 58)
    constrained = build_skeleton(
        context,
        strategy,
        _inputs(site, entries=entries, water=(water,), retained=(retained,)),
    )

    assert skeleton_geometry_digest(baseline.artifact) != skeleton_geometry_digest(constrained.artifact)
    assert all(not water.intersects(shape(edge.geometry.model_dump(exclude={"crs"}))) for edge in constrained.artifact.edges)
    assert all(not retained.intersects(shape(space.geometry.model_dump(exclude={"crs"}))) for space in constrained.artifact.primary_open_spaces)
    assert constrained.artifact.retained_geometry_refs


def test_waterfront_preference_changes_linear_spine_and_height_policy_does_not():
    site = box(0, 0, 100, 100)
    entries = (_entry("south", 50, 0),)
    water = box(72, 75, 90, 90)
    inputs = _inputs(
        site,
        entries=entries,
        water=(water,),
        spine_entry_id="south",
        spine_target=Point(50, 100),
    )
    context = _context()
    baseline_strategy = _strategy(_catalog(), "LINEAR_SPINE")
    waterfront_catalog = _catalog(_intent("open-space:prefer-waterfront", "PREFERENCE"))
    waterfront_strategy = _strategy(waterfront_catalog, "LINEAR_SPINE")

    baseline = build_skeleton(context, baseline_strategy, inputs)
    waterfront = build_skeleton(context, waterfront_strategy, inputs)
    taller = build_skeleton(
        context,
        baseline_strategy.model_copy(update={"height_policy": {"policy": "along_spine", "height_m": 120}}),
        inputs,
    )

    assert skeleton_geometry_digest(baseline.artifact) != skeleton_geometry_digest(waterfront.artifact)
    assert skeleton_geometry_digest(baseline.artifact) == skeleton_geometry_digest(taller.artifact)


def test_l_shape_central_water_hole_and_disconnected_land_blocks_are_handled():
    l_shape = Polygon([(0, 0), (100, 0), (100, 35), (35, 35), (35, 100), (0, 100)])
    l_result = build_skeleton(
        _context(),
        _strategy(_catalog(), "CONNECTED_GRID"),
        _inputs(l_shape, entries=(_entry("south", 50, 0), _entry("north", 0, 80))),
    )
    assert l_result.status == "READY"
    assert all(l_shape.buffer(1e-6).covers(shape(edge.geometry.model_dump(exclude={"crs"}))) for edge in l_result.artifact.edges)

    water_hole = Polygon(
        [(0, 0), (100, 0), (100, 100), (0, 100)],
        holes=[[(40, 40), (60, 40), (60, 60), (40, 60), (40, 40)]],
    )
    water = box(40, 40, 60, 60)
    water_result = build_skeleton(
        _context(),
        _strategy(_catalog(), "CONNECTED_GRID"),
        _inputs(water_hole, entries=(_entry("west", 0, 50), _entry("east", 100, 50)), water=(water,)),
    )
    assert water_result.status == "READY"
    assert all(not water.intersects(shape(edge.geometry.model_dump(exclude={"crs"}))) for edge in water_result.artifact.edges)

    split = box(0, 0, 80, 80), box(105, 0, 185, 80)
    from shapely.geometry import MultiPolygon

    islands = MultiPolygon(split)
    island_result = build_skeleton(
        _context(),
        _strategy(_catalog(), "CONNECTED_GRID"),
        _inputs(islands, entries=(_entry("west", 0, 40), _entry("east", 185, 40))),
    )
    assert island_result.status == "READY"
    assert island_result.connected_components == 2


def test_unique_entry_requires_explicit_linear_target_and_no_entry_is_blocked():
    site = box(0, 0, 100, 100)
    single_entry = (_entry("south", 50, 0),)
    context = _context()
    linear = _strategy(_catalog(), "LINEAR_SPINE")

    with pytest.raises(SkeletonBuildError, match="explicit.*target") as missing_target:
        build_skeleton(context, linear, _inputs(site, entries=single_entry))
    assert missing_target.value.status == "BLOCKED"
    assert missing_target.value.failure_geometry is not None

    with pytest.raises(SkeletonBuildError, match="entry") as no_entry:
        build_skeleton(context, linear, _inputs(site, entries=()))
    assert no_entry.value.status == "BLOCKED"
    assert no_entry.value.failure_geometry is not None


def test_rotated_grid_failure_geometry_is_returned_in_world_coordinates():
    site = box(0, 0, 120, 90)
    inputs = _inputs(
        site,
        entries=(_entry("west", 0, 45), _entry("east", 120, 45)),
        retained=(site,),
    )

    with pytest.raises(SkeletonBuildError, match="safe grid domain") as blocked:
        build_skeleton(_context(), _strategy(_catalog(), "CONNECTED_GRID"), inputs)

    assert blocked.value.failure_geometry is not None
    assert site.buffer(1e-6).covers(blocked.value.failure_geometry)


def test_external_contact_inside_site_boundary_tolerance_is_snapped_for_routing():
    site = box(0, 0, 100, 100)
    entries = (_entry("west", -1e-8, 50), _entry("east", 100 + 1e-8, 50))

    result = build_skeleton(
        _context(),
        _strategy(_catalog(), "CENTRAL_COMMON"),
        _inputs(site, entries=entries),
    )

    assert result.status == "READY"
    assert all(site.buffer(1e-6).covers(shape(edge.geometry.model_dump(exclude={"crs"}))) for edge in result.artifact.edges)


def test_roads_crossing_at_different_levels_do_not_form_one_component():
    at_grade = (
        RoadSegment("horizontal", LineString([(0, 5), (10, 5)]), layer=0),
        RoadSegment("vertical", LineString([(5, 0), (5, 10)]), layer=0),
    )
    grade_separated = (
        RoadSegment("horizontal", LineString([(0, 5), (10, 5)]), layer=0),
        RoadSegment("vertical", LineString([(5, 0), (5, 10)]), layer=1),
    )

    assert count_road_components(at_grade) == 1
    assert count_road_components(grade_separated) == 2
