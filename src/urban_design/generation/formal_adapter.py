"""Approved frozen manifest to typed W6 dictionary context (read-only)."""
from urban_design.approved_generation import ApprovedGenerationBlocked
from urban_design.generation_context import context_digest
from .contracts import AssumptionSpec, AssumptionSourceKind, FrozenRef, GenerationClass, GenerationContext

VERSION = 'formal-context-adapter-v1'


def adapt_frozen_context(frozen, *, seed: int) -> GenerationContext:
    if frozen.status != 'READY' or frozen.context is None:
        raise ApprovedGenerationBlocked(list(frozen.blockers) or ['freeze is not READY'])
    manifest = frozen.context
    if frozen.context_hash != context_digest(manifest):
        raise ApprovedGenerationBlocked(['frozen context hash mismatch'])
    refs = tuple(FrozenRef(id=r['id'], sha256='sha256:'+r['payload_hash'], kind=r['entity_type'])
                 for r in manifest.refs if 'entity_type' in r)
    def unique(kind):
        values = [r for r in refs if r.kind == kind]
        if len(values) != 1:
            raise ApprovedGenerationBlocked([f'freeze requires exactly one {kind} ref'])
        return values[0]
    workspace = unique('WorkspaceRevision')
    constraint = unique('ConstraintSet')
    site = unique('StudyArea')
    context_ref = FrozenRef(id='formal-freeze-'+frozen.context_hash, sha256='sha256:'+frozen.context_hash, kind='GenerationContextManifest')
    # No synthetic analysis or brief: these refs identify the resolved site and
    # approved workspace spatial brief. Analysis scores are not inferred.
    return GenerationContext(workspace_ref=workspace, analysis_ref=site, brief_ref=workspace,
        source_refs=(*refs, context_ref), constraint_refs=(constraint,), crs='EPSG:28992',
        coordinate_unit='m', seed=seed, generation_class=GenerationClass.APPROVED_INPUTS,
        method_parameters={'formal_manifest': manifest.model_dump(mode='json')},
        assumptions=(AssumptionSpec(id='formal_manifest', statement='Read-only freeze of approved D1/D2 plus hash-verified observational 3D BAG evidence; no synthetic analysis.',
            source_kind=AssumptionSourceKind.PROJECT_DATA, source_refs=(context_ref,)),))


def retained_gfa_bounds(manifest):
    """Unknown is contagious; never sum only the known part as total GFA."""
    missing = [r['building_id'] for r in manifest.floor_estimates
               if r['floor_count']['status'].upper() == 'UNAVAILABLE'
               or r.get('gfa_upper_m2') is None or r.get('gfa_lower_m2') is None]
    if missing:
        return dict(status='UNAVAILABLE', lower_m2=None, upper_m2=None, unavailable_buildings=missing,
                    known_lower_m2=sum(r['gfa_lower_m2'] for r in manifest.floor_estimates if r.get('gfa_lower_m2') is not None),
                    known_upper_m2=sum(r['gfa_upper_m2'] for r in manifest.floor_estimates if r.get('gfa_upper_m2') is not None))
    return dict(status='ESTIMATE', lower_m2=sum(r['gfa_lower_m2'] for r in manifest.floor_estimates),
                upper_m2=sum(r['gfa_upper_m2'] for r in manifest.floor_estimates), unavailable_buildings=[])
