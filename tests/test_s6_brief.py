"""Black-box checks for the S6 design-intent brief validator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from shapely.geometry import LineString, box, mapping, shape


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "s6_brief.py"
sys.path.insert(0, str(ROOT / "scripts"))
import s6_brief


def _valid_brief() -> dict:
    return {
        "strategy": "axial",
        "concept": {
            "statement_zh": "以連續的公共軸線串接工作、居住與水岸空間，保留既有紋理。",
            "responds_to_zh": ["回應基地北側大眾運輸", "延續水岸步行連結"],
        },
        "precedents": [
            {"name": "Rotterdam precedent A", "borrow_zh": "借用尺度", "not_applicable_zh": "不複製密度"},
            {"name": "Rotterdam precedent B", "borrow_zh": "借用連結", "not_applicable_zh": "不移植用途"},
        ],
        "development_streets": [{"strip_id": "strip-1", "reason_zh": "沿既有入口延續公共軸線並連接基地內部。"}],
        "strips": [
            {
                "strip_id": "strip-1",
                "segment_m": [0, 200],
                "typologies": ["perimeter"],
                "frontage": "both_sides",
                "floors": [4, 5],
                "reason_zh": "此帶寬足以容納周邊式街廓，並保留中央公共空間。",
            }
        ],
        "height_strategy": {
            "landmarks": [{"location_zh": "主軸節點", "strip_id": "strip-1", "height_m": 17.5, "reason_zh": "在轉乘步行軸線交會處形成辨識點。"}],
            "low_zones": [],
            "reason_zh": "高度由街道和公園界面向內漸變。",
        },
        "open_spaces": [
            {"name_zh": "水岸公園", "location_zh": "西側水岸", "strip_id": "strip-1", "segment_m": [0, 100], "area_m2_target": 10000, "use_zh": "步行與生態", "reason_zh": "維持連續開放的水岸公共界面。"},
            {"name_zh": "軸線廣場", "location_zh": "主軸中段", "area_m2_target": 5000, "use_zh": "停留與集會", "reason_zh": "支援工作日與週末的日常活動。"},
        ],
        "movement": {
            "pedestrian_cycle_spine_zh": "沿北側入口向水岸連續通行。",
            "car_access_zh": "汽車由既有外部道路接入。",
            "service_loop_zh": "服務車流使用基地外緣迴路。",
            "bike_parking_zh": "入口與轉乘節點設置自行車停車。",
        },
        "gfa_allocation": {
            "by_strip": [{"strip_id": "strip-1", "gfa_m2": 70000}],
            "total_new_gfa_m2": 70000,
            "far_check_zh": "新建與保留建築合計不超過基地 FAR 上限。",
        },
        "tradeoffs": ["軸線連續性與基地內部安靜度需平衡。", "開放空間連續性會限制部分可建面積。", "混合用途需要分時管理服務動線。"],
        "sources": ["site-facts.json"],
    }


def _facts() -> dict:
    strip = {
        "id": "strip-1",
        "width_min_m": 120,
        "width_max_m": 120,
        "length_m": 200,
        "orientation_deg_from_east_ccw": 0.0,
        "area_m2": 24000.0,
        "width_series_every_25m": [
            {"station_m": float(station), "width_m": 120.0}
            for station in range(0, 201, 25)
        ],
        "stations": [],
    }
    strip_geometry = mapping(box(0, -60, 200, 60))
    axis_geometry = mapping(LineString([(0, 0), (200, 0)]))
    return {
        "site": {"land_area_m2": 100000, "horizontal_crs": "EPSG:28992", "units": "m"},
        "gfa": {"retained_upper_m2": 0, "new_gfa_budget_m2": 80000, "far_max": 0.8},
        "height": {"cap_m": 20, "floor_height_m": 3.5},
        "buildable": {"strips": [strip]},
        "geometry": {
            "crs": "EPSG:28992",
            "site": mapping(box(-10, -90, 210, 90)),
            "water": mapping(box(0, 61, 200, 64)),
            "buildable": strip_geometry,
            "waterfront_band": mapping(box(0, 60, 200, 70)),
            "dakpark": mapping(box(140, 65, 160, 80)),
            "strips": [{"id": "strip-1", "geometry": strip_geometry, "axis": axis_geometry}],
            "retained_buildings": [{"id": "retained-1", "geometry": mapping(box(90, 65, 100, 80))}],
            "retained_roads": [],
            "zones": [],
            "entrances": [
                {"id": "entry-1", "coordinates": [0.0, 0.0]},
                {"id": "entry-2", "coordinates": [120.0, 0.0]},
            ],
            "external_high_roads": {
                "pedestrian": [mapping(LineString([(0, 65), (40, 65)]))],
                "bicycle": [],
            },
        },
        "entrances": [
            {"id": "entry-1", "coordinates": [0.0, 0.0]},
            {"id": "entry-2", "coordinates": [120.0, 0.0]},
        ],
        "precedents": [{"name": "Rotterdam precedent A"}, {"name": "Rotterdam precedent B"}],
    }


def _run_validate(tmp_path: Path, brief: dict, facts: dict) -> subprocess.CompletedProcess[str]:
    brief_path = tmp_path / "brief.json"
    facts_path = tmp_path / "facts.json"
    brief_path.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    facts_path.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "validate", "--brief", str(brief_path), "--facts", str(facts_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_validate_accepts_schema_valid_brief_within_facts(tmp_path: Path) -> None:
    result = _run_validate(tmp_path, _valid_brief(), _facts())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "通過" in result.stdout


def test_validate_rejects_unknown_strip_over_budget_and_narrow_double_perimeter(tmp_path: Path) -> None:
    brief = _valid_brief()
    brief["development_streets"][0]["strip_id"] = "missing-strip"
    brief["precedents"][0]["name"] = "Missing precedent"
    brief["strips"][0]["floors"] = [5, 6]
    brief["gfa_allocation"]["by_strip"][0]["strip_id"] = "missing-strip"
    brief["gfa_allocation"]["by_strip"][0]["gfa_m2"] = 90000
    brief["gfa_allocation"]["total_new_gfa_m2"] = 90000
    facts = _facts()
    facts["buildable"]["strips"][0]["width_min_m"] = 50
    for sample in facts["buildable"]["strips"][0]["width_series_every_25m"]:
        sample["width_m"] = 50

    result = _run_validate(tmp_path, brief, facts)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "STRIP_ID_UNKNOWN" in result.stdout
    assert "PRECEDENT_UNKNOWN" in result.stdout
    assert "FLOOR_HEIGHT_CAP_EXCEEDED" in result.stdout
    assert "GFA_BUDGET_EXCEEDED" in result.stdout
    assert "NARROW_BAND_DOUBLE_PERIMETER" in result.stdout


def test_validate_rejects_segment_and_landmark_station_beyond_strip_length() -> None:
    brief = _valid_brief()
    brief["strips"][0]["segment_m"] = [0, 201]
    brief["height_strategy"]["landmarks"][0]["station_m"] = 201

    issues = s6_brief._validate_brief(brief, _facts())
    codes = [code for code, _message in issues]
    assert codes.count("SEGMENT_OUT_OF_RANGE") == 1, issues
    assert codes.count("STATION_OUT_OF_RANGE") == 1, issues


def test_validate_rejects_out_of_range_nested_segment() -> None:
    brief = _valid_brief()
    brief["strips"][0]["segments"] = [{"segment_m": [0, 201], "building_types_zh": ["連棟"]}]

    issues = s6_brief._validate_brief(brief, _facts())
    assert any(code == "SEGMENT_OUT_OF_RANGE" for code, _message in issues), issues


def test_nested_segment_without_anchor_is_reported_as_unspecified() -> None:
    brief = _valid_brief()
    brief["strips"][0].pop("segment_m")
    brief["strips"][0]["segments"] = [{"building_types_zh": ["連棟"], "floors": [4, 5]}]

    row = s6_brief._brief_segment_rows(brief)[0]
    assert row["_is_child"] is True
    assert row.get("segment_m") is None
    assert any("帶段落" in item for item in s6_brief._missing_anchor_items(brief))
    assert "位置未指定" in s6_brief._intent_markdown(brief, _facts())


def test_legacy_brief_without_anchors_keeps_locations_unspecified() -> None:
    brief = _valid_brief()
    issues = s6_brief._validate_brief(brief, _facts())

    assert not issues, issues
    assert len(s6_brief._missing_anchor_items(brief)) == 2
    assert "位置未指定" in s6_brief._intent_markdown(brief, _facts())


def test_build_station_adjacency_rows_records_every_25m_and_nearest_features() -> None:
    facts = _facts()
    strip = facts["buildable"]["strips"][0]

    rows = s6_brief._build_station_adjacency_rows(strip, facts)

    assert [row["station_m"] for row in rows] == list(map(float, range(0, 201, 25)))
    first = rows[0]
    assert first["width_m"] == 120
    assert first["midpoint_epsg28992"] == [0.0, 0.0]
    assert first["nearest_entrances"][0] == {"id": "entry-1", "distance_m": 0.0}
    assert len(first["nearest_entrances"]) == 2
    assert rows[6]["dakpark_distance_m"] == 65.0
    assert rows[4]["water_distance_m"] == 61.0
    assert rows[4]["water_side_from_axis"] == "left"
    assert rows[4]["nearest_retained_building_distance_m"] == 65.0
    assert first["adjacent_external_high_integration_road"] is True
    assert first["nearest_external_high_integration_road"]["distance_m"] == 5.0


def test_build_station_adjacency_records_nearest_interior_section_when_axis_starts_outside_band() -> None:
    facts = _facts()
    facts["geometry"]["strips"][0]["geometry"] = mapping(box(0.05, -60, 200, 60))
    strip = facts["buildable"]["strips"][0]

    first = s6_brief._build_station_adjacency_rows(strip, facts)[0]

    assert first["station_m"] == 0.0
    assert first["cross_section_geometry_station_m"] == 0.1


def test_facts_summary_adds_location_keypoints_and_50m_adjacency_table() -> None:
    facts = _facts()
    strip = facts["buildable"]["strips"][0]
    strip["stations"] = s6_brief._build_station_adjacency_rows(strip, facts)
    strip["summary_zh"] = s6_brief._strip_summary_zh(strip, strip["stations"])

    location = s6_brief._spatial_locator_summary(facts)
    summary = s6_brief._facts_summary(facts)

    assert "entry-1" in location
    assert "最寬可建段" in location
    assert "| 帶 | s (m) |" in summary
    assert "| strip-1 | 50 |" in summary
    assert "summary_zh" not in summary


def test_dakpark_named_open_space_passes_when_its_segment_is_near_dakpark() -> None:
    brief = _valid_brief()
    brief["open_spaces"][0]["name_zh"] = "Dakpark 綠廊"
    brief["open_spaces"][0]["segment_m"] = [100, 175]

    issues = s6_brief._validate_brief(brief, _facts())

    assert not any(code == "PARK_NAME_LOCATION_MISMATCH" for code, _message in issues), issues


def test_dakpark_named_open_space_fails_when_its_segment_is_far_from_dakpark() -> None:
    brief = _valid_brief()
    brief["open_spaces"][0]["name_zh"] = "Dakpark 綠廊"
    brief["open_spaces"][0]["segment_m"] = [0, 50]
    facts = _facts()
    facts["geometry"]["dakpark"] = mapping(box(500, 25, 520, 40))

    issues = s6_brief._validate_brief(brief, facts)

    assert any(code == "PARK_NAME_LOCATION_MISMATCH" for code, _message in issues), issues


def test_waterfront_named_open_space_passes_when_its_segment_is_near_water() -> None:
    brief = _valid_brief()
    brief["open_spaces"][0]["name_zh"] = "港岸公園"

    issues = s6_brief._validate_brief(brief, _facts())

    assert not any(code == "PARK_NAME_LOCATION_MISMATCH" for code, _message in issues), issues


def test_waterfront_named_open_space_fails_when_its_segment_is_far_from_water() -> None:
    brief = _valid_brief()
    brief["open_spaces"][0]["name_zh"] = "港岸公園"
    facts = _facts()
    facts["geometry"]["water"] = mapping(box(0, 120, 200, 140))

    issues = s6_brief._validate_brief(brief, facts)

    assert any(code == "PARK_NAME_LOCATION_MISMATCH" for code, _message in issues), issues


def test_landmark_location_entry_reference_passes_within_80m() -> None:
    brief = _valid_brief()
    landmark = brief["height_strategy"]["landmarks"][0]
    landmark["location_zh"] = "entry-1 北側入口節點"
    landmark["station_m"] = 75

    issues = s6_brief._validate_brief(brief, _facts())

    assert not any(code == "LANDMARK_ENTRY_MISMATCH" for code, _message in issues), issues


def test_landmark_location_entry_reference_fails_beyond_80m() -> None:
    brief = _valid_brief()
    landmark = brief["height_strategy"]["landmarks"][0]
    landmark["location_zh"] = "entry-1 北側入口節點"
    landmark["station_m"] = 150

    issues = s6_brief._validate_brief(brief, _facts())

    assert any(code == "LANDMARK_ENTRY_MISMATCH" for code, _message in issues), issues


def test_wide_land_park_coverage_warns_without_failing_validation(tmp_path: Path) -> None:
    brief = _valid_brief()
    brief["open_spaces"][0]["segment_m"] = [0, 150]

    result = _run_validate(tmp_path, brief, _facts())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[WARN] WIDE_LAND_UNDERUSED" in result.stdout
    assert "周邊式街廓" in result.stdout


def test_wide_land_park_coverage_at_60_percent_does_not_warn(tmp_path: Path) -> None:
    brief = _valid_brief()
    brief["open_spaces"][0]["segment_m"] = [0, 120]

    result = _run_validate(tmp_path, brief, _facts())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "WIDE_LAND_UNDERUSED" not in result.stdout


def test_wide_land_coverage_counts_park_typology_on_strip_segments() -> None:
    brief = _valid_brief()
    brief["open_spaces"][0]["name_zh"] = "軸線廣場"
    brief["strips"][0]["typologies"] = ["park"]
    brief["strips"][0]["segment_m"] = [0, 150]
    facts = _facts()

    issue = s6_brief._wide_land_park_coverage_issue(
        brief,
        {"strip-1": facts["buildable"]["strips"][0]},
    )

    assert issue is not None
    assert issue[0] == "WIDE_LAND_UNDERUSED"
    assert "75.0%" in issue[1]


def test_10m_cross_section_slices_cover_each_facts_band_area_within_one_percent() -> None:
    facts = json.loads((ROOT / "artifacts" / "s6-brief" / "facts" / "site-facts.json").read_text(encoding="utf-8"))
    for strip in facts["geometry"]["strips"]:
        strip_id = str(strip["id"])
        band = shape(strip["geometry"])
        axis = s6_brief._axis_line(shape(strip["axis"]))
        station_length = s6_brief._station_length(facts, strip_id, axis)
        assert axis is not None and station_length is not None

        slices = s6_brief._partition_strip_geometry(axis, band, station_length, step_m=10.0)
        sliced_area = sum(piece.area for piece in slices)
        relative_error = abs(sliced_area - band.area) / band.area
        assert relative_error < 0.01, (strip_id, band.area, sliced_area, relative_error)


def test_open_space_target_area_must_fit_inside_its_segment() -> None:
    brief = _valid_brief()
    brief["open_spaces"][0]["area_m2_target"] = 10_000_000
    issues = s6_brief._validate_brief(brief, _facts())
    assert any(code == "OPEN_SPACE_EXCEEDS_SEGMENT" for code, _message in issues), issues


def test_open_space_target_area_within_segment_passes() -> None:
    brief = _valid_brief()
    brief["open_spaces"][0]["area_m2_target"] = 1
    issues = s6_brief._validate_brief(brief, _facts())
    assert not any(code == "OPEN_SPACE_EXCEEDS_SEGMENT" for code, _message in issues), issues


def test_strip_rows_must_carry_segments_and_cover_strip() -> None:
    brief = _valid_brief()
    brief["strips"][0].pop("segment_m")
    codes = {code for code, _message in s6_brief._validate_brief(brief, _facts())}
    assert {"STRIP_SEGMENT_REQUIRED", "STRIP_COVERAGE_LOW"} <= codes


def test_strip_coverage_low_when_segments_cover_under_85_percent() -> None:
    brief = _valid_brief()
    brief["strips"][0]["segment_m"] = [0, 100]
    codes = {code for code, _message in s6_brief._validate_brief(brief, _facts())}
    assert "STRIP_COVERAGE_LOW" in codes
