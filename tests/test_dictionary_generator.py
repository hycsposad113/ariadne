from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from shapely.affinity import rotate, translate
from shapely.geometry import GeometryCollection, MultiPolygon, Point, box

from urban_design.morphology.dictionary_generator import (
    ExternalContact,
    GeneratorInputs,
    IntensitySpec,
    PreservedBuilding,
    ZonePreference,
    generate_scenario,
    load_recipes,
    render_axonometric_png,
    validate_road_orthogonality,
    write_scenario,
)
from urban_design.morphology_dictionary import load_dictionary


ROOT = Path(__file__).resolve().parents[1]
RECIPE_DIR = ROOT / "config" / "morphology-recipes"
ANGLE = 32.4


def _rotated(geometry):
    return rotate(geometry, ANGLE, origin=(250, 150))


def _inputs() -> GeneratorInputs:
    area = _rotated(box(0, 0, 500, 300))
    retained = PreservedBuilding(
        building_id="retained-known",
        bag_id="bag-known",
        geometry=_rotated(box(45, 115, 73, 145)),
        height_m=10.5,
        floor_count=3,
        floor_count_status="ESTIMATE_FROM_3DBAG",
        confidence="LOW",
    )
    unknown = PreservedBuilding(
        building_id="retained-unknown",
        bag_id="bag-unknown",
        geometry=_rotated(box(410, 125, 438, 153)),
        height_m=None,
        floor_count=None,
        floor_count_status="UNKNOWN",
        confidence="LOW",
    )
    contacts = (
        ExternalContact("contact-west", _rotated(Point(0, 150)), "way-west", "west"),
        ExternalContact("contact-east", _rotated(Point(500, 150)), "way-east", "east"),
    )
    return GeneratorInputs(
        design_area=area,
        water_geometry=_rotated(box(210, 105, 270, 150)),
        preserved_buildings=(retained, unknown),
        zones=(ZonePreference("zone-mixed", area, "Mixed use", "PREFERENCE"),),
        open_spaces=GeometryCollection(),
        external_contacts=contacts,
        crs="EPSG:28992",
        source_provenance={},
    )


def _intensities() -> dict[str, IntensitySpec]:
    return {
        "A": IntensitySpec(
            code="A",
            far_upper_bound=1.592296,
            height_upper_bound_m=20.0,
            coverage_upper_bound=None,
            first_floor_height_m=4.5,
            standard_floor_height_m=3.5,
        ),
        "B": IntensitySpec(
            code="B",
            far_upper_bound=2.0,
            height_upper_bound_m=40.0,
            coverage_upper_bound=0.5,
            first_floor_height_m=4.5,
            standard_floor_height_m=3.5,
        ),
    }


def _scenario(intensity: str = "B", seed: int = 17):
    recipe = load_recipes(RECIPE_DIR)["perimeter_block_city"]
    return generate_scenario(
        _inputs(),
        recipe,
        intensity=_intensities()[intensity],
        seed=seed,
        dictionary=load_dictionary(ROOT / "config" / "morphology-dictionary"),
    )


def test_every_generated_road_segment_is_parallel_or_perpendicular_to_main_axis():
    scenario = _scenario()

    result = validate_road_orthogonality(scenario, tolerance_deg=1.0)

    assert result["valid"], result["off_axis_segments"][:5]
    assert result["maximum_deviation_deg"] <= 1.0


def test_generated_buildings_respect_preserved_footprints_and_three_metre_setback():
    scenario = _scenario()

    for building in scenario.buildings:
        for preserved in scenario.inputs.preserved_buildings:
            assert building.footprint.intersection(preserved.geometry).area <= 1e-8
            assert building.footprint.distance(preserved.geometry) >= 3.0 - 1e-6


def test_no_generated_building_enters_water_or_fifteen_metre_waterfront_band():
    scenario = _scenario()

    for building in scenario.buildings:
        assert building.footprint.intersection(scenario.waterfront_no_build).area <= 1e-8


def test_every_generated_building_uses_a_resolvable_building_dictionary_type():
    scenario = _scenario()
    entries = load_dictionary(ROOT / "config" / "morphology-dictionary")["entry_by_id"]

    assert scenario.buildings
    assert all(building.dictionary_type_id in entries for building in scenario.buildings)
    assert all(entries[building.dictionary_type_id]["level"] == "building_plan" for building in scenario.buildings)
    assert all(building.selection_reason["zone_function_rules_version"] for building in scenario.buildings)
    assert all(building.selection_reason["atmosphere_query_targets"] for building in scenario.buildings)


def test_fixed_seed_replays_identical_scenario_hash():
    first = _scenario(seed=29)
    second = _scenario(seed=29)

    assert first.scenario_hash == second.scenario_hash


def test_fixed_seed_renders_identical_artifact_hashes(tmp_path):
    scenario = _scenario(seed=29)

    first = write_scenario(scenario, tmp_path / "first")
    second = write_scenario(scenario, tmp_path / "second")

    assert first["artifact_hashes"] == second["artifact_hashes"]


def test_axonometric_renderer_accepts_multi_polygon_building_templates(tmp_path):
    scenario = _scenario(seed=31)
    building = scenario.buildings[0]
    polygon = list(building.footprint.geoms)[0] if building.footprint.geom_type == "MultiPolygon" else building.footprint
    multipart = MultiPolygon((polygon, translate(polygon, xoff=35.0)))
    altered = replace(scenario, buildings=(replace(building, footprint=multipart), *scenario.buildings[1:]))

    output = tmp_path / "axonometric.png"
    render_axonometric_png(altered, output)

    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_land_far_stays_within_intensity_upper_bound_and_unknown_retained_floors_are_a_warning():
    for intensity in ("A", "B"):
        scenario = _scenario(intensity=intensity)

        assert scenario.metrics["far_land_area"]["known_value"] <= _intensities()[intensity].far_upper_bound + 1e-9
        assert scenario.metrics["far_land_area"]["unknown_retained_building_count"] == 1
        assert scenario.validation["valid"]
        assert any("unknown retained" in item.casefold() for item in scenario.validation["warnings"])
