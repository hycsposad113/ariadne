# Ariadne Documentation Index

Welcome to the technical documentation for **Ariadne**, an open-source, contestable AI design partner for early-stage urban design.

> [!NOTE]
> **Working Language Notice**: The public architectural guides, user guides, and integration specifications are written in **English**. Many internal development records, weekly milestone audits (e.g., `docs/w4-closeout/`, `docs/w7/`, `docs/w8/`), and Architecture Decision Records in [`docs/decisions/`](decisions/) are preserved in **Traditional Chinese (zh-TW)**, the working language used during the research semester at TU Delft.

---

## Core Guides

| Document | Description |
|---|---|
| [**Architecture Guide**](architecture.md) | In-depth breakdown of system architecture, component boundaries, SQLite event ledger, deterministic generation pipeline, microclimate simulation adapters, and sequence flows. |
| [**AI Integration & MCP**](ai-integration.md) | Comprehensive specification of the Ariadne agent, judgement skills (`J-SITE`, `J-MORPH`, `J-COMPARE`, `J-CLIMATE`), revision skill (`R-PROPOSE`), JSON schemas, validation rules, and the 15 Stdio MCP tools. |
| [**User Guide**](user-guide.md) | Step-by-step visual walkthrough of a complete design session across the five tabs: **Site**, **Conditions**, **Generate**, **Compare**, and **Refine**. |

---

## Foundational Engineering Specifications

Ariadne was developed under a formal multi-week engineering constitution. The authoritative project specifications are:

- [**00 Product Vision**](00_PRODUCT_VISION.md): The motivating problem in early-stage urban design, computational co-design principles, and pedagogical framing for TU Delft IDEM307.
- [**01 Product Requirements**](01_PRODUCT_REQUIREMENTS.md): Functional and non-functional requirements for GIS synchronization, morphological generation, and simulation pipelines.
- [**02 System Architecture**](02_SYSTEM_ARCHITECTURE.md): Component responsibilities, storage boundaries, validation gates, retry policies (`OUTCOME_UNKNOWN`), and credential safety.
- [**03 Agent Architecture**](03_AGENT_ARCHITECTURE.md): Permission boundaries, agent roles, anti-hallucination guardrails, and the human contestability model.
- [**05 Evidence Framework**](05_EVIDENCE_FRAMEWORK.md): Formal data model for Evidence Cards, claims, parameter lineage, and contest events.
- [**06 Evaluation Framework**](06_EVALUATION_FRAMEWORK.md): Acceptance gates, consistency benchmarks, and test harness definitions.
- [**07 Implementation Plan**](07_IMPLEMENTATION_PLAN.md): Milestone roadmap, deliverables, and semester execution tracks.
- [**Architecture Decision Records**](decisions/): Recorded decisions regarding spatial gates, weather chronology, font outline rendering, and platform session dockets.

---

## Key Directories

- [`knowledge/judgement/`](../knowledge/judgement/): Markdown definitions of judgement skills (`J-SITE-zh.md`, `J-MORPH-zh.md`, `J-COMPARE-zh.md`, `J-CLIMATE-zh.md`, `R-PROPOSE-zh.md`) and their corresponding JSON schemas.
- [`knowledge/v2/`](../knowledge/v2/): The urban morphology knowledge base curriculum, fabric schemas, and topic units.
- [`scripts/`](../scripts/): Standalone python simulation scripts for E1 sunlight, E2 radiation, E3/E4 energy and mass, E5 OpenFOAM wind screening, and Place Syntax Tool (PST).
- [`config/`](../config/): Model provider profiles (`model-providers.json`) and runtime configuration policies.
