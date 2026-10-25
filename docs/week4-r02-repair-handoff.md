# Week 4 R02 Executor Handoff

**Task:** M2-A03-R02  
**Package:** [`artifacts/week4-repair-r02/`](../artifacts/week4-repair-r02/)  
**Executor status:** `EXECUTOR_SELF_CHECKED`  
**Acceptance:** pending independent Sol/Astra review

R02 repairs the workspace source-lineage path, draft validation, platform/API port separation, browser flow, bounded critic adapter, and syntax calculation/figure lineage. The package records the tested state and its limitations; this is not a Week 4 acceptance or approval of source coverage, a design policy, or a weather method.

## Authority and source state

The active StudyArea is Rotterdam M4H v5, revision 1, `CONFIRMED_FOR_EXPLORATION`, with geometry hash `sha256:3dedb804fa4f07f4c9570bcc64e68c8d576c03340455ab35fd4963bca52aa4f5`. The project remains at revision 6. The current workspace remains revision 2 / `DRAFT`; ledger count and maximum sequence are 183; there are 52 DatasetSnapshots and 109 Artifacts. No formal Site or DesignBoundary approval is inferred.

R02 used the retained spatial-r01 OSM road source: OSM contributors via Overpass, ODbL 1.0, retrieved 2026-09-21, with source package manifest hash `c1456e51d34402fd280dfee10ef28fd34f53195955d990a07be79a7185f85c09`. No new OSM, PDOK, weather, or model request was made. No DatasetSnapshot was published.

The SQLite main-file hash differs from the older R02 baseline capture (`b524535a…`) and is captured again as `6a89b1d3…`. The semantic state listed above matches the prior capture; the database is mutable runtime state and is not treated as an immutable archive. The R02 verifier checks both the captured hash and current semantic references separately.

## Implemented and tested behavior

- Workspace selection resolves to spatial-r01 feature, Artifact, DatasetSnapshot, project, and active StudyArea lineage. Invalid references fail closed.
- Workspace revisions remain draft-only until a human decision; historical revisions are retained.
- Platform API uses 8789. The QGIS bridge port 8788 is not occupied by the platform API. Hermes PID 12407 remains the 8787 listener. A current HTTP response from Hermes could not be obtained in this sandbox, so current page/API availability is unverified.
- A real Chromium run persisted and reloaded two revisions using a disposable SQLite copy. It saved a non-default polygon and editable BAG/OSM feature dispositions. The authoritative live database hash was unchanged.
- No verified same-revision Evidence Card bundle is available. The package carries an empty Evidence Card set with `BLOCKED_SOURCE_RESULT_ALIGNMENT`; the critic rejects unresolvable IDs and no live model call was made.
- The 800 m angular integration/choice outputs were calculated for the scoped roads and linked to spatial-r01 source features. The study-area-only network has no complete route-graph acquisition envelope or radius-specific stability evidence, so both outputs remain `BLOCKED_COVERAGE_EVIDENCE_ABSENT`. The 2 km and 10 km layers are explicitly uncomputed and contain no values. The figure is an exploratory artifact, not a validated Rotterdam result.

## Gate map

| Gate | Status | Evidence and limitation |
|---|---|---|
| CP4-0 | `PARTIAL` | Baseline and protected inputs rechecked; SQLite semantic state matches, but its byte hash changed since baseline. Current Hermes HTTP was not verifiable. |
| CP4-1a | `PARTIAL` | Syntax calculations and known-answer/fork/cycle/radius tests pass; regional source coverage is not established. |
| CP4-1b | `PARTIAL` | Browser editing geometry persisted and reloaded in a disposable database; QGIS GUI runtime was not tested. |
| CP4-2 | `PASS` | Typed source-linked workspace behavior and fail-closed cases pass; browser round-trip passed against disposable SQLite. |
| CP4-3 | `PARTIAL` | Chromium flow passed; actual QGIS-to-platform GUI synchronization remains unverified. |
| CP4-4 | `PASS` | Draft save/reload is consistent; no unapproved constraint is promoted. |
| CP4-5 | `BLOCKED` | Current site Evidence Cards and source-result-aligned metrics are unavailable. |
| CP4-6 | `PARTIAL` | 800 m values/figure are source-linked but coverage-blocked; 2 km and 10 km were not computed. |
| CP4-7 | `BLOCKED` | No live credential and no verified Evidence Card bundle; only fake-transport tests are in scope. |
| CP4-8 | `PARTIAL` | R02 package and regression evidence are ready for independent review; integrated live QGIS, live AI, and regional Syntax gates remain blocked. |

## Review boundaries and next step

Before independent review, the result remains `EXECUTOR_SELF_CHECKED`. Synthetic Week 5 fixture work may be separately considered. Source-dependent design work, live QGIS synchronization, source-complete 10 km Syntax, and live AI remain blocked. The next step is independent review of the package, verifier, test results, and gate map; do not infer an overall Week 4 `PASS` from this handoff.

## Verification run

The full backend suite passed **408 tests** with 8 deprecation warnings. Frontend Vitest passed **3 tests**; the production build succeeded with Vite's large-chunk advisory. The R02 integrity suite passed **7 tests**, including one valid package and six fail-closed mutations. The extended package verifier passes with **31 package files and 165 parent-file checks**. The appended [`checkpoint-self-check.json`](../artifacts/week4-repair-r02/checkpoint-self-check.json) records each CP-R0–CP-R6 focused command/output, state and ledger counts, input/response examples, protected hashes, and remaining dependencies; raw focused and full-suite logs are under the package's `test-logs/` directory. The retained Chromium run passed against disposable SQLite and recorded no outbound model, geodata, or weather requests.

The older baseline listed 283 protected paths. All 280 non-runtime files still match their recorded hashes. The three mutable SQLite main/WAL/SHM files differ from their older captured hashes; the current SQLite main hash matches the R02 capture, and live semantic checks still report v5 active, workspace rev 2 DRAFT, ledger 183, 52 snapshots, and 109 Artifacts. These byte differences are recorded as runtime-state drift, not as immutable archive corruption.
