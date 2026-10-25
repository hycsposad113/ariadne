"""Acceptance checks for the executable Space Syntax feasibility probe."""

import math

from scripts.probe_space_syntax import run_space_syntax_probe


def test_space_syntax_probe_matches_hand_counted_square_cycle_reference():
    report = run_space_syntax_probe()

    assert report["status"] == "PASS"
    square = report["test_results"]["square_cycle_fixture"]["output_sample"]
    for segment_id in ("sq_A", "sq_B", "sq_C", "sq_D"):
        assert math.isclose(square[segment_id]["integration"], 0.75, abs_tol=1e-6)
        # Each square segment receives half of one equal-route opposite-pair
        # path under this probe's undirected fractional-choice convention.
        assert math.isclose(square[segment_id]["choice"], 0.5, abs_tol=1e-6)
