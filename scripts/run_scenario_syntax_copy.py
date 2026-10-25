"""Run J10 against an explicitly supplied disposable DB, via in-process API."""
import argparse
import json
from pathlib import Path
import subprocess
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from urban_design.scenario_syntax_api import create_scenario_syntax_router
from urban_design.store import ProjectStateStore

parser = argparse.ArgumentParser()
parser.add_argument('--database', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
if not str(args.database.resolve()).startswith('/private/tmp/'):
    raise ValueError('This rehearsal requires a disposable /private/tmp database')
args.output.mkdir(parents=True, exist_ok=True)
store = ProjectStateStore(args.database)
app = FastAPI(); app.include_router(create_scenario_syntax_router(store, args.output / 'results'))
records = []
with TestClient(app) as client:
    for row in store.list_current('Scenario'):
        for mode in ('pedestrian','bicycle'):
            start = subprocess.check_output(['date','-u','+%Y-%m-%dT%H:%M:%SZ'],text=True).strip()
            clock = time.perf_counter()
            response = client.post(f'/api/v1/scenarios/{row.entity_id}/syntax', json={'mode':mode})
            print(row.entity_id, mode, response.status_code, flush=True)
            if response.status_code != 202:
                records.append({'scenario': row.entity_id, 'mode':mode,'http_status':response.status_code,'error':response.json()});print(response.json(),flush=True);continue
            job = response.json()['job_id']
            result = client.get(f'/api/v1/scenarios/{row.entity_id}/syntax', params={'mode':mode,'job_id':job})
            payload = result.json()
            filename = args.output / f'{row.entity_id}-{mode}.json'
            filename.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
            receipt = {'scenario': row.entity_id, 'mode':mode,'start_utc':start, 'elapsed_seconds':time.perf_counter()-clock,
                       'status':payload.get('status'),'error':payload.get('error'),
                       'before':(payload.get('before') or {}).get('metrics'), 'after':(payload.get('after') or {}).get('metrics'),
                       'connections':len(payload.get('merge',{}).get('connection_points',[])), 'output':str(filename)}
            records.append(receipt);print(json.dumps(receipt),flush=True)
            (args.output/'summary.json').write_text(json.dumps(records,indent=2))

(args.output/'summary.json').write_text(json.dumps(records,indent=2))
