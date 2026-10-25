"""Synthetic approved-shaped contracts, never production decisions."""
from types import SimpleNamespace as NS
from shapely.geometry import box, LineString, mapping, shape
from urban_design.generation_context import GenerationContext, Readiness, context_digest
from urban_design.generation.formal_adapter import adapt_frozen_context
from urban_design.generation.formal_pipeline import run_formal_pipeline
from urban_design.morphology.contracts import SiteRoadInput


def fixture():
    refs=tuple(dict(id=id,entity_type=kind,revision=1,payload_hash='a'*64) for id,kind in
        [('w','WorkspaceRevision'),('c','ConstraintSet'),('s','StudyArea'),('road-source','Artifact'),('road-snapshot','DatasetSnapshot')])
    manifest=GenerationContext(project_id='p',workspace_revision=8,input_hash='b'*64,refs=refs,
        far_denominator={'scope':'LAND_AREA','area_m2':240000,'unit':'m2'},allocation_policy=None,
        zones=({'zone_id':'z','target_use':'Residential','geometry':mapping(box(0,0,600,400))},),
        floor_estimates=({'building_id':'retained','floor_count':{'status':'ESTIMATE','lower':1,'upper':2},'gfa_lower_m2':400,'gfa_upper_m2':800},))
    frozen=Readiness(status='READY',context=manifest,context_hash=context_digest(manifest))
    context=adapt_frozen_context(frozen,seed=42)
    constraints=[NS(name=n,scope='whole_site',value=v,denominator='land_area' if n=='far_upper_limit' else None) for n,v in
        [('far_upper_limit',.8),('coverage_upper_limit',.35),('height_upper_limit',20),('standard_floor_height',3.5),('first_floor_height',3.5)]]
    constraints += [NS(name='road_width',scope='road:'+n,value=v) for n,v in [('primary',14),('secondary',10),('residential',6)]]
    roads=tuple(SiteRoadInput(road_id='r'+str(i),geometry=LineString(coords),layer=0,bridge=False,tunnel=False,
        source_artifact_id='road-source',source_snapshot_id='road-snapshot',road_width_scope='road:residential',highway='residential') for i,coords in
        enumerate([[(-10,100),(20,100)],[(580,300),(610,300)]]))
    inputs=NS(design_area=box(0,0,600,400),water_geometry=box(0,400,600,450),source_network_roads=roads,
        retained_buildings=((NS(feature_id='retained'),box(270,30,290,50),{}),),constraint_set=NS(constraints=constraints))
    return context,manifest,inputs


def test_formal_diversity_replay_and_land_far(monkeypatch):
    context,manifest,inputs=fixture()
    a=run_formal_pipeline(context,manifest,inputs)
    # Recipe order must not transfer envelopes or placement preferences
    # between candidates. Replay with reversed order proves independence.
    from urban_design.generation import formal_pipeline
    monkeypatch.setattr(formal_pipeline, 'RECIPES', tuple(reversed(formal_pipeline.RECIPES)))
    b=run_formal_pipeline(context,manifest,inputs)
    assert a['status']=='READY', [(c['recipe_id'],c['failure_reasons']) for c in a['candidates']]
    assert a['valid_count']>=3 and len(a['candidates'])==5
    valid=[c for c in a['candidates'] if c['status']=='VALID']
    assert len({c['family'] for c in valid})==3
    assert len(set().union(*(set(c['metrics']['dictionary_types']) for c in valid)))>=4
    for d in a['pairwise_differences']:
        assert max(d['difference_ratios']['road'],d['difference_ratios']['street_block'])>=.1
        assert d['substantive']
    assert {c['recipe_id']:c['result_hash'] for c in a['candidates']}=={c['recipe_id']:c['result_hash'] for c in b['candidates']}
    tradeoff=a['authored_recipe_settings']['accepted_tradeoff']
    assert tradeoff['label']=='ACCEPTED_TRADEOFF_FOUNDER_2026-10-04'
    assert tradeoff['fallback_lanes_m']=='201-242'
    assert a['authored_recipe_settings']['south_strip_collector']['provenance']=='FOUNDER_DECISION_2026-10-04'
    for c in a['candidates']:
        roles={f['properties']['role']:shape(f['geometry']) for f in c['geometry']['features'] if f['properties']['role'] in {'site_area','water'}}
        assert roles['site_area'].equals(inputs.design_area)
        assert roles['water'].equals(inputs.water_geometry)
        if c['status']!='VALID': continue
        m=c['metrics']
        assert .70<=m['far']<=.80 and m['coverage']<=.35
        assert m['open_space_ratio']>=.4 and m['unallocated_share']<=.2
        assert 10.5<=m['highest_new_height_m']<=20
        assert len(m['dictionary_types'])>=4
        assert all(z['assigned_new_gfa_m2']>0 for z in m['zone_uses'])
        assert m['far_denominator']=='land_area' and m['far_denominator_m2']==240000
        assert m['far']==(m['new_gfa_m2']+800)/240000
        for f in c['geometry']['features']:
            if f['properties']['role']=='new_building':
                assert shape(f['geometry']).intersection(inputs.water_geometry.buffer(15)).area<1e-6
                assert shape(f['geometry']).intersection(inputs.retained_buildings[0][1]).area<1e-6


def test_unknown_gfa_blocks_and_failed_candidates_retained():
    context,manifest,inputs=fixture()
    unknown=manifest.model_copy(update={'floor_estimates':({'building_id':'unknown','floor_count':{'status':'UNAVAILABLE'},'gfa_lower_m2':None,'gfa_upper_m2':None},)})
    # Build a matching freeze; do not falsify the approved manifest digest.
    context=adapt_frozen_context(Readiness(status='READY',context=unknown,context_hash=context_digest(unknown)),seed=42)
    assert run_formal_pipeline(context,unknown,inputs)['status']=='BLOCKED'
    context,manifest,inputs=fixture()
    inputs.constraint_set.constraints[0].value=.001
    result=run_formal_pipeline(context,manifest,inputs)
    assert len(result['candidates'])==5
    failed=[c for c in result['candidates'] if c['status']=='FAIL']
    assert failed and all(c['geometry']['features'] and c['failure_reasons'] for c in failed)


def test_manifest_substitution_rejected():
    import pytest
    context,manifest,inputs=fixture()
    with pytest.raises(ValueError,match='manifest differs'):
        run_formal_pipeline(context,manifest.model_copy(update={'workspace_revision':9}),inputs)


def test_real_disconnected_land_not_discarded():
    import pytest
    from shapely.geometry import MultiPolygon
    from urban_design.generation.formal_pipeline import skeleton_inputs
    context,manifest,inputs=fixture()
    inputs.water_geometry=box(300,-10,310,410)
    inputs.source_network_roads=inputs.source_network_roads[:1]
    resolved=skeleton_inputs(inputs,context)
    assert resolved.site_geometry.area==236000
    from urban_design.generation.skeleton import build_skeleton, SkeletonBuildError
    from urban_design.generation.strategy_catalog import build_strategy_catalog
    with pytest.raises(SkeletonBuildError,match='each disconnected land component'):
        build_skeleton(context,build_strategy_catalog(NS(intents=())).strategies[0],resolved)


def test_large_rd_coordinate_rotation_preserves_dictionary_semantics():
    from shapely import affinity
    context,manifest,inputs=fixture()
    def transform(g):
        return affinity.translate(affinity.rotate(g,15,origin=(0,0)),88000,435000)
    inputs.design_area=transform(inputs.design_area)
    inputs.water_geometry=transform(inputs.water_geometry)
    from dataclasses import replace
    inputs.source_network_roads=tuple(replace(r,geometry=transform(r.geometry)) for r in inputs.source_network_roads)
    inputs.retained_buildings=tuple((d,transform(g),p) for d,g,p in inputs.retained_buildings)
    updated=manifest.model_copy(update={'zones':({'zone_id':'z','target_use':'Residential','geometry':mapping(inputs.design_area)},)})
    context=adapt_frozen_context(Readiness(status='READY',context=updated,context_hash=context_digest(updated)),seed=42)
    result=run_formal_pipeline(context,updated,inputs)
    assert result['valid_count']>=3,[(c['recipe_id'],c['failure_reasons']) for c in result['candidates']]
    for candidate in result['candidates']:
        if candidate['status']=='VALID':
            assert candidate['orientation_deg']%15==0
            for f in candidate['geometry']['features']:
                if f['properties']['role']=='new_building':
                    assert inputs.design_area.covers(shape(f['geometry']))


def test_all_candidates_have_road_access():
    context, manifest, inputs = fixture()
    result = run_formal_pipeline(context, manifest, inputs)
    assert result['status'] == 'READY'
    for candidate in result['candidates']:
        access = candidate['metrics']['road_access']
        assert access['accessible_count'] == access['total_new_buildings'] > 0
        assert access['max_distance_m'] <= access['rule_m'] == 40
        assert access['provenance'] == 'ASSUMED_COMMANDER'
        roads = [shape(f['geometry']).buffer(f['properties']['width_m']/2) for f in candidate['geometry']['features'] if f['properties']['role']=='road']
        measured = []
        for f in candidate['geometry']['features']:
            if f['properties']['role'] != 'new_building': continue
            footprint = shape(f['geometry'])
            parts = footprint.geoms if footprint.geom_type=='MultiPolygon' else (footprint,)
            distance = max(min(part.distance(road) for road in roads) for part in parts)
            assert distance <= 40
            measured.append(distance)
        assert abs(max(measured)-access['max_distance_m']) < 1e-7
        skeleton = candidate['stages']['skeleton']
        nodes = {n['id']:shape(n['geometry']) for n in skeleton['nodes']}
        for edge in skeleton['edges']:
            coords = shape(edge['geometry']).coords
            from shapely.geometry import Point
            assert Point(coords[0]).distance(nodes[edge['from_node_id']]) < 1e-7
            assert Point(coords[-1]).distance(nodes[edge['to_node_id']]) < 1e-7
            assert edge['width_m'] in (4.5,6,14)


def test_remote_block_rejected_before_placement():
    import pytest
    from urban_design.generation.block_program import geometry_value
    from urban_design.generation.contracts import ProgramBlock
    from urban_design.generation.formal_placement import place_program
    blocks = NS(blocks=(ProgramBlock(id='remote', geometry=geometry_value(box(200,200,300,300))),))
    road = NS(geometry=NS(model_dump=lambda: mapping(LineString([(0,0),(0,100)]))), width_m=6)
    with pytest.raises(ValueError, match='road-accessible'):
        place_program(blocks, angle=0, zones=[{'zone_id':'z','target_use':'Residential','geometry':mapping(box(0,0,400,400))}],
                      recipe_id='remote', seed=42, target_gfa_m2=100000, road_edges=(road,))


def test_access_boundary_half_width_and_detached_members():
    from shapely.geometry import MultiPolygon
    from urban_design.generation.road_access import road_surface, footprint_access_distance, road_access_metrics
    edge = NS(geometry=NS(model_dump=lambda: mapping(LineString([(0,0),(0,100)]))), width_m=6)
    roads = road_surface((edge,))
    at_limit = box(43,20,53,30)
    assert footprint_access_distance(at_limit, roads) == 40
    assert road_access_metrics([at_limit], roads)['accessible_count'] == 1
    assert road_access_metrics([box(43.01,20,53,30)], roads)['accessible_count'] == 0
    detached = MultiPolygon([box(4,20,14,30), box(80,20,90,30)])
    assert footprint_access_distance(detached, roads) == 77
    assert road_access_metrics([detached], roads)['accessible_count'] == 0


def test_pipeline_rejects_inaccessible_massing_even_if_placement_is_bypassed(monkeypatch):
    from shapely import affinity
    from urban_design.generation.block_program import geometry_value
    import urban_design.generation.formal_pipeline as pipeline
    original = pipeline.build_massing
    def displaced(*args, **kwargs):
        artifact = original(*args, **kwargs)
        first, *rest = artifact.buildings
        first = first.model_copy(update={'footprint':geometry_value(affinity.translate(shape(first.footprint.model_dump()),10000,10000))})
        return artifact.model_copy(update={'buildings':(first,*rest)})
    monkeypatch.setattr(pipeline, 'build_massing', displaced)
    result = pipeline.run_formal_pipeline(*fixture())
    for candidate in result['candidates']:
        assert candidate['status'] == 'INVALID'
        assert any('road access:' in reason for reason in candidate['failure_reasons'])
        assert candidate['metrics']['road_access']['accessible_count'] < candidate['metrics']['road_access']['total_new_buildings']
        checks = candidate['stages']['massing']['validation']['checks']
        assert next(c['status'] for c in checks if c['check_id']=='road_access') == 'FAIL'
