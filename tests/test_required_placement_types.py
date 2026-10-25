"""Candidate-local preferences cannot displace required dictionary diversity."""
from shapely.geometry import box, shape
from test_formal_dictionary_pipeline import fixture
from urban_design.generation.block_program import build_block_program, geometry_value
from urban_design.generation.formal_pipeline import approved_parameters, skeleton_inputs
from urban_design.generation.formal_placement import place_program, TYPES
from urban_design.generation.legacy_profile_adapter import generate_legacy_profile
from urban_design.generation.skeleton import build_skeleton
from urban_design.generation.strategy_catalog import build_strategy_catalog
from types import SimpleNamespace


def test_required_types_precede_repeated_preferred_slabs():
    context, manifest, inputs = fixture()
    context = context.model_copy(update={'method_parameters': {
        **context.method_parameters, **approved_parameters(inputs),
        'grid_spacing_m': 100., 'grid_alignment_deg': 0.}})
    strategy = build_strategy_catalog(SimpleNamespace(intents=())).strategies[0]
    skeleton = build_skeleton(context, strategy, skeleton_inputs(inputs, context)).artifact
    blocks = build_block_program(context, skeleton, geometry_value(inputs.design_area),
        strategy_id='required-types', ground_use='UNALLOCATED')
    # Author a tight fixture budget for one complete envelope of each type
    # plus a slab. Every possible slab gets a preference, so the old ordering
    # repeatedly picked slabs and exhausted the required-type budget.
    dimensions = ((40., 40.), (32., 32.), (40., 24.), (56., 56.))
    target = 1920. + sum(5 * generate_legacy_profile(type_id,
        box(-w/2, -d/2, w/2, d/2), {'rotation_deg': 0},
        crs='EPSG:28992', coordinate_unit='m').geometry.area
        for type_id, (w, d) in zip(TYPES, dimensions))
    preferred = {box(x*8-20, y*8-12, x*8+20, y*8+12).wkb_hex
        for x in range(76) for y in range(51)}
    packed, recipes, _ = place_program(blocks, angle=0, zones=manifest.zones,
        recipe_id='required-types', seed=42, target_gfa_m2=target, floor_count=5,
        road_edges=skeleton.edges, minimum_types=4, preferred_cells=preferred)
    assert {recipe.type_id for recipe in recipes.values()} == set(TYPES)
    assert all(shape(block.geometry.model_dump()).area > 0 for block in packed.blocks)
