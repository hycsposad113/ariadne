# RENDER-C01 current-v1 baseline attempt

Status: CURRENT_VERSION_REPRODUCIBILITY BLOCKED; NOT_RELEASE_ACCEPTANCE.

Canonical v4 SVG and historical PNG/assertions are preserved. Historical mapping:
`tests/test_site_proposal_rotterdam_v4.py::test_offline_rebuild_matches_canonical_artifacts_across_store_schema` → `HISTORICAL_BLOCKED`.
Only this node is within the Founder policy classification; all other failures remain release blocking. Classification does not skip execution or turn the historical failure into PASS.

Version `qgis-qt-current-v1` rendered the canonical SVG in two independent QGIS Python/Qt subprocesses. Both PNGs are 420003 bytes with SHA-256 `f9a40d3040025a79ba6a6e43461c8425c854f71e6f515afc422beefe3a87ed7c`.
The evidence package is `/private/tmp/q5-renderer-version-baseline-20261006-01/`; its exclusive manifest records parent SVG, helper/code hashes, exact commands, runtime, OS, DPI, and loaded Qt/QtSvg/libpng/zlib binaries.

Effective font binary paths and fallback mapping are unavailable through the observed QRawFont API. Resolved family/style is diagnostic only. Font identities remain null; current-version gate is typed BLOCKED. This is a retained baseline attempt, not a qualified fixed release baseline. Independent cross-provider review and Founder acceptance remain outstanding. Full-suite results are retained in the private report and must be read before any release recommendation.

No new dependencies or tracked PNGs. No W6 acceptance is claimed.
