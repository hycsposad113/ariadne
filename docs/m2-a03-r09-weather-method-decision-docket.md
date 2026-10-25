# M2-A03-R09 — Weather method decision docket

**Task status:** `PASS` for the append-only dossier and deterministic integrity package. The weather-method conclusion remains **`SEMANTICS_UNRESOLVED`**; no source is approved or selected.

## Scope and boundary

This docket records only the source-method evidence needed before a Rotterdam M4H v5 weather input can be approved. It does not rerun M2-A03 r03, download any candidate ZIP, call a weather API, request PDOK or OSM, convert `Minute=0`, publish a `DatasetSnapshot`, or start climate analysis. The package is at `artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r09-weather-method-evidence/`.

The exact unresolved question is what `Minute=0` means in each retained Rotterdam TMYx file: the hourly interval endpoint, midnight/date-boundary mapping, and the timestamp/accumulation interval for solar-radiation fields. A generic EPW range, a parser read, or a project validator cannot answer that provider-specific question.

## Stage 0 baseline revalidation

The retained R08-R01 frozen verifier was run again to a disposable `/private/tmp` output with `PYTHONDONTWRITEBYTECODE=1`. It returned `PASS` with 53 retained input files, three candidates, and no acceptance failures. The frozen result remains byte-preserved at:

- `artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-r01-verifier-repair-20260919T172048Z/frozen-verification-result.json`
- size `15643` bytes
- SHA-256 `sha256:49d0f3408892fc9412e01a47af74c154626bc69d50f88e3804218a5db85a3bab`

The retained R08 manifest has 53/53 matching files. Its source-semantics conclusion is still `SEMANTICS_UNRESOLVED`. The blocked r03 package has 13 manifest entries, zero integrity mismatches, zero published Artifacts, and zero `DatasetSnapshot` records.

The read-only SQLite authority state at capture time was:

- active project pointer: `study-area-rotterdam-m4h-pilot-project-v5`;
- StudyArea v5: `CONFIRMED_FOR_EXPLORATION`, geometry `sha256:3dedb804fa4f07f4c9570bcc64e68c8d576c03340455ab35fd4963bca52aa4f5`, Artifact `sha256:9a59159505505dbe658ec6667ecfeb9024b868faf6377e7cd91889c763170d32`;
- v4: `SUPERSEDED`, preserved and superseded by v5;
- ledger events: `24`;
- `DatasetSnapshot` state versions: `0`.

All R05-R08-R01 packages, the blocked r03 package, SQLite, source code, QGIS state, and Hermes state were protected. The root is not a Git repository, so no worktree, branch, commit or diff was created.

## First-party evidence classification

The captures are stored with their actual retrieval headers (credential-bearing `Set-Cookie` lines redacted), source URL, UTC start/end, size, and SHA-256 in the package retrieval log.

| Source | Classification | Capture | Size | SHA-256 | Supports | Does not establish |
|---|---|---|---:|---|---|---|
| `climate-onebuilding-home` | `PROVIDER_SPECIFIC_SEMANTICS` | `source-documents/climate-onebuilding-home.html` | 15801 | `sha256:eb91ee39b7c4c57aee6f8f1f0968b2fecc7eecd12813c86200c9d35225a6016e` | Provider-specific provenance and release-family description for TMYx. | Does not state the Minute=0 interval endpoint, midnight/day-boundary convention, or solar-radiation timestamp for any Rotterdam file. |
| `climate-onebuilding-netherlands-index` | `PROVIDER_SPECIFIC_SEMANTICS` | `source-documents/climate-onebuilding-netherlands-index.html` | 50072 | `sha256:3b51e7b0192356a163a3996af137d1e1be1d127721e44bec69c843fd0f563062` | File-family/station naming and period-variant listing. | Does not specify timestamp semantics, EPW transformation rules, or whether Minute=0 is an endpoint encoding for the listed files. |
| `climate-onebuilding-sources` | `PROVIDER_SPECIFIC_SEMANTICS` | `source-documents/climate-onebuilding-sources.html` | 37125 | `sha256:db80ffe6a7bcb4b41894f5d4c0f9442e5dd1b94701a634947e3758d3a3de9fc2` | Provider source lineage, TMYx period variants, and solar-data provenance. | Does not give a file-family-specific Minute=0 convention or the exact timestamp of radiation accumulation for Rotterdam TMYx records. |
| `energyplus-epw-dictionary` | `GENERIC_FORMAT_RULE` | `source-documents/energyplus-epw-weather-file-format.pdf` | 139050 | `sha256:cd74baa05726bd47e51d6bd29932e93bb7ad4ce76eec15eab30a78c3b3c7d36a` | Generic EPW representation rule and generic radiation accumulation wording. | Cannot identify whether the three retained Rotterdam files use Minute=0 as interval start, interval end, or another encoding; cannot authorize 0→60. |
| `knmi-10-minute` | `PROVIDER_SPECIFIC_SEMANTICS` | `source-documents/knmi-10-minute-dataset.html` | 26012 | `sha256:77324cd8a7c8a9ee61cd2b05fc2867cc5829de067b0b5c6efa555c08b4c141f4` | Explicit provider-specific timestamp convention for this KNMI 10-minute product, plus version, licence, format, and quality notice. | This is not one of the Rotterdam TMYx files and is not an hourly EPW; its incomplete, unvalidated near-real-time archive cannot be selected as the project weather input here. |
| `ncei-global-hourly-isd` | `PROVIDER_SPECIFIC_SEMANTICS` | `source-documents/ncei-global-hourly-isd.html` | 48887 | `sha256:f5c539b78c094d78ffab488f3e4893047140d0a76786ae0894beebc069e8563d` | Hourly source-data family, broad station/coverage and QC description. | Does not state the EPW interval endpoint, solar-radiation timestamp, exact Rotterdam file lineage, or a project-approved licence/selection rule. |

`Climate.OneBuilding` describes TMYx provenance (hourly ISD source, period variants and ERA5 solar for the 2026 release) and its Netherlands index lists the Rotterdam file families. The provider-hosted EnergyPlus dictionary is **`GENERIC_FORMAT_RULE`** evidence: it describes Hour 1 as `00:01–01:00`, permits a Minute range `0..60`, and describes radiation values as accumulated over preceding minutes. Those rules do not identify the endpoint convention in the three Rotterdam TMYx files.

The retained R08/R08-R01 bytes and verifier are recorded as **`PARSER_BEHAVIOR` / `DATASET_OBSERVATION`** evidence. They show the raw records and the unapproved `Minute=0 → Minute=60` experiment, but parser readability and a passing derived validator do not establish source semantics. The current `Minute=60` check is a **`PROJECT_IMPLEMENTATION_CONTRACT`**, not provider evidence.

KNMI's official 10-minute product is **`PROVIDER_SPECIFIC_SEMANTICS`** evidence for that product only: its metadata states that the timestamp denotes the end of the observation interval in UTC, supplies version 1.0, NetCDF, CC BY 4.0 and coverage metadata, and warns that the historical near-real-time archive is incomplete and not manually validated. It is not an hourly EPW/TMYx source and is retained only as a documented alternative for human review. NOAA NCEI's official ISD page describes global hourly/synoptic observations and broad coverage, but does not provide a project-specific EPW endpoint/radiation convention or selection/licence decision for Rotterdam.

The explicit **`INFERENCE`** boundary is that no generic `0..60` rule, station distance, or parser result can be promoted to a provider-specific claim for the retained files.

## Decision matrix and recommendation

The package decision matrix records four unapproved options:

1. retain `BLOCKED` while seeking direct provider-specific evidence for the three file families;
2. review a documented alternative with explicit time semantics, without selecting it;
3. submit a human/architecture-approved derived-method proposal with raw parent bytes and row-level mapping; or
4. retain the least-assumptive `BLOCKED` state until one of the first three is decided.

The recommendation is to retain `BLOCKED` / `SEMANTICS_UNRESOLVED`. This recommendation is not source approval, method approval, weather selection, or authorization for a conversion.

## Integrity and fault controls

`integrity-manifest.json` excludes itself to avoid a self-hash cycle. It lists each package file and this docket with size, SHA-256, kind, and parent path/hash relations. `r09-verify.py` checks listed files, all parent hashes, evidence classifications, request counters and the read-only authority state. `r09-regression.py` runs a valid disposable copy, a one-byte mutation, and a missing-parent-reference mutation; the latter two must return `BLOCKED`. Outputs are written only under `/private/tmp`.

Recorded counters are:

- candidate ZIP/API requests: `0`;
- PDOK requests: `0`;
- OSM requests: `0`;
- outbound provider messages: `0`;
- approved weather sources: `0`;
- `DatasetSnapshots` published: `0`.

## Human decision required

Before any Stage 2 source path, a human research lead must choose whether to seek direct provider clarification, assess an alternative source, or authorize a fully evidenced derived-method proposal. The next decision must name the method, exact source/version, timestamp rule, transformation (if any), limitations, scope, and approver. Until then, the three retained Rotterdam TMYx files remain unapproved and their interval semantics remain unresolved.
