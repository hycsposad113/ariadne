# W6-10 executor handoff (DRAFT)

## Scope and authority

Source plan: `project/docs/w6/2026-10-01-week6-execution-plan-DRAFT-zh.md:232-241`, common rules 52-125 and checkpoints 285 onward. Base main `6bb2d9f`, executor branch `wp/w6-10-snapping`.

Core native worker: gpt-6.1-sol / low (coupled exact geometry/topology). UI native worker: gpt-6-luna / max (bounded component/utility). Root integration: GPT-6 Codex. No provider fallback or external review dispatched.

No HumanDecision, ConstraintSet, approved scenario, site or policy is created. Tests use self-created disposable databases and synthetic FIXTURE_ONLY scenarios. Original provenance remains in scenario parameters. Formal baseline and W6-8 accepted editor integration remain NOT_READY pending their owner and human inputs. This delivery is not CP6-B or CP-W6 acceptance.

## Core contracts

- Seven snap kinds use projected ground metres on straight edges defined by their endpoints. Fractions are along edge length from start; midpoint does not mean whole multi-edge road midpoint.
- Perpendicular uses the original moving-node position unless `perpendicular_anchor_node_id` is supplied. The caller must display this anchor; a fixed incident endpoint can be passed explicitly.
- Known equal layer/bridge/tunnel may connect. Absent layer is None and never inferred as 0. Unknown level produces no candidates; explicit requested snap fails NOT_READY. Free movement does not infer connectivity.
- Endpoints merge node IDs. Selected interior points split every compatible target edge at that point; cross-level edges remain isolated. Split children preserve access refs and append parent edge lineage.
- Duplicate endpoint/geometry edges, zero lengths, locked changes, ID collisions and unavailable explicit targets fail without mutating input.
- Components count actual shared graph node IDs, never geometric crossings alone.
- Roads invalidate supplied Syntax/accessibility refs, published road-job refs, and transitive `road_dependency_refs`. Prior records/artifacts remain intact. Height-only edits preserve road/accessibility state.
- `publish_road_job_reference` verifies graph bytes-derived hash and road revision, then uses scenario CAS. Delayed/competing publication fails; it attaches an UNVERIFIED artifact reference only, never graph geometry or approval. Production publishers must invoke this guard in their publication path; existing external job runtimes were not changed.

## Integration steps

1. `scenario_editing_api.register_scenario_edit_routes(router, store, artifact_root)` already receives the scenario router. Existing registration exposes the new POST `/api/v1/scenarios/{scenario_id}/road-nodes/{node_id}/snap-candidates`; no `api.py` edit is included. If integration builds a separate router, call this registration once and include that router, avoiding duplicate routes.
2. Move request now accepts optional `snap_kind`, `target_id`, `perpendicular_anchor_node_id`. Tolerance and dependency refs are read from server-owned scenario state. Preview includes graph hash, road revision, numeric fraction/length and position semantics. Pass the selected target node or first target edge ID.
3. Integrate RoadSnapPanel in App Refine stage beside ScenarioStudio road editing. Props and component tests define locale, graph/revision, readiness, preview/apply callbacks. Feed API candidates, preserve FIXTURE_ONLY/DRAFT, and map absent approved baseline or LEVEL_UNKNOWN to BLOCKED/NOT_READY. Request callbacks must submit expected road revision and an idempotency key. Do not fabricate approvals.
4. Durable analysis publisher owner must use `publish_road_job_reference` or equivalent same-transaction hash/revision/CAS contract; never publish old output into a newer graph. Use explicit dependency refs for downstream comparison/report artifacts. No automatic analysis rerun.

## Remaining acceptance gates

Independent Claude cross-provider review, immutable reviewer package acceptance, formal approved baseline, actual App integration, browser-operated visual/bounds evidence and restart/publication recovery in integrated runtime are pending. No servers or protected ports were used.

## Execution and environment notes

Expected red tests were run before implementation. One combined run was attempted before the worker had created `test_road_snapping.py`; pytest returned missing file, with no tests run, and was rerun after the file existed.

Standard npm test failed with EPERM writing shared node_modules/.vite-temp. A trial `--cacheDir` was rejected by Vitest (unsupported option). `--configLoader runner` succeeds without config edits. Standard build failed with TS5033 EPERM for shared node_modules/.tmp build-info; TypeScript config checks use `/private/tmp` build-info, then Vite runs with runner. No dependency changes/downloads, file deletion, cleanup, runtime service changes, or decision-secret access. Generated ignored dist and temporary test/cache artifacts are retained.

## Validation commands

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_road_editing.py tests/test_road_snapping.py tests/test_road_invalidation.py tests/test_road_snapping_api.py tests/test_scenario_editing_api.py tests/test_editing.py tests/test_scenario_api.py`
- `npm --prefix web run test` (EPERM); successful equivalent: `npm --prefix web run test -- --configLoader runner`.
- `npm --prefix web run build` (TS5033 EPERM); equivalent checks: `web/node_modules/.bin/tsc -p web/tsconfig.app.json --tsBuildInfoFile /private/tmp/w6-10-app.tsbuildinfo` and `web/node_modules/.bin/tsc -p web/tsconfig.node.json --tsBuildInfoFile /private/tmp/w6-10-node.tsbuildinfo`, then from `web/`: `npm --prefix web exec -- vite build --configLoader runner`.

Integration adapters must map panel `graph_hash` to API `expected_graph_hash`, `revision` to `expected_revision`, and filter request bodies to declared fields (coordinates, revision/hash, kind/target, optional anchor, plus move idempotency key). Never send candidate display metadata as command authority. Always provide `candidatesGraphHash` and `candidatesRevision`; callbacks must reject non-2xx responses and reconcile returned graph/revision before changing parent graph state.

## Claude review prompt

Read-only review of `/Users/jackhsieh/Downloads/TUD/Q5/w6-10-snapping`, branch `wp/w6-10-snapping`, frozen source files/hashes listed in `docs/w6/W6-10-source-manifest.json`. Verify actual code and test evidence against W6 plan lines 232-241, 52-125 and CP6-B. Review seven geometry classes, actual shared-node topology, split lineage/access refs, unknown level refusal, zero/duplicate/locked rejection, transitive stale and height-only control, old-job/CAS failure, bilingual standalone UI and delayed preview suppression. Do not mutate main, runtime DB, ledger, approvals, sources or services. No live AI/EPW/credentials/decision secrets. Record reviewer provider/model/command and findings. Code delivery and fixture tests do not establish formal baseline, browser visual integration, recovery or CP6-B acceptance. Founder retains decisions and final acceptance.

## Fresh final results

- Python listed suite: **62 passed**, one existing Starlette/AnyIO deprecation warning.
- Full frontend runner suite: **32 files / 199 tests passed**.
- Both TypeScript project checks: exit 0. Vite runner production build: exit 0; existing >500 kB chunk warning. RoadSnapPanel remains intentionally unmounted, so the built App does not claim integrated road-panel operation.
- UI development reruns: intermediate utility full run was 193 passed/1 failed (unknown endpoint-level mismatch), repaired to fail closed; intermediate panel focused run was 12 passed/2 failed (test label query and unavailable matcher), then corrected. No result resubmission or service retries.

## Git delivery BLOCKED by managed sandbox

The one attempted explicit-file `git add` failed exit 128:
`Unable to create '/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-10-snapping/index.lock': Operation not permitted`.
The worktree's Git metadata is outside writable roots. No staging/commit succeeded; no commit SHA exists. No retry, permission bypass, reset, clean or file deletion was performed. `.venv` was pre-existing untracked and is excluded from delivery.

After reviewing the frozen files, run outside this restricted executor sandbox:

```sh
cd /Users/jackhsieh/Downloads/TUD/Q5/w6-10-snapping
git add src/urban_design/editing/roads.py src/urban_design/editing/road_dependencies.py src/urban_design/scenario_editing_api.py tests/test_road_editing.py tests/test_road_snapping.py tests/test_road_invalidation.py tests/test_road_snapping_api.py web/src/utils/scenarioEdits.ts web/src/utils/scenarioEdits.test.ts web/src/components/RoadSnapPanel.tsx web/src/components/RoadSnapPanel.css web/src/components/RoadSnapPanel.test.tsx docs/w6/W6-10-snapping-handoff.md docs/w6/W6-10-source-manifest.json
git add docs/w6/W6-10-commit-message.txt
git commit -F docs/w6/W6-10-commit-message.txt
```

The prepared commit message has actual newline trailers. Do not stage .venv or generated dist.
