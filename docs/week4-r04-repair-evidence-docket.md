# Week 4 R04 Repair Evidence Docket

**Task:** `WEEK4-R04-NARROW-REPAIR`  
**Task status:** `PASS` for the bounded R04 repair  
**Overall Week 4 status:** `INCOMPLETE`  
**Evidence package:** [`artifacts/week4-repair-r04/`](../artifacts/week4-repair-r04/)

## Scope and result

R04 replaces the active workspace API's double-countable OSM road-length card with a deterministic planar union of the retained, clipped OSM highway centerlines. It also removes remote Google Fonts dependencies and makes real-browser output paths explicit, temporary-root-safe, and non-overwriting. This is an implementation method repair for an observational card; it is not a planning rule, access finding, source approval, or human design decision.

The R03 card summed the clipped length of each of 140 ways and reported **8501.232713 m**. The R04 union reports **8496.540522 m**. The **4.692191 m** difference is coincident centerline geometry counted more than once by the way sum. The R03 Evidence Bundle and R03 package files remain unchanged.

The current road card is `osm_highway_unique_centerline_length`, method `r04-deduplicated-osm-centerline-union-v1`, with input hash `sha256:244c547b79129d155f24827133d41e9c615f5777fa2b42356f3008cd2603334c` and output hash `sha256:c1b054cdef2b4e47388cb2e2a86a71c597a94fbd4af30d244274979f397ab9fb`. Its lineage is the active Rotterdam M4H StudyArea v5 revision 1 (`sha256:3dedb804fa4f07f4c9570bcc64e68c8d576c03340455ab35fd4963bca52aa4f5`), EPSG:28992, source package `m2-a03-spatial-input-study-area-rotterdam-m4h-pilot-project-v5-spatial-r01` revision `spatial-r01`. Source Artifact and DatasetSnapshot IDs are recorded in the Evidence Card itself.

The metric describes the union length of clipped centerline geometry. It does not establish a connected pedestrian graph, public right of way, access permission, passability, safety, travel time, or source completeness beyond the retained acquisition.

## Validation evidence

- Focused backend and preserved Week 4 regression set: **42 passed**.
- Full pytest: **450 passed**, 7 deprecation warnings.
- Frontend Vitest: **3 passed**; TypeScript/Vite production build succeeded. Vite retained its bundle-size advisory.
- R04 integrity fault tests: valid manifest `PASS`; single-byte mutation, missing parent, and removed parent reference each `BLOCKED`.
- Real-browser E2E: Chromium 153 passed with API/web ports 50489/50509; both workspace revisions were written only to disposable SQLite. The authoritative database hash remained `6a89b1d3f94f387f180e1a454953d744ec36446081cd0a5b8c6e1b63576b7937` before and after.
- Browser output root was typed as `absolute_temporary` at `/private/tmp/week4-r04-browser-20260923`. Chromium made 0 non-local font requests and 0 external HTTP requests. Full report, screenshot, and downloaded figure hashes are retained under `browser/` in the package.
- Runtime authority state remained active StudyArea v5, project revision 6, workspace revision 2 DRAFT, ledger 183, 109 Artifacts, and 52 DatasetSnapshots. No new DatasetSnapshot was published.

The pre-R04 R03 verifier result remains recorded as `PASS_WITH_DECLARED_R02_SOURCE_PARENT_DRIFT`. Its current invocation is `BLOCKED` only on the R04 source/test parent drift listed in `archive-preservation.json`; all **30/30** frozen R03 package files still match their manifest entries. All **31/31** frozen R02 package files also match. The R02 historical parent drift is preserved, not repaired or concealed.

## Remaining gates

Week 4 remains incomplete. The QGIS GUI integration was not exercised; 2 km and 10 km Syntax layers remain uncomputed; live AI was not called; formal Site or DesignBoundary approval was not made; and no climate analysis was started. No PDOK, OSM, weather, candidate API, model, or QGIS MCP request was made for R04.

The first full-suite run exposed a historical R03 test that still expected the pre-R04 source hashes. The test now separately checks unchanged R03 package-file integrity and the explicitly expected source-parent drift. The final complete suite passed as recorded above; no R02 or R03 evidence-package file was edited.

## Package records

See `gate-status.json`, `package-record.json`, `request-log.json`, `road-metric-decision.json`, `test-results.json`, `integrity-fault-results.json`, `integrity-manifest.json`, and `browser/report.json` in the linked R04 package.
