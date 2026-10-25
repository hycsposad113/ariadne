from datetime import datetime, timezone
import pytest
from shapely.geometry import box, mapping
from urban_design.generation.contracts import *
from urban_design.generation.hashing import semantic_digest, generation_context_digest, stage_seed
from urban_design.generation.massing_adapter import run_fixture_dictionary_pipeline


def ref(id):
    return FrozenRef(id=id, sha256=semantic_digest(id), kind="ILLUSTRATIVE_FIXTURE")


def fixture():
    values = {"diversity_min_difference_ratio":(0.01,"ratio"), "waterfront_band_m":(17,"m"), "retained_setback_m":(4,"m"), "standard_floor_height_m":(3.2,"m"), "first_floor_height_m":(4,"m"), "height_upper_bound_m":(30,"m"), "far_upper_bound":(4,"ratio")}
    context = GenerationContext(workspace_ref=ref("workspace"), analysis_ref=ref("analysis"), brief_ref=ref("brief"),
        crs="EPSG:28992", coordinate_unit="m", seed=42, generation_class="EXPLORATORY",
        method_parameters={k:{"value":v,"unit":u} for k,(v,u) in values.items()},
        assumptions=tuple(AssumptionSpec(id=k, statement="Synthetic test setting", source_kind="ILLUSTRATIVE_FIXTURE") for k in values))
    method=MethodProvenance(method_id="fixture-g2", version="1", description="synthetic connected G2", source_kind="REGISTERED_DETERMINISTIC_METHOD")
    validation=ValidationReport(geometry_status="PASS", topology_status="PASS", constraint_status="UNKNOWN", checks=(), unknowns=("FIXTURE_ONLY",), failures=())
    skeletons=[]
    recipes=[]
    profiles=[("building.h_plan",dict(width_m=80,depth_m=60,left_wing_width_m=15,right_wing_width_m=15,thickness_m=12)),
              ("building.e_plan",dict(width_m=80,depth_m=60,spine_thickness_m=12,wing_thickness_m=12)),
              ("building.comb",dict(spine_length_m=80,wing_depth_m=24,wing_count=4,gap_m=14,spine_thickness_m=10,wing_thickness_m=8))]
    for i,(type_id,parameters) in enumerate(profiles):
        id=f"fixture-{i}"
        x=180+i*90
        skeletons.append(SkeletonArtifact(artifact_id=id, context_hash=generation_context_digest(context), input_refs=(context.workspace_ref,), seed=stage_seed(context.seed,id,"skeleton"), algorithm_version="fixture-g2-v1", method=method, assumptions=context.assumptions, created_at=datetime(2026,1,1,tzinfo=timezone.utc),
            nodes=(SkeletonNode(id="a",geometry=dict(type="Point",coordinates=(x,0)),level=0,access="UNKNOWN"), SkeletonNode(id="b",geometry=dict(type="Point",coordinates=(x,600)),level=0,access="UNKNOWN")),
            edges=(SkeletonEdge(id="road",from_node_id="a",to_node_id="b",geometry=dict(type="LineString",coordinates=((x,0),(x,600))),level=0,access="UNKNOWN",width_m=12,width_ref=ref("width")),),
            primary_open_spaces=(OpenSpaceArtifact(id="park",geometry=mapping(box(10,10,40+i*10,40+i*10)),access_policy=AccessPolicy(status="UNKNOWN")),), retained_geometry_refs=(),connections=(),validation=validation))
        recipes.append(FixtureDictionaryRecipe(recipe_id=id,version="fixture-v1",source_ref=ref(id),type_id=type_id,geometry_parameters=parameters,floor_uses=("work","housing","housing")))
    return context, AreaGeometryValue(**mapping(box(0,0,600,600))), skeletons, recipes


def test_three_substantive_fixture_candidates_reproduce_and_measure_floors():
    args=fixture()
    result=run_fixture_dictionary_pipeline(*args)
    assert result.status == "FIXTURE_ONLY", result.model_dump()
    assert result.valid_count == 3
    assert all(d["substantive"] for d in result.pairwise_differences)
    assert result == run_fixture_dictionary_pipeline(*args)
    assert result.formal_status == "BLOCKED"
    for candidate in result.candidates:
        assert candidate.new_gfa_m2 == sum(candidate.floor_areas_m2)
        assert candidate.new_gfa_m2 == sum(candidate.program_gfa_m2.values())
        assert candidate.total_gfa_m2 == candidate.new_gfa_m2


def test_failure_retained_and_no_height_only_padding():
    context,site,skeletons,recipes=fixture()
    bad=recipes[0].model_copy(update={"type_id":"building.i_slab"})
    result=run_fixture_dictionary_pipeline(context,site,skeletons,[bad,*recipes[1:]])
    assert result.status == "FAIL" and result.valid_count == 2
    failed=result.candidates[0]
    assert failed.status == "FAIL" and failed.input_hash and failed.block_hash and failed.failure_reasons
    duplicates=[r.model_copy(update={"recipe_id":f"clone-{i}"}) for i,r in enumerate([recipes[0]]*3)]
    repeated=run_fixture_dictionary_pipeline(context,site,[skeletons[0]]*3,duplicates)
    assert repeated.status == "FAIL"


def test_unknown_retained_gfa_is_never_zero_and_formal_context_blocked():
    context,site,skeletons,recipes=fixture()
    retained=FixtureRetainedBuilding(source_ref=ref("retained"),geometry=mapping(box(550,550,560,560)))
    result=run_fixture_dictionary_pipeline(context,site,skeletons,recipes,retained_buildings=(retained,))
    assert result.valid_count == 3
    assert all(c.retained_gfa_m2 is None and c.total_gfa_m2 is None for c in result.candidates)
    assert all(c.massing.validation.constraint_status == StageStatus.UNKNOWN for c in result.candidates)
    assert run_fixture_dictionary_pipeline(context.model_copy(update={"generation_class":GenerationClass.APPROVED_INPUTS}),site,skeletons,recipes).status == "BLOCKED"


def test_context_mismatch_and_missing_parameter_fail_closed():
    context,site,skeletons,recipes=fixture()
    wrong=skeletons[0].model_copy(update={"context_hash":semantic_digest("wrong")})
    result=run_fixture_dictionary_pipeline(context,site,[wrong,*skeletons[1:]],recipes)
    assert result.candidates[0].status == "FAIL"
    assert "context hash mismatch" in result.candidates[0].failure_reasons[0]


def test_input_hashes_bind_site_water_retained_and_parameter_provenance():
    context,site,skeletons,recipes=fixture()
    baseline=run_fixture_dictionary_pipeline(context,site,skeletons,recipes)
    water=AreaGeometryValue(**mapping(box(0,590,600,600)))
    with_water=run_fixture_dictionary_pipeline(context,site,skeletons,recipes,water_geometry=water)
    assert all(a.input_hash != b.input_hash and a.block_hash != b.block_hash for a,b in zip(baseline.candidates,with_water.candidates))
    # Parameter removal remains a retained failure; it cannot silently default to 15 m.
    values=dict(context.method_parameters)
    values.pop("waterfront_band_m")
    changed=GenerationContext.model_validate({**context.model_dump(),"method_parameters":values})
    aligned=[s.model_copy(update={"context_hash":generation_context_digest(changed)}) for s in skeletons]
    failures=run_fixture_dictionary_pipeline(changed,site,aligned,recipes)
    assert all("waterfront_band_m" in c.failure_reasons[0] for c in failures.candidates)


def test_untrusted_pass_does_not_override_endpoint_geometry():
    context,site,skeletons,recipes=fixture()
    edge=skeletons[0].edges[0].model_copy(update={"geometry":LinearGeometryValue(type="LineString",coordinates=((180,1),(180,600)))})
    wrong=skeletons[0].model_copy(update={"edges":(edge,)})
    result=run_fixture_dictionary_pipeline(context,site,[wrong,*skeletons[1:]],recipes)
    assert "endpoint geometry/level mismatch" in result.candidates[0].failure_reasons[0]


def test_far_failure_retains_generated_massing_and_measurements():
    context,site,skeletons,recipes=fixture()
    values=dict(context.method_parameters)
    values["far_upper_bound"]={"value":0.001,"unit":"ratio"}
    context=GenerationContext.model_validate({**context.model_dump(),"method_parameters":values})
    aligned=[s.model_copy(update={"context_hash":generation_context_digest(context)}) for s in skeletons]
    result=run_fixture_dictionary_pipeline(context,site,aligned,recipes)
    assert result.status == "FAIL"
    assert all(c.massing and c.massing_hash and c.new_gfa_m2 > 0 and c.floor_areas_m2 for c in result.candidates)
    assert all(c.massing.validation.constraint_status == StageStatus.FAIL and c.massing.validation.failures for c in result.candidates)


def test_sourced_clearances_measured_and_direct_approved_massing_blocked():
    from shapely.geometry import shape
    from urban_design.generation.massing_adapter import build_massing
    context,site,skeletons,recipes=fixture()
    water=AreaGeometryValue(**mapping(box(0,590,600,600)))
    retained=FixtureRetainedBuilding(source_ref=ref("retained"),geometry=mapping(box(550,550,560,560)))
    result=run_fixture_dictionary_pipeline(context,site,skeletons,recipes,water_geometry=water,retained_buildings=(retained,))
    assert result.valid_count == 3
    for candidate in result.candidates:
        for building in candidate.massing.buildings:
            footprint=shape(building.footprint.model_dump())
            assert footprint.distance(shape(water.model_dump())) >= 17
            assert footprint.distance(shape(retained.geometry.model_dump())) >= 4
    with pytest.raises(ValueError,match="BLOCKED"):
        build_massing(context.model_copy(update={"generation_class":GenerationClass.APPROVED_INPUTS}),result.candidates[0].block_program,recipes[0])


@pytest.mark.parametrize("crossing",[False,True])
def test_disconnected_and_unnoded_crossing_reject_untrusted_pass(crossing):
    context,site,skeletons,recipes=fixture()
    old=skeletons[0]
    node_c=SkeletonNode(id="c",geometry=dict(type="Point",coordinates=(0,300)),level=0,access="UNKNOWN")
    node_d=SkeletonNode(id="d",geometry=dict(type="Point",coordinates=(600,300)),level=0,access="UNKNOWN")
    edge=SkeletonEdge(id="cross",from_node_id="c",to_node_id="d",geometry=dict(type="LineString",coordinates=((0,300),(600,300))),level=0,access="UNKNOWN",width_m=12,width_ref=ref("width"))
    if crossing:
        # Connect graph by an extra correctly noded branch; crossing itself lacks node.
        branch=SkeletonEdge(id="branch",from_node_id="a",to_node_id="c",geometry=dict(type="LineString",coordinates=((180,0),(0,300))),level=0,access="UNKNOWN",width_m=12,width_ref=ref("width"))
        edges=(*old.edges,edge,branch)
    else:
        edges=(*old.edges,edge)
    wrong=old.model_copy(update={"nodes":(*old.nodes,node_c,node_d),"edges":edges})
    result=run_fixture_dictionary_pipeline(context,site,[wrong,*skeletons[1:]],recipes)
    expected="without a shared node" if crossing else "disconnected"
    assert expected in result.candidates[0].failure_reasons[0]


def test_tiny_geometry_changes_do_not_pad_substantive_candidates():
    from shapely.affinity import translate
    from shapely.geometry import shape
    context,site,skeletons,recipes=fixture()
    skeletons=[skeletons[0]]*3
    modified=[]
    clones=[]
    for i in range(3):
        dx=i*0.001
        original=skeletons[i]
        nodes=tuple(n.model_copy(update={"geometry":PointGeometryValue(**mapping(translate(shape(n.geometry.model_dump()),xoff=dx)))}) for n in original.nodes)
        edges=tuple(e.model_copy(update={"geometry":LinearGeometryValue(**mapping(translate(shape(e.geometry.model_dump()),xoff=dx)))}) for e in original.edges)
        spaces=tuple(s.model_copy(update={"geometry":AreaGeometryValue(**mapping(translate(shape(s.geometry.model_dump()),xoff=dx)))}) for s in original.primary_open_spaces)
        modified.append(original.model_copy(update={"nodes":nodes,"edges":edges,"primary_open_spaces":spaces}))
        clones.append(recipes[0].model_copy(update={"recipe_id":f"tiny-{i}"}))
    result=run_fixture_dictionary_pipeline(context,site,modified,clones)
    assert result.valid_count == 3 and result.status == "FAIL"
    assert all(not d["substantive"] for d in result.pairwise_differences)
