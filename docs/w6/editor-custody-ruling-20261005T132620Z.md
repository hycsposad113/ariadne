# W6 editor custody ruling

Author: Codex / OpenAI gpt-6.1-sol(low).
Status: CUSTODY_REVIEW_RECORDED; not milestone acceptance.

Custody commit: `06d6a895e5e6435738f50796840c725d4be6583c`.
Current integration baseline: `8aff49459c57d981767733034e40c502c000e5cf`.

The six files were preserved as pre-existing work, not authored by Grok as G4. The retained CP0 report `docs/w6/week6-test-baseline-r01.md` predates the custody commit and identifies the R02/PNG work as Codex CP0. Syntax changes are consistent with the earlier CP8 bounded correction (explicit network-mode evidence, never inference from radius); git author metadata alone does not prove model provenance. Their inclusion is an independently reviewed adoption; same-provider inherited work still requires Claude's final review.

No bulk cherry-pick is approved by this ruling. Import reviewed content in a new Codex fix commit only after the frozen baseline completes. The original custody commit is preserved unchanged.

| File | Custody file SHA-256 | Ruling |
|---|---|---|
| `tests/test_site_proposal_rotterdam_v4.py` | `3a9b82a6e2f9dfd23d2c0c2be832d105a2d5b0e77dc2948e4fcce97b571668b7` | REJECT_AS_IS: replaces PNG equivalence with nonblankness; retain original and require decoded-pixel equivalence evidence |
| `tests/test_week4_repair_integrity.py` | `841866fefa896a4137b545e396f3d57ea82f872825783bb71d55d5a0b40805d9` | REVIEWED_FOR_CONTROLLED_IMPORT: focused verification still required before integration |
| `tests/test_syntax_context_api.py` | `51cfa5d435cd812dc97409de28588a30f27d2fa37dea420432723ccefa1e8436` | REVIEWED_FOR_CONTROLLED_IMPORT: focused verification still required before integration |
| `web/src/components/SidebarSyntax.tsx` | `62976ef16730faf5e152c1d7a02346d0989acc1f6bdfc691be16618c86cd873f` | REVIEWED_FOR_CONTROLLED_IMPORT: focused verification still required before integration |
| `web/src/components/SidebarSyntax.test.tsx` | `3584f73b4a50d378884b952748ed96cdc746abfc4cafd7ff106b267a45eea9af` | REVIEWED_FOR_CONTROLLED_IMPORT: focused verification still required before integration |
| `web/src/i18n/conditions.ts` | `3dbedd5939c4bd8bb89ae4abf421d7854b4beac0cec0f19c171a1ebfbc399815` | REVIEWED_FOR_CONTROLLED_IMPORT: focused verification still required before integration |

## Review evidence

- R02 uses an explicit approved read-only root and hash-pinned immutable parent manifest, copies SQLite through `mode=ro` plus SQLite backup, and performs mutation tests on copies. It removes an unavailable-worktree skip rather than suppressing the check. Import must include `tests/fixtures/week4_r02_readonly/fixture-manifest.json` and retained static fixture content, with their hashes reviewed. Missing or altered approved parents must fail.
- Syntax API negative test asserts the manifest's exact 3000 m display contract rejects 10000 m, separately from analysis radius.
- Sidebar mode resolution requires explicit typed layer/plan agreement on ID, metric and radius, and displays unknown on conflicts; tests cover missing, invalid and conflicting modes. Four translations support these states.
- PNG custody edits verify CRC, zlib, dimensions and nonblankness, but remove comparison against the canonical raster. A changed visible map could pass. This violates the no-weakened-assertions guardrail and is rejected as-is. Structural validation may be retained only alongside a justified equivalence contract; no source or historical evidence will be altered to obtain PASS.

## Current boundary

No production source file, formal database, ledger, StudyArea, weather bytes, QGIS or Hermes changed by this ruling. C0 pytest/Vitest/build/lint remain in progress in the separately recorded runner. No full-suite PASS or deployment readiness is claimed.
