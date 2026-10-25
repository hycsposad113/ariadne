# Morphology Preview Catalog v1

This work package exposes the already-generated morphology outputs through a pinned, read-only catalog. P1 introduced the typed catalog and standalone viewer; P2 mounts a GET-only preview router into the workspace FastAPI app without changing the existing persisted Scenario routes; P3 mounts the viewer as a separate `ScenarioStudio` tab alongside editable scenarios. The new tab is an exploratory artifact surface, not a formal Scenario workflow.

Every candidate remains `UNAPPROVED_PREVIEW`; `human_decision_created` is false. The viewer offers image viewing and download only; it does not offer accept, edit, generate, import, or climate actions. A preview is not a Scenario, a design approval, a preservation decision, or a climate input. No overall winner is calculated.

## Source verification

The configured source is the immutable `run-01` bundle. Its manifest pin is `14b2378ca16f79b84ce8fd60fbe6aa81ff11e7cccdec875034be5740e6b37452`, and its comparison artifact hash is `55cce34ae134bea87799694ac296654ac17631bb8bb39a869be0bfdf9229f2bd`.

A fresh local HTTP smoke loaded 10 candidates (five A and five B), verified all 52 manifest entries, and fetched all 30 plan, axonometric, and geometry assets through the GET API. Every served asset byte sequence and ETag matched the pinned source. The existing Scenario listing was read-only. The run used a disposable copy of the retained SQLite database; the source database hash and its table counts remained unchanged. The 16 input references are preserved with their source hashes. The fresh receipt and process cleanup identities are in [http-smoke.json](../../out/openai-preview-browser-20260930T092415Z-6a79d76b-8ff8-4ca3-bbfc-963383dc365d/smoke-fixed/http-smoke.json).

The comparison's original unknowns remain unknown: run creation time and generator commit are null, and the retained-building data keeps its confidence and unknown-floor status. No provenance value was inferred from file timestamps or the current Git revision. Detailed hashes and byte counts are in [`real-source-smoke.json`](../../artifacts/preview-catalog-v1/real-source-smoke.json).

## Catalog and API boundary

`preview_catalog.py` accepts a configured root and pinned manifest SHA-256. It rejects pin drift, unsupported or extra schema fields, duplicate JSON keys, non-finite numbers, identity/status mismatches, non-EPSG:28992 or invalid geometry, missing or corrupt assets, unsafe paths, and symlink traversal. Each displayed metric is taken from its deterministic `metrics.json` field and checked against the `comparison.json` summary; the warning list must also match the metrics artifact so the unknown-floor/partial-FAR caveat cannot disappear. It validates assets once and serves the same verified bytes retained in the catalog, avoiding a later path reopen between verification and response. `UNKNOWN` retained-building floor status requires both `floor_count` and `height_m` to be null. Geometry coordinates must fit the configured EPSG:28992 ranges and the candidate StudyArea bounding box, and `metrics.building_count` must equal the number of `generated_building` features.

`preview_api.py` exposes only these GET routes:

| Route | Behavior |
| --- | --- |
| `GET /api/v1/morphology/previews` | Explicit `DISABLED` response when unconfigured; otherwise the pinned A/B catalog. A configured missing or invalid bundle returns 503 with a safe error category. |
| `GET /api/v1/morphology/previews/{intensity}/{strategy_id}` | Typed detail for a known candidate. |
| `GET /api/v1/morphology/previews/{intensity}/{strategy_id}/assets/{kind}` | Service startup validates the configured source and freezes its verified bytes in memory. This route serves those bytes; source drift after startup is intentionally not detected and does not return 409. |

On a successfully verified configured startup, the catalog listing and each
detail response include the same UTC `verified_at_utc` timestamp and
`source_reverified: false`. A disabled catalog returns a null verification time
and `source_reverified: false`. The preview UI displays `來源於 {時間} 驗證，啟動後未再驗證`.
For a configured source that fails startup validation, catalog and detail
requests return 503 with the safe error category (for example,
`hash_mismatch`, `missing_file`, or `schema_error`); the UI displays that
category instead of treating the response as an empty catalog.

### Commander Decision: Source Drift Policy

As decided by the Founder (2026-09-30), source verification and byte freezing occur strictly at service startup. The service retains verified asset bytes in memory and serves those bytes directly. After startup, the server intentionally does not detect filesystem drift and does not return HTTP 409 Conflict. A service restart performs verification again; if that validation fails, the entire catalog is unavailable with HTTP 503 and a safe error category. This accepted policy replaces the exploratory `integrity drift → 409` behavior in the Task P2 table of `docs/superpowers/plans/2026-09-30-preview-and-ui-zh.md`.

The router has no `ProjectStateStore` dependency and contains no write routes. Unknown candidates and asset kinds return 404. The serialized API does not include source filesystem paths.

## Isolated demo

The demo harness binds only to `127.0.0.1` and asks the OS for an available port by default:

```sh
MORPHOLOGY_PREVIEW_ROOT=/path/to/run-01 \
MORPHOLOGY_PREVIEW_MANIFEST_SHA256='replace-with-64-character-manifest-hash' \
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/preview_catalog_demo.py --port 0
```

Alternatively, pass `--root <bundle-directory>` and `--manifest-sha256 'replace-with-64-character-manifest-hash'` directly.

Use the emitted API URL as the Vite demo's `api` query parameter. From `web/`, run `npm run dev -- --host 127.0.0.1 --port 0`; open `preview-catalog-demo.html?api=<emitted-api-url>`. The demo server enables GET-only CORS for numeric loopback ports so a Vite tab can call the separately bound API. This CORS middleware is confined to the demo harness.

The viewer groups the ten cards by assumption set and labels A/B as assumptions, not quality ranks. It shows the source plan and axonometric PNGs and an EPSG:28992 geometry view using the actual geometry bounds. Retained-feature confidence, unknown floors, generator-reported metrics, provenance gaps, and pinned hashes remain visible. The new Playwright verifier exercised the mounted React application in real headless Chromium. It clicked all five main sidebar tabs and AI model settings at 1280, 1440, and 1920 viewport widths, then opened the preview tab and rendered five A plus five B candidates at each width. Before the reviewed P0 patch, the fifth sidebar tab extended beyond the 330 px sidebar at all three widths; after the patch, all six controls stayed within bounds and no document overflow was measured. At 1440 px, Chromium visibly rendered a B plan, its axonometric image, and its geometry; the standalone viewer screenshots show the actual plan and axonometric images. Downloaded plan and axonometric bytes matched their pinned source files. Browser-served assets matched source bytes and SHA-256 ETags, and the walkthrough made no external or mutating API requests.

The browser API served the real pinned preview catalog. Site-context, scenario-list, and AI-profile status were deterministic local UI fixtures; this is visual integration evidence, not formal-runtime or database acceptance. The before/after receipts, viewport bounds, request logs, and screenshot hashes are in [before-final](../../out/openai-preview-browser-20260930T092415Z-6a79d76b-8ff8-4ca3-bbfc-963383dc365d/before-final/receipt.json) and [after-final](../../out/openai-preview-browser-20260930T092415Z-6a79d76b-8ff8-4ca3-bbfc-963383dc365d/after-final/receipt.json). The reviewed App-only P0 patch and before/after file hashes are recorded in [reviewed-p0-app-integration.json](../../out/openai-preview-browser-20260930T092415Z-6a79d76b-8ff8-4ca3-bbfc-963383dc365d/reviewed-p0-app-integration.json).

## P2/P3 workspace integration

The workspace app includes the preview router with paired `morphology_preview_root` and `morphology_preview_manifest_sha256` settings. The launcher accepts the corresponding paired CLI flags. With both omitted the catalog is explicitly `DISABLED`; configuring only one is rejected; a configured invalid bundle is reported as 503 rather than an empty catalog. The router has no `ProjectStateStore` dependency and registers only GET routes. The existing Scenario API routes remain unchanged.

P3 displays the catalog under a separate `既有探索預覽` tab in `ScenarioStudio`. The existing editable-scenario tab remains separate. The preview UI labels every item `UNAPPROVED_PREVIEW`, labels A/B as assumption sets, displays retained-building confidence and unknown floors, known-part FAR, provenance gaps and pinned hashes, and provides plan/axonometric viewing and download plus the EPSG:28992 geometry view. It exposes no preview acceptance, editing, generation, import, or scenario-write action. Errors are distinct from an empty catalog.

### Source drift policy

Source verification and byte freezing occur when the workspace app is constructed for service startup. The server retains verified asset bytes and serves those bytes directly. After startup, filesystem drift is intentionally not detected and does not return HTTP 409 Conflict; the UI shows the startup verification time and states that the source has not been reverified since startup. A restart revalidates the source; failure makes the whole catalog return 503 with its safe error category. This Founder decision replaces the exploratory P2 plan's 409 behavior. It does not change the formal project architecture or authorize an automatic restart/reload.

The paired root and manifest pin have no default research source. Both absent means disabled. The configured source remains read-only, and GET requests do not create or update Scenario, ledger, or HumanDecision records.

This worktree integration is available for review only. It does not claim merge to main, production-runtime activation, import into the formal Scenario table, deployment, or milestone acceptance.

## Verification

Fresh focused checks on the integration worktree: 49 Python tests passed across preview integration, morphology preview API, catalog, and Scenario API; 18 Vitest tests passed across the preview catalog, `ScenarioStudio`, and AI model settings; TypeScript and Vite production build passed with the existing large-chunk advisory. Python and browser-verifier syntax checks and `git diff --check` passed. Pytest emitted one existing AnyIO `BlockingPortal` deprecation warning.

The real-source HTTP receipt is linked above. True Chromium evidence, bounds, request counts, exact-byte/ETag checks, downloads, and local screenshot hashes are linked above. All app preview routes remain GET-only; the UI leaves each candidate `UNAPPROVED_PREVIEW`, with no accept, edit, import, generate, or scenario-write action. The test harness used dynamically selected loopback ports and stopped only direct processes it spawned. No service was started on 5195, 8787, or 8788, and no formal runtime or user browser page was used.
