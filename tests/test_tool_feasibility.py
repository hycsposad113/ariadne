"""Owned Milestone 1 feasibility and reconciliation tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.tool_feasibility_probe import (
    FIXTURE_PATH,
    _new_run_root,
    build_m1_gate_manifest,
    manifest_for_directory,
    reconcile_outcome,
    run_m1_gate_tests,
    validate_qgis_probe_request,
)
from urban_design.gates import M1_GATE_DEFINITIONS, EvidenceRefRecord, M1GateRecord, REVIEWER_ID
from urban_design.probe_contracts import validate_probe_report


def test_fixture_has_locked_controls_and_sensor_area() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["units"] == "m"
    assert fixture["offset_axis"] == "x"
    assert fixture["offsets_m"] == [0.0, -1.0, 1.0]
    assert fixture["sensor"]["area_m2"] == 4.0
    assert all(fixture["locked_controls"].values())


def test_forbidden_qgis_operations_are_rejected(tmp_path: Path) -> None:
    for operation in ("execute_code", "qgis.execute_code", "dynamic_python", "run_sql", "batch_process"):
        with pytest.raises(PermissionError, match="denied"):
            validate_qgis_probe_request(operation, output_path=tmp_path / "out.gpkg", controlled_root=tmp_path)


def test_allowed_qgis_operation_is_validation_only(tmp_path: Path) -> None:
    result = validate_qgis_probe_request(
        "urban.validate_crs", output_path=tmp_path / "out.gpkg", controlled_root=tmp_path
    )
    assert result == {"operation": "urban.validate_crs", "allowed": True, "dispatched": False}
    with pytest.raises(PermissionError, match="outside"):
        validate_qgis_probe_request(
            "urban.validate_crs", output_path=tmp_path.parent / "out.gpkg", controlled_root=tmp_path
        )


def test_outcome_unknown_does_not_blindly_retry(tmp_path: Path) -> None:
    expected = tmp_path / "result.bin"
    unknown = reconcile_outcome(
        dispatch_status="OUTCOME_UNKNOWN",
        expected_artifact=expected,
        expected_sha256=None,
        observed_project_revision="r1",
        expected_project_revision="r1",
        ledger_record_present=False,
    )
    assert unknown["status"] == "OUTCOME_UNKNOWN"
    assert unknown["retry_allowed"] is False


def test_outcome_unknown_resolves_only_with_matching_evidence(tmp_path: Path) -> None:
    expected = tmp_path / "result.bin"
    expected.write_bytes(b"controlled-result")
    digest = "sha256:" + hashlib.sha256(b"controlled-result").hexdigest()
    resolved = reconcile_outcome(
        dispatch_status="OUTCOME_UNKNOWN",
        expected_artifact=expected,
        expected_sha256=digest,
        observed_project_revision="r1",
        expected_project_revision="r1",
        ledger_record_present=True,
    )
    assert resolved["status"] == "SUCCEEDED"
    assert resolved["retry_allowed"] is False
    unresolved = reconcile_outcome(
        dispatch_status="OUTCOME_UNKNOWN",
        expected_artifact=expected,
        expected_sha256=digest,
        observed_project_revision="r2",
        expected_project_revision="r1",
        ledger_record_present=True,
    )
    assert unresolved["status"] == "OUTCOME_UNKNOWN"


def test_outcome_unknown_rejects_artifact_hash_mismatch(tmp_path: Path) -> None:
    expected = tmp_path / "result.bin"
    expected.write_bytes(b"unexpected-result")
    mismatch = reconcile_outcome(
        dispatch_status="OUTCOME_UNKNOWN",
        expected_artifact=expected,
        expected_sha256="sha256:" + hashlib.sha256(b"expected-result").hexdigest(),
        observed_project_revision="r1",
        expected_project_revision="r1",
        ledger_record_present=True,
    )
    assert mismatch["status"] == "TOOL_FAILED"
    assert mismatch["retry_allowed"] is False


def test_manifest_hashes_successful_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "nested" / "output.json"
    artifact.parent.mkdir()
    artifact.write_text('{"ok": true}\n', encoding="utf-8")
    manifest = manifest_for_directory(tmp_path)
    assert manifest[0]["path"] == "nested/output.json"
    assert manifest[0]["size_bytes"] > 0
    assert manifest[0]["sha256"].startswith("sha256:")


def test_report_contract_is_explicit() -> None:
    report_path = Path(__file__).parents[1] / "docs" / "milestone1-feasibility.md"
    report = report_path.read_text(encoding="utf-8")
    required = (
        "SEC-001",
        "SEC-005",
        "SEC-006",
        "CLM-001",
        "CLM-002",
        "OUTCOME_UNKNOWN",
        "x86_64",
        "arm64",
        "No Radiance installation was found",
    )
    for marker in required:
        assert marker in report
    assert "QGIS MCP" in report
    assert "127.0.0.1:9876" in report
    assert "QGIS MCP route is unavailable" not in report


def test_probe_output_root_is_run_scoped(tmp_path: Path) -> None:
    first = _new_run_root(tmp_path)
    second = _new_run_root(tmp_path)
    assert first != second
    assert first.is_dir() and second.is_dir()
    assert len(list(tmp_path.iterdir())) == 2


def test_qgis_gate_requires_live_facade_evidence(tmp_path: Path) -> None:
    raw_qgis = tmp_path / "raw" / "qgis" / "qgis-report.json"
    raw_qgis.parent.mkdir(parents=True)
    raw_qgis.write_text("{}", encoding="utf-8")
    report = {
        "climate": {
            "ladybug": {"status": "PASS", "runs": [{"status": "SUCCEEDED"}]},
            "honeybee_radiance": {"status": "PASS", "runs": [{"status": "SUCCEEDED"}]},
        },
        "qgis": {"facade_smoke": {"status": "BLOCKED"}},
    }
    manifest = build_m1_gate_manifest(report, report_root=tmp_path, report_path="composite/probe-report.json")
    qgis = next(item for item in manifest["required_gates"] if item["gate_id"] == "SEC-006")
    assert qgis["status"] == "BLOCKED"


def test_honeybee_requires_incident_radiation_evidence(tmp_path: Path) -> None:
    (tmp_path / "raw" / "climate").mkdir(parents=True)
    report = {
        "climate": {
            "ladybug": {"status": "PASS", "runs": [{"status": "SUCCEEDED"}]},
            "honeybee_radiance": {
                "status": "PASS",
                "runs": [{"status": "SUCCEEDED", "incident_radiation": {"artifact_nonempty": False}}],
            },
        },
        "qgis": {"facade_smoke": {"status": "PASS"}},
    }
    manifest = build_m1_gate_manifest(report, report_root=tmp_path, report_path="composite/probe-report.json")
    honeybee = next(item for item in manifest["required_gates"] if item["gate_id"] == "CLM-002")
    assert honeybee["status"] == "BLOCKED"
    assert manifest["overall_status"] == "BLOCKED"


def test_static_gate_requires_actual_collected_pytest_evidence(tmp_path: Path) -> None:
    manifest = build_m1_gate_manifest(
        {"climate": {}, "qgis": {}}, report_root=tmp_path, report_path="composite/probe-report.json"
    )
    static = next(item for item in manifest["required_gates"] if item["gate_id"] == "DET-002")
    assert static["status"] == "BLOCKED"
    assert static["observed"]["all_collected"] is False
    assert manifest["overall_status"] == "BLOCKED"


def test_gate_record_rejects_expected_observed_mismatch(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}\n", encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(evidence.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="expected and observed"):
        M1GateRecord(
            gate_id="DET-002",
            test_ids=M1_GATE_DEFINITIONS["DET-002"]["tests"],
            fixture_or_run_id="run-1",
            expected={"all_passed": True},
            observed={"all_passed": False},
            evidence_refs=[EvidenceRefRecord(path="evidence.json", sha256=digest, size_bytes=evidence.stat().st_size)],
            status="PASS",
            reviewer=REVIEWER_ID,
            reason="test",
        )


def test_bounded_gate_runner_records_each_mapped_node(tmp_path: Path) -> None:
    result = run_m1_gate_tests(tmp_path / "run")
    assert result["collect_returncode"] == 0
    assert result["returncode"] == 0
    assert result["collected_count"] == len(M1_GATE_DEFINITIONS)
    assert len(result["node_results"]) == len(M1_GATE_DEFINITIONS)
    assert all(item["collected"] and item["outcome"] == "PASS" for item in result["node_results"])


def test_missing_gate_evidence_blocks_even_with_passed_pytest(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    pytest_run = run_m1_gate_tests(run_root)
    (run_root / "raw" / "gates" / "pytest-gate-run.json").unlink()
    manifest = build_m1_gate_manifest(
        {"climate": {}, "qgis": {}},
        report_root=run_root,
        report_path="composite/probe-report.json",
        pytest_run=pytest_run,
        run_id=run_root.name,
    )
    det = next(item for item in manifest["required_gates"] if item["gate_id"] == "DET-002")
    assert det["status"] == "BLOCKED"


def test_source_report_hash_mismatch_blocks_runtime_gate(tmp_path: Path) -> None:
    source = tmp_path / "raw" / "climate" / "climate-report.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"status":"PASS"}\n', encoding="utf-8")
    report = {
        "run_id": "run-1",
        "fixture": {"offsets_m": [0.0, -1.0, 1.0], "sha256": "sha256:" + "0" * 64},
        "source_reports": {"climate": {"path": "raw/climate/climate-report.json", "sha256": "sha256:" + "f" * 64}},
        "climate": {"ladybug": {"status": "PASS", "runs": []}, "honeybee_radiance": {"status": "PASS", "runs": []}},
        "qgis": {"facade_smoke": {"status": "BLOCKED"}},
    }
    manifest = build_m1_gate_manifest(report, report_root=tmp_path, report_path="composite/probe-report.json")
    ladybug = next(item for item in manifest["required_gates"] if item["gate_id"] == "CLM-001")
    assert ladybug["status"] == "BLOCKED"


def test_typed_probe_report_rejects_missing_climate_tier() -> None:
    with pytest.raises(Exception):
        validate_probe_report(
            {
                "probe_id": "invalid",
                "timestamp_utc": "2026-09-14T00:00:00+00:00",
                "runtime": {},
                "fixture": {},
                "qgis": {"facade_smoke": {}},
                "climate": {"ladybug": {"tier": "screening", "status": "PASS", "runs": []}},
                "output_root": "/tmp/run",
            }
        )
