import pytest
from shapely.geometry import box, Polygon, MultiPolygon
from urban_design.generation.legacy_profile_adapter import generate_legacy_profile


def profile(type_id, width=40, depth=40):
    return generate_legacy_profile(type_id, box(-width/2,-depth/2,width/2,depth/2),
        {'rotation_deg':0}, crs='EPSG:28992', coordinate_unit='m').geometry


def test_adapter_uses_preserved_w5_template_operator():
    from urban_design.morphology.dictionary_generator import _template_geometry
    from urban_design.morphology_dictionary import load_dictionary
    for type_id, width, depth in [('building.courtyard_closed',40,40),('building.l_block',32,32),
                                  ('building.i_slab',40,24),('building.point_array',56,56)]:
        entry=next(e for e in load_dictionary()['entries'] if e['id']==type_id)
        shapes,_=_template_geometry(box(-width/2,-depth/2,width/2,depth/2),entry,
            seed_text='reference',recipe={'building_edge_setback_m':2})
        from shapely.ops import unary_union
        assert profile(type_id,width,depth).equals(unary_union(shapes))


def test_four_profiles_preserve_semantics():
    court=profile('building.courtyard_closed')
    assert isinstance(court,Polygon) and len(court.interiors)==1
    assert court.area==pytest.approx(36*36*.66)
    l=profile('building.l_block',32,32)
    assert l.area==pytest.approx(2*28*(28*.22)-(28*.22)**2)
    assert isinstance(l,Polygon) and not l.equals(l.envelope) and not l.interiors
    bar=profile('building.i_slab',40,24)
    assert bar.equals(bar.envelope) and bar.area==pytest.approx(32*12)
    points=profile('building.point_array',56,56)
    assert isinstance(points,MultiPolygon) and len(points.geoms)==4
    assert all(g.area==pytest.approx(225) for g in points.geoms)
    assert min(a.distance(b) for i,a in enumerate(points.geoms) for b in list(points.geoms)[i+1:])==pytest.approx(17)


def test_adapter_rejects_clipped_or_missing_semantics():
    with pytest.raises(ValueError,match='cannot satisfy'):
        profile('building.courtyard_closed',32,32)
    with pytest.raises(ValueError,match='rectangular'):
        generate_legacy_profile('building.l_block',box(0,0,40,40).difference(box(0,0,10,10)),
            {'rotation_deg':0},crs='EPSG:28992',coordinate_unit='m')
    with pytest.raises(ValueError,match='unsupported'):
        profile('building.invented')


def test_grid_generator_connects_actual_groups_not_adjacent_atomic_lines():
    from shapely.geometry import LineString, GeometryCollection
    from urban_design.generation.skeleton import _connect_components, _RoadPath, _effective_component_count
    paths=[_RoadPath(LineString([(10,10),(40,10)]),'LOCAL','road_local_width_m'),
           _RoadPath(LineString([(40,10),(40,40)]),'LOCAL','road_local_width_m'),
           _RoadPath(LineString([(70,70),(90,70)]),'LOCAL','road_local_width_m')]
    connected=_connect_components(paths,site=box(0,0,100,100),obstacles=GeometryCollection(),
        width_m=6,clearance_m=.25,strategy_id='regression')
    assert len(connected)>3
    assert _effective_component_count([p.geometry for p in connected],[0]*len(connected),[])==1
