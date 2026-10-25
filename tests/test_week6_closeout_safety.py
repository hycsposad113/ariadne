"""Safety and fault-matrix checks for the Week 6 closeout drill."""

from __future__ import annotations

import importlib.util
import json
import signal
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "week6_closeout",
    Path(__file__).resolve().parents[1] / "web" / "e2e" / "week6_closeout.py",
)
closeout = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(closeout)


def test_protected_ports_are_refused_before_any_bind():
    for port in (8795, 5195, 8787, 8644, 8788, 8789, 9876, 5173):
        with pytest.raises(closeout.CloseoutRefusal, match="protected"):
            closeout.assert_drill_port(port, kind="api")


def test_drill_ports_must_stay_in_the_temporary_ranges():
    with pytest.raises(closeout.CloseoutRefusal, match="temporary drill range"):
        closeout.assert_drill_port(8873, kind="api")
    with pytest.raises(closeout.CloseoutRefusal, match="temporary drill range"):
        closeout.assert_drill_port(5273, kind="web")


def test_listening_drill_port_is_refused_without_stopping_the_owner():
    held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    held.bind(("127.0.0.1", 8889))
    held.listen(1)
    try:
        with pytest.raises(closeout.CloseoutRefusal, match="occupied"):
            closeout.assert_drill_port(8889, kind="api")
        assert held.getsockname()[1] == 8889
    finally:
        held.close()


def test_existing_output_root_is_refused(tmp_path: Path):
    root = tmp_path / "closeout-out"
    root.mkdir()
    with pytest.raises(FileExistsError, match="already exists"):
        closeout.resolve_e2e_output_directory(root, project_root=closeout.PROJECT_ROOT)


def test_backup_refuses_the_authority_path_and_copies_a_readonly_source(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker(value) VALUES ('kept')")
    authority = tmp_path / "do-not-create" / "state.sqlite3"
    monkeypatch.setattr(closeout, "AUTHORITY_DATABASE", authority)
    with pytest.raises(closeout.CloseoutRefusal, match="authority"):
        closeout.isolated_backup(source, authority)
    assert not authority.exists()

    monkeypatch.setattr(closeout, "AUTHORITY_DATABASE", tmp_path / "other-authority.sqlite3")
    destination = tmp_path / "copy" / "state.sqlite3"
    digest = closeout.isolated_backup(source, destination)
    assert digest == closeout.sha256_file(destination)
    with sqlite3.connect(destination) as copied:
        assert copied.execute("SELECT value FROM marker").fetchone()[0] == "kept"
        assert copied.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_tampered_artifact_stays_outcome_unknown(tmp_path: Path):
    row = closeout.fault_tampered_artifact(tmp_path / "artifact")
    assert row == {
        "expected": "OUTCOME_UNKNOWN",
        "actual": "OUTCOME_UNKNOWN",
        "recovery": "ORIGINAL_BYTES_RETAINED",
    }


def test_wrong_passphrase_is_refused_and_omitted_from_the_result(tmp_path: Path):
    row = closeout.fault_wrong_passphrase(tmp_path / "keys" / "decision-key")
    assert row["expected"] == "REJECTED"
    assert row["actual"] == "REJECTED"
    assert row["recovery"] == "TEST_KEY_STILL_ACCEPTED"
    encoded = json.dumps(row)
    assert "closeout-test-key" not in encoded
    assert "closeout-wrong-key" not in encoded


def test_tampered_copy_hash_does_not_replace_the_backup(tmp_path: Path):
    source = tmp_path / "backup.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE marker(value TEXT)")
        connection.execute("INSERT INTO marker(value) VALUES ('stable')")
    recorded = closeout.sha256_file(source)
    row = closeout.fault_tampered_database_hash(source, tmp_path / "tampered.sqlite3")
    assert row == {
        "expected": "HASH_MISMATCH",
        "actual": "HASH_MISMATCH",
        "recovery": "BACKUP_HASH_RETAINED",
    }
    assert closeout.sha256_file(source) == recorded


def test_radiance_missing_directory_is_unavailable(tmp_path: Path):
    row = closeout.fault_radiance_unavailable(tmp_path / "no-radiance")
    assert row["expected"] == "UNAVAILABLE"
    assert row["actual"] == "UNAVAILABLE"
    assert row["recovery"] == "PINNED_MANIFEST_PRESENT"


def test_formal_e2_refusal_does_not_dispatch():
    row = closeout.fault_formal_e2_refusal()
    assert row == {"expected": "BLOCKED", "actual": "BLOCKED", "recovery": "READY_FOR_FOUNDER"}


@pytest.mark.parametrize("http_status", [401, 429])
def test_live_ai_fault_uses_the_fake_transport(tmp_path: Path, http_status: int):
    row = closeout.fault_live_ai(tmp_path / f"live-{http_status}.sqlite3", http_status=http_status)
    assert row["expected"] == f"HTTP_{http_status}"
    assert row["actual"] == f"HTTP_{http_status}"
    assert row["recovery"] == "NO_SOCKET"
    assert "fixture-key-not-live" not in json.dumps(row)


def test_killed_owner_recovers_as_interrupted_without_rerunning(tmp_path: Path):
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    def kill() -> None:
        import os

        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)

    try:
        row = closeout.recover_after_dead_owner(
            tmp_path / "jobs.sqlite3",
            process.pid,
            output_root=tmp_path / "job-root",
            before_recover=kill,
        )
    finally:
        if process.poll() is None:
            kill()
    assert row["expected"] == "INTERRUPTED"
    assert row["actual"] == "INTERRUPTED"
    assert row["recovery"] == "INTERRUPTED"
    assert row["error_code"] == "RECOVERY_REQUIRED"
