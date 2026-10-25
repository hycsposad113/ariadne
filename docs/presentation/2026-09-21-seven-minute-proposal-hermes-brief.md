# Hermes Brief — Seven-Minute Urban Design Project Proposal

## Purpose

Prepare a seven-minute academic proposal presentation for the TU Delft Q5
project **Evidence-Based, Contestable Agentic Urban Design Environment**.

This is a project proposal, not a final-results presentation. Explain the
research problem, proposed system, demonstrator, methods, evaluation and
eight-week delivery logic. Use current implementation evidence only to show
feasibility and methodological discipline. Do not present planned Week 2–8
outputs as completed results.

## Source authority and conflict rule

The nine authoritative engineering documents are the source of truth. The
preserved research report is supporting evidence. When status statements
conflict, use the newest current-status record in `README.md` and
`docs/07_IMPLEMENTATION_PLAN.md`, then disclose the conflict rather than
silently combining versions.

One known conflict matters for the deck: `docs/00_PRODUCT_VISION.md` still
contains an older sentence naming StudyArea v4. The current authoritative state
is active Rotterdam M4H StudyArea **v5**, with v4 superseded. Do not repeat the
stale v4 statement.

## Core must-read set

Read these files in this order:

1. `README.md`
   - Project summary, research question, current state, four-stage workflow,
     technology direction and limitations.
2. `AGENTS.md`
   - Engineering constitution, human authority and the core law:
     “LLMs reason. Deterministic tools calculate. Validators verify. Humans
     decide.”
3. `docs/00_PRODUCT_VISION.md`
   - Why the project exists, target user, four-stage journey, principles,
     contribution and eight-week boundary. Apply the v5 correction above.
4. `docs/01_PRODUCT_REQUIREMENTS.md`
   - Project settings, P0 contract, out-of-scope boundary and acceptance logic.
   - Focus on P0-01, P0-02, P0-04 through P0-14, and P0-17 through P0-21.
5. `docs/05_EVIDENCE_FRAMEWORK.md`
   - Evidence classes, evidence chain, parameter registry, provenance,
     immutable artifacts, contest events and human decisions.
6. `docs/07_IMPLEMENTATION_PLAN.md`
   - Current implementation status, fixed MVP contract, Weeks 1–8, risks,
     cut order and non-cuttable mandates.
7. `docs/superpowers/plans/2026-09-21-eight-week-project-blueprint.md`
   - Clean Week 1–8 dependency graph and weekly checkpoints.

## Method and architecture set

Read these after the core set:

8. `docs/02_SYSTEM_ARCHITECTURE.md`
   - Conceptual stack, deterministic tools, state, validation, failure handling
     and trust boundaries.
9. `docs/03_AGENT_ARCHITECTURE.md`
   - Orchestrator, Site Intelligence, Morphological Exploration, Scenario
     Critic, Climate Co-Designer and Verifier roles.
10. `docs/06_EVALUATION_FRAMEWORK.md`
    - Release gates, deterministic tests, benchmarks, contestability and
      evaluation criteria.

## Current-state evidence set

Use these to distinguish verified feasibility from future work:

11. `docs/milestone1-feasibility.md`
    - Verified typed foundation, bounded QGIS path, Ladybug screening smoke and
      Honeybee-Radiance verification smoke. These are feasibility fixtures, not
      urban-design findings.
12. `docs/m2-a02-live-bridge.md`
    - Human Draw → Confirm StudyArea bridge and external-process boundary.
13. `docs/m2-a03-r09-r01-review-addendum.md`
    - Current weather evidence boundary. The weather method remains
      `SEMANTICS_UNRESOLVED`; no weather source is approved.
14. `docs/superpowers/plans/2026-09-21-week2-spatial-input-gate.md`
    - Detailed future Week 2 spatial execution plan. It is planning material,
      not completed implementation.

## Supporting research

Use `docs/research/research_report.md` for literature, conceptual context and
citations. It cannot override the engineering documents or turn illustrative
values into project facts.

## Project facts the deck must communicate

- **Problem:** Urban-design work is fragmented across GIS, geometry,
  environmental simulation, files, screenshots and narrative judgment. The
  evidence chain and decision history are easily lost.
- **Research question:** How can an agentic urban-design environment coordinate
  site analysis, morphological exploration, scenario evaluation and
  environmental refinement while preserving provenance, reproducibility,
  sensitivity to assumptions and meaningful designer contestability?
- **Proposal:** A local, single-user research prototype where agents coordinate
  work, deterministic tools calculate, validators check evidence and the
  designer retains decision authority.
- **Workflow:** Draw and confirm StudyArea → Understand → Explore → Test →
  Refine → explicit human decision.
- **Demonstrator:** One Rotterdam M4H case with a human-confirmed StudyArea v5.
  StudyArea is an exploration envelope, not a cadastral or legal boundary.
- **Spatial evidence:** Frozen PDOK and OSM snapshots with query, licence,
  retrieval time, version, hashes and data gaps.
- **Accessibility:** Fixed approved origins reaching selected grocery
  destinations within a network threshold; initial 800 m and versioned
  400/800/1200 m challenges. Unreachable origins remain in the denominator.
- **Morphology:** Reproducible perimeter-block and linear-block families using
  registered COMPAS operations. Rejected candidates remain inspectable.
- **Critique and contestability:** Inspect, Challenge, Modify, Rerun, Compare,
  Fork, Reject and Override create versioned state and append-only history.
- **Climate experiment:** One selected building, one translation axis, one
  baseline and two feasible offsets; Ladybug/ladybug-radiance screening and
  Honeybee-Radiance verification under locked controls.
- **Research contribution:** Contestability is implemented as a computational
  and evidence property rather than an explanation layer added after analysis.
- **Evaluation:** Known-answer deterministic tests, evidence relationship
  checks, adversarial agent tests, replay, immutable hashes and weekly gates.

## Current state that must remain honest

Verified or accepted now:

- Milestone 1 typed contracts, SQLite state/ledger, deterministic adapter and
  bounded tool interfaces exist.
- Real QGIS, Ladybug and Honeybee-Radiance feasibility paths have passing smoke
  evidence under their documented limits.
- Rotterdam M4H StudyArea v5 is active and `CONFIRMED_FOR_EXPLORATION`.
- Historical evidence and rejected alternatives are retained append-only.

Not completed now:

- The Week 2 spatial gate has not been implemented or accepted.
- No new spatial DatasetSnapshot has been published by the split Week 2 path.
- Origin, grocery taxonomy and pedestrian-network policies are not approved.
- Weather remains `BLOCKED / SEMANTICS_UNRESOLVED` and blocks Week 6 only.
- Accessibility, morphology, critic UI, climate experiment and integrated
  Weeks 3–8 workflow are planned work.
- No formal Site or DesignBoundary is approved.

Use the weather issue as a brief example of fail-closed evidence handling. Do
not make EPW Minute semantics the main story of the proposal.

## Seven-slide narrative and timing

Target spoken duration: exactly 7:00, approximately 800–900 English words.

| Slide | Time | Purpose |
| --- | ---: | --- |
| 1. The problem and research question | 0:50 | Show fragmented urban-design evidence and state the research question. |
| 2. The proposed principle | 0:55 | Explain the core law and why the designer retains authority. |
| 3. The proposed workflow and system | 1:00 | Show Draw/Confirm → Understand → Explore → Test → Refine and the controlled tool/evidence loop. |
| 4. Rotterdam M4H demonstrator | 1:10 | Explain StudyArea v5, frozen spatial evidence, accessibility and two morphology families. |
| 5. Contestability and evaluation | 1:10 | Show evidence chain, challenge/rerun/fork/override and deterministic evaluation. |
| 6. Eight-week execution and current position | 1:20 | Present the Week 1–8 dependency map; separate completed feasibility, planned work and blocked weather gate. |
| 7. Contribution, limits and proposal | 0:35 | State expected contribution, bounded claims and what the project will demonstrate. |

Total: 7:00.

## Visual direction

- Use 16:9 widescreen and a restrained academic/editorial visual language.
- Prefer one clear visual argument per slide over dashboard-like collections of
  cards.
- Use a workflow diagram, evidence-chain diagram and eight-week dependency
  timeline as the main explanatory graphics.
- Keep body text at presentation-readable size; move detail into speaker notes.
- Use Rotterdam/M4H imagery or maps only when provenance and status are clear.
- The following map may illustrate a **historical contested-boundary review**,
  but must never be labelled as an approved Site or active formal boundary:
  `artifacts/milestone2-boundary-decision-rotterdam-m4h/run-20260916T123000Z/map-overview.png`.
- The active StudyArea geometry source is:
  `.urban_design_runtime/artifacts/study-area-bridge/study-areas/4818687ee13f2c4fe78471d52320074948de269d5687c494ca2fa213afe39533.geojson`.
  If a new map is rendered from it, label it “human-confirmed exploration
  StudyArea v5,” not “site boundary.”
- Clearly mark proposed interfaces, future analyses and illustrative diagrams
  as proposed. Do not fabricate interface screenshots or analysis values.

## Required deliverables

Create:

1. A seven-slide, 16:9 presentation deck.
2. A PDF export.
3. Speaker notes for every slide.
4. A continuous 800–900 word rehearsal script timed to 7:00.
5. A slide-by-slide source map naming the local files supporting each claim.
6. An asset manifest listing every image, map and diagram and whether it is
   observed evidence, historical evidence or a proposed diagram.
7. Rendered slide previews and a visual QA report covering overflow,
   readability, source labels and timing.

Suggested output directory:

`artifacts/presentation/2026-09-21-seven-minute-project-proposal/`

## Prohibited claims

Do not claim that:

- the complete prototype already exists;
- Week 2 spatial acceptance has passed;
- weather is approved;
- accessibility, morphology or climate results have been calculated for M4H;
- StudyArea v5 is a cadastral, ownership, zoning or legal-buildability boundary;
- an agent makes the final design decision;
- lower incident radiation proves thermal comfort;
- green tests alone prove semantic acceptance;
- rejected historical site proposals are active project truth.

## Copy-paste Hermes prompt

```text
You are preparing a seven-minute academic project-proposal presentation for the
TU Delft Q5 project in:

/Users/jackhsieh/Downloads/TUD/Q5/project

First read this briefing in full:

docs/presentation/2026-09-21-seven-minute-proposal-hermes-brief.md

Then read every file in its Core must-read set, Method and architecture set,
and Current-state evidence set in the stated order. Treat the nine
authoritative engineering documents as the source of truth. Use
docs/research/research_report.md only as supporting research. If documents
conflict, use the newest current status in README.md and
docs/07_IMPLEMENTATION_PLAN.md and report the conflict. In particular, the
active Rotterdam M4H StudyArea is v5; the v4 sentence in Product Vision is
stale.

Task:

Create a polished seven-slide, 16:9, English proposal deck and a spoken script
that lasts 7:00. The audience is an academic urban-design/research review. The
deck must explain the problem, research question, proposed system, Rotterdam
M4H demonstrator, research method, evaluation strategy, eight-week plan,
expected contribution and limitations.

This is a proposal, not a final-results presentation. Separate these states
visibly and verbally:

1. verified feasibility or accepted current state;
2. planned implementation;
3. blocked or unresolved work.

Use this exact seven-slide timing:

1. Problem and research question — 0:50
2. Proposed principle — 0:55
3. Workflow and system — 1:00
4. Rotterdam M4H demonstrator — 1:10
5. Contestability and evaluation — 1:10
6. Eight-week execution and current position — 1:20
7. Contribution, limits and proposal — 0:35

Total: 7:00. Keep the complete spoken script between 800 and 900 words.

The conceptual center is:

LLMs reason.
Deterministic tools calculate.
Validators verify.
Humans decide.

Show the workflow:

Draw and confirm StudyArea
→ Understand
→ Explore
→ Test
→ Refine
→ explicit human decision

Explain that contestability is implemented through evidence and state:
Inspect, Challenge, Modify, Rerun, Compare, Fork, Reject and Override preserve
prior evidence and create versioned records.

Use the Rotterdam M4H StudyArea v5 as an exploration envelope. Never describe
it as a formal cadastral or legal site. Explain the proposed spatial evidence,
accessibility analysis, perimeter/linear morphology families, evidence-bounded
critic and controlled climate experiment without inventing results.

Current-status boundary:

- Milestone 1 foundation and bounded QGIS/Ladybug/Honeybee feasibility have
  accepted evidence under documented limits.
- StudyArea v5 is active and confirmed for exploration.
- Week 2 spatial separation and acceptance are planned, not completed.
- Spatial DatasetSnapshots and the three spatial policies are not yet approved.
- Weather is BLOCKED / SEMANTICS_UNRESOLVED and is required before Week 6 only.
- Weeks 3–8 analysis and integration remain planned work.
- No formal Site or DesignBoundary is approved.

Mention the weather issue only as a short example of fail-closed evidence
handling. Do not turn the deck into a weather-file investigation.

Visual requirements:

- Use a restrained academic/editorial design, not a dashboard layout.
- Use one main visual argument per slide.
- Include a workflow diagram, evidence-chain diagram and eight-week dependency
  timeline.
- Use maps or images only with explicit provenance and status.
- Any visual derived from a rejected historical boundary package must be
  labelled historical/rejected and cannot represent the active formal site.
- Proposed interfaces and future outputs must be labelled proposed.
- Do not fabricate screenshots, metrics, maps or analysis results.
- Keep detailed citations in speaker notes and a source map rather than filling
  slides with long paths.

Before creating the deck, inspect the project for an official course template.
If one exists, preserve its visual system. If none exists, use a clean academic
layout with strong hierarchy, readable type and restrained color. Do not stop
merely because no template is present.

Required outputs:

- editable presentation deck;
- PDF export;
- speaker notes for every slide;
- continuous 800–900 word rehearsal script;
- slide-by-slide source map;
- visual asset manifest with evidence-status labels;
- rendered slide previews;
- visual and timing QA report.

Save all outputs under:

artifacts/presentation/2026-09-21-seven-minute-project-proposal/

Before finalizing:

1. Check every factual claim against a named local source.
2. Remove unsupported numbers and generic promotional language.
3. Confirm planned work is not written in the past tense.
4. Confirm the seven timings total exactly 7:00.
5. Rehearse the script for 7:00 and revise if needed.
6. Render every slide and inspect readability, clipping and overlap.
7. Confirm the deck never promotes StudyArea to a legal boundary.
8. Confirm the deck never claims weather, accessibility, morphology or climate
   work is complete.

Return a concise completion report containing:

- output paths;
- slide titles and timing;
- total script word count and rehearsed duration;
- source and asset summary;
- current-state claims used;
- unresolved issues or assumptions;
- visual QA result.
```

