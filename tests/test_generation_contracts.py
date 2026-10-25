from __future__ import annotations

from datetime import datetime, timezone
import math

import pytest
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union
import urban_design.generation.contracts as generation_contracts

from urban_design.generation.contracts import (
    AssumptionSourceKind,
    AssumptionSpec,
    BlockProgramArtifact,
    BuildingMassing,
    ConnectionRecord,
    FloorGeometry,
    FrozenRef,
    GenerationContext,
    GenerationClass,
    GeometryValue,
    MassingArtifact,
    MethodProvenance,
    MethodSourceKind,
    ProgramBlock,
    ProgramZone,
    RoadArtifact,
    SkeletonArtifact,
    StageStatus,
    ValidationReport,
)
from urban_design.generation.hashing import (
    geometry_request_payload,
    canonical_geometry_payload,
    generation_context_digest,
    project_request_to_context,
    semantic_digest,
    stage_artifact_digest,
    stage_seed,
)


def _ref(name: str, digit: str) -> FrozenRef:
    return FrozenRef(id=name, sha256=f"sha256:{digit * 64}", kind="SYNTHETIC_FIXTURE")


def _context(**overrides) -> GenerationContext:
    values = {
        "workspace_ref": _ref("workspace-fixture", "1"),
        "analysis_ref": _ref("analysis-fixture", "2"),
        "brief_ref": _ref("brief-fixture", "3"),
        "source_refs": [_ref("source-fixture", "4")],
        "constraint_refs": [_ref("constraint-fixture", "5")],
        "crs": "EPSG:28992",
        "coordinate_unit": "m",
        "seed": 17,
        "method_parameters": {"cell_width_m": 24.0},
        "assumptions": [
            AssumptionSpec(
                id="cell_width_m",
                statement="Synthetic fixture only",
                source_kind=AssumptionSourceKind.ILLUSTRATIVE_FIXTURE,
                source_refs=[_ref("fixture-source", "6")],
            )
        ],
        "generation_class": GenerationClass.EXPLORATORY,
    }
    values.update(overrides)
    return GenerationContext.model_validate(values)


def _method() -> MethodProvenance:
    return MethodProvenance(
        method_id="synthetic-grid-method",
        version="fixture-v1",
        description="Deterministic synthetic method",
        source_kind=MethodSourceKind.REGISTERED_DETERMINISTIC_METHOD,
        source_refs=[_ref("method-fixture", "7")],
    )


def _validation() -> ValidationReport:
    return ValidationReport(
        geometry_status=StageStatus.PASS,
        topology_status=StageStatus.UNKNOWN,
        constraint_status=StageStatus.NOT_RUN,
        checks=[],
        unknowns=["Synthetic fixture has no topology input"],
        failures=[],
    )


def _stage_kwargs() -> dict:
    return {
        "artifact_id": "artifact-fixture",
        "context_hash": generation_context_digest(_context()),
        "input_refs": [_ref("input-fixture", "8")],
        "seed": 17,
        "algorithm_version": "fixture-stage-v1",
        "method": _method(),
        "assumptions": _context().assumptions,
        "created_at": datetime(2026, 9, 30, tzinfo=timezone.utc),
    }


def test_request_projection_ignores_all_three_ui_modes_and_created_at():
    context_payload = _context().model_dump(mode="json")
    request = {**context_payload, "mode": "SKELETON_FIRST", "created_at": "fixture-time-A", "job_id": "job-A"}
    projections = [
        project_request_to_context({**request, "mode": mode, "created_at": f"fixture-time-{index}"})
        for index, mode in enumerate(("SKELETON_FIRST", "FULL_SCHEME", "STEPWISE"))
    ]

    assert projections[0] == projections[1] == projections[2]
    assert generation_context_digest(projections[0]) == generation_context_digest(projections[2])
    assert generation_context_digest({**request, "mode": "FULL_SCHEME"}) == generation_context_digest(
        {**request, "mode": "STEPWISE"}
    )
    assert not hasattr(projections[0], "mode")


def test_stage_hash_excludes_mode_and_timestamps():
    base = {
        "input_refs": [{"id": "site-fixture", "sha256": "sha256:" + "a" * 64, "kind": "PROJECT_DATA"}],
        "input_hash": "sha256:" + "b" * 64,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [4, 0], [4, 3], [0, 3], [0, 0]]],
            "crs": "EPSG:28992",
        },
        "seed": 17,
        "strategy_id": "fixture-grid",
        "algorithm_version": "fixture-v1",
        "method_parameters": {"spacing_m": 12},
    }
    first = {**base, "mode": "FULL_SCHEME", "created_at": "time-A", "job_id": "job-A"}
    second = {**base, "mode": "STEPWISE", "created_at": "time-B", "job_id": "job-B"}
    third = {**base, "mode": "SKELETON_FIRST", "created_at": "time-C", "job_id": "job-C"}

    assert geometry_request_payload(first) == geometry_request_payload(second)
    assert semantic_digest(geometry_request_payload(first)) == semantic_digest(geometry_request_payload(third))
    assert geometry_request_payload(first)["input_hash"] == base["input_hash"]
    assert geometry_request_payload(first)["geometry"] == canonical_geometry_payload(box(0, 0, 4, 3))
    assert semantic_digest(geometry_request_payload(first)) == semantic_digest(geometry_request_payload(second))
    assert semantic_digest(geometry_request_payload(first)) != semantic_digest(geometry_request_payload({**second, "seed": 18}))


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("input_refs", [_ref("site-b", "3")]),
        ("input_hash", "sha256:" + "4" * 64),
        ("geometry", box(0, 0, 5, 3)),
        ("seed", 18),
        ("strategy_id", "fixture-grid-v2"),
        ("algorithm_version", "fixture-v2"),
        ("method_parameters", {"spacing_m": 13}),
    ],
)
def test_geometry_request_digest_binds_each_computational_input(field, changed):
    base = {
        "input_refs": [_ref("site-a", "1")],
        "input_hash": "sha256:" + "2" * 64,
        "geometry": box(0, 0, 4, 3),
        "seed": 17,
        "strategy_id": "fixture-grid",
        "algorithm_version": "fixture-v1",
        "method_parameters": {"spacing_m": 12},
    }
    baseline = semantic_digest(geometry_request_payload(base))

    assert semantic_digest(geometry_request_payload({**base, field: changed})) != baseline


@pytest.mark.parametrize(
    ("reference_field", "changed"),
    [
        ("id", "site-b"),
        ("sha256", "sha256:" + "f" * 64),
        ("kind", "CONSTRAINT"),
    ],
)
def test_geometry_request_digest_binds_each_reference_semantic_field(reference_field, changed):
    reference = {"id": "site-a", "sha256": "sha256:" + "1" * 64, "kind": "PROJECT_DATA"}
    base = {
        "input_refs": [reference],
        "input_hash": "sha256:" + "2" * 64,
        "geometry": box(0, 0, 4, 3),
        "seed": 17,
        "strategy_id": "fixture-grid",
        "algorithm_version": "fixture-v1",
        "method_parameters": {"spacing_m": 12},
    }

    baseline = semantic_digest(geometry_request_payload(base))
    changed_reference = {**reference, reference_field: changed}

    assert semantic_digest(geometry_request_payload({**base, "input_refs": [changed_reference]})) != baseline


def test_generation_context_reference_collections_are_immutable():
    context = _context()

    assert isinstance(context.source_refs, tuple)
    with pytest.raises(AttributeError):
        context.source_refs.append(_ref("late-source", "9"))
    with pytest.raises(TypeError):
        context.method_parameters["cell_width_m"] = 99


def test_geometry_request_payload_requires_every_computational_input():
    incomplete = {
        "seed": 17,
        "strategy_id": "fixture-grid",
        "algorithm_version": "fixture-v1",
        "method_parameters": {},
    }

    try:
        geometry_request_payload(incomplete)
    except KeyError as error:
        assert error.args == ("input_refs",)
    else:
        raise AssertionError("missing input refs must fail closed")


def test_geometry_hash_canonicalizes_ring_orientation_and_start_vertex():
    first = Polygon([(0, 0), (4, 0), (4, 3), (0, 3), (0, 0)])
    reordered = Polygon([(4, 3), (4, 0), (0, 0), (0, 3), (4, 3)])

    assert canonical_geometry_payload(first) == canonical_geometry_payload(reordered)
    assert semantic_digest({"geometry": first}) == semantic_digest({"geometry": reordered})


def test_geometry_hash_canonicalizes_holes_and_multipolygon_component_order():
    first_component = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
        holes=[[(2, 2), (2, 3), (3, 3), (3, 2), (2, 2)]],
    )
    reordered_component = Polygon(
        [(10, 10), (10, 0), (0, 0), (0, 10), (10, 10)],
        holes=[[(3, 3), (2, 3), (2, 2), (3, 2), (3, 3)]],
    )
    other = box(20, 0, 21, 1)
    first = MultiPolygon([first_component, other])
    reordered = MultiPolygon([other, reordered_component])

    assert semantic_digest(first) == semantic_digest(reordered)


def test_geometry_hash_uses_projected_metre_crs_and_rejects_nonfinite_coordinates():
    with pytest.raises(ValueError, match="EPSG:28992|projected"):
        canonical_geometry_payload(box(0, 0, 4, 3), crs="EPSG:4326")

    nonfinite = Polygon([(0, 0), (1, 0), (math.nan, 1), (0, 0)])
    with pytest.raises(ValueError, match="finite"):
        canonical_geometry_payload(nonfinite)


def test_geometry_hash_rejects_crs_metadata_that_disagrees_with_projected_contract():
    geojson = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [4, 0], [4, 3], [0, 3], [0, 0]]],
        "crs": "EPSG:4326",
    }

    with pytest.raises(ValueError, match="CRS"):
        canonical_geometry_payload(geojson)


def test_hash_precision_rejects_a_narrow_corridor_that_would_split_connected_geometry():
    connected = unary_union(
        [box(0, 0, 5, 10), box(7, 0, 12, 10), box(5, 4.9998, 7, 5.0002)]
    )
    assert connected.geom_type == "Polygon" and connected.is_valid

    with pytest.raises(ValueError, match="topology|precision|collapse"):
        canonical_geometry_payload(connected)


def test_geometry_hash_precision_does_not_mutate_source_geometry():
    geometry = box(0.0004, 0, 1.0004, 1)
    source_coordinates = tuple(geometry.exterior.coords)

    canonical_geometry_payload(geometry)

    assert tuple(geometry.exterior.coords) == source_coordinates


def test_geometry_hash_rejects_a_polygon_collapsed_by_hash_precision():
    narrow = box(0, 0, 0.0004, 2)

    try:
        canonical_geometry_payload(narrow)
    except ValueError as error:
        assert "precision" in str(error).lower() or "collapse" in str(error).lower()
    else:
        raise AssertionError("precision normalization must not silently collapse geometry")


def test_stage_seed_is_stable_and_derived_per_strategy_and_stage():
    assert stage_seed(17, "fixture-grid", "skeleton") == stage_seed(17, "fixture-grid", "skeleton")
    assert stage_seed(17, "fixture-grid", "skeleton") != stage_seed(17, "fixture-grid", "massing")


def test_created_at_does_not_change_stage_artifact_digest():
    artifact = SkeletonArtifact(
        **_stage_kwargs(),
        nodes=[],
        edges=[],
        primary_open_spaces=[],
        retained_geometry_refs=[],
        connections=[],
        validation=_validation(),
    )
    later = artifact.model_copy(update={"created_at": datetime(2026, 10, 1, tzinfo=timezone.utc)})

    assert stage_artifact_digest(artifact) == stage_artifact_digest(later)
    payload = artifact.model_dump(mode="json")
    assert stage_artifact_digest({**payload, "mode": "FULL_SCHEME", "job_id": "job-A"}) == stage_artifact_digest(
        {**payload, "mode": "STEPWISE", "job_id": "job-B"}
    )


def test_stage_artifacts_each_round_trip_as_typed_json():
    skeleton = SkeletonArtifact(
        **_stage_kwargs(),
        nodes=[],
        edges=[],
        primary_open_spaces=[],
        retained_geometry_refs=[],
        connections=[],
        validation=_validation(),
    )
    blocks = BlockProgramArtifact(
        **{**_stage_kwargs(), "artifact_id": "blocks-fixture"},
        parent_skeleton_ref=_ref("skeleton-fixture", "9"),
        blocks=[ProgramBlock(id="block-fixture", geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]})],
        zones=[ProgramZone(id="zone-fixture", geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}, use="mixed")],
        frontages=[],
        program_allocations=[],
        unallocated_areas=[],
    )
    massing = MassingArtifact(
        **{**_stage_kwargs(), "artifact_id": "massing-fixture"},
        parent_block_ref=_ref("blocks-fixture", "a"),
        buildings=[
            BuildingMassing(
                id="building-fixture",
                footprint={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                floors=[
                    FloorGeometry(
                        level=0,
                        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                        floor_height_m=3.5,
                        use="retail",
                    ),
                    FloorGeometry(
                        level=1,
                        geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
                        floor_height_m=3.0,
                        use="office",
                    ),
                ],
                height_m=3.5,
                use="mixed",
                type_id="building.fixture",
                variant_id="fixture",
            )
        ],
        retained_refs=[],
        validation=_validation(),
    )

    for model_type, value in (
        (SkeletonArtifact, skeleton),
        (BlockProgramArtifact, blocks),
        (MassingArtifact, massing),
    ):
        assert model_type.model_validate_json(value.model_dump_json()) == value

    assert [(floor.level, floor.floor_height_m, floor.use) for floor in massing.buildings[0].floors] == [
        (0, 3.5, "retail"),
        (1, 3.0, "office"),
    ]


def test_methods_and_assumptions_retain_source_kinds_in_serialized_context():
    context = _context()
    encoded = context.model_dump(mode="json")

    assert encoded["assumptions"][0]["source_kind"] == "ILLUSTRATIVE_FIXTURE"
    assert _method().model_dump(mode="json")["source_kind"] == "REGISTERED_DETERMINISTIC_METHOD"
    assert "A2" in (GenerationContext.__doc__ or "")


def test_context_and_geometry_contracts_reject_invalid_crs_boolean_seed_and_empty_geometry():
    with pytest.raises(ValueError, match="EPSG:28992"):
        _context(crs="EPSG:4326")
    with pytest.raises(ValueError, match="seed"):
        _context(seed=True)
    with pytest.raises(ValueError, match="non-empty|positive|valid"):
        GeometryValue(type="Polygon", coordinates=[])


def test_generation_class_is_a_closed_typed_contract():
    assert _context(generation_class=GenerationClass.APPROVED_INPUTS).generation_class is GenerationClass.APPROVED_INPUTS
    with pytest.raises(ValueError, match="generation_class"):
        _context(generation_class="UNVERIFIED_INPUTS")


def test_road_stage_contract_rejects_area_geometry():
    with pytest.raises(ValueError):
        RoadArtifact(
            id="road-fixture",
            from_node_id="node-a",
            to_node_id="node-b",
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            level=0,
            access="proposed",
        )


def test_skeleton_edge_rejects_area_geometry_independently():
    edge_model = getattr(generation_contracts, "SkeletonEdge", None)
    assert edge_model is not None

    with pytest.raises(ValueError, match="LineString|MultiLineString|type"):
        edge_model(
            id="bad-edge",
            from_node_id="node-a",
            to_node_id="node-b",
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            level=0,
            access="unknown",
        )


def test_skeleton_contract_has_typed_nodes_edges_and_explicit_open_space_access():
    node_model = getattr(generation_contracts, "SkeletonNode", None)
    edge_model = getattr(generation_contracts, "SkeletonEdge", None)
    open_space_model = getattr(generation_contracts, "OpenSpaceArtifact", None)
    access_policy_model = getattr(generation_contracts, "AccessPolicy", None)
    access_status = getattr(generation_contracts, "AccessStatus", None)
    assert node_model is not None and edge_model is not None
    assert open_space_model is not None and access_policy_model is not None and access_status is not None
    assert {"nodes", "edges"} <= set(SkeletonArtifact.model_fields)

    nodes = [
        node_model(id="node-a", geometry={"type": "Point", "coordinates": [0, 0]}, level=0, access="unknown"),
        node_model(id="node-b", geometry={"type": "Point", "coordinates": [10, 0]}, level=0, access="unknown"),
    ]
    edge = edge_model(
        id="edge-ab",
        from_node_id="node-a",
        to_node_id="node-b",
        geometry={"type": "LineString", "coordinates": [[0, 0], [10, 0]]},
        level=0,
        access="unknown",
        width_m=6,
        width_ref=_ref("width-policy", "a"),
    )
    open_space = open_space_model(
        id="open-fixture",
        geometry={
            "type": "Polygon",
            "coordinates": [
                [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]],
                [[4, 4], [4, 6], [6, 6], [6, 4], [4, 4]],
            ],
        },
        access_policy=access_policy_model(status=access_status.UNKNOWN),
    )
    artifact = SkeletonArtifact(
        **_stage_kwargs(),
        nodes=nodes,
        edges=[edge],
        primary_open_spaces=[open_space],
        retained_geometry_refs=[],
        connections=[ConnectionRecord(id="connection-ab", from_node_id="node-a", to_node_id="node-b", level=0, status="fixture")],
        validation=_validation(),
    )

    assert artifact.edges[0].width_ref.id == "width-policy"
    assert artifact.primary_open_spaces[0].access_policy.status is access_status.UNKNOWN
    with pytest.raises(ValueError, match="node"):
        SkeletonArtifact(
            **_stage_kwargs(),
            nodes=nodes,
            edges=[edge_model.model_validate({**edge.model_dump(), "to_node_id": "missing-node"})],
            primary_open_spaces=[open_space],
            retained_geometry_refs=[],
            connections=[],
            validation=_validation(),
        )

    with pytest.raises(ValueError, match="source|reference"):
        access_policy_model(status=access_status.PUBLIC, source_refs=[])


def test_floor_geometry_records_each_floor_height_and_use_and_rejects_zero_height():
    assert {"floor_height_m", "use"} <= set(FloorGeometry.model_fields)
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    floor = FloorGeometry(level=0, geometry=geometry, floor_height_m=3.5, use="retail")

    assert floor.floor_height_m == 3.5
    assert floor.use == "retail"
    with pytest.raises(ValueError, match="floor_height_m"):
        FloorGeometry(level=0, geometry=geometry, floor_height_m=0, use="retail")
    with pytest.raises(ValueError, match="use"):
        FloorGeometry(level=0, geometry=geometry, floor_height_m=3.5, use=" ")


def test_skeleton_node_rejects_nonpoint_geometry():
    node_model = getattr(generation_contracts, "SkeletonNode", None)
    assert node_model is not None

    with pytest.raises(ValueError, match="Point|type"):
        node_model(
            id="bad-node",
            geometry={"type": "LineString", "coordinates": [[0, 0], [1, 0]]},
            level=0,
            access="unknown",
        )


def test_transform_audit_records_forward_inverse_and_roundtrip_status_without_claiming_proof():
    audit_model = getattr(generation_contracts, "CoordinateTransformAudit", None)
    assert audit_model is not None
    audit = audit_model(
        source_crs="EPSG:4326",
        target_crs="EPSG:28992",
        forward_operation_id="registered.forward.v1",
        inverse_operation_id="registered.inverse.v1",
        axis_order="xy",
        horizontal_unit="m",
        source_ref=_ref("source-geometry", "b"),
        output_ref=_ref("projected-geometry", "c"),
        roundtrip_check_ref=_ref("roundtrip-check", "d"),
        roundtrip_status=StageStatus.UNKNOWN,
    )
    context = _context(coordinate_transforms=[audit])

    assert context.coordinate_transforms[0].inverse_operation_id == "registered.inverse.v1"
    assert context.coordinate_transforms[0].roundtrip_status is StageStatus.UNKNOWN
    with pytest.raises(ValueError, match="roundtrip"):
        audit_model(**{**audit.model_dump(), "roundtrip_status": StageStatus.PASS})


def test_strategy_contract_is_registered_data_and_rejects_callable_policy():
    strategy_model = getattr(generation_contracts, "StrategySpec", None)
    assert strategy_model is not None
    assert "registered_method" in strategy_model.model_fields
    strategy_model(
        strategy_id="fixture-strategy",
        topology_family="fixture-grid",
        registered_method=_method(),
        height_policy={"max_height_m": 18},
        program_policy={"ground_floor": "retail"},
    )

    with pytest.raises(ValueError, match="JSON-compatible"):
        strategy_model(
            strategy_id="bad-strategy",
            topology_family="fixture-grid",
            registered_method=_method(),
            program_policy={"callback": lambda: None},
        )


def _local_transform(**overrides):
    model = getattr(generation_contracts, "LocalWorldTransform", None)
    assert model is not None, "G0 must persist actual local-world affine matrices"
    values = dict(forward=[[0, 1, -200], [-1, 0, 100]],
                  inverse=[[0, -1, 100], [1, 0, 200]])
    values.update(overrides)
    return model.model_validate(values)


@pytest.mark.parametrize("forward,inverse,world,local", [
    ([[0, 1, -200], [-1, 0, 100]], [[0, -1, 100], [1, 0, 200]], [100, 200], [0, 0]),
    ([[0, 1, -200], [-1, 0, 100]], [[0, -1, 100], [1, 0, 200]], [105, 202], [2, -5]),
    ([[1, 0, 0], [0, 1, 0]], [[1, 0, 0], [0, 1, 0]], [105, 202], [105, 202]),
    ([[0.6, 0.8, -220], [-0.8, 0.6, -40]], [[0.6, -0.8, 100], [0.8, 0.6, 200]], [105, 202], [4.6, -2.8]),
])
def test_local_transform_known_answers_and_serialization(forward, inverse, world, local):
    transform = _local_transform(forward=forward, inverse=inverse)
    assert transform.world_to_local(world) == pytest.approx(local, abs=transform.tolerance_m, rel=0)
    assert transform.local_to_world(local) == pytest.approx(world, abs=transform.tolerance_m, rel=0)
    restored = type(transform).model_validate_json(transform.model_dump_json())
    assert restored == transform
    assert restored.local_to_world(restored.world_to_local(world)) == pytest.approx(world, abs=transform.tolerance_m, rel=0)
    with pytest.raises(TypeError):
        transform.forward[0][0] = 4
    with pytest.raises(ValueError):
        transform.direction = "local_to_world"


@pytest.mark.parametrize("overrides", [
    {"inverse": [[0, -1, 101], [1, 0, 200]]},
    {"inverse": [[0, -1, 100.00001], [1, 0, 200]]},
    {"forward": [[0, 0, 0], [0, 0, 0]]},
    {"forward": [[float('nan'), 1, 0], [-1, 0, 0]]},
    {"inverse": [[0, -1, float('inf')], [1, 0, 200]]},
    {"forward": [[True, 1, 0], [-1, 0, 0]]},
    {"forward": [[0, 1], [-1, 0]]},
    {"inverse": [[0, -1, 100]]},
    {"forward": [[0, 1, 0], [-1, 0, 0], [0, 0, 1]]},
    {"forward": [[2, 0, 0], [0, 2, 0]], "inverse": [[0.5, 0, 0], [0, 0.5, 0]]},
    {"forward": [[1, 1, 0], [0, 1, 0]], "inverse": [[1, -1, 0], [0, 1, 0]]},
    {"forward": [[-1, 0, 0], [0, 1, 0]], "inverse": [[-1, 0, 0], [0, 1, 0]]},
    {"direction": "local_to_world"}, {"world_crs": "EPSG:4326"},
    {"coordinate_unit": "pixels"}, {"source_frame": "local"},
    {"roundtrip_status": "PASS"}, {"tolerance_m": 100},
    {"tolerance_m": True}, {"version": "unregistered"},
])
def test_local_transform_rejects_invalid_matrices_and_claims(overrides):
    # Construct the class first so missing implementation cannot satisfy rejection.
    transform = _local_transform()
    with pytest.raises(ValueError):
        type(transform).model_validate({**transform.model_dump(), **overrides})


def test_local_transform_binds_context_and_request_hashes_without_ui_metadata():
    transform = _local_transform()
    changed = _local_transform(forward=[[0, 1, -201], [-1, 0, 100]], inverse=[[0, -1, 100], [1, 0, 201]])
    a = _context(local_world_transform=transform)
    b = _context(local_world_transform=changed)
    assert generation_context_digest(a) != generation_context_digest(b)
    payload = a.model_dump(mode="json")
    assert project_request_to_context(payload).local_world_transform == transform
    assert generation_context_digest({**payload, "mode": "STEPWISE", "job_id": "A", "created_at": "A"}) == generation_context_digest(a)
    request = dict(input_refs=[_ref("fixture", "a").model_dump()], input_hash=generation_context_digest(a),
                   geometry=box(0, 0, 4, 3), seed=17, strategy_id="fixture", algorithm_version="fixture-v1", method_parameters={})
    assert semantic_digest(geometry_request_payload(request)) != semantic_digest(geometry_request_payload({**request, "input_hash": generation_context_digest(b)}))
    # Direct request transform content must also bind, even with a stale input_hash.
    assert semantic_digest(geometry_request_payload({**request, "local_world_transform": transform.model_dump()})) != semantic_digest(geometry_request_payload({**request, "local_world_transform": changed.model_dump()}))
    assert _context().local_world_transform is None
    legacy = _context().model_dump()
    legacy.pop("local_world_transform")
    assert project_request_to_context(legacy).local_world_transform is None


@pytest.mark.parametrize("point", [[True, 1], [1], [1, 2, 3], [float('inf'), 2]])
def test_local_transform_rejects_invalid_points(point):
    transform = _local_transform()
    with pytest.raises(ValueError):
        transform.world_to_local(point)
