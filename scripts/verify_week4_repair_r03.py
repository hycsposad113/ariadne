#!/usr/bin/env python3
"""Verify the append-only Week 4 R03 package without mutating project state."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = ROOT / "artifacts/week4-repair-r03"
MANIFEST_NAME = "integrity-manifest.json"
IMPLEMENTATION_AMENDMENT_NAME = "implementation-record-r01.json"
IMPLEMENTATION_AMENDMENT_R02_NAME = "implementation-record-r02.json"
IMPLEMENTATION_AMENDMENT_R03_NAME = "implementation-record-r03.json"
IMPLEMENTATION_AMENDMENT_R04_NAME = "implementation-record-r04.json"
SUPPLEMENTAL_MANIFEST_NAME = "integrity-manifest-r01.json"
SUPPLEMENTAL_MANIFEST_R02_NAME = "integrity-manifest-r02.json"
SUPPLEMENTAL_MANIFEST_R03_NAME = "integrity-manifest-r03.json"
R02_DRIFT_ADDENDUM_NAME = "r02-current-source-drift-r01.json"
R02_DRIFT_RECONCILIATION_NAME = "r02-current-source-drift-r02.json"
SUPPLEMENTAL_MANIFEST_NAMES = (
    SUPPLEMENTAL_MANIFEST_NAME,
    SUPPLEMENTAL_MANIFEST_R02_NAME,
    SUPPLEMENTAL_MANIFEST_R03_NAME,
)
SPATIAL_R01_REL = PurePosixPath(
    "artifacts/milestone2-analysis-inputs-rotterdam-m4h/"
    "run-study-area-rotterdam-m4h-pilot-project-v5-spatial-spatial-r01"
)
PACKAGE_REL = PurePosixPath("artifacts/week4-repair-r03")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: Any) -> PurePosixPath | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        return None
    return path


def _package_path(package_root: Path, project_relative: Any) -> Path | None:
    rel = _safe_relative(project_relative)
    if rel is None:
        return None
    try:
        package_rel = rel.relative_to(PACKAGE_REL)
    except ValueError:
        return None
    return package_root.joinpath(*package_rel.parts)


def _declared_parent_path(package_root: Path, project_root: Path, relative: str) -> tuple[Path, Path]:
    """Resolve package-internal parents in the verified package copy itself."""
    path = PurePosixPath(relative)
    try:
        package_relative = path.relative_to(PACKAGE_REL)
    except ValueError:
        return project_root.joinpath(*path.parts), project_root
    return package_root.joinpath(*package_relative.parts), package_root


def _read_json(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
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
    package_root: Path = DEFAULT_PACKAGE,
    *,
    project_root: Path = ROOT,
    expected_supplemental_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Fail closed on changed/missing files, incomplete parent links, or unsafe claims."""
    package_root = Path(package_root).resolve()
    project_root = Path(project_root).resolve()
    errors: list[str] = []
    manifest = _read_json(package_root / MANIFEST_NAME, errors, "integrity manifest")
    if manifest is None:
        return {"status": "BLOCKED", "checked_files": 0, "checked_parents": 0, "errors": errors}
    if manifest.get("schema_version") != "week4-r03-integrity-manifest-v1":
        errors.append("integrity manifest schema_version is unsupported")
    if manifest.get("manifest_excludes_self") is not True:
        errors.append("integrity manifest must explicitly exclude its self-hash")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        errors.append("integrity manifest files must be a non-empty list")
        entries = []

    base_entries = list(entries)
    supplemental_manifests: list[tuple[str, dict[str, Any]]] = []
    lineage_r01 = None
    lineage_r02 = None
    all_supplemental_entries: list[dict[str, Any]] = []
    base_path_set = {item.get("path") for item in base_entries if isinstance(item, dict)}
    seen_supplemental_paths: set[str] = set()
    for manifest_name in SUPPLEMENTAL_MANIFEST_NAMES:
        supplemental_path = package_root / manifest_name
        if not supplemental_path.exists():
            continue
        supplemental = _read_json(
            supplemental_path,
            errors,
            f"supplemental integrity manifest {manifest_name}",
        )
        if supplemental is None:
            continue
        supplemental_manifests.append((manifest_name, supplemental))
        if supplemental.get("schema_version") != "week4-r03-integrity-manifest-amendment-v1":
            errors.append(f"supplemental integrity manifest {manifest_name} schema_version is unsupported")
        if supplemental.get("package_id") != manifest.get("package_id"):
            errors.append(f"supplemental integrity manifest {manifest_name} package_id differs from base manifest")
        if supplemental.get("manifest_excludes_self") is not True:
            errors.append(f"supplemental integrity manifest {manifest_name} must explicitly exclude its self-hash")
        expected_base_path = (PACKAGE_REL / MANIFEST_NAME).as_posix()
        if supplemental.get("base_manifest_path") != expected_base_path:
            errors.append(f"supplemental integrity manifest {manifest_name} does not identify the base manifest")
        elif supplemental.get("base_manifest_sha256") != _sha256(package_root / MANIFEST_NAME):
            errors.append(f"supplemental integrity manifest {manifest_name} base SHA-256 mismatch")

        if manifest_name == SUPPLEMENTAL_MANIFEST_NAME:
            if supplemental_manifests[0][0] != SUPPLEMENTAL_MANIFEST_NAME:
                errors.append("R03 supplemental manifest chain is out of order")
        else:
            previous_name = {
                SUPPLEMENTAL_MANIFEST_R02_NAME: SUPPLEMENTAL_MANIFEST_NAME,
                SUPPLEMENTAL_MANIFEST_R03_NAME: SUPPLEMENTAL_MANIFEST_R02_NAME,
            }[manifest_name]
            previous_path = (PACKAGE_REL / previous_name).as_posix()
            previous_file = package_root / previous_name
            if not previous_file.is_file():
                errors.append(f"R03 supplemental manifest {manifest_name} is present without its {previous_name} predecessor")
            elif (
                supplemental.get("previous_manifest_path") != previous_path
                or supplemental.get("previous_manifest_sha256") != _sha256(previous_file)
            ):
                errors.append(f"R03 supplemental manifest {manifest_name} does not bind its {previous_name} predecessor")

        supplemental_entries = supplemental.get("files")
        if not isinstance(supplemental_entries, list) or not supplemental_entries:
            errors.append(f"supplemental integrity manifest {manifest_name} files must be a non-empty list")
            supplemental_entries = []
        for item in supplemental_entries:
            path = item.get("path") if isinstance(item, dict) else None
            if not isinstance(path, str):
                errors.append(f"supplemental integrity manifest {manifest_name} contains an invalid file path")
                continue
            if path in base_path_set or path in seen_supplemental_paths:
                errors.append(f"supplemental integrity manifest repeats a package path: {path}")
            seen_supplemental_paths.add(path)
            all_supplemental_entries.append(item)

    if supplemental_manifests:
        latest_name, _ = supplemental_manifests[-1]
        latest_manifest_sha256 = _sha256(package_root / latest_name)
        if expected_supplemental_manifest_sha256 is None:
            errors.append("an externally supplied latest supplemental manifest SHA-256 anchor is required")
        elif not re.fullmatch(r"[0-9a-f]{64}", expected_supplemental_manifest_sha256):
            errors.append("external supplemental manifest SHA-256 anchor must be 64 lowercase hexadecimal characters")
        elif expected_supplemental_manifest_sha256 != latest_manifest_sha256:
            errors.append("latest supplemental manifest SHA-256 does not match the external anchor")
    elif expected_supplemental_manifest_sha256 is not None:
        errors.append("external supplemental manifest SHA-256 anchor was supplied but no supplemental manifest exists")

    entries = [*base_entries, *all_supplemental_entries]
    if supplemental_manifests:
        lineage_r01 = _read_json(
            package_root / IMPLEMENTATION_AMENDMENT_NAME,
            errors,
            "historical implementation record amendment",
        )
        lineage_r02 = _read_json(
            package_root / IMPLEMENTATION_AMENDMENT_R02_NAME,
            errors,
            "current implementation record amendment",
        )
    lineage_r03 = None
    if (package_root / SUPPLEMENTAL_MANIFEST_R02_NAME).is_file():
        lineage_r03 = _read_json(
            package_root / IMPLEMENTATION_AMENDMENT_R03_NAME,
            errors,
            "latest implementation record amendment",
        )
    lineage_r04 = None
    if (package_root / SUPPLEMENTAL_MANIFEST_R03_NAME).is_file():
        lineage_r04 = _read_json(
            package_root / IMPLEMENTATION_AMENDMENT_R04_NAME,
            errors,
            "current implementation record amendment",
        )

    def is_valid_superseded_source_parent(relative: str, historical_sha: Any) -> bool:
        if not all(isinstance(record, dict) for record in (lineage_r01, lineage_r02, lineage_r03, lineage_r04)):
            return False
        historical_files = lineage_r01.get("files")
        second_files = lineage_r02.get("files")
        third_files = lineage_r03.get("files")
        current_files = lineage_r04.get("files")
        if not all(isinstance(files, list) for files in (historical_files, second_files, third_files, current_files)):
            return False
        historical_records = [historical_files, second_files, third_files]
        old_matches = [
            item for files in historical_records for item in files
            if isinstance(item, dict) and item.get("path") == relative and item.get("sha256") == historical_sha
        ]
        current = next((item for item in current_files if isinstance(item, dict) and item.get("path") == relative), None)
        if not old_matches or not isinstance(current, dict):
            return False
        for record, previous_name, expected_id in (
            (lineage_r02, IMPLEMENTATION_AMENDMENT_NAME, "implementation-record-r02"),
            (lineage_r03, IMPLEMENTATION_AMENDMENT_R02_NAME, "implementation-record-r03"),
            (lineage_r04, IMPLEMENTATION_AMENDMENT_R03_NAME, "implementation-record-r04"),
        ):
            previous_path = package_root / previous_name
            previous_rel = (PACKAGE_REL / previous_name).as_posix()
            supersedes = record.get("supersedes")
            if (
                record.get("amendment_id") != expected_id
                or not isinstance(supersedes, dict)
                or supersedes.get("path") != previous_rel
                or not previous_path.is_file()
                or supersedes.get("sha256") != _sha256(previous_path)
            ):
                return False
        source_path = project_root.joinpath(*PurePosixPath(relative).parts)
        return (
            source_path.is_file()
            and not source_path.is_symlink()
            and source_path.stat().st_size == current.get("size_bytes")
            and _sha256(source_path) == current.get("sha256")
        )

    listed: set[str] = set()
    checked_files = 0
    checked_parents = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"file entry {index} is not an object")
            continue
        rel = _safe_relative(entry.get("path"))
        if rel is None or rel.as_posix() == MANIFEST_NAME:
            errors.append(f"file entry {index} has an unsafe path")
            continue
        relative = rel.as_posix()
        if relative in listed:
            errors.append(f"duplicate manifest path: {relative}")
            continue
        listed.add(relative)
        path = package_root.joinpath(*rel.parts)
        if path.is_symlink() or package_root not in path.resolve().parents:
            errors.append(f"package file escapes package root or is a symlink: {relative}")
            continue
        if not path.is_file():
            errors.append(f"listed package file is missing: {relative}")
            continue
        checked_files += 1
        try:
            expected_size = int(entry.get("size_bytes"))
        except (TypeError, ValueError):
            expected_size = -1
        if path.stat().st_size != expected_size:
            errors.append(f"package file size mismatch: {relative}")
        expected_sha = entry.get("sha256")
        if not isinstance(expected_sha, str) or _sha256(path) != expected_sha:
            errors.append(f"package file SHA-256 mismatch: {relative}")

        parent_paths = entry.get("parent_paths")
        parent_sha256 = entry.get("parent_sha256")
        if not isinstance(parent_paths, list) or not isinstance(parent_sha256, dict):
            errors.append(f"parent references are invalid: {relative}")
            continue
        safe_parents: list[str] = []
        for parent in parent_paths:
            parent_rel = _safe_relative(parent)
            if parent_rel is None:
                errors.append(f"unsafe declared parent path for {relative}: {parent}")
                continue
            safe_parents.append(parent_rel.as_posix())
        if len(safe_parents) != len(set(safe_parents)):
            errors.append(f"duplicate declared parent path: {relative}")
        if not safe_parents:
            errors.append(f"package file has no declared provenance parents: {relative}")
        if set(safe_parents) != set(parent_sha256):
            errors.append(f"parent path/hash references are incomplete: {relative}")
        for parent_rel in safe_parents:
            expected_parent_sha = parent_sha256.get(parent_rel)
            parent_path, parent_root = _declared_parent_path(package_root, project_root, parent_rel)
            if parent_path.is_symlink() or parent_root not in parent_path.resolve().parents:
                errors.append(f"declared parent escapes project root or is a symlink: {parent_rel}")
                continue
            if not parent_path.is_file():
                errors.append(f"declared parent file is missing: {parent_rel}")
                continue
            checked_parents += 1
            if not isinstance(expected_parent_sha, str) or _sha256(parent_path) != expected_parent_sha:
                if is_valid_superseded_source_parent(parent_rel, expected_parent_sha):
                    continue
                errors.append(f"declared parent SHA-256 mismatch: {parent_rel}")

    actual = {
        item.relative_to(package_root).as_posix()
        for item in package_root.rglob("*")
        if item.is_file()
        and item.relative_to(package_root).as_posix() not in set((MANIFEST_NAME, *SUPPLEMENTAL_MANIFEST_NAMES))
    }
    for extra in sorted(actual - listed):
        errors.append(f"unmanifested package file: {extra}")
    for missing in sorted(listed - actual):
        errors.append(f"manifest lists absent package file: {missing}")

    record = _read_json(package_root / "package-record.json", errors, "package record")
    base_implementation_record_path = package_root / "implementation-record.json"
    amendment = _read_json(
        package_root / IMPLEMENTATION_AMENDMENT_NAME,
        errors,
        "implementation record amendment",
    )
    if amendment is not None:
        if amendment.get("schema_version") != "week4-r03-implementation-record-amendment-v1":
            errors.append("implementation record amendment schema_version is unsupported")
        supersedes = amendment.get("supersedes")
        expected_base_path = (PACKAGE_REL / "implementation-record.json").as_posix()
        if not isinstance(supersedes, dict) or supersedes.get("path") != expected_base_path:
            errors.append("implementation amendment does not name the original implementation record")
        elif not base_implementation_record_path.is_file() or supersedes.get("sha256") != _sha256(base_implementation_record_path):
            errors.append("implementation amendment does not bind the original record bytes")

        amendment_files = amendment.get("files")
        if not isinstance(amendment_files, list) or not amendment_files:
            errors.append("implementation amendment must list current changed files")
            amendment_files = []
        amendment_paths: set[str] = set()
        for item in amendment_files:
            if not isinstance(item, dict):
                errors.append("implementation amendment contains an invalid file entry")
                continue
            rel = _safe_relative(item.get("path"))
            if rel is None:
                errors.append("implementation amendment contains an unsafe source path")
                continue
            relative = rel.as_posix()
            if relative in amendment_paths:
                errors.append(f"implementation amendment repeats a source path: {relative}")
                continue
            amendment_paths.add(relative)
            source_path = project_root.joinpath(*rel.parts)
            if source_path.is_symlink() or project_root not in source_path.resolve().parents or not source_path.is_file():
                errors.append(f"implementation amendment source is missing or unsafe: {relative}")
                continue
            if source_path.stat().st_size != item.get("size_bytes") or _sha256(source_path) != item.get("sha256"):
                if not is_valid_superseded_source_parent(relative, item.get("sha256")):
                    errors.append(f"implementation amendment source hash/size mismatch: {relative}")

        amendment_entry = next(
            (item for item in entries if isinstance(item, dict) and item.get("path") == IMPLEMENTATION_AMENDMENT_NAME),
            None,
        )
        expected_amendment_parents = {
            expected_base_path,
            *amendment_paths,
        }
        if not isinstance(amendment_entry, dict) or set(amendment_entry.get("parent_paths", [])) != expected_amendment_parents:
            errors.append("implementation amendment manifest parents do not match its declared inputs")
        package_record_entry = next(
            (item for item in entries if isinstance(item, dict) and item.get("path") == "package-record.json"),
            None,
        )
        if not isinstance(package_record_entry, dict) or (PACKAGE_REL / IMPLEMENTATION_AMENDMENT_NAME).as_posix() not in package_record_entry.get("parent_paths", []):
            errors.append("package record manifest parents do not include the implementation amendment")

    if supplemental_manifests:
        amendment_r02 = _read_json(
            package_root / IMPLEMENTATION_AMENDMENT_R02_NAME,
            errors,
            "second implementation record amendment",
        )
        if amendment_r02 is not None:
            if amendment_r02.get("schema_version") != "week4-r03-implementation-record-amendment-v1":
                errors.append("second implementation record amendment schema_version is unsupported")
            if amendment_r02.get("amendment_id") != "implementation-record-r02":
                errors.append("second implementation amendment ID is invalid")
            supersedes = amendment_r02.get("supersedes")
            expected_path = (PACKAGE_REL / IMPLEMENTATION_AMENDMENT_NAME).as_posix()
            r01_path = package_root / IMPLEMENTATION_AMENDMENT_NAME
            if not isinstance(supersedes, dict) or supersedes.get("path") != expected_path:
                errors.append("second implementation amendment does not name implementation-record-r01")
            elif not r01_path.is_file() or supersedes.get("sha256") != _sha256(r01_path):
                errors.append("second implementation amendment does not bind implementation-record-r01 bytes")

            amendment_files = amendment_r02.get("files")
            if not isinstance(amendment_files, list) or not amendment_files:
                errors.append("second implementation amendment must list current changed files")
                amendment_files = []
            amendment_paths_r02: set[str] = set()
            for item in amendment_files:
                if not isinstance(item, dict):
                    errors.append("second implementation amendment contains an invalid file entry")
                    continue
                rel = _safe_relative(item.get("path"))
                if rel is None:
                    errors.append("second implementation amendment contains an unsafe source path")
                    continue
                relative = rel.as_posix()
                if relative in amendment_paths_r02:
                    errors.append(f"second implementation amendment repeats a source path: {relative}")
                    continue
                amendment_paths_r02.add(relative)
                source_path = project_root.joinpath(*rel.parts)
                if source_path.is_symlink() or project_root not in source_path.resolve().parents or not source_path.is_file():
                    errors.append(f"second implementation amendment source is missing or unsafe: {relative}")
                    continue
                if source_path.stat().st_size != item.get("size_bytes") or _sha256(source_path) != item.get("sha256"):
                    if not is_valid_superseded_source_parent(relative, item.get("sha256")):
                        errors.append(f"second implementation amendment source hash/size mismatch: {relative}")

            amendment_entry = next(
                (item for item in entries if isinstance(item, dict) and item.get("path") == IMPLEMENTATION_AMENDMENT_R02_NAME),
                None,
            )
            expected_parents = {
                expected_path,
                *amendment_paths_r02,
            }
            if not isinstance(amendment_entry, dict) or set(amendment_entry.get("parent_paths", [])) != expected_parents:
                errors.append("second implementation amendment manifest parents do not match its declared inputs")

        if (package_root / SUPPLEMENTAL_MANIFEST_R02_NAME).is_file():
            amendment_r03 = _read_json(
                package_root / IMPLEMENTATION_AMENDMENT_R03_NAME,
                errors,
                "third implementation record amendment",
            )
            if amendment_r03 is not None:
                if amendment_r03.get("schema_version") != "week4-r03-implementation-record-amendment-v1":
                    errors.append("third implementation record amendment schema_version is unsupported")
                if amendment_r03.get("amendment_id") != "implementation-record-r03":
                    errors.append("third implementation amendment ID is invalid")
                supersedes = amendment_r03.get("supersedes")
                expected_path_r03 = (PACKAGE_REL / IMPLEMENTATION_AMENDMENT_R02_NAME).as_posix()
                r02_record_path = package_root / IMPLEMENTATION_AMENDMENT_R02_NAME
                if not isinstance(supersedes, dict) or supersedes.get("path") != expected_path_r03:
                    errors.append("third implementation amendment does not name implementation-record-r02")
                elif not r02_record_path.is_file() or supersedes.get("sha256") != _sha256(r02_record_path):
                    errors.append("third implementation amendment does not bind implementation-record-r02 bytes")

                amendment_files_r03 = amendment_r03.get("files")
                if not isinstance(amendment_files_r03, list) or not amendment_files_r03:
                    errors.append("third implementation amendment must list current source files")
                    amendment_files_r03 = []
                amendment_paths_r03: set[str] = set()
                for item in amendment_files_r03:
                    if not isinstance(item, dict):
                        errors.append("third implementation amendment contains an invalid file entry")
                        continue
                    rel = _safe_relative(item.get("path"))
                    if rel is None:
                        errors.append("third implementation amendment contains an unsafe source path")
                        continue
                    relative = rel.as_posix()
                    if relative in amendment_paths_r03:
                        errors.append(f"third implementation amendment repeats a source path: {relative}")
                        continue
                    amendment_paths_r03.add(relative)
                    source_path = project_root.joinpath(*rel.parts)
                    if source_path.is_symlink() or project_root not in source_path.resolve().parents or not source_path.is_file():
                        errors.append(f"third implementation amendment source is missing or unsafe: {relative}")
                        continue
                    if source_path.stat().st_size != item.get("size_bytes") or _sha256(source_path) != item.get("sha256"):
                        if not is_valid_superseded_source_parent(relative, item.get("sha256")):
                            errors.append(f"third implementation amendment source hash/size mismatch: {relative}")

                amendment_entry_r03 = next(
                    (item for item in entries if isinstance(item, dict) and item.get("path") == IMPLEMENTATION_AMENDMENT_R03_NAME),
                    None,
                )
                expected_parents_r03 = {expected_path_r03, *amendment_paths_r03}
                if not isinstance(amendment_entry_r03, dict) or set(amendment_entry_r03.get("parent_paths", [])) != expected_parents_r03:
                    errors.append("third implementation amendment manifest parents do not match its declared inputs")

        if (package_root / SUPPLEMENTAL_MANIFEST_R03_NAME).is_file():
            amendment_r04 = _read_json(
                package_root / IMPLEMENTATION_AMENDMENT_R04_NAME,
                errors,
                "fourth implementation record amendment",
            )
            if amendment_r04 is not None:
                if amendment_r04.get("schema_version") != "week4-r03-implementation-record-amendment-v1":
                    errors.append("fourth implementation record amendment schema_version is unsupported")
                if amendment_r04.get("amendment_id") != "implementation-record-r04":
                    errors.append("fourth implementation amendment ID is invalid")
                supersedes = amendment_r04.get("supersedes")
                expected_path_r04 = (PACKAGE_REL / IMPLEMENTATION_AMENDMENT_R03_NAME).as_posix()
                r03_record_path = package_root / IMPLEMENTATION_AMENDMENT_R03_NAME
                if not isinstance(supersedes, dict) or supersedes.get("path") != expected_path_r04:
                    errors.append("fourth implementation amendment does not name implementation-record-r03")
                elif not r03_record_path.is_file() or supersedes.get("sha256") != _sha256(r03_record_path):
                    errors.append("fourth implementation amendment does not bind implementation-record-r03 bytes")
                amendment_files_r04 = amendment_r04.get("files")
                if not isinstance(amendment_files_r04, list) or not amendment_files_r04:
                    errors.append("fourth implementation amendment must list current source files")
                    amendment_files_r04 = []
                amendment_paths_r04: set[str] = set()
                for item in amendment_files_r04:
                    if not isinstance(item, dict):
                        errors.append("fourth implementation amendment contains an invalid file entry")
                        continue
                    rel = _safe_relative(item.get("path"))
                    if rel is None:
                        errors.append("fourth implementation amendment contains an unsafe source path")
                        continue
                    relative = rel.as_posix()
                    if relative in amendment_paths_r04:
                        errors.append(f"fourth implementation amendment repeats a source path: {relative}")
                        continue
                    amendment_paths_r04.add(relative)
                    source_path = project_root.joinpath(*rel.parts)
                    if source_path.is_symlink() or project_root not in source_path.resolve().parents or not source_path.is_file():
                        errors.append(f"fourth implementation amendment source is missing or unsafe: {relative}")
                        continue
                    if source_path.stat().st_size != item.get("size_bytes") or _sha256(source_path) != item.get("sha256"):
                        errors.append(f"fourth implementation amendment source hash/size mismatch: {relative}")
                amendment_entry_r04 = next(
                    (item for item in entries if isinstance(item, dict) and item.get("path") == IMPLEMENTATION_AMENDMENT_R04_NAME),
                    None,
                )
                expected_parents_r04 = {expected_path_r04, *amendment_paths_r04}
                if not isinstance(amendment_entry_r04, dict) or set(amendment_entry_r04.get("parent_paths", [])) != expected_parents_r04:
                    errors.append("fourth implementation amendment manifest parents do not match its declared inputs")

        drift_record = _read_json(
            package_root / R02_DRIFT_ADDENDUM_NAME,
            errors,
            "current R02 source-drift addendum",
        )
        if drift_record is not None:
            if (
                drift_record.get("schema_version") != "week4-r03-r02-source-drift-v1"
                or drift_record.get("status") != "BLOCKED_SOURCE_PARENT_DRIFT"
                or drift_record.get("verifier_status") != "BLOCKED"
            ):
                errors.append("R02 source-drift addendum does not preserve its blocked verifier status")

            r02_manifest_path = project_root / "artifacts/week4-repair-r02/integrity-manifest.json"
            if not r02_manifest_path.is_file():
                errors.append("frozen R02 integrity manifest is missing for source-drift verification")
                r02_manifest_for_drift = None
            else:
                r02_manifest_for_drift = _read_json(
                    r02_manifest_path,
                    errors,
                    "frozen R02 manifest for source-drift verification",
                )
                if drift_record.get("manifest_sha256") != _sha256(r02_manifest_path):
                    errors.append("R02 source-drift addendum manifest SHA-256 mismatch")

            expected_drift_errors: list[str] = []
            expected_drift_by_key: dict[tuple[str, str, str], int] = {}
            if r02_manifest_for_drift is not None:
                r02_files = r02_manifest_for_drift.get("files")
                if not isinstance(r02_files, list) or len(r02_files) != 31:
                    errors.append("R02 source-drift addendum parent manifest must list exactly 31 files")
                    r02_files = []
                for r02_entry in r02_files:
                    parents = r02_entry.get("parent_sha256") if isinstance(r02_entry, dict) else None
                    if not isinstance(parents, dict):
                        errors.append("R02 manifest entry has invalid parent hashes during drift verification")
                        continue
                    for parent, expected_sha in parents.items():
                        parent_rel = _safe_relative(parent)
                        if parent_rel is None:
                            errors.append(f"R02 manifest has an unsafe source parent: {parent}")
                            continue
                        parent_path = project_root.joinpath(*parent_rel.parts)
                        if parent_path.is_symlink() or project_root not in parent_path.resolve().parents or not parent_path.is_file():
                            errors.append(f"R02 source parent is missing or unsafe: {parent}")
                            continue
                        actual_sha = _sha256(parent_path)
                        if actual_sha != expected_sha:
                            expected_drift_errors.append(f"parent SHA-256 mismatch: {parent}")
                            key = (parent, str(expected_sha), actual_sha)
                            expected_drift_by_key[key] = expected_drift_by_key.get(key, 0) + 1

            actual_drift = drift_record.get("source_parent_drift")
            expected_drift = [
                {
                    "path": path,
                    "expected_sha256": expected_sha,
                    "actual_sha256": actual_sha,
                    "reference_count": reference_count,
                }
                for (path, expected_sha, actual_sha), reference_count in sorted(expected_drift_by_key.items())
            ]
            if actual_drift != expected_drift:
                errors.append("R02 source-drift addendum does not match the current exact source-parent hashes")
            if drift_record.get("verifier_errors") != expected_drift_errors:
                errors.append("R02 source-drift addendum verifier errors do not match the frozen parent references")
            if drift_record.get("source_parent_drift_count") != len(expected_drift_errors) or not expected_drift_errors:
                errors.append("R02 source-drift addendum parent drift count is incorrect or empty")
            expected_parent_count = sum(
                len(item.get("parent_paths", []))
                for item in (r02_manifest_for_drift or {}).get("files", [])
                if isinstance(item, dict)
            )
            if drift_record.get("checked_files") != 31 or drift_record.get("checked_parents") != expected_parent_count:
                errors.append("R02 source-drift addendum did not check the complete frozen package")
            if drift_record.get("archive_files_verified") != 31 or drift_record.get("archive_hashes_match") is not True:
                errors.append("R02 source-drift addendum does not prove all 31 frozen package files match")
            semantic = drift_record.get("semantic_state")
            authority = (record or {}).get("authority") if isinstance(record, dict) else None
            if not isinstance(semantic, dict) or not isinstance(authority, dict):
                errors.append("R02 source-drift addendum lacks captured SQLite semantic state")
            else:
                semantic_pairs = {
                    "active_study_area_id": authority.get("active_study_area_id"),
                    "study_area_revision": authority.get("active_study_area_revision"),
                    "study_area_status": authority.get("active_study_area_status"),
                    "study_area_geometry_sha256": authority.get("study_area_geometry_sha256"),
                    "project_revision": authority.get("project_revision"),
                    "ledger_event_count": authority.get("ledger_event_count_before_and_after"),
                    "dataset_snapshot_count": authority.get("dataset_snapshot_count_before_and_after"),
                    "artifact_count": authority.get("artifact_count_before_and_after"),
                    "workspace_revision": authority.get("workspace_revision_before_and_after"),
                    "workspace_status": "DRAFT",
                }
                for key, expected_value in semantic_pairs.items():
                    if semantic.get(key) != expected_value:
                        errors.append(f"R02 source-drift addendum SQLite semantic state differs from R03 baseline: {key}")
                if semantic.get("database_main_sha256") != authority.get("database_sha256_before_and_after"):
                    errors.append("R02 source-drift addendum database hash differs from R03 baseline")
                if semantic.get("database_hash_matches_capture") is not True:
                    errors.append("R02 source-drift addendum database hash was not verified against its capture")

            drift_entry = next(
                (item for item in entries if isinstance(item, dict) and item.get("path") == R02_DRIFT_ADDENDUM_NAME),
                None,
            )
            required_drift_parents = {
                "artifacts/week4-repair-r02/integrity-manifest.json",
                "artifacts/week4-repair-r02/package-record.json",
                "artifacts/week4-repair-r02/checkpoint-self-check.json",
                "scripts/verify_week4_repair_r02.py",
                "scripts/build_week4_r03_integrity_manifest.py",
                (PACKAGE_REL / MANIFEST_NAME).as_posix(),
                (PACKAGE_REL / "runtime-state-before.json").as_posix(),
                (PACKAGE_REL / "runtime-state-after.json").as_posix(),
                "tests/test_week4_repair_integrity.py",
                *[item["path"] for item in expected_drift],
            }
            if not isinstance(drift_entry, dict) or not required_drift_parents.issubset(set(drift_entry.get("parent_paths", []))):
                errors.append("R02 source-drift addendum manifest parents do not cover the captured evidence")
            elif drift_record.get("verifier_script") != {
                "path": "scripts/verify_week4_repair_r02.py",
                "sha256": drift_entry.get("parent_sha256", {}).get("scripts/verify_week4_repair_r02.py"),
            }:
                errors.append("R02 source-drift addendum verifier identity is not bound by its parent hashes")

        if (package_root / SUPPLEMENTAL_MANIFEST_R02_NAME).is_file():
            reconciliation = _read_json(
                package_root / R02_DRIFT_RECONCILIATION_NAME,
                errors,
                "R02 source-drift reconciliation",
            )
            if reconciliation is not None:
                historical_r02 = (record or {}).get("r02_preservation", {})
                historical_count = historical_r02.get("current_source_parent_hash_mismatches")
                current_count = (drift_record or {}).get("source_parent_drift_count")
                current_rows = (drift_record or {}).get("source_parent_drift")
                test_row = next(
                    (item for item in current_rows or [] if isinstance(item, dict) and item.get("path") == "tests/test_week4_repair_integrity.py"),
                    None,
                )
                delta = current_count - historical_count if isinstance(current_count, int) and isinstance(historical_count, int) else None
                expected_reconciliation = {
                    "schema_version": "week4-r03-r02-source-drift-reconciliation-v1",
                    "status": "HISTORICAL_COUNT_RECONCILED",
                    "historical_count": historical_count,
                    "current_count": current_count,
                    "delta_occurrences": delta,
                    "unique_current_parent_paths": len(current_rows) if isinstance(current_rows, list) else None,
                    "delta_attribution": {
                        "path": "tests/test_week4_repair_integrity.py",
                        "expected_sha256": test_row.get("expected_sha256") if isinstance(test_row, dict) else None,
                        "actual_sha256": test_row.get("actual_sha256") if isinstance(test_row, dict) else None,
                        "reference_count": test_row.get("reference_count") if isinstance(test_row, dict) else None,
                    },
                    "r02_archive_files_verified": (drift_record or {}).get("archive_files_verified"),
                    "r02_archive_hashes_match": (drift_record or {}).get("archive_hashes_match"),
                    "r02_bytes_modified_by_r03": (record or {}).get("r02_modified_by_r03"),
                    "historical_record": {
                        "path": (PACKAGE_REL / "package-record.json").as_posix(),
                        "sha256": _sha256(package_root / "package-record.json") if (package_root / "package-record.json").is_file() else None,
                        "captured_at_utc": (record or {}).get("created_at_utc"),
                        "field": "r02_preservation.current_source_parent_hash_mismatches",
                        "value": historical_count,
                    },
                    "current_recheck": {
                        "path": (PACKAGE_REL / R02_DRIFT_ADDENDUM_NAME).as_posix(),
                        "sha256": _sha256(package_root / R02_DRIFT_ADDENDUM_NAME) if (package_root / R02_DRIFT_ADDENDUM_NAME).is_file() else None,
                        "captured_at_utc": (drift_record or {}).get("captured_at_utc"),
                        "status": (drift_record or {}).get("status"),
                        "field": "source_parent_drift_count",
                        "value": current_count,
                        "unique_parent_paths": len(current_rows) if isinstance(current_rows, list) else None,
                    },
                }
                for key, expected_value in expected_reconciliation.items():
                    if reconciliation.get(key) != expected_value:
                        errors.append(f"R02 source-drift reconciliation field is inconsistent: {key}")
                current_unique_path_count = len(current_rows) if isinstance(current_rows, list) else None
                if historical_count != 21 or current_count != 24 or delta != 3 or current_unique_path_count != 6:
                    errors.append("R02 source-drift reconciliation does not preserve the 21-to-24 historical/current counts")
                if (
                    reconciliation.get("scope")
                    != "Append-only reconciliation of the package-record historical R02 drift count and the subsequent exact source-parent recheck."
                    or reconciliation.get("interpretation")
                    != "The package-record count of 21 is preserved as its historical capture. The subsequent read-only exact recheck found 24 parent-hash mismatch occurrences across six paths; three references to tests/test_week4_repair_integrity.py account for the difference. All 31 frozen R02 package files remain byte-identical."
                ):
                    errors.append("R02 source-drift reconciliation scope or interpretation is invalid")
                reconciliation_entry = next(
                    (item for item in entries if isinstance(item, dict) and item.get("path") == R02_DRIFT_RECONCILIATION_NAME),
                    None,
                )
                required_reconciliation_parents = {
                    (PACKAGE_REL / "package-record.json").as_posix(),
                    (PACKAGE_REL / R02_DRIFT_ADDENDUM_NAME).as_posix(),
                    "artifacts/week4-repair-r02/integrity-manifest.json",
                    "tests/test_week4_repair_integrity.py",
                }
                if not isinstance(reconciliation_entry, dict) or not required_reconciliation_parents.issubset(set(reconciliation_entry.get("parent_paths", []))):
                    errors.append("R02 source-drift reconciliation manifest parents do not cover its historical/current evidence")

    if record is not None:
        if record.get("status") != "R03_REPAIR_EVIDENCE_COMPLETE":
            errors.append("package record does not report evidence completion")
        if record.get("week4_overall_status") != "INCOMPLETE":
            errors.append("package record must preserve the incomplete overall Week 4 status")
        if (record.get("authority") or {}).get("formal_site_or_design_boundary_approved") is not False:
            errors.append("package record must not claim formal site or design-boundary approval")
        if record.get("approved_weather_source_count") != 0:
            errors.append("package record must not approve a weather source")
        if record.get("dataset_snapshots_published_by_r03") != 0:
            errors.append("package record must not claim DatasetSnapshot publication")
        if record.get("r02_modified_by_r03") is not False:
            errors.append("package record must preserve the R02 read-only boundary")
        if record.get("formal_analysis_started") is not False:
            errors.append("package record must not claim formal analysis started")

    # Confirm the frozen R02 archive itself remains complete, independent of its
    # intentionally changed current-source parents.
    r02_root = project_root / "artifacts/week4-repair-r02"
    r02_manifest = _read_json(r02_root / "integrity-manifest.json", errors, "frozen R02 manifest")
    if r02_manifest is not None:
        r02_entries = r02_manifest.get("files")
        if not isinstance(r02_entries, list) or len(r02_entries) != 31:
            errors.append("frozen R02 manifest must list exactly 31 archive files")
        else:
            for entry in r02_entries:
                rel = _safe_relative(entry.get("path") if isinstance(entry, dict) else None)
                if rel is None:
                    errors.append("frozen R02 manifest contains an unsafe archive path")
                    continue
                path = r02_root.joinpath(*rel.parts)
                if not path.is_file() or path.is_symlink():
                    errors.append(f"frozen R02 archive file is missing: {rel.as_posix()}")
                    continue
                if path.stat().st_size != entry.get("size_bytes") or _sha256(path) != entry.get("sha256"):
                    errors.append(f"frozen R02 archive file hash mismatch: {rel.as_posix()}")

    evidence = _read_json(package_root / "evidence-bundle.json", errors, "Evidence Card bundle")
    if evidence is not None:
        scope = evidence.get("scope")
        cards = evidence.get("cards")
        gaps = evidence.get("evidence_gaps")
        if not isinstance(scope, dict) or scope.get("project_id") != "rotterdam-m4h-pilot-project":
            errors.append("Evidence Card scope is not the active Rotterdam project")
        if not isinstance(scope, dict) or scope.get("study_area_id") != "study-area-rotterdam-m4h-pilot-project-v5":
            errors.append("Evidence Card scope is not StudyArea v5")
        if not isinstance(scope, dict) or scope.get("source_package_revision") != "spatial-r01":
            errors.append("Evidence Card source revision is not spatial-r01")
        if evidence.get("status") != "VERIFIED_SOURCE_RESULT_ALIGNMENT":
            errors.append("Evidence Card bundle is not source/result aligned")
        if not isinstance(cards, list) or len(cards) != 5:
            errors.append("R03 must contain the five expected observational cards")
        else:
            bundle_entry = next((item for item in entries if isinstance(item, dict) and item.get("path") == "evidence-bundle.json"), {})
            bundle_parents = bundle_entry.get("parent_sha256", {})
            for card in cards:
                if not isinstance(card, dict) or card.get("status") != "VERIFIED_OBSERVATION":
                    errors.append("Evidence Card has an invalid status")
                    continue
                if not card.get("unit") or not card.get("limitations"):
                    errors.append(f"Evidence Card lacks unit or limitations: {card.get('card_id')}")
                if (
                    card.get("source_package_id") != scope.get("source_package_id")
                    or card.get("source_package_revision") != scope.get("source_package_revision")
                    or card.get("study_area_id") != scope.get("study_area_id")
                    or card.get("study_area_revision") != scope.get("study_area_revision")
                    or card.get("study_area_geometry_sha256") != scope.get("study_area_geometry_sha256")
                ):
                    errors.append(f"Evidence Card scope differs from its bundle: {card.get('card_id')}")
                for hash_key in ("input_sha256", "output_sha256"):
                    if not isinstance(card.get(hash_key), str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", card[hash_key]):
                        errors.append(f"Evidence Card has an invalid {hash_key}: {card.get('card_id')}")
                if isinstance(card.get("input_sha256"), str) and isinstance(card.get("output_sha256"), str):
                    expected_card_id = "card-r03-{}-{}".format(
                        card.get("metric_key"),
                        hashlib.sha256((card["input_sha256"] + card["output_sha256"]).encode()).hexdigest()[:16],
                    )
                    if card.get("card_id") != expected_card_id:
                        errors.append(f"Evidence Card ID is not derived from its verified hashes: {card.get('card_id')}")
                parent_artifact_ids = set()
                parent_snapshot_ids = set()
                for parent in card.get("parents", []):
                    if not isinstance(parent, dict):
                        errors.append(f"Evidence Card has an invalid parent: {card.get('card_id')}")
                        continue
                    if parent.get("entity_type") == "Artifact":
                        parent_artifact_ids.add(parent.get("id"))
                        raw_source_path = parent.get("path")
                        if not isinstance(raw_source_path, str) or not raw_source_path.startswith("spatial-r01/"):
                            errors.append(f"Evidence Card Artifact parent has an unexpected source URI: {parent.get('id')}")
                            continue
                        source_rel = _safe_relative(raw_source_path.removeprefix("spatial-r01/"))
                        expected = parent.get("sha256")
                        if source_rel is None or not isinstance(expected, str) or not expected.startswith("sha256:"):
                            errors.append(f"Evidence Card Artifact parent is incomplete: {parent.get('id')}")
                            continue
                        path = project_root.joinpath(*SPATIAL_R01_REL.parts, *source_rel.parts)
                        manifest_rel = (SPATIAL_R01_REL / source_rel).as_posix()
                        if bundle_parents.get(manifest_rel) != expected.removeprefix("sha256:"):
                            errors.append(f"Evidence Card Artifact parent hash is not bound by the package manifest: {manifest_rel}")
                        if not path.is_file() or path.stat().st_size != parent.get("size_bytes") or _sha256(path) != expected.removeprefix("sha256:"):
                            errors.append(f"Evidence Card Artifact parent does not match retained source bytes: {manifest_rel}")
                    elif parent.get("entity_type") == "DatasetSnapshot":
                        parent_snapshot_ids.add(parent.get("id"))
                if set(card.get("source_artifact_ids", [])) != parent_artifact_ids:
                    errors.append(f"Evidence Card Artifact identities do not match parents: {card.get('card_id')}")
                if set(card.get("dataset_snapshot_ids", [])) != parent_snapshot_ids:
                    errors.append(f"Evidence Card DatasetSnapshot identities do not match parents: {card.get('card_id')}")
        if not isinstance(gaps, list) or not gaps or any(not isinstance(gap, dict) or gap.get("status") not in {"UNKNOWN", "BLOCKED"} for gap in gaps):
            errors.append("Evidence Card bundle must preserve explicit UNKNOWN/BLOCKED gaps")

        if record is not None and isinstance(scope, dict):
            source_package = record.get("source_package")
            authority = record.get("authority")
            if not isinstance(source_package, dict):
                errors.append("package record source package is missing")
            else:
                if source_package.get("package_id") != scope.get("source_package_id"):
                    errors.append("package record source package ID differs from Evidence Card scope")
                if source_package.get("revision") != scope.get("source_package_revision"):
                    errors.append("package record source package revision differs from Evidence Card scope")
                if source_package.get("source_integrity_status") != evidence.get("status"):
                    errors.append("package record source integrity status differs from Evidence Card bundle")
                if not isinstance(cards, list) or source_package.get("evidence_card_count") != len(cards):
                    errors.append("package record Evidence Card count differs from Evidence Card bundle")
                if not isinstance(gaps, list) or source_package.get("evidence_gap_count") != len(gaps):
                    errors.append("package record Evidence Gap count differs from Evidence Card bundle")
            if not isinstance(authority, dict):
                errors.append("package record authority state is missing for source scope comparison")
            else:
                if scope.get("project_id") != authority.get("project_id") or scope.get("project_revision") != authority.get("project_revision"):
                    errors.append("Evidence Card project scope differs from package authority state")
                if scope.get("study_area_id") != authority.get("active_study_area_id"):
                    errors.append("Evidence Card StudyArea differs from package authority state")
                if scope.get("study_area_revision") != authority.get("active_study_area_revision"):
                    errors.append("Evidence Card StudyArea revision differs from package authority state")
                if scope.get("study_area_geometry_sha256") != authority.get("study_area_geometry_sha256"):
                    errors.append("Evidence Card geometry hash differs from package authority state")

    syntax = _read_json(package_root / "syntax/syntax-status.json", errors, "Syntax status")
    if syntax is not None:
        if syntax.get("status") != "EXPLORATORY_800M_ONLY_SOURCE_COVERAGE_INSUFFICIENT":
            errors.append("Syntax status overstates its coverage")
        plan = syntax.get("layer_plan")
        if not isinstance(plan, list) or len(plan) != 6:
            errors.append("Syntax plan must list all six planned layers")
        else:
            computed = [item for item in plan if item.get("calculation_status") == "COMPUTED"]
            uncomputed = [item for item in plan if item.get("radius_m") in (2000, 10000)]
            if len(computed) != 2 or any(item.get("radius_m") != 800 for item in computed):
                errors.append("Only the two actual 800 m Syntax layers may be reported computed")
            if any(item.get("formal_result_eligible") is not False or item.get("segment_value_count") != 1272 for item in computed):
                errors.append("800 m Syntax layer counts or exploratory status changed")
            if len(uncomputed) != 4 or any(item.get("calculation_status") != "NOT_COMPUTED_COVERAGE_BLOCKED" or item.get("segment_value_count") != 0 for item in uncomputed):
                errors.append("2 km/10 km Syntax layers must remain uncomputed with zero values")
        if record is not None:
            source_package = record.get("source_package") or {}
            authority = record.get("authority") or {}
            if syntax.get("package_id") != source_package.get("package_id"):
                errors.append("Syntax source package ID differs from package record")
            if syntax.get("package_revision") != source_package.get("revision"):
                errors.append("Syntax source package revision differs from package record")
            if syntax.get("study_area_id") != authority.get("active_study_area_id"):
                errors.append("Syntax StudyArea differs from package authority state")
            if syntax.get("study_area_geometry_sha256") != authority.get("study_area_geometry_sha256"):
                errors.append("Syntax geometry hash differs from package authority state")
            if (record.get("syntax") or {}).get("status") != syntax.get("status"):
                errors.append("package record Syntax status differs from Syntax status artifact")

    figure = _read_json(package_root / "syntax/figure-record.json", errors, "exploratory figure record")
    if figure is not None:
        if figure.get("formal_result_eligible") is not False or figure.get("status") != "EXPLORATORY_RENDERED":
            errors.append("Syntax figure is not explicitly exploratory")
        for extension in ("svg", "png"):
            file_record = figure.get("files", {}).get(extension)
            figure_path = _package_path(package_root, file_record.get("path") if isinstance(file_record, dict) else None)
            if figure_path is None or not figure_path.is_file():
                errors.append(f"exploratory Syntax {extension.upper()} is missing or unsafe")
                continue
            if figure_path.stat().st_size != file_record.get("size_bytes") or _sha256(figure_path) != file_record.get("sha256"):
                errors.append(f"exploratory Syntax {extension.upper()} hash does not match its figure record")
        if record is not None:
            source_package = record.get("source_package") or {}
            authority = record.get("authority") or {}
            if figure.get("source_package_id") != source_package.get("package_id"):
                errors.append("figure source package ID differs from package record")
            if figure.get("source_package_revision") != source_package.get("revision"):
                errors.append("figure source package revision differs from package record")
            if figure.get("project_id") != authority.get("project_id"):
                errors.append("figure project differs from package authority state")
            if figure.get("study_area_id") != authority.get("active_study_area_id"):
                errors.append("figure StudyArea differs from package authority state")
            if figure.get("study_area_geometry_sha256") != authority.get("study_area_geometry_sha256"):
                errors.append("figure geometry hash differs from package authority state")

    if record is not None:
        report_path = _package_path(package_root, (record.get("browser_e2e") or {}).get("report_path"))
        report = _read_json(report_path, errors, "Chromium E2E report") if report_path is not None else None
        if report is None:
            errors.append("package record does not reference a safe Chromium report")
        else:
            if report.get("status") != "PASS" or report.get("database", {}).get("live_sqlite_written") is not False:
                errors.append("Chromium E2E report is not a successful disposable-database run")
            if report.get("api_port") in (8787, report.get("web_port")) or report.get("web_port") == 8787:
                errors.append("Chromium E2E port assignment conflicts with Hermes 8787 or each other")
            if report.get("outbound_model_requests") != 0 or report.get("outbound_geodata_weather_requests") != 0 or report.get("outbound_external_http_requests") != 0:
                errors.append("Chromium E2E reports outbound external requests")
            if report.get("blocked_external_request_attempts") and not all(isinstance(url, str) for url in report["blocked_external_request_attempts"]):
                errors.append("Chromium E2E external-request block log is malformed")

    requests = _read_json(package_root / "request-log.json", errors, "request log")
    if requests is not None:
        external = requests.get("external_requests", {})
        for key in (
            "candidate_zip_or_weather_api_requests",
            "pdok_requests",
            "osm_requests",
            "outbound_model_requests",
            "qgis_mcp_calls",
            "outbound_external_http_requests",
        ):
            if external.get(key) != 0:
                errors.append(f"request log reports a forbidden request count for {key}")
        network = requests.get("browser_network_boundary", {})
        if network.get("attempts_dispatched") is not False:
            errors.append("browser external requests were not confirmed blocked before dispatch")

    before = _read_json(package_root / "runtime-state-before.json", errors, "runtime state before")
    after = _read_json(package_root / "runtime-state-after.json", errors, "runtime state after")
    if before is not None and after is not None and before != after:
        errors.append("captured authoritative SQLite summaries differ before and after package generation")
    if record is not None and before is not None and after is not None:
        authority = record.get("authority")
        if not isinstance(authority, dict):
            errors.append("package record is missing its captured authority state")
        else:
            expected_authority = {
                "project_id": before.get("project_id"),
                "project_revision": before.get("project_revision"),
                "active_study_area_id": before.get("active_study_area_id"),
                "active_study_area_revision": before.get("study_area_revision"),
                "active_study_area_status": before.get("study_area_status"),
                "study_area_geometry_sha256": before.get("study_area_geometry_sha256"),
                "workspace_revision_before_and_after": before.get("workspace_revision"),
                "ledger_event_count_before_and_after": before.get("ledger_event_count"),
                "dataset_snapshot_count_before_and_after": before.get("dataset_snapshot_count"),
                "artifact_count_before_and_after": before.get("artifact_count"),
                "database_sha256_before_and_after": before.get("database_sha256"),
            }
            for key, expected in expected_authority.items():
                if authority.get(key) != expected:
                    errors.append(f"package record authority revision/state mismatch: {key}")
            if authority.get("active_study_area_id") != "study-area-rotterdam-m4h-pilot-project-v5" or authority.get("active_study_area_revision") != 1:
                errors.append("package record authority must bind active StudyArea v5 revision 1")
            if authority.get("workspace_revision_before_and_after") != 2:
                errors.append("package record authority must preserve the captured DRAFT workspace revision 2")

    r03_integrity_status = "PASS" if not errors else "BLOCKED"
    r02_status = (
        (drift_record or {}).get("status", "UNVERIFIED")
        if supplemental_manifests
        else "UNVERIFIED"
    )
    return {
        "status": "PASS_WITH_DECLARED_R02_SOURCE_PARENT_DRIFT" if not errors else "BLOCKED",
        "r03_integrity_status": r03_integrity_status,
        "r02_current_verifier_status": r02_status,
        "independent_acceptance": "PENDING_SOL_OR_ASTRA_REVIEW",
        "latest_supplemental_manifest_sha256": (
            _sha256(package_root / supplemental_manifests[-1][0]) if supplemental_manifests else None
        ),
        "checked_files": checked_files,
        "checked_parents": checked_parents,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument(
        "--expected-supplemental-manifest-sha256",
        help="externally supplied SHA-256 anchor for the latest append-only supplemental manifest",
    )
    args = parser.parse_args()
    result = verify_package(
        args.package,
        project_root=args.project_root,
        expected_supplemental_manifest_sha256=args.expected_supplemental_manifest_sha256,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["r03_integrity_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
