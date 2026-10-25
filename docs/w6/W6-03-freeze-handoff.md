# W6-03 fixture-first context freeze handoff

Status: PARTIAL / fixture implementation delivered; formal generation BLOCKED pending Founder decisions. CP6-P, CP-W6 and evidence level 2 are not accepted by this package.

## Scope and authority

Executor worked directly in `wp/w6-03-freeze`, based on `6bb2d9f`. No delegation, external review, AI request, runtime DB access, server startup, HumanDecision creation, decision-secret handling, dependency change or shared integration-file edit was performed.

The session system identifies the executor as GPT-6; exact model variant/effort is not exposed to this executor. This handoff does not claim verified `gpt-6.1-sol/low` routing. W6-03's requested route is Sol 6.1 Low because its authority and context hashing are coupled. No model fallback or dispatch occurred.

## Delivered files

- `src/urban_design/generation_context.py`: strict request/response contracts, existing server authority resolver, one read transaction, source artifact verification, reproducible context digest, read-only freeze and stale 409. No store/model/validator changes.
- `tests/test_generation_context.py`: synthetic SQLite fixtures; no HumanDecision records. Positive authority-resolution inputs are explicitly mocked; they are not evidence of real approval. Tests cover a valid unapproved draft, non-authoritative labels, rejection of client approval flags, source-byte corruption, revision/hash drift, overlap priority, explicit EDA denominator and floor unknown/range.
- `web/src/components/GenerationReadinessPanel.tsx` and `.test.tsx`: standalone Conditions panel, English/Traditional Chinese chrome, original server diagnostics, no approval/generation control.

Context is a manifest returned by the server, not a new authoritative entity. Freeze does not persist or activate anything. It binds current workspace/StudyArea/ConstraintSet/source record revisions and payload hashes, existing approval references, allocated zone geometry, EDA denominator and retained floor estimates. A consumer must revalidate the expected revision/hash immediately before its own authoritative generation operation; this package does not retrofit the legacy generator or promise transaction atomicity across HTTP requests or external file changes.

Existing W5 approval semantics are reused: one WorkspaceRevision decision binds EDA/dispositions/spatial brief/zones together, and one ConstraintSet decision binds constraints/allocation policy. This does not implement new W6 Founder decision workflows. EDA is the explicit conceptual FAR denominator used by the existing generator; no alternative denominator or legal parcel authority is inferred. Priority is existing workspace zone list order, not a new ranking. Unknown/ranged retained floors remain unavailable for scalar GFA/FAR; no zero substitution.

## Fresh validation

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_generation_context.py tests/test_constraint_set.py tests/test_design_brief.py`: 21 passed, 3 existing deprecation warnings.
- `npm --prefix web run test -- --configLoader runner`: 32 files, 193 tests passed.
- `web/node_modules/.bin/tsc -p web/tsconfig.app.json --tsBuildInfoFile /private/tmp/w6-03-app.tsbuildinfo`: passed.
- `web/node_modules/.bin/tsc -p web/tsconfig.node.json --tsBuildInfoFile /private/tmp/w6-03-node.tsbuildinfo`: passed.
- `web/node_modules/.bin/vite build web --configLoader runner`: passed; existing >500 kB chunk warning.
- `git diff --check`: passed before commit.

No live UI screenshots or real approved-input integration were claimed. Cross-provider Claude review, immutable level-2 package, Founder decisions and integration-owner wiring remain pending.

## Retries and retained artifacts

Initial `npm --prefix web run test` failed with EPERM writing shared `node_modules/.vite-temp`. Initial `npm --prefix web run build` failed with EPERM writing shared `node_modules/.tmp` build-info. The attempted `npm --prefix web run test -- --configLoader runner --cacheDir /private/tmp/w6-03-vitest-cache` failed because Vitest does not support `--cacheDir`. The accompanying `npm --prefix web run build -- --configLoader runner` still failed at TypeScript's build-info writes. Final runner-only tests succeeded; build was split into the two TypeScript commands above with temporary build-info and Vite runner build. Python focused tests were rerun after added source/valid-draft cases: 19, then 20, then 21 passing tests. No outcome-unknown or paid/authentication retry occurred.

No files/directories were deleted or cleanup commands run. `/private/tmp/w6-03-*.tsbuildinfo` and ignored `web/dist` build outputs remain. Initial untracked `.venv` was preserved and excluded from commit. Test fault injection overwrote only its synthetic temporary 3D BAG fixture. No ports were opened or stopped.

## Integration steps (W6-2 owner only)

1. In `api.py`, import `create_generation_context_router` from `urban_design.generation_context`; call `app.include_router(create_generation_context_router(store))` with the existing authoritative store. No new DB construction/path selection by this module.
2. Fetch `GET /projects/{project_id}/generation-context/readiness` after Conditions state loads and after workspace/constraint mutations; clear old readiness during refresh or request failure.
3. In `App.tsx` Conditions stage render `<GenerationReadinessPanel readiness={generationReadiness} />` within the existing `I18nProvider`. Prop type is exported `GenerationReadiness | null`; parent owns fetch, cancellation, errors and refresh. `null` displays NOT_READY.
4. A future generation integration must POST `/projects/{project_id}/generation-context/freeze` with `expected_workspace_revision` and `expected_context_hash` from the latest readiness response. Handle 409 BLOCKED/STALE by stopping and refreshing; do not auto-resubmit generation. This response itself neither generates nor grants approval.

## Commit boundary

`git add` was rejected by the filesystem sandbox while creating `/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-03-freeze/index.lock`. No files were staged and no commit was made. The sandbox permits source writes in this worktree but not the external Git worktree metadata. No alternate index/object-store or permission bypass was attempted. The pre-stage `git diff --check` had no tracked edits to inspect; a final per-file `git diff --no-index --check /dev/null <file>` check covers the new files.

From an authorized terminal in this worktree:

```sh
git add src/urban_design/generation_context.py tests/test_generation_context.py web/src/components/GenerationReadinessPanel.tsx web/src/components/GenerationReadinessPanel.test.tsx docs/w6/W6-03-freeze-handoff.md
git commit -m "feat(w6-03): add fixture-first generation context freeze" -m "Co-Authored-By: GPT-6"
```
