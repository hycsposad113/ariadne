"""Fail-closed integrity checks for R04 package and parent files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.verify_week4_repair_r04 import verify_package


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sample_package(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    package = root / "artifacts/week4-r04-fixture"
    package.mkdir(parents=True)
    parent = root / "parents/source.txt"
    parent.parent.mkdir(parents=True)
    parent.write_text("retained source", encoding="utf-8")
    payload = package / "payload.json"
    payload.write_text('{"status":"fixture"}\n', encoding="utf-8")
    manifest = {
        "schema_version": "week4-r04-integrity-manifest-v1",
        "package_path": "artifacts/week4-r04-fixture",
        "manifest_excludes_self": True,
        "files": [{
            "path": "payload.json",
            "size_bytes": payload.stat().st_size,
            "sha256": _sha(payload),
            "kind": "json",
            "parent_paths": ["parents/source.txt"],
            "parent_sha256": {"parents/source.txt": _sha(parent)},
        }],
    }
    (package / "integrity-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root, package


def test_valid_manifest_and_parent_pass(tmp_path):
    root, package = _sample_package(tmp_path)
    result = verify_package(package, project_root=root)
    assert result["status"] == "PASS"
    assert result["checked_files"] == 1
    assert result["checked_parents"] == 1


def test_single_byte_mutation_blocks_package(tmp_path):
    root, package = _sample_package(tmp_path)
    payload = package / "payload.json"
    payload.write_bytes(payload.read_bytes()[:-1] + b"X")
    result = verify_package(package, project_root=root)
    assert result["status"] == "BLOCKED"
    assert any("mismatch" in error for error in result["errors"])


def test_missing_declared_parent_blocks_package(tmp_path):
    root, package = _sample_package(tmp_path)
    (root / "parents/source.txt").unlink()
    result = verify_package(package, project_root=root)
    assert result["status"] == "BLOCKED"
    assert any("parent is missing" in error for error in result["errors"])


def test_removed_parent_reference_blocks_package(tmp_path):
    root, package = _sample_package(tmp_path)
    manifest_path = package / "integrity-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["parent_paths"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = verify_package(package, project_root=root)
    assert result["status"] == "BLOCKED"
    assert any("parent paths and SHA map differ" in error for error in result["errors"])
