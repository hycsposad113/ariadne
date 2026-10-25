"""Hand-calculated small network test fixtures for PST 3.3.1.

Every expected value in this module is derived from first principles using
the Space Syntax angular segment analysis definitions:
1. Turn cost: angular cost = turn_angle_in_degrees / 90.0
   (Turner 2007; 90 degrees turn = 1.0 full angular turn).
2. Segment midpoint network walking radius: distance is cumulative along the network
   between segment midpoints.
3. Total Depth (TD): sum of shortest angular costs to all reachable segments within radius.
4. Choice (Betweenness): number of shortest angular paths between all origin-destination
   pairs (s, t) that pass through the segment. Directed pairs count as 2.0 (s->t and t->s),
   undirected pairs count as 1.0.
5. Grade-separated crossings (unlinks): intersecting lines with an unlink point do not
   form a topological junction in CreateSegmentMap and remain disjoint.
"""

from __future__ import annotations

import math
from pathlib import Path
import pytest

from urban_design.syntax_engines.pst_adapter import PSTAdapter, PSTLine, PSTRequest

PST_RUNTIME = Path.home() / ".local/share/urban-design-runtimes/pstalgo-3.3.1"
PST_MANIFEST = Path(__file__).resolve().parents[1] / "config/runtimes/pstalgo-3.3.1.json"


def get_adapter() -> PSTAdapter:
    return PSTAdapter(manifest_path=PST_MANIFEST, runtime_root=PST_RUNTIME, timeout_seconds=30)


@pytest.mark.skipif(
    not (PST_RUNTIME / "bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_pst_fixture_straight_corridor():
    """1. Straight Collinear Corridor (3 segments).

    Geometry:
      Segment A: [0, 0] -> [100, 0] (length 100m, midpoint (50, 0))
      Segment B: [100, 0] -> [200, 0] (length 100m, midpoint (150, 0))
      Segment C: [200, 0] -> [300, 0] (length 100m, midpoint (250, 0))

    Manual Derivation (Radius R = 500m, walking):
      - Turn angles: A-B = 0 deg, B-C = 0 deg.
      - Network distances:
        dist(A, B) = 100m <= 500m
        dist(B, C) = 100m <= 500m
        dist(A, C) = 200m <= 500m
        All 3 segments are mutually reachable.
      - Node count (including origin):
        A: 3, B: 3, C: 3.
      - Angular Depth:
        All turn angles are 0 degrees -> angular cost = 0.0.
        Total Depth for A = cost(A, B) + cost(A, C) = 0.0 + 0.0 = 0.0.
        Total Depth for B = cost(B, A) + cost(B, C) = 0.0 + 0.0 = 0.0.
        Total Depth for C = cost(C, A) + cost(C, B) = 0.0 + 0.0 = 0.0.
      - Choice (Angular Betweenness):
        Pairs of segments: (A, B), (A, C), (B, C).
        Only path between A and C passes through intermediate segment B.
        In directed accounting (PST native):
          Directed pairs (A, C) and (C, A) pass through B -> choice(B) = 2.0.
          Neither A nor C lies between any other pair -> choice(A) = 0.0, choice(C) = 0.0.
    """
    lines = (
        PSTLine("A", ((0.0, 0.0), (100.0, 0.0))),
        PSTLine("B", ((100.0, 0.0), (200.0, 0.0))),
        PSTLine("C", ((200.0, 0.0), (300.0, 0.0))),
    )
    adapter = get_adapter()
    res = adapter.compute(PSTRequest(lines=lines, radius_m=500.0))

    # Match segments by source line ID
    seg_a = next(s for s in res.segments if s.source_line_id == "A")
    seg_b = next(s for s in res.segments if s.source_line_id == "B")
    seg_c = next(s for s in res.segments if s.source_line_id == "C")
    idx_a = res.segments.index(seg_a)
    idx_b = res.segments.index(seg_b)
    idx_c = res.segments.index(seg_c)

    # Node count: 3 reachable segments for each
    assert res.node_counts[idx_a] == 3
    assert res.node_counts[idx_b] == 3
    assert res.node_counts[idx_c] == 3

    # Total depth: all 0.0 since all lines are straight
    assert res.total_depths[idx_a] == pytest.approx(0.0)
    assert res.total_depths[idx_b] == pytest.approx(0.0)
    assert res.total_depths[idx_c] == pytest.approx(0.0)

    # Choice: only middle segment B has betweenness (2 directed paths: A->C and C->A)
    assert res.choices[idx_a] == pytest.approx(0.0)
    assert res.choices[idx_b] == pytest.approx(2.0)
    assert res.choices[idx_c] == pytest.approx(0.0)


@pytest.mark.skipif(
    not (PST_RUNTIME / "bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_pst_fixture_t_junction():
    """2. T-Junction (Main street A-B, Side branch C).

    Geometry:
      Segment A: [0, 0] -> [100, 0]
      Segment B: [100, 0] -> [200, 0]
      Segment C: [100, 0] -> [100, 100]

    Manual Derivation (Radius R = 500m, walking):
      - Turn angles:
        A to B: collinear -> 0 deg -> cost = 0.0 turns.
        A to C: 90 deg right angle -> cost = 90 / 90 = 1.0 turn.
        B to C: 90 deg right angle -> cost = 90 / 90 = 1.0 turn.
      - Total Depth:
        From A: to B is 0.0, to C is 1.0 -> TD(A) = 0.0 + 1.0 = 1.0.
        From B: to A is 0.0, to C is 1.0 -> TD(B) = 0.0 + 1.0 = 1.0.
        From C: to A is 1.0, to B is 1.0 -> TD(C) = 1.0 + 1.0 = 2.0.
      - Choice:
        Pairs: (A, B) connects directly (0 turns).
               (A, C) connects directly at junction (1 turn).
               (B, C) connects directly at junction (1 turn).
        No segment lies strictly in between any other pair of segments.
        Therefore, choice = 0.0 for all 3 segments.
    """
    lines = (
        PSTLine("A", ((0.0, 0.0), (100.0, 0.0))),
        PSTLine("B", ((100.0, 0.0), (200.0, 0.0))),
        PSTLine("C", ((100.0, 0.0), (100.0, 100.0))),
    )
    adapter = get_adapter()
    res = adapter.compute(PSTRequest(lines=lines, radius_m=500.0))

    seg_a = next(s for s in res.segments if s.source_line_id == "A")
    seg_b = next(s for s in res.segments if s.source_line_id == "B")
    seg_c = next(s for s in res.segments if s.source_line_id == "C")
    idx_a = res.segments.index(seg_a)
    idx_b = res.segments.index(seg_b)
    idx_c = res.segments.index(seg_c)

    assert res.node_counts[idx_a] == 3
    assert res.node_counts[idx_b] == 3
    assert res.node_counts[idx_c] == 3

    assert res.total_depths[idx_a] == pytest.approx(1.0)
    assert res.total_depths[idx_b] == pytest.approx(1.0)
    assert res.total_depths[idx_c] == pytest.approx(2.0)

    assert res.choices[idx_a] == pytest.approx(0.0)
    assert res.choices[idx_b] == pytest.approx(0.0)
    assert res.choices[idx_c] == pytest.approx(0.0)


@pytest.mark.skipif(
    not (PST_RUNTIME / "bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_pst_fixture_cross_intersection():
    """3. Cross / 4-way At-Grade Intersection (4 arms meeting at origin).

    Geometry:
      H: [-100, 0] -> [100, 0]
      V: [0, -100] -> [0, 100]

    Manual Derivation (Radius R = 500m, walking):
      - CreateSegmentMap splits at (0,0) into 4 arms: H1, H2, V1, V2.
      - Symmetry:
        For any of the 4 arms:
          - 1 opposite arm with 0 turn (cost = 0.0).
          - 2 perpendicular arms with 90 deg turn (cost = 1.0 each).
          - Total Depth = 0.0 + 1.0 + 1.0 = 2.0.
      - Node count = 4 for all segments.
      - Symmetry requires all 4 arms to have identical total depths and choice = 0.0.
    """
    lines = (
        PSTLine("H", ((-100.0, 0.0), (100.0, 0.0))),
        PSTLine("V", ((0.0, -100.0), (0.0, 100.0))),
    )
    adapter = get_adapter()
    res = adapter.compute(PSTRequest(lines=lines, radius_m=500.0))

    assert len(res.segments) == 4
    for i in range(4):
        assert res.node_counts[i] == 4
        assert res.total_depths[i] == pytest.approx(2.0)
        assert res.choices[i] == pytest.approx(0.0)


@pytest.mark.skipif(
    not (PST_RUNTIME / "bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_pst_fixture_turn_angles():
    """4. Turn Angles: 30, 45, 90, 135 degrees.

    Manual Derivation:
      Formula: angular cost = theta_degrees / 90.0
      - 30 degrees: cost = 30 / 90 = 1/3 ~ 0.333333 turns
      - 45 degrees: cost = 45 / 90 = 1/2 = 0.5 turns
      - 90 degrees: cost = 90 / 90 = 1.0 turns
      - 135 degrees: cost = 135 / 90 = 1.5 turns
      Since each network has only 2 connected segments, TD(A) = TD(B) = angular_cost.
    """
    adapter = get_adapter()
    expected_costs = {
        30: 30.0 / 90.0,
        45: 45.0 / 90.0,
        90: 90.0 / 90.0,
        135: 135.0 / 90.0,
    }

    for deg, expected_cost in expected_costs.items():
        rad = math.radians(deg)
        lines = (
            PSTLine("base", ((0.0, 0.0), (100.0, 0.0))),
            PSTLine("branch", ((100.0, 0.0), (100.0 + 100.0 * math.cos(rad), 100.0 * math.sin(rad)))),
        )
        res = adapter.compute(PSTRequest(lines=lines, radius_m=500.0))
        assert len(res.segments) == 2
        assert res.node_counts == (2, 2)
        assert res.total_depths[0] == pytest.approx(expected_cost, rel=1e-4)
        assert res.total_depths[1] == pytest.approx(expected_cost, rel=1e-4)


@pytest.mark.skipif(
    not (PST_RUNTIME / "bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_pst_fixture_isolated_components():
    """5. Disconnected / Isolated Components.

    Geometry:
      Component 1: Segment X [0, 0] -> [100, 0]
      Component 2: Segment Y [1000, 1000] -> [1100, 1000]

    Manual Derivation:
      The two segments have no topological connection.
      - Node count for X: only X itself is reachable -> node_count = 1.
      - Node count for Y: only Y itself is reachable -> node_count = 1.
      - Total depth = 0.0 for both.
      - Choice = 0.0 for both.
    """
    lines = (
        PSTLine("X", ((0.0, 0.0), (100.0, 0.0))),
        PSTLine("Y", ((1000.0, 1000.0), (1100.0, 1000.0))),
    )
    adapter = get_adapter()
    res = adapter.compute(PSTRequest(lines=lines, radius_m=500.0))

    assert res.node_counts == (1, 1)
    assert res.total_depths == (0.0, 0.0)
    assert res.choices == (0.0, 0.0)


@pytest.mark.skipif(
    not (PST_RUNTIME / "bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_pst_fixture_grade_separated_crossing():
    """6. Grade-Separated Crossing (Overpass / Tunnel with Unlinks).

    Geometry:
      Line H: [-50, 0] -> [50, 0] (ground level)
      Line V: [0, -50] -> [0, 50] (bridge / flyover)
      Crossing at (0, 0).
      Unlinks: ((0.0, 0.0),)

    Manual Derivation:
      With explicit unlink at (0, 0), CreateSegmentMap does NOT split the lines
      into 4 intersecting segments. Instead, it treats the crossing as grade-separated.
      - H remains 1 continuous segment of 100m.
      - V remains 1 continuous segment of 100m.
      - Since they are unlinked, there is no topological transition between H and V.
      - For H: node_count = 1 (only itself), TD = 0.0, choice = 0.0.
      - For V: node_count = 1 (only itself), TD = 0.0, choice = 0.0.
    """
    lines = (
        PSTLine("H", ((-50.0, 0.0), (50.0, 0.0))),
        PSTLine("V", ((0.0, -50.0), (0.0, 50.0))),
    )
    adapter = get_adapter()
    res = adapter.compute(PSTRequest(lines=lines, radius_m=200.0, unlinks=((0.0, 0.0),)))

    assert len(res.segments) == 2
    assert res.node_counts == (1, 1)
    assert res.total_depths == (0.0, 0.0)
    assert res.choices == (0.0, 0.0)
