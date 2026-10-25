"""Regression tests for the versioned R04 amendment verifier self-test."""

from __future__ import annotations

import json
import subprocess
import sys
import hashlib
import shutil

import pytest

from test_week4_repair_integrity import (
    _approved_readonly_source_root, _safe_relative_path, _sqlite_backup,
)
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts/verify_week4_repair_r04_amendments_r02.py"
PACKAGE = ROOT / "artifacts/week4-repair-r04"


def _readonly_provenance_clone(tmp_path):
    """Resolve current parents explicitly; never refresh historical manifest hashes.

    The declared R02 read-only authority contract supplies only an isolated
    SQLite backup. This is current provenance, not a frozen historical DB.
    All source parents still come from the worktree under test.
    """
    source_root, _immutable, database_relative = _approved_readonly_source_root()
    clone_root = _safe_relative_path(tmp_path, "current-provenance")
    package_relative = PACKAGE.relative_to(ROOT).as_posix()
    source_package = _safe_relative_path(ROOT, package_relative)
    clone_package = _safe_relative_path(clone_root, package_relative)
    parents = set()
    for name in ("integrity-manifest.json", "integrity-manifest-r01.json"):
        manifest = json.loads(_safe_relative_path(source_package, name).read_text())
        parents.update(parent for entry in manifest["files"] for parent in entry["parent_paths"])
    # Validate every declared path before the first clone write. Resolve both
    # sides even for package-local parents; ancestor symlinks must not escape.
    paths = {}
    for relative in sorted(parents):
        target = _safe_relative_path(clone_root, relative)
        source = _safe_relative_path(
            source_root if relative == database_relative else ROOT, relative,
        )
        paths[relative] = (source, target)
    public = "docs/week4-r04-repair-evidence-docket-r01.md"
    public_source = _safe_relative_path(ROOT, public)
    public_target = _safe_relative_path(clone_root, public)
    receipt_path = _safe_relative_path(tmp_path, "provenance-backup-receipt.json")
    shutil.copytree(source_package, clone_package)
    receipts = {}
    for relative, (source, target) in paths.items():
        if target.is_file():
            continue  # package-local historical parents are already retained
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative == database_relative:
            receipts[relative] = _sqlite_backup(source, target)
        else:
            if source.is_symlink() or not source.is_file():
                raise AssertionError(f"current source parent is missing or unsafe: {relative}")
            shutil.copy2(source, target)
    public_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(public_source, public_target)
    receipt_path.write_text(json.dumps({
        "contract": "tests/fixtures/week4_r02_readonly/fixture-manifest.json",
        "source_root": str(source_root), "read_mode": "mode=ro",
        "copy_method": "sqlite3.Connection.backup",
        "scope": "current provenance only; historical parent hashes unchanged",
        "backups": receipts,
    }, sort_keys=True, indent=2))
    return clone_root, clone_package


def test_self_test_returns_status_and_runs_fault_cases_when_upstream_is_valid(tmp_path):
    provenance_root, provenance_package = _readonly_provenance_clone(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--package",
            str(provenance_package),
            "--project-root",
            str(provenance_root),
            "--self-test",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.stderr == ""
    assert "Traceback" not in completed.stdout
    result = json.loads(completed.stdout)
    self_test = result["self_test"]

    if result["upstream"]["status"] == "PASS":
        assert completed.returncode == 0, completed.stdout
        assert result["status"] == "PASS"
        assert self_test["status"] == "PASS"
        assert self_test["project_root_isolated_per_case"] is True
        assert self_test["public_docket_copy_used"] is True
        assert self_test["cases"] == {
            "valid_clone": "PASS",
            "byte_mutation": "BLOCKED",
            "missing_file": "BLOCKED",
            "missing_parent": "BLOCKED",
            "public_docket_copy_mutation": "BLOCKED",
        }
    else:
        assert completed.returncode == 1
        assert result["status"] == "BLOCKED"
        assert self_test["status"] == "BLOCKED"
        assert self_test["cases"] == {}
        assert "self-test skipped because upstream R04/R01 verification did not pass" in self_test["errors"]
        assert result["upstream"]["errors"]
        assert all("mismatch" in error for error in result["upstream"]["errors"])


def test_readonly_provenance_requires_explicit_authority_contract(tmp_path, monkeypatch):
    monkeypatch.delenv("Q5_READONLY_FIXTURE_ROOT", raising=False)
    with pytest.raises(pytest.fail.Exception, match="Q5_READONLY_FIXTURE_ROOT is required"):
        _readonly_provenance_clone(tmp_path)
    assert not (tmp_path / "current-provenance").exists()


def test_provenance_backup_preserves_archive_and_exact_current_drift(tmp_path):
    root, package = _readonly_provenance_clone(tmp_path)
    historical = json.loads((PACKAGE / "integrity-manifest.json").read_text())
    expected = set()
    for name in ("integrity-manifest.json", "integrity-manifest-r01.json"):
        assert (package / name).read_bytes() == (PACKAGE / name).read_bytes()
        manifest = json.loads((package / name).read_text())
        for entry in manifest["files"]:
            for parent, digest in entry["parent_sha256"].items():
                path = _safe_relative_path(root, parent)
                assert path.is_file() and not path.is_symlink(), parent
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    expected.add(parent)
    assert ".urban_design_runtime/state.sqlite3" in expected
    completed = subprocess.run([sys.executable, str(VERIFIER), "--package", str(package),
                                "--project-root", str(root), "--self-test"],
                               cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 1 and completed.stderr == ""
    result = json.loads(completed.stdout)
    assert result["status"] == "BLOCKED"
    assert result["self_test"]["cases"] == {}
    errors = result["upstream"]["errors"]
    direct = {error.split("mismatch: ", 1)[1] for error in errors
              if error.startswith("declared R04 parent SHA-256 mismatch: ")}
    assert direct == expected
    assert all("mismatch" in error for error in errors)
    assert result["upstream"]["checked_files"] == 25
    assert historical == json.loads((package / "integrity-manifest.json").read_text())


@pytest.mark.parametrize("case", [
    "absolute", "traversal", "source_ancestor_symlink",
    "clone_ancestor_symlink", "authority_ancestor_symlink",
    "backup_destination_ancestor_symlink",
])
def test_provenance_paths_fail_before_clone_write(tmp_path, monkeypatch, case):
    """Malicious parents cannot trigger even the initial package copy."""
    module = sys.modules[__name__]
    project = tmp_path / "project"
    package = project / "artifacts/week4-repair-r04"
    package.mkdir(parents=True)
    authority = tmp_path / "authority"
    authority.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_bytes(b"must remain unchanged")
    destination = tmp_path / "disposable"
    destination.mkdir()
    clone = destination / "current-provenance"
    clone.mkdir()
    relative = "parents/sentinel.txt"
    database_relative = ".urban_design_runtime/state.sqlite3"
    if case == "absolute":
        relative = str(sentinel)
    elif case == "traversal":
        relative = "../outside/sentinel.txt"
    elif case == "source_ancestor_symlink":
        (project / "parents").symlink_to(outside, target_is_directory=True)
    elif case == "clone_ancestor_symlink":
        (clone / "parents").symlink_to(outside, target_is_directory=True)
    elif case == "authority_ancestor_symlink":
        relative = database_relative
        (authority / ".urban_design_runtime").symlink_to(outside, target_is_directory=True)
    else:
        relative = database_relative
        (clone / ".urban_design_runtime").symlink_to(outside, target_is_directory=True)
    for name in ("integrity-manifest.json", "integrity-manifest-r01.json"):
        (package / name).write_text(json.dumps({"files": [{"parent_paths": [relative]}]}))
    monkeypatch.setattr(module, "ROOT", project)
    monkeypatch.setattr(module, "PACKAGE", package)
    # Isolate path validation from the separately tested real authority contract.
    monkeypatch.setattr(module, "_approved_readonly_source_root",
                        lambda: (authority, set(), database_relative))
    writes = []
    def forbid_write(*args, **kwargs):
        writes.append(args)
        raise AssertionError("clone write occurred before path preflight")
    monkeypatch.setattr(shutil, "copytree", forbid_write)
    monkeypatch.setattr(shutil, "copy2", forbid_write)
    monkeypatch.setattr(module, "_sqlite_backup", forbid_write)
    before = {p.relative_to(outside).as_posix(): p.read_bytes()
              for p in outside.rglob("*") if p.is_file()}
    with pytest.raises(AssertionError, match="confined relative path|escapes its root"):
        _readonly_provenance_clone(destination)
    assert writes == []
    assert {p.relative_to(outside).as_posix(): p.read_bytes()
            for p in outside.rglob("*") if p.is_file()} == before
    assert not (destination / "provenance-backup-receipt.json").exists()
    assert not (clone / "artifacts").exists()
