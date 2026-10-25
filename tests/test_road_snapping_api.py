from test_scenario_editing_api import _scenario


def test_preview_revision_and_explicit_midpoint_apply(tmp_path):
    client, store, sid = _scenario(tmp_path)
    params = store.current(sid).payload['parameters']
    graph = params['road_graph']
    moving = next(n for n in graph['nodes'] if n['x_m'] == 90050 and n['y_m'] == 436000)
    url = f"/api/v1/scenarios/{sid}/road-nodes/{moving['node_id']}"
    query = {'x_m': 90050, 'y_m': 436040.2, 'expected_revision': 0}
    preview = client.post(url + '/snap-candidates', json=query)
    assert preview.status_code == 200, preview.text
    candidates = preview.json()['candidates']
    midpoint = next(c for c in candidates if c['snap_kind'] == 'MIDPOINT')
    moved = client.post(url + '/move', json={**query, 'snap_kind': 'MIDPOINT', 'target_id': midpoint['target_edge_ids'][0], 'idempotency_key': 'midpoint'})
    assert moved.status_code == 201, moved.text
    assert moved.json()['snap_kind'] == 'MIDPOINT'
    assert client.post(url + '/snap-candidates', json=query).status_code == 409
    assert store.list_current('HumanDecision') == []


def test_height_edit_preserves_graph_accessibility_and_status(tmp_path):
    client, store, sid = _scenario(tmp_path)
    record = store.current(sid)
    payload = dict(record.payload)
    parameters = dict(payload['parameters'])
    parameters['accessibility_hash'] = 'fixture-access-hash'
    parameters['result_statuses'] = {'access': 'CURRENT'}
    payload['parameters'] = parameters
    store.update(sid, payload, expected_revision=record.revision, replace=True, actor='test', reason='fixture refs')
    before = store.current(sid).payload['parameters']
    building = before['editable_buildings'][0]['building_id']
    response = client.post(f'/api/v1/scenarios/{sid}/edits', json={'building_id': building, 'command': {'type': 'add_floor', 'new_floor_id': 'height-only'}, 'expected_revision': 0, 'idempotency_key': 'height'})
    assert response.status_code == 201, response.text
    after = store.current(sid).payload['parameters']
    for key in ('road_graph', 'accessibility_hash', 'result_statuses'):
        assert before[key] == after[key]


def test_delayed_publication_preserves_new_graph_and_history(tmp_path):
    import pytest
    from urban_design.editing.road_dependencies import publish_road_job_reference
    from urban_design.scenario_editing_api import _graph_from_payload
    client, store, sid = _scenario(tmp_path)
    before = store.current(sid)
    params = before.payload['parameters']
    old_hash = _graph_from_payload(params['road_graph']).graph_hash
    moving = next(n for n in params['road_graph']['nodes'] if n['x_m'] == 90050 and n['y_m'] == 436000)
    response = client.post(f"/api/v1/scenarios/{sid}/road-nodes/{moving['node_id']}/move", json={'x_m': 90050.123456, 'y_m': 436040.2, 'expected_revision': 0, 'idempotency_key': 'road'})
    assert response.status_code == 201, response.text
    current = store.current(sid)
    with pytest.raises(ValueError, match='STALE'):
        publish_road_job_reference(store, sid, job_graph_hash=old_hash, job_revision=0, result_id='old-job', artifact_ref=before.payload['geometry_artifact_id'])
    assert store.current(sid).revision == current.revision
    assert store.current(sid).payload == current.payload


def test_current_job_reference_is_unverified_then_staled_by_road_edit(tmp_path):
    from urban_design.editing.road_dependencies import publish_road_job_reference
    from urban_design.scenario_editing_api import _graph_from_payload
    client, store, sid = _scenario(tmp_path)
    before = store.current(sid)
    params = before.payload['parameters']
    digest = _graph_from_payload(params['road_graph']).graph_hash
    updated = publish_road_job_reference(store, sid, job_graph_hash=digest, job_revision=0, result_id='fixture-job', artifact_ref=before.payload['geometry_artifact_id'])
    assert updated.payload['parameters']['road_job_result_refs']['fixture-job']['validation_status'] == 'UNVERIFIED'
    moving = next(n for n in params['road_graph']['nodes'] if n['x_m'] == 90050 and n['y_m'] == 436000)
    response = client.post(f"/api/v1/scenarios/{sid}/road-nodes/{moving['node_id']}/move", json={'x_m': 90050.123456, 'y_m': 436040.2, 'expected_revision': 0, 'idempotency_key': 'road'})
    assert response.status_code == 201, response.text
    assert 'fixture-job' in response.json()['stale_result_ids']
    assert store.current(sid).payload['parameters']['result_statuses']['fixture-job'] == 'STALE'


def test_job_publication_concurrent_scenario_change_fails_cas(tmp_path, monkeypatch):
    import pytest
    from urban_design.editing.road_dependencies import publish_road_job_reference
    from urban_design.scenario_editing_api import _graph_from_payload
    from urban_design.store import RevisionConflictError
    client, store, sid = _scenario(tmp_path)
    before = store.current(sid)
    digest = _graph_from_payload(before.payload['parameters']['road_graph']).graph_hash
    update = store.update
    def race(entity_id, payload, **kwargs):
        if kwargs.get('action') == 'AttachRoadJobReference':
            current = store.current(entity_id)
            parameters = {**current.payload['parameters'], 'road_edit_revision_id': 1}
            update(entity_id, {**current.payload, 'parameters': parameters}, expected_revision=current.revision, replace=True, actor='test', reason='simulate concurrent road revision')
        return update(entity_id, payload, **kwargs)
    monkeypatch.setattr(store, 'update', race)
    with pytest.raises(RevisionConflictError):
        publish_road_job_reference(store, sid, job_graph_hash=digest, job_revision=0, result_id='racing-job', artifact_ref=before.payload['geometry_artifact_id'])
    assert 'road_job_result_refs' not in store.current(sid).payload['parameters']
    assert store.current(sid).payload['parameters']['road_edit_revision_id'] == 1


def test_snap_apply_rejects_stale_graph_hash_even_at_same_revision(tmp_path):
    client, store, sid = _scenario(tmp_path)
    graph = store.current(sid).payload['parameters']['road_graph']
    moving = next(n for n in graph['nodes'] if n['x_m'] == 90050 and n['y_m'] == 436000)
    response = client.post(f"/api/v1/scenarios/{sid}/road-nodes/{moving['node_id']}/move", json={'x_m': 90050, 'y_m': 436040.2, 'expected_revision': 0, 'expected_graph_hash': 'stale', 'idempotency_key': 'stale'})
    assert response.status_code == 409, response.text
    assert 'STALE' in response.json()['detail']
