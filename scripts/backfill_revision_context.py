#!/usr/bin/env python3
"""Add an immutable proposal context artifact to one retained revision directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from urban_design.judgement.core import Registry, canonical
from urban_design.judgement.proposal_service import build_revision_context


def _read_only_database(path):
    resolved = Path(path).expanduser().resolve(strict=True)
    connection = sqlite3.connect(resolved.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _load_records(proposal_id, proposals_db, judgements_db):
    with _read_only_database(proposals_db) as db:
        row = db.execute('SELECT project, payload FROM proposals WHERE id=?', (proposal_id,)).fetchone()
    if row is None:
        raise ValueError('proposal not found: ' + proposal_id)
    proposal = json.loads(row['payload'])
    project = row['project']
    if proposal.get('id') != proposal_id or proposal.get('project_id') != project:
        raise ValueError('proposal record identity mismatch')

    card_id = proposal.get('card_id')
    with _read_only_database(judgements_db) as db:
        row = db.execute('SELECT payload FROM judgement_runs WHERE project=? AND id=?',
                         (project, card_id)).fetchone()
        if row is None:
            raise ValueError('judgement card not found: ' + str(card_id))
        card = json.loads(row['payload'])
        table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='judgement_responses'").fetchone()
        if table:
            card['responses'] = [json.loads(item['payload']) for item in db.execute(
                'SELECT payload FROM judgement_responses WHERE project=? AND run_id=? ORDER BY rowid',
                (project, card_id))]
        else:
            card['responses'] = []
    return project, proposal, card


def backfill_revision_context(proposal_id, proposals_db, judgements_db, revision_root):
    if not proposal_id or proposal_id in {'.', '..'} or Path(proposal_id).name != proposal_id:
        raise ValueError('proposal id must be a single path component')
    project, proposal, card = _load_records(proposal_id, proposals_db, judgements_db)

    revision_root = Path(revision_root).expanduser().resolve(strict=True)
    revision_dir = (revision_root / proposal_id).resolve()
    if not revision_dir.is_relative_to(revision_root):
        raise ValueError('revision directory escapes revision root')
    manifest_path = revision_dir / 'manifest.json'
    backup_path = revision_dir / 'manifest.pre-context.json'
    context_path = revision_dir / 'revision-context.json'
    staged_manifest_path = revision_dir / 'manifest.next.json'
    if not manifest_path.is_file():
        raise ValueError('revision manifest not found')
    if backup_path.exists() or context_path.exists() or staged_manifest_path.exists():
        raise ValueError('revision context backfill already started or already present')

    old_manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(old_manifest_bytes)
    if manifest.get('proposal_id') != proposal_id or manifest.get('project_id') != project:
        raise ValueError('revision manifest proposal or project mismatch')
    expected_subject = 'harbour_grain@draft-r' + str(manifest.get('draft_revision'))
    if manifest.get('subject_id') != expected_subject:
        raise ValueError('revision manifest draft subject mismatch')
    outputs = manifest.get('outputs')
    if not isinstance(outputs, list) or any(item.get('path') == 'revision-context.json' for item in outputs):
        raise ValueError('revision manifest outputs are invalid or already list revision-context.json')

    context = build_revision_context(proposal, card, Registry())
    context_bytes = (canonical(context) + '\n').encode('utf-8')
    with context_path.open('xb') as stream:
        stream.write(context_bytes)

    updated_manifest = dict(manifest)
    updated_manifest['outputs'] = [*outputs, {
        'path': 'revision-context.json',
        'sha256': hashlib.sha256(context_bytes).hexdigest(),
    }]
    with staged_manifest_path.open('xb') as stream:
        stream.write((canonical(updated_manifest) + '\n').encode('utf-8'))

    manifest_path.rename(backup_path)
    os.replace(staged_manifest_path, manifest_path)
    return context_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proposal-id', required=True)
    parser.add_argument('--proposals-db', required=True)
    parser.add_argument('--judgements-db', required=True)
    parser.add_argument('--revision-root', required=True,
                        help='parent directory containing one subdirectory per proposal id')
    args = parser.parse_args(argv)
    try:
        context_path = backfill_revision_context(args.proposal_id, args.proposals_db,
                                                args.judgements_db, args.revision_root)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f'ERROR: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    print(f'WROTE: {context_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
