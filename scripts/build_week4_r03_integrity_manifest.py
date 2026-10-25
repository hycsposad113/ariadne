#!/usr/bin/env python3
"""Create the R03 package's final append-only file and parent-hash manifest."""

from __future__ import annotations

import hashlib
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_REL = Path("artifacts/week4-repair-r03")
PACKAGE = ROOT / PACKAGE_REL
MANIFEST = PACKAGE / "integrity-manifest.json"
IMPLEMENTATION_AMENDMENT = PACKAGE / "implementation-record-r01.json"
IMPLEMENTATION_AMENDMENT_R02 = PACKAGE / "implementation-record-r02.json"
IMPLEMENTATION_AMENDMENT_R03 = PACKAGE / "implementation-record-r03.json"
IMPLEMENTATION_AMENDMENT_R04 = PACKAGE / "implementation-record-r04.json"
SUPPLEMENTAL_MANIFEST = PACKAGE / "integrity-manifest-r01.json"
SUPPLEMENTAL_MANIFEST_R02 = PACKAGE / "integrity-manifest-r02.json"
SUPPLEMENTAL_MANIFEST_R03 = PACKAGE / "integrity-manifest-r03.json"
SPATIAL_R01 = Path(
    "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)
R02 = Path("artifacts/week4-repair-r02")
AMENDED_FILES = {
    "README.md": "Clarify partial Week 4 UI and analysis status.",
    "src/urban_design/e2e_ports.py": "Refuse reserved service ports during isolated browser tests.",
    "scripts/build_week4_r03_integrity_manifest.py": "Add append-only implementation amendment and complete package parent links.",
    "scripts/verify_week4_repair_r03.py": "Check implementation amendment and cross-artifact source lineage.",
    "tests/test_week4_e2e_ports.py": "Cover reserved service port refusal and ephemeral selection.",
    "tests/test_week4_r03_integrity.py": "Cover absent parent files and source revision drift.",
}
AMENDED_FILES_R02 = {
    "scripts/build_week4_r03_integrity_manifest.py": "Build append-only R03 validation amendment manifests.",
    "scripts/verify_week4_repair_r03.py": "Verify chained R03 manifest additions and validation records.",
    "tests/test_week4_r03_integrity.py": "Verify chained R03 manifest and its base-manifest binding.",
    "tests/test_week4_repair_integrity.py": "Assert intact R02 archive bytes and report exact current-source drift.",
}
AMENDED_FILES_R03 = {
    "scripts/build_week4_r03_integrity_manifest.py": "Append-only R03 validation manifest chain, external digest anchoring, and R02 count reconciliation.",
    "scripts/verify_week4_repair_r03.py": "Require external manifest anchoring, validate R03 lineage, and distinguish R03 integrity from historical R02 drift.",
    "tests/test_week4_r03_integrity.py": "Exercise external anchors, qualified status, and fail-closed chained-manifest mutations.",
}
AMENDED_FILES_R04 = {
    "scripts/build_week4_r03_integrity_manifest.py": "Append the final R03 source/test record and integrity manifest chain revision.",
    "scripts/verify_week4_repair_r03.py": "Verify the R03 latest integrity-manifest chain and its trusted external digest.",
    "tests/test_week4_r03_integrity.py": "Correctly assert fail-closed behavior for a missing external manifest digest.",
}
SUPPLEMENTAL_FILES = (
    "implementation-record-r02.json",
    "r02-current-source-drift-r01.json",
)
SUPPLEMENTAL_FILES_R02 = (
    "implementation-record-r03.json",
    "r02-current-source-drift-r02.json",
)
SUPPLEMENTAL_FILES_R03 = (
    "implementation-record-r04.json",
)
R02_DRIFT_RECORD = PACKAGE / "r02-current-source-drift-r01.json"
R02_DRIFT_RECONCILIATION = PACKAGE / "r02-current-source-drift-r02.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parent_file_path(project_relative: str) -> Path:
    relative = PurePosixPath(project_relative)
    try:
        package_relative = relative.relative_to(PACKAGE_REL.as_posix())
    except ValueError:
        return ROOT.joinpath(*relative.parts)
    return PACKAGE.joinpath(*package_relative.parts)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_implementation_amendment() -> dict[str, Any]:
    """Append current source/test hashes without rewriting the original record."""
    if IMPLEMENTATION_AMENDMENT.exists():
        raise FileExistsError(f"refusing to overwrite append-only implementation amendment: {IMPLEMENTATION_AMENDMENT}")
    base_record = PACKAGE / "implementation-record.json"
    if not base_record.is_file():
        raise FileNotFoundError(f"original implementation record is missing: {base_record}")
    entries: list[dict[str, Any]] = []
    for relative, role in sorted(AMENDED_FILES.items()):
        path = ROOT.joinpath(*Path(relative).parts)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"amended implementation input is missing or unsafe: {relative}")
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "role": role,
        })
    amendment = {
        "schema_version": "week4-r03-implementation-record-amendment-v1",
        "amendment_id": "implementation-record-r01",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Append-only current source, test, and task-scoped documentation hashes for final R03 integrity hardening.",
        "supersedes": {
            "path": (PACKAGE_REL / "implementation-record.json").as_posix(),
            "sha256": _sha256(base_record),
        },
        "files": entries,
    }
    IMPLEMENTATION_AMENDMENT.write_text(json.dumps(amendment, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "WRITTEN_ONCE",
        "path": (PACKAGE_REL / IMPLEMENTATION_AMENDMENT.name).as_posix(),
        "sha256": _sha256(IMPLEMENTATION_AMENDMENT),
        "file_count": len(entries),
    }


def write_implementation_amendment_r02() -> dict[str, Any]:
    """Append hashes for the test-status correction and manifest-chain verifier."""
    if IMPLEMENTATION_AMENDMENT_R02.exists():
        raise FileExistsError(f"refusing to overwrite append-only implementation amendment: {IMPLEMENTATION_AMENDMENT_R02}")
    if not IMPLEMENTATION_AMENDMENT.is_file():
        raise FileNotFoundError(f"implementation-record-r01 is missing: {IMPLEMENTATION_AMENDMENT}")
    entries: list[dict[str, Any]] = []
    for relative, role in sorted(AMENDED_FILES_R02.items()):
        path = ROOT.joinpath(*Path(relative).parts)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"amended implementation input is missing or unsafe: {relative}")
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "role": role,
        })
    amendment = {
        "schema_version": "week4-r03-implementation-record-amendment-v1",
        "amendment_id": "implementation-record-r02",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Append-only validation of the R02 historical source-drift state and chained R03 integrity manifest.",
        "supersedes": {
            "path": (PACKAGE_REL / IMPLEMENTATION_AMENDMENT.name).as_posix(),
            "sha256": _sha256(IMPLEMENTATION_AMENDMENT),
        },
        "files": entries,
    }
    IMPLEMENTATION_AMENDMENT_R02.write_text(json.dumps(amendment, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "WRITTEN_ONCE",
        "path": (PACKAGE_REL / IMPLEMENTATION_AMENDMENT_R02.name).as_posix(),
        "sha256": _sha256(IMPLEMENTATION_AMENDMENT_R02),
        "file_count": len(entries),
    }


def write_implementation_amendment_r03() -> dict[str, Any]:
    """Append current verifier, builder, and test hashes without rewriting earlier records."""
    if IMPLEMENTATION_AMENDMENT_R03.exists():
        raise FileExistsError(f"refusing to overwrite append-only implementation amendment: {IMPLEMENTATION_AMENDMENT_R03}")
    if not IMPLEMENTATION_AMENDMENT_R02.is_file():
        raise FileNotFoundError(f"implementation-record-r02 is missing: {IMPLEMENTATION_AMENDMENT_R02}")
    entries: list[dict[str, Any]] = []
    for relative, role in sorted(AMENDED_FILES_R03.items()):
        path = ROOT.joinpath(*Path(relative).parts)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"amended implementation input is missing or unsafe: {relative}")
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "role": role,
        })
    amendment = {
        "schema_version": "week4-r03-implementation-record-amendment-v1",
        "amendment_id": "implementation-record-r03",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Append-only record of R03 external integrity anchoring, qualified verification status, and R02 drift-count reconciliation.",
        "supersedes": {
            "path": (PACKAGE_REL / IMPLEMENTATION_AMENDMENT_R02.name).as_posix(),
            "sha256": _sha256(IMPLEMENTATION_AMENDMENT_R02),
        },
        "files": entries,
    }
    IMPLEMENTATION_AMENDMENT_R03.write_text(json.dumps(amendment, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "WRITTEN_ONCE",
        "path": (PACKAGE_REL / IMPLEMENTATION_AMENDMENT_R03.name).as_posix(),
        "sha256": _sha256(IMPLEMENTATION_AMENDMENT_R03),
        "file_count": len(entries),
    }


def write_implementation_amendment_r04() -> dict[str, Any]:
    """Append final source/test hashes after the R03 package audit correction."""
    if IMPLEMENTATION_AMENDMENT_R04.exists():
        raise FileExistsError(f"refusing to overwrite append-only implementation amendment: {IMPLEMENTATION_AMENDMENT_R04}")
    if not IMPLEMENTATION_AMENDMENT_R03.is_file():
        raise FileNotFoundError(f"implementation-record-r03 is missing: {IMPLEMENTATION_AMENDMENT_R03}")
    entries: list[dict[str, Any]] = []
    for relative, role in sorted(AMENDED_FILES_R04.items()):
        path = ROOT.joinpath(*Path(relative).parts)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"amended implementation input is missing or unsafe: {relative}")
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "role": role,
        })
    amendment = {
        "schema_version": "week4-r03-implementation-record-amendment-v1",
        "amendment_id": "implementation-record-r04",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Append-only final source and test hashes for the externally anchored R03 integrity package.",
        "supersedes": {
            "path": (PACKAGE_REL / IMPLEMENTATION_AMENDMENT_R03.name).as_posix(),
            "sha256": _sha256(IMPLEMENTATION_AMENDMENT_R03),
        },
        "files": entries,
    }
    IMPLEMENTATION_AMENDMENT_R04.write_text(json.dumps(amendment, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "WRITTEN_ONCE",
        "path": (PACKAGE_REL / IMPLEMENTATION_AMENDMENT_R04.name).as_posix(),
        "sha256": _sha256(IMPLEMENTATION_AMENDMENT_R04),
        "file_count": len(entries),
    }


def write_r02_source_drift_reconciliation() -> dict[str, Any]:
    """Append an explicit reconciliation of the historical 21 and current 24 counts."""
    if R02_DRIFT_RECONCILIATION.exists():
        raise FileExistsError(f"refusing to overwrite append-only R02 reconciliation: {R02_DRIFT_RECONCILIATION}")
    package_record_path = PACKAGE / "package-record.json"
    if not package_record_path.is_file() or not R02_DRIFT_RECORD.is_file():
        raise FileNotFoundError("R03 package record or current R02 source-drift capture is missing")
    package_record = _read_json(package_record_path)
    drift = _read_json(R02_DRIFT_RECORD)
    historical_count = (package_record.get("r02_preservation") or {}).get("current_source_parent_hash_mismatches")
    current_count = drift.get("source_parent_drift_count")
    rows = drift.get("source_parent_drift")
    if not isinstance(rows, list):
        raise ValueError("current R02 source-drift addendum has no drift rows")
    test_row = next(
        (item for item in rows if isinstance(item, dict) and item.get("path") == "tests/test_week4_repair_integrity.py"),
        None,
    )
    delta = current_count - historical_count if isinstance(current_count, int) and isinstance(historical_count, int) else None
    if (
        historical_count != 21
        or current_count != 24
        or delta != 3
        or len(rows) != 6
        or not isinstance(test_row, dict)
        or test_row.get("reference_count") != delta
    ):
        raise ValueError("R02 source-drift evidence no longer supports the 21-to-24, three-reference reconciliation")
    manifest_path = ROOT / R02 / "integrity-manifest.json"
    manifest = _read_json(manifest_path)
    r02_entries = manifest.get("files")
    if not isinstance(r02_entries, list) or len(r02_entries) != 31:
        raise ValueError("frozen R02 manifest must list exactly 31 package files")
    for entry in r02_entries:
        relative = PurePosixPath(entry["path"])
        archive_path = ROOT / R02.joinpath(*relative.parts)
        if archive_path.is_symlink() or not archive_path.is_file():
            raise ValueError(f"frozen R02 archive file is missing or unsafe: {entry['path']}")
        if archive_path.stat().st_size != entry.get("size_bytes") or _sha256(archive_path) != entry.get("sha256"):
            raise ValueError(f"frozen R02 archive file changed: {entry['path']}")

    reconciliation = {
        "schema_version": "week4-r03-r02-source-drift-reconciliation-v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Append-only reconciliation of the package-record historical R02 drift count and the subsequent exact source-parent recheck.",
        "status": "HISTORICAL_COUNT_RECONCILED",
        "historical_record": {
            "path": (PACKAGE_REL / "package-record.json").as_posix(),
            "sha256": _sha256(package_record_path),
            "captured_at_utc": package_record.get("created_at_utc"),
            "field": "r02_preservation.current_source_parent_hash_mismatches",
            "value": historical_count,
        },
        "current_recheck": {
            "path": (PACKAGE_REL / R02_DRIFT_RECORD.name).as_posix(),
            "sha256": _sha256(R02_DRIFT_RECORD),
            "captured_at_utc": drift.get("captured_at_utc"),
            "status": drift.get("status"),
            "field": "source_parent_drift_count",
            "value": current_count,
            "unique_parent_paths": len(rows),
        },
        "historical_count": historical_count,
        "current_count": current_count,
        "delta_occurrences": delta,
        "unique_current_parent_paths": len(rows),
        "delta_attribution": {
            "path": test_row["path"],
            "expected_sha256": test_row["expected_sha256"],
            "actual_sha256": test_row["actual_sha256"],
            "reference_count": test_row["reference_count"],
        },
        "r02_archive_files_verified": len(r02_entries),
        "r02_archive_hashes_match": True,
        "r02_bytes_modified_by_r03": False,
        "interpretation": "The package-record count of 21 is preserved as its historical capture. The subsequent read-only exact recheck found 24 parent-hash mismatch occurrences across six paths; three references to tests/test_week4_repair_integrity.py account for the difference. All 31 frozen R02 package files remain byte-identical.",
    }
    R02_DRIFT_RECONCILIATION.write_text(json.dumps(reconciliation, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "WRITTEN_ONCE",
        "path": (PACKAGE_REL / R02_DRIFT_RECONCILIATION.name).as_posix(),
        "sha256": _sha256(R02_DRIFT_RECONCILIATION),
        "historical_count": historical_count,
        "current_count": current_count,
        "delta_occurrences": delta,
    }


def write_r02_source_drift_record(report_path: Path) -> dict[str, Any]:
    """Append a reproducible record separating intact R02 bytes from source drift."""
    if R02_DRIFT_RECORD.exists():
        raise FileExistsError(f"refusing to overwrite append-only R02 source-drift record: {R02_DRIFT_RECORD}")
    report_path = Path(report_path).resolve()
    report = _read_json(report_path)
    manifest_path = ROOT / R02 / "integrity-manifest.json"
    manifest = _read_json(manifest_path)
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) != 31:
        raise ValueError("frozen R02 manifest must list exactly 31 package files")
    archive_failures: list[str] = []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            archive_failures.append("invalid frozen R02 file entry")
            continue
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            archive_failures.append(f"unsafe frozen R02 file path: {item['path']}")
            continue
        archive_path = ROOT / R02.joinpath(*relative.parts)
        if archive_path.is_symlink() or not archive_path.is_file():
            archive_failures.append(f"missing or unsafe frozen R02 file: {item['path']}")
            continue
        if archive_path.stat().st_size != item.get("size_bytes") or _sha256(archive_path) != item.get("sha256"):
            archive_failures.append(f"frozen R02 archive hash/size mismatch: {item['path']}")
    if archive_failures:
        raise ValueError("frozen R02 archive bytes failed verification: " + "; ".join(archive_failures))

    expected_errors: list[str] = []
    drift_by_key: dict[tuple[str, str, str], int] = {}
    for item in entries:
        parents = item.get("parent_sha256")
        if not isinstance(parents, dict):
            raise ValueError(f"invalid parent hash map in frozen R02 entry: {item.get('path')}")
        for parent, expected_sha in parents.items():
            relative = PurePosixPath(parent)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe frozen R02 parent path: {parent}")
            parent_path = ROOT.joinpath(*relative.parts)
            if parent_path.is_symlink() or not parent_path.is_file():
                raise ValueError(f"missing or unsafe frozen R02 parent: {parent}")
            actual_sha = _sha256(parent_path)
            if actual_sha != expected_sha:
                expected_errors.append(f"parent SHA-256 mismatch: {parent}")
                key = (parent, str(expected_sha), actual_sha)
                drift_by_key[key] = drift_by_key.get(key, 0) + 1

    report_errors = report.get("errors")
    if (
        report.get("status") != "BLOCKED"
        or report.get("checked_files") != 31
        or report.get("checked_parents") != sum(len(item.get("parent_paths", [])) for item in entries)
        or not expected_errors
        or report_errors != expected_errors
    ):
        raise ValueError("R02 verifier result is not an exact source-parent-drift-only BLOCKED result")

    source_drift = [
        {
            "path": path,
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
            "reference_count": reference_count,
        }
        for (path, expected_sha, actual_sha), reference_count in sorted(drift_by_key.items())
    ]
    record = {
        "schema_version": "week4-r03-r02-source-drift-v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Current read-only R02 verifier result; distinguishes frozen package-byte integrity from changed current source parents.",
        "status": "BLOCKED_SOURCE_PARENT_DRIFT",
        "verifier_status": "BLOCKED",
        "verifier_command": "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/verify_week4_repair_r02.py artifacts/week4-repair-r02",
        "verifier_script": {
            "path": "scripts/verify_week4_repair_r02.py",
            "sha256": _sha256(ROOT / "scripts/verify_week4_repair_r02.py"),
        },
        "manifest_path": (R02 / "integrity-manifest.json").as_posix(),
        "manifest_sha256": _sha256(manifest_path),
        "checked_files": report["checked_files"],
        "checked_parents": report["checked_parents"],
        "archive_files_verified": len(entries),
        "archive_hashes_match": True,
        "source_parent_drift_count": len(expected_errors),
        "source_parent_drift": source_drift,
        "verifier_errors": expected_errors,
        "semantic_state": report.get("semantic_state"),
    }
    R02_DRIFT_RECORD.parent.mkdir(parents=True, exist_ok=True)
    R02_DRIFT_RECORD.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "WRITTEN_ONCE",
        "path": (PACKAGE_REL / R02_DRIFT_RECORD.name).as_posix(),
        "sha256": _sha256(R02_DRIFT_RECORD),
        "drift_occurrences": len(expected_errors),
        "unique_parent_paths": len({item["path"] for item in source_drift}),
    }


def _amendment_paths() -> set[str]:
    record = _read_json(PACKAGE / "implementation-record-r01.json")
    entries = record.get("files")
    if not isinstance(entries, list):
        raise ValueError("implementation amendment must list current source files")
    return {item["path"] for item in entries if isinstance(item, dict) and isinstance(item.get("path"), str)}


def _amendment_paths_r02() -> set[str]:
    record = _read_json(IMPLEMENTATION_AMENDMENT_R02)
    entries = record.get("files")
    if not isinstance(entries, list):
        raise ValueError("implementation-record-r02 must list current source files")
    return {item["path"] for item in entries if isinstance(item, dict) and isinstance(item.get("path"), str)}


def _amendment_paths_r03() -> set[str]:
    if not IMPLEMENTATION_AMENDMENT_R03.is_file():
        raise FileNotFoundError(f"implementation-record-r03 is missing: {IMPLEMENTATION_AMENDMENT_R03}")
    record = _read_json(IMPLEMENTATION_AMENDMENT_R03)
    entries = record.get("files")
    if not isinstance(entries, list):
        raise ValueError("implementation-record-r03 must list current source files")
    return {item["path"] for item in entries if isinstance(item, dict) and isinstance(item.get("path"), str)}


def _amendment_paths_r04() -> set[str]:
    if not IMPLEMENTATION_AMENDMENT_R04.is_file():
        raise FileNotFoundError(f"implementation-record-r04 is missing: {IMPLEMENTATION_AMENDMENT_R04}")
    record = _read_json(IMPLEMENTATION_AMENDMENT_R04)
    entries = record.get("files")
    if not isinstance(entries, list):
        raise ValueError("implementation-record-r04 must list current source files")
    return {item["path"] for item in entries if isinstance(item, dict) and isinstance(item.get("path"), str)}


def _evidence_parents() -> set[str]:
    bundle = _read_json(PACKAGE / "evidence-bundle.json")
    parent_paths: set[str] = set()
    for card in bundle.get("cards", []):
        for parent in card.get("parents", []):
            if parent.get("entity_type") == "Artifact" and isinstance(parent.get("path"), str):
                uri = parent["path"]
                if not uri.startswith("spatial-r01/"):
                    raise ValueError(f"unexpected Evidence Card source URI: {uri}")
                parent_paths.add((SPATIAL_R01 / uri.removeprefix("spatial-r01/")).as_posix())
    return parent_paths


def _parent_map() -> dict[str, set[str]]:
    package = PACKAGE_REL.as_posix()
    r02_parent_paths = {
        (R02 / "integrity-manifest.json").as_posix(),
        (R02 / "checkpoint-self-check.json").as_posix(),
        (R02 / "syntax/source-manifest.json").as_posix(),
        (R02 / "syntax/syntax-result.json").as_posix(),
        (R02 / "syntax/context.geojson").as_posix(),
        (R02 / "syntax/study-area.geojson").as_posix(),
        (R02 / "syntax/syntax-local-800m-integration-r02.png").as_posix(),
    }
    source_parent = (SPATIAL_R01 / "source-and-integrity-manifest.json").as_posix()
    evidence_code = {
        "scripts/build_week4_r03_inputs.py",
        "src/urban_design/api.py",
        "src/urban_design/r03_evidence.py",
    }
    syntax_code = {
        "scripts/render_syntax_figure.py",
        "src/urban_design/figure_export.py",
        "src/urban_design/r03_syntax.py",
    }
    browser_code = {
        "scripts/run_workspace_server.py",
        "src/urban_design/api.py",
        "web/e2e/workspace_flow.py",
        "web/src/App.tsx",
        "web/src/components/PanelEvidenceAndCritic.tsx",
        "web/src/components/SidebarSyntax.tsx",
        "web/src/components/Viewport2D.tsx",
    }
    amendment_paths = _amendment_paths()
    bundle_rel = f"{package}/evidence-bundle.json"
    syntax_status_rel = f"{package}/syntax/syntax-status.json"
    figure_record_rel = f"{package}/syntax/figure-record.json"
    rendered_svg = f"{package}/syntax/800m-integration-exploratory.svg"
    browser_report = f"{package}/browser/run-20260922T224451128616Z/report.json"
    browser_output_parents = {bundle_rel, syntax_status_rel, figure_record_rel, rendered_svg, source_parent, *browser_code}
    common_syntax = r02_parent_paths | {source_parent} | syntax_code
    parent_map = {
        f"{package}/baseline.json": {
            (R02 / "integrity-manifest.json").as_posix(),
            (R02 / "checkpoint-self-check.json").as_posix(),
            source_parent,
        },
        bundle_rel: {source_parent} | _evidence_parents() | evidence_code,
        f"{package}/syntax/syntax-status.json": common_syntax,
        figure_record_rel: common_syntax | {syntax_status_rel, rendered_svg,
            f"{package}/syntax/800m-integration-exploratory.png"},
        rendered_svg: common_syntax,
        f"{package}/syntax/800m-integration-exploratory.png": common_syntax,
        f"{package}/service-state-final.json": {f"{package}/baseline.json"},
        f"{package}/request-log.json": {
            f"{package}/baseline.json", f"{package}/service-state-final.json", browser_report,
        },
        f"{package}/gate-status.json": {
            f"{package}/baseline.json", bundle_rel, syntax_status_rel, browser_report,
            "docs/superpowers/plans/2026-09-22-week4-platform-site-analysis-zh.md",
        },
        f"{package}/implementation-record.json": {f"{package}/baseline.json"},
        f"{package}/implementation-record-r01.json": {
            f"{package}/implementation-record.json",
            *amendment_paths,
        },
        f"{package}/package-record.json": {
            f"{package}/baseline.json",
            f"{package}/gate-status.json",
            f"{package}/request-log.json",
            f"{package}/implementation-record.json",
            f"{package}/implementation-record-r01.json",
            f"{package}/runtime-state-before.json",
            f"{package}/runtime-state-after.json",
            f"{package}/service-state-final.json",
            browser_report,
            (R02 / "integrity-manifest.json").as_posix(),
            source_parent,
        },
        f"{package}/failed-browser-attempts.json": {
            f"{package}/browser/run-20260922T223142143277Z/01_after_revision_one.png",
            f"{package}/browser/run-20260922T223142143277Z/03_downloaded_exploratory_800m.svg",
            "web/e2e/workspace_flow.py",
            "scripts/run_workspace_server.py",
        },
    }

    for run_directory in sorted((PACKAGE / "browser").glob("run-*")):
        for output in run_directory.iterdir():
            if not output.is_file():
                continue
            relative = (PACKAGE_REL / output.relative_to(PACKAGE)).as_posix()
            if output.name == "report.json":
                parent_map[relative] = browser_output_parents
            else:
                parent_map[relative] = browser_output_parents

    parent_map[f"{package}/runtime-state-before.json"] = {f"{package}/baseline.json"}
    parent_map[f"{package}/runtime-state-after.json"] = {f"{package}/baseline.json"}
    return parent_map


def _supplemental_parent_map() -> dict[str, set[str]]:
    package = PACKAGE_REL.as_posix()
    source_files = _amendment_paths_r02()
    base_manifest = (PACKAGE_REL / MANIFEST.name).as_posix()
    r02_manifest = (R02 / "integrity-manifest.json").as_posix()
    r02_manifest_obj = _read_json(ROOT / r02_manifest)
    drifted_parents: set[str] = set()
    for item in r02_manifest_obj.get("files", []):
        if not isinstance(item, dict):
            continue
        for parent, expected_hash in (item.get("parent_sha256") or {}).items():
            path = ROOT.joinpath(*PurePosixPath(parent).parts)
            if path.is_file() and not path.is_symlink() and _sha256(path) != expected_hash:
                drifted_parents.add(parent)
    return {
        f"{package}/implementation-record-r02.json": {
            f"{package}/implementation-record-r01.json",
            *source_files,
        },
        f"{package}/r02-current-source-drift-r01.json": {
            r02_manifest,
            f"{R02.as_posix()}/package-record.json",
            f"{R02.as_posix()}/checkpoint-self-check.json",
            "scripts/verify_week4_repair_r02.py",
            base_manifest,
            f"{package}/runtime-state-before.json",
            f"{package}/runtime-state-after.json",
            "scripts/build_week4_r03_integrity_manifest.py",
            "tests/test_week4_repair_integrity.py",
            *drifted_parents,
        },
    }


def _supplemental_parent_map_r02() -> dict[str, set[str]]:
    package = PACKAGE_REL.as_posix()
    source_files = _amendment_paths_r03()
    previous_manifest = (PACKAGE_REL / SUPPLEMENTAL_MANIFEST.name).as_posix()
    drift = _read_json(R02_DRIFT_RECORD)
    drifted_paths = {
        item["path"] for item in drift.get("source_parent_drift", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }


def _supplemental_parent_map_r03() -> dict[str, set[str]]:
    package = PACKAGE_REL.as_posix()
    return {
        f"{package}/implementation-record-r04.json": {
            f"{package}/implementation-record-r03.json",
            *_amendment_paths_r04(),
        },
    }
    return {
        f"{package}/implementation-record-r03.json": {
            f"{package}/implementation-record-r02.json",
            *source_files,
        },
        f"{package}/r02-current-source-drift-r02.json": {
            f"{package}/package-record.json",
            f"{package}/r02-current-source-drift-r01.json",
            (R02 / "integrity-manifest.json").as_posix(),
            "tests/test_week4_repair_integrity.py",
            *drifted_paths,
        },
    }


def build_manifest() -> dict[str, Any]:
    if MANIFEST.exists():
        raise FileExistsError(f"refusing to overwrite append-only manifest: {MANIFEST}")
    parent_map = _parent_map()
    files = sorted(
        (path for path in PACKAGE.rglob("*") if path.is_file() and path != MANIFEST),
        key=lambda item: item.relative_to(PACKAGE).as_posix(),
    )
    entries: list[dict[str, Any]] = []
    for path in files:
        relative = path.relative_to(PACKAGE).as_posix()
        project_relative = (PACKAGE_REL / relative).as_posix()
        if project_relative not in parent_map or not parent_map[project_relative]:
            raise ValueError(f"package file has no declared provenance parents: {relative}")
        parent_paths = sorted(parent_map.get(project_relative, set()))
        parents: dict[str, str] = {}
        for parent in parent_paths:
            parent_path = _parent_file_path(parent)
            if not parent_path.is_file():
                raise FileNotFoundError(f"declared parent is missing: {parent}")
            parents[parent] = _sha256(parent_path)
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "kind": path.suffix.lstrip(".") or "file",
            "parent_paths": parent_paths,
            "parent_sha256": parents,
        })
    return {
        "schema_version": "week4-r03-integrity-manifest-v1",
        "package_id": "week4-r03-repair-evidence-rotterdam-m4h-v5",
        "manifest_excludes_self": True,
        "files": entries,
    }


def build_supplemental_manifest() -> dict[str, Any]:
    if SUPPLEMENTAL_MANIFEST.exists():
        raise FileExistsError(f"refusing to overwrite append-only supplemental manifest: {SUPPLEMENTAL_MANIFEST}")
    if not MANIFEST.is_file():
        raise FileNotFoundError(f"base R03 manifest is missing: {MANIFEST}")
    parent_map = _supplemental_parent_map()
    entries: list[dict[str, Any]] = []
    for relative in SUPPLEMENTAL_FILES:
        path = PACKAGE / relative
        project_relative = (PACKAGE_REL / relative).as_posix()
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"supplemental package file is missing or unsafe: {relative}")
        parents = sorted(parent_map[project_relative])
        parent_hashes: dict[str, str] = {}
        for parent in parents:
            parent_path = _parent_file_path(parent)
            if not parent_path.is_file():
                raise FileNotFoundError(f"supplemental parent is missing: {parent}")
            parent_hashes[parent] = _sha256(parent_path)
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "kind": path.suffix.lstrip(".") or "file",
            "parent_paths": parents,
            "parent_sha256": parent_hashes,
        })
    return {
        "schema_version": "week4-r03-integrity-manifest-amendment-v1",
        "package_id": "week4-r03-repair-evidence-rotterdam-m4h-v5",
        "base_manifest_path": (PACKAGE_REL / MANIFEST.name).as_posix(),
        "base_manifest_sha256": _sha256(MANIFEST),
        "manifest_excludes_self": True,
        "files": entries,
    }


def build_supplemental_manifest_r02() -> dict[str, Any]:
    if SUPPLEMENTAL_MANIFEST_R02.exists():
        raise FileExistsError(f"refusing to overwrite append-only supplemental manifest: {SUPPLEMENTAL_MANIFEST_R02}")
    if not MANIFEST.is_file() or not SUPPLEMENTAL_MANIFEST.is_file():
        raise FileNotFoundError("base and r01 R03 manifests must exist before writing supplemental r02")
    parent_map = _supplemental_parent_map_r02()
    entries: list[dict[str, Any]] = []
    for relative in SUPPLEMENTAL_FILES_R02:
        path = PACKAGE / relative
        project_relative = (PACKAGE_REL / relative).as_posix()
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"supplemental package file is missing or unsafe: {relative}")
        parents = sorted(parent_map[project_relative])
        parent_hashes: dict[str, str] = {}
        for parent in parents:
            parent_path = _parent_file_path(parent)
            if not parent_path.is_file() or parent_path.is_symlink():
                raise FileNotFoundError(f"supplemental parent is missing or unsafe: {parent}")
            parent_hashes[parent] = _sha256(parent_path)
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "kind": path.suffix.lstrip(".") or "file",
            "parent_paths": parents,
            "parent_sha256": parent_hashes,
        })
    return {
        "schema_version": "week4-r03-integrity-manifest-amendment-v1",
        "package_id": "week4-r03-repair-evidence-rotterdam-m4h-v5",
        "base_manifest_path": (PACKAGE_REL / MANIFEST.name).as_posix(),
        "base_manifest_sha256": _sha256(MANIFEST),
        "previous_manifest_path": (PACKAGE_REL / SUPPLEMENTAL_MANIFEST.name).as_posix(),
        "previous_manifest_sha256": _sha256(SUPPLEMENTAL_MANIFEST),
        "manifest_excludes_self": True,
        "files": entries,
    }


def build_supplemental_manifest_r03() -> dict[str, Any]:
    if SUPPLEMENTAL_MANIFEST_R03.exists():
        raise FileExistsError(f"refusing to overwrite append-only supplemental manifest: {SUPPLEMENTAL_MANIFEST_R03}")
    if not MANIFEST.is_file() or not SUPPLEMENTAL_MANIFEST_R02.is_file():
        raise FileNotFoundError("base and r02 R03 manifests must exist before writing supplemental r03")
    parent_map = _supplemental_parent_map_r03()
    entries: list[dict[str, Any]] = []
    for relative in SUPPLEMENTAL_FILES_R03:
        path = PACKAGE / relative
        project_relative = (PACKAGE_REL / relative).as_posix()
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"supplemental package file is missing or unsafe: {relative}")
        parents = sorted(parent_map[project_relative])
        parent_hashes: dict[str, str] = {}
        for parent in parents:
            parent_path = _parent_file_path(parent)
            if not parent_path.is_file() or parent_path.is_symlink():
                raise FileNotFoundError(f"supplemental parent is missing or unsafe: {parent}")
            parent_hashes[parent] = _sha256(parent_path)
        entries.append({
            "path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
            "kind": path.suffix.lstrip(".") or "file",
            "parent_paths": parents,
            "parent_sha256": parent_hashes,
        })
    return {
        "schema_version": "week4-r03-integrity-manifest-amendment-v1",
        "package_id": "week4-r03-repair-evidence-rotterdam-m4h-v5",
        "base_manifest_path": (PACKAGE_REL / MANIFEST.name).as_posix(),
        "base_manifest_sha256": _sha256(MANIFEST),
        "previous_manifest_path": (PACKAGE_REL / SUPPLEMENTAL_MANIFEST_R02.name).as_posix(),
        "previous_manifest_sha256": _sha256(SUPPLEMENTAL_MANIFEST_R02),
        "manifest_excludes_self": True,
        "files": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-implementation-amendment",
        action="store_true",
        help="append current R03 source/test hashes without modifying the original implementation record",
    )
    parser.add_argument(
        "--write-implementation-amendment-r02",
        action="store_true",
        help="append current source hashes for the R03 validation amendment",
    )
    parser.add_argument(
        "--write-implementation-amendment-r03",
        action="store_true",
        help="append current source hashes for the R03 external-anchor and reconciliation amendment",
    )
    parser.add_argument(
        "--write-implementation-amendment-r04",
        action="store_true",
        help="append the final R03 source/test hashes for its next manifest revision",
    )
    parser.add_argument(
        "--write-r02-source-drift-reconciliation",
        action="store_true",
        help="append a historical-to-current R02 source-drift count reconciliation",
    )
    parser.add_argument(
        "--write-supplemental-manifest",
        action="store_true",
        help="append a new manifest for R03 validation addendum files",
    )
    parser.add_argument(
        "--write-supplemental-manifest-r02",
        action="store_true",
        help="append the next chained R03 manifest for R02 reconciliation and current verifier lineage",
    )
    parser.add_argument(
        "--write-supplemental-manifest-r03",
        action="store_true",
        help="append the final chained R03 manifest revision",
    )
    parser.add_argument(
        "--write-r02-source-drift-record",
        type=Path,
        metavar="VERIFIER_REPORT",
        help="append exact current R02 source-parent drift using a read-only verifier JSON report",
    )
    args = parser.parse_args()
    if args.write_implementation_amendment:
        print(json.dumps(write_implementation_amendment(), sort_keys=True, indent=2))
        return 0
    if args.write_implementation_amendment_r02:
        print(json.dumps(write_implementation_amendment_r02(), sort_keys=True, indent=2))
        return 0
    if args.write_implementation_amendment_r03:
        print(json.dumps(write_implementation_amendment_r03(), sort_keys=True, indent=2))
        return 0
    if args.write_implementation_amendment_r04:
        print(json.dumps(write_implementation_amendment_r04(), sort_keys=True, indent=2))
        return 0
    if args.write_r02_source_drift_reconciliation:
        print(json.dumps(write_r02_source_drift_reconciliation(), sort_keys=True, indent=2))
        return 0
    if args.write_r02_source_drift_record:
        print(json.dumps(write_r02_source_drift_record(args.write_r02_source_drift_record), sort_keys=True, indent=2))
        return 0
    if args.write_supplemental_manifest:
        supplemental = build_supplemental_manifest()
        SUPPLEMENTAL_MANIFEST.write_text(json.dumps(supplemental, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "WRITTEN_ONCE",
            "manifest_path": (PACKAGE_REL / SUPPLEMENTAL_MANIFEST.name).as_posix(),
            "file_count": len(supplemental["files"]),
            "parent_reference_count": sum(len(item["parent_paths"]) for item in supplemental["files"]),
            "sha256": _sha256(SUPPLEMENTAL_MANIFEST),
        }, sort_keys=True, indent=2))
        return 0
    if args.write_supplemental_manifest_r02:
        supplemental = build_supplemental_manifest_r02()
        SUPPLEMENTAL_MANIFEST_R02.write_text(json.dumps(supplemental, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "WRITTEN_ONCE",
            "manifest_path": (PACKAGE_REL / SUPPLEMENTAL_MANIFEST_R02.name).as_posix(),
            "file_count": len(supplemental["files"]),
            "parent_reference_count": sum(len(item["parent_paths"]) for item in supplemental["files"]),
            "sha256": _sha256(SUPPLEMENTAL_MANIFEST_R02),
        }, sort_keys=True, indent=2))
        return 0
    if args.write_supplemental_manifest_r03:
        supplemental = build_supplemental_manifest_r03()
        SUPPLEMENTAL_MANIFEST_R03.write_text(json.dumps(supplemental, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "WRITTEN_ONCE",
            "manifest_path": (PACKAGE_REL / SUPPLEMENTAL_MANIFEST_R03.name).as_posix(),
            "file_count": len(supplemental["files"]),
            "parent_reference_count": sum(len(item["parent_paths"]) for item in supplemental["files"]),
            "sha256": _sha256(SUPPLEMENTAL_MANIFEST_R03),
        }, sort_keys=True, indent=2))
        return 0
    manifest = build_manifest()
    MANIFEST.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "WRITTEN_ONCE",
        "manifest_path": MANIFEST.relative_to(ROOT).as_posix(),
        "file_count": len(manifest["files"]),
        "parent_reference_count": sum(len(item["parent_paths"]) for item in manifest["files"]),
        "sha256": _sha256(MANIFEST),
    }, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
