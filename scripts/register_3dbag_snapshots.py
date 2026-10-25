#!/usr/bin/env python3
"""Verify a local 3D BAG manifest and append its records to a DB copy by default.

The authority database is opened read-only, copied with SQLite's backup API,
then the registration is appended only to that copy. Direct authority writes
require ``--write-authority`` and its exact ``--expected-sha256``.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Sequence
from uuid import uuid4

from urban_design.store import EntityNotFoundError, ProjectStateStore
from urban_design.three_d_bag import (
    append_snapshot_registration_to_store,
    build_snapshot_registration_bundle,
)

try:
    from .persist_analysis_results import (
        AUTHORITY_DB,
        _database_signature,
        _verify_write_invariants,
        backup_database_readonly,
        sha256_file,
    )
except ImportError:  # Direct ``python scripts/register_3dbag_snapshots.py`` execution.
    from persist_analysis_results import (
        AUTHORITY_DB,
        _database_signature,
        _verify_write_invariants,
        backup_database_readonly,
        sha256_file,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "config/3dbag-height-source-manifest-v1.json"


def _append_idempotent(store: ProjectStateStore, bundle: object, backup_path: Path, backup_sha: str) -> dict[str, object]:
    artifacts = []
    snapshots = []
    for item in bundle.artifacts:
        try:
            existing = store.current(item.id)
        except EntityNotFoundError:
            artifacts.append(item)
        else:
            if existing.entity_type != "Artifact" or existing.payload != item.model_dump(mode="json"):
                raise ValueError(f"existing 3D BAG Artifact {item.id} differs from the verified manifest")
    for item in bundle.dataset_snapshots:
        try:
            existing = store.current(item.id)
        except EntityNotFoundError:
            snapshots.append(item)
        else:
            if existing.entity_type != "DatasetSnapshot" or existing.payload != item.model_dump(mode="json"):
                raise ValueError(f"existing 3D BAG DatasetSnapshot {item.id} differs from the verified manifest")
    if artifacts or snapshots:
        state_records, events = append_snapshot_registration_to_store(
            store,
            replace(bundle, artifacts=tuple(artifacts), dataset_snapshots=tuple(snapshots)),
            backup_path=backup_path,
            expected_backup_sha256=f"sha256:{backup_sha.removeprefix('sha256:')}",
        )
    else:
        state_records, events = [], []
    return {
        "write_status": "APPENDED" if state_records else "ALREADY_PRESENT",
        "state_record_ids": [item.entity_id for item in state_records],
        "ledger_event_ids": [item.event_id for item in events],
        "dataset_snapshot_ids": [item.id for item in bundle.dataset_snapshots],
        "artifact_ids": [item.id for item in bundle.artifacts],
        "idempotent_existing_count": len(bundle.artifacts) + len(bundle.dataset_snapshots) - len(state_records),
        "human_decision_count_created": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--database", type=Path, default=AUTHORITY_DB, help="Read-only source DB; default is the designated authority DB.")
    parser.add_argument("--copy-out", type=Path, help="Retain a new dry-run SQLite copy here; default uses the authority-dryrun output directory.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--write-authority", action="store_true", help="Append directly to the designated authority DB after backup and exact hash check.")
    modes.add_argument("--write-copy", action="store_true", help="Explicitly append to the supplied non-authority DB in place.")
    parser.add_argument("--expected-sha256", help="Required current file SHA-256 for --write-authority or --write-copy.")
    parser.add_argument("--backup-out", type=Path, help="Optional non-overwriting pre-write backup path.")
    parser.add_argument("--output", type=Path, help="Optional non-overwriting JSON registration receipt.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.write_authority or args.write_copy) and not args.expected_sha256:
        requirement = (
            "--write-authority requires --expected-sha256"
            if args.write_authority
            else "--write-copy requires --expected-sha256"
        )
        parser.error(requirement)
    if not (args.write_authority or args.write_copy) and args.expected_sha256:
        parser.error("--expected-sha256 is only valid with an explicit write mode")

    source = args.database.expanduser().resolve()
    if args.write_authority and source != AUTHORITY_DB:
        parser.error("--write-authority is limited to the designated authority database")
    if args.write_copy and source == AUTHORITY_DB:
        parser.error("--write-copy refuses the designated authority database; use --write-authority")
    if not source.is_file():
        raise FileNotFoundError(f"database does not exist: {source}")
    source_sha_before = sha256_file(source)
    if (args.write_authority or args.write_copy) and source_sha_before != args.expected_sha256:
        raise ValueError("database SHA-256 does not match --expected-sha256")

    bundle = build_snapshot_registration_bundle(args.manifest.expanduser().resolve())
    mode_authority = bool(args.write_authority)
    if args.write_authority or args.write_copy:
        target = source
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if args.copy_out is None:
            out_dir = Path.home() / ".local/share/urban-design-data/authority-dryrun" / f"3dbag-{timestamp}-{uuid4().hex[:8]}"
            out_dir.mkdir(parents=True, exist_ok=False)
            target = out_dir / "state-copy.sqlite3"
        else:
            target = args.copy_out.expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
        backup_database_readonly(source, target)

    if args.write_authority or args.write_copy:
        current = _database_signature(source)
        if current["quick_check"] != "ok" or current["integrity_check"] != "ok":
            raise RuntimeError("database failed pre-write integrity checks")
        if args.write_copy and target == AUTHORITY_DB:
            raise ValueError("copy write mode resolved to the protected authority DB")
        if args.backup_out:
            backup = args.backup_out.expanduser().resolve()
        else:
            backup = target.with_name(target.stem + ".prewrite-backup.sqlite3")
        backup_database_readonly(target, backup)
        backup_sha = sha256_file(backup)
        if sha256_file(target) != args.expected_sha256:
            raise RuntimeError("database changed after expected SHA-256 validation and backup")
        before = _database_signature(target)
        with ProjectStateStore(target) as store:
            result = _append_idempotent(store, bundle, backup, backup_sha)
        after = _database_signature(target, event_columns=before["stable_event_columns"], event_through_sequence=before["ledger_max_sequence"])
        _verify_write_invariants(before, after)
        result.update({
            "mode": "authority_write" if mode_authority else "explicit_copy_write",
            "database_path": str(target),
            "database_sha256_before": source_sha_before,
            "database_sha256_after": sha256_file(target),
            "prewrite_backup_path": str(backup),
            "prewrite_backup_sha256": backup_sha,
            "ledger_event_count_before": before["ledger_event_count"],
            "ledger_event_count_after": after["ledger_event_count"],
            "ledger_prefix_sha256_before": before["ledger_event_prefix_sha256"],
            "ledger_prefix_sha256_after": after["ledger_event_prefix_sha256"],
        })
    else:
        before = _database_signature(source)
        backup = target.with_name(target.stem + ".prewrite-backup.sqlite3")
        backup_database_readonly(target, backup)
        backup_sha = sha256_file(backup)
        with ProjectStateStore(target) as store:
            result = _append_idempotent(store, bundle, backup, backup_sha)
        after = _database_signature(target, event_columns=before["stable_event_columns"], event_through_sequence=before["ledger_max_sequence"])
        _verify_write_invariants(before, after)
        source_sha_after = sha256_file(source)
        if source_sha_after != source_sha_before:
            raise RuntimeError("default 3D BAG dry-run changed its source database")
        result.update({
            "mode": "dry_run_disposable_copy",
            "source_database_sha256_before": source_sha_before,
            "source_database_sha256_after": source_sha_after,
            "database_path": str(target),
            "database_sha256_after": sha256_file(target),
            "prewrite_backup_path": str(backup),
            "prewrite_backup_sha256": backup_sha,
            "ledger_event_count_before": before["ledger_event_count"],
            "ledger_event_count_after": after["ledger_event_count"],
            "ledger_prefix_sha256_before": before["ledger_event_prefix_sha256"],
            "ledger_prefix_sha256_after": after["ledger_event_prefix_sha256"],
        })

    result["manifest_sha256"] = bundle.manifest_sha256
    result["project_id"] = bundle.project_id
    if args.output:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        result["receipt_path"] = str(output)
        result["receipt_sha256"] = sha256_file(output)
    else:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
