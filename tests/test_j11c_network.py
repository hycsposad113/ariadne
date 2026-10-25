"""J11c geometry regressions use real construction, never provider mocks."""
from shapely.geometry import Point, LineString, box, shape
from shapely.ops import unary_union
from urban_design.generation import multimodal_network as n


def entry(identity,xy,weight=1):
    return n.Entrance(id=identity,coordinates=xy,modes=['pedestrian','bicycle'],source_ids={},weight=weight)


def test_compound_internal_loop_removed_even_when_matched_by_diagnosis():
    ring=list(Point(100,100).buffer(10,quad_segs=4).exterior.coords)
    features=[{'id':str(i),'geometry':{'type':'LineString','coordinates':cs},'properties':{'highway':'footway'}} for i,cs in enumerate((ring[:9],ring[8:]))]
    rows=n.classify_existing(features,box(0,0,240,240),n.NetworkRules(),destination_routes=[LineString(ring)])
    assert all(d.disposition=='removed' for d in rows)


def test_radial_single_core_across_land_parts_and_area():
    land=unary_union([box(0,0,300,240),box(0,-100,300,-40)])
    v=n.generate_variants(land,[],[entry('north',(150,240)),entry('east',(300,120)),entry('west',(0,120))],'radial',n.NetworkRules())[0]
    assert len(v.parameters['central_core'])==1
    assert 1500<=shape(v.parameters['central_core'][0]).area<=3000


def test_radial_major_entries_ring_and_distinct_spokes():
    entries=[entry('north',(150,300),3),entry('east',(300,150),2),entry('west',(0,150)),entry('south',(150,0))]
    v=n.generate_variants(box(0,0,300,300),[],entries,'radial',n.NetworkRules())[0]
    core=shape(v.parameters['central_core'][0]);ring=core.boundary
    spokes=[r for r in v.roads if ':radial-spoke:' in r.id]
    assert len(spokes)==len(entries)
    assert all(LineString(r.coordinates).distance(ring)<1e-6 for r in spokes)
    assert all(LineString(r.coordinates).distance(Point(e.coordinates))<1e-6 for e,r in zip(entries,spokes))
    assert all(LineString(a.coordinates).intersection(LineString(b.coordinates)).length<1e-6 for i,a in enumerate(spokes) for b in spokes[:i])


def test_service_does_not_circle_each_retained_building():
    site=box(0,0,300,160);obstacles=[box(60,60,80,80),box(150,60,170,80)]
    v=n.generate_variants(site,obstacles,[entry('north',(150,160))],'green_service',n.NetworkRules())[0]
    service=[LineString(r.coordinates) for r in v.roads if 'motor_vehicle' in r.modes]
    assert sum(g.is_ring for g in service)==1
    assert all(g.length<=40 for g in service if not g.is_ring)


def test_connect_fixed_disconnected_retained_routes_before_placement():
    fixed=n._road(LineString([(40,90),(40,110)]),'fixed',n.NetworkRules()).model_copy(update={'origin':'retained','source_road_ids':['fixed']})
    v=n.generate_variants(box(0,0,240,240),[],[], 'grid',n.NetworkRules(),fixed_roads=[fixed])[0]
    q=n.geometry_quality(box(0,0,240,240),[fixed,*v.roads],[],[],n.NetworkRules())
    assert q['connected_component_count']==1


def test_connect_land_circuits_around_obstacle_not_through_it():
    domain=box(0,0,200,200).difference(box(90,0,110,140))
    lines=[LineString([(30,30),(30,100)]),LineString([(170,30),(170,100)])]
    bridges,failures=n.connect_support(lines,domain,n.NetworkRules())
    assert not failures and len(bridges)==1
    assert domain.buffer(1e-7).covers(bridges[0])
    assert all(bridges[0].distance(g)<1e-6 for g in lines)


def test_safe_cleanup_merges_submetre_collinear_vertices_without_crossing_obstacle():
    line=LineString([(0,0),(10,0),(10.2,0),(20,0)])
    clean=n.clean_path(line,box(-1,-1,21,1),n.NetworkRules())
    assert list(clean.coords)==[(0,0),(20,0)]
    blocked=LineString([(0,0),(0,10),(10,10),(10,0)])
    clean=n.clean_path(blocked,box(-1,-1,11,11).difference(box(1,-1,9,9)),n.NetworkRules())
    assert clean.equals(blocked)


def test_quality_rejects_short_fragment_created_by_fixed_intersection():
    rules=n.NetworkRules()
    main=n._road(LineString([(0,0),(100,0)]),'main',rules)
    fixed=n._road(LineString([(1,-50),(1,50)]),'fixed',rules).model_copy(update={'origin':'retained','source_road_ids':['source']})
    q=n.geometry_quality(box(-10,-60,110,60),[main,fixed],[box(10,10,70,50)],[],rules)
    assert not q['minimum_segment_pass']
    assert any(s['length_m']==1 for s in q['short_segments'])


def test_mode_reconciliation_does_not_use_motor_only_road_as_walk_connection():
    rules=n.NetworkRules()
    roads=[n._road(LineString([(10,20),(40,20)]),'left',rules),n._road(LineString([(60,20),(90,20)]),'right',rules),n._road(LineString([(40,20),(60,20)]),'motor',rules).model_copy(update={'modes':['motor_vehicle']})]
    added,errors=n.connect_modes(roads,box(0,0,100,100),rules,'test')
    assert not errors and added
    walk=[LineString(r.coordinates) for r in [*roads,*added] if 'pedestrian' in r.modes]
    assert all(unary_union(walk).distance(g)<1e-6 for g in walk)
    q=n.geometry_quality(box(0,0,100,100),[r for r in [*roads,*added] if 'pedestrian' in r.modes],[],[],rules)
    assert q['connected_component_count']==1
