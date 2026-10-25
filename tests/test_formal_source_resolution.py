"""Resolver compatibility without decisions or relaxed artifact integrity."""
import hashlib
import json
from types import SimpleNamespace
import pytest
from shapely.geometry import box
from urban_design.approved_generation import _resolve_source_feature, _floor_estimates
from urban_design.store import ProjectStateStore
from urban_design.workspace_contracts import FeatureDisposition


def source(tmp_path):
    store = ProjectStateStore(tmp_path / 'state.sqlite3')
    path = tmp_path / 'source.json'
    document = {'type':'FeatureCollection','features':[{'id':'uuid','properties':{'identificatie':'0599100000765601'},'geometry':{'type':'Polygon','coordinates':[[[0,0],[10,0],[10,10],[0,10],[0,0]]]}}]}
    path.write_text(json.dumps(document))
    store.create('Artifact',dict(id='a',uri=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),crs='EPSG:28992'),entity_id='a',project_id='p')
    store.create('DatasetSnapshot',dict(id='s',normalized_artifact_id='a'),entity_id='s',project_id='p')
    return store,path


def disposition(identifier):
    return FeatureDisposition(feature_id='building',feature_kind='building',disposition='preserve',source_artifact_id='a',source_snapshot_id='s',source_feature_id=identifier)


def test_identificatie_matches_but_wrong_id_and_hash_rejected(tmp_path):
    store,path=source(tmp_path)
    with store:
        assert _resolve_source_feature(store,disposition('0599100000765601'),'p',['s'])[3].area == 100
        with pytest.raises(ValueError,match='0 source features'):
            _resolve_source_feature(store,disposition('wrong'),'p',['s'])
        path.write_text(path.read_text()+' ')
        with pytest.raises(ValueError,match='SHA-256'):
            _resolve_source_feature(store,disposition('0599100000765601'),'p',['s'])


def test_unknown_retained_floor_is_not_zero(tmp_path):
    with ProjectStateStore(tmp_path/'unknown.sqlite3') as store:
        inputs=SimpleNamespace(constraint_decision=SimpleNamespace(id='approved-ref'),constraint_set=SimpleNamespace(constraints=[SimpleNamespace(name='standard_floor_height',value=3.5,unit='m',scope='whole_site')]),source_snapshots=[],retained_buildings=[(disposition('0599100000765601'),box(0,0,10,10),{'identificatie':'0599100000765601'})])
        counts,records=_floor_estimates(store,inputs)
        assert counts == (None,)
        assert records[0]['floor_count']['status'] == 'unavailable'
