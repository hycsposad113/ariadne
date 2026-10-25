# Week 4 R04-R02 Current Parent Lineage Record

**Captured:** `2026-09-23T12:27:28.158745+00:00`  
**ARCHIVE_INTEGRITY:** `PASS_INTERNAL_FILES_WITH_PARENT_DRIFT_RECORDED`  
**CURRENT_PARENT_LINEAGE:** `BLOCKED_SOURCE_PARENT_DRIFT`  
**R02_SELF_TEST_CURRENT:** `BLOCKED_LIVE; PASS_ON_FIXED_FIXTURE`  
**WEEK_4_OVERALL:** `INCOMPLETE`

This is a new append-only record. It does not rewrite any earlier docket, manifest, verifier, or test-result artifact. It records freshly read file hashes after the full test run and retains the available HTML/CSS source bytes under `source-captures/`.

## Fresh parent hashes and lineage

| Parent | R04 base expected | R02 expected | Fresh captured SHA-256 | Size bytes |
|---|---|---|---|---:|
| `web/index.html` | `38d008dd8d933ba03fc119f27f5cf6d3e899083a5fcd9f919add16c15401721a` | `38d008dd8d933ba03fc119f27f5cf6d3e899083a5fcd9f919add16c15401721a` | `e5a3204b16a227e9adeabe9d914e3a654970f29684e89e38278fee3348d69da0` | `587` |
| `web/src/index.css` | `1fdec4aeb07bcd0c69a7b95558fb077dd5a05e87ce6de0deb203b1d11b5961b3` | `1fdec4aeb07bcd0c69a7b95558fb077dd5a05e87ce6de0deb203b1d11b5961b3` | `abf0f4d1cf7d87aa91327c6548b887a1f8856c090be61104ca666e0ac46397aa` | `5301` |

R04 and R01 package-internal integrity is **25/25 files** (22 base plus 3 R01 amendment files). The original R02 evidence package is **4/4**, and the prior R02 follow-up is **5/5** internally. Parent lineage is reported separately: the R04 base currently mismatches the two WebUI parents; R02 also has its historic test-source parent mismatch; the prior follow-up now mismatches the fresh CSS parent. Exact per-manifest counts and mismatches are in `archive-integrity.json`.

`web/src/index.css` was hash `24d23eed901013bd3550015c9ca0032b456eba33d45ec0dda9e53376e5538527` and size 5495 in the prior follow-up capture; it is now hash `abf0f4d1cf7d87aa91327c6548b887a1f8856c090be61104ca666e0ac46397aa` and size 5301 (size delta -194 bytes). The prior bytes are unavailable, so no textual or byte-level diff can be asserted. The search found no file with the prior hash in the recorded project/evidence/temp roots, and `tmutil listlocalsnapshots /` listed no snapshots. This checkout is not a Git worktree. The current CSS file mtime is `2026-09-23T09:56:57.349570+00:00`; metadata does not identify who edited it. The earlier confirmation that Grok changed the icon does not establish authorship of this later CSS revision.

## Self-test coverage

The historical clean-state R02 result remains archived at `artifacts/week4-repair-r04-amendments-r02/verification-results.json` with SHA-256 `842d9d8cea5b56cbeca46e1388702efb335f6060f891982c01245815e80fa5c5` and recorded PASS. The current live CLI returns structured `BLOCKED` before running cases because the live R04/R01 parent precondition fails; it emits no traceback.

A separate fixed, synthetic fixture under `tests/fixtures/week4_r04_r02_clean/` now invokes the real R02 CLI and real R01/R04 verifier, independently of current project parents. Its current outcomes are `{"byte_mutation": "BLOCKED", "missing_file": "BLOCKED", "missing_parent": "BLOCKED", "public_docket_copy_mutation": "BLOCKED", "valid_clone": "PASS"}`. The outer fixture manifest verifies all 17 retained fixture files. This is a live rerun against fixed test bytes, not a claim that the missing historical CSS version was reconstructed.

## Tests and protected state

Focused tests: **6 passed**. Full project suite: **453 passed, 7 warnings** using `.venv/bin/python -m pytest -q`. The authoritative runtime SQLite file remains SHA-256 `6a89b1d3f94f387f180e1a454953d744ec36446081cd0a5b8c6e1b63576b7937`; no ledger, StudyArea, weather data, QGIS, Hermes, or design-approval state was changed or exercised. Week 4 remains `INCOMPLETE`.

Machine-readable status, fresh hashes, captured bytes, search scope, verification output, tests, and manifest are in [`artifacts/week4-repair-r04-amendments-r02-lineage-20260923T122728Z/`](../artifacts/week4-repair-r04-amendments-r02-lineage-20260923T122728Z/). The manifest excludes itself and records size, SHA-256, kind, and parent paths/hashes for every packaged file.
