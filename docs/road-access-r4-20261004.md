# W6 road access round 4 — execution evidence

Parent: `4b1938eb6f9b6b6500898f07eec1f43aa1824691`.
Worktree: `/Users/jackhsieh/Downloads/TUD/Q5/w6-06-generator`.
Branch: `wp/w6-road-access`. Executor ran directly in this session, without
background agent dispatch or native subagents. No live AI was used.
Commander independent review and Founder acceptance remain separate gates.

## Founder-authorised skeleton change

`formal-dictionary-v6-south-strip-collector` records
`FOUNDER_DECISION_2026-10-04` in `authored_recipe_settings.south_strip_collector`.
Only CENTRAL_COMMON and LINEAR_SPINE add the collector. CONNECTED_GRID retains
its geometry. Existing inputs, constraints, retained footprints, validation
rules, zone boundaries and ledger history are unchanged.

The shared principal-site orientation, rounded to the existing 15-degree grid,
defines a local frame. The southern half of each site's bounding rectangle is
sampled horizontally every 4 m, starting at the southern bound plus collector
half-width and 0.25 m numerical clearance. Sections are clipped to the safe
land domain and obstacle exclusions. The longest continuous section is chosen;
sections tied within 1 micrometre prefer the centre of the southern half, then
southern coordinate and WKB. This identifies the long southern arm from site
geometry rather than from zone labels, preselected buildings or fixed RD
coordinates. It also supplies a deterministic southern collector on rectangle
fixtures without placing an equal-length section against the boundary.

Collector and connectors use approved `road_collector_width_m`. Protection
includes retained footprints buffered 3 m, primary open spaces, water/no-build
polygons and the approved 15 m waterfront band, then an additional road
half-width plus 0.25 m clearance. A typed geometry-only collector exclusion
field carries the resolved waterfront band without changing the old skeleton's
obstacle policy. The collector centreline follows the grid axis; connectors
use the existing deterministic visibility router to avoid obstacles. Both
endpoints attach to width-clear portions of the original network. Routes stay
within land inset by road half-width plus 0.25 m. Failure to obtain either
attachment is BLOCKED rather than publishing a floating collector. Existing
micrometre noding and graph validation remain active.

Fallback rebuild now preserves each original road class, including the new
collector and connectors, instead of relabelling all collector-width roads
CONNECTOR. This changes semantic road IDs where the old rebuild lost classes.
Recipe version, context, collector geometry and output hashes also change as
intended. No existing test assertions or validator thresholds were changed.

Round-3 4.5 m access lanes remain building-led fallback only: targets must
exceed 40 m, complete dictionary profiles are placed and reselected, and lanes
unused by final buildings are pruned. The existing 25% search cap uses the
current skeleton length including the Founder collector. Historical added
length in the comparison table instead uses the before skeleton and includes
the collector and connectors. These are different denominators and purposes.

## Final offline output

Final geometry runs:

- `out/road-access-r4-width-clear-a-20261004/`
- `out/road-access-r4-width-clear-b-20261004/`
- comparison table, source hashes and PNG:
  `out/road-access-r4-width-clear-comparison-20261004/`
- audit and test evidence: `out/road-access-r4-evidence-20261004/`

Both runs use seed 42 and the read-only rehearsal database
`out/formal-dictionary/fifth-rehearsal-db/state.sqlite3`. They create no
Scenario/Artifact/HumanDecision/ledger records. No runtime database is opened.
All five candidates are VALID; the substantive-difference/three-family gate
is READY. Every candidate has all four dictionary types, all five approved
zones receive new GFA, FAR uses the unchanged land denominator, and all detached
building components pass the 40 m road-surface proximity rule.

| Candidate | FAR | Road m | Fallback lanes m | Max access distance m |
|---|---:|---:|---:|---:|
| grid-mixed | 0.757951 | 4872.83 | 0.00 | 36.034904 |
| common-mixed | 0.743333 | 2921.18 | 226.49 | 38.662510 |
| spine-mixed | 0.735016 | 2494.97 | 242.49 | 39.766875 |
| grid-fine | 0.771730 | 5275.91 | 0.00 | 17.292722 |
| common-compact | 0.765776 | 2578.76 | 201.16 | 38.662510 |

The fallback lengths are reduced in common-mixed/compact but are not near zero;
spine needs more than round 3 while now serving Residential. No claim of a
minimum road length or accepted design is made. The comparison's Residential
GFA column measures assigned new GFA in the zone named Residential, separately
from Residential + Tidal Park and floor-use subtotals. Before/r1 are archived
historical statuses, not fresh validation under the current gate. Their 0 m
4.5 m fallback column does not omit r1 full-width added roads: those appear in
the Added m column.

## Tests and audit

Final focused command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_south_strip_collector.py tests/test_generation_skeleton.py tests/test_building_access_lanes.py tests/test_required_placement_types.py
```

Fresh result: **18 passed in 2.77 s**, exit 0. Log: `terminal-focused.log`.
The collector regressions check replay, rotation to large RD coordinates,
grid alignment, complete-width site/retained/waterfront/primary-space
clearance, both endpoint attachments and class/width retention after rebuild.

Final full foreground command:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider
```

Fresh complete foreground result: **5 failed, 1,640 passed, 3 skipped,
12 warnings in 1,621.87 s (27:01)**, exit 1. Log:
`full-pytest-terminal.log`. Failures are exactly the five authorised known
worktree-only failures:

- `test_m2a02_plugin_launcher.py::test_project_has_an_unambiguous_visible_identity`
- `test_m2a02_r02_georeference.py::test_project_xml_has_finite_anchor_extent_context_and_correct_new_draft_path`
- `test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema`
- `test_week4_r03_integrity.py::test_r03_archive_stays_intact_and_r04_source_parent_drift_is_explicit`
- `test_week4_r04_amendments_r02.py::test_self_test_returns_status_and_runs_fault_cases_when_upstream_is_valid`

All four additional round-3 failures pass in this fresh full run:
`test_formal_diversity_replay_and_land_far`,
`test_large_rd_coordinate_rotation_preserves_dictionary_semantics`,
`test_all_candidates_have_road_access`, and
`test_job_runs_real_pipeline_and_reuses_proposed_ids`.
No assertions were weakened, fixtures substituted or expected hashes hardcoded.
The first test still reverses recipe order and compares exact candidate hashes;
the workflow test still checks actual publication, reuse, no HumanDecision and
tampering rejection in a self-built temporary database.

Final source/database hashes are rechecked after the full suite in
`final-verification.json` against `source-hashes-final.json`. The five known
failures are not represented as a wholly passing pytest run. The authorised
round-4 test boundary is satisfied; independent Commander review and Founder
acceptance are still pending. The near-zero fallback expectation is unmet
(201–242 m on non-grid families) and remains explicitly disclosed.

The independent audit recomputes worst detached-component road distance,
collector buffers versus retained +3 m, primary spaces, the resolved waterfront
band and land extent; verifies node/edge endpoint agreement and graph reach to
original roads; and compares exact candidate `result_hash` values across the
two runs. It uses the approved rehearsal copy read only and hashes it before
and after. Final receipt: `audit-width-clear.json`: **PASS**, exit 0, all five
candidate hashes equal, 126 new building records passing, database bytes
unchanged (`992ad023d26bbfeffce78ef0e7dd0054f123c3bc5819520ead58be648ff9bd18`).
The final QGIS plot also exited 0; its PNG was inspected.

Generation command (run twice with separate a/b output directories):

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/run_formal_dictionary_generation.py --database out/formal-dictionary/fifth-rehearsal-db/state.sqlite3 --dry-run --output out/road-access-r4-width-clear-a-20261004
```

Audit and plot commands:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/audit_road_access_r4.py --first out/road-access-r4-width-clear-a-20261004/report.json --second out/road-access-r4-width-clear-b-20261004/report.json --database out/formal-dictionary/fifth-rehearsal-db/state.sqlite3 --output out/road-access-r4-evidence-20261004/audit-width-clear.json
MPLCONFIGDIR=/private/tmp/w6-road-access-r4-mpl XDG_CACHE_HOME=/private/tmp/w6-road-access-r4-cache /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/compare_road_access_r4.py --before out/road-access-before-20261003/report.json --r1 out/road-access-final-20261003/report.json --r3 out/road-access-r3-final-20261003/report.json --r4 out/road-access-r4-width-clear-a-20261004/report.json --output out/road-access-r4-width-clear-comparison-20261004
```

## Preserved attempts and corrections

1. Initial real-site runs `r4-first` and `r4-replay` both achieved READY/5 VALID
   with equal candidate hashes. Their comparison is preserved under
   `r4-comparison`. These precede the equal-length-section tie rule and road
   class preservation changes and are not final source verification.
2. Initial focused access test was deliberately interrupted, exit 2, after
   254.98 s with no completed tests while the rectangle tie rule was corrected.
   The corrected access test passed 1/1 in 149.74 s (`access-focused.log`).
3. `r4-final`, then `r4-terminal-a/b`, and `r4-terminal-comparison` are retained
   pre-width-clear routing outputs. The terminal pair replay hashes match.
   First audit (`audit.json`) correctly failed the additional complete road
   width containment check: the eastern connector's centreline was inside
   land but its buffer followed the boundary outside. This was corrected in
   routing, not by weakening the audit or clipping away its failed geometry.
4. The first full foreground pytest was deliberately interrupted, exit 2,
   at **289 passed, 6 warnings in 248.65 s**, while that routing correction
   was implemented. Its preserved log is `full-pytest.log`; it is not full
   acceptance evidence. A fresh full run uses `full-pytest-terminal.log`.
5. Focused geometry suites passed 17/17 in 2.69 s and 2.65 s before the extra
   class-retention regression; final suite passes 18/18. These are preserved
   as `geometry-focused.log`, `width-clear-focused.log`, `terminal-focused.log`.
   The first isolated collector test also passed 1/1 in 0.10 s with
   `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_south_strip_collector.py`.
6. A read-only process inventory command (`ps`) was rejected by the sandbox;
   it was not retried or bypassed. Only this executor's pytest was interrupted.
7. QGIS plotting exited 0 and produced PNGs, while emitting bundled
   `Cannot find proj.db` warnings. The plot performs no CRS reprojection;
   coordinates are already EPSG:28992. Temporary font/cache paths are retained.
8. One documentation patch failed its context match and made no changes;
   the corrected patch was applied after inspecting the actual lines.
9. Read-only collection using `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest --collect-only -q -p no:cacheprovider`
   completed with 1,648 tests collected in 4.39 s, exit 0. This mapped full-run
   progress to test IDs; it is not a substitute for executing the suite.
10. The first final-receipt assertion rejected a progress count of 1,650:
    two isolated `E` lines in pytest's failure explanations had been mistaken
    for progress markers. Restricting parsing to the section before FAILURES
    produced the correct 1,648 count and saved `final-verification.json`.
    Actual pytest assertions, results and logs were unchanged. The rejected
    receipt attempt created no output file.

No files/directories were deleted, no cleanup/reset was performed, no shared
service or port was touched, no dependencies were added/upgraded/downloaded,
no UI/weather/validator/ledger/StudyArea changes were made, and no credentials
or decision passphrases were read/requested/generated. All offline attempts
and their output directories are retained.

## Git boundary

One attempt to stage only the seven authored source/script/test/document files
on the verified `wp/w6-road-access` branch failed, exit 128:

```text
fatal: Unable to create '/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-06-generator/index.lock': Operation not permitted
```

No commit was attempted after this sandbox rejection. Changes remain
uncommitted; HEAD remains `4b1938eb6f9b6b6500898f07eec1f43aa1824691`.
No permission bypass or Git cleanup was attempted. No push, merge, rebase,
reset, clean or branch deletion is authorised or performed.

## Founder-accepted tradeoff (recorded by Grok after the worker snapshot)

Founder 2026-10-04 accepted the disclosed tradeoff. Authored recipe settings
now carry `ACCEPTED_TRADEOFF_FOUNDER_2026-10-04`: fallback lanes 201–242 m,
roads +64–80%, open space −6.4 percentage points. The label is stored beside
the recipe and is not a skeleton method parameter, so it does not change
placement hashes. Lane simplification remains later work. Merge, restart, and
regeneration on the formal database stay with the Founder.
