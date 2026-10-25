#!/usr/bin/env python3
"""Verify R04 package files, parent lineage, and narrow repair claims."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = ROOT / "artifacts/week4-repair-r04"
MANIFEST_NAME = "integrity-manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: Any) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        return None
    return path


def _load_json(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is missing or invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return None
    return value


def verify_package(
    package_root: str | Path = DEFAULT_PACKAGE,
    *,
    project_root: str | Path = ROOT,
    require_complete: bool = False,
) -> dict[str, Any]:
    package = Path(package_root).resolve()
    root = Path(project_root).resolve()
    errors: list[str] = []
    manifest = _load_json(package / MANIFEST_NAME, errors, "integrity manifest")
    if manifest is None:
        return {"status": "BLOCKED", "checked_files": 0, "checked_parents": 0, "errors": errors}
    if manifest.get("schema_version") != "week4-r04-integrity-manifest-v1":
        errors.append("unsupported R04 integrity manifest schema")
    if manifest.get("manifest_excludes_self") is not True:
        errors.append("integrity manifest must exclude its self hash")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        errors.append("manifest files must be a non-empty list")
        entries = []

    checked_files = 0
    checked_parents = 0
    seen: set[str] = set()
    entry_by_path: dict[str, dict[str, Any]] = {}
    package_rel = _safe_relative(manifest.get("package_path"))
    if package_rel is None:
        errors.append("manifest package_path is invalid")
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("manifest contains a non-object file entry")
            continue
        relative = _safe_relative(entry.get("path"))
        if relative is None:
            errors.append(f"manifest contains unsafe file path: {entry.get('path')!r}")
            continue
        key = relative.as_posix()
        if key == MANIFEST_NAME or key in seen:
            errors.append(f"manifest repeats or self-lists path: {key}")
            continue
        seen.add(key)
        entry_by_path[key] = entry
        path = package.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file():
            errors.append(f"package file is missing or unsafe: {key}")
        elif path.stat().st_size != entry.get("size_bytes") or _sha256(path) != entry.get("sha256"):
            errors.append(f"package file size or SHA-256 mismatch: {key}")
        else:
            checked_files += 1

        parents = entry.get("parent_paths")
        parent_hashes = entry.get("parent_sha256")
        if not isinstance(parents, list) or not isinstance(parent_hashes, dict):
            errors.append(f"parent lineage is invalid for {key}")
            continue
        if not all(isinstance(parent, str) for parent in parents):
            errors.append(f"parent paths contain invalid values for {key}")
            continue
        if len(parents) != len(set(parents)) or set(parents) != set(parent_hashes):
            errors.append(f"parent paths and SHA map differ for {key}")
            continue
        for parent in parents:
            safe_parent = _safe_relative(parent)
            if safe_parent is None:
                errors.append(f"unsafe declared parent path for {key}: {parent!r}")
                continue
            if package_rel is not None and safe_parent.parts[: len(package_rel.parts)] == package_rel.parts:
                parent_file = package.joinpath(*safe_parent.parts[len(package_rel.parts):])
            else:
                parent_file = root.joinpath(*safe_parent.parts)
            if parent_file.is_symlink() or not parent_file.is_file():
                errors.append(f"declared parent is missing or unsafe: {parent}")
                continue
            if _sha256(parent_file) != parent_hashes[parent]:
                errors.append(f"declared parent SHA-256 mismatch: {parent}")
                continue
            checked_parents += 1

    actual_paths: set[str] = set()
    for path in package.rglob("*"):
        if path.is_symlink():
            errors.append(f"package contains an unsafe symlink: {path.relative_to(package).as_posix()}")
        elif path.is_file() and path.name != MANIFEST_NAME:
            actual_paths.add(path.relative_to(package).as_posix())
    if actual_paths != seen:
        errors.append("package file inventory differs from the integrity manifest")

    if require_complete:
        _verify_semantics(package, root, entry_by_path, errors)

    return {
        "status": "PASS" if not errors else "BLOCKED",
        "checked_files": checked_files,
        "checked_parents": checked_parents,
        "errors": errors,
    }


def _verify_semantics(
    package: Path,
    root: Path,
    entries: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    required = {
        "evidence-bundle.json",
        "road-metric-decision.json",
        "request-log.json",
        "gate-status.json",
        "package-record.json",
        "decision-docket.md",
        "browser/report.json",
        "implementation-record.json",
    }
    if not required.issubset(entries):
        errors.append(f"R04 manifest lacks required package records: {sorted(required - set(entries))}")
        return
    bundle = _load_json(package / "evidence-bundle.json", errors, "R04 Evidence Card bundle")
    decision = _load_json(package / "road-metric-decision.json", errors, "road metric decision")
    request_log = _load_json(package / "request-log.json", errors, "request log")
    gates = _load_json(package / "gate-status.json", errors, "gate status")
    record = _load_json(package / "package-record.json", errors, "package record")
    browser = _load_json(package / "browser/report.json", errors, "Chromium E2E report")
    if bundle is not None:
        cards = bundle.get("cards")
        roads = [card for card in cards or [] if isinstance(card, dict) and card.get("metric_key") == "osm_highway_unique_centerline_length"]
        if bundle.get("schema_version") != "week4-r04-evidence-bundle-v1" or bundle.get("status") != "VERIFIED_SOURCE_RESULT_ALIGNMENT":
            errors.append("R04 Evidence Card bundle status or schema is invalid")
        if len(roads) != 1 or any(card.get("metric_key") == "osm_highway_centerline_length" for card in cards or []):
            errors.append("R04 bundle must have exactly one unique-centerline card and no stale R03 road card")
        elif (
            roads[0].get("value") != 8496.540522
            or roads[0].get("algorithm_version") != "r04-deduplicated-osm-centerline-union-v1"
            or not roads[0].get("method_diagnostics")
            or not roads[0].get("source_artifact_ids")
            or not roads[0].get("dataset_snapshot_ids")
        ):
            errors.append("R04 road card result, method, diagnostics, or provenance is incomplete")
    if decision is not None and decision.get("selected_metric_key") != "osm_highway_unique_centerline_length":
        errors.append("road metric decision does not identify the R04 metric")
    if request_log is not None:
        counts = request_log.get("requests", {})
        required_zero = (
            "pdok_requests", "osm_requests", "weather_requests", "candidate_api_requests",
            "outbound_model_requests", "qgis_mcp_calls", "outbound_external_http_requests",
        )
        if any(counts.get(key) != 0 for key in required_zero):
            errors.append("request log reports an out-of-scope external or QGIS request")
    if gates is not None:
        checkpoints = gates.get("r04_checkpoints", {})
        if any(checkpoints.get(f"CP{index}", {}).get("status") != "PASS" for index in range(5)):
            errors.append("one or more bounded R04 checkpoints is not PASS")
        if gates.get("week4_overall_status") != "INCOMPLETE":
            errors.append("R04 must preserve the incomplete Week 4 status")
        if any(gates.get("week4_gates", {}).get(key) == "PASS" for key in ("QGIS_GUI", "REGIONAL_SYNTAX", "LIVE_AI", "FORMAL_HUMAN_DECISION")):
            errors.append("R04 cannot claim completion of out-of-scope Week 4 gates")
    if record is not None:
        if record.get("status") != "R04_REPAIR_EVIDENCE_COMPLETE" or record.get("week4_overall_status") != "INCOMPLETE":
            errors.append("R04 package record status is invalid or overclaims Week 4")
        for field in ("approved_weather_source_count", "dataset_snapshots_published", "outbound_model_requests"):
            if record.get(field) != 0:
                errors.append(f"R04 package record must keep {field}=0")
        if record.get("formal_analysis_started") is not False or record.get("formal_site_or_design_boundary_approved") is not False:
            errors.append("R04 package record overclaims formal analysis or approval")
        if record.get("qgis_gui_tested") is not False or record.get("live_ai_tested") is not False:
            errors.append("R04 package record overclaims QGIS or live AI testing")
    if browser is not None:
        if browser.get("status") != "PASS" or browser.get("output_dir", {}).get("kind") != "absolute_temporary":
            errors.append("Chromium E2E did not PASS with an explicit absolute temporary output path")
        if browser.get("non_local_font_requests") != [] or browser.get("outbound_external_http_requests") != 0:
            errors.append("Chromium E2E reports a non-local font or external HTTP request")
        database = browser.get("database", {})
        if database.get("live_sqlite_written") is not False or database.get("authoritative_live_db_hash_before") != database.get("authoritative_live_db_hash_after"):
            errors.append("Chromium E2E modified or changed the authoritative SQLite database")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = verify_package(args.package, project_root=args.project_root, require_complete=True)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
