"""One approved M4H data fetch on a SQLite backup under /private/tmp.

Never opens authority through ProjectStateStore; never reads decision secrets.
"""
import json
from pathlib import Path
import sqlite3
import time
from shapely.geometry import box, mapping, shape
from shapely.ops import transform
from pyproj import Transformer
from urban_design.site_extents import ExtentService, ExtentRequest, utc, encoded, save, digest
from urban_design.store import ProjectStateStore
from urban_design.extent_export import export_geopackage

AUTHORITY = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')

def ledger(connection):
    count, maximum = connection.execute('SELECT count(*),max(sequence) FROM ledger_events').fetchone()
    return {'count': count, 'max_sequence': maximum}

if __name__ == '__main__':
    stamp = utc().replace(':', '').replace('-', '')
    root = Path('/private/tmp') / ('j9-extent-live-' + stamp)
    root.mkdir(exist_ok=False)
    backup = root / 'copy.sqlite3'
    with sqlite3.connect('file:' + str(AUTHORITY) + '?mode=ro', uri=True) as source:
        before = ledger(source)
        with sqlite3.connect(backup) as target:
            source.backup(target)
    print(f'{utc()} backup={backup} authority={before}', flush=True)
    started = time.perf_counter()
    receipt = {'task_id': 'j9-dl-map', 'started_at': utc(), 'backup': str(backup), 'ledger_before': before}
    try:
        with ProjectStateStore(backup) as store:
            project = store.current('rotterdam-m4h-pilot-project')
            study = store.current(project.payload['active_study_area_id'])
            artifact = store.current(study.payload['geometry_artifact_id'])
            study_path = Path(artifact.payload['uri'])
            if digest(study_path.read_bytes()) != artifact.payload['sha256']:
                raise ValueError('StudyArea artifact hash mismatch')
            doc = json.loads(study_path.read_bytes())
            geometry = shape(doc['geometry'] if doc.get('type') == 'Feature' else doc)
            extent = box(*geometry.buffer(50).bounds)
            wgs = transform(Transformer.from_crs(28992, 4326, always_xy=True).transform, extent)
            service = ExtentService(store)
            job = service.create(project.entity_id, ExtentRequest(geometry=mapping(wgs), idempotency_key='m4h-' + stamp))
            print(f'{utc()} extent={job["id"]} job={job["job_id"]}', flush=True)
            result = service.run(job['job_id'])
            receipt['result'] = result
            path = Path(result['manifest_path'])
            receipt['export'] = export_geopackage(path, root / 'extent.gpkg')
            manifest = json.loads(path.read_bytes())
            for item in manifest['sources']:
                print(f'{utc()} {item["name"]}: {item["status"]}; count={item.get("count")}; bytes={item.get("bytes")}; elapsed={item.get("elapsed_s")}; error={item.get("error")}', flush=True)
            # Same local comparison envelope avoids equating 10km roads with 2km context.
            context_ref = Path(__file__).resolve().parents[1] / 'config/context/manifest.json'
            context = json.loads(context_ref.read_bytes())
            context_root = Path.home() / '.local/share/urban-design-data/context' / context['run_directory']
            comparison = {'existing_context_distance_m': context['context_distance_m'], 'comparison_scope': 'rough extent + 500m; both sources clipped by intersection',
                          'existing_context_manifest_sha256': digest(context_ref.read_bytes()), 'source_dates_differ': True}
            for name, filename in [('buildings', 'buildings.geojson'), ('roads', 'roads.geojson')]:
                old_path = context_root / context['layer_files'][name]['file']
                old_bytes = old_path.read_bytes()
                if digest(old_bytes).removeprefix('sha256:') != context['layer_files'][name]['sha256'].removeprefix('sha256:'):
                    raise ValueError('surrounding context hash mismatch')
                old = json.loads(old_bytes)['features']
                old_geoms = [shape(feature['geometry']) for feature in old if shape(feature['geometry']).intersects(extent.buffer(500))]
                new_path = path.parent / filename
                comparison[name] = {'existing_local_count': len(old_geoms), 'existing_full_count': len(old)}
                if new_path.exists():
                    new = json.loads(new_path.read_bytes())['features']
                    new_geoms = [shape(f['geometry']) for f in new if shape(f['geometry']).intersects(extent.buffer(500))]
                    comparison[name].update(fetched_local_count=len(new_geoms), count_difference=len(new_geoms) - len(old_geoms))
                    if name == 'roads':
                        old_length = sum(g.intersection(extent.buffer(500)).length for g in old_geoms)
                        new_length = sum(g.intersection(extent.buffer(500)).length for g in new_geoms)
                        comparison[name].update(existing_local_length_m=old_length, fetched_local_length_m=new_length, difference_m=new_length-old_length)
                else:
                    comparison[name]['status'] = 'UNAVAILABLE_FETCH_SOURCE_FAILED'
            receipt['comparison'] = comparison
            receipt['copy_ledger_after'] = ledger(store.connection)
    except Exception as exc:
        receipt['error'] = f'{type(exc).__name__}: {exc}'
        print(receipt['error'], flush=True)
    with sqlite3.connect('file:' + str(AUTHORITY) + '?mode=ro', uri=True) as source:
        receipt['ledger_after'] = ledger(source)
    receipt.update(finished_at=utc(), elapsed_s=round(time.perf_counter() - started, 3))
    save(root / 'receipt.json', encoded(receipt))
    print(f'{utc()} receipt={root / "receipt.json"}', flush=True)
    if receipt['ledger_after'] != before:
        raise RuntimeError('STOP: formal ledger changed')
