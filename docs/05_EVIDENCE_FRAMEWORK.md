# Evidence Framework

> **2026-09-22 現行規劃修訂：** 本文件採納 [工作流程與學期排程修訂契約](08_WORKFLOW_REALIGNMENT_2026-09-22.md)。其中第 5 節明列的產品範圍與排程條款優先於下方保留的舊版敘述；未列為取代的安全、證據與人類決策契約繼續有效。學期 W4 合併平台接入與基地分析，W5 開始生成／編輯，W8 驗收核心、W9 收尾。這是規劃修訂，不是實作或政策批准。

新增方法證據：Syntax 的 segment/角度成本/metric radius/正規化與邊界敏感性；逐層 footprint 的 GFA/FAR 與設計分母；編輯 command 的前後 geometry/graph hash；日照位置/時區/時段；出圖鏡頭/色階/結果版本。前端拖曳預覽不是 EvidenceResult。保留建築缺樓層仍未知；使用者設計上限不是法規觀測。archival_integrity 與 current_authority_state 分開，合法新增 ledger 不讓歷史證據失效。

Status: authoritative project contract for the documentation handoff.

This document defines how the project turns research, source data, deterministic computation, interpretation, and human decisions into contestable design evidence. The M2-A01 implementation adds a bounded StudyArea confirmation contract while preserving this evidence vocabulary; later production stages remain subject to their own runtime gates.

The governing rule is:

> LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.

The research report at [the supporting research report](../deep-research-report.md) informs this framework, but it is not itself an authoritative software specification. The product requirements in [01_PRODUCT_REQUIREMENTS.md](01_PRODUCT_REQUIREMENTS.md) consume these definitions.

The active MVP demonstration is the human-confirmed Rotterdam M4H `StudyArea`
v5. Historical Delft proposal packages and rejected or proposed Rotterdam
boundary experiments remain preserved evidence history. They do not set
`Project.site_id`, approve a formal `Site`, or replace the future
`DesignBoundary` and `HumanDecision` gates.

## Authority and evidence classes

Every material statement must be classified before it is used. Classification prevents a research suggestion, a project setting, a computed value, and a design opinion from being silently treated as the same kind of fact.

| Class | Meaning | Permitted authority | Required treatment |
| --- | --- | --- | --- |
| RESEARCH_FINDING | A claim, method, limitation, or relationship reported by a publication or other identified research source. | The cited source, within its stated scope. | Preserve a portable citation and relevant passage or page note. Do not turn it into a project constraint without an explicit project decision. |
| DATASET_OBSERVATION | A value or condition observed in an identified external dataset or service, such as an official or openly maintained geospatial source. | The source publisher and the snapshot actually used. | Freeze the input for a benchmark, retain provenance, license/attribution, query, retrieval time, and hash. Source authority does not remove data-coverage limitations. |
| PROJECT_DECISION | A deliberate setting, constraint, scope choice, weighting choice, or human instruction for this project. | An identified human or approved project governance event. | Version it, record its rationale and alternatives, and expose it as challengeable when it affects an analysis. |
| COMPUTED_RESULT | A result produced by a registered deterministic method and tool from identified inputs and parameters. | The reproducible run plus validator checks. | Record tool/version, input and output artifacts, units, CRS where relevant, exit status, and validation status. |
| INTERPRETATION | An observation, comparison, inference, or recommendation derived from linked evidence. | The linked evidence and the stated reasoning scope. | Link every material claim to evidence and assumptions. Normative preference requires a human decision rule. |
| ILLUSTRATIVE_EXAMPLE | A placeholder used to explain a contract or interaction. | No project authority. | Label it visibly. It must never become an executable constraint or validated result by copying. |

Missing data is not a measured zero. Modelled access is not verified legal or public access. A research relationship is not a project-specific causal result. These distinctions remain visible in evidence cards and exports.

## Complete evidence chain

The minimum traceable chain is:

```
SOURCE
  then
CLAIM
  then
PARAMETER
  then
METRIC
  then
METHOD
  then
TOOL
  then
RESULT
  then
INTERPRETATION
  then
DECISION
```

The links are typed references, rather than an assumption that one record contains every object. A card may start at a project decision or a dataset observation, but it must still expose the relevant upstream and downstream references.

* SOURCE identifies research, an external dataset, or a project decision record.
* CLAIM states what is being asserted and labels its type: observation, comparison, inference, or normative_judgement.
* PARAMETER names a value, unit, context, scale, source type, alternatives, and status.
* METRIC defines the formula, unit, inputs, interpretation limits, and implementation version.
* METHOD describes the reproducible procedure, including transformations and preconditions.
* TOOL identifies the registered deterministic tool or model adapter used to execute the method.
* RESULT references the output artifact and its verified values, units, and status.
* INTERPRETATION states what the result supports, what it does not support, and under which assumptions.
* DECISION records the human action or project choice, its author, reason, time, and relation to the evidence.

An LLM may propose a plan or interpretation, but an LLM response alone cannot create a COMPUTED_RESULT, validate a source, or establish a design decision.

Every evidence item also declares one semantic class: `DATASET_OBSERVATION`,
`COMPUTED_RESULT`, `AI_INTERPRETATION`, `HYPOTHESIS`, or `DATA_GAP`.
`AI_INTERPRETATION` and `HYPOTHESIS` entries may propose a risk, question, or
next analysis, but cannot author measurements or formal cadastral, ownership,
zoning-compliance, or legal-buildability claims. A `DATA_GAP` is not zero and
cannot carry computed values.

## Typed conceptual Evidence Card

The following is the minimum conceptual shape. The implementation may use another serialization, but field meanings and traceability must be preserved.

```yaml
evidence_id: <stable evidence identifier>
project_id: <project identifier>
scenario_id: <scenario identifier or null for a project/site-level card>
semantic_type: DATASET_OBSERVATION | COMPUTED_RESULT | AI_INTERPRETATION | HYPOTHESIS | DATA_GAP
input_versions:
  - <dataset, project-state, scenario, or recipe version>
claim:
  id: <claim identifier>
  type: observation | comparison | inference | normative_judgement
  statement: <bounded claim text>
source_refs:
  - <portable research citation or project-decision identifier>
dataset_refs:
  - <frozen dataset snapshot or derived input identifier>
metric:
  id: <metric definition identifier>
  name: <metric name>
parameters:
  - <parameter registry identifier and effective version>
method:
  id: <method identifier>
  description: <reproducible method summary>
tool: <registered tool identifier>
tool_version: <pinned tool version or explicit unavailable status>
result:
  artifact_refs:
    - <result artifact identifier>
  values: <computed or observed values, or an explicit unavailable status>
  status: observed | computed | unavailable
units: <unit for every reported value, or explicitly unitless>
assumptions:
  - <assumption identifier and effective version>
limitations:
  - <known limitation or unresolved uncertainty>
confidence:
  level: unknown | low | medium | high
  basis: <evidence completeness and validation basis>
  uncertainty: <known uncertainty or none recorded>
  assessed_by: <validator, researcher, or human identifier>
validation_status: unverified | validated | invalid | superseded | contested
human_status: not_reviewed | inspected | challenged | accepted | rejected | modified | overridden
created_at: <timestamp with timezone>
```

The placeholders above are illustrative contract values. They are not dataset values, validated metric values, or project settings.

An Evidence Card is complete only when each non-null reference resolves to the correct project, scenario version, units, and result. A syntactically valid card with a wrong scenario, wrong dataset, wrong comparison, or wrong unit fails relationship validation.

### Card requirements by evidence class

* A RESEARCH_FINDING card includes a portable citation reference and a relevant section/page/passage note when available. It may remain unverified when citation metadata are incomplete.
* A DATASET_OBSERVATION card includes a snapshot identifier, source URL or service identity, request/query, retrieval timestamp, license/attribution, raw artifact reference, and hash.
* A PROJECT_DECISION card includes the decision author, rationale, effective version, alternatives considered when known, and the contestability action that can revise it.
* A COMPUTED_RESULT card includes all input and recipe versions, deterministic tool and version, parameters, artifact hashes, exit status, units, CRS and coordinate transformations where applicable, and validator results.
* An INTERPRETATION card includes evidence references, assumption references, scope, limitations, uncertainty, and any explicit decision rule. A normative_judgement is not valid as a system conclusion without a human decision.

For climate evidence, also record weather source and file/version, time convention, true north, materials, context geometry, sensor definition, tool version, simulation parameters, geometry hash, sensor-grid hash, and recipe hash. Ladybug screening and Honeybee-Radiance verification are separate methods; their absolute outputs must not be treated as numerically interchangeable.

## Parameter Registry

The Parameter Registry is the versioned source of effective analysis conditions. A parameter is never an unexplained literal embedded in a prompt or tool call.

```yaml
parameter_id: <stable parameter identifier>
name: <human-readable name>
value: <typed value or explicit unavailable status>
unit: <unit, or explicitly unitless>
context: <project, site, scenario, metric, method, or experiment context>
scale: <spatial, temporal, scenario, or population scale>
source_type: research_finding | dataset_observation | project_decision | computed_result | interpretation | illustrative_example
evidence_refs:
  - <supporting evidence identifiers>
alternatives:
  - id: <alternative identifier>
    value: <alternative typed value>
    status: considered | selected | rejected | superseded
confidence:
  level: unknown | low | medium | high
  basis: <why this level is assigned>
sensitivity_required: true | false
status: proposed | effective | challenged | superseded | invalid
```

Changing a parameter creates a new effective version and a new analysis event. It does not mutate a previous card or silently alter a result. sensitivity_required true means the analysis must either run the registered sensitivity variants or explicitly record why it could not; it does not imply that a result is robust.

The Registry must retain the difference between an illustrative example, a project setting deliberately frozen for the prototype, a value observed in an input dataset, and a value computed by a deterministic method.

### Approved project settings for the MVP

These are approved scope decisions, not universal standards. Their effective versions must be frozen in project state before an experimental run.

| Setting | Approved MVP decision |
| --- | --- |
| Exploration context | One human-confirmed QGIS `StudyArea`; its polygon artifact, projected CRS, units, geometry hash, actor/time, and confirmation event are versioned. |
| Formal boundary | `DesignBoundary` is separate from StudyArea. `CADASTRAL`, `OWNERSHIP`, `ZONING_COMPLIANCE`, and `LEGAL_BUILDABILITY` require `APPROVED` status plus explicit `HumanDecision` data. |
| Site inputs | Frozen PDOK and OpenStreetMap snapshots. Final benchmark runs do not use live API responses as their authoritative input. |
| GIS integration | QGIS MCP is mandatory, behind a controlled and allow-listed facade. |
| Accessibility default | 800 m network-distance threshold for the selected definition. |
| Accessibility challenge variants | 400 m, 800 m, and 1200 m reruns. These are project sensitivity settings, not universal walking-distance standards. |
| Accessibility definition | Fraction of a fixed, approved set of public-access reference points that can reach at least one selected grocery destination within network distance less than or equal to the selected threshold. |
| Morphology | COMPAS perimeter-block and linear-block families, with one accepted candidate from each family in the MVP demonstration. |
| Climate objective | Reduce summer cumulative incident radiation on a defined public-space sensor area, while also reporting spatial distribution. |
| Climate methods | Ladybug/ladybug-radiance screening and Honeybee-Radiance verification, compared within each method and checked for directional agreement. |
| Climate experiment | One selected scenario and one selected building; translation along one declared axis; one baseline and two feasible offsets. |
| Climate locks | Footprint, floors, height, FAR where applicable, weather, material assumptions, context, sensor definition, and simulation settings are locked unless a new experiment explicitly changes one. |
| Sensor condition | The sensor area remains outside every candidate footprint. |
| Objective weighting | No hidden aggregate objective weights. A weighting rule must be an explicit project decision. |

The report's examples such as a FAR target, a height limit, an open-space ratio, or a sample metric value are ILLUSTRATIVE_EXAMPLE unless an authoritative source, project evidence, or explicit human decision promotes them to an effective project parameter. For example, a text example containing FAR 2.2, height 24 m, or green 35% is not executable merely because it appears in supporting research.

## Evidence status and validation rules

validation_status describes the lifecycle of the evidence record. The states are conceptual and must be preserved across exports.

| Status | Meaning | What it may support |
| --- | --- | --- |
| unverified | Required provenance, relationship, deterministic checks, or human review is incomplete. | Discovery and a clearly labelled provisional view. It cannot support a final validated claim. |
| validated | Required references resolve; inputs, units/CRS, method, tool run, artifact, and applicable invariants pass the validator. | A bounded project claim within the recorded scope and assumptions. |
| invalid | A check failed, an input/result is unavailable, or the record is structurally or semantically inconsistent. | Diagnosis only. It cannot be used as supporting evidence. |
| superseded | A later version or rerun is the effective record. | Historical audit and replay; it remains retained and visible. |
| contested | A human challenged an assumption, claim, method, or decision, and the challenge has not been resolved by an accepted rerun or decision. | A contest record and historical context; it is not silently treated as settled evidence. |

Validation is fail-closed for missing evidence, unresolved references, CRS or unit mismatch, invalid geometry, missing artifacts, NaN/Inf values, failed invariants, mismatched scenario versions, and mismatched climate recipe/weather/sensor-grid hashes. A tool exit status of success does not by itself validate the semantic result.

Every numerical or comparative claim shown to a user must resolve to a validated result or explicitly show its unverified, invalid, or contested state. A claim with no evidence reference is rejected. A claim saying a scenario is best is rejected unless a human supplies and accepts an explicit decision rule; otherwise the system may report bounded observations and trade-offs.

## Provenance, hashing, snapshots, and versioning

Provenance is part of the evidence, not optional metadata.

### Provenance requirements

Each source, dataset snapshot, parameter version, scenario version, metric definition, method, tool run, model run, result artifact, interpretation, contest event, and human decision receives a stable identifier. Records must expose their upstream inputs and downstream uses. A StudyArea geometry reference must resolve to a persisted typed Artifact with matching project, URI, exact bytes/hash, size, MIME, CRS, and producer; formal approval references a typed HumanDecision whose project, target ID/version/hash, action, actor, time, reason, and ledger event are checked together.

At minimum, a run records:

* project version and scenario version;
* input snapshot and parameter versions;
* metric, method, tool, tool version, and execution environment where material;
* request/query and retrieval time for external data;
* output artifact references and content hashes;
* exit status and validator results;
* actor and timestamp;
* related evidence and ledger event identifiers.

The backend project state is authoritative. LLM conversation text, the live QGIS canvas, browser state, and generated prose are not authoritative project state.

### Artifact hashes

For every immutable file or byte representation used in a benchmark, store its cryptographic digest, preferably SHA-256, as sha256:<64 lowercase hexadecimal characters>. Hash the exact bytes used by the run, and record MIME type, size where available, creation time, and URI/path. A transformed artifact receives its own hash and links to the input artifact; a hash is never copied from a parent.

If an artifact cannot be hashed or the hash cannot be reconciled, its evidence remains unverified. Hashes in documentation examples are placeholders and must not be persisted as if they were real digests.

### Dataset snapshots

An external dataset snapshot retains the raw response or source bytes, request URL/query or source identity, retrieval timestamp with timezone, publisher, license/attribution, snapshot version, and SHA-256 hash. A live response may be inspected for development, but the benchmark input is the frozen snapshot. A changed response creates a new snapshot and invalidates comparability until the new version is explicitly selected.

### Scenario and result versions

The StudyArea workflow is also append-only. A confirmation registers or
resolves the saved QGIS Artifact, records its exact hash/size/URI/MIME/CRS/
producer, and records the projected CRS's canonical units, human actor/time,
and `ConfirmStudyArea`/`ActivateStudyArea` events. A later draw creates a new
project-scoped monotonic version with a `supersedes` relationship; dependent
results are marked stale by their declared StudyArea ID or geometry hash and
are never silently rerun. Runtime authorization checks these persisted
relationships before exploration.
StudyArea confirmation authorizes exploration only. Formal claims require an
approved, HumanDecision-backed DesignBoundary.

The unit contract stores canonical `m` or `ft` values after comparing declared
aliases with the projected CRS axis units; angular or unsupported units remain
invalid.

Every scenario version records its parent scenario, site model version, generator/operator, seed where applicable, parameters and constraints, mutation or generation reason, geometry artifact hash, and status. A rejected candidate is retained with its rejection reason and evidence. Reruns create new result and evidence versions; they do not overwrite the original.

Climate comparisons are comparable only when the relevant geometry, weather, recipe, material, context, sensor-grid, and simulation-setting hashes match, except for the declared intervention variable. Screening and verification results remain separate method/version families.

### Model-run metadata

When an LLM is used, record provider, model identifier, adapter version, prompt/template version and hash, structured request, tool decisions, final structured output, response hash, and concise rationale summary where useful. Do not store private chain-of-thought and do not treat it as evidence. Provider or model changes create a new model-run version and may affect reproducibility of prose; deterministic results still require their own tool provenance.

## Confidence

Confidence describes the quality, completeness, validation coverage, and uncertainty of an evidence record within its stated scope. It is not an arbitrary LLM probability and it is not a substitute for validation.

The recommended levels are unknown, low, medium, and high, each accompanied by a basis, assessor, and uncertainty statement. A high confidence level can mean that provenance and deterministic checks are complete for a narrow computation; it does not mean the result is universally true or that a normative decision is correct. A numeric probability may be used only when a documented, calibrated method supports it and the calibration evidence is itself recorded.

## Human review and decisions

Human review is a first-class record. human_status must identify the actor, timestamp, action, reason, affected evidence/parameter/scenario, and resulting event or decision. The minimum conceptual decision states are:

* not_reviewed: no human review is recorded;
* inspected: the user opened the supporting chain;
* challenged: the user disputed an assumption, claim, method, or result;
* accepted: the user accepted a proposal or result for the stated use;
* rejected: the user rejected a proposal or result;
* modified: the user changed a parameter or design condition;
* overridden: a human decision replaces an agent recommendation for the stated context.

An override appends a new decision. It never rewrites a computed result, turns invalid evidence into valid evidence, or deletes the prior recommendation.

## Contest events and state transitions

Contestability changes computational state. An explanation without a new state, rerun, comparison, fork, or decision is not sufficient.

Every contest event is append-only and records at least:

```yaml
event_id: <stable event identifier>
timestamp: <timestamp with timezone>
actor: <human, agent role, validator, or tool identity>
action: Inspect | Challenge | Modify | Rerun | Compare | Fork | Reject | Override
target_id: <evidence, parameter, scenario, claim, or decision identifier>
prior_status: <status before event>
changed_refs: <parameter, snapshot, scenario, or result references>
reason: <human reason or bounded system explanation>
resulting_refs: <new event, evidence, result, branch, or decision identifiers>
supersedes: <prior event/result/decision if applicable>
```

| Action | Required effect |
| --- | --- |
| Inspect | Expose source, input versions, parameters, metric, method, tool, result, limitations, hashes, and current human status. An audit event may be recorded; no claim status is silently improved. |
| Challenge | Mark the affected assumption/claim/decision contested, record the reason, and identify the permitted change or follow-up analysis. |
| Modify | Create new parameter, constraint, or design versions and preserve the prior versions. |
| Rerun | Execute a new versioned method/tool activity using the changed conditions; create new result and evidence records. |
| Compare | Produce a bounded comparison with matched inputs and explicit scope; show whether ordering or interpretation changes. |
| Fork | Create a new scenario or project branch with parent lineage and copied references; later edits remain branch-specific. |
| Reject | Record a human rejection and reason while retaining the proposal, inputs, and evidence. |
| Override | Append a human decision that governs the stated context; retain the agent recommendation and all supporting evidence. |

The first required demonstration is the accessibility challenge:

```
800 m project setting
  then Challenge
400 m / 800 m / 1200 m versioned reruns
  then Compare
show whether the conclusion remains stable
  then Human decision
accept, reject, modify, or override with reason
```

The accessibility rerun must preserve the origin set, destination taxonomy, destination snapshot, network snapshot, threshold, scenario-specific public-passage overlays, unreachable origins, and denominator rules. Building-massing changes alone must not imply a pedestrian graph change. The negative control is that changing building height only leaves accessibility unchanged.

## Research citation requirements

Mandatory research claims must resolve to portable citations. A non-portable citation marker copied from a search or model response is not sufficient for an authoritative project claim.

For each research source, capture the following when available:

* authors or responsible organization;
* title;
* publication, venue, or repository;
* year;
* DOI;
* stable URL;
* exact relevant section, page, figure, table, or passage note;
* citation status and the evidence claim(s) that use it.

Do not invent missing citation fields. If a source is mentioned in the supporting report but portable metadata cannot be confirmed from the supplied materials, mark the record citation_status: unresolved, list the missing fields, and keep dependent evidence unverified until the citation is resolved or the claim is narrowed. The local report link may preserve audit context, but it does not replace portable citation metadata for a final public or research artifact.

Citation records should distinguish a source's direct finding from the project's interpretation and from a project decision inspired by that finding. Citations must influence the recorded method, parameter, limitation, or decision where justified; a bibliography entry alone does not establish a requirement.

### Resolved portable source register for the MVP contract

The following sources resolve the research and software-capability claims that directly shape the P0 contract. A resolved citation establishes source identity and scope; it does not prove that the corresponding local runtime is installed, compatible, or operational. Repository-backed tools must still be pinned to a tested release or commit during Milestone 1.

| Source ID | Portable citation | Relevant section or passage | Contract use | Citation status |
| --- | --- | --- | --- | --- |
| SRC-CONTESTABLE-AI | Kars Alfrink, Ianus Keller, Gerd Kortuem, and Neelke Doorn. “Contestable AI by Design: Towards a Framework.” *Minds and Machines* 33, 613–639 (2023). DOI: [10.1007/s11023-022-09611-z](https://doi.org/10.1007/s11023-022-09611-z). | Abstract; Section 2, “Contestability in Automated Decision-Making”; Sections 6.1.2–6.1.4 on interactive control, intervention, scrutiny, and human authority. | Supports lifecycle contestability, traceable decisions, direct intervention, and human review. The eight MVP contest actions and their state transitions remain PROJECT_DECISION records. | resolved |
| SRC-W3C-PROV-DM | W3C Provenance Working Group. “PROV-DM: The PROV Data Model.” W3C Recommendation (2013). Stable URL: [w3.org/TR/prov-dm](https://www.w3.org/TR/prov-dm/). | Introduction; Sections 2.1.1–2.1.3 on entities, activities, derivation, agents, and responsibility; Section 2.2.2 on provenance of provenance; normative Section 5. | Supports the typed provenance graph and responsibility relationships. The project’s Evidence Card fields and validation states are a domain-specific PROJECT_DECISION, not a claim of formal PROV-DM conformance. | resolved |
| SRC-QGIS-MCP | Nicolas Karasiak and contributors. “qgis-mcp.” GitHub repository. Stable URL: [github.com/nkarasiak/qgis-mcp](https://github.com/nkarasiak/qgis-mcp). | README sections “Architecture,” “Tools,” “Configuration,” and “Authentication”; repository security warning that the socket connection is not a sandbox. | Supports the feasibility hypothesis for MCP-mediated QGIS inspection and command execution. It also supports the requirement for a controlled facade, allow-list, authentication, audit logs, timeouts, and independent validation. | resolved; local runtime `0.14.0` verified |
| SRC-COMPAS | COMPAS Association and contributors. “The COMPAS framework.” GitHub repository. Stable URL: [github.com/compas-dev/compas](https://github.com/compas-dev/compas). | README overview, installation, framework packages, host integrations, tests, and license. | Supports the feasibility hypothesis for deterministic Python geometry operations and host-independent geometry data. It does not establish that the two project morphology families are already implemented. | resolved; runtime version pending |
| SRC-LADYBUG-RADIATION | Ladybug Tools contributors. “ladybug_radiance.study.radiation.” API documentation. Stable URL: [ladybug.tools/ladybug-radiance/docs/ladybug_radiance.study.radiation.html](https://www.ladybug.tools/ladybug-radiance/docs/ladybug_radiance.study.radiation.html). | `RadiationStudy` module and class documentation, including input mesh/context requirements and the stated exclusion of reflections. | Supports the bounded screening-method capability and its limitation. It does not justify numerical interchangeability with Honeybee-Radiance. | resolved; local package `0.2.12` and Radiance `6.0.2` verified |
| SRC-HONEYBEE-RADIANCE | Ladybug Tools contributors. “honeybee-radiance.” GitHub repository. Stable URL: [github.com/ladybug-tools/honeybee-radiance](https://github.com/ladybug-tools/honeybee-radiance). | README overview, installation, command-line interface, tests, and license. | Supports the feasibility hypothesis for the higher-fidelity Radiance verification tier. Operational readiness, recipes, weather, materials, context, and result validity remain runtime gates. | resolved; local package `1.66.288` and Radiance `6.0.2` verified |

The 400 m, 800 m, and 1200 m accessibility thresholds; the exact accessibility denominator; the morphology family constraints; the active Rotterdam M4H StudyArea; and the summer public-space radiation objective are project settings. They are not represented as universal findings from these sources. Claims in the supporting research report that are outside the P0 contract remain non-authoritative until separately registered and resolved.

## Quality gates and unresolved states

An evidence bundle is ready for an authoritative display only when:

1. every material claim has a typed claim, resolved evidence references, scope, assumptions, and limitations;
2. every input snapshot, parameter, scenario, method, and result has a version or explicit unavailable status;
3. units, CRS, transformations, geometry, and relationship checks pass where applicable;
4. output artifacts and hashes reconcile to the run;
5. confidence has a stated basis and is not an unsupported LLM probability;
6. the human status and any contest events are visible;
7. portable research citations are resolved for claims that depend on research.

If any gate fails, keep the record unverified, invalid, or contested as appropriate and show the reason. Never promote a partial chain to validated evidence by inference.

## Related authoritative documents

These documents are authored in the same handoff and should link back to this contract rather than redefine it:

* [Product requirements](01_PRODUCT_REQUIREMENTS.md)
* [Product vision](00_PRODUCT_VISION.md)
* [System architecture](02_SYSTEM_ARCHITECTURE.md)
* [Agent architecture](03_AGENT_ARCHITECTURE.md)
* [Evaluation framework](06_EVALUATION_FRAMEWORK.md)
* [Implementation plan](07_IMPLEMENTATION_PLAN.md)
* [Repository governance](../AGENTS.md)
