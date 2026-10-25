# Week 6 CP0 Test Portability Baseline R01

Date: 2026-10-04  
Worktree: `/Users/jackhsieh/Downloads/TUD/Q5/w6-08-editor`  
Branch and starting revision: `wp/w6-integration`, `7ea3b8995795d0222143bbb743edb27b5192aa59`  
Main revision observed in the source checkout: `516bbaa` (`516bbaafa42522e809031f47df4cd35d4dc7e306`)

This record covers only the CP0 test portability repair for the Rotterdam v4 rebuild and the Week 4 R02 integrity verifier. A passing pytest assertion means the test reproduced and classified the recorded state; it does not change the R02 package's historical `BLOCKED` status or establish CP0 acceptance. Root review remains pending.

## Original pre-repair RED baseline (task record)

The original CP0 task record supplied these exact baseline commands and outcomes:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest --collect-only -q -p no:cacheprovider tests/test_site_proposal_rotterdam_v4.py tests/test_week4_repair_integrity.py
```

Task-record result: **16 collected**.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema tests/test_week4_repair_integrity.py::test_r02_archive_remains_intact_and_reports_exact_current_source_drift
```

Task-record result: **1 failed, 1 skipped**. The v4 node failed on a raw PNG byte mismatch at its former comparison on line 224; the PNG was 1240×850 and the exact SVG and geometry hashes matched. The R02 node skipped because this worktree did not contain `.urban_design_runtime/state.sqlite3`. This was test portability and raster-encoding evidence, not a change to the product or historical package gates.

## Changes and boundaries

The v4 test now keeps `boundary_sha256` and `geometry_sha256` exact, requires a byte-identical SVG and exact equality for other immutable rebuild inputs, and validates each PNG as a complete 1240×850 RGBA PNG with valid chunk CRCs, complete zlib data, visible alpha, and decoded pixel variation. It checks the generated proposal and render records against each run's own PNG bytes before normalizing only that raster's checkout-dependent size and SHA fields. Retained parent-image references stay exact.

The R02 test now requires `Q5_READONLY_FIXTURE_ROOT`. It reads the current source root explicitly and verifies the worktree-missing StudyArea GeoJSON against [fixture-manifest.json](../../tests/fixtures/week4_r02_readonly/fixture-manifest.json) (347 bytes; SHA-256 `9a59159505505dbe658ec6667ecfeb9024b868faf6377e7cd91889c763170d32`). It opens the current authority database with SQLite `mode=ro`, creates every disposable copy through `sqlite3.Connection.backup()` under pytest's `tmp_path`, and checks `quick_check`. Current authority values are queried from that disposable database at test time; current ledger and entity counts are not new fixed assertions. Without the explicit root, the test fails with a clear message and is not reported as skipped.

The byte-mutation and missing-parent controls remain in place. No production source or R02/R03/R04 historical package was edited. No official database, service, QGIS process, or listener was written, restarted, or stopped. The existing untracked `.venv` was preserved.

## Fresh verification after repair

Collection used the exact command above: **16 tests collected in 0.09s**.

With the approved current source root explicitly supplied:

```sh
Q5_READONLY_FIXTURE_ROOT=/Users/jackhsieh/Downloads/TUD/Q5/project PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema tests/test_week4_repair_integrity.py::test_r02_archive_remains_intact_and_reports_exact_current_source_drift
```

Result: **2 passed in 11.97s**. In the v4 rebuild, boundary and geometry hashes remained exact. The R02 test verified that the package verifier's dynamic semantic state matched the SQLite backup and that its reported historical/source drift was exact; the package itself remains classified by its verifier result.

The required negative controls ran separately:

```sh
Q5_READONLY_FIXTURE_ROOT=/Users/jackhsieh/Downloads/TUD/Q5/project PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_week4_repair_integrity.py::test_single_byte_mutation_is_blocked tests/test_week4_repair_integrity.py::test_missing_declared_parent_is_blocked
```

Result: **2 passed in 0.27s**. A separate no-root check produced the expected clear pytest failure (`Q5_READONLY_FIXTURE_ROOT is required for R02 current-state verification`) rather than a skip. No full suite was run; CP10 owns that gate.

## Read-only authority snapshot, separate from the test baseline

The supplied read-only capture at `2026-10-04T19:03:08Z` recorded the official database at `/Users/jackhsieh/Downloads/TUD/Q5/project/.urban_design_runtime/state.sqlite3` with main-file SHA-256 `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`. Its disposable SQLite backup was `/private/tmp/q5-w6-closeout-cp0-6f10adby/authority-backup.sqlite3`, SHA-256 `0138554b746017a5f47f5e94e3521426b6576ae24965e61485f1c00546bdca76`, and `quick_check=ok`.

Counts read from that backup were ledger 303; HumanDecision 3; DesignScenario 5, all `PROPOSED`; Artifact 168; DatasetSnapshot 58; and EvidenceCard 27. The active StudyArea was v5, `CONFIRMED_FOR_EXPLORATION`; D2A was effective; WorkspaceRevision was 8, `DRAFT`. These are dated observations from that backup, not permanent expectations in the test. A fresh read-only recheck during this task confirmed the main-file SHA and the same dynamic counts; its separately created disposable backup had a different file hash, so it is not conflated with the 19:03 backup receipt.

At that recorded observation, listeners on ports 8795 (PID 48257) and 5195 (PID 42650) were live; `lsof` identified their cwd/database association. Process arguments could not be inspected because `ps` returned `operation not permitted`. Both processes were left untouched.

## Worktree fixture separation

The two inputs needed from the explicit source root are the changing runtime SQLite database and the pinned 347-byte StudyArea GeoJSON. No other missing fixture was required by these two selected nodes. The full suite was not inventoried, so any unrelated local-only fixture gaps remain unclassified and unvendored; no large data files were copied into the worktree.


## Captured closeout receipts — 2026-10-04

The exclusive evidence package is [out/week6-closeout-baseline-20261004T195527Z](../../out/week6-closeout-baseline-20261004T195527Z/README.md). Its self-excluding file manifest is [manifest.json](../../out/week6-closeout-baseline-20261004T195527Z/manifest.json), SHA-256 `331daeac36d19672a395673fc48ff59b1aca4031ff412b34b1f1f17d78b2b6fe`. Each post-repair receipt JSON contains the exact command and exit code, and links its complete stdout/stderr captures.

The fresh capture completed at `2026-10-04T19:58:14Z`: collection **16 collected** (exit 0); the two exact target nodes **2 passed in 12.05s** (exit 0); byte-mutation and missing-parent controls **2 passed in 0.24s** (exit 0). The no-root control emitted the required `Q5_READONLY_FIXTURE_ROOT is required` diagnostic and returned **exit 1, as expected**. See the four receipt records under `post-repair/` in the package. No full suite was run; CP10 owns that gate. These are focused test results only; root review remains pending and they do not establish CP0 overall PASS.

The raw pre-repair files available at `/private/tmp/q5-w6-closeout-20261004T175417Z/` are retained byte-for-byte under `pre-repair-supplied/`. Their collection log matches 16 collected (exit 0), but their target-node log records **2 failed** (PNG byte mismatch plus a ledger mismatch, 303 versus 285) with exit 1, rather than the original task-recorded **1 failed + 1 skipped** result. Those files have no paired invocation receipt, so they are not treated as proof of the stated 1+1 capture; both records are kept distinct and the mismatch remains unresolved.

The package contains no SQLite/DB files. The current R02 run used the explicit approved read-only root `/Users/jackhsieh/Downloads/TUD/Q5/project`; disposable database state was generated by the test via SQLite backup API under pytest temporary storage. The worktree HEAD remains `7ea3b8995795d0222143bbb743edb27b5192aa59`; no commit was created.
