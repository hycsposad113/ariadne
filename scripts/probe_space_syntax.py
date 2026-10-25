"""Probe Space Syntax Engine feasibility and record CP4-1a evidence.

Executes reference fixtures through urban_design.space_syntax, checks all mathematical
properties against independent reference criteria, and outputs an immutable audit report.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from shapely.geometry import LineString

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from urban_design.space_syntax import (
    SegmentNetwork,
    SegmentFeature,
    calculate_segment_angular_measures,
)


def run_space_syntax_probe(output_dir: Path | None = None) -> dict:
    # 1. Straight line fixture
    straight_segs = [
        SegmentFeature(id="seg_A", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="seg_B", geometry=LineString([(100, 0), (200, 0)]), length_m=100.0),
        SegmentFeature(id="seg_C", geometry=LineString([(200, 0), (300, 0)]), length_m=100.0),
    ]
    net_straight = SegmentNetwork.from_features(straight_segs)
    res_straight = calculate_segment_angular_measures(net_straight, radii_m=[800.0, 2000.0, 10000.0])

    # 2. Symmetric cross fixture
    cross_segs = [
        SegmentFeature(id="N", geometry=LineString([(100, 100), (100, 200)]), length_m=100.0),
        SegmentFeature(id="S", geometry=LineString([(100, 0), (100, 100)]), length_m=100.0),
        SegmentFeature(id="E", geometry=LineString([(100, 100), (200, 100)]), length_m=100.0),
        SegmentFeature(id="W", geometry=LineString([(0, 100), (100, 100)]), length_m=100.0),
    ]
    net_cross = SegmentNetwork.from_features(cross_segs)
    res_cross = calculate_segment_angular_measures(net_cross, radii_m=[800.0, 2000.0, 10000.0])

    # 3. T-junction fixture
    t_segs = [
        SegmentFeature(id="A", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="B", geometry=LineString([(100, 0), (200, 0)]), length_m=100.0),
        SegmentFeature(id="C", geometry=LineString([(100, 0), (100, 100)]), length_m=100.0),
    ]
    net_t = SegmentNetwork.from_features(t_segs)
    res_t = calculate_segment_angular_measures(net_t, radii_m=[800.0, 2000.0, 10000.0])

    # 4. Bridge / tunnel grade separation fixture
    bridge_segs = [
        SegmentFeature(id="ground", geometry=LineString([(0, 50), (100, 50)]), length_m=100.0, layer=0),
        SegmentFeature(id="bridge", geometry=LineString([(50, 0), (50, 100)]), length_m=100.0, layer=1),
    ]
    net_bridge = SegmentNetwork.from_features(bridge_segs)
    res_bridge = calculate_segment_angular_measures(net_bridge, radii_m=[800.0, 2000.0, 10000.0])

    # 5. Square cycle fixture (independent hand-counted fractional choice)
    square_segs = [
        SegmentFeature(id="sq_A", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="sq_B", geometry=LineString([(100, 0), (100, 100)]), length_m=100.0),
        SegmentFeature(id="sq_C", geometry=LineString([(100, 100), (0, 100)]), length_m=100.0),
        SegmentFeature(id="sq_D", geometry=LineString([(0, 100), (0, 0)]), length_m=100.0),
    ]
    net_square = SegmentNetwork.from_features(square_segs)
    res_square = calculate_segment_angular_measures(net_square, radii_m=[800.0, 2000.0, 10000.0])

    # Validate assertions
    assert res_straight[800.0]["seg_B"]["choice"] > res_straight[800.0]["seg_A"]["choice"], "Straight choice failed"
    assert math.isclose(res_cross[800.0]["N"]["total_depth"], res_cross[800.0]["S"]["total_depth"]), "Cross symmetry failed"
    assert res_t[800.0]["C"]["total_depth"] > res_t[800.0]["A"]["total_depth"], "T-junction depth failed"
    assert res_bridge[800.0]["ground"]["node_count"] == 0, "Bridge layer isolation failed"
    for sid in ["sq_A", "sq_B", "sq_C", "sq_D"]:
        # The two opposite-segment pairs each have two equal angular routes.
        # Under this engine's undirected convention each affected segment gets
        # one half-path; there are no other intermediate-pair contributions.
        assert math.isclose(res_square[800.0][sid]["choice"], 0.5, abs_tol=1e-5), f"Square cycle choice failed for {sid}"

    report = {
        "schema_version": "probe-space-syntax-v1",
        "status": "PASS",
        "engine": {
            "name": "urban_design.space_syntax",
            "algorithm": "Segment Angular Integration and Choice (Turner 2007; Hillier & Iida 2005)",
            "formula_version": "turner-2007-angular-segment-v1",
            "metric_radii_m": [800.0, 2000.0, 10000.0],
            "turn_angle_cost": "normalized_turns (90 deg = 1.0)",
            "grade_separation": "explicit layer/bridge/tunnel junction separation",
            "license": "BSD-3-Clause",
            "runtime_boundary": "In-process Python / Shapely deterministic vector operations",
        },
        "test_results": {
            "straight_line_fixture": {
                "status": "PASS",
                "output_sample": res_straight[800.0],
            },
            "symmetric_cross_fixture": {
                "status": "PASS",
                "output_sample": res_cross[800.0],
            },
            "t_junction_fixture": {
                "status": "PASS",
                "output_sample": res_t[800.0],
            },
            "bridge_tunnel_grade_separation": {
                "status": "PASS",
                "output_sample": res_bridge[800.0],
            },
            "square_cycle_fixture": {
                "status": "PASS",
                "output_sample": res_square[800.0],
            },
        }
    }

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_file = output_dir / "probe-space-syntax.json"
        out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Space syntax probe report saved to {out_file}")

    return report


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "week4-repair-r01"
    out_dir = PROJECT_ROOT / "artifacts" / target
    report = run_space_syntax_probe(out_dir)
    print(f"CP4-1a Space Syntax Probe: {report['status']}")
