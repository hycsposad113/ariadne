"""Week 7's globally registered plugin must leave other tests' RO backup alone."""
import sqlite3

from urban_design.week7.service import AUTHORITY_DATABASE

pytest_plugins = ["tests.week7_support"]


def test_non_week7_can_backup_authority_database_readonly(tmp_path):
    destination = tmp_path / "readonly-backup.sqlite3"
    with sqlite3.connect(AUTHORITY_DATABASE.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(destination) as backup:
            source.backup(backup)
            assert backup.execute("PRAGMA quick_check").fetchone() == ("ok",)
    assert destination.is_file()
