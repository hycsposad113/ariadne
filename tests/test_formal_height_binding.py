"""Synthetic evidence only; no HumanDecision creation or runtime DB access."""
import hashlib
import json
from types import SimpleNamespace as NS

import pytest
from shapely.geometry import box

from urban_design.approved_generation import ApprovedGenerationBlocked
from urban_design.generation.height_binding import bind_retained_heights
from urban_design.generation.formal_adapter import adapt_frozen_context, retained_gfa_bounds
from urban_design.generation_context import GenerationContext, Readiness, context_digest
from urban_design.store import ProjectStateStore
from urban_design.three_d_bag import THREE_DBAG_VERTICAL_REFERENCE

BAG = '0599100000000001'


def setup_sources(tmp_path, *, industrial=True):
    store = ProjectStateStore(tmp_path/'test.sqlite3')
    raw = tmp_path/'tile.gz'
    raw.write_bytes(b'synthetic source bytes, not an actual tile')
    raw_hash = 'sha256:'+hashlib.sha256(raw.read_bytes()).hexdigest()
    path = tmp_path/'table.json'
    doc = dict(schema_version='3dbag-height-table-v1', data_version='v1', license='CC BY 4.0', attribution='synthetic',
        study_area_id='study', study_area_version='v5', study_area_geometry_sha256='sha256:'+'a'*64,
        study_area_artifact_sha256='sha256:'+'b'*64, study_area_horizontal_crs='EPSG:28992',
        vertical_reference=THREE_DBAG_VERTICAL_REFERENCE, buffer_distance_m=500, buffer_geometry_sha256='sha256:'+'c'*64,
        buffer_bbox_m=[0,0,100,100], buffered_area_m2=10000,
        source_tiles=[dict(tile_id='tile',url='https://data.3dbag.nl/tile',path=str(raw),sha256=raw_hash)],
        records=[dict(bag_identificatie=BAG, roof_p70_height_m=17., ground_height_m=3., height_above_ground_m=14.,
                      source_version='v1', roof_part_count=1, source_tile_ids=['tile'],
                      roof_p70_aggregation='maximum-roofpart-b3_h_70p', status='AVAILABLE',unavailable_reason=None)])
    path.write_text(json.dumps(doc))
    for id, file, parents in [('raw',raw,[]),('table',path,['raw'])]:
        store.create('Artifact',dict(id=id,uri=str(file),sha256='sha256:'+hashlib.sha256(file.read_bytes()).hexdigest(),parent_artifact_ids=parents),entity_id=id,project_id='p')
    store.create('DatasetSnapshot',dict(id='snapshot',project_id='p',source='https://data.3dbag.nl/tile',version='v1',sha256=raw_hash,
        raw_artifact_id='raw',normalized_artifact_id='table'),entity_id='snapshot',project_id='p')
    inputs=NS(project_id='p',study_area=NS(entity_id='study',payload={'geometry_sha256':'sha256:'+'a'*64}),
        constraint_set=NS(constraints=[NS(name='standard_floor_height',scope='whole_site',value=3.5)]),
        constraint_decision=NS(id='existing-decision-reference'),retained_buildings=[
            (NS(feature_id='building'),box(0,0,10,10),{'identificatie':BAG,'gebruiksdoel':'kantoorfunctie,industriefunctie' if industrial else 'woonfunctie'}),
            (NS(feature_id='unknown'),box(20,0,30,10),{'identificatie':'0599100000000002'})])
    return store,inputs,path,raw


def test_binding_estimate_upper_bound_and_unknown_not_zero(tmp_path):
    store,inputs,path,raw=setup_sources(tmp_path)
    with store:
        before=store.connection.total_changes
        result=bind_retained_heights(store,inputs)
        first,unknown=result.estimates
        assert first['floor_count']['lower'] == 1
        assert first['floor_count']['upper'] == 4
        assert first['gfa_lower_m2'] == 100
        assert first['gfa_upper_m2'] == 400
        assert first['snapshot_ids'] == ['snapshot']
        assert first['status'] == 'ESTIMATE'
        assert unknown['gfa_upper_m2'] is None
        assert unknown['floor_count']['status'] == 'UNAVAILABLE'
        bounds=retained_gfa_bounds(NS(floor_estimates=result.estimates))
        assert bounds['upper_m2'] is None and bounds['known_upper_m2'] == 400
        assert store.connection.total_changes == before
        assert store.list_current('HumanDecision') == []


@pytest.mark.parametrize('artifact', ['raw','normalized'])
def test_hash_mismatch_blocks(tmp_path,artifact):
    store,inputs,path,raw=setup_sources(tmp_path)
    with store:
        file=raw if artifact == 'raw' else path
        file.write_bytes(file.read_bytes()+b' ')
        with pytest.raises(ApprovedGenerationBlocked,match='blocked') as exc:
            bind_retained_heights(store,inputs)
        assert 'hash-invalid' in exc.value.missing[0]


def test_missing_snapshot_blocks(tmp_path):
    store,inputs,path,raw=setup_sources(tmp_path)
    with store:
        # Append a second table source but no corresponding DatasetSnapshot.
        document=json.loads(path.read_text())
        document['source_tiles'].append(dict(tile_id='missing',url='https://data.3dbag.nl/missing',sha256='sha256:'+'f'*64))
        path.write_text(json.dumps(document))
        # Synthetic store update only; no production evidence correction.
        current=store.current('table')
        store.update('table',{**current.payload,'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()},expected_revision=current.revision)
        with pytest.raises(ApprovedGenerationBlocked) as exc:
            bind_retained_heights(store,inputs)
        assert 'missing 3D BAG snapshot' in exc.value.missing[0]


def frozen_manifest(binding):
    manifest=GenerationContext(project_id='p',workspace_revision=8,input_hash='d'*64,
        refs=tuple(dict(id=id,entity_type=kind,revision=1,payload_hash=digit*64) for id,kind,digit in
                   [('workspace','WorkspaceRevision','a'),('study','StudyArea','b'),('constraint','ConstraintSet','c')]),
        far_denominator=dict(scope='LAND_AREA',area_m2=8000,unit='m2'),allocation_policy=None,zones=(),
        floor_estimates=binding.estimates,height_source_manifest=binding.manifest)
    return Readiness(status='READY',context_hash=context_digest(manifest),context=manifest)


def test_formal_adapter_replay_hash_and_source_drift(tmp_path):
    store,inputs,path,raw=setup_sources(tmp_path,industrial=False)
    with store:
        frozen=frozen_manifest(bind_retained_heights(store,inputs))
        first=adapt_frozen_context(frozen,seed=42)
        assert first == adapt_frozen_context(frozen,seed=42)
        assert first.generation_class.value == 'APPROVED_INPUTS'
        assert first.analysis_ref.id == 'study'
        assert all(r.kind != 'SYNTHETIC_FIXTURE' for r in first.source_refs)
        assert first.method_parameters['formal_manifest']['far_denominator']['area_m2'] == 8000
        changed=frozen.context.model_copy(update={'height_source_manifest':()})
        assert context_digest(changed) != frozen.context_hash
        with pytest.raises(ApprovedGenerationBlocked):
            adapt_frozen_context(frozen.model_copy(update={'context':changed}),seed=42)


def test_readiness_binds_observations_and_blocks_hash_or_missing_snapshot(tmp_path,monkeypatch):
    from urban_design import generation_context as gc
    store,inputs,path,raw=setup_sources(tmp_path)
    def rec(id,kind,payload):
        return NS(entity_id=id,entity_type=kind,revision=1,payload=payload)
    inputs.workspace_record=rec('workspace','WorkspaceRevision',{'id':'workspace'})
    inputs.constraint_record=rec('constraints','ConstraintSet',{'id':'constraints'})
    inputs.study_area=rec('study','StudyArea',inputs.study_area.payload)
    inputs.workspace=NS(revision=8)
    inputs.workspace_decision=NS(id='existing-d1',target_id='workspace',target_version='8',target_payload_digest='d'*64)
    inputs.constraint_decision=NS(id='existing-d2',target_id='constraints',target_version='1',target_payload_digest='e'*64)
    inputs.source_snapshots=()
    inputs.source_artifacts=()
    inputs.input_hash='f'*64
    inputs.design_area=box(0,0,100,100)
    inputs.water_geometry=box(0,0,20,100)
    inputs.zones=()
    inputs.constraint_set=NS(allocation_policy=None,constraints=[
        NS(name='standard_floor_height',scope='whole_site',value=3.5),
        NS(name='far_upper_limit',scope='whole_site',denominator='land_area')])
    monkeypatch.setattr(gc,'_load_approved_inputs',lambda *a,**kw: inputs)
    with store:
        ready=gc.resolve_readiness(store,'p')
        assert ready.status == 'READY'
        assert ready.context.far_denominator['area_m2'] == 8000
        assert any(r['id']=='snapshot' for r in ready.context.refs)
        assert ready.context.height_source_manifest[0]['normalized_artifact_id']=='table'
        request=gc.FreezeRequest(expected_workspace_revision=8,expected_context_hash=ready.context_hash)
        assert gc.freeze_context(store,'p',request) == ready
        path.write_bytes(path.read_bytes()+b' ')
        blocked=gc.resolve_readiness(store,'p')
        assert blocked.status == 'BLOCKED' and 'hash-invalid' in blocked.blockers[0]
        monkeypatch.setattr(store,'list_current',lambda *a,**kw: [])
        blocked=gc.resolve_readiness(store,'p')
        assert blocked.status == 'BLOCKED' and 'missing registered' in blocked.blockers[0]


def test_commander_demolished_zero_is_evidence_bound(tmp_path):
    store,inputs,path,raw=setup_sources(tmp_path)
    inputs.retained_buildings[1][2].update(identificatie='0599100000765601',status='Pand gesloopt')
    with store:
        result=bind_retained_heights(store,inputs)
        demolished=result.estimates[1]
        assert demolished['status']=='ASSUMED_COMMANDER'
        assert demolished['gfa_lower_m2']==demolished['gfa_upper_m2']==0
        assert demolished['footprint_area_m2']==100
        assert retained_gfa_bounds(NS(floor_estimates=result.estimates))['upper_m2']==400


def test_same_id_without_demolition_evidence_remains_unknown(tmp_path):
    store,inputs,path,raw=setup_sources(tmp_path)
    inputs.retained_buildings[1][2]['identificatie']='0599100000765601'
    with store:
        row=bind_retained_heights(store,inputs).estimates[1]
        assert row['gfa_upper_m2'] is None
