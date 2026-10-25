"""Founder collector geometry, independent of placement and live state."""
from types import SimpleNamespace as NS

from shapely import affinity
from shapely.geometry import LineString, box, shape
from shapely.ops import unary_union

from urban_design.generation.skeleton import _RoadPath, _south_strip_collector


def test_collector_is_aligned_connected_and_width_clear_after_rd_transform():
    angle = 30
    transform = lambda g: affinity.translate(affinity.rotate(g, angle, origin=(0, 0)), 88000, 435000)
    site = transform(box(0, 0, 600, 240))
    retained = transform(box(60, 10, 150, 60))
    waterfront = transform(box(0, 0, 600, 15))
    common = transform(box(260, 150, 300, 190))
    original = [_RoadPath(transform(LineString([(10, 200), (590, 200)])), 'SPINE', 'road_collector_width_m')]
    inputs = NS(site_geometry=site, retained_geometries=(retained,), no_build_geometries=(),
                water_geometries=(), collector_exclusion_geometries=(waterfront,))
    context = NS(method_parameters={'grid_alignment_deg': angle})
    paths = _south_strip_collector(context, NS(strategy_id='synthetic'), inputs, original, (common,), 14, .25)
    replay = _south_strip_collector(context, NS(strategy_id='synthetic'), inputs, original, (common,), 14, .25)
    assert [p.geometry.wkb_hex for p in paths] == [p.geometry.wkb_hex for p in replay]
    new = paths[len(original):]
    collector = next(p.geometry for p in new if p.road_class == 'SOUTH_STRIP_COLLECTOR')
    local = affinity.rotate(collector, -angle, origin=(0, 0))
    assert abs(local.bounds[3] - local.bounds[1]) < 1e-7
    assert collector.length > 500
    surface = unary_union([p.geometry.buffer(7, cap_style=2) for p in new])
    assert surface.intersection(retained.buffer(3)).area < 1e-6
    assert surface.intersection(waterfront).area < 1e-6
    assert surface.intersection(common).area < 1e-6
    assert surface.difference(site).area < 1e-6
    network = unary_union([p.geometry for p in paths])
    # Each endpoint has a new connector that reaches an original edge.
    for point in (shape({'type':'Point','coordinates':collector.coords[0]}),
                  shape({'type':'Point','coordinates':collector.coords[-1]})):
        assert any(p.geometry.distance(point) < 1e-7 and p.geometry.distance(original[0].geometry) < 1e-7
                   for p in new if p.road_class == 'SOUTH_STRIP_CONNECTOR')
    assert not network.is_empty


def test_fallback_rebuild_preserves_founder_collector_class():
    from test_formal_dictionary_pipeline import fixture
    from urban_design.generation.formal_pipeline import approved_parameters, skeleton_inputs
    from urban_design.generation.skeleton import build_skeleton
    from urban_design.generation.strategy_catalog import build_strategy_catalog
    from urban_design.generation.road_access import rebuild_access_skeleton
    context, _, inputs = fixture()
    context = context.model_copy(update={'method_parameters':{**context.method_parameters,
        **approved_parameters(inputs), 'grid_alignment_deg':0}})
    resolved = skeleton_inputs(inputs, context)
    strategy = next(s for s in build_strategy_catalog(NS(intents=())).strategies
                    if s.topology_family=='CENTRAL_COMMON')
    base = build_skeleton(context, strategy, resolved).artifact
    rebuilt = rebuild_access_skeleton(context, strategy, resolved, base, [])
    classes = lambda artifact: {e.id.split(':')[1] for e in artifact.edges}
    assert 'south_strip_collector' in classes(base)
    assert classes(rebuilt) == classes(base)
    assert all(e.width_m==14 for e in rebuilt.edges if 'south_strip' in e.id)
