import json
import hashlib
import importlib
from pathlib import Path

import pytest


def adapter_api():
    return importlib.import_module("urban_design.syntax_engines.pst_adapter")


def write_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime_root = tmp_path / "runtime"
    python_dir = runtime_root / "python"
    python_dir.mkdir(parents=True)
    runtime_file = python_dir / "pstalgo-placeholder.py"
    contents = b"pinned fixture\n"
    runtime_file.write_bytes(contents)
    manifest_path = tmp_path / "runtime-manifest.json"
    manifest = {
        "schema_version": "pst-runtime-manifest-v1",
        "runtime_path": str(runtime_root),
        "files": [{
            "path": "python/pstalgo-placeholder.py",
            "size_bytes": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest(),
        }],
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return runtime_root, manifest_path


def write_json_worker(tmp_path: Path, *, mismatch: bool = False) -> Path:
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "source_id = 'wrong' if " + repr(mismatch) + " else request['lines'][0]['id']\n"
        "line = request['lines'][0]\n"
        "segment = {'id': source_id + '::pst-segment-0001', 'source_line_id': source_id, 'start': line['coordinates'][0], 'end': line['coordinates'][-1]}\n"
        "count = 1\n"
        "json.dump({'schema_version':'pst-angular-result-v1','segments':[segment],'source_line_count':len(request['lines']),'explicit_unlink_count':len(request['unlinks']),'segment_map_generated_unlink_count':0,'segment_map_settings':request['segment_map'],'node_counts':[1]*count,'total_depths':[0.0]*count,'choices':[0.0]*count,'total_depth_weights':[0.0]*count,'choice_node_counts':[1]*count,'choice_total_depths':[0.0]*count,'choice_total_depth_weights':[0.0]*count}, sys.stdout)\n",
        encoding="utf-8",
    )
    return worker


def valid_request():
    api = adapter_api()
    return api.PSTRequest(
        lines=(api.PSTLine(id="a", coordinates=((0.0, 0.0), (10.0, 0.0))),),
        radius_m=800.0,
    )


def test_runtime_verification_rejects_a_modified_pinned_file(tmp_path: Path) -> None:
    runtime_root, manifest_path = write_runtime(tmp_path)
    (runtime_root / "python" / "pstalgo-placeholder.py").write_bytes(b"tinned fixture\n")

    with pytest.raises(adapter_api().PSTRuntimeIntegrityError, match="sha256"):
        adapter_api().verify_runtime(manifest_path, runtime_root=runtime_root)


def test_runtime_verification_rejects_a_symlinked_runtime_root(tmp_path: Path) -> None:
    runtime_root, manifest_path = write_runtime(tmp_path)
    runtime_alias = tmp_path / "runtime-alias"
    runtime_alias.symlink_to(runtime_root, target_is_directory=True)

    with pytest.raises(adapter_api().PSTRuntimeIntegrityError, match="root"):
        adapter_api().verify_runtime(manifest_path, runtime_root=runtime_alias)


def test_adapter_runs_worker_in_a_child_process_and_returns_typed_result(tmp_path: Path) -> None:
    runtime_root, manifest_path = write_runtime(tmp_path)
    worker_path = write_json_worker(tmp_path)

    result = adapter_api().PSTAdapter(
        manifest_path=manifest_path,
        runtime_root=runtime_root,
        worker_script_path=worker_path,
        timeout_seconds=1,
    ).compute(valid_request())

    assert isinstance(result, adapter_api().PSTResult)
    assert result.segments[0].source_line_id == "a"
    assert result.segments[0].id == "a::pst-segment-0001"
    assert result.node_counts == (1,)
    assert result.total_depths == (0.0,)
    assert result.choices == (0.0,)
    assert result.total_depth_weights == (0.0,)
    assert result.graph_line_count == 1


def test_adapter_fails_closed_before_spawning_when_runtime_is_tampered(tmp_path: Path) -> None:
    runtime_root, manifest_path = write_runtime(tmp_path)
    marker = tmp_path / "worker-ran"
    worker_path = tmp_path / "worker.py"
    worker_path.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    (runtime_root / "python" / "pstalgo-placeholder.py").write_bytes(b"tampered\n")

    with pytest.raises(adapter_api().PSTRuntimeIntegrityError):
        adapter_api().PSTAdapter(
            manifest_path=manifest_path,
            runtime_root=runtime_root,
            worker_script_path=worker_path,
            timeout_seconds=1,
        ).compute(valid_request())

    assert not marker.exists()


def test_adapter_rejects_worker_output_that_does_not_match_request(tmp_path: Path) -> None:
    runtime_root, manifest_path = write_runtime(tmp_path)
    worker_path = write_json_worker(tmp_path, mismatch=True)

    with pytest.raises(adapter_api().PSTExecutionError, match="source line IDs"):
        adapter_api().PSTAdapter(
            manifest_path=manifest_path,
            runtime_root=runtime_root,
            worker_script_path=worker_path,
            timeout_seconds=1,
        ).compute(valid_request())


def test_adapter_rejects_worker_output_with_missing_source_line_coverage(tmp_path: Path) -> None:
    api = adapter_api()
    runtime_root, manifest_path = write_runtime(tmp_path)
    worker_path = write_json_worker(tmp_path)
    request = api.PSTRequest(
        lines=(
            api.PSTLine(id="a", coordinates=((0.0, 0.0), (10.0, 0.0))),
            api.PSTLine(id="b", coordinates=((10.0, 0.0), (20.0, 0.0))),
        ),
        radius_m=800.0,
    )

    with pytest.raises(api.PSTExecutionError, match="coverage"):
        api.PSTAdapter(
            manifest_path=manifest_path,
            runtime_root=runtime_root,
            worker_script_path=worker_path,
            timeout_seconds=1,
        ).compute(request)


def test_request_rejects_non_finite_coordinates_and_timeouts_over_two_hours() -> None:
    api = adapter_api()
    with pytest.raises(ValueError, match="finite"):
        api.PSTRequest(
            lines=(api.PSTLine(id="a", coordinates=((0.0, 0.0), (float("nan"), 1.0))),),
            radius_m=800.0,
        )

    with pytest.raises(ValueError, match="7200"):
        api.PSTAdapter(manifest_path=Path("missing.json"), timeout_seconds=7201)


def test_request_defaults_to_network_walking_radius_without_topology_edits() -> None:
    request = valid_request()

    assert request.to_payload()["radius_mode"] == "walking"
    assert request.to_payload()["segment_map"] == {
        "snap_m": 0.0,
        "min_tail_m": 0.0,
        "colinear_deviation": 1.0,
        "extrude_m": 0.0,
    }


def test_request_supports_metric_mode() -> None:
    api = adapter_api()
    req = valid_request()
    assert req.metric_mode == "both"
    assert req.to_payload()["metric_mode"] == "both"

    req_int = api.PSTRequest(
        lines=req.lines,
        radius_m=req.radius_m,
        metric_mode="integration",
    )
    assert req_int.metric_mode == "integration"
    assert req_int.to_payload()["metric_mode"] == "integration"

    req_cho = api.PSTRequest(
        lines=req.lines,
        radius_m=req.radius_m,
        metric_mode="choice",
    )
    assert req_cho.metric_mode == "choice"
    assert req_cho.to_payload()["metric_mode"] == "choice"

    with pytest.raises(ValueError, match="metric_mode"):
        api.PSTRequest(
            lines=req.lines,
            radius_m=req.radius_m,
            metric_mode="invalid",
        )


def test_adapter_surfaces_nonzero_worker_exit_as_execution_error(tmp_path: Path) -> None:
    runtime_root, manifest_path = write_runtime(tmp_path)
    worker_path = tmp_path / "worker.py"
    worker_path.write_text("import sys\nsys.stderr.write('native failure')\nsys.exit(7)\n", encoding="utf-8")

    with pytest.raises(adapter_api().PSTExecutionError, match="native failure"):
        adapter_api().PSTAdapter(
            manifest_path=manifest_path,
            runtime_root=runtime_root,
            worker_script_path=worker_path,
            timeout_seconds=1,
        ).compute(valid_request())


@pytest.mark.skipif(
    not Path.home().joinpath(".local/share/urban-design-runtimes/pstalgo-3.3.1/bin/libpstalgo.dylib").is_file(),
    reason="local PST 3.3.1 runtime is not installed",
)
def test_native_segment_map_splits_at_grade_level_crossings_and_preserves_unlinks() -> None:
    api = adapter_api()
    manifest_path = Path(__file__).resolve().parents[1] / "config/runtimes/pstalgo-3.3.1.json"
    runtime_root = Path.home() / ".local/share/urban-design-runtimes/pstalgo-3.3.1"
    adapter = api.PSTAdapter(manifest_path=manifest_path, runtime_root=runtime_root, timeout_seconds=60)
    lines = (
        api.PSTLine(id="horizontal", coordinates=((-50.0, 0.0), (50.0, 0.0))),
        api.PSTLine(id="vertical", coordinates=((0.0, -50.0), (0.0, 50.0))),
    )

    connected = adapter.compute(api.PSTRequest(lines=lines, radius_m=100.0))
    unlinked = adapter.compute(api.PSTRequest(lines=lines, radius_m=100.0, unlinks=((0.0, 0.0),)))

    assert connected.graph_line_count > unlinked.graph_line_count
    assert unlinked.node_counts == (1, 1)
