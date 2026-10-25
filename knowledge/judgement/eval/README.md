# Judgement evaluation

The fixed suite contains eight cases from the J-SITE, J-COMPARE, and J-CLIMATE specifications. Each case points to a hash-pinned input snapshot and declares the intended stance, parameter-family, forbidden-content, and claim expectations. Snapshot provenance and source files are recorded in [manifest.json](manifest.json) and [source-manifest.json](source-manifest.json).

Run the deterministic offline plumbing check from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python scripts/judgement_eval.py
```

This verifies snapshot/source hashes, deterministic assembler output, case shape, input ablations, and `core.validate` wiring. Its fixed card is not a model result. Semantic expectations and consistency are explicitly **not evaluated** by this default run.

An explicitly authorized Commander can run a real profile through `JudgementService` and the durable `ModelProviderRouter`. First configure that profile in `config/model-providers.json` with `enabled: true` and `use_ariadne_persona: true`. The selected profile must not require a Keychain credential; this runner does not access Keychain or read environment-held API secrets. A profile that is disabled, lacks the Ariadne persona setting, requires a Keychain secret, or is unavailable is reported as blocked with no fallback. For example, `codex-cli` is the currently configured Ariadne CLI profile.

Replace the paths and project id with the intended existing project database, a separate judgement database path whose parent directory exists, and its project id. This command dispatches real model requests and must only be run by a Commander with the stated project authorization:

```sh
PROJECT_AI_AUTHORIZED=1 ARIADNE_LIVE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  .venv/bin/python scripts/judgement_eval.py \
  --provider-profile codex-cli \
  --project-db /absolute/path/to/existing-project-state.sqlite3 \
  --judgement-db /absolute/path/to/separate-judgement-runs.sqlite3 \
  --project-id YOUR_PROJECT_ID \
  --confirm-live
```

Two-profile comparison additionally requires a second distinct, enabled profile with `use_ariadne_persona: true`, plus `--comparison-provider-profile PROFILE_ID`. Each profile runs through a single-profile router with no fallback. The runner stops that profile's case loop after any non-`VALIDATED` result; `OUTCOME_UNKNOWN`, provider-auth, and provider-payment states are retained and not retried across cases. The report compares stance, parameter-family sets, and source-reference sets only when both profile results validate. Otherwise the case is `NOT_COMPARABLE`, with a null stance-match field. Claim correctness remains a human review task.

Live execution was not performed while this suite was authored. No real model consistency result is implied by fixture passes.
