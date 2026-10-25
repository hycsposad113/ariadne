# E3 Building Energy Use + E4 Thermal Mass (Four Fabrics Full Models, Final)

**Exploratory; not an energy certification.** All four schemes use full building models (Harbour grain's 253 buildings calculated in full, superseding prior 3/253 sampled extrapolation of 108.6). Ideal loads, ASHRAE 2019 CZ5, WWR 40%; fan power not reported by EnergyPlus (set to 0).

## E3 Annual Comparison (Heavy Mass Construction, Cooling & Heating On)

| Scheme | Scope | New GFA (m²) | Heating Demand (kWh-th/y) | Cooling Demand (kWh-th/y) | EUI (kWh/m²·y) | Peak Heating (kW) | Peak Cooling (kW) |
|---|---|---:|---:|---:|---:|---:|---:|
| Courtyard islands | Full model (83 buildings) | 129,350.0 | 4,905,931.2 | 759,712.5 | **63.1** | 2,805.3 | 2,317.9 |
| Harbour grain | Full model (253 buildings) | 139,128.3 | 8,549,416.0 | 1,421,076.5 | **93.4** | 4,253.4 | 4,402.8 |
| Closed block extension | Full model (168 buildings) | 126,875.4 | 9,171,886.8 | 1,333,380.4 | **100.4** | 4,293.2 | 4,303.6 |
| Landscape figure | Full model (51 buildings) | 125,492.0 | 10,541,436.0 | 1,184,047.8 | **116.1** | 4,623.2 | 4,545.9 |

## E4 Harbour Thermal Mass Sensitivity (Full 253 Buildings)

| Metric | Heavy Mass | Light Construction | Difference (Light - Heavy) |
|---|---:|---:|---:|
| Summer overheating hours (Jun–Aug >26°C, heating only, floor-weighted hours) | 840.4 | 883.9 | +43.5 |
| Winter heating demand (Dec–Feb, kWh-th) | 5,456,772.7 | 5,466,727.2 | +9,954.4 |
| Peak cooling load (cooling on, kW-th) | 4,402.8 | 4,662.7 | +259.9 |

Sources: `artifacts/w8/e3e4/` (closed, courtyard, landscape full models) and `artifacts/w8/e3e4-harbour-full/` (harbour full model); previous sampled results retained for audit.
