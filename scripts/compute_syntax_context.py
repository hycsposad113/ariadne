"""Compute exploratory Space Syntax context layers around the StudyArea.

The Week 5 PST run stored values only for segments intersecting the StudyArea.
This script re-runs the pinned PST 3.3.1 adapter on the same verified retained
OSM extracts and keeps every segment within ``--max-context-m`` of the
StudyArea, so designers can read the surrounding network context.

Outputs are EXPLORATORY display artifacts written to a fresh run directory; the
authority database is never opened. Formulas match ``pst_syntax`` exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, shape

from urban_design.pst_syntax import DEFAULT_PST_MANIFEST, prepare_pst_lines
from urban_design.syntax_engines.pst_adapter import PSTAdapter, PSTRequest

SCHEMA_VERSION = "syntax-context-v1"
EXTRACTION_DIR = Path.home() / ".local/share/urban-design-data/week5-syntax-modes/extracted"
OUTPUT_ROOT = Path.home() / ".local/share/urban-design-data/syntax-context"

# (mode, extract buffer m, metric radius m) — same pairing as the Week 5 layers of record.
MODES: tuple[tuple[str, int, float], ...] = (
    ("pedestrian", 1500, 800.0),
    ("bicycle", 6000, 2000.0),
    ("motor_vehicle", 20000, 10000.0),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified(record: dict[str, Any], label: str) -> Path:
    path = Path(record["path"]).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    if sha256_file(path) != record["sha256"]:
        raise ValueError(f"{label} hash does not match its extraction manifest: {path}")
    return path


def _quantile_breaks(values: list[float]) -> list[float]:
    ordered = sorted(v for v in values if math.isfinite(v))
    if not ordered:
        return [0.0] * 6
    pick = lambda q: round(ordered[min(len(ordered) - 1, int(len(ordered) * q))], 4)  # noqa: E731
    return [round(ordered[0], 4), pick(0.2), pick(0.4), pick(0.6), pick(0.8), round(ordered[-1], 4)]


def compute_mode(mode: str, buffer_m: int, radius_m: float, max_context_m: float, adapter: PSTAdapter, extraction_dir: Path = EXTRACTION_DIR) -> dict[str, Any]:
    manifest_path = extraction_dir / f"extraction-manifest_{mode}_{buffer_m}m.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("extraction", {}).get("buffer_radius_m") != buffer_m:
        raise ValueError(f"{manifest_path} describes a different buffer radius")
    study_path = _verified(manifest["inputs"]["study_area"], "StudyArea")
    network_path = _verified(manifest["outputs"]["network"], f"{mode} network")
    unlinks_path = _verified(manifest["outputs"]["unlinks"], f"{mode} unlinks")

    study_doc = json.loads(study_path.read_text(encoding="utf-8"))
    study_area = shape(study_doc.get("geometry", study_doc) if study_doc.get("type") == "Feature" else study_doc)
    network = json.loads(network_path.read_text(encoding="utf-8"))
    if network.get("crs", {}).get("properties", {}).get("name") != "EPSG:28992":
        raise ValueError(f"{network_path} is not tagged as EPSG:28992")
    unlinks = tuple(tuple(map(float, item)) for item in json.loads(unlinks_path.read_text(encoding="utf-8")))

    lines = prepare_pst_lines(network["features"])
    started = time.perf_counter()
    result = adapter.compute(PSTRequest(lines=lines, radius_m=radius_m, radius_mode="walking", unlinks=unlinks))
    elapsed = time.perf_counter() - started

    reliable_within_m = max(0.0, buffer_m - radius_m)
    segments: list[dict[str, Any]] = []
    for index, segment in enumerate(result.segments):
        geometry = LineString([segment.start, segment.end])
        distance = float(geometry.distance(study_area))
        if distance > max_context_m:
            continue
        nc = max(0, result.node_counts[index] - 1)
        td = result.total_depths[index]
        choice = result.choices[index] / 2.0
        nain = (nc ** 1.2) / (td + 2.0) if (nc > 0 and td > 0) else 0.0
        nach = math.log(choice + 1.0) / math.log(td + 3.0) if (choice > 0 and td > 0) else 0.0
        segments.append({
            "id": f"{mode}:{segment.id}",
            "source_line_id": segment.source_line_id,
            "coordinates": [[round(segment.start[0], 2), round(segment.start[1], 2)], [round(segment.end[0], 2), round(segment.end[1], 2)]],
            "distance_to_site_m": round(distance, 1),
            "inside_site": distance == 0.0,
            "boundary_effect_risk": distance > reliable_within_m,
            "nain": round(nain, 6),
            "nach": round(nach, 6),
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_level": "EXPLORATORY",
        "formal_result_eligible": False,
        "engine": "PST 3.3.1",
        "formula_version": "pstalgo-3.3.1-walking-radius-v1",
        "network_mode": mode,
        "radius_m": radius_m,
        "extract_buffer_m": buffer_m,
        "max_context_m": max_context_m,
        "reliable_within_m": reliable_within_m,
        "limitations": (
            f"Values farther than {reliable_within_m:g} m from the StudyArea lie within one metric radius of the "
            f"{buffer_m} m extract edge and are flagged boundary_effect_risk. OSM completeness, semantics and "
            "directionality are not established. Exploratory display only; not a formal result."
        ),
        "legend_breaks": {"nain": _quantile_breaks([s["nain"] for s in segments]), "nach": _quantile_breaks([s["nach"] for s in segments])},
        "segment_count": len(segments),
        "network_segment_count": len(result.segments),
        "runtime_seconds": round(elapsed, 3),
        "inputs": {
            "extraction_manifest": {"path": str(manifest_path), "sha256": sha256_file(manifest_path)},
            "study_area": manifest["inputs"]["study_area"],
            "network": manifest["outputs"]["network"],
            "unlinks": manifest["outputs"]["unlinks"],
            "pst_runtime_manifest": {"path": str(DEFAULT_PST_MANIFEST), "sha256": sha256_file(DEFAULT_PST_MANIFEST)},
        },
        "attribution": "© OpenStreetMap contributors (ODbL 1.0)",
        "segments": segments,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-context-m", type=float, default=3000.0)
    parser.add_argument("--modes", nargs="*", default=[m[0] for m in MODES])
    parser.add_argument("--extraction-dir", type=Path, default=EXTRACTION_DIR)
    parser.add_argument("--acquisition-buffer-m", type=int, help="Use extent-fetch extraction manifests; requires --extraction-dir")
    args = parser.parse_args()
    if not math.isfinite(args.max_context_m) or args.max_context_m < 0:
        parser.error("--max-context-m must be finite and non-negative")
    if args.acquisition_buffer_m is not None and args.acquisition_buffer_m < 10000:
        parser.error("extent acquisition buffer must be at least 10000 m")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = OUTPUT_ROOT / f"run-{stamp}"
    output_dir.mkdir(parents=True, exist_ok=False)
    adapter = PSTAdapter(manifest_path=DEFAULT_PST_MANIFEST)

    outputs: dict[str, Any] = {}
    for mode, buffer_m, radius_m in MODES:
        if mode not in args.modes:
            continue
        print(f"[{datetime.now(timezone.utc).isoformat()}] {mode}: radius {radius_m:g} m on {buffer_m} m extract ...", flush=True)
        payload = compute_mode(mode, args.acquisition_buffer_m or buffer_m, radius_m, args.max_context_m, adapter, args.extraction_dir)
        path = output_dir / f"syntax_context_{mode}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        outputs[mode] = {"path": path.name, "sha256": sha256_file(path), "segment_count": payload["segment_count"], "runtime_seconds": payload["runtime_seconds"]}
        print(f"  -> {payload['segment_count']} segments within {args.max_context_m:g} m ({payload['runtime_seconds']} s)", flush=True)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "max_context_m": args.max_context_m,
        "outputs": outputs,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifest: {output_dir / 'manifest.json'}  sha256={sha256_file(output_dir / 'manifest.json')}")


if __name__ == "__main__":
    main()
