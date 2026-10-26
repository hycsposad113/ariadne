# Ariadne AI Integration & MCP Reference

This document describes how Ariadne configures AI models, structures domain knowledge, validates agent reasoning, and exposes platform capabilities through the **Model Context Protocol (MCP)**.

---

## 1. Supported Model Providers & Keychain Security

Ariadne is model-provider agnostic. Supported execution routes are declared in [`config/model-providers.json`](../config/model-providers.json):

| Provider Profile | Adapter Type | Target Model | Data Egress | Key / Auth Storage |
|---|---|---|---|---|
| **`codex-cli`** | `cli_subprocess` | `gpt-6-luna` (`reasoning_effort=max`) | Cloud | Local Codex CLI session |
| **`claude-cli`** | `cli_subprocess` | Anthropic default (`claude`) | Cloud | Local Claude Code CLI session |
| **`openai-gpt-4o`** | `openai_compatible` | `gpt-4o` | Cloud | macOS Keychain (`urban-design-openai-gpt-4o`) |
| **`ollama-template`**| `openai_compatible` | Disabled template (unconfigured) | Local (offline) | None (Local loopback) |

> [!NOTE]
> **Provider Configuration**: Ollama is a disabled template with no endpoint or model configured. Configure and enable it before use. API profiles must implement the protocol supported by their configured adapter; the OpenAI-compatible profile requires an OpenAI-compatible endpoint.

### 1.1 Zero-Credential Storage Architecture
Ariadne enforces strict secret protection:
- **No keys in git or logs**: The repository contains zero API keys, secrets, or bearer tokens.
- **macOS Keychain isolation**: Settings status checks query Keychain item presence without returning the value. Authorized live dispatch reads the key into process memory for the provider request; the key is not exposed in status responses or logs.
- **Fail-closed status reporting**: The UI **AI Model Settings** panel reports status indicators (`AVAILABLE`, `MISSING_KEY`, `DISABLED`, `OVER_BUDGET`, `CLI_NOT_INSTALLED`, `NOT_LOGGED_IN`) without exposing credentials.
- **Weekly call budget**: Default limit of **200 live calls per week** prevents accidental cost overruns.

---

## 2. Agent Persona: `SOUL.md`

Profiles with `use_ariadne_persona=true` load `integrations/hermes/ariadne/SOUL.md` for supported requests. The current configuration enables this for Codex CLI (and not Claude CLI):

```text
Core Constitutional Law:
- LLMs reason.
- Deterministic tools calculate.
- Validators verify.
- Humans decide.
```

### Behavioral Principles
1. **Evidence First, Suggestions Second**: In every response, Ariadne must cite verified evidence cards (`card-*`) and deterministic metric claims (`claim-*`). It must never fabricate coordinates, FAR values, sunlight hours, or regulatory approvals.
2. **Space Syntax Caution**: Ariadne must explicitly qualify topological integration and choice metrics with the disclaimer: *"Space syntax measures structural accessibility within the network graph; it does not represent actual pedestrian footfall or vehicle counts."*
3. **Reference the Design Baseline**: When evaluating generated schemes, Ariadne actively compares outcomes against the original design baseline (the author's studio design: FAR ≈ 0.8, 4–6 storeys, about 40 % open space, a 15 m waterfront public promenade, and adaptive reuse of industrial silos).
4. **Respect Designer Authority**: Ariadne never claims or implies that a design decision has been finalized. Unapproved schemes are labeled `ASSUMED` or `UNAPPROVED_PREVIEW`.

---

## 3. Specialized Judgement Skills

Rather than relying on unstructured conversational prompts, Ariadne invokes specialized domain skills located in [`knowledge/judgement/`](../knowledge/judgement/):

| Skill ID | Focus Area | Inputs Passed | Primary Output |
|---|---|---|---|
| **`J-SITE`** | Site diagnosis & heritage | Study area bounds, BAG heritage silos, 800 m / 2 km context | Site constraints & retention recommendations |
| **`J-MORPH`** | Morphology & generation | Parametric strategy briefs, block geometry, road connectivity | Fabric viability & FAR density balance |
| **`J-COMPARE`** | Cross-scheme trade-offs | Multi-scheme metric scorecards, baseline delta | Comparative trade-off critique across the 4 fabrics |
| **`J-CLIMATE`** | Microclimate interpretation | E1 sunlight hours, UTCI heat stress, E2 radiation, E5 wind | Microclimate vulnerability identification & fix guidance |
| **`R-PROPOSE`** | Parametric revision drafting| Contested Judgement Card, designer response, massing state | Structured geometric operations for deterministic rerun |

---

## 4. Schemas & Deterministic Output Validation

Ariadne models must output structured JSON conforming to strict JSON Schemas. Workspace state and `HumanDecision` records use `.urban_design_runtime/state.sqlite3`. Judgement, response, and proposal history is stored in the separate `ariadne-judgements.sqlite3` database beside the project database. Outputs are programmatically validated before entering the judgements store.

### 4.1 Judgement Card Schema (`judgement-card.schema.json`)
Every judgement produced by `J-SITE`, `J-MORPH`, `J-COMPARE`, or `J-CLIMATE` must provide:
```json
{
  "skill_id": "J-CLIMATE",
  "skill_version": "1.0.0",
  "stage": "compare",
  "subject": {
    "kind": "scheme",
    "ids": ["harbour_grain"]
  },
  "observations": [
    {
      "text": "Winter solstice mean sunlight in courtyard centres is 0.11 hours.",
      "refs": [
        {
          "kind": "metric",
          "id": "e1.harbour.courtyard.winter.mean_h",
          "value": 0.108,
          "unit": "h"
        }
      ]
    },
    {
      "text": "Quayside perimeter blocks shelter the inner basin from prevailing southwest winds.",
      "refs": [
        {
          "kind": "artifact",
          "id": "e5_openfoam_harbour_sw_vector",
          "value": null,
          "unit": null
        }
      ]
    },
    {
      "text": "Peak summer UTCI conditions show localized heat stress along unshaded south quays.",
      "refs": [
        {
          "kind": "metric",
          "id": "utci.harbour.summer_p95_c",
          "value": 32.4,
          "unit": "C"
        }
      ]
    }
  ],
  "judgement": {
    "stance": "CONCERN",
    "headline": "Winter courtyard daylight is constrained by south wing heights in harbour grain massing."
  },
  "reasoning": [
    {
      "lens": "L4-microclimate",
      "text": "Low winter sun angles at 51.9N lead to deep courtyard overshadowing when south wings match full block height.",
      "knowledge_refs": ["KU-SOL-001"]
    },
    {
      "lens": "L2-movement",
      "text": "Quayside street corridors maintain permeability to water edges but generate wind channels under western flow.",
      "knowledge_refs": ["KU-WND-002"]
    }
  ],
  "confidence": {
    "level": "high",
    "why": "Grounded in deterministic Radiance ray-tracing runs on verified massing geometry."
  },
  "revision_directions": [
    {
      "action": "Lower southern courtyard wings to admit low-angle winter solar radiation.",
      "target": "south_courtyard_wings",
      "parameter_family": "height",
      "expected_effect": "Improves winter solar access to ground courtyards and northern interior facades.",
      "trade_off": "Potential loss of gross floor area unless redistributed to northern corners."
    }
  ],
  "counterpoints": [
    "Enclosed perimeter massing provides superior wind sheltering along public promenades compared to open pavilions."
  ],
  "limitations": [
    "E5 wind screening uses a coarse mesh; fine aerodynamic edge turbulence requires dedicated high-resolution CFD."
  ],
  "questions_for_designer": [
    "Should solar penetration in residential courtyards take priority over maintaining uniform perimeter cornice heights?"
  ]
}
```

### 4.2 Revision Proposal Schema (`proposal.schema.json`)
When the designer contests a card and requests revisions, `R-PROPOSE` generates executable operations:
```json
{
  "proposal_id": "prop-harbour-winter-solar-01",
  "responds_to": {
    "card_id": "card-j-climate-004",
    "response_ids": ["resp-designer-001"]
  },
  "summary": "Lower southern wings of courtyard blocks by one floor and rerun microclimate assessment.",
  "operations": [
    {
      "op": "REMOVE_TOP_FLOOR",
      "building_ids": ["bldg-b2-south", "bldg-b3-south"],
      "floors": 1
    },
    {
      "op": "RERUN",
      "analyses": ["E1", "UTCI"]
    }
  ],
  "rationale": [
    "Winter noon sun altitude at 51.9N is 14.7 degrees; stepping down southern wings improves solar exposure on courtyard ground and north facades."
  ],
  "expected_effects": [
    "Qualitative improvement in winter courtyard daylight hours and ground solar access. Final numerical change is determined after deterministic rerun."
  ],
  "trade_offs": [
    "Reduction in residential gross floor area on affected southern wings unless floor count is redistributed."
  ],
  "risks": [
    "Potential visual stepping on cornice line along the secondary east-west street."
  ],
  "not_simulated": [
    "Interior daylight distribution within individual residential units."
  ],
  "questions_for_designer": [
    "Do you approve redistributing the removed floor capacity to the northern block corners?"
  ]
}
```

> [!NOTE]
> **Qualitative Expected Effects**: A proposal may describe qualitative expected effects and trade-offs. Report numerical changes only after a successful deterministic rerun, using the resulting metrics. No fixed improvement or GFA loss is guaranteed.

### 4.3 Validation Guardrails
A deterministic Python validator checks every generated card:
1. **Numerical fidelity**: The validator checks numbers and references across the card against the assembled evidence bundle. It accepts values sourced from bundle metrics or supplied input text, using the validator’s displayed-precision comparison; it does not establish that every number equals a numeric metric field within floating-point tolerance.
2. **Forbidden keywords**: Any assertion that the AI "approves", "certifies", or "authorizes" a plan causes immediate rejection.
3. **Counterpoint mandate**: Even when expressing strong support (`SUPPORT`), the model must supply counterpoints and trade-offs.

---

## 5. Model Context Protocol (MCP) Server

Ariadne embeds an MCP Server (`src/urban_design/ariadne_mcp`) communicating over `stdio`. External AI assistants (Codex CLI, Claude Code CLI, Claude Desktop, Cursor) can query and co-design with Ariadne through 15 dedicated tools:

| # | Tool Name | Type | Description & Parameters | Constitutional Constraints |
|---|---|---|---|---|
| 1 | `get_site_analysis` | Read | Fetch verified site metrics, BAG footprints, and 24 evidence claims. `(project_id, language)` | Returns evidence-card and claim IDs; response omits cryptographic hashes. |
| 2 | `get_syntax_layers` | Read | Fetch 6 Space Syntax layers (NAIN, NACH). `(project_id, language)` | Mandatory disclaimer: topological potential $\neq$ traffic. |
| 3 | `get_surrounding_context_summary` | Read | Summarize land-use, green space, and water boundaries. `(project_id, language)` | Contextual boundary constraints only. |
| 4 | `list_scenarios` | Read | List active schemes, unapproved previews, and baseline targets. `(include_assumed, include_portfolio_baseline, language)` | Clearly flags `ASSUMED` preview states. |
| 5 | `compare_scenarios` | Read | Compare metric scorecards across schemes vs. portfolio baseline. `(scenario_ids, include_portfolio_baseline, language)` | Multi-dimensional comparative delta table. |
| 6 | `draft_constraints` | Draft | Convert natural-language design intentions into draft constraints. `(prompt, far_upper_bound, max_height_m, min_open_space_ratio, waterfront_setback_m, project_id, language)` | Marked `status: DRAFT`; actor is `AGENT_AUTOMATION`. |
| 7 | `run_preview_generation` | Action | Trigger deterministic generator to produce unapproved scheme preview. `(seed, strategy_floor_count, road_width_m, project_id, language)` | Creates exploratory massing; does not alter state. |
| 8 | `critique_scenario` | Analysis | Run structured critique of an existing scheme. `(scenario_id, prompt, project_id, language)` | Grounded in verified evidence cards. |
| 9 | `explain_decision_needed` | Read | Summarize pending design decisions requiring human approval. `(project_id, language)` | Reasserts AI cannot decide; never asks for secret. |
| 10 | `run_judgement` | Action | Execute a specialized judgement skill (`J-SITE`, `J-MORPH`, `J-COMPARE`, `J-CLIMATE`). `(skill_id, subject_ids, language, project_id)` | Schema-validated card appended to dialogue timeline. |
| 11 | `list_judgements` | Read | List stored judgements in the requested language. `(language, project_id)` | Returns stored cards matching requested language; no stage/subject filter. |
| 12 | `respond_to_judgement` | Action | Append an agent response to a judgement using `kind` (`agree`, `contest`, or `supplement`) and `text`. `(judgement_id, kind, text, language, project_id)` | Records an agent response; designer decisions are recorded separately through the platform’s HumanDecision flow. |
| 13 | `request_revision_proposal` | Action | Trigger `R-PROPOSE` to draft parametric fixes responding to contestation. `(card_id, language, project_id)` | Generates dry-run operations; no auto-execution. |
| 14 | `get_proposal` | Read | Retrieve stored proposal details, affected footprints, and GFA impact. `(proposal_id, language, project_id)` | Exposes dry-run diff and GFA delta. |
| 15 | `get_design_dialogue` | Read | Retrieve judgement, response and proposal history for a subject. `(subject, language, project_id)` | Result is scoped to the specified subject (default `harbour_grain`). |

> [!IMPORTANT]
> **No Approval Tools**: The MCP server deliberately exposes **zero approval or decision-signing tools**. Even through MCP, an external AI agent cannot execute a `HumanDecision` or approve a scheme.

---

## 6. Client Configuration Examples

### Codex CLI (`~/.codex/config.toml` or `./config.toml`)
```toml
[mcp_servers.ariadne]
command = "/path/to/ariadne/.venv/bin/python"
args = ["-m", "urban_design.ariadne_mcp"]
env = { ARIADNE_API_BASE_URL = "http://127.0.0.1:8789" }
```

### Claude Code CLI
```bash
claude mcp add ariadne --env ARIADNE_API_BASE_URL=http://127.0.0.1:8789 -- /path/to/ariadne/.venv/bin/python -m urban_design.ariadne_mcp
```

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "ariadne": {
      "command": "/path/to/ariadne/.venv/bin/python",
      "args": ["-m", "urban_design.ariadne_mcp"],
      "env": {
        "ARIADNE_API_BASE_URL": "http://127.0.0.1:8789"
      }
    }
  }
}
```
