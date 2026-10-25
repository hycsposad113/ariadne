#!/usr/bin/env python3
"""Verify R04/R01 and exercise its verifier using complete disposable clones."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from verify_week4_repair_r04_amendments import (
    BASE_MANIFEST,
    DEFAULT_PACKAGE,
    DOCKET_AMENDMENT_DOC,
    ROOT,
    SUPPLEMENTAL_MANIFESTS,
    verify_package_with_amendments as verify_r01,
)


R01_DOCKET_IN_PACKAGE = "decision-docket-r01.md"
R01_CORRECTION = "docket-correction-r01.json"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: Any) -> PurePosixPath | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        return None
    return path


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _copy_tree(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"package root is missing or unsafe: {source}")
    destination.mkdir(parents=True, exist_ok=False)
    for source_path in source.rglob("*"):
        relative = source_path.relative_to(source)
        target_path = destination / relative
        if source_path.is_symlink():
            raise ValueError(f"cannot clone package symlink: {relative.as_posix()}")
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        elif source_path.is_file():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)


def _source_parent_hashes(package: Path) -> tuple[PurePosixPath, dict[str, str]]:
    manifest = _load_json(package / BASE_MANIFEST)
    package_relative = _safe_relative(manifest.get("package_path"))
    if package_relative is None:
        raise ValueError("base R04 manifest has an unsafe package_path")

    names = [BASE_MANIFEST, *SUPPLEMENTAL_MANIFESTS]
    parents: dict[str, str] = {}
    for name in names:
        path = package / name
        if not path.is_file():
            if name == BASE_MANIFEST:
                raise ValueError(f"required R04 manifest is missing: {name}")
            continue
        data = _load_json(path)
        entries = data.get("files")
        if not isinstance(entries, list):
            raise ValueError(f"manifest has no file list: {name}")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"manifest has invalid entry: {name}")
            paths = entry.get("parent_paths")
            hashes = entry.get("parent_sha256")
            if not isinstance(paths, list) or not isinstance(hashes, dict) or set(paths) != set(hashes):
                raise ValueError(f"manifest has incomplete parent links: {name}")
            for parent in paths:
                safe = _safe_relative(parent)
                digest = hashes.get(parent)
                if safe is None or not isinstance(digest, str):
                    raise ValueError(f"manifest has unsafe parent link: {parent!r}")
                previous = parents.setdefault(safe.as_posix(), digest)
                if previous != digest:
                    raise ValueError(f"manifests disagree on parent hash: {parent}")
    return package_relative, parents


def _make_project_clone(package: Path, source_root: Path, case_root: Path) -> tuple[Path, Path]:
    package_relative, parents = _source_parent_hashes(package)
    project_clone = case_root / "project"
    project_clone.mkdir(parents=True, exist_ok=False)
    package_clone = project_clone.joinpath(*package_relative.parts)
    package_clone.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree(package, package_clone)

    for relative, expected_sha in parents.items():
        parent_relative = _safe_relative(relative)
        if parent_relative is None:
            raise ValueError(f"unsafe declared parent path: {relative}")
        if parent_relative.parts[: len(package_relative.parts)] == package_relative.parts:
            # These lineage inputs are already part of the cloned package.
            continue
        source = source_root.joinpath(*parent_relative.parts)
        target = project_clone.joinpath(*parent_relative.parts)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"declared source parent is missing or unsafe: {relative}")
        if _sha(source) != expected_sha:
            raise ValueError(f"declared source parent hash changed before cloning: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    public_source = source_root / DOCKET_AMENDMENT_DOC
    public_target = project_clone / DOCKET_AMENDMENT_DOC
    package_docket = package / R01_DOCKET_IN_PACKAGE
    if public_source.is_symlink() or not public_source.is_file() or not package_docket.is_file():
        raise ValueError("public R01 docket or packaged R01 docket is missing or unsafe")
    if _sha(public_source) != _sha(package_docket):
        raise ValueError("public R01 docket does not match the packaged R01 docket")
    public_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(public_source, public_target)
    return project_clone, package_clone


def _mutate_one_byte(path: Path) -> None:
    data = path.read_bytes()
    if not data:
        raise ValueError(f"cannot mutate empty file: {path.name}")
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))


def _fault_case(
    *,
    name: str,
    package: Path,
    source_root: Path,
    case_root: Path,
    mutate: Callable[[Path, Path], None] | None = None,
) -> str:
    project_clone, package_clone = _make_project_clone(package, source_root, case_root)
    if mutate is not None:
        mutate(project_clone, package_clone)
    result = verify_r01(package_clone, project_root=project_clone, check_public_docket=True)
    return str(result.get("status", "BLOCKED"))


def _run_self_test(package_root: str | Path, project_root: str | Path) -> dict[str, Any]:
    package = Path(package_root).resolve()
    root = Path(project_root).resolve()
    cases: dict[str, str] = {}
    errors: list[str] = []
    clone_project_roots: set[Path] = set()

    def run(name: str, mutate: Callable[[Path, Path], None] | None = None) -> None:
        try:
            with tempfile.TemporaryDirectory(prefix=f"r04-r02-{name}-") as temporary:
                case_root = Path(temporary)
                clone_project_roots.add((case_root / "project").resolve())
                cases[name] = _fault_case(
                    name=name,
                    package=package,
                    source_root=root,
                    case_root=case_root,
                    mutate=mutate,
                )
        except Exception as exc:
            cases[name] = "ERROR"
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    run("valid_clone")
    run("byte_mutation", lambda _root, clone: _mutate_one_byte(clone / R01_DOCKET_IN_PACKAGE))
    run("missing_file", lambda _root, clone: (clone / R01_DOCKET_IN_PACKAGE).unlink())

    def remove_declared_parent(clone_root: Path, _clone: Path) -> None:
        # This R01 implementation record parent is external to the package.
        target = clone_root / "scripts/append_week4_repair_r04_docket_r01.py"
        target.unlink()

    run("missing_parent", remove_declared_parent)

    def mutate_public_docket(clone_root: Path, _clone: Path) -> None:
        _mutate_one_byte(clone_root / DOCKET_AMENDMENT_DOC)

    run("public_docket_copy_mutation", mutate_public_docket)

    expected = {
        "valid_clone": "PASS",
        "byte_mutation": "BLOCKED",
        "missing_file": "BLOCKED",
        "missing_parent": "BLOCKED",
        "public_docket_copy_mutation": "BLOCKED",
    }
    if cases != expected:
        errors.append(f"self-test outcomes differ from expectations: {cases!r}")
    return {
        "status": "PASS" if not errors else "BLOCKED",
        "project_root_isolated_per_case": (
            len(cases) == len(expected)
            and len(clone_project_roots) == len(expected)
            and root not in clone_project_roots
        ),
        "public_docket_copy_used": cases.get("public_docket_copy_mutation") == "BLOCKED",
        "cases": cases,
        "errors": errors,
    }


def verify_week4_r04_amendments_r02(
    package_root: str | Path = DEFAULT_PACKAGE,
    *,
    project_root: str | Path = ROOT,
    run_self_test: bool = False,
) -> dict[str, Any]:
    upstream = verify_r01(package_root, project_root=project_root, check_public_docket=True)
    result: dict[str, Any] = {
        "status": upstream.get("status", "BLOCKED"),
        "upstream": upstream,
    }
    if run_self_test:
        if upstream.get("status") != "PASS":
            result["self_test"] = {
                "status": "BLOCKED",
                "project_root_isolated_per_case": False,
                "public_docket_copy_used": False,
                "cases": {},
                "errors": ["self-test skipped because upstream R04/R01 verification did not pass"],
            }
        else:
            self_test = _run_self_test(package_root, project_root)
            result["self_test"] = self_test
            if self_test["status"] != "PASS":
                result["status"] = "BLOCKED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="verify independent disposable project clones with byte, missing-file, missing-parent, and public-docket faults",
    )
    args = parser.parse_args()
    try:
        result = verify_week4_r04_amendments_r02(
            args.package,
            project_root=args.project_root,
            run_self_test=args.self_test,
        )
    except Exception as exc:
        result = {
            "status": "BLOCKED",
            "errors": [f"verification failed safely: {type(exc).__name__}: {exc}"],
        }
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
