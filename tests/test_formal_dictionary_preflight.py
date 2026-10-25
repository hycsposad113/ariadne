"""Formal entry point must fail closed before invoking fixture generation."""
import importlib.util
from pathlib import Path

import pytest

from urban_design.store import ProjectStateStore

spec = importlib.util.spec_from_file_location('formal_entry', Path(__file__).parents[1] / 'scripts/run_formal_dictionary_generation.py')
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def test_blocked_inputs_leave_database_unchanged(tmp_path):
    database = tmp_path / 'state.sqlite3'
    with ProjectStateStore(database) as store:
        store.create_project({'id': 'p', 'name': 'synthetic'}, project_id='p')
    before = database.read_bytes()
    result = entry.preflight(database)
    assert result['status'] == 'BLOCKED'
    assert result['readiness']['status'] == 'BLOCKED'
    assert result['scenario_ids'] == []
    assert result['candidate_generation_status'] == 'NOT_RUN'
    assert result['readiness']['context'] is None
    assert database.read_bytes() == before
    with ProjectStateStore(database, read_only=True) as store:
        assert store.list_current('HumanDecision') == []
        assert store.list_current('Scenario') == []


def test_runtime_path_and_symlink_rejected_before_store_open(tmp_path):
    runtime = tmp_path / '.urban_design_runtime'
    runtime.mkdir()
    database = runtime / 'state.sqlite3'
    database.write_bytes(b'not a database')
    alias = tmp_path / 'copy.sqlite3'
    alias.symlink_to(database)
    for path in (database, alias):
        with pytest.raises(ValueError, match='runtime databases are prohibited'):
            entry.preflight(path)


def test_report_preserves_blockers_and_never_overwrites(tmp_path):
    result = dict(blockers=['unknown retained GFA'], status='BLOCKED')
    output = tmp_path / 'report'
    entry.write_report(result, output)
    assert 'unknown retained GFA' in (output / 'report.json').read_text()
    assert 'BLOCKED' in (output / 'report.md').read_text()
    with pytest.raises(FileExistsError):
        entry.write_report(result, output)
