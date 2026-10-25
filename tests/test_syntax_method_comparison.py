"""Small deterministic comparisons between the project engine and PST 3.3.1."""

import hashlib
import json
import math
import subprocess
from pathlib import Path

import pytest
from shapely.geometry import LineString

from urban_design.space_syntax import SegmentFeature, SegmentNetwork, calculate_segment_angular_measures
from urban_design.syntax_engines.pst_adapter import PSTAdapter, PSTLine, PSTRequest


PST_RUNTIME = Path.home() / ".local/share/urban-design-runtimes/pstalgo-3.3.1"
PST_MANIFEST = Path(__file__).resolve().parents[1] / "config/runtimes/pstalgo-3.3.1.json"
METHOD_MANIFEST = Path(__file__).resolve().parents[1] / "config/runtimes/syntax-method-comparison-v1.json"


def fixture_network(name: str):
    if name == "straight":
        return [
            ("A", [(0.0, 0.0), (100.0, 0.0)], 0),
            ("B", [(100.0, 0.0), (200.0, 0.0)], 0),
            ("C", [(200.0, 0.0), (300.0, 0.0)], 0),
        ], ()
    if name == "t_junction":
        return [
            ("A", [(0.0, 0.0), (100.0, 0.0)], 0),
            ("B", [(100.0, 0.0), (200.0, 0.0)], 0),
            ("C", [(100.0, 0.0), (100.0, 100.0)], 0),
        ], ()
    if name == "cross":
        return [
            ("N", [(100.0, 100.0), (100.0, 200.0)], 0),
            ("S", [(100.0, 0.0), (100.0, 100.0)], 0),
            ("E", [(100.0, 100.0), (200.0, 100.0)], 0),
            ("W", [(0.0, 100.0), (100.0, 100.0)], 0),
        ], ()
    if name == "turn_30_degrees":
        return [
            ("A", [(0.0, 0.0), (100.0, 0.0)], 0),
            ("B", [(100.0, 0.0), (186.6025403784, 50.0)], 0),
        ], ()
    if name == "isolated_component":
        return [
            ("A", [(0.0, 0.0), (100.0, 0.0)], 0),
            ("B", [(100.0, 0.0), (200.0, 0.0)], 0),
            ("isolated", [(1000.0, 1000.0), (1100.0, 1000.0)], 0),
        ], ()
    if name == "grade_separated_crossing":
        return [
            ("ground", [(0.0, 50.0), (100.0, 50.0)], 0),
            ("bridge", [(50.0, 0.0), (50.0, 100.0)], 1),
        ], ((50.0, 50.0),)
    if name == "closed_square_radius":
        return [
            ("A", [(0.0, 0.0), (200.0, 0.0)], 0),
            ("B", [(200.0, 0.0), (200.0, 200.0)], 0),
            ("C", [(200.0, 200.0), (0.0, 200.0)], 0),
            ("D", [(0.0, 200.0), (0.0, 0.0)], 0),
        ], ()
    if name == "equal_angular_routes":
        return [
            ("origin", [(-100.0, 0.0), (0.0, 0.0)], 0),
            ("upper_a", [(0.0, 0.0), (50.0, 50.0)], 0),
            ("upper_b", [(50.0, 50.0), (100.0, 0.0)], 0),
            ("lower_a", [(0.0, 0.0), (50.0, -50.0)], 0),
            ("lower_b", [(50.0, -50.0), (100.0, 0.0)], 0),
            ("destination", [(100.0, 0.0), (200.0, 0.0)], 0),
        ], ()
    raise AssertionError(f"unknown fixture: {name}")


def relative_error(first: float, second: float) -> float:
    if first == second:
        return 0.0
    scale = max(abs(first), abs(second))
    if scale == 0:
        return 0.0
    return abs(first - second) / scale


def normalized_metrics(node_count: int, total_depth: float, choice: float) -> tuple[float, float]:
    nain = node_count**1.2 / (total_depth + 2.0) if node_count else 0.0
    nach = math.log(choice + 1.0) / math.log(total_depth + 3.0)
    return nain, nach


@pytest.mark.skipif(
    not (PST_RUNTIME / "bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_method_comparison_v1_reports_project_precision_blocker() -> None:
    adapter = PSTAdapter(manifest_path=PST_MANIFEST, runtime_root=PST_RUNTIME, timeout_seconds=60)
    total_depth_errors: list[tuple[str, str, float]] = []
    choice_errors: list[float] = []
    nain_errors: list[float] = []
    nach_errors: list[float] = []
    for name in (
        "straight",
        "t_junction",
        "cross",
        "turn_30_degrees",
        "isolated_component",
        "grade_separated_crossing",
        "equal_angular_routes",
    ):
        rows, unlinks = fixture_network(name)
        features = [
            SegmentFeature(
                id=line_id,
                geometry=LineString(coordinates),
                length_m=LineString(coordinates).length,
                layer=layer,
            )
            for line_id, coordinates, layer in rows
        ]
        project_metrics = calculate_segment_angular_measures(
            SegmentNetwork.from_features(features), radii_m=[500.0], angle_cost_unit="turns"
        )[500.0]
        pst_result = adapter.compute(
            PSTRequest(
                lines=tuple(PSTLine(id=line_id, coordinates=tuple(coordinates)) for line_id, coordinates, _ in rows),
                radius_m=500.0,
                unlinks=unlinks,
                radius_mode="walking",
            )
        )
        pst_by_source = {segment.source_line_id: index for index, segment in enumerate(pst_result.segments)}
        assert len(pst_by_source) == len(pst_result.segments), f"{name}: unexpected line splitting"
        assert set(pst_by_source) == set(project_metrics), f"{name}: source line coverage differs"

        for line_id, expected in project_metrics.items():
            pst_index = pst_by_source[line_id]
            # PST counts the origin segment and directed OD paths; the project engine
            # excludes the origin and accumulates each undirected pair once.
            comparable_node_count = pst_result.node_counts[pst_index] - 1
            comparable_choice = pst_result.choices[pst_index] / 2.0
            pst_nain, pst_nach = normalized_metrics(
                comparable_node_count, pst_result.total_depths[pst_index], comparable_choice
            )
            project_nain, project_nach = normalized_metrics(
                expected["node_count"], expected["total_depth"], expected["choice"]
            )
            assert comparable_node_count == expected["node_count"], f"{name}/{line_id}: NC differs"
            total_depth_error = relative_error(pst_result.total_depths[pst_index], expected["total_depth"])
            if total_depth_error > 1e-6:
                total_depth_errors.append((name, line_id, total_depth_error))
            choice_errors.append(relative_error(comparable_choice, expected["choice"]))
            nain_errors.append(relative_error(pst_nain, project_nain))
            nach_errors.append(relative_error(pst_nach, project_nach))

    # Keep the comparison threshold fixed. The only fixture blocker is the
    # project's six-decimal TD output, which prevents comparing unrounded values.
    assert {(name, line_id) for name, line_id, _ in total_depth_errors} == {
        ("turn_30_degrees", "A"),
        ("turn_30_degrees", "B"),
    }
    assert max(error for _, _, error in total_depth_errors) == pytest.approx(1.029802291725951e-6)
    assert max(choice_errors) <= 1e-6
    assert max(nain_errors) <= 1e-6
    assert max(nach_errors) <= 1e-6


@pytest.mark.skipif(
    not (PST_RUNTIME / "bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_metric_radius_uses_network_distance_not_euclidean_distance() -> None:
    rows, unlinks = fixture_network("closed_square_radius")
    features = [
        SegmentFeature(
            id=line_id,
            geometry=LineString(coordinates),
            length_m=LineString(coordinates).length,
            layer=layer,
        )
        for line_id, coordinates, layer in rows
    ]
    project = calculate_segment_angular_measures(
        SegmentNetwork.from_features(features), radii_m=[300.0], angle_cost_unit="turns"
    )[300.0]
    lines = tuple(PSTLine(id=line_id, coordinates=tuple(coordinates)) for line_id, coordinates, _ in rows)
    adapter = PSTAdapter(manifest_path=PST_MANIFEST, runtime_root=PST_RUNTIME, timeout_seconds=60)
    walking = adapter.compute(PSTRequest(lines=lines, radius_m=300.0, unlinks=unlinks, radius_mode="walking"))
    straight = adapter.compute(PSTRequest(lines=lines, radius_m=300.0, unlinks=unlinks, radius_mode="straight"))
    walking_by_source = {segment.source_line_id: index for index, segment in enumerate(walking.segments)}
    straight_by_source = {segment.source_line_id: index for index, segment in enumerate(straight.segments)}

    for line_id, expected in project.items():
        assert walking.node_counts[walking_by_source[line_id]] - 1 == expected["node_count"]
    assert straight.node_counts[straight_by_source["A"]] - 1 == 3


def test_method_manifest_is_unapproved_and_pins_implementation_hashes() -> None:
    manifest = json.loads(METHOD_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["status"] == "BLOCKED_PROJECT_PRECISION_M4H_PENDING"
    assert manifest["approved_for_operational_use"] is False
    assert manifest["fixture_comparison"]["status"] == "BLOCKED_PROJECT_PRECISION"
    assert manifest["fixture_comparison"]["primary_fixture_count"] == 7
    assert manifest["fixture_comparison"]["maximum_relative_errors"]["total_depth"] == pytest.approx(
        1.029802291725951e-6
    )

    comparison_revision = manifest["comparison_implementation"]["git_revision"]
    historical_files = (
        ("project", "source_path", "source_sha256"),
        ("pst", "adapter_source_path", "adapter_source_sha256"),
        ("pst", "worker_source_path", "worker_source_sha256"),
        ("pst", "runtime_manifest_path", "runtime_manifest_sha256"),
    )
    historical_paths = set()
    project_root = Path(__file__).resolve().parents[1]
    for engine_key, source_key, hash_key in historical_files:
        engine = manifest["engines"][engine_key]
        relative_path = engine[source_key]
        historical_paths.add(relative_path)
        historical_bytes = subprocess.run(
            ["git", "show", f"{comparison_revision}:{relative_path}"],
            cwd=project_root,
            check=True,
            capture_output=True,
        ).stdout
        assert hashlib.sha256(historical_bytes).hexdigest() == engine[hash_key]

    current_hashes = manifest["current_implementation_hashes"]
    assert set(current_hashes) == historical_paths
    for relative_path, expected_hash in current_hashes.items():
        current_bytes = (project_root / relative_path).read_bytes()
        assert hashlib.sha256(current_bytes).hexdigest() == expected_hash


@pytest.mark.skipif(
    not (PST_RUNTIME / "bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_default_preprocessing_preserves_short_tails_and_does_not_snap_gaps() -> None:
    adapter = PSTAdapter(manifest_path=PST_MANIFEST, runtime_root=PST_RUNTIME, timeout_seconds=60)
    short_tail_lines = (
        PSTLine(id="west", coordinates=((-100.0, 0.0), (0.0, 0.0))),
        PSTLine(id="east", coordinates=((0.0, 0.0), (100.0, 0.0))),
        PSTLine(id="short_spur", coordinates=((0.0, 0.0), (0.0, 5.0))),
    )
    short_tail_result = adapter.compute(PSTRequest(lines=short_tail_lines, radius_m=200.0))
    assert {segment.source_line_id for segment in short_tail_result.segments} == {
        "west",
        "east",
        "short_spur",
    }

    gap_rows = [
        ("first", [(0.0, 0.0), (100.0, 0.0)], 0),
        ("second", [(100.0, 0.5), (200.0, 0.5)], 0),
    ]
    features = [
        SegmentFeature(
            id=line_id,
            geometry=LineString(coordinates),
            length_m=LineString(coordinates).length,
            layer=layer,
        )
        for line_id, coordinates, layer in gap_rows
    ]
    project = calculate_segment_angular_measures(
        SegmentNetwork.from_features(features), radii_m=[300.0], angle_cost_unit="turns"
    )[300.0]
    gap_result = adapter.compute(
        PSTRequest(
            lines=tuple(PSTLine(id=line_id, coordinates=tuple(coordinates)) for line_id, coordinates, _ in gap_rows),
            radius_m=300.0,
        )
    )
    pst_by_source = {segment.source_line_id: index for index, segment in enumerate(gap_result.segments)}
    for line_id, expected in project.items():
        assert gap_result.node_counts[pst_by_source[line_id]] - 1 == expected["node_count"]
