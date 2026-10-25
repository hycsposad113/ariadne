# Contributing to Ariadne

Thank you for your interest in contributing to **Ariadne**! We welcome bug reports, documentation improvements, architectural critiques, and pull requests.

---

## The Core Constitutional Boundary

Before writing or proposing any code, please review [`AGENTS.md`](AGENTS.md):

> **LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.**

Any contribution that:
- Allows an AI agent to automatically execute or sign a binding `HumanDecision`,
- Uses an LLM to hallucinate or estimate GIS coordinates, geometry, or simulation metrics,
- Bypasses schema validation, or
- Embeds API keys or credentials in code or repository state

will be rejected immediately.

---

## Development Setup

### 1. Prerequisites
- **Python 3.12**
- **Node.js**: Use a Node version supported by the full lockfile: `^22.22.2`, `^24.15.0`, or `>=26.0.0`; otherwise adjust the dependency set and verify it.
- **Git**

### 2. Environment Setup
```bash
# Clone the repository
git clone https://github.com/hycsposad113/ariadne.git
cd ariadne

# Set up Python virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install from a portable lockfile that pins a published package or repository revision.
# Note: The current `requirements.lock` contains a machine-local path and is not usable from a clean clone.
pip install -r requirements.lock
pip install -e .

# Set up frontend
cd web
npm install
cd ..
```

### 3. Initialize Decision Passphrase
```bash
python -m urban_design.decision_key init
```

---

## Coding Standards & Formatting

- **Python**: Follow PEP 8 and strict typing with Pydantic models. Type hints are mandatory on public functions and endpoints.
- **TypeScript / React**: Use the configured Oxlint command: `npm --prefix web run lint`. Prettier and ESLint are not configured in this snapshot.
- **Git Commits**: Use descriptive commit messages following the Conventional Commits specification (e.g., `feat:`, `fix:`, `docs:`, `test:`).

---

## Running Tests

All automated tests must pass before submitting a pull request:

```bash
# 1. Run Python backend test suite
PYTHONPATH=src pytest -q

# 2. Run React/TypeScript test suite
npm --prefix web run test

# 3. Check web build & linting
npm --prefix web run build
npm --prefix web run lint
```

---

## Submitting a Pull Request

1. Fork the repository and create your feature branch: `git checkout -b feat/your-feature-name`.
2. Commit your changes with clear, descriptive messages.
3. Ensure all tests pass locally.
4. Open a pull request against the `main` branch using the provided [Pull Request Template](.github/pull_request_template.md).
5. The maintainer will review your submission against the architectural gates and constitutional rules.
