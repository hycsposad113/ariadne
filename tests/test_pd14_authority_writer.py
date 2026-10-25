from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

import scripts.annotate_pd14_ledger as writer


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pd14_writer_requires_expected_hash_before_any_write(tmp_path: Path) -> None:
    database = tmp_path / "nonexistent.sqlite3"
    backup_dir = tmp_path / "backups"

    with pytest.raises(SystemExit) as exc:
        writer.main(
            ["--database", str(database), "--backup-dir", str(backup_dir)]
        )

    assert exc.value.code == 2
    assert not database.exists()
    assert not backup_dir.exists()
    assert not (tmp_path / "receipt.json").exists()


def test_pd14_writer_rejects_stale_hash_without_backup_or_mutation(
    pd14_pre_annotation_db: Path, tmp_path: Path
) -> None:
    database = pd14_pre_annotation_db
    before = _sha(database)
    backup_dir = tmp_path / "backups"
    receipt = tmp_path / "receipt.json"

    result = writer.main(
        [
            "--database", str(database),
            "--expected-sha256", "0" * 64,
            "--backup-dir", str(backup_dir),
            "--receipt-out", str(receipt),
        ]
    )

    assert result == 1
    assert _sha(database) == before
    assert not backup_dir.exists()
    assert not receipt.exists()


def test_pd14_writer_refuses_authority_path_without_explicit_write_flag(
    pd14_pre_annotation_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = pd14_pre_annotation_db
    monkeypatch.setattr(writer, "AUTHORITY_DATABASE", database.resolve(), raising=False)
    before = _sha(database)
    receipt = tmp_path / "receipt.json"

    result = writer.main(
        [
            "--database", str(database),
            "--expected-sha256", before,
            "--backup-dir", str(tmp_path / "backups"),
            "--receipt-out", str(receipt),
        ]
    )

    assert result == 1
    assert _sha(database) == before
    assert not (tmp_path / "backups").exists()
    assert not receipt.exists()


def test_pd14_writer_refuses_write_flag_for_non_authority_path(
    pd14_pre_annotation_db: Path, tmp_path: Path,
) -> None:
    database = pd14_pre_annotation_db
    before = _sha(database)
    receipt = tmp_path / "receipt.json"

    result = writer.main(
        [
            "--database", str(database),
            "--expected-sha256", before,
            "--write-authority",
            "--backup-dir", str(tmp_path / "backups"),
            "--receipt-out", str(receipt),
        ]
    )

    assert result == 1
    assert _sha(database) == before
    assert not (tmp_path / "backups").exists()
    assert not receipt.exists()


def test_pd14_writer_appends_six_annotations_to_a_disposable_copy(
    pd14_pre_annotation_db: Path, tmp_path: Path,
) -> None:
    database = pd14_pre_annotation_db
    before = _sha(database)
    backup_dir = tmp_path / "backups"
    receipt_path = tmp_path / "receipt.json"

    result = writer.main(
        [
            "--database", str(database),
            "--expected-sha256", before,
            "--backup-dir", str(backup_dir),
            "--receipt-out", str(receipt_path),
        ]
    )

    assert result == 0
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "PASS"
    assert receipt["annotations_added"] == 6
    assert receipt["old_event_prefix"]["sha256_before"] == receipt["old_event_prefix"]["sha256_after"]
    assert receipt["preexisting_ledger"]["sha256_before"] == receipt["preexisting_ledger"]["sha256_after"]
    assert receipt["preexisting_ledger"]["sequence_range"] == [1, receipt["ledger_event_count_before"]]
    assert receipt["ledger_event_count_after"] == receipt["ledger_event_count_before"] + 6
    assert Path(receipt["backup"]["path"]).is_file()
    assert _sha(Path(receipt["backup"]["path"])) == receipt["backup"]["sha256"]
    assert [item["target_sequence"] for item in receipt["annotations"]] == list(range(182, 188))

    with sqlite3.connect(database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM state_heads WHERE entity_type='ProvenanceAnnotation'"
        ).fetchone()[0] == 6
        assert conn.execute(
            "SELECT COUNT(*) FROM ledger_events"
        ).fetchone()[0] == receipt["ledger_event_count_before"] + 6

    after_first_write = _sha(database)
    replay_receipt = tmp_path / "receipt-replay.json"
    replay_result = writer.main(
        [
            "--database", str(database),
            "--expected-sha256", after_first_write,
            "--backup-dir", str(backup_dir),
            "--receipt-out", str(replay_receipt),
        ]
    )
    replay = json.loads(replay_receipt.read_text())
    assert replay_result == 0
    assert replay["status"] == "PASS"
    assert replay["annotations_added"] == 0
    assert _sha(database) == after_first_write
