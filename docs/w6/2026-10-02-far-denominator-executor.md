# FAR denominator executor record — PARTIAL, not accepted

Branch `wp/w6-far-land`, starting HEAD `b6ac2e0`. No authoritative DB/service/ConstraintSet schema/ledger changes. Direct session execution; no delegates or provider calls.

## Inventory and behaviour

| Path | Before | Current change / remaining work |
|---|---|---|
| morphology/metrics.py | GFA / caller-supplied design geometry area | Optional explicit FAR area; default unchanged, coverage geometry unchanged |
| morphology/strategies.py | Whole-site budget uses land_area (all non-buildable masks); zone budget uses zone area | Explicit Constraint denominator resolved centrally; land subtracts only water, EDA uses full design area; missing denominator preserves old budgets |
| morphology/validation.py | Whole-site metrics use inputs.land_area; zone uses intersection with land_area | UNCHANGED pending clarification of prohibition on validator edits. Explicit EDA checks and water-only land semantics still need wiring |
| approved_generation.py | Report claims EDA; lower bound uses EDA; known FAR uses candidate metric (site generator actually uses land geometry) | Propagates denominator; verified workspace BGT water artifacts supply water union; explicit report FAR/lower bound use selected area; label + area included; comparison hash binds selected basis/water geometry |
| morphology/dictionary_generator.py | Unapproved intensity catalogue budgets and known-part FAR use design minus water; no ConstraintSet input | Numerical preview behaviour unchanged; legacy/unspecified:land_area label added. No formal ConstraintSet route exists here |
| scenario_comparison.py | Reads persisted numbers; hash/rules/method compatibility | Preserves historical results, exposes per-scenario denominator, rejects mixed denominator metadata; never recalculates old evidence |
| scenario_editing_api.py | Synthetic fixture area; dashboard explicitly FIXTURE_ONLY | Numbers unchanged; legacy label and area added. No formal approved editing route exists |
| generation_context.py | Hardcoded EDA manifest | Reads ConstraintSet denominator and verified water union; label, area and water hash bind context digest |
| morphology/massing.py | Receives maximum GFA budget; no FAR division | No change required; budget comes from strategies |
| massing_adapter | No such module in this checkout | No implementation claim |
| scenario_api.py / ariadne_mcp/tools.py / qgis_facade.py | Fixture metrics, portfolio constants, or externally supplied area | Unchanged; no approved ConstraintSet FAR calculation here |
| web readiness / comparison / dashboard | Readiness hardcoded EDA; comparison missing basis; fixture dashboard missing area | en / zh-TW selected-basis label and area; legacy dashboard area disclosed |

New resolver `urban_design.far.resolve_far_denominator` accepts typed site context and optional legacy basis. It rejects missing water evidence, unsupported denominator, and nonpositive area. Empty verified BGT collection means zero water; overlapping/outside water is handled by union and geometry difference. Existing schemas and validators are unchanged.

Explicit `land_area` example: EDA 10,000 m², intersected water 2,000 m², GFA 8,000 m² => denominator 8,000 m², FAR 1.00, cap 0.8 => GFA limit 6,400 m². EDA basis => FAR 0.80 and GFA limit 8,000 m². This is a synthetic test example, not a site measurement.

## Remaining mandatory work

The user requested both formal FAR verification changes and no validator edits. A clarification was requested allowing only FAR measurement/comparison edits in morphology/validation.py. No answer has been received in this execution. Therefore this change is PARTIAL: formal validation still has legacy land semantics. The optional metrics denominator argument is not wired there. Do not accept or deploy this patch until this conflict is resolved, full/zone validation is wired, and a coupled generation-budget-validation-report test passes for both denominator modes. Current passing tests do not establish this missing integration.

Independent Claude review and Founder acceptance were not performed.

## Execution evidence and retries

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_far_denominator.py tests/test_approved_generation.py tests/test_generation_context.py tests/test_scenario_comparison.py tests/test_scenario_editing_api.py tests/test_morphology_metrics.py`: initial 42 passed, 4 failed (metadata local variable and older test mock); fixed code scope and test mock.
- Expanded same command with `tests/test_morphology.py tests/test_assumed_generation.py`: 72 passed, one existing Starlette deprecation warning.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_far_denominator.py tests/test_dictionary_generator.py`: 14 passed, including explicit known/unknown report basis test.
- `npm --prefix web run test`: EPERM writing shared node_modules/.vite-temp.
- Retry with `--configLoader runner --cache.dir /private/tmp/w6-far-vitest-cache`: rejected because Vitest deprecated --cache.dir.
- `npm --prefix web run test -- --configLoader runner --cache false`: 33 files, 201 tests passed.
- `npm --prefix web run build`: EPERM writing shared node_modules/.tmp tsbuildinfo.
- `web/node_modules/.bin/tsc -p web/tsconfig.app.json --tsBuildInfoFile /private/tmp/w6-far-app.tsbuildinfo` and node config equivalent: passed.
- Vite invoked from repository root via npm exec initially failed unresolved index.html; corrected working directory to web.
- From web: `../web/node_modules/.bin/vite build --configLoader runner --outDir /private/tmp/w6-far-web-dist`: passed (existing >500 kB chunk warning). Output outside project was not emptied.
- `git diff --check`: passed.

No files or directories deleted. Temporary scripts, build-info, test artifacts and build outputs retained in /private/tmp or system temporary directory; no cleanup. No server started. Existing untracked .venv untouched.

Final fresh combined Python run (the six original focused suites plus dictionary generator): **55 passed**, one Starlette deprecation warning, 10.08 s. Final diff whitespace check passed.

Git stage attempted only the 15 named changed/new files on wp/w6-far-land; sandbox returned `fatal: Unable to create '/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-03-freeze/index.lock': Operation not permitted`. No retry, no bypass, no commit. HEAD remains b6ac2e0; commit SHA unavailable. All edits remain unstaged.

## Round 2 — 2026-10-02 clarification applied

The Commander explicitly authorizes generation FAR/capacity validation edits. The earlier unresolved-validation section is historical and superseded by this round. `morphology/validation.py` now resolves whole-site FAR area through `far.py`; coverage, geometry, source and evidence-integrity validation remain unchanged. Zone FAR uses zone intersected with EDA, subtracting BGT water for explicit land_area. Legacy checks retain intersection with historical land geometry. Validation receipts expose whole-site and zone denominator labels/areas.

The coupled parameterized test calls the site generator using the same ConstraintSet for budget, candidate validation and approved report, for land_area, exploration_design_area and absent denominator. It asserts cap = 0.8 × selected area, candidate FAR = GFA / selected area, zone FAR and area, and report FAR/area. Known legacy report metadata now discloses the actual generator land basis; its historical number is unchanged. Unknown legacy lower bounds retain EDA. Explicit reports no longer claim EDA in their method text when land is selected.

Files changed across both rounds: src/urban_design/{far.py,approved_generation.py,generation_context.py,scenario_comparison.py,scenario_editing_api.py}; src/urban_design/morphology/{contracts.py,dictionary_generator.py,metrics.py,strategies.py,validation.py}; tests/{test_far_denominator.py,test_generation_context.py}; web/src/components/{GenerationReadinessPanel.tsx,ScenarioStudio.tsx}; web/src/i18n/scenarios.ts; this executor record. The inventory above remains applicable except validation is now wired as described here.

Fresh commands/results:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_far_denominator.py tests/test_morphology.py tests/test_approved_generation.py tests/test_generation_context.py tests/test_scenario_comparison.py tests/test_scenario_editing_api.py tests/test_morphology_metrics.py tests/test_dictionary_generator.py tests/test_assumed_generation.py`: **84 passed**, one Starlette deprecation warning, 70.41 s.
- After the final legacy report metadata correction: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/pytest -q -p no:cacheprovider tests/test_far_denominator.py tests/test_approved_generation.py`: **21 passed**, 2.92 s.
- `npm --prefix web run test`: EPERM on shared node_modules/.vite-temp. Allowed retry `npm --prefix web run test -- --configLoader runner --cache false`: **33 files / 201 tests passed**, 5.85 s.
- `npm --prefix web run build`: EPERM on shared node_modules/.tmp build-info. Allowed equivalent verification: `web/node_modules/.bin/tsc -p web/tsconfig.app.json --tsBuildInfoFile /private/tmp/w6-far-round2-app.tsbuildinfo` and `web/node_modules/.bin/tsc -p web/tsconfig.node.json --tsBuildInfoFile /private/tmp/w6-far-round2-node.tsbuildinfo`: exit 0. From web, `./node_modules/.bin/vite build --configLoader runner --outDir /private/tmp/w6-far-round2-web-dist`: exit 0, 1926 modules; existing chunk-size warning.
- `git diff --check`: exit 0.

Retries: initial new integration tests referenced a nonexistent result.generation_metadata attribute (6 passed / 3 failed); corrected to result.metadata, then reran the expanded suite. Frontend retries are recorded above. No files/directories deleted and no cleanup performed; all temporary outputs retained. No server, live AI, weather reads, authoritative DB, HumanDecision, or ledger mutation. Existing .venv untouched. Independent Claude review and Founder acceptance remain required.

Round-2 stage attempt: the explicit `git add` of the 16 named files failed with `fatal: Unable to create '/Users/jackhsieh/Downloads/TUD/Q5/project/.git/worktrees/w6-03-freeze/index.lock': Operation not permitted`. No retry or bypass; no commit SHA. Changes remain unstaged on wp/w6-far-land.
