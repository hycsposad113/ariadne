"""R03 package verifier checks immutable bytes, external anchoring, and provenance links."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts.verify_week4_repair_r03 import SUPPLEMENTAL_MANIFEST_NAMES, verify_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "artifacts/week4-repair-r03"


def _package_copy(tmp_path: Path) -> Path:
    target = tmp_path / "week4-repair-r03"
    shutil.copytree(PACKAGE_ROOT, target)
    return target


def _trusted_anchor() -> str:
    return hashlib.sha256((PACKAGE_ROOT / "integrity-manifest-r03.json").read_bytes()).hexdigest()


def _verify(package: Path):
    return verify_package(
        package,
        project_root=PROJECT_ROOT,
        expected_supplemental_manifest_sha256=_trusted_anchor(),
    )


def _refresh_manifest_file_entry(package: Path, relative: str) -> None:
    manifest_path = package / "integrity-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = package / relative
    entry = next(item for item in manifest["files"] if item["path"] == relative)
    entry["size_bytes"] = target.stat().st_size
    entry["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _refresh_supplemental_file_entry(package: Path, relative: str) -> None:
    manifest_path = package / "integrity-manifest-r01.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = package / relative
    entry = next(item for item in manifest["files"] if item["path"] == relative)
    entry["size_bytes"] = target.stat().st_size
    entry["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _declared_parent_drift_paths() -> set[str]:
    drift_paths: set[str] = set()
    manifest_paths = [PACKAGE_ROOT / "integrity-manifest.json"] + [
        PACKAGE_ROOT / name for name in SUPPLEMENTAL_MANIFEST_NAMES
    ]
    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            for parent, expected_sha in entry.get("parent_sha256", {}).items():
                parent_path = PROJECT_ROOT / parent
                if parent_path.is_file() and hashlib.sha256(parent_path.read_bytes()).hexdigest() != expected_sha:
                    drift_paths.add(parent)
    return drift_paths


def _assert_amendment_drift_error_matches_frozen_record(error: str) -> None:
    label, relative = error.split(" source hash/size mismatch: ", 1)
    suffix_by_label = {
        "implementation amendment": "r01",
        "second implementation amendment": "r02",
        "third implementation amendment": "r03",
        "fourth implementation amendment": "r04",
    }
    record = json.loads(
        (PACKAGE_ROOT / f"implementation-record-{suffix_by_label[label]}.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in record["files"] if item["path"] == relative)
    data = (PROJECT_ROOT / relative).read_bytes()
    assert len(data) != entry["size_bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]


def test_r03_archive_stays_intact_and_r04_source_parent_drift_is_explicit():
    study_area_parent = (
        ".urban_design_runtime/artifacts/study-area-bridge/study-areas/"
        "4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson"
    )
    if not (PROJECT_ROOT / study_area_parent).is_file():
        pytest.skip(
            "missing untracked runtime file "
            f"{study_area_parent}; "
            "this worktree does not carry the local StudyArea artifact, so R03 parent drift cannot be checked"
        )
    result = _verify(PACKAGE_ROOT)
    required_reported_drift = {
        "scripts/run_workspace_server.py",
        "src/urban_design/api.py",
        "src/urban_design/r03_evidence.py",
        "web/e2e/workspace_flow.py",
        "web/src/components/PanelEvidenceAndCritic.tsx",
        "tests/test_week4_r03_integrity.py",
        "src/urban_design/r03_syntax.py",
        "web/src/components/Viewport2D.tsx",
    }
    expected_addendum_errors = {
        "R02 source-drift addendum does not match the current exact source-parent hashes",
        "R02 source-drift addendum verifier errors do not match the frozen parent references",
        "R02 source-drift addendum parent drift count is incorrect or empty",
        "R02 source-drift addendum manifest parents do not cover the captured evidence",
    }
    assert result["status"] == "BLOCKED", result["errors"]
    reported_drift = {
        error.removeprefix("declared parent SHA-256 mismatch: ")
        for error in result["errors"]
        if error.startswith("declared parent SHA-256 mismatch: ")
    }
    assert reported_drift <= _declared_parent_drift_paths()
    assert required_reported_drift <= reported_drift
    amendment_errors = {
        error
        for error in result["errors"]
        if " source hash/size mismatch: " in error
        and "implementation amendment" in error
    }
    for error in amendment_errors:
        _assert_amendment_drift_error_matches_frozen_record(error)
    assert amendment_errors
    expected_non_parent_errors = expected_addendum_errors | amendment_errors
    assert set(result["errors"]) - {
        f"declared parent SHA-256 mismatch: {path}" for path in reported_drift
    } == expected_non_parent_errors
    assert result["r03_integrity_status"] == "BLOCKED"
    assert result["r02_current_verifier_status"] == "BLOCKED_SOURCE_PARENT_DRIFT"
    assert result["independent_acceptance"] == "PENDING_SOL_OR_ASTRA_REVIEW"
    assert result["checked_files"] == 30
    assert result["checked_parents"] >= 278


def test_single_byte_package_mutation_is_blocked(tmp_path):
    package = _package_copy(tmp_path)
    target = package / "evidence-bundle.json"
    target.write_bytes(target.read_bytes() + b" ")
    result = _verify(package)
    assert result["status"] == "BLOCKED"
    assert any("SHA-256 mismatch" in error or "size mismatch" in error for error in result["errors"])


def test_missing_parent_hash_reference_is_blocked(tmp_path):
    package = _package_copy(tmp_path)
    manifest_path = package / "integrity-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["parent_paths"])
    del entry["parent_sha256"][entry["parent_paths"][0]]
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result = _verify(package)
    assert result["status"] == "BLOCKED"
    assert any("parent path/hash references are incomplete" in error for error in result["errors"])


def test_missing_declared_parent_file_is_blocked(tmp_path):
    package = _package_copy(tmp_path)
    manifest_path = package / "integrity-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["files"] if item["parent_paths"])
    missing_parent = "artifacts/week4-repair-r03/test-injected-missing-parent.json"
    entry["parent_paths"].append(missing_parent)
    entry["parent_sha256"][missing_parent] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result = _verify(package)
    assert result["status"] == "BLOCKED"
    assert any("declared parent file is missing" in error for error in result["errors"])


def test_wrong_source_revision_is_blocked_after_manifest_rehash(tmp_path):
    package = _package_copy(tmp_path)
    record_path = package / "package-record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["source_package"]["revision"] = "spatial-r99"
    record_path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _refresh_manifest_file_entry(package, "package-record.json")
    result = _verify(package)
    assert result["status"] == "BLOCKED"
    assert any("package record source package revision differs from Evidence Card scope" in error for error in result["errors"])


def test_supplemental_manifest_binds_original_base_manifest(tmp_path):
    package = _package_copy(tmp_path)
    base_manifest = package / "integrity-manifest.json"
    base_manifest.write_bytes(base_manifest.read_bytes() + b" ")
    result = _verify(package)
    assert result["status"] == "BLOCKED"
    assert any("supplemental integrity manifest" in error and "base SHA-256 mismatch" in error for error in result["errors"])


def test_r02_source_drift_semantics_fail_closed_after_supplemental_rehash(tmp_path):
    package = _package_copy(tmp_path)
    relative = "r02-current-source-drift-r01.json"
    record_path = package / relative
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["source_parent_drift_count"] += 1
    record_path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    _refresh_supplemental_file_entry(package, relative)
    result = _verify(package)
    assert result["status"] == "BLOCKED"
    assert any("source-drift addendum parent drift count is incorrect" in error for error in result["errors"])


def test_external_latest_manifest_anchor_is_required():
    result = verify_package(PACKAGE_ROOT, project_root=PROJECT_ROOT)
    assert result["status"] == "BLOCKED"
    assert any("manifest SHA-256 anchor is required" in error for error in result["errors"])


def test_external_latest_manifest_anchor_must_match():
    result = verify_package(
        PACKAGE_ROOT,
        project_root=PROJECT_ROOT,
        expected_supplemental_manifest_sha256="0" * 64,
    )
    assert result["status"] == "BLOCKED"
    assert any("does not match the external anchor" in error for error in result["errors"])


def test_coordinated_previous_manifest_rehash_is_blocked_by_external_anchor(tmp_path):
    package = _package_copy(tmp_path)
    previous_path = package / "integrity-manifest-r01.json"
    previous_path.write_bytes(previous_path.read_bytes() + b" ")
    second_path = package / "integrity-manifest-r02.json"
    second = json.loads(second_path.read_text(encoding="utf-8"))
    second["previous_manifest_sha256"] = hashlib.sha256(previous_path.read_bytes()).hexdigest()
    second_path.write_text(json.dumps(second, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    latest_path = package / "integrity-manifest-r03.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    latest["previous_manifest_sha256"] = hashlib.sha256(second_path.read_bytes()).hexdigest()
    latest_path.write_text(json.dumps(latest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    result = _verify(package)
    assert result["status"] == "BLOCKED"
    assert any("latest supplemental manifest SHA-256 does not match the external anchor" in error for error in result["errors"])


def test_r02_historical_count_is_reconciled_without_rewriting_package_record():
    package_record = json.loads((PACKAGE_ROOT / "package-record.json").read_text(encoding="utf-8"))
    reconciliation = json.loads((PACKAGE_ROOT / "r02-current-source-drift-r02.json").read_text(encoding="utf-8"))
    assert package_record["r02_preservation"]["current_source_parent_hash_mismatches"] == 21
    assert reconciliation["historical_count"] == 21
    assert reconciliation["current_count"] == 24
    assert reconciliation["delta_occurrences"] == 3
    assert reconciliation["delta_attribution"]["path"] == "tests/test_week4_repair_integrity.py"
