# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-10-25

Initial public research submission for **IDEM307 Generative AI and Design**, TU Delft (2026–27).

### Added
- **5-Stage Design Workflow**: Complete implementation of **Site**, **Conditions**, **Generate**, **Compare**, and **Refine** stages in React 19 + TypeScript.
- **QGIS 3 Integration**: Vector Study Area plugin transmitting selected layer ID and feature ID to the local bridge on `127.0.0.1:8788`, which reads and validates selected geometry via QGIS MCP, interoperating with the platform API (default `127.0.0.1:8789`, plugin default `127.0.0.1:8795`).
- **Authoritative Data Ingestion**: Runtime source consumption of previously prepared, verified local Dutch building footprints (PDOK BAG CC0) and street networks (OpenStreetMap ODbL) from a source package (with separate source-backed 3DBAG height joins).
- **Multi-Fabric Morphological Generation**: Deterministic road-network, block-parcelation, and massing-typology generators producing four distinct schemes:
  - Harbour grain (`harbour_grain`)
  - Closed block extension (`closed_block_extension`)
  - Courtyard islands (`courtyard_islands`)
  - Landscape figure (`landscape_figure`)
- **Space Syntax Analysis**: Pinned Place Syntax Tool (PST 3.3.1) adapter calculating Normalised Angular Integration (NAIN) and Choice (NACH) across 800 m, 2 km, and 10 km radii.
- **Microclimate Simulation Matrix**:
  - E1 Sunlight Hours (Winter solstice, equinox, summer solstice via Radiance ray tracing)
  - UTCI Heat Stress (Outdoor comfort modeling at peak 14:00 summer conditions)
  - E2 Incident Solar Radiation ($kWh/m^2$ on facades and ground)
  - E3 Energy Use Intensity (EUI) and E4 Thermal Mass dampening via EnergyPlus ideal loads
  - E5 Pedestrian Wind Screening (Coarse-mesh CFD in Docker with OpenFOAM 2506 across 4 prevailing wind sectors)
- **Ariadne AI Agent Engine**: Specialized judgement skills (`J-SITE`, `J-MORPH`, `J-COMPARE`, `J-CLIMATE`) outputting schema-validated Judgement Cards (`judgement-card.schema.json`).
- **Contestability & Revision Loop**: Interactive Agree/Contest/Supplement options and `R-PROPOSE` parametric revision proposals (`proposal.schema.json`) with dry-run previews and differential re-judgements.
- **HumanDecision Passphrase Gate**: Cryptographic scrypt passphrase hashing (`~/.config/urban-design/decision-key`, mode 0600) ensuring only human designers can execute binding decisions.
- **Model Provider Flexibility**: Configuration profiles for Codex CLI (`gpt-6-luna`), Claude CLI, OpenAI-compatible APIs (macOS Keychain key retrieval), and local Ollama.
- **Model Context Protocol (MCP) Server**: Stdio MCP server (`python -m urban_design.ariadne_mcp`) providing 15 tools for external agent environments without approval capabilities.
- **Comprehensive Testing Suites**: Automated backend pytest and web Vitest test suites ensuring determinism, schema validity, and API resilience.
