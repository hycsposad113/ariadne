# M2-A03-R08-R01 — Acceptance-gate repair addendum

**Task status: PASS for the repaired verifier; source semantics remain `SEMANTICS_UNRESOLVED`.**

R08-R01 repairs the acceptance boundary of the retained R08 Minute-semantics
review without rewriting that package or approving a weather source. The
repair package is
`artifacts/milestone2-analysis-inputs-rotterdam-m4h/m2-a03-r08-r01-verifier-repair-20260919T172048Z/`.
It records 53 input files from the retained R08 integrity manifest by path,
size, and SHA-256. The retained R08 manifest independently revalidated with
all 53 files matching.

## Corrected evidence chain

The historical R08 review document cited
`sha256:cb177c88d32479d4900bc2895ec403b004666f49acb0cdd063206b188d40f4ef`
for `r08-verification-result.json`. The retained result currently on disk is
instead 10,734 bytes with SHA-256
`sha256:f63f92f136e533c94f7f7917a2df64b5147dab6423666a2100d3f9ac3335ea6a`.
R08-R01 records both values as historical evidence and does not replace the
retained result. The corrected read-only verifier is
`r08-r01-verify.py`; its single frozen result is
`frozen-verification-result.json`, 15,643 bytes with SHA-256
`sha256:49d0f3408892fc9412e01a47af74c154626bc69d50f88e3804218a5db85a3bab`.

The frozen result is `PASS` for the verifier only. It requires the R08 input
manifest and references to match, the three copied R06 manifests to match,
ZIP opening and CRC checks to pass, the sole ZIP EPW member to match the
preserved source EPW, the R07 original copy to match that source, the R07
derived hashes to match its integrity manifest, and the raw/derived validator
and transformation records to agree. It also requires all row-level
non-Minute fields, headers, Year/Month/Day/Hour values, weather values,
Ladybug headers, and full datetime indices to match; the only allowed change
is the recorded `Minute=0` to `Minute=60` experiment. Every gate is explicit
in the frozen result (69 gates across the three candidates and package-level
checks).

The verifier accepts an explicit disposable output path only. It rejects a
path inside the repair package, so a later invocation cannot overwrite the
frozen result. `r08-r01-regression.py` records 63 independent candidate-gate
fault injections; each changed gate produces `BLOCKED`. It also records a
later verification to a disposable path leaving the frozen result byte-for-
byte unchanged, and rechecks all 53 retained R08 input hashes.
The repair integrity manifest lists six package files; its SHA-256 is
`sha256:b4e19158bd158db3fb80ed3900e03d694c06453c6c6cdf19bcb59a4bb22ce488`.

## Source and project state

The source conclusion remains `SEMANTICS_UNRESOLVED`. The provider-hosted
generic EPW dictionary's `0..60` statement is not provider-specific evidence
for the three Rotterdam files, and the project's `Minute=60` validator remains
an implementation contract. R08-R01 made zero candidate ZIP/API requests,
published zero weather Artifacts, and published zero DatasetSnapshots. It did
not rerun r03, modify the source validator, perform a conversion, or begin
accessibility, morphology, PDOK, OSM, or climate analysis.

The active StudyArea remains v5, with the retained R08 authority state and
ledger unchanged (ledger sequence 24; DatasetSnapshot count 0). R05, R06, R07,
the blocked r03 package, the v1-v5 StudyArea evidence, SQLite state, QGIS
state, and Hermes state remain byte-preserved.

This addendum is a repair record and does not choose between retaining the
originals plus a future explicitly approved derivative and obtaining
provider-specific timing clarification or another documented source.
