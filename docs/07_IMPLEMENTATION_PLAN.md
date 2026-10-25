# Eight-Week Contestable Urban Design Prototype Implementation Plan

> **2026-09-22 現行規劃修訂：** 本文件採納 [工作流程與學期排程修訂契約](08_WORKFLOW_REALIGNMENT_2026-09-22.md)。其中第 5 節明列的產品範圍與排程條款優先於下方保留的舊版敘述；未列為取代的安全、證據與人類決策契約繼續有效。學期 W4 合併平台接入與基地分析，W5 開始生成／編輯，W8 驗收核心、W9 收尾。這是規劃修訂，不是實作或政策批准。

## 現行學期排程入口

| 學期週 | 本週成果 | Checkpoint |
|---|---|---|
| W1–3 | 既有基礎與實際未完成項的對照，不重新開三週工期 | 基線驗證 |
| W4（現在） | 平台同步＋保留／分區＋基地分析＋六張 Syntax 圖＋AI | CP4-0–CP4-8 |
| W5 | 三至五個空間策略＋人類選擇＋基本量體／道路編輯 | CP-W5 |
| W6 | 分面與完整吸附＋日照／陰影＋雙層輻射 | CP-W6 |
| W7 | 四階段串接、contestability、E2 獨立驗收 | CP-W7 |
| W8 | 核心凍結、出圖、重播與報告版 | CP-W8 |
| W9 | 修復、報告、容量允許的附加功能 | CP-W9 |

現行執行入口是 [Week 4 中文詳細計畫](superpowers/plans/2026-09-22-week4-platform-site-analysis-zh.md) 與 [學期整體藍圖](superpowers/plans/2026-09-22-semester-project-blueprint-zh.md)。下方的工程 Week 1–8 表、舊 cut order 與舊 MVP 規模保留作歷史依據；衝突時只按修訂契約第 5 節取代，不把新的學期 W4 叫作舊工程 Week 4。舊測試／證據與未被修訂的要求保留。

本輪只完成文件修訂；下方 execution status 是歷史記錄，不能作為此時服務、SQLite 或新功能已通過的聲明。

**Goal:** Deliver a local, single-user, model-provider-independent research prototype that runs Draw → Confirm StudyArea → Understand → Explore → Test → Refine and leaves every computed claim, challenge, rerun, and human decision inspectable and replayable.

**Architecture:** A controlled application state machine coordinates typed domain models, a backend-owned SQLite project state and append-only Design Ledger, immutable dataset/result artifacts, bounded role prompts, and allow-listed deterministic tool adapters. LLMs produce structured plans and interpretations; QGIS MCP, COMPAS, Ladybug, and Honeybee-Radiance calculate; validators verify relationships and invariants; the designer decides.

**Tech Stack:** Python domain models and API, SQLite for project state and ledger, immutable files for snapshots and result artifacts, QGIS MCP through a restricted facade, PDOK and OSM snapshot adapters, COMPAS for perimeter-block and linear-block geometry, Ladybug/ladybug-radiance for screening, Honeybee-Radiance for verification, and a provider-neutral LLM adapter.

---

> **Execution status:** Milestone 1 implementation is authorized and has produced the typed contracts, SQLite state/ledger store, deterministic adapter, bounded QGIS facade, fixtures, tests, and feasibility probe. The latest M1-R02 run passes all required deterministic, security, QGIS, Ladybug, and Honeybee-Radiance gates after certification was repaired to require actual collected pytest results and revalidated hashed evidence. Historical M2-R01 produced the repaired, independent-boundary Delft v2 package, and M2-R02 produced its map-only v3 revision with preserved v2/v1 byte lineage, a projected clipped viewport, complete SVG layout, and independently rendered PNG. M2-A01-R01 and M2-A02-R01 delivered the bounded bridge contract. M2-A02-R02 repaired the dedicated project with a source-verified EPSG:28992 M4H drawing anchor, finite initial extent, display-only context, and backend locality checks. M2-A02-R03 completed the visible dedicated QGIS lifecycle: after the unrelated instance was saved and closed, the visible `rotterdam-m4h-pilot-project — QGIS` window drew and confirmed the intended polygon through the launch-scoped bridge. StudyArea v5 is active with matching hashes and v4 is preserved and superseded. M2-A03-R05 attempted the allowlisted live source run and failed closed on EPW chronology before publishing source snapshots; its r03 package is preserved as BLOCKED, and no analysis policy was activated. The active StudyArea remains exploration-only and no formal Site or DesignBoundary is approved.

## M2-A02-R01 decision record — active demonstration identity

**Decision:** The sole active MVP demonstration is the human-confirmed
Rotterdam M4H `StudyArea` v5 (`study-area-rotterdam-m4h-pilot-project-v5`).

**Rationale and provenance:** This record documents the user's prior explicit
selection of Rotterdam M4H for the demonstration. The decision aligns the
forward-looking MVP documents with the persisted project pointer and does not
rewrite historical evidence. Delft proposal packages remain historical,
superseded research/proposal evidence; rejected or proposed Rotterdam boundary
experiments remain historical boundary evidence.

**Boundary:** The decision preserves `Project.site_id = null` and does not
approve a cadastral `Site` or `DesignBoundary`. Formal claims still require a
future approved `DesignBoundary` backed by an explicit `HumanDecision`.

**Status:** M2-A02 is complete. No PDOK, OSM, origin, destination, network, or
weather snapshot was acquired or frozen by M2-A02. The active v5 geometry is
`EPSG:28992` metres with geometry hash
`sha256:3dedb804fa4f07f4c9570bcc64e68c8d576c03340455ab35fd4963bca52aa4f5`
and artifact hash
`sha256:9a59159505505dbe658ec6667ecfeb9024b868faf6377e7cd91889c763170d32`.
M2-A03-R05 attempted its source-acquisition task and remains BLOCKED because the live EPW candidate failed the hourly chronology validator before any source snapshot was published.

## M2-A02-R02 repair record — georeferenced QGIS capture

The active v4 bytes and the blocked M2-A03 packages remain append-only and
unchanged. The repair adds `config/rotterdam-m4h-anchor.json`, whose extent is
derived from the retained source-backed M4H viewport and whose explicit status
is `DRAWING_LOCATION_GUARD_ONLY`. It does not create or adopt a Site or
DesignBoundary. The dedicated QGIS project uses EPSG:28992, a finite extent
around that anchor, and a read-only `NON_AUTHORITATIVE_DRAWING_CONTEXT` layer
whose retained bytes and source hashes are checked at launch. New draft layers
are created beside the project file; the prior nested GeoPackage is preserved.

Shared StudyArea validation and the bridge independently reject geometry outside
the CRS area of use or outside the configured project anchor. The companion
plugin reports anchor and context readiness separately and rejects unresolved
or out-of-anchor drawings before posting. The automated repair and regression
suites pass. The human draw and confirmation have now created exactly one v5
version, superseded v4, and marked the blocked M2-A03 packages stale without
rewriting their bytes. No source acquisition or automatic rerun was performed.

## M2-A02-R03 repair record — visible dedicated QGIS lifecycle

Inspection found that direct QGIS startup could load the isolated Rotterdam
project, profile, context, and MCP listener in a second background process while
macOS kept an unrelated `Untitled Project — QGIS` window visible. Because the
window identity could not be established, the launcher now performs a
single-instance preflight before profile creation, token generation, bridge
startup, or QGIS startup. If any QGIS process is present it fails with a
save/close/retry instruction and leaves that process untouched. This prevents
duplicate hidden/orphan instances and preserves Hermes 8787. The repaired QGIS
project now has an explicit `rotterdam-m4h-pilot-project` title and project
name for the later visible-window gate. The later supervised run displayed the
correct project title and completed the intended v5 human draw; the dedicated
process remains tied to the launch-scoped bridge and QGIS MCP socket.

## M2-A03 execution status — r03 live acquisition blocked after v5

M2-A03 created `artifacts/milestone2-analysis-inputs-rotterdam-m4h/` with a
request record, a deterministic 1,200 m envelope derivation, typed validation
helpers, and a `SnapshotObservation` ledger event. The historical v4 geometry
was declared as EPSG:28992 but its observed bounds are `x=419..744,
y=-469..-213`, outside the projected EPSG:28992 area of use. Both historical
v4 packages remain `BLOCKED` and byte-preserved. After v5 activation,
append-only `MarkStale` events (ledger sequences 22 and 23) record that their
v4 inputs are stale. M2-A03-R05 then attempted the allowlisted live run, but
the Rotterdam EPW candidate failed the hourly chronology validator; its r03
package is preserved as `BLOCKED` with zero published source Artifacts or
DatasetSnapshots. Origin, destination, network, and weather policies remain
proposed and unselected.

### M2-A03-R05-R01 diagnostic repair

The retained raw candidate was absent, so R01 performed exactly one diagnostic
GET to the allowlisted Climate.OneBuilding Rotterdam TMYx URL and preserved the
response under
`artifacts/milestone2-analysis-inputs-rotterdam-m4h/diagnostics/epw-r05-20260919T123015Z/`.
The 424,688-byte ZIP is readable and contains one 35-column, 8,760-row EPW.
Its month/day/hour sequence is complete with no duplicate or missing records,
but every row uses `Minute=0`, which failed the then-current project
validator's `Minute=60` implementation contract. The earlier R05-R01 record
described this against the then-cited `1..60` reference; R08 later recorded the
provider-hosted generic `0..60` dictionary. Neither generic rule establishes
provider-specific semantics. The source is therefore still
`BLOCKED_SOURCE_INVALID_EPWTIMING`; the response is diagnostic evidence only
and was not published as a DatasetSnapshot.

The same inspection found that TMYx source years change at month boundaries.
R01 removed only the validator's over-strict requirement that all rows share
one year, while retaining the 35-column, complete chronology, `Minute=60`,
finite-field, and year validity gates. Failed acquisition receipts now record
whether a request was sent, whether a response arrived, and whether validation
failed; later sources remain explicitly `NOT_ATTEMPTED_BLOCKED`. No r03 rerun,
source publication, accessibility, morphology, or climate simulation occurred.

### M2-A03-R08 source-semantic review

The persistent R08 review package is recorded at
`artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-minute-semantics-20260919T154701Z/`.
Its read-only investigation of the provider-hosted EnergyPlus EPW Data
Dictionary found that the generic Minute field is documented as `0..60` and
that Minute is not used directly by the simulation; the provider's Rotterdam
index does not explain the Minute convention of the three retained TMYx files.
The project validator still requires `Minute=60` as an implementation
contract. The provider-specific time semantics therefore remain
`SEMANTICS_UNRESOLVED`; no derived EPW or DatasetSnapshot is approved.

## M2-A03 boundary decision — Week 2 spatial input track and weather gate

**Decision date:** 2026-09-21. **Decision type:** implementation-boundary
clarification; it does not approve a weather source, a transformation, or a
DatasetSnapshot.

Week 2 is split into two independently reported gates:

1. **Spatial input gate — required for Weeks 3–4.** This gate covers the active
   StudyArea v5, PDOK building/road/water observations, OSM pedestrian and
   grocery observations, origin and destination inventories, network metadata,
   CRS/units, licences, query/retrieval metadata, hashes, data gaps, and the
   human decisions that define the origin denominator, destination taxonomy,
   and pedestrian-network policy. It does not require a weather file.
2. **Weather method gate — required for Week 6.** This gate covers the EPW or
   alternative weather method, provider/file-specific time convention,
   selection, allowed transformation, licence, and climate experiment lock.
   It remains `SEMANTICS_UNRESOLVED` and `BLOCKED` until the source semantics
   or a human-approved alternative method is established.

The two gates share StudyArea identity, provenance, CRS/unit records, ledger
lineage, and explicit data-gap handling. They do not share completion: a
passing spatial gate does not approve weather, and resolving the weather gate
does not approve spatial policies.

Week 2 Spatial Gate PASS unlocks Week 3 accessibility and Week 4 morphology.
Weather Gate PASS is required before Week 6 climate experiments. Spatial PASS
with Weather BLOCKED is a valid intermediate state. Unresolved weather does
not block Week 3 or Week 4.

Historical behavior: `acquire_mandatory_sources` and `build_m2a03_package`
treated PDOK, OSM, and EPW as one atomic bundle. That combined path remains
only so the blocked r03 package and earlier receipts can be replayed. It is
not the Week 3 entry gate, and it does not make a weather file a prerequisite
for Week 3 accessibility or Week 4 morphology. The spatial execution path is
`acquire_spatial_sources`, `build_m2a03_spatial_package`, and
`freeze_m2a03_spatial_policies`. The retained r03 package remains immutable
and `BLOCKED`. No weather source is approved.

This boundary allows Week 3 accessibility and Week 4 morphology engineering
to proceed after the spatial gate and its human policy decisions pass. Week 6
remains blocked until the weather method gate passes. The project must report
these as separate `PASS` or `BLOCKED` results rather than inventing a new
global success status.

## Fixed MVP contract

The implementation must demonstrate one human-confirmed, human-drawn Rotterdam M4H StudyArea using analysis-specific frozen PDOK and OSM snapshots. Confirmation of the StudyArea is the exploration prerequisite; it does not approve a legal site or formal boundary. A separate approved DesignBoundary with explicit HumanDecision data is required before CADASTRAL, OWNERSHIP, ZONING_COMPLIANCE, or LEGAL_BUILDABILITY claims. The implementation must expose the mandatory QGIS MCP integration behind a controlled allowlist, generate two COMPAS morphology families (perimeter block and linear blocks), retain one accepted candidate from each family and every rejected candidate, calculate one primary accessibility metric, report FAR/coverage/height as descriptive or constraint measures, run the 800 m accessibility setting plus 400/800/1200 m challenge reruns, and complete one controlled climate experiment.

The climate experiment uses a baseline and two feasible translations of one selected building along one declared axis. Footprint, floors, height, FAR where applicable, weather, material assumptions, context, sensor definition, and simulation settings are locked. The sensor area is outside every candidate footprint. Ladybug/ladybug-radiance is the screening tier; Honeybee-Radiance is the verification tier. Their absolute outputs are not interchangeable. Report area-weighted summer cumulative incident radiation and spatial distribution, compare changes within each method, and record directional agreement or disagreement without claiming proven thermal-comfort improvement.

The accessibility definition is:

> The fraction of a fixed, approved set of public-access reference points that can reach at least one selected grocery destination within network distance less than or equal to the selected threshold.

The implementation records origins, destination taxonomy and snapshot, network snapshot and policy, threshold, scenario-specific passage overlays, unreachable origins, and denominator rules. The initial threshold is 800 m; 400 m and 1200 m are contestability settings, not universal walking standards. Building height changes alone must not change accessibility; an explicit passage overlay is required to change the pedestrian graph.

Research findings, project decisions, dataset observations, computed results, and illustrative examples remain separate labels. Missing observations remain missing, and modelled access remains distinct from verified legal/public access.

## Milestones

### Week 1 — Schemas, state, ledger, and real tool smoke tests

**Goal:** Establish the typed contracts and authoritative state needed for every later stage, and prove that the mandatory external tools can execute the smallest real operations.

**Scope:** Define `Project`, `Site`, `Artifact`, `DataSnapshot`, `ToolRun`, `MetricDefinition`, `Assumption`, `DesignScenario`, `EvidenceCard`, `Claim`, `ContestEvent`, `HumanDecision`, and `LedgerEvent` schemas. Implement append-only ledger transactions and deterministic replay. Define provider-neutral LLM adapter interfaces for structured plans, claims, and experiment proposals. Build the QGIS MCP facade with an allowlist, controlled inputs/outputs, serialized dispatch, and no raw `execute_code`, dynamic Python, unrestricted SQL, or batch bypass in the default profile. Run real smoke tests for a known geometry operation through QGIS MCP, Ladybug screening, and Honeybee-Radiance verification.

**Dependencies:** The approved handoff; a usable QGIS profile/plugin/server pair; callable Ladybug and Honeybee-Radiance environments; a tiny known geometry fixture; a writable controlled artifact directory; and a minimal SQLite database. Model provider credentials are optional for deterministic smoke tests because the adapter contract can be exercised with a fixture adapter.

**Deliverables:** Versioned domain schemas; initial SQLite schema and append-only ledger; replay command/library; provider-neutral LLM adapter interface; QGIS MCP facade policy; smoke-test records for QGIS, Ladybug, and Honeybee-Radiance; and a versioned known-answer geometry fixture.

**Tests:** Run `DET-002`, `DET-003`, `DET-008`, `DET-009`, `SEC-001`, `SEC-002`, `SEC-003`, `SEC-005`, `SEC-006`, `CLM-001`, and `CLM-002` from the evaluation framework. Expected results are known geometry validation, both radiation paths executing or producing explicit failure records, append-only events replaying to the same state, and no unsafe or unknown QGIS outcome treated as success. Week 1 performs only the foundation replay check; the complete `EVD-005` selected-scenario replay and export remains a Weeks 7–8 release gate.

**Definition of done:** A known geometry operation completes through the allowlisted QGIS MCP path or is explicitly `BLOCKED` with preserved connection evidence; both radiation routes have real smoke-test evidence; Honeybee includes incident-radiation values and a spatial artifact; schema round-trip and negative fixtures behave as specified; ledger replay reconstructs the initial state; and an external connection loss produces `OUTCOME_UNKNOWN` with no blind retry. Full `EVD-005` is not a Week 1 completion claim.

**Risks:** Tool environments may be unavailable or versions may drift; an apparently successful QGIS call may leave project state uncertain; schema shortcuts may permit unverified relationships.

**Fallback:** Keep the milestone incomplete and preserve the exact failure record. Use fixture adapters to continue schema work, but do not claim tool readiness. Reconcile QGIS artifacts and project state before any idempotent retry. A missing radiation tier is a mandatory gate failure, not a reason to remove that tier.

### Week 2 — StudyArea confirmation and analysis-specific data

**Goal:** Convert a saved, human-drawn QGIS polygon into a confirmed,
reproducible StudyArea package that can start all four exploratory stages.

**Scope:** Accept a saved QGIS Polygon/MultiPolygon artifact and require a
human confirmation before activation. Validate only non-empty, valid, finite,
positive-area geometry, projected horizontal CRS with matching canonical units,
and matching artifact/canonical geometry hashes. Register or resolve the typed
Artifact and require project, URI, hash, size, MIME, CRS, and producer equality.
Create a project-scoped monotonic append-only StudyArea version, record actor/time and `ConfirmStudyArea`/`ActivateStudyArea` events, set
`Project.active_study_area_id`, and preserve superseded versions. Freeze PDOK,
OSM, origins, selected grocery destination taxonomy, pedestrian network policy,
descriptive/constraint settings, horizontal CRS, vertical
reference where applicable, units, retrieval timestamps, licence/attribution,
request/query, and SHA-256 hashes separately for each analysis. Record data
gaps and distinguish missing from zero. Do not infer a formal site boundary;
DesignBoundary approval is a later HumanDecision gate for formal claims.

**Historical behavior:** the original Week 2 scope also listed a weather file
in the same freeze. That combined requirement is superseded by the 2026-09-21
boundary above. A weather file is not required for Week 3 or Week 4. Weather
Gate PASS remains required before Week 6.

**Dependencies:** Week 1 schemas, ledger, QGIS facade, and artifact store; access to the approved PDOK/OSM endpoints or provided snapshots; the human confirmation of the saved polygon.

**Deliverables:** Confirmed StudyArea record with a resolvable typed Artifact;
retained QGIS polygon artifact;
frozen PDOK/OSM spatial snapshot bundle; origin/destination/network manifests;
CRS/unit manifest; data-gap register; licence/attribution records;
and ledger events for confirmation, activation, and snapshot creation.
Historical behavior: a weather manifest was previously listed here as part of
the same Week 2 deliverable. It is now the separate Weather Gate and is not
required before Week 3 or Week 4.

**Tests:** Run `SA-001` through `SA-005`, `DET-001`, `DET-009`, `EVD-001`,
`EVD-002`, `EVD-003`, `EVD-006`, `SEC-004`, and `BEN-001` on the package.
Re-fetch or copy the artifact and verify hashes; submit missing-CRS,
missing-unit, invalid-geometry, and geographic-CRS fixtures; inspect that data
gaps remain explicit and no formal claim bypasses DesignBoundary approval.

**Definition of done:** Human StudyArea confirmation is recorded before
exploration; runtime replay verifies the active pointer and matching confirmation
and activation events; every required artifact/snapshot has a stable hash and
source metadata; CRS/units/vertical
reference are validated; origin and destination denominator rules are frozen;
documented data gaps are visible; formal claims fail closed without an
approved HumanDecision-backed DesignBoundary; and the same snapshot manifest
can be loaded twice without drift.

**Risks:** StudyArea confirmation may be delayed; PDOK and OSM coverage or tagging may be incomplete; layers may use incompatible timestamps or CRS; a live source may change between retrievals.

**Fallback:** Keep the StudyArea unconfirmed and continue only with
fixture/schema work. Use the last valid frozen snapshot only when its
provenance and licence are present. Do not fill missing observations with zero
or silently change the geometry; record a new StudyArea version and human
confirmation. Stop formal claims when DesignBoundary approval is absent.

**M2-A02 execution status:** The live QGIS StudyArea bridge, dedicated
`urban-design` profile, bounded FastAPI capture/status API, companion plugin,
and Ladybug readiness reporting are complete and verified. This subtask does
not mark the broader Week 2 data package complete. Historical behavior at the
M2-A02 close: PDOK/OSM, origin/destination, network, and weather snapshots were
still unacquired. That historical combined status does not make a weather
snapshot a prerequisite for Week 3 or Week 4.

### Week 3 — Accessibility, evidence, map, and threshold reruns

**Goal:** Deliver a reference-checked primary accessibility analysis and an inspectable visual evidence surface.

**Scope:** Build the pedestrian graph from the frozen network policy; implement the fixed accessibility definition with 800 m as the initial setting; retain unreachable origins in the fixed denominator; support explicit passage overlays; create Evidence Cards with formula, inputs, parameters, units, hashes, assumptions, limitations, and human status; render the basic map; render basic 3D massing from the site/scenario artifact; and implement versioned 400/800/1200 m reruns.

**Dependencies:** Week 1 schemas/ledger and Week 2 site package; independent reference calculations for the graph and accessibility fraction; the map and massing artifact contracts.

**Deliverables:** Accessibility tool and metric definition; known graph/reference fixtures; destination taxonomy and denominator record; Evidence Card renderer/serializer; basic evidence map; basic 3D massing view; threshold challenge/rerun records; and before/after comparison data.

**Tests:** Run `DET-004`, `DET-005`, `DET-006`, `ACC-001`, `ACC-002`, `ACC-003`, `ACC-005`, `ACC-006`, `ACC-007`, `ACC-008`, `EVD-001`, `EVD-003`, `EVD-006`, `UI-001`, and `UI-002`. Expected results include independent reference agreement, unchanged denominator, preserved unreachable origins, distinct versioned threshold results, evidence-linked map/massing, and no claim when inputs or relationships mismatch.

**Definition of done:** The 800 m result agrees with the independent reference within the pre-registered fixture tolerance; 400 m and 1200 m reruns are distinct and preserved; the height-only negative control is ready for Week 4; explicit passage overlays can alter the graph; the map and 3D massing point to frozen artifacts; and every displayed metric opens an Evidence Card.

**Risks:** Network topology or public-passage semantics may be wrong; invalid origins could change the denominator; map layers may show current live data instead of frozen evidence; a result could be visually plausible but stale.

**Fallback:** Freeze the reference fixture as the acceptance surface and mark live-data integration incomplete. Reject invalid origins rather than changing the denominator. Hide or label stale visual layers until hashes and versions reconcile.

### Week 4 — Two morphology families, lineage, overlays, and controls

**Goal:** Produce valid, distinguishable perimeter-block and linear-block scenarios under explicit constraints while preserving rejected alternatives and network-control semantics.

**Scope:** Implement registered COMPAS generators for perimeter block and linear blocks; require parent scenario, seed, parameter set, site version, and geometry hash on each call; apply FAR/coverage/height and geometry validity checks; retain one accepted candidate per family; preserve all rejected/invalid candidates and reasons; add scenario-specific public-passage overlays; and run the height-only accessibility negative control and explicit-overlay positive control.

**Dependencies:** Week 2 frozen site and Week 3 graph/evidence contracts; COMPAS runtime; constraint definitions as project decisions; accepted map and 3D artifact interfaces.

**Deliverables:** Two generator adapters; constraint and geometry verifier; scenario lineage records; accepted and rejected candidate bundle; public-passage overlay records; family comparison view; and control-test evidence.

**Tests:** Run `MOR-001` through `MOR-006`, `ACC-004`, `ACC-005`, `DET-003`, `DET-005`, `DET-006`, `DET-007`, `EVD-004`, `UI-002`, and `BEN-003`. Expected results are at least one valid accepted candidate from each family, inspectable rejected candidates, complete lineage, a passing height-only negative control, and a passing overlay positive control.

**Definition of done:** Both families generate reproducibly from frozen inputs; accepted geometry is valid and within constraints; family identity is inspectable from registered operators; all rejected candidates remain queryable; height-only changes leave accessibility unchanged; and only an explicit passage overlay changes the pedestrian graph.

**Risks:** Operators may generate invalid or non-distinguishable geometry; illustrative numbers may be mistaken for constraints; scenario lineage may be lost during export; an overlay may be applied implicitly from building massing.

**Fallback:** Reduce operator parameter ranges and candidate count while retaining both families. Require a human project decision for any constraint. Reject candidates with a recorded reason and preserve the artifact. Disable implicit network mutation and require a separately versioned overlay.

### Week 5 — Evidence-constrained critic and designer contestability

**Goal:** Make comparison and contestation change verified project state rather than only producing explanations.

**Scope:** Feed the Scenario Critic only validated Evidence Bundles. Require every claim to carry evidence IDs, assumption IDs, scope, uncertainty/limitation, and a claim type. Reject fabricated IDs, wrong-scenario evidence, unsupported numerical claims, unit mismatches, hidden overall rankings, and stale results. Implement Evidence Inspector controls for Inspect, Challenge, Modify, Rerun, Compare, Fork, Reject, and Override. Complete the 800 m challenge flow and preserve the 400/800/1200 results, original claims, forks, rejections, and human overrides in the append-only ledger.

**Dependencies:** Weeks 1–4 schemas, evidence cards, metrics, scenarios, and ledger; a fixture LLM adapter or configured provider; fixed critic evidence bundles.

**Deliverables:** Critic schema/policy; relationship verifier; Evidence Inspector; challenge and rerun handlers; fork/reject/override persistence; stale-result guard; and critic benchmark fixture suite.

**Tests:** Run `AGT-001` through `AGT-008`, `EVD-001`, `EVD-003`, `EVD-004`, `CON-001` through `CON-008`, `BEN-002`, and `DET-008`. Expected results are binary rejection of unsupported or mismatched claims, state-changing challenge/rerun, preserved original results, complete fork/reject/override history, and no hidden normative ranking.

**Definition of done:** A designer can inspect a claim, challenge 800 m, modify the threshold, rerun 400/1200 m, compare results, fork a state, reject a proposal, and override a recommendation; each action changes versioned state and appends ledger events; no computed artifact is mutated; and the critic uses only validated evidence.

**Risks:** The model may generate fluent but unsupported prose; a valid evidence ID may point to the wrong scenario or units; challenge UI may record text without changing state; stale results may remain selectable.

**Fallback:** Use deterministic fixed critic fixtures and a constrained template adapter until live-provider behavior meets the same schema. Disable the affected action rather than recording a cosmetic contest. Mark stale cards and block comparison until rerun.

### Week 6 — Controlled climate experiment with two tiers

**Goal:** Execute one reproducible, bounded radiation experiment with independent screening and verification paths.

**Scope:** Select one approved scenario and building; declare one translation axis; produce baseline and two feasible offsets; lock footprint, floors, height, FAR where applicable, weather, materials, context, sensor definition, and simulation settings; verify the sensor area is outside every footprint; run Ladybug/ladybug-radiance screening and Honeybee-Radiance verification; parse area-weighted summer cumulative incident radiation and spatial distribution; recheck geometry/constraints; and record method-specific deltas plus directional agreement/disagreement.

**Dependencies:** Weeks 1–5 artifact, scenario, verifier, evidence, and ledger contracts; installed Ladybug and Honeybee-Radiance paths; a declared weather file and recipe; a sensor-grid fixture; human approval of the experiment plan.

**Deliverables:** Experiment plan and locked-control manifest; baseline/two-variant geometry artifacts; Ladybug screening records; Honeybee-Radiance verification records; sensor and settings hashes; within-method comparison; directional agreement/disagreement report; and failed-hypothesis record where applicable.

**Tests:** Run `CLM-001` through `CLM-009`, `MOR-002`, `DET-007`, `EVD-001`, `EVD-002`, `EVD-004`, and `BEN-004`. Expected results are two executable method paths, matching locked controls within each comparison, sensor exclusion, explicit invalid/non-convergent outcomes, and no cross-method absolute-value claim or thermal-comfort overclaim.

**Definition of done:** Baseline and two feasible offsets have complete provenance through both required tiers; target metric and spatial distribution are reported; settings/weather/geometry/sensor hashes match within each comparison; constraints are preserved; directional agreement or disagreement is recorded; and a failed improvement remains an honest result if the hypothesis fails.

**Risks:** Climate dependencies may not execute; recipes may drift; screening and verification values may be conflated; a lower radiation value may be over-interpreted; a feasible-looking variant may violate a locked condition.

**Fallback:** Preserve explicit tool failure and keep both tiers in the plan. Use the smallest approved recipe/fixture for smoke evidence while marking full experiment incomplete. Report within-method changes only and require verifier approval before any comparison.

### Week 7 — Full integration, recovery, export, and walkthrough

**Goal:** Connect the four stages into a recoverable designer workflow whose backend state survives stale data and tool failures.

**Scope:** Integrate Understand → Explore → Test → Refine with the human decision surface; handle QGIS `OUTCOME_UNKNOWN`, stale snapshots, stale scenarios, failed geometry, non-convergent climate runs, and malformed model output; implement research-bundle/ledger export; replay the selected scenario from frozen artifacts; and run a timed designer walkthrough covering inspect, challenge, rerun, compare, fork, reject, override, and export.

**Dependencies:** Completion of Weeks 1–6 gates; all adapters and schemas; a clean export directory; an independent walkthrough reviewer.

**Deliverables:** Integrated workflow; recovery-state transitions; stale-result UI; replay/export bundle; complete demonstration script; and walkthrough record with ledger/evidence references.

**Tests:** Run `AGT-009`, `AGT-010`, `SEC-003`, `SEC-004`, `SEC-005`, `EVD-005`, `EVD-008`, `CON-001` through `CON-008`, `BEN-005`, `DET-008`, and the end-to-end smoke sequence. Expected results are safe recovery, no unverified retry, replayable state, preserved history, and a human action that changes state at every required contestability point.

**Definition of done:** An independent reviewer can load the frozen case, traverse all four stages, inspect evidence, challenge and rerun an assumption, compare versions, make a human decision, replay the selected scenario, and export the bundle. Any injected failure leaves an honest status and recoverable next action.

**Risks:** Integration may expose inconsistent IDs or stale caches; export may omit large artifacts or hashes; the walkthrough may depend on hidden browser/QGIS state; recovery may retry a non-idempotent call.

**Fallback:** Run the complete flow from a recorded fixture bundle and label live integration gaps. Block export until references and hashes are complete. Reconcile state before retry and require a new version for any recovery that changes inputs.

### Week 8 — Freeze, independent rerun, benchmark, and demonstration

**Goal:** Produce a reviewable release candidate and an evidence-bounded research demonstration.

**Scope:** Freeze dependency versions, configuration, prompts/templates, model adapter configuration, QGIS profile/plugin/server versions, reference dataset, snapshots, weather, climate recipes, and fixture manifests. Independently rerun the full case; execute every release-blocking test; benchmark site metrics, critic reliability, morphology validity/lineage, climate controls, and end-to-end replay/export; document failures, unknown outcomes, and limitations; and prepare the 8–12 minute demonstration.

**Dependencies:** Weeks 1–7 definitions of done; an independent runner; a clean or separately provisioned environment; final document reconciliation by the controller.

**Deliverables:** Frozen dependency/configuration manifest; independent rerun bundle; benchmark report; release-gate report; limitations and unresolved-feasibility register; demonstration script; and final research export.

**Tests:** Run all tests marked `RELEASE BLOCKING` in `docs/06_EVALUATION_FRAMEWORK.md`, including `DET-*`, `ACC-*`, `AGT-*`, `EVD-*`, `MOR-*`, `CLM-*`, `CON-*`, `SEC-*`, `UI-*`, and `BEN-*`. Each test must have a fixture/run ID, observed result, evidence references, status, and reviewer. Expected result: every mandatory test is `PASS`; any `FAIL`, `BLOCKED`, or `OUTCOME_UNKNOWN` keeps the prototype incomplete.

**Definition of done:** Frozen inputs and versions are documented; an independent rerun reconstructs the selected scenario and decision; both climate tiers and the accessibility challenge are demonstrated; all rejected/failed alternatives remain inspectable; all release-blocking gates pass; and the controller records whether the prototype is ready for the course research release.

**Risks:** A clean rerun may reveal environment or version drift; benchmark evidence may be incomplete; time pressure may encourage silent removal of mandatory gates; the demonstration may overstate research conclusions.

**Fallback:** Report the prototype as incomplete with exact failed/blocked/unknown gates. Cut optional scope according to the cut order below, rerun the remaining mandatory gates, and escalate any mandatory gate failure or schedule decision to the human.

## Risk register

Likelihood and impact are preliminary planning judgements, not measured probabilities. The register is updated with observed evidence during each milestone.

| ID | Risk and trigger | Impact | Mitigation | Fallback / decision owner |
|---|---|---|---|---|
| `R-01` | QGIS MCP cannot connect, or a post-dispatch connection is lost. | A GIS result may be missing or its outcome may be unknown. | Pin profile/plugin/server versions; serialize calls; record expected artifacts and project state. | Mark `OUTCOME_UNKNOWN`, reconcile before retry, and escalate a mandatory gate to the human. |
| `R-02` | Agent reaches raw `execute_code`, unrestricted SQL, dynamic Python, or an unapproved batch path. | Unsafe or unbounded external execution. | Use a narrow facade, allowlist, schemas, resource limits, controlled directories, and `SEC-*` tests. | Deny and log the request; keep the default profile unavailable until the gate passes. |
| `R-03` | PDOK/OSM sources have missing tags, mismatched timestamps, or changing responses. | Site metrics may be incomplete or irreproducible. | Freeze raw responses, query/timestamp/licence/hash, coverage, and data-gap metadata. | Use an approved frozen fixture; do not replace missing values with zero. |
| `R-04` | CRS, vertical reference, or units are absent or inconsistent. | Distances, areas, heights, and climate geometry can be wrong while looking plausible. | Precondition validators, known-answer fixtures, explicit units on Evidence Cards. | Fail closed and create a new version after correction. |
| `R-05` | Human site or experiment approval arrives late. | Adoption or climate schedule slips. | Separate proposal from final adoption; parallelize fixture and schema work. | Keep state `PROPOSED` and do not silently adopt a site or experiment. |
| `R-06` | COMPAS operators generate invalid, out-of-bound, or indistinguishable families. | Morphology stage cannot support the approved demonstration. | Register two explicit families, fixed seeds, geometry/constraint verifier, and rejected-candidate retention. | Narrow parameter ranges/candidate count while retaining both families; escalate if one family remains infeasible. |
| `R-07` | Pedestrian graph, destination taxonomy, passage overlay, or denominator semantics drift. | Accessibility comparisons become misleading. | Freeze origin/destination/network versions; test unreachable origins, height-only negative, overlay positive, and thresholds. | Block comparison and issue a new explicit graph or taxonomy version. |
| `R-08` | Agent fabricates or mislinks evidence, units, rankings, or stale results. | Natural-language output can mislead the designer. | Evidence-only critic input, relationship verifier, stale guard, malformed-output handling. | Reject the claim and use a fixture adapter until reliability gates pass. |
| `R-09` | Ladybug or Honeybee-Radiance dependency/recipe fails or does not converge. | Climate experiment cannot be validated. | Week 1 real smoke tests; locked recipes/settings; explicit invalid status and convergence records. | Preserve failed hypothesis/tool run; keep both tiers mandatory and escalate incomplete status. |
| `R-10` | Screening and verification values are compared as if numerically identical. | Climate conclusions become scientifically invalid. | Store method-specific outputs and compare deltas within each method; report direction only across methods. | Block the comparison and correct the Evidence Card/report. |
| `R-11` | Replay/export omits an artifact, hash, parent, or human decision. | The result cannot be independently reconstructed. | Append-only ledger, export manifest, replay test, independent Week 7/8 reruns. | Block release until the missing link is restored; no manual prose patch counts as replay. |
| `R-12` | Schedule pressure expands or silently cuts the MVP. | The prototype may become neither demonstrable nor auditable. | Use fixed contract, cut order, binary gates, and weekly definition of done. | Cut optional scope only; any mandatory cut requires a human scope/schedule decision. |

## Cut order

When time or environment constraints require reduction, cut in this order and record the cut in the ledger and release report:

1. Optional search sophistication and extra mutation operators.
2. Extra candidates beyond one accepted candidate per morphology family and the required rejected-candidate examples.
3. Visual polish and nonessential interaction styling.
4. Additional benchmarks beyond the frozen-site, critic-fixture, morphology, climate, and end-to-end gates.
5. Optional metrics, Space Syntax lenses, and future optimization interfaces.

The cut order never removes a release gate by implication. A cut that affects a mandatory requirement is a human decision and leaves the prototype incomplete until the revised scope is approved and re-evaluated.

## Non-cuttable mandates

The following remain mandatory for the approved MVP:

- The four stages Understand, Explore, Test, and Refine, followed by a human decision.
- One human-confirmed Rotterdam M4H StudyArea with analysis-specific frozen PDOK/OSM snapshots and provenance; formal claims use a separate approved DesignBoundary.
- QGIS MCP integration, controlled permissions, serialized operations, and `OUTCOME_UNKNOWN` recovery.
- The exact accessibility definition, 800 m initial setting, 400/800/1200 m challenge reruns, denominator rules, unreachable-origin handling, height-only negative control, and explicit-passage positive control.
- Both COMPAS morphology families, one accepted candidate per family, valid constraints, lineage, and retained rejected candidates.
- Ladybug/ladybug-radiance screening and Honeybee-Radiance verification; method-specific comparison and no thermal-comfort overclaim.
- One controlled climate experiment with locked variables, baseline, two feasible offsets, external sensor area, and complete settings/provenance.
- Evidence Inspector, evidence-constrained claims, Design Ledger, replay/export, stale-result handling, and human inspect/challenge/modify/rerun/compare/fork/reject/override actions.
- Provider-neutral model adapter and the boundary that deterministic tools calculate while humans decide.
- Honest labels for research findings, project decisions, dataset observations, computed results, and illustrative examples; missing data remain missing.

## P0 inventory

These identifiers and meanings are governed by [01_PRODUCT_REQUIREMENTS.md](01_PRODUCT_REQUIREMENTS.md). This table is a delivery index, not a second requirements definition.

| ID | Authoritative requirement title |
|---|---|
| `P0-01` | Human-confirmed StudyArea and formal boundary guard |
| `P0-02` | Frozen PDOK and OpenStreetMap data |
| `P0-03` | Controlled QGIS MCP integration |
| `P0-04` | Typed evidence for material outputs |
| `P0-05` | Contestable accessibility metric |
| `P0-06` | Two COMPAS morphology families |
| `P0-07` | Scenario lineage and versioning |
| `P0-08` | Deterministic validation and relationship checks |
| `P0-09` | Bounded agent interaction |
| `P0-10` | Contestability actions |
| `P0-11` | Evidence-bounded Scenario Critic |
| `P0-12` | Ladybug climate screening |
| `P0-13` | Honeybee-Radiance verification |
| `P0-14` | One controlled climate refinement experiment |
| `P0-15` | Basic evidence map |
| `P0-16` | Basic 3D massing |
| `P0-17` | Append-only Design Ledger |
| `P0-18` | Human decisions and overrides |
| `P0-19` | Provider-independent model adapter |
| `P0-20` | Replayable export and complete case |
| `P0-21` | Explicit decision rules and no hidden aggregate score |

## P0 consistency matrix

The following matrix maps every authoritative P0 requirement to evidence/rationale, architecture component, evaluation tests, and implementation milestone. The rationale column uses the project’s evidence-status vocabulary; it is not a new empirical claim.

| Requirement | Evidence / rationale | Architecture component | Evaluation test(s) | Milestone |
|---|---|---|---|---|
| `P0-01` | `PROJECT_DECISION`: one human-confirmed QGIS StudyArea bounds exploration; formal claims remain behind HumanDecision-backed DesignBoundary approval. | StudyArea/DesignBoundary models; confirmation service; project state; snapshot manifest. | `SA-001`..`SA-005`, `EVD-001`, `EVD-003`, `BEN-005`. | Week 2 |
| `P0-02` | `PROJECT_DECISION` plus `DATASET_OBSERVATION`: frozen PDOK/OSM inputs enable reproducibility and preserve gaps. | Data connectors; immutable artifact store; licence/hash manifest. | `DET-001`, `EVD-002`, `EVD-003`, `EVD-006`, `BEN-001`. | Week 2 |
| `P0-03` | `PROJECT_DECISION`: mandatory QGIS MCP needs a bounded and auditable execution boundary. | QGIS MCP facade; policy gate; serialized dispatcher; state reconciler. | `SEC-001`..`SEC-006`, `AGT-001`, `AGT-009`. | Weeks 1–2 |
| `P0-04` | `RESEARCH_FINDING` translated into `PROJECT_DECISION`: material claims require a complete evidence chain. | Evidence Card schema/store; artifact and relationship validators; Evidence Inspector. | `EVD-001`..`EVD-008`, `AGT-002`..`AGT-007`. | Weeks 1, 3, 5 |
| `P0-05` | `PROJECT_DECISION`: a fixed-origin grocery-access fraction makes the assumptions and denominator testable. | Graph builder; accessibility metric; Parameter Registry; rerun service. | `ACC-001`..`ACC-008`, `CON-002`..`CON-004`. | Weeks 3–5 |
| `P0-06` | `PROJECT_DECISION`: two registered COMPAS families provide bounded morphological alternatives. | COMPAS adapter; morphology operators; constraint engine. | `MOR-001`..`MOR-003`, `MOR-006`, `BEN-003`. | Week 4 |
| `P0-07` | `PROJECT_DECISION`: scenario history must survive generation, rejection, modification, and forks. | Scenario lineage graph; immutable geometry artifacts; rejection records. | `MOR-004`, `MOR-005`, `EVD-005`, `CON-005`. | Weeks 4–7 |
| `P0-08` | `RESEARCH_FINDING` plus `PROJECT_DECISION`: syntactic validity cannot establish semantic correctness. | Deterministic Verifier; CRS/unit/geometry/topology and relationship gates. | `DET-001`..`DET-009`, `AGT-003`, `AGT-005`, `ACC-008`. | Weeks 1–8 |
| `P0-09` | `PROJECT_DECISION`: six roles operate through one controlled harness. | Orchestrator; role policies; tool router; Evidence Bundle builder. | `AGT-001`..`AGT-010`, `SEC-001`. | Weeks 1, 5, 7 |
| `P0-10` | `RESEARCH_FINDING` translated into `PROJECT_DECISION`: contestability must change state. | Contest command handlers; version/fork service; comparison and decision records. | `CON-001`..`CON-008`, `ACC-006`, `BEN-005`. | Weeks 3, 5, 7 |
| `P0-11` | `PROJECT_DECISION`: criticism remains bounded by validated evidence and explicit decision rules. | Critic schema/policy; relationship verifier; comparison view. | `AGT-002`..`AGT-007`, `BEN-002`. | Week 5 |
| `P0-12` | `PROJECT_DECISION`: Ladybug/ladybug-radiance supplies the screening method. | Screening adapter; recipe/settings manifest; parser. | `CLM-001`, `CLM-003`..`CLM-008`, `BEN-004`. | Weeks 1, 6 |
| `P0-13` | `PROJECT_DECISION`: Honeybee-Radiance supplies a separate verification method. | Verification adapter; locked recipe; method-specific comparator. | `CLM-002`..`CLM-009`, `BEN-004`. | Weeks 1, 6 |
| `P0-14` | `PROJECT_DECISION`: one baseline and two offsets form a controlled, falsifiable experiment. | Experiment Plan; control manifest; sensor and climate validators. | `CLM-003`..`CLM-009`, `EVD-004`. | Week 6 |
| `P0-15` | `PROJECT_DECISION`: a map makes spatial evidence inspectable. | Evidence map renderer; frozen-layer and CRS resolver. | `UI-001`, `EVD-001`, `EVD-006`. | Week 3 |
| `P0-16` | `PROJECT_DECISION`: basic 3D connects geometry identity to scenarios and climate results. | 3D massing artifact/view; scenario-state renderer. | `UI-002`, `MOR-002`, `CLM-004`. | Weeks 3–6 |
| `P0-17` | `RESEARCH_FINDING` translated into `PROJECT_DECISION`: chat history cannot provide authoritative replay. | SQLite transactions; append-only Design Ledger; replay engine. | `DET-008`, `EVD-005`, `CON-008`, `BEN-005`. | Weeks 1, 5, 7–8 |
| `P0-18` | `PROJECT_DECISION`: consequential acceptance, rejection, modification, and override remain human actions. | HumanDecision schema; approval gates; ledger events. | `CON-006`..`CON-008`, `EVD-005`, `BEN-005`. | Weeks 2, 5–8 |
| `P0-19` | `PROJECT_DECISION`: provider independence protects domain truth from provider formats. | Provider-neutral model adapter; model-run metadata; schema validator. | `AGT-008`, `AGT-010`, `EVD-007`. | Weeks 1, 5 |
| `P0-20` | `PROJECT_DECISION`: the research claim requires a portable four-stage trace. | Export manifest; artifact store; replay engine; walkthrough. | `EVD-005`, `EVD-008`, `BEN-005`. | Weeks 7–8 |
| `P0-21` | `PROJECT_DECISION`: normative ranking requires an explicit human rule. | Parameter/decision registry; critic policy; trade-off comparison. | `AGT-006`, `CON-004`, `BEN-002`. | Week 5 |

## Documentation red-team record

The final handoff review challenged the documents as one system rather than accepting individual drafts. It produced the following corrections and remaining feasibility gates:

| Area | Adversarial finding | Resolution or gate |
|---|---|---|
| Product | The research report's broad optimization and multi-metric programme exceeded a credible single-person eight-week prototype. | P0 retains one site, two morphology families, one accessibility metric, one assumption challenge, and one controlled climate experiment. Optional search, extra candidates, polish, and additional benchmarks are cut first. |
| Architecture | Six named agents could be misread as a swarm, and broad QGIS MCP access could bypass the deterministic boundary. | Roles are bounded capabilities behind one harness. The QGIS facade denies arbitrary code, dynamic Python, unrestricted SQL, and batch equivalents. Backend state is authoritative. |
| Reliability | A post-dispatch timeout could cause a duplicate external operation if treated as ordinary failure. | `OUTCOME_UNKNOWN` requires artifact and project-state reconciliation before any bounded retry. Operations against one QGIS instance are serialized. |
| GIS | Building-form changes do not inherently change network accessibility; invalid origins could also alter the denominator silently. | Height-only change is a negative control. Only a versioned passage overlay can change graph topology. The approved origin set, including unreachable origins, remains the denominator. |
| Requirements | Early drafts contained circular dependencies and a provisional 20-item traceability scheme. | Dependencies are acyclic. The final 21 P0 requirements map one-to-one to evidence/rationale, architecture, evaluation tests, and milestones in the matrix above. |
| Morphology | Superficial parameter variation could be presented as meaningful diversity. | P0 fixes two operator-defined families and tests family identity, validity, lineage, reproducibility, and rejected-candidate retention without claiming optimality. |
| Climate | The original example changed more than one design variable, and similarly named radiation outputs could be treated as interchangeable or as thermal-comfort proof. | The first experiment changes one declared-axis offset only. Screening and verification remain separate method families; comparisons are within method, with directional agreement/disagreement reported across them. No thermal-comfort claim is permitted. |
| Evidence | A syntactically valid evidence ID can still support the wrong scenario, units, dataset, or result. | Relationship validation is required in addition to schema validation. Research, external data, project decisions, computed outputs, interpretation, and illustrative examples remain distinct. |
| Contestability | Explanation alone could be mistaken for contestability, or a human override could erase an inconvenient result. | Challenge/modify/rerun/fork/reject/override create append-only state transitions. Overrides govern decisions but cannot mutate computed evidence. |
| Evaluation | An aggregate pass rate could conceal a critical failure, and a failed experiment could be hidden. | Every release-blocking test must pass. Failed hypotheses and directional disagreement remain valid recorded results. |

The documentation is allowed to enter Milestone 1 with unresolved runtime feasibility because Week 1 exists to test it. The latest M1-R02 evidence establishes the live bounded QGIS geometry operation, standalone Ladybug screening, Honeybee-Radiance verification, typed QGIS denial auditing, transactional replay tests, and fail-closed gate certification over actual pytest results and hashed artifacts. The local deployment uses an explicit Intel-QGIS-under-Rosetta fallback and a separate ARM64 Radiance runtime; native ARM portability and clean-machine reproduction remain pre-release checks. Failure of a mandatory gate requires an explicit human scope or schedule decision; it cannot be resolved by changing the documentation claim.

## Static self-audit against the approved handoff

This self-audit records how these planning documents satisfy the approved handoff. The controller separately verifies the complete nine-document set:

| Handoff section | Check | Result in these two documents |
|---|---|---|
| Section 20 | Evaluation contains deterministic correctness, accessibility controls/negative and positive controls, agent reliability, evidence, morphology, climate, contestability, benchmarks, and binary release gates. | Covered by `docs/06_EVALUATION_FRAMEWORK.md` sections and IDs listed in its release-gate inventory. |
| Section 21 | Weeks 1–8 are present in the approved sequence; Week 1 includes real QGIS/Ladybug/Honeybee smoke tests; each week has goal, scope, dependencies, deliverables, tests, definition of done, risks, fallback. | Covered by the eight milestone sections above. |
| Section 25 | Every authoritative P0 item maps to evidence/rationale, architecture, test, and milestone. | Covered by the 21-row matrix above using the final identifiers from `docs/01_PRODUCT_REQUIREMENTS.md`. |
| Section 26 | Red-team prompts cover product scope, architecture/permissions/retry, GIS CRS/denominator, morphology, climate tier separation, evidence, contestability, and binary evaluation. | Covered by fixed MVP contract, risk register, non-cuttable mandates, and evaluation self-audit. |
| Section 27 | Unresolved feasibility risks remain visible; no critical test is accepted by an aggregate score; mandatory failures produce incomplete status and human escalation. | Covered by release-gate policy, risk register, fallback rules, and Week 8 definition of done. |

The controller must additionally verify cross-document wording, exact source-copy hash, final P0 field completeness, six-agent-role detail, and the nine-document count. Those checks are outside the authority of this two-file subtask and must not be inferred from this matrix.
