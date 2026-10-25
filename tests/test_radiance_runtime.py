"""Tests for Radiance 6.0.2 runtime verification per W6 precursor lane plan (F1)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

RUNTIME_PATH = Path.home() / ".local" / "share" / "urban-design-runtimes" / "radiance-6.0.2-arm64"
MANIFEST_PATH = Path(__file__).resolve().parent.parent / "config" / "runtimes" / "radiance-6.0.2-arm64.json"
REQUIRED_EXECUTABLES = ["rad", "gendaymtx", "rtrace", "rfluxmtx", "oconv", "rmtxop"]
EXPECTED_ARCHIVE_SHA256 = "329ca788c6cedc641ad47577ce985ae16ee291acb1d5d02d7995192d58118cf0"


def _get_radiance_bin_dir() -> Path:
    if RUNTIME_PATH.exists() and (RUNTIME_PATH / "bin").is_dir():
        return RUNTIME_PATH / "bin"
    rtrace_in_path = shutil.which("rtrace")
    if rtrace_in_path:
        return Path(rtrace_in_path).parent
    pytest.skip(
        f"Radiance runtime not found at {RUNTIME_PATH} and not available in PATH. "
        "F1 runtime verification skipped."
    )


def test_radiance_manifest_integrity() -> None:
    assert MANIFEST_PATH.exists(), f"Manifest file missing: {MANIFEST_PATH}"
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["version"] == "6.0.2"
    assert manifest["architecture"] == "arm64"
    assert manifest["source"]["archive_sha256"] == EXPECTED_ARCHIVE_SHA256
    for exe in REQUIRED_EXECUTABLES:
        assert exe in manifest["required_executables"]
        assert exe in manifest["executable_hashes"]


def test_radiance_executables_exist_and_match_manifest() -> None:
    bin_dir = _get_radiance_bin_dir()
    assert MANIFEST_PATH.exists()
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        manifest = json.load(f)

    for exe_name in REQUIRED_EXECUTABLES:
        exe_path = bin_dir / exe_name
        assert exe_path.exists(), f"Missing required Radiance executable: {exe_name} at {exe_path}"
        assert os.access(exe_path, os.X_OK), f"Executable {exe_name} is not executable"

        with exe_path.open("rb") as f:
            computed_hash = hashlib.sha256(f.read()).hexdigest()
        expected_hash = manifest["executable_hashes"][exe_name]
        assert (
            computed_hash == expected_hash
        ), f"Hash mismatch for {exe_name}: expected {expected_hash}, got {computed_hash}"


def test_radiance_rtrace_version() -> None:
    bin_dir = _get_radiance_bin_dir()
    rtrace_path = bin_dir / "rtrace"
    env = os.environ.copy()
    lib_dir = bin_dir.parent / "lib"
    if lib_dir.is_dir():
        env["RAYPATH"] = str(lib_dir)

    result = subprocess.run(
        [str(rtrace_path), "-version"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, f"rtrace -version failed: {result.stderr}"
    assert "RADIANCE 6.0.2" in result.stdout or "RADIANCE 6.0.2" in result.stderr


def test_e1_runtime_verifier_uses_pinned_manifest_and_configures_raypath() -> None:
    from urban_design.environment.sunlight import verify_radiance_runtime

    status = verify_radiance_runtime()

    assert status.available is True
    assert status.version == "6.0.2"
    assert status.manifest_version == "6.0.2"
    assert os.environ["RAYPATH"] == str(RUNTIME_PATH / "lib")


def test_e1_runtime_verifier_rejects_version_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    from urban_design.environment.sunlight import verify_radiance_runtime

    captured: dict[str, str] = {}

    def wrong_version(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        assert isinstance(env, dict)
        captured["raypath"] = str(env.get("RAYPATH"))
        return subprocess.CompletedProcess(command, 0, "RADIANCE 6.0.1 test", "")

    monkeypatch.setattr(subprocess, "run", wrong_version)
    status = verify_radiance_runtime()

    assert status.available is False
    assert status.version == "6.0.1"
    assert "6.0.2" in (status.reason or "")
    assert captured["raypath"] == str(RUNTIME_PATH / "lib")
