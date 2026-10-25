"""D1 payload and temporary SQLite/API rehearsal; no human decisions."""
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box, mapping

from urban_design.api import create_workspace_app
from urban_design.geometry import canonical_geometry_hash
from urban_design.store import ProjectStateStore

spec = importlib.util.spec_from_file_location('prepare_d1', Path(__file__).resolve().parents[1] / 'scripts/prepare_d1_draft.py')
d1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d1)


@pytest.fixture
def inputs(monkeypatch):
    geometry = mapping(box(0, 0, 10, 10))
    monkeypatch.setattr(d1, 'EDA_HASH', canonical_geometry_hash(geometry))
    features = []
    for bag, page, _ in d1.BUILDINGS:
        features.append(dict(id='bag:' + bag, source_artifact_id=f'artifact-pdok-bag-pand-p{page}-normalized-3390e215019805a1',
                             source_snapshot_id=f'snapshot-pdok-bag-pand-p{page}-3390e215019805a1', source_feature_id=bag))
    context = dict(study_area=dict(id=d1.AREA, status='CONFIRMED_FOR_EXPLORATION', geometry=geometry), buildings=features,
                   source_snapshot_ids=sorted({f['source_snapshot_id'] for f in features}))
    workspace = dict(revision=1, feature_dispositions=[dict(feature_id='bag:existing', feature_kind='building', disposition='undecided',
                                                          source_artifact_id=features[0]['source_artifact_id'], source_snapshot_id=None, source_feature_id=None, annotation='existing')])
    zone_ids = ['zone-energy-hub', 'zone-residential-tidal-park', 'zone-art-space-recreation', 'zone-residential', 'zone-maker-recycle-hub']
    names = ['Energy Hub', 'Residential + Tidal Park', 'Art Space + Recreation', 'Residential', 'Maker Space + Recycle Hub']
    zones = dict(crs=dict(properties=dict(name='EPSG:28992')), features=[dict(id=z, properties=dict(name=n), geometry=mapping(box(i, 0, i+1, 1))) for i, (z, n) in enumerate(zip(zone_ids, names))])
    return context, workspace, zones


def test_payload_and_api_temporary_db(tmp_path, inputs):
    context, workspace, zones = inputs
    payload = d1.build_payload(*inputs)
    assert payload['actor_kind'] == 'AGENT_AUTOMATION'
    assert payload['expected_workspace_revision'] == 1
    ds = payload['feature_dispositions']
    assert len(ds) == 7 and ds[0]['disposition'] == 'undecided'
    assert all(d['feature_id'] != 'bag:0599100000641246' for d in ds)
    merged = [d for d in ds if d['feature_id'] == 'bag:0599100010058726']
    assert len(merged) == 1 and '#7/#11' in merged[0]['annotation']
    assert 'Pand gesloopt' in ds[1]['annotation']
    assert all('ASSUMED_FROM_PORTFOLIO' in d['annotation'] for d in ds[1:])
    brief = payload['spatial_brief']
    assert brief['exploration_design_area']['geometry'] == json.loads(json.dumps(context['study_area']['geometry']))
    for z in brief['zones']:
        assert z['target_far'] is z['target_coverage_ratio'] is z['target_height_m'] is None
        assert z['status'] == 'DRAFT_PENDING_HUMAN_DECISION'
        assert d1.PREFERENCE in z['draft_preferences']
        assert z['draft_constraints'][0].startswith(d1.WATERFRONT)
    store = ProjectStateStore(tmp_path / 'state.sqlite3')
    store.create('StudyArea', {'status': 'CONFIRMED_FOR_EXPLORATION'}, entity_id=d1.AREA)
    for sid in context['source_snapshot_ids']:
        store.create('DatasetSnapshot', {'status': 'CONFIRMED'}, entity_id=sid)
    for aid in {f['source_artifact_id'] for f in context['buildings']}:
        store.create('Artifact', {}, entity_id=aid)
    initial = dict(workspace_id='workspace-' + d1.PROJECT, project_id=d1.PROJECT, revision=1, study_area_id=d1.AREA,
                   source_snapshot_ids=context['source_snapshot_ids'], feature_dispositions=workspace['feature_dispositions'], status='DRAFT')
    store.create('WorkspaceRevision', initial, entity_id=initial['workspace_id'])
    before = store._connection.execute('select count(*) from ledger_events').fetchone()[0]
    with TestClient(create_workspace_app(store)) as client:
        first = client.post('/api/v1/workspaces/sync', json=payload)
        assert first.status_code == 201, first.text
        revision = first.json()['workspace_revision']
        assert revision['revision'] == 2 and revision['status'] == 'DRAFT'
        # Fresh revision is fetched for a deliberate replay, never an automatic retry.
        current = client.get('/api/v1/workspaces/' + initial['workspace_id']).json()
        replay_payload = d1.build_payload(context, current, zones)
        second = client.post('/api/v1/workspaces/sync', json=replay_payload)
        assert second.status_code == 200, second.text
        assert second.json()['idempotent_replay'] is True
        assert second.json()['workspace_revision'] == revision
    assert store.list_current('HumanDecision') == []
    assert store._connection.execute('select count(*) from ledger_events').fetchone()[0] == before + 1
    assert store._connection.execute('select actor_kind from ledger_events order by rowid desc limit 1').fetchone()[0] == 'AGENT_AUTOMATION'


def test_rejects_source_mismatch_and_changed_area(inputs):
    context, workspace, zones = inputs
    context['buildings'][0]['source_snapshot_id'] = 'wrong'
    with pytest.raises(ValueError, match='lineage'):
        d1.build_payload(*inputs)
    context['study_area']['geometry'] = mapping(box(0, 0, 20, 20))
    with pytest.raises(ValueError, match='unchanged'):
        d1.build_payload(*inputs)


def test_preserves_existing_roads_and_rejects_15(inputs):
    context, workspace, zones = inputs
    road = dict(feature_id='way/1', feature_kind='road', disposition='undecided', source_artifact_id='road-source', annotation='keep')
    workspace['feature_dispositions'].append(road)
    payload = d1.build_payload(*inputs)
    assert [d for d in payload['feature_dispositions'] if d['feature_kind'] == 'road'][0]['disposition'] == 'undecided'
    workspace['feature_dispositions'].append(dict(road, feature_id='bag:0599100000641246'))
    with pytest.raises(ValueError, match='#15'):
        d1.build_payload(*inputs)
