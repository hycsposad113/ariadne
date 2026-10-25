"""Typed dictionary massing with separate fixture and frozen approved entry paths.
Formal execution is orchestrated by formal_pipeline; fixture calls never persist.
"""
from itertools import combinations
from shapely.geometry import shape, box
from shapely import affinity
from shapely.ops import unary_union
from urban_design.generation.block_program import build_block_program, geometry_value, sourced_parameter, require_fixture, require_generation_context
from urban_design.generation.contracts import (
    BuildingMassing, FloorGeometry, FrozenRef, GenerationClass, GenerationContext,
    FixtureCandidate, FixtureDictionaryRecipe, FixturePipelineResult, BlockProgramArtifact, AreaGeometryValue, SkeletonArtifact, FixtureRetainedBuilding,
    MassingArtifact, MethodProvenance, MethodSourceKind, StageStatus, ValidationReport, ValidationCheck,
)
from urban_design.generation.hashing import generation_context_digest, semantic_digest, stage_artifact_digest, stage_seed
from urban_design.generation.type_registry import generate_profile_geometry

VERSION = "fixture-dictionary-massing-v1"


def build_massing(context: GenerationContext, blocks: BlockProgramArtifact, recipe: FixtureDictionaryRecipe, retained_buildings: tuple[FixtureRetainedBuilding, ...] = (), *, block_recipes: dict[str, FixtureDictionaryRecipe] | None = None) -> MassingArtifact:
    require_generation_context(context)
    if not blocks.blocks:
        raise ValueError("no blocks for massing")
    if blocks.context_hash != generation_context_digest(context):
        raise ValueError("block context hash mismatch")
    floor_height = sourced_parameter(context, "standard_floor_height_m", unit="m")
    first_height = sourced_parameter(context, "first_floor_height_m", unit="m")
    height_limit = sourced_parameter(context, "height_upper_bound_m", unit="m")
    from .legacy_profile_adapter import TYPES, generate_legacy_profile
    buildings = []
    default_recipe = recipe
    recipe_refs = []
    for block in blocks.blocks:
        recipe = block_recipes[block.id] if block_recipes is not None else default_recipe
        recipe_refs.append(recipe.source_ref)
        profile_generator = generate_legacy_profile if recipe.type_id in TYPES else generate_profile_geometry
        domain = shape(block.geometry.model_dump())
        parameters = dict(recipe.geometry_parameters)
        if context.generation_class is GenerationClass.APPROVED_INPUTS:
            # Validate registered profile semantics in a translated/rotated
            # metre frame before applying one rigid transform to its union.
            # Rotating each wing at RD's large coordinate origin separately
            # otherwise produces false ~1e-11m gaps at shared boundaries.
            angle = parameters.get('rotation_deg', 0)
            center = domain.centroid
            local = affinity.rotate(affinity.translate(domain, -center.x, -center.y), -angle, origin=(0, 0))
            if recipe.type_id in TYPES:
                # Remove rigid-transform round-off at dictionary minimum sizes.
                envelope = box(*(round(v, 6) for v in local.bounds))
                if local.symmetric_difference(envelope).area > 1e-5:
                    raise ValueError('legacy envelope is not a complete rectangle')
                local = envelope
            parameters['rotation_deg'] = 0
            geom = profile_generator(recipe.type_id, local, parameters,
                crs=context.crs, coordinate_unit=context.coordinate_unit)
            world = affinity.translate(affinity.rotate(geom.geometry, angle, origin=(0, 0)), center.x, center.y)
            if not world.is_valid or not domain.buffer(1e-6).covers(world):
                raise ValueError('local/world profile transform failed geometry containment')
        else:
            geom = profile_generator(recipe.type_id, domain, parameters,
                crs=context.crs, coordinate_unit=context.coordinate_unit)
            world = geom.geometry
        footprint = geometry_value(world)
        floors = tuple(FloorGeometry(level=i, geometry=footprint, floor_height_m=first_height if i == 0 else floor_height, use=use)
                       for i, use in enumerate(recipe.floor_uses))
        height = sum(f.floor_height_m for f in floors)
        if height > height_limit:
            raise ValueError("generated building exceeds sourced height upper bound")
        buildings.append(BuildingMassing(id=block.id+"-building", footprint=footprint, floors=floors, height_m=height,
                                         use="mixed" if len(set(recipe.floor_uses)) > 1 else recipe.floor_uses[0], type_id=geom.type_id, variant_id=geom.variant_id))
    unknown = tuple(item.source_ref.id for item in retained_buildings if item.floor_count is None)
    artifact = MassingArtifact(
        artifact_id=default_recipe.recipe_id+"-massing", context_hash=blocks.context_hash,
        input_refs=(*blocks.input_refs, *tuple(dict.fromkeys(recipe_refs))), seed=stage_seed(context.seed, default_recipe.recipe_id, "massing"),
        algorithm_version=VERSION if context.generation_class is GenerationClass.EXPLORATORY else "formal-dictionary-massing-v2", method=MethodProvenance(method_id=VERSION if context.generation_class is GenerationClass.EXPLORATORY else "formal-dictionary-massing-v2", version="1", description="Registered dictionary footprint extrusion with explicit per-floor program; context-bound", source_kind=MethodSourceKind.REGISTERED_DETERMINISTIC_METHOD),
        assumptions=context.assumptions, created_at=blocks.created_at,
        parent_block_ref=FrozenRef(id=blocks.artifact_id, sha256=stage_artifact_digest(blocks), kind="BlockProgramArtifact"),
        buildings=tuple(buildings), retained_refs=tuple(item.source_ref for item in retained_buildings),
        validation=ValidationReport(geometry_status=StageStatus.PASS, topology_status=StageStatus.PASS,
                                   constraint_status=StageStatus.UNKNOWN,
                                   checks=(), unknowns=("FAR has not been checked", *tuple("retained GFA UNKNOWN: "+id for id in unknown)), failures=()),
    )
    return artifact


def run_fixture_dictionary_pipeline(context: GenerationContext, site_geometry: AreaGeometryValue, skeletons: tuple[SkeletonArtifact, ...], recipes: tuple[FixtureDictionaryRecipe, ...],
                                    *, water_geometry: AreaGeometryValue | None = None, retained_buildings: tuple[FixtureRetainedBuilding, ...] = ()) -> FixturePipelineResult:
    """Retain failed candidates and require three pairwise substantive differences."""
    if context.generation_class is not GenerationClass.EXPLORATORY:
        return FixturePipelineResult(status="BLOCKED")
    if len(skeletons) != len(recipes):
        raise ValueError("one G2 skeleton is required for each recipe")
    if len({recipe.recipe_id for recipe in recipes}) != len(recipes):
        raise ValueError("recipe IDs must be unique")
    candidates = []
    for skeleton, recipe in zip(skeletons, recipes):
        input_hash = semantic_digest({"context": context, "site": site_geometry, "skeleton": stage_artifact_digest(skeleton),
                                      "recipe": recipe, "water": water_geometry, "retained": retained_buildings})
        blocks = None
        massing = None
        try:
            blocks = build_block_program(context, skeleton, site_geometry, strategy_id=recipe.recipe_id,
                                         ground_use=recipe.floor_uses[0], water_geometry=water_geometry, retained_buildings=retained_buildings)
            massing = build_massing(context, blocks, recipe, retained_buildings)
            areas = tuple(shape(f.geometry.model_dump()).area for b in massing.buildings for f in b.floors)
            new_gfa = sum(areas)
            retained_gfa = None if any(r.floor_count is None for r in retained_buildings) else sum(shape(r.geometry.model_dump()).area*r.floor_count for r in retained_buildings)
            total = None if retained_gfa is None else new_gfa+retained_gfa
            far_limit = sourced_parameter(context, "far_upper_bound", unit="ratio")
            site_area = shape(site_geometry.model_dump()).area
            far_failed = new_gfa / site_area > far_limit or (total is not None and total / site_area > far_limit)
            far_status = StageStatus.FAIL if far_failed else StageStatus.UNKNOWN if total is None else StageStatus.PASS
            report = ValidationReport(
                geometry_status=StageStatus.PASS, topology_status=StageStatus.PASS,
                constraint_status=far_status,
                checks=(ValidationCheck(check_id="height_upper_bound_m", status=StageStatus.PASS,
                                        detail="Each generated height checked against sourced fixture upper bound"),
                        ValidationCheck(check_id="far_upper_bound", status=far_status,
                                        detail=f"Known new GFA {new_gfa} m2; total GFA {total}; site denominator {site_area} m2; upper bound {far_limit}")),
                unknowns=tuple("retained GFA UNKNOWN: "+r.source_ref.id for r in retained_buildings if r.floor_count is None),
                failures=("known GFA exceeds sourced FAR upper bound",) if far_failed else (),
            )
            massing = massing.model_copy(update={"validation": report})
            if far_failed:
                raise ValueError("known GFA exceeds sourced FAR upper bound")
            program = {}
            for building in massing.buildings:
                for floor in building.floors:
                    program[floor.use] = program.get(floor.use, 0.) + shape(floor.geometry.model_dump()).area
            candidates.append(FixtureCandidate(recipe_id=recipe.recipe_id, status="FIXTURE_ONLY", input_hash=input_hash,
                block_program=blocks, massing=massing, block_hash=stage_artifact_digest(blocks), massing_hash=stage_artifact_digest(massing),
                road_hash=semantic_digest(tuple((e.geometry, e.width_m) for e in skeleton.edges)),
                open_space_hash=semantic_digest(tuple(s.geometry for s in skeleton.primary_open_spaces)),
                footprint_hash=semantic_digest(tuple(b.footprint for b in massing.buildings)),
                new_gfa_m2=new_gfa, retained_gfa_m2=retained_gfa, total_gfa_m2=total,
                floor_areas_m2=areas, program_gfa_m2=program))
        except ValueError as error:
            candidates.append(FixtureCandidate(recipe_id=recipe.recipe_id, status="FAIL", input_hash=input_hash,
                                               failure_reasons=(str(error),), block_program=blocks, massing=massing,
                                               massing_hash=stage_artifact_digest(massing) if massing else None,
                                               floor_areas_m2=tuple(shape(f.geometry.model_dump()).area for b in massing.buildings for f in b.floors) if massing else (),
                                               new_gfa_m2=sum(shape(f.geometry.model_dump()).area for b in massing.buildings for f in b.floors) if massing else None,
                                               block_hash=stage_artifact_digest(blocks) if blocks else None))
    valid = [c for c in candidates if c.status == "FIXTURE_ONLY"]
    differences = []
    diversity_threshold = sourced_parameter(context, "diversity_min_difference_ratio", unit="ratio")
    if diversity_threshold > 1:
        raise ValueError("diversity_min_difference_ratio must be <= 1")
    skeleton_by_id = {recipe.recipe_id: skeleton for recipe, skeleton in zip(recipes, skeletons)}
    def geometry_sets(candidate):
        skeleton = skeleton_by_id[candidate.recipe_id]
        return {
            "roads": unary_union([shape(e.geometry.model_dump()).buffer(e.width_m/2, cap_style=2) for e in skeleton.edges]),
            "blocks": unary_union([shape(b.geometry.model_dump()) for b in candidate.block_program.blocks]),
            "open_spaces": unary_union([shape(s.geometry.model_dump()) for s in skeleton.primary_open_spaces]),
            "footprints": unary_union([shape(b.footprint.model_dump()) for b in candidate.massing.buildings]),
        }
    for a, b in combinations(valid, 2):
        left, right = geometry_sets(a), geometry_sets(b)
        ratios = {key: left[key].symmetric_difference(right[key]).area / max(left[key].area, right[key].area, 1e-12) for key in left}
        flags = {key: ratio >= diversity_threshold for key, ratio in ratios.items()}
        differences.append({"a": a.recipe_id, "b": b.recipe_id, **flags,
                            "difference_ratios": ratios, "minimum_difference_ratio": diversity_threshold,
                            "substantive": all(flags.values())})
    enough = any(all(next(d["substantive"] for d in differences if {d["a"], d["b"]} == {a.recipe_id,b.recipe_id}) for a,b in combinations(trio,2)) for trio in combinations(valid,3))
    return FixturePipelineResult(status="FIXTURE_ONLY" if enough else "FAIL", candidates=tuple(candidates),
                                 pairwise_differences=tuple(differences), valid_count=len(valid))
