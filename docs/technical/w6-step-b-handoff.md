# W6 step B executor handoff (2026-10-02)

Status: IMPLEMENTED_PENDING_COMMANDER_REVIEW. No browser/server validation or Founder acceptance was performed.
Branch: wp/w6-step-b. Starting HEAD: 51f30bbff05ef55b34a194aca640628042b56ddf (a0ea28e plus reviewed a7cf42e merge).
Execution: direct session; no subagent, background dispatch, live AI or provider fallback.

## Changes

- api.py includes W6-3 readiness/freeze and W6-5 workflow routers. The resolver uses the injected served ProjectStateStore, verifies D1/D2 and source hashes, and freezes a typed context with fixed seed 42.
- formal_service.py registers a MASSING handler for Full scheme and invokes the existing formal_pipeline. formal_persistence.py is the extracted Step A writer shared with the rehearsal script. It appends AGENT_AUTOMATION Artifact/PROPOSED Scenario records only, rechecks authority before publication, keeps deterministic identities and verifies existing geometry bytes instead of overwriting them.
- Dedicated durable job SQLite lives under configured scenario_artifact_root/generation/jobs.sqlite3, separately from authority state. Stable authority geometry is under generation/formal/<typed-context-hash>. Published job manifests bind result reports under generation/jobs/<job-id>.
- Read-only GET /api/projects/{project_id}/formal-proposals returns typed metrics, Scenario identity, strategy, geometry Artifact identity/path and hash-verified GeoJSON. Bound observed retained heights are supplied for display; unknowns remain unknown.
- Conditions/Generate mount readiness panels; Generate mounts the workflow panel with mode ribbon controls and a Compare results link. Compare lists formal PROPOSED separately from previews, supports 2D/3D and two formal proposals with synchronized cameras. Properties show denominator, metrics and per-zone uses. Decision 3 is a disabled Founder entry.
- Existing formal pipeline exposes primary open spaces and street blocks; metrics retain the full geometric remainder definition of open space. The displayed primary open-space layer is not a public-accessibility claim.

## Explicit limitations and pending gates

Skeleton first / Stepwise return NOT_READY / STAGED_FORMAL_SELECTION_NOT_IMPLEMENTED. The approved formal pipeline is monolithic and cannot yet resume from selected skeleton/program outputs; no fixture handler substitutes for this.
Full scheme ends at the existing MASSING workflow selection stop (AWAITING_SELECTION); this is workflow selection, not Scenario acceptance. No selection endpoint was called during rehearsal.
The server uses synchronous deterministic dispatch, inherited from W6-5; readiness/source verification and generation can take time.
Commander cross-provider code review and temporary-port browser verification remain pending. Founder decides acceptance; all proposals remain unaccepted.
No protected runtime DB, weather inputs, secrets, live AI or protected port was used. No HumanDecision was created.

## Rehearsal

Database: /private/tmp/claude-501/-Users-jackhsieh-Downloads-TUD-Q5-project/ed3e0c5c-6991-4bd5-8782-84d13fc450f1/scratchpad/runs/step-b/rehearsal-state.sqlite3
Output root: /private/tmp/w6-step-b-rehearsal-20261002
Receipt: /private/tmp/w6-step-b-rehearsal-20261002/receipt.json
Workflow: 08227d1c67054240a3eedd4a846fca33
Job: 587360a660c94d1dbd1de10173392ad2 (READY, PUBLISHED on reconciliation)
Typed context: sha256:3da03eb0172d0e54863947bf716d18e7d03cfa9f5c61308d87c5f706db87aed1
FAR denominator: land_area = 183591.328035937 m2 for all five proposals.

| Scenario ID | FAR | Coverage | Max new height m | Open-space ratio |
|---|---:|---:|---:|---:|
| formal-dict-3da03eb0172d-common-compact-a1ff97864a21 | 0.764436103 | 0.177475138 | 14.0 | 0.743717038 |
| formal-dict-3da03eb0172d-common-mixed-98854aff5f7b | 0.743086842 | 0.153750131 | 17.5 | 0.751165887 |
| formal-dict-3da03eb0172d-grid-fine-18c292b0c44c | 0.773887774 | 0.159910317 | 17.5 | 0.680275648 |
| formal-dict-3da03eb0172d-grid-mixed-f764c233baa3 | 0.754998864 | 0.156132535 | 17.5 | 0.693232800 |
| formal-dict-3da03eb0172d-spine-mixed-475cd5c6320c | 0.737395244 | 0.152611811 | 17.5 | 0.796726508 |

Initial TestClient run invoked Full scheme once and published five proposals; its subsequent list assertion failed because the first API implementation compared uppercase PROPOSED with the DB's lowercase proposed. This was a known list failure, not an unknown generation result. After the fix, the existing READY job was only reconciled (runner.run returned existing READY without redispatch); its manifest/hashes and five proposal IDs were verified. Scenario/Artifact counts and HumanDecision revisions stayed unchanged during reconciliation. The initial persistence code only writes Scenario and Artifact entity types.

## Verification commands and results

Final Python suite: 63 passed, 1 warning in 35.00s.
```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_formal_workflow_service.py tests/test_generation_modes.py tests/test_generation_jobs.py tests/test_generation_context.py tests/test_formal_dictionary_preflight.py tests/test_formal_dictionary_pipeline.py tests/test_formal_height_binding.py tests/test_formal_legacy_profiles.py tests/test_formal_source_resolution.py
```
The focused integration test runs the real formal pipeline on synthetic frozen inputs in a temporary authority DB; it proves BLOCKED, explicit NOT_READY, router wiring, proposal listing, identical and distinct-key idempotency, artifact-tamper rejection, publication receipt and no HumanDecision writes.

Frontend:
```sh
npm --prefix web run test
npm --prefix web run build
npm --prefix web run test -- --configLoader runner --no-cache
web/node_modules/.bin/tsc -p web/tsconfig.app.json --tsBuildInfoFile /private/tmp/w6-app.tsbuildinfo
web/node_modules/.bin/tsc -p web/tsconfig.node.json --tsBuildInfoFile /private/tmp/w6-node.tsbuildinfo
cd web && node_modules/.bin/vite build --configLoader runner
```
Original test/build commands were blocked by EPERM writes to shared node_modules/.vite-temp and .tmp. The CLI-only alternatives require no config/dependency changes. Frontend: 37 files / 226 tests passed; TypeScript and Vite build passed. Vite reports the existing >500kB bundle-size warning. Python reports one Starlette anyio deprecation warning.
Rehearsal commands: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python /private/tmp/w6_rehearse.py; then .venv/bin/python -u /private/tmp/w6_reconcile.py with the same environment. No server was started.

## Retries and generated-output handling

- Initial sandbox test/build failures were retried with configLoader runner / temporary build-info. An attempted --cache.dir flag was rejected as deprecated; --no-cache succeeded.
- Initial frontend run had six failures (legacy placeholder expectation and malformed generic mock response on the new endpoint); API-response shape guarding and updated/new component tests resolved them.
- Synthetic backend fixture produced four VALID proposals, unlike the approved rehearsal's five. The integration test now asserts the actual valid proposal count and excludes failed candidates rather than assuming five.
- Focused suites were rerun after the status, publication, integrity and UI corrections; the final results are recorded below.
- A read-only ps diagnostic was denied by sandbox; no process was stopped or retried.
- No manual delete/reset/clean/rebase/push was run. Temporary scripts, cache/build-info and rehearsal outputs are retained. Vite rebuilt its generated dist output with its default output handling; no source files were removed.
- Pre-existing untracked .venv was preserved and excluded from staging.

## Changed files

- scripts/run_formal_dictionary_generation.py
- src/urban_design/api.py
- src/urban_design/generation/workflow.py
- src/urban_design/generation/formal_persistence.py
- src/urban_design/generation/formal_service.py
- tests/test_formal_workflow_service.py
- web/src/App.tsx
- web/src/App.test.tsx
- web/src/components/CompareWorkspace.tsx
- web/src/components/CompareWorkspace.test.tsx
- web/src/components/GenerationWorkflowPanel.tsx
- web/src/components/FormalProperties.tsx
- docs/technical/w6-step-b-handoff.md

## Git result

Staging failed once: fatal: Unable to create '/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-05-workflow/index.lock': Operation not permitted.
No staging/commit retry, escalation or permission bypass was attempted. No new commit SHA exists; HEAD remains 51f30bbff05ef55b34a194aca640628042b56ddf on wp/w6-step-b. Changes remain unstaged for Commander review and staging outside this sandbox.
