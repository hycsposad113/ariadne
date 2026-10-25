# Agent Architecture

> **2026-09-22 現行規劃修訂：** 本文件採納 [工作流程與學期排程修訂契約](08_WORKFLOW_REALIGNMENT_2026-09-22.md)。其中第 5 節明列的產品範圍與排程條款優先於下方保留的舊版敘述；未列為取代的安全、證據與人類決策契約繼續有效。學期 W4 合併平台接入與基地分析，W5 開始生成／編輯，W8 驗收核心、W9 收尾。這是規劃修訂，不是實作或政策批准。

新增受限任務：基地證據解釋、設計訴求轉成待確認的 hard/soft constraints、有來源的案例／圖像檢索、3–5 策略提議、作用範圍明確的幾何命令、分析比較。模型不能直接操作 ledger 或批准設定。Syntax 的尺度不自動等於交通模式；影像與空間氛圍描述不等於模擬證據。真實 provider 接入、錯 evidence／單位／版本拒絕，以及人類接受 gate 都是驗收要求。六角色仍是同一受控 harness 的能力，不要求新增無界自主代理。

Status: approved role and control architecture for the documentation handoff. The six roles below are capabilities invoked by one controlled application harness. They do not imply six independent autonomous processes.

## 1. Governing principle

The system is a controlled agentic state machine:

> LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.

The Orchestrator is primarily deterministic. It owns state transitions, policy, permissions, tool routing, approvals, retries, stale-state handling, outcome reconciliation, and ledger commits. A model may help with planning, interpretation, hypothesis generation, or narrative synthesis, but model text is never project state, evidence, a calculation, or permission.

Roles are bounded capabilities behind one harness. A role cannot invoke another role directly, bypass a harness gate, write an immutable artifact, mutate a previous ledger event, or promote its own proposal to an accepted decision. If deterministic software is sufficient, the operation remains a deterministic service rather than becoming an agent action.

## 2. Controller, state, and permission model

The harness receives a typed command with a project revision and idempotency key. It performs schema and precondition checks, invokes at most the permitted role capability, resolves only registered tools, validates returned artifacts and relationships, writes state and ledger events transactionally, and returns a typed status. The harness may stop without producing a result when evidence, approval, or external execution status is insufficient.

The backend owns authoritative project state. Roles may read only the state and Evidence Bundle granted for their current stage. They may propose new records through the harness, but they cannot directly update SQLite, delete artifacts, rewrite a scenario, or alter a prior event. Immutable files hold input snapshots and result artifacts; the append-only Design Ledger records lineage, challenges, reruns, rejections, overrides, and human decisions.

### Permission principles

| Boundary | Allowed | Forbidden |
| --- | --- | --- |
| Role → harness | typed role request and proposed output | direct database writes, hidden state transitions |
| Harness → tool adapter | registered tool, validated parameters, approved input artifacts | arbitrary tool names, unvalidated paths or code |
| Harness → model adapter | bounded context, schema, evidence bundle, prompt-template version | private credentials, arbitrary filesystem, unbounded chat history |
| Role → evidence | inspect cited artifacts and metadata within scope | treating prose or an ID alone as proof |
| Human → project | challenge, modify assumptions, approve, reject, override | rewriting computed result bytes or old events |
| QGIS facade → QGIS MCP | allow-listed operations on controlled layers/directories | unrestricted code, dynamic Python, unrestricted SQL, bypass batch calls |

The harness assigns role permissions from the current project stage, target revision, and approval state. A role receives no authority merely because a model requested it.

## 3. Role contracts

Each role has the following contract. The YAML is normative at the field level; concrete schema names and versions are implementation details that must be pinned when code is introduced.

### Orchestrator

```yaml
name: Orchestrator
mission: >-
  Advance the approved four-stage workflow through deterministic state
  transitions while enforcing permissions, evidence, approvals, recovery,
  and append-only provenance.
inputs:
  - typed user command
  - project and state revision
  - current stage and approval state
  - role request or model Plan, when semantic planning is useful
  - registered tool and policy versions
outputs:
  - validated next action or explicit stop status
  - state transition and Design Ledger event
  - tool/model run references and immutable artifact references
  - approval request, rejection, stale result, or OUTCOME_UNKNOWN status
allowed_tools:
  - model adapter for bounded Plan or rationale summary
  - registered role capabilities through the harness
  - policy/precondition validators
  - registered tool facades and artifact store
  - SQLite transaction and append-only ledger writer
forbidden_actions:
  - direct unvalidated external tool execution
  - treating model output, chat, browser, or QGIS canvas as authoritative state
  - bypassing human approval or verifier gates
  - rewriting prior events, computed results, or evidence relationships
  - blindly retrying a post-dispatch uncertain operation
  - inventing a value, constraint, metric, or evidence relationship
required_evidence:
  - command identity and idempotency key
  - current project revision and precondition result
  - role/tool/model outputs with versions and hashes
  - validation result and resulting state transition
  - human decision when approval is required
validation:
  - schema and precondition validation before dispatch
  - relationship and deterministic validation after every role/tool output
  - transactional state-plus-ledger commit
  - outcome reconciliation for external execution
human_approval:
  - required for site adoption, constraint activation, proposal acceptance,
    experiment-plan approval, and consequential override
  - not required for a previously approved deterministic rerun with unchanged
    approved inputs and parameters
failure_conditions:
  - missing evidence, approval, permission, or required input
  - stale project revision or incompatible artifact versions
  - validator failure, tool/model failure, or unresolved external outcome
  - any attempt to perform an unregistered or prohibited action
handoff_targets:
  - Site Intelligence
  - Morphological Exploration
  - Scenario Critic
  - Climate Co-Designer
  - Verifier
```

The Orchestrator does not decide which design is best. It stops at a human decision boundary and records the decision that follows.

### Site Intelligence

```yaml
name: Site Intelligence
mission: >-
  Build an evidence-grounded Site Model from the human-confirmed StudyArea and
  analysis-specific frozen PDOK/OSM inputs, exposing data coverage,
  assumptions, and gaps.
inputs:
  - human-confirmed StudyArea artifact and version
  - optional proposed or approved DesignBoundary (required only for formal claims)
  - frozen PDOK and OSM snapshots
  - source metadata, licenses, queries, and retrieval timestamps
  - project CRS, vertical reference, units, origin/destination settings
  - approved accessibility definition and network policy
outputs:
  - normalized Site Model and layer/artifact references
  - deterministic site metrics and accessibility result requests
  - source-linked observations, assumptions, data gaps, and limitations
  - evidence bundle suitable for downstream roles
allowed_tools:
  - pdok snapshot and normalization adapter
  - osm snapshot, POI, and walkable-network adapter
  - allow-listed QGIS MCP facade for loading, CRS checks, and GIS metrics
  - deterministic geometry, network, FAR, coverage, and height validators
  - model adapter for questions, interpretations, and evidence-grounded summaries
forbidden_actions:
  - use of live unsnapshotted data as final research input
  - treating missing observations as measured zero
  - treating modeled access as verified legal/public access
  - changing the confirmed StudyArea, taxonomy, network policy, or constraints
    without a human decision and new project revision
  - treating StudyArea confirmation as cadastral, ownership, zoning, or legal
    buildability evidence
  - executing arbitrary QGIS code, SQL, or unregistered processing
  - making normative claims about the best design
required_evidence:
  - boundary artifact and SHA-256
  - PDOK/OSM snapshot hashes, query/source/license metadata
  - CRS, vertical reference, units, transforms, and layer provenance
  - origin set, grocery destination taxonomy, network snapshot, threshold,
    denominator, unreachable origins, and public-passage policy
  - metric definitions, tool runs, versions, parameters, and limitations
validation:
  - geometry and CRS/unit preconditions
  - known-answer/reference fixtures for site and network metrics
  - snapshot and hash verification
  - evidence relationship and coverage validation
human_approval:
  - StudyArea confirmation is required before the four exploratory stages;
    runtime authorization re-resolves its persisted Artifact, StudyArea, and
    matching confirmation/activation events
  - a separate persisted HumanDecision-backed DesignBoundary approval is required for
    CADASTRAL, OWNERSHIP, ZONING_COMPLIANCE, or LEGAL_BUILDABILITY claims
  - not required to inspect or prepare a proposal for approval
failure_conditions:
  - missing or inconsistent snapshot, CRS, units, denominator, or provenance
  - unavailable data presented as a positive observation
  - network or layer result fails reference validation
  - QGIS outcome is unknown and cannot be reconciled
handoff_targets:
  - Orchestrator
  - Morphological Exploration
  - Scenario Critic
```

The approved accessibility metric is the fraction of a fixed, approved set of public-access reference points that can reach at least one selected grocery destination within network distance less than or equal to the selected threshold. The initial threshold is 800 m, with 400 m, 800 m, and 1200 m as contestability reruns. These are project settings, not universal walking-distance standards. A building-height-only change must not alter the pedestrian graph.

### Morphological Exploration

```yaml
name: Morphological Exploration
mission: >-
  Produce bounded, traceable urban-mass proposals using registered COMPAS
  morphology operators and explicit project constraints.
inputs:
  - confirmed StudyArea and site-model revision for the requested analysis
  - approved DesignBoundary only when a formal claim is requested
  - approved constraints and assumptions
  - parent scenario or explicit root scenario
  - morphology family, parameters, seed, and mutation reason
  - relevant validated site evidence
outputs:
  - candidate geometry artifact and hash
  - scenario lineage including parent, generator version, seed, parameters,
    constraints, mutation, and reason
  - deterministic geometry/FAR/coverage/height validation report
  - accepted or rejected candidate status with evidence-linked reason
allowed_tools:
  - registered COMPAS generator and mutation adapter
  - deterministic geometry and area-metric validators
  - artifact store and scenario-lineage writer through the harness
  - model adapter for bounded proposal wording or hypothesis generation
forbidden_actions:
  - direct vertex generation from unconstrained model prose
  - unregistered geometry operators or hidden parameter changes
  - deleting rejected candidates or mutating parent scenarios
  - accepting a candidate, changing constraints, or declaring a best design
  - changing pedestrian accessibility by changing height alone
  - arbitrary QGIS execution or direct database writes
required_evidence:
  - confirmed StudyArea and constraint revision
  - parent scenario and geometry hash, or explicit root identity
  - generator/operator version, seed, parameters, and mutation reason
  - geometry, FAR, coverage, height, and hard-constraint validation outputs
  - rejected-candidate reason and related ledger event
validation:
  - geometry validity and site containment
  - hard constraints, units, and CRS checks
  - same seed/config deterministic geometry hash check
  - morphology-family and lineage consistency
human_approval:
  - required to activate or change design constraints
  - required to accept a generated proposal as a project candidate
  - not required to generate inspectable candidates or preserve rejections
failure_conditions:
  - invalid geometry, overflow, self-intersection, or constraint violation
  - missing parent, seed, parameters, operator version, or site revision
  - lineage cannot be reconstructed
  - proposal relies on unsupported ranking or fabricated evidence
handoff_targets:
  - Orchestrator
  - Scenario Critic
  - Climate Co-Designer
  - Verifier
```

The MVP requires perimeter-block and linear-block families, with at least one accepted candidate from each family after validation and human decision. Rejected candidates remain inspectable.

### Scenario Critic

```yaml
name: Scenario Critic
mission: >-
  Compare validated scenarios and state bounded observations, comparisons,
  inferences, assumptions, limitations, and trade-offs without inventing a
  metric or collapsing multiple objectives into an implicit overall ranking.
inputs:
  - validated Evidence Bundle only
  - scenario lineage and comparison-compatible revisions
  - metric definitions, units, assumptions, and sensitivity variants
  - human-supplied decision rule when a normative comparison is requested
  - challenge event or rerun result when applicable
outputs:
  - evidence-linked Claim or ClaimSet
  - explicit claim type: observation, comparison, inference, or normative
    judgment
  - assumptions, scope, uncertainty, limitations, and sensitivity statement
  - proposed challenge/rerun if a premise is disputed
allowed_tools:
  - Evidence Store and Design Ledger read access through the harness
  - deterministic comparison and sensitivity services
  - model adapter for semantic interpretation and structured claim drafting
  - verifier capability for relationship and policy checks
forbidden_actions:
  - calculating or estimating numeric results in prose
  - citing nonexistent, wrong-scenario, wrong-unit, or wrong-version evidence
  - calling a scenario best without an explicit human decision rule
  - hiding conflicting metrics, assumptions, data gaps, or failed hypotheses
  - creating an implicit weighted total score
  - changing a premise without a challenge event and rerun
required_evidence:
  - every claim's evidence IDs, assumption IDs, scope, and limitations
  - metric definitions, values, units, scenario IDs, and tool-run metadata
  - input snapshot and artifact hashes
  - sensitivity variants, including 400/800/1200 accessibility where relevant
  - human decision rule for any normative judgment
validation:
  - schema validation and evidence relationship checks
  - scenario/unit/version compatibility checks
  - unsupported-claim, scope, ranking, and assumption-policy checks
  - deterministic values must agree with referenced artifacts
human_approval:
  - required for a normative decision, accepted comparison basis, or override
  - not required to produce an explicitly provisional, evidence-linked critique
failure_conditions:
  - evidence missing, incompatible, stale, or unresolved
  - claim exceeds evidence scope or turns correlation into causation
  - unsupported ranking or hidden weighting detected
  - challenge cannot identify the premise and rerun needed
handoff_targets:
  - Orchestrator
  - Site Intelligence for site/network assumption reruns
  - Morphological Exploration for design-parameter changes
  - Climate Co-Designer for bounded environmental hypotheses
  - Verifier
```

The Critic receives validated evidence rather than raw GIS or model-provider data. Its conclusion must remain bounded, for example: “under the stated network, destination taxonomy, and 800 m setting, B measures higher accessibility than A.” It cannot turn that comparison into a universal or normative design verdict.

### Climate Co-Designer

```yaml
name: Climate Co-Designer
mission: >-
  Propose and evaluate one controlled climate-design intervention whose inputs,
  locked conditions, method tier, and outcome remain reproducible and
  contestable.
inputs:
  - one human-selected scenario and building
  - approved experiment plan and independent/dependent variables
  - locked footprint, floors, height, FAR where applicable, context, weather,
    materials, true north, time convention, sensor definition, and settings
  - Ladybug screening and Honeybee-Radiance verification contracts
  - validated baseline and candidate geometry artifacts
outputs:
  - hypothesis and declared-axis translation proposal
  - baseline plus two feasible offsets within the approved experiment
  - screening and verification result artifacts with settings and hashes
  - within-method comparison, directional agreement/disagreement, constraint
    check, and accept/reject/fork recommendation
allowed_tools:
  - climate sensor-grid and recipe adapter
  - Ladybug / ladybug-radiance screening adapter
  - Honeybee-Radiance verification adapter
  - deterministic geometry, constraint, comparability, and convergence checks
  - model adapter for hypothesis and bounded interpretation
forbidden_actions:
  - changing multiple independent variables without approval
  - treating Ladybug and Honeybee-Radiance absolute values as interchangeable
  - claiming lower radiation proves thermal-comfort improvement
  - changing weather, materials, context, sensor definition, or settings silently
  - accepting a failed improvement hypothesis as success
  - executing arbitrary climate code or writing over prior results
required_evidence:
  - approved plan and human approval record
  - geometry, site/context, weather-file, material, sensor-grid, and settings
    hashes
  - true north, time convention, coordinate system, method/tool versions
  - baseline and both feasible variants
  - within-method values, spatial distribution, constraints, limitations, and
    directional agreement/disagreement between tiers
validation:
  - sensor area outside every candidate footprint
  - locked-condition and single-variable checks
  - artifact/hash and method comparability checks
  - FAR/geometry/height and other constraint recheck
  - deterministic rerun and convergence checks where configured
human_approval:
  - required before activating the experiment plan and accepting a refined
    design or override
  - not required to prepare a proposed hypothesis for review
failure_conditions:
  - missing weather/settings/sensor/geometry provenance
  - baseline or variant not comparable, or output method unclear
  - constraint violation, failed execution, or unresolved external outcome
  - no improvement or directional disagreement hidden from the record
handoff_targets:
  - Orchestrator
  - Scenario Critic
  - Verifier
```

The MVP outcome is area-weighted summer cumulative incident radiation plus spatial distribution. “Best” means only best within the tested range and metric definition, if a human has supplied that decision rule. A failed improvement hypothesis remains a valid research result.

### Verifier

```yaml
name: Verifier
mission: >-
  Determine whether schemas, tool results, evidence relationships, lineage,
  provenance, and state transitions satisfy their contracts before adoption.
inputs:
  - proposed role output or external tool result
  - typed artifact and run metadata
  - current and expected project revisions
  - metric definitions, policy rules, fixtures, and approval records
  - relevant prior ledger events
outputs:
  - PASS, FAIL, BLOCKED, STALE, REJECTED, or OUTCOME_UNKNOWN verification
  - machine-readable validation findings
  - evidence relationship verdict and provenance completeness result
  - permission to commit, request reconciliation, or stop the workflow
allowed_tools:
  - schema and precondition validators
  - deterministic geometry, CRS, unit, network, metric, and constraint tests
  - artifact/hash/provenance checker
  - Evidence Store and Design Ledger read access
  - controlled external-state reconciliation adapter
forbidden_actions:
  - replacing a deterministic check with an LLM estimate
  - accepting valid JSON as proof of semantic correctness
  - repairing a wrong result by rewriting evidence or old events
  - granting permissions, human approval, or normative preference
  - treating a lost connection as failure or success without reconciliation
required_evidence:
  - input and output artifact hashes
  - tool/model/environment/version metadata
  - schema, precondition, semantic, deterministic, and provenance findings
  - expected versus observed project/external state for uncertain runs
  - approval and revision identity for a proposed transition
validation:
  - schema, precondition, relationship, deterministic, provenance, and human
    decision validation in that order
  - known-answer fixtures and replay checks
  - stale revision and idempotency checks
  - QGIS/climate outcome reconciliation before any retry or adoption
human_approval:
  - verifier never supplies approval; it only checks that the required human
    decision exists and targets the current revision
failure_conditions:
  - any release-blocking invariant fails
  - result is stale, incomplete, incompatible, or semantically mislinked
  - external state cannot be reconciled
  - validation itself cannot run with trustworthy inputs
handoff_targets:
  - Orchestrator
  - originating role for correction or rerun
  - human designer when an approval, challenge, or scope decision is required
```

## 4. Handoffs and state transitions

Handoffs are typed messages routed by the Orchestrator. They carry the source role, target role, project revision, scenario or experiment identity, evidence bundle IDs, assumptions, requested action, idempotency key, and stopping policy. A handoff does not transfer authority over project state.

```text
Human draws QGIS polygon → confirms StudyArea
        ↓
Site Intelligence → Verifier → Orchestrator
        ↓
Morphological Exploration → Verifier → Human acceptance/rejection
        ↓
Scenario Critic → Verifier → Human challenge/rule/decision
        ↓
Climate Co-Designer → Verifier → Human accept/reject/fork
        ↓
Design Ledger + replay/export
```

The principal contestability actions are:

| Action | Required transition |
| --- | --- |
| `Inspect` | retrieve source, parameter, tool, artifact, assumption, and lineage records |
| `Challenge` | create a `ContestEvent` naming the challenged claim/assumption and its current revision |
| `Modify` | create a new assumption, constraint, radius, weight, or design parameter revision |
| `Rerun` | execute with the new revision and preserve the prior result and run |
| `Fork` | create a new scenario lineage branch from the selected state |
| `Reject` | append a rejection and reason while retaining the proposal/artifact |
| `Override` | append a human decision with author, reason, target, and resulting state |

`Challenge` must cause a state transition. A note saying “I disagree” with no changed assumption, rerun, fork, rejection, or decision event is incomplete contestability. A human override never mutates computed evidence; it adds a decision that may select or supersede a proposal while leaving the original computation auditable.

## 5. Stale state and external execution

Every handoff carries the state revision on which it was prepared. If that revision changes before application, the result becomes `STALE`; it is retained as an artifact and cannot update current project state without an explicit, compatible reconciliation action. A role must stop when its evidence bundle is stale, incomplete, or incompatible.

QGIS MCP and climate runtimes are external execution processes. A post-dispatch timeout or connection loss is `OUTCOME_UNKNOWN`, not an automatic failure and not success. The Orchestrator and Verifier reconcile expected artifacts, output hashes, run identifiers, external project revision, adapter logs, and ledger records. They do not blindly retry. A retry is allowed only when the request is confirmed not to have started, or the operation is explicitly idempotent under the same key.

QGIS requests pass through the allow-listed facade. No role may request unrestricted `execute_code`, arbitrary dynamic Python, unrestricted SQL, or a batch equivalent. Operations against one QGIS instance are serialized and unexpected project changes are detected. The backend remains authoritative over project state, regardless of what is visible on the QGIS canvas.

## 6. Stopping conditions

The harness must stop and return a typed status when any of the following holds:

- required human approval is absent or targets an earlier revision;
- required evidence, provenance, source snapshot, metric definition, unit, CRS, or setting is missing;
- a role requests a forbidden tool, unregistered parameter, arbitrary code, or hidden weighting;
- a deterministic validator or semantic relationship check fails;
- a result is stale or comparison inputs are incompatible;
- an external execution outcome is unknown and reconciliation is insufficient;
- an experiment violates a locked condition or has multiple undeclared variables;
- a claim exceeds the scope of its evidence or asserts a normative ranking without a human rule;
- a required release-blocking test has not passed.

Stopping is a valid outcome. The system must preserve the attempted action, failure or uncertainty, and next human action needed in the ledger. It must not convert a blocked or unresolved workflow into a plausible narrative.

## 7. Human contestability and release gates

The designer must be able to inspect the evidence chain, challenge an assumption, modify the premise, rerun deterministic analysis, compare old and new results, reject an agent proposal, fork a scenario, and override a consequential decision with a recorded reason. These actions must be visible in the UI and reconstructable from SQLite plus immutable artifacts.

Release-blocking tests are binary and all must pass; there is no aggregate “95% pass” waiver. The authoritative test identifiers and assertions are defined in [06_EVALUATION_FRAMEWORK.md](06_EVALUATION_FRAMEWORK.md). Role-specific coverage includes:

| Concern | Authoritative evaluation tests |
| --- | --- |
| CRS, units, deterministic geometry, graph and metric correctness | `DET-001` through `DET-009`; `ACC-001` through `ACC-008` |
| Role permissions, evidence relationships, stale results and model output | `AGT-001` through `AGT-010`; `EVD-001` through `EVD-008` |
| Morphology validity, reproducibility and lineage | `MOR-001` through `MOR-006` |
| QGIS MCP restriction and uncertain execution | `SEC-001` through `SEC-006` |
| Separate climate methods and controlled experiment evidence | `CLM-001` through `CLM-009` |
| State-changing human contestability and preserved decisions | `CON-001` through `CON-008` |
| Map/3D identity and complete research demonstration | `UI-001`, `UI-002`, and `BEN-001` through `BEN-005` |

The six roles are complete only when these gates, the corresponding evidence checks, and the required human decision boundaries are implemented and independently verified. Until then, this document describes intended architecture and unresolved feasibility remains visible.

`STALE` and `REJECTED` are operational states used to preserve an unusable
result or candidate with its reason. They are not release verdicts. For
evaluation, every release-blocking check is reported as `PASS`, `FAIL`,
`BLOCKED`, or `OUTCOME_UNKNOWN`, and all such checks must be `PASS` before
release.
