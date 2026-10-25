"""M2-A03 provenance, fail-closed, and blocked-anchor regressions."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from urban_design.analysis_inputs import (
    ArtifactIntegrityError,
    PACKAGE_STATUS_BLOCKED,
    PROPOSED_PROJECT_DECISION,
    ProvenanceValidationError,
    StudyAreaAnchorError,
    build_m2a03_package,
    classify_observation,
    ensure_metric_crs,
    inspect_active_study_area,
    inventory_osm_grocery_tags,
    load_analysis_input_package,
    package_is_stale,
    require_approved_policy,
    sha256_bytes,
    validate_artifact_record,
    validate_normalized_artifact_record,
    validate_snapshot_record,
)
from urban_design.geometry import canonical_geometry_hash
from urban_design.store import ProjectStateStore


NOW = "2026-09-18T12:00:00+00:00"


def _write_geojson(path: Path, *, x: float = 88700.0, y: float = 435700.0) -> tuple[str, str]:
    geometry = {
        "type": "Polygon",
        "coordinates": [[[x, y], [x + 20, y], [x + 20, y + 20], [x, y + 20], [x, y]]],
    }
    payload = {"type": "Feature", "properties": {}, "geometry": geometry}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return canonical_geometry_hash(geometry), sha256_bytes(path.read_bytes())


def _make_store(
    tmp_path: Path,
    *,
    valid_geometry: bool = True,
    study_area_crs: str = "EPSG:28992",
    study_area_units: str = "m",
    version: str = "v4",
    x: float | None = None,
    y: float | None = None,
) -> tuple[Path, str, str, str]:
    database = tmp_path / "state.sqlite3"
    artifact_path = tmp_path / "study-area.geojson"
    geometry_hash, artifact_hash = _write_geojson(
        artifact_path,
        x=x if x is not None else (88700 if valid_geometry else 419),
        y=y if y is not None else (435700 if valid_geometry else -213),
    )
    project_id = "rotterdam-m4h-pilot-project"
    area_id = f"study-area-rotterdam-m4h-pilot-project-{version}"
    artifact_id = "study-area-artifact-test"
    with ProjectStateStore(database) as store:
        store.create_project(
            project_id,
            {
                "id": project_id,
                "name": project_id,
                "active_study_area_id": area_id,
                "site_id": None,
                "status": "proposed",
            },
            actor="fixture",
            reason="fixture project",
        )
        store.create(
            "Artifact",
            {
                "id": artifact_id,
                "type": "study_area_geometry",
                "uri": str(artifact_path),
                "sha256": artifact_hash,
                "mime": "application/geo+json",
                "crs": study_area_crs,
                "producer": "QGIS",
                "created_at": NOW,
                "project_id": project_id,
                "size_bytes": artifact_path.stat().st_size,
                "parent_artifact_ids": [],
            },
            entity_id=artifact_id,
            project_id=project_id,
            actor="fixture",
            reason="fixture artifact",
        )
        confirmation = store.append_ledger_event(
            target_id=area_id,
            target_type="StudyArea",
            project_id=project_id,
            actor="fixture",
            action="ConfirmStudyArea",
            reason="fixture confirmation",
            resulting_refs=(area_id,),
            payload={"confirmation": "CONFIRMED_FOR_EXPLORATION"},
            event_id="confirm-study-area-test",
        )
        store.create(
            "StudyArea",
            {
                "id": area_id,
                "project_id": project_id,
                "version": version,
                "status": "CONFIRMED_FOR_EXPLORATION",
                "source": "HUMAN_DRAWN_QGIS",
                "horizontal_crs": study_area_crs,
                "units": study_area_units,
                "geometry_artifact_id": artifact_id,
                "artifact_sha256": artifact_hash,
                "geometry_sha256": geometry_hash,
                "confirmation_event_id": confirmation.event_id,
                "supersedes_id": None,
            },
            entity_id=area_id,
            project_id=project_id,
            actor="fixture",
            reason="fixture StudyArea",
        )
        store.append_ledger_event(
            target_id=project_id,
            target_type="Project",
            project_id=project_id,
            actor="fixture",
            action="ActivateStudyArea",
            reason="fixture activation",
            resulting_refs=(area_id,),
            payload={"active_study_area_id": area_id},
            event_id="activate-study-area-test",
        )
    return database, project_id, area_id, artifact_path.as_posix()


def _artifact_record(root: Path, name: str = "raw.json") -> dict[str, object]:
    path = root / name
    path.write_bytes(b"raw source bytes")
    return {
        "id": "artifact-raw-test",
        "type": "raw_source",
        "uri": name,
        "sha256": sha256_bytes(path.read_bytes()),
        "mime": "application/json",
        "crs": "EPSG:28992",
        "producer": "test-source",
        "created_at": NOW,
        "project_id": "rotterdam-m4h-pilot-project",
        "size_bytes": path.stat().st_size,
        "parent_artifact_ids": [],
    }


def test_active_study_area_hash_events_and_anchor_are_verified(tmp_path: Path) -> None:
    database, _, _, _ = _make_store(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    inspection = inspect_active_study_area(database)
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    assert after == before
    assert inspection.anchor_status == "VALID"
    assert inspection.query_envelope == (87500.0, 434500.0, 89920.0, 436920.0)
    assert inspection.query_envelope_axis_order == "always_xy"
    assert inspection.pyproj_version
    assert inspection.query_envelope_crs84[0] < inspection.query_envelope_crs84[2]
    assert inspection.query_envelope_crs84[1] < inspection.query_envelope_crs84[3]


def test_default_inspection_resolves_active_v5_and_rejects_stale_v4(tmp_path: Path) -> None:
    database, _, _, _ = _make_store(tmp_path, version="v5")

    inspection = inspect_active_study_area(database)

    assert inspection.study_area_id == "study-area-rotterdam-m4h-pilot-project-v5"
    with pytest.raises(StudyAreaAnchorError, match="stale|active project pointer"):
        inspect_active_study_area(
            database,
            study_area_id="study-area-rotterdam-m4h-pilot-project-v4",
        )


def test_current_v4_is_blocked_without_geographic_anchor(tmp_path: Path) -> None:
    database, _, _, _ = _make_store(tmp_path, valid_geometry=False)
    inspection = inspect_active_study_area(database)
    assert inspection.anchor_status == "OUTSIDE_CRS_AREA_OF_USE"
    assert inspection.query_envelope[-1] == 1007.0


def test_study_area_inside_crs_but_outside_m4h_anchor_is_blocked(tmp_path: Path) -> None:
    database, _, _, _ = _make_store(tmp_path, x=100000, y=400000)

    inspection = inspect_active_study_area(database)

    assert inspection.anchor_status == "OUTSIDE_PROJECT_ANCHOR"
    assert inspection.anchor_reason and "configured M4H anchor" in inspection.anchor_reason


def test_blocked_package_preserves_request_failure_and_observation_event(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, valid_geometry=False)
    package_dir = build_m2a03_package(database, tmp_path / "package", project_id=project_id, study_area_id=area_id)
    package = load_analysis_input_package(package_dir)
    assert package["status"] == PACKAGE_STATUS_BLOCKED
    assert package["failure"]["external_requests_executed"] is False
    assert (package_dir / "request.json").is_file()
    assert (package_dir / "failure-evidence.json").is_file()
    with ProjectStateStore(database) as store:
        events = [event for event in store.events(target_id=package["package_id"]) if event.action == "SnapshotObservation"]
        assert len(events) == 1
        assert not any(event.action in {"AccessibilityResult", "ClimateResult", "Approve"} for event in store.events(project_id=project_id))


def test_raw_artifact_hash_and_missing_bytes_fail_closed(tmp_path: Path) -> None:
    record = _artifact_record(tmp_path)
    assert validate_artifact_record(record, root=tmp_path)["sha256"] == record["sha256"]
    (tmp_path / "raw.json").write_bytes(b"modified")
    with pytest.raises(ArtifactIntegrityError):
        validate_artifact_record(record, root=tmp_path)
    (tmp_path / "raw.json").unlink()
    with pytest.raises(ArtifactIntegrityError):
        validate_artifact_record(record, root=tmp_path)


def test_normalized_artifact_requires_raw_parent_and_hash(tmp_path: Path) -> None:
    raw = _artifact_record(tmp_path)
    normalized_path = tmp_path / "normalized.json"
    normalized_path.write_bytes(b"normalized bytes")
    normalized = {
        **raw,
        "id": "artifact-normalized-test",
        "uri": "normalized.json",
        "sha256": sha256_bytes(normalized_path.read_bytes()),
        "type": "normalized_source",
        "parent_artifact_ids": [raw["id"]],
        "raw_parent_artifact_id": raw["id"],
    }
    assert validate_normalized_artifact_record(normalized, raw_artifact=raw, root=tmp_path)["id"] == normalized["id"]
    invalid = dict(normalized)
    invalid["raw_parent_artifact_id"] = "other-raw"
    with pytest.raises(ProvenanceValidationError):
        validate_normalized_artifact_record(invalid, raw_artifact=raw, root=tmp_path)
def test_snapshot_requires_portable_provenance_and_hash_lineage(tmp_path: Path) -> None:
    artifact = _artifact_record(tmp_path)
    artifacts = {artifact["id"]: artifact}
    base = {
        "id": "snapshot-test",
        "project_id": "rotterdam-m4h-pilot-project",
        "source_url": "https://example.test/source",
        "query": "exact query",
        "retrieved_at": NOW,
        "publisher": "Example Publisher",
        "license": "ODbL-1.0",
        "version": "2026-09-18",
        "attribution": "Example Publisher",
        "sha256": artifact["sha256"],
        "raw_artifact_id": artifact["id"],
        "limitations": ["fixture only"],
        "availability": "OBSERVED",
    }
    assert validate_snapshot_record(base, artifacts=artifacts, root=tmp_path)["id"] == "snapshot-test"
    for field in ("source_url", "license", "retrieved_at", "publisher"):
        invalid = dict(base)
        invalid[field] = "" if field != "retrieved_at" else "2026-09-18T12:00:00"
        with pytest.raises(ProvenanceValidationError):
            validate_snapshot_record(invalid, artifacts=artifacts, root=tmp_path)


def test_metric_crs_and_observation_states_are_fail_closed() -> None:
    assert ensure_metric_crs("EPSG:28992") == "EPSG:28992"
    with pytest.raises(ValueError, match="geographic CRS"):
        ensure_metric_crs("EPSG:4326")
    assert classify_observation("OBSERVED", count=0) == "EMPTY"
    assert classify_observation("UNAVAILABLE") == "UNAVAILABLE"
    assert classify_observation("FAILED") == "FAILED"
    with pytest.raises(ValueError):
        classify_observation("EMPTY", count=1)


def test_wrong_project_study_area_crs_units_and_hash_fail_closed(tmp_path: Path) -> None:
    database, _, area_id, artifact_path = _make_store(tmp_path)
    with pytest.raises(StudyAreaAnchorError):
        inspect_active_study_area(database, project_id="other-project")
    with pytest.raises(StudyAreaAnchorError):
        inspect_active_study_area(database, study_area_id="other-study-area")
    (Path(artifact_path)).write_bytes(b"changed active bytes")
    with pytest.raises(ArtifactIntegrityError):
        inspect_active_study_area(database)
    database, _, _, _ = _make_store(tmp_path / "crs", study_area_crs="EPSG:4326")
    with pytest.raises(StudyAreaAnchorError):
        inspect_active_study_area(database)
    database, _, _, _ = _make_store(tmp_path / "units", study_area_units="degrees")
    with pytest.raises(StudyAreaAnchorError):
        inspect_active_study_area(database)


def test_raw_osm_grocery_categories_remain_recoverable() -> None:
    result = inventory_osm_grocery_tags(
        [
            {"properties": {"@id": "1", "tags": {"shop": "supermarket"}}},
            {"properties": {"@id": "2", "tags": {"shop": "convenience"}}},
            {"properties": {"@id": "3", "tags": {"shop": "grocery"}}},
            {"properties": {"@id": "4", "tags": {"shop": "supermarket"}}},
        ]
    )
    assert result["counts_by_shop_tag"] == {"convenience": 1, "grocery": 1, "supermarket": 2}
    assert {record["shop"] for record in result["records"]} == {"supermarket", "convenience", "grocery"}


def test_proposed_policy_cannot_be_consumed_and_study_area_replacement_is_stale() -> None:
    policy = {"status": PROPOSED_PROJECT_DECISION}
    with pytest.raises(ValueError, match="not approved"):
        require_approved_policy(policy, name="network policy")
    package = {"study_area": {"geometry_sha256": "sha256:" + "a" * 64}}
    assert package_is_stale(package, current_geometry_sha256="sha256:" + "b" * 64)


def test_offline_package_reload_detects_modified_manifest_file(tmp_path: Path) -> None:
    database, project_id, area_id, _ = _make_store(tmp_path, valid_geometry=False)
    package_dir = build_m2a03_package(database, tmp_path / "package", project_id=project_id, study_area_id=area_id)
    (package_dir / "request.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError):
        load_analysis_input_package(package_dir)


def _pdok_page(feature_id: str) -> bytes:
    payload = {
        "type": "FeatureCollection",
        "timeStamp": NOW,
        "numberReturned": 1,
        "numberMatched": 1,
        "features": [
            {
                "type": "Feature",
                "id": feature_id,
                "properties": {"identificatie": feature_id},
                "geometry": {"type": "Polygon", "coordinates": [[[4.42, 51.90], [4.421, 51.90], [4.421, 51.901], [4.42, 51.901], [4.42, 51.90]]]},
            }
        ],
    }
    return json.dumps(payload).encode()


def _osm_body(*, rich: bool) -> bytes:
    elements: list[dict[str, object]] = []
    if rich:
        elements = [
            {"type": "way", "id": 11, "nodes": [111, 112], "tags": {"highway": "footway", "foot": "yes"}, "geometry": [{"lat": 51.9, "lon": 4.42}, {"lat": 51.901, "lon": 4.421}]},
            {"type": "way", "id": 12, "nodes": [121, 122], "tags": {"highway": "residential", "access": "private"}, "geometry": [{"lat": 51.902, "lon": 4.422}, {"lat": 51.903, "lon": 4.423}]},
            {"type": "node", "id": 21, "lat": 51.9005, "lon": 4.4205, "tags": {"shop": "supermarket", "entrance": "yes"}},
            {"type": "node", "id": 22, "lat": 51.9006, "lon": 4.4206, "tags": {"shop": "convenience"}},
            {"type": "node", "id": 23, "lat": 51.9007, "lon": 4.4207, "tags": {"public_transport": "stop_position"}},
        ]
    return json.dumps({"osm3s": {"timestamp_osm_base": NOW}, "elements": elements}).encode()


def _spatial_fetcher(*, mode: str = "rich"):
    def fetch(url: str, **_kwargs: object):
        lowered = url.lower()
        if lowered.endswith(".zip") or lowered.endswith(".epw") or "climate.onebuilding.org" in lowered:
            raise RuntimeError(f"weather source requested: {url}")
        if mode == "pdok-fail" and "/collections/" in url:
            raise RuntimeError("simulated PDOK transport failure")
        if mode == "osm-fail" and "overpass" in url:
            raise RuntimeError("simulated Overpass transport failure")
        if "overpass" in url:
            return _osm_body(rich=mode == "rich"), 200, {}, NOW
        return _pdok_page("feature-1"), 200, {}, NOW

    return fetch


def _snapshot_count(database: Path) -> int:
    with ProjectStateStore(database) as store:
        return int(store.connection.execute("SELECT COUNT(*) FROM state_heads WHERE entity_type = 'DatasetSnapshot'").fetchone()[0])


def test_spatial_package_contract_excludes_weather_and_replays_without_requests(tmp_path: Path) -> None:
    from urban_design.analysis_inputs import (
        AnalysisInputError,
        build_m2a03_spatial_package,
        load_m2a03_spatial_package,
        require_spatial_package_use,
    )
    from urban_design.study_area_workflow import FormalClaimGuardError, validate_formal_claim

    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    package_dir = build_m2a03_spatial_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="spatial-r01",
        created_at=NOW,
        fetcher=_spatial_fetcher(),
    )
    package = load_m2a03_spatial_package(package_dir)
    assert package["schema_version"] == "m2-a03-spatial-input-decision-package-v1"
    assert package["track"] == "SPATIAL_INPUT"
    assert package["status"] == "READY_FOR_HUMAN_REVIEW"
    assert package["weather_gate"] == {
        "status": "SEMANTICS_UNRESOLVED",
        "required_for": "WEEK_6",
        "blocks_spatial_track": False,
        "evidence_refs": ["R09", "R09-R01"],
    }
    assert package["crs_record"]["horizontal_crs"] == "EPSG:28992"
    assert package["crs_record"]["units"] == "m"
    assert package["crs_record"]["vertical_reference"] is None
    assert package["no_accessibility_result"] is True
    assert package["no_climate_result"] is True
    assert package["formal_claim_status"] == "BLOCKED"
    assert "weather_candidates" not in package
    assert "weather_selection" not in package["proposed_policies"]
    assert not list(package_dir.rglob("*.epw"))
    assert not list(package_dir.rglob("*.zip"))
    assert package["origin_inventory"]["count"] == 2
    assert package["grocery_inventory"]["counts_by_shop_tag"]["supermarket"] == 1
    assert package["decision_packet"]["selected_origin_ids"] is None
    assert package["decision_packet"]["approval_reason"] is None
    with pytest.raises(FormalClaimGuardError):
        validate_formal_claim("CADASTRAL")
    with pytest.raises(FormalClaimGuardError):
        validate_formal_claim("OWNERSHIP")
    before = _snapshot_count(database)
    replayed = build_m2a03_spatial_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="spatial-r01",
        fetcher=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("replay issued a live request")),
    )
    assert replayed == package_dir
    assert _snapshot_count(database) == before
    assert load_m2a03_spatial_package(package_dir)["package_id"] == package["package_id"]
    raw = next((package_dir / "sources" / "raw").iterdir())
    raw.write_bytes(raw.read_bytes() + b" ")
    with pytest.raises(ArtifactIntegrityError):
        load_m2a03_spatial_package(package_dir)
    raw.write_bytes(raw.read_bytes()[:-1])
    loaded = load_m2a03_spatial_package(package_dir)
    decision = json.loads((package_dir / "spatial-input-decision-package.json").read_text(encoding="utf-8"))
    decision["artifacts"] = [record for record in decision["artifacts"] if record["id"] != decision["normalized_artifacts"][0]["raw_parent_artifact_id"]]
    (package_dir / "spatial-input-decision-package.json").write_text(json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = json.loads((package_dir / "package-manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        data = (package_dir / entry["path"]).read_bytes()
        entry["sha256"] = sha256_bytes(data)
        entry["size_bytes"] = len(data)
    (package_dir / "package-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ProvenanceValidationError, match="raw parent"):
        load_m2a03_spatial_package(package_dir)
    stale = dict(loaded)
    with pytest.raises(StudyAreaAnchorError, match="stale"):
        require_spatial_package_use(stale, active_geometry_sha256="sha256:" + "ab" * 32)
    invalid = json.loads(json.dumps(loaded))
    invalid["crs_record"]["horizontal_crs"] = "EPSG:4326"
    with pytest.raises(AnalysisInputError):
        require_spatial_package_use(invalid, active_geometry_sha256=loaded["study_area"]["geometry_sha256"])


def test_spatial_source_failures_do_not_publish_a_complete_snapshot_set(tmp_path: Path) -> None:
    from urban_design.analysis_inputs import build_m2a03_spatial_package, load_m2a03_spatial_package

    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    empty_dir = build_m2a03_spatial_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="spatial-empty",
        created_at=NOW,
        fetcher=_spatial_fetcher(mode="empty"),
    )
    empty_package = load_m2a03_spatial_package(empty_dir)
    assert empty_package["status"] == "READY_FOR_HUMAN_REVIEW"
    assert empty_package["origin_inventory"]["status"] == "EMPTY"
    assert empty_package["origin_inventory"]["count"] == 0
    assert empty_package["grocery_inventory"]["status"] == "EMPTY"
    blocked_dir = build_m2a03_spatial_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="spatial-pdok-fail",
        created_at=NOW,
        fetcher=_spatial_fetcher(mode="pdok-fail"),
    )
    blocked = load_m2a03_spatial_package(blocked_dir)
    assert blocked["status"] == "BLOCKED"
    assert blocked["snapshots"] == []
    assert blocked["origin_inventory"]["status"] == "UNAVAILABLE"
    assert blocked["origin_inventory"]["count"] is None
    assert "counts_by_shop_tag" not in blocked["grocery_inventory"]
    osm_dir = build_m2a03_spatial_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="spatial-osm-fail",
        created_at=NOW,
        fetcher=_spatial_fetcher(mode="osm-fail"),
    )
    osm_blocked = load_m2a03_spatial_package(osm_dir)
    assert osm_blocked["status"] == "BLOCKED"
    assert osm_blocked["snapshots"] == []
    assert _snapshot_count(database) == len(empty_package["snapshots"])


def test_spatial_publication_failure_is_retryable_and_preserves_peers(tmp_path: Path) -> None:
    from urban_design.analysis_inputs import AnalysisInputPublicationError, build_m2a03_spatial_package

    database, project_id, area_id, _ = _make_store(tmp_path, version="v5", x=88700, y=435700)
    output = tmp_path / "packages"
    peer = output / "peer-package"
    peer.mkdir(parents=True)
    (peer / "keep.txt").write_text("keep\n", encoding="utf-8")

    def publisher(_stage: Path, _target: Path) -> None:
        raise OSError("injected publication failure")

    with pytest.raises(AnalysisInputPublicationError, match="retry is safe"):
        build_m2a03_spatial_package(
            database,
            output,
            project_id=project_id,
            study_area_id=area_id,
            package_revision="spatial-publish-fail",
            created_at=NOW,
            fetcher=_spatial_fetcher(),
            package_publisher=publisher,
        )
    assert (peer / "keep.txt").read_text(encoding="utf-8") == "keep\n"
    assert _snapshot_count(database) == 0
    package_dir = build_m2a03_spatial_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="spatial-publish-fail",
        created_at=NOW,
        fetcher=_spatial_fetcher(),
    )
    assert _snapshot_count(database) > 0
    with pytest.raises(AnalysisInputPublicationError, match="retry is safe"):
        build_m2a03_spatial_package(
            database,
            output,
            project_id=project_id,
            study_area_id=area_id,
            package_revision="spatial-sqlite-fail",
            created_at=NOW,
            fetcher=_spatial_fetcher(),
            commit_hook=lambda: (_ for _ in ()).throw(OSError("injected SQLite interruption")),
        )
    assert (peer / "keep.txt").exists()
    recovered = build_m2a03_spatial_package(
        database,
        output,
        project_id=project_id,
        study_area_id=area_id,
        package_revision="spatial-sqlite-fail",
        fetcher=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("retry fetched")),
    )
    assert recovered.name.endswith("spatial-sqlite-fail")
    assert package_dir.exists()
