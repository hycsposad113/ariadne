"""Direct sunlight duration simulation prototype (W6 precursor lane).

Implements:
1. Optional Radiance method: Ladybug Sunpath + ladybug_radiance.intersection_matrix
2. Headless method: Ladybug Sunpath + pure Python ray intersection
3. Daylight saving time validation (Europe/Amsterdam)
4. Convergence across timesteps (1, 4, 12)
5. Surface offset and self-occlusion / inside-obstacle guards
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import warnings
import zoneinfo
from datetime import date, datetime, timedelta, time
from dataclasses import dataclass
from typing import Any, Sequence

from ladybug.location import Location
from ladybug.sunpath import Sunpath
from ladybug_geometry.geometry3d import Face3D, Point3D, Vector3D
import ladybug_radiance.config as rad_config
import ladybug_radiance.intersection as rad_intersection
from shapely.geometry import Point, Polygon

from .contracts import (
    AnalysisPeriod,
    ColormapBin,
    ColormapSpec,
    Obstacle,
    PointSunlightResult,
    SensorPoint,
    SiteLocation,
    SunlightSimulationResult,
)


_RADIANCE_SIM_FOLDER: str | None = None


def _radiance_sim_folder() -> str:
    """Per-process Radiance working folder. ladybug_radiance defaults to the shared system temp dir with
    fixed file names (scene.oct …), so two concurrent runs corrupt each other's octree."""
    global _RADIANCE_SIM_FOLDER
    if _RADIANCE_SIM_FOLDER is None:
        import atexit, shutil, tempfile
        _RADIANCE_SIM_FOLDER = tempfile.mkdtemp(prefix="urban-design-radiance-")
        atexit.register(shutil.rmtree, _RADIANCE_SIM_FOLDER, True)
    return _RADIANCE_SIM_FOLDER
from .geometry_adapter import polygon_faces_to_footprint

DEFAULT_RADIANCE_PATH = Path.home() / ".local" / "share" / "urban-design-runtimes" / "radiance-6.0.2-arm64"
DEFAULT_RADIANCE_MANIFEST_PATH = Path(__file__).resolve().parents[3] / "config" / "runtimes" / "radiance-6.0.2-arm64.json"
RADIANCE_SENSOR_BATCH_SIZE = 512


@dataclass(frozen=True)
class RadianceRuntimeStatus:
    available: bool
    version: str | None = None
    manifest_version: str | None = None
    reason: str | None = None


class RadianceExecutionError(RuntimeError):
    """Raised when the verified Radiance runtime fails during visibility analysis."""


def configure_radiance_runtime(custom_path: Path | str | None = None) -> bool:
    """Ensure Radiance environment variables and ladybug_radiance paths are bound."""
    rad_dir = Path(custom_path) if custom_path else DEFAULT_RADIANCE_PATH
    if not (rad_dir.exists() and (rad_dir / "bin" / "rtrace").is_file() and (rad_dir / "lib").is_dir()):
        return False

    bin_dir = str(rad_dir / "bin")
    lib_dir = str(rad_dir / "lib")

    current_path = os.environ.get("PATH", "")
    if bin_dir not in current_path:
        os.environ["PATH"] = f"{bin_dir}:{current_path}"
    os.environ["RAYPATH"] = lib_dir

    rad_config.folders.radiance_path = str(rad_dir)
    rad_intersection.OCONV_EXE = os.path.join(bin_dir, "oconv")
    rad_intersection.RCONTRIB_EXE = os.path.join(bin_dir, "rcontrib")
    rad_intersection.OBJ2MESH_EXE = os.path.join(bin_dir, "obj2mesh")

    return True


def verify_radiance_runtime(
    custom_path: Path | str | None = None,
    manifest_path: Path | str | None = None,
) -> RadianceRuntimeStatus:
    """Verify the selected Radiance runtime version against its pinned manifest."""
    runtime_dir = Path(custom_path) if custom_path else DEFAULT_RADIANCE_PATH
    pinned_manifest = Path(manifest_path) if manifest_path else DEFAULT_RADIANCE_MANIFEST_PATH
    try:
        manifest = json.loads(pinned_manifest.read_text(encoding="utf-8"))
        manifest_version = str(manifest["version"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return RadianceRuntimeStatus(
            available=False,
            reason=f"RADIANCE_MANIFEST_UNAVAILABLE: {type(exc).__name__}: {exc}",
        )

    if manifest_version != "6.0.2" or manifest.get("architecture") != "arm64":
        return RadianceRuntimeStatus(
            available=False,
            manifest_version=manifest_version,
            reason="RADIANCE_MANIFEST_MISMATCH: expected pinned Radiance 6.0.2 arm64 manifest",
        )

    bin_dir = runtime_dir / "bin"
    lib_dir = runtime_dir / "lib"
    required = ("rtrace", "oconv", "rcontrib", "obj2mesh")
    missing = [name for name in required if not (bin_dir / name).is_file() or not os.access(bin_dir / name, os.X_OK)]
    if missing or not lib_dir.is_dir():
        reason = "RADIANCE_RUNTIME_INCOMPLETE: " + (", ".join(missing) if missing else "lib directory missing")
        return RadianceRuntimeStatus(available=False, manifest_version=manifest_version, reason=reason)

    runtime_env = os.environ.copy()
    existing_path = runtime_env.get("PATH", "")
    if str(bin_dir) not in existing_path.split(os.pathsep):
        runtime_env["PATH"] = f"{bin_dir}{os.pathsep}{existing_path}"
    runtime_env["RAYPATH"] = str(lib_dir)
    try:
        version_run = subprocess.run(
            [str(bin_dir / "rtrace"), "-version"],
            capture_output=True,
            text=True,
            env=runtime_env,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return RadianceRuntimeStatus(
            available=False,
            manifest_version=manifest_version,
            reason=f"RADIANCE_VERSION_CHECK_FAILED: {type(exc).__name__}: {exc}",
        )

    version_text = f"{version_run.stdout}\n{version_run.stderr}"
    version_match = re.search(r"\bRADIANCE\s+([0-9]+(?:\.[0-9]+)+)\b", version_text, flags=re.IGNORECASE)
    actual_version = version_match.group(1) if version_match else None
    if version_run.returncode != 0 or actual_version != manifest_version:
        observed = actual_version or "unrecognized version string"
        return RadianceRuntimeStatus(
            available=False,
            version=actual_version,
            manifest_version=manifest_version,
            reason=f"RADIANCE_VERSION_MISMATCH: manifest requires {manifest_version}; rtrace reported {observed}",
        )

    if not configure_radiance_runtime(runtime_dir):
        return RadianceRuntimeStatus(
            available=False,
            version=actual_version,
            manifest_version=manifest_version,
            reason="RADIANCE_RUNTIME_CONFIGURATION_FAILED: required runtime paths could not be configured",
        )
    return RadianceRuntimeStatus(
        available=True,
        version=actual_version,
        manifest_version=manifest_version,
    )


def is_radiance_available() -> bool:
    """Check if Radiance 6.0.2 runtime is operational."""
    return verify_radiance_runtime().available


def get_rotterdam_m4h_demo_location() -> SiteLocation:
    """Return Rotterdam M4H StudyArea v5 centroid coordinates for demonstration only.

    Tag: 位置示範，非分析結果 / DEMO_LOCATION_NOT_ANALYSIS_RESULT
    """
    try:
        from pyproj import Transformer

        # StudyArea v5 centroid in EPSG:28992
        cx, cy = 89170.4815569684, 435924.34854081983
        transformer = Transformer.from_crs("EPSG:28992", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(cx, cy)
    except Exception:
        # Fallback to verified centroid values
        lat, lon = 51.90792059236453, 4.430539900521947

    return SiteLocation(
        latitude=round(lat, 6),
        longitude=round(lon, 6),
        elevation=0.0,
        timezone="Europe/Amsterdam",
        location_tag="位置示範，非分析結果 (DEMO_LOCATION_NOT_ANALYSIS_RESULT)",
    )


def generate_sun_vectors(
    location: SiteLocation,
    period: AnalysisPeriod,
    true_north_offset_deg: float = 0.0,
) -> list[tuple[datetime, Vector3D, float, float]]:
    """Generate daytime sun vectors above the horizon for the specified period, timezone, and True North.

    Args:
        location: Geographic coordinates and timezone.
        period: Date range, daily hours, and sampling timestep.
        true_north_offset_deg: Grid convergence angle from Grid North to True North in degrees.
            Rotates sun vectors so that simulated sun positions align with the local projected CRS.

    Returns:
        List of tuples: (datetime_utc, vector_towards_sun, altitude_deg, azimuth_deg)
    """
    tz = zoneinfo.ZoneInfo(location.timezone)
    utc_tz = zoneinfo.ZoneInfo("UTC")

    # We evaluate solar position with Sunpath in UTC (time_zone=0.0)
    sp_utc = Sunpath.from_location(
        Location(
            city="AnalysisSite",
            country="AnalysisCountry",
            latitude=location.latitude,
            longitude=location.longitude,
            time_zone=0.0,
            elevation=location.elevation,
        )
    )

    results: list[tuple[datetime, Vector3D, float, float]] = []

    delta_day = timedelta(days=1)
    step_hours = 1.0 / period.timestep
    analysis_dates = period.dates
    if analysis_dates is None:
        analysis_dates = []
        curr_date = period.start_date
        while curr_date <= period.end_date:
            analysis_dates.append(curr_date)
            curr_date += delta_day

    # Pre-calculate True North rotation angle
    # When Grid North is rotated by gamma relative to True North,
    # azimuth relative to Grid North is azimuth_true - gamma.
    rot_rad = -math.radians(true_north_offset_deg)
    cos_rot = math.cos(rot_rad)
    sin_rot = math.sin(rot_rad)

    for curr_date in analysis_dates:
        # Step through daily analysis hours
        h = period.start_hour
        while h < period.end_hour - 1e-9:
            # Midpoint integration within each step
            sample_local_hour = h + 0.5 * step_hours
            if sample_local_hour >= period.end_hour:
                break

            hour_int = int(sample_local_hour)
            minute_float = (sample_local_hour - hour_int) * 60.0
            minute_int = int(minute_float)
            second_int = int(round((minute_float - minute_int) * 60.0))
            if second_int == 60:
                second_int = 0
                minute_int += 1
            if minute_int == 60:
                minute_int = 0
                hour_int += 1

            # Handle day rollover if sample hits exactly 24:00
            if hour_int >= 24:
                dt_target_date = curr_date + timedelta(days=hour_int // 24)
                hour_int %= 24
            else:
                dt_target_date = curr_date

            try:
                dt_local = datetime(
                    dt_target_date.year,
                    dt_target_date.month,
                    dt_target_date.day,
                    hour_int,
                    minute_int,
                    second_int,
                    tzinfo=tz,
                )
            except Exception:
                # Fallback for DST boundary edge case
                dt_local = datetime.combine(
                    dt_target_date, time(0, 0), tzinfo=tz
                ) + timedelta(seconds=int(sample_local_hour * 3600))

            dt_utc = dt_local.astimezone(utc_tz)
            utc_hour_decimal = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0

            sun = sp_utc.calculate_sun(
                month=dt_utc.month,
                day=dt_utc.day,
                hour=utc_hour_decimal,
                is_solar_time=False,
            )

            # Altitude > 0 means the sun is above the horizon
            if sun.altitude > 0.0:
                # sun.sun_vector points from sun to ground. We reverse it so it points towards the sky/sun.
                raw_vx = -sun.sun_vector.x
                raw_vy = -sun.sun_vector.y
                raw_vz = -sun.sun_vector.z

                # Apply True North rotation around Z-axis if specified
                if abs(true_north_offset_deg) > 1e-9:
                    adj_vx = raw_vx * cos_rot + raw_vy * sin_rot
                    adj_vy = raw_vy * cos_rot - raw_vx * sin_rot
                    adj_vz = raw_vz
                    adj_azimuth = (sun.azimuth - true_north_offset_deg) % 360.0
                else:
                    adj_vx, adj_vy, adj_vz = raw_vx, raw_vy, raw_vz
                    adj_azimuth = sun.azimuth

                vec_towards_sun = Vector3D(adj_vx, adj_vy, adj_vz).normalize()
                results.append((dt_utc, vec_towards_sun, sun.altitude, adj_azimuth))

            h += step_hours

    return results



def ray_box_intersection(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    box: tuple[float, float, float, float, float, float],
) -> bool:
    """Kay-Kajiya slab method for Ray-AABB intersection in pure Python.

    box: (min_x, min_y, min_z, max_x, max_y, max_z)
    Returns True if ray intersects box in positive t.
    """
    ox, oy, oz = origin
    dx, dy, dz = direction
    tmin = 1e-6
    tmax = 1e9

    for o, d, bmin, bmax in (
        (ox, dx, box[0], box[3]),
        (oy, dy, box[1], box[4]),
        (oz, dz, box[2], box[5]),
    ):
        if abs(d) < 1e-12:
            if o < bmin or o > bmax:
                return False
        else:
            inv_d = 1.0 / d
            t1 = (bmin - o) * inv_d
            t2 = (bmax - o) * inv_d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
            if tmin > tmax:
                return False

    return tmax > 1e-6


def check_point_inside_box(
    point: tuple[float, float, float],
    box: tuple[float, float, float, float, float, float],
    tolerance: float = 1e-5,
) -> bool:
    """Return True if point is strictly inside or on the boundary of an AABB."""
    px, py, pz = point
    return (
        (box[0] - tolerance) <= px <= (box[3] + tolerance)
        and (box[1] - tolerance) <= py <= (box[4] + tolerance)
        and (box[2] - tolerance) <= pz <= (box[5] + tolerance)
    )


def ray_triangle_intersection(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    v0: tuple[float, float, float],
    v1: tuple[float, float, float],
    v2: tuple[float, float, float],
) -> bool:
    """Möller–Trumbore ray-triangle intersection algorithm in pure Python."""
    ox, oy, oz = origin
    dx, dy, dz = direction
    e1x, e1y, e1z = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
    e2x, e2y, e2z = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]

    hx = dy * e2z - dz * e2y
    hy = dz * e2x - dx * e2z
    hz = dx * e2y - dy * e2x

    a = e1x * hx + e1y * hy + e1z * hz
    if abs(a) < 1e-12:
        return False
    f = 1.0 / a

    sx, sy, sz = ox - v0[0], oy - v0[1], oz - v0[2]
    u = f * (sx * hx + sy * hy + sz * hz)
    if u < -1e-6 or u > 1.0 + 1e-6:
        return False

    qx = sy * e1z - sz * e1y
    qy = sz * e1x - sx * e1z
    qz = sx * e1y - sy * e1x

    v = f * (dx * qx + dy * qy + dz * qz)
    if v < -1e-6 or (u + v) > 1.0 + 1e-6:
        return False

    t = f * (e2x * qx + e2y * qy + e2z * qz)
    return t > 1e-6


def ray_polygon_faces_intersection(
    origin: tuple[float, float, float],
    direction: tuple[float, float, float],
    faces: Sequence[Sequence[tuple[float, float, float]]],
) -> bool:
    """Test if a ray intersects any face of a 3D polygon obstacle."""
    for face in faces:
        n = len(face)
        if n < 3:
            continue
        v0 = face[0]
        for i in range(1, n - 1):
            if ray_triangle_intersection(origin, direction, v0, face[i], face[i + 1]):
                return True
    return False


def check_point_inside_polygon_obstacle(
    point: tuple[float, float, float],
    faces: Sequence[Sequence[tuple[float, float, float]]],
    tolerance: float = 1e-5,
) -> bool:
    """Check if a sensor point is inside a closed 3D prism obstacle."""
    if not faces:
        return False
    px, py, pz = point
    all_z = [pt[2] for face in faces for pt in face]
    min_z = min(all_z) - tolerance
    max_z = max(all_z) + tolerance
    if not (min_z <= pz <= max_z):
        return False

    try:
        ground_footprint = polygon_faces_to_footprint(faces)
    except ValueError:
        return False
    return ground_footprint.buffer(tolerance).covers(Point(px, py))


def box_to_face3d_list(box: tuple[float, float, float, float, float, float]) -> list[Face3D]:
    """Convert an AABB tuple into 5 Face3D polygons (South, North, West, East, Top) for Radiance."""
    x0, y0, z0, x1, y1, z1 = box
    return [
        # South face (y = y0)
        Face3D([Point3D(x0, y0, z0), Point3D(x1, y0, z0), Point3D(x1, y0, z1), Point3D(x0, y0, z1)]),
        # North face (y = y1)
        Face3D([Point3D(x1, y1, z0), Point3D(x0, y1, z0), Point3D(x0, y1, z1), Point3D(x1, y1, z1)]),
        # West face (x = x0)
        Face3D([Point3D(x0, y1, z0), Point3D(x0, y0, z0), Point3D(x0, y0, z1), Point3D(x0, y1, z1)]),
        # East face (x = x1)
        Face3D([Point3D(x1, y0, z0), Point3D(x1, y1, z0), Point3D(x1, y1, z1), Point3D(x1, y0, z1)]),
        # Top face (z = z1)
        Face3D([Point3D(x0, y0, z1), Point3D(x1, y0, z1), Point3D(x1, y1, z1), Point3D(x0, y1, z1)]),
    ]


def pure_python_box_ray_intersection(
    sensor_points: Sequence[SensorPoint],
    obstacles: Sequence[Obstacle],
    sun_vectors: Sequence[tuple[datetime, Vector3D, float, float]],
    timestep: int,
    *,
    vector_dates: Sequence[str] | None = None,
    daily_date_keys: Sequence[str] = (),
    daily_results_out: dict[str, list[PointSunlightResult]] | None = None,
) -> list[PointSunlightResult]:
    """Calculate sunlight hours using pure Python ray-obstacle intersection.

    Supports both BOX_AABB and POLYGONS obstacles.
    """
    results: list[PointSunlightResult] = []
    step_duration = 1.0 / timestep
    total_daytime = len(sun_vectors)
    date_keys = tuple(daily_date_keys or dict.fromkeys(vector_dates or ()))
    daily_sample_counts = {date_key: 0 for date_key in date_keys}
    for date_key in vector_dates or ():
        if date_key in daily_sample_counts:
            daily_sample_counts[date_key] += 1

    # Partition obstacles by kind
    boxes: list[tuple[float, float, float, float, float, float]] = []
    poly_obstacles: list[tuple[list[list[tuple[float, float, float]]], tuple[float, float, float, float, float, float]]] = []
    for obs in obstacles:
        if obs.kind == "BOX_AABB" and obs.bounds is not None:
            boxes.append(obs.bounds)
        elif obs.kind == "POLYGONS" and obs.faces:
            vertices = [point for face in obs.faces for point in face]
            if not vertices:
                continue
            bounds = (
                min(point[0] for point in vertices),
                min(point[1] for point in vertices),
                min(point[2] for point in vertices),
                max(point[0] for point in vertices),
                max(point[1] for point in vertices),
                max(point[2] for point in vertices),
            )
            poly_obstacles.append((obs.faces, bounds))

    for pt in sensor_points:
        if pt.status == "EXCLUDED_INSIDE_FOOTPRINT":
            results.append(
                PointSunlightResult(
                    point_id=pt.point_id,
                    coordinates=pt.coordinates,
                    status=pt.status,
                    sunlight_hours=0.0,
                    visible_samples=0,
                    total_daytime_samples=total_daytime,
                    direct_fraction=0.0,
                )
            )
            if daily_results_out is not None:
                for date_key in date_keys:
                    daily_results_out.setdefault(date_key, []).append(
                        PointSunlightResult(
                            point_id=pt.point_id,
                            coordinates=pt.coordinates,
                            status=pt.status,
                            sunlight_hours=0.0,
                            visible_samples=0,
                            total_daytime_samples=daily_sample_counts[date_key],
                            direct_fraction=0.0,
                        )
                    )
            continue

        # Check if VALID sensor point is inside any box obstacle
        for b in boxes:
            if check_point_inside_box(pt.coordinates, b):
                raise ValueError(
                    f"Sensor point {pt.point_id} at {pt.coordinates} is inside obstacle box {b}."
                )
        # Check if VALID sensor point is inside any polygon obstacle
        for faces, _bounds in poly_obstacles:
            if check_point_inside_polygon_obstacle(pt.coordinates, faces):
                raise ValueError(
                    f"Sensor point {pt.point_id} at {pt.coordinates} is inside polygon obstacle."
                )

        if pt.surface_offset <= 0.0:
            warnings.warn(
                f"Sensor point {pt.point_id} has surface_offset <= 0.0 ({pt.surface_offset}m); "
                "risk of coplanar self-occlusion.",
                UserWarning,
                stacklevel=2,
            )

        # Offset origin along surface normal
        ox = pt.coordinates[0] + pt.normal[0] * pt.surface_offset
        oy = pt.coordinates[1] + pt.normal[1] * pt.surface_offset
        oz = pt.coordinates[2] + pt.normal[2] * pt.surface_offset
        origin = (ox, oy, oz)

        visible_count = 0
        daily_visible_counts = {date_key: 0 for date_key in date_keys}
        for vector_index, (_, v, _, _) in enumerate(sun_vectors):
            # Check dot product with surface normal
            dot = pt.normal[0] * v.x + pt.normal[1] * v.y + pt.normal[2] * v.z
            if dot <= 0.0:
                # Sun is behind the surface plane
                continue

            direction = (v.x, v.y, v.z)
            blocked = False
            for b in boxes:
                if ray_box_intersection(origin, direction, b):
                    blocked = True
                    break

            if not blocked:
                for faces, bounds in poly_obstacles:
                    if ray_box_intersection(origin, direction, bounds) and ray_polygon_faces_intersection(origin, direction, faces):
                        blocked = True
                        break

            if not blocked:
                visible_count += 1
                if vector_dates is not None and vector_index < len(vector_dates):
                    date_key = vector_dates[vector_index]
                    if date_key in daily_visible_counts:
                        daily_visible_counts[date_key] += 1

        hours = visible_count * step_duration
        fraction = (visible_count / total_daytime) if total_daytime > 0 else 0.0

        results.append(
            PointSunlightResult(
                point_id=pt.point_id,
                coordinates=pt.coordinates,
                status=pt.status,
                sunlight_hours=round(hours, 4),
                visible_samples=visible_count,
                total_daytime_samples=total_daytime,
                direct_fraction=round(fraction, 4),
            )
        )
        if daily_results_out is not None:
            for date_key in date_keys:
                daily_visible = daily_visible_counts[date_key]
                daily_total = daily_sample_counts[date_key]
                daily_results_out.setdefault(date_key, []).append(
                    PointSunlightResult(
                        point_id=pt.point_id,
                        coordinates=pt.coordinates,
                        status=pt.status,
                        sunlight_hours=round(daily_visible * step_duration, 4),
                        visible_samples=daily_visible,
                        total_daytime_samples=daily_total,
                        direct_fraction=round(daily_visible / daily_total, 4) if daily_total > 0 else 0.0,
                    )
                )

    return results


def calculate_direct_sunlight_hours(
    location: SiteLocation,
    period: AnalysisPeriod,
    sensor_points: Sequence[SensorPoint],
    obstacles: Sequence[Obstacle] = (),
    method: str = "ladybug_radiance",
    true_north_offset_deg: float = 0.0,
) -> SunlightSimulationResult:
    """Calculate direct sunlight hours for sensor points across an analysis period.

    Methods:
    - 'ladybug_radiance': calls Radiance via ladybug_radiance intersection_matrix
    - 'pure_python_box_ray': independent Python reference implementation
    """
    if method not in ("ladybug_radiance", "pure_python_box_ray"):
        raise ValueError(f"Unsupported calculation method: {method}")

    analysis_dates = period.dates
    if analysis_dates is None:
        analysis_dates = []
        current_date = period.start_date
        while current_date <= period.end_date:
            analysis_dates.append(current_date)
            current_date += timedelta(days=1)
    daily_date_keys = [item.isoformat() for item in analysis_dates]

    # Generate daytime sun vectors (adjusted for True North convergence if specified)
    sun_data = generate_sun_vectors(
        location=location,
        period=period,
        true_north_offset_deg=true_north_offset_deg,
    )
    total_daytime_samples = len(sun_data)
    daytime_hours = total_daytime_samples * (1.0 / period.timestep)
    local_zone = zoneinfo.ZoneInfo(location.timezone)
    vector_dates = [timestamp.astimezone(local_zone).date().isoformat() for timestamp, *_ in sun_data]
    daily_sample_counts = {date_key: 0 for date_key in daily_date_keys}
    for date_key in vector_dates:
        if date_key in daily_sample_counts:
            daily_sample_counts[date_key] += 1

    # Check for empty daytime vectors (e.g. nighttime period)
    if total_daytime_samples == 0:
        point_results = [
            PointSunlightResult(
                point_id=pt.point_id,
                coordinates=pt.coordinates,
                status=pt.status,
                sunlight_hours=0.0,
                visible_samples=0,
                total_daytime_samples=0,
                direct_fraction=0.0,
            )
            for pt in sensor_points
        ]
        daily_results = {
            date_key: [
                PointSunlightResult(
                    point_id=pt.point_id,
                    coordinates=pt.coordinates,
                    status=pt.status,
                    sunlight_hours=0.0,
                    visible_samples=0,
                    total_daytime_samples=0,
                    direct_fraction=0.0,
                )
                for pt in sensor_points
            ]
            for date_key in daily_date_keys
        }
        return SunlightSimulationResult(
            results=point_results,
            daily_results=daily_results,
            total_sun_vectors=0,
            daytime_hours=0.0,
            period=period,
            location=location,
            method=method,  # type: ignore[arg-type]
            engine=(
                "ladybug-sunpath+python-raycast"
                if method == "pure_python_box_ray"
                else "ladybug-sunpath+ladybug-radiance"
            ),
            fixture_tag="FIXTURE_ONLY",
            metadata={
                "note": "No sun above horizon during analysis period",
                "true_north_offset_deg": true_north_offset_deg,
            },
        )

    # Guard against sensor points inside obstacles (only check VALID points)
    boxes = [obs.bounds for obs in obstacles if obs.kind == "BOX_AABB" and obs.bounds is not None]
    poly_faces = [obs.faces for obs in obstacles if obs.kind == "POLYGONS" and obs.faces]

    for pt in sensor_points:
        if pt.status == "EXCLUDED_INSIDE_FOOTPRINT":
            continue
        for b in boxes:
            if check_point_inside_box(pt.coordinates, b):
                raise ValueError(
                    f"Sensor point {pt.point_id} at {pt.coordinates} is inside obstacle {b}."
                )
        for faces in poly_faces:
            if check_point_inside_polygon_obstacle(pt.coordinates, faces):
                raise ValueError(
                    f"Sensor point {pt.point_id} at {pt.coordinates} is inside polygon obstacle."
                )
        if pt.surface_offset <= 0.0:
            warnings.warn(
                f"Sensor point {pt.point_id} surface_offset is {pt.surface_offset} <= 0; "
                "self-occlusion warning.",
                UserWarning,
                stacklevel=2,
            )

    if method == "pure_python_box_ray":
        daily_results: dict[str, list[PointSunlightResult]] = {}
        results = pure_python_box_ray_intersection(
            sensor_points=sensor_points,
            obstacles=obstacles,
            sun_vectors=sun_data,
            timestep=period.timestep,
            vector_dates=vector_dates,
            daily_date_keys=daily_date_keys,
            daily_results_out=daily_results,
        )
    else:
        # Primary method: ladybug_radiance
        runtime_status = verify_radiance_runtime()
        if not runtime_status.available:
            raise RadianceExecutionError(
                f"RADIANCE_RUNTIME_VERIFICATION_FAILED: {runtime_status.reason or 'runtime unavailable'}"
            )

        valid_indices = [i for i, pt in enumerate(sensor_points) if pt.status != "EXCLUDED_INSIDE_FOOTPRINT"]
        valid_points = [sensor_points[i] for i in valid_indices]
        daily_results = {date_key: [] for date_key in daily_date_keys}

        if not valid_points:
            results = []
            for pt in sensor_points:
                results.append(
                    PointSunlightResult(
                        point_id=pt.point_id,
                        coordinates=pt.coordinates,
                        status=pt.status,
                        sunlight_hours=0.0,
                        visible_samples=0,
                        total_daytime_samples=total_daytime_samples,
                        direct_fraction=0.0,
                    )
                )
                for date_key in daily_date_keys:
                    daily_results[date_key].append(
                        PointSunlightResult(
                            point_id=pt.point_id,
                            coordinates=pt.coordinates,
                            status=pt.status,
                            sunlight_hours=0.0,
                            visible_samples=0,
                            total_daytime_samples=daily_sample_counts[date_key],
                            direct_fraction=0.0,
                        )
                    )
        else:
            context_faces: list[Face3D] = []
            for obs in obstacles:
                if obs.kind == "BOX_AABB" and obs.bounds is not None:
                    context_faces.extend(box_to_face3d_list(obs.bounds))
                elif obs.kind == "POLYGONS" and obs.faces:
                    for face_pts in obs.faces:
                        context_faces.append(Face3D([Point3D(*p) for p in face_pts]))

            offsets = [pt.surface_offset for pt in valid_points if pt.surface_offset > 0.0]
            chosen_offset = min(offsets) if offsets else 0.05

            lb_vectors = [v for _, v, _, _ in sun_data]
            matrix = []
            for batch_start in range(0, len(valid_points), RADIANCE_SENSOR_BATCH_SIZE):
                point_batch = valid_points[batch_start:batch_start + RADIANCE_SENSOR_BATCH_SIZE]
                try:
                    batch_matrix = rad_intersection.intersection_matrix(
                        vectors=lb_vectors,
                        points=[Point3D(*pt.coordinates) for pt in point_batch],
                        normals=[Vector3D(*pt.normal).normalize() for pt in point_batch],
                        context_geometry=context_faces,
                        offset_distance=chosen_offset,
                        numericalize=False,
                        sim_folder=_radiance_sim_folder(),
                    )
                except Exception as exc:
                    raise RadianceExecutionError(
                        f"RADIANCE_INTERSECTION_FAILED: {type(exc).__name__}: {exc}"
                    ) from exc
                matrix.extend(batch_matrix)

            results = []
            step_duration = 1.0 / period.timestep
            valid_cursor = 0
            for pt in sensor_points:
                if pt.status == "EXCLUDED_INSIDE_FOOTPRINT":
                    results.append(
                        PointSunlightResult(
                            point_id=pt.point_id,
                            coordinates=pt.coordinates,
                            status=pt.status,
                            sunlight_hours=0.0,
                            visible_samples=0,
                            total_daytime_samples=total_daytime_samples,
                            direct_fraction=0.0,
                        )
                    )
                    for date_key in daily_date_keys:
                        daily_results[date_key].append(
                            PointSunlightResult(
                                point_id=pt.point_id,
                                coordinates=pt.coordinates,
                                status=pt.status,
                                sunlight_hours=0.0,
                                visible_samples=0,
                                total_daytime_samples=daily_sample_counts[date_key],
                                direct_fraction=0.0,
                            )
                        )
                else:
                    row = matrix[valid_cursor]
                    valid_cursor += 1
                    visible_count = sum(1 for val in row if bool(val))
                    hours = visible_count * step_duration
                    fraction = (visible_count / total_daytime_samples) if total_daytime_samples > 0 else 0.0
                    results.append(
                        PointSunlightResult(
                            point_id=pt.point_id,
                            coordinates=pt.coordinates,
                            status=pt.status,
                            sunlight_hours=round(hours, 4),
                            visible_samples=visible_count,
                            total_daytime_samples=total_daytime_samples,
                            direct_fraction=round(fraction, 4),
                        )
                    )
                    visible_by_date = {date_key: 0 for date_key in daily_date_keys}
                    for vector_index, value in enumerate(row):
                        if bool(value) and vector_index < len(vector_dates):
                            date_key = vector_dates[vector_index]
                            if date_key in visible_by_date:
                                visible_by_date[date_key] += 1
                    for date_key in daily_date_keys:
                        daily_visible = visible_by_date[date_key]
                        daily_total = daily_sample_counts[date_key]
                        daily_results[date_key].append(
                            PointSunlightResult(
                                point_id=pt.point_id,
                                coordinates=pt.coordinates,
                                status=pt.status,
                                sunlight_hours=round(daily_visible * step_duration, 4),
                                visible_samples=daily_visible,
                                total_daytime_samples=daily_total,
                                direct_fraction=round(daily_visible / daily_total, 4) if daily_total > 0 else 0.0,
                            )
                        )

    return SunlightSimulationResult(
        results=results,
        daily_results=daily_results,
        total_sun_vectors=total_daytime_samples,
        daytime_hours=round(daytime_hours, 4),
        period=period,
        location=location,
        method=method,  # type: ignore[arg-type]
        engine=(
            "ladybug-sunpath+python-raycast"
            if method == "pure_python_box_ray"
            else "ladybug-sunpath+ladybug-radiance"
        ),
        fixture_tag="FIXTURE_ONLY",
        metadata={
            "sensor_count": len(sensor_points),
            "obstacle_count": len(obstacles),
            "timestep": period.timestep,
            "true_north_offset_deg": true_north_offset_deg,
            "radiance_sensor_batch_size": RADIANCE_SENSOR_BATCH_SIZE if method == "ladybug_radiance" else None,
            "radiance_sensor_batch_count": (
                math.ceil(sum(pt.status != "EXCLUDED_INSIDE_FOOTPRINT" for pt in sensor_points) / RADIANCE_SENSOR_BATCH_SIZE)
                if method == "ladybug_radiance"
                else None
            ),
        },
    )


def create_sunlight_colormap_spec(
    max_hours: float = 10.0,
    num_bins: int = 5,
) -> ColormapSpec:
    """Create a uniform colormap specification for baseline and modified sunlight visualization.

    Ensures that baseline and modified runs share identical bounds and bins for direct comparison.
    Palette spans from deep shadow (#0d1b2a) to peak direct sunlight (#e76f51).
    """
    if max_hours <= 0.0:
        max_hours = 1.0

    step = max_hours / num_bins
    colors = [
        "#0d1b2a",  # 0: Deep Shadow
        "#1b4965",  # 1: Deep Blue / Low Sun
        "#5fa8d3",  # 2: Sky Blue / Moderate Sun
        "#f4a261",  # 3: Warm Amber / High Sun
        "#e76f51",  # 4: Radiant Gold / Peak Sun
    ]

    bins: list[ColormapBin] = []
    for i in range(num_bins):
        low = round(i * step, 2)
        high = round((i + 1) * step, 2)
        color = colors[i % len(colors)]
        label = f"{low:.1f} - {high:.1f} h" if i < num_bins - 1 else f"{low:.1f}+ h"
        bins.append(ColormapBin(min_hours=low, max_hours=high, color_hex=color, label=label))

    return ColormapSpec(
        min_value=0.0,
        max_value=round(max_hours, 2),
        unit="hours",
        bins=bins,
        palette_name="sunlight_amber_indigo",
    )
