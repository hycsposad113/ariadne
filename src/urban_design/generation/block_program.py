"""Typed G2 to block/program adapter; approved calls require a frozen manifest."""
import math
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from urban_design.generation.contracts import (
    AreaGeometryValue, BlockProgramArtifact, FrozenRef, GenerationClass,
    GenerationContext, FixtureRetainedBuilding, MethodProvenance, MethodSourceKind, ProgramBlock,
    ProgramZone, ProgramAllocation, SkeletonArtifact, StageStatus,
)
from urban_design.generation.hashing import generation_context_digest, semantic_digest, stage_artifact_digest, stage_seed

VERSION = "fixture-block-program-v1"


def geometry_value(geometry):
    return AreaGeometryValue(**mapping(geometry))


def sourced_parameter(context: GenerationContext, name: str, *, unit: str) -> float:
    """Resolve explicitly sourced numeric settings, never regulatory defaults."""
    value = context.method_parameters.get(name)
    if not isinstance(value, dict) or set(value) != {"value", "unit"} or value["unit"] != unit:
        raise ValueError(f"{name} requires explicit value and unit {unit}")
    number = value["value"]
    if isinstance(number, bool) or not isinstance(number, (float, int)) or not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} requires a positive finite number")
    return float(number)


def parameter_ref(context, name):
    return FrozenRef(id=name, sha256=generation_context_digest(context), kind="METHOD_PARAMETER")


def require_fixture(context):
    if context.generation_class is not GenerationClass.EXPLORATORY:
        raise ValueError("BLOCKED: approved GenerationContext resolver awaits W6-3")
    if not context.assumptions or any(item.source_kind.value != "ILLUSTRATIVE_FIXTURE" for item in context.assumptions):
        raise ValueError("FIXTURE_ONLY requires explicit ILLUSTRATIVE_FIXTURE assumptions")


def require_generation_context(context):
    if context.generation_class is GenerationClass.EXPLORATORY:
        return require_fixture(context)
    from urban_design.generation_context import GenerationContext as Manifest, context_digest
    if not isinstance(context.method_parameters.get('formal_manifest'), dict):
        raise ValueError('BLOCKED: approved freeze manifest is required')
    manifest = Manifest.model_validate(context.method_parameters['formal_manifest'])
    refs = [r for r in context.source_refs if r.kind == 'GenerationContextManifest']
    if len(refs) != 1 or refs[0].sha256 != 'sha256:'+context_digest(manifest):
        raise ValueError('BLOCKED: formal manifest hash mismatch')


def build_block_program(context: GenerationContext, skeleton: SkeletonArtifact,
                        site_geometry: AreaGeometryValue, *, strategy_id: str,
                        ground_use: str, water_geometry: AreaGeometryValue | None = None, retained_buildings: tuple[FixtureRetainedBuilding, ...] = ()) -> BlockProgramArtifact:
    require_generation_context(context)
    if skeleton.context_hash != generation_context_digest(context):
        raise ValueError("skeleton context hash mismatch")
    if skeleton.validation.failures or skeleton.validation.geometry_status is not StageStatus.PASS or skeleton.validation.topology_status is not StageStatus.PASS:
        raise ValueError("skeleton geometry/topology is not PASS")
    if not ground_use.strip():
        raise ValueError("ground use must be explicit")
    if not skeleton.edges:
        raise ValueError("skeleton has no roads")
    adjacency = {node.id: set() for node in skeleton.nodes}
    for edge in skeleton.edges:
        if edge.geometry.type != "LineString":
            raise ValueError("fixture adapter supports LineString roads only")
        adjacency[edge.from_node_id].add(edge.to_node_id)
        adjacency[edge.to_node_id].add(edge.from_node_id)
    reached = set()
    pending = [skeleton.nodes[0].id]
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(adjacency[node] - reached)
    if reached != set(adjacency):
        # G2 explicitly permits same-level roads connected through primary
        # public spaces. The formal adapter respects that contract; fixtures
        # retain their historical road-only rule.
        from .skeleton import _effective_component_count
        count = _effective_component_count(
            [shape(e.geometry.model_dump()) for e in skeleton.edges],
            [e.level for e in skeleton.edges],
            [shape(s.geometry.model_dump()) for s in skeleton.primary_open_spaces])
        if context.generation_class is GenerationClass.EXPLORATORY or count != 1:
            raise ValueError("skeleton road graph is disconnected")
    for i, edge in enumerate(skeleton.edges):
        for other in skeleton.edges[i+1:]:
            if edge.level != other.level:
                continue
            intersection = shape(edge.geometry.model_dump()).intersection(shape(other.geometry.model_dump()))
            shared = {edge.from_node_id, edge.to_node_id} & {other.from_node_id, other.to_node_id}
            if not intersection.is_empty:
                if intersection.geom_type != "Point" or not shared:
                    raise ValueError("same-level roads intersect without a shared node")
                nodes = {n.id: shape(n.geometry.model_dump()) for n in skeleton.nodes}
                if not any(intersection.distance(nodes[id]) < 1e-7 for id in shared):
                    raise ValueError("same-level road crossing geometry disagrees with shared node")
    site = shape(site_geometry.model_dump())
    exclusions = []
    for edge in skeleton.edges:
        if edge.width_m is None:
            raise ValueError("skeleton road width is UNKNOWN")
        line = shape(edge.geometry.model_dump())
        tolerance = 1e-6 if context.generation_class is GenerationClass.APPROVED_INPUTS else 0
        if not site.buffer(tolerance).covers(line):
            raise ValueError("skeleton road lies outside site")
        nodes = {node.id: node for node in skeleton.nodes}
        for node_id, coord in ((edge.from_node_id, line.coords[0]), (edge.to_node_id, line.coords[-1])):
            node = shape(nodes[node_id].geometry.model_dump())
            if node.distance(shape({"type": "Point", "coordinates": coord})) > 1e-7 or nodes[node_id].level != edge.level:
                raise ValueError("skeleton endpoint geometry/level mismatch")
        exclusions.append(line.buffer(edge.width_m / 2, cap_style=2))
    for space in skeleton.primary_open_spaces:
        geometry = shape(space.geometry.model_dump())
        tolerance = 1e-6 if context.generation_class is GenerationClass.APPROVED_INPUTS else 0
        if not site.buffer(tolerance).covers(geometry):
            raise ValueError("skeleton open space lies outside site")
        exclusions.append(geometry)
    waterfront = sourced_parameter(context, "waterfront_band_m", unit="m")
    setback = sourced_parameter(context, "retained_setback_m", unit="m")
    if water_geometry is not None:
        exclusions.append(shape(water_geometry.model_dump()).buffer(waterfront))
    for retained in retained_buildings:
        exclusions.append(shape(retained.geometry.model_dump()).buffer(setback))
    developable = site.difference(unary_union(exclusions))
    parts = [developable] if developable.geom_type == "Polygon" else list(getattr(developable, "geoms", ()))
    parts = sorted((g for g in parts if g.geom_type == "Polygon" and g.area > 1e-6), key=lambda g: (g.bounds, g.area))
    if not parts:
        raise ValueError("no developable blocks")
    blocks = tuple(ProgramBlock(id=f"{strategy_id}-block-{i}", geometry=geometry_value(g)) for i, g in enumerate(parts))
    zones = tuple(ProgramZone(id=b.id, geometry=b.geometry, use=ground_use) for b in blocks)
    return BlockProgramArtifact(
        artifact_id=f"{strategy_id}-blocks", context_hash=generation_context_digest(context),
        input_refs=(context.workspace_ref, context.brief_ref, context.analysis_ref,
                    FrozenRef(id="resolved-site-geometry", sha256=semantic_digest(site_geometry), kind="RESOLVED_GEOMETRY"),
                    FrozenRef(id="resolved-exclusions", sha256=semantic_digest({"water": water_geometry, "retained": retained_buildings}), kind="RESOLVED_GEOMETRY")),
        seed=stage_seed(context.seed, strategy_id, "block_program"), algorithm_version=VERSION if context.generation_class is GenerationClass.EXPLORATORY else "formal-block-program-v1",
        method=MethodProvenance(method_id=VERSION if context.generation_class is GenerationClass.EXPLORATORY else "formal-block-program-v1", version="1", description="Road-buffer subtraction and deterministic polygon decomposition; context-bound", source_kind=MethodSourceKind.REGISTERED_DETERMINISTIC_METHOD),
        assumptions=context.assumptions, created_at=skeleton.created_at,
        parent_skeleton_ref=FrozenRef(id=skeleton.artifact_id, sha256=stage_artifact_digest(skeleton), kind="SkeletonArtifact"),
        blocks=blocks, zones=zones, frontages=(),
        program_allocations=tuple(ProgramAllocation(zone_id=b.id, use=ground_use, area_m2=shape(b.geometry.model_dump()).area, source_refs=(context.brief_ref,)) for b in blocks),
        unallocated_areas=(),
    )
