"""J16 geometry controls; synthetic dimensions are never formal site evidence."""
import pytest
from shapely.geometry import box, LineString
from shapely.ops import unary_union
from urban_design.generation import block_first as bf
from urban_design.generation.multimodal_network import NetworkRules


def test_all_parallel_buildable_bands_are_sampled_without_crossing_canal():
    assert hasattr(bf, 'strip_axes'), 'J16 strip core missing'
    domain = unary_union([box(0, 0, 400, 70), box(0, 100, 400, 180)])
    axes, meta = bf.strip_axes(domain, 'grid')
    mains = [a for a in axes if a['role'] != 'branch']
    assert len(mains) == 2
    assert all(domain.buffer(1e-6).covers(a['geometry']) for a in mains)
    assert all(a['geometry'].length >= 380 for a in mains)
    assert meta['sample_step_m'] == 10
    assert {round(s['width_m']) for s in meta['sections']} == {70, 80}


@pytest.mark.parametrize('width,kind', [(120,'both_perimeter'),(80,'mixed'),(50,'double_bar'),(30,'single')])
def test_width_class_drives_street_offset(width,kind):
    assert hasattr(bf, 'strip_axes'), 'J16 strip core missing'
    axes, meta = bf.strip_axes(box(0, 0, 400, width), 'axial')
    assert {s['class'] for s in meta['sections']} == {kind}
    line = axes[0]['geometry']
    if kind == 'mixed':
        y = line.interpolate(.5, normalized=True).y
        assert max(y-7.5, width-y-7.5) >= 44
        assert min(y-7.5, width-y-7.5) >= 12
    if kind == 'single':
        assert axes[0]['role'] == 'path'
    else:
        assert axes[0]['width_m'] == 15


def test_strip_frontage_uses_repeated_complete_envelopes():
    assert hasattr(bf, 'strip_axes'), 'J16 strip core missing'
    site = box(0,0,600,120)
    axes,meta = bf.strip_axes(site,'axial')
    blocks = bf.place_blocks(axes,site,box(1000,1000,1010,1010),{},NetworkRules())
    assert len(blocks) >= 12
    assert sum(b['profile'].geometry.area*4 for b in blocks) >= 50000
    assert all(site.covers(b['profile'].geometry) for b in blocks)
    surface = unary_union([a['geometry'].buffer(a['width_m']/2) for a in axes])
    assert all(not b['profile'].geometry.intersects(surface) for b in blocks)


def test_transverse_window_never_exceeds_ninety_metres():
    axes,meta=bf.strip_axes(box(0,0,210,50),'grid')
    assert all(60 <= s['window_m'] <= 90 for s in meta['strips'])


def test_tapered_strip_can_fill_frontage_instead_of_losing_entire_stations():
    from shapely.geometry import Polygon
    site=Polygon([(0,0),(600,0),(600,70),(300,100),(0,90)])
    axes,meta=bf.strip_axes(site,'axial')
    blocks=bf.place_blocks(axes,site,box(1000,1000,1010,1010),{},NetworkRules())
    assert len(blocks)>=10
    assert sum(b['profile'].geometry.area*4 for b in blocks)>35000


def test_curved_development_roads_are_straight_pst_sources_with_complete_lineage():
    from shapely.geometry import Polygon,shape
    site=Polygon([(0,0),(600,0),(600,70),(300,100),(0,90)])
    built=bf.build_structure(family='axial',site=site,water=box(1000,1000,1010,1010),retained={},entrances=[],fixed_roads=[],network_rules=NetworkRules())
    roads={r.id:r for r in built['roads']}
    assert all(len(r.coordinates)==2 for r in roads.values() if r.origin=='new')
    for d in built['development']:
        assert shape(d['geometry']).equals(LineString(roads[d['road_id']].coordinates))


def test_strategy_priority_responds_to_entrance_transit_and_external_integration():
    assert hasattr(bf,'strip_priority'), 'J16 strategy priority missing'
    common=dict(family='axial',centre_distance_m=100,main_strip=True,axis_gfa_m2=0)
    near=bf.strip_priority(entry_distance_m=10,transit_distance_m=10,baseline_percentile=90,**common)
    far=bf.strip_priority(entry_distance_m=200,transit_distance_m=200,baseline_percentile=10,**common)
    assert near>far
    a=bf.strip_priority(entry_distance_m=50,transit_distance_m=50,baseline_percentile=50,family='grid',centre_distance_m=50,main_strip=True,axis_gfa_m2=0)
    b=bf.strip_priority(entry_distance_m=50,transit_distance_m=50,baseline_percentile=50,family='grid',centre_distance_m=50,main_strip=True,axis_gfa_m2=10000)
    assert a>b


def test_short_tail_is_park_when_no_sixty_to_ninety_partition_exists():
    axes,meta=bf.strip_axes(box(0,0,105,45),'grid')
    assert all(60 <= s['window_m'] <= 90 for s in meta['strips'])
    assert all(a['geometry'].length<=90 for a in axes if a['role']!='branch')


def test_far_longitudinal_facade_cannot_cover_short_pst_road_segment():
    line=LineString([(0,0),(10,0)])
    measured=bf.frontage_assessment([line],[dict(type_id='building.rowhouse',geometry=box(100,9,160,21))],box(0,-80,200,80),road_half=7.5)
    assert measured['defining_edge_ratio']==0
    assert measured['qualified_bilateral_ratio']==0


def test_j16b_subdivision_returns_whole_land_polygons_before_massing():
    from shapely.geometry import Point
    site=box(0,0,400,120)
    axes,meta=bf.strip_axes(site,'axial')
    rules=NetworkRules()
    roads,development,public,failures=bf.roads_from_structure(
        axes,[],site,box(1000,1000,1010,1010),{},[],[],rules,family='axial',meta=meta)
    blocks=bf.strip_land_blocks(axes,roads,site,box(1000,1000,1010,1010),{},rules)
    surfaces=unary_union([LineString(r.coordinates).buffer(r.width_m/2+.001,join_style=2) for r in roads])
    expected=site.difference(surfaces)
    measured=unary_union([b['geometry'] for b in blocks])
    assert len(blocks)>=8
    assert all(2000<=b['geometry'].area<=9000 for b in blocks)
    assert expected.symmetric_difference(measured).area<.01
    assert all('profile' not in b for b in blocks)
    assert all(b['subdivision_method']=='BUILDABLE_LAND_MINUS_ROAD_SURFACES' for b in blocks)
    assert all(not b['geometry'].intersects(surfaces.buffer(-.0001)) for b in blocks)


def test_j16b_land_subdivision_preserves_irregular_boundary_and_retained_setback():
    from shapely.geometry import Polygon
    site=Polygon([(0,0),(400,0),(400,120),(180,135),(0,120)])
    kept={'hall':box(200,30,230,55)}
    built=bf.build_structure(family='grid',site=site,water=box(1000,1000,1010,1010),
        retained=kept,entrances=[],fixed_roads=[],network_rules=NetworkRules())
    assert built['blocks']
    assert all('profile' not in b for b in built['blocks'])
    assert all(site.covers(b['geometry']) for b in built['blocks'])
    assert all(not b['geometry'].intersects(kept['hall'].buffer(3)) for b in built['blocks'])
    assert any(b['geometry'].symmetric_difference(b['geometry'].minimum_rotated_rectangle).area>1
               for b in built['blocks'])
