# W6 formal face publication repair

Status: FIXED_ON_BRANCH; W6 acceptance remains INCOMPLETE.
Author: OpenAI gpt-6.1-sol(low).
Branch: `wp/w6-closeout-fix-face-publication`.
Reviewed source: `b58859397f9f102c35f4eda2ce47cac3c53c73ba`, integrated in baseline `8aff49459c57d981767733034e40c502c000e5cf`.

## Reproduced defects and resulting behavior

1. SETBACK changed floor polygons/GFA to 3728 m² but left DesignScenario geometry artifact/hash unchanged. Publication now materializes the complete scenario document with actual edited floor polygons, advances both geometry references, and records the prior geometry artifact as parent.
2. Failure inserting ToolExecution after prior independent commits returned HTTP 409 but advanced scenario authority. The existing `commit_batch` now owns Artifact, ToolExecution, scenario revision and ledger insertion as one transaction. The bounded typed helper uses existing store insertion primitives only inside that callback and rejects target/project/status/provenance mismatches. No store schema or `store.py` change.
3. An arbitrary operation name was treated as a top extrusion. The request now admits only explicit supported operations and rejects unknown operations before mutation.
4. Artifact identities previously used only scenario/face revision and could collide across buildings or undo branches. They now include scenario revision, building identity and request fingerprint in a hash; file creation is exclusive. Staging and unrelated peer files are preserved on failure.

## Fresh validation

Command: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/jackhsieh/Downloads/TUD/Q5/project/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_week6_face_publication.py tests/test_formal_face_editing_api.py tests/test_formal_editor_authority.py`.

- Before repair: three new regressions failed on the original branch source.
- After repair: **11 passed**, one existing dependency deprecation warning, 5.10 s.
- Failure injection covers both ToolExecution and DesignScenario insertion; all authority counts, scenario payload/revision and ledger event IDs remain unchanged.
- Actual published file size/hash matches Artifact and Scenario references, records its parent, and contains four edited polygons totaling 3728.0 m².
- Existing 4000.0 → 3728.0 m², 272 m² difference, 20 m refusal, stale/idempotency, restart/lineage and peer-file retention checks remain. The collision test now occupies the new computed artifact ID; its behavioral assertions were not removed or relaxed.
- `git diff --check` passed.

Evidence: `artifacts/w6-codex-c0-20261005T130642Z-596cb9a9/face-publication-green-r03.txt`, SHA-256 `6876c37f26234205798ea8891a6a024b5dbf4e34206e568416133d4e66133487`.
Baseline full suite: 1806 passed, 2 failed, 6 skipped; Vitest 279 passed, build/lint passed. This is pre-repair baseline evidence, not repaired full-suite acceptance.
Official DB hash unchanged: `2f70e846d4ecb4109f54314e210fb4ba7ce90adc57c420fe6c4f31e8cd7fb366`.

## Validation retries and limitations

A preliminary mixed scratch/worktree test invocation imported the original worktree module due to pytest path resolution. It is not candidate validation. A subsequent isolated-copy test asserted module origin, exposed the old-ID collision fixture mismatch, then passed 8 checks after adapting that fixture. The final 11-test result above runs the actual repaired worktree.

Files retained after a filesystem publication followed by database rollback are orphan evidence, not authoritative output; exclusive creation prevents silent overwrite/retry. The helper intentionally depends on existing private insertion primitives inside the public batch transaction; tests guard that integration contract.

E1 geometry conversion for edited floor features, formal authority resolution against actual D1, complete validation/staleness/UI behavior, redo/holes and the wider C1 audit remain separate open work. This repair does not claim C2/C3 browser or full-chain acceptance and does not authorize main merge or deployment.
