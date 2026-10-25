"""Machine-readable Milestone 1 gate definitions and fail-closed certification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


M1_GATE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "DET-002": {"tests": ["tests/test_geometry.py::test_det002_known_answer_square"], "evidence": ["tests/fixtures/geometry_100m_square.json"]},
    "DET-003": {"tests": ["tests/test_geometry.py::test_det003_invalid_geometry_fails_closed"], "evidence": ["tests/test_geometry.py"]},
    "DET-008": {"tests": ["tests/test_geometry.py::test_det008_canonical_hash_is_stable"], "evidence": ["tests/test_geometry.py"]},
    "DET-009": {"tests": ["tests/test_geometry.py::test_det009_missing_units_boundary_and_nonfinite_fail_closed"], "evidence": ["tests/test_geometry.py"]},
    "SEC-001": {"tests": ["tests/test_qgis_facade.py::test_policy_denies_unrestricted_and_out_of_root_requests"], "evidence": ["tests/test_qgis_facade.py"]},
    "SEC-002": {"tests": ["tests/test_qgis_facade.py::test_denied_request_is_audited_without_transport"], "evidence": ["tests/test_qgis_facade.py"]},
    "SEC-003": {"tests": ["tests/test_qgis_facade.py::test_facade_allows_registered_operation_but_serializes_dispatch"], "evidence": ["tests/test_qgis_facade.py"]},
    "SEC-005": {"tests": ["tests/test_tool_feasibility.py::test_outcome_unknown_does_not_blindly_retry"], "evidence": ["tests/test_tool_feasibility.py"]},
    "SEC-006": {"tests": ["tests/test_tool_feasibility.py::test_qgis_gate_requires_live_facade_evidence"], "evidence": ["raw/qgis/qgis-report.json"]},
    "CLM-001": {"tests": ["tests/test_tool_feasibility.py::test_fixture_has_locked_controls_and_sensor_area"], "evidence": ["raw/climate/climate-report.json"]},
    "CLM-002": {"tests": ["tests/test_tool_feasibility.py::test_honeybee_requires_incident_radiation_evidence"], "evidence": ["raw/climate/climate-report.json"]},
}

REVIEWER_ID = "automated:m1-gate-runner-v1"
PASS = "PASS"
BLOCKED = "BLOCKED"
_STATUS = {PASS, BLOCKED, "FAIL", "OUTCOME_UNKNOWN"}
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


class EvidenceRefRecord(BaseModel):
    """A re-checkable relative evidence reference."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    size_bytes: int = Field(gt=0)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        path = Path(value)
        if not value.strip() or path.is_absolute() or ".." in path.parts:
            raise ValueError("evidence reference path must be relative and traversal-free")
        return value

    @field_validator("sha256")
    @classmethod
    def hash_format(cls, value: str) -> str:
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            raise ValueError("evidence reference requires a sha256 digest")
        int(value[7:], 16)
        return value


class PytestNodeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    outcome: Literal["PASS", "FAIL", "SKIPPED", "ERROR", "NOT_COLLECTED"]
    collected: bool

    @field_validator("node_id")
    @classmethod
    def node_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pytest node id must be non-empty")
        return value


class PytestRunRecord(BaseModel):
    """Evidence produced by one bounded, non-recursive pytest invocation."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    reviewer: str
    collect_command: list[str]
    command: list[str]
    collect_returncode: int | None
    returncode: int | None
    collected_count: int = Field(ge=0)
    node_results: list[PytestNodeRecord]
    junit_path: str
    collect_stdout: str = ""
    collect_stderr: str = ""
    stdout: str = ""
    stderr: str = ""

    @field_validator("reviewer")
    @classmethod
    def automated_reviewer(cls, value: str) -> str:
        if not value.startswith("automated:"):
            raise ValueError("pytest evidence reviewer must identify an automated executor")
        return value

    @model_validator(mode="after")
    def unique_nodes(self) -> "PytestRunRecord":
        ids = [item.node_id for item in self.node_results]
        if len(ids) != len(set(ids)):
            raise ValueError("pytest node results must be unique")
        return self


class M1GateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate_id: str
    test_ids: list[str]
    fixture_or_run_id: str
    expected: Any
    observed: Any
    evidence_refs: list[EvidenceRefRecord]
    status: str
    reviewer: str
    reason: str

    @field_validator("status")
    @classmethod
    def gate_status(cls, value: str) -> str:
        value = value.upper() if isinstance(value, str) else value
        if value not in _STATUS:
            raise ValueError("unsupported M1 gate status")
        return value

    @field_validator("gate_id", "fixture_or_run_id", "reviewer", "reason")
    @classmethod
    def required_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("gate metadata must be non-empty")
        return value

    @field_validator("test_ids")
    @classmethod
    def required_tests(cls, value: list[str]) -> list[str]:
        if not value or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError("every gate requires at least one mapped test id")
        if len(value) != len(set(value)):
            raise ValueError("gate test ids must be unique")
        return value

    @field_validator("expected", "observed", mode="before")
    @classmethod
    def observation_required(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("expected and observed values are mandatory")
        return value

    @model_validator(mode="after")
    def pass_requires_matching_observation(self) -> "M1GateRecord":
        if self.status == PASS:
            if not self.evidence_refs:
                raise ValueError("a passing gate requires evidence references")
            if self.expected != self.observed:
                raise ValueError("a passing gate requires expected and observed values to match")
        return self


class M1GateManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str = "m1-gates-v2"
    run_id: str
    reviewer: str
    required_gates: list[M1GateRecord]
    overall_status: str
    report_path: str
    pytest_run: PytestRunRecord | None = None

    @field_validator("run_id", "reviewer", "report_path")
    @classmethod
    def manifest_text(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("manifest metadata must be non-empty")
        return value

    @field_validator("overall_status")
    @classmethod
    def overall_value(cls, value: str) -> str:
        if value not in {PASS, BLOCKED}:
            raise ValueError("overall status must be PASS or BLOCKED")
        return value

    @model_validator(mode="after")
    def aggregate_status(self) -> "M1GateManifest":
        expected = set(M1_GATE_DEFINITIONS)
        actual = {gate.gate_id for gate in self.required_gates}
        if len(actual) != len(self.required_gates) or actual != expected:
            raise ValueError("manifest must contain every required M1 gate exactly once")
        if self.reviewer != REVIEWER_ID:
            raise ValueError("manifest reviewer must identify the gate executor")
        calculated = PASS if all(gate.status == PASS for gate in self.required_gates) else BLOCKED
        if self.overall_status != calculated:
            raise ValueError("overall status does not match gate statuses")
        if self.overall_status == PASS and self.pytest_run is None:
            raise ValueError("a passing manifest requires pytest execution evidence")
        return self


def _resolve_path(report_root: Path, path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if path.startswith("tests/") or path.startswith("src/"):
        return _REPO_ROOT / candidate
    return report_root / candidate


def _evidence_ref(report_root: Path, path: str) -> EvidenceRefRecord | None:
    candidate = _resolve_path(report_root, path)
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        return None
    if Path(path).is_absolute():
        try:
            relative = str(candidate.relative_to(report_root))
        except ValueError:
            return None
    else:
        relative = path
    return EvidenceRefRecord(path=relative, sha256=_file_hash(candidate), size_bytes=candidate.stat().st_size)


def _source_valid(report: Mapping[str, Any], report_root: Path, kind: str) -> bool:
    record = report.get("source_reports", {}).get(kind)
    if not isinstance(record, Mapping):
        return False
    path = record.get("path")
    expected = record.get("sha256")
    if not isinstance(path, str) or not isinstance(expected, str):
        return False
    candidate = _resolve_path(report_root, path)
    return candidate.is_file() and candidate.stat().st_size > 0 and _file_hash(candidate) == expected


def _pytest_observation(pytest_run: Mapping[str, Any] | None, test_ids: Sequence[str]) -> tuple[bool, dict[str, Any], str]:
    expected = {"mapped_nodes": list(test_ids), "all_collected": True, "all_passed": True}
    if not isinstance(pytest_run, Mapping):
        return False, {"mapped_nodes": [], "all_collected": False, "all_passed": False}, "pytest gate evidence is unavailable"
    try:
        parsed = PytestRunRecord.model_validate(pytest_run)
    except Exception as exc:
        return False, {"mapped_nodes": [], "all_collected": False, "all_passed": False}, f"invalid pytest evidence: {exc}"
    by_id = {item.node_id: item for item in parsed.node_results}
    observations = [by_id.get(node_id) for node_id in test_ids]
    all_collected = parsed.collect_returncode == 0 and parsed.collected_count == len(parsed.node_results) and parsed.collected_count >= len(test_ids) and all(item is not None and item.collected for item in observations)
    all_passed = all_collected and parsed.returncode == 0 and all(item is not None and item.outcome == PASS for item in observations)
    observed = {"mapped_nodes": list(test_ids), "all_collected": all_collected, "all_passed": all_passed}
    return all_passed, observed, "mapped pytest nodes were collected and passed" if all_passed else "one or more mapped pytest nodes were missing, skipped, failed, or errored"


def _artifact_valid(path: Path, expected_hash: str | None = None, expected_size: int | None = None) -> bool:
    return path.is_file() and path.stat().st_size > 0 and (expected_hash is None or _file_hash(path) == expected_hash) and (expected_size is None or path.stat().st_size == expected_size)


def _run_artifacts_valid(tier_root: Path, run: Mapping[str, Any]) -> bool:
    artifacts = run.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return False
    run_dir = tier_root / str(run.get("run_id", ""))
    if not run_dir.is_dir():
        return False
    return all(
        isinstance(artifact, Mapping)
        and isinstance(artifact.get("path"), str)
        and _artifact_valid(run_dir / artifact["path"], artifact.get("sha256"), artifact.get("size_bytes"))
        for artifact in artifacts
    )


def _resolve_run_file(report_root: Path, tier_root: Path, run: Mapping[str, Any], value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    options = [tier_root / candidate, report_root / "raw" / "climate" / candidate, tier_root / str(run.get("run_id", "")) / candidate]
    return next((item for item in options if item.is_file()), options[0])


def _climate_runtime(report: Mapping[str, Any], report_root: Path, tier: str) -> tuple[bool, dict[str, Any], str, list[str]]:
    expected_offsets = sorted(float(value) for value in report.get("fixture", {}).get("offsets_m", [0.0, -1.0, 1.0]))
    expected = {"offsets_m": expected_offsets, "all_succeeded": True, "provenance_valid": True, "artifacts_hash_valid": True}
    tier_data = report.get("climate", {}).get(tier)
    runs = tier_data.get("runs") if isinstance(tier_data, Mapping) else None
    tier_root = report_root / "raw" / "climate" / tier
    if not isinstance(runs, list):
        return False, {"offsets_m": [], "all_succeeded": False, "provenance_valid": False, "artifacts_hash_valid": False}, "missing climate runs", ["raw/climate/climate-report.json"]
    offsets = sorted(float(run.get("offset_m")) for run in runs if isinstance(run, Mapping) and isinstance(run.get("offset_m"), (int, float)) and math.isfinite(float(run["offset_m"])))
    all_succeeded = isinstance(tier_data, Mapping) and tier_data.get("status") == PASS and offsets == expected_offsets and len(runs) == len(expected_offsets) and all(isinstance(run, Mapping) and run.get("status") == "SUCCEEDED" for run in runs)
    provenance_valid = True
    artifacts_valid = True
    source_hash = report.get("fixture", {}).get("sha256")
    evidence = ["raw/climate/climate-report.json"]
    for run in runs:
        if not isinstance(run, Mapping):
            provenance_valid = artifacts_valid = False
            continue
        if run.get("fixture_sha256") != source_hash or not isinstance(run.get("units"), Mapping) or run.get("units", {}).get("geometry") != "m" or run.get("units", {}).get("result") != "kWh/m2":
            provenance_valid = False
        weather_path = _resolve_run_file(report_root, tier_root, run, run.get("weather_path"))
        if weather_path is None or not _artifact_valid(weather_path, run.get("weather_sha256")) or not _run_artifacts_valid(tier_root, run):
            artifacts_valid = False
        if isinstance(run.get("geometry"), Mapping):
            geometry = run["geometry"]
            if geometry.get("sensor_area_m2") != 4.0 or geometry.get("sensor_outside_context", geometry.get("sensor_outside_building")) is not True:
                provenance_valid = False
        else:
            provenance_valid = False
    if tier == "honeybee_radiance":
        expected_hb = {**expected, "incident_values_valid": True, "spatial_artifacts_valid": True}
        incident_valid = True
        spatial_valid = True
        for run in runs:
            if not isinstance(run, Mapping):
                incident_valid = spatial_valid = False
                continue
            incident = run.get("incident_radiation")
            values = run.get("incident_radiation_values")
            sensor = run.get("sensor_artifact")
            def command_succeeded(name: str) -> bool:
                value = run.get(name)
                if not isinstance(value, Mapping):
                    return False
                command = value.get("command") if isinstance(value.get("command"), Mapping) else value
                return isinstance(command, Mapping) and command.get("returncode") == 0

            commands_ok = all(command_succeeded(name) for name in ("translation", "sky_matrix", "octree", "sky_dome", "incident_radiation"))
            incident_path = _resolve_run_file(report_root, tier_root, run, incident.get("artifact") if isinstance(incident, Mapping) else None)
            if not isinstance(incident, Mapping) or not incident.get("artifact_nonempty") or not commands_ok or not isinstance(values, list) or not values or any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values) or not isinstance(sensor, Mapping) or len(values) != sensor.get("sensor_count") or incident_path is None or not incident_path.is_file():
                incident_valid = False
            spatial = run.get("spatial_artifact")
            spatial_path = _resolve_run_file(report_root, tier_root, run, spatial.get("path") if isinstance(spatial, Mapping) else None)
            spatial_payload_valid = False
            if spatial_path is not None and spatial_path.is_file():
                try:
                    spatial_payload = json.loads(spatial_path.read_text(encoding="utf-8"))
                    sensor_count = sensor.get("sensor_count") if isinstance(sensor, Mapping) else None
                    spatial_payload_valid = (
                        spatial_payload.get("type") == "SensorGridRadiation"
                        and spatial_payload.get("unit") == "kWh/m2"
                        and spatial_payload.get("raw_unit") == "Wh/m2"
                        and spatial_payload.get("sensor_count") == sensor_count
                        and isinstance(spatial_payload.get("sensors"), list)
                        and len(spatial_payload.get("sensors", [])) == sensor_count
                    )
                except (OSError, ValueError, TypeError):
                    spatial_payload_valid = False
            sensor_path = _resolve_run_file(report_root, tier_root, run, sensor.get("path") if isinstance(sensor, Mapping) else None)
            sensor_valid = isinstance(sensor, Mapping) and isinstance(sensor.get("sensor_count"), int) and sensor.get("sensor_count", 0) > 0 and sensor_path is not None and _artifact_valid(sensor_path, sensor.get("sha256"))
            if not isinstance(spatial, Mapping) or spatial_path is None or not _artifact_valid(spatial_path, spatial.get("sha256"), spatial.get("size_bytes")) or not spatial_payload_valid or not sensor_valid:
                spatial_valid = False
        observed = {**expected, "offsets_m": offsets, "all_succeeded": all_succeeded, "provenance_valid": provenance_valid, "artifacts_hash_valid": artifacts_valid, "incident_values_valid": incident_valid, "spatial_artifacts_valid": spatial_valid}
        valid = _source_valid(report, report_root, "climate") and all(observed[key] == expected_hb[key] for key in expected_hb)
        return valid, observed, "Honeybee controls, incident values, and spatial artifacts validated" if valid else "Honeybee runtime evidence is incomplete or failed validation", evidence
    results_valid = True
    for run in runs:
        values = run.get("radiation_values") if isinstance(run, Mapping) else None
        total = run.get("area_weighted_total_kwh_m2") if isinstance(run, Mapping) else None
        if not isinstance(values, list) or not values or any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in values) or not isinstance(total, (int, float)) or not math.isfinite(total) or total < 0:
            results_valid = False
    expected["results_valid"] = True
    observed = {**expected, "offsets_m": offsets, "all_succeeded": all_succeeded, "provenance_valid": provenance_valid, "artifacts_hash_valid": artifacts_valid, "results_valid": results_valid}
    valid = _source_valid(report, report_root, "climate") and all(observed[key] == expected[key] for key in expected)
    return valid, observed, "Ladybug controls, runs, and artifacts validated" if valid else "Ladybug runtime evidence is incomplete or failed validation", evidence


def _qgis_runtime(report: Mapping[str, Any], report_root: Path) -> tuple[bool, dict[str, Any], str, list[str]]:
    expected = {"facade_status": PASS, "artifact_nonempty": True, "artifact_hash_valid": True, "ledger_state_linked": True}
    smoke = report.get("qgis", {}).get("facade_smoke")
    dispatch = report.get("qgis", {}).get("facade_dispatch")
    artifact = smoke.get("artifact") if isinstance(smoke, Mapping) else None
    artifact_path = Path(artifact) if isinstance(artifact, str) else None
    smoke_ok = artifact_path is not None and _artifact_valid(artifact_path, smoke.get("artifact_sha256") if isinstance(smoke, Mapping) else None)
    observed = {"facade_status": smoke.get("status") if isinstance(smoke, Mapping) else BLOCKED, "artifact_nonempty": smoke_ok, "artifact_hash_valid": smoke_ok, "ledger_state_linked": bool(smoke.get("ledger_state_linked") if isinstance(smoke, Mapping) else False)}
    if isinstance(dispatch, Mapping) and isinstance(dispatch.get("artifact"), str):
        dispatch_path = Path(dispatch["artifact"])
        dispatch_ok = _artifact_valid(dispatch_path)
        observed["artifact_nonempty"] = dispatch_ok
        observed["artifact_hash_valid"] = dispatch_ok and dispatch.get("artifact_sha256") == _file_hash(dispatch_path)
    audit_ok = True
    if isinstance(dispatch, Mapping) and isinstance(dispatch.get("audit_artifact"), str):
        audit_path = Path(dispatch["audit_artifact"])
        audit_ok = _artifact_valid(audit_path, dispatch.get("audit_artifact_sha256"))
    valid = _source_valid(report, report_root, "qgis") and audit_ok and all(observed[key] == expected[key] for key in expected)
    evidence = ["raw/qgis/qgis-report.json"]
    if isinstance(dispatch, Mapping):
        for key in ("artifact", "audit_artifact"):
            value = dispatch.get(key)
            if isinstance(value, str):
                path = Path(value)
                if path.is_file() and path.is_relative_to(report_root):
                    evidence.append(str(path.relative_to(report_root)))
    return valid, observed, "live QGIS facade artifact, hash, and ledger link validated" if valid else "live QGIS facade evidence is unavailable or failed validation", evidence


def build_m1_gate_manifest(
    report: dict[str, Any],
    *,
    report_root: Path,
    report_path: str,
    pytest_run: Mapping[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a manifest from actual pytest evidence and revalidated artifacts."""
    run_id = run_id or str(report.get("run_id") or report.get("probe_id") or "unidentified-run")
    pytest_record: PytestRunRecord | None = None
    if pytest_run is not None:
        try:
            pytest_record = PytestRunRecord.model_validate(pytest_run)
        except Exception:
            pytest_record = None
    records: list[M1GateRecord] = []
    for gate_id, definition in M1_GATE_DEFINITIONS.items():
        test_ids = list(definition["tests"])
        evidence_paths = ["raw/gates/pytest-gate-run.json", "raw/gates/pytest-junit.xml", *definition.get("evidence", [])]
        evidence_refs: list[EvidenceRefRecord] = []
        evidence_complete = True
        for path in evidence_paths:
            ref = _evidence_ref(report_root, path)
            if ref is None:
                evidence_complete = False
            if ref is not None and all(existing.path != ref.path for existing in evidence_refs):
                evidence_refs.append(ref)
        if gate_id in {"CLM-001", "CLM-002"}:
            valid, observed, reason, runtime_evidence = _climate_runtime(report, report_root, "ladybug" if gate_id == "CLM-001" else "honeybee_radiance")
            expected = {"offsets_m": sorted(float(value) for value in report.get("fixture", {}).get("offsets_m", [0.0, -1.0, 1.0])), "all_succeeded": True, "provenance_valid": True, "artifacts_hash_valid": True}
            if gate_id == "CLM-002":
                expected.update({"incident_values_valid": True, "spatial_artifacts_valid": True})
            else:
                expected.update({"results_valid": True})
            tier_name = "ladybug" if gate_id == "CLM-001" else "honeybee_radiance"
            tier_runs = report.get("climate", {}).get(tier_name, {}).get("runs", [])
            for run in tier_runs if isinstance(tier_runs, list) else []:
                if not isinstance(run, Mapping):
                    continue
                run_id_value = run.get("run_id")
                for artifact in run.get("artifacts", []) if isinstance(run.get("artifacts"), list) else []:
                    if isinstance(artifact, Mapping) and isinstance(artifact.get("path"), str) and isinstance(run_id_value, str):
                        runtime_evidence.append(f"raw/climate/{tier_name}/{run_id_value}/{artifact['path']}")
            for path in runtime_evidence:
                ref = _evidence_ref(report_root, path)
                if ref is None:
                    evidence_complete = False
                if ref is not None and all(existing.path != ref.path for existing in evidence_refs):
                    evidence_refs.append(ref)
            test_ok, _, test_reason = _pytest_observation(pytest_run, test_ids)
            status = PASS if valid and test_ok and evidence_complete else BLOCKED
            if not test_ok:
                reason = f"{reason}; {test_reason}"
            if not evidence_complete:
                reason = f"{reason}; one or more required evidence files are missing, empty, or invalid"
            record = M1GateRecord(gate_id=gate_id, test_ids=test_ids, fixture_or_run_id=run_id, expected=expected, observed=observed, evidence_refs=evidence_refs, status=status, reviewer=REVIEWER_ID, reason=reason)
        elif gate_id == "SEC-006":
            valid, observed, reason, runtime_evidence = _qgis_runtime(report, report_root)
            expected = {"facade_status": PASS, "artifact_nonempty": True, "artifact_hash_valid": True, "ledger_state_linked": True}
            test_ok, _, test_reason = _pytest_observation(pytest_run, test_ids)
            status = PASS if valid and test_ok and evidence_complete else BLOCKED
            if not test_ok:
                reason = f"{reason}; {test_reason}"
            if not evidence_complete:
                reason = f"{reason}; one or more required evidence files are missing, empty, or invalid"
            record = M1GateRecord(gate_id=gate_id, test_ids=test_ids, fixture_or_run_id=run_id, expected=expected, observed=observed, evidence_refs=evidence_refs, status=status, reviewer=REVIEWER_ID, reason=reason)
        else:
            test_ok, observed, reason = _pytest_observation(pytest_run, test_ids)
            expected = {"mapped_nodes": test_ids, "all_collected": True, "all_passed": True}
            status = PASS if test_ok and evidence_complete else BLOCKED
            if not evidence_complete:
                reason = f"{reason}; one or more required evidence files are missing, empty, or invalid"
            record = M1GateRecord(gate_id=gate_id, test_ids=test_ids, fixture_or_run_id=run_id, expected=expected, observed=observed, evidence_refs=evidence_refs, status=status, reviewer=REVIEWER_ID, reason=reason)
        records.append(record)
    manifest = M1GateManifest(required_gates=records, overall_status=PASS if all(item.status == PASS for item in records) else BLOCKED, report_path=report_path, run_id=run_id, reviewer=REVIEWER_ID, pytest_run=pytest_record)
    return manifest.model_dump(mode="json")


__all__ = [
    "EvidenceRefRecord",
    "M1_GATE_DEFINITIONS",
    "M1GateManifest",
    "M1GateRecord",
    "PytestNodeRecord",
    "PytestRunRecord",
    "REVIEWER_ID",
    "build_m1_gate_manifest",
]
