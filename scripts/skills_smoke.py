#!/usr/bin/env python3
"""Commander-only S8 smoke: SQLite backup to /private/tmp, never write source DB.

Run outside the executor sandbox. A single job never retries unknown delivery.
Without PROJECT_AI_AUTHORIZED=1 this verifies only NON_AI_TEMPLATE.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from urban_design.skills.contracts import RunRequest
from urban_design.skills.runner import SkillRunner
from urban_design.store import ProjectStateStore


def backup_database(source: Path, target: Path):
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as origin:
        before = origin.execute('SELECT count(*), max(sequence) FROM ledger_events').fetchone()
        with sqlite3.connect(target) as destination:
            origin.backup(destination)
    return before


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', required=True, type=Path)
    parser.add_argument('--scenario-id', required=True)
    parser.add_argument('--conditions-json', default='null', help='Local applicability conditions; no measurements')
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='j13-skills-smoke-', dir='/private/tmp')) / '.urban_design_runtime'
    root.mkdir()
    target = root / 'state.sqlite3'
    before = backup_database(args.source_db, target)
    store = ProjectStateStore(target)
    try:
        runner = SkillRunner(store)
        job, _ = runner.submit(args.scenario_id, 'S8', RunRequest(
            idempotency_key='commander-smoke-' + uuid4().hex, conditions=json.loads(args.conditions_json)))
        runner.execute(job['run_id'])
        result = runner.get(args.scenario_id, 'S8', job['run_id'])
        print(json.dumps({'copy_database': str(target), 'result': result}, ensure_ascii=False, indent=2))
    finally:
        store.close()
        with sqlite3.connect(args.source_db.resolve().as_uri() + '?mode=ro', uri=True) as origin:
            after = origin.execute('SELECT count(*), max(sequence) FROM ledger_events').fetchone()
        print(json.dumps({'source_ledger_before': before, 'source_ledger_after': after, 'unchanged': before == after}))
        if before != after:
            raise RuntimeError('formal ledger changed during smoke; stop and reconcile')
    return 0 if result['status'] in {'VALIDATED_DRAFT', 'NON_AI_TEMPLATE'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
