import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'backfill_revision_context.py'


def load_backfill_script():
    assert SCRIPT_PATH.is_file(), 'backfill_revision_context.py has not been implemented'
    spec = importlib.util.spec_from_file_location('backfill_revision_context', SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_writes_context_and_preserves_old_manifest_in_tmp(tmp_path):
    module = load_backfill_script()
    proposal_id = 'proposal-backfill-test'
    proposal = {
        'id': proposal_id, 'project_id': 'project-test', 'card_id': 'card-before',
        'proposal': {'summary': '測試降低南側量體。', 'operations': [
            {'op': 'REMOVE_TOP_FLOOR', 'building_ids': ['new-7', 'new-8'], 'floors': 1},
            {'op': 'RERUN', 'analyses': ['E1']},
        ]},
        'dry_run': {'gfa_before_m2': 130000, 'gfa_after_m2': 125000,
                    'affected_building_ids': ['new-7', 'new-8'],
                    'solar_access_check': {'courtyards': [], 'warning': False}},
    }
    proposals_db = tmp_path / 'proposals.sqlite3'
    with sqlite3.connect(proposals_db) as db:
        db.execute('CREATE TABLE proposals (id TEXT, project TEXT, input_hash TEXT, payload TEXT)')
        db.execute('INSERT INTO proposals VALUES (?,?,?,?)',
                   (proposal_id, 'project-test', 'input-hash', json.dumps(proposal, ensure_ascii=False)))

    metrics = {
        'e1.harbour.courtyard.winter.mean_h': {'value': 0.108},
        'e1.harbour.all.winter.mean_h': {'value': 1.79},
        'e1.harbour.all.winter.ge2h_pct': {'value': 12.5},
        'e1.harbour.street.winter.mean_h': {'value': 1.8},
        'utci.harbour.all.very_strong_pct': {'value': 14.2},
    }
    judgements_db = tmp_path / 'judgements.sqlite3'
    with sqlite3.connect(judgements_db) as db:
        db.execute('CREATE TABLE judgement_runs (id TEXT, project TEXT, skill TEXT, input_hash TEXT, payload TEXT)')
        db.execute('INSERT INTO judgement_runs VALUES (?,?,?,?,?)',
                   ('card-before', 'project-test', 'J-CLIMATE', 'judgement-hash', json.dumps({
                       'id': 'card-before', 'round': 4, 'skill_id': 'J-CLIMATE', 'metrics': metrics,
                   })))
        db.execute('CREATE TABLE judgement_responses (id TEXT, run_id TEXT, project TEXT, payload TEXT)')
        response = {'id': 'response-before', 'kind': 'contest', 'text': '冬季日照仍需改善。'}
        db.execute('INSERT INTO judgement_responses VALUES (?,?,?,?)',
                   ('response-before', 'card-before', 'project-test', json.dumps(response, ensure_ascii=False)))

    revision_root = tmp_path / 'revisions'
    revision_dir = revision_root / proposal_id
    revision_dir.mkdir(parents=True)
    buildings_path = revision_dir / 'buildings.json'
    buildings_path.write_text('{"editable_buildings":[]}')
    buildings_hash = hashlib.sha256(buildings_path.read_bytes()).hexdigest()
    old_manifest_bytes = json.dumps({
        'proposal_id': proposal_id, 'project_id': 'project-test',
        'draft_id': 'draft-test', 'draft_revision': 5,
        'subject_id': 'harbour_grain@draft-r5', 'analyses': ['E1'],
        'outputs': [{'path': 'buildings.json', 'sha256': buildings_hash}],
    }, ensure_ascii=False).encode()
    (revision_dir / 'manifest.json').write_bytes(old_manifest_bytes)

    assert module.main([
        '--proposal-id', proposal_id,
        '--proposals-db', str(proposals_db),
        '--judgements-db', str(judgements_db),
        '--revision-root', str(revision_root),
    ]) == 0

    backup = revision_dir / 'manifest.pre-context.json'
    context_path = revision_dir / 'revision-context.json'
    context = json.loads(context_path.read_text())
    new_manifest = json.loads((revision_dir / 'manifest.json').read_text())
    assert backup.read_bytes() == old_manifest_bytes
    assert context['card_id'] == 'card-before' and context['card_round'] == 4
    assert {'id': 'response-before', 'kind': 'contest', 'text': '冬季日照仍需改善。'} in context['designer_responses']
    assert any(item['id'] == 'seed-courtyard_role' for item in context['designer_responses'])
    assert [item for item in new_manifest['outputs'] if item['path'] != 'revision-context.json'] == [
        {'path': 'buildings.json', 'sha256': buildings_hash}]
    context_output = next(item for item in new_manifest['outputs'] if item['path'] == 'revision-context.json')
    assert context_output['sha256'] == hashlib.sha256(context_path.read_bytes()).hexdigest()
