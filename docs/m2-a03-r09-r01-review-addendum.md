# M2-A03-R09-R01 — Weather-method evidence repair addendum

**Task status: PASS for the bounded evidence repair; weather semantics remain `SEMANTICS_UNRESOLVED`.**

This append-only repair adds two first-party KNMI documentation captures to a new package at
`artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r09-r01-alternative-evidence/`.
It does not modify the original R09 docket or package, the R08/R08-R01 evidence, r03,
production code, SQLite, the ledger, QGIS, or Hermes. It does not select a station,
download a candidate weather file, convert an EPW, publish a DatasetSnapshot, or begin
climate analysis.

## Stage 0 recheck

The retained R08-R01 disposable preflight completed `PASS` with 53 input files, three
candidates, and no acceptance failures. The frozen result remains 15,643 bytes with
SHA-256 `sha256:49d0f3408892fc9412e01a47af74c154626bc69d50f88e3804218a5db85a3bab`.
The retained R09 package remains a 21-file, hash-consistent `PASS` package with
`SEMANTICS_UNRESOLVED`; r03 remains `BLOCKED` with 13 manifest files, zero artifacts,
and zero source snapshots. The live observation captured for this repair is StudyArea
v5 `CONFIRMED_FOR_EXPLORATION`, active pointer v5, ledger 24, and DatasetSnapshot count
0. Those live values are recorded separately from archival parent checks.

## Chronology correction

The retained R09 records establish the following observed chronology for the same KNMI
10-minute documentation URL:

| observed order | retained record | status | UTC time |
| --- | --- | --- | --- |
| 1 | `doc-05` / `knmi-10-minute.txt` | HTTP 200 | `2026-09-20T12:59:07Z` |
| 2 | `doc-05-initial-403` / `knmi-10-minute-initial-403.txt` | HTTP 403 | `2026-09-20T13:05:59Z` |

The original bytes and historical identifiers remain unchanged. The new record uses only
these timestamps and the observed order. No evidence supports assigning an initial or
retry label to either record; the filename and request identifier are retained as byte
labels, not as temporal semantics.

## Newly captured first-party evidence

The KNMI [validated hourly dataset page](https://dataplatform.knmi.nl/dataset/hourly-in-situ-meteorological-observations-validated-1-0)
was captured at 2026-09-20T13:47:54Z–13:47:57Z, HTTP 200, response Date
2026-09-20T13:47:56Z. Its retained body is 26,218 bytes and its redacted response
headers are 780 bytes; both hashes are recorded in the package manifest. The page states
that the product is version 1.0, covers observations from 1951-01-01 onward at an hourly
interval, uses CC BY 4.0, and is a Netherlands in-situ station product. This is source
metadata for a KNMI product, not a Rotterdam TMYx file.

The [KNMI validated-hourly technical documentation](https://dataplatform.knmi.nl/dataset/docs/hourly-in-situ-meteorological-observations-validated-1-0)
was captured at 2026-09-20T13:47:57Z, HTTP 200, response Date 2026-09-20T13:47:57Z.
It states that timestamps are stored in UTC and represent the end of the measuring
interval preceding the timestamp. Its hourly example explicitly spans
2025-01-02T23:00:00Z–2025-01-03T00:00:00Z and is represented at 00:00Z. It also states
that variable durations can differ and identifies `Q` as hourly global solar radiation,
an integral with respect to time in J/cm². The same documentation describes station
metadata, future modification of validated data, and completeness/aggregation limits.

These statements are genuine provider-specific semantics for the KNMI validated-hourly
product. They do not resolve the retained Climate.OneBuilding Rotterdam TMYx files:
there is no direct statement about their `Minute=0`, their EPW day/date boundary, their
radiation timestamp, or a 35-field EPW mapping. No KNMI station was selected; no station
coordinates/WIGOS record or underlying NetCDF/EDR variable metadata was fetched. A KNMI
observation series is not thereby a typical meteorological year. The package therefore
records KNMI as `DOCUMENTED_ALTERNATIVE_FOR_REVIEW_ONLY`, not as an approved source.

Before this route could become a method, a later human/architecture decision would need
to address station suitability and dates, a versioned weather-period or TMY method,
variable-specific metadata and missingness, EPW fields/units/header/timezone/elevation,
DST and 8760/8784 handling, global/direct/diffuse/infrared radiation treatment, and an
explicitly approved transformation and limitation record.

## Verifier boundary repair

The original R09 verifier coupled its package result to live SQLite and mutable source
hashes. That made a future legal live ledger/source change appear to damage a historical
package. R09-R01 records an archival parent set that excludes mutable live authority and
runs two independent checks:

- `archival_integrity` checks the new package, addendum, immutable R09/R08/R08-R01/r03
  parents, manifest sizes/hashes, source classifications, chronology correction, and
  forbidden-request counters.
- `current_authority_state` reads a supplied read-only SQLite path and reports `MATCH`,
  `DRIFT`, or `UNAVAILABLE` against the captured v5/ledger/snapshot observation. A
  disposable ledger advancement therefore reports authority `DRIFT` while archival
  integrity remains `PASS`; the real database is never modified.

The package-local verifier writes only to a disposable output path. Its regression script
runs a valid-copy check, a one-byte mutation check (`BLOCKED`), and a missing-parent
reference check (`BLOCKED`), then repeats the retained R08 53/53 and frozen-result hash
checks. It also exercises the simulated authority drift case without touching SQLite.

The conclusion is deliberately unchanged: `SEMANTICS_UNRESOLVED`, zero approved weather
sources, zero DatasetSnapshots, zero candidate ZIP/API requests, zero PDOK/OSM requests,
zero outbound provider messages, no conversion, and no climate or Week 3 work. The least
assumptive recommendation remains to retain `BLOCKED` pending direct provider evidence or
a human-approved research-method decision.
