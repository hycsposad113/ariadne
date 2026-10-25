#!/usr/bin/env python3
"""Append PD-14 provenance annotations with fail-closed DB guards.

The authority path is deliberately fixed to the primary project checkout.
Disposable copies may be written without --write-authority; the authority DB
requires both --write-authority and an exact expected SHA-256.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from urban_design.provenance_audit import PD14_SPECIFICATIONS, annotate_pd14_events
from urban_design.store import ProjectStateStore


AUTHORITY_DATABASE = Path(
    "/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3"
).resolve()
OLD_EVENT_PREFIX_END = 187


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _typed_value(value: Any) -> list[Any]:
    if value is None:
        return ["null", None]
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    if isinstance(value, int):
        return ["integer", value]
    if isinstance(value, float):
        return ["real", value.hex()]
    if isinstance(value, str):
        return ["text-utf8-hex", value.encode("utf-8").hex()]
    raise TypeError(f"unsupported SQLite value type: {type(value).__name__}")


def _digest_rows(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    representation = {
        "columns": list(columns),
        "rows": [[_typed_value(value) for value in row] for row in rows],
    }
    encoded = json.dumps(
        representation, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _connect_readonly(database: Path, *, immutable: bool = False) -> sqlite3.Connection:
    query = "mode=ro&immutable=1" if immutable else "mode=ro"
    uri = f"file:{quote(database.resolve().as_posix(), safe='/')}?{query}"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _ledger_signature(connection: sqlite3.Connection, end_sequence: int) -> dict[str, Any]:
    columns = [row["name"] for row in connection.execute("PRAGMA table_info(ledger_events)")]
    rows = connection.execute(
        "SELECT * FROM ledger_events WHERE sequence <= ? ORDER BY sequence",
        (end_sequence,),
    ).fetchall()
    sequences = [int(row["sequence"]) for row in rows]
    expected_sequences = list(range(1, end_sequence + 1))
    if sequences != expected_sequences:
        raise ValueError(
            f"ledger prefix must contain sequences 1..{end_sequence}; found "
            f"{len(sequences)} rows ending at {sequences[-1] if sequences else None}"
        )
    return {
        "count": len(rows),
        "first_sequence": sequences[0],
        "last_sequence": sequences[-1],
        "columns": columns,
        "sha256": _digest_rows(columns, [tuple(row) for row in rows]),
    }


def _ledger_prefix_signature(connection: sqlite3.Connection) -> dict[str, Any]:
    signature = _ledger_signature(connection, OLD_EVENT_PREFIX_END)
    signature["encoding"] = "typed SQLite values; TEXT encoded as exact UTF-8 bytes represented in hex"
    return signature


def _annotation_ids(connection: sqlite3.Connection) -> set[str]:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='state_versions'"
    ).fetchone():
        raise ValueError("state_versions table is missing")
    return {
        row["entity_id"]
        for row in connection.execute(
            "SELECT entity_id FROM state_versions WHERE entity_type='ProvenanceAnnotation'"
        )
        if row["entity_id"] in {f"provenance-annotation-seq-{seq}" for seq in PD14_SPECIFICATIONS}
    }


def _state_signature(connection: sqlite3.Connection) -> dict[str, Any]:
    head_columns = ["entity_id", "entity_type", "project_id", "current_revision"]
    head_rows = connection.execute(
        "SELECT entity_id, entity_type, project_id, current_revision FROM state_heads "
        "WHERE entity_type != 'ProvenanceAnnotation' ORDER BY entity_type, entity_id"
    ).fetchall()
    version_columns = [
        "entity_id", "entity_type", "revision", "project_id", "payload_json",
        "created_at", "parent_revision", "supersedes", "event_id",
    ]
    version_rows = connection.execute(
        "SELECT entity_id, entity_type, revision, project_id, payload_json, created_at, "
        "parent_revision, supersedes, event_id FROM state_versions "
        "WHERE entity_type != 'ProvenanceAnnotation' ORDER BY entity_type, entity_id, revision"
    ).fetchall()
    head_counts = {
        row["entity_type"]: row["count"]
        for row in connection.execute(
            "SELECT entity_type, COUNT(*) AS count FROM state_heads GROUP BY entity_type ORDER BY entity_type"
        )
    }
    protected_heads = [
        list(row)
        for row in connection.execute(
            "SELECT entity_id, entity_type, project_id, current_revision FROM state_heads "
            "WHERE entity_type IN ('Project','StudyArea','Constraint','HumanDecision') "
            "ORDER BY entity_type, entity_id"
        )
    ]
    return {
        "head_counts": head_counts,
        "non_annotation_heads_sha256": _digest_rows(
            head_columns, [tuple(row) for row in head_rows]
        ),
        "non_annotation_versions_sha256": _digest_rows(
            version_columns, [tuple(row) for row in version_rows]
        ),
        "protected_head_rows": protected_heads,
    }


def _readback_annotations(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT sv.entity_id, sv.revision, sv.payload_json, sv.event_id, "
        "le.sequence AS ledger_sequence, le.actor, le.actor_kind, le.actor_session_id "
        "FROM state_versions AS sv JOIN ledger_events AS le ON le.event_id = sv.event_id "
        "WHERE sv.entity_type='ProvenanceAnnotation' ORDER BY sv.entity_id"
    ).fetchall()
    expected_ids = {f"provenance-annotation-seq-{seq}" for seq in PD14_SPECIFICATIONS}
    annotations: list[dict[str, Any]] = []
    for row in rows:
        if row["entity_id"] not in expected_ids:
            continue
        payload = json.loads(row["payload_json"])
        target_sequence = next(
            (seq for seq in PD14_SPECIFICATIONS if row["entity_id"] == f"provenance-annotation-seq-{seq}"),
            None,
        )
        if target_sequence is None:
            raise ValueError(f"unexpected PD-14 annotation id: {row['entity_id']}")
        target_event = connection.execute(
            "SELECT event_id FROM ledger_events WHERE sequence=?", (target_sequence,)
        ).fetchone()
        spec = PD14_SPECIFICATIONS[target_sequence]
        if target_event is None or payload.get("target_event_id") != target_event["event_id"]:
            raise ValueError(f"annotation {row['entity_id']} points at the wrong ledger event")
        if payload.get("category") != spec["category"] or payload.get("rationale") != spec["rationale"]:
            raise ValueError(f"annotation {row['entity_id']} does not match the PD-14 specification")
        if row["revision"] != 1 or row["actor"] != "annotation-auditor" or row["actor_kind"] != "AGENT_AUTOMATION":
            raise ValueError(f"annotation {row['entity_id']} has unexpected revision or actor metadata")
        annotations.append(
            {
                "annotation_id": row["entity_id"],
                "target_sequence": target_sequence,
                "target_event_id": payload["target_event_id"],
                "annotation_revision": row["revision"],
                "ledger_sequence": row["ledger_sequence"],
                "ledger_event_id": row["event_id"],
                "actor": row["actor"],
                "actor_kind": row["actor_kind"],
                "actor_session_id": row["actor_session_id"],
                "category": payload["category"],
                "source_actor_label": payload["source_actor_label"],
                "rationale": payload["rationale"],
            }
        )
    return annotations


def _backup_with_sqlite_cli(database: Path, backup: Path) -> None:
    command = ["sqlite3", str(database), f'.backup "{backup}"']
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "sqlite3 .backup failed: " + (result.stderr.strip() or f"exit {result.returncode}")
        )
    if not backup.is_file():
        raise RuntimeError("sqlite3 .backup reported success but no snapshot file exists")


def _write_json_no_overwrite(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append PD-14 ledger annotations with DB guards")
    parser.add_argument("--database", type=Path, required=True, help="Explicit SQLite database path")
    parser.add_argument(
        "--expected-sha256", required=True,
        help="Exact SHA-256 expected before the operation; stale state fails closed",
    )
    parser.add_argument("--write-authority", action="store_true", help="Permit writes to the primary authority DB")
    parser.add_argument(
        "--backup-dir", type=Path,
        default=Path.home() / ".local" / "share" / "urban-design-backups",
    )
    parser.add_argument("--receipt-out", type=Path, required=True, help="New, non-existing receipt path")
    args = parser.parse_args(argv)

    database = args.database.resolve()
    receipt_path = args.receipt_out.resolve()
    backup_dir = args.backup_dir.resolve()
    is_authority = database == AUTHORITY_DATABASE.resolve()
    if is_authority and not args.write_authority:
        print("BLOCKED: primary authority DB requires --write-authority", file=sys.stderr)
        return 1
    if args.write_authority and not is_authority:
        print("BLOCKED: --write-authority is restricted to the primary authority DB path", file=sys.stderr)
        return 1
    if not database.is_file():
        print(f"BLOCKED: database does not exist: {database}", file=sys.stderr)
        return 1
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.expected_sha256):
        print("BLOCKED: --expected-sha256 must be 64 hexadecimal characters", file=sys.stderr)
        return 1
    if receipt_path.exists() or receipt_path.is_symlink():
        print(f"BLOCKED: receipt path already exists: {receipt_path}", file=sys.stderr)
        return 1
    if not receipt_path.parent.is_dir():
        print(f"BLOCKED: receipt parent directory does not exist: {receipt_path.parent}", file=sys.stderr)
        return 1

    sha_before = _sha256(database)
    if sha_before.lower() != args.expected_sha256.lower():
        print(
            f"BLOCKED: expected SHA-256 {args.expected_sha256.lower()} but found {sha_before}",
            file=sys.stderr,
        )
        return 1

    operation_started = datetime.now(timezone.utc).isoformat()
    try:
        with closing(_connect_readonly(database)) as connection:
            quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
            if quick_check != "ok":
                raise ValueError(f"database quick_check failed: {quick_check}")
            prefix_before = _ledger_prefix_signature(connection)
            state_before = _state_signature(connection)
            total_before, max_sequence_before = connection.execute(
                "SELECT COUNT(*), MAX(sequence) FROM ledger_events"
            ).fetchone()
            preexisting_ledger_before = _ledger_signature(connection, int(max_sequence_before))
            existing_annotations = _annotation_ids(connection)
            target_rows = connection.execute(
                "SELECT sequence, event_id FROM ledger_events WHERE sequence BETWEEN 182 AND 187 ORDER BY sequence"
            ).fetchall()
            if [row["sequence"] for row in target_rows] != list(range(182, 188)):
                raise ValueError("ledger events 182-187 are incomplete")
            expected_annotation_ids = {f"provenance-annotation-seq-{seq}" for seq in PD14_SPECIFICATIONS}
            if existing_annotations - expected_annotation_ids:
                raise ValueError("unexpected pre-existing PD-14 annotation identifiers")
        if sha_before != _sha256(database):
            raise ValueError("database changed during read-only preflight")

        annotations_added: list[dict[str, Any]] = []
        backup_info: dict[str, Any] | None = None
        if existing_annotations != expected_annotation_ids:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = backup_dir / f"state_pre_pd14_annotations_{stamp}_{sha_before[:12]}.sqlite3"
            if backup_path.exists():
                raise FileExistsError(f"backup path already exists: {backup_path}")
            _backup_with_sqlite_cli(database, backup_path)
            backup_sha = _sha256(backup_path)
            with closing(_connect_readonly(backup_path, immutable=True)) as backup_connection:
                backup_quick = backup_connection.execute("PRAGMA quick_check").fetchone()[0]
                backup_prefix = _ledger_prefix_signature(backup_connection)
            if backup_quick != "ok" or backup_prefix["sha256"] != prefix_before["sha256"]:
                raise ValueError("backup integrity or old ledger prefix does not match pre-write state")
            if sha_before != _sha256(database):
                raise ValueError("database changed after backup and before writable store open")
            backup_info = {
                "path": str(backup_path),
                "sha256": backup_sha,
                "quick_check": backup_quick,
                "sqlite_cli_command": "sqlite3 <database> .backup <backup-file>",
            }

            store = ProjectStateStore(database)
            try:
                records = annotate_pd14_events(store)
                annotations_added = [
                    {
                        "annotation_id": record.entity_id,
                        "target_sequence": int(record.entity_id.rsplit("-", 1)[1]),
                        "ledger_event_id": record.event_id,
                    }
                    for record in records
                ]
            finally:
                store.close()

        sha_after = _sha256(database)
        with closing(_connect_readonly(database)) as connection:
            quick_after = connection.execute("PRAGMA quick_check").fetchone()[0]
            prefix_after = _ledger_prefix_signature(connection)
            state_after = _state_signature(connection)
            total_after, max_sequence_after = connection.execute(
                "SELECT COUNT(*), MAX(sequence) FROM ledger_events"
            ).fetchone()
            preexisting_ledger_after = _ledger_signature(connection, int(max_sequence_before))
            annotation_readback = _readback_annotations(connection)
            current_annotations = _annotation_ids(connection)
        if quick_after != "ok":
            raise ValueError(f"post-write quick_check failed: {quick_after}")
        if prefix_after["sha256"] != prefix_before["sha256"]:
            raise ValueError("old ledger event values 1-187 changed")
        if preexisting_ledger_after["sha256"] != preexisting_ledger_before["sha256"]:
            raise ValueError("one or more pre-existing ledger event values changed")
        if state_after["non_annotation_heads_sha256"] != state_before["non_annotation_heads_sha256"]:
            raise ValueError("a non-annotation entity head changed")
        if state_after["non_annotation_versions_sha256"] != state_before["non_annotation_versions_sha256"]:
            raise ValueError("a pre-existing non-annotation state version changed")
        if current_annotations != expected_annotation_ids:
            raise ValueError("not all six PD-14 annotations are persisted")
        if len(annotation_readback) != 6:
            raise ValueError("PD-14 annotation readback did not return six verified records")
        expected_delta = 6 - len(existing_annotations)
        if total_after != total_before + expected_delta:
            raise ValueError("ledger append count does not match the number of missing PD-14 annotations")
        if max_sequence_after != max_sequence_before + expected_delta:
            raise ValueError("ledger maximum sequence does not match the append count")
        if state_after["head_counts"].get("ProvenanceAnnotation", 0) != state_before["head_counts"].get("ProvenanceAnnotation", 0) + expected_delta:
            raise ValueError("annotation head count does not match the append count")
        if sha_before != sha_after and expected_delta == 0:
            raise ValueError("database changed during an idempotent no-op")

        operation_completed = datetime.now(timezone.utc).isoformat()
        receipt = {
            "schema_version": "wc4-pd14-authority-write-receipt-v1",
            "status": "PASS",
            "mode": "authority_write_after_sqlite_cli_backup" if is_authority else "disposable_database_write",
            "database_path": str(database),
            "authority_write": is_authority,
            "expected_sha256": args.expected_sha256.lower(),
            "database_sha256_before": sha_before,
            "database_sha256_after": sha_after,
            "operation_started_at_utc": operation_started,
            "operation_completed_at_utc": operation_completed,
            "backup": backup_info,
            "ledger_event_count_before": int(total_before),
            "ledger_event_count_after": int(total_after),
            "ledger_max_sequence_before": int(max_sequence_before),
            "ledger_max_sequence_after": int(max_sequence_after),
            "annotations_added": len(annotations_added),
            "annotations": annotation_readback,
            "old_event_prefix": {
                "sequence_range": [1, OLD_EVENT_PREFIX_END],
                "sha256_before": prefix_before["sha256"],
                "sha256_after": prefix_after["sha256"],
                "columns": prefix_before["columns"],
                "encoding": prefix_before["encoding"],
            },
            "preexisting_ledger": {
                "sequence_range": [1, int(max_sequence_before)],
                "sha256_before": preexisting_ledger_before["sha256"],
                "sha256_after": preexisting_ledger_after["sha256"],
                "columns": preexisting_ledger_before["columns"],
                "encoding": "typed SQLite values; TEXT encoded as exact UTF-8 bytes represented in hex",
            },
            "non_annotation_state": {
                "heads_sha256_before": state_before["non_annotation_heads_sha256"],
                "heads_sha256_after": state_after["non_annotation_heads_sha256"],
                "versions_sha256_before": state_before["non_annotation_versions_sha256"],
                "versions_sha256_after": state_after["non_annotation_versions_sha256"],
                "protected_head_rows_before": state_before["protected_head_rows"],
                "protected_head_rows_after": state_after["protected_head_rows"],
            },
            "forbidden_state_changes": {
                "human_decision_created": False,
                "constraint_changed": False,
                "study_area_changed": False,
                "dataset_snapshot_created": False,
            },
            "source_requests": 0,
            "provider_messages": 0,
        }
        _write_json_no_overwrite(receipt_path, receipt)
        print(json.dumps({"status": "PASS", "database_sha256_after": sha_after, "ledger_event_count_after": total_after, "annotations_added": len(annotations_added), "receipt": str(receipt_path)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
