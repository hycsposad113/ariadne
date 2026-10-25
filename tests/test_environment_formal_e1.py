from __future__ import annotations

from datetime import date, datetime, timezone
import importlib
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Point, Polygon

from urban_design.environment.contracts import AnalysisPeriod, SensorPoint, SiteLocation
from urban_design.environment.geometry_adapter import (
    UnknownRetainedHeightError,
    formal_scenario_geojson_to_environment,
    obstacle_to_2d_footprint,
)
from urban_design.environment.pipeline import run_e1_environment_pipeline
from urban_design.environment.router import get_default_draft_plan, router
from urban_design.environment.sunlight import RadianceRuntimeStatus
from urban_design.environment.sunlight import calculate_direct_sunlight_hours, generate_sun_vectors
from urban_design.models import ActorKind, Artifact, Scenario, ScenarioStatus
from urban_design.store import ProjectStateStore


def _geojson(building_x: float) -> dict:
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": [
            {
                "type": "Feature",
                "id": "site-area",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [40, 0], [40, 30], [0, 30], [0, 0]]]},
                "properties": {"role": "site_area"},
            },
            {
                "type": "Feature",
                "id": "water",
                "geometry": {"type": "GeometryCollection", "geometries": []},
                "properties": {"role": "water"},
            },
            {
                "type": "Feature",
                "id": "building-1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[building_x, 0], [building_x + 5, 0], [building_x + 5, 5], [building_x, 5], [building_x, 0]]],
                },
                "properties": {"role": "new_building", "height_m": 12.0},
            },
            {
                "type": "Feature",
                "id": "open-space-1",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [40, 0], [40, 30], [0, 30], [0, 0]]],
                },
                "properties": {"role": "primary_open_space"},
            },
        ],
    }


def _persist_formal_scenario(store: ProjectStateStore, root: Path, scenario_id: str, building_x: float) -> str:
    geometry = _geojson(building_x)
    raw = (json.dumps(geometry, sort_keys=True, separators=(",", ":")) + "\n").encode()
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    path = root / f"{scenario_id}.geojson"
    path.write_bytes(raw)
    artifact_id = f"artifact-{scenario_id}-geometry"
    artifact = Artifact(
        id=artifact_id,
        type="SCENARIO_GEOMETRY",
        uri=str(path),
        sha256=digest,
        mime="application/geo+json",
        crs="EPSG:28992",
        producer="formal-dictionary-v2",
        created_at=datetime.now(timezone.utc),
        project_id="project-e1",
        size_bytes=len(raw),
    )
    store.create_typed(artifact, actor="test", actor_kind=ActorKind.TEST_HARNESS, reason="Formal scenario geometry fixture")
    scenario = Scenario(
        id=scenario_id,
        project_id="project-e1",
        site_id="site-e1",
        site_version="v5",
        geometry_artifact_id=artifact_id,
        geometry_sha256=digest,
        generator="formal-dictionary-v2",
        generator_version="formal-dictionary-v2",
        constraint_set_id="constraints-e1",
        status=ScenarioStatus.PROPOSED,
        parameters={
            "provenance": "APPROVED_INPUTS",
            "validation": {"valid": True, "failure_reasons": []},
            "floor_estimates": [],
        },
    )
    store.create_typed(scenario, actor="test", actor_kind=ActorKind.TEST_HARNESS, reason="Formal proposal fixture")
    return digest


def test_formal_geojson_requires_epsg28992_and_height_and_builds_obstacle() -> None:
    geometry = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[80, 180], [160, 180], [160, 250], [80, 250], [80, 180]]]},
                "properties": {"role": "site_area"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "GeometryCollection", "geometries": []},
                "properties": {"role": "water"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[100, 200], [140, 200], [140, 215], [120, 215], [120, 235], [100, 235], [100, 200]]],
                },
                "properties": {"role": "new_building", "height_m": 21.0},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[80, 180], [160, 180], [160, 250], [80, 250], [80, 180]]]},
                "properties": {"role": "primary_open_space"},
            },
        ],
    }

    converted = formal_scenario_geojson_to_environment(geometry)

    assert len(converted.obstacles) == 1
    assert converted.obstacles[0].obstacle_id
    assert max(point[2] for face in converted.obstacles[0].faces for point in face) == 21.0
    assert isinstance(converted.public_open_space, Polygon)
    assert converted.public_open_space.area == 4600.0

    wrong_crs = {**geometry, "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}}
    with pytest.raises(ValueError, match="EPSG:28992"):
        formal_scenario_geojson_to_environment(wrong_crs)
    misleading_crs = {**geometry, "crs": {"type": "name", "properties": {"name": "EPSG:128992"}}}
    with pytest.raises(ValueError, match="EPSG:28992"):
        formal_scenario_geojson_to_environment(misleading_crs)

    missing_height = json.loads(json.dumps(geometry))
    building_feature = next(
        feature for feature in missing_height["features"]
        if feature["properties"].get("role") == "new_building"
    )
    del building_feature["properties"]["height_m"]
    with pytest.raises(ValueError, match="height_m"):
        formal_scenario_geojson_to_environment(missing_height)


def test_formal_building_footprint_holes_survive_extrusion_and_roundtrip() -> None:
    from urban_design.environment.sunlight import check_point_inside_polygon_obstacle

    geometry = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[-5, -5], [25, -5], [25, 25], [-5, 25], [-5, -5]]]},
                "properties": {"role": "site_area"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "GeometryCollection", "geometries": []},
                "properties": {"role": "water"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]],
                        [[5, 5], [15, 5], [15, 15], [5, 15], [5, 5]],
                    ],
                },
                "properties": {"role": "retained", "height_m": 12.0},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[-5, -5], [25, -5], [25, 25], [-5, 25], [-5, -5]]]},
                "properties": {"role": "primary_open_space"},
            },
        ],
    }

    converted = formal_scenario_geojson_to_environment(geometry)
    obstacle = converted.obstacles[0]
    footprint = obstacle_to_2d_footprint(obstacle)

    assert footprint.area == pytest.approx(300.0)
    assert len(footprint.interiors) == 1
    assert check_point_inside_polygon_obstacle((2.0, 2.0, 0.05), obstacle.faces) is True
    assert check_point_inside_polygon_obstacle((10.0, 10.0, 0.05), obstacle.faces) is False


def test_real_formal_roles_exclude_demolished_retained_and_skip_non_building_context() -> None:
    def polygon(x0: float, y0: float, x1: float, y1: float) -> dict:
        return {
            "type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
        }

    demolished_id = "bag:0599100000765601"
    geometry = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [60, 0], [60, 40], [0, 40], [0, 0]]]},
                "properties": {"role": "site_area"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "GeometryCollection", "geometries": []},
                "properties": {"role": "water"},
            },
            {
                "type": "Feature",
                "geometry": polygon(0, 0, 20, 20),
                "properties": {
                    "role": "retained",
                    "building_id": demolished_id,
                    "height_m": None,
                    "height_estimate": {"bag_observed_status": "Pand gesloopt"},
                },
            },
            {
                "type": "Feature",
                "geometry": polygon(20, 0, 23, 3),
                "properties": {
                    "role": "retained",
                    "building_id": "bag:zero-floor-retained",
                    "height_m": None,
                    "height_estimate": {"floor_count": {"lower": 0, "upper": 0}},
                },
            },
            {
                "type": "Feature",
                "geometry": polygon(25, 0, 30, 5),
                "properties": {"role": "retained", "building_id": "bag:retained-20m", "height_m": 20.7},
            },
            {
                "type": "Feature",
                "geometry": polygon(35, 0, 40, 5),
                "properties": {"role": "retained", "building_id": "bag:retained-12m", "height_m": 12.5},
            },
            {
                "type": "Feature",
                "geometry": polygon(45, 0, 50, 5),
                "properties": {"role": "new_building", "building_id": "new:1", "height_m": 18.0},
            },
            {"type": "Feature", "geometry": polygon(0, 25, 5, 30), "properties": {"role": "road", "height_m": None}},
            {"type": "Feature", "geometry": polygon(10, 25, 15, 30), "properties": {"role": "street_block", "height_m": None}},
            # This envelope deliberately duplicates new:1 and must not be counted as another obstacle.
            {"type": "Feature", "geometry": polygon(45, 0, 50, 5), "properties": {"role": "massing_envelope", "height_m": 18.0}},
            {"type": "Feature", "geometry": polygon(-5, -5, 60, 40), "properties": {"role": "primary_open_space"}},
        ],
    }

    converted = formal_scenario_geojson_to_environment(geometry)

    assert {obstacle.obstacle_id for obstacle in converted.obstacles} == {
        "bag:retained-20m",
        "bag:retained-12m",
        "new:1",
    }
    assert len(converted.obstacles) == 3
    assert converted.excluded_obstacles == (
        {
            "building_id": demolished_id,
            "reason": "BAG status 'Pand gesloopt' identifies a demolished retained building; excluded as a sunlight obstacle.",
        },
        {
            "building_id": "bag:zero-floor-retained",
            "reason": "Recorded floor-count evidence is 0..0; excluded as a sunlight obstacle.",
        },
    )

    database_shape = json.loads(json.dumps(geometry))
    del database_shape["features"][2]["properties"]["height_estimate"]
    database_shape["features"][3]["properties"].pop("height_estimate")
    converted_from_scenario_metadata = formal_scenario_geojson_to_environment(
        database_shape,
        floor_estimates=[
            {
                "building_id": demolished_id,
                "bag_observed_status": "Pand gesloopt",
                "floor_count": {"lower": 0, "upper": 0},
                "height_above_ground_m": None,
            },
            {
                "building_id": "bag:zero-floor-retained",
                "floor_count": {"lower": 0, "upper": 0},
                "height_above_ground_m": None,
            },
        ],
    )
    assert converted_from_scenario_metadata.excluded_obstacles == converted.excluded_obstacles


def test_formal_retained_building_without_height_or_demolition_evidence_blocks_with_id() -> None:
    geometry = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[-5, -5], [20, -5], [20, 20], [-5, 20], [-5, -5]]]},
                "properties": {"role": "site_area"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "GeometryCollection", "geometries": []},
                "properties": {"role": "water"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
                "properties": {"role": "retained", "building_id": "bag:height-unknown", "height_m": None},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[-5, -5], [20, -5], [20, 20], [-5, 20], [-5, -5]]]},
                "properties": {"role": "primary_open_space"},
            },
        ],
    }

    with pytest.raises(UnknownRetainedHeightError, match="bag:height-unknown"):
        formal_scenario_geojson_to_environment(geometry)


def test_e1_default_is_explicit_unapproved_three_date_rotterdam_plan() -> None:
    plan = get_default_draft_plan()

    assert plan.status == "DRAFT_UNAPPROVED"
    assert plan.location.latitude == pytest.approx(51.90)
    assert plan.location.longitude == pytest.approx(4.45)
    assert plan.location.timezone == "Europe/Amsterdam"
    assert plan.period.dates == [date(2026, 3, 21), date(2026, 6, 21), date(2026, 12, 21)]
    assert (plan.period.start_hour, plan.period.end_hour) == (8.0, 18.0)
    assert plan.grid_definition.spacing_m == 5.0
    assert plan.status == "DRAFT_UNAPPROVED"
    assert "DRAFT_DOMAIN_FOUNDER_2026-10-04" in plan.notes
    assert "site land" in plan.comparison_domain.lower()
    assert "water" in plan.comparison_domain.lower()
    assert "roads" in plan.comparison_domain.lower()
    assert "geometric analysis extent" in plan.comparison_domain.lower()
    assert "not a legal right of way" in plan.comparison_domain.lower()
    assert plan.period.timestep == 4


def test_formal_public_space_domain_is_site_area_minus_buildings_and_water_including_roads() -> None:
    def polygon(x0: float, y0: float, x1: float, y1: float) -> dict:
        return {
            "type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
        }

    geometry = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": [
            {"type": "Feature", "geometry": polygon(0, 0, 50, 40), "properties": {"role": "site_area"}},
            {"type": "Feature", "geometry": polygon(0, 0, 10, 10), "properties": {"role": "water"}},
            {"type": "Feature", "geometry": polygon(20, 0, 30, 10), "properties": {"role": "new_building", "building_id": "new:1", "height_m": 9.0}},
            {"type": "Feature", "geometry": polygon(30, 0, 40, 10), "properties": {"role": "retained", "building_id": "retained:1", "height_m": 12.0}},
            {"type": "Feature", "geometry": polygon(0, 20, 50, 22), "properties": {"role": "road"}},
            {"type": "Feature", "geometry": polygon(44, 30, 46, 32), "properties": {"role": "primary_open_space"}},
        ],
    }

    converted = formal_scenario_geojson_to_environment(geometry)

    assert converted.public_open_space.area == pytest.approx(1700.0)
    assert converted.public_open_space.covers(Point(5, 21))
    assert not converted.public_open_space.covers(Point(5, 5))
    assert not converted.public_open_space.covers(Point(25, 5))


def test_common_public_space_overlap_discards_zero_area_geometry_collection_parts() -> None:
    from shapely.geometry import GeometryCollection, LineString, box
    from urban_design.environment.router import _polygonal_overlap

    first = GeometryCollection([box(0, 0, 2, 2), LineString([(3, 3), (4, 4)])])
    overlap = _polygonal_overlap(first, box(0, 0, 5, 5))

    assert isinstance(overlap, Polygon)
    assert overlap.area == pytest.approx(4.0)


def test_e1_pipeline_reports_march_21_per_scheme_stats_and_overlap_delta() -> None:
    from shapely.geometry import box

    plan = get_default_draft_plan()
    baseline_domain = box(0, 0, 40, 30).difference(box(0, 0, 5, 5))
    modified_domain = box(0, 0, 40, 30).difference(box(20, 0, 25, 5))
    common_domain = baseline_domain.intersection(modified_domain)

    result = run_e1_environment_pipeline(
        plan=plan,
        baseline_geometry=[{"id": "baseline-building", "height_m": 8, "footprint": {"coordinates": [[(0, 0), (5, 0), (5, 5), (0, 5), (0, 0)]]}}],
        modified_geometry=[{"id": "modified-building", "height_m": 8, "footprint": {"coordinates": [[(20, 0), (25, 0), (25, 5), (20, 5), (20, 0)]]}}],
        boundary_polygon=common_domain,
        baseline_domain=baseline_domain,
        modified_domain=modified_domain,
        method="pure_python_box_ray",
        project_id="project-e1",
    )

    assert result.status == "SUCCESS"
    assert result.baseline_march_21_statistics.date == date(2026, 3, 21)
    assert result.baseline_march_21_statistics.sensor_count == sum(
        point.status == "VALID" for point in result.baseline_sunlight.results
    )
    assert result.modified_march_21_statistics.sensor_count == sum(
        point.status == "VALID" for point in result.modified_sunlight.results
    )
    assert result.baseline_march_21_statistics.mean_hours == pytest.approx(
        sum(point.sunlight_hours for point in result.baseline_sunlight.daily_results["2026-03-21"] if point.status == "VALID") / result.baseline_march_21_statistics.sensor_count
    )
    assert result.comparison.metadata["paired_sensor_count"] > 0
    assert result.comparison.metadata["paired_domain"] == "COMMON_OVERLAP"
    assert result.comparison.metadata["paired_domain_area_m2"] == pytest.approx(common_domain.area)
    assert result.comparison.metadata["legal_right_of_way"] is False
    assert result.baseline_march_21_statistics.sensors_at_least_2_hours_note.startswith("Reference statistic only")
    assert result.metadata["elapsed_seconds"] >= 0
    assert result.metadata["baseline_elapsed_seconds"] >= 0
    assert result.metadata["modified_elapsed_seconds"] >= 0


def test_runtime_status_labels_python_fallback_when_radiance_verification_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("urban_design.environment.router")
    reason = "RADIANCE_VERSION_MISMATCH: manifest requires 6.0.2; rtrace reported 6.0.1"
    monkeypatch.setattr(
        module,
        "verify_radiance_runtime",
        lambda: RadianceRuntimeStatus(
            available=False,
            version="6.0.1",
            manifest_version="6.0.2",
            reason=reason,
        ),
    )

    status = module.get_runtime_status()

    assert status.radiance_available is False
    assert status.engine == "ladybug-sunpath+python-raycast"
    assert status.fallback_reason == reason


def test_sun_vectors_use_selected_local_dates_and_dst_offsets() -> None:
    location = SiteLocation(latitude=51.90, longitude=4.45, timezone="Europe/Amsterdam")
    period = AnalysisPeriod(
        start_date=date(2026, 3, 21),
        end_date=date(2026, 12, 21),
        dates=[date(2026, 3, 21), date(2026, 6, 21), date(2026, 12, 21)],
        start_hour=12.0,
        end_hour=13.0,
        timestep=1,
    )

    vectors = generate_sun_vectors(location, period)
    by_local_date = {}
    for utc_time, _vector, _altitude, _azimuth in vectors:
        local_time = utc_time.astimezone(timezone.utc)
        local_date = utc_time.date()
        by_local_date[local_date] = local_time.hour

    assert by_local_date == {
        date(2026, 3, 21): 11,
        date(2026, 6, 21): 10,
        date(2026, 12, 21): 11,
    }

    transition_period = AnalysisPeriod(
        start_date=date(2026, 3, 29),
        end_date=date(2026, 10, 25),
        dates=[date(2026, 3, 29), date(2026, 10, 25)],
        start_hour=10.0,
        end_hour=11.0,
        timestep=1,
    )
    transition_vectors = generate_sun_vectors(location, transition_period)
    utc_hour_by_local_date = {
        timestamp.astimezone(ZoneInfo(location.timezone)).date(): timestamp.hour
        for timestamp, _vector, _altitude, _azimuth in transition_vectors
    }
    assert utc_hour_by_local_date == {
        date(2026, 3, 29): 8,
        date(2026, 10, 25): 9,
    }


def test_radiance_intersection_batches_more_than_512_sensor_points(monkeypatch: pytest.MonkeyPatch) -> None:
    from urban_design.environment import sunlight as sunlight_module

    calls: list[int] = []

    def fake_intersection_matrix(*, vectors, points, **_kwargs):
        calls.append(len(points))
        return [[True for _ in vectors] for _ in points]

    monkeypatch.setattr(sunlight_module, "verify_radiance_runtime", lambda: RadianceRuntimeStatus(available=True, version="6.0.2", manifest_version="6.0.2"))
    monkeypatch.setattr(sunlight_module.rad_intersection, "intersection_matrix", fake_intersection_matrix)
    result = calculate_direct_sunlight_hours(
        location=SiteLocation(latitude=51.90, longitude=4.45, timezone="Europe/Amsterdam"),
        period=AnalysisPeriod(
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 21),
            start_hour=12.0,
            end_hour=12.25,
            timestep=4,
        ),
        sensor_points=[SensorPoint.create(index * 5.0, 100.0) for index in range(513)],
        obstacles=(),
        method="ladybug_radiance",
    )

    assert len(result.results) == 513
    assert calls == [512, 1]
    assert result.metadata["radiance_sensor_batch_size"] == 512
    assert result.metadata["radiance_sensor_batch_count"] == 2


def test_south_building_casts_noon_shadow_north_with_python_raycast() -> None:
    location = SiteLocation(latitude=51.90, longitude=4.45, timezone="Europe/Amsterdam")
    period = AnalysisPeriod(
        start_date=date(2026, 6, 21),
        end_date=date(2026, 6, 21),
        start_hour=13.5,
        end_hour=13.75,
        timestep=4,
    )
    building = {
        "id": "south-wall",
        "height_m": 20.0,
        "footprint": {"type": "Polygon", "coordinates": [[(-5, -10), (5, -10), (5, -5), (-5, -5), (-5, -10)]]},
    }
    from urban_design.environment.geometry_adapter import massing_to_obstacles

    result = calculate_direct_sunlight_hours(
        location=location,
        period=period,
        sensor_points=[SensorPoint.create(0, 0), SensorPoint.create(0, -15)],
        obstacles=massing_to_obstacles([building]),
        method="pure_python_box_ray",
    )

    north_sensor, south_sensor = result.results
    assert north_sensor.sunlight_hours == 0.0
    assert south_sensor.sunlight_hours > 0.0
    assert result.engine == "ladybug-sunpath+python-raycast"


def test_python_crosscheck_uses_polygon_bounds_before_triangle_intersections(monkeypatch: pytest.MonkeyPatch) -> None:
    from urban_design.environment import sunlight as sunlight_module
    from urban_design.environment.geometry_adapter import massing_to_obstacles

    triangle_checks: list[bool] = []
    original_check = sunlight_module.ray_polygon_faces_intersection

    def count_triangle_check(origin, direction, faces):
        triangle_checks.append(True)
        return original_check(origin, direction, faces)

    monkeypatch.setattr(sunlight_module, "ray_polygon_faces_intersection", count_triangle_check)
    building = {
        "id": "far-building",
        "height_m": 10.0,
        "footprint": {"coordinates": [[(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]]},
    }
    result = calculate_direct_sunlight_hours(
        location=SiteLocation(latitude=51.90, longitude=4.45, timezone="Europe/Amsterdam"),
        period=AnalysisPeriod(
            start_date=date(2026, 6, 21),
            end_date=date(2026, 6, 21),
            start_hour=12.0,
            end_hour=12.25,
            timestep=4,
        ),
        sensor_points=[SensorPoint.create(1000, 1000)],
        obstacles=massing_to_obstacles([building]),
        method="pure_python_box_ray",
    )

    assert result.results[0].status == "VALID"
    assert triangle_checks == []


def test_draft_pipeline_persists_unverified_artifact_and_tool_execution(tmp_path: Path) -> None:
    plan = get_default_draft_plan().model_copy(
        update={
            "period": AnalysisPeriod(
                start_date=date(2026, 6, 21),
                end_date=date(2026, 6, 21),
                dates=[date(2026, 6, 21)],
                start_hour=12.0,
                end_hour=13.0,
                timestep=1,
            ),
        }
    )
    with ProjectStateStore(tmp_path / "e1-copy.sqlite3") as store:
        result = run_e1_environment_pipeline(
            plan=plan,
            baseline_geometry=[],
            modified_geometry=[{"id": "building", "height_m": 8, "footprint": {"coordinates": [[(10, 10), (20, 10), (20, 20), (10, 20), (10, 10)]]}}],
            boundary_polygon=[(0, 0), (30, 0), (30, 30), (0, 30)],
            method="pure_python_box_ray",
            project_id="project-e1",
            run_id="draft-persisted",
            store=store,
        )

        assert result.status == "SUCCESS"
        assert result.metadata["E1_PLAN"] == "DRAFT_DOMAIN_FOUNDER_2026-10-04"
        assert result.metadata["plan_status"] == "DRAFT_UNAPPROVED"
        assert result.metadata["engine"] == "ladybug-sunpath+python-raycast"
        assert result.evidence_card["validation_status"] == "unverified"
        execution = store.current(result.tool_execution["id"])
        artifact = store.current(result.artifact["id"])
        assert execution.entity_type == "ToolExecution"
        assert execution.payload["status"] == "SUCCEEDED"
        assert artifact.entity_type == "Artifact"
        assert artifact.payload["bundle"]["E1_PLAN"] == "DRAFT_DOMAIN_FOUNDER_2026-10-04"
        assert artifact.payload["bundle"]["plan_status"] == "DRAFT_UNAPPROVED"
        assert artifact.payload["bundle"]["period"]["dates"] == ["2026-06-21"]
        assert store.list_current("HumanDecision", project_id="project-e1") == []


def test_formal_scenario_api_run_uses_store_geometry_and_persists_to_db_copy(tmp_path: Path) -> None:
    database = tmp_path / "formal-e1-copy.sqlite3"
    root = tmp_path / "formal-geometry"
    root.mkdir()
    store = ProjectStateStore(database)
    store.create_project({"id": "project-e1", "name": "E1 fixture project"}, project_id="project-e1")
    _persist_formal_scenario(store, root, "formal-baseline", building_x=5)
    _persist_formal_scenario(store, root, "formal-proposal", building_x=20)

    app = FastAPI()
    app.state.project_store = store
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/api/environment/e1/simulate",
            json={
                "project_id": "project-e1",
                "baseline_scenario_id": "formal-baseline",
                "modified_scenario_id": "formal-proposal",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "SUCCESS"
    assert payload["plan"]["status"] == "DRAFT_UNAPPROVED"
    assert payload["metadata"]["engine"] == "ladybug-sunpath+ladybug-radiance"
    assert payload["metadata"]["E1_PLAN"] == "DRAFT_DOMAIN_FOUNDER_2026-10-04"
    assert payload["metadata"]["cross_check"]["tolerance_mean_absolute_delta_hours"] == 0.25
    assert payload["metadata"]["cross_check"]["status"] == "PASS"
    sample = payload["metadata"]["cross_check"]["sample"]
    assert sample["seed"] == 20261004
    assert sample["sample_size_used"] <= sample["population_valid_count"]
    assert sample["mode"] in {"STRATIFIED_FIXED_COUNT", "FULL", "FULL_BECAUSE_POPULATION_WITHIN_SAMPLE"}
    assert payload["metadata"]["elapsed_seconds"] >= 0
    assert payload["baseline_sunlight"]["results"]
    assert payload["modified_sunlight"]["results"]
    assert len(store.list_current("ToolExecution", project_id="project-e1")) == 1
    assert len(store.list_current("Artifact", project_id="project-e1")) == 3
    assert store.list_current("HumanDecision", project_id="project-e1") == []
    store.close()


def test_formal_scenario_api_labels_python_fallback_when_manifest_version_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "formal-e1-fallback-copy.sqlite3"
    root = tmp_path / "formal-geometry-fallback"
    root.mkdir()
    store = ProjectStateStore(database)
    store.create_project({"id": "project-e1", "name": "E1 fixture project"}, project_id="project-e1")
    _persist_formal_scenario(store, root, "formal-baseline", building_x=5)
    _persist_formal_scenario(store, root, "formal-proposal", building_x=20)

    module = importlib.import_module("urban_design.environment.router")
    mismatch = "RADIANCE_VERSION_MISMATCH: manifest requires 6.0.2; rtrace reported 6.0.1"
    monkeypatch.setattr(
        module,
        "verify_radiance_runtime",
        lambda: RadianceRuntimeStatus(
            available=False,
            version="6.0.1",
            manifest_version="6.0.2",
            reason=mismatch,
        ),
    )
    app = FastAPI()
    app.state.project_store = store
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/api/environment/e1/simulate",
            json={
                "project_id": "project-e1",
                "baseline_scenario_id": "formal-baseline",
                "modified_scenario_id": "formal-proposal",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "SUCCESS"
    assert payload["engine"] == "ladybug-sunpath+python-raycast"
    assert payload["metadata"]["engine_selection"]["fallback_reason"] == mismatch
    assert payload["metadata"]["cross_check"] is None
    store.close()


def test_formal_scenario_api_returns_blocked_with_unknown_retained_building_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("urban_design.environment.router")
    store = ProjectStateStore(":memory:")

    def raise_unknown_height(*_args):
        raise UnknownRetainedHeightError("bag:unknown-height")

    monkeypatch.setattr(module, "_formal_scenario_environment", raise_unknown_height)
    app = FastAPI()
    app.state.project_store = store
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post(
            "/api/environment/e1/simulate",
            json={
                "project_id": "project-e1",
                "baseline_scenario_id": "formal-baseline",
                "modified_scenario_id": "formal-proposal",
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "BLOCKED"
    assert payload["engine"] == "NOT_RUN"
    assert payload["metadata"]["blocked_at"] == "formal_geometry_validation"
    assert payload["metadata"]["blocked_building_id"] == "bag:unknown-height"
    assert "bag:unknown-height" in payload["blocked_reason"]
    assert store.list_current("HumanDecision", project_id="project-e1") == []
    store.close()


def test_cross_check_sample_is_deterministic_and_stays_inside_the_fixed_count() -> None:
    from urban_design.environment.pipeline import CROSS_CHECK_SAMPLE_SIZE, select_cross_check_sensors

    points = [SensorPoint.create(float(index), 0.0) for index in range(100)]
    first, first_meta = select_cross_check_sensors(points, scope="stratified")
    second, _second_meta = select_cross_check_sensors(points, scope="stratified")
    full, full_meta = select_cross_check_sensors(points, scope="full")

    assert [point.point_id for point in first] == [point.point_id for point in second]
    assert len(first) == CROSS_CHECK_SAMPLE_SIZE
    assert first_meta["seed"] == 20261004
    assert first_meta["mode"] == "STRATIFIED_FIXED_COUNT"
    assert len(full) == 100
    assert full_meta["mode"] == "FULL"


def test_missing_site_and_water_are_supplemented_without_rewriting_the_artifact() -> None:
    from shapely.geometry import box

    from urban_design.environment.geometry_adapter import supplement_missing_domain_features

    stored = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:28992"}},
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
                "properties": {"role": "new_building", "building_id": "new:1", "height_m": 9.0},
            },
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[0, 20], [40, 20]]},
                "properties": {"role": "road", "width_m": 4.0},
            },
        ],
    }
    original_features = list(stored["features"])
    supplemented, sources = supplement_missing_domain_features(
        stored,
        site_area=box(0, 0, 50, 40),
        water=Polygon(),
        site_properties={"workspace_id": "workspace-test"},
    )

    assert stored["features"] == original_features
    assert sources["site_area"] == "approved_workspace_exploration_design_area"
    assert sources["water"] == "approved_workspace_bgt_waterdeel"
    converted = formal_scenario_geojson_to_environment(supplemented)
    assert converted.public_open_space.area == pytest.approx(1900.0)
    assert converted.public_open_space.covers(Point(5, 20))
    assert not converted.public_open_space.covers(Point(5, 5))

    again, again_sources = supplement_missing_domain_features(
        supplemented,
        site_area=box(0, 0, 1, 1),
        water=box(0, 0, 1, 1),
    )
    assert again_sources == {"site_area": "scenario_artifact", "water": "scenario_artifact"}
    assert len(again["features"]) == len(supplemented["features"])
