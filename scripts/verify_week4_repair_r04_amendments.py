#!/usr/bin/env python3
"""Verify the immutable R04 base package plus append-only docket amendments."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from verify_week4_repair_r04 import DEFAULT_PACKAGE, ROOT, verify_package as verify_base


BASE_MANIFEST = "integrity-manifest.json"
SUPPLEMENTAL_MANIFESTS = ("integrity-manifest-r01.json",)
DOCKET_AMENDMENT_DOC = "docs/week4-r04-repair-evidence-docket-r01.md"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path, errors: list[str], label: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is missing or invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return None
    return value


def _safe(value: Any) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        return None
    return path


def _manifest_file_set(package: Path, base: dict[str, Any], amendments: list[dict[str, Any]], errors: list[str]) -> set[str]:
    expected: set[str] = set()
    for source in [base, *amendments]:
        for entry in source.get("files", []):
            relative = _safe(entry.get("path") if isinstance(entry, dict) else None)
            if relative is None:
                errors.append("an R04 manifest contains an unsafe file path")
                continue
            key = relative.as_posix()
            if key in expected:
                errors.append(f"R04 manifest chain repeats file path: {key}")
            expected.add(key)
            path = package.joinpath(*relative.parts)
            if path.is_symlink() or not path.is_file():
                errors.append(f"R04 amendment file is missing or unsafe: {key}")
                continue
            if path.stat().st_size != entry.get("size_bytes") or _sha(path) != entry.get("sha256"):
                errors.append(f"R04 amendment file size or SHA-256 mismatch: {key}")
    return expected


def verify_package_with_amendments(
    package_root: str | Path = DEFAULT_PACKAGE,
    *,
    project_root: str | Path = ROOT,
    run_fault_tests: bool = False,
    check_public_docket: bool = True,
) -> dict[str, Any]:
    package = Path(package_root).resolve()
    root = Path(project_root).resolve()
    errors: list[str] = []
    base = _load(package / BASE_MANIFEST, errors, "base R04 manifest")
    if base is None:
        return {"status": "BLOCKED", "checked_files": 0, "checked_parents": 0, "errors": errors}
    base_sha = _sha(package / BASE_MANIFEST)
    amendments: list[dict[str, Any]] = []
    amendment_names = []
    prior_path = (PurePosixPath(base.get("package_path", "")) / BASE_MANIFEST).as_posix()
    prior_sha = base_sha
    for name in SUPPLEMENTAL_MANIFESTS:
        path = package / name
        if not path.is_file():
            continue
        amendment = _load(path, errors, f"R04 supplemental manifest {name}")
        if amendment is None:
            continue
        if amendment.get("schema_version") != "week4-r04-integrity-manifest-amendment-v1":
            errors.append(f"unsupported supplemental manifest schema: {name}")
        if amendment.get("package_path") != base.get("package_path"):
            errors.append(f"supplemental manifest package path differs: {name}")
        if amendment.get("manifest_excludes_self") is not True:
            errors.append(f"supplemental manifest must exclude itself: {name}")
        base_path = (PurePosixPath(base.get("package_path", "")) / BASE_MANIFEST).as_posix()
        if amendment.get("base_manifest_path") != base_path or amendment.get("base_manifest_sha256") != base_sha:
            errors.append(f"supplemental manifest does not bind frozen base R04 manifest: {name}")
        if amendment.get("previous_manifest_path") != prior_path or amendment.get("previous_manifest_sha256") != prior_sha:
            errors.append(f"supplemental manifest chain is broken: {name}")
        amendment_names.append(name)
        amendments.append(amendment)
        prior_path = (PurePosixPath(base.get("package_path", "")) / name).as_posix()
        prior_sha = _sha(path)

    base_entries = base.get("files")
    if not isinstance(base_entries, list):
        errors.append("base R04 manifest files are invalid")
        base_entries = []
    # Verify the immutable original package on a disposable copy that excludes
    # later append-only amendments, using the original verifier unchanged.
    with tempfile.TemporaryDirectory(prefix="r04-base-verify-", dir="/private/tmp") as temporary:
        temp_root = Path(temporary)
        relative_package = _safe(base.get("package_path"))
        if relative_package is None:
            errors.append("base R04 manifest package path is invalid")
            base_result = {"status": "BLOCKED", "checked_files": 0, "checked_parents": 0, "errors": []}
        else:
            base_copy = temp_root.joinpath(*relative_package.parts)
            base_copy.mkdir(parents=True)
            shutil.copy2(package / BASE_MANIFEST, base_copy / BASE_MANIFEST)
            for entry in base_entries:
                relative = _safe(entry.get("path") if isinstance(entry, dict) else None)
                if relative is None:
                    continue
                source = package.joinpath(*relative.parts)
                target = base_copy.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_file() and not source.is_symlink():
                    shutil.copy2(source, target)
            base_result = verify_base(base_copy, project_root=root, require_complete=True)
            if base_result.get("status") != "PASS":
                errors.append(f"frozen R04 base package verification failed: {base_result.get('errors')}")

    all_entries = [base, *amendments]
    package_file_set = _manifest_file_set(package, base, amendments, errors)
    checked_parents = 0
    package_rel = _safe(base.get("package_path"))
    for source_manifest in all_entries:
        for entry in source_manifest.get("files", []):
            if not isinstance(entry, dict):
                continue
            relative_path = _safe(entry.get("path"))
            if relative_path is None:
                continue
            key = relative_path.as_posix()
            parents = entry.get("parent_paths")
            hashes = entry.get("parent_sha256")
            if not isinstance(parents, list) or not isinstance(hashes, dict) or not all(isinstance(item, str) for item in parents):
                errors.append(f"invalid parent references for R04 path {key}")
                continue
            if len(parents) != len(set(parents)) or set(parents) != set(hashes):
                errors.append(f"parent path/hash references are incomplete for R04 path {key}")
                continue
            for parent in parents:
                safe_parent = _safe(parent)
                if safe_parent is None:
                    errors.append(f"unsafe declared parent path for {key}: {parent!r}")
                    continue
                if package_rel is not None and safe_parent.parts[:len(package_rel.parts)] == package_rel.parts:
                    parent_path = package.joinpath(*safe_parent.parts[len(package_rel.parts):])
                else:
                    parent_path = root.joinpath(*safe_parent.parts)
                if parent_path.is_symlink() or not parent_path.is_file():
                    errors.append(f"declared R04 parent is missing or unsafe: {parent}")
                elif _sha(parent_path) != hashes[parent]:
                    errors.append(f"declared R04 parent SHA-256 mismatch: {parent}")
                else:
                    checked_parents += 1

    ignored_manifests = {BASE_MANIFEST, *amendment_names}
    actual_files: set[str] = set()
    for path in package.rglob("*"):
        if path.is_symlink():
            errors.append(f"package contains an unsafe symlink: {path.relative_to(package).as_posix()}")
        elif path.is_file() and path.relative_to(package).as_posix() not in ignored_manifests:
            actual_files.add(path.relative_to(package).as_posix())
    if actual_files != package_file_set:
        errors.append("R04 package inventory differs from its base and supplemental manifests")

    correction = _load(package / "docket-correction-r01.json", errors, "R04 docket correction") if amendments else None
    if correction is not None:
        old_docket = package / "decision-docket.md"
        corrected_docket = package / "decision-docket-r01.md"
        original_test_results = _load(package / "test-results.json", errors, "base R04 test results")
        focused_summary = (((original_test_results or {}).get("focused_backend") or {}).get("summary") or "")
        full_summary = (original_test_results or {}).get("full_pytest_summary") or ""
        focused_match = re.search(r"\b(\d+) passed\b", focused_summary)
        full_match = re.search(r"\b(\d+) passed\b", full_summary)
        corrected = correction.get("corrected_results", {})
        if correction.get("supersedes", {}).get("path") != (PurePosixPath(base.get("package_path", "")) / "decision-docket.md").as_posix():
            errors.append("R04 docket correction names the wrong superseded file")
        if correction.get("supersedes", {}).get("sha256") != _sha(old_docket):
            errors.append("R04 docket correction does not bind the original docket hash")
        if focused_match is None or int(focused_match.group(1)) != corrected.get("focused_test_count"):
            errors.append("R04 corrected focused-test count does not match the preserved test result")
        if full_match is None or int(full_match.group(1)) != corrected.get("full_pytest_count"):
            errors.append("R04 corrected full-pytest count does not match the preserved test result")
        if not corrected_docket.is_file() or "43 passed" not in corrected_docket.read_text(encoding="utf-8") or "451 passed" not in corrected_docket.read_text(encoding="utf-8"):
            errors.append("R04 corrected docket does not carry the final 43/451 test counts")
        if check_public_docket:
            public_docket = root / DOCKET_AMENDMENT_DOC
            if not corrected_docket.is_file() or not public_docket.is_file() or _sha(corrected_docket) != _sha(public_docket):
                errors.append("public R04 docket does not byte-match its verified package amendment")

    result = {
        "status": "PASS" if not errors else "BLOCKED",
        "checked_files": len(package_file_set),
        "checked_parents": checked_parents,
        "errors": errors,
        "base_result": base_result,
        "amendment_manifests": amendment_names,
    }
    if run_fault_tests and not errors:
        result["fault_tests"] = _fault_tests(package, root)
        if any(value != "BLOCKED" for key, value in result["fault_tests"].items() if key != "valid_clone") or result["fault_tests"].get("valid_clone") != "PASS":
            result["status"] = "BLOCKED"
            result["errors"].append("append-only R04 amendment fault-injection expectations failed")
    return result


def _copy_package(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        rel = path.relative_to(source)
        target = destination / rel
        if path.is_symlink():
            raise ValueError(f"cannot fault-test a package symlink: {rel}")
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _fault_tests(package: Path, root: Path) -> dict[str, str]:
    outcomes: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="r04-amendment-faults-", dir="/private/tmp") as temporary:
        temp_root = Path(temporary)
        relative_package = package.relative_to(root) if package.is_relative_to(root) else Path("artifacts/week4-repair-r04")
        clone = temp_root / "valid" / relative_package
        clone.parent.mkdir(parents=True)
        _copy_package(package, clone)
        public_doc = temp_root / "valid" / DOCKET_AMENDMENT_DOC
        public_doc.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package / "decision-docket-r01.md", public_doc)
        outcomes["valid_clone"] = verify_package_with_amendments(clone, project_root=root)["status"]

        byte_clone_root = temp_root / "byte-mutation"
        byte_clone = byte_clone_root / relative_package
        byte_clone.parent.mkdir(parents=True)
        _copy_package(package, byte_clone)
        byte_target = byte_clone / "decision-docket-r01.md"
        raw = byte_target.read_bytes()
        byte_target.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        shutil.copy2(package / "decision-docket-r01.md", byte_clone_root / DOCKET_AMENDMENT_DOC)
        outcomes["byte_mutation"] = verify_package_with_amendments(byte_clone, project_root=root)["status"]

        missing_parent_root = temp_root / "missing-parent"
        missing_parent = missing_parent_root / relative_package
        missing_parent.parent.mkdir(parents=True)
        _copy_package(package, missing_parent)
        manifest_path = missing_parent / "integrity-manifest-r01.json"
        amendment = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = next(item for item in amendment["files"] if item["path"] == "docket-correction-r01.json")
        entry["parent_paths"].append("artifacts/week4-repair-r04/no-such-parent-r01.json")
        entry["parent_sha256"]["artifacts/week4-repair-r04/no-such-parent-r01.json"] = "0" * 64
        manifest_path.write_text(json.dumps(amendment, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        shutil.copy2(package / "decision-docket-r01.md", missing_parent_root / DOCKET_AMENDMENT_DOC)
        outcomes["missing_parent"] = verify_package_with_amendments(missing_parent, project_root=root)["status"]

    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--self-test", action="store_true", help="also inject faults into disposable package copies")
    args = parser.parse_args()
    result = verify_package_with_amendments(args.package, project_root=args.project_root, run_fault_tests=args.self_test)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
