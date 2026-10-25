# Week 4 R04-R02 Follow-up: Current Parent Drift and Test Environment

**Captured:** `2026-09-23T09:42:07.547082+00:00`  
**R02 verifier implementation:** `PASS` (verified in the clean upstream state recorded by the original R02 package)  
**Current R04/R01 upstream integrity:** `BLOCKED_SOURCE_PARENT_DRIFT`  
**Current R02 CLI self-test:** `BLOCKED` before fault cases, with structured JSON and no traceback  
**Current project-environment full pytest:** `PASS` — 452 passed, 7 warnings  
**Overall Week 4:** `INCOMPLETE`

This append-only follow-up records the state after the user confirmed that Grok Build intentionally edited `web/index.html` and `web/src/index.css` to change the WebUI icon. The files were preserved as requested. No old R04, R01, or R02 manifest was rebuilt. The original R02 clean-state verification and test results remain in [`artifacts/week4-repair-r04-amendments-r02/`](../artifacts/week4-repair-r04-amendments-r02/); this follow-up records the later state.

## Current integrity results

All 22 files declared by the frozen R04 base manifest and all 3 supplemental R01 files still match their archived SHA-256 and size. The R04 and R01 manifest files are unchanged. The current upstream verifier is blocked only by declared parent hashes for the two WebUI files:

| Parent | Frozen expected SHA-256 | Current SHA-256 | Attribution |
|---|---|---|---|
| `web/index.html` | `38d008dd8d933ba03fc119f27f5cf6d3e899083a5fcd9f919add16c15401721a` | `e5a3204b16a227e9adeabe9d914e3a654970f29684e89e38278fee3348d69da0` | User-confirmed Grok Build icon edit |
| `web/src/index.css` | `1fdec4aeb07bcd0c69a7b95558fb077dd5a05e87ce6de0deb203b1d11b5961b3` | `24d23eed901013bd3550015c9ca0032b456eba33d45ec0dda9e53376e5538527` | User-confirmed Grok Build icon edit |

The R02 evidence package's four listed internal files still match their manifest. Its parent links also include the R02 regression test as it existed when the R02 package was recorded. This task subsequently adjusted that test to cover the structured fail-closed state after the confirmed upstream edits:

| Parent | Prior R02 expected SHA-256 | Current SHA-256 | Attribution |
|---|---|---|---|
| `tests/test_week4_r04_amendments_r02.py` | `64cc792a9ca30e68a277eaf61be6af0b51c422eeefb72ee8b86ee54693275852` | `5be64a08f63be90ee4c21c307636979098cc2e13f65a882e7c8dc15da3a70714` | This task updated the assertion to expect structured BLOCKED when upstream drift exists |

The original R04 base manifest hash remains `52927a6de6c05099b3ba063e8ea93805fb7e28378092fe85a78a0b1bc133f8a8`; the supplemental R01 manifest hash remains `5ca2d0ffa73e50fd01069dbdaa36a2acb43fb92e0796ce55c1f82c580bae99c5`; the original R02 evidence manifest hash remains `476170073d43200930a64c2a3a6b53a70e15849b32ccaf04c869275a848ba0e2`. The authoritative runtime SQLite file remains `6a89b1d3f94f387f180e1a454953d744ec36446081cd0a5b8c6e1b63576b7937`. The Week 4 gate remains `INCOMPLETE`.

## Verifier and tests

The current versioned R02 CLI returns JSON `BLOCKED` because its upstream R04/R01 precondition fails. It safely skips disposable fault cases in this state; stderr is empty and no traceback is emitted. The focused R02 regression test passes and asserts this structured outcome.

The canonical full suite, `.venv/bin/python -m pytest -q`, passed 452 tests with 7 existing deprecation warnings. An initial bare `pytest -q` used the global pyenv interpreter, which lacks `ladybug.epw`; four R08-R01 tests failed during import there. Running from the project `.venv` resolved the environment mismatch.

## Status boundaries and next step

The versioned R02 repair remains supported by the original clean-state self-test evidence: valid clone passed; byte mutation, missing file, missing parent, and mutation of the cloned public docket each blocked. The current upstream verification is now `BLOCKED_SOURCE_PARENT_DRIFT`; this does not invalidate the archived R04/R01 package bytes, and it must not be described as a current verifier pass.

No WebUI edit was reverted or copied into historic evidence. No R04/R01/R02 package, SQLite state, ledger, StudyArea, or Week 4 gate was rewritten by this follow-up. The Control Tower should decide whether the icon work needs a new append-only R04 parent-lineage amendment. After that decision, rerun the R02 verifier and update evidence only in a new append-only record. Week 4 remains incomplete.

Machine-readable results and checksums are in [`artifacts/week4-repair-r04-amendments-r02-followup/`](../artifacts/week4-repair-r04-amendments-r02-followup/). Its integrity manifest excludes itself and records each file's size, SHA-256, kind, and parent paths/hashes.
