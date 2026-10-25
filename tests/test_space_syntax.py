"""Known-answer reference tests for Space Syntax Segment Angular Analysis.

These tests assert mathematical properties and known reference answers independently
of the implementation details:
1. Straight collinear line: zero angular depth between segments, center segment has highest choice.
2. T-junction: straight arm has zero turn, orthogonal arm has 90-degree turn.
3. Symmetric cross: all four arms have identical choice and integration by rotational symmetry.
4. Turn angle monotonicity: 30-deg bend has strictly lower angular depth than 90-deg bend.
5. Isolated component: disconnected elements do not connect across infinite metric distance.
6. Bridge / tunnel grade separation: 2D crossing with differing layer attributes does not form a topological junction.
"""

import math
import pytest
from shapely.geometry import LineString


def test_space_syntax_engine_reference_straight_line():
    """3 collinear segments: A-(0,0)->(100,0), B-(100,0)->(200,0), C-(200,0)->(300,0).

    Theoretical expectations:
    - Angular turn between A and B is 0.0 rad.
    - Angular turn between B and C is 0.0 rad.
    - Total angular depth from B to A is 0.0, from B to C is 0.0.
    - Segment B lies on the shortest angular path between A and C.
    - Choice of B > Choice of A and Choice of C.
    """
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    segments = [
        SegmentFeature(id="seg_A", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="seg_B", geometry=LineString([(100, 0), (200, 0)]), length_m=100.0),
        SegmentFeature(id="seg_C", geometry=LineString([(200, 0), (300, 0)]), length_m=100.0),
    ]
    net = SegmentNetwork.from_features(segments)
    results = calculate_segment_angular_measures(net, radii_m=[500.0])

    r_A = results[500.0]["seg_A"]
    r_B = results[500.0]["seg_B"]
    r_C = results[500.0]["seg_C"]

    # All angular depths are 0.0
    assert r_A["total_depth"] == 0.0
    assert r_B["total_depth"] == 0.0
    assert r_C["total_depth"] == 0.0

    # Segment B is intermediate between A and C; A and C are endpoints
    assert r_B["choice"] > r_A["choice"]
    assert r_B["choice"] > r_C["choice"]
    assert r_A["choice"] == r_C["choice"]


def test_space_syntax_engine_reference_symmetric_cross():
    """Symmetric 4-arm cross meeting at (100, 100):
    N: (100, 100) -> (100, 200)
    S: (100, 0)   -> (100, 100)
    E: (100, 100) -> (200, 100)
    W: (0, 100)   -> (100, 100)

    Theoretical expectations:
    - By 4-fold rotational symmetry, all four segments must have identical
      node counts, mean depth, angular integration, and angular choice.
    - Opposite pairs (N-S, E-W) have turn angle 0 (straight).
    - Orthogonal pairs (N-E, N-W, S-E, S-W) have turn angle pi/2 (90 deg).
    """
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    segments = [
        SegmentFeature(id="N", geometry=LineString([(100, 100), (100, 200)]), length_m=100.0),
        SegmentFeature(id="S", geometry=LineString([(100, 0), (100, 100)]), length_m=100.0),
        SegmentFeature(id="E", geometry=LineString([(100, 100), (200, 100)]), length_m=100.0),
        SegmentFeature(id="W", geometry=LineString([(0, 100), (100, 100)]), length_m=100.0),
    ]
    net = SegmentNetwork.from_features(segments)
    results = calculate_segment_angular_measures(net, radii_m=[500.0])

    r_N = results[500.0]["N"]
    r_S = results[500.0]["S"]
    r_E = results[500.0]["E"]
    r_W = results[500.0]["W"]

    # All four arms must match exactly by symmetry
    assert math.isclose(r_N["total_depth"], r_S["total_depth"], rel_tol=1e-6)
    assert math.isclose(r_N["total_depth"], r_E["total_depth"], rel_tol=1e-6)
    assert math.isclose(r_N["total_depth"], r_W["total_depth"], rel_tol=1e-6)

    assert math.isclose(r_N["choice"], r_S["choice"], rel_tol=1e-6)
    assert math.isclose(r_N["choice"], r_E["choice"], rel_tol=1e-6)
    assert math.isclose(r_N["choice"], r_W["choice"], rel_tol=1e-6)

    assert r_N["node_count"] == 3


def test_space_syntax_engine_reference_t_junction():
    """T-junction: Main street A-B straight, C branch turning at 90 degrees.
    A: (0, 0) -> (100, 0)
    B: (100, 0) -> (200, 0)
    C: (100, 0) -> (100, 100)

    Theoretical expectations:
    - Path A-B is straight (angle turn 0.0).
    - Path A-C requires a 90-degree turn (turn angle pi/2).
    - Path B-C requires a 90-degree turn (turn angle pi/2).
    - Depth of A to B is 0.0; Depth of A to C is 1.0 (in normalized turn units) or pi/2.
    - Depth of B to A is 0.0; Depth of B to C is 1.0 or pi/2.
    - Depth of C to A is 1.0 or pi/2; Depth of C to B is 1.0 or pi/2.
    - Therefore, TotalDepth(C) = 2.0 > TotalDepth(A) = 1.0.
    - Integration of A and B is strictly higher than Integration of C.
    """
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    segments = [
        SegmentFeature(id="A", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="B", geometry=LineString([(100, 0), (200, 0)]), length_m=100.0),
        SegmentFeature(id="C", geometry=LineString([(100, 0), (100, 100)]), length_m=100.0),
    ]
    net = SegmentNetwork.from_features(segments)
    results = calculate_segment_angular_measures(net, radii_m=[500.0])

    r_A = results[500.0]["A"]
    r_B = results[500.0]["B"]
    r_C = results[500.0]["C"]

    # C must have strictly higher total angular depth than A or B
    assert r_C["total_depth"] > r_A["total_depth"]
    assert math.isclose(r_A["total_depth"], r_B["total_depth"], rel_tol=1e-6)
    # A and B have higher integration (lower depth) than the cul-de-sac-like leg C
    assert r_A["integration"] > r_C["integration"]


def test_space_syntax_engine_angle_monotonicity():
    """Monotonicity: A 30-degree bend must produce strictly lower angular depth
    than a 90-degree bend.
    """
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    # Net 1: 30 degree bend (rad = pi/6)
    # Segment 1: (0,0) -> (100,0)
    # Segment 2: (100,0) -> (100 + 100*cos(30 deg), 100*sin(30 deg))
    rad30 = math.radians(30)
    net30 = SegmentNetwork.from_features([
        SegmentFeature(id="s1", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="s2", geometry=LineString([(100, 0), (100 + 100 * math.cos(rad30), 100 * math.sin(rad30))]), length_m=100.0),
    ])

    # Net 2: 90 degree bend (rad = pi/2)
    net90 = SegmentNetwork.from_features([
        SegmentFeature(id="s1", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="s2", geometry=LineString([(100, 0), (100, 100)]), length_m=100.0),
    ])

    res30 = calculate_segment_angular_measures(net30, radii_m=[500.0])[500.0]
    res90 = calculate_segment_angular_measures(net90, radii_m=[500.0])[500.0]

    assert res30["s1"]["total_depth"] < res90["s1"]["total_depth"]


def test_space_syntax_isolated_component():
    """Disconnected segment must have node_count=0 and not connect to main network."""
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    segments = [
        SegmentFeature(id="main_1", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="main_2", geometry=LineString([(100, 0), (200, 0)]), length_m=100.0),
        SegmentFeature(id="iso_1", geometry=LineString([(1000, 1000), (1100, 1000)]), length_m=100.0),
    ]
    net = SegmentNetwork.from_features(segments)
    results = calculate_segment_angular_measures(net, radii_m=[500.0])[500.0]

    assert results["iso_1"]["node_count"] == 0
    assert results["iso_1"]["choice"] == 0.0
    assert results["iso_1"]["integration"] == 0.0


def test_space_syntax_bridge_tunnel_layer_rule():
    """Bridge/tunnel: Two segments cross at (50, 50) in 2D coordinates,
    but segment 1 is on layer=0 (ground) and segment 2 is on layer=1 (bridge).
    They must NOT connect to form an intersection.
    """
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    segments = [
        SegmentFeature(id="ground", geometry=LineString([(0, 50), (100, 50)]), length_m=100.0, layer=0),
        SegmentFeature(id="bridge", geometry=LineString([(50, 0), (50, 100)]), length_m=100.0, layer=1),
    ]
    net = SegmentNetwork.from_features(segments)
    results = calculate_segment_angular_measures(net, radii_m=[500.0])[500.0]

    # Since they are on different layers, they do not connect! Node count for each must be 0.
    assert results["ground"]["node_count"] == 0
    assert results["bridge"]["node_count"] == 0


def test_space_syntax_independent_known_answer_linear_corridor():
    """Independent known-answer test for 3 collinear segments A-B-C (length 100m each).

    Independent hand calculations:
    - Segments: A (0..100), B (100..200), C (200..300).
    - Turn angles: A-B = 0 rad, B-C = 0 rad.
    - Angular costs (in turns): 0.0.
    - At R=500m:
      Node counts: 2 for all.
      Total depth: 0.0 for all.
      Mean depth: 0.0 for all.
      Choice(B) = 1.0 (B is intermediate on undirected pair (A, C)).
      Choice(A) = 0.0, Choice(C) = 0.0.
      NAIN(B) = 2.0^1.2 / (0.0 + 2.0) = 2.2973967 / 2 = 1.148698.
      NACH(B) = ln(1.0 + 1.0) / ln(0.0 + 3.0) = ln(2) / ln(3) = 0.630930.
      NACH(A) = ln(0.0 + 1.0) / ln(0.0 + 3.0) = 0.0.
    """
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    segments = [
        SegmentFeature(id="A", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="B", geometry=LineString([(100, 0), (200, 0)]), length_m=100.0),
        SegmentFeature(id="C", geometry=LineString([(200, 0), (300, 0)]), length_m=100.0),
    ]
    net = SegmentNetwork.from_features(segments)
    results = calculate_segment_angular_measures(net, radii_m=[500.0])[500.0]

    # Exact independent values
    assert results["A"]["total_depth"] == 0.0
    assert results["B"]["total_depth"] == 0.0
    assert results["C"]["total_depth"] == 0.0

    assert math.isclose(results["B"]["choice"], 1.0, rel_tol=1e-5)
    assert math.isclose(results["A"]["choice"], 0.0, abs_tol=1e-5)
    assert math.isclose(results["C"]["choice"], 0.0, abs_tol=1e-5)

    expected_nain_b = (2.0 ** 1.2) / 2.0  # 1.148698
    expected_nach_b = math.log(2.0) / math.log(3.0)  # 0.630930
    assert math.isclose(results["B"]["nain"], expected_nain_b, rel_tol=1e-4)
    assert math.isclose(results["B"]["nach"], expected_nach_b, rel_tol=1e-4)
    assert math.isclose(results["A"]["nach"], 0.0, abs_tol=1e-5)


def test_space_syntax_independent_known_answer_square_cycle():
    """Independent known-answer test for a 4-segment square cycle (side length 100m).

    S1: (0,0)->(100,0)
    S2: (100,0)->(100,100)
    S3: (100,100)->(0,100)
    S4: (0,100)->(0,0)

    Independent hand calculations:
    - 4 corners each turn by 90 degrees = 1.0 turn.
    - Each segment connects to 2 adjacent segments with turn cost 1.0,
      and opposite segment with turn cost 2.0 (via 2 equal shortest paths).
    - Total depth = 1.0 + 1.0 + 2.0 = 4.0 turns.
    - Mean depth = 4.0 / 3 = 1.333333.
    - Integration = 1 / (4/3) = 0.75.
    - Fractional undirected pair Choice for each segment = 0.5: one of the two
      equally short routes for the opposite pair passes through that segment.
    - NAIN = 3.0^1.2 / (4.0 + 2.0) = 3.737193 / 6 = 0.622865.
    - NACH = ln(0.5 + 1.0) / ln(4.0 + 3.0) = ln(1.5) / ln(7).
    """
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    segments = [
        SegmentFeature(id="S1", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="S2", geometry=LineString([(100, 0), (100, 100)]), length_m=100.0),
        SegmentFeature(id="S3", geometry=LineString([(100, 100), (0, 100)]), length_m=100.0),
        SegmentFeature(id="S4", geometry=LineString([(0, 100), (0, 0)]), length_m=100.0),
    ]
    net = SegmentNetwork.from_features(segments)
    results = calculate_segment_angular_measures(net, radii_m=[500.0])[500.0]

    for sid in ["S1", "S2", "S3", "S4"]:
        r = results[sid]
        assert r["node_count"] == 3
        assert math.isclose(r["total_depth"], 4.0, rel_tol=1e-5)
        assert math.isclose(r["mean_depth"], 4.0 / 3.0, rel_tol=1e-5)
        assert math.isclose(r["integration"], 0.75, rel_tol=1e-5)
        assert math.isclose(r["choice"], 0.5, rel_tol=1e-4)

        expected_nain = (3.0 ** 1.2) / 6.0
        expected_nach = math.log(1.5) / math.log(7.0)
        assert math.isclose(r["nain"], expected_nain, rel_tol=1e-4)
        assert math.isclose(r["nach"], expected_nach, rel_tol=1e-4)


def test_space_syntax_metric_radius_cutoff_behavior():
    """Verify metric radius strictly cuts off segments beyond threshold distance."""
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    # 3 collinear segments: midpoints at 50, 150, 250
    # Step from A(mid 50) to B(mid 150) = 100m.
    # Step from A(mid 50) to C(mid 250) = 200m.
    segments = [
        SegmentFeature(id="A", geometry=LineString([(0, 0), (100, 0)]), length_m=100.0),
        SegmentFeature(id="B", geometry=LineString([(100, 0), (200, 0)]), length_m=100.0),
        SegmentFeature(id="C", geometry=LineString([(200, 0), (300, 0)]), length_m=100.0),
    ]
    net = SegmentNetwork.from_features(segments)
    res = calculate_segment_angular_measures(net, radii_m=[50.0, 150.0, 250.0])

    # At R=50m: no connection (step is 100m > 50m)
    assert res[50.0]["A"]["node_count"] == 0
    assert res[50.0]["B"]["node_count"] == 0

    # At R=150m: A reaches B (100m <= 150m), but not C (200m > 150m)
    assert res[150.0]["A"]["node_count"] == 1
    assert res[150.0]["B"]["node_count"] == 2  # B reaches A and C (both are 100m away)
    assert res[150.0]["C"]["node_count"] == 1

    # At R=250m: all segments reach each other
    assert res[250.0]["A"]["node_count"] == 2
    assert res[250.0]["C"]["node_count"] == 2


def test_space_syntax_intersection_noding_requirement():
    """Segments that physically cross in 2D but lack an endpoint at the intersection
    must NOT form a junction (proves topological noding discipline).
    """
    from urban_design.space_syntax import (
        SegmentNetwork,
        SegmentFeature,
        calculate_segment_angular_measures,
    )

    # Segments crossing without shared vertex:
    # Seg 1: (0, 50) -> (100, 50)
    # Seg 2: (50, 0) -> (50, 100)
    # Neither segment has a vertex at (50, 50)
    un_noded = [
        SegmentFeature(id="h", geometry=LineString([(0, 50), (100, 50)]), length_m=100.0),
        SegmentFeature(id="v", geometry=LineString([(50, 0), (50, 100)]), length_m=100.0),
    ]
    net_unnoded = SegmentNetwork.from_features(un_noded)
    res_unnoded = calculate_segment_angular_measures(net_unnoded, radii_m=[500.0])[500.0]
    assert res_unnoded["h"]["node_count"] == 0
    assert res_unnoded["v"]["node_count"] == 0

    # Properly noded into 4 segments meeting at (50, 50):
    noded = [
        SegmentFeature(id="w", geometry=LineString([(0, 50), (50, 50)]), length_m=50.0),
        SegmentFeature(id="e", geometry=LineString([(50, 50), (100, 50)]), length_m=50.0),
        SegmentFeature(id="s", geometry=LineString([(50, 0), (50, 50)]), length_m=50.0),
        SegmentFeature(id="n", geometry=LineString([(50, 50), (50, 100)]), length_m=50.0),
    ]
    net_noded = SegmentNetwork.from_features(noded)
    res_noded = calculate_segment_angular_measures(net_noded, radii_m=[500.0])[500.0]
    assert res_noded["w"]["node_count"] == 3
    assert res_noded["e"]["node_count"] == 3


def test_space_syntax_metric_radius_keeps_shorter_higher_angle_label():
    """A low-angle long route to X must not hide a short route that reaches Y inside R."""
    from urban_design.space_syntax import (
        SegmentFeature,
        SegmentNetwork,
        calculate_segment_angular_measures,
    )

    segments = [
        SegmentFeature("S", LineString([(0, 0), (100, 0)]), 100.0),
        # This low-turn route reaches X at about 1,055 m and cannot then add Y within 1,100 m.
        SegmentFeature("A", LineString([(100, 0), (200, 0)]), 1000.0),
        SegmentFeature("X", LineString([(200, 0), (300, 0)]), 10.0),
        # A short reverse-direction route costs a 180-degree turn but reaches Y well within R.
        SegmentFeature("B", LineString([(0, 0), (200, 0)]), 10.0),
        SegmentFeature("Y", LineString([(300, 0), (400, 0)]), 100.0),
    ]
    result = calculate_segment_angular_measures(
        SegmentNetwork.from_features(segments), radii_m=[1100.0]
    )[1100.0]["S"]

    # S reaches A, B and X by both alternatives, and Y only through the shorter label at X.
    assert result["node_count"] == 4
    assert math.isclose(result["total_depth"], 4.0, abs_tol=1e-6)
    assert math.isclose(result["mean_depth"], 1.0, abs_tol=1e-6)


def test_space_syntax_shortest_angular_choice_has_hand_counted_chain_value():
    """In a five-segment chain, the center is internal to four unordered pairs."""
    from urban_design.space_syntax import (
        SegmentFeature,
        SegmentNetwork,
        calculate_segment_angular_measures,
    )

    segments = [
        SegmentFeature("D", LineString([(0, -100), (0, 0)]), 100.0),
        SegmentFeature("A", LineString([(0, 0), (100, 0)]), 100.0),
        SegmentFeature("C", LineString([(100, 0), (200, 0)]), 100.0),
        SegmentFeature("B", LineString([(200, 0), (300, 0)]), 100.0),
        SegmentFeature("E", LineString([(300, 0), (300, 100)]), 100.0),
    ]
    result = calculate_segment_angular_measures(
        SegmentNetwork.from_features(segments), radii_m=[500.0]
    )[500.0]

    # Ordered along the chain D-A-C-B-E, two nodes lie on each side of C.
    # Exactly 2*2=4 unordered source-target pairs have C as an intermediate segment.
    assert math.isclose(result["C"]["choice"], 4.0, abs_tol=1e-6)


def test_turn_angle_uses_source_node_endpoint_identity_with_small_coordinate_drift():
    """Shared OSM node identity, not rounded XY equality, determines endpoint direction."""
    from urban_design.space_syntax import SegmentFeature, SegmentNetwork

    features = [
        SegmentFeature(
            "incoming",
            LineString([(0.0, 0.0), (100.0, 0.0)]),
            100.0,
            end_node_id="shared-node",
        ),
        SegmentFeature(
            "outgoing",
            LineString([(100.005, 0.005), (200.005, 0.005)]),
            100.0,
            start_node_id="shared-node",
        ),
    ]
    network = SegmentNetwork.from_features(features)
    junction = ("osm-node", "shared-node")

    assert network.get_turn_angle("incoming", "outgoing", junction) == pytest.approx(0.0)


def test_segment_network_rejects_duplicate_ids_and_invalid_lengths():
    from urban_design.space_syntax import SegmentFeature, SegmentNetwork

    duplicate_ids = [
        SegmentFeature("same", LineString([(0, 0), (1, 0)]), 1.0),
        SegmentFeature("same", LineString([(1, 0), (2, 0)]), 1.0),
    ]
    with pytest.raises(ValueError, match="segment IDs must be unique"):
        SegmentNetwork.from_features(duplicate_ids)

    for invalid_length in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(ValueError, match="finite positive length"):
            SegmentNetwork.from_features(
                [SegmentFeature("bad", LineString([(0, 0), (1, 0)]), invalid_length)]
            )


def test_segment_angular_analysis_rejects_invalid_radius_and_angle_unit():
    from urban_design.space_syntax import (
        SegmentFeature,
        SegmentNetwork,
        calculate_segment_angular_measures,
    )

    network = SegmentNetwork.from_features(
        [SegmentFeature("single", LineString([(0, 0), (1, 0)]), 1.0)]
    )
    for invalid_radius in (-1.0, math.nan, math.inf):
        with pytest.raises(ValueError, match="finite non-negative metric radii"):
            calculate_segment_angular_measures(network, radii_m=[invalid_radius])
    with pytest.raises(ValueError, match="angle_cost_unit"):
        calculate_segment_angular_measures(network, radii_m=[1.0], angle_cost_unit="degrees")


def test_segment_angular_engine_matches_independent_exhaustive_reference():
    """Compare radius, angular depth and choice with independent simple-path enumeration.

    The fixture uses exact straight segments and a declared midpoint-to-midpoint
    metric distance (half of each adjacent segment length). This validates the
    implementation under that local computational contract; it does not approve
    a project-wide movement-radius policy or a Rotterdam analysis method.
    """
    from urban_design.space_syntax import (
        SegmentFeature,
        SegmentNetwork,
        calculate_segment_angular_measures,
    )

    features = [
        SegmentFeature("A", LineString([(0, 0), (100, 0)]), 100.0),
        SegmentFeature("B", LineString([(100, 0), (100, 100)]), 100.0),
        SegmentFeature("C", LineString([(100, 100), (0, 100)]), 100.0),
        SegmentFeature("D", LineString([(0, 100), (0, 0)]), 100.0),
    ]
    network = SegmentNetwork.from_features(features)
    for radius_m, node_count, total_depth, choice in (
        (199.999, 2, 2.0, 0.0),
        (200.0, 3, 4.0, 0.5),
    ):
        expected = _exhaustive_segment_reference(features, radius_m=radius_m)
        observed = calculate_segment_angular_measures(network, radii_m=[radius_m])[radius_m]
        for segment_id, values in expected.items():
            assert values == {
                "node_count": node_count,
                "total_depth": pytest.approx(total_depth),
                "choice": pytest.approx(choice),
            }
            assert observed[segment_id]["node_count"] == values["node_count"]
            assert observed[segment_id]["total_depth"] == pytest.approx(values["total_depth"])
            assert observed[segment_id]["choice"] == pytest.approx(values["choice"])


def _exhaustive_segment_reference(features, *, radius_m):
    """Small-graph reference using simple-path enumeration, not engine internals."""
    from collections import defaultdict

    by_id = {feature.id: feature for feature in features}
    endpoints = {}
    vectors = {}
    for feature in features:
        coordinates = list(feature.geometry.coords)
        start = (round(float(coordinates[0][0]), 4), round(float(coordinates[0][1]), 4), feature.layer)
        end = (round(float(coordinates[-1][0]), 4), round(float(coordinates[-1][1]), 4), feature.layer)
        endpoints[feature.id] = (start, end)
        vectors[feature.id] = (
            (float(coordinates[0][0]), float(coordinates[0][1])),
            (float(coordinates[-1][0]), float(coordinates[-1][1])),
        )

    adjacency = defaultdict(list)
    for first in features:
        for direction in (1, -1):
            junction = endpoints[first.id][1 if direction == 1 else 0]
            first_entry, first_exit = vectors[first.id]
            if direction == -1:
                first_entry, first_exit = first_exit, first_entry
            first_vector = (first_exit[0] - first_entry[0], first_exit[1] - first_entry[1])
            first_norm = math.hypot(*first_vector)
            for second in features:
                if second.id == first.id:
                    continue
                for next_direction in (1, -1):
                    entry_index = 0 if next_direction == 1 else 1
                    if endpoints[second.id][entry_index] != junction:
                        continue
                    second_entry, second_exit = vectors[second.id]
                    if next_direction == -1:
                        second_entry, second_exit = second_exit, second_entry
                    second_vector = (second_exit[0] - second_entry[0], second_exit[1] - second_entry[1])
                    second_norm = math.hypot(*second_vector)
                    cosine = sum(a * b for a, b in zip(first_vector, second_vector)) / (first_norm * second_norm)
                    turn_cost = math.acos(max(-1.0, min(1.0, cosine))) / (math.pi / 2.0)
                    midpoint_step = (first.length_m + second.length_m) / 2.0
                    adjacency[(first.id, direction)].append(
                        (second.id, next_direction, turn_cost, midpoint_step)
                    )

    routes_by_source = {}
    for source in by_id:
        target_routes = defaultdict(list)

        def visit(segment_id, direction, path, angle_cost, distance_m):
            for next_id, next_direction, turn_cost, step_m in adjacency[(segment_id, direction)]:
                candidate_distance = distance_m + step_m
                if next_id in path or candidate_distance > radius_m + 1e-9:
                    continue
                candidate_path = path + (next_id,)
                candidate_angle = angle_cost + turn_cost
                target_routes[next_id].append((candidate_angle, candidate_path))
                visit(next_id, next_direction, candidate_path, candidate_angle, candidate_distance)

        visit(source, 1, (source,), 0.0, 0.0)
        visit(source, -1, (source,), 0.0, 0.0)
        routes_by_source[source] = target_routes

    result = {
        segment_id: {"node_count": 0, "total_depth": 0.0, "choice": 0.0}
        for segment_id in by_id
    }
    for source, target_routes in routes_by_source.items():
        for target, routes in target_routes.items():
            best_cost = min(route[0] for route in routes)
            best_paths = sorted({path for cost, path in routes if math.isclose(cost, best_cost, abs_tol=1e-9)})
            result[source]["node_count"] += 1
            result[source]["total_depth"] += best_cost
            for path in best_paths:
                for intermediate in set(path[1:-1]):
                    result[intermediate]["choice"] += 1.0 / len(best_paths)

    for values in result.values():
        values["choice"] /= 2.0
    return result


def test_segment_turn_angle_uses_local_tangent_not_polyline_chord():
    from urban_design.space_syntax import SegmentFeature, SegmentNetwork

    features = [
        SegmentFeature(
            "curved-approach",
            LineString([(-10, 0), (-1, 0), (0, 1)]),
            LineString([(-10, 0), (-1, 0), (0, 1)]).length,
        ),
        SegmentFeature(
            "eastbound-departure",
            LineString([(0, 1), (10, 1), (20, 1)]),
            20.0,
        ),
    ]
    network = SegmentNetwork.from_features(features)
    junction = ((0.0, 1.0), 0)

    # The approach's final bearing is 45 degrees. Its full-line chord is only
    # about 5.7 degrees, so measuring the chord understates the junction turn.
    assert network.get_turn_angle("curved-approach", "eastbound-departure", junction) == pytest.approx(
        math.pi / 4.0
    )
