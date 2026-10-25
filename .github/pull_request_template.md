## Description

Provide a summary of the changes introduced in this pull request and link any relevant issues.

Fixes #(issue)

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Documentation update
- [ ] Architectural / refactoring change

## Constitutional & Governance Checklist

- [ ] **No autonomous decisions**: This change does not allow AI models to create or approve `HumanDecision` events.
- [ ] **Deterministic calculation**: All GIS, geometry, and simulation values originate from deterministic tools or identified datasets.
- [ ] **Zero secrets**: No API keys, credentials, or private passphrases are introduced into git history, tests, or state.
- [ ] **Validation adherence**: Output schemas and type models are updated and validated.

## Testing & Quality Assurance

- [ ] Backend tests pass: `PYTHONPATH=src pytest -q`
- [ ] Frontend tests pass: `npm --prefix web run test`
- [ ] Frontend build succeeds: `npm --prefix web run build`
- [ ] Linter passes: `npm --prefix web run lint`
