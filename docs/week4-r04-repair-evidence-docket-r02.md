# Week 4 R04-R02 Amendment Verifier Repair Evidence Docket

**Task:** `WEEK4-R04-AMENDMENT-VERIFIER-R02`  
**Task status:** `PASS` for the versioned verifier repair  
**R04 narrow repair status:** `PASS` (unchanged)  
**Overall Week 4 status:** `INCOMPLETE`  
**Append-only evidence package:** [`artifacts/week4-repair-r04-amendments-r02/`](../artifacts/week4-repair-r04-amendments-r02/)

## Baseline and preserved defect

Before this repair, the normal R04 amendment-aware verifier passed with 25 package files and 133 parent references. The frozen base manifest SHA-256 is `52927a6de6c05099b3ba063e8ea93805fb7e28378092fe85a78a0b1bc133f8a8`; the R01 supplemental manifest SHA-256 is `5ca2d0ffa73e50fd01069dbdaa36a2acb43fb92e0796ce55c1f82c580bae99c5`.

The legacy `scripts/verify_week4_repair_r04_amendments.py --self-test` reproduced a `FileNotFoundError` and exited 1. In `_fault_tests`, its byte-mutation branch copies the public R01 docket to `byte_clone_root / DOCKET_AMENDMENT_DOC` without first creating the clone's `docs/` directory (line 259). It also calls the old verifier with the original project root, so the disposable public-docket copy is not the copy being checked. Neither the legacy verifier nor its R01 append helper was modified. Their baseline SHA-256 values are recorded in `verification-results.json`.

## R02 repair

The replacement is the versioned `scripts/verify_week4_repair_r04_amendments_r02.py`. Its self-test creates an independent temporary project root for every case, clones the R04 package and the declared external parent files, copies the public R01 docket into that clone, and passes the cloned root to the R01 verifier. A dedicated public-docket-copy mutation case proves that the verifier reads the clone's copy: the valid clone passes, while changing only that public copy blocks verification.

The R02 CLI self-test completed with JSON status `PASS`, exit code 0, and no traceback. Its cases were:

| Disposable case | Expected and observed status |
|---|---|
| Valid R04/R01 clone | `PASS` |
| One-byte package mutation | `BLOCKED` |
| Missing package file | `BLOCKED` |
| Missing declared external parent | `BLOCKED` |
| Mutated cloned public docket | `BLOCKED` |

The focused pytest command `./.venv/bin/python -m pytest -q tests/test_week4_r04_amendments_r02.py tests/test_week4_r04_integrity.py` passed **5 tests**. The full `./.venv/bin/python -m pytest -q` suite passed **452 tests**, with 7 existing deprecation warnings, in 246.10 seconds.

## Preservation and remaining gates

The R04 base and R01 manifest files, all 25 R04/R01 package files, both legacy verifier/helper files, and the authoritative `.urban_design_runtime/state.sqlite3` retained their pre-repair SHA-256 values. The R04 gate record remains `week4_overall_status: INCOMPLETE`; no state, ledger, StudyArea, weather data, or approval was changed.

R04's bounded repair remains `PASS`. This verifier repair does not complete the QGIS GUI gate, 2 km/10 km Syntax, live AI, or the formal Site/DesignBoundary decision. Those remain `UNVERIFIED`, `BLOCKED`, or `PENDING` as recorded by the R04 gate map.

## Verification records

See `verification-results.json`, `test-results.json`, and `integrity-manifest.json` in the append-only R02 evidence package. The R02 manifest excludes itself and records file sizes, SHA-256 values, and parent paths/hashes.
