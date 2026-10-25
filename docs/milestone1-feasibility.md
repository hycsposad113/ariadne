# Milestone 1 tool feasibility evidence

Probe date: 2026-09-14. The original `.milestone1-probe-output*` directories are
preserved historical evidence and were not modified. M1-R01 writes remain in
their original fresh-run directories. M1-R02 writes each probe to a fresh
`.milestone1-r02-runs/run-<timestamp>-<id>/` directory with separate raw QGIS,
raw climate, bounded pytest, composite, and gate-manifest records. The latest
bounded run is:

`.milestone1-r02-runs/run-20260914T211554Z-08fd3bd52079/`

The climate fixture is a controlled two-hour smoke input; it is not an EPW and
produces no design conclusion. The final rerun used a fresh disposable QGIS
profile and completed the bounded facade and read-only MCP checks.

## Gate result

Implementation files under review are the typed domain/store/adapter modules
under `src/urban_design/`, including `geometry.py`, `probe_contracts.py`,
`gates.py`, and `qgis_facade.py`; tests and the locked fixtures are under
`tests/`.

| Gate | Result | Evidence |
|---|---|---|
| SEC-001/SEC-002 forbidden QGIS operations | PASS | Owned tests reject unrestricted operations, path escapes, and unapproved parameters; the latest run persists a typed denial audit with `dispatched=false` and `transport_called=false`. |
| SEC-003 serialized QGIS dispatch | PASS (owned test) | The facade lock test proves concurrent calls are serialized. |
| SEC-005 post-dispatch recovery | PASS (simulation) | Owned tests require artifact hash, project revision, and ledger evidence before resolving `OUTCOME_UNKNOWN`; no blind retry is allowed. |
| SEC-006 bounded QGIS MCP geometry route | PASS | The live facade dispatched fixed `urban.buffer_fixture` through the QGIS MCP socket, produced a non-empty artifact, linked state/ledger records, and passed the independent read-only geometry checks. |
| CLM-001 Ladybug screening | PASS | `RadiationStudy` completed for baseline, -1 m, and +1 m. Each run returned a nonzero radiation value, an area-weighted total, and a hash manifest. |
| CLM-002 Honeybee-Radiance verification | PASS | Translation, cumulative sky matrix, octree, sky dome, and `dc scoeff` incident-radiation calculation completed for all three offsets. Each run has finite values, a spatial sensor artifact, command return codes, and SHA-256 manifests. |

The machine-readable M1-R02 gate manifest reports `PASS` for all 11 required
gates. Each record contains the gate id, mapped test ids, fixture/run id,
expected and observed values, relative evidence references with SHA-256 and
size, status, and the automated reviewer identity
`automated:m1-gate-runner-v1`. Static gates are `BLOCKED` when a mapped pytest
node is not collected and passing. Runtime gates revalidate source-report
hashes, controlled offsets, units, sensor semantics, command return codes,
non-empty artifacts, incident values, spatial artifacts, and the QGIS ledger
link. Missing mandatory evidence is never promoted to PASS. Full EVD-005 replay
remains a Weeks 7–8 release gate; Week 1 records only the foundation replay
checks.

## Historical evidence retained from the prior probe

The following QGIS and climate paragraphs retain earlier probe details for audit
context. The current gate state is the table above and the machine-readable
manifest in the latest run directory.

## QGIS-LTR and MCP evidence

The host is an Apple Silicon Mac with `arm64` architecture. The installed QGIS
binary is Intel `x86_64`:

```text
/Applications/QGIS-LTR.app/Contents/MacOS/QGIS: Mach-O 64-bit executable x86_64
QGIS 3.40.5-Bratislava 'Bratislava' (8d6d1b54486)
Python version 3.9.5
Qt version 5.15.2
GDAL/OGR version 3.3.2
PROJ version 8.1.1
GEOS 3.9.1-CAPI-1.14.2
```

The disposable QGIS profile used for the smoke contains the `QGIS MCP` plugin,
version `0.14.0`, licensed `GPLv2+`, with declared QGIS compatibility `3.28`
through `4.99`. The project environment contains `qgis-mcp-server` version
`0.14.0` at
`.venv/bin/qgis-mcp-server`. The plugin and server versions match.

The live connection method was `MCP stdio client -> QGIS MCP TCP socket
127.0.0.1:9876`. A bounded stdio session completed `initialize`, `ping`,
`diagnose`, and `list_tools`; the server reported 118 tools and `ping` returned
`{"pong": true}`. `diagnose` returned `healthy`, QGIS `3.40.5-Bratislava`,
plugin version `0.14.0`, server version `0.14.0`, no client version drift, and
the expected QGIS processing providers. The socket-only probe also returned
`connected`.

The facade geometry smoke used the fixed `urban.buffer_fixture` operation. Its
injected adapter has no algorithm pass-through: it calls the fixed
`native:buffer` operation with distance `10 m` and four segments, reloads the
result, and records a `ToolExecution` state revision and append-only ledger
event. The artifact is non-empty (98,304 bytes) with SHA-256
`sha256:632244a8b254dc348559271a324737b3cf141328bcbc67d6c33feb4e6ea35a0e`.

A separate bounded stdio probe used only these read-only calls: `ping`,
`diagnose`, `get_layers`, and `get_layer_features(include_geometry=True)`. It
sent no privileged call; the recorded `privileged_calls_dispatched` list is
empty. On disposable layers named `m1_point` and `m1_buffer`, the deterministic
checks were:

* `m1_point`: one feature, WKT `Point (0 0)`;
* `m1_buffer`: one feature, bounding box `[-10.0, -10.0, 10.0, 10.0]`.

This is a live QGIS MCP transport and geometry response smoke. It does not
claim that later site operations are implemented; the owned policy facade
rejects raw arbitrary execution and the report keeps that boundary explicit.
The current QGIS project has no saved project path and
contains four disposable smoke layers; this is suitable for connectivity
evidence but not site evidence.

The host sandbox cannot open loopback sockets and returned
`PermissionError: [Errno 1] Operation not permitted` for the identical socket
probe. The final M1-R02 rerun used a fresh disposable profile and completed the
bounded live facade smoke. The earlier M1-R01 evidence remains preserved
separately.

`qgis_process --version` exited 0 but emitted two
`Cannot find proj.db` warnings on stderr. The version and binary were still
reported; a clean deployment should verify the QGIS PROJ data path. A clean
ARM-native QGIS installation was not available. The documented target profile
therefore uses the verified Intel QGIS-LTR binary under the host's Rosetta
translation layer, with the QGIS MCP server running from the project Python
environment and a disposable QGIS profile. This is an explicit local fallback
and makes no portability claim for a native ARM QGIS deployment or for other
machines; native ARM verification remains a pre-release deployment task.

The default QGIS profile was not used for the smoke. A temporary copy that was
placed there during setup was moved to `/private/tmp/qgis-default-plugin-m1-backup`
after verification; the default profile is clean again.

## Climate runtime and fixture

The project `.venv` is Python `3.12.13` on `arm64`. Installed package versions
reported by import metadata are:

| Package | Version |
|---|---:|
| `ladybug-core` | 0.44.59 |
| `ladybug-geometry` | 1.35.4 |
| `ladybug-radiance` | 0.2.12 |
| `honeybee-core` | 1.64.68 |
| `honeybee-radiance` | 1.66.288 |
| `honeybee-schema` | 2.2.0 |
| `honeybee-energy` | unavailable |

The controlled fixture is
`tests/fixtures/climate_smoke.json`, hash
`sha256:50446a0ca8ff85749fc48002ebf5eb559bdc6b7649dd80bd9f974a096386f533`.
It defines local Cartesian metres, a 4.0 m2 horizontal sensor, one 3 m by 3 m
by 3 m context building, and offsets `0`, `-1`, and `+1` m along the x axis.
Its two WEA records use DNI/DHI values in W/m2. The generated WEA artifact was
nonempty (151 bytes), hash
`sha256:78bc2a745acf1b4e6e5c7e512cee9783448795f0267d00b2a7a990c614a3ddb3`.

### Radiance runtime

The first unconfigured attempt recorded
`AssertionError: No Radiance installation was found.` and remains preserved as
the failure mode that motivated the remediation. A bounded remediation then
downloaded the official [LBNL-ETA Radiance 6.0.2 macOS ARM64 archive](https://github.com/LBNL-ETA/Radiance/releases/download/rad6R0P2/Radiance_c1700d56_OSX_arm64.zip), verified
SHA-256
`329ca788c6cedc641ad47577ce985ae16ee291acb1d5d02d7995192d58118cf0`, and
extracted it to the disposable runtime path
`/private/tmp/radiance-arm64/radiance`. The probe ran with:

```text
BINPATH=/private/tmp/radiance-arm64/radiance/bin
PATH=/private/tmp/radiance-arm64/radiance/bin:$PATH
RAYPATH=/private/tmp/radiance-arm64/radiance/lib
```

All six required commands (`rad`, `gendaymtx`, `rtrace`, `rfluxmtx`, `oconv`,
and `rmtxop`) resolved from that path. `rtrace -version` returned
`RADIANCE 6.0.2 2026-02-02 LBNL (6.0.c1700d56cc)`. The runtime is intentionally
outside the project `.venv`; the package environment and external executable
environment remain separate. The source archive URL and the complete inventory
are retained in the climate source report.

### Ladybug/ladybug-radiance

All three fixture runs reached `RadiationStudy`, invoked the configured
Radiance executables, extracted radiation values, and wrote non-empty result
artifacts. The observed values were:

| Offset | Radiation value (kWh/m2) | Area-weighted total (kWh/m2) |
|---:|---:|---:|
| 0 m | 1.1516186493 | 4.6064745972 |
| -1 m | 1.1458213933 | 4.5832855730 |
| +1 m | 1.1581441201 | 4.6325764806 |

The run records the 4.0 m2 sensor, local metre geometry, W/m2 weather inputs,
fixture hash, weather hash, package versions, Radiance command paths, and
artifact manifests. These values are feasibility outputs only and are not a
thermal-comfort conclusion.

### Honeybee-Radiance

For all three offsets, `honeybee-radiance translate model-to-rad-folder` exited
0, `honeybee-radiance sky mtx ...` generated a non-empty cumulative sky matrix,
and `honeybee-radiance octree from-folder ...` generated a non-empty octree with
return code 0. The verification records retain command lines, return codes,
stdout/stderr, sensor area, weather hash, package versions, and manifests for
the HBJSON, RAD, PTS, sky-matrix, octree, and WEA artifacts. The screening and
verification records remain separate; their absolute values are not compared.

## Uncertain execution and security evidence

`reconcile_outcome` is exercised with a controlled local artifact simulation,
not a fabricated QGIS or climate result. It returns `SUCCEEDED` only when the
expected artifact hash matches, the observed project revision equals the
expected revision, and an authoritative ledger record is present. Missing or
insufficient evidence remains `OUTCOME_UNKNOWN`; an existing artifact with a
wrong hash becomes `TOOL_FAILED`; every branch sets `retry_allowed` to false.

The product `QgisFacadePolicy` permits only the documented `urban.*` operation
names and operation-specific parameter keys. It bounds input/output paths to
an explicit controlled root, checks finite positive metric parameters and
identifier fields, and rejects caller-supplied algorithms or code fields. The
probe validator applies the same operation allowlist before any external
dispatch. Both reject arbitrary Python, dynamic Python, unrestricted SQL, and
batch aliases with `PermissionError`.

The local verification run completed with `58 passed` and a clean `py_compile`
check for all `src/urban_design` and `scripts` Python modules. The M1-R02
bounded gate runner collected and passed all 11 mapped nodes in its persisted
JUnit and JSON records.

## Red-team review

The controller rechecked the implementation after the real tool runs. Typed
evidence validation rejects wrong-project, wrong-scenario, wrong-dataset,
wrong-unit, stale-tool, and mismatched-artifact relationships. SQLite append-only
triggers reject historical updates and deletes; the transaction test confirms a
ledger failure rolls back the state revision. The QGIS policy rejects unknown
operations, forbidden aliases, extra parameters, unsafe paths, invalid ranges,
and missing required fields. The live route dispatched only the fixed
`native:buffer` adapter and the independent MCP probe dispatched no privileged
call. An uncertain post-dispatch result remains `OUTCOME_UNKNOWN` without a
blind retry until artifact hash, project revision, and ledger evidence all
reconcile. Climate output checks reject zero-byte files and verify every
manifest hash, keeping the screening and verification tiers distinct.

The remaining findings are deployment risks rather than Milestone 1 blockers:
the installed QGIS binary is Intel on an ARM host and emits `proj.db` warnings,
native ARM QGIS and clean-machine reproduction are still unverified, and the
Radiance runtime is a disposable external installation. `honeybee-energy` is
not installed but is not required by this bounded fixture. No red-team check
found a condition that blocks the next milestone within the documented local
profile.

## Reproduction

Run the owned tests with:

```text
python3 -m pytest tests/test_tool_feasibility.py -q
```

Run the full bounded environment probe with the climate environment using:

```text
BINPATH=/private/tmp/radiance-arm64/radiance/bin \
PATH=/private/tmp/radiance-arm64/radiance/bin:$PATH \
RAYPATH=/private/tmp/radiance-arm64/radiance/lib \
./.venv/bin/python scripts/tool_feasibility_probe.py --output-dir .milestone1-r02-runs
```

The latter command needs loopback access for the QGIS section. Under the
restricted sandbox it records the exact socket permission failure while still
running the climate probes. Each run writes separate raw source reports and a
composite report; the composite records each source path, hash, timestamp, and
status without self-reference.

## Blockers and risks

There is no unresolved mandatory Milestone 1 feasibility blocker in the current
local profile. `honeybee-energy` is absent, although it was not required by the
bounded fixture commands. QGIS uses an Intel binary on an ARM host, so the
explicit deployment fallback is Rosetta translation; native ARM portability and
clean-machine reproduction remain pre-release risks. The Radiance runtime is a
disposable `/private/tmp` installation and must be provisioned from the pinned
archive digest before a fresh machine run. The raw third-party QGIS MCP surface
exposes privileged tools; the product must keep using the explicit allowlisted
facade and retain independent artifact/project reconciliation after any lost
connection.
