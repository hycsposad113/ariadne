"""Fixed clean-fixture coverage for the R02 verifier's real clone harness."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts/verify_week4_repair_r04_amendments_r02.py"
FIXTURE_DIR = ROOT / "tests/fixtures/week4_r04_r02_clean"
FIXTURE_ROOT = FIXTURE_DIR / "project"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_fixed_fixture_manifest() -> None:
    manifest_path = FIXTURE_DIR / "fixture-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_excludes_self"] is True
    assert manifest["schema_version"] == "week4-r04-r02-clean-fixture-v1"
    entries = manifest["files"]
    assert entries
    for entry in entries:
        path = FIXTURE_DIR / entry["path"]
        assert path.is_file() and not path.is_symlink(), entry["path"]
        assert path.stat().st_size == entry["size_bytes"], entry["path"]
        assert _sha256(path) == entry["sha256"], entry["path"]


def test_fixed_clean_fixture_runs_all_five_real_r01_fault_cases():
    """Use fixed fixture bytes so live parent drift cannot skip fault cases."""
    fixture_package = FIXTURE_ROOT / "artifacts/week4-repair-r04"
    _verify_fixed_fixture_manifest()
    assert fixture_package.is_dir(), "fixed R02 clean-state fixture is missing"

    completed = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--package",
            str(fixture_package),
            "--project-root",
            str(FIXTURE_ROOT),
            "--self-test",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stderr == ""
    assert "Traceback" not in completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "PASS"
    assert result["upstream"]["status"] == "PASS"
    assert result["self_test"] == {
        "status": "PASS",
        "project_root_isolated_per_case": True,
        "public_docket_copy_used": True,
        "cases": {
            "valid_clone": "PASS",
            "byte_mutation": "BLOCKED",
            "missing_file": "BLOCKED",
            "missing_parent": "BLOCKED",
            "public_docket_copy_mutation": "BLOCKED",
        },
        "errors": [],
    }
