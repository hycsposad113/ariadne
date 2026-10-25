from __future__ import annotations

import hashlib
import json
import os
import signal
from pathlib import Path

import pytest

from urban_design.morphology.preview_catalog import PreviewCatalogError, get_asset, load_catalog

GENERATOR = "dictionary-generator-v4"
ROWS = (("A", "perimeter_block_city"), ("B", "linear_green_mixed"))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put_json(path: Path, value: object, *, allow_nan: bool = False) -> bytes:
    data = json.dumps(value, allow_nan=allow_nan).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def make_bundle(root: Path, *, crs: str = "EPSG:28992", nonfinite: bool = False) -> tuple[Path, str]:
    root.mkdir(parents=True)
    strategies = []
    for intensity, strategy in ROWS:
        sid = f"{intensity}-{strategy}-seed-42"
        shash = digest(sid.encode())
        warnings = ["1 unknown retained floor estimate(s); known-part FAR is reported separately"]
        folder = root / intensity / strategy
        plan, axon = b"\x89PNG\r\n\x1a\nplan", b"\x89PNG\r\n\x1a\naxon"
        (folder / "plan.png").parent.mkdir(parents=True)
        (folder / "plan.png").write_bytes(plan)
        (folder / "axonometric.png").write_bytes(axon)
        recipe = {
            "schema_version": "morphology-recipe-v1", "id": strategy,
            "recipe_path": "/private/host/recipe.json", "recipe_sha256": "a" * 64,
            "run": {"intensity": intensity, "scenario_hash": shash, "seed": 42},
        }
        recipe_bytes = put_json(folder / "recipe.json", recipe)
        metrics = {
            "generation_metadata": {
                "generator_version": GENERATOR, "recipe_id": strategy,
                "recipe_sha256": "a" * 64,
                "dictionary_catalogue": {"sha256": "b" * 64},
                "source_provenance": {"study_area": {"file_sha256": "c" * 64}},
            },
            "human_decision_created": False,
            "intensity": {"code": intensity, "coverage_upper_bound": 0.5 if intensity == "B" else None,
                          "far_upper_bound_land": 2.0 if intensity == "B" else 1.5,
                          "height_upper_bound_new_buildings_m": 40.0 if intensity == "B" else 20.0},
            "metrics": {
                "far_land_area": {
                    "denominator_area_m2": 100.0, "known_gfa_m2": 125.0,
                    "known_retained_gfa_m2": 25.0, "known_value": 1.25,
                    "new_gfa_m2": 100.0, "status": "KNOWN_PARTIAL_WITH_UNKNOWN_RETAINED_COUNT",
                    "unknown_floor_warning": True, "unknown_retained_building_count": 1,
                    "upper_bound": 2.0, "upper_bound_check": "PASS",
                },
                "coverage_ratio": {
                    "denominator_area_m2": 100.0, "footprint_union_area_m2": 25.0,
                    "upper_bound": 0.5, "upper_bound_check": "PASS", "value": 0.25,
                },
                "maximum_height_m": {
                    "generated_building_m": 20.0, "generated_height_upper_bound_check": "PASS",
                    "generated_height_upper_bound_m": 40.0, "known_all_building_m": 20.0,
                    "known_preserved_building_m": 18.0, "unknown_preserved_building_count": 1,
                },
                "open_space_ratio": {
                    "area_m2": 50.0, "denominator_area_m2": 100.0,
                    "method": "fixture source transcription", "value": 0.5,
                },
                "building_count": 1,
            },
            "orientation": {"value_deg": 0.0},
            "scenario_hash": shash, "scenario_id": sid,
            "scenario_status": "UNAPPROVED_PREVIEW", "valid": True,
            "validation": {"valid": True, "checks": {"geometry": "PASS"}, "warnings": warnings},
        }
        metrics_bytes = put_json(folder / "metrics.json", metrics)
        x = float("nan") if nonfinite else 0.0
        y = 435_500.0
        geo = {
            "type": "FeatureCollection", "name": sid,
            "crs": {"type": "name", "properties": {"name": crs}},
            "properties": {"generator_version": GENERATOR, "scenario_hash": shash, "validation_valid": True},
            "features": [
                {"type": "Feature", "id": "site", "properties": {"feature_kind": "study_area"},
                 "geometry": {"type": "Polygon", "coordinates": [[[x, y], [10, y], [10, y + 10], [x, y + 10], [x, y]]]}},
                {"type": "Feature", "id": "retained-1",
                 "properties": {"feature_kind": "preserved_building", "confidence": "LOW",
                                "floor_estimate_status": "UNKNOWN", "floor_count": None, "height_m": None},
                 "geometry": {"type": "Polygon", "coordinates": [[[1, y + 1], [2, y + 1], [2, y + 2], [1, y + 2], [1, y + 1]]]}},
                {"type": "Feature", "id": "generated-1",
                 "properties": {"feature_kind": "generated_building"},
                 "geometry": {"type": "Polygon", "coordinates": [[[3, y + 3], [4, y + 3], [4, y + 4], [3, y + 4], [3, y + 3]]]}},
            ],
        }
        geo_bytes = put_json(folder / "scenario.geojson", geo, allow_nan=nonfinite)
        hashes = {name: digest(data) for name, data in {
            "axonometric.png": axon, "metrics.json": metrics_bytes, "plan.png": plan,
            "recipe.json": recipe_bytes, "scenario.geojson": geo_bytes,
        }.items()}
        strategies.append({
            "artifact_hashes": hashes, "building_count": 1, "coverage_ratio": 0.25,
            "external_contacts": {"available": 0, "connected": 0, "observed": 0},
            "failure_reasons": [], "intensity": intensity, "land_far": 1.25,
            "maximum_height_m": 20.0, "open_space_ratio": 0.5, "scenario_hash": shash,
            "scenario_id": sid, "strategy_id": strategy, "strategy_label": strategy,
            "type_composition": {}, "valid": True, "warnings": warnings,
        })
    (root / "comparison.png").write_bytes(b"\x89PNG\r\n\x1a\ncomparison")
    comparison = {
        "decision_rule": None, "generator_version": GENERATOR, "human_decision_created": False,
        "limitations": ["Run date and source revision were not recorded."], "overall_winner": None,
        "run_status": "UNAPPROVED_PREVIEW", "schema_version": "dictionary-generator-comparison-v1",
        "seed": 42, "strategy_count": 2, "valid_count_by_intensity": {"A": 1, "B": 1},
        "study_area": {"file_sha256": "d" * 64, "geometry_area_m2": 100.0,
                       "geometry_sha256": "sha256:" + "e" * 64, "horizontal_crs": "EPSG:28992",
                       "id": "study-area-fixture-v1", "source_file": "source/study-area.geojson",
                       "units": "m", "version": "v1"},
        "strategies": strategies,
    }
    put_json(root / "comparison.json", comparison)
    return root, reseal(root)


def reseal(root: Path) -> str:
    comparison_path = root / "comparison.json"
    comparison = json.loads(comparison_path.read_text())
    for candidate in comparison["strategies"]:
        for name in ("scenario.geojson", "metrics.json", "recipe.json", "plan.png", "axonometric.png"):
            asset_path = root / candidate["intensity"] / candidate["strategy_id"] / name
            candidate["artifact_hashes"][name] = digest(asset_path.read_bytes())
    put_json(comparison_path, comparison)
    return reseal_manifest(root)


def reseal_manifest(root: Path) -> str:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "artifact-manifest.json":
            data = path.read_bytes()
            files[path.relative_to(root).as_posix()] = {"sha256": digest(data), "size_bytes": len(data)}
    manifest = {"algorithm": "SHA-256", "files": files, "manifest_excludes_self": True,
                "schema_version": "dictionary-generator-artifact-manifest-v1"}
    return digest(put_json(root / "artifact-manifest.json", manifest))


def test_loads_pinned_catalog_and_preserves_unknown_provenance(tmp_path: Path) -> None:
    root, pin = make_bundle(tmp_path / "bundle")
    catalog = load_catalog(root, pin)
    assert {item.intensity for item in catalog.identities} == {"A", "B"}
    assert len(catalog.identities) == 2
    assert all(item.status == "UNAPPROVED_PREVIEW" and not item.human_decision_created for item in catalog.identities)
    assert all(item.run_created_at is None and item.generator_commit is None for item in catalog.identities)
    assert catalog.limits_by_intensity["A"].far_upper_bound_land == 1.5
    assert catalog.limits_by_intensity["B"].height_upper_bound_new_buildings_m == 40.0
    retained = catalog.get_preview("A", "perimeter_block_city").retained_buildings[0]
    assert (retained.confidence, retained.floor_estimate_status, retained.floor_count) == ("LOW", "UNKNOWN", None)
    assert "1 unknown retained floor estimate(s); known-part FAR is reported separately" in (
        catalog.get_preview("A", "perimeter_block_city").metrics.warnings
    )


def test_rejects_manifest_digest_drift(tmp_path: Path) -> None:
    root, _ = make_bundle(tmp_path / "bundle")
    with pytest.raises(PreviewCatalogError, match="manifest"):
        load_catalog(root, "0" * 64)


def test_intentionally_serves_startup_verified_bytes_without_post_startup_drift_checks(tmp_path: Path) -> None:
    """Source drift is intentionally not detected after startup; pinned bytes remain served."""
    root, pin = make_bundle(tmp_path / "bundle")
    catalog = load_catalog(root, pin)
    original = get_asset(catalog, "A", "perimeter_block_city", "plan").content
    (root / "A/perimeter_block_city/plan.png").write_bytes(b"later mutation")
    asset = get_asset(catalog, "A", "perimeter_block_city", "plan")
    assert asset.content == original and asset.sha256 == digest(original)


def test_rejects_path_traversal_and_symlink_escape(tmp_path: Path) -> None:
    root, _ = make_bundle(tmp_path / "traversal")
    manifest_path = root / "artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["../outside.png"] = {"sha256": "f" * 64, "size_bytes": 1}
    pin = digest(put_json(manifest_path, manifest))
    with pytest.raises(PreviewCatalogError, match="path"):
        load_catalog(root, pin)

    root, _ = make_bundle(tmp_path / "symlink")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside bytes")
    asset_path = root / "A/perimeter_block_city/plan.png"
    asset_path.unlink()
    asset_path.symlink_to(outside)
    pin = reseal(root)
    with pytest.raises(PreviewCatalogError, match="symlink|path|contain"):
        load_catalog(root, pin)


def test_rejects_asset_hash_drift_and_identity_drift(tmp_path: Path) -> None:
    root, pin = make_bundle(tmp_path / "hash")
    (root / "A/perimeter_block_city/plan.png").write_bytes(b"corrupt")
    with pytest.raises(PreviewCatalogError, match="hash|size|integrity"):
        load_catalog(root, pin)

    root, _ = make_bundle(tmp_path / "identity")
    path = root / "A/perimeter_block_city/metrics.json"
    data = json.loads(path.read_text())
    data["scenario_id"] = "A-other-seed-42"
    put_json(path, data)
    with pytest.raises(PreviewCatalogError, match="identity|scenario"):
        load_catalog(root, reseal(root))


@pytest.mark.parametrize(
    ("summary_field", "incorrect_value"),
    (
        ("land_far", 9.0),
        ("coverage_ratio", 0.9),
        ("maximum_height_m", 39.0),
        ("open_space_ratio", 0.9),
        ("building_count", 8),
    ),
)
def test_rejects_comparison_metric_summaries_that_drift_from_metrics_artifact(
    tmp_path: Path,
    summary_field: str,
    incorrect_value: int | float,
) -> None:
    root, _ = make_bundle(tmp_path / summary_field)
    comparison_path = root / "comparison.json"
    comparison = json.loads(comparison_path.read_text())
    comparison["strategies"][0][summary_field] = incorrect_value
    put_json(comparison_path, comparison)

    with pytest.raises(PreviewCatalogError, match="summary does not match metrics.json"):
        load_catalog(root, reseal(root))


def test_rejects_comparison_warning_that_drops_partial_far_caveat(tmp_path: Path) -> None:
    root, _ = make_bundle(tmp_path / "warnings")
    comparison_path = root / "comparison.json"
    comparison = json.loads(comparison_path.read_text())
    comparison["strategies"][0]["warnings"] = []
    put_json(comparison_path, comparison)

    with pytest.raises(PreviewCatalogError, match="warnings summary does not match metrics.json"):
        load_catalog(root, reseal(root))


def test_rejects_wrong_crs_and_nonfinite_geometry(tmp_path: Path) -> None:
    root, pin = make_bundle(tmp_path / "wrong-crs", crs="EPSG:4326")
    with pytest.raises(PreviewCatalogError, match="CRS|crs"):
        load_catalog(root, pin)
    root, pin = make_bundle(tmp_path / "nonfinite", nonfinite=True)
    with pytest.raises(PreviewCatalogError, match="finite|JSON|geometry"):
        load_catalog(root, pin)


@pytest.mark.parametrize("manifest_change", ("extra", "missing"))
def test_rejects_manifest_inventory_with_extra_or_missing_rows(tmp_path: Path, manifest_change: str) -> None:
    root, _ = make_bundle(tmp_path / manifest_change)
    manifest_path = root / "artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest_change == "extra":
        manifest["files"]["unexpected.bin"] = {"sha256": digest(b"extra"), "size_bytes": 5}
    else:
        del manifest["files"]["A/perimeter_block_city/plan.png"]
    pin = digest(put_json(manifest_path, manifest))

    with pytest.raises(PreviewCatalogError):
        load_catalog(root, pin)


def test_rejects_candidate_asset_hash_that_does_not_match_manifest(tmp_path: Path) -> None:
    root, _ = make_bundle(tmp_path / "candidate-hash")
    comparison_path = root / "comparison.json"
    comparison = json.loads(comparison_path.read_text())
    comparison["strategies"][0]["artifact_hashes"]["plan.png"] = "0" * 64
    comparison_bytes = put_json(comparison_path, comparison)
    manifest_path = root / "artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"]["comparison.json"] = {
        "sha256": digest(comparison_bytes),
        "size_bytes": len(comparison_bytes),
    }
    pin = digest(put_json(manifest_path, manifest))

    with pytest.raises(PreviewCatalogError, match="candidate artifact hash mismatch"):
        load_catalog(root, pin)


def test_rejects_invalid_geometry(tmp_path: Path) -> None:
    root, _ = make_bundle(tmp_path / "invalid-geometry")
    scenario_path = root / "A/perimeter_block_city/scenario.geojson"
    geojson = json.loads(scenario_path.read_text())
    geojson["features"][1]["geometry"]["coordinates"] = [
        [[1, 435501], [2, 435502], [1, 435502], [2, 435501], [1, 435501]]
    ]
    put_json(scenario_path, geojson)
    with pytest.raises(PreviewCatalogError, match="invalid geometry|invalid at feature"):
        load_catalog(root, reseal(root))


def test_rejects_feature_geometry_outside_the_study_area_bbox(tmp_path: Path) -> None:
    root, _ = make_bundle(tmp_path / "outside-study-area")
    scenario_path = root / "A/perimeter_block_city/scenario.geojson"
    geojson = json.loads(scenario_path.read_text())
    geojson["features"][2]["geometry"]["coordinates"] = [
        [[100, 435503], [101, 435503], [101, 435504], [100, 435504], [100, 435503]]
    ]
    put_json(scenario_path, geojson)
    with pytest.raises(PreviewCatalogError, match="StudyArea bounding box"):
        load_catalog(root, reseal(root))


@pytest.mark.parametrize(
    ("field", "value"),
    (("floor_count", 0), ("height_m", 2.5)),
)
def test_rejects_unknown_retained_building_with_known_floor_or_height(
    tmp_path: Path,
    field: str,
    value: int | float,
) -> None:
    root, _ = make_bundle(tmp_path / "unknown-zero")
    scenario_path = root / "A/perimeter_block_city/scenario.geojson"
    geojson = json.loads(scenario_path.read_text())
    geojson["features"][1]["properties"][field] = value
    put_json(scenario_path, geojson)

    with pytest.raises(PreviewCatalogError, match="UNKNOWN.*null"):
        load_catalog(root, reseal(root))


@pytest.mark.parametrize("missing_field", ("floor_count", "height_m"))
def test_rejects_unknown_retained_building_with_missing_null_field(tmp_path: Path, missing_field: str) -> None:
    root, _ = make_bundle(tmp_path / "unknown-missing")
    scenario_path = root / "A/perimeter_block_city/scenario.geojson"
    geojson = json.loads(scenario_path.read_text())
    del geojson["features"][1]["properties"][missing_field]
    put_json(scenario_path, geojson)

    with pytest.raises(PreviewCatalogError, match="UNKNOWN.*null"):
        load_catalog(root, reseal(root))


def test_rejects_building_count_that_does_not_match_generated_building_features(tmp_path: Path) -> None:
    root, _ = make_bundle(tmp_path / "generated-count")
    comparison_path = root / "comparison.json"
    comparison = json.loads(comparison_path.read_text())
    comparison["strategies"][0]["building_count"] = 2
    put_json(comparison_path, comparison)
    metrics_path = root / "A/perimeter_block_city/metrics.json"
    metrics = json.loads(metrics_path.read_text())
    metrics["metrics"]["building_count"] = 2
    put_json(metrics_path, metrics)

    with pytest.raises(PreviewCatalogError, match="generated_building"):
        load_catalog(root, reseal(root))


def test_rejects_directory_symlink_in_bundle(tmp_path: Path) -> None:
    root, pin = make_bundle(tmp_path / "directory-symlink")
    candidate_dir = root / "A/perimeter_block_city"
    target_dir = root / "A/perimeter_block_city-retained"
    candidate_dir.rename(target_dir)
    candidate_dir.symlink_to(target_dir.name, target_is_directory=True)

    with pytest.raises(PreviewCatalogError, match="symlink|path"):
        load_catalog(root, pin)


def _raise_fifo_test_timeout(_signum: int, _frame: object) -> None:
    raise TimeoutError("FIFO preview read blocked instead of rejecting a non-regular file")


def test_rejects_fifo_without_blocking(tmp_path: Path, monkeypatch) -> None:
    root, pin = make_bundle(tmp_path / "fifo")
    asset_path = root / "A/perimeter_block_city/plan.png"
    asset_path.rename(asset_path.with_name("plan.png.retained"))
    os.mkfifo(asset_path)
    observed_flags: list[int] = []
    real_open = os.open

    def open_and_record_flags(path, flags, *args, **kwargs):
        if path == asset_path.name:
            observed_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_and_record_flags)
    previous_handler = signal.signal(signal.SIGALRM, _raise_fifo_test_timeout)
    signal.setitimer(signal.ITIMER_REAL, 2)
    try:
        with pytest.raises(PreviewCatalogError):
            load_catalog(root, pin)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
    assert observed_flags
    assert observed_flags[-1] & os.O_NONBLOCK


@pytest.mark.parametrize("point", ((300_001, 435_503), (3, 288_999), (3, 629_001)))
def test_rejects_coordinates_outside_epsg_28992_reasonable_bounds(tmp_path: Path, point: tuple[int, int]) -> None:
    root, _ = make_bundle(tmp_path / f"coordinate-{point[0]}-{point[1]}")
    scenario_path = root / "A/perimeter_block_city/scenario.geojson"
    geojson = json.loads(scenario_path.read_text())
    x, y = point
    geojson["features"][2]["geometry"]["coordinates"] = [
        [[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]
    ]
    put_json(scenario_path, geojson)

    with pytest.raises(PreviewCatalogError, match="EPSG:28992 coordinate bounds"):
        load_catalog(root, reseal(root))


def test_rejects_unknown_schema_status_and_duplicate_json_keys(tmp_path: Path) -> None:
    root, _ = make_bundle(tmp_path / "schema")
    comparison_path = root / "comparison.json"
    comparison = json.loads(comparison_path.read_text())
    comparison["schema_version"] = "unexpected-comparison-v9"
    put_json(comparison_path, comparison)
    with pytest.raises(PreviewCatalogError, match="schema"):
        load_catalog(root, reseal(root))

    root, _ = make_bundle(tmp_path / "status")
    metrics_path = root / "A/perimeter_block_city/metrics.json"
    metrics = json.loads(metrics_path.read_text())
    metrics["scenario_status"] = "ACCEPTED"
    put_json(metrics_path, metrics)
    with pytest.raises(PreviewCatalogError, match="identity|status"):
        load_catalog(root, reseal(root))

    root, _ = make_bundle(tmp_path / "duplicate")
    comparison_path = root / "comparison.json"
    comparison_path.write_text('{"schema_version":"dictionary-generator-comparison-v1","schema_version":"unexpected"}')
    manifest_path = root / "artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    duplicate_bytes = comparison_path.read_bytes()
    manifest["files"]["comparison.json"] = {
        "sha256": digest(duplicate_bytes),
        "size_bytes": len(duplicate_bytes),
    }
    pin = digest(put_json(manifest_path, manifest))
    with pytest.raises(PreviewCatalogError, match="duplicate"):
        load_catalog(root, pin)
