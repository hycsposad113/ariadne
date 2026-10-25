# M2-A03-R07 — EPW Minute=0 compatibility and derived-file method evaluation

**Task status: PASS (evaluation delivered; `HUMAN RESEARCH-METHOD DECISION REQUIRED`)**

This is an offline evaluation of the three retained M2-A03-R06 Climate.OneBuilding responses. It does not select a station, publish an EPW candidate, create a `DatasetSnapshot`, rerun r03, or start climate analysis. No network request was made in R07 (`network_requests=0`). The retained R06 originals remain the only source evidence.

The EPW contract checked here is the current deterministic validator in `src/urban_design/m2a03_sources.py`: UTF-8 `LOCATION`, 35 columns, 8,760 or 8,784 rows, complete month/day/hour sequence, `Minute=60`, valid timestamp ranges, and finite weather fields. The official reference retained in the R05/R06 evidence is the [EnergyPlus EPW Data Dictionary](https://bigladdersoftware.com/epx/docs/23-1/auxiliary-programs/energyplus-weather-file-epw-data-dictionary.html), together with the [Climate.OneBuilding Netherlands index](https://climate.onebuilding.org/WMO_Region_6_Europe/NLD_Netherlands/index.html). The official field specification permits Minute values in the `1..60` range; this project contract requires the end-of-hour value `60` for the hourly rows.

## Retained originals and offline revalidation

Every file listed by each R06 diagnostic integrity manifest matched its recorded size and SHA-256. Each ZIP passed `ZipFile.testzip()`, contained seven members and exactly one EPW member, and the extracted EPW hash and size were rechecked. All three original EPWs have 8,760 rows, 35 columns, the same `DATA PERIODS,1,1,Data,Sunday,1/ 1,12/31` line, complete month/day/hour coverage, no duplicate or missing keys, and no non-finite weather values. All three fail the current validator at row 9 because `Minute=0`.

| Candidate | URL / station | ZIP bytes / SHA-256 | EPW bytes / SHA-256 | EPW first → last row | source years | station / distance to v5 | original validator |
|---|---|---|---|---|---|---|---|
| 01 | `https://climate.onebuilding.org/WMO_Region_6_Europe/NLD_Netherlands/ZH_Zuid-Holland/NLD_ZH_Rotterdam.The.Hague.AP.063440_TMYx.2011-2025.zip` / WMO 063440, 51.96060, 4.44690 | 424,691 / `faa7a3bc8e6e67c7957b3d726ebeaa6ff521610d1dcfe06eca0294becf0c6a91` | 1,593,131 / `3c9a109d7f0b2e54c2b204d592bf5ec59774d16f36054bb89c284db4b5f7802a` | `2012,1,1,1,0` → `2018,12,31,24,0` | 2011, 2012, 2015, 2016, 2017, 2018, 2021, 2022, 2024, 2025 | EPSG:28992 `(90372.0327,441770.2491)` / 5,633.3177 m | **FAIL**, row 9 `Minute=0`, expected `60` |
| 02 | `https://climate.onebuilding.org/WMO_Region_6_Europe/NLD_Netherlands/ZH_Zuid-Holland/NLD_ZH_Rotterdam.The.Hague.AP.063440_TMYx.2009-2023.zip` / WMO 063440, 51.96060, 4.44690 | 425,323 / `d912682d6192eac0f58d4599a614876b868e370f7e7af63e54a9db6e2cae46cc` | 1,592,314 / `ed73b9e453d7cf36fe16dbe3d24d2ab025cac41939b31a300e736a10c6fd3813` | `2015,1,1,1,0` → `2020,12,31,24,0` | 2009, 2010, 2012, 2013, 2015, 2016, 2017, 2018, 2020, 2022 | EPSG:28992 `(90372.0327,441770.2491)` / 5,633.3177 m | **FAIL**, row 9 `Minute=0`, expected `60` |
| 03 | `https://climate.onebuilding.org/WMO_Region_6_Europe/NLD_Netherlands/ZH_Zuid-Holland/NLD_ZH_Rotterdam.Geulhaven.AWS.063430_TMYx.zip` / WMO 063430, 51.89095, 4.31159 | 420,600 / `bd4ad7f54b6d504f2038dc1cd2a73fa2d4cb385bcb9945bff92aa81a198570c4` | 1,578,936 / `ff3d49802ed5c201bfc8ad5c5be42d0bb99ae6aa1e3ca8ea486e4f42347cbd10` | `1995,1,1,1,0` → `1998,12,31,24,0` | 1994, 1995, 1996, 1997, 1998 | EPSG:28992 `(80957.7996,434150.8367)` / 7,808.8881 m | **FAIL**, row 9 `Minute=0`, expected `60` |

The distances are comparison observations only. They are not a station-approval or selection rule. The source years vary within the TMYx rows and were preserved; R01 already removed the over-strict uniform-year check while retaining the actual chronology and finite-field gates.

## Experimental 0→60 copies

For each original EPW, a temporary copy was made under:

`/private/tmp/m2-a03-r07-minute-evaluation.uaPgb8/`

The transformation was limited to data rows whose fifth field was exactly the string `0`; it replaced that field with `60` and preserved line endings. It did not reorder rows, change headers, change any other column, or change a weather value. The experiment results are recorded in `evaluation.json`, with generated-file hashes and sizes in `temp-integrity-manifest.json`. These files are outside the authoritative artifact root.

For all three candidates:

- 8,760 of 8,760 Minute fields changed from `0` to `60`.
- Headers are identical; row count and row order are identical.
- Every one of the other 34 columns is byte-for-byte equal for every row.
- The derived file is exactly 8,760 bytes larger because one-character `0` values became two-character `60` values.
- The derived copy passes `_epw_metadata`; no source selection or publication was performed.

The derived EPW sizes and SHA-256 values are:

| Candidate | derived bytes | derived SHA-256 |
|---|---:|---|
| 01 | 1,601,891 | `d6cc646473f2805002e28c99d13eb0c6d5fa08d40734b8fb2c89dbaae1371369` |
| 02 | 1,601,074 | `bc9585b17a16429544770ba8ac1e0ac75b23eeaf4e4b76d5a09b76f01b79b431` |
| 03 | 1,587,696 | `08850c8629b63a4f7dc27497df14e172de25a0e0b247def39414578aaef563b6` |

Negative controls were also run in memory, then passed through the same proposed transformation and the existing validator. A non-zero `Minute=30`, a mixed `0/30` file, a missing row, and a 36-column row all remained **FAIL**. The transformation therefore does not turn those structural defects into a pass.

## Ladybug comparison

`ladybug.epw.EPW.from_file_string` read both the retained raw file and the derived copy for all three candidates. Each parse produced 35 collections with 8,760 values, and the same first and last Ladybug datetime (`01 Jan 00:00` and `31 Dec 23:00`) and `is_leap_year=false`.

The raw-versus-derived comparison found exactly one collection difference: the EPW Minute collection (collection index 4) changed from all `0` to all `60`. The Year, Month, Day, and Hour collections, all 30 weather-value collections, headers, analysis periods, row order, and Ladybug datetime index were equal. This establishes **program readability** and **data-preserving format compatibility** for the copies. It does not establish that the provider's `Minute=0` convention has the same time-boundary meaning as the EPW `Minute=60` convention.

## Time, boundary, and solar-radiation limits

No deterministic comparison showed a row shift or a month/day/hour boundary change. The transformation intentionally leaves the hour field, day/month, `DATA PERIODS`, source years, and every weather value untouched. Ladybug also produced the same derived datetime index in this test.

Semantic equivalence remains **UNRESOLVED**. The retained source evidence does not include a Climate.OneBuilding/provider statement explaining whether its `Minute=0` rows represent the beginning of each hour, an end-of-hour record encoded with a non-conforming value, or another convention. Changing only Minute to `60` can make a file satisfy the project validator while still changing how a downstream consumer treats the reporting endpoint. In particular, equivalence at midnight/day boundaries and the timestamp used for solar-position interpretation cannot be inferred from unchanged radiation numbers or from Ladybug's parser behavior. No climate calculation was run to hide or resolve this ambiguity.

## Decision options and recommendation

**Option A — retain originals plus an explicit derived EPW.** Keep each R06 ZIP and EPW immutable, record a versioned transform whose sole rule is `Minute=0 → Minute=60`, retain parent hashes and the exact row-level comparison, and submit the time-semantics question for an explicit research-method decision before any formal candidate is selected or published. Acceptance would require a human-approved method record and evidence that this mapping is the intended provider convention for these files.

**Option B — find a source or provider clarification with conforming Minute semantics.** Obtain a new authorized source response or authoritative source documentation with `Minute=60` (or an explicitly documented equivalent), then repeat the ordinary source gate. No such request was made in R07.

The evidence supports keeping Option A as a traceable research option, but it does not authorize adopting it. Option B is preferred for source fidelity until the provider semantics or a human-approved research method resolves the ambiguity. Neither option selects a station in R07.

## Authority and scope checks

The read-only runtime check after the offline experiment found:

- active StudyArea: `study-area-rotterdam-m4h-pilot-project-v5`, `CONFIRMED_FOR_EXPLORATION`, geometry SHA-256 `3dedb804fa4f07f4c9570bcc64e68c8d576c03340455ab35fd4963bca52aa4f5`, artifact SHA-256 `9a59159505505dbe658ec6667ecfeb9024b868faf6377e7cd91889c763170d32`;
- v4 remains present and `SUPERSEDED`, with geometry SHA-256 `73b36df67a2de3c5aea65ae1275dd814c7e08af5aead05a2d0728c52906bfce4` and artifact SHA-256 `63a51c22550dbd318d55f534a5e080db2bb583dbd1c886c45356254e28cf7839`;
- ledger event count remains 24 and the latest event is the prior r03 `SnapshotObservation` record;
- `DatasetSnapshot` rows remain 0;
- the blocked r03 package remains blocked, and its 13-entry package manifest revalidated with zero mismatches;
- no PDOK, OSM, QGIS, Hermes, accessibility, morphology, or climate-analysis work was performed.

The only project file added for R07 is this decision document. The EPW copies, evaluator, JSON evidence, and temporary integrity manifest remain under `/private/tmp`; no formal source, Artifact, DatasetSnapshot, SQLite, ledger, or r03 file was changed.

## Reproducibility and tests

The offline evaluator is retained at `/private/tmp/m2-a03-r07-minute-evaluation.uaPgb8/evaluate.py`. Its output is `/private/tmp/m2-a03-r07-minute-evaluation.uaPgb8/evaluation.json`; the generated-file manifest is `/private/tmp/m2-a03-r07-minute-evaluation.uaPgb8/temp-integrity-manifest.json`.

The existing 37 focused M2-A03 tests were collected and passed:

```text
PYTHONPATH=src .venv/bin/pytest -q tests/test_m2a03_sources.py tests/test_m2a03_analysis_inputs.py
37 passed in 6.73s
```

No production code changed, so the full suite was not rerun under the packet's no-code-change rule.

**Unresolved issue:** the raw candidates are not formally valid under the current EPW gate, and the 0→60 copies are not approved derived sources. **HUMAN RESEARCH-METHOD DECISION REQUIRED** (or a new authorized source/provider clarification) before M2-A03 can publish a candidate or DatasetSnapshot.
