# M2-A03 Weather Method and Analysis-Input Freeze Implementation Plan

> **Superseded-plan notice (2026-09-21):** This document is retained as
> immutable historical planning evidence. Its atomic PDOK/OSM/EPW completion
> model is superseded for current execution by
> `2026-09-21-week2-spatial-input-gate.md`. R08 through R09-R01 and the blocked
> r03 package remain authoritative historical evidence; this notice does not
> approve weather or alter any recorded result.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the weather-source method with human authority, then produce and independently accept one reproducible Rotterdam M4H v5 Week 2 analysis-input package without changing the approved StudyArea or treating unproven weather semantics as valid.

**Architecture:** Keep immutable R05–R08-R01 evidence and the blocked r03 package as historical parents. First build a source-specific decision dossier; only a recorded human method and source decision can unlock a narrowly tested source path, a fresh acquisition revision, and the separate origin/destination/network policy decisions. The backend ledger and typed artifacts remain authoritative; QGIS is an external tool, not project state.

**Tech Stack:** Python 3.11+, pytest, Pydantic, SQLite ledger, PDOK OGC API, OSM Overpass, EPW/Ladybug, SHA-256 manifests, EPSG:28992.

---

## Operating boundary and file map

This plan covers **M2-A03 / Week 2 only**. The next action is `M2-A03-R09` source-method research. It does not reopen the completed R08-R01 verifier repair and does not start accessibility, morphology, or climate analysis. The current weather conclusion is `SEMANTICS_UNRESOLVED`; approved weather sources and DatasetSnapshots are both zero. StudyArea v5 remains the exploration scope, and r03 remains `BLOCKED`. The last independently checked R08-R01 frozen result hash is `49d0f3408892fc9412e01a47af74c154626bc69d50f88e3804218a5db85a3bab`; this is a verifier PASS, not weather approval.

| File or directory | Responsibility | Earliest allowed change |
| --- | --- | --- |
| `AGENTS.md`, `README.md`, `docs/01_PRODUCT_REQUIREMENTS.md`, `docs/02_SYSTEM_ARCHITECTURE.md`, `docs/03_AGENT_ARCHITECTURE.md`, `docs/05_EVIDENCE_FRAMEWORK.md`, `docs/06_EVALUATION_FRAMEWORK.md`, `docs/07_IMPLEMENTATION_PLAN.md` | Authoritative rules and Week 2 gates | Read now; update only if implementation reality later changes |
| `docs/m2-a03-r08-minute-semantics-review.md`, `docs/m2-a03-r08-r01-review-addendum.md` | Accepted weather evidence and repaired verifier boundary | Read only |
| `artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-minute-semantics-20260919T154701Z/` | Retained R08 source/evaluation evidence | Never rewrite |
| `artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-r01-verifier-repair-20260919T172048Z/` | Frozen R08-R01 verification | Never rewrite |
| `artifacts/milestone2-analysis-inputs-rotterdam-m4h/run-study-area-rotterdam-m4h-pilot-project-v5-r03/` | Historical blocked acquisition | Never rerun or rewrite |
| `docs/m2-a03-r09-weather-method-decision-docket.md` | New R09 evidence classification and human decision request | Stage 1 only |
| `artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r09-weather-method-evidence/` | New append-only R09 source-document captures, manifest, and request log | Stage 1 only |
| `src/urban_design/m2a03_sources.py`, `src/urban_design/analysis_inputs.py`, `scripts/build_m2a03_analysis_inputs.py` | Existing source validator/acquisition/publication path | Stage 3 only, if the approved route requires a narrow change |
| `tests/test_m2a03_sources.py`, `tests/test_m2a03_analysis_inputs.py` | Offline behavior and fail-closed tests | Stage 3 only, if code changes |
| `.urban_design_runtime/state.sqlite3`, authoritative artifact root, StudyArea/QGIS state | Live project authority | Stage 4 or 5 only as explicitly required by the approved operation |

There is no Git repository at this workspace root (`git status` returns `fatal: not a git repository`). Do not invent a branch, worktree, commit, or diff. Use new package paths, hash manifests, and file-by-file review as the change record. A later migration to Git would require a separate decision.

## Stage 0 — Reconfirm the acceptance boundary (read-only)

**Owner:** Executor prepares evidence; Control Tower verifies. **Output:** short baseline section in the R09 dossier. **No live source request.**

- [ ] Read the source-of-truth files in the table above and the exact R08-R01 addendum.
- [ ] Confirm the frozen result hash with `shasum -a 256 artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-r01-verifier-repair-20260919T172048Z/frozen-verification-result.json`; expected hash is `49d0f3408892fc9412e01a47af74c154626bc69d50f88e3804218a5db85a3bab`.
- [ ] Re-run the retained verifier only to a newly created disposable directory under `/private/tmp`. Run `r09_preflight_dir=$(mktemp -d /private/tmp/m2-a03-r09-preflight.XXXXXX)` and then `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-r01-verifier-repair-20260919T172048Z/r08-r01-verify.py --output "$r09_preflight_dir/result.json"` in the same shell. Expected: `PASS`, 53 input files, three candidates, no acceptance failures. Preserve the frozen result.
- [ ] Read-only inspect active StudyArea, DatasetSnapshot count, ledger count, and r03 package status. Record actual current values and any drift; do not substitute the historical 24/0 counts as live observations.
- [ ] Inspect the acquisition order in `src/urban_design/m2a03_sources.py` and the CLI default `--revision r03` in `scripts/build_m2a03_analysis_inputs.py`; do not invoke the build CLI now.

**Self-check:** Each baseline claim names a file, query, or verifier output. Any hash mismatch, authority-state drift, or missing evidence is `BLOCKED` and stops this packet before new conclusions. A verifier `PASS` is never recorded as approval of a weather source.

## Stage 1 — Produce the weather-method decision dossier (next executable task)

**Owner:** Executor; Control Tower independently reviews. **Output:** one R09 append-only evidence package and one decision docket. **No source selection or conversion.**

- [ ] Record the precise unresolved question: what does `Minute=0` mean for each of the three retained Rotterdam TMYx files, including the interval endpoint, day boundary, and solar-radiation timestamp?
- [ ] Search only first-party public documentation and metadata from the relevant weather providers or dataset producers. Capture URL, publisher, title, version/date, retrieval time, licence/attribution, exact file family or station scope, relevant short excerpt or page location, and what the evidence does **not** establish. Do not download candidate EPW ZIPs or invoke weather APIs.
- [ ] Separate `GENERIC_FORMAT_RULE`, `PROVIDER_SPECIFIC_SEMANTICS`, `PARSER_BEHAVIOR`, `PROJECT_IMPLEMENTATION_CONTRACT`, and `INFERENCE` in the dossier. The provider-hosted generic EPW dictionary's `0..60` range is not proof of the three source files' endpoint meaning.
- [ ] For route B, document any first-party alternative weather-source documentation that explicitly states its hourly timestamp convention, coverage, version, licence, and suitability for Rotterdam. A listing or station proximity alone is insufficient. Do not select or download a candidate.
- [ ] For route A, state the exact additional source-specific evidence needed before `0→60` can be considered; keep all retained derived EPWs labeled experimental and unapproved.
- [ ] Write the R09 dossier and immutable package with `integrity-manifest.json` using the retained R08 manifest's `files` convention: each included file has `path`, `size_bytes`, `sha256`, `kind`, `parent_paths`, and `parent_sha256`; exclude the manifest itself to avoid a self-hash cycle. Add a package-local deterministic verifier that checks existence, hashes, sizes, and parent references, plus a retrieval/request log. Explicitly record `candidate ZIP/API requests = 0`, `approved weather sources = 0`, `DatasetSnapshots published = 0`, and `SEMANTICS_UNRESOLVED` unless decisive new evidence changes only the evidence classification.
- [ ] Prepare a human decision table: retain `BLOCKED`; authorize provider-specific clarification **without sending a message in this task**; consider a documented alternative; or review a fully evidenced derived-method proposal. Recommend the least assumptive route supported by evidence, without casting the recommendation as approval.

**Self-check:** Every claimed timestamp meaning is tied to a provider-specific page or statement that covers the exact file family. If no such evidence exists, the dossier says `SEMANTICS_UNRESOLVED`. No code, validator, database, ledger, R05–R08-R01 artifact, r03 package, QGIS state, or Hermes process has changed. All new files hash-verify from their manifest. The task stops after reporting; it does not contact a provider or continue to Stage 2.

## Stage 2 — Human research-method and weather-source decision (locked)

**Owner:** Human designer/research lead. **Input:** accepted R09 dossier and Control Tower review. **Output:** an explicit, versioned decision record identifying the method, source, allowed transformation if any, scope, limitations, and approver.

- [ ] Decide whether to seek provider clarification, assess a documented alternative source, or authorize a narrowly specified source/derivative method supported by direct evidence.
- [ ] Keep weather selection separate from method approval. A decision to investigate a source does not select that source as the analysis input.
- [ ] If route A is proposed, require evidence of the source files' interval semantics and explicit treatment of midnight/day boundaries and radiation data before any conversion becomes eligible.
- [ ] If evidence or approval is absent, record `HUMAN RESEARCH-METHOD DECISION REQUIRED` and stop. Do not add a DatasetSnapshot or mark Week 2 complete.

**Self-check:** The decision is attributable to a human, references exact evidence hashes and file versions, and states what is approved. An agent recommendation, Ladybug parse success, or green test suite is not an approval event.

## Stage 3 — Narrow offline source-path change, only if authorized (locked)

**Owner:** separate Executor task, followed by Control Tower review. **Input:** Stage 2 decision. **Output:** tested source adapter or an explicit finding that existing code already handles the approved source.

- [ ] Inspect the decision against `_epw_metadata`, `acquire_epw_candidates`, `acquire_mandatory_sources`, and `build_m2a03_package`; identify the smallest necessary code change. If no change is needed, record that finding and move to source preflight.
- [ ] For any code change, write a failing offline test first in `tests/test_m2a03_sources.py` or `tests/test_m2a03_analysis_inputs.py` for the approved source behavior, a malformed interval, a missing row, and an unchanged legacy raw file. Run the specific test and confirm it fails for the intended reason.
- [ ] Implement only the approved rule. Preserve raw bytes, derived-parent hashes and transformation version if a derivative was approved; never relax the global chronology validator merely to make the retained files pass.
- [ ] Run the focused suite with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_m2a03_sources.py tests/test_m2a03_analysis_inputs.py`; expected: all collected tests pass.
- [ ] Run the full suite with `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider`; expected: all collected tests pass. Compare counts to the last verified 37 focused / 292 full only as a drift signal, not as a fixed assertion after new tests.
- [ ] Re-verify the R08/R08-R01 hashes and unchanged v5/r03 authority state after the code task.

**Self-check:** Tests exercise the new semantic gate, negative controls and parent lineage, not just parser success. Approved behavior is scoped to the authorized source. A change that alters original R08 bytes, silently normalizes any `Minute=0`, or publishes a snapshot fails review. A new architecture choice returns to the human before implementation.

## Stage 4 — Preflight and one controlled live acquisition (locked)

**Owner:** separate Executor task, with Control Tower before/after verification. **Input:** accepted Stage 3 plus explicit authorization for live source requests. **Output:** a fresh immutable revision whose raw and normalized artifacts have complete provenance, or a truthful `BLOCKED` package.

- [ ] Verify the active v5 StudyArea and typed Artifact; confirm all intended endpoints, licensing, query bounds, page limits, and weather URLs against the human-approved route.
- [ ] Review the actual acquisition order: BAG `pand`, BGT `wegdeel`, BGT `waterdeel`, OSM ways/nodes/POIs, then EPW. Preflight weather locally before dispatching the first PDOK/OSM request so the already-known EPW failure cannot waste a repeat live run.
- [ ] Choose a **new unused** revision suffix after inspecting the output root. Never use the CLI default `r03`; never overwrite a retained package. Record the exact command and source-request budget in the task report before execution.
- [ ] Dispatch the approved run once, recording URL/query, retrieval time, status, response hash/size, licence, source version, CRS/units, and error receipts per source. A lost connection after dispatch is `OUTCOME_UNKNOWN`; reconcile remote/local receipts and authoritative state before any retry.
- [ ] Verify every raw/normalized artifact hash and parent relationship, every DatasetSnapshot's source metadata, completeness/pagination, and explicit data-gap classification. Reload the package twice and compare manifests.

**Self-check:** Successful acquisition reaches `READY_FOR_HUMAN_REVIEW`, not automatic policy approval. If any mandatory source or relationship fails, keep the package `BLOCKED` and publish no partial source snapshot as complete. The source route matches the human decision; v5 and historical packages stay immutable; Hermes still owns 8787.

## Stage 5 — Human analysis-policy freeze (locked)

**Owner:** Human decision with a bounded Executor recording task. **Input:** accepted source bundle and data-gap register. **Output:** versioned policies bound to exact source hashes.

- [ ] Present the observed origin inventory, proposed origin denominator/access rule, raw grocery tags and proposed destination taxonomy, pedestrian network rule, descriptive versus constraint settings, selected weather file/time convention, CRS, units, vertical-reference limitations, source licence, and data gaps.
- [ ] Obtain separate human decisions for origin/denominator, destination taxonomy, pedestrian network, and weather selection. Record exact assumptions and accepted limitations; retain rejected alternatives.
- [ ] Bind each approved policy to the active v5 StudyArea and frozen source/snapshot hashes. A source or geometry change invalidates the dependent decision and requires a new version, not an in-place edit.
- [ ] Keep CADASTRAL, OWNERSHIP, ZONING_COMPLIANCE, and LEGAL_BUILDABILITY claims blocked without a separate approved HumanDecision-backed DesignBoundary.

**Self-check:** All four policies have attributable human decisions, exact source lineage, and visible gaps. No missing observation has become zero. An incomplete policy set remains under review; it does not unlock accessibility or climate analysis.

## Stage 6 — Independent Week 2 acceptance (locked)

**Owner:** Control Tower, independent of the Executor. **Output:** `PASS` or `BLOCKED` audit and the next single packet.

- [ ] Recompute artifact and snapshot hashes from the frozen package; verify ledger replay, v5 pointer, confirmation/activation events, no stale-site substitution, and idempotent double-load.
- [ ] Audit the Week 2 gates in `docs/07_IMPLEMENTATION_PLAN.md` against `docs/06_EVALUATION_FRAMEWORK.md`: `SA-001`–`SA-005`, `DET-001`, `DET-009`, `EVD-001`, `EVD-002`, `EVD-003`, `EVD-006`, `SEC-004`, and `BEN-001`. Map each gate to actual collected tests and runtime evidence; do not infer gate success from total pytest count.
- [ ] Verify CRS/units/vertical reference, valid geometry, query coverage/pagination, source version, licences, weather semantics, policy-human-decision linkage, and preserved data gaps.
- [ ] Confirm formal-claim blocking without DesignBoundary and preserved Hermes 8787 ownership; do not launch or restart unrelated services for this check.
- [ ] Mark Week 2 `PASS` only when every mandatory gate has evidence. Otherwise report `BLOCKED` with the smallest next repair packet. Plan Week 3 separately after a genuine Week 2 PASS.

**Self-check:** The audit distinguishes tested implementation behavior, observed data, and human approval. No `OUTCOME_UNKNOWN`, missing source, or unresolved weather semantics is promoted to `PASS`.

## The one executable prompt to hand to the Executor now

The following packet is the only authorized work from this plan at present. Stages 2–6 are dependency-locked and require fresh packets after each review. The Executor should use GPT-5.6 Luna with Extra High reasoning under `AGENTS.md`; no new Codex task is created by this plan.

### EXECUTION PACKET

**Task ID:** `M2-A03-R09`

**Milestone:** Week 2, M2-A03 analysis-specific input preparation.

**Objective:** Produce an append-only, source-faithful weather-method decision dossier for the three retained Rotterdam EPWs and publicly documented alternatives, without approving a source, changing a validator, or dispatching candidate ZIP/API requests.

**Why this task exists:** R08-R01 proves the integrity of the existing minute experiment, but provider-specific timestamp semantics remain unresolved. The current builder acquires PDOK/OSM before EPW; rerunning it now would repeat live requests while the known weather gate remains unresolved.

**Current repository state:** R08-R01 frozen verifier `PASS`, 53 retained R08 inputs, 69 gates, 63 negative cases; `SEMANTICS_UNRESOLVED`, approved weather sources 0, DatasetSnapshots 0, v5 active, r03 `BLOCKED`. These are the last reviewed values; recheck live state before relying on them. The root is not a Git repository.

**Source-of-truth documents:** `AGENTS.md`, `README.md`, `docs/01_PRODUCT_REQUIREMENTS.md`, `docs/02_SYSTEM_ARCHITECTURE.md`, `docs/03_AGENT_ARCHITECTURE.md`, `docs/05_EVIDENCE_FRAMEWORK.md`, `docs/06_EVALUATION_FRAMEWORK.md`, `docs/07_IMPLEMENTATION_PLAN.md`, `docs/m2-a03-r08-minute-semantics-review.md`, and `docs/m2-a03-r08-r01-review-addendum.md`.

**Relevant implementation files:** Read `src/urban_design/m2a03_sources.py`, `src/urban_design/analysis_inputs.py`, and `scripts/build_m2a03_analysis_inputs.py`. Read the retained R08 source evidence and R08-R01 verifier package. Do not edit these files.

**Required behaviour:** Complete Stages 0 and 1 above. Search public first-party provider/dataset documentation, record each source's exact scope and time convention, and prepare a decision table distinguishing generic EPW rules from file-family-specific semantics. If no direct evidence resolves `Minute=0`, preserve `SEMANTICS_UNRESOLVED`. Treat alternative weather sources as candidates for human review, not selected inputs.

**Scope:** Read-only state and code inspection; public documentation/metadata retrieval; a new `docs/m2-a03-r09-weather-method-decision-docket.md`; and a new immutable `artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r09-weather-method-evidence/` package with content, retrieval log, relative-path/hash/size manifest, and parent references.

**Out of scope:** Candidate ZIP/API requests, provider emails or other outbound messages, `0→60` conversion, climate analysis, PDOK/OSM acquisition, QGIS/Hermes operation, policy selection, DatasetSnapshot publication, new site/boundary, and Week 3 work.

**Architectural constraints:** Keep raw/derived evidence separate. The current `Minute=60` check is an implementation contract, not proof of source semantics. The existing R08/R08-R01 evidence, r03 package, SQLite/ledger, StudyArea, and production files remain immutable.

**Evidence / research constraints:** For every factual claim, record issuer, document URL, version/date, retrieval time, precise supported claim, scope, limitation, and local capture/hash. Distinguish `RESEARCH_FINDING`, `PROJECT_DECISION`, `DATASET_OBSERVATION`, and `INFERENCE`. Do not infer source-file endpoint meaning from generic format ranges, distance, or Ladybug parsing.

**State constraints:** No authoritative state changes. Preserve `SEMANTICS_UNRESOLVED` if direct evidence is absent. Report any live-state drift without repairing it in this task.

**Tool constraints:** Public documentation GETs only; zero candidate weather ZIP/API and zero PDOK/OSM requests. No QGIS, bridge, Hermes 8787, or climate simulation. Disposable verification output must be outside the frozen repair package.

**Allowed changes:** Only the two new R09 paths named in Scope. Existing files may be read but not changed.

**Protected areas:** R05–R08-R01 packages, r03, `.urban_design_runtime/`, all `src/`, `scripts/`, `tests/`, authoritative docs, and unrelated services.

**Implementation expectations:** First verify the baseline and read acquisition order; then collect scoped primary-source evidence; write a concise decision docket; create a deterministic integrity manifest; independently recalculate every new file's size/hash and compare retained-parent hashes. Do not contact providers or solve a method question by code change.

**Validation requirements:** Re-run the retained R08-R01 verifier to a disposable path, check the frozen result hash, verify the new manifest and source locations, and inspect authority state without mutation.

**Tests required:** Positive: retained verifier reports `PASS`; the package-local R09 verifier reports `PASS` for all new manifest entries. Failure: change one byte in a disposable copy of a listed file and confirm the R09 verifier reports `BLOCKED`; likewise remove one declared parent reference and confirm `BLOCKED`. Regression: R08 53/53 and frozen result unchanged. Boundary: generic-format evidence cannot be labeled provider-specific, and zero candidate ZIP/API requests is demonstrable in the request log. No production pytest run is needed because no production code changes.

**Acceptance criteria:** One reproducible R09 dossier and manifest; every timestamp claim properly scoped; A/B decision options and remaining evidence gaps explicit; no source approval or snapshot; all protected hashes and authority state unchanged; request log shows zero forbidden requests.

**Definition of Done:** Deliver the R09 package and final report, then stop for Control Tower review and human method decision. Do not begin Stage 2 or another milestone.

**Failure policy:** If evidence cannot be obtained or is ambiguous, record the attempted public-document scope, leave `SEMANTICS_UNRESOLVED`, report `BLOCKED` for method resolution, and stop. If a verifier/authority invariant changes, stop before writing conclusions and report the mismatch. Do not retry uncertain dispatched requests blindly.

**Documentation update:** Only the new R09 docket. Do not revise authoritative project docs or historical review documents in this task.

**Required final report:** Use the exact sections `TASK STATUS`, `SUMMARY`, `FILES CHANGED`, `IMPLEMENTATION`, `TESTS ADDED`, `TEST RESULTS`, `MANUAL / INTEGRATION TEST RESULTS`, `ASSUMPTIONS`, `DEVIATIONS FROM PACKET`, `RISKS DISCOVERED`, `DOCUMENTATION UPDATED`, `UNRESOLVED ISSUES`, and `RECOMMENDED NEXT STEP`. Use `PASS` only for dossier/integrity completion, and distinguish it from unresolved weather method. Stop after the report.

**Sub-agent task contract:** If delegation is used, each delegated task must state `objective`, `scope`, `relevant_files`, `allowed_changes`, `forbidden_changes`, `acceptance_criteria`, `tests`, and `expected_return`. Internal sub-agents must follow `AGENTS.md` model governance and cannot approve their own output.

## Plan self-review

- [x] The next executable packet covers only R09 evidence collection and is consistent with the unresolved human gate.
- [x] Later stages have explicit unlock conditions and self-checks; none implies that verifier PASS proves weather semantics.
- [x] Existing source order, CLI default revision, protected package paths, and focused test paths were checked against live files.
- [x] No production code step is prescribed before the human method decision; the exact source-specific implementation must be planned from that decision rather than guessed now.
- [x] Git/worktree/commit steps are inapplicable because the current project root has no `.git` repository.
