# Week 2 Spatial Input Gate Implementation Plan

> **2026-09-22 SUPERSEDED AS CURRENT EXECUTION ENTRY：** 原文完整保留作歷史計畫。新的學期排程與產品範圍使用 [整體中文藍圖](2026-09-22-semester-project-blueprint-zh.md) 及 [Week 4 詳細計畫](2026-09-22-week4-platform-site-analysis-zh.md)。舊 spatial gate 的來源／政策保護要求仍有效；新需求不自動批准任何舊政策。下方 prompt 不再作為目前任務的預設入口。

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to execute this plan phase by phase. Stop at
> every checkpoint and validate its evidence before continuing. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete and independently accept the Rotterdam M4H Week 2 spatial
input package so Weeks 3–4 can proceed, while preserving the unresolved weather
method as a separate gate that blocks Week 6 only.

**Architecture:** Replace the current atomic PDOK/OSM/EPW acquisition path with
two explicit tracks. The spatial track acquires and freezes StudyArea-linked
PDOK and OSM data, then records three human-approved accessibility policies.
The weather track retains R08–R09-R01 evidence and remains blocked without
affecting spatial acceptance. Historical combined APIs remain replayable.

**Tech Stack:** Python 3.11+, Pydantic, SQLite append-only ledger, pytest,
PDOK OGC API, OSM Overpass, pyproj, Shapely, SHA-256 manifests.

**Planning status:** This document is execution-ready planning material. Its
creation does not authorize or claim completion of CP0–CP8, source acquisition,
policy approval, SQLite mutation or Week 2 spatial acceptance.

---

## Operating boundary

The active exploration envelope is
`study-area-rotterdam-m4h-pilot-project-v5`. StudyArea confirmation authorizes
exploration only. It does not create a formal Site or DesignBoundary and cannot
support cadastral, ownership, zoning-compliance or legal-buildability claims.

The target valid intermediate state is:

```text
WEEK_2_SPATIAL_GATE: PASS
WEATHER_METHOD_GATE: BLOCKED / SEMANTICS_UNRESOLVED
WEEK_3_ENTRY: AUTHORIZED
WEEK_6_ENTRY: BLOCKED
```

The project root is not a Git repository. Do not invent branches, commits or
worktrees. Every operational output uses a new immutable package directory,
SHA-256 manifest, parent references and append-only ledger events.

## File map

| Responsibility | Files |
| --- | --- |
| Spatial source acquisition | `src/urban_design/m2a03_sources.py`, `tests/test_m2a03_sources.py` |
| Spatial package build/load | `src/urban_design/analysis_inputs.py`, `scripts/build_m2a03_spatial_inputs.py`, `tests/test_m2a03_analysis_inputs.py` |
| Human policy freeze | `src/urban_design/spatial_input_policy.py`, `scripts/approve_m2a03_spatial_inputs.py`, `tests/test_m2a03_spatial_policy.py` |
| Authoritative contracts | `README.md`, `docs/02_SYSTEM_ARCHITECTURE.md`, `docs/06_EVALUATION_FRAMEWORK.md`, `docs/07_IMPLEMENTATION_PLAN.md` |
| Historical combined replay | `acquire_mandatory_sources()`, `build_m2a03_package()`, `scripts/build_m2a03_analysis_inputs.py` |
| Protected evidence | R05–R09-R01 directories and `run-study-area-rotterdam-m4h-pilot-project-v5-r03/` |

## Public interfaces

Add these interfaces without removing historical APIs:

```python
@dataclass(frozen=True)
class SpatialSourceBundle:
    artifacts: tuple[dict[str, Any], ...]
    normalized_artifacts: tuple[dict[str, Any], ...]
    snapshots: tuple[dict[str, Any], ...]
    request_records: tuple[dict[str, Any], ...]
    network_manifest: dict[str, Any]
    grocery_inventory: dict[str, Any]
    origin_inventory: dict[str, Any]


def acquire_spatial_sources(
    *,
    package_root: Path,
    project_id: str,
    created_at: str,
    observed_bbox: Sequence[float],
    fetcher: FetchCallable | None = None,
    package_namespace: str | None = None,
) -> SpatialSourceBundle: ...


def build_m2a03_spatial_package(
    database: str | Path,
    output_root: str | Path,
    *,
    project_id: str,
    study_area_id: str | None = None,
    package_revision: str,
    append_ledger: bool = True,
    fetcher: Any | None = None,
) -> Path: ...


def load_m2a03_spatial_package(package_root: str | Path) -> dict[str, Any]: ...


def freeze_m2a03_spatial_policies(
    database: str | Path,
    spatial_package_root: str | Path,
    output_root: str | Path,
    *,
    actor: str,
    reason: str,
    origin_ids: Sequence[str],
    destination_tags: Sequence[str],
    network_policy: Mapping[str, Any],
) -> Path: ...
```

The acquisition decision record has this contract:

```json
{
  "schema_version": "m2-a03-spatial-input-decision-package-v1",
  "track": "SPATIAL_INPUT",
  "status": "READY_FOR_HUMAN_REVIEW",
  "weather_gate": {
    "status": "SEMANTICS_UNRESOLVED",
    "required_for": "WEEK_6",
    "blocks_spatial_track": false,
    "evidence_refs": ["R09", "R09-R01"]
  }
}
```

The accepted policy package has this contract:

```json
{
  "schema_version": "m2-a03-spatial-input-acceptance-v1",
  "status": "ACCEPTED_FOR_WEEK3",
  "spatial_package_id": "...",
  "study_area_id": "study-area-rotterdam-m4h-pilot-project-v5",
  "policy_decision_ids": {
    "origin_denominator": "...",
    "destination_taxonomy": "...",
    "pedestrian_network": "..."
  },
  "weather_gate_status": "SEMANTICS_UNRESOLVED"
}
```

## Phase 0 — Baseline and preservation

**Files:** read-only project documents, SQLite and retained evidence. Disposable
verifier output goes under `/private/tmp`.

- [ ] Read `AGENTS.md`, `README.md`, authoritative documents 01, 02, 03, 05,
  06 and 07, plus R08, R08-R01, R09 and R09-R01 records.
- [ ] Run R08-R01 verifier with `.venv/bin/python` to a new disposable output.
- [ ] Run R09-R01 verifier with `--authority-db
  .urban_design_runtime/state.sqlite3`; require archival `PASS` and authority
  `MATCH`.
- [ ] Recompute R08, R09, R09-R01 and r03 manifest entries without writing to
  those packages.
- [ ] Query live SQLite for active StudyArea, v4 status, ledger count, spatial
  DatasetSnapshot count and weather DatasetSnapshot count.
- [ ] Check the existing port 8787 listener and GET `/`; do not restart or kill
  the process.
- [ ] Record a one-run request budget: three allowlisted PDOK collections with
  bounded pagination, one bounded Overpass dispatch and zero weather requests.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
  artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-r01-verifier-repair-20260919T172048Z/r08-r01-verify.py \
  --output /private/tmp/m2-a03-cp0-r08-r01/result.json
```

**Checkpoint CP0 — baseline:** Pass only if v5 is active and
`CONFIRMED_FOR_EXPLORATION`, v4 is `SUPERSEDED`, retained evidence verifies,
r03 is immutable and blocked, approved weather sources and DatasetSnapshots are
zero, Hermes owns 8787, and the report uses actual SQLite values. Any mismatch
is `BLOCKED_BASELINE_DRIFT`.

## Phase 1 — Reconcile the authoritative Week 2 boundary

**Files:**

- Modify: `README.md`
- Modify: `docs/02_SYSTEM_ARCHITECTURE.md`
- Modify: `docs/06_EVALUATION_FRAMEWORK.md`
- Modify: `docs/07_IMPLEMENTATION_PLAN.md`
- Create: this plan
- Create: `docs/superpowers/plans/2026-09-21-eight-week-project-blueprint.md`
- Modify only by notice: `docs/superpowers/plans/2026-09-20-m2-a03-input-freeze.md`

- [ ] Define separate spatial and weather goals, deliverables and acceptance
  states.
- [ ] State that spatial `PASS` unlocks Weeks 3–4.
- [ ] State that weather `PASS` is required before Week 6.
- [ ] Preserve the old plan and add only a superseded-plan notice.
- [ ] Search for stale claims that weather is required for Week 3 or Week 4.

Run:

```bash
rg -n "Week 2|Week 3|Week 4|Week 6|weather|spatial" \
  README.md docs/02_SYSTEM_ARCHITECTURE.md docs/06_EVALUATION_FRAMEWORK.md \
  docs/07_IMPLEMENTATION_PLAN.md
```

**Checkpoint CP1 — document consistency:** Every remaining combined-gate
statement is explicitly historical. No authoritative document claims that
unresolved weather blocks Week 3 accessibility or Week 4 morphology.

## Phase 2 — Split spatial source acquisition with TDD

**Files:**

- Modify: `src/urban_design/m2a03_sources.py`
- Modify: `tests/test_m2a03_sources.py`

- [ ] Write tests that import `SpatialSourceBundle` and
  `acquire_spatial_sources()` and assert only BAG `pand`, BGT `wegdeel`, BGT
  `waterdeel` and bounded OSM are requested.
- [ ] Run those tests and observe failure because the interface is absent.
- [ ] Add the frozen dataclass and extract the existing PDOK/OSM sequence.
- [ ] Preserve receipts for success, validation failure, transport failure and
  not-attempted sources.
- [ ] Keep `acquire_mandatory_sources()` as the combined compatibility path.
- [ ] Add failures for duplicate/pagination faults, malformed OSM geometry,
  incomplete OSM responses and staging rollback.
- [ ] Add a fetcher that raises for `.zip`; prove spatial acquisition never
  requests or parses EPW.

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q \
  -p no:cacheprovider tests/test_m2a03_sources.py
```

**Checkpoint CP2 — source separation:** The source suite passes; an offline
spatial fixture succeeds with a `.zip`-rejecting fetcher; R08–R09-R01 hashes are
unchanged.

## Phase 3 — Build the immutable spatial package

**Files:**

- Modify: `src/urban_design/analysis_inputs.py`
- Create: `scripts/build_m2a03_spatial_inputs.py`
- Modify: `tests/test_m2a03_analysis_inputs.py`
- Modify: `tests/test_m2a03_sources.py`

- [ ] Write failing tests for `build_m2a03_spatial_package()` and
  `load_m2a03_spatial_package()`.
- [ ] Require the persisted active StudyArea, confirmation/activation events,
  projected CRS, units and matching hashes.
- [ ] Call only `acquire_spatial_sources()`.
- [ ] Publish raw/normalized artifacts, snapshots, receipts, envelope,
  CRS/unit/vertical-reference manifest, inventories, proposed policies, data
  gaps and informational weather reference.
- [ ] Exclude EPW, weather DatasetSnapshots and weather policy.
- [ ] Keep filesystem publication and SQLite mutation atomic and retryable.
- [ ] Require an explicit unused revision in the new CLI.
- [ ] Keep `build_m2a03_package()` unchanged for historical replay.
- [ ] Verify mutation, missing parent, stale StudyArea and invalid CRS block
  loading; duplicate load creates no second snapshot set.
- [ ] Verify failed publication never deletes a peer package and emits no
  accessibility or climate result.

**Checkpoint CP3 — package integrity:** Focused tests pass. Disposable byte
mutation and missing-parent controls return `BLOCKED`. Historical packages and
production authority remain unchanged.

## Phase 4 — Implement human policy freeze

**Files:**

- Create: `src/urban_design/spatial_input_policy.py`
- Create: `scripts/approve_m2a03_spatial_inputs.py`
- Create: `tests/test_m2a03_spatial_policy.py`

- [ ] Write failing tests for exact origin subset, observed destination tags,
  explicit network rules, stale source/StudyArea hashes and conflicting replay.
- [ ] Represent each policy as a typed `ParameterDefinition` with
  `source_type=PROJECT_DECISION`, source refs and effective version.
- [ ] Bind one typed `HumanDecision` and one approval ledger event to each
  parameter.
- [ ] Reject empty origins/tags, unobserved values and conflicting duplicate
  decisions.
- [ ] Require exclusion of `foot=no`, `access=no`, `access=private`; preserve
  conditional/ambiguous access as a limitation.
- [ ] Generate a decision packet with observed counts, IDs, tag distribution,
  limitations and concrete options. Do not select for the human.
- [ ] Publish one immutable acceptance package that references the source
  package and never mutates it.

**Checkpoint CP4 — human authority:** All three decisions identify the human
actor and reason, reference exact source/StudyArea hashes, have matching events,
replay from SQLite and yield one `ACCEPTED_FOR_WEEK3` package. Weather is absent
from the decision set.

## Phase 5 — Offline regression and red-team checks

Run focused and full suites:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q \
  -p no:cacheprovider tests/test_m2a03_sources.py \
  tests/test_m2a03_analysis_inputs.py tests/test_m2a03_spatial_policy.py

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q \
  -p no:cacheprovider
```

- [ ] Inject an EPW failure and prove the spatial package can pass.
- [ ] Inject PDOK and OSM failures and prove the package blocks atomically.
- [ ] Keep empty observations distinct from unavailable observations.
- [ ] Reject unobserved origin IDs and grocery tags.
- [ ] Reject source and StudyArea hash drift.
- [ ] Replay without live requests.
- [ ] Prevent duplicate logical snapshots.
- [ ] Verify no missing value becomes zero.
- [ ] Keep formal claims blocked without DesignBoundary approval.

**Checkpoint CP5 — implementation readiness:** All collected tests pass with
observed counts. Weather evidence and r03 remain byte-identical.

## Phase 6 — One controlled live spatial acquisition

The user authorized one complete spatial run after CP0–CP5 pass.

- [ ] Recheck endpoint URLs, licences, envelope and request limits.
- [ ] Choose an unused spatial revision and persist the exact command and
  request budget before dispatch.
- [ ] Execute complete PDOK pagination and one bounded Overpass dispatch.
- [ ] Make zero weather ZIP/API requests.
- [ ] If connection state becomes uncertain after dispatch, record
  `OUTCOME_UNKNOWN`, reconcile receipts and SQLite, and do not retry blindly.
- [ ] Recompute artifact/snapshot hashes and load the package twice.
- [ ] Confirm SQLite contains only expected spatial Artifacts,
  DatasetSnapshots and observation events.

**Checkpoint CP6 — live source package:** Status is
`READY_FOR_HUMAN_REVIEW`; receipts and lineage validate; gaps stay visible; no
weather request occurred.

## Phase 7 — Human policy decision and acceptance

- [ ] Generate the decision packet from the live package.
- [ ] Present origin, destination and network options with counts and limits.
- [ ] Obtain the human's explicit three choices and reason.
- [ ] Run `scripts/approve_m2a03_spatial_inputs.py` with those exact values.
- [ ] Validate the three typed records, decisions and ledger events.
- [ ] Publish and reload the immutable acceptance package.
- [ ] Verify Week 3 authorization passes and Week 6 remains blocked.

**Checkpoint CP7 — Week 2 spatial acceptance:** v5 remains active; all spatial
snapshots have provenance; all three policies have human decisions; the package
reloads without drift; status is `ACCEPTED_FOR_WEEK3`; weather remains
`SEMANTICS_UNRESOLVED`.

## Phase 8 — Independent Control Tower review

- [ ] Independently validate CP0–CP7 evidence and gate mappings.
- [ ] Replay SQLite and ledger state.
- [ ] Recompute snapshot, artifact and acceptance-package hashes.
- [ ] Confirm no EPW, climate run, formal Site or DesignBoundary claim exists.
- [ ] Recheck protected packages and Hermes ownership.
- [ ] Report exact observed state:

```text
WEEK_2_SPATIAL_GATE: PASS | BLOCKED | OUTCOME_UNKNOWN
WEATHER_METHOD_GATE: BLOCKED / SEMANTICS_UNRESOLVED
WEEK_3_ENTRY: AUTHORIZED only when spatial gate is PASS
WEEK_6_ENTRY: BLOCKED until weather gate is PASS
```

**Checkpoint CP8 — independent acceptance:** Report `PASS` only when an
independent reviewer reproduces every gate from persisted evidence. Any failed
integrity, authority, request-accounting or preservation check produces
`BLOCKED` or `OUTCOME_UNKNOWN` and prevents the Week 3 authorization claim.

## Executor prompt

```text
Use superpowers:executing-plans.

Execute:
docs/superpowers/plans/2026-09-21-week2-spatial-input-gate.md

Objective:
Complete the Week 2 Spatial Input Gate for the active Rotterdam M4H StudyArea
v5. Split PDOK/OSM spatial acquisition from the weather method, publish one
validated spatial source package, obtain and record the three required human
policy decisions, and independently verify ACCEPTED_FOR_WEEK3.

Authorization:
You are authorized to modify the files named in the plan, run offline tests,
make one controlled live PDOK/OSM acquisition after offline checkpoints pass,
write the resulting spatial Artifacts/DatasetSnapshots and ledger events, and
create the append-only spatial acceptance package.

Required checkpoints:
Stop and self-check at CP0 through CP7. Do not advance after a failed, BLOCKED,
or OUTCOME_UNKNOWN checkpoint. At CP7, present the observed policy decision
packet to the human and obtain explicit choices before recording HumanDecision
data.

Protected state:
Do not modify R05–R09-R01 evidence, the blocked r03 package, StudyArea v5
geometry, superseded v4, rejected site proposals, historical ledger events, or
weather bytes. Do not convert Minute=0, relax the EPW validator, select a
weather source, publish a weather DatasetSnapshot, start climate analysis, or
start Week 3 calculations.

External boundaries:
Make zero weather ZIP/API requests. Do not operate QGIS unless baseline
reconciliation proves it is required. Do not kill, restart, or take port 8787
from Hermes. A post-dispatch connection loss is OUTCOME_UNKNOWN and must be
reconciled before any retry.

Testing:
Use TDD for each code phase. Run the focused M2-A03 tests after each task and
the complete pytest suite before live acquisition. Run mutation,
missing-parent, stale-StudyArea, invalid-policy, duplicate-dispatch and
atomic-rollback tests.

Versioning:
The project root is not a Git repository. Do not invent commits or worktree
claims. Use unused revision IDs, immutable package directories, SHA-256
manifests, parent references and append-only ledger events.

Final report:
TASK STATUS
SUMMARY
CHECKPOINT RESULTS
FILES CHANGED
PUBLIC INTERFACES
LIVE REQUEST ACCOUNTING
STATE / LEDGER CHANGES
TEST RESULTS
INTEGRITY RESULTS
HUMAN DECISIONS
WEATHER GATE STATUS
RISKS / LIMITATIONS
RECOMMENDED NEXT STEP

A PASS applies only to WEEK_2_SPATIAL_GATE. Weather must remain BLOCKED /
SEMANTICS_UNRESOLVED unless a separate human-authorized weather task resolves
it.
```

## Self-review record

- Spec coverage: every user-authorized phase, interface and checkpoint is
  mapped above.
- Placeholder scan: no deferred implementation placeholder is used.
- Type consistency: the four public signatures and both package schema names
  match the governing execution specification.
- Historical preservation: combined APIs and protected packages remain
  replay-only parents.
