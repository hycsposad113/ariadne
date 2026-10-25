"""Hash-gated E2 dual-tier radiation, persisted via the existing job mechanism."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
import statistics
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import shape

from urban_design.models import (ToolExecution, EvidenceCard, Project, Scenario, DatasetSnapshot, MetricDefinition,
                                 EvidenceValidationStatus, ActorKind)
from urban_design.generation.job_store import GenerationJobStore, JobStatus
from urban_design.generation.job_runner import GenerationJobRunner, PreparedOutput, write_prepared_manifest
from .contracts import GroundGridDefinition, SensorPoint
from .geometry_adapter import formal_scenario_geojson_to_environment, supplement_missing_domain_features
from .sensors import generate_ground_sensor_grid
from .sunlight import DEFAULT_RADIANCE_PATH, DEFAULT_RADIANCE_MANIFEST_PATH, verify_radiance_runtime
from .weather_snapshot import (E2Blocked, bound_approval, canonical_bytes, checked_artifact, create_record,
                               load_weather, persist_bytes, sha256)

METHODS = ("ladybug_radiance", "honeybee_radiance")
VERSION = "e2-radiation-v2"
RADIANCE_PARAMETERS = "-I -ab 2 -ad 2048 -lw 0.0001 -u-"
# Exact preserved PD-08 section bytes; content version, never an approval revision.
PD08_ASSUMPTION_REF = 'PD-08@sha256:f49e646b0855477eb1a99a6f83f497a70deb34910e0e884fbcdeeb260a57ed20'
LIMITATIONS = ["累積入射輻射不代表熱舒適、耗能或材料蓄熱。", "公共開放空間為幾何分析範圍，不代表 legal right of way。",
               "Minute=0 視為 hour_end 是 PD-08 專案假設，非供應商證據。",
               "Ladybug 遮擋篩選不含建築表面多次反射；Honeybee 驗證採獨立反射 recipe。"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class WeatherLineage(StrictModel):
    snapshot_id: str = Field(min_length=1)
    snapshot_version: str = Field(min_length=1)
    bundle_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    derived_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    mapping_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def weather_lineage(weather, bundle):
    return WeatherLineage(snapshot_id=weather.entity_id, snapshot_version=weather.payload["version"],
        bundle_sha256=weather.payload["payload_digest"],
        **{name + "_sha256": bundle["artifacts"][name]["sha256"]
           for name in ("source", "derived", "mapping")}).model_dump(mode="json")


def check_qualification_lineage(receipt, weather, bundle):
    # Deliberately exact-weather-specific. A general runtime smoke does not
    # establish weather semantics or qualify a different snapshot/version.
    try:
        lineage = WeatherLineage.model_validate(receipt.get("weather_lineage")).model_dump(mode="json")
    except ValueError as exc:
        raise E2Blocked("METHOD_QUALIFICATION_WEATHER_LINEAGE_INVALID") from exc
    if (receipt.get("qualification_scope") != "EXACT_WEATHER_FIXTURE_ONLY"
            or lineage != weather_lineage(weather, bundle)):
        raise E2Blocked("METHOD_QUALIFICATION_WEATHER_LINEAGE_INVALID")


class Recipe(StrictModel):
    classification: Literal["ASSUMED_COMMANDER"] = "ASSUMED_COMMANDER"
    ground_reflectance: Literal[0.2] = 0.2
    building_reflectance: Literal[0.2] = 0.2
    screening: Literal["RadiationStudy; Tregenza 145; opaque visibility; no interreflection"] = "RadiationStudy; Tregenza 145; opaque visibility; no interreflection"
    verification: Literal["Honeybee solar average sky times hourly record count; rfluxmtx -I -ab 2 -ad 2048 -lw 0.0001 -u-"] = "Honeybee solar average sky times hourly record count; rfluxmtx -I -ab 2 -ad 2048 -lw 0.0001 -u-"
    excluded_faces: tuple[Literal["building_bottom_faces"], ...] = ("building_bottom_faces",)
    noise_repetitions: int = Field(default=3, ge=3, le=10)
    noise_sigma_multiplier: Literal[2.0] = 2.0
    noise_classification: Literal["ASSUMED_COMMANDER"] = "ASSUMED_COMMANDER"
    sampling: Literal["LOW_DISCREPANCY_U_MINUS_SINGLE_PROCESS"] = "LOW_DISCREPANCY_U_MINUS_SINGLE_PROCESS"


class ScenarioPin(StrictModel):
    scenario_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    geometry_artifact_id: str = Field(min_length=1)
    geometry_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    environment_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class E2Plan(StrictModel):
    project_id: str = Field(min_length=1)
    weather_snapshot_id: str = Field(min_length=1)
    weather_bundle_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    baseline: ScenarioPin
    modified: ScenarioPin
    grid: GroundGridDefinition
    start_month: int = Field(default=6, ge=1, le=12)
    start_day: int = Field(default=1, ge=1, le=31)
    end_month: int = Field(default=8, ge=1, le=12)
    end_day: int = Field(default=31, ge=1, le=31)
    start_hour: int = Field(default=1, ge=1, le=24)
    end_hour: int = Field(default=24, ge=1, le=24)
    time_basis: Literal["EPW_LOCAL_STANDARD_HOUR_END"] = "EPW_LOCAL_STANDARD_HOUR_END"
    true_north_deg: float
    sensor_offset_m: Literal[0.05] = 0.05
    recipe: Recipe = Field(default_factory=Recipe)
    comparison_domain: Literal["COMMON_OVERLAP"] = "COMMON_OVERLAP"
    sensitivity_offsets: tuple[Literal[-1, 0, 1], ...] = (-1, 0, 1)
    method_validation_artifact_id: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_period_and_grid(self):
        from datetime import date
        if date(2017, self.start_month, self.start_day) > date(2017, self.end_month, self.end_day):
            raise ValueError("period must not wrap the year")
        if self.start_hour > self.end_hour or self.sensitivity_offsets != (-1, 0, 1):
            raise ValueError("hour order or sensitivity offsets invalid")
        if (self.grid.crs != "EPSG:28992" or self.grid.spacing_m <= 0
                or not all(math.isfinite(v) for v in (self.grid.origin_x, self.grid.origin_y, self.grid.spacing_m))):
            raise ValueError("E2 requires projected metres and positive sensor spacing")
        if self.baseline.scenario_id == self.modified.scenario_id:
            raise ValueError("two different scenarios required")
        return self


def runtime_fingerprint():
    status = verify_radiance_runtime()
    if not status.available:
        raise E2Blocked(status.reason or "RADIANCE_RUNTIME_NOT_VALIDATED")
    manifest = json.loads(DEFAULT_RADIANCE_MANIFEST_PATH.read_bytes())
    for name in ("rtrace", "oconv", "rcontrib", "obj2mesh", "gendaymtx", "rfluxmtx", "rmtxop"):
        if hashlib.sha256((DEFAULT_RADIANCE_PATH / "bin" / name).read_bytes()).hexdigest() != manifest["executable_hashes"].get(name):
            raise E2Blocked("RADIANCE_EXECUTABLE_HASH_MISMATCH:" + name)
    from honeybee_radiance.config import folders
    folders.radiance_path = str(DEFAULT_RADIANCE_PATH)
    return {"radiance_version": status.version, "manifest_sha256": sha256(DEFAULT_RADIANCE_MANIFEST_PATH.read_bytes()),
            "packages": {name: version(name) for name in ("ladybug-core", "ladybug-radiance", "honeybee-core", "honeybee-radiance")},
            "implementation_sha256": sha256(Path(__file__).read_bytes()), "recipe": Recipe().model_dump(mode="json")}


def scenario_geometry(store, pin: ScenarioPin, project_id):
    scenario = store.current(pin.scenario_id)
    p = scenario.payload
    if (scenario.entity_type != "DesignScenario" or scenario.project_id != project_id or scenario.revision != pin.revision
            or not str(p.get("generator", "")).startswith("formal-dictionary-")
            or p.get("parameters", {}).get("validation", {}).get("valid") is not True
            or p.get("geometry_artifact_id") != pin.geometry_artifact_id or p.get("geometry_sha256") != pin.geometry_sha256
            or p.get("status", "").lower() in {"stale", "blocked", "superseded"}):
        raise E2Blocked("SCENARIO_BINDING_INVALID:" + pin.scenario_id)
    artifact, raw = checked_artifact(store, pin.geometry_artifact_id, project_id)
    if artifact.payload.get("sha256") != pin.geometry_sha256 or artifact.payload.get("crs") != "EPSG:28992":
        raise E2Blocked("SCENARIO_GEOMETRY_HASH_OR_CRS_INVALID")
    doc = json.loads(raw)
    roles = {f.get("properties", {}).get("role") for f in doc.get("features", [])}
    domain_refs = {}
    if "site_area" not in roles or "water" not in roles:
        from urban_design.approved_generation import _load_approved_inputs
        inputs = _load_approved_inputs(store, project_id, site_generation=True)
        doc, domain_refs = supplement_missing_domain_features(doc, site_area=inputs.design_area, water=inputs.water_geometry)
        domain_refs.update(approved_inputs_hash=inputs.input_hash, workspace_digest=inputs.workspace.payload_digest)
    geometry = formal_scenario_geojson_to_environment(doc, p.get("parameters", {}).get("floor_estimates", []))
    environment_digest = sha256(canonical_bytes({"site": geometry.site_area.wkb_hex, "public": geometry.public_open_space.wkb_hex,
        "water": geometry.water_geometry.wkb_hex, "obstacles": [o.model_dump(mode="json") for o in geometry.obstacles],
        "domain_sources": domain_refs, "excluded": geometry.excluded_obstacles}))
    return geometry, {"environment_sha256": environment_digest, "scenario_revision": scenario.revision, "geometry_sha256": pin.geometry_sha256,
                      "domain_sources": domain_refs, "excluded_obstacles": list(geometry.excluded_obstacles)}


def publish_plan(store, plan: E2Plan, root):
    return persist_bytes(store, plan.project_id, Path(root), "experiment-plan", canonical_bytes(plan.model_dump(mode="json")))


def load_plan(store, identifier, project_id):
    record, raw = checked_artifact(store, identifier, project_id)
    if record.payload.get("type") != "experiment-plan":
        raise E2Blocked("EXPERIMENT_PLAN_TYPE_INVALID")
    plan = E2Plan.model_validate_json(raw)
    if plan.project_id != project_id:
        raise E2Blocked("EXPERIMENT_PLAN_PROJECT_MISMATCH")
    decision = bound_approval(store, record, record.payload["sha256"])
    return record, plan, decision


def ready_inputs(store, plan_id, project_id):
    record, plan, decision = load_plan(store, plan_id, project_id)
    weather, bundle, epw, weather_decision = load_weather(store, plan.weather_snapshot_id, project_id)
    if weather.payload["payload_digest"] != plan.weather_bundle_sha256:
        raise E2Blocked("PLAN_WEATHER_HASH_MISMATCH")
    validation, raw = checked_artifact(store, plan.method_validation_artifact_id, project_id)
    receipt = json.loads(raw)
    # JSON syntax and a valid artifact digest do not attest receipt semantics.
    # Reject non-objects before accessing fields; do not hide programmer errors.
    if not isinstance(receipt, dict):
        raise E2Blocked("METHOD_QUALIFICATION_RECEIPT_OBJECT_REQUIRED")
    if (receipt.get("classification") != "FIXTURE_ONLY"
            or receipt.get("supplier_timing_semantics_proven") is not False):
        raise E2Blocked("METHOD_QUALIFICATION_ATTESTATION_INVALID")
    check_qualification_lineage(receipt, weather, bundle)
    fingerprint = runtime_fingerprint()
    if (validation.payload.get("type") != "method-validation" or receipt.get("status") != "PASS"
            or receipt.get("fingerprint") != fingerprint or set(receipt.get("methods", {})) != set(METHODS)):
        raise E2Blocked("METHODS_NOT_VALIDATED")
    # The real fixture results are hash-checked again, not just its PASS label.
    for ref in receipt["fixture_artifacts"]:
        artifact, _ = checked_artifact(store, ref["id"], project_id)
        if artifact.payload["sha256"] != ref["sha256"]:
            raise E2Blocked("METHOD_FIXTURE_HASH_MISMATCH")
    if len(receipt["fixture_artifacts"]) != 4:
        raise E2Blocked("METHOD_FIXTURE_COUNT_INVALID")
    for method in METHODS:
        cases = receipt["methods"][method]
        if (len(cases) != 2 or [c.get("case") for c in cases] != ["unshaded", "shaded"]
                or any(c.get("method") != method or c.get("fingerprint") != fingerprint for c in cases)
                or not 0 <= cases[1]["value_kwh_m2"] < cases[0]["value_kwh_m2"] <= cases[0]["energy_upper_bound_kwh_m2"]):
            raise E2Blocked("METHOD_FIXTURE_SEMANTICS_INVALID")
        for case in cases:
            check_qualification_lineage(case, weather, bundle)
            if case.get("classification") != "FIXTURE_ONLY":
                raise E2Blocked("METHOD_FIXTURE_CLASSIFICATION_INVALID")
            matches = [r for r in receipt["fixture_artifacts"] if r["sha256"] == sha256(canonical_bytes(case))]
            if len(matches) != 1:
                raise E2Blocked("METHOD_FIXTURE_RESULT_BINDING_INVALID")
    geometries = [scenario_geometry(store, pin, project_id) for pin in (plan.baseline, plan.modified)]
    for pin, (_, metadata) in zip((plan.baseline, plan.modified), geometries):
        if pin.environment_sha256 != metadata["environment_sha256"]:
            raise E2Blocked("ENVIRONMENT_GEOMETRY_OR_DOMAIN_CHANGED")
    return record, plan, decision, weather, weather_decision, epw, fingerprint, geometries


def readiness(store, plan_id, project_id):
    try:
        ready_inputs(store, plan_id, project_id)
    except (ValueError, KeyError, OSError) as exc:
        return {"status": "BLOCKED", "dispatch_allowed": False, "reasons": [str(exc)]}
    return {"status": "READY", "dispatch_allowed": True, "reasons": []}


def weather_for_period(epw_path, plan, offset):
    from ladybug.epw import EPW
    from ladybug.wea import Wea
    from ladybug.dt import DateTime
    from ladybug.datacollection import HourlyDiscontinuousCollection
    epw = EPW(str(epw_path))
    selected = []
    for index, dt in enumerate(epw.direct_normal_radiation.datetimes):
        md = (dt.month, dt.day)
        if (plan.start_month, plan.start_day) <= md <= (plan.end_month, plan.end_day) and plan.start_hour <= dt.hour + 1 <= plan.end_hour:
            selected.append(index)
    if not selected:
        raise E2Blocked("EMPTY_ANALYSIS_PERIOD")
    times = [DateTime.from_hoy((index + 1 + offset) % 8760) for index in selected]
    def collection(original):
        return HourlyDiscontinuousCollection(original.header.duplicate(), [original.values[i] for i in selected], times)
    wea = Wea(epw.location, collection(epw.direct_normal_radiation), collection(epw.diffuse_horizontal_radiation))
    wea.enforce_on_hour = True
    return wea


def local_meshes(points, obstacles, origin):
    from ladybug_geometry.geometry3d import Mesh3D, Point3D
    ox, oy = origin
    vertices = []; faces = []
    for p in points:
        x, y, z = p.coordinates
        base = len(vertices)
        vertices.extend(Point3D(x-ox+dx, y-oy+dy, z+p.surface_offset) for dx,dy in ((-.01,-.01),(.01,-.01),(.01,.01),(-.01,.01)))
        faces.append((base,base+1,base+2,base+3))
    sensor = Mesh3D(tuple(vertices), tuple(faces))
    from ladybug_geometry.geometry3d import Face3D
    context = []
    for obstacle in obstacles:
        for face in obstacle.faces:
            geometry = Face3D(tuple(Point3D(x - ox, y - oy, z) for x, y, z in face))
            if geometry.normal.z < -0.99:
                continue
            context.append(geometry)
    return sensor, context


def command(args, root, label, timeout=480):
    env = os.environ.copy()
    env["RAYPATH"] = str(DEFAULT_RADIANCE_PATH / "lib")
    env["PATH"] = str(DEFAULT_RADIANCE_PATH / "bin") + os.pathsep + env.get("PATH", "")
    started = time.monotonic()
    process = subprocess.Popen(args, cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    dispatch = {"command": args, "pid": process.pid, "status": "DISPATCHED", "cwd": str(root)}
    (root / (label + "-dispatch.json")).write_bytes(canonical_bytes(dispatch))
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, ConnectionError) as exc:
        (root / (label + ".json")).write_bytes(canonical_bytes({**dispatch, "status": "OUTCOME_UNKNOWN",
            "observed_returncode": process.poll(), "seconds": time.monotonic()-started}))
        # Preserve process identity and partial artifacts; reconciliation decides
        # what happened. Do not launch another process or infer nonexecution.
        raise E2Blocked("OUTCOME_UNKNOWN:" + label) from exc
    (root / (label + ".json")).write_bytes(canonical_bytes({**dispatch, "returncode": process.returncode,
         "stdout": stdout, "stderr": stderr, "seconds": time.monotonic()-started}))
    if process.returncode:
        raise E2Blocked("TOOL_FAILED:" + label)


def calculate(method, wea, points, obstacles, origin, north, root):
    root.mkdir(parents=True, exist_ok=False)
    sensor, context = local_meshes(points, obstacles, origin)
    wea.write(str(root / "weather.wea"))
    if method == "ladybug_radiance":
        from ladybug_radiance.skymatrix import SkyMatrix
        from ladybug_radiance.study.radiation import RadiationStudy
        sky = SkyMatrix(wea, north=north, high_density=False, ground_reflectance=0.2)
        sky.folder = str(root)
        study = RadiationStudy(sky, sensor, context, offset_distance=0, by_vertex=False, sim_folder=str(root))
        values = list(study.radiation_values)
    elif method == "honeybee_radiance":
        from honeybee.model import Model
        from honeybee.shade import Shade
        from honeybee_radiance.sensorgrid import SensorGrid
        from honeybee_radiance.sensor import Sensor
        from honeybee_radiance.modifier.material import Plastic
        shades = [Shade(f"context_{i}", face) for i, face in enumerate(context)]
        material = Plastic.from_single_reflectance("assumed_commander_02", 0.2)
        for shade in shades:
            shade.properties.radiance.modifier = material
        model = Model("e2_verification", orphaned_shades=shades, units="Meters")
        model.properties.radiance.add_sensor_grid(SensorGrid("public_sensor", [Sensor(v.to_array(), (0,0,1)) for v in sensor.face_centroids]))
        hbjson = model.to_hbjson("model", str(root))
        cli = [sys.executable, "-m", "honeybee_radiance"]
        rad = root / "radiance"
        command(cli + ["translate", "model-to-rad-folder", hbjson, "--folder", str(rad), "--grid-check", "--no-view-check"], root, "translate")
        command(cli + ["sky", "mtx", str(root / "weather.wea"), "--folder", str(root / "sky"), "--name", "summer", "--solar", "--cumulative", "--north", str(north)], root, "sky")
        command(cli + ["octree", "from-folder", str(rad / "model"), "--output", str(root / "scene.oct")], root, "octree")
        command(cli + ["sky", "skydome", "--sky-density", "1", "--folder", str(root / "dome"), "--name", "summer"], root, "dome")
        dome = next(p for p in (root / "dome").glob("summer*") if p.is_file())
        pts = next((rad / "model").rglob("public_sensor.pts"))
        command(cli + ["dc", "scoeff", str(root / "scene.oct"), str(pts), str(dome), str(root / "sky/summer.mtx"),
                       "--sensor-count", str(len(points)), "--output-format", "a", "--conversion", "0.265074126 0.670114631 0.064811243", "--order-by-sensor", "--remove-header",
                       "--rad-params", RADIANCE_PARAMETERS, "--output", str(root / "incident.mtx")], root, "incident")
        lines = (root / "incident.mtx").read_text().splitlines()
        values = [float(line.strip()) * len(wea.hoys) / 1000 for line in lines if line.strip() and not line.startswith(("#", "NROWS=", "NCOLS=", "NCOMP=", "FORMAT="))]
    else:
        raise E2Blocked("UNKNOWN_METHOD")
    if len(values) != len(points) or any(not math.isfinite(v) or v < 0 for v in values):
        raise E2Blocked("INVALID_SENSOR_RESULTS")
    return dict(zip((p.point_id for p in points), values))


def compare_distributions(baseline, modified):
    """Within-method common-overlap direction, retaining displaced sensor area."""
    base_points = {p["point_id"]: p for p in baseline["sensors"]}
    mod_points = {p["point_id"]: p for p in modified["sensors"]}
    common = sorted(set(baseline["values"]) & set(modified["values"]))
    if not common:
        raise E2Blocked("NO_COMMON_VALID_SENSORS")
    area = sum(base_points[p]["cell_area_m2"] for p in common)
    for p in common:
        if base_points[p]["cell_area_m2"] != mod_points[p]["cell_area_m2"]:
            raise E2Blocked("SENSOR_AREA_MISMATCH")
    base = sum(base_points[p]["cell_area_m2"] * baseline["values"][p] for p in common) / area
    mod = sum(base_points[p]["cell_area_m2"] * modified["values"][p] for p in common) / area
    delta = mod - base
    occupied = sorted(set(baseline["values"]) - set(modified["values"]))
    return {"baseline_kwh_m2": base, "modified_kwh_m2": mod, "delta_kwh_m2": delta,
            "direction": "DECREASED" if delta < 0 else "INCREASED" if delta > 0 else "UNCHANGED",
            "common_points": len(common), "common_area_m2": area, "newly_occupied_point_ids": occupied,
            "newly_occupied_area_m2": sum(base_points[p]["cell_area_m2"] for p in occupied),
            "occupancy_ratio": len(occupied) / len(baseline["values"]),
            "area_occupancy_ratio": sum(base_points[p]["cell_area_m2"] for p in occupied) / baseline["valid_area_m2"]}


def noise_assessment(deltas, recipe):
    """Observed repeatability band, not a calibrated physical-accuracy claim."""
    if len(deltas) < recipe.noise_repetitions or any(not math.isfinite(v) for v in deltas):
        raise ValueError("NOISE_REQUIRES_FINITE_REPEATED_DELTAS")
    mean = statistics.mean(deltas)
    sigma = statistics.stdev(deltas)
    threshold = recipe.noise_sigma_multiplier * sigma
    direction = ("NOT_SIGNIFICANT" if abs(mean) <= threshold else
                 "INCREASED" if mean > 0 else "DECREASED")
    return {"classification": recipe.noise_classification, "sample_count": len(deltas),
            "delta_samples_kwh_m2": list(deltas), "delta_mean_kwh_m2": mean,
            "delta_sample_stddev_kwh_m2": sigma, "sigma_multiplier": recipe.noise_sigma_multiplier,
            "threshold_kwh_m2": threshold, "direction": direction,
            "sampling": recipe.sampling, "threshold_definition": "abs(mean delta) <= 2 * sample SD of paired deltas",
            "scope": "Observed repeat variability under low-discrepancy sampling; not absolute accuracy or a p-value"}


def direction_summary(comparisons):
    by_method = {}
    for method in METHODS:
        shifts = comparisons[method]
        base = shifts["0"]["direction"]
        reversed_direction = any({base, shifts[s]["direction"]} == {"INCREASED", "DECREASED"} for s in ("-1", "1"))
        by_method[method] = {"directions": {s: v["direction"] for s, v in shifts.items()}, "sensitivity_reversed": reversed_direction}
    significant = {"INCREASED", "DECREASED"}
    agreement = {s: (comparisons[METHODS[0]][s]["direction"] == comparisons[METHODS[1]][s]["direction"]
                    if all(comparisons[m][s]["direction"] in significant for m in METHODS) else None)
                 for s in ("-1", "0", "1")}
    return {"methods": by_method, "direction_agreement_by_offset": agreement,
            "sensitivity_reversed": any(v["sensitivity_reversed"] for v in by_method.values()),
            "explanation": "只比較各方法內的改善（入射輻射降低）／變差方向。篩選使用天空 patch 遮擋；驗證使用含反射的 Radiance 係數。方向一致不代表絕對值可互換。"}


def sensor_distribution(points, values):
    valid = [p for p in points if p.status == "VALID"]
    if not valid or set(values) != {p.point_id for p in valid}:
        raise E2Blocked("MISSING_SENSOR_VALUES")
    area = sum(p.cell_area_m2 for p in valid)
    total_area = sum(p.cell_area_m2 for p in points)
    return {"sensors": [p.model_dump(mode="json") for p in points], "values": values, "unit": "kWh/m²",
            "area_weighted_kwh_m2": sum(p.cell_area_m2 * values[p.point_id] for p in valid) / area,
            "point_count": len(points), "valid_points": len(valid), "excluded_points": len(points)-len(valid),
            "valid_area_m2": area, "total_area_m2": total_area, "point_coverage_ratio": len(valid)/len(points),
            "area_coverage_ratio": area/total_area}


def validate_methods(store, project_id, snapshot_id, root):
    """Real shaded/unshaded fixture; imports and declared PASS never suffice."""
    fingerprint = runtime_fingerprint()
    weather, bundle, epw, _ = load_weather(store, snapshot_id, project_id, require_approval=False)
    qualification = {"qualification_scope": "EXACT_WEATHER_FIXTURE_ONLY",
                     "weather_lineage": weather_lineage(weather, bundle)}
    from types import SimpleNamespace
    from .geometry_adapter import footprint_to_obstacle
    from .contracts import SensorPoint
    fixture_period = SimpleNamespace(start_month=6, start_day=21, end_month=6, end_day=21, start_hour=9, end_hour=15)
    wea = weather_for_period(epw, fixture_period, 0)
    point = SensorPoint.create(x=0, y=0, z=0, normal=(0,0,1), surface_offset=0.05, cell_area_m2=1)
    # Enclose fixture sensor beneath a box roof. This is a physical fixture,
    # never substituted for a formal scenario or planning measurement.
    obstacle = footprint_to_obstacle([(-3,-3), (3,-3), (3,3), (-3,3)], 5)
    energy_upper_bound = (sum(wea.direct_normal_irradiance.values) + sum(wea.diffuse_horizontal_irradiance.values)) / 1000
    results = {}; refs = []
    root = Path(root)
    for method in METHODS:
        runs = []
        for label, obstacles in (("unshaded", []), ("shaded", [obstacle])):
            folder = root / method / label
            started = time.monotonic()
            values = calculate(method, wea, [point], obstacles, (0,0), 0, folder)
            value = values[point.point_id]
            result = {"method": method, "case": label, "value_kwh_m2": value, "seconds": time.monotonic()-started,
                      **qualification, "classification": "FIXTURE_ONLY", "energy_upper_bound_kwh_m2": energy_upper_bound, "fingerprint": fingerprint}
            artifact = persist_bytes(store, project_id, root / "registered", "method-fixture", canonical_bytes(result))
            refs.append({"id": artifact.entity_id, "sha256": artifact.payload["sha256"]})
            runs.append(result)
        if not 0 < runs[0]["value_kwh_m2"] <= energy_upper_bound or runs[1]["value_kwh_m2"] >= runs[0]["value_kwh_m2"]:
            raise E2Blocked("METHOD_FIXTURE_DIRECTION_FAILED:" + method)
        results[method] = runs
    receipt = {**qualification, "classification": "FIXTURE_ONLY", "supplier_timing_semantics_proven": False,
               "status": "PASS", "methods": results, "fixture_artifacts": refs, "fingerprint": fingerprint,
               "acceptance": "positive unshaded radiation and physically enclosed sensor reduction, separately in both real methods"}
    return persist_bytes(store, project_id, root / "registered", "method-validation", canonical_bytes(receipt))


def find_method_validation(store, project_id: str, snapshot_id: str, weather=None, bundle=None):
    if weather is None or bundle is None:
        weather, bundle, _, _ = load_weather(store, snapshot_id, project_id, require_approval=False)
    expected_lineage = weather_lineage(weather, bundle)
    try:
        artifacts = store.list_current("Artifact", project_id=project_id)
    except Exception:
        return None
    for record in artifacts:
        if record.payload.get("type") != "method-validation":
            continue
        try:
            _, raw = checked_artifact(store, record.entity_id, project_id)
            receipt = json.loads(raw)
            if (isinstance(receipt, dict)
                    and receipt.get("status") == "PASS"
                    and receipt.get("classification") == "FIXTURE_ONLY"
                    and receipt.get("weather_lineage") == expected_lineage):
                return record
        except Exception:
            continue
    return None



def persist_run(store, plan_record, plan, weather, weather_decision, plan_decision, payload, root, job_id, method, pin, offset):
    artifact = persist_bytes(store, plan.project_id, root, "radiation-result", canonical_bytes(payload), parents=[plan_record.entity_id, pin.geometry_artifact_id])
    suffix = f"{job_id}-{method}-{pin.scenario_id}-{offset}"
    run = ToolExecution(id="tool-e2-" + suffix, project_id=plan.project_id, scenario_id=pin.scenario_id,
                        tool=method, tool_version=VERSION, environment={"RAYPATH": str(DEFAULT_RADIANCE_PATH / "lib"), "Radiance": "6.0.2"},
                        input_refs=[plan_record.entity_id, weather.entity_id, weather_decision, plan_decision],
                        input_snapshot_hashes={weather.entity_id: weather.payload["sha256"]},
                        input_artifact_ids=[plan_record.entity_id, pin.geometry_artifact_id],
                        input_artifact_hashes_by_id={plan_record.entity_id: plan_record.payload["sha256"], pin.geometry_artifact_id: pin.geometry_sha256},
                        parameters={"offset_hours": offset, "recipe": plan.recipe.model_dump(mode="json"), "plan": plan.model_dump(mode="json")},
                        output_artifact_refs=[artifact.entity_id], output_artifact_hashes=[artifact.payload["sha256"]],
                        status=payload["status"], idempotency_key=suffix, limitations=LIMITATIONS)
    create_record(store, "ToolExecution", run.model_dump(mode="json"), plan.project_id)
    # Start unverified; promotion below requires current approvals, immutable
    # bytes, a recomputed weighted metric, and domain relationship validation.
    metric_id = "metric-e2-incident-" + plan_record.payload["sha256"][7:31]
    evidence = EvidenceCard(id="evidence-e2-" + suffix, project_id=plan.project_id, scenario_id=pin.scenario_id,
        input_versions=[str(pin.revision)], claim={"id": "claim-e2-"+suffix, "type": "observation", "statement": "面積加權累積入射輻射；未改善及失敗結果同樣保留。"},
        source_refs=[run.id, plan_record.entity_id, weather_decision, plan_decision],
        dataset_refs=[{"id": weather.entity_id, "project_id": plan.project_id, "version": weather.payload["version"], "sha256": weather.payload["sha256"]}],
        metric={"id": metric_id, "name": "Area weighted cumulative incident radiation", "unit": "kWh/m²"},
        method={"id": method, "description": getattr(plan.recipe, "screening" if method == METHODS[0] else "verification")},
        tool=method, tool_version=VERSION,
        result={"artifact_refs": [artifact.entity_id], "artifact_hashes": [artifact.payload["sha256"]],
                "values": {"area_weighted_kwh_m2": payload["distribution"]["area_weighted_kwh_m2"]} if payload["status"] == "SUCCEEDED" else {},
                "status": "computed" if payload["status"] == "SUCCEEDED" else "unavailable", "project_id": plan.project_id,
                "scenario_id": pin.scenario_id, "dataset_ids": [weather.entity_id], "units": "kWh/m²"},
        units="kWh/m²", assumptions=["ASSUMED_COMMANDER", PD08_ASSUMPTION_REF], limitations=LIMITATIONS,
        confidence={"level": "low", "basis": "Frozen inputs and method fixture", "uncertainty": "Authored materials and hour-end assumption; independent review pending", "assessed_by": "e2_service"},
        validation_status="unverified", created_at=datetime.now(timezone.utc))
    if payload["status"] == "SUCCEEDED":
        try:
            approved_record, approved_document, current_pd = load_plan(store, plan_record.entity_id, plan.project_id)
            current_weather, _, _, current_wd = load_weather(store, weather.entity_id, plan.project_id)
            if (current_pd != plan_decision or current_wd != weather_decision
                    or approved_record.payload["sha256"] != plan_record.payload["sha256"]
                    or current_weather.payload["payload_digest"] != plan.weather_bundle_sha256):
                raise E2Blocked("EVIDENCE_APPROVAL_BINDING_CHANGED")
            _, result_bytes = checked_artifact(store, artifact.entity_id, plan.project_id)
            observed = json.loads(result_bytes)
            if (observed["method"] != method or observed["scenario_id"] != pin.scenario_id
                    or observed["offset_hours"] != offset or observed["plan_id"] != plan_record.entity_id
                    or observed["weather_snapshot_id"] != weather.entity_id
                    or observed["fingerprint"] != runtime_fingerprint()):
                raise E2Blocked("EVIDENCE_RESULT_BINDING_INVALID")
            distribution = observed["distribution"]
            recomputed = sensor_distribution([SensorPoint.model_validate(p) for p in distribution["sensors"]], distribution["values"])
            if recomputed != distribution:
                raise E2Blocked("EVIDENCE_WEIGHTED_METRIC_MISMATCH")
            scenario_geometry(store, pin, plan.project_id)
            source_scenario = store.current(pin.scenario_id)
            if (str(source_scenario.payload.get("status", "")).lower() == "draft"
                    or source_scenario.payload.get("parameters", {}).get("provenance") == "FORMAL_DRAFT"):
                raise E2Blocked("DRAFT_SCENARIO_NOT_FORMAL_EVIDENCE")
            metric = MetricDefinition(id=metric_id, name=evidence.metric.name, formula="sum(A_i * radiation_i) / sum(A_i); valid ground cells only",
                unit="kWh/m²", input_refs=[plan_record.entity_id, weather.entity_id], implementation_version=VERSION,
                reference_fixture=plan.method_validation_artifact_id)
            create_record(store, "MetricDefinition", metric.model_dump(mode="json"), plan.project_id)
            def typed(model, stored):
                return model.model_validate({k:v for k,v in stored.payload.items() if k in model.model_fields})
            project = typed(Project, store.current(plan.project_id))
            scenario = typed(Scenario, store.current(pin.scenario_id))
            dataset = typed(DatasetSnapshot, current_weather)
            evidence.validation_status = EvidenceValidationStatus.VALIDATED
            evidence.result.validation_status = EvidenceValidationStatus.VALIDATED
            evidence.validate_relationships(project=project, scenario=scenario, datasets=[dataset], tool_execution=run, metric=metric)
        except (ValueError, KeyError, OSError) as exc:
            evidence.validation_status = EvidenceValidationStatus.UNVERIFIED
            evidence.result.validation_status = EvidenceValidationStatus.UNVERIFIED
            evidence.limitations.append("EVIDENCE_PROMOTION_BLOCKED:" + str(exc))
    promoted = evidence.validation_status == EvidenceValidationStatus.VALIDATED
    retained = evidence.model_copy(deep=True)
    retained.validation_status = EvidenceValidationStatus.UNVERIFIED
    retained.result.validation_status = EvidenceValidationStatus.UNVERIFIED
    create_record(store, "EvidenceCard", retained.model_dump(mode="json"), plan.project_id)
    if promoted:
        def promotion_check():
            _, _, pd = load_plan(store, plan_record.entity_id, plan.project_id)
            _, _, _, wd = load_weather(store, weather.entity_id, plan.project_id)
            if pd != plan_decision or wd != weather_decision:
                raise E2Blocked("EVIDENCE_APPROVAL_BINDING_CHANGED")
            scenario_geometry(store, pin, plan.project_id)
        try:
            store.update(evidence.id, evidence.model_dump(mode="json"), replace=True,
                         action="PromoteE2Evidence", actor="e2_service", actor_kind=ActorKind.AGENT_AUTOMATION,
                         before_commit=promotion_check)
        except (ValueError, KeyError, OSError) as exc:
            evidence = retained
            evidence.limitations.append("EVIDENCE_PROMOTION_BLOCKED:" + str(exc))
            store.update(evidence.id, evidence.model_dump(mode="json"), replace=True, action="BlockE2Promotion")
    return {"artifact_id": artifact.entity_id, "sha256": artifact.payload["sha256"], "tool_execution_id": run.id, "evidence_card_id": evidence.id, "evidence_validation_status": evidence.validation_status.value}


def execute_job(store, job, staging, token):
    root = Path(staging)
    body = job.request
    pr, plan, pd, weather, wd, epw, fingerprint, geometries = ready_inputs(store, body["plan_id"], body["project_id"])
    if body["fingerprint"] != fingerprint or body["plan_decision"] != pd or body["weather_decision"] != wd:
        raise E2Blocked("DISPATCH_INPUT_CHANGED")
    refs = {r["id"]: r["sha256"] for r in job.input_refs}
    if refs.get(pr.entity_id) != pr.payload["sha256"] or refs.get(weather.entity_id) != weather.payload["sha256"]:
        raise E2Blocked("FROZEN_INPUT_CHANGED")
    overlap = geometries[0][0].public_open_space.intersection(geometries[1][0].public_open_space)
    if overlap.is_empty or overlap.area <= 0:
        raise E2Blocked("NO_COMMON_OVERLAP")
    grids = []
    for geometry, _ in geometries:
        # Generate on the site first so occupied and water-excluded cells remain
        # visible. Clip cell areas to the site to avoid edge overcounting.
        points = generate_ground_sensor_grid(geometry.site_area, plan.grid.spacing_m, (plan.grid.origin_x, plan.grid.origin_y),
                    surface_offset=plan.sensor_offset_m, crs=plan.grid.crs)
        from shapely.geometry import Point, box
        adjusted = []
        half = plan.grid.spacing_m / 2
        for p in points:
            cell = box(p.coordinates[0]-half, p.coordinates[1]-half, p.coordinates[0]+half, p.coordinates[1]+half).intersection(geometry.site_area)
            status = "VALID" if geometry.public_open_space.covers(Point(p.coordinates[0],p.coordinates[1])) else "EXCLUDED_INSIDE_FOOTPRINT"
            adjusted.append(p.model_copy(update={"cell_area_m2": cell.area, "status": status}))
        grids.append(adjusted)
    origin = ((geometries[0][0].site_area.bounds[0] + geometries[0][0].site_area.bounds[2])/2,
              (geometries[0][0].site_area.bounds[1] + geometries[0][0].site_area.bounds[3])/2)
    results = {}; comparisons = {}; failed = False
    for method in METHODS:
        results[method] = {}; comparisons[method] = {}
        for offset in (-1,0,1):
            wea = weather_for_period(epw, plan, offset)
            pair = []
            for pin, (geometry, metadata), points in zip((plan.baseline, plan.modified), geometries, grids):
                if token.cancelled:
                    raise E2Blocked("CANCELLED")
                folder = root / method / str(offset) / pin.scenario_id
                started = time.monotonic()
                payload = {"status": "FAILED", "method": method, "scenario_id": pin.scenario_id, "offset_hours": offset,
                           "metadata": metadata, "fingerprint": fingerprint, "plan_id": pr.entity_id, "weather_snapshot_id": weather.entity_id,
                           "limitations": LIMITATIONS}
                try:
                    repetitions = plan.recipe.noise_repetitions if method == "honeybee_radiance" else 1
                    samples = []
                    for repeat in range(repetitions):
                        if token.cancelled:
                            raise E2Blocked("CANCELLED")
                        folder.mkdir(parents=True, exist_ok=True)
                        dispatch_receipt = folder / ("repeat-" + str(repeat) + "-dispatch.json")
                        dispatch_receipt.write_bytes(canonical_bytes({"method": method, "repeat": repeat,
                            "status": "DISPATCHED", "pid": None, "process_identity": "LIBRARY_BOUNDARY_NOT_EXPOSED",
                            "scenario_id": pin.scenario_id, "scenario_revision": pin.revision,
                            "geometry_sha256": pin.geometry_sha256, "cwd": str(folder)}))
                        values = calculate(method, wea, [p for p in points if p.status == "VALID"], geometry.obstacles,
                                           origin, plan.true_north_deg, folder / ("repeat-" + str(repeat)))
                        (folder / ("repeat-" + str(repeat) + ".json")).write_bytes(canonical_bytes({
                            "status": "RETURNED", "sensor_values_sha256": sha256(canonical_bytes(values))}))
                        samples.append(sensor_distribution(points, values))
                    mean_values = {identifier: statistics.mean(v["values"][identifier] for v in samples)
                                   for identifier in samples[0]["values"]}
                    payload.update(status="SUCCEEDED", distribution=sensor_distribution(points, mean_values),
                                   repeated_distributions=samples,
                                   sampling_metadata={"sample_count": repetitions, "recipe": plan.recipe.model_dump(mode="json"),
                                                      "rad_params": RADIANCE_PARAMETERS if method == METHODS[1] else "deterministic opaque visibility"})
                except Exception as exc:
                    payload["failure"] = f"{type(exc).__name__}:{exc}"
                    if isinstance(exc, (ConnectionError, TimeoutError, subprocess.TimeoutExpired)) or "OUTCOME_UNKNOWN" in str(exc):
                        payload["status"] = "OUTCOME_UNKNOWN"
                    failed = True
                payload["seconds"] = time.monotonic()-started
                payload["records"] = persist_run(store, pr, plan, weather, wd, pd, payload, Path(store.database).parent / "e2-artifacts", job.job_id, method, pin, offset)
                results[method].setdefault(str(offset), []).append(payload)
                pair.append(payload)
                if payload["status"] == "OUTCOME_UNKNOWN":
                    # Preserve the observed failure and stop. Never redispatch.
                    (root / "outcome-unknown.json").write_bytes(canonical_bytes(payload))
                    raise E2Blocked("OUTCOME_UNKNOWN")
            if all(p["status"] == "SUCCEEDED" for p in pair):
                comparisons[method][str(offset)] = compare_distributions(pair[0]["distribution"], pair[1]["distribution"])
                if method == "honeybee_radiance":
                    deltas = [compare_distributions(a, b)["delta_kwh_m2"]
                              for a, b in zip(pair[0]["repeated_distributions"], pair[1]["repeated_distributions"])]
                    noise = noise_assessment(deltas, plan.recipe)
                    comparisons[method][str(offset)].update(direction=noise["direction"], noise_metadata=noise)
                else:
                    comparisons[method][str(offset)]["noise_metadata"] = {"classification": "DETERMINISTIC_METHOD",
                        "sample_count": 1, "delta_sample_stddev_kwh_m2": 0.0, "threshold_kwh_m2": 0.0}

    summary = direction_summary(comparisons) if not failed else None
    result = {"job_id": job.job_id, "status": "FAILED" if failed else "SUCCEEDED", "plan_id": pr.entity_id,
              "plan_sha256": pr.payload["sha256"], "weather_snapshot_id": weather.entity_id,
              "weather_bundle_sha256": weather.payload["payload_digest"], "results": results, "comparisons": comparisons,
              "direction_summary": summary, "limitations": LIMITATIONS, "evidence_validation_status": "validated" if not failed and all(
                  v["records"]["evidence_validation_status"] == "validated" for shifts in results.values() for pair in shifts.values() for v in pair
              ) else "unverified"}
    raw = canonical_bytes(result)
    (root / "result.json").write_bytes(raw)
    # Every raw command, scene, sky and spatial result is covered by the durable
    # job manifest, not only the final summary file.
    outputs = [PreparedOutput(artifact_id="e2-"+job.job_id+"-"+hashlib.sha256(str(p.relative_to(root)).encode()).hexdigest()[:16],
                    relative_path=str(p.relative_to(root)), sha256=sha256(p.read_bytes()), size_bytes=p.stat().st_size)
               for p in sorted(root.rglob("*")) if p.is_file()]
    return write_prepared_manifest(root, handler_version=VERSION, input_refs=job.input_refs, output_refs=outputs)


def open_jobs(store, job_database):
    path = Path(job_database) if job_database else Path(store.database).with_name("e2-jobs.sqlite3")
    jobs = GenerationJobStore(path)
    work = path.with_suffix("")
    runner = GenerationJobRunner(jobs, staging_root=work / "staging", output_root=work / "out")
    runner.register_handler("E2_RADIATION", VERSION, lambda job, staging, token: execute_job(store, job, staging, token), external=True)
    def current(job):
        try:
            record, raw = checked_artifact(store, job.request["plan_id"], job.project_id)
            plan = E2Plan.model_validate_json(raw)
            refs = {r["id"]: r["sha256"] for r in job.input_refs}
            if refs.get(record.entity_id) != record.payload["sha256"]:
                return False
            for pin in (plan.baseline, plan.modified):
                _, metadata = scenario_geometry(store, pin, job.project_id)
                if metadata["environment_sha256"] != pin.environment_sha256:
                    return False
            return True
        except (ValueError, KeyError, OSError):
            return False
    runner.revision_is_current = current
    original_complete = jobs.complete
    def complete(job_id, owner_token, *, stale=False):
        # Serialize authoritative revision reads against writers through the
        # operational completion commit. Projection still rechecks on reads.
        with store.locked_connection() as connection:
            owns_transaction = not connection.in_transaction
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            try:
                return original_complete(job_id, owner_token, stale=stale or not current(jobs.get(job_id)))
            finally:
                if owns_transaction:
                    connection.rollback()  # read-only authority transaction
    jobs.complete = complete
    return jobs, runner, work / "out"


def simulate(store, plan_id, project_id, idempotency_key, job_database=None):
    pr, plan, pd, weather, wd, _, fingerprint, _ = ready_inputs(store, plan_id, project_id)
    jobs, runner, output = open_jobs(store, job_database)
    job, created = jobs.enqueue(project_id=project_id, idempotency_key=idempotency_key, stage="E2_RADIATION",
        request={"plan_id": plan_id, "project_id": project_id, "plan_decision": pd, "weather_decision": wd, "fingerprint": fingerprint},
        expected_revision=sha256(canonical_bytes([pin.model_dump(mode="json") for pin in (plan.baseline, plan.modified)])),
        input_refs=[{"id": pr.entity_id, "sha256": pr.payload["sha256"], "kind": "experiment_plan"},
                    {"id": weather.entity_id, "sha256": weather.payload["sha256"], "kind": "weather_snapshot"},
                    *[{"id": pin.geometry_artifact_id, "sha256": pin.geometry_sha256, "kind": "scenario_geometry"} for pin in (plan.baseline, plan.modified)]])
    if created:
        runner.run(job.job_id)
    return read_result(store, job.job_id, project_id, job_database)


def reconcile_unknown(store, jobs, runner, job):
    """Capture receipts, observed processes, files and ledger; never redispatch."""
    report_path = runner.staging_root / job.job_id / "reconciliation.json"
    if report_path.is_file():
        return json.loads(report_path.read_bytes())
    files = []; receipts = []; processes = []
    for directory in (runner.staging_root / job.job_id, runner.output_root / job.job_id):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path == report_path:
                continue
            files.append({"path": str(path), "sha256": sha256(path.read_bytes())})
            if path.name.endswith("-dispatch.json"):
                receipt = json.loads(path.read_bytes()); receipts.append(receipt)
                state = "UNKNOWN"
                try:
                    if isinstance(receipt.get("pid"), int):
                        os.kill(receipt["pid"], 0)
                        state = "PID_EXISTS_IDENTITY_NOT_REVALIDATED"
                except ProcessLookupError:
                    state = "PID_NOT_PRESENT"
                except PermissionError:
                    pass
                terminal = path.with_name(path.name.replace("-dispatch.json", ".json"))
                final = json.loads(terminal.read_bytes()) if terminal.is_file() else {}
                processes.append({"pid": receipt["pid"], "observation": state,
                                  "receipt_returncode": final.get("returncode", final.get("observed_returncode"))})
    ledger_runs = [r.entity_id for r in store.list_current("ToolExecution", project_id=job.project_id)
                   if r.entity_id.startswith("tool-e2-" + job.job_id + "-")]
    report = {"status": "OUTCOME_UNKNOWN", "reconciliation_status": "UNRESOLVED",
              "redispatch_allowed": False, "dispatch_receipts": receipts, "process_observations": processes,
              "receipt_gap": "NO_DISPATCH_RECEIPT_AT_FAILED_BOUNDARY" if not receipts else None,
              "output_files": files, "ledger_tool_execution_ids": ledger_runs,
              "ledger_event_ids": [e.event_id for identifier in ledger_runs for e in store.events(target_id=identifier)],
              "job_events": [{"seq": e.seq, "status": e.to_status.value, "reason": e.reason} for e in jobs.events(job.job_id)],
              "note": "Inspection snapshot only; process identity may be unknown. Explicit reconciliation required before any retry."}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with report_path.open("xb") as stream:
            stream.write(canonical_bytes(report))
    except FileExistsError:
        return json.loads(report_path.read_bytes())
    return report


def read_result(store, job_id, project_id, job_database=None):
    jobs, runner, output = open_jobs(store, job_database)
    job = jobs.get(job_id)
    if job.project_id != project_id:
        raise E2Blocked("JOB_PROJECT_MISMATCH")
    if job.status.value != "READY":
        response = {"job_id": job.job_id, "status": job.status.value, "reason": job.error_code,
                    "dispatch_retried": False, "published_as_current": False}
        if job.status is JobStatus.OUTCOME_UNKNOWN:
            response["reconciliation"] = reconcile_unknown(store, jobs, runner, job)
        if job.status is JobStatus.STALE_FOR_CURRENT_CONTEXT:
            response["historical_output_refs"] = list(job.output_refs)
        return response
    if not runner.revision_is_current(job):
        return {"job_id": job.job_id, "status": "STALE_FOR_CURRENT_CONTEXT", "dispatch_retried": False,
                "published_as_current": False, "historical_output_refs": list(job.output_refs)}
    path = output / job_id
    manifest = json.loads((path / "manifest.json").read_bytes())
    if sha256((path / "manifest.json").read_bytes()) != job.output_manifest_sha256:
        raise E2Blocked("RESULT_MANIFEST_HASH_MISMATCH")
    for ref in manifest["output_refs"]:
        if sha256((path / ref["relative_path"]).read_bytes()) != ref["sha256"]:
            raise E2Blocked("RESULT_ARTIFACT_HASH_MISMATCH")
    return json.loads((path / "result.json").read_bytes())
