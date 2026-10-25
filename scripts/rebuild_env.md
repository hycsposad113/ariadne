# Environment Reconstruction Guide (W6 Precursor Lane F5)

This document specifies the exact runtime dependencies, versions, external binaries, and steps required to reproduce the Rotterdam M4H Urban Design platform environment from a clean system.

---

## 1. Runtime Specifications

| Runtime / Tool | Version | Architecture / Platform | Location / Source |
|---|---|---|---|
| **Python** | `3.12.13` | macOS `arm64` | Pyenv / system; project virtualenv at `.venv` |
| **Node.js** | `v22.22.3` | macOS `arm64` | Node / nvm; web workspace at `web/` |
| **npm** | `10.9.2` | macOS `arm64` | Bundled with Node |
| **Radiance** | `6.0.2` (`2026-02-02 LBNL 6.0.c1700d56cc`) | macOS `arm64` | `~/.local/share/urban-design-runtimes/radiance-6.0.2-arm64` |
| **QGIS LTR** | `3.40.5-Bratislava` | macOS `x86_64` (Rosetta) / `arm64` | `/Applications/QGIS-LTR.app` |
| **PST (Place Syntax Tool)** | `3.3.1` | macOS `arm64` | KTH / Chalmers (`libpstalgo.dylib`), QGIS profile |
| **QGIS MCP Server** | `0.14.0` | Python | Installed in `.venv/bin/qgis-mcp-server` |

---

## 2. Radiance 6.0.2 (arm64) Setup

1. **Official Archive**:
   - URL: `https://github.com/LBNL-ETA/Radiance/releases/download/rad6R0P2/Radiance_c1700d56_OSX_arm64.zip`
   - SHA-256: `329ca788c6cedc641ad47577ce985ae16ee291acb1d5d02d7995192d58118cf0`
   - File Size: `8,202,089` bytes

2. **Extraction Location**:
   ```bash
   mkdir -p ~/.local/share/urban-design-runtimes
   unzip Radiance_c1700d56_OSX_arm64.zip -d ~/.local/share/urban-design-runtimes/radiance-6.0.2-arm64
   ```

3. **Environment Variables**:
   ```bash
   export RAYPATH="$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib"
   export PATH="$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/bin:$PATH"
   ```

4. **Verification**:
   ```bash
   rtrace -version
   # Expected: RADIANCE 6.0.2 2026-02-02 LBNL (6.0.c1700d56cc)
   ```

---

## 3. Python Environment Setup

1. **Create Virtual Environment**:
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install Locked Dependencies**:
   ```bash
   pip install -r requirements.lock
   pip install -e .
   ```

3. **Core Dependencies Summary**:
   - `ladybug-core`: `0.44.59`
   - `ladybug-geometry`: `1.35.4`
   - `ladybug-radiance`: `0.2.12`
   - `honeybee-core`: `1.64.68`
   - `honeybee-radiance`: `1.66.288`
   - `pydantic`: `2.13.5`
   - `shapely`: `2.1.2`
   - `pyproj`: `3.7.2`
   - `fastapi`: `0.141.1`
   - `pytest`: `9.0.2`

---

## 4. Web Frontend Setup

1. **Prerequisites**: Node.js `v22.22.3`
2. **Installation** (only in primary repo, never in worktrees with symlinked node_modules):
   ```bash
   npm --prefix web ci
   ```
3. **Run Tests**:
   ```bash
   npm --prefix web run test
   ```
4. **Build & Lint**:
   ```bash
   npm --prefix web run build
   npm --prefix web run lint
   ```

---

## 5. Verification Commands

1. **Environment & Sunlight Tests**:
   ```bash
   PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
   RAYPATH=$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/lib \
   PATH=$HOME/.local/share/urban-design-runtimes/radiance-6.0.2-arm64/bin:$PATH \
   pytest -q -p no:cacheprovider tests/test_environment_*.py tests/test_radiance_runtime.py
   ```

2. **Full Frontend Verification**:
   ```bash
   npm --prefix web run test
   npm --prefix web run build
   npm --prefix web run lint
   ```
