# W6 road access round 3 execution evidence

Executor scope: local offline generation in `wp/w6-road-access`; no delegation,
live AI, runtime database, UI, weather, validator or human-decision changes.
Commander review and Founder acceptance remain separate.

## Checkout and method

Requested parent: `fd2670523f8ae6a6f7a83784fdd1cbc7eb600460`.
Observed parent: `05dd13bfa9d5f5d0664f0161f461ff3be58a58b7`.
The only difference is the existing `scripts/compare_road_access_r2.py`;
generation source is identical. No checkout, reset or branch mutation was used.

Round 3 restores four dictionary types both in placement and candidate validation.
Candidates use their own trial preferences; recipe ordering and common-compact
anchors no longer transfer cells between candidates. Required type coverage
precedes repeated preferred envelopes in the packing queue.

An experimental intermediate-building search considered complete slab/L
envelopes of at most 1,024 m² within 100 m of a missing approved zone. The
completed real-site run regressed to two VALID candidates, so this experiment
was withdrawn; it is not part of the final code. The existing 4.5 m lane width,
35/15/5 m access halos, 40 m component-footprint proximity rule, 25% original
network budget and final-building pruning remain unchanged. FAR ≥0.70, open
space ≥40%, every approved zone receiving assigned GFA, height/waterfront/
retained constraints and three-family/substantive-difference gates remain active.
Recipe versions advance to `formal-dictionary-v5-independent-access` and
`formal-envelope-program-v5-required-types`.

## Preserved attempts and corrections

1. Strict independent generation: `out/road-access-r3-independent-20261003/`.
   Three candidates VALID; common-mixed and spine-mixed lack Residential GFA.
   Its original comparison is retained under
   `out/road-access-r3-independent-comparison-20261003/`.
2. Two initial read-only target diagnostics failed on local profile rotation
   and floating-point envelope dimensions. The corrected diagnostic script,
   selected-target and all-slab logs are under
   `out/road-access-r3-diagnostics-20261003/`. No production files were edited
   by string-replacement scripts. For each non-grid family, all 59 Residential
   slabs in that archived stage had no direct one-bend route; this is not a
   proof that the zone or a multi-lane solution is impossible.
3. A local-envelope generation was deliberately interrupted (exit 130) after
   focused tests identified a required-type packing regression. It has no
   completed report. Its log remains `local-generation.log`.
4. The earlier focused suite was interrupted: 1 failed, 8 passed, exit 2.
   The earlier full suite was interrupted: 1 failed, 292 passed, exit 2.
   Both exposed `test_formal_diversity_replay_and_land_far`, with common/spine
   missing types and common-compact below FAR. These are partial runs, not
   passing test evidence. Logs are `focused.log` and `full-pytest.log`.
5. The new packing regression first failed because its G2 fixture omitted
   grid spacing/alignment. Those fixture parameters were supplied; the fresh
   required-type/access suite passes 6 tests in 2.50 s. A preserved copy of
   HEAD placement fails the same required-type regression (`EXPECTED_RED`).
   Logs are `required-types-focused.log` and
   `required-types-focused-rerun.log`; the old source is
   `formal_placement_before.py`.
6. The completed experimental run is retained in
   `out/road-access-r3-required-types-20261003/`: two VALID; all non-grid
   candidates miss Residential, common-mixed and common-compact also miss FAR.
   The corresponding full suite was interrupted after 289 passed in 1,016.18 s,
   exit 2, because the failed search experiment was withdrawn. It is incomplete
   evidence; its log remains `full-pytest-final.log`.
7. A read-only 40 m halo diagnostic also found no direct one-bend route for
   the 59 archived Residential slab envelopes in each non-grid family.
   Its completed log is `halo40.log`. Production retains the 35/15/5 m halos;
   the diagnostic did not change the 40 m acceptance rule or generator.

No files or directories were deleted. No shared service was stopped or restarted.
The stopped processes were only this executor's offline generator and pytest
sessions. The first QGIS plotting run exited 0 and produced a PNG, with PROJ
database and non-writable font/cache warnings. Subsequent plots use temporary
cache paths. No CRS reprojection is performed by the comparison script.

## Final verification

Final generation completed with exit 2, status **INCOMPLETE**, two VALID
candidates. All 137 generated building records pass component-footprint
proximity, all five candidates have four dictionary types, all added lengths
are ≤25%, and the largest open-space drop is 0.70702 percentage points.
The final code does not meet the five-VALID or three-valid-family requirements.

| Candidate | Status | FAR | Added m | Added % | Open-space drop points | Missing requirement |
|---|---|---:|---:|---:|---:|---|
| grid-mixed | VALID | 0.757951 | 0.00 | 0.00 | 0.0590 | none |
| common-mixed | FAIL | 0.740964 | 342.65 | 19.28 | 0.7070 | Residential GFA |
| spine-mixed | FAIL | 0.736453 | 125.51 | 9.03 | 0.2667 | Residential GFA |
| grid-fine | VALID | 0.771730 | 0.00 | 0.00 | -0.0432 | none |
| common-compact | FAIL | 0.655452 | 378.94 | 24.99 | -1.8364 | FAR ≥0.70 |

`out/road-access-r3-comparison-20261003/` contains the before/r1/r3 table,
JSON with source hashes and independently recomputed access/lengths, and PNG.
`final-audit.json` independently confirms lane width 4.5 m, at most two
segments, grid alignment and no retained/primary-space surface overlap.
Maximum building proximity is 39.745421 m. Negative open-space drops mean
increases. The lane budget is a search cap; these are achieved lengths of
failed/valid proposals, not a proven minimum for a five-VALID solution.
Common/spine still have unused budget but the bounded building trial search
does not reach Residential. Compact spends nearly all its budget while its
packing falls below FAR; the earlier strict independent attempt did better
(three VALID), so these results do not establish geometric impossibility.

The complete terminal foreground pytest finished with exit 1:
**9 failed, 1,634 passed, 3 skipped, 12 warnings in 3,273.44 s (54:33)**.
The five known worktree failures remain unchanged by name. Four additional
release-blocking failures are:

- `test_formal_diversity_replay_and_land_far`: fixture spine/compact fail FAR.
- `test_large_rd_coordinate_rotation_preserves_dictionary_semantics`: only
  one fixture candidate VALID; the other four fail FAR.
- `test_all_candidates_have_road_access`: pipeline INCOMPLETE at its READY
  precondition, not a passed end-to-end access regression.
- `test_job_runs_real_pipeline_and_reuses_proposed_ids`: real pipeline workflow
  returns job status FAILED instead of READY.

The reversed-recipe replay computes both runs but fails the READY assertion
before its hash-equality assertion. Therefore full replay determinism has not
passed verification. The isolated required-type/access suite passed 6/6, and
the terminal full suite includes that new placement test. No tests or gates
were weakened to remove failures. This round is unaccepted.

The before/r1 status and type counts in the comparison are archived historical
results, not revalidation under the restored per-candidate four-type gate.

Commands:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/run_formal_dictionary_generation.py --database out/formal-dictionary/fifth-rehearsal-db/state.sqlite3 --dry-run --output out/road-access-r3-final-20261003
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_required_placement_types.py tests/test_building_access_lanes.py
MPLCONFIGDIR=/private/tmp/w6-road-access-r3-mpl XDG_CACHE_HOME=/private/tmp/w6-road-access-r3-cache /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/compare_road_access_r3.py --before out/road-access-before-20261003/report.json --r1 out/road-access-final-20261003/report.json --r3 out/road-access-r3-final-20261003/report.json --output out/road-access-r3-comparison-20261003
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python out/road-access-r3-diagnostics-20261003/audit.py --report out/road-access-r3-final-20261003/report.json --before out/road-access-before-20261003/report.json --output out/road-access-r3-diagnostics-20261003/final-audit.json
```

The terminal full-suite run includes the new isolated placement test.
Runtime database paths are rejected
by the generation script; the supplied rehearsal copy is read only and dry-run
does not persist scenarios or ledger events.

Final plotting and audit each exited 0. The plot still emitted the bundled
PROJ database warning, but performed no reprojection; final font/cache warnings
were avoided by temporary cache paths, which are retained. Final source and
rehearsal DB hashes are in `terminal-source-hashes.json`. Intermediate hashes
remain separately preserved and must not be confused with the final code.

All eight source/fixture/database hashes in `terminal-source-hashes.json`
were checked again after the full suite and match. The rehearsal DB bytes
remain unchanged. Receipt: `terminal-source-verification.json`.

## Git boundary

Staging only the six changed project files was attempted on the verified
`wp/w6-road-access` branch. It failed with exit 128:

```text
Unable to create '/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-06-generator/index.lock': Operation not permitted
```

No commit was attempted after this rejection. All changes remain uncommitted;
HEAD remains `05dd13bfa9d5f5d0664f0161f461ff3be58a58b7`. No permission bypass,
Git cleanup, reset, push, merge, rebase or branch deletion was used.
