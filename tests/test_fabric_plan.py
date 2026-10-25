"""Independent FAB1 checks against frozen fabric inputs and synthetic geometry.

The source-fabric projections below are embedded intentionally: these tests do
not read a runner artifact or another worktree at runtime. Each projection keeps
the dimensions, street hierarchy, density and park ranges, and composition IDs
exercised by FAB1, with its source revision and snapshot hash retained for review.
"""
from __future__ import annotations

import copy
import math

import pytest
from shapely.geometry import GeometryCollection, Polygon, box, mapping, shape
from shapely.ops import unary_union

from urban_design.generation.fabric_plan import compare_plans, generate_plan, validate_plan


_SNAPSHOT_SCHEMA = "fab1-input-snapshot-v1"
_SOURCE_FABRIC_REVISION = "36f4d9573de9d765929015fd0871933de6461e17"


def _dimension(minimum: float, maximum: float | None = None) -> dict:
    return {
        "minimum": minimum,
        "maximum": minimum if maximum is None else maximum,
        "unit": "m",
    }


def _density_target(minimum: float, maximum: float, *, status: str) -> dict:
    return {
        "range": {"minimum": minimum, "maximum": maximum},
        "unit": "dimensionless",
        "status": status,
    }


def _source_fabric(
    fabric_id: str,
    *,
    short: tuple[float, float],
    long: tuple[float, float],
    pattern: str,
    street_widths: tuple[tuple[float, float], ...],
    gsi: tuple[float, float],
    fsi: tuple[float, float],
    density_status: str,
    park_percent: tuple[float, float],
    buildings: tuple[str, ...],
    open_spaces: tuple[str, ...],
    snapshot_sha256: str,
) -> dict:
    return {
        "id": fabric_id,
        "fixture_source": {
            "manifest_schema": _SNAPSHOT_SCHEMA,
            "source_revision": _SOURCE_FABRIC_REVISION,
            "snapshot_path": f"artifacts/fab1/run-2/inputs/fabrics/{fabric_id}.json",
            "snapshot_sha256": snapshot_sha256,
            "projection": "dimensions, hierarchy widths, density and park ranges, and morphology IDs",
        },
        "blocks": {
            "short_edge_m": _dimension(*short),
            "long_edge_m": _dimension(*long),
        },
        "street_network": {
            "pattern": pattern,
            "hierarchy": [
                {"section_width_m": _dimension(*width)} for width in street_widths
            ],
        },
        "density_targets": {
            "GSI": _density_target(*gsi, status=density_status),
            "FSI": _density_target(*fsi, status=density_status),
        },
        "land_use_budget": {
            "parks": {
                "minimum": park_percent[0],
                "maximum": park_percent[1],
                "unit": "percent_site_area",
                "status": "EDITORIAL",
            },
        },
        "building_composition": {"components": [{"part_id": item} for item in buildings]},
        "open_space_system": {"types": [{"part_id": item} for item in open_spaces]},
    }


# Values are from the 2026-10-11 snapshot manifest in the shared checkout.
# The values remain labeled as precedent-derived or editorial in the source
# dictionaries; the fixture does not turn them into regulations or approvals.
SOURCE_FABRICS = {
    "fabric.harbour_grain": _source_fabric(
        "fabric.harbour_grain",
        short=(68.6, 68.6),
        long=(127.4, 127.4),
        pattern="linear_parallel",
        street_widths=((18, 24), (12, 16), (6, 8)),
        gsi=(0.2180, 0.5065),
        fsi=(1.9643, 2.2736),
        density_status="MEASURED_PRECEDENT",
        park_percent=(6, 12),
        buildings=(
            "block.rowhouse_strip",
            "building.rowhouse",
            "building.i_slab",
            "building.industrial_hall",
            "block.perimeter",
        ),
        open_spaces=("space.waterfront_promenade", "space.shared_street", "space.plaza"),
        snapshot_sha256="620c82044a3baac87a3d8dd5549028edc33b45ad3d298588f0864bda7c469347",
    ),
    "fabric.closed_block_extension": _source_fabric(
        "fabric.closed_block_extension",
        short=(64.9, 64.9),
        long=(102.7, 102.7),
        pattern="deformed_grid",
        street_widths=((14, 18), (10, 14), (4, 7)),
        gsi=(0.40, 0.60),
        fsi=(1.6, 3.0),
        density_status="LITERATURE",
        park_percent=(8, 14),
        buildings=(
            "block.perimeter",
            "block.hybrid",
            "building.courtyard_closed",
            "building.terraced",
            "building.i_slab",
        ),
        open_spaces=("space.courtyard", "space.shared_street", "space.plaza"),
        snapshot_sha256="d43aa89539375fcf9acc89d33fc04d488929573bba82cea474dd1262a350b46f",
    ),
    "fabric.courtyard_islands": _source_fabric(
        "fabric.courtyard_islands",
        short=(75, 120),
        long=(115, 200),
        pattern="deformed_grid",
        street_widths=((18, 24), (12, 16), (5, 8)),
        gsi=(0.2787, 0.3082),
        fsi=(1.9643, 2.4636),
        density_status="MEASURED_PRECEDENT",
        park_percent=(8, 14),
        buildings=(
            "block.superblock",
            "block.open",
            "building.courtyard_closed",
            "building.u_block",
            "building.courtyard_open_corner",
        ),
        open_spaces=("space.courtyard", "space.covered_public_passage", "space.plaza"),
        snapshot_sha256="2661f9ae8087740fa78ec82a967fb742063691d2736049b80812fa8ab02cb7e5",
    ),
    "fabric.landscape_figure": _source_fabric(
        "fabric.landscape_figure",
        short=(37.7, 52.7),
        long=(84.4, 87.0),
        pattern="landscape_led",
        street_widths=((16, 24), (8, 12), (4, 7)),
        gsi=(0.2203, 0.3013),
        fsi=(0.7623, 1.5997),
        density_status="MEASURED_PRECEDENT",
        park_percent=(18, 28),
        buildings=(
            "block.open",
            "block.towers_park",
            "building.point_array",
            "building.i_slab",
            "building.terraced",
        ),
        open_spaces=("space.linear_park", "space.pocket_park", "space.plaza"),
        snapshot_sha256="e82493aede0c0b3573eef2a0fa6c19d702fe28fd3bfbe04d22f86cea466e2fb0",
    ),
}


# An explicit synthetic editorial range exercises the generic rectangle
# operator without treating one precedent-derived source range as universal.
EDITORIAL_RECTANGLE_FABRIC = _source_fabric(
    "fabric.harbour_grain",
    short=(45, 55),
    long=(90, 110),
    pattern="synthetic_orthogonal_grid",
    street_widths=((10, 12), (6, 8), (4, 6)),
    gsi=(0, 1),
    fsi=(0, 10),
    density_status="ILLUSTRATIVE_EXAMPLE",
    park_percent=(0, 100),
    buildings=("building.rowhouse", "building.industrial_hall"),
    open_spaces=("space.plaza",),
    snapshot_sha256="EDITORIAL_FIXTURE_ONLY",
)


def _facts(site) -> dict:
    empty = mapping(GeometryCollection())
    return {
        "geometry": {
            "crs": "EPSG:28992",
            "site": mapping(site),
            "water": empty,
            "waterfront_band": empty,
            "dakpark": empty,
            "buildable": mapping(site),
            "retained_buildings": [],
            "retained_roads": [],
            "entrances": [],
        },
        "retained_buildings": [],
    }


def _context() -> dict:
    return {
        "horizontal_crs": "EPSG:28992",
        "site": {"principal_axis": {"long_axis_azimuth_deg": 90.0}},
        "boundary_and_alignments": {},
    }


def _edge_lengths(geometry) -> tuple[float, float]:
    rectangle = geometry.minimum_rotated_rectangle
    coords = list(rectangle.exterior.coords)
    lengths = sorted(math.dist(coords[i], coords[i + 1]) for i in range(2))
    return lengths[0], lengths[1]


def _polygon_parts(geometry) -> list:
    return list(geometry.geoms) if hasattr(geometry, 'geoms') else [geometry]


def _assert_axis_aligned_rectangle(geometry) -> None:
    assert geometry.geom_type == "Polygon"
    coords = list(geometry.exterior.coords)
    assert len(coords) == 5
    for start, end in zip(coords, coords[1:]):
        dx, dy = abs(end[0] - start[0]), abs(end[1] - start[1])
        assert min(dx, dy) <= 1e-6, (start, end)


@pytest.fixture(scope="module")
def rectangular_plan() -> dict:
    site = box(0, 0, 600, 280)
    return generate_plan(_facts(site), _context(), copy.deepcopy(EDITORIAL_RECTANGLE_FABRIC))


def test_rectangular_site_has_orthogonal_blocks_full_land_cover_and_building_frontage(rectangular_plan):
    plan = rectangular_plan
    result = validate_plan(plan)

    assert plan["blocks"]
    new_buildings = [row for row in plan["buildings"] if not row["properties"].get("retained")]
    assert new_buildings
    for row in plan["blocks"] + new_buildings:
        _assert_axis_aligned_rectangle(shape(row["geometry"]))

    assert result["checks"]["ORTHOGONAL_TEMPLATES"]["passed"]
    assert result["checks"]["BLOCK_DICTIONARY_DIMENSIONS"]["passed"]
    assert result["checks"]["STREET_FRONTAGE"]["passed"]
    assert result["checks"]["ALL_BUILDINGS_FRONTAGE"]["passed"]
    assert result["checks"]["LAND_MANAGEMENT"]["passed"]
    assert result["checks"]["LAND_COVERAGE"]["passed"]
    assert result["checks"]["LAND_NO_OVERLAP"]["passed"]
    assert result["checks"]["LAND_SUM_100_PERCENT"]["passed"]
    assert result["checks"]["LAND_COVERAGE"]["unallocated_m2"] == pytest.approx(0, abs=0.01)
    assert result["metrics"]["allocation_percent"] == pytest.approx(100, abs=0.01)


def test_acute_site_corner_stays_out_of_acute_massing_and_is_allocated():
    base = box(0, 0, 500, 500)
    acute_extension = Polygon([(500, 200), (650, 250), (500, 300)])
    site = unary_union([base, acute_extension])
    plan = generate_plan(_facts(site), _context(), copy.deepcopy(SOURCE_FABRICS["fabric.harbour_grain"]))
    result = validate_plan(plan)

    assert plan["blocks"]
    assert result["checks"]["ORTHOGONAL_TEMPLATES"]["passed"]
    assert result["checks"]["MASSING_CORNERS"]["passed"]
    allocated = unary_union([shape(row["geometry"]) for row in plan["land_use"]])
    assert acute_extension.difference(allocated).area <= 0.01
    assert result["checks"]["LAND_COVERAGE"]["passed"]
    assert result["checks"]["LAND_COVERAGE"]["unallocated_m2"] == pytest.approx(0, abs=0.01)


def test_intentionally_unallocated_land_fails_coverage_and_accounting(rectangular_plan):
    damaged = copy.deepcopy(rectangular_plan)
    largest = max(range(len(damaged["land_use"])), key=lambda i: shape(damaged["land_use"][i]["geometry"]).area)
    missing_area = shape(damaged["land_use"][largest]["geometry"]).area
    damaged["land_use"].pop(largest)

    result = validate_plan(damaged)

    assert result["status"] == "FAIL"
    assert not result["checks"]["LAND_COVERAGE"]["passed"]
    assert not result["checks"]["LAND_SUM_100_PERCENT"]["passed"]
    assert result["checks"]["LAND_COVERAGE"]["unallocated_m2"] == pytest.approx(missing_area)


def test_missing_fire_access_fails_fire_negative_control(rectangular_plan):
    damaged = copy.deepcopy(rectangular_plan)
    for row in damaged["roads"]:
        row["properties"]["modes"] = [mode for mode in row["properties"]["modes"] if mode != "fire"]

    result = validate_plan(damaged)

    assert any(not row["properties"].get("retained") for row in damaged["buildings"])
    assert result["status"] == "FAIL"
    assert not result["checks"]["FIRE_ALL_EXTERIORS"]["passed"]


def test_frozen_fabric_dimensions_keep_harbour_elongated_and_courtyard_larger():
    site = box(0, 0, 700, 360)
    facts, context = _facts(site), _context()
    harbour = generate_plan(facts, context, copy.deepcopy(SOURCE_FABRICS["fabric.harbour_grain"]))
    courtyard = generate_plan(
        facts,
        context,
        copy.deepcopy(SOURCE_FABRICS["fabric.courtyard_islands"]),
        intent={"block_short_m": 120, "block_long_m": 200},
    )
    harbour_short, harbour_long = _edge_lengths(shape(harbour["blocks"][0]["geometry"]))
    courtyard_short, courtyard_long = _edge_lengths(shape(courtyard["blocks"][0]["geometry"]))

    assert (harbour_short, harbour_long) == pytest.approx((68.6, 127.4))
    assert (courtyard_short, courtyard_long) == pytest.approx((120, 200))
    assert courtyard_short * courtyard_long > harbour_short * harbour_long
    assert harbour_long / harbour_short > courtyard_long / courtyard_short

    comparison = compare_plans([harbour, courtyard])
    assert comparison["winner"] is None
    assert comparison["pairwise"][0]["distinct"]


@pytest.mark.parametrize("fabric_id", tuple(SOURCE_FABRICS))
def test_each_updated_frozen_fabric_generates_recomputed_geometry(fabric_id):
    site = box(0, 0, 800, 500)
    plan = generate_plan(_facts(site), _context(), copy.deepcopy(SOURCE_FABRICS[fabric_id]))
    result = validate_plan(plan)

    assert plan["fabric_id"] == fabric_id
    assert plan["blocks"] and plan["buildings"]
    assert result["checks"]["GEOMETRY_VALID"]["passed"]
    assert result["checks"]["LAND_COVERAGE"]["passed"]
    assert result["checks"]["LAND_NO_OVERLAP"]["passed"]

    land = shape(plan["site"]).difference(shape(plan["water"]))
    footprints = unary_union([shape(row["geometry"]) for row in plan["buildings"]])
    expected_gsi = footprints.intersection(land).area / land.area
    expected_gfa = sum(
        shape(row["geometry"]).area * row["properties"]["floors"]
        + (
            shape(row["properties"]["mezzanine_geometry"]).area
            if row["properties"].get("mezzanine_geometry")
            else 0
        )
        for row in plan["buildings"]
        if not row["properties"].get("retained")
    )
    assert result["metrics"]["gsi"] == pytest.approx(expected_gsi)
    assert result["metrics"]["new_gfa_m2"] == pytest.approx(expected_gfa)


def test_all_four_frozen_fabric_projections_retain_source_ranges_and_composition():
    assert set(SOURCE_FABRICS) == {
        "fabric.harbour_grain",
        "fabric.closed_block_extension",
        "fabric.courtyard_islands",
        "fabric.landscape_figure",
    }
    assert SOURCE_FABRICS["fabric.closed_block_extension"]["blocks"] == {
        "short_edge_m": _dimension(64.9),
        "long_edge_m": _dimension(102.7),
    }
    assert SOURCE_FABRICS["fabric.harbour_grain"]["blocks"] == {
        "short_edge_m": _dimension(68.6),
        "long_edge_m": _dimension(127.4),
    }
    assert SOURCE_FABRICS["fabric.courtyard_islands"]["blocks"] == {
        "short_edge_m": _dimension(75, 120),
        "long_edge_m": _dimension(115, 200),
    }
    assert SOURCE_FABRICS["fabric.landscape_figure"]["blocks"] == {
        "short_edge_m": _dimension(37.7, 52.7),
        "long_edge_m": _dimension(84.4, 87.0),
    }
    expected_density = {
        "fabric.harbour_grain": ((0.2180, 0.5065), (1.9643, 2.2736), "MEASURED_PRECEDENT", (6, 12)),
        "fabric.closed_block_extension": ((0.40, 0.60), (1.6, 3.0), "LITERATURE", (8, 14)),
        "fabric.courtyard_islands": ((0.2787, 0.3082), (1.9643, 2.4636), "MEASURED_PRECEDENT", (8, 14)),
        "fabric.landscape_figure": ((0.2203, 0.3013), (0.7623, 1.5997), "MEASURED_PRECEDENT", (18, 28)),
    }
    expected_hashes = {
        "fabric.harbour_grain": "620c82044a3baac87a3d8dd5549028edc33b45ad3d298588f0864bda7c469347",
        "fabric.closed_block_extension": "d43aa89539375fcf9acc89d33fc04d488929573bba82cea474dd1262a350b46f",
        "fabric.courtyard_islands": "2661f9ae8087740fa78ec82a967fb742063691d2736049b80812fa8ab02cb7e5",
        "fabric.landscape_figure": "e82493aede0c0b3573eef2a0fa6c19d702fe28fd3bfbe04d22f86cea466e2fb0",
    }
    for fabric_id, (gsi, fsi, status, parks) in expected_density.items():
        fabric = SOURCE_FABRICS[fabric_id]
        assert fabric["density_targets"]["GSI"] == _density_target(*gsi, status=status)
        assert fabric["density_targets"]["FSI"] == _density_target(*fsi, status=status)
        assert fabric["land_use_budget"]["parks"] == {
            "minimum": parks[0],
            "maximum": parks[1],
            "unit": "percent_site_area",
            "status": "EDITORIAL",
        }
        assert fabric["fixture_source"]["snapshot_path"] == (
            f"artifacts/fab1/run-2/inputs/fabrics/{fabric_id}.json"
        )
        assert fabric["fixture_source"]["source_revision"] == _SOURCE_FABRIC_REVISION
        assert fabric["fixture_source"]["snapshot_sha256"] == expected_hashes[fabric_id]
    assert all(fabric["fixture_source"]["manifest_schema"] == _SNAPSHOT_SCHEMA for fabric in SOURCE_FABRICS.values())
    assert all(fabric["building_composition"]["components"] for fabric in SOURCE_FABRICS.values())
    assert all(fabric["open_space_system"]["types"] for fabric in SOURCE_FABRICS.values())


@pytest.mark.parametrize(
    "intent",
    [
        {"block_short_m": 68.7},
        {"block_long_m": 127.5},
        {"coverage_limit": 0.4},
    ],
)
def test_intent_values_outside_closed_contract_are_rejected(intent):
    facts = _facts(box(0, 0, 600, 280))
    with pytest.raises(ValueError, match="INTENT_OUT_OF_BOUNDS|UNKNOWN_INTENT_PARAMETER"):
        generate_plan(facts, _context(), copy.deepcopy(SOURCE_FABRICS["fabric.harbour_grain"]), intent=intent)



def test_per_block_ring_roads_fail_second_round_road_budget():
    """負控制：重現第一輪 12 m 環路，面積必須由線幾何重新計算。"""
    from shapely.geometry import LineString
    from urban_design.generation.fabric_plan import _validate_second_round
    site = box(0, 0, 240, 160)
    roads = []
    for x in (12, 92, 172):
        for y in (12, 92):
            ring = box(x, y, x + 56, y + 56).exterior
            roads.append({'id':f'ring-{len(roads)}', 'geometry':mapping(LineString(ring.coords)),
                          # Stale, underreported derived ROW must not hide the
                          # actual buffered area of the delivered centerline.
                          'properties':{'width_m':12, 'role':'block_edge_street',
                                        'right_of_way':mapping(box(0, 0, 1, 1))}})
    plan = _second_round_fixture(site)
    plan['roads'] = roads
    checks = _second_round_checks(plan)
    claimed_percent = 100 * sum(shape(r['properties']['right_of_way']).area for r in roads) / site.area
    assert claimed_percent < 1
    assert checks['ROAD_AREA_BUDGET']['percentage'] > 28
    assert not checks['ROAD_AREA_BUDGET']['passed']


def _second_round_fixture(site=box(0, 0, 100, 100), fabric_id="fabric.harbour_grain"):
    return {
        'site':mapping(site), 'water':mapping(GeometryCollection()),
        'waterfront_band':mapping(GeometryCollection()), 'roads':[], 'blocks':[],
        'boundary_parcels':[],
        'buildings':[], 'land_use':[], 'fabric_id':fabric_id,
        'fabric_dictionary':copy.deepcopy(SOURCE_FABRICS[fabric_id]),
        'context_reference':{'site':{'principal_axis':{'long_axis_length_m':100,'long_axis_azimuth_deg':90}}},
    }


def _second_round_checks(plan):
    from urban_design.generation.fabric_plan import _validate_second_round
    checks = {}
    def check(ident, passed, **evidence):
        checks[ident] = {'passed':bool(passed), **evidence}
    _validate_second_round(plan, check)
    return checks


def _test_feature(geometry, ident, **properties):
    if properties.get('role')=='primary_street':
        properties.setdefault('modes',['pedestrian','bicycle','car'])
    return {'id':ident, 'geometry':mapping(geometry), 'properties':properties}


def test_road_budget_recomputes_geometry_and_includes_waterfront_cap():
    from shapely.geometry import LineString
    plan = _second_round_fixture()
    plan['roads']=[_test_feature(LineString([(0,20),(100,20)]),'main',width_m=20,role='primary_street')]
    result=_second_round_checks(plan)
    assert result['ROAD_AREA_BUDGET']['passed']
    assert result['PRIMARY_STREET_THROUGH_SITE']['passed']
    plan['land_use']=[_test_feature(box(0,50,100,65),'quay',category='waterfront')]
    assert not _second_round_checks(plan)['ROAD_WATERFRONT_COMBINED_BUDGET']['passed']


@pytest.mark.parametrize('length,width',[(79,20),(100,17),(100,23)])
def test_short_or_wrong_width_primary_fails(length,width):
    from shapely.geometry import LineString
    plan=_second_round_fixture()
    plan['roads']=[_test_feature(LineString([(0,20),(length,20)]),'main',width_m=width,role='primary_street')]
    assert not _second_round_checks(plan)['PRIMARY_STREET_THROUGH_SITE']['passed']


def test_waterfront_width_and_unserved_shoreline_negative_controls():
    from shapely.geometry import LineString
    plan=_second_round_fixture()
    # The source band lies immediately landward of an actual water edge. An
    # empty water geometry would make the shoreline test vacuously pass.
    plan['water']=mapping(box(0,-20,100,0))
    band=box(0,0,100,12)
    plan['waterfront_band']=mapping(band)
    plan['land_use']=[_test_feature(band,'quay',category='waterfront')]
    plan['roads']=[_test_feature(LineString([(0,6),(100,6)]),'path',width_m=12,role='waterfront_path')]
    assert _second_round_checks(plan)['WATERFRONT_PUBLIC_BAND']['passed']
    plan['roads'][0]['properties']['width_m']=3
    assert not _second_round_checks(plan)['WATERFRONT_PUBLIC_BAND']['passed']
    plan['roads'][0]['properties']['width_m']=12
    # Missing shoreline access is the failure; unallocated area elsewhere in
    # the waterfront band does not substitute for this longitudinal check.
    plan['roads'][0]['geometry']=mapping(LineString([(0,6),(90,6)]))
    result=_second_round_checks(plan)['WATERFRONT_PUBLIC_BAND']
    assert not result['passed']
    assert result['unserved_shoreline_m'] > 0


def test_missing_waterfront_fails_cleanly_when_water_geometry_is_empty():
    # Empty water has no boundary in Shapely; absence of a waterfront must be
    # reported as a failed check rather than aborting unrelated validation.
    result = _second_round_checks(_second_round_fixture())['WATERFRONT_PUBLIC_BAND']
    assert not result['passed']
    assert result['components'] == 0
    assert result['unserved_shoreline_m'] == pytest.approx(0)


@pytest.mark.parametrize('geometry,reason',[(box(0,0,20,20),None),(box(0,0,10,40),'入口'),(box(0,0,30,30),'入口')])
def test_plaza_size_shape_reason_and_budget_negative_controls(geometry,reason):
    plan=_second_round_fixture()
    plan['land_use']=[_test_feature(geometry,'plaza',category='plazas',reason_zh=reason)]
    assert not _second_round_checks(plan)['PLAZA_BUDGET_AND_LOCATION']['passed']


@pytest.mark.parametrize('fid,park_area,passed',[('fabric.harbour_grain',800,True),('fabric.harbour_grain',1500,False),('fabric.landscape_figure',2000,True),('fabric.landscape_figure',1400,False),('fabric.landscape_figure',2600,False)])
def test_park_dictionary_and_landscape_task_range(fid,park_area,passed):
    plan=_second_round_fixture(fabric_id=fid)
    plan['land_use']=[_test_feature(box(0,0,100,park_area/100),'park',category='parks')]
    check = _second_round_checks(plan)['PARK_AREA_BUDGET']
    if fid == 'fabric.landscape_figure':
        # The task-specific 15–25% screen is reported beside, not substituted
        # into, the source dictionary's editorial 18–28% envelope.
        assert plan['fabric_dictionary']['land_use_budget']['parks']['minimum'] == 18
        assert plan['fabric_dictionary']['land_use_budget']['parks']['maximum'] == 28
        assert tuple(check['required_percent']) == (15, 25)
    assert check['passed'] is passed


def test_empty_or_low_coverage_block_and_large_service_plot_fail():
    plan=_second_round_fixture()
    block=box(0,0,60,60)
    plan['blocks']=[_test_feature(block,'block')]
    plan['land_use']=[_test_feature(block,'plot',category='blocks')]
    result=_second_round_checks(plan)
    assert not result['EVERY_BLOCK_BUILT_COVERAGE']['passed']
    assert not result['NO_LARGE_UNBUILT_PLOT']['passed']
    plan['buildings']=[_test_feature(box(0,0,60,10),'building',block_id='block',building_type='building.industrial_hall')]
    assert not _second_round_checks(plan)['EVERY_BLOCK_BUILT_COVERAGE']['passed']
    plan['buildings'][0]['geometry']=mapping(box(0,0,60,20))
    assert _second_round_checks(plan)['EVERY_BLOCK_BUILT_COVERAGE']['passed']
    plan['land_use'].append(_test_feature(box(60,0,100,60),'empty-service',category='service'))
    assert not _second_round_checks(plan)['NO_LARGE_UNBUILT_PLOT']['passed']


def test_boundary_parcel_has_real_parent_and_contained_building_geometry():
    from shapely.geometry import LineString
    plan = generate_plan(
        _facts(box(0, 0, 800, 500)),
        _context(),
        copy.deepcopy(SOURCE_FABRICS['fabric.closed_block_extension']),
    )
    parcel = box(0, 0, 40, 40)
    footprint = box(10, 4, 30, 36)
    plan['blocks'] = []
    plan['boundary_parcels'] = [
        _test_feature(parcel, 'parcel-1', template='orthogonal_rectangle', reason_zh='基地南側可建地')
    ]
    plan['buildings'] = [
        _test_feature(
            footprint,
            'building-1',
            block_id=None,
            parcel_id='parcel-1',
            retained=False,
            building_type='building.industrial_hall',
            use='industrial',
            floors=1,
            height_m=6,
            first_floor_height_m=6,
            depth_m=20,
        )
    ]
    plan['roads'] = [
        _test_feature(
            LineString([(0, 44), (40, 44)]),
            'parcel-frontage',
            width_m=8,
            role='boundary_plot_service_lane',
            modes=['pedestrian', 'bicycle', 'service', 'fire'],
        )
    ]

    assert parcel.area == 1600
    assert parcel.covers(footprint)
    assert footprint.area / parcel.area == pytest.approx(0.4)
    assert footprint.area / parcel.area == pytest.approx(
        plan['fabric_dictionary']['density_targets']['GSI']['range']['minimum']
    )
    assert validate_plan(plan)['checks']['BOUNDARY_PARCEL_SEMANTICS']['passed']

    invalid_metadata = copy.deepcopy(plan)
    invalid_metadata['buildings'][0]['properties']['parcel_id'] = 'missing-parcel'
    invalid_parent = validate_plan(invalid_metadata)['checks']['BOUNDARY_PARCEL_SEMANTICS']
    assert not invalid_parent['passed']
    assert 'building-1' in invalid_parent['failure_locations']

    out_of_parcel = copy.deepcopy(plan)
    out_of_parcel['buildings'].append(
        _test_feature(
            box(39, 35, 41, 37),
            'cross-boundary-building',
            block_id=None,
            parcel_id='parcel-1',
            retained=False,
            building_type='building.industrial_hall',
            use='industrial',
            floors=1,
            height_m=6,
            first_floor_height_m=6,
            depth_m=20,
        )
    )
    assert not parcel.covers(shape(out_of_parcel['buildings'][1]['geometry']))
    assert not validate_plan(out_of_parcel)['checks']['BOUNDARY_PARCEL_SEMANTICS']['passed']

    conflicting_parent = copy.deepcopy(plan)
    conflicting_parent['buildings'][0]['properties']['block_id'] = 'block-1'
    parent_result = validate_plan(conflicting_parent)['checks']['BOUNDARY_PARCEL_SEMANTICS']
    assert not parent_result['passed']
    assert 'building-1' in parent_result['failure_locations']

    overlapping_parcels = copy.deepcopy(plan)
    overlapping_parcels['boundary_parcels'].append(
        _test_feature(
            box(30, 0, 70, 40),
            'parcel-2',
            template='orthogonal_rectangle',
            reason_zh='相鄰獨立宗地',
        )
    )
    overlapping_parcels['buildings'].append(
        _test_feature(
            box(45, 4, 65, 36),
            'building-2',
            block_id=None,
            parcel_id='parcel-2',
            retained=False,
            building_type='building.industrial_hall',
            use='industrial',
            floors=1,
            height_m=6,
            first_floor_height_m=6,
            depth_m=20,
        )
    )
    assert overlapping_parcels['boundary_parcels'][0]['geometry'] != overlapping_parcels['boundary_parcels'][1]['geometry']
    assert shape(overlapping_parcels['boundary_parcels'][0]['geometry']).intersection(
        shape(overlapping_parcels['boundary_parcels'][1]['geometry'])
    ).area == 400
    overlap_result = validate_plan(overlapping_parcels)['checks']['BOUNDARY_PARCEL_SEMANTICS']
    assert not overlap_result['passed']
    assert {
        (row['parcel_id'], row['other_id'], row['overlap_m2'])
        for row in overlap_result['overlaps']
    } == {('parcel-1', 'parcel-2', 400)}

    public_row_crossing = copy.deepcopy(plan)
    public_row_crossing['roads'].append(
        _test_feature(
            LineString([(0, 2), (40, 2)]),
            'public-row-through-parcel',
            width_m=4,
            role='primary_street',
            modes=['pedestrian', 'bicycle', 'car'],
        )
    )
    row_result = validate_plan(public_row_crossing)['checks']['BOUNDARY_PARCEL_SEMANTICS']
    assert not row_result['passed']
    assert {
        (row['parcel_id'], row['other_id'], row['overlap_m2'])
        for row in row_result['overlaps']
    } == {('parcel-1', 'public_right_of_way', 160)}


def test_shared_courtyard_must_be_marked_contained_and_20_to_45m():
    plan=_second_round_fixture()
    plan['land_use']=[_test_feature(box(0,0,100,100),'plot',category='blocks')]
    plan['buildings']=[_test_feature(box(0,0,100,12),'b',building_type='building.courtyard_closed',block_id='block')]
    assert not _second_round_checks(plan)['SHARED_COURTYARD_MARKED_WIDTH']['passed']
    plan['courtyards']=[_test_feature(box(20,20,80,50),'court',label_zh='共用內院',block_id='block')]
    assert _second_round_checks(plan)['SHARED_COURTYARD_MARKED_WIDTH']['passed']
    plan['courtyards'][0]['geometry']=mapping(box(20,20,80,70))
    assert not _second_round_checks(plan)['SHARED_COURTYARD_MARKED_WIDTH']['passed']


def test_original_42_checks_remain_and_new_gfa_is_recomputed(rectangular_plan):
    original = {
        'ALL_BUILDINGS_FRONTAGE','BLOCK_DICTIONARY_DIMENSIONS','BLOCK_MINIMUM',
        'BLOCK_STREET_FRONTAGE','BUILDING_BUILDABLE','BUILDING_CONTAINMENT',
        'BUILDING_NO_OVERLAP','BUILDING_ROAD_CLEARANCE','CONNECTIVITY_BICYCLE',
        'CONNECTIVITY_CAR','CONNECTIVITY_FIRE','CONNECTIVITY_PEDESTRIAN',
        'CONNECTIVITY_SERVICE','COURTYARD_CLEAR_WIDTH','CRS','ENTRANCES_BICYCLE',
        'ENTRANCES_CAR','ENTRANCES_PEDESTRIAN','FIRE_ALL_EXTERIORS','FLOOR_HEIGHT',
        'GEOMETRY_VALID','HEIGHT_CAP','LAND_COVERAGE','LAND_MANAGEMENT',
        'LAND_NO_OVERLAP','LAND_SUM_100_PERCENT','LAND_USE_CATEGORIES',
        'MASSING_CORNERS','MEZZANINE_GEOMETRY','NEW_GFA_TARGET',
        'ORTHOGONAL_TEMPLATES','PARK_COHERENT_SHAPE','PARK_PRESENT',
        'PRIMARY_STREET_DICTIONARY','RETAINED_ROADS_PRESERVED','RETAINED_UNCHANGED',
        'SLAB_LENGTH_DEPTH','SLAB_SPACING','STREET_FRONTAGE','TERRACE_FRONTAGE',
        'WATERFRONT_CONTINUITY','WING_DEPTH',
    }
    assert len(original) == 42
    plan=copy.deepcopy(rectangular_plan)
    assert original <= validate_plan(plan)['checks'].keys()
    # 報表快取宣稱達標，實際建築樓地板為零，驗證器仍必須 FAIL。
    plan['buildings']=[]
    plan['metrics']['new_gfa_m2']=146873
    result=validate_plan(plan)
    assert not result['checks']['NEW_GFA_TARGET']['passed']
    assert result['checks']['NEW_GFA_TARGET']['new_gfa_m2']==0


def _park_semantics_plan(base_plan, geometry, *, street_frontage=True):
    """Build a focused public-validator fixture with a real adjacent street ROW."""
    from shapely.geometry import LineString

    plan = copy.deepcopy(base_plan)
    site = box(0, 0, 200, 160)
    plan['site'] = mapping(site)
    plan['water'] = mapping(GeometryCollection())
    plan['waterfront_band'] = mapping(GeometryCollection())
    plan['roads'] = []
    if street_frontage:
        plan['roads'] = [
            _test_feature(
                LineString([(20, 36), (60, 36)]),
                'park-frontage-street',
                width_m=8,
                role='block_edge_street',
                modes=['pedestrian', 'bicycle'],
            )
        ]
    plan['blocks'] = []
    plan['buildings'] = []
    plan['boundary_parcels'] = []
    plan['courtyards'] = []
    plan['land_use'] = [
        _test_feature(
            geometry,
            'synthetic-public-park',
            category='parks',
            manager='公共空間管理',
            role='公共連續公園',
            reason_zh='供周邊居民使用的連續公共綠地',
        )
    ]
    return plan


def test_triangular_public_park_with_usable_core_and_street_frontage_passes(rectangular_plan):
    from shapely.geometry import LineString

    triangle = Polygon([(20, 40), (60, 40), (20, 100)])
    row = _test_feature(
        # Four metres outside the park edge; the buffered public ROW reaches
        # the park boundary without consuming its usable interior.
        LineString([(20, 36), (60, 36)]),
        'park-frontage-street',
        width_m=8,
        role='block_edge_street',
        modes=['pedestrian', 'bicycle'],
    )
    row_of_way = shape(row['geometry']).buffer(row['properties']['width_m'] / 2, cap_style=2, join_style=2)
    usable_core = triangle.buffer(-7.5, join_style=2)

    assert triangle.is_valid and triangle.geom_type == 'Polygon'
    assert triangle.area == pytest.approx(1200)
    assert not usable_core.is_empty and len(_polygon_parts(usable_core)) == 1
    assert triangle.boundary.distance(row_of_way) == pytest.approx(0)

    plan = _park_semantics_plan(rectangular_plan, triangle)
    check = validate_plan(plan)['checks']['PARK_COHERENT_SHAPE']
    assert check['passed']
    evidence = next(item for item in check['park_geometry'] if item['park_id'] == 'synthetic-public-park')
    assert evidence['eroded_components'] == 1
    assert evidence['eroded_area_m2'] > 0
    assert evidence['frontage_distance_m'] <= 3.01


def test_narrow_necked_park_fails_even_when_it_is_one_valid_polygon(rectangular_plan):
    geometry = unary_union([
        box(20, 40, 60, 80),
        box(80, 40, 120, 80),
        box(60, 55, 80, 65),
    ])
    assert geometry.geom_type == 'Polygon' and geometry.is_valid
    assert geometry.area > 1000
    core = geometry.buffer(-7.5, join_style=2)
    assert len(_polygon_parts(core)) == 2

    plan = _park_semantics_plan(rectangular_plan, geometry)
    check = validate_plan(plan)['checks']['PARK_COHERENT_SHAPE']
    assert not check['passed']
    evidence = next(item for item in check['park_geometry'] if item['park_id'] == 'synthetic-public-park')
    assert evidence['eroded_components'] == 2


def test_long_narrow_park_fails_for_lacking_usable_width(rectangular_plan):
    strip = box(20, 40, 120, 50)
    assert strip.is_valid and strip.area == pytest.approx(1000)
    assert strip.buffer(-7.5, join_style=2).is_empty

    check = validate_plan(_park_semantics_plan(rectangular_plan, strip))['checks']['PARK_COHERENT_SHAPE']
    assert not check['passed']
    evidence = next(item for item in check['park_geometry'] if item['park_id'] == 'synthetic-public-park')
    assert evidence['eroded_area_m2'] == pytest.approx(0)


def test_disconnected_park_fragments_fail_the_single_park_contract(rectangular_plan):
    from shapely.geometry import MultiPolygon

    fragments = MultiPolygon([box(20, 40, 60, 80), box(80, 40, 120, 80)])
    assert fragments.is_valid and fragments.geom_type == 'MultiPolygon'
    assert fragments.area > 1000

    check = validate_plan(_park_semantics_plan(rectangular_plan, fragments))['checks']['PARK_COHERENT_SHAPE']
    assert not check['passed']
    evidence = next(item for item in check['park_geometry'] if item['park_id'] == 'synthetic-public-park')
    assert evidence['eroded_components'] == 2


def test_park_remnant_without_public_street_frontage_fails(rectangular_plan):
    remote_triangle = Polygon([(120, 80), (160, 80), (120, 140)])
    plan = _park_semantics_plan(rectangular_plan, remote_triangle, street_frontage=False)
    assert not plan['roads']
    check = validate_plan(plan)['checks']['PARK_COHERENT_SHAPE']
    assert not check['passed']
    assert 'synthetic-public-park' in check['failure_locations']


def test_park_far_from_an_actual_public_street_fails_frontage_distance(rectangular_plan):
    from shapely.geometry import LineString

    remote_triangle = Polygon([(120, 80), (160, 80), (120, 140)])
    plan = _park_semantics_plan(rectangular_plan, remote_triangle)
    plan['roads'][0]['geometry'] = mapping(LineString([(20, 10), (60, 10)]))

    check = validate_plan(plan)['checks']['PARK_COHERENT_SHAPE']
    assert not check['passed']
    evidence = next(item for item in check['park_geometry'] if item['park_id'] == 'synthetic-public-park')
    assert evidence['frontage_distance_m'] > 3.01


def test_original_park_area_floor_of_1000_square_metres_remains(rectangular_plan):
    undersized = Polygon([(20, 40), (60, 40), (20, 89)])
    assert undersized.is_valid
    assert undersized.area == pytest.approx(980)
    assert not undersized.buffer(-7.5, join_style=2).is_empty

    check = validate_plan(_park_semantics_plan(rectangular_plan, undersized))['checks']['PARK_COHERENT_SHAPE']
    assert not check['passed']
    evidence = next(item for item in check['park_geometry'] if item['park_id'] == 'synthetic-public-park')
    assert evidence['area_m2'] == pytest.approx(980)


def test_park_at_original_1000_square_metre_floor_can_pass(rectangular_plan):
    floor_area_triangle = Polygon([(20, 40), (60, 40), (20, 90)])
    assert floor_area_triangle.area == pytest.approx(1000)
    assert not floor_area_triangle.buffer(-7.5, join_style=2).is_empty

    check = validate_plan(
        _park_semantics_plan(rectangular_plan, floor_area_triangle)
    )['checks']['PARK_COHERENT_SHAPE']
    assert check['passed']


@pytest.mark.parametrize('metadata_field', ['manager', 'role', 'reason_zh'])
def test_public_park_requires_management_role_and_reason(rectangular_plan, metadata_field):
    triangle = Polygon([(20, 40), (60, 40), (20, 100)])
    plan = _park_semantics_plan(rectangular_plan, triangle)
    plan['land_use'][0]['properties'][metadata_field] = None

    check = validate_plan(plan)['checks']['PARK_COHERENT_SHAPE']
    assert not check['passed']
    assert 'synthetic-public-park' in check['failure_locations']


def _landscape_green_axis_plan(park_geometries, *, connector_geometries=(), roads=()):
    plan = _second_round_fixture(box(0, 0, 200, 100), fabric_id='fabric.landscape_figure')
    plan['land_use'] = [
        _test_feature(
            geometry,
            f'axis-park-{index}',
            category='parks',
            role='完整管理公園單元',
            manager='公共空間管理',
            reason_zh='沿公共綠軸管理的完整公園單元',
        )
        for index, geometry in enumerate(park_geometries)
    ]
    plan['green_axis_connectors'] = [
        _test_feature(
            geometry,
            f'green-connector-{index}',
            role='道路側綠軸接續帶',
            manager='公共空間管理',
            reason_zh='接續相鄰綠軸公園的實際綠帶',
        )
        for index, geometry in enumerate(connector_geometries)
    ]
    plan['roads'] = list(roads)
    return plan


def test_landscape_green_axis_accepts_connected_parks_connector_and_real_public_crossing():
    from shapely.geometry import LineString

    parks = [box(0, 40, 46, 60), box(54, 40, 72, 60), box(80, 40, 100, 60)]
    connector = box(72, 48, 80, 52)
    road = _test_feature(
        LineString([(50, 25), (50, 75)]),
        'green-axis-public-crossing',
        width_m=8,
        role='block_edge_street',
        modes=['pedestrian', 'bicycle'],
    )

    before_road_crossing = unary_union([*parks, connector])
    assert len(_polygon_parts(before_road_crossing)) == 2
    row = shape(road['geometry']).buffer(road['properties']['width_m'] / 2, cap_style=2, join_style=2)
    park_gap = LineString([(46, 50), (54, 50)])
    assert row.covers(park_gap)
    assert park_gap.length == pytest.approx(road['properties']['width_m'])

    check = _second_round_checks(
        _landscape_green_axis_plan(parks, connector_geometries=[connector], roads=[road])
    )['LANDSCAPE_GREEN_AXIS_CONTINUITY']
    assert check['passed']
    assert check['components_before_crossings'] == 2
    assert check['components_after_crossings'] == 1
    crossing = next(item for item in check['crossings'] if item['road_id'] == road['id'])
    assert crossing['gap_m'] == pytest.approx(8)
    assert crossing['width_m'] == pytest.approx(8)
    assert check['axis_span_m'] == pytest.approx(100)


def test_landscape_green_axis_rejects_large_middle_gap_despite_long_span():
    from shapely.geometry import LineString

    parks = [box(0, 40, 20, 60), box(149, 40, 169, 60)]
    road = _test_feature(
        LineString([(84.5, 25), (84.5, 75)]),
        'too-short-for-green-gap',
        width_m=20,
        role='block_edge_street',
        modes=['pedestrian', 'bicycle'],
    )
    nearest_green_connection = LineString([(20, 50), (149, 50)])
    row = shape(road['geometry']).buffer(road['properties']['width_m'] / 2, cap_style=2, join_style=2)
    assert nearest_green_connection.length == pytest.approx(129)
    assert not row.covers(nearest_green_connection)

    check = _second_round_checks(
        _landscape_green_axis_plan(parks, roads=[road])
    )['LANDSCAPE_GREEN_AXIS_CONTINUITY']
    assert not check['passed']
    assert check['components_before_crossings'] > 1
    assert check['components_after_crossings'] > 1
    assert check['axis_span_m'] == pytest.approx(169)


def test_landscape_green_axis_does_not_treat_long_span_or_private_row_as_continuity():
    from shapely.geometry import LineString

    parks = [box(0, 40, 46, 60), box(54, 40, 100, 60)]
    disconnected_connector = box(48, 48, 52, 52)
    private_lane = _test_feature(
        LineString([(50, 25), (50, 75)]),
        'private-green-axis-lane',
        width_m=8,
        role='boundary_plot_service_lane',
        modes=['pedestrian', 'service'],
    )
    raw_green = unary_union([*parks, disconnected_connector])
    assert len(_polygon_parts(raw_green)) == 3
    assert raw_green.bounds[2] - raw_green.bounds[0] == pytest.approx(100)
    private_row = shape(private_lane['geometry']).buffer(
        private_lane['properties']['width_m'] / 2, cap_style=2, join_style=2
    )
    assert private_row.covers(LineString([(46, 50), (54, 50)]))
    assert disconnected_connector.distance(parks[0]) == pytest.approx(2)
    assert disconnected_connector.distance(parks[1]) == pytest.approx(2)

    check = _second_round_checks(
        _landscape_green_axis_plan(
            parks,
            connector_geometries=[disconnected_connector],
            roads=[private_lane],
        )
    )['LANDSCAPE_GREEN_AXIS_CONTINUITY']
    assert not check['passed']
    assert check['components_before_crossings'] == 3
    assert check['components_after_crossings'] == 3
    assert check['axis_span_m'] == pytest.approx(100)


def _courtyard_island_plan(block_geometry, building_geometries, courtyard_geometries):
    plan = _second_round_fixture(block_geometry, fabric_id='fabric.courtyard_islands')
    plan['blocks'] = [_test_feature(block_geometry, 'island-block')]
    plan['buildings'] = [
        _test_feature(
            geometry,
            f'island-wing-{index}',
            block_id='island-block',
            building_type='building.courtyard_closed',
        )
        for index, geometry in enumerate(building_geometries)
    ]
    plan['land_use'] = [
        _test_feature(block_geometry, 'island-block-land', category='blocks', manager='街廓管理')
    ]
    plan['courtyards'] = [
        _test_feature(
            geometry,
            f'island-court-{index}',
            block_id='island-block',
            label_zh='共用內院',
            manager='街廓共用管理',
        )
        for index, geometry in enumerate(courtyard_geometries)
    ]
    return plan


def _courtyard_island_wings(*, width=75, length=115, maker_depth=20, wing_depth=14):
    return [
        box(0, 0, maker_depth, length),
        box(width - wing_depth, wing_depth, width, length - wing_depth),
        box(maker_depth, 0, width, wing_depth),
        box(maker_depth, length - wing_depth, width, length),
    ]


def test_courtyard_island_accepts_one_real_41_by_87_metre_void():
    block = box(0, 0, 75, 115)
    wings = _courtyard_island_wings()
    actual_void = box(20, 14, 61, 101)
    assert actual_void.area == pytest.approx(41 * 87)
    assert unary_union(wings).intersection(actual_void).area == pytest.approx(0)
    assert len(_polygon_parts(block.difference(unary_union(wings)))) == 1

    check = _second_round_checks(
        _courtyard_island_plan(block, wings, [actual_void])
    )['COURTYARD_ISLAND_SINGLE_VOID']
    assert check['passed']
    island = next(item for item in check['islands'] if item['block_id'] == 'island-block')
    assert island['marked_courtyard_count'] == 1
    assert island['whole_useful_void_count'] == 1
    assert island['whole_void_widths_m'] == pytest.approx([41])
    assert island['twenty_metre_core_components'] == [1]


def test_courtyard_island_rejects_large_real_void_hidden_by_20m_marking():
    block = box(0, 0, 100, 150)
    wings = _courtyard_island_wings(width=100, length=150, maker_depth=14, wing_depth=14)
    actual_void = box(14, 14, 86, 136)
    small_mark = box(40, 40, 60, 60)
    assert actual_void.area == pytest.approx(72 * 122)
    assert small_mark.area == pytest.approx(20 * 20)
    assert len(_polygon_parts(block.difference(unary_union(wings)))) == 1

    check = _second_round_checks(
        _courtyard_island_plan(block, wings, [small_mark])
    )['COURTYARD_ISLAND_SINGLE_VOID']
    assert not check['passed']
    island = next(item for item in check['islands'] if item['block_id'] == 'island-block')
    assert island['marked_courtyard_count'] == 1
    assert island['whole_useful_void_count'] == 1
    assert island['whole_void_widths_m'] == pytest.approx([72])
    assert island['twenty_metre_core_components'] == [1]


def test_courtyard_island_rejects_two_separate_useful_voids():
    block = box(0, 0, 75, 115)
    wings = _courtyard_island_wings()
    middle_wing = box(20, 50, 61, 64)
    first_court = box(30.5, 22, 50.5, 42)
    second_court = box(30.5, 72.5, 50.5, 92.5)
    assert len(_polygon_parts(block.difference(unary_union([*wings, middle_wing])))) == 2

    check = _second_round_checks(
        _courtyard_island_plan(block, [*wings, middle_wing], [first_court, second_court])
    )['COURTYARD_ISLAND_SINGLE_VOID']
    assert not check['passed']
    island = next(item for item in check['islands'] if item['block_id'] == 'island-block')
    assert island['marked_courtyard_count'] == 2
    assert island['whole_useful_void_count'] == 2
    assert sorted(island['whole_void_widths_m']) == pytest.approx([36, 37])
    assert island['twenty_metre_core_components'] == [1, 1]


def test_waterfront_width_metadata_cannot_hide_retained_building_obstruction():
    from shapely.geometry import LineString
    plan=_second_round_fixture()
    band=box(0,0,100,12)
    plan['water']=mapping(box(0,-20,100,0))
    plan['waterfront_band']=mapping(band)
    plan['land_use']=[_test_feature(band,'quay',category='waterfront')]
    plan['roads']=[_test_feature(LineString([(0,6),(100,6)]),'path',width_m=12,role='waterfront_path')]
    plan['buildings']=[_test_feature(box(40,8,60,20),'retained',retained=True)]
    result=_second_round_checks(plan)['WATERFRONT_PUBLIC_BAND']
    assert not result['passed']
    assert result['right_of_way_obstructions'][0]['building_overlaps'][0]['building_id']=='retained'


def test_waterfront_twelve_meter_claim_with_only_six_clear_meters_fails():
    from shapely.geometry import LineString
    plan = _second_round_fixture()
    band = box(0, 0, 100, 12)
    retained = box(0, 0, 100, 6)
    path = _test_feature(
        LineString([(0, 6), (100, 6)]),
        'path',
        width_m=12,
        role='waterfront_path',
    )
    plan['water'] = mapping(box(0, -20, 100, 0))
    plan['waterfront_band'] = mapping(band)
    plan['land_use'] = [_test_feature(band, 'quay', category='waterfront')]
    plan['roads'] = [path]
    plan['buildings'] = [_test_feature(retained, 'retained', retained=True)]

    effective_open_area = band.difference(retained).area
    effective_open_width = effective_open_area / shape(path['geometry']).length
    assert path['properties']['width_m'] == 12
    assert effective_open_width == pytest.approx(6)
    result = _second_round_checks(plan)['WATERFRONT_PUBLIC_BAND']
    assert not result['passed']
    assert result['right_of_way_obstructions'][0]['building_overlaps'][0]['building_id'] == 'retained'


def test_waterfront_clipped_row_cannot_use_metadata_to_claim_outside_land():
    from shapely.geometry import LineString
    site = box(0, 0, 100, 100)
    band = box(0, 0, 100, 6)
    plan = _second_round_fixture(site)
    path = _test_feature(
        LineString([(0, 0), (100, 0)]),
        'edge-path',
        width_m=12,
        role='waterfront_path',
    )
    raw_row = shape(path['geometry']).buffer(6, cap_style=2, join_style=2)
    clipped_row = raw_row.intersection(site)
    plan['water'] = mapping(box(0, -20, 100, 0))
    plan['waterfront_band'] = mapping(band)
    plan['land_use'] = [_test_feature(band, 'quay', category='waterfront')]
    plan['roads'] = [path]

    assert clipped_row.covers(band)
    assert raw_row.difference(site).area == pytest.approx(600)
    result = _second_round_checks(plan)['WATERFRONT_PUBLIC_BAND']
    assert not result['passed']
    assert result['right_of_way_obstructions'][0]['outside_land_m2'] == pytest.approx(600)


def test_internal_courtyard_service_path_is_block_use_and_reported_separately():
    from shapely.geometry import LineString
    plan=_second_round_fixture()
    plan['roads']=[
        _test_feature(LineString([(0,20),(100,20)]),'main',width_m=20,role='primary_street'),
        _test_feature(LineString([(0,60),(100,60)]),'court-fire',width_m=4,role='courtyard_fire_lane'),
    ]
    result=_second_round_checks(plan)['ROAD_AREA_BUDGET']
    assert result['passed']
    assert result['percentage']==pytest.approx(20)
    assert result['all_circulation_percent']==pytest.approx(24)
    assert 'courtyard_fire_lane' in result['excluded_internal_roles']


def test_primary_width_metadata_cannot_claim_land_outside_site():
    from shapely.geometry import LineString
    plan=_second_round_fixture()
    plan['roads']=[_test_feature(LineString([(0,2),(100,2)]),'main',width_m=18,role='primary_street')]
    result=_second_round_checks(plan)['PRIMARY_STREET_THROUGH_SITE']
    assert not result['passed']
    assert result['right_of_way_obstructions'][0]['outside_land_m2']>0


def test_primary_street_requires_walk_cycle_and_car_modes():
    from shapely.geometry import LineString
    plan=_second_round_fixture()
    plan['roads']=[_test_feature(LineString([(0,20),(100,20)]),'main',width_m=20,role='primary_street',modes=['pedestrian','bicycle'])]
    assert not _second_round_checks(plan)['PRIMARY_STREET_THROUGH_SITE']['passed']


def test_visibility_route_bends_around_fixed_obstacle_without_crossing_it():
    from shapely.geometry import Point
    from urban_design.generation.fabric_plan import _visible_route
    obstacle = box(40, 20, 60, 80)
    domain = box(0, 0, 100, 100).difference(obstacle)
    route = _visible_route(Point(10, 50), Point(90, 50), domain)
    assert route is not None
    assert len(route.coords) >= 4
    assert domain.buffer(1e-7).covers(route)
    assert route.length > 80


def test_full_width_waterfront_cannot_connect_disjoint_feasible_land():
    from shapely.geometry import Point
    from urban_design.generation.fabric_plan import _visible_route
    # A six-metre neck is real land but cannot carry a ten-metre public band.
    land = unary_union([box(0, 0, 40, 40), box(40, 17, 60, 23), box(60, 0, 100, 40)])
    feasible = land.buffer(-5.01, join_style=2)
    assert len(_polygon_parts(feasible)) == 2
    assert _visible_route(Point(20, 20), Point(80, 20), feasible) is None


def test_sub_decimetre_network_gap_does_not_report_a_discarded_connector_as_added():
    from shapely.geometry import LineString
    from urban_design.generation.fabric_plan import _components, _join_roads
    roads = [
        _test_feature(LineString([(0, 0), (10, 0)]), 'left', width_m=4, role='block_edge_street', modes=['car']),
        _test_feature(LineString([(10.06, 0), (20, 0)]), 'right', width_m=4, role='block_edge_street', modes=['car']),
    ]
    def add(line, width, role, modes=None, level=2):
        # Match the generator's minimum-length writer, which used to silently
        # discard the selected .06m link while join declared progress.
        if line.length > .1:
            roads.append(_test_feature(line, f'link-{len(roads)}', width_m=width, role=role, modes=['car']))
    _join_roads(roads, box(-5, -5, 25, 5), add, mode='car')
    assert len(roads) == 3
    assert shape(roads[-1]['geometry']).length > .1
    assert len(_components(roads)) == 1


def test_public_right_of_way_is_road_land_before_net_park_accounting():
    site = box(0, 0, 900, 400)
    water = box(0, 0, 500, 100)
    land = site.difference(water)
    facts = _facts(site)
    facts['geometry']['water'] = mapping(water)
    facts['geometry']['buildable'] = mapping(land)
    facts['geometry']['waterfront_band'] = mapping(water.buffer(15).intersection(land))
    plan = generate_plan(facts, _context(), copy.deepcopy(SOURCE_FABRICS['fabric.landscape_figure']))
    internal = {'courtyard_fire_lane', 'courtyard_service_gate', 'facade_service_spur', 'retained_service_lane', 'boundary_plot_service_lane', 'park_maintenance_path'}
    street = unary_union([
        shape(q['geometry']).buffer(q['properties']['width_m']/2, cap_style=2, join_style=2)
        for q in plan['roads'] if q['properties']['role'] not in internal
    ]).intersection(land)
    allocated = unary_union([
        shape(q['geometry']) for q in plan['land_use']
        if q['properties']['category'] in {'roads', 'waterfront'}
    ])
    mass = unary_union([shape(q['geometry']) for q in plan['buildings']])
    assert street.difference(mass).difference(allocated).area < .05
    park = unary_union([
        shape(q['geometry']) for q in plan['land_use'] if q['properties']['category'] == 'parks'
    ])
    assert park.intersection(street).area < .05


def _third_round_checks(plan):
    """第三輪檢查獨立以測試幾何執行，不讀預填報表數字。"""
    from urban_design.generation.fabric_plan import _validate_third_round
    checks = {}
    def check(ident, passed, **evidence):
        checks[ident] = {'passed': bool(passed), **evidence}
    _validate_third_round(plan, check)
    return checks


@pytest.mark.parametrize('service_percent,passed', [(0, True), (8, True), (8.01, False), (14.7, False)])
def test_fab1c_service_budget_recomputed_instead_of_cached_percentage(service_percent, passed):
    plan = _second_round_fixture()
    plan['land_use'] = [_test_feature(box(0, 0, 100, service_percent), 'service', category='service')]
    plan['metrics'] = {'service_percent': 0}
    result = _third_round_checks(plan)['SERVICE_AREA_BUDGET']
    assert result['percentage'] == pytest.approx(service_percent)
    assert result['passed'] is passed


@pytest.mark.parametrize('fid,percent,passed', [
    ('fabric.harbour_grain', 44.99, False), ('fabric.harbour_grain', 45, True),
    ('fabric.closed_block_extension', 45, True), ('fabric.courtyard_islands', 44, False),
    ('fabric.landscape_figure', 37.99, False), ('fabric.landscape_figure', 38, True),
])
def test_fab1c_block_land_budget_uses_task_threshold_and_actual_union(fid, percent, passed):
    plan = _second_round_fixture(fabric_id=fid)
    feature = _test_feature(box(0, 0, 100, percent), 'block-land', category='blocks')
    plan['land_use'] = [feature, copy.deepcopy(feature)]
    plan['metrics'] = {'block_land_percent': 100}
    result = _third_round_checks(plan)['BLOCK_LAND_BUDGET']
    assert result['percentage'] == pytest.approx(percent)
    assert result['passed'] is passed


def _fab1c_service_fixture():
    from shapely.geometry import LineString
    plan = _second_round_fixture()
    allocation = _test_feature(box(20, 20, 40, 40), 'loading-yard', category='service',
                               name_zh='街坊共用卸貨院', function='loading', manager='街廓管理',
                               role='卸貨院', reason_zh='服務相鄰廠房卸貨')
    plan['land_use'] = [allocation]
    plan['roads'] = [_test_feature(LineString([(0, 16), (100, 16)]), 'street',
                                    width_m=8, role='secondary_street', modes=['service','fire','pedestrian'])]
    plan['service_facilities'] = [_test_feature(box(20, 20, 40, 40), 'loading-facility',
                                                serves_allocation_id='loading-yard', function='loading',
                                                name_zh='街坊共用卸貨院')]
    return plan


def test_fab1c_service_function_requires_real_named_street_facing_use():
    plan = _fab1c_service_fixture()
    assert _third_round_checks(plan)['SERVICE_FUNCTION_FRONTAGE']['passed']
    for field in ('name_zh', 'function'):
        invalid = copy.deepcopy(plan)
        invalid['land_use'][0]['properties'].pop(field)
        invalid['service_facilities'][0]['properties'].pop(field)
        assert not _third_round_checks(invalid)['SERVICE_FUNCTION_FRONTAGE']['passed']
    invalid = copy.deepcopy(plan)
    invalid['roads'] = []
    assert not _third_round_checks(invalid)['SERVICE_FUNCTION_FRONTAGE']['passed']
    invalid = copy.deepcopy(plan)
    for row in invalid['land_use'] + invalid['service_facilities']:
        row['properties']['function'] = 'landscape_maintenance'
    assert not _third_round_checks(invalid)['SERVICE_FUNCTION_FRONTAGE']['passed']


def test_fab1c_large_park_or_plaza_must_have_name():
    plan = _second_round_fixture()
    plan['land_use'] = [_test_feature(box(0, 0, 60, 60), 'public-space', category='parks',
                                     manager='公共空間管理', role='完整公園', reason_zh='社區公共綠地')]
    assert not _second_round_checks(plan)['NO_LARGE_UNBUILT_PLOT']['passed']
    plan['land_use'][0]['properties']['name_zh'] = '港灣公園'
    assert _second_round_checks(plan)['NO_LARGE_UNBUILT_PLOT']['passed']


def _fab1c_islands(count=4, separation=20):
    from shapely.geometry import LineString
    plan = _second_round_fixture(box(0, 0, 1300, 300), fabric_id='fabric.courtyard_islands')
    plan['blocks'] = [_test_feature(box(i * (115 + separation), 20, i * (115 + separation) + 115, 95),
                                    f'island-{i}', axis_azimuth_deg=90) for i in range(count)]
    plan['roads'] = [_test_feature(LineString([(125 + i * (115 + separation), 0),
                                               (125 + i * (115 + separation), 150)]),
                                    f'separation-{i}', width_m=separation, role='secondary_street',
                                    modes=['pedestrian','bicycle','car']) for i in range(max(0, count-1))]
    plan['land_use'] = [_test_feature(box(115+i*(115+separation), 0, 115+i*(115+separation)+separation, 150),
                                     f'separation-land-{i}', category='roads') for i in range(max(0,count-1))]
    return plan


@pytest.mark.parametrize('count,passed', [(1,False),(3,False),(4,True),(7,True),(8,False)])
def test_fab1c_courtyard_island_count_requires_four_to_seven(count, passed):
    plan = _fab1c_islands(count)
    assert _third_round_checks(plan)['COURTYARD_ISLAND_COUNT_SPACING']['passed'] is passed


@pytest.mark.parametrize('gap', [10, 14.9, 25.1, 35])
def test_fab1c_courtyard_island_separation_cannot_be_hidden_by_metadata(gap):
    plan = _fab1c_islands(separation=gap)
    plan['metrics'] = {'island_spacing_m': 20}
    assert not _third_round_checks(plan)['COURTYARD_ISLAND_COUNT_SPACING']['passed']


def test_fab1c_courtyard_island_dimensions_are_measured():
    plan = _fab1c_islands()
    plan['blocks'][0]['geometry'] = mapping(box(0,20,114,94))
    plan['blocks'][0]['properties'].update(short_edge_m=75,long_edge_m=115)
    assert not _third_round_checks(plan)['COURTYARD_ISLAND_COUNT_SPACING']['passed']


def _fab1c_coastal_fixture():
    from shapely.geometry import LineString
    plan = _second_round_fixture(box(0,0,200,160))
    plan['water'] = mapping(box(0,-20,200,0))
    plan['waterfront_band'] = mapping(box(0,0,200,12))
    plan['context_reference']['site']['principal_axis']['long_axis_length_m'] = 200
    plan['roads'] = [
        _test_feature(LineString([(0,6),(70,6)]),'waterfront-west',width_m=12,role='waterfront_path',modes=['pedestrian','bicycle']),
        _test_feature(LineString([(110,6),(200,6)]),'waterfront-east',width_m=12,role='waterfront_path',modes=['pedestrian','bicycle']),
    ]
    plan['waterfront_detours'] = [_test_feature(LineString([(70,6),(90,12),(110,6)]),'marked-detour',
                                                width_m=4, name_zh='保留建築前步行繞道',length_m=1)]
    return plan


def test_fab1c_waterfront_detour_recomputes_route_length_and_endpoint_linkage():
    from shapely.geometry import LineString
    plan = _fab1c_coastal_fixture()
    result = _third_round_checks(plan)['WATERFRONT_DETOUR_GEOMETRY']
    assert result['passed']
    assert result['detours'][0]['length_m'] == pytest.approx(2*math.hypot(20,6))
    invalid = copy.deepcopy(plan)
    invalid['waterfront_detours'][0]['geometry'] = mapping(LineString([(70,6),(90,60),(110,6)]))
    assert not _third_round_checks(invalid)['WATERFRONT_DETOUR_GEOMETRY']['passed']
    invalid = copy.deepcopy(plan)
    invalid['waterfront_detours'][0]['geometry'] = mapping(LineString([(75,6),(90,12),(105,6)]))
    assert not _third_round_checks(invalid)['WATERFRONT_DETOUR_GEOMETRY']['passed']
    invalid = copy.deepcopy(plan)
    invalid['waterfront_detours'][0]['properties'].pop('name_zh')
    assert not _third_round_checks(invalid)['WATERFRONT_DETOUR_GEOMETRY']['passed']


def test_fab1c_waterfront_detour_cannot_cross_building_or_leave_land():
    from shapely.geometry import LineString
    plan = _fab1c_coastal_fixture()
    plan['buildings'] = [_test_feature(box(85,8,95,16),'fixed-obstacle',retained=True)]
    assert not _third_round_checks(plan)['WATERFRONT_DETOUR_GEOMETRY']['passed']
    plan['buildings'] = []
    plan['waterfront_detours'][0]['geometry'] = mapping(LineString([(70,6),(90,-10),(110,6)]))
    assert not _third_round_checks(plan)['WATERFRONT_DETOUR_GEOMETRY']['passed']


def test_fab1c_northeast_rejects_wrong_count_and_nonrectangular_fragments():
    plan = _fab1c_coastal_fixture()
    plan['blocks'] = [_test_feature(box(135,20+30*i,160,40+30*i),f'ne-{i}') for i in range(3)]
    assert _third_round_checks(plan)['NORTHEAST_REGULAR_BLOCKS']['passed']
    invalid = copy.deepcopy(plan)
    invalid['blocks'].pop()
    assert not _third_round_checks(invalid)['NORTHEAST_REGULAR_BLOCKS']['passed']
    invalid = copy.deepcopy(plan)
    invalid['blocks'][0]['geometry'] = mapping(Polygon([(135,20),(160,20),(145,40)]))
    assert not _third_round_checks(invalid)['NORTHEAST_REGULAR_BLOCKS']['passed']


def test_fab1c_service_facility_outside_parent_or_tiny_proxy_fails():
    plan = _fab1c_service_fixture()
    plan['service_facilities'][0]['geometry'] = mapping(box(39,20,59,40))
    assert not _third_round_checks(plan)['SERVICE_FUNCTION_FRONTAGE']['passed']
    plan['service_facilities'][0]['geometry'] = mapping(box(20,20,22,22))
    assert not _third_round_checks(plan)['SERVICE_FUNCTION_FRONTAGE']['passed']


def test_fab1c_south_quay_shared_alley_requires_actual_clear_width():
    from shapely.geometry import LineString
    plan = _fab1c_coastal_fixture()
    plan['south_quay_band'] = _test_feature(box(0,16,200,50),'south-quay',frontage_axis_azimuth_deg=90)
    plan['roads'].append(_test_feature(LineString([(0,54),(200,54)]),'shared-alley',width_m=8,
                                       role='south_quay_shared_alley',modes=['service','fire','pedestrian']))
    assert _third_round_checks(plan)['SOUTH_QUAY_SHARED_ALLEY']['passed']
    plan['roads'][-1]['properties']['width_m'] = 5
    assert not _third_round_checks(plan)['SOUTH_QUAY_SHARED_ALLEY']['passed']
    plan['roads'][-1]['properties']['width_m'] = 8
    plan['buildings'] = [_test_feature(box(50,52,100,60),'alley-obstacle')]
    assert not _third_round_checks(plan)['SOUTH_QUAY_SHARED_ALLEY']['passed']


@pytest.mark.parametrize('built_length,passed', [(119.9,False),(120,True),(160,True)])
def test_fab1c_south_quay_facade_coverage_measures_real_waterfront_face(built_length, passed):
    from shapely.geometry import LineString
    plan = _fab1c_coastal_fixture()
    plan['roads'] = [_test_feature(LineString([(0,6),(200,6)]),'public-waterfront',width_m=12,
                                   role='waterfront_path',modes=['pedestrian','bicycle'])]
    plan['south_quay_band'] = _test_feature(box(0,12,200,40),'south-quay',frontage_axis_azimuth_deg=90)
    plan['buildings'] = [_test_feature(box(0,12,built_length,32),'quay-building',retained=False,
                                       building_type='building.industrial_hall')]
    result = _third_round_checks(plan)['SOUTH_QUAY_FACADE_CONTINUITY']
    assert result['percentage'] == pytest.approx(built_length/2)
    assert result['passed'] is passed


def test_fab1c_south_quay_rear_building_or_tiny_band_overlap_does_not_count_as_frontage():
    from shapely.geometry import LineString
    plan = _fab1c_coastal_fixture()
    plan['roads'] = [_test_feature(LineString([(0,6),(200,6)]),'public-waterfront',width_m=12,
                                   role='waterfront_path',modes=['pedestrian','bicycle'])]
    plan['south_quay_band'] = _test_feature(box(0,12,200,40),'south-quay',frontage_axis_azimuth_deg=90)
    plan['buildings'] = [_test_feature(box(0,39.9,200,59.9),'rear-building',retained=False,
                                       building_type='building.industrial_hall')]
    assert not _third_round_checks(plan)['SOUTH_QUAY_FACADE_CONTINUITY']['passed']


@pytest.fixture(scope='module')
def fabric_runner_module():
    import importlib.util
    from pathlib import Path
    import sys
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'run_fabric_plan.py'
    spec = importlib.util.spec_from_file_location('fab1c_test_runner', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fab1c_landuse_renderer_never_calls_mobility_overlay(fabric_runner_module, monkeypatch):
    from shapely.geometry import LineString
    runner = fabric_runner_module
    def forbidden_overlay(*args, **kwargs):
        pytest.fail('土地使用圖呼叫了交通模式彩線繪製器')
    monkeypatch.setattr(runner, '_draw_mode_access_strokes', forbidden_overlay)
    site = box(0,0,200,100)
    plan = _second_round_fixture(site)
    plan['roads'] = [_test_feature(LineString([(0,40),(200,40)]),'main',role='primary_street',
                                   width_m=20,modes=['pedestrian','bicycle','car'],hierarchy=0)]
    audit = {}
    image = runner._map_image(title='第三輪土地使用圖負控制', note='', facts=_facts(site),plan=plan,
                              canvas_size=(900,600),show_side_panel=False,mode='landuse',render_audit=audit)
    assert image.size == (900,600)
    assert audit['mode_overlay_render']['mode_overlay_line_segments_drawn'] == 0
    assert audit['mobility_overlay_status'] == 'PASS'


def test_fab1c_mobility_renderer_calls_each_full_permitted_network(fabric_runner_module, monkeypatch):
    from shapely.geometry import LineString
    runner = fabric_runner_module
    observed = []
    original = runner._draw_mode_access_strokes
    def record(draw, coords, modes, transform):
        observed.append((list(coords),list(modes)))
        return original(draw,coords,modes,transform)
    monkeypatch.setattr(runner,'_draw_mode_access_strokes',record)
    site = box(0,0,200,100)
    plan = _second_round_fixture(site)
    coords = [(0,40),(100,40),(200,40)]
    plan['roads'] = [_test_feature(LineString(coords),'main',role='primary_street',width_m=20,
                                   modes=['pedestrian','bicycle','car'],hierarchy=0)]
    audit = {}
    runner._map_image(title='第三輪交通方式圖',note='',facts=_facts(site),plan=plan,
                       canvas_size=(900,600),show_side_panel=False,mode='mobility',render_audit=audit)
    assert observed == [(coords,['pedestrian','bicycle','car'])]
    assert audit['mode_overlay_render']['mode_overlay_line_segments_drawn'] == 6
    assert set(audit['available_modes']) == {'pedestrian','bicycle','car'}


def test_fab1c_retains_all_second_round_gates_and_reports_new_global_gates(rectangular_plan):
    result = validate_plan(rectangular_plan)
    required = {
        'BOUNDARY_PARCEL_SEMANTICS','ROAD_AREA_BUDGET','ROAD_WATERFRONT_COMBINED_BUDGET',
        'WATERFRONT_PUBLIC_BAND','PRIMARY_STREET_THROUGH_SITE','PLAZA_BUDGET_AND_LOCATION',
        'PARK_AREA_BUDGET','EVERY_BLOCK_BUILT_COVERAGE','NO_LARGE_UNBUILT_PLOT',
        'SHARED_COURTYARD_MARKED_WIDTH','SERVICE_AREA_BUDGET','SERVICE_FUNCTION_FRONTAGE',
        'BLOCK_LAND_BUDGET','SOUTH_QUAY_SHARED_ALLEY','SOUTH_QUAY_FACADE_CONTINUITY',
        'NORTHEAST_REGULAR_BLOCKS','WATERFRONT_DETOUR_GEOMETRY',
        'BUILDING_STREET_EDGE_3M','NORTHEAST_NO_SMALL_BUILDING_BLOCKS','SOUTH_QUAY_MAX_GAP',
    }
    assert required <= result['checks'].keys()
    assert 'MALFORMED_PLAN' not in result['checks']


def _fab1c_six_floor_plan(base_plan):
    plan = copy.deepcopy(base_plan)
    plan['fabric_id'] = 'fabric.landscape_figure'
    plan['fabric_dictionary'] = copy.deepcopy(SOURCE_FABRICS['fabric.landscape_figure'])
    plan['parameters']['point_floor_height_assumption'] = {
        'version':'fab1c-point-six-storey-v1','ground_floor_m':4.,'upper_floor_m':3.2,
        'maximum_floors':6,'maximum_height_m':20.,'basis':'本輪明列探索設定',
    }
    plan['buildings'] = [_test_feature(box(60,80,80,100),'six-floor-point',
                                      block_id=plan['blocks'][0]['id'],retained=False,
                                      building_type='building.point_array',use='residential',depth_m=20,
                                      floors=6,height_m=20,first_floor_height_m=4,
                                      standard_floor_height_m=3.2,max_floors=6,
                                      floor_height_assumption_version='fab1c-point-six-storey-v1')]
    return plan


def test_fab1c_six_floors_require_explicit_profile_real_height_and_correct_fabric(rectangular_plan):
    plan = _fab1c_six_floor_plan(rectangular_plan)
    assert validate_plan(plan)['checks']['FLOOR_HEIGHT']['passed']
    for field, value in [('height_m',19),('standard_floor_height_m',3.5),
                         ('floor_height_assumption_version','unknown'),('building_type','building.i_slab')]:
        invalid = copy.deepcopy(plan)
        invalid['buildings'][0]['properties'][field] = value
        assert not validate_plan(invalid)['checks']['FLOOR_HEIGHT']['passed']
    invalid = copy.deepcopy(plan)
    invalid['fabric_id'] = 'fabric.harbour_grain'
    assert not validate_plan(invalid)['checks']['FLOOR_HEIGHT']['passed']
    invalid = copy.deepcopy(plan)
    invalid['parameters'].pop('point_floor_height_assumption')
    assert not validate_plan(invalid)['checks']['FLOOR_HEIGHT']['passed']


@pytest.mark.parametrize('gfa,expected', [(146873*.85-.1,False), (146873*.85,True), (146873*.85+.1,True), (146873+.1,False)])
def test_fab1c_new_gfa_exact_minimum_does_not_round_up(rectangular_plan,gfa,expected):
    plan = copy.deepcopy(rectangular_plan)
    area = gfa / 5
    plan['buildings'] = [_test_feature(box(0,0,area/200,200),'slightly-under-target',
                                      block_id=plan['blocks'][0]['id'],retained=False,
                                      building_type='building.courtyard_closed',use='residential',depth_m=14,
                                      floors=5,height_m=18,first_floor_height_m=4,
                                      standard_floor_height_m=3.5,max_floors=5)]
    check = validate_plan(plan)['checks']['NEW_GFA_TARGET']
    assert check['new_gfa_m2'] == pytest.approx(gfa)
    assert check['passed'] is expected


def test_fab1c_runner_requires_island_gate_only_for_islands_and_preserves_conditional_gates(fabric_runner_module):
    runner = fabric_runner_module
    core_ids = set(runner._required_core_check_ids('harbour_grain'))
    assert 'COURTYARD_ISLAND_COUNT_SPACING' not in core_ids
    checks = {'passed':True,'status':'PASS','failure_ids':[],
              'checks':{key:{'passed':True,'status':'PASS'} for key in core_ids}}
    summary = {'fabric_id':'harbour_grain','core_checks':checks,
               'runner_checks':{
                   'LANDUSE_NO_MOBILITY_OVERLAY':{'passed':True,'status':'PASS'},
                   'WATERFRONT_DETOUR_MARKED':{'passed':True,'status':'PASS','expected_ids':[]},
                   'MAP_TEXT_LABEL_LIMIT':{'passed':True,'counts':{'landuse':10,'mobility':7},'maximum':10,'status':'PASS'},
               }}
    assert runner._fab1c_case_status(summary) == ('PASS',[])
    invalid = copy.deepcopy(summary)
    invalid['fabric_id'] = 'courtyard_islands'
    assert runner._fab1c_case_status(invalid)[0] == 'FAIL'
    assert 'COURTYARD_ISLAND_SINGLE_VOID' in runner._required_core_check_ids('courtyard_islands')
    assert 'LANDSCAPE_GREEN_AXIS_CONTINUITY' in runner._required_core_check_ids('landscape_figure')
    invalid = copy.deepcopy(summary)
    invalid['core_checks']['checks'].pop('SERVICE_AREA_BUDGET')
    assert runner._fab1c_case_status(invalid)[0] == 'FAIL'
    invalid = copy.deepcopy(summary)
    invalid['runner_checks']['LANDUSE_NO_MOBILITY_OVERLAY']['passed'] = False
    assert runner._fab1c_case_status(invalid)[0] == 'FAIL'
    invalid = copy.deepcopy(summary)
    invalid['runner_checks']['WATERFRONT_DETOUR_MARKED']['passed'] = False
    assert runner._fab1c_case_status(invalid)[0] == 'FAIL'
    invalid = copy.deepcopy(summary)
    invalid['runner_checks'].pop('WATERFRONT_DETOUR_MARKED')
    status, failures = runner._fab1c_case_status(invalid)
    assert status == 'FAIL'
    assert 'WATERFRONT_DETOUR_MARKED' in failures
    invalid = copy.deepcopy(summary)
    invalid['runner_checks']['MAP_TEXT_LABEL_LIMIT']['passed'] = False
    invalid['runner_checks']['MAP_TEXT_LABEL_LIMIT']['counts']['landuse'] = 11
    assert runner._fab1c_case_status(invalid)[0] == 'FAIL'
    invalid = copy.deepcopy(summary)
    invalid['runner_checks'].pop('MAP_TEXT_LABEL_LIMIT')
    status, failures = runner._fab1c_case_status(invalid)
    assert status == 'FAIL'
    assert 'MAP_TEXT_LABEL_LIMIT' in failures


def test_fab1c_courtyard_count_cannot_hide_many_non_island_mainland_parcels():
    plan = _fab1c_islands()
    plan['buildings'] = [_test_feature(box(20,30,40,50),'island-member',block_id='island-0',retained=False)]
    assert _third_round_checks(plan)['COURTYARD_ISLAND_COUNT_SPACING']['passed']
    plan['buildings'].append(_test_feature(box(1000,20,1020,40),'small-mainland-plot',
                                         block_id=None,parcel_id='tiny-plot',retained=False))
    plan['boundary_parcels'] = [_test_feature(box(990,10,1030,50),'tiny-plot')]
    assert not _third_round_checks(plan)['COURTYARD_ISLAND_COUNT_SPACING']['passed']


def test_fab1c_island_separation_can_be_public_green_but_not_private_plot():
    plan = _fab1c_islands()
    plan['roads'] = []
    for row in plan['land_use']:
        row['properties'].update(category='parks',manager='公共空間管理',name_zh='島間公共綠帶',role='公共綠帶')
    assert _third_round_checks(plan)['COURTYARD_ISLAND_COUNT_SPACING']['passed']
    for row in plan['land_use']:
        row['properties'].update(category='blocks',manager='街廓管理')
    assert not _third_round_checks(plan)['COURTYARD_ISLAND_COUNT_SPACING']['passed']


def test_fab1c_island_dimensions_cannot_include_public_road_edge():
    from shapely.geometry import LineString
    plan = _fab1c_islands()
    assert _third_round_checks(plan)['COURTYARD_ISLAND_ROAD_CLEARANCE']['passed']
    plan['roads'].append(_test_feature(LineString([(0,22),(115,22)]), 'edge-cutting-main-street',
                                       width_m=18,role='primary_street',modes=['pedestrian','bicycle','car']))
    assert not _third_round_checks(plan)['COURTYARD_ISLAND_ROAD_CLEARANCE']['passed']


def test_fab1c_frozen_inputs_are_copied_and_tampering_is_rejected(fabric_runner_module, tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    runner = fabric_runner_module
    actual = Path(runner.OUTPUT_DIR) / 'run-2' / 'inputs'
    copied_root = tmp_path / 'artifacts'
    shutil.copytree(actual, copied_root / 'run-2' / 'inputs')
    monkeypatch.setattr(runner, 'OUTPUT_DIR', copied_root)
    monkeypatch.setattr(runner, 'INPUTS_DIR', copied_root / 'run-3' / 'inputs')
    manifest = runner.load_frozen_run2_snapshot()
    assert (runner.INPUTS_DIR / 'manifest.json').read_bytes() == (actual / 'manifest.json').read_bytes()
    record = manifest['files'][0]
    source = copied_root / record['snapshot_path']
    archived = runner.INPUTS_DIR / source.relative_to(copied_root / 'run-2' / 'inputs')
    assert archived.read_bytes() == source.read_bytes()
    source.write_bytes(source.read_bytes() + b' ')
    with pytest.raises(ValueError, match='SHA-256'):
        runner.load_frozen_run2_snapshot()


def _fab1c_capacity_plot():
    from shapely.geometry import LineString
    plan=_second_round_fixture(box(0,0,400,150),fabric_id='fabric.landscape_figure')
    plan['buildable']=plan['site'];plan['parameters']={}
    plan['boundary_parcels']=[_test_feature(box(20,40,110,70),'western-plot',reason_zh='實際西側宗地')]
    plan['buildings']=[_test_feature(box(25,48,105,62),'old-slab',parcel_id='western-plot',block_id=None,
                                   retained=False,building_type='building.i_slab',depth_m=14,floors=5,height_m=18,
                                   first_floor_height_m=4,standard_floor_height_m=3.5,max_floors=5)]
    plan['roads']=[_test_feature(LineString([(0,74),(400,74)]),'public-street',width_m=6,
                               role='secondary_street',modes=['pedestrian','bicycle','car','service','fire'])]
    plan['land_use']=[_test_feature(box(20,40,110,70),'managed-plot',category='blocks',manager='街坊共用管理')]
    return plan


def test_fab1c_capacity_repacking_counts_real_points_and_preserves_input():
    from urban_design.generation.fabric_plan import _reconfigure_landscape_capacity
    plan=_fab1c_capacity_plot();before=copy.deepcopy(plan)
    result=_reconfigure_landscape_capacity(plan)
    assert plan==before
    assert len(result['buildings'])==4
    assert sum(shape(b['geometry']).area*b['properties']['floors'] for b in result['buildings'])==pytest.approx(9600)
    for b in result['buildings']:
        assert shape(b['geometry']).area==pytest.approx(400)
        assert b['properties']['height_m']==20
        assert shape(plan['buildable']).covers(shape(b['geometry']))
    row=next(r for r in result['roads'] if r['id']=='public-street')
    assert row==before['roads'][0]


def test_fab1c_capacity_repacking_cannot_cross_public_road_to_invent_capacity():
    from shapely.geometry import LineString
    from urban_design.generation.fabric_plan import _reconfigure_landscape_capacity
    plan=_fab1c_capacity_plot()
    plan['roads'].append(_test_feature(LineString([(0,55),(400,55)]),'protected-crossing',width_m=8,
                                       role='secondary_street',modes=['pedestrian','bicycle','car']))
    result=_reconfigure_landscape_capacity(plan)
    assert result['buildings']==plan['buildings']
    assert next(r for r in result['roads'] if r['id']=='protected-crossing')==plan['roads'][-1]


def _fourth_round_checks(plan):
    """第四輪新增檢查直接重算輸入幾何，不讀核心快取。"""
    from urban_design.generation.fabric_plan import _validate_fourth_round
    checks = {}

    def check(ident, passed, **evidence):
        checks[ident] = {'passed': bool(passed), **evidence}

    _validate_fourth_round(plan, check)
    return checks


def _fab1d_frontage_plan():
    plan = _second_round_fixture(box(0, 0, 100, 100))
    plan['buildings'] = [_test_feature(box(20, 20, 40, 40), 'new-building', retained=False)]
    return plan


def test_fab1d_building_frontage_passes_with_one_real_metre_or_more():
    from shapely.geometry import LineString
    plan = _fab1d_frontage_plan()
    plan['roads'] = [_test_feature(LineString([(0, 17), (60, 17)]), 'public-street',
                                  width_m=2, role='secondary_street')]
    result = _fourth_round_checks(plan)['BUILDING_STREET_EDGE_3M']
    assert result['passed']
    assert result['buildings'][0]['fronting_edge_length_m'] >= 1
    assert result['buildings'][0]['street_distance_m'] <= 3


def test_fab1d_isolated_building_and_submetre_public_spur_fail_frontage():
    from shapely.geometry import LineString
    isolated = _fab1d_frontage_plan()
    assert not _fourth_round_checks(isolated)['BUILDING_STREET_EDGE_3M']['passed']

    short_spur = _fab1d_frontage_plan()
    # The .71 m diagonal public spur approaches the building's outer corner
    # within 3 m, while less than 1 m of either exterior edge is supported.
    short_spur['roads'] = [_test_feature(LineString([(17.385, 17.385), (17.885, 17.885)]), 'short-public-spur',
                                         width_m=2, role='secondary_street')]
    check = _fourth_round_checks(short_spur)['BUILDING_STREET_EDGE_3M']
    assert not check['passed']
    assert check['buildings'][0]['street_distance_m'] <= 3
    assert check['buildings'][0]['fronting_edge_length_m'] < 1


@pytest.mark.parametrize('role', [
    'facade_service_spur', 'retained_service_lane', 'boundary_plot_service_lane',
    'courtyard_fire_lane', 'courtyard_service_gate', 'park_maintenance_path',
])
def test_fab1d_internal_service_roads_cannot_supply_public_building_frontage(role):
    from shapely.geometry import LineString
    plan = _fab1d_frontage_plan()
    plan['roads'] = [_test_feature(LineString([(0, 17), (60, 17)]), 'internal-road',
                                  width_m=2, role=role)]
    check = _fourth_round_checks(plan)['BUILDING_STREET_EDGE_3M']
    assert not check['passed']
    assert check['buildings'][0]['street_distance_m'] is None


def _fab1d_northeast_plan():
    plan = _second_round_fixture(box(0, 0, 1000, 300))
    plan['water'] = mapping(box(0, -20, 1000, 0))
    plan['waterfront_band'] = mapping(box(0, 0, 1000, 12))
    # run3's northeast zone starts at 62% of the site along its long axis.
    plan['blocks'] = [
        _test_feature(box(650, 30, 700, 70), 'large-ne-west'),
        _test_feature(box(750, 130, 800, 170), 'large-ne-east'),
    ]
    plan['buildings'] = [
        _test_feature(box(660, 40, 690, 60), 'large-ne-building-1', retained=False),
        _test_feature(box(760, 140, 790, 160), 'large-ne-building-2', retained=False),
    ]
    return plan


def test_fab1d_northeast_accepts_assigned_buildings_in_large_blocks():
    check = _fourth_round_checks(_fab1d_northeast_plan())['NORTHEAST_NO_SMALL_BUILDING_BLOCKS']
    assert check['passed']
    assert check['minimum_block_area_m2'] == 1500


@pytest.mark.parametrize('fragment_kind', ['small_building_block', 'unassigned_building'])
def test_fab1d_northeast_rejects_small_or_unassigned_building_fragments(fragment_kind):
    plan = _fab1d_northeast_plan()
    if fragment_kind == 'small_building_block':
        plan['blocks'].append(_test_feature(box(850, 30, 870, 55), 'tiny-ne-block'))
        plan['buildings'].append(_test_feature(box(854, 34, 866, 50), 'tiny-ne-building', retained=False))
    else:
        plan['buildings'].append(_test_feature(box(880, 210, 910, 240), 'unassigned-ne-building', retained=False))
    check = _fourth_round_checks(plan)['NORTHEAST_NO_SMALL_BUILDING_BLOCKS']
    assert not check['passed']
    assert check['failure_locations']


def test_fab1d_waterfront_accepts_named_legal_connected_four_metre_bypass_and_keeps_unserved_measure():
    from shapely.geometry import LineString
    plan = _fab1c_coastal_fixture()
    # A retained barrier makes the ten-metre eroded feasible land split into
    # two components; the bypass still follows legal land and connects both
    # measured waterfront segments.
    plan['buildings'] = [_test_feature(box(95, 10, 105, 160), 'retained-divider', retained=True)]
    plan['waterfront_detours'] = [_test_feature(
        LineString([(70, 6), (70.5, 5), (80, 5), (80.5, 6), (110, 6)]),
        'named-shoreline-bypass', width_m=4,
        purpose='shoreline_bypass', name_zh='西南連通步行替代路徑',
    )]
    check = _second_round_checks(plan)['WATERFRONT_PUBLIC_BAND']
    assert check['passed']
    assert check['founder_run4_exception_applied']
    assert check['unserved_shoreline_m'] > 0
    assert check['remaining_unserved_shoreline_m'] > 0
    assert '未服務岸線' in check['exception_basis_zh']


@pytest.mark.parametrize('damage', ['missing_name', 'over_60m'])
def test_fab1d_unmarked_or_overlength_waterfront_bypass_fails(damage):
    from shapely.geometry import LineString
    plan = _fab1c_coastal_fixture()
    plan['buildings'] = [_test_feature(box(95, 10, 105, 160), 'retained-divider', retained=True)]
    geometry = LineString([(70, 6), (70.5, 5), (109.5, 5), (110, 6)])
    properties = {'width_m': 4, 'purpose': 'shoreline_bypass', 'name_zh': '合法替代路徑'}
    if damage == 'over_60m':
        points = [(70, 6), (70.5, 5)]
        points.extend((71 + index, 7.5 if index % 2 == 0 else 5) for index in range(20))
        points.append((110, 6))
        geometry = LineString(points)
    else:
        properties.pop('name_zh')
    plan['waterfront_detours'] = [_test_feature(geometry, 'invalid-shoreline-bypass', **properties)]
    assert not _second_round_checks(plan)['WATERFRONT_PUBLIC_BAND']['passed']
    assert not _third_round_checks(plan)['WATERFRONT_DETOUR_GEOMETRY']['passed']


def _fab1d_south_quay_plan(gap_m):
    from shapely.geometry import LineString
    plan = _second_round_fixture(box(0, 0, 200, 160))
    plan['water'] = mapping(box(0, -20, 200, 0))
    plan['waterfront_band'] = mapping(box(0, 0, 200, 12))
    plan['roads'] = [_test_feature(LineString([(0, 6), (200, 6)]), 'public-waterfront',
                                  width_m=12, role='waterfront_path')]
    plan['south_quay_band'] = _test_feature(
        box(0, 12, 200, 40), 'south-quay', frontage_side='min_y', frontage_axis_azimuth_deg=90,
    )
    plan['buildings'] = [
        _test_feature(box(0, 12, 50, 32), 'quay-west', retained=False),
        _test_feature(box(50 + gap_m, 12, 200, 32), 'quay-east', retained=False),
    ]
    return plan


@pytest.mark.parametrize('gap_m,passed', [(12.0, True), (12.01, False)])
def test_fab1d_waterfront_facade_gap_is_measured_on_actual_projected_frontage(gap_m, passed):
    result = _fourth_round_checks(_fab1d_south_quay_plan(gap_m))['SOUTH_QUAY_MAX_GAP']
    assert result['passed'] is passed
    assert result['maximum_gap_m'] == pytest.approx(gap_m, abs=1e-4)


def test_fab1d_map_text_audit_counts_positioned_chinese_labels_and_keeps_facilities_symbol_only(fabric_runner_module):
    from shapely.geometry import LineString, Point
    runner = fabric_runner_module
    site = box(0, 0, 200, 100)
    plan = _second_round_fixture(site)
    plan['waterfront_detours'] = [
        _test_feature(LineString([(10, 20 + index * 5), (30, 20 + index * 5)]), f'detour-{index}',
                      width_m=4, length_m=20, name_zh=f'替代路徑{index}')
        for index in range(11)
    ]
    plan['service_facilities'] = [_test_feature(Point(100, 50), 'facility-symbol',
                                                function='loading', name_zh='卸貨設施')]
    audit = {}
    runner._map_image(title='第四輪標注負控制', note='', facts=_facts(site), plan=plan,
                      canvas_size=(900, 600), show_side_panel=True, mode='landuse', render_audit=audit)
    assert audit['map_text_annotation_count'] == 11
    assert audit['service_facilities'][0]['symbol_only'] is True
    expected = {f'detour-{index}' for index in range(11)}
    assert {row['feature_id'] for row in audit['waterfront_detours']['labels']} == expected
    mobility_audit = {}
    runner._map_image(title='第四輪交通路徑標示', note='', facts=_facts(site), plan=plan,
                      canvas_size=(900, 600), show_side_panel=True, mode='mobility', render_audit=mobility_audit)
    assert {row['feature_id'] for row in mobility_audit['waterfront_detours']['labels']} == expected


def test_fab1d_case_status_fails_closed_without_map_text_gate(fabric_runner_module):
    runner = fabric_runner_module
    core_ids = set(runner._required_core_check_ids('harbour_grain'))
    checks = {'passed': True, 'status': 'PASS', 'failure_ids': [],
              'checks': {key: {'passed': True, 'status': 'PASS'} for key in core_ids}}
    summary = {'fabric_id': 'harbour_grain', 'core_checks': checks,
               'runner_checks': {
                   runner.LANDUSE_NO_MOBILITY_OVERLAY: {'passed': True},
                   runner.WATERFRONT_DETOUR_MARKED: {'passed': True},
               }}
    status, failures = runner._fab1c_case_status(summary)
    assert status == 'FAIL'
    assert runner.MAP_TEXT_LABEL_LIMIT in failures


def test_compare_plans_ignores_block_axis_metadata_when_delivered_roads_are_identical(rectangular_plan):
    baseline = copy.deepcopy(rectangular_plan)
    metadata_only = copy.deepcopy(rectangular_plan)
    metadata_only['block_axis_azimuth_deg'] = (metadata_only['block_axis_azimuth_deg'] + 37) % 180
    for block in metadata_only['blocks']:
        block['properties']['axis_azimuth_deg'] = 37

    comparison = compare_plans([baseline, metadata_only])
    pair = comparison['pairwise'][0]
    assert pair['direction_difference_deg'] == pytest.approx(0, abs=1e-8)
    assert pair['measured_road_frame_deg'][0] == pytest.approx(pair['measured_road_frame_deg'][1])
    assert pair['dimensions_distinct'] == {'road_direction': False, 'block_size': False, 'type_mix': False}
    assert not pair['distinct']
    assert comparison['winner'] is None
