# W6-09 face editing executor handoff

Status: PARTIAL — fixture core implemented; CP6-A and evidence level 2 NOT PASSED.

Core author: gpt-6.1-sol / low (bounded topology and floor lineage coupling,
Founder 2026-09-30 routing). Root integration: GPT-6.1 Codex session.
No cross-provider review or Founder acceptance claimed.

## Implemented contract

`editing/faces.py` exposes immutable Face/FaceRevision and FaceEditHistory.
Subdivision uses line or strictly internal closed contour in face-local metres;
contour remainder is explicitly partitioned into polygons, not repaired.
Subdivision retains exact floor geometry, GFA and floor-stack volume.
Side extrusion supports positive integer metre pushes of full-storey rectangular
subfaces; top extrusion adds positive integer storeys over the selected top
subface. Upper-two-storey inset modifies exactly those two footprints. Undo
restores the stored parent, exact geometry hash and GFA; old revisions remain.
Geometry changes preserve unaffected partitions; changed faces have empty
successors (explicit invalidation/reselection), rather than invented geometric
correspondence. Precise changed-face successor lineage remains incomplete.

Only hole-free Polygon floor stacks with contiguous levels and fully supported
upper footprints are accepted. Holes, self intersections, unsupported cantilevers,
arbitrary-height facade extrusion, split/collapsed/topology-changing setbacks,
stale references and invalid steps are rejected. No repair buffer is used; the
negative buffer is the explicitly requested inset operation.
All results are FIXTURE_ONLY, production BLOCKED, acceptance/analysis ineligible.
Metrics are independently summed floor areas and area × storey height in m²/m³.
No CRS inference: router inputs explicitly declare FIXTURE_LOCAL_METRES.

## Integration steps (W6-2 owns shared files)

1. In api.py import `create_face_editing_router` from
   `urban_design.face_editing_api` and
   `app.include_router(create_face_editing_router())`.
   GET `/api/v1/editing/faces/readiness` always reports formal BLOCKED.
   POST `/api/v1/editing/faces/fixture-preview` is stateless, isolated fixture
   replay; provide building_id, provenance FIXTURE_ONLY, coordinate_reference
   FIXTURE_LOCAL_METRES, first/standard heights, floors {id,level,ring}, actions.
   No store, artifact root or database is accessed.
2. In App.tsx Refine stage mount `FaceSelection3D` and `FaceEditControls`.
   Selection props: faces {id,floorId,parentRevision,kind,triangles}, selectedId,
   onSelect. Geometry adapter must produce exact world-space triangles for
   semantic faces; never resolve a semantic ID from nearest mesh index.
   This adapter is pending and no existing 3D component was modified.
3. Controls props: selection {id,floorId,parentRevision,kind,localBounds},
   fixtureOnly, onPreview. Set fixtureOnly only in explicit fixture workspace;
   formal workspace stays false. Use selection.localBounds for drawing coordinates
   and key/revision selection reset. onPreview maps camelCase command to API
   snake_case, retains NEW_USABLE_FLOORS_PROTOTYPE semantics, replays actions
   from immutable fixture input. Reload the new face list after a geometry edit.
4. Formal W6-8 editor adapter, approved limits/bounds, durable revision storage,
   idempotency and scenario persistence are pending. Do not mount stateless
   fixture-preview as a formal scenario edit endpoint.

## Founder points and remaining gates

Façade-only shape vs newly usable floor plates; supported operation bounds;
arbitrary facade height; inward local pushes/top removal; general cantilever
solid topology; exact changed-face successor lineage require further work.
Prototype currently implements NEW_USABLE_FLOORS_PROTOTYPE; façade-only choice
is explicitly rejected. Formal activation remains BLOCKED.
No real-browser 3D walkthrough, level-2 immutable review manifest, durable recovery,
Claude independent review or Founder acceptance was performed.

## Fresh verification and retries

- Python: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_face_editing.py tests/test_face_editing_api.py tests/test_editing.py tests/test_scenario_editing_api.py tests/test_road_editing.py`: 55 passed; one existing Starlette deprecation warning.
- Frontend: `npm --prefix web run test -- --configLoader runner --cache false`: 196 passed, 33 files (after final drawing regression).
- Standard test startup EPERM at shared node_modules/.vite-temp; attempted
  --cache.dir /private/tmp/w6-09-vitest was rejected as deprecated; retry with
  runner and --cache false succeeded. Focused component suite first passed 5
  tests; full suite first passed 195 tests; final drawing regression added one.
- `npm --prefix web run build -- --configLoader runner` failed EPERM writing
  shared node_modules/.tmp TypeScript build info. Unchanged-config substitute:
  `web/node_modules/.bin/tsc -p web/tsconfig.app.json --incremental --tsBuildInfoFile /private/tmp/w6-09-app.tsbuildinfo`
  and equivalent tsconfig.node.json /private/tmp/w6-09-node.tsbuildinfo;
  `web/node_modules/.bin/vite build web --configLoader runner --outDir /private/tmp/w6-09-web-build` succeeded.
  Existing >500 kB chunk warning remains. Build emits current shell; unmounted new
  components are typechecked and unit tested, not demonstrated in that shell.
- Core worker ran focused tests twice while correcting lineage/validation.
  Root ran API tests and broader Python regression, then reran after adding malformed-cut rejection. No failed API action retried
  against an external service.
- No files/directories deleted; no cleanup, downloads, new dependencies, servers,
  reserved-port actions, DB access, live AI or HumanDecision creation.
  /private/tmp build artifacts/cache retained. Initial untracked .venv retained
  and excluded from commit.

## Git delivery BLOCKED

Root attempted explicit-file `git add`, followed by `git commit`; both failed
EPERM creating `/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-09-faces/index.lock`.
The linked worktree Git metadata lies outside permitted writable roots. No commit
was created and no permission bypass/retry attempted. HEAD remains
`6bb2d9f3a0598a1433873fe628fc01923edc05d5`, branch `wp/w6-09-faces`.
The following command is for an authorized shell with write access to Git metadata:

```sh
git add src/urban_design/editing/faces.py src/urban_design/face_editing_api.py tests/test_face_editing.py tests/test_face_editing_api.py web/src/components/FaceEditControls.tsx web/src/components/FaceEditControls.test.tsx web/src/components/FaceSelection3D.tsx web/src/components/FaceSelection3D.test.tsx docs/w6/W6-09-face-editing-handoff.md
git commit -m 'feat(editing): add fixture face subdivision and floor-aligned local extrusion' -m 'Keep formal edits blocked pending baseline and Founder semantics; add isolated preview router, selection controls, regression tests and integration handoff.' -m 'Co-Authored-By: GPT-6.1 Sol'
```
