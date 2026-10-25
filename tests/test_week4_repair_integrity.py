"""R02 package integrity, lineage, and fail-closed regression tests."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import shutil
from collections import Counter
from pathlib import Path
from pathlib import PurePosixPath

import pytest

from scripts.verify_week4_repair_r02 import verify_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_REL = Path("artifacts/week4-repair-r02")
PACKAGE_ROOT = PROJECT_ROOT / PACKAGE_REL
MANIFEST = "integrity-manifest.json"
FIXTURE_MANIFEST = PROJECT_ROOT / "tests/fixtures/week4_r02_readonly/fixture-manifest.json"
FIXTURE_ROOT_ENV = "Q5_READONLY_FIXTURE_ROOT"


HISTORICAL_LEDGER_PREFIX = 285
HISTORICAL_LEDGER_PREFIX_SHA256 = "d7b084c3daf5630b465946dfa834172125daee33f4fb7baea4574f2582700992"


def _ledger_prefix_chain(connection: sqlite3.Connection, prefix: int = HISTORICAL_LEDGER_PREFIX) -> str:
    """Rolling SHA-256 of ledger rows with sequence 1..prefix, in order."""
    columns: list[str] = []
    for info in connection.execute("PRAGMA table_info(ledger_events)"):
        name = info[1]
        if not isinstance(name, str) or not name.isidentifier():
            raise AssertionError(f"unexpected ledger column name: {name!r}")
        columns.append(name)
    if not columns or columns[0] != "sequence":
        raise AssertionError("ledger sequence is not the first column")
    rows = connection.execute(
        f"SELECT {', '.join(columns)} FROM ledger_events WHERE sequence <= ? ORDER BY sequence",
        (prefix,),
    ).fetchall()
    if [row[0] for row in rows] != list(range(1, prefix + 1)):
        raise AssertionError(f"historical ledger prefix {prefix} is missing, gapped, or reordered")
    link = b""
    for row in rows:
        token = json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        link = hashlib.sha256(link + token).digest()
    return link.hex()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _safe_relative_path(root: Path, raw_path: str) -> Path:
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise AssertionError(f"fixture path is not a confined relative path: {raw_path!r}")
    resolved_root = root.resolve()
    resolved = resolved_root.joinpath(*relative.parts).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise AssertionError(f"fixture path escapes its root: {raw_path!r}")
    return resolved


def _approved_readonly_source_root() -> tuple[Path, set[str], str]:
    raw_root = os.environ.get(FIXTURE_ROOT_ENV)
    if not raw_root:
        pytest.fail(
            f"{FIXTURE_ROOT_ENV} is required for R02 current-state verification; "
            "set it to the approved read-only project root",
            pytrace=False,
        )
    try:
        source_root = Path(raw_root).expanduser().resolve(strict=True)
    except OSError as exc:
        pytest.fail(f"{FIXTURE_ROOT_ENV} does not resolve to a readable project root: {exc}", pytrace=False)
    if not source_root.is_dir():
        pytest.fail(f"{FIXTURE_ROOT_ENV} must name a directory: {source_root}", pytrace=False)

    fixture_manifest = _read_json(FIXTURE_MANIFEST)
    if fixture_manifest.get("schema_version") != "q5-readonly-fixture-manifest-v1":
        pytest.fail(f"unsupported read-only fixture manifest: {FIXTURE_MANIFEST}", pytrace=False)
    if fixture_manifest.get("source_root_env") != FIXTURE_ROOT_ENV:
        pytest.fail("fixture manifest source-root variable does not match the test contract", pytrace=False)

    allowed_static_paths = set()
    for item in fixture_manifest.get("immutable_files", []):
        relative = item.get("path")
        if not isinstance(relative, str):
            pytest.fail("read-only fixture manifest contains an invalid path", pytrace=False)
        path = _safe_relative_path(source_root, relative)
        if not path.is_file():
            pytest.fail(f"approved read-only fixture is missing: {relative}", pytrace=False)
        data = path.read_bytes()
        if len(data) != item.get("size_bytes"):
            pytest.fail(f"approved read-only fixture size mismatch: {relative}", pytrace=False)
        if hashlib.sha256(data).hexdigest() != item.get("sha256"):
            pytest.fail(f"approved read-only fixture SHA-256 mismatch: {relative}", pytrace=False)
        allowed_static_paths.add(relative)

    dynamic_database = fixture_manifest.get("dynamic_sqlite")
    if not isinstance(dynamic_database, dict) or dynamic_database.get("copy_method") != "sqlite3.Connection.backup":
        pytest.fail("fixture manifest must declare the SQLite backup API for the dynamic authority database", pytrace=False)
    database_relative = dynamic_database.get("path")
    if not isinstance(database_relative, str):
        pytest.fail("fixture manifest does not declare its dynamic SQLite path", pytrace=False)
    database_path = _safe_relative_path(source_root, database_relative)
    if not database_path.is_file():
        pytest.fail(f"approved read-only authority database is missing: {database_relative}", pytrace=False)
    return source_root, allowed_static_paths, database_relative


def _sqlite_backup(source: Path, target: Path) -> dict[str, str | int]:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.execute("PRAGMA query_only=ON")
        source_connection.backup(target_connection)
        target_connection.commit()
        quick_check = target_connection.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise AssertionError(f"disposable SQLite backup quick_check failed: {quick_check}")
    finally:
        target_connection.close()
        source_connection.close()
    data = target.read_bytes()
    return {"size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _refresh_entry(project_root: Path, package_root: Path, package_relative: str) -> None:
    manifest_path = package_root / MANIFEST
    manifest = _read_json(manifest_path)
    entry = next(item for item in manifest["files"] if item["path"] == package_relative)
    data = (package_root / package_relative).read_bytes()
    entry["size_bytes"] = len(data)
    entry["sha256"] = hashlib.sha256(data).hexdigest()
    project_relative = (PACKAGE_REL / package_relative).as_posix()
    for child in manifest["files"]:
        if project_relative in child.get("parent_sha256", {}):
            child["parent_sha256"][project_relative] = entry["sha256"]
    _write_json(manifest_path, manifest)


def _copy_verification_tree(tmp_path: Path) -> tuple[Path, Path]:
    source_root, allowed_static_paths, database_relative = _approved_readonly_source_root()
    temp_root = tmp_path / "project"
    temp_package = temp_root / PACKAGE_REL
    temp_package.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PACKAGE_ROOT, temp_package)
    manifest = _read_json(temp_package / MANIFEST)
    parent_paths = {
        parent
        for item in manifest["files"]
        for parent in item.get("parent_paths", [])
    }
    runtime = _read_json(temp_package / "runtime-state-check.json")
    package = _read_json(temp_package / "package-record.json")
    if runtime["database_path"] != database_relative:
        raise AssertionError("R02 runtime database path differs from the approved fixture manifest")
    parent_paths.add(database_relative)
    parent_paths.add(package["authority"]["study_area_artifact_path"])
    for parent in sorted(parent_paths):
        target = _safe_relative_path(temp_root, parent)
        if PurePosixPath(parent).parts[: len(PACKAGE_REL.parts)] == PACKAGE_REL.parts:
            if not target.is_file():
                raise AssertionError(f"R02 package parent is missing from the disposable tree: {parent}")
            continue
        source = _safe_relative_path(source_root, parent)
        if not source.is_file():
            raise AssertionError(f"approved read-only source parent is missing: {parent}")
        if not (PROJECT_ROOT / parent).is_file() and parent != database_relative and parent not in allowed_static_paths:
            raise AssertionError(f"worktree-only missing parent is not allowed by fixture manifest: {parent}")
        if parent == database_relative:
            _sqlite_backup(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return temp_root, temp_package


def _verify_fixture(tmp_path: Path, mutator=None):
    temp_root, temp_package = _copy_verification_tree(tmp_path)
    if mutator:
        mutator(temp_root, temp_package)
    return verify_package(temp_package, project_root=temp_root)


def test_r02_archive_remains_intact_and_reports_exact_current_source_drift(tmp_path):
    temp_root, temp_package = _copy_verification_tree(tmp_path)
    runtime = _read_json(temp_package / "runtime-state-check.json")
    database_path = _safe_relative_path(temp_root, runtime["database_path"])
    result = verify_package(temp_package, project_root=temp_root)
    manifest = _read_json(temp_package / MANIFEST)
    expected_source_drift = []
    for entry in manifest["files"]:
        for parent in entry.get("parent_paths", []):
            parent_path = _safe_relative_path(temp_root, parent)
            assert parent_path.is_file(), f"expected historical parent is missing: {parent}"
            expected_hash = entry["parent_sha256"][parent]
            actual_hash = hashlib.sha256(parent_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                expected_source_drift.append(f"parent SHA-256 mismatch: {parent}")

    with sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        assert db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert _ledger_prefix_chain(db) == HISTORICAL_LEDGER_PREFIX_SHA256
        ledger_count, ledger_max = db.execute(
            "SELECT COUNT(*), COALESCE(MAX(sequence), 0) FROM ledger_events"
        ).fetchone()
        snapshot_count = db.execute(
            "SELECT COUNT(*) FROM state_heads WHERE entity_type='DatasetSnapshot'"
        ).fetchone()[0]
        artifact_count = db.execute(
            "SELECT COUNT(*) FROM state_heads WHERE entity_type='Artifact'"
        ).fetchone()[0]
        workspace_revision = db.execute(
            "SELECT current_revision FROM state_heads WHERE entity_id=? AND entity_type='WorkspaceRevision'",
            (runtime["workspace"]["id"],),
        ).fetchone()[0]
        project_revision = db.execute(
            "SELECT current_revision FROM state_heads WHERE entity_id=? AND entity_type='Project'",
            (runtime["project"]["id"],),
        ).fetchone()[0]
        study_area = _read_json(temp_package / "package-record.json")["authority"]
        study_area_id = runtime["active_study_area"]["id"]
        study_area_revision = db.execute(
            "SELECT current_revision FROM state_heads WHERE entity_id=? AND entity_type='StudyArea'",
            (study_area_id,),
        ).fetchone()[0]
        study_area_payload = json.loads(db.execute(
            "SELECT payload_json FROM state_versions WHERE entity_id=? AND entity_type='StudyArea' AND revision=?",
            (study_area_id, study_area_revision),
        ).fetchone()[0])
        workspace_status = json.loads(db.execute(
            "SELECT payload_json FROM state_versions WHERE entity_id=? AND entity_type='WorkspaceRevision' AND revision=?",
            (runtime["workspace"]["id"], workspace_revision),
        ).fetchone()[0])["status"]

    semantic_state = result["semantic_state"]
    assert semantic_state["database_main_sha256"] == hashlib.sha256(database_path.read_bytes()).hexdigest()
    assert ledger_count >= HISTORICAL_LEDGER_PREFIX
    assert semantic_state["ledger_event_count"] == ledger_count
    assert semantic_state["ledger_max_sequence"] == ledger_max
    assert semantic_state["dataset_snapshot_count"] == snapshot_count
    assert semantic_state["artifact_count"] == artifact_count
    assert semantic_state["workspace_revision"] == workspace_revision
    assert semantic_state["project_revision"] == project_revision
    assert semantic_state["study_area_revision"] == study_area_revision
    assert semantic_state["study_area_status"] == study_area_payload["status"]
    assert semantic_state["study_area_artifact_sha256"] == study_area["study_area_artifact_sha256"]
    assert semantic_state["workspace_status"] == workspace_status

    baseline = runtime["expected_baseline"]
    semantic_comparisons = {
        "ledger_event_count": baseline["ledger_event_count"],
        "ledger_max_sequence": baseline["ledger_max_sequence"],
        "dataset_snapshot_count": baseline["dataset_snapshot_count"],
        "artifact_count": baseline["artifact_record_count"],
        "project_revision": runtime["project"]["revision"],
        "active_study_area_id": runtime["active_study_area"]["id"],
        "study_area_revision": baseline["active_study_area_revision"],
        "study_area_status": runtime["active_study_area"]["status"],
        "study_area_geometry_artifact_id": runtime["active_study_area"]["geometry_artifact_id"],
        "study_area_geometry_sha256": runtime["active_study_area"]["geometry_sha256"],
        "study_area_artifact_sha256": study_area["study_area_artifact_sha256"],
        "study_area_artifact_size_bytes": _safe_relative_path(
            temp_root, runtime["active_study_area_artifact_path"]
        ).stat().st_size,
        "workspace_revision": runtime["workspace"]["revision"],
        "workspace_status": runtime["workspace"]["status"],
        "workspace_study_area_id": runtime["active_study_area"]["id"],
    }
    expected_semantic_drift = {
        f"authoritative SQLite semantic state mismatch for {field}"
        for field, expected in semantic_comparisons.items()
        if semantic_state[field] != expected
    }
    expected_runtime_drift = set()
    if runtime["active_study_area"]["id"] != semantic_state["active_study_area_id"]:
        expected_runtime_drift.add("runtime capture StudyArea ID differs from SQLite")
    if runtime["active_study_area"]["revision"] != semantic_state["study_area_revision"]:
        expected_runtime_drift.add("runtime capture StudyArea revision differs from SQLite")
    if runtime["active_study_area"]["geometry_sha256"] != semantic_state["study_area_geometry_sha256"]:
        expected_runtime_drift.add("runtime capture StudyArea hash differs from SQLite")
    if runtime["ledger_event_count"] != ledger_count:
        expected_runtime_drift.add("runtime capture ledger count differs from SQLite")
    if runtime["dataset_snapshot_count"] != snapshot_count:
        expected_runtime_drift.add("runtime capture snapshot count differs from SQLite")
    if runtime["artifact_count"] != artifact_count:
        expected_runtime_drift.add("runtime capture artifact count differs from SQLite")
    expected_errors = [
        *expected_source_drift,
        *sorted(expected_semantic_drift),
        *sorted(expected_runtime_drift),
    ]

    assert result["checked_files"] == len(manifest["files"]) == 31
    assert result["checked_parents"] == sum(len(item.get("parent_paths", [])) for item in manifest["files"])
    assert Counter(result["errors"]) == Counter(expected_errors)
    assert result["status"] == ("BLOCKED" if expected_errors else "PASS")


def test_single_byte_mutation_is_blocked(tmp_path):
    def mutate(_root, package):
        target = package / "syntax/context.geojson"
        target.write_bytes(target.read_bytes() + b" ")

    result = _verify_fixture(tmp_path, mutate)
    assert result["status"] == "BLOCKED"
    assert any("SHA-256 mismatch" in error or "size mismatch" in error for error in result["errors"])


def test_missing_declared_parent_is_blocked(tmp_path):
    def mutate(root, package):
        manifest = _read_json(package / MANIFEST)
        entry = next(item for item in manifest["files"] if item["path"] == "syntax/source-manifest.json")
        external = next(parent for parent in entry["parent_paths"] if not parent.startswith(PACKAGE_REL.as_posix() + "/"))
        missing_parent = root / external
        missing_parent.rename(missing_parent.with_name(missing_parent.name + ".preserved-missing-parent"))

    result = _verify_fixture(tmp_path, mutate)
    assert result["status"] == "BLOCKED"
    assert any("parent file is missing" in error for error in result["errors"])


def test_wrong_parent_hash_is_blocked(tmp_path):
    def mutate(_root, package):
        manifest = _read_json(package / MANIFEST)
        entry = next(item for item in manifest["files"] if item["path"] == "package-record.json")
        parent = entry["parent_paths"][0]
        entry["parent_sha256"][parent] = "0" * 64
        _write_json(package / MANIFEST, manifest)

    result = _verify_fixture(tmp_path, mutate)
    assert result["status"] == "BLOCKED"
    assert any("parent SHA-256 mismatch" in error for error in result["errors"])


def test_wrong_source_revision_is_blocked_even_after_manifest_rehash(tmp_path):
    def mutate(_root, package):
        record_path = package / "package-record.json"
        record = _read_json(record_path)
        record["source_package_revision"] = "spatial-r02"
        _write_json(record_path, record)
        _refresh_entry(_root, package, "package-record.json")

    result = _verify_fixture(tmp_path, mutate)
    assert result["status"] == "BLOCKED"
    assert any("source_package_revision" in error for error in result["errors"])


def test_unknown_evidence_card_id_is_blocked_even_after_manifest_rehash(tmp_path):
    def mutate(root, package):
        handoff_path = package / "handoff.json"
        handoff = _read_json(handoff_path)
        handoff["valid_evidence_cards"] = ["evidence-card-not-in-r02"]
        _write_json(handoff_path, handoff)
        _refresh_entry(root, package, "handoff.json")

    result = _verify_fixture(tmp_path, mutate)
    assert result["status"] == "BLOCKED"
    assert any("Evidence Card IDs do not resolve" in error for error in result["errors"])


def test_source_feature_removed_from_context_is_blocked_even_after_manifest_rehash(tmp_path):
    def mutate(root, package):
        context_path = package / "syntax/context.geojson"
        context = _read_json(context_path)
        context["features"][0]["properties"]["source_feature_id"] = "way/not-in-spatial-r01"
        _write_json(context_path, context)
        _refresh_entry(root, package, "syntax/context.geojson")

    result = _verify_fixture(tmp_path, mutate)
    assert result["status"] == "BLOCKED"
    assert any("absent source feature" in error for error in result["errors"])


def test_ledger_prefix_chain_rejects_a_gap_and_changes_when_history_changes():
    def chain_for(second: str) -> str:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE ledger_events (sequence INTEGER, event_id TEXT)")
        connection.executemany(
            "INSERT INTO ledger_events (sequence, event_id) VALUES (?, ?)",
            [(1, "a"), (2, second)],
        )
        try:
            return _ledger_prefix_chain(connection, prefix=2)
        finally:
            connection.close()

    assert chain_for("b") == chain_for("b")
    assert chain_for("b") != chain_for("c")
    gapped = sqlite3.connect(":memory:")
    gapped.execute("CREATE TABLE ledger_events (sequence INTEGER, event_id TEXT)")
    gapped.executemany(
        "INSERT INTO ledger_events (sequence, event_id) VALUES (?, ?)",
        [(1, "a"), (3, "c")],
    )
    try:
        with pytest.raises(AssertionError, match="missing, gapped, or reordered"):
            _ledger_prefix_chain(gapped, prefix=2)
    finally:
        gapped.close()
