# M2-A02 — Live QGIS StudyArea Bridge

M2-A02 provides the local Draw → Confirm StudyArea vertical slice. The
companion QGIS plugin identifies the designer's saved selection; it never sends
the polygon as authoritative input. The FastAPI bridge independently checks
QGIS state through a bounded qgis-mcp socket and obtains the exact geometry only
with a backend-generated `export_layer` request.

## Runtime boundary

`Open Urban Design QGIS.command` creates `.urban_design_runtime/` and uses only
the project-local `urban-design` QGIS profile. It copies the pinned qgis-mcp
plugin and the companion plugin into that profile, writes a launch-scoped
session token to child-process environments, starts the loopback bridge, and
stops that bridge when QGIS exits. It does not select or edit the default QGIS
profile and does not load historical SiteProposal or DesignBoundary records.

The Urban Design bridge binds to `127.0.0.1:8788` by default. Port
`127.0.0.1:8787` is reserved for the Hermes Web UI: the launcher and the
standalone bridge entry point reject `URBAN_DESIGN_BRIDGE_PORT=8787`, and the
plugin rejects a configured bridge URL targeting port 8787. Before changing
any runtime state, the launcher checks 8788 with `lsof`; if another process is
listening it reports the owner and exits without killing it or silently
choosing another port. A launch-scoped token and the same explicit bridge URL
are passed to the companion plugin, so a second launch cannot silently reuse
the first launch's session.

The project `.venv` remains the source of the pinned qgis-mcp 0.14.0 and
Ladybug/Honeybee packages. The launcher uses a host Python that provides
FastAPI and Uvicorn for the bridge, then adds the project runtime's
site-packages and an optional Radiance installation to the bridge child only.
This avoids loading Python 3.12 packages into QGIS's bundled Python 3.9
process. Set `URBAN_DESIGN_BRIDGE_PYTHON` or `URBAN_DESIGN_RADIANCE_ROOT` when
the host defaults are not suitable.

## M2-A02-R02 georeferenced project repair

The dedicated project now loads the typed configuration in
`config/rotterdam-m4h-anchor.json`. Its EPSG:28992 viewport is derived from the
retained M2-R05 v4 source-backed M4H viewport and is labelled
`DRAWING_LOCATION_GUARD_ONLY`; it is not a Site or DesignBoundary. The retained
GeoJSON context is loaded as the read-only, attributed
`NON_AUTHORITATIVE_DRAWING_CONTEXT` layer. Its bytes, source-record hash, and
anchor source hash are checked before the launcher starts the bridge. The
context is excluded from capture and is never registered as an analysis
snapshot.

Both the plugin and the backend fail closed when the project anchor or context
is unresolved. The plugin checks project CRS, finite canvas/geometry bounds, and
the configured locality for immediate feedback. After QGIS MCP export, the
backend independently checks the EPSG:28992 area of use and the configured
locality before `StudyAreaConfirmationService` can write state. The old nested
`.urban_design_runtime/.urban_design_runtime/study-area-draft.gpkg` is retained
as historical input; new drafts are created beside the project at
`.urban_design_runtime/study-area-draft.gpkg`.

## M2-A02-R03 visible dedicated QGIS lifecycle

The macOS QGIS-LTR installation does not provide a verified concurrent GUI
instance boundary. Directly starting a second QGIS binary can load the
isolated project, profile, context, and MCP socket while macOS continues to
show an unrelated existing QGIS window. A process and a successful socket
probe therefore do not establish a usable designer-facing window.

The launcher now uses a safe single-instance preflight. It detects any QGIS
process before creating the isolated profile, generating a session token, or
starting the bridge/MCP children. It fails with an instruction to save and
close every existing QGIS window, then retry the launcher. It never closes,
reuses, modifies, or cleans up the detected QGIS process. Repeated launcher
invocations fail at this same preflight and cannot create hidden bridge or
MCP children. The repaired project has an explicit
`rotterdam-m4h-pilot-project` project name and title for the later visible
window check.

The R03 inspection first found an unrelated QGIS instance. After it was saved
and fully closed, the launcher was reopened and the visible window title was
verified as `rotterdam-m4h-pilot-project — QGIS`. The intended M4H polygon was
drawn, exactly one feature was selected, and `Use as Study Area` completed
through the launch-scoped bridge. No unrelated QGIS process was stopped or
reused.

## Companion plugin

The toolbar exposes `Draw Study Area`, `Use as Study Area`, and a live status
refresh. Draw creates or activates the persistent GeoPackage layer `Study Area
Draft` with EPSG:28992 and enters `QgsMapToolDigitizeFeature` polygon capture.
The completed feature is added to that layer's edit buffer. Use commits only
that layer, requires one saved selected feature, checks non-empty valid polygon
geometry, and posts through `QNetworkAccessManager` without blocking QGIS.

The capture body is exactly:

```json
{
  "instance": "<absolute QGIS project instance>",
  "layer_id": "<QGIS layer id>",
  "fid": 7,
  "actor": "qgis-designer",
  "request_id": "<UUID>"
}
```

It contains no geometry, output path, target CRS, or expression. The bridge
rejects any extra field before QGIS is contacted.

## Bridge API

`GET /api/v1/integrations/status` reports separate typed readiness for the
FastAPI bridge, qgis-mcp server/plugin, and Ladybug components. qgis-mcp is
`READY` only when the socket probe reaches QGIS and both reported versions are
exactly `0.14.0`. Ladybug statuses describe package imports and required
Radiance executable paths only; they do not run a climate fixture.

`POST /api/v1/projects/{project_id}/study-area/capture` accepts only the five
selection identifiers above. The backend verifies the active layer, dedicated
layer name, vector polygon type, EPSG:28992 metre units, one selected FID, and
FID equality. It then generates a path under the controlled artifact root and
the fixed expression `$id = <non-negative integer>`, calls only the bounded
`export_layer` command, re-reads the GeoJSON, canonicalizes and validates it,
registers the immutable Artifact, and delegates the atomic versioned state
transition to `StudyAreaConfirmationService`.

The typed response includes the StudyArea ID/version, artifact and geometry
hashes, `EPSG:28992`, metres, planar area in square metres, confirmation and
activation event IDs, and ledger references. A repeated request ID returns the
original response without another QGIS export. Reusing a request ID with a
different fingerprint is rejected. A connection loss after dispatch is
returned as `OUTCOME_UNKNOWN` with automatic retry disabled; reconciliation is
required before a later attempt.

The bridge's QGIS command allowlist contains only `ping`, `get_plugin_info`,
`get_active_layer`, `get_layer_info`, `get_selection`, and `export_layer`.
Arbitrary code, processing, SQL, and batch routes are not reachable through
this slice.

## Verification state

The automated M2-A02 bridge, launcher/plugin, and M2-A02-R02 georeference
suites, the complete project pytest suite, and Python `compileall` are release
checks for this implementation. Those automated checks pass. The prior v4
capture remains byte-preserved historical evidence because its coordinates are
outside the declared EPSG:28992 area of use. The visible v5 capture is now
independently verified in the live state store: it is active and
`CONFIRMED_FOR_EXPLORATION`, its bbox is inside the configured M4H anchor, and
its artifact and canonical geometry hashes match the persisted records. The
v4 and v5 StudyArea records are linked by an append-only `SupersedeStudyArea`
event. The two historical blocked v4 M2-A03 packages were marked stale by
append-only ledger events; their package bytes were not rewritten and no
source request was run by M2-A02.

The final process check shows Hermes PID 12407 owning
`127.0.0.1:8787`, Urban Design bridge PID 11993 owning
`127.0.0.1:8788`, and the dedicated QGIS PID 12092 owning
`127.0.0.1:9876`. Hermes' cwd and runtime remain under `~/.hermes`; the
launcher's cleanup scope is project-local and did not target PID 12407. A
read-only HTTP check returned `200 OK` and the Hermes WebUI HTML on 8787. The
bridge root returned its expected JSON `404`; an authenticated status request
using the launch-scoped token returned `200 OK` with Backend, QGIS MCP,
Ladybug, Anchor, and Context all `READY`. The token was not printed. A
read-only accessibility query returned the visible title
`rotterdam-m4h-pilot-project — QGIS`. The launcher rejects both `8787` and
numeric aliases such as `08787` before touching the runtime, and refuses an
occupied 8788 without killing or borrowing its owner.

No PDOK, OSM, origin, destination, network, EPW, accessibility, morphology,
Space Syntax, climate analysis, or React frontend was started by M2-A02-R03.
The two historical v4 M2-A03 packages remain source-free and are marked stale
against v5. A later M2-A03-R05 run was separately authorized; its r03 package
failed closed on live EPW chronology before any source snapshots were
published.
