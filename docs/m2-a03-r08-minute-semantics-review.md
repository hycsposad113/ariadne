# M2-A03-R08 — Persistent Minute semantics review

**Task status: PASS for the review package; source semantics: `SEMANTICS_UNRESOLVED`**

R08 preserves the R07 offline evaluation in a new append-only review package. It does not publish a weather `Artifact` or `DatasetSnapshot`, select a station, approve `Minute=0 → 60`, rerun r03, or start climate analysis. Candidate ZIP/API request count is zero. The existing R05, R06, R07, blocked r03, SQLite, ledger, StudyArea, QGIS, and Hermes state remain outside the package and were not rewritten.

## Persistent package

The review package is:

`artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-minute-semantics-20260919T154701Z/`

Its `integrity-manifest.json` contains 53 frozen evidence files with relative paths, sizes, SHA-256 values, and parent-path hashes. `r08-verification-result.json` is generated verifier output and is intentionally excluded from its own input manifest to avoid a self-hash cycle; its size is 10,734 bytes and SHA-256 is `cb177c88d32479d4900bc2895ec403b004666f49acb0cdd063206b188d40f4ef`.

The package contains, in separate namespaces:

- `source-originals/candidate-01..03/response.zip`: exact copies of the three R06 response ZIPs;
- `source-originals/candidate-01..03/epw/`: the exact single EPW member from each ZIP;
- the R06 diagnostic manifest, source record, URL, headers, status, timestamps, and curl receipts;
- `r07-evaluation/evaluate.py`, `evaluation.json`, and the original R07 temporary manifest copied byte-for-byte;
- `r07-evaluation/candidate-01..03/original.epw`: verified R07 copies of the source EPW;
- `r07-evaluation/candidate-01..03/derived-minute60.epw`: the unapproved R07 experimental outputs;
- `lineage.json`, `source-semantics/source-evidence.json`, `authority-state.json`, and `r08-verify.py`.

The lineage file distinguishes source originals from unapproved derived experiments. For every candidate, the R08 source EPW matches the only EPW member of the copied R06 ZIP, the R07 original copy matches that source EPW, and the derived file is related only by the recorded `Minute=0 → Minute=60` experiment.

## Revalidation from the new location

`r08-verify.py` was run from the new package with:

```text
PYTHONPATH=src .venv/bin/python artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-minute-semantics-20260919T154701Z/r08-verify.py
```

The result is `PASS` with zero manifest failures. All three source archives pass ZIP CRC validation and all source/member hashes match their R06 manifests. For every candidate, the source/original EPW still fails the current project timing gate at row 9 with `Minute=0`; the derived copy passes. All three preserve headers, row order, all 34 non-Minute columns, and all weather values. Ladybug reads both files, and the only data-collection difference remains the Minute collection.

The R07 negative controls remain recorded as failures for non-zero or mixed Minute, missing row, and wrong column count. R08 additionally exercised the persistent verifier with synthetic missing-file, hash-mismatch, and parent-mismatch inputs; each returned `BLOCKED` without modifying the package.

## Public first-party source investigation

The investigation used only read-only public Climate.OneBuilding pages and the provider-hosted EPW dictionary. No candidate ZIP or API endpoint was requested. The full evidence record, retrieval timestamp, search scope, page locations, supported claims, and limitations is [source-evidence.json](../artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-minute-semantics-20260919T154701Z/source-semantics/source-evidence.json).

The [Climate.OneBuilding home page](https://climate.onebuilding.org/) describes TMYx as created by the site authors from hourly ISD data and identifies the 2011–2025 and 2009–2023 releases. The [Netherlands provider index](https://climate.onebuilding.org/WMO_Region_6_Europe/NLD_Netherlands/index.html) lists the three Rotterdam file families, but neither page states how their Minute field is intended to encode an interval endpoint.

The provider-hosted [EnergyPlus EPW Data Dictionary](https://climate.onebuilding.org/papers/EnergyPlus_Weather_File_Format.pdf) gives the generic format rule: Hour 1 is `00:01`–`01:00`, Minute is `0..60`, and Minute is not used directly by the simulation. Its DATA PERIODS section describes records per hour and requires multiple interval records to match the simulation time steps. This is first-party format evidence, but it is not a provider statement about the semantics of these three specific Rotterdam files.

This changes the evidentiary classification of an earlier statement without rewriting the immutable R07 package: `Minute=0` is within the provider-hosted generic EPW dictionary's stated `0..60` range. The project's `Minute=60` check remains an implementation contract. It must not be presented as proof that the source provider rejects `Minute=0`, and the generic rule must not be presented as proof that a 0→60 transformation is semantically equivalent for these files.

**Conclusion: `SEMANTICS_UNRESOLVED`.** No inspected first-party Climate.OneBuilding page explicitly explains whether `Minute=0` in these Rotterdam TMYx files means the start of an hour, an end-of-hour record encoded with zero, or another convention. EnergyPlus rules and Ladybug parser behavior cannot substitute for that provider-specific evidence. Midnight/day-boundary and solar-radiation timestamp interpretation therefore remain unresolved.

## Authority-state check

The read-only state capture in `authority-state.json` records the post-copy check:

- active StudyArea v5 remains `CONFIRMED_FOR_EXPLORATION` with geometry SHA-256 `3dedb804fa4f07f4c9570bcc64e68c8d576c03340455ab35fd4963bca52aa4f5` and artifact SHA-256 `9a59159505505dbe658ec6667ecfeb9024b868faf6377e7cd91889c763170d32`;
- v4 remains `SUPERSEDED` with its prior hashes;
- ledger count remains 24 and the last event remains the r03 `SnapshotObservation`;
- DatasetSnapshot count remains 0;
- r03 remains `BLOCKED` and its 13-entry package manifest has zero mismatches.

No QGIS or Hermes process was started or disturbed. R08 did not send an HTTP request to port 8787.

## Method decision boundary

Option A remains available for human review: retain each source ZIP/EPW unchanged and create an explicitly versioned derived EPW with the exact row-level comparison and parent hashes. It is still unapproved. Option B is to obtain provider-specific clarification or another source whose timing convention is documented. R08 does not choose between them and does not authorize a DatasetSnapshot.

The narrow documentation correction in `docs/07_IMPLEMENTATION_PLAN.md` records the R08 source-spec finding while preserving the R05/R06/R07 historical evidence. No production source or validator was changed.
