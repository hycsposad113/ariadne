# Eight-Week Urban Design Project Blueprint

> **2026-09-22 SUPERSEDED AS CURRENT EXECUTION ENTRY：** 原文完整保留作歷史計畫。新的學期排程與產品範圍使用 [整體中文藍圖](2026-09-22-semester-project-blueprint-zh.md) 及 [Week 4 詳細計畫](2026-09-22-week4-platform-site-analysis-zh.md)。舊 spatial gate 的來源／政策保護要求仍有效；新需求不自動批准任何舊政策。下方 prompt 不再作為目前任務的預設入口。

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` for one week at a time. Every week ends with an
> independent checkpoint before the next week begins. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Deliver an evidence-based, contestable urban-design prototype covering
StudyArea confirmation, spatial evidence, accessibility, morphology, agent
critique, climate refinement, integration and independent release validation.

**Architecture:** The blueprint is a clean-start normative sequence. Typed
project state and immutable evidence flow from deterministic tools through
validators to human decisions. Week 2 has independent spatial and weather
gates: spatial acceptance unlocks Weeks 3–4, while weather acceptance is
required before Week 6.

**Tech Stack:** Python, Pydantic, SQLite, FastAPI, pytest, QGIS MCP, PDOK, OSM,
COMPAS, Ladybug/ladybug-radiance, Honeybee-Radiance, React/TypeScript evidence
surfaces, SHA-256 manifests.

**Planning status:** This is a normative roadmap. Writing it does not execute,
accept or reopen any week and does not alter current project authority.

---

## Dependency graph

```text
Week 1 foundation
   ├── Week 2 spatial gate → Week 3 → Week 4 → Week 5 ─┐
   └── Week 2 weather gate ─────────────────────────────┤
                                                        ↓
                                                      Week 6
                                                        ↓
                                                      Week 7
                                                        ↓
                                                      Week 8
```

This blueprint does not reset current status. In the present workspace Week 1
foundation and StudyArea confirmation already have accepted evidence, while the
new Week 2 spatial gate is planned for implementation and weather remains
blocked.

## Week 1 — Foundation

- [ ] Define typed entities for project, StudyArea, DesignBoundary, Artifact,
  DatasetSnapshot, Scenario, ToolRun, Evidence, ParameterDefinition and
  HumanDecision.
- [ ] Implement SQLite versioned state, append-only ledger and deterministic
  replay.
- [ ] Implement provider-neutral model adapters and restricted QGIS facade.
- [ ] Run known-answer geometry, QGIS, Ladybug and Honeybee smoke tests.
- [ ] Inject post-dispatch connection loss and require `OUTCOME_UNKNOWN` plus
  state/artifact reconciliation.

**Checkpoint W1:** Pass only when typed round trips, geometry gates, ledger
replay, QGIS security boundaries and both climate paths have real evidence.
Fixture success cannot substitute for unavailable mandatory runtime evidence.

## Week 2 — StudyArea and analysis inputs

- [ ] Draw, save, validate and human-confirm one QGIS StudyArea.
- [ ] Freeze PDOK/OSM spatial sources with receipts, licences, CRS, units,
  hashes and lineage.
- [ ] Inventory origins, grocery tags and pedestrian-network candidates.
- [ ] Obtain human decisions for origin denominator, destination taxonomy and
  pedestrian policy.
- [ ] Independently accept the immutable spatial package.
- [ ] Build the separate weather evidence dossier and report it independently
  as `PASS`, `FAIL`, `BLOCKED` or `OUTCOME_UNKNOWN`.

**Checkpoint W2:** Spatial `PASS` unlocks Weeks 3–4. Weather `PASS` is optional
at W2 but mandatory before Week 6. Formal cadastral, ownership, zoning and
buildability claims remain blocked without DesignBoundary approval.

## Week 3 — Accessibility and evidence surface

- [ ] Build a deterministic pedestrian graph from the approved policy.
- [ ] Validate topology, edge units, components and known shortest paths.
- [ ] Implement the fixed-origin accessibility fraction at 800 m.
- [ ] Preserve unreachable origins in the denominator.
- [ ] Create Evidence Cards with formula, inputs, units, hashes, limitations
  and status.
- [ ] Render an evidence map and basic 3D massing.
- [ ] Run versioned 400/800/1200 m sensitivity calculations.

**Checkpoint W3:** The 800 m result matches an independent reference; all
threshold runs remain distinct; denominator invariants hold; evidence
relationships validate; every display resolves a complete Evidence Card.

## Week 4 — Morphology and controls

- [ ] Register deterministic perimeter-block and linear-block generators.
- [ ] Bind each candidate to parent, StudyArea, source package, seed,
  parameters and constraints.
- [ ] Validate geometry, FAR, coverage and height.
- [ ] Preserve every rejected or invalid candidate.
- [ ] Obtain human acceptance for one candidate from each family.
- [ ] Implement explicit public-passage overlays.
- [ ] Run height-only negative and overlay positive accessibility controls.

**Checkpoint W4:** Both families are reproducible and distinguishable;
accepted candidates satisfy effective constraints; rejected history is
complete; height-only changes preserve graph/accessibility hashes; only an
explicit overlay changes the graph.

## Week 5 — Evidence-constrained critic and contestability

- [ ] Define critic input/output schemas and relationship verification.
- [ ] Reject fabricated evidence, wrong-scenario evidence, unit mismatches,
  unsupported numbers and hidden overall rankings.
- [ ] Implement Inspect, Challenge, Modify, Rerun, Compare, Fork, Reject and
  Override.
- [ ] Execute the 800 m to 400/1200 m challenge flow.
- [ ] Preserve original evidence, forks, rejections and human overrides.
- [ ] Run adversarial critic and stale-result benchmarks.

**Checkpoint W5:** Every contestability action changes versioned state and
appends ledger events; originals remain immutable; an unsupported critic claim
cannot be accepted.

## Week 6 — Controlled climate experiment

- [ ] Resolve and approve the weather method gate.
- [ ] Select one approved scenario and building.
- [ ] Define one translation axis, baseline and two feasible offsets.
- [ ] Lock geometry, floors, height, weather, materials, context, sensor grid
  and recipes.
- [ ] Obtain human approval for the experiment plan.
- [ ] Run Ladybug/ladybug-radiance screening.
- [ ] Run Honeybee-Radiance verification.
- [ ] Compare within each method and record directional agreement or
  disagreement.
- [ ] Preserve failed and non-improving hypotheses.

**Checkpoint W6:** Both tiers execute with matching locked controls; sensor
exclusion holds; results contain area-weighted cumulative incident radiation
and spatial distribution; no cross-method absolute-value or thermal-comfort
overclaim is made.

## Week 7 — Integration, recovery and export

- [ ] Integrate Understand → Explore → Test → Refine.
- [ ] Authorize stages from persisted state.
- [ ] Handle stale snapshots, invalid geometry, malformed model output, failed
  climate runs and QGIS `OUTCOME_UNKNOWN`.
- [ ] Implement research-bundle and ledger export.
- [ ] Replay the selected scenario solely from frozen artifacts and ledger.
- [ ] Run the complete designer walkthrough.

**Checkpoint W7:** An independent reviewer can inspect, challenge, rerun,
compare, fork, reject, override, replay and export without hidden chat, browser
or live-QGIS state.

## Week 8 — Freeze and release decision

- [ ] Freeze dependencies, configurations, prompts, datasets, weather, recipes
  and fixture manifests.
- [ ] Provision a clean or independently controlled environment.
- [ ] Re-run all release-blocking tests.
- [ ] Rebuild the selected scenario and decisions from frozen evidence.
- [ ] Run deterministic, critic, morphology, climate and end-to-end benchmarks.
- [ ] Document failures, limitations and unresolved feasibility.
- [ ] Prepare and rehearse the 8–12 minute research demonstration.
- [ ] Obtain the final human release decision.

**Checkpoint W8:** Release is eligible only when every release-blocking gate is
`PASS`. Any `FAIL`, `BLOCKED` or `OUTCOME_UNKNOWN` remains visible and keeps the
prototype incomplete.

## Cross-week acceptance record

Every weekly record must contain:

- exact input and output artifact hashes;
- source, tool and model versions;
- test IDs mapped to collected nodes;
- observed state counts;
- ledger event references;
- human decisions and reasons where required;
- unresolved gaps and limitations;
- explicit `PASS`, `FAIL`, `BLOCKED` or `OUTCOME_UNKNOWN`;
- the next authorized phase.

No week may rewrite prior evidence, convert missing data to zero, infer a formal
boundary from StudyArea confirmation, accept its own executor output without
independent review, hide failed scenarios or hypotheses, or treat a green test
total as semantic acceptance.

## Fixed assumptions

- This is a clean-start normative blueprint; current workspace status is
  reported separately.
- Detailed current Week 2 execution follows
  `2026-09-21-week2-spatial-input-gate.md`.
- Spatial acceptance may pass while weather remains blocked.
- One controlled live PDOK/OSM run is authorized after offline checkpoints.
- Human spatial-policy selection occurs after live inventory observation.
- Port 8787 remains owned by Hermes.
- Immutable revisions, manifests and ledger records replace Git checkpoints in
  this non-Git workspace.

## Self-review record

- Spec coverage: Weeks 1–8, dependencies and completion gates are explicit.
- Placeholder scan: every phase names concrete work and acceptance evidence.
- Dependency consistency: Week 3 and Week 4 depend on spatial acceptance;
  Week 6 depends on weather acceptance and the Week 5 chain.
