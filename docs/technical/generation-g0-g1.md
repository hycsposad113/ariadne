# Generation G0/G1 contract and capability boundary

This note records the bounded G0/G1 implementation in this worktree. The CP-G0/CP-G1 labels below are a task-level coverage checklist for this change; they do not add or replace a project milestone gate. Contracts and registry metadata are not evidence that the complete staged building generator, project integration, or human acceptance exists.

## CP-G0 contract coverage

| Check | Required contract | Evidence | Status and limit |
|---|---|---|---|
| CP-G0.1 Context and provenance | Frozen workspace, analysis, brief, source, and constraint references; EPSG:28992/metres; strict integer seed; typed method and assumption provenance; closed `EXPLORATORY` / `APPROVED_INPUTS` class | `GenerationContext`, `FrozenRef`, `MethodProvenance`, `AssumptionSpec`, and contract tests | PASS for typed serialization and validation. The class tag does not itself prove a human approval or unlock an approval gate. |
| CP-G0.2 Strategy | Registry identity and registered deterministic method; declarative JSON policies; reject executable callbacks | `StrategySpec` and callable-policy counterexample | PASS as a data contract; no strategy executor is implemented. |
| CP-G0.3 Skeleton | Typed point nodes and linear edges with level/access; edge width paired with a reference; primary open-space geometry separated from explicit access policy; retained references, graph connections, and separate geometry/topology/constraint report fields | `SkeletonNode`, `SkeletonEdge`, `OpenSpaceArtifact`, `AccessPolicy`, `SkeletonArtifact`, and negative graph/type cases | PASS as schema and validation only. No skeleton computation is claimed. An open-space hole does not establish public access. |
| CP-G0.4 Block/program | Parent-skeleton reference; typed blocks, zones, frontages, program allocations, and unallocated geometry with a reason | `BlockProgramArtifact` and typed JSON round-trip test | PASS as schema only; no block/program computation is claimed. |
| CP-G0.5 Massing | Parent-block reference; footprint; per-floor level, geometry, height, and use; retained references and validation report | `MassingArtifact`, `FloorGeometry`, and independent invalid-height / invalid-use cases | PASS as schema only; no floorplate or massing computation is claimed. |
| CP-G0.6 Serialization and digest | Each stage has its own typed JSON round-trip; geometry request digest binds references, input hash, canonical geometry, seed, strategy, algorithm version, and method parameters; UI mode/time/job metadata are excluded; stage seed is independently derived | `test_stage_artifacts_each_round_trip_as_typed_json`, hash sensitivity cases, and stage-seed test | PASS for the fixture contracts. Digests do not certify the correctness of an unimplemented calculation. |
| CP-G0.7 Geometry and transforms | Hash-only 1 mm normalization; canonical ring orientation/start, holes, and component order; reject non-finite, collapsed, or topology-changing precision cases; preserve the source geometry; persist rigid 2D forward/inverse matrices separately from CRS transform IDs and round-trip evidence fields | `canonical_geometry_payload`, precision and non-mutation counterexamples, `CoordinateTransformAudit`, `LocalWorldTransform`, independent point fixtures | Local rigid arithmetic and serialization verified in synthetic tests; independent review pending. CRS audit remains separate and `UNKNOWN` without measured evidence; local checks confer no CRS acceptance. |

## CP-G1 capability coverage

| Check | Required capability | Evidence | Status and limit |
|---|---|---|---|
| CP-G1.1 Registry | Every checked-in dictionary type has a registry record with variant, implementation/version where present, capability state, supported/unsupported features, parameter domain, and semantic test IDs | `build_type_registry` and dictionary coverage test | PASS for all 31 checked-in IDs. H, E, and comb have registered footprint adapters; other dictionary estimates and design hypotheses are not treated as support. |
| CP-G1.2 H footprint and retained geometry | Two wings joined by a distinct central crossbar; compare against the 1,800 m² reference union; test asymmetric dimensions, rotation, invalid thickness, a non-breaking obstacle removal, and rejection when an obstacle severs the connector | `test_morphology_shape_semantics.py` | PASS for synthetic fixtures only. The reference rectangles are `[10,10,20,70]`, `[80,10,90,70]`, and `[20,35,80,45]`. Obstacle subtraction cannot return a disconnected result labelled H. |
| CP-G1.3 E/comb semantic distinction | E is one spine with three same-side wings. Comb accepts variable integer wing counts 2–5. E and comb-3 may share geometric semantics only under a matching dimension layout; output metadata retains the distinct type IDs | E and comb independent reference-union cases, matched/mismatched E↔comb-3 fixture, and metadata assertions | PASS for these bounded footprint fixtures. The matched fixture maps E `(width=44, depth=60, spine=10, wing=8)` to comb `(spine_length=60, spine=10, wing_depth=34, wing=8, count=3, gap=12, rotation=-90)`. Changing a dimension breaks equivalence. |
| CP-G1.4 Comb parameter domain | Register a versioned comb adapter with strict integer `wing_count`, engineering/editorial envelopes for spine length (40–120 m), wing depth (10–36 m), wing count (2–5), gap (12–30 m), and derived thickness/gap checks that retain positive end margins | Registry range metadata and direct/v5 rejection and reference tests | PASS for the registered domain. The adapter does not read dictionary estimates as run-time defaults; every geometry parameter is supplied explicitly. |
| CP-G1.5 Obstacle semantic preservation | H crossbar, E/comb spine, and each required wing must remain single connected features attached to their connector after obstacle subtraction | H/E/comb broken-feature counterexamples and a non-breaking H obstacle success case | PASS for tested footprint semantics. The adapter rejects the candidate when a required feature is destroyed; it does not move retained geometry or create a replacement/public passage. |
| CP-G1.6 Explicit unsupported behavior | Types without adapters, including slab, fail closed. Opening geometry/orientation, ground/upper-floor range, per-floor massing generation, and public-access policy remain unsupported | Registry capability assertions and adapter rejection tests | PASS for explicit rejection. A polygon hole or gap never implies a public-access classification. The separate access-policy contract can preserve sourced classifications; footprint adapters do not generate them. |
| CP-G1.7 v4 compatibility evidence | Preserve the v4 implementation while adding versioned G1 behavior | `git diff --unified=0` against the v4 parent and the G0/G1 adapter commit | PASS by additive-only history: the original v4 algorithm remains unchanged. No representative historical v4 artifact was replayed in this worktree. |

## Runtime and integration limits

The v5 H/E/comb adapters return footprint geometry only. Comb supports a single-spine footprint with 2–5 same-side wings; comb-3 matches E only for corresponding spine, wing, gap, and rotation dimensions, while the generated type/variant/version metadata remains distinct. The adapters do not produce a skeleton, block program, floor-by-floor massing, openings, access decision, environmental analysis, or a complete building. Types without a registered adapter, including slab, remain fail-closed. No COMPAS dependency is installed or invoked. The contract remains fixture-oriented pending A2 schema freeze and ARCH01 review; Nonlinear CRS inverse-transform execution and measured CRS round-trip proof remain open. Local rigid 2D persistence and deterministic inverse validation are implemented separately. No live site/source/model/QGIS/weather input, production runtime, protected database, or human decision was used or changed. G2 and later work are outside scope.

The preserved `generate_scenario`/v4 path is unchanged in this branch. Passing these focused tests establishes local G0/G1 contract behavior only; it does not establish integration, milestone acceptance, or readiness of the full generator.

## G0 local-coordinate persistence addition (2026-09-30)

`GenerationContext.local_world_transform` optionally persists `LocalWorldTransform`.
`None` declares that supplied geometry already uses world coordinates; it cannot
verify an omitted caller-applied transformation. Any applied local translation or
rotation must be supplied as this record. Matrix rows multiply column `[x,y,1]`: forward
is world→local and inverse is local→world, with fixed frame labels, xy axes,
EPSG:28992 world CRS and metre coordinates. Both matrices are immutable 2×3 tuples.

`local-rigid-2d-v1` / `local-transform-tolerance-v1` are engineer-defined arithmetic
versions: translation/inverse-composition absolute tolerance is 1e-9 m; linear
coefficients/orthonormality absolute tolerance is 1e-12 (dimensionless). These are
not professional CRS accuracy claims, design steps, or the hash-only 1 mm geometry
grid. The validator derives the inverse deterministically, compares coefficients
and translations, and checks both compositions. Nonfinite/bool/malformed matrices,
singular matrices, scale, shear, reflection, changed frame/CRS/unit/version claims,
and caller-supplied PASS flags are rejected. Callers cannot relax these tolerances.

Independent fixture answers: `[[0,1,-200],[-1,0,100]]` maps world `[100,200]`
to local `[0,0]` and world `[105,202]` to `[2,-5]`; inverse
`[[0,-1,100],[1,0,200]]` restores the named world points. Identity and a non-axis
rotation (`0.6/0.8`) also serialize and restore independent known coordinates.
Point mapping returns new tuples and never changes source geometry. Fixed absolute
tolerances do not guarantee arbitrary-coordinate floating-point accuracy; very
large translations that exceed cancellation tolerance fail closed.

Context digests include the actual matrices and all direction/frame/version/tolerance
content. Geometry requests bind the context input hash and directly supplied
`local_world_transform` content, even if a caller retains a stale input hash.
UI mode/time/job exclusions remain unchanged. Requests omitting the new optional
field project to `None`; adding that field changes the new context digest schema,
so historical G0 digest bytes are not promised unchanged. Historical v4 output and
all registry/shape source files remain unchanged. No new stage, G2 skeleton,
nonlinear reprojection, pixel geometry, COMPAS, site run, runtime, database,
ledger, human decision or approval mechanism is implemented. Local test success
is not milestone acceptance.


## Claude cross-provider findings G-D1–D4 repair

The 3 m `MIN_RETAINED_WIDTH_M` and `MIN_CONNECTION_LENGTH_M` constants are
EDITORIAL engineering assumptions, above the hash-only 1 mm grid. Necessary
connector/wing geometry is checked in its original rectangular long/transverse
axes: retained longitudinal span and transverse sections at polygon vertex
interval limits and midpoints must meet the width minimum. Each contiguous
attachment must provide a connection edge of at least 3 m. These conservative
checks reject narrowed features instead of labelling them H/E/comb; every returned
footprint must also pass `canonical_geometry_payload` without altering its coordinates.
They are not a general clearance or arbitrary-polygon medial-axis calculation.

`MorphologyCapability` serializes `range_basis=EDITORIAL_ENVELOPE_V1`,
`not_regulatory=True`, and `range_source`. These are engineering/editorial
envelopes, not regulations and not human-approved constraints. Comb wing depth
10–36 m is an executor-defined engineering value, not a dictionary field.
The other comb intervals remain the existing dictionary-aligned editorial
adapter envelope. H/E intentionally have no absolute upper-size envelope:
they retain positive dimension, relative fit, site containment, and the same
3 m retained-feature checks as comb. Comb additionally bounds its variable-wing
layout; this difference is an adapter scope choice, not planning evidence.

Hash serialization normalizes negative zero in coordinates and all JSON values,
including local/world matrices. Historical v4 generation and evidence are unchanged;
new canonical digests may differ for payloads containing negative zero.
PROJECT_DATA/HUMAN_DECISION provenance requires nonempty frozen source refs.
Each context method-parameter key must equal an assumption ID or a source ID
(context sources or assumption sources); unresolved keys fail closed. This is
reference linkage, not independent verification of the source's substance.

## 已知限制，留待 G2

- G-D5: stage `context_hash` and seed are format/type checked only; their relationship to the originating context is not resolved.
- G-D6: `ValidationReport` can carry PASS status alongside failures; cross-field consistency remains unchecked.
- G-D7: `permitted_type_ids` are not validated against the capability registry.
- G-D8: ring-orientation wording and implementation differ (canonical exterior is CW, not CCW); unsupported-parameter errors remain generic rather than capability-specific.

The review event groups five observations under G-D5..D8 without a finer mapping;
G-D8 above explicitly retains both remaining observations. These findings are
documented only and are not repaired or accepted in this G0/G1 correction.

Additional observed implementation limit: independently rotated feature boundaries
can lose exact shared-edge topology at non-axis rotations (37.3° synthetic
fixtures). Such candidates fail closed; this correction does not introduce
snapping or change the existing assembly algorithm to make them accepted.
