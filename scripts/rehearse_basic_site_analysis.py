"""Run basic site analysis via TestClient on an existing /private/tmp SQLite backup.

No service binding, network request, HumanDecision or formal-state mutation.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import time
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.site_intelligence.basic_analysis import create_basic_analysis_router
from urban_design.site_extents import utc, digest, encoded, save
from urban_design.store import ProjectStateStore

AUTHORITY = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')

def ledger(path):
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as connection:
        count, sequence = connection.execute('SELECT count(*),max(sequence) FROM ledger_events').fetchone()
        return {'count': count, 'max_sequence': sequence}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--syntax-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_bytes())
    backup = Path(receipt['backup']).resolve()
    if not backup.is_relative_to(Path('/private/tmp')):
        raise ValueError('only /private/tmp DB backups may be opened as a store')
    args.output.mkdir(parents=True, exist_ok=False)
    before = ledger(AUTHORITY)
    started_at = utc()
    started = time.perf_counter()
    print(f'{utc()} analysis started; copy={backup}; formal={before}', flush=True)
    with ProjectStateStore(backup) as store:
        copy_before = ledger(backup)
        app = FastAPI()
        app.include_router(create_basic_analysis_router(store, syntax_root=args.syntax_root,
            syntax_hash=digest((args.syntax_root / 'manifest.json').read_bytes()).removeprefix('sha256:')))
        with TestClient(app) as client:
            response = client.get('/api/v1/projects/rotterdam-m4h-pilot-project/site-analysis/basic', params={'extent_id': receipt['result']['extent_id']})
        result = response.json()
        save(args.output / 'api-result.json', encoded(result))
        audit = {'started_at': started_at, 'finished_at': utc(), 'status_code': response.status_code,
            'source_receipt': str(args.receipt), 'source_receipt_sha256': digest(args.receipt.read_bytes()),
            'result_sha256': digest((args.output / 'api-result.json').read_bytes()), 'backup': str(backup),
            'formal_ledger_before': before, 'formal_ledger_after': ledger(AUTHORITY), 'copy_ledger_before': copy_before,
            'copy_ledger_after': ledger(backup), 'elapsed_s': round(time.perf_counter()-started, 3)}
        save(args.output / 'audit.json', encoded(audit))
        if response.status_code == 200:
            save(args.output / 'overlay.geojson', encoded(result['overlay_wgs84']))
            for side in result['transit']:
                print(side['side'], {mode: None if value is None else (value['name'], value['distance_m']) for mode, value in side['nearest_by_mode'].items()}, flush=True)
            for side in result['landuse']:
                print(side['side'], side['bag_usage_percent'], side['osm_ring_area_percent'], flush=True)
            print('top entrances', [(entry['id'],entry['side'],entry['distance_potential']) for entry in result['entrances'][:5]], flush=True)
        print(json.dumps(audit), flush=True)
        if audit['formal_ledger_after'] != before or audit['copy_ledger_after'] != copy_before:
            raise RuntimeError('STOP: analysis changed ledger')
        if response.status_code != 200:
            raise RuntimeError(f'analysis incomplete: HTTP {response.status_code}: {result}')
