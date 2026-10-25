"""Offline replay of a retained extent-fetch receipt on another /private/tmp DB backup.

No HTTP is sent. Only hash-verified prior response bytes may satisfy requests.
Original retrieval times and frozen-parent hashes are carried into the manifest.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import time
from urllib.error import HTTPError
from urban_design.site_extents import ExtentService, ExtentRequest, Response, utc, digest, encoded, save, PLANS, public_transport
from urban_design.extent_export import verified_manifest, export_geopackage
from urban_design.generation.job_store import GenerationJobStore
from urban_design.store import ProjectStateStore

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--public-planning', action='store_true', help='Supplement frozen replay with public PDOK WMS only; never resend OSM/BAG/3DBAG')
    args = parser.parse_args()
    live_requests = []
    parent = json.loads(args.receipt.read_bytes())
    manifest_path = Path(parent['result']['manifest_path'])
    manifest = verified_manifest(manifest_path)
    frozen_hash = digest(manifest_path.read_bytes())
    artifacts = {item['url']: item for source in manifest['sources'] for item in source['artifacts']}
    errors = {attempt['url']: attempt for source in manifest['sources'] for attempt in source.get('requests', []) if attempt['status'] == 'REQUEST_FAILED'}
    def frozen_transport(url, *, method='GET', data=None, max_bytes=200_000_000):
        if args.public_planning and url.startswith(PLANS + '?'):
            live_requests.append({'url': url, 'time': utc(), 'method': method})
            return public_transport(url, method=method, data=data, max_bytes=max_bytes)
        if url in errors:
            raise HTTPError(url, 404, 'retained original HTTP 404; offline replay, no request sent', {}, None)
        item = artifacts[url]
        if method == 'POST':
            from urllib.parse import parse_qs
            if parse_qs(data.decode()).get('data') != [item['query']]:
                raise ValueError('frozen query differs; old response cannot establish new acquisition scope')
        body = Path(item['path']).read_bytes()
        if digest(body) != item['sha256'] or len(body) != item['bytes']:
            raise ValueError('frozen response changed')
        if len(body) > max_bytes:
            raise ValueError('DEFERRED_SIZE')
        return Response(b'' if method == 'HEAD' else body, {'content-length': str(len(body)),
            'x-q5-original-retrieved-at': item['time'], 'x-q5-frozen-parent-sha256': frozen_hash})
    stamp = utc().replace(':', '').replace('-', '')
    root = Path('/private/tmp') / ('j9-extent-reconciled-' + stamp)
    root.mkdir(exist_ok=False)
    backup = root / 'copy.sqlite3'
    with sqlite3.connect('file:' + parent['backup'] + '?mode=ro', uri=True) as source:
        with sqlite3.connect(backup) as target:
            source.backup(target)
    # Read the already-dispatched request; operational DB is an existing local copy.
    old_jobs = GenerationJobStore(Path(parent['backup']).parent / 'extent-jobs/jobs.sqlite3')
    prior_job = old_jobs.get(parent['result']['job_id'])
    started = time.perf_counter()
    print(f'{utc()} offline frozen replay parent={frozen_hash}', flush=True)
    with ProjectStateStore(backup) as store:
        service = ExtentService(store, transport=frozen_transport)
        job = service.create(manifest['project_id'], ExtentRequest(geometry=prior_job.request['geometry_wgs84'], idempotency_key='reconcile-' + stamp))
        result = service.run(job['job_id'])
        export = export_geopackage(Path(result['manifest_path']), root / 'extent.gpkg')
        for source in result['sources']:
            print(f'{source["name"]}: {source["status"]} count={source.get("count")} bytes={source.get("bytes")} elapsed={source.get("elapsed_s")} error={source.get("error")}', flush=True)
    receipt = {'task_id': 'j9-dl-map', 'mode': 'FROZEN_RECONCILIATION_WITH_PLANNING_SUPPLEMENT' if args.public_planning else 'OFFLINE_FROZEN_RECONCILIATION', 'live_http_requests': len(live_requests), 'live_requests': live_requests,
        'source_receipt': str(args.receipt), 'source_receipt_sha256': digest(args.receipt.read_bytes()),
        'frozen_manifest_sha256': frozen_hash, 'result': result, 'export': export,
        'comparison': parent.get('comparison'), 'backup': str(backup), 'elapsed_s': time.perf_counter() - started, 'finished_at': utc()}
    save(root / 'receipt.json', encoded(receipt))
    print(f'receipt={root / "receipt.json"}', flush=True)
