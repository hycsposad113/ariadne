# Test report — v1.0.0 (2026-10-25)

Run on the integrated release branch before merge (macOS, Python 3.12, Node 24), with the runtime data packs present locally.

| Suite | Command | Result |
|---|---|---|
| Web unit tests | `npm --prefix web run test` | 513 passed (80 files) |
| Web build | `npm --prefix web run build` | passed |
| Web lint | `npm --prefix web run lint` | 0 errors (warnings only) |
| Backend | `PYTHONPATH=src pytest -q --continue-on-collection-errors` | 3,261 passed, 5 skipped; 41 failed and 11 errors in legacy tests that read historical run directories or temporary folders no longer present, plus 2 modules needing optional simulation packages (`honeybee_energy`, `ladybug_comfort`) |
| Backend, release-critical subset on the merged main | syntax receipts, fabric plans API, database guard, judgement/proposal services, Ariadne MCP, model profiles, climate figures | 231 passed |
| Browser walkthrough | `web/e2e/platform_walkthrough_1017.py` | 6/6 flows PASS (massing editing, road editing, compare/generate, human-decision dialog; English and Traditional Chinese) |
| Browser fabric comparison | `web/e2e/fabric_compare.py` | PASS (English and Traditional Chinese) |
| Language consistency scan | five tabs × two languages, text + aria-label + title + placeholder | 0 mixed-language strings (identifiers and source data excluded) |
| MCP stdio check | 15 tools listed and called with `language` | PASS |
| Live judgement | J-CLIMATE via codex-cli, English | VALIDATED |

Without the runtime data packs (not included in this repository) more backend tests fail because their inputs are absent; see the README section "About data packs".
