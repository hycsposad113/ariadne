#!/usr/bin/env python3
"""Prepare authorised D1 DRAFT only. No decision calls and no HTTP retries.

Without --api-base, read --database (a quiescent copy only) and print JSON.
With --api-base, obtain fresh verified site context and workspace from that API.
"""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.request import Request, urlopen

from urban_design.geometry import canonical_geometry_hash
from urban_design.workspace_contracts import SyncRequest, validate_spatial_brief_zoning

PROJECT = 'rotterdam-m4h-pilot-project'
AREA = 'study-area-rotterdam-m4h-pilot-project-v5'
EDA_HASH = 'sha256:3dedb804fa4f07f4c9570bcc64e68c8d576c03340455ab35fd4963bca52aa4f5'
COPY = Path('/private/tmp/claude-501/-Users-jackhsieh-Downloads-TUD-Q5-project/ed3e0c5c-6991-4bd5-8782-84d13fc450f1/scratchpad/runs/d1-draft/rehearsal-state.sqlite3')
ZONES = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/artifacts/portfolio-baseline/zones.geojson')
BUILDINGS = [
    ('0599100000765601', '007', 'p15 #5; LOW; 加蓋=否; BAG 狀態 Pand gesloopt，與 portfolio 現況不符，依 portfolio 保留'),
    ('0599100010058726', '009', 'p15 #7/#11 兩個圖面區塊合併同一 BAG pand; #7 MEDIUM、加蓋=是; #11 LOW、加蓋=否'),
    ('0599100010039532', '008', 'p15 #9; MEDIUM; 加蓋=否'),
    ('0599100000641255', '003', 'p15 #12; LOW; 加蓋=否'),
    ('0599100000188925', '001', 'p15 #13; LOW; 加蓋=是'),
    ('0599100000752293', '006', 'p15 #17; HIGH（僅空間對位）; 加蓋=是'),
]
PREFERENCE = '街廓對齊道路或基地主軸，不預設正南北（FOUNDER_STATED，全區偏好）'
WATERFRONT = '15 m 水岸帶：新建築不得進入；既有保留建築（含其上加蓋）可留；允許親水步道（FOUNDER_STATED）'


def http_json(base, path, payload=None):
    request = Request(base.rstrip('/') + path, data=None if payload is None else json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'}, method='GET' if payload is None else 'POST')
    with urlopen(request, timeout=60) as response:
        return json.load(response)


def copy_context(database):
    """Immutable read of an explicitly quiescent copy; never open the formal DB."""
    database = Path(database).resolve(strict=True)
    formal = Path('/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3')
    if database == formal or (formal.exists() and database.samefile(formal)):
        raise ValueError('formal database is forbidden')
    with sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        def current(entity_id):
            row = connection.execute('SELECT v.payload_json FROM state_versions v JOIN state_heads h ON v.entity_id=h.entity_id AND v.revision=h.current_revision WHERE v.entity_id=?', (entity_id,)).fetchone()
            if row is None:
                raise ValueError('missing source record: ' + entity_id)
            return json.loads(row[0])
        area = current(AREA)
        artifact = current(area['geometry_artifact_id'])
        document = json.loads(Path(artifact['uri']).read_text())
        area['geometry'] = document.get('geometry', document)
        workspace = current('workspace-' + PROJECT)
        features = []
        for bag, page, _ in BUILDINGS:
            snap_id = f'snapshot-pdok-bag-pand-p{page}-3390e215019805a1'
            art_id = f'artifact-pdok-bag-pand-p{page}-normalized-3390e215019805a1'
            snapshot, source = current(snap_id), current(art_id)
            if snapshot['normalized_artifact_id'] != art_id:
                raise ValueError('snapshot lineage mismatch')
            raw = Path(source['uri']).read_bytes()
            if 'sha256:' + hashlib.sha256(raw).hexdigest() != source['sha256']:
                raise ValueError('source artifact hash mismatch')
            matches = [f for f in json.loads(raw)['features'] if f['properties'].get('identificatie') == bag]
            if len(matches) != 1:
                raise ValueError('source feature missing or ambiguous: ' + bag)
            features.append(dict(id='bag:' + bag, source_artifact_id=art_id, source_snapshot_id=snap_id, source_feature_id=bag))
        return dict(study_area=area, buildings=features, source_snapshot_ids=workspace['source_snapshot_ids']), workspace


def build_payload(context, workspace, zones_document):
    area = context['study_area']
    if area['id'] != AREA or area['status'] != 'CONFIRMED_FOR_EXPLORATION' or canonical_geometry_hash(area['geometry']) != EDA_HASH:
        raise ValueError('D1 requires unchanged confirmed StudyArea v5')
    dispositions = [dict(d) for d in workspace['feature_dispositions']]
    ids = {d['feature_id'] for d in dispositions}
    if 'bag:0599100000641246' in ids:
        raise ValueError('#15 already present; manual reconciliation required')
    features = {f['id']: f for f in context['buildings']}
    for bag, page, note in BUILDINGS:
        feature_id = 'bag:' + bag
        f = features[feature_id]
        art = f'artifact-pdok-bag-pand-p{page}-normalized-3390e215019805a1'
        snap = f'snapshot-pdok-bag-pand-p{page}-3390e215019805a1'
        if f['source_artifact_id'] != art or f['source_snapshot_id'] != snap or f['source_feature_id'] != bag or snap not in context['source_snapshot_ids']:
            raise ValueError('verified source lineage mismatch: ' + feature_id)
        d = dict(feature_id=feature_id, feature_kind='building', disposition='preserve', source_artifact_id=art,
                 source_snapshot_id=snap, source_feature_id=bag, annotation=note + '; ASSUMED_FROM_PORTFOLIO; FOUNDER_STATED; DRAFT')
        existing = next((x for x in dispositions if x['feature_id'] == feature_id), None)
        if existing is not None and existing != d:
            raise ValueError('existing D1 disposition differs; manual reconciliation required')
        if existing is None:
            dispositions.append(d)
    zones = []
    expected = ['zone-energy-hub', 'zone-residential-tidal-park', 'zone-art-space-recreation', 'zone-residential', 'zone-maker-recycle-hub']
    if [f['id'] for f in zones_document['features']] != expected or zones_document['crs']['properties']['name'] != 'EPSG:28992':
        raise ValueError('unexpected five-zone source')
    for f in zones_document['features']:
        name = f['properties']['name']
        zones.append(dict(zone_id=f['id'], name=name, target_use=name, geometry=f['geometry'], author='AGENT_AUTOMATION',
                          notes='p18 人工描繪；LOW 信心；PREFERENCE；ASSUMED_FROM_PORTFOLIO',
                          draft_preferences=['PREFERENCE; ASSUMED_FROM_PORTFOLIO', PREFERENCE],
                          draft_constraints=[WATERFRONT + '；相關水岸區適用，buffer 幾何未指定，僅草稿文字']))
    request = SyncRequest(project_id=PROJECT, study_area_id=AREA, expected_workspace_revision=workspace['revision'],
                          source_snapshot_ids=context['source_snapshot_ids'], feature_dispositions=dispositions,
                          spatial_brief=dict(exploration_design_area=dict(geometry=area['geometry'], author='AGENT_AUTOMATION; FOUNDER_STATED'), zones=zones),
                          actor_kind='AGENT_AUTOMATION', actor_session_id='d1-founder-authorized-2026-10-01', idempotency_key='d1-draft-founder-2026-10-01-v1')
    validate_spatial_brief_zoning(request.spatial_brief)
    return request.model_dump(mode='json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-base')
    parser.add_argument('--database', type=Path, default=COPY, help='quiescent copy for offline JSON only')
    parser.add_argument('--zones', type=Path, default=ZONES)
    args = parser.parse_args()
    if args.api_base:
        context = http_json(args.api_base, f'/api/v1/projects/{PROJECT}/site-context')
        workspace = http_json(args.api_base, '/api/v1/workspaces/workspace-' + PROJECT)
    else:
        context, workspace = copy_context(args.database)
    payload = build_payload(context, workspace, json.loads(args.zones.read_text()))
    # A single explicit POST; failures and unknown outcomes propagate without retry.
    result = http_json(args.api_base, '/api/v1/workspaces/sync', payload) if args.api_base else payload
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
