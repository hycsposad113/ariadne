# Product Requirements

> **2026-09-22 現行規劃修訂：** 本文件採納 [工作流程與學期排程修訂契約](08_WORKFLOW_REALIGNMENT_2026-09-22.md)。其中第 5 節明列的產品範圍與排程條款優先於下方保留的舊版敘述；未列為取代的安全、證據與人類決策契約繼續有效。學期 W4 合併平台接入與基地分析，W5 開始生成／編輯，W8 驗收核心、W9 收尾。這是規劃修訂，不是實作或政策批准。

新增核心需求 R26-01–14 見修訂契約第 2 節。P0-05 的 grocery accessibility 保留為受政策約束的指標；P0-06 擴為 3–5 空間策略；P0-14 保留受控實驗但不限制所有編輯只能單軸；P0-15/16 擴為地圖、互動 3D、分面與道路吸附；P0-20 同時要求成果出圖。舊 P0 其餘證據與決策要求保留。三尺度 Syntax、E1 日照和 R26-13 出圖新增為核心；E3 耗能、E4 蓄熱、E5 風場、精細交通模式及模型匯出為附加項。

Status: authoritative MVP requirements for the Evidence-Based, Contestable Agentic Urban Design Environment.

This document turns the approved handoff into testable product requirements. It uses the evidence contract in [05_EVIDENCE_FRAMEWORK.md](05_EVIDENCE_FRAMEWORK.md) and preserves the supporting [research report](../deep-research-report.md) as source material. It does not authorize production implementation beyond the stated scope.

## Product law

The product assists a designer through Draw → Confirm Study Area → Understand / Site Intelligence, Explore / Morphological Exploration, Test / Scenario Critic, Refine / Climate Co-Designer, and Human Decision.

The governing behavior is: LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.

The system must expose how a conclusion was produced, what assumptions it depends on, how a challenge changes state, and which human decision governs the next step. It must not present itself as an autonomous designer of the best city.

The exploration entry contract is intentionally narrow: `StudyArea` means only
that a human confirmed a saved QGIS Polygon/MultiPolygon for exploratory use.
It does not establish ownership, cadastral identity, zoning compliance, or
legal buildability. Those four formal claim classes require a separate typed
`DesignBoundary` in `APPROVED` status with explicit `HumanDecision` data.

## Priority definitions

* P0 is required for the approved eight-week single-user course-research prototype and its end-to-end demonstration.
* P1 is a valuable extension after the P0 path is stable. It must not be used to justify missing P0 evidence.
* P2 is a later research or product direction whose scope and validation are intentionally deferred.
* OUT OF SCOPE is excluded from this prototype and must not enter through an unstated dependency or aspirational UI.

## Project settings and illustrative examples

These are approved MVP project decisions, not universal standards. The sole
active MVP demonstration is the human-confirmed Rotterdam M4H `StudyArea` v5.
Historical Delft proposal evidence and rejected or proposed Rotterdam boundary
experiments remain preserved history; `Project.site_id` remains null until a
future formal decision, and StudyArea confirmation does not approve a
`DesignBoundary`.

| Setting | P0 decision |
| --- | --- |
| Exploration envelope | One human-drawn QGIS `StudyArea`, explicitly confirmed by a human before the four exploratory stages. A typed Artifact must resolve with matching project, URI, bytes/hash, size, MIME, CRS, and producer; the polygon, projected CRS canonical units, artifact hash, confirmation actor/time, and ledger events are versioned. |
| Formal boundary | A `DesignBoundary` is a separate proposed/approved record. `CADASTRAL`, `OWNERSHIP`, `ZONING_COMPLIANCE`, and `LEGAL_BUILDABILITY` claims require `APPROVED` status plus explicit `HumanDecision` data. |
| Inputs | Frozen PDOK and OpenStreetMap snapshots with query/source identity, retrieval time, attribution/license, and hashes. |
| GIS | QGIS MCP is mandatory behind a controlled allow-list and verifier. |
| Accessibility | Fraction of a fixed approved set of public-access reference points that can reach at least one selected grocery destination within network distance less than or equal to the selected threshold. Default 800 m; challenge variants 400 m, 800 m, 1200 m. |
| Morphology | COMPAS perimeter-block and linear-block families; one accepted candidate from each in the MVP demonstration. |
| Climate | One controlled incident-radiation refinement experiment with Ladybug screening and Honeybee-Radiance verification. |

Concrete values shown in the research report as examples, including FAR 2.2, height 24 m, green 35%, or sample metric values, are illustrative until an authoritative source, project evidence, or explicit human decision makes them effective project parameters. Sample scenario names and values in documentation are not validated results.

## P0

### P0-01 - Human-confirmed Study Area and formal boundary guard

id: P0-01
description: Accept a human-drawn QGIS polygon as the versioned StudyArea exploration envelope, require confirmation before starting Understand/Explore/Test/Refine, and keep formal DesignBoundary approval separate.
user_value: Gives the designer a bounded, repeatable case whose evidence can be inspected and replayed.
acceptance_criteria: A confirmed StudyArea has a saved Polygon/MultiPolygon artifact that resolves to a matching typed Artifact, projected horizontal CRS with canonical axis units, finite valid positive-area geometry, canonical geometry hash, confirmation actor/time/event, supersedes lineage, and active project pointer. Runtime stage authorization verifies the persisted StudyArea plus matching confirmation and activation events. All four exploratory stages run from it without an approved Site or DesignBoundary. Formal cadastral, ownership, zoning-compliance, and legal-buildability claims fail closed until an approved DesignBoundary carries explicit HumanDecision data.
dependencies: The Parameter Registry and project-decision rules in 05_EVIDENCE_FRAMEWORK.md.
failure_condition: A run proceeds without a confirmed StudyArea, missing or unresolved/mismatched Artifact metadata, missing artifact/hash/CRS/units, invalid or non-finite geometry, a mismatched supersedes link, missing runtime confirmation/activation events, or a formal claim without an approved HumanDecision-backed DesignBoundary.

### P0-02 - Frozen PDOK and OpenStreetMap data

id: P0-02
description: Use frozen PDOK and OpenStreetMap snapshots as the authoritative input for the MVP benchmark.
user_value: Lets the designer reproduce and audit the same site evidence after an external service changes.
acceptance_criteria: Each snapshot retains source identity, query/request, retrieval timestamp, license or attribution, raw artifact reference, version, and content hash; derived inputs link to exact snapshot versions; changed live responses create new versions.
dependencies: P0-01; snapshot and artifact rules in 05_EVIDENCE_FRAMEWORK.md; registered source adapters.
failure_condition: A final benchmark value relies only on a live response, an unhashed input, missing attribution, or an unresolved snapshot.

### P0-03 - Controlled QGIS MCP integration

id: P0-03
description: Provide the mandatory QGIS MCP integration through a controlled facade for confirmed StudyArea analysis and evidence rendering.
user_value: Gives the designer reproducible GIS analysis while keeping external execution bounded and inspectable.
acceptance_criteria: Use a controlled QGIS project/profile where practical; record compatible client/server/plugin versions; expose only allow-listed operations and controlled paths; deny unrestricted code execution, dynamic Python, unrestricted SQL, and equivalent bypasses; serialize operations; treat post-dispatch connection loss as outcome unknown until reconciliation.
dependencies: P0-02; backend-owned project state; deterministic verifier.
failure_condition: The agent can execute arbitrary QGIS code, bypass the facade, treat the live canvas as authoritative, or blindly retry an outcome-unknown dispatch.

### P0-04 - Typed evidence for material outputs

id: P0-04
description: Represent every major analytical output and material claim as an Evidence Card linked through source, claim, parameter, metric, method, tool, result, interpretation, and decision.
user_value: Lets the designer inspect why a result exists, identify missing support, and challenge the conditions behind it.
acceptance_criteria: Required card fields resolve to the correct project, scenario, inputs, units, result, and timestamps; numerical/comparative claims show evidence, scope, assumptions, limitations, and validation status; statuses distinguish unverified, validated, invalid, superseded, and contested; evidence classes remain distinct.
dependencies: 05_EVIDENCE_FRAMEWORK.md; P0-02; typed evidence and artifact interfaces.
failure_condition: The system displays an unsupported number, loses source/version provenance, conflates missing with zero, or promotes illustrative text or LLM prose to validated evidence.

### P0-05 - Contestable accessibility metric

id: P0-05
description: Compute the approved accessibility fraction using fixed origins, selected grocery destination taxonomy, network snapshot, threshold, scenario-specific public-passage overlays, unreachable-origin handling, and denominator rules.
user_value: Gives the designer an inspectable accessibility comparison whose assumptions can be changed and rerun.
acceptance_criteria: Default threshold is 800 m; versioned reruns support 400 m, 800 m, and 1200 m; each result records origin set, destinations, snapshots, threshold, overlays, unreachable origins, denominator, and units; changing building height only leaves accessibility unchanged; original evidence is preserved.
dependencies: P0-01; P0-02; P0-03; P0-08.
failure_condition: Any denominator, destination, network, threshold, or public-passage rule is hidden; a height-only edit changes accessibility without a graph change; or a challenge overwrites the original.

### P0-06 - Two COMPAS morphology families

id: P0-06
description: Generate bounded morphology candidates with COMPAS using the approved perimeter-block and linear-block families.
user_value: Lets the designer compare two interpretable families within a controlled computational design space.
acceptance_criteria: Both families produce typed geometry artifacts for the confirmed StudyArea and effective constraints; one accepted candidate from each family is retained in the demonstration; generators, parameters, seeds where applicable, constraints, and geometry hashes are recorded; invalid and rejected candidates remain inspectable.
dependencies: P0-01; P0-04; P0-08; registered COMPAS operators.
failure_condition: A candidate uses unregistered free-form geometry, lacks generator/parameter lineage, or disappears after rejection.

### P0-07 - Scenario lineage and versioning

id: P0-07
description: Preserve immutable parent-child lineage for every generated, modified, accepted, rejected, forked, and rerun scenario.
user_value: Allows the designer to understand how a design changed and compare alternatives without losing history.
acceptance_criteria: Every version records parent, site-model version, generator/operator, seed where applicable, parameters, constraints, reason, geometry hash, and status; forks do not mutate parents; rejected alternatives and result versions remain linked.
dependencies: P0-04; P0-06; typed project-state interfaces.
failure_condition: A scenario is edited in place, loses its parent/hash, receives a result from the wrong version, or is deleted when rejected.

### P0-08 - Deterministic validation and relationship checks

id: P0-08
description: Validate schemas, relationships, CRS, units, geometry, artifacts, tool status, and domain invariants before evidence or claims become authoritative.
user_value: Prevents plausible-looking but wrong GIS, geometry, simulation, or comparison results from guiding design decisions.
acceptance_criteria: CRS/unit mismatches fail closed; geometry, site containment, hard constraints, artifact existence, hashes, NaN/Inf values, exit status, and required relationships are checked; existing-but-wrong evidence IDs and scenario/result mismatches are rejected; schema validity alone is insufficient.
dependencies: P0-02; P0-04; registered deterministic tools and validation interfaces.
failure_condition: An invalid CRS, unit, geometry, artifact, relationship, or mismatched run reaches validated status.

### P0-09 - Bounded agent interaction

id: P0-09
description: Use one controlled workflow with bounded Orchestrator, Site Intelligence, Morphological Exploration, Scenario Critic, Climate Co-Designer, and Verifier capabilities.
user_value: Provides useful agent assistance without allowing an autonomous black-box workflow to author calculations or decisions.
acceptance_criteria: The Orchestrator owns routing, permissions, and transitions; roles return structured plans/claims/comparisons/experiment proposals; agents use validated evidence bundles; deterministic software performs deterministic operations directly; agents cannot invent numeric results.
dependencies: P0-04; P0-08; registered tools and project-state interfaces.
failure_condition: An agent writes authoritative numbers, calls an unregistered tool, treats prose as approval, or bypasses validation or permissions.

### P0-10 - Contestability actions

id: P0-10
description: Implement Inspect, Challenge, Modify, Rerun, Compare, Fork, Reject, and Override as state-changing, append-only contest events.
user_value: Lets the designer alter reasoning conditions, test consequences, and retain an auditable history of disagreement.
acceptance_criteria: Inspect exposes the chain; Challenge marks the target contested; Modify versions the changed condition; Rerun creates new results; Compare reports scope and stability; Fork creates lineage; Reject records a reason; Override records a human decision; the accessibility 800 m challenge supports 400/800/1200 m reruns while retaining prior evidence.
dependencies: P0-04; P0-05; P0-07; P0-17; P0-18.
failure_condition: A challenge only displays an explanation, does not change computational state, erases the original, or cannot expose the resulting event and comparison.

### P0-11 - Evidence-bounded Scenario Critic

id: P0-11
description: Compare scenarios using validated evidence bundles and label observations, comparisons, inferences, limitations, and trade-offs without silently ranking a scenario as best.
user_value: Helps the designer understand measured differences while keeping preference open to challenge.
acceptance_criteria: Every critic claim identifies evidence IDs, assumption IDs, scope, and uncertainty/limitations; comparisons include primary accessibility plus descriptive FAR, coverage, and height; conflicting or unstable results are shown; normative preference requires an explicit human decision rule.
dependencies: P0-04; P0-05; P0-07; P0-08; P0-09.
failure_condition: The critic invents metrics, cites the wrong scenario, omits conflict, or calls an option best without an accepted decision rule.

### P0-12 - Ladybug climate screening

id: P0-12
description: Provide Ladybug/ladybug-radiance screening for the approved incident-radiation objective.
user_value: Gives the designer a bounded, interpretable first pass before verification.
acceptance_criteria: Screening records geometry, weather, materials, context, sensor definition, recipe/settings, tool version, and hashes; reports area-weighted summer cumulative incident radiation and spatial distribution; shows screening limitations and keeps its method status distinct from verification.
dependencies: P0-04; P0-08; approved climate settings in 05_EVIDENCE_FRAMEWORK.md.
failure_condition: Screening hides assumptions, uses a sensor inside a candidate footprint, or is presented as verified thermal-comfort evidence.

### P0-13 - Honeybee-Radiance verification

id: P0-13
description: Verify the selected climate experiment with Honeybee-Radiance and compare changes within each method.
user_value: Gives the designer a second method and makes directional agreement or disagreement visible.
acceptance_criteria: Verification records weather, geometry, sensor-grid, recipe/settings hashes, tool version, and result artifacts; absolute screening and verification outputs are not numerically interchanged; baseline-to-offset changes are compared within each method; hash mismatches block unqualified comparison.
dependencies: P0-12; P0-08; pinned Honeybee-Radiance execution settings.
failure_condition: Verification lacks provenance, silently mixes methods, ignores hash mismatch, or claims directional agreement without within-method comparison.

### P0-14 - One controlled climate refinement experiment

id: P0-14
description: Run one experiment on one selected scenario and one selected building using translation along one declared axis, one baseline, and two feasible offsets.
user_value: Lets the designer test a small, interpretable climate intervention with locked conditions and a reproducible outcome.
acceptance_criteria: Record control, building, axis, baseline, offsets, expected direction, and comparison/stopping rule; lock footprint, floors, height, FAR where applicable, weather, materials, context, sensor definition, and settings; keep the sensor outside every footprint; report area-weighted summer cumulative incident radiation plus spatial distribution; retain failed improvement hypotheses.
dependencies: P0-06; P0-07; P0-08; P0-12; P0-13.
failure_condition: Undeclared variables change, a locked condition is violated without rejection, the sensor overlaps a footprint, or a failed hypothesis is hidden.

### P0-15 - Basic evidence map

id: P0-15
description: Provide a basic map for the confirmed StudyArea, frozen source layers, scenario context, and selected evidence locations or overlays.
user_value: Gives the designer a spatial way to inspect what a metric or claim refers to.
acceptance_criteria: Map identifies site and snapshot versions; layers/evidence open source, parameter/method context, result status, and hash/artifact reference; CRS/unit state is visible or discoverable; missing data and modelled access are distinct from zero and verified public access.
dependencies: P0-01; P0-02; P0-03; P0-04.
failure_condition: A map layer has unknown provenance, hides CRS/unit state, or makes data absence look like measured absence.

### P0-16 - Basic 3D massing

id: P0-16
description: Provide basic 3D massing views for selected and alternative validated scenario geometry artifacts.
user_value: Lets the designer relate evidence and climate results to the form being evaluated.
acceptance_criteria: View identifies scenario version and geometry hash; accepted, rejected, invalid, and superseded states remain distinguishable; the MVP needs no live Rhino, Grasshopper, or Revit connector; shown geometry is the analyzed artifact or labelled preview.
dependencies: P0-06; P0-07; P0-08; P0-15.
failure_condition: The view shows wrong-version or unvalidated geometry as analyzed, or requires a deferred CAD connector.

### P0-17 - Append-only Design Ledger

id: P0-17
description: Maintain a structured Design Ledger for project, data, analysis, scenario, contest, and decision events.
user_value: Provides a replayable account of how evidence and designs changed.
acceptance_criteria: Events record timestamp, actor, type/action, project and scenario versions, inputs, tool/version, parameters, outputs, evidence, assumptions, human status, parent, and superseded references; snapshots, analyses, generations, rejections, challenges, reruns, experiments, and decisions are retained; updates append events transactionally; chat, canvas, browser, and prose are not authoritative.
dependencies: P0-02; P0-04; P0-07; typed project-state interfaces.
failure_condition: An event is rewritten/deleted, a prior decision disappears, or a result cannot be tied to inputs, tool run, evidence, and human response.

### P0-18 - Human decisions and overrides

id: P0-18
description: Record human acceptance, rejection, modification, and override decisions with author, timestamp, reason, target, and resulting event.
user_value: Keeps design authority with the human designer and makes disagreement reviewable.
acceptance_criteria: A human can accept/reject a proposal with reason; a modification creates new versions and a contest event; an override appends a governing decision while retaining the recommendation and evidence; the selected demonstration scenario identifies its governing human decision.
dependencies: P0-16; P0-17; human-status rules in 05_EVIDENCE_FRAMEWORK.md.
failure_condition: The agent recommendation is treated as approval, a response lacks actor/reason, or an override rewrites computed or invalid evidence.

### P0-19 - Provider-independent model adapter

id: P0-19
description: Keep the application independent of any single LLM provider through an adapter for planning, structured claims, critique, and experiment proposals.
user_value: Allows the prototype to change reasoning providers without changing project truth or deterministic contracts.
acceptance_criteria: Domain code consumes internal schemas; each model run records provider, model ID, adapter and prompt/template versions/hashes, request, response hash, and rationale summary where useful; malformed/unsupported output is rejected or unverified; no commercial provider is required by the application contract.
dependencies: P0-04; P0-08; P0-09; tool and project-state interfaces.
failure_condition: Provider-specific messages leak into domain state, model output bypasses validation, model metadata is missing, or one provider is silently required.

### P0-20 - Replayable export and complete case

id: P0-20
description: Export a research bundle and replay one complete Understand, Explore, Test, and Refine case ending in a human decision.
user_value: Gives the designer and reviewer a portable account that can be checked outside the live interface.
acceptance_criteria: Export manifests snapshots, scenario versions, metric/method/tool runs, artifacts, evidence cards, contest events, decisions, and hashes; portable citation metadata is retained where applicable; replay reconstructs selected lineage and reports unavailable/mismatched artifacts; rejected, challenged, and superseded history is retained.
dependencies: P0-01 through P0-19; P0-21; provenance and citation rules in 05_EVIDENCE_FRAMEWORK.md.
failure_condition: Export omits source/hash/version/decision, replay cannot reconstruct lineage, history is silently dropped, or an incomplete case is presented as complete.

### P0-21 - Explicit decision rules and no hidden aggregate score

id: P0-21
description: Keep descriptive metrics and trade-offs visible and require a human-supplied decision rule for normative ranking or aggregate weighting.
user_value: Prevents an opaque score from deciding what counts as a better urban design.
acceptance_criteria: Report primary accessibility, FAR, coverage, height, and climate outcomes with units/status; provide no hidden default objective weights; store any weighting/ranking rule as a versioned project decision; preserve comparisons without a ranking rule.
dependencies: P0-04; P0-11; P0-17; P0-18.
failure_condition: Metrics collapse into an unexplained score, a scenario is called best without a decision rule, or weighting is hidden from the evidence chain.

## P1 — After the MVP path is stable

* P1-01: Add courtyard, cluster, or hybrid morphology operators while preserving lineage and validation.
* P1-02: Add more urban metrics or a carefully scoped Space Syntax lens with formulas, units, sources, fixtures, and sensitivity settings.
* P1-03: Evaluate NSGA-II or another bounded multi-objective method under a registered benchmark.
* P1-04: Add stronger parameter sensitivity workflows and stability reporting.
* P1-05: Configure more model providers and provider-regression evaluation.
* P1-06: Improve map, 3D, evidence navigation, and export presentation.
* P1-07: Add richer climate recipes after the single radiation experiment is reproducible.

## P2 — Later research or product directions

* P2-01: Multi-site benchmarking beyond the approved Rotterdam M4H pilot.
* P2-02: Additional climate/performance domains such as CFD, UTCI, energy, or full climate optimization.
* P2-03: Collaboration, enterprise permissions, resident participation, or claims of comprehensive democratic contestability.
* P2-04: Global data-source adapters and non-Netherlands data models.
* P2-05: Fine-tuning, autonomous agent swarms, or provider-specific application architecture.
* P2-06: Live CAD synchronization and production-scale deployment.

## OUT OF SCOPE for this prototype

The following are excluded from P0 and must not enter as implicit acceptance criteria:

* NSGA-II, MAP-Elites, or a broad optimizer UI beyond the approved bounded morphology workflow.
* Full Space Syntax, global sensitivity libraries, and a large unbounded metric catalog.
* Multiple sites, global adapters, or live changing APIs as final benchmark inputs.
* Free-form AI geometry or unrestricted QGIS code execution, dynamic Python, SQL, or batch bypasses.
* CFD, UTCI, energy, complete thermal-comfort claims, and full climate optimization.
* Rhino, Grasshopper, Revit connectors, and live CAD synchronization.
* Collaboration/enterprise functionality, multi-user permissions, or resident/democratic contestability claims.
* Fine-tuning or a mandatory commercial LLM provider.
* Claims of a universal best city, walkability truth, or proven thermal comfort from lower radiation alone.

## Traceability

* [Evidence contracts](05_EVIDENCE_FRAMEWORK.md) define fields, statuses, provenance, hashes, snapshots, confidence, citations, and contest transitions.
* [Product vision](00_PRODUCT_VISION.md) defines the user-facing framing.
* [System architecture](02_SYSTEM_ARCHITECTURE.md) defines state ownership, adapters, and execution boundaries.
* [Agent architecture](03_AGENT_ARCHITECTURE.md) defines bounded roles and permissions.
* [Evaluation framework](06_EVALUATION_FRAMEWORK.md) defines verification and research evaluation.
* [Implementation plan](07_IMPLEMENTATION_PLAN.md) defines milestones.
* [Repository governance](../AGENTS.md) defines development and model governance.
