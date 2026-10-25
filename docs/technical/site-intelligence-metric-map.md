# Site Intelligence Metric Map (A0)

This map describes existing calculations and frozen result readers. It does not
claim that a metric is currently recomputed, accepted, or exposed in the UI.
`site_analysis.py` explicitly says its direct calculations do not verify source
provenance, completeness, hashes, or CRS. The persisted readers in
`analysis_persistence.py` perform separate hash and lineage checks; adapters
must preserve those outcomes.

## Scope and status rules

The displayed StudyArea is a versioned exploration scope, not a formal Site,
DesignBoundary, cadastral parcel, ownership record, or buildable-land mask. An
analysis extent is recorded separately from that polygon. In particular, the
800 m, 2 km, and 10 km Syntax radii are calculation radii; they do not imply a
matching source-acquisition buffer. PD-20 records the actual extraction
envelopes independently (pedestrian 1.5 km; bicycle 4 km/6 km; motor vehicle
15 km/20 km).

Every projected analysis uses one of these statuses:

| Status | Meaning |
|---|---|
| `AVAILABLE` | A scalar or category result exists and its exact inputs, scope, method, unit, and result reference resolve. This does not imply human acceptance. |
| `PARTIAL` | A result exists for stated coverage, with machine-readable limitation codes and retained source limitation text. It cannot be generalized beyond that coverage. |
| `BLOCKED` | Required source, policy, lineage, or semantic relationship is absent or invalid. Its scalar value is `null`. |
| `NOT_RUN` | No calculation or result load was requested/completed. Its scalar value is `null`. |

Missing source coverage is never represented by a zero. A zero is available only
when a deterministic result explicitly records complete coverage for its scope.

## Metric and source map

| Domain / field | Existing implementation or result source | Scope, method, and unit | Status and limits to preserve | Historical reference |
|---|---|---|---|---|
| StudyArea area | `site_analysis.calculate_site_metrics`; `ProblemDefinitionBundle.study_area_area_m2` | Supplied polygon area; square metres. The helper does not validate CRS or source lineage. | Only available after the StudyArea artifact, projected CRS, geometry hash, and area method resolve. Exploration area is not a legal site area. | W5 `claim-w5-site-001`; W6 report input section. |
| Building count / footprint / ground coverage | `site_analysis.calculate_site_metrics` | Intersecting BAG features; clipped footprint union; footprint union divided by StudyArea area. Count, m², ratio. | The existing helper returns `null` unless building coverage is explicitly declared complete. Coverage ratio is geometric, not statutory building coverage. BAG features are not necessarily distinct physical buildings. | W5 `claim-w5-site-002` through `-004`; W6 source inventory. |
| Building height / floor area / FAR | `site_analysis.calculate_site_metrics` declares `height_status=UNAVAILABLE`, `far_status=UNAVAILABLE`, `calculated_far=null`. The W5 report separately cites a partial 3D BAG match and the PD-11 floor-estimate method. | W5 report: 3D BAG roof-height matches for a subset; estimated floors use the recorded 3.0 m rule. Height in m; GFA estimate in m². | Direct helper output is blocked/null. The report estimate is partial and method-dependent; missing heights stay unknown. Estimated GFA is not measured GFA or FAR. The 3.0 m assumption must never fill missing heights. | W5 `claim-w5-site-005/-006`; W6 data-gap section. |
| Registered use / function | `site_analysis.calculate_site_metrics` `usage_distribution`; `problem_definition.compute_functional_monoculture` | BAG `gebruiksdoel` labels; W6 compares StudyArea features with a geometric outside 0–800 m ring. Categories/counts and Shannon index. | Registered labels are not actual tenancy, occupancy, or current use. Missing labels stay unknown and are excluded only as the named method specifies. The 0–800 m comparison ring is not a walking catchment. | W5 `claim-w5-site-007/-013`; W6 problem 1. |
| Road length | `site_analysis.calculate_site_metrics`; `r04_evidence.calculate_clipped_road_length_metrics` | Clipped OSM way-length sum by `highway` label; R04 also reports unioned centerline length and overlap excess. Metres. | The sum can double-count coincident ways. Neither length nor OSM tags prove a connected graph, public right-of-way, passability, safety, or travel time. Keep sum and deduplicated length as distinct metrics. | W5 `claim-w5-site-008/-009`; W6 problem 2. |
| Road topology / detour proxies | `problem_definition.compute_spatial_fragmentation`; `compute_sociospatial_isolation` | Quantized OSM coordinate-vertex graph, boundary-line intersections, and sampled route-to-straight-line ratios. Vertices, vertices/ha, points, ratio. | Graph construction does not split every interior crossing or model access control, grade separation, slope, or legal passage. Degree-one vertices are not automatically dead-ends. Geometric boundary intersections are not confirmed entrances. Detour ratios are not travel time. | W6 problems 2–3; W5 `claim-w5-site-010`. |
| Syntax integration / choice | `pst_syntax.compute_pst_six_syntax_layers`; persisted via `analysis_persistence.get_persisted_syntax_bundle` | PST 3.3.1 NAIN/NACH at pedestrian 800 m, bicycle 2 km, and motor-vehicle 10 km; normalized syntax values per segment. | PD-20 mode-specific networks replace the earlier common-network baseline for these scales. Preserve mode, radius, extraction envelope, method, segment coverage, and stability status. Pedestrian 800 m remains `BLOCKED_BOUNDARY_STABILITY_UNASSESSED`; bicycle 2 km and motor-vehicle 10 km remain exploratory envelope/stability results. Different network modes/scales are not directly ranked. NAIN/NACH are not observed pedestrian or vehicle flows. | W5 `claim-w5-site-018` through `-024`; PD-20/PD-21 docket and decision record. |
| Green geometry | `problem_definition.compute_ecological_disconnection`; frozen OSM green polygons in the W5/W6 result packages | Intersections/unions and distances between tagged polygons; m², ratio, feature count, m. | OSM tags do not measure canopy, vegetation condition, ecological connectivity, ownership, or public access. W6’s green context `retrieved_at` is null; do not invent an exact retrieval time. | W5 `claim-w5-site-017`; W6 problem 4. |
| Water area / water-land interface / route proximity | `site_analysis.calculate_site_metrics`; `problem_definition.compute_waterfront_inaccessibility` | BGT water geometry union and boundary intersection; optional distance to selected OSM route labels. m², m, ratio. | Geometric proximity is not a verified public route, public right, or accessible waterfront. Interface length is not quay type, water depth, flood protection, or suitability. The selected 22 m threshold is a method parameter, not a legal standard. | W5 `claim-w5-site-014/-015`; W6 problem 5. |
| Unclassified residual | `site_analysis.calculate_site_metrics`; `problem_definition.compute_unclassified_residual_ground` | StudyArea minus observed building and water unions; m², ratio, polygon count. | It is a geometric difference only. It is not open/public space, vacancy, ownership, surface material, or buildable land. W6 problem 6 remains pending designer confirmation. | W5 `claim-w5-site-016`; W6 problem 6. |
| Functional surroundings | W5 frozen 2 km OSM context; `problem_definition.compute_functional_monoculture` for BAG comparison | OSM feature counts in a declared context snapshot; BAG categories in the named 0–800 m geometric ring. | Feature counts are not population, households, demand, or a complete facility inventory. W5 reports no independent amenity/landuse polygon layer and cannot establish actual tenants. | W5 `claim-w5-site-012/-013`; W6 problem 1. |
| Environmental method availability | `site_analysis.calculate_site_metrics` data-gap register; evidence and climate gate records | Method/readiness state, not a simulated site metric. No unit. | Local wind is explicitly unverified and requires CFD boundary conditions/mesh. Weather-dependent work remains method-gated; this adapter emits no invented wind, comfort, radiation, or energy value. Unsupported analysis is `BLOCKED` or `NOT_RUN` with null value. | W5 `claim-w5-site-025`; Evidence Framework climate/method gates; README current-gate summary. |

## Provenance and policy notes

The W5 site report is marked pending designer review and its Syntax outputs are
exploratory. The W6 problem-definition report records an independent
deterministic recomputation, not design acceptance or a `HumanDecision`.
There is a report-level registered-use discrepancy: W5 describes 31/51 BAG
features with a valid use label while W6 describes 43/51 known labels. These
counts use different frozen inputs or processing contexts and must not be
combined or silently reconciled; a bundle may use only one hash- and
scope-bound result at a time.

PD-20 is a project decision that supersedes the earlier common-network baseline
for the three Syntax scales. The coarse common-network mode remains a distinct
label for any legacy result; it is not a fallback for missing mode-specific
data. This implementation does not change the authoritative architecture or
the existing calculations.

The persisted site/Syntax readers verify stored output hashes and current input
lineage. A stale or blocked reader result must remain so in the projection.
Fresh fixtures prove adapter behavior only; they do not prove that the live
workspace has current inputs, that a provider was called, or that any metric is
accepted or deployed.

Observation limitation codes describe validation state; `limitation_details`
retains the source's original caveat text for later review. The projection does
not replace those caveats with a generic code or treat their prose as a new
measurement.

The A2 builder projects dictionaries returned by the existing calculation or
result-loading boundary; it does not open the project store, launch an analysis,
or persist a new Artifact or ledger event. Its content-derived `bundle_ref` is a
local identity for that projection, not a persisted or accepted project record.
Callers must supply exact frozen scope/input references and retain the loader's
status. A legacy EvidenceCard without typed source coverage or input references
stays blocked instead of being promoted from its display value.


## A-M1..M8 repair boundary (2026-09-30)

This is a worktree implementation contract, not merge, deployment, A3/A4,
or human acceptance. `validate_analysis_bundle` both recomputes the content
reference and resolves that exact reference as a validated, same-workspace
Artifact with the exact StudyArea/scenario in a backend-owned read-only index.
The builder remains a local projection: it does not persist or approve that
Artifact. A caller without the index entry gets `ANALYSIS_BUNDLE_INVALID`
before any suggestion provider call. The later integration owner must provide
that index entry; no API/store/ledger integration is included here.

| Finding | Implemented boundary | Regression nodes (under tests/) |
|---|---|---|
| M1 | Unicode numeric characters and financial CJK numbers rejected in every AI narrative, including DESIGN_PREFERENCE. Exact registered reference IDs and compound method/tool versions are an explicit allowlist. A complete metric ID is exempt only after the server registry resolves its exact key, unit and method to the bundle observation; bare numbers are never exempt. | test_opportunity_relationships.py::test_numeric_unicode_counterexamples_are_rejected; ::test_registered_method_version_is_an_explicit_identifier_allowlist; ::test_ai_design_preference_requires_evidence_and_cannot_contain_numbers |
| M2 | Real provider failure statuses return UNAVAILABLE without repair; unknown outcomes never retry; only invalid model output gets at most one repair. Invalid server bundle fails before dispatch. | test_opportunity_relationships.py::test_provider_failure_status_is_unavailable_without_repair; ::test_unknown_provider_outcome_is_not_retried; ::test_invalid_bundle_never_dispatches_or_repairs_provider |
| M3 | Draft citations deduplicate exact refs in first-seen order. The known local DeterministicFixtureProvider receives at most five cards because it emits one hypothesis per card; arbitrary/live oversized responses still reject. Duplicate metric/scope/method observations still reject. | test_opportunity_relationships.py::test_draft_evidence_references_are_deduplicated_in_first_seen_order; ::test_real_site_metrics_bundle_with_multiple_observations_supports_suggestions |
| M4 | Five suggestions, ten narrative entries, and one thousand characters per accepted text field; private keys and think/credential strings filtered from retained raw output. | test_opportunity_relationships.py::test_suggestion_count_is_capped_at_five; ::test_suggestion_text_fields_have_length_bounds; ::test_additional_exact_private_keys_are_filtered |
| M5 | Explicit loader status allowlist; unknown/failure states carry no numbers, even when source values exist. | test_site_intelligence_adapters.py::test_unrecognized_site_loader_status_suppresses_values; ::test_unrecognized_syntax_loader_status_suppresses_values |
| M6 | Base-site bundle rejects scenario-specific evidence. A scenario bundle may cite base-site inputs or its exact scenario; foreign scenario/revision/hash fails. Syntax extent must match StudyArea, radius, mode. | test_opportunity_relationships.py::test_bundle_without_scenario_rejects_scenario_bound_evidence; test_site_intelligence_adapters.py::test_syntax_extent_id_must_match_radius_and_network_mode |
| M7 | Resolve and rehash bundle. OBSERVATION evidence resolves one exact metric/scope/unit/method record with identical scalar value, analysis_status, and ordered input_refs. VALIDATED is distinct from AVAILABLE/PARTIAL. | test_opportunity_relationships.py::test_unregistered_content_hashed_bundle_is_rejected; ::test_bundle_content_hash_is_rechecked_before_opportunity_validation; ::test_indexed_observation_requires_exact_status_and_lineage |
| M8 | Road sum caveats, clipped building union method, not-flow Syntax limits, real residual keys, and problem status retained. Empty Syntax coverage is missing; registered-use totals must match the strict source building count. | test_site_intelligence_adapters.py::test_coverage_caveat_preserves_union_method; ::test_problem_status_and_residual_metric_codes_follow_problem_definition_keys; ::test_explicit_empty_syntax_segments_without_count_are_missing; ::test_usage_category_total_must_match_strict_building_count |

Credential filtering is deterministic and covers explicit sensitive key aliases,
Bearer and sk-style values, and think blocks. It is not a universal recognizer
for arbitrarily named or unmarked secrets/private prose; providers must still
exclude them at their boundary. Fresh fixture tests are not evidence of live
provider safety, current runtime data, or production acceptance.


M3 supplementary acceptance: the immutable bundle and all observations remain
intact; only the exact known `DeterministicFixtureProvider` input card list is
bounded. Five fixture hypotheses describe that bounded sample, not every
observation. No live/model output is truncated into an accepted response: six
proposals reject as a whole and remain visible in bounded raw audit output.
Regression nodes in `test_opportunity_relationships.py`:
`test_numeric_metric_id_exemption_requires_resolved_matching_registry`,
`test_registered_full_metric_id_does_not_exempt_extra_measured_numbers`,
`test_registered_metric_id_exemption_never_matches_partial_identifiers`, and
`test_fixture_card_bound_preserves_full_bundle_zero_and_rejects_live_overflow`.
These cover missing/wrong registry bindings, exact ID plus 120m or 120公尺 in
the same narrative, unchanged zero values/full observations, and whole-response
rejection of an oversized simulated live provider (no network call).


## A2-F1..F6 second repair (2026-09-30)

The Founder supersedes the reviewer's proposed legacy-status rejection: a
validated legacy EVIDENCE/OBSERVATION with `analysis_status=None` remains usable,
with server-derived `LEGACY_ANALYSIS_STATUS_UNSET` in limitations/uncertainties
and a `designer_questions` entry asking whether completeness may be assumed.
This is an implementation constraint and notification, not a HumanDecision.

AI statements require `StatementTemplate` selections from `STATEMENT_TEMPLATES`.
`METRIC_TENDENCY` accepts an exact registered bundle metric ID and closed
`direction`/`verification` enums. The server renders the statement and verifies
the metric's unit, method and cited input lineage. Model-authored free hypotheses
and altered rendered statements reject. No quantity is inserted into statements;
measurements remain in source-bound observations with units and frozen input
references. Numeric text detection is a secondary, best-effort defense in other
AI narrative fields; it is not a universal natural-language quantity classifier.
The exact local deterministic fixture is projected into the same closed slots;
arbitrary provider prose never receives that conversion.

Production response parsing permits only `LIVE_AI: ACTIVE` and
`NON_AI: DETERMINISTIC_TEMPLATE`. Explicit `is_live=False` offline test fakes
may omit status. All other statuses fail closed before content parsing/repair;
exact `LIVE_AI: OUTCOME_UNKNOWN` retains its distinct no-retry result. Even
well-formed template content cannot authorize unavailable provider output.
Retained raw output uses a field allowlist plus think/thinking/reasoning/
scratchpad and credential-pattern filtering (including ghp_, AKIA, xoxb-, JWT,
AIza, PEM and Basic authentication). Unmarked secrets/private prose cannot be
universally recognized; these tests use synthetic strings and no credentials.

The server appends cited observation/index limitations to `uncertainties` and
emits `PARTIAL_ANALYSIS_EVIDENCE` from typed partial status. Substring matches
and model-authored notification fields confer no authority. Scenario comparison
and improvement candidates must match the exact bundle scenario. Observation
scopes resolve as StudyArea/spatial Artifact within the bundle StudyArea;
layer/coverage scopes resolve as spatial entities with verified coverage.

Fresh offline regression evidence and each changed pre-existing test are in
`artifacts/site-intelligence-v1/verification.md`. No live AI, source acquisition,
store/ledger/API/UI integration, merge or acceptance is established here.
