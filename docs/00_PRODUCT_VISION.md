# Product Vision

> **2026-09-22 現行規劃修訂：** 本文件採納 [工作流程與學期排程修訂契約](08_WORKFLOW_REALIGNMENT_2026-09-22.md)。其中第 5 節明列的產品範圍與排程條款優先於下方保留的舊版敘述；未列為取代的安全、證據與人類決策契約繼續有效。學期 W4 合併平台接入與基地分析，W5 開始生成／編輯，W8 驗收核心、W9 收尾。這是規劃修訂，不是實作或政策批准。

新版產品是 QGIS 按鈕同步至自有平台，讓設計者選保留建築與道路、畫局部需求、理解基地與三尺度 Space Syntax、生成 3–5 個空間策略、直接編輯並比較環境結果，最後出圖。四階段仍為 Understand → Explore → Test → Refine。舊文的兩家族、basic 3D、Syntax 非核心及單軸限定只保留為前版範圍與回歸案例；不再限制新版產品。下方歷史狀態不是目前 SQLite 的證明。

## Why This Project Exists

Urban designers increasingly work across fragmented evidence and software: public geodata, GIS analysis, computational geometry, environmental simulation, design alternatives, and narrative judgement. Moving among these systems makes it difficult to preserve why a value was calculated, which assumptions produced it, how a proposal changed, and who accepted or rejected a conclusion. A conversational model can help coordinate this work, but an unbounded model can also hide assumptions, invent measurements, and turn situated trade-offs into unsupported recommendations.

This project will demonstrate an **Evidence-Based, Contestable Agentic Urban Design Environment**: a local, single-user course research prototype that coordinates evidence, deterministic computation, and controlled design experiments while keeping consequential conclusions traceable, challengeable, and under designer control.

The governing law is:

> LLMs reason. Deterministic tools calculate. Validators verify. Humans decide.

The core research question is:

> How can an agentic urban-design environment coordinate site analysis, morphological exploration, scenario evaluation, and environmental refinement while preserving provenance, reproducibility, sensitivity to assumptions, and meaningful designer contestability?

## Target User and Current Workflow

The primary user is an urban designer or design researcher conducting an early-stage study of a site. The eight-week prototype serves one researcher working on one Rotterdam M4H case. It is not a planning-authority system and does not make decisions for residents, clients, or regulators.

The active MVP demonstration is the human-confirmed Rotterdam M4H `StudyArea`
version `v5`, which supersedes the earlier v4 StudyArea for current exploration.
Historical Delft proposal packages remain superseded research and proposal
evidence, while rejected or proposed Rotterdam boundary experiments remain
historical boundary evidence. This selection does not set a formal
`Site` or `DesignBoundary`: formal claims still require a future approved
`DesignBoundary` backed by an explicit `HumanDecision`.

Today, the user must manually connect data acquisition, QGIS operations, design geometry, radiation studies, spreadsheets, screenshots, and prose. Tool files and chat transcripts rarely form a coherent evidence chain. When a threshold, dataset, or design premise changes, it can be unclear which results are stale or whether the original conclusion still holds.

The product proposition is a structured environment in which the designer can ask questions, generate bounded alternatives, inspect computed evidence, change a premise, rerun the affected analysis, compare results, and record a human decision without erasing earlier states.

## Four-Stage Journey

Before the four stages, the designer draws a polygon in QGIS and saves it as a retained artifact. A human confirmation registers and resolves that typed artifact, canonicalizes units against its projected CRS axes, and creates a versioned `StudyArea` with a geometry hash, confirmation actor/time, and ledger events. Runtime entry checks replay the persisted StudyArea and its matching confirmation/activation events. This confirmation authorizes exploration only; it does not assert cadastral ownership, zoning compliance, or legal buildability. A later `DesignBoundary` may be proposed and approved through an explicit `HumanDecision` when formal claims are needed.

1. **Understand — Site Intelligence.** Load the confirmed StudyArea and freeze the PDOK/OSM snapshots required by the specific analysis. Use validated GIS operations to establish observations and data gaps, while exposing coordinate systems, units, methods, and provenance.
2. **Explore — Morphological Exploration.** Generate one perimeter-block and one linear-block candidate through registered COMPAS operators. Preserve parameters, constraints, lineage, rejected candidates, and explicit pedestrian-passage overlays.
3. **Test — Scenario Critic.** Compare scenarios through a deterministic accessibility metric and descriptive geometry measures. Link each interpretation to evidence, assumptions, limitations, and source versions. Let the designer challenge the 800 m threshold and rerun at 400 m or 1200 m without overwriting the first result.
4. **Refine — Climate Co-Designer.** Propose a single-variable experiment that translates one selected building along a declared axis. Screen baseline and two feasible offsets with Ladybug/ladybug-radiance, verify them with Honeybee-Radiance, and report method-specific changes and directional agreement or disagreement.

The journey ends with an explicit human acceptance, rejection, modification, fork, or override. The Design Ledger preserves the complete sequence.

## Product Principles

- **Evidence before interpretation.** Measurements originate in identified datasets and deterministic tools.
- **Visible assumptions.** Thresholds, taxonomies, constraints, transformations, weather, and simulation settings are versioned inputs.
- **State-changing contestability.** A challenge can modify a permitted premise and trigger a new calculation; explanation alone is insufficient.
- **Plural alternatives.** The system presents trade-offs and does not create an undisclosed overall score.
- **Reproducible history.** Inputs, tools, results, scenario lineage, rejections, and decisions remain inspectable.
- **Bounded agency.** LLM roles plan, interpret, and formulate hypotheses through typed interfaces; deterministic software owns calculation, validation, permissions, and state transitions.
- **Honest failure.** Missing observations are not zero, modelled public access is not verified legal access, and a failed design hypothesis remains a valid result.
- **Human authority.** The designer confirms the StudyArea, approves any formal DesignBoundary, constraints, generated proposals, experiment plan, and consequential decisions.

## Research Contribution

The prototype studies a **contestable orchestration protocol** rather than a new GIS, geometry, or radiation algorithm. Its contribution is a working chain from source to claim, parameter, metric, method, tool result, interpretation, contest event, and human decision. Evaluation asks whether this chain is correct, reproducible, and usable for the designer operating the system.

The research does not establish comprehensive democratic or resident contestability. Such a claim would require affected-community participation and a broader governance study.

## Differentiation

- A **generic architecture chatbot** can discuss a site but cannot establish authoritative measurements or replay an evidence chain.
- A **generic QGIS assistant** controls GIS operations but does not govern cross-stage design lineage, experiments, claims, and human decisions.
- A **pure generative-design engine** searches alternatives but may hide why they exist or collapse trade-offs into a single fitness score.
- An **automatic Ladybug workflow** runs environmental analysis but does not connect its assumptions and outputs to contestable design decisions.
- A **Grasshopper script** can encode a valuable parametric workflow but is not the required core platform and does not by itself provide project-wide evidence governance.
- An **autonomous AI designer** implies delegated design authority. This product retains authority with the designer.

## Eight-Week Boundary

The mandatory prototype comprises one human-confirmed Rotterdam M4H StudyArea for exploration; analysis-specific frozen PDOK/OSM data; QGIS MCP; two COMPAS morphology families; one primary accessibility metric; one threshold challenge and rerun; a two-tier controlled radiation experiment; a basic map and 3D massing view; scenario comparison; an Evidence Inspector; bounded interaction; and an append-only Design Ledger. A formal DesignBoundary is a separate, human-approved contract for formal claims and is not an exploration prerequisite.

NSGA-II, MAP-Elites, broad Space Syntax, global sensitivity packages, additional sites or provider integrations, multi-user collaboration, and Rhino, Grasshopper, or Revit connectors are future work. Reliability and a complete four-stage case take precedence over breadth.

## Long-Term Direction

After the research prototype establishes its central claim, future work may add additional evidence sources, metrics, design operators, environmental objectives, model adapters, and stakeholder-facing contestation mechanisms. Each extension must retain typed contracts, deterministic validation, explicit assumptions, reproducible artifacts, and human authority.

## Sources of Truth

Product requirements are defined in [01_PRODUCT_REQUIREMENTS.md](01_PRODUCT_REQUIREMENTS.md). The technical boundaries are defined in [02_SYSTEM_ARCHITECTURE.md](02_SYSTEM_ARCHITECTURE.md), evidence semantics in [05_EVIDENCE_FRAMEWORK.md](05_EVIDENCE_FRAMEWORK.md), evaluation in [06_EVALUATION_FRAMEWORK.md](06_EVALUATION_FRAMEWORK.md), and delivery order in [07_IMPLEMENTATION_PLAN.md](07_IMPLEMENTATION_PLAN.md). The preserved research report is supporting evidence and does not override these decisions.
