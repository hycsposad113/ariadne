# Fixed R04/R01 fixture for the R02 verifier

This synthetic, local fixture is used only to exercise the production R04/R01 verifier and R02 disposable-clone fault harness. Its records carry `fixture_only: true` where applicable; source and snapshot identifiers are explicitly synthetic. It does not claim to be retained R04 evidence and is not a source for design or planning analysis.

The project tree includes a minimal valid base package, an R01 amendment, the matching public R01 docket, and one declared external helper parent. The R02 regression test verifies the outer fixture manifest before invoking the real R02 CLI.
