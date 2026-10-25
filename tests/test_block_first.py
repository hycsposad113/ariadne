"""J15 block-first negative controls. Synthetic geometry is not site evidence."""
import pytest
from shapely.geometry import LineString, box, mapping
from shapely.ops import unary_union

from urban_design.generation.block_first import (
    VERSION, BlockFirstRules, build_structure, development_axes, drawing_guard,
    frontage_assessment, frontage_class, generate_block_first, place_blocks,
)
from urban_design.generation.massing_revision import facade_segments, streetwall_continuity
from urban_design.generation.multimodal_network import Entrance, NetworkRoad, NetworkRules, hard_checks
from urban_design.generation.network_massing_coupling import CouplingRules, merged_open_spaces
from urban_design.generation.type_registry import generate_streetwall_profile
from urban_design.scenario_syntax import digest


def road(id, coords, *, modes=('pedestrian', 'bicycle', 'motor_vehicle'), origin='new', layer=0, hierarchy='service'):
    return NetworkRoad(
        id=id, coordinates=coords, width_m=6, modes=list(modes), origin=origin, layer=layer,
        source_road_ids=[id] if origin == 'retained' else [], semantics_provenance='ILLUSTRATIVE_TEST',
        hierarchy='retained' if origin == 'retained' else hierarchy,
        width_class='city' if origin == 'retained' else 'service',
        access='service_only' if origin == 'new' else 'public', rule_card_ids=['test'],
    )


def entry(x, y, identity='e'):
    return Entrance(
        id=identity, coordinates=(x, y),
        modes=['pedestrian', 'bicycle', 'motor_vehicle'],
        source_ids={m: ['outside'] for m in ('pedestrian', 'bicycle', 'motor_vehicle')},
        weight=1,
    )


def external(site):
    feature = dict(id='outside', geometry=mapping(LineString([(-40, 150), (5, 150)])), properties={'layer': 0})
    east = dict(id='outside-e', geometry=mapping(LineString([(395, 150), (440, 150)])), properties={'layer': 0})
    return dict(_site=site, _water=box(0, 0, 400, 25), motor_vehicle=[feature, east], pedestrian=[feature, east], bicycle=[feature, east])


@pytest.mark.parametrize('field,value', [
    ('block_along_m', 59), ('block_depth_m', 43), ('block_min_m', 43),
    ('qualified_band_m', 39), ('defining_edge_min', 0.79), ('perimeter_outer_m', 45),
])
def test_block_first_size_gates_cannot_be_relaxed(field, value):
    with pytest.raises(ValueError):
        BlockFirstRules(**{field: value})


def test_j12c_quality_gates_remain_unrelaxed():
    with pytest.raises(ValueError):
        CouplingRules(bilateral_min=0.59)
    with pytest.raises(ValueError):
        CouplingRules(largest_park_min_m2=19999)
    with pytest.raises(ValueError):
        CouplingRules(remnant_max_m2=3001)


def test_one_sided_streetwall_ratio_is_zero():
    axis = LineString([(0, 0), (200, 0)])
    r = road('axis', list(axis.coords), modes=('pedestrian', 'bicycle'), hierarchy='main')
    north = generate_streetwall_profile(box(10, 4, 190, 60), wing_depth_m=12, setback_m=1)
    witnesses = [dict(type_id=north.type_id, facade_segments=facade_segments(north.geometry, [r], []))]
    assert streetwall_continuity([axis], witnesses)['streetwall_continuity_ratio'] == 0


def test_bilateral_perimeter_blocks_reach_assigned_streetwall_gate():
    axis = LineString([(0, 0), (200, 0)])
    r = road('axis', list(axis.coords), modes=('pedestrian', 'bicycle'), hierarchy='main')
    north = generate_streetwall_profile(box(10, 4, 190, 60), wing_depth_m=12, setback_m=1)
    south = generate_streetwall_profile(box(10, -60, 190, -4), wing_depth_m=12, setback_m=1)
    witnesses = [
        dict(type_id=p.type_id, facade_segments=facade_segments(p.geometry, [r], []))
        for p in (north, south)
    ]
    assert streetwall_continuity([axis], witnesses)['streetwall_continuity_ratio'] >= 0.6


def test_motor_surface_fragments_park_below_two_hectares():
    site = box(0, 0, 200, 200)
    water = box(500, 500, 520, 520)
    car = road('cut', [(100, 0), (100, 200)])
    ground, spaces, remnants = merged_open_spaces(site, water, [car], [], {})
    assert max((s['area_m2'] for s in spaces), default=0) < 20000
    assert len(spaces) >= 2


def test_shared_park_path_does_not_split_park():
    site = box(0, 0, 200, 200)
    water = box(500, 500, 520, 520)
    path = road('park', [(100, 0), (100, 200)], modes=('pedestrian', 'bicycle'))
    ground, spaces, remnants = merged_open_spaces(site, water, [path], [], {})
    assert len(spaces) == 1 and spaces[0]['area_m2'] == 40000 and not remnants


def test_building_on_road_fails_hard_overlap():
    site = box(0, 0, 200, 200)
    roads = [road('city', [(0, 100), (200, 100)], origin='retained')]
    building = box(90, 95, 110, 120)
    result = hard_checks(
        site=site, roads=roads, buildings=[building], retained_before={}, retained_after={},
        water=box(400, 400, 410, 410), entrances=[], external=external(site),
        rules=NetworkRules(), public_spaces=(),
    )
    assert result['checks']['road_overlap'] is False
    assert result['status'] == 'INVALID'


def test_fire_beyond_40m_fails_closed():
    site = box(0, 0, 200, 200)
    roads = [road('city', [(0, 0), (40, 0)], origin='retained')]
    building = box(150, 150, 170, 170)
    result = hard_checks(
        site=site, roads=roads, buildings=[building], retained_before={}, retained_after={},
        water=box(400, 400, 410, 410), entrances=[entry(0, 0)], external=external(site),
        rules=NetworkRules(), public_spaces=(),
    )
    assert result['checks']['fire_service'] is False


def test_invalid_or_forged_status_cannot_be_drawn():
    for row in [{}, {'status': 'INVALID'}, {'status': 'VALID', 'version': VERSION, 'buildings': [{}], 'checks': {'wall': False}}]:
        with pytest.raises(ValueError, match='figure output prohibited'):
            drawing_guard(row)


def test_axial_structure_places_blocks_on_both_sides():
    site = box(0, 40, 400, 300)
    water = box(0, 0, 400, 25)
    rules = NetworkRules()
    axes, meta = development_axes(
        'axial', site, water, {}, [entry(0, 150, 'w'), entry(400, 150, 'e')], rules,
    )
    assert axes
    blocks = place_blocks(axes, site, water, {}, rules)
    sides = {b['side'] for b in blocks}
    assert 1 in sides and -1 in sides
    assert len(blocks) >= 2


def test_green_service_axis_is_service_not_central_motor():
    site = box(0, 40, 400, 320)
    water = box(0, 0, 400, 25)
    axes, meta = development_axes(
        'green_service', site, water, {}, [entry(0, 180, 'w'), entry(400, 180, 'e')], NetworkRules(),
    )
    assert meta.get('green')
    assert axes and all(a['role'] == 'service' for a in axes)


def test_retained_footprint_is_not_invaded():
    site = box(0, 40, 400, 300)
    water = box(0, 0, 400, 25)
    kept = {'hall': box(180, 140, 220, 180)}
    built = build_structure(
        family='axial', site=site, water=water, retained=kept,
        entrances=[entry(0, 150, 'w'), entry(400, 150, 'e')],
        fixed_roads=[road('city', [(-20, 150), (20, 150)], origin='retained')],
        network_rules=NetworkRules(),
    )
    union = unary_union([b['geometry'] for b in built['blocks']]) if built['blocks'] else box(0, 0, 1, 1)
    assert union.intersects(kept['hall'].buffer(3)) is False or not built['blocks']


def _parameters():
    return dict(
        first_floor_height_m={'value': 4.5},
        standard_floor_height_m={'value': 3.5},
        height_upper_bound_m={'value': 20},
        far_upper_bound={'value': 0.8},
        coverage_upper_bound={'value': 0.35},
    )


def _zones(site):
    return [
        dict(zone_id='z-res', target_use='residential', geometry=mapping(box(0, 120, 400, 300))),
        dict(zone_id='z-mix', target_use='mixed', geometry=mapping(box(0, 80, 200, 160))),
        dict(zone_id='z-off', target_use='office', geometry=mapping(box(200, 80, 400, 160))),
        dict(zone_id='z-maker', target_use='maker', geometry=mapping(box(0, 40, 400, 90))),
    ]


def _fake_syntax(roads, site, rules):
    from urban_design.generation.multimodal_network import syntax_roads
    segs = []
    for r in syntax_roads(roads, 'pedestrian', rules):
        segs.append(dict(
            id=r.id, nain=1.0, nach=0.1, inside_site=True, coordinates=r.coordinates,
            source_line_id='proposal:' + r.id, distance_to_site_m=0,
        ))
    return dict(
        status='COMPUTED', mode='pedestrian', radius_m=800,
        road_input_sha256=digest([r.model_dump() for r in syntax_roads(roads, 'pedestrian', rules)]),
        site_sha256=digest(mapping(site)),
        after={'segments': segs, 'metrics': {'mean_integration_nain': 1.0}},
        before={'segments': segs, 'metrics': {'mean_integration_nain': 0.8}},
    )


def test_frontage_class_follows_buildable_width():
    rules = BlockFirstRules()
    assert frontage_class(60, 60, rules) == 'both_perimeter'
    assert frontage_class(50, 40, rules) == 'mixed'
    assert frontage_class(22, 22, rules) == 'double_bar'
    assert frontage_class(28, 8, rules) == 'single'
    assert frontage_class(18, 18, rules) == 'single'


def test_wide_street_without_facades_has_zero_bilateral_ratio():
    rules = BlockFirstRules()
    domain = box(0, -80, 200, 80)
    line = LineString([(0, 0), (200, 0)])
    measured = frontage_assessment([line], [], domain, rules, road_half=3.75)
    assert measured['eligible_length_m'] > 0
    assert measured['qualified_bilateral_ratio'] == 0
    assert measured['bilateral_gate'] is False
    assert measured['defining_edge_ratio'] == 0


def test_narrow_band_is_excluded_from_bilateral_denominator():
    from urban_design.generation.type_registry import generate_block_profile
    rules = BlockFirstRules()
    domain = box(0, -12, 80, 12)
    line = LineString([(0, 0), (80, 0)])
    profile = generate_block_profile('building.i_slab', box(4, 4, 76, 16), wing_depth_m=12)
    measured = frontage_assessment(
        [line], [dict(type_id=profile.type_id, geometry=profile.geometry)], domain, rules, road_half=3.75,
    )
    assert measured['eligible_length_m'] == 0
    assert measured['defining_edge_ratio'] >= 0.8
    assert measured['bilateral_gate'] is False


def test_single_sided_row_counts_as_defining_edge_not_bilateral():
    rules = BlockFirstRules()
    wide = box(0, -80, 80, 80)
    narrow = box(80, -12, 160, 12)
    domain = unary_union([wide, narrow])
    line = LineString([(0, 0), (160, 0)])
    bar = box(90, 4, 150, 16)
    from urban_design.generation.type_registry import generate_block_profile
    profile = generate_block_profile('building.i_slab', bar, wing_depth_m=12)
    measured = frontage_assessment(
        [line], [dict(type_id=profile.type_id, geometry=profile.geometry)], domain, rules, road_half=3.75,
    )
    assert measured['eligible_length_m'] > 0
    assert measured['qualified_bilateral_ratio'] == 0
    assert measured['defining_length_m'] > 0


def test_generate_block_first_uses_matching_syntax_and_reports_failures_without_drawing():
    site = box(0, 40, 400, 300)
    water = box(0, 0, 400, 25)
    rules = NetworkRules()
    built = build_structure(
        family='axial', site=site, water=water, retained={},
        entrances=[entry(0, 150, 'w'), entry(400, 150, 'e')],
        fixed_roads=[road('city', [(-40, 150), (20, 150)], origin='retained'), road('city-e', [(380, 150), (440, 150)], origin='retained')],
        network_rules=rules,
    )
    if not built['roads']:
        pytest.fail('structure produced no roads')
    syntax = _fake_syntax(built['roads'], site, rules)
    row = generate_block_first(
        family='axial', site=site, water=water, retained={},
        entrances=[entry(0, 150, 'w'), entry(400, 150, 'e')],
        fixed_roads=[road('city', [(-40, 150), (20, 150)], origin='retained'), road('city-e', [(380, 150), (440, 150)], origin='retained')],
        zones=_zones(site), syntax_document=syntax, network_rules=rules,
        denominator=site.difference(water).area, retained_gfa=0, parameters=_parameters(),
        external=external(site), structure=built,
    )
    assert row['version'] == VERSION
    assert row['status'] in ('VALID', 'INVALID')
    if row['status'] != 'VALID':
        with pytest.raises(ValueError, match='figure output prohibited'):
            drawing_guard(row)
        assert row['failure_reasons']
