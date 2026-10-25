# System Architecture

> **2026-09-22 現行規劃修訂：** 本文件採納 [工作流程與學期排程修訂契約](08_WORKFLOW_REALIGNMENT_2026-09-22.md)。其中第 5 節明列的產品範圍與排程條款優先於下方保留的舊版敘述；未列為取代的安全、證據與人類決策契約繼續有效。學期 W4 合併平台接入與基地分析，W5 開始生成／編輯，W8 驗收核心、W9 收尾。這是規劃修訂，不是實作或政策批准。

新增的工作區快照、保留／可改 overlay、局部分區 brief、Syntax adapter、道路＋量體生成、幾何命令與出圖仍透過既有 typed backend／SQLite／ledger。前端即時儀表板可顯示標記清楚的預覽，但正式接受與分析必須後端重算。道路／通道／入口的明確版本化變更可以觸發 graph 更新；單純高度變更仍不得改 accessibility。天氣依賴按分析方法檢查，E1 不一律依賴 EPW。新模組地圖見中文整體計畫；不得假稱新增介面已實作。

Status: approved architecture with the Milestone 1 foundation implemented. The interfaces below remain contracts for later stages. QGIS MCP has a passing smoke through a disposable QGIS-LTR profile, and both Ladybug and Honeybee-Radiance have passing real smoke records using a separate Radiance 6.0.2 ARM64 runtime. The documented local QGIS fallback is the verified Intel QGIS-LTR binary under Rosetta on the ARM host; native ARM portability remains a pre-release deployment check.

## 1. Purpose and governing boundary

The system is a local, single-user, evidence-based and contestable urban-design prototype. A human-confirmed `StudyArea` is the exploration envelope; it is not a legal or cadastral site. A separate `DesignBoundary` may later be approved through explicit `HumanDecision` data for formal claims. The workflow is:

For the current single-site demonstration, the active exploration envelope is
the human-confirmed Rotterdam M4H `StudyArea` v5. Delft packages and rejected
or proposed Rotterdam boundary experiments are historical evidence only; the
architecture does not treat them as the active site or as formal approval.

```text
DRAW / CONFIRM  StudyArea (human action)
     ↓
UNDERSTAND  Site Intelligence
     ↓
EXPLORE     Morphological Exploration
     ↓
TEST        Scenario Critic
     ↓
REFINE      Climate / Performance Co-Designer
     ↓
HUMAN       Inspect, challenge, rerun, compare, reject or override
```

The governing rule is:

> LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.

The application is model-provider independent. OpenAI, another cloud provider, or an optional local model may supply semantic reasoning through the same internal model adapter. The provider, message format, and provider-specific tool protocol must not become part of the typed domain model.

The approved MVP is deliberately bounded: one human-confirmed Rotterdam M4H StudyArea; analysis-specific frozen PDOK and OSM snapshots; mandatory QGIS MCP; perimeter-block and linear-block COMPAS families; one accepted candidate from each family; retained rejected candidates; the approved network accessibility metric; descriptive or constraint measures for FAR, coverage and height; one assumption challenge and rerun; one controlled climate experiment; Ladybug screening; Honeybee-Radiance verification; basic map and 3D massing; scenario comparison; Evidence Inspector; bounded agent interaction; and the Design Ledger. Formal DesignBoundary approval is a later human gate for formal claims, not a prerequisite for exploration. Multiple sites, broad metric catalogs, additional providers, Rhino/Grasshopper/Revit connectors, and other generative-search systems remain deferred.

## 2. Conceptual stack and process boundaries

```text
┌──────────────────────────────────────────────────────────────┐
│ React / TypeScript Web IDE                                   │
│ map · basic 3D · scenario comparison · Evidence Inspector    │
└──────────────────────────────┬───────────────────────────────┘
                               │ typed HTTP/JSON API
┌──────────────────────────────▼───────────────────────────────┐
│ FastAPI application boundary                                  │
│ authentication/session boundary · request validation · API     │
└──────────────────────────────┬───────────────────────────────┘
                               │ domain commands/events
┌──────────────────────────────▼───────────────────────────────┐
│ Typed Python domain layer                                     │
│ Project · StudyArea · DesignBoundary · SiteModel · Scenario     │
│ Constraint · Assumption                                        │
│ Artifact · ToolRun · EvidenceRecord · Claim · ContestEvent     │
│ HumanDecision · ExperimentPlan                                │
└──────────────────────────────┬───────────────────────────────┘
                               │ controlled commands
┌──────────────────────────────▼───────────────────────────────┐
│ Harness / deterministic Orchestrator                          │
│ state machine · policy gates · role routing · idempotency      │
│ stale-state checks · approval gates · ledger transaction       │
└───────────────┬──────────────────────┬────────────────────────┘
                │                      │
                │ semantic plan only   │ validated tool calls
        ┌───────▼────────┐      ┌──────▼────────────────────────┐
        │ Model adapter   │      │ Validated tool interfaces      │
        │ plan/claims/    │      │ QGIS MCP · COMPAS · climate     │
        │ hypotheses      │      │ PDOK/OSM and other data inputs │
        └────────────────┘      └──────┬─────────────┬───────────┘
                                       │             │ external process boundaries
                            ┌──────────▼───┐   ┌─────▼────────────┐
                            │ deterministic │   │ QGIS / climate   │
                            │ verifiers     │   │ runtimes         │
                            └──────────┬───┘   └─────┬────────────┘
                                       │             │ immutable outputs
                            ┌──────────▼─────────────▼───────────┐
                            │ SQLite project state and ledger     │
                            │ immutable snapshots and artifacts   │
                            └─────────────────────────────────────┘
```

The web UI is a presentation and interaction client. It cannot make a browser state, chat transcript, or live QGIS canvas authoritative. FastAPI is the API boundary, not the location of unvalidated calculations. The typed domain layer defines the stable vocabulary and preconditions. The harness controls all state transitions and tool execution. Adapters isolate external tools and providers. Verifiers decide whether returned artifacts and relationships satisfy their contracts before a result can support a claim or transition project state.

QGIS and climate tools run outside the backend Python environment where required. They are separate processes or environments connected through explicit adapters, filesystem artifact exchange, and/or a constrained protocol. The process boundary is part of provenance and must be recorded in each `ToolRun`; a Python import that happens to work locally is not sufficient evidence of a supported deployment.

## 3. Component responsibilities

### React / TypeScript UI

The UI renders site layers, basic 3D massing, scenario lineage, comparisons, evidence cards, assumptions, experiment settings, and the Design Ledger. It submits typed commands such as `challenge_assumption`, `rerun_analysis`, `fork_scenario`, `reject_proposal`, and `record_override`. It displays status values including `PENDING_APPROVAL`, `RUNNING`, `SUCCEEDED`, `FAILED`, `STALE`, `OUTCOME_UNKNOWN`, `REJECTED`, and `BLOCKED` without converting them into prose claims of success.

The UI may display model rationale summaries and tool traces supplied by the backend. It does not calculate FAR, accessibility, geometry validity, radiation, or other consequential metrics in browser code. Client values are untrusted until revalidated by FastAPI and the domain layer. A UI action that changes a premise must create a backend command and an append-only event; editing a displayed result does not change the result artifact. The lifecycle labels shown here (`PENDING_APPROVAL`, `RUNNING`, `SUCCEEDED`, `FAILED`, `STALE`, `REJECTED`, and `BLOCKED`) describe operational records. Evaluation and release gates normalize their verdict to `PASS`, `FAIL`, `BLOCKED`, or `OUTCOME_UNKNOWN`; a lifecycle label never bypasses that gate.

### FastAPI API

FastAPI exposes resource and command endpoints for projects, site models, snapshots, scenarios, evidence bundles, experiments, contest events, human decisions, ledger history, and artifact retrieval. It authenticates the local session as appropriate to the deployment profile, validates request schemas, checks revision or event preconditions, and delegates to the harness.

The API returns typed status and error envelopes. It must distinguish a rejected precondition from an external run whose outcome is unknown. It must not accept a client-supplied metric result, evidence relationship, or tool status as authoritative without revalidation.

Illustrative command surface:

```text
GET  /projects/{project_id}
GET  /projects/{project_id}/scenarios/{scenario_id}
GET  /projects/{project_id}/evidence/{evidence_id}
GET  /projects/{project_id}/ledger
POST /projects/{project_id}/commands/plan
POST /projects/{project_id}/commands/challenge
POST /projects/{project_id}/commands/rerun
POST /projects/{project_id}/commands/fork
POST /projects/{project_id}/commands/reject
POST /projects/{project_id}/commands/override
POST /projects/{project_id}/experiments
GET  /artifacts/{artifact_id}
```

Exact routes may change during implementation, but every command must be represented in the ledger with actor, precondition, inputs, resulting state, and references to produced artifacts.

### Typed Python domain layer

The domain layer owns Pydantic or equivalent typed models, invariants, state transitions, and serialization schemas. Minimum entities are:

| Entity | Responsibility and required identity |
| --- | --- |
| `Project` | active StudyArea pointer, optional formal site, project settings and current revision |
| `StudyArea` | human-drawn QGIS Polygon/MultiPolygon artifact, projected CRS/units, canonical hash, confirmation event, version/supersedes lineage |
| `DesignBoundary` | formal boundary related to a StudyArea; `APPROVED` requires explicit HumanDecision data |
| `SiteModel` | frozen analysis boundary/data snapshot, CRS, units, source snapshots, normalized layers |
| `DataSnapshot` | source, query, retrieval time, license, raw artifact and hash |
| `Constraint` | explicit project decision or sourced requirement, unit, scope, status |
| `Assumption` | visible premise, source/scope, challenge status, resulting reruns |
| `DesignScenario` | parent lineage, geometry hash, parameters, constraints, status |
| `Artifact` | type, URI, SHA-256, MIME type, CRS where relevant, producer and timestamp |
| `ToolRun` | tool and version, environment, inputs, parameters, outputs, status, trace IDs |
| `ModelRun` | provider/model identity, adapter and prompt-template versions, structured request/output hashes, status |
| `MetricDefinition` | formula, unit, parameter schema, implementation version, reference fixture |
| `EvidenceRecord` | claim scope, metric/result references, assumptions, method, tool run and limitations |
| `Claim` | typed observation/comparison/inference/normative status and evidence IDs |
| `ContestEvent` | challenge/rerun/fork/reject/override command and resulting event |
| `HumanDecision` | accepted/rejected/modified/override status, author, reason and target |
| `ExperimentPlan` | locked conditions, independent/dependent variables, method tiers and approval |

Every identifier is immutable. New computations, challenges, and decisions reference prior identifiers and create new records. A human override appends a decision; it does not rewrite a computed result or make invalid evidence valid.

### Study Area confirmation and exploration gate

The bounded confirmation command accepts an already saved QGIS polygon
artifact, re-reads its bytes, verifies the artifact hash, Polygon/MultiPolygon
type, finite valid positive area, projected horizontal CRS, and explicit units,
then creates or resolves a typed `Artifact` whose project, URI, hash, size, MIME,
CRS, and producer match those bytes. Artifact registration, the append-only
`StudyArea` version, `ConfirmStudyArea`, `ActivateStudyArea`, and the active
pointer commit in one transaction. Runtime stage authorization re-resolves the
persisted StudyArea and requires matching confirmation and activation events;
an in-memory confirmed payload is insufficient. It does not approve a `Site`,
approve a `DesignBoundary`, freeze datasets, or infer ownership or legal status.
The four exploratory stages may start once the StudyArea is
`CONFIRMED_FOR_EXPLORATION`; changing the geometry creates a superseding version
and marks explicitly dependent results stale without an automatic rerun.

Unit aliases are deterministic: metre/meter spellings normalize to `m`, and
foot/feet spellings normalize to `ft` only when the projected CRS declares foot
axes. Other aliases, angular units, and CRS/unit mismatches fail closed.

Formal claim types `CADASTRAL`, `OWNERSHIP`, `ZONING_COMPLIANCE`, and
`LEGAL_BUILDABILITY` are fail-closed unless the caller supplies a typed,
`APPROVED` DesignBoundary with explicit HumanDecision data. Evidence semantics
remain distinct: `DATASET_OBSERVATION`, `COMPUTED_RESULT`, `AI_INTERPRETATION`,
`HYPOTHESIS`, and `DATA_GAP`. AI interpretations can propose risks or next
analyses, but cannot author measurements or formal claims.

### Harness / Orchestrator

The harness is a controlled state machine. It selects the next permitted stage, verifies preconditions, requests a semantic plan where useful, resolves registered tool names, applies policy and approval gates, executes adapters, runs deterministic validation, commits artifacts and ledger events transactionally, and exposes a replayable history.

The harness owns:

- stage and role routing;
- allowed-tool and parameter policy;
- approval requirements for adopting a site, activating constraints, accepting generated proposals, approving experiment plans, and overriding consequential decisions;
- idempotency keys and duplicate-dispatch prevention;
- input revision checks and stale-result handling;
- outcome reconciliation before retry;
- final status assignment and ledger commit.

The Orchestrator role is primarily deterministic. An LLM can propose a plan, summarize evidence, suggest a hypothesis, or identify a trade-off. It cannot choose an unregistered tool, calculate a numeric result, authorize a prohibited action, or silently advance a human approval gate.

## 4. Typed tool interfaces

All adapters accept and return typed requests and responses. A tool response must include the tool identity, tool-version identity, input artifact hashes, parameter values, output artifact hashes, execution status, environment metadata, and limitations. Data strings, layer labels, and model output are treated as untrusted data, never as instructions.

### QGIS MCP facade

QGIS MCP is mandatory for the MVP, but its broad underlying surface is not exposed to roles or the UI. The application supplies a narrow, versioned facade such as:

```text
urban.get_project_info
urban.validate_crs
urban.load_snapshot
urban.calculate_far
urban.build_pedestrian_graph
urban.destination_accessibility
urban.intersection_density
urban.landuse_entropy
urban.green_access
urban.render_evidence_map
```

The facade validates geometry types, CRS, units, layer identity, snapshot hashes, scenario identity, output paths, and parameter ranges before dispatch. It permits only registered processing algorithms and known output formats. It must not expose unrestricted `execute_code`, arbitrary dynamic Python, unrestricted SQL, or an equivalent batch or processing bypass. A developer/debug profile may expose additional diagnostics only when separately isolated and access-controlled; it must not make unrestricted execution available to research roles and is never the default research run.

The QGIS boundary requires, where practical:

- a dedicated QGIS project and profile;
- pinned compatible client, server, plugin, and QGIS versions;
- controlled input layers and controlled output directories;
- serialized operations against one QGIS instance;
- a lock or equivalent single-dispatch mechanism;
- detection of unexpected QGIS project changes before and after a run;
- a backend snapshot of expected project state, with the backend remaining authoritative over the live canvas.

If the connection is lost after dispatch, the status is `OUTCOME_UNKNOWN`. The harness must reconcile the expected output artifacts, output hashes, QGIS project revision, and ledger/tool-run evidence before deciding whether the operation succeeded, failed, or must remain unresolved. It must not blindly retry, because an external operation may have completed and a duplicate could be destructive or produce ambiguous state.

The Milestone 1 target profile is the verified Intel QGIS-LTR binary under
Rosetta on this Apple Silicon host, paired with the matching plugin/server and
the bounded adapter. This explicit fallback resolves local execution without
making a portability claim for native ARM QGIS or other machines. A clean
machine and native ARM smoke remain pre-release deployment checks; if that
check fails, the deployment record must retain the failure and keep the
fallback explicit.

### COMPAS adapter

COMPAS is used as a controlled geometry engine behind an application adapter. Candidate operations are registered, deterministic, and parameterized:

```text
compas.generate_typology
compas.mutate_parameter
compas.open_block
compas.redistribute_height
compas.validate_geometry
compas.compute_area_metrics
compas.export_scenario
```

The generator request includes `parent_scenario_id`, site-model revision, constraint revision, explicit parameters, and seed. The response includes a geometry artifact hash, lineage record, validation report, and rejected-candidate reason where applicable. COMPAS does not decide what is normatively preferable.

### Climate adapter

Climate execution is an external boundary where required. The adapter prepares a locked recipe, sensor grid, geometry artifact, weather file, material assumptions, true-north and time-convention metadata, then invokes the selected method and parses results into immutable artifacts.

```text
climate.make_sensor_grid
climate.screen_incident_radiation
climate.run_radiance
climate.compare_runs
climate.convergence_check
```

The MVP has two distinct tiers:

1. Ladybug / ladybug-radiance screening.
2. Honeybee-Radiance verification.

Their absolute outputs are not assumed numerically interchangeable. Comparisons are made within each method, followed by a recorded directional agreement or disagreement. The measured outcome is area-weighted summer cumulative incident radiation plus spatial distribution. It must not be described as proven thermal-comfort improvement.

The first experiment uses one selected scenario, one selected building, a declared-axis translation, a baseline, and two feasible offsets. Footprint, floors, height, FAR where applicable, weather, materials, context, sensor definition, and simulation settings are locked. The sensor area must remain outside every candidate footprint. A failed improvement hypothesis is a valid result and is preserved in the ledger.

### Data connectors

PDOK and OSM connectors retrieve or import frozen snapshots. They preserve request/query, retrieval timestamp, license, raw response, normalized artifact, and SHA-256 hash. Live responses cannot silently replace a frozen research input. Missing observations remain missing and are not converted to zero.

**Week 2 gate split (2026-09-21).** Week 2 Spatial Gate PASS unlocks Week 3 accessibility and Week 4 morphology. Weather Gate PASS is required before Week 6 climate experiments. Spatial PASS with Weather BLOCKED is a valid intermediate state. The spatial connector set is PDOK BAG `pand`, PDOK BGT `wegdeel`, PDOK BGT `waterdeel`, and one bounded OSM Overpass request. It does not request, download, inspect, or parse an EPW or ZIP weather source. Historical behavior: earlier combined acquisition text that froze a weather file inside the same Week 2 package is the pre-split path. That historical path does not make weather a Week 3 or Week 4 prerequisite.

The Site Model must record horizontal CRS, vertical reference when applicable, units, coordinate transformations, origin and destination sets, destination taxonomy, network snapshot, unreachable origins, and denominator rules. The approved accessibility metric is the fraction of a fixed, approved set of public-access reference points that can reach at least one selected grocery destination within network distance less than or equal to the selected project threshold. The initial threshold is 800 m; contestability reruns are 400 m, 800 m, and 1200 m. These are project settings, not universal walking-distance standards. Building height alone must not alter the pedestrian graph.

## 5. Model adapter and semantic boundary

The model adapter exposes provider-neutral operations such as:

```text
plan_workflow(request: PlanRequest) -> PlanResponse
summarize_evidence(bundle: EvidenceBundle) -> ClaimDraft
propose_hypothesis(context: ExperimentContext) -> HypothesisDraft
```

The adapter records provider, model ID, adapter version, prompt/template version, structured request hash, response hash, tool decisions, and a relevant rationale summary. It does not store private chain-of-thought. Provider-specific retries, token formats, and API errors are translated into internal statuses.

Model outputs are proposals. The harness checks schema, registered tool names, role permissions, evidence IDs, scenario scope, units, assumptions, and decision language. Numeric correctness, geometry validity, CRS, network distances, FAR, coverage, height, and radiation values are determined by deterministic tools and validators. A malformed or unsupported output must become a controlled failure; it must not be repaired by silently guessing.

## 6. Evidence, state, and storage

SQLite is the authoritative store for mutable project metadata, typed state, append-only Design Ledger events, lineage, claims, assumptions, human decisions, tool/model run metadata, and artifact references. Transactions must update project state and corresponding ledger events atomically. The ledger is provenance for design and research decisions; runtime tracing is separate.

Immutable files store frozen raw datasets, normalized snapshots, geometry, maps, 3D exports, sensor grids, simulation outputs, reports, and replay packages. Every large artifact is content-addressed or hash-recorded with a URI, MIME type, producer, creation time, schema/version, CRS where relevant, and SHA-256. An artifact may be superseded by a new artifact reference, but its bytes and record remain available for audit.

An Evidence Record links, at minimum:

```text
claim
→ evidence result(s)
→ metric definition and unit
→ assumption(s)
→ input snapshot/artifact hashes
→ method/tool/version
→ parameters and coordinate context
→ validation report
→ limitations and sensitivity variants
→ human review / contest event
```

The system distinguishes research findings, project decisions, dataset observations, computed results, interpretations, illustrative examples, and normative judgments. An evidence ID that exists but points to the wrong scenario, units, dataset version, or result must fail relationship validation.

The backend is authoritative for project state. Chat history, generated prose, browser state, and the live QGIS canvas are views or external observations. The four memory concerns remain separate: working request/plan, project state, evidence/artifacts, and immutable Design Ledger history.

## 7. Versioning and reproducibility

Every replayable operation pins or records:

- domain/schema version;
- project and state revision;
- site boundary and Site Model revision;
- PDOK/OSM snapshot hashes and source metadata;
- CRS, vertical reference, units, and coordinate transforms;
- scenario parent, geometry hash, generator version, seed, and parameters;
- metric definition and implementation version;
- QGIS client/server/plugin/QGIS versions where applicable;
- COMPAS and climate adapter/tool versions;
- weather file/version, time convention, true north, materials, context, sensor-grid hash, and simulation settings;
- model provider/model ID, adapter and prompt-template versions when an LLM is used;
- operating-system and architecture information for external processes;
- artifact hashes and trace/ledger IDs.

Changing any value that affects computation creates a new revision or run. Comparisons must reject incompatible revisions, including different weather hashes or sensor grids, unless an explicit comparison contract supports the difference. A replay must reconstruct the prior state and artifacts from the ledger without mutating them.

## 8. Validation gates

Validation is layered:

1. **Schema validation:** fields, types, required references, and allowed enum values.
2. **Precondition validation:** project revision, approval status, CRS, units, geometry type, input existence, permissions, and tool availability.
3. **Semantic relationship validation:** evidence belongs to the cited scenario and method; metric units and denominator rules match; claims remain within their scope.
4. **Deterministic result validation:** known-answer fixtures, geometry invariants, network topology, FAR/coverage/height checks, output completeness, and climate constraints.
5. **Provenance validation:** hashes, versions, settings, and lineage are present and consistent.
6. **Human decision validation:** required approval exists for the action and is attached to the correct target and revision.

Valid JSON is therefore not sufficient for a valid result. A claim that cites an existing but wrong-scenario evidence ID is rejected. A result with missing CRS, units, weather hash, or sensor-grid identity is blocked from comparison or decision use.

## 9. Error handling, retries, and uncertain execution

All commands and tool runs use typed statuses and an idempotency key. Errors are classified by boundary:

| Class | Examples | Required handling |
| --- | --- | --- |
| `FAILED_PRECONDITION` | missing approval, CRS mismatch, missing snapshot, disallowed tool | refuse before dispatch; no external run is claimed |
| `INVALID_REQUEST` | malformed schema, unknown scenario, invalid parameter type | return field-level error; no state mutation |
| `TOOL_FAILED` | process exits non-zero with reliable exit status | retain logs/artifacts, append failure event, no result adoption |
| `MODEL_FAILED` | provider rejects request or returns malformed structured output before tool dispatch | bounded adapter retry only under policy; otherwise fail |
| `STALE` | input revision changed while a queued or completed result is being applied | do not apply result; retain it as stale artifact and require explicit rerun |
| `OUTCOME_UNKNOWN` | post-dispatch connection loss, timeout without reliable completion, process termination ambiguity | reconcile artifacts and external state; do not blindly retry or mark success |
| `REJECTED` | validator or human rejects candidate/result | preserve candidate and reason; no silent deletion |

Retries are allowed only for a known pre-dispatch transient failure, a provider request that is confirmed not to have started, or a tool operation explicitly declared idempotent with the same idempotency key. A post-dispatch connection loss is never an automatic retry. Reconciliation checks expected artifact paths and hashes, process/run identifiers, external project revision, adapter logs, and ledger records. Outcomes are resolved to `SUCCEEDED`, `TOOL_FAILED`, `REJECTED`, `STALE`, or remain `OUTCOME_UNKNOWN` when evidence is insufficient.

## 10. Trust, security, secrets, and deployment assumptions

The frontend/backend trust boundary treats all browser input as untrusted. The backend/tool boundary treats all external process output as untrusted until validated. The model/data boundary treats model text and dataset labels as untrusted content, not executable instructions. Tool capabilities are granted by role and facade allowlist; they are not inferred from a prompt.

Site Intelligence relationship validation assumes its `RelationshipResolver` is a backend-owned, read-only project index; a request caller cannot supply authoritative reference records or scope-coverage results. Before accepting an opportunity, the backend recomputes the analysis bundle reference from its contents and validates bundle references, scenarios, scopes, and metric relationships against that index. An unverified source may support a clearly partial hypothesis, but it cannot be promoted to validated evidence by the model or caller. The exact bundle reference must resolve as a validated Artifact with matching workspace, StudyArea, and scenario; local construction alone does not register it. OBSERVATION bindings also compare indexed analysis status and ordered input lineage with the bundle. Suggestion preflight rejects an invalid bundle before provider dispatch.

Secrets include model-provider API keys, local credentials, MCP transport credentials if used, and any deployment tokens. They must be supplied through the local environment or a secret manager, excluded from SQLite, immutable artifacts, browser storage, prompts, model-run payloads, and logs. Logs must redact authorization headers, keys, cookies, and sensitive request material. A model provider is not given arbitrary filesystem access.

The target is a local single-user course research prototype. Deployment assumptions must be recorded with each run: OS, CPU architecture (including ARM/Intel), Python/Node versions, QGIS installation/profile, external tool paths, adapter versions, and configured data/artifact directories. Milestone 1 records the current ARM host plus the Intel QGIS-under-Rosetta fallback and the separate ARM64 Radiance runtime. A clean-machine demonstration remains a pre-release deployment gate. If QGIS or a climate runtime cannot be installed or executed on the target architecture, the system reports the feasibility gate as unresolved or failed; it does not claim portability by inference.

## 11. Non-negotiable release boundaries

The architecture cannot release the MVP when any of these are unresolved:

- QGIS MCP facade restrictions or serialized external-process recovery are absent;
- the backend cannot distinguish `OUTCOME_UNKNOWN` from a confirmed failure or success;
- climate screening and Honeybee-Radiance verification are conflated;
- accessibility reruns do not preserve 400/800/1200 settings and prior results;
- computed evidence can be rewritten by a human override;
- a claim can cite missing, wrong-scope, wrong-unit, or wrong-scenario evidence;
- model-provider selection leaks into domain contracts;
- required lineage, hashes, versions, or replay records are missing;
- a mandatory integration is asserted without a passed smoke test.

All release-blocking tests are binary and must pass. An aggregate percentage cannot waive a failed critical gate.
