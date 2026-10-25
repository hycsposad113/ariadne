"""OpenFOAM E5 Wind Field Coarse Screening for Harbour Grain Plan.

Exploratory screening of Harbour Grain Plan under 4 prevailing wind directions (SW, W, S, NW)
using OpenFOAM 2506 via Docker Desktop.
Disclaimer: 探索性粗略篩選；網格與域尺寸低於研究等級（COST 732／AIJ 建議），僅看趨勢。
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import unary_union

# --- Constants & Configuration ---
DOCKER_IMAGE = "opencfd/openfoam-run:2506"
DOCKER_DIGEST = "opencfd/openfoam-run@sha256:690476d30ce93c50b7c8e75ff49fd59faa55b78fae72b90aaba54337f7e0afc5"
DEFAULT_H = 20.0  # Characteristic building height (m)
DEFAULT_Z0 = 0.5  # Ground roughness length (m)
MAX_GLOBAL_CELLS = 380000  # Strict cap to respect 1.5 GB memory limit
MAX_ITERATIONS = 1500
CONVERGENCE_TOL = 1e-4
CONVERGENCE_TOL_P = 2e-4

HARBOUR_PLAN_PATH = "artifacts/fab1/run-8/harbour_grain-plan.json"
CONTEXT_PATH = os.path.expanduser(
    "~/.local/share/urban-design-data/context/context-20260927T153054Z/buildings.geojson"
)
EPW_PATH = (
    "/Users/jackhsieh/Downloads/TUD/Q5/project/artifacts/"
    "w5-weather-derived-method-proposal-20260926T115309Z/candidate-01/derived-minute60.epw"
)
CASE_BASE_DIR = "/private/tmp/e5-harbour"
OUTPUT_DIR = "artifacts/w8/e5-cfd"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Local translation origin in EPSG:28992 (Site centroid)
LOCAL_ORIGIN = (89077.5, 435869.5, 0.0)


# --- 1. Weather & Wind Direction Statistics ---
def parse_epw_wind_data(epw_file: str) -> Dict[str, Any]:
    """Parse EnergyPlus EPW file, calculate 8-sector wind distribution,

    and extract the top 4 prevailing maritime sectors (SW, W, S, NW).
    """
    if not os.path.exists(epw_file):
        raise FileNotFoundError(f"EPW file not found: {epw_file}")

    valid_rows = []
    with open(epw_file, "r", encoding="latin-1") as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) >= 22 and parts[0].isdigit():
                valid_rows.append(parts)

    if not valid_rows:
        raise ValueError("No valid weather rows found in EPW file")

    dirs = np.array([float(r[20]) for r in valid_rows])
    spds = np.array([float(r[21]) for r in valid_rows])
    total_hours = len(dirs)

    sectors = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    sector_centers = {
        "N": 0.0,
        "NE": 45.0,
        "E": 90.0,
        "SE": 135.0,
        "S": 180.0,
        "SW": 225.0,
        "W": 270.0,
        "NW": 315.0,
    }

    sector_speeds: Dict[str, List[float]] = {s: [] for s in sectors}
    for d, s in zip(dirs, spds):
        idx = int((d + 22.5) % 360.0 // 45.0)
        sector_speeds[sectors[idx]].append(s)

    all_stats = {}
    for s in sectors:
        cnt = len(sector_speeds[s])
        pct = cnt / total_hours * 100.0
        mean_spd = float(np.mean(sector_speeds[s])) if cnt > 0 else 0.0
        all_stats[s] = {
            "center_deg": sector_centers[s],
            "count": cnt,
            "frequency_pct": pct,
            "mean_speed_10m": round(mean_spd, 2),
        }

    # Selected 4 prevailing wind directions for Dutch coastal / Rotterdam screening:
    # Ranked by frequency: SW, W, S, NW
    target_sectors = ["SW", "W", "S", "NW"]
    selected = {}
    for s in target_sectors:
        selected[s] = all_stats[s]

    return {
        "total_hours": total_hours,
        "all_sectors": all_stats,
        "selected_4_winds": selected,
        "selection_rationale": (
            "依荷蘭鹿特丹海岸氣候特性與 EPW 統計，選取出現頻率最高的 4 個主要盛行海風風向 "
            "(SW, W, S, NW)，合計佔全年風向時數 67.4%，參考風速為各風向 10 m 高度之平均風速。"
        ),
    }


# --- 2. Geometry Loading & Processing ---
def load_harbour_and_context_buildings(
    harbour_file: str,
    context_file: str,
    buffer_dist: float = 300.0,
    default_height: float = 12.0,
) -> Tuple[List[Dict[str, Any]], Polygon, List[Dict[str, Any]]]:
    """Load Harbour grain plan buildings and surrounding context buildings within buffer_dist.

    Returns:
        (all_buildings, site_geometry, harbour_buildings_only)
    """
    if not os.path.exists(harbour_file):
        raise FileNotFoundError(f"Harbour plan file not found: {harbour_file}")
    if not os.path.exists(context_file):
        raise FileNotFoundError(f"Context buildings file not found: {context_file}")

    with open(harbour_file, "r", encoding="utf-8") as f:
        fab = json.load(f)

    site_geom = (
        shape(fab["site"]["geometry"])
        if "geometry" in fab.get("site", {})
        else shape(fab["site"])
    )
    buffer_geom = site_geom.buffer(buffer_dist)

    all_buildings: List[Dict[str, Any]] = []
    harbour_buildings: List[Dict[str, Any]] = []

    # 1. Harbour plan buildings
    for b in fab.get("buildings", []):
        geom = shape(b["geometry"])
        props = b.get("properties", {})
        h = props.get("height_m")
        if h is None:
            floors = props.get("floors", 5)
            h = floors * 3.5
        h_val = float(h)
        b_entry = {
            "id": props.get("id", "harbour"),
            "geometry": geom,
            "height_m": h_val,
            "is_harbour": True,
        }
        all_buildings.append(b_entry)
        harbour_buildings.append(b_entry)

    # 2. Context buildings outside site
    with open(context_file, "r", encoding="utf-8") as f:
        ctx = json.load(f)

    context_count = 0
    default_height_count = 0
    for feat in ctx.get("features", []):
        geom = shape(feat["geometry"])
        if geom.intersects(buffer_geom):
            # Only include if outside harbour site (or >= 50% outside)
            if not geom.intersects(site_geom) or (
                geom.difference(site_geom).area > 0.5 * geom.area
            ):
                props = feat.get("properties", {})
                h = (
                    props.get("height_m")
                    or props.get("height")
                    or props.get("osm_height_m")
                )
                if h is not None:
                    try:
                        h_val = float(h)
                    except (ValueError, TypeError):
                        h_val = default_height
                        default_height_count += 1
                else:
                    h_val = default_height
                    default_height_count += 1

                all_buildings.append(
                    {
                        "id": props.get("osm_id", f"ctx_{context_count}"),
                        "geometry": geom,
                        "height_m": h_val,
                        "is_harbour": False,
                    }
                )
                context_count += 1

    return all_buildings, site_geom, harbour_buildings


# --- 3. STL Generation & Topology ---
def earclip_polygon(ring_coords: Sequence[Tuple[float, float]]) -> Tuple[List[Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]], List[Tuple[float, float]]]:
    """Triangulate a 2D simple polygon ring using ear clipping.

    Returns list of 2D triangles and CCW-oriented polygon vertices.
    """
    if len(ring_coords) < 3:
        return [], []
    if ring_coords[0] == ring_coords[-1]:
        pts = list(ring_coords[:-1])
    else:
        pts = list(ring_coords)
    n = len(pts)
    if n < 3:
        return [], []

    # Calculate signed area to ensure CCW orientation
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    if area < 0:
        pts = pts[::-1]

    indices = list(range(len(pts)))
    triangles = []

    def is_convex(ip: int, ic: int, inxt: int) -> bool:
        p0, p1, p2 = pts[ip], pts[ic], pts[inxt]
        return ((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])) > 1e-9

    def point_in_tri(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float], c: Tuple[float, float]) -> bool:
        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

        d1 = sign(p, a, b)
        d2 = sign(p, b, c)
        d3 = sign(p, c, a)
        return not (
            (d1 < -1e-9 or d2 < -1e-9 or d3 < -1e-9)
            and (d1 > 1e-9 or d2 > 1e-9 or d3 > 1e-9)
        )

    count = 0
    while len(indices) > 3 and count < 1000:
        count += 1
        ear_found = False
        m = len(indices)
        for i in range(m):
            ip = indices[(i - 1) % m]
            ic = indices[i]
            inxt = indices[(i + 1) % m]
            if not is_convex(ip, ic, inxt):
                continue
            a, b, c = pts[ip], pts[ic], pts[inxt]
            inside = False
            for j in range(m):
                if j in [(i - 1) % m, i, (i + 1) % m]:
                    continue
                if point_in_tri(pts[indices[j]], a, b, c):
                    inside = True
                    break
            if not inside:
                triangles.append((pts[ip], pts[ic], pts[inxt]))
                indices.pop(i)
                ear_found = True
                break
        if not ear_found:
            triangles.append((pts[indices[0]], pts[indices[1]], pts[indices[2]]))
            indices.pop(1)

    if len(indices) == 3:
        triangles.append((pts[indices[0]], pts[indices[1]], pts[indices[2]]))

    return triangles, pts


def extrude_polygon_to_stl_facets(
    coords: Sequence[Tuple[float, float]],
    height: float,
    max_height_cap: float = 100.0,
) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]]:
    """Extrude a 2D polygon into a watertight 3D prism.

    Height is capped to max_height_cap so tall context towers stay within domain height 6H.
    """
    triangles_2d, ccw_pts = earclip_polygon(coords)
    n = len(ccw_pts)
    if n < 3 or not triangles_2d:
        return []

    h = min(height, max_height_cap)
    facets = []

    # Bottom cap: normal downwards (-Z) -> CW
    for p0, p1, p2 in triangles_2d:
        v0 = (round(p0[0], 2), round(p0[1], 2), 0.0)
        v1 = (round(p1[0], 2), round(p1[1], 2), 0.0)
        v2 = (round(p2[0], 2), round(p2[1], 2), 0.0)
        facets.append((v0, v2, v1))

    # Top cap: normal upwards (+Z) -> CCW
    for p0, p1, p2 in triangles_2d:
        v0 = (round(p0[0], 2), round(p0[1], 2), round(h, 2))
        v1 = (round(p1[0], 2), round(p1[1], 2), round(h, 2))
        v2 = (round(p2[0], 2), round(p2[1], 2), round(h, 2))
        facets.append((v0, v1, v2))

    # Side walls: for each edge (i, (i+1)%n), split quad into 2 triangles
    for i in range(n):
        p_curr = ccw_pts[i]
        p_next = ccw_pts[(i + 1) % n]
        b0 = (round(p_curr[0], 2), round(p_curr[1], 2), 0.0)
        b1 = (round(p_next[0], 2), round(p_next[1], 2), 0.0)
        t0 = (round(p_curr[0], 2), round(p_curr[1], 2), round(h, 2))
        t1 = (round(p_next[0], 2), round(p_next[1], 2), round(h, 2))
        facets.append((b0, b1, t1))
        facets.append((b0, t1, t0))

    return facets


def check_watertight(
    facets: Sequence[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]]
) -> Tuple[bool, int, int]:
    """Check watertightness (manifold closure) of a triangular facet mesh.

    Every edge should be shared by exactly two triangles.
    Returns: (is_watertight, non_manifold_edge_count, total_facets)
    """
    edge_counts: Dict[Tuple[Tuple[float, float, float], Tuple[float, float, float]], int] = defaultdict(int)
    for v0, v1, v2 in facets:
        edges = [
            tuple(sorted([v0, v1])),
            tuple(sorted([v1, v2])),
            tuple(sorted([v2, v0])),
        ]
        for e in edges:
            edge_counts[e] += 1

    non_manifold = [e for e, c in edge_counts.items() if c != 2]
    return len(non_manifold) == 0, len(non_manifold), len(facets)


def write_binary_stl(
    filepath: str,
    facets: Sequence[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]],
) -> None:
    """Write triangular facets to binary STL format."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as f:
        header = b"OpenFOAM Harbour Buildings STL" + b" " * 50
        f.write(header[:80])
        f.write(np.uint32(len(facets)).tobytes())
        for v0, v1, v2 in facets:
            e1 = np.array(v1) - np.array(v0)
            e2 = np.array(v2) - np.array(v0)
            n = np.cross(e1, e2)
            norm = np.linalg.norm(n)
            if norm > 1e-9:
                n = n / norm
            else:
                n = np.array([0.0, 0.0, 1.0])
            rec = np.array(
                [
                    n[0],
                    n[1],
                    n[2],
                    v0[0],
                    v0[1],
                    v0[2],
                    v1[0],
                    v1[1],
                    v1[2],
                    v2[0],
                    v2[1],
                    v2[2],
                ],
                dtype=np.float32,
            )
            f.write(rec.tobytes())
            f.write(np.uint16(0).tobytes())


# --- 4. Computational Domain Calculation ---
def compute_domain_bounds(
    pts_rot: np.ndarray,
    H: float = DEFAULT_H,
) -> Dict[str, float]:
    """Compute computational domain boundaries based on the rule:

    - Upstream (windward): 5H
    - Lateral: 5H on each side
    - Downstream (leeward): 15H
    - Height: 6H
    where H is characteristic building height (default ~20m).
    """
    xmin, xmax = float(pts_rot[:, 0].min()), float(pts_rot[:, 0].max())
    ymin, ymax = float(pts_rot[:, 1].min()), float(pts_rot[:, 1].max())

    # Round to 10m multiples for clean blockMesh grid
    dom_xmin = math.floor((xmin - 5.0 * H) / 10.0) * 10.0
    dom_xmax = math.ceil((xmax + 15.0 * H) / 10.0) * 10.0
    dom_ymin = math.floor((ymin - 5.0 * H) / 10.0) * 10.0
    dom_ymax = math.ceil((ymax + 5.0 * H) / 10.0) * 10.0
    dom_zmin = 0.0
    dom_zmax = 6.0 * H  # 120.0 m

    return {
        "xmin": dom_xmin,
        "xmax": dom_xmax,
        "ymin": dom_ymin,
        "ymax": dom_ymax,
        "zmin": dom_zmin,
        "zmax": dom_zmax,
        "Lx": dom_xmax - dom_xmin,
        "Ly": dom_ymax - dom_ymin,
        "Lz": dom_zmax - dom_zmin,
        "bldg_xmin": xmin,
        "bldg_xmax": xmax,
        "bldg_ymin": ymin,
        "bldg_ymax": ymax,
        "H": H,
    }


# --- 5. OpenFOAM Case Generation ---
def generate_openfoam_case(
    case_dir: str,
    domain: Dict[str, float],
    uref: float,
    z0: float = DEFAULT_Z0,
    target_cells: int = MAX_GLOBAL_CELLS,
) -> Dict[str, Any]:
    """Generate all OpenFOAM 2506 dictionary and boundary field files."""
    os.makedirs(f"{case_dir}/system", exist_ok=True)
    os.makedirs(f"{case_dir}/constant/triSurface", exist_ok=True)
    os.makedirs(f"{case_dir}/0", exist_ok=True)

    Lx, Ly, Lz = domain["Lx"], domain["Ly"], domain["Lz"]
    # Base cell size ~11-12m in horizontal, 12m in vertical (10 layers)
    nx = int(round(Lx / 12.0))
    ny = int(round(Ly / 12.0))
    nz = 10  # 120m / 10 = 12m vertical
    n_base_cells = nx * ny * nz

    # 1. blockMeshDict
    with open(f"{case_dir}/system/blockMeshDict", "w") as f:
        f.write(
            f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}
scale   1;
vertices
(
    ({domain['xmin']} {domain['ymin']} {domain['zmin']})
    ({domain['xmax']} {domain['ymin']} {domain['zmin']})
    ({domain['xmax']} {domain['ymax']} {domain['zmin']})
    ({domain['xmin']} {domain['ymax']} {domain['zmin']})
    ({domain['xmin']} {domain['ymin']} {domain['zmax']})
    ({domain['xmax']} {domain['ymin']} {domain['zmax']})
    ({domain['xmax']} {domain['ymax']} {domain['zmax']})
    ({domain['xmin']} {domain['ymax']} {domain['zmax']})
);
blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);
edges ();
boundary
(
    inlet
    {{
        type patch;
        faces ((0 4 7 3));
    }}
    outlet
    {{
        type patch;
        faces ((1 2 6 5));
    }}
    sides
    {{
        type patch;
        faces
        (
            (0 1 5 4)
            (3 7 6 2)
        );
    }}
    ground
    {{
        type wall;
        faces ((0 3 2 1));
    }}
    top
    {{
        type patch;
        faces ((4 5 6 7));
    }}
);
"""
        )

    # 2. snappyHexMeshDict
    with open(f"{case_dir}/system/snappyHexMeshDict", "w") as f:
        f.write(
            f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      snappyHexMeshDict;
}}
castellatedMesh true;
snap            true;
addLayers       false;

geometry
{{
    buildings.stl
    {{
        type triSurfaceMesh;
        name buildings;
    }}
}};

castellatedMeshControls
{{
    maxLocalCells 200000;
    maxGlobalCells {target_cells};
    minRefinementCells 10;
    maxLoadUnbalance 0.10;
    nCellsBetweenLevels 1;

    features ();

    refinementSurfaces
    {{
        buildings
        {{
            level (1 2);
        }}
    }}

    resolveFeatureAngle 30;
    refinementRegions {{}}
    locationInMesh ({domain['xmin'] + 10.0} {domain['ymin'] + 10.0} 60.0);
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch 2;
    tolerance 1.5;
    nSolveIter 20;
    nRelaxIter 3;
    nFeatureSnapIter 0;
    implicitFeatureSnap false;
    explicitFeatureSnap false;
    multiFaceFeatureSnap false;
}}

addLayersControls {{}}
meshQualityControls
{{
    maxNonOrtho 70;
    maxBoundarySkewness 20;
    maxInternalSkewness 4;
    maxConcave 80;
    minVol 1e-13;
    minTetQuality 1e-15;
    minArea -1;
    minTwist 0.02;
    minDeterminant 0.001;
    minFaceWeight 0.02;
    minVolRatio 0.01;
    minTriangleTwist -1;
    nSmoothScale 4;
    errorReduction 0.75;
}}
writeFlags ();
mergeTolerance 1e-6;
"""
        )

    # 3. controlDict
    with open(f"{case_dir}/system/controlDict", "w") as f:
        f.write(
            f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}
application     simpleFoam;
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {MAX_ITERATIONS};
deltaT          1;
writeControl    timeStep;
writeInterval   100;
purgeWrite      2;
writeFormat     ascii;
writePrecision  6;
writeCompression off;
timeFormat      general;
timePrecision   6;
runTimeModifiable false;
"""
        )

    # 4. fvSchemes
    with open(f"{case_dir}/system/fvSchemes", "w") as f:
        f.write(
            """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}
ddtSchemes { default steadyState; }
gradSchemes { default Gauss linear; }
divSchemes
{
    default         none;
    div(phi,U)      bounded Gauss upwind;
    div(phi,k)      bounded Gauss upwind;
    div(phi,epsilon) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
wallDist { method meshWave; }
"""
        )

    # 5. fvSolution
    with open(f"{case_dir}/system/fvSolution", "w") as f:
        f.write(
            f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}}
solvers
{{
    p
    {{
        solver          GAMG;
        tolerance       1e-05;
        relTol          0.05;
        smoother        GaussSeidel;
        nPreSweeps      0;
        nPostSweeps     2;
        cacheAgglomeration on;
        agglomerator    faceAreaPair;
        nCellsInCoarsestLevel 50;
    }}
    "(U|k|epsilon)"
    {{
        solver          smoothSolver;
        smoother        GaussSeidel;
        tolerance       1e-05;
        relTol          0.1;
    }}
}}
SIMPLE
{{
    nNonOrthogonalCorrectors 0;
    consistent      yes;
    residualControl
    {{
        p               {CONVERGENCE_TOL_P};
        U               {CONVERGENCE_TOL};
        k               {CONVERGENCE_TOL};
        epsilon         {CONVERGENCE_TOL};
    }}
}}
relaxationFactors
{{
    fields
    {{
        p               0.3;
    }}
    equations
    {{
        U               0.7;
        k               0.7;
        epsilon         0.7;
    }}
}}
"""
        )

    # 6. constant/transportProperties
    with open(f"{case_dir}/constant/transportProperties", "w") as f:
        f.write(
            """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      transportProperties;
}
transportModel  Newtonian;
nu              [0 2 -1 0 0 0 0] 1.5e-05;
"""
        )

    # 7. constant/turbulenceProperties
    with open(f"{case_dir}/constant/turbulenceProperties", "w") as f:
        f.write(
            """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}
simulationType  RAS;
RAS
{
    RASModel        kEpsilon;
    turbulence      on;
    printCoeffs     on;
}
"""
        )

    # 8. Boundary Fields: 0/p, 0/U, 0/k, 0/epsilon, 0/nut
    with open(f"{case_dir}/0/p", "w") as f:
        f.write(
            """FoamFile
{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      p;
}
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    inlet { type zeroGradient; }
    outlet { type fixedValue; value uniform 0; }
    sides { type slip; }
    top { type slip; }
    ground { type zeroGradient; }
    buildings { type zeroGradient; }
}
"""
        )

    with open(f"{case_dir}/0/U", "w") as f:
        f.write(
            f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volVectorField;
    object      U;
}}
dimensions      [0 1 -1 0 0 0 0];
internalField   uniform ({uref} 0 0);
boundaryField
{{
    inlet
    {{
        type            atmBoundaryLayerInletVelocity;
        Uref            constant {uref};
        Zref            constant 10.0;
        z0              constant {z0};
        d               uniform 0.0;
        zGround         constant 0.0;
        zDir            (0 0 1);
        flowDir         (1 0 0);
        value           uniform ({uref} 0 0);
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform (0 0 0);
        value           uniform ({uref} 0 0);
    }}
    sides {{ type slip; }}
    top {{ type slip; }}
    ground {{ type noSlip; }}
    buildings {{ type noSlip; }}
}}
"""
        )

    with open(f"{case_dir}/0/k", "w") as f:
        f.write(
            f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      k;
}}
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform 0.5;
boundaryField
{{
    inlet
    {{
        type            atmBoundaryLayerInletK;
        Uref            constant {uref};
        Zref            constant 10.0;
        z0              constant {z0};
        d               uniform 0.0;
        zGround         constant 0.0;
        zDir            (0 0 1);
        flowDir         (1 0 0);
        value           uniform 0.5;
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform 0.5;
        value           uniform 0.5;
    }}
    sides {{ type slip; }}
    top {{ type slip; }}
    ground {{ type kqRWallFunction; value uniform 0.5; }}
    buildings {{ type kqRWallFunction; value uniform 0.5; }}
}}
"""
        )

    with open(f"{case_dir}/0/epsilon", "w") as f:
        f.write(
            f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      epsilon;
}}
dimensions      [0 2 -3 0 0 0 0];
internalField   uniform 0.1;
boundaryField
{{
    inlet
    {{
        type            atmBoundaryLayerInletEpsilon;
        Uref            constant {uref};
        Zref            constant 10.0;
        z0              constant {z0};
        d               uniform 0.0;
        zGround         constant 0.0;
        zDir            (0 0 1);
        flowDir         (1 0 0);
        value           uniform 0.1;
    }}
    outlet
    {{
        type            inletOutlet;
        inletValue      uniform 0.1;
        value           uniform 0.1;
    }}
    sides {{ type slip; }}
    top {{ type slip; }}
    ground
    {{
        type            atmEpsilonWallFunction;
        z0              uniform {z0};
        value           uniform 0.1;
    }}
    buildings
    {{
        type            epsilonWallFunction;
        value           uniform 0.1;
    }}
}}
"""
        )

    with open(f"{case_dir}/0/nut", "w") as f:
        f.write(
            f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      nut;
}}
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform 0;
boundaryField
{{
    inlet {{ type calculated; value uniform 0; }}
    outlet {{ type calculated; value uniform 0; }}
    sides {{ type calculated; value uniform 0; }}
    top {{ type calculated; value uniform 0; }}
    ground
    {{
        type            atmNutkWallFunction;
        z0              uniform {z0};
        value           uniform 0;
    }}
    buildings
    {{
        type            nutkWallFunction;
        value           uniform 0;
    }}
}}
"""
        )

    return {
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "n_base_cells": n_base_cells,
    }


# --- 6. OpenFOAM Execution via Docker ---
def run_openfoam_workflow(case_dir: str) -> Dict[str, Any]:
    """Execute blockMesh, snappyHexMesh, simpleFoam, and writeCellCentres in Docker.

    Measures execution time, retrieves mesh size and convergence residuals.
    """
    t_start = time.time()

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "--platform",
        "linux/arm64",
        "-v",
        f"{case_dir}:/case",
        "-w",
        "/case",
        DOCKER_IMAGE,
        "bash",
        "-c",
        (
            "set -e && cd /case && "
            "blockMesh > log.blockMesh 2>&1 && "
            "snappyHexMesh -overwrite > log.snappyHexMesh 2>&1 && "
            "checkMesh > log.checkMesh 2>&1 && "
            "simpleFoam > log.simpleFoam 2>&1 || true && "
            "postProcess -func writeCellCentres > log.writeCellCentres 2>&1"
        ),
    ]

    p = subprocess.run(
        docker_cmd,
        capture_output=True,
        text=True,
    )
    t_total = time.time() - t_start

    # Parse logs
    log_mesh = ""
    mesh_cells = 0
    checkmesh_path = os.path.join(case_dir, "log.checkMesh")
    if os.path.exists(checkmesh_path):
        with open(checkmesh_path, "r", encoding="utf-8", errors="ignore") as f:
            log_mesh = f.read()
        m = re.search(r"cells:\s+(\d+)", log_mesh)
        if m:
            mesh_cells = int(m.group(1))

    # Parse simpleFoam log
    log_solver = ""
    iterations = 0
    final_residuals: Dict[str, float] = {}
    converged = False
    simplefoam_path = os.path.join(case_dir, "log.simpleFoam")
    if os.path.exists(simplefoam_path):
        with open(simplefoam_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        for line in lines:
            if line.startswith("Time = "):
                m_t = re.search(r"Time =\s+(\d+)", line)
                if m_t:
                    iterations = int(m_t.group(1))
            if "SIMPLE solution converged in" in line:
                converged = True
            m_res = re.search(
                r"Solving for (Ux|Uy|Uz|p|k|epsilon).*?Final residual = ([\d\.e\-\+]+)",
                line,
            )
            if m_res:
                final_residuals[m_res.group(1)] = float(m_res.group(2))

    return {
        "execution_time_seconds": round(t_total, 1),
        "mesh_cells": mesh_cells,
        "iterations": iterations,
        "converged": converged,
        "final_residuals": final_residuals,
        "success": (mesh_cells > 0 and iterations > 0),
    }


# --- 7. Field Reader & Post-processing ---
def parse_vector_field(filepath: str) -> np.ndarray:
    """Read OpenFOAM ascii vector field (e.g. C or U)."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Field file not found: {filepath}")

    with open(filepath, "r", encoding="latin-1") as f:
        content = f.read()

    # Find the nonuniform List<vector> section
    m = re.search(r"nonuniform\s+List<vector>\s+(\d+)\s*\((.*?)\)\s*;", content, re.DOTALL)
    if not m:
        # Check uniform
        m_u = re.search(r"internalField\s+uniform\s+\(([\d\.e\-\+]+)\s+([\d\.e\-\+]+)\s+([\d\.e\-\+]+)\)", content)
        if m_u:
            vx, vy, vz = float(m_u.group(1)), float(m_u.group(2)), float(m_u.group(3))
            return np.array([[vx, vy, vz]])
        raise ValueError(f"Could not parse vector list from {filepath}")

    n_items = int(m.group(1))
    raw_vecs = m.group(2)
    # Extract numbers inside parentheses: (x y z)
    vecs = re.findall(r"\(([\d\.e\-\+]+)\s+([\d\.e\-\+]+)\s+([\d\.e\-\+]+)\)", raw_vecs)
    arr = np.array(vecs, dtype=np.float32)
    return arr


def log_law_scale_pedestrian_wind(
    u_mag_p: float,
    zp: float,
    z0: float = DEFAULT_Z0,
    z_target: float = 1.5,
) -> float:
    """Scale near-wall fluid velocity to target pedestrian height (1.5 m)

    using standard Atmospheric Boundary Layer logarithmic law:
        U(z) = U_P * ln((z + z0) / z0) / ln((zP + z0) / z0)
    If zP <= z_target, returns u_mag_p directly.
    """
    if zp <= z_target:
        return float(u_mag_p)
    scale = math.log((z_target + z0) / z0) / math.log((zp + z0) / z0)
    return float(u_mag_p * scale)


def extract_pedestrian_wind(
    case_dir: str,
    uref: float,
    rotation_angle_rad: float,
    local_origin: Tuple[float, float, float] = LOCAL_ORIGIN,
    z_max_surface: float = 15.0,
    col_bin_res: float = 3.5,
) -> Dict[str, Any]:
    """Extract pedestrian height (~1.5 m) wind speed and wind speed ratio (U/Uref).

    To avoid missing open-terrain cells where base grid z is coarse, identifies the
    lowest fluid cell above ground for each spatial column in the domain and applies
    physical ABL rough wall-function logarithmic scaling to pedestrian height (1.5 m).
    Maps rotated tunnel coordinates back to global EPSG:28992 coordinates.
    """
    # 1. Cell centres C: look in 0/C or latest time/C
    c_path = os.path.join(case_dir, "0", "C")
    if not os.path.exists(c_path):
        times = [d for d in os.listdir(case_dir) if d.isdigit()]
        if times:
            latest = max(times, key=int)
            c_path = os.path.join(case_dir, latest, "C")

    # 2. Velocity U: look in latest time directory
    times = [d for d in os.listdir(case_dir) if d.isdigit() and int(d) > 0]
    if not times:
        raise FileNotFoundError(f"No solved time steps found in {case_dir}")
    latest_time = max(times, key=int)
    u_path = os.path.join(case_dir, latest_time, "U")

    C = parse_vector_field(c_path)
    U = parse_vector_field(u_path)

    if len(C) != len(U):
        raise ValueError(f"Length mismatch: C has {len(C)} cells, U has {len(U)} cells")

    # Candidate surface layer cells (cz <= z_max_surface)
    surf_mask = C[:, 2] <= z_max_surface
    C_surf = C[surf_mask]
    U_surf = U[surf_mask]

    # Column-wise lowest fluid cell identification
    xmin, ymin = float(C_surf[:, 0].min()), float(C_surf[:, 1].min())
    col_x = np.floor((C_surf[:, 0] - xmin) / col_bin_res).astype(np.int32)
    col_y = np.floor((C_surf[:, 1] - ymin) / col_bin_res).astype(np.int32)

    lowest_dict: Dict[Tuple[int, int], Tuple[float, float, float, float, float, float]] = {}
    for i in range(len(C_surf)):
        key = (int(col_x[i]), int(col_y[i]))
        cz = float(C_surf[i, 2])
        if key not in lowest_dict or cz < lowest_dict[key][2]:
            lowest_dict[key] = (
                float(C_surf[i, 0]),
                float(C_surf[i, 1]),
                cz,
                float(U_surf[i, 0]),
                float(U_surf[i, 1]),
                float(U_surf[i, 2]),
            )

    cx_pts, cy_pts, cz_pts = [], [], []
    u_15_pts, ratio_pts = [], []

    for cell in lowest_dict.values():
        cx, cy, cz, ux, uy, uz = cell
        u_mag = math.sqrt(ux * ux + uy * uy + uz * uz)
        u_15 = log_law_scale_pedestrian_wind(u_mag, cz, z0=DEFAULT_Z0, z_target=1.5)
        r = u_15 / uref

        cx_pts.append(cx)
        cy_pts.append(cy)
        cz_pts.append(cz)
        u_15_pts.append(u_15)
        ratio_pts.append(r)

    cx_arr = np.array(cx_pts, dtype=np.float32)
    cy_arr = np.array(cy_pts, dtype=np.float32)
    cz_arr = np.array(cz_pts, dtype=np.float32)
    u_15_arr = np.array(u_15_pts, dtype=np.float32)
    ratio_arr = np.array(ratio_pts, dtype=np.float32)

    # Inverse rotation to EPSG:28992
    cos_a = math.cos(rotation_angle_rad)
    sin_a = math.sin(rotation_angle_rad)
    x0, y0, _ = local_origin

    x_geo = x0 + cx_arr * cos_a + cy_arr * sin_a
    y_geo = y0 - cx_arr * sin_a + cy_arr * cos_a

    return {
        "x_geo": x_geo,
        "y_geo": y_geo,
        "z_local": cz_arr,
        "u_mag": u_15_arr,
        "ratio": ratio_arr,
        "uref": uref,
        "latest_time": latest_time,
    }


def get_site_outdoor_mask(
    site_geom: Polygon,
    buildings: Sequence[Dict[str, Any]],
    bounds: Tuple[float, float, float, float],
    shape: Tuple[int, int],
    buffer_dist: float = 100.0,
) -> np.ndarray:
    """Generate boolean raster mask for outdoor pedestrian spaces (site + buffer_dist),

    strictly excluding all building footprints (both Harbour plan and context buildings).
    """
    ny, nx = shape
    minx, miny, maxx, maxy = bounds
    mask_img = Image.new("L", (nx, ny), 0)
    draw = ImageDraw.Draw(mask_img)

    def to_px(x: float, y: float) -> Tuple[int, int]:
        px = int(np.clip((x - minx) / (maxx - minx) * (nx - 1), 0, nx - 1))
        py = int(np.clip((maxy - y) / (maxy - miny) * (ny - 1), 0, ny - 1))
        return px, py

    target_geom = site_geom.buffer(buffer_dist) if buffer_dist > 0.0 else site_geom
    if target_geom.geom_type == "Polygon":
        draw.polygon([to_px(x, y) for x, y in target_geom.exterior.coords], fill=255)
    elif target_geom.geom_type == "MultiPolygon":
        for poly in target_geom.geoms:
            draw.polygon([to_px(x, y) for x, y in poly.exterior.coords], fill=255)

    # Mask out ALL building footprints within the evaluation zone
    for b in buildings:
        geom = b["geometry"].intersection(Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]))
        if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        rings = [geom.exterior.coords] if geom.geom_type == "Polygon" else [p.exterior.coords for p in geom.geoms]
        for ring in rings:
            draw.polygon([to_px(x, y) for x, y in ring], fill=0)

    return np.array(mask_img) > 0


# --- 8. Rasterization, Mapping & Visualization ---
def get_font(size: int = 16, language: str = "zh-TW") -> ImageFont.FreeTypeFont:
    """Load system font for Traditional Chinese or English Latin."""
    if language == "en":
        candidates = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
        ]
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def get_chinese_font(size: int = 16) -> ImageFont.FreeTypeFont:
    """Load a clean system font that supports Traditional Chinese (backwards compatibility)."""
    return get_font(size, language="zh-TW")


def colormap_wind_ratio(val: float) -> Tuple[int, int, int]:
    """Color mapping for wind speed ratio U/Uref (0.0 to 1.6+).

    <0.3: Deep calm (dark blue/purple)
    0.3 - 0.7: Sheltered (cyan/teal)
    0.7 - 1.0: Moderate (green)
    1.0 - 1.2: Brisk (yellow/orange)
    >1.2: High wind acceleration (red/crimson)
    """
    v = max(0.0, min(1.6, val))
    if v < 0.3:  # Stagnant
        t = v / 0.3
        return (int(30 + 30 * t), int(40 + 70 * t), int(140 + 60 * t))
    elif v < 0.7:  # Sheltered
        t = (v - 0.3) / 0.4
        return (int(60 + 20 * t), int(110 + 90 * t), int(200 - 40 * t))
    elif v < 1.0:  # Moderate
        t = (v - 0.7) / 0.3
        return (int(80 + 130 * t), int(200 + 30 * t), int(160 - 130 * t))
    elif v < 1.2:  # Transition
        t = (v - 1.0) / 0.2
        return (int(210 + 40 * t), int(230 - 60 * t), int(30 - 20 * t))
    else:  # High wind ratio
        t = min(1.0, (v - 1.2) / 0.4)
        return (int(250 - 20 * t), int(170 - 130 * t), int(10 + 20 * t))


def rasterize_wind_data(
    ped_data: Dict[str, Any],
    site_geom: Polygon,
    grid_res: float = 3.0,
    margin: float = 120.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Tuple[float, float, float, float]]:
    """Rasterize scattered pedestrian wind speed ratio onto a regular 2D grid with iterative diffusion."""
    study_geom = site_geom.buffer(margin)
    minx, miny, maxx, maxy = study_geom.bounds

    nx = int(math.ceil((maxx - minx) / grid_res))
    ny = int(math.ceil((maxy - miny) / grid_res))

    xg = np.linspace(minx, maxx, nx)
    yg = np.linspace(miny, maxy, ny)

    x_pts = ped_data["x_geo"]
    y_pts = ped_data["y_geo"]
    r_pts = ped_data["ratio"]

    in_bounds = (x_pts >= minx) & (x_pts <= maxx) & (y_pts >= miny) & (y_pts <= maxy)
    x_in = x_pts[in_bounds]
    y_in = y_pts[in_bounds]
    r_in = r_pts[in_bounds]

    col_idx = np.clip(np.floor((x_in - minx) / grid_res).astype(np.int32), 0, nx - 1)
    row_idx = np.clip(np.floor((y_in - miny) / grid_res).astype(np.int32), 0, ny - 1)

    sum_grid = np.zeros((ny, nx), dtype=np.float32)
    cnt_grid = np.zeros((ny, nx), dtype=np.int32)

    for r, c, val in zip(row_idx, col_idx, r_in):
        sum_grid[r, c] += val
        cnt_grid[r, c] += 1

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio_grid = np.where(cnt_grid > 0, sum_grid / cnt_grid, 0.0)

    # Iterative diffusion to smoothly propagate continuous velocities across gaps
    filled = ratio_grid.copy()
    valid = cnt_grid > 0
    for _ in range(8):
        if np.all(valid):
            break
        up = np.roll(filled, -1, axis=0)
        down = np.roll(filled, 1, axis=0)
        left = np.roll(filled, -1, axis=1)
        right = np.roll(filled, 1, axis=1)
        v_up = np.roll(valid, -1, axis=0).astype(np.float32)
        v_down = np.roll(valid, 1, axis=0).astype(np.float32)
        v_left = np.roll(valid, -1, axis=1).astype(np.float32)
        v_right = np.roll(valid, 1, axis=1).astype(np.float32)

        denom = v_up + v_down + v_left + v_right
        safe_denom = np.maximum(denom, 1e-6)
        new_vals = np.where(denom > 0, (up * v_up + down * v_down + left * v_left + right * v_right) / safe_denom, filled)
        update = (~valid) & (denom > 0)
        filled = np.where(update, new_vals, filled)
        valid = valid | update

    return filled, xg, yg, (minx, miny, maxx, maxy)



def render_wind_field_map(
    ratio_grid: np.ndarray,
    bounds: Tuple[float, float, float, float],
    buildings: Sequence[Dict[str, Any]],
    site_geom: Polygon,
    wind_name: str,
    wind_deg: float,
    uref: float,
    freq_pct: float,
    output_png: str,
    title_suffix: str = "",
    language: str = "zh-TW",
) -> None:
    """Render a high-resolution wind speed ratio map with PIL in Traditional Chinese or English."""
    minx, miny, maxx, maxy = bounds
    ny, nx = ratio_grid.shape

    # Canvas dimensions
    W = 1400
    H = 1000
    margin_l = 80
    margin_r = 180  # Room for colorbar
    margin_t = 110  # Header
    margin_b = 90  # Scale bar & disclaimer

    map_w = W - margin_l - margin_r
    map_h = H - margin_t - margin_b

    # Coordinate transformation functions
    def to_pixel(x: float, y: float) -> Tuple[int, int]:
        px = margin_l + int((x - minx) / (maxx - minx) * map_w)
        py = margin_t + int((maxy - y) / (maxy - miny) * map_h)  # Invert Y for image
        return px, py

    # 1. Create base RGB image from ratio_grid
    grid_img = Image.new("RGB", (nx, ny))
    grid_pixels = grid_img.load()
    for j in range(ny):
        for i in range(nx):
            val = float(ratio_grid[j, i])
            color = colormap_wind_ratio(val)
            grid_pixels[i, ny - 1 - j] = color  # Invert Y for PIL

    # Resize to map area
    grid_scaled = grid_img.resize((map_w, map_h), Image.Resampling.BILINEAR)

    # 2. Main Canvas
    canvas = Image.new("RGB", (W, H), (252, 253, 255))
    canvas.paste(grid_scaled, (margin_l, margin_t))
    draw = ImageDraw.Draw(canvas)

    # Font setup
    is_en = (language == "en")
    f_title = get_font(24, language=language)
    f_subtitle = get_font(15, language=language)
    f_legend = get_font(13, language=language)
    f_disclaimer = get_font(12, language=language)

    # 3. Draw site boundary
    if site_geom.geom_type == "Polygon":
        site_pts = [to_pixel(x, y) for x, y in site_geom.exterior.coords]
        draw.line(site_pts, fill=(20, 20, 20), width=3)
    elif site_geom.geom_type == "MultiPolygon":
        for poly in site_geom.geoms:
            site_pts = [to_pixel(x, y) for x, y in poly.exterior.coords]
            draw.line(site_pts, fill=(20, 20, 20), width=3)

    # 4. Draw building footprints (dark slate/navy for harbour, grey for context)
    for b in buildings:
        geom = b["geometry"].intersection(Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]))
        if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        is_harb = b.get("is_harbour", False)
        fill_color = (40, 48, 60) if is_harb else (120, 125, 135)
        outline_color = (20, 25, 30) if is_harb else (90, 95, 105)

        rings = []
        if geom.geom_type == "Polygon":
            rings = [geom.exterior.coords]
        elif geom.geom_type == "MultiPolygon":
            rings = [p.exterior.coords for p in geom.geoms]

        for ring in rings:
            pts = [to_pixel(x, y) for x, y in ring]
            if len(pts) >= 3:
                draw.polygon(pts, fill=fill_color, outline=outline_color)

    # Map border
    draw.rectangle([margin_l, margin_t, margin_l + map_w, margin_t + map_h], outline=(100, 110, 125), width=2)

    # 5. Title & Header
    if is_en:
        title_text = f"Harbour Grain Pedestrian Wind Screening: {wind_name} ({wind_deg:.0f}°) Wind Speed Ratio U/Uref{title_suffix}"
        sub_text = (
            f"Incoming Wind: {wind_name} ({wind_deg:.0f}°) | 10 m Ref Speed Uref = {uref:.2f} m/s | "
            f"Annual Frequency: {freq_pct:.1f}% | Evaluation Height: 1.5 m Pedestrian Level"
        )
    else:
        title_text = f"港埠方案行人風場篩選：{wind_name} 風向（{wind_deg:.0f}°）風速比 U/Uref {title_suffix}"
        sub_text = (
            f"入射風向：{wind_name} ({wind_deg:.0f}°) | 10 m 參考風速 Uref = {uref:.2f} m/s | "
            f"全年出現頻率：{freq_pct:.1f}% | 評估高度：行人平面 1.5 m"
        )
    draw.text((margin_l, 25), title_text, fill=(20, 25, 35), font=f_title)
    draw.text((margin_l, 65), sub_text, fill=(70, 80, 95), font=f_subtitle)

    # 6. Wind direction arrow in top-right of map
    arrow_cx = margin_l + map_w - 70
    arrow_cy = margin_t + 70
    rad = math.radians(wind_deg)
    # Wind vector blowing towards:
    vx = -math.sin(rad)
    vy = math.cos(rad)  # Y is up in world, down in image
    ax_start = arrow_cx - vx * 35
    ay_start = arrow_cy + vy * 35
    ax_end = arrow_cx + vx * 35
    ay_end = arrow_cy - vy * 35
    draw.ellipse([arrow_cx - 45, arrow_cy - 45, arrow_cx + 45, arrow_cy + 45], fill=(255, 255, 255, 220), outline=(50, 60, 75), width=2)
    draw.line([(ax_start, ay_start), (ax_end, ay_end)], fill=(200, 20, 20), width=4)
    # Arrow head
    draw.polygon(
        [
            (ax_end, ay_end),
            (ax_end - vx * 12 + vy * 8, ay_end + vy * 12 + vx * 8),
            (ax_end - vx * 12 - vy * 8, ay_end + vy * 12 - vx * 8),
        ],
        fill=(200, 20, 20),
    )
    arrow_label = f"{wind_name} Wind" if is_en else f"{wind_name}風"
    draw.text((arrow_cx - 20, arrow_cy + 22), arrow_label, fill=(30, 30, 30), font=f_legend)

    # 7. Colorbar on the right
    cb_x = margin_l + map_w + 30
    cb_y = margin_t + 60
    cb_w = 26
    cb_h = map_h - 150
    cb_title = "Wind Ratio U/Uref" if is_en else "風速比 U/Uref"
    draw.text((cb_x - 10, cb_y - 30), cb_title, fill=(20, 25, 35), font=f_legend)

    for step in range(cb_h):
        val = 1.6 * (1.0 - step / float(cb_h))
        col = colormap_wind_ratio(val)
        y_pos = cb_y + step
        draw.line([(cb_x, y_pos), (cb_x + cb_w, y_pos)], fill=col, width=1)
    draw.rectangle([cb_x, cb_y, cb_x + cb_w, cb_y + cb_h], outline=(80, 90, 100), width=1)

    # Colorbar ticks
    ticks = [0.0, 0.3, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6]
    for tk in ticks:
        t_y = cb_y + int((1.6 - tk) / 1.6 * cb_h)
        draw.line([(cb_x + cb_w, t_y), (cb_x + cb_w + 6, t_y)], fill=(50, 50, 50), width=1)
        label = f"{tk:.1f}"
        if tk == 0.3:
            label += " (Calm)" if is_en else " (靜風)"
        elif tk == 1.2:
            label += " (High Wind)" if is_en else " (強風加速)"
        draw.text((cb_x + cb_w + 10, t_y - 7), label, fill=(30, 35, 45), font=f_legend)

    # 8. Scale bar & Disclaimer (bottom)
    scale_x = margin_l + 20
    scale_y = H - 55
    scale_m = 200.0  # 200 meters scale bar
    scale_px = int(scale_m / (maxx - minx) * map_w)
    draw.line([(scale_x, scale_y), (scale_x + scale_px, scale_y)], fill=(30, 30, 30), width=4)
    draw.line([(scale_x, scale_y - 6), (scale_x, scale_y + 6)], fill=(30, 30, 30), width=2)
    draw.line([(scale_x + scale_px, scale_y - 6), (scale_x + scale_px, scale_y + 6)], fill=(30, 30, 30), width=2)
    draw.text((scale_x + scale_px // 2 - 20, scale_y - 20), f"{int(scale_m)} m", fill=(30, 30, 30), font=f_legend)

    # Disclaimer
    if is_en:
        disclaimer = (
            "[Note] Exploratory coarse screening; mesh and domain sizes below research guidelines (COST 732/AIJ); relative trends only. "
            "Target ≤ 400k cells, solved in 1 CPU / 1.5 GB environment."
        )
    else:
        disclaimer = (
            "【注意】本圖為探索性粗略篩選；網格與域尺寸低於研究等級（COST 732／AIJ 建議），僅看趨勢。"
            "建築群網格目標 ≤ 40 萬格，於 1 CPU / 1.5 GB 探索環境完成求解。"
        )
    draw.text((margin_l + 220, H - 50), disclaimer, fill=(180, 40, 30), font=f_disclaimer)

    os.makedirs(os.path.dirname(output_png), exist_ok=True)
    canvas.save(output_png, quality=95)


def render_risk_zones_map(
    ratio_grids: Dict[str, np.ndarray],
    bounds: Tuple[float, float, float, float],
    buildings: Sequence[Dict[str, Any]],
    site_geom: Polygon,
    output_png: str,
    language: str = "zh-TW",
) -> None:
    """Render High Wind Risk (U/Uref > 1.2) and Stagnant Wind (U/Uref < 0.3) composite zones."""
    minx, miny, maxx, maxy = bounds
    first_grid = next(iter(ratio_grids.values()))
    ny, nx = first_grid.shape

    W = 1400
    H = 1000
    margin_l = 80
    margin_r = 220
    margin_t = 110
    margin_b = 90

    map_w = W - margin_l - margin_r
    map_h = H - margin_t - margin_b

    def to_pixel(x: float, y: float) -> Tuple[int, int]:
        px = margin_l + int((x - minx) / (maxx - minx) * map_w)
        py = margin_t + int((maxy - y) / (maxy - miny) * map_h)
        return px, py

    # Max ratio across all 4 directions & Min ratio across all directions
    all_r = np.stack(list(ratio_grids.values()), axis=0)
    max_r = np.max(all_r, axis=0)
    min_r = np.min(all_r, axis=0)

    # Base background: neutral light grey
    grid_img = Image.new("RGB", (nx, ny), (242, 244, 248))
    grid_pixels = grid_img.load()

    for j in range(ny):
        for i in range(nx):
            mx = float(max_r[j, i])
            mn = float(min_r[j, i])
            if mx > 1.2:  # High wind zone under any prevailing wind
                t = min(1.0, (mx - 1.2) / 0.4)
                grid_pixels[i, ny - 1 - j] = (int(255), int(100 - 60 * t), int(80 - 60 * t))
            elif mn < 0.3:  # Stagnant wind zone under any prevailing wind
                grid_pixels[i, ny - 1 - j] = (140, 160, 225)
            else:
                grid_pixels[i, ny - 1 - j] = (235, 240, 245)

    grid_scaled = grid_img.resize((map_w, map_h), Image.Resampling.BILINEAR)

    canvas = Image.new("RGB", (W, H), (252, 253, 255))
    canvas.paste(grid_scaled, (margin_l, margin_t))
    draw = ImageDraw.Draw(canvas)

    is_en = (language == "en")
    f_title = get_font(24, language=language)
    f_subtitle = get_font(15, language=language)
    f_legend = get_font(13, language=language)
    f_disclaimer = get_font(12, language=language)

    # Draw site boundary
    if site_geom.geom_type == "Polygon":
        site_pts = [to_pixel(x, y) for x, y in site_geom.exterior.coords]
        draw.line(site_pts, fill=(20, 20, 20), width=3)
    elif site_geom.geom_type == "MultiPolygon":
        for poly in site_geom.geoms:
            site_pts = [to_pixel(x, y) for x, y in poly.exterior.coords]
            draw.line(site_pts, fill=(20, 20, 20), width=3)

    # Draw buildings
    for b in buildings:
        geom = b["geometry"].intersection(Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]))
        if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        is_harb = b.get("is_harbour", False)
        fill_color = (40, 48, 60) if is_harb else (130, 135, 145)
        rings = [geom.exterior.coords] if geom.geom_type == "Polygon" else [p.exterior.coords for p in geom.geoms]
        for ring in rings:
            pts = [to_pixel(x, y) for x, y in ring]
            if len(pts) >= 3:
                draw.polygon(pts, fill=fill_color, outline=(20, 20, 20))

    draw.rectangle([margin_l, margin_t, margin_l + map_w, margin_t + map_h], outline=(100, 110, 125), width=2)

    # Header
    if is_en:
        draw.text((margin_l, 25), "Harbour Grain Wind Risk Composite Zones (4-Wind Envelope)", fill=(20, 25, 35), font=f_title)
        sub = "Combined 4 prevailing winds (SW, W, S, NW): High wind acceleration (U/Uref > 1.2) & stagnant zones (U/Uref < 0.3)"
    else:
        draw.text((margin_l, 25), "港埠方案風環境風險複合分區圖（4 風向包絡）", fill=(20, 25, 35), font=f_title)
        sub = "綜合 4 個盛行風向（SW, W, S, NW）：標示強風加速區（U/Uref > 1.2）與靜風通風不良區（U/Uref < 0.3）"
    draw.text((margin_l, 65), sub, fill=(70, 80, 95), font=f_subtitle)

    # Legend
    leg_x = margin_l + map_w + 25
    leg_y = margin_t + 50
    leg_title = "[Zone Legend]" if is_en else "【分區圖例】"
    draw.text((leg_x, leg_y), leg_title, fill=(20, 25, 35), font=f_legend)

    # Red
    draw.rectangle([leg_x, leg_y + 35, leg_x + 30, leg_y + 55], fill=(255, 70, 50), outline=(100, 20, 20))
    red_txt = "High wind zone\n(U/Uref > 1.2)\nCanyon acceleration" if is_en else "高風速比區 (U/Uref > 1.2)\n易引發街谷峽管強風"
    draw.text((leg_x + 40, leg_y + 35), red_txt, fill=(30, 30, 30), font=f_legend)

    # Blue
    draw.rectangle([leg_x, leg_y + 90, leg_x + 30, leg_y + 110], fill=(140, 160, 225), outline=(50, 70, 150))
    blue_txt = "Stagnant zone\n(U/Uref < 0.3)\nLeeward wake" if is_en else "靜風區 (U/Uref < 0.3)\n背風面、污染物易滯留"
    draw.text((leg_x + 40, leg_y + 90), blue_txt, fill=(30, 30, 30), font=f_legend)

    # Neutral
    draw.rectangle([leg_x, leg_y + 145, leg_x + 30, leg_y + 165], fill=(235, 240, 245), outline=(120, 120, 120))
    neu_txt = "Comfortable zone\n(0.3 - 1.2)\nEveryday walking" if is_en else "舒適風速區 (0.3 - 1.2)\n常規步行散步區"
    draw.text((leg_x + 40, leg_y + 145), neu_txt, fill=(30, 30, 30), font=f_legend)

    # Buildings
    draw.rectangle([leg_x, leg_y + 200, leg_x + 30, leg_y + 220], fill=(40, 48, 60), outline=(20, 20, 20))
    bldg_txt = "Building Footprints" if is_en else "建築群實體"
    draw.text((leg_x + 40, leg_y + 200), bldg_txt, fill=(30, 30, 30), font=f_legend)

    # Scale & Disclaimer
    scale_x = margin_l + 20
    scale_y = H - 55
    scale_m = 200.0
    scale_px = int(scale_m / (maxx - minx) * map_w)
    draw.line([(scale_x, scale_y), (scale_x + scale_px, scale_y)], fill=(30, 30, 30), width=4)
    draw.text((scale_x + scale_px // 2 - 20, scale_y - 20), f"{int(scale_m)} m", fill=(30, 30, 30), font=f_legend)

    if is_en:
        disclaimer = "[Note] Exploratory coarse screening; mesh and domain sizes below research guidelines (COST 732/AIJ); trends only."
    else:
        disclaimer = "【注意】探索性粗略篩選；網格與域尺寸低於研究等級（COST 732／AIJ 建議），僅看趨勢。"
    draw.text((margin_l + 220, H - 50), disclaimer, fill=(180, 40, 30), font=f_disclaimer)

    os.makedirs(os.path.dirname(output_png), exist_ok=True)
    canvas.save(output_png, quality=95)


def render_lawson_comfort_map(
    ratio_grids: Dict[str, np.ndarray],
    wind_stats: Dict[str, Dict[str, Any]],
    bounds: Tuple[float, float, float, float],
    buildings: Sequence[Dict[str, Any]],
    site_geom: Polygon,
    output_png: str,
    language: str = "zh-TW",
) -> None:
    """Estimate Lawson pedestrian comfort classes weighted by 4 prevailing wind frequencies."""
    minx, miny, maxx, maxy = bounds
    first_grid = next(iter(ratio_grids.values()))
    ny, nx = first_grid.shape

    W = 1400
    H = 1000
    margin_l = 80
    margin_r = 220
    margin_t = 110
    margin_b = 90

    map_w = W - margin_l - margin_r
    map_h = H - margin_t - margin_b

    def to_pixel(x: float, y: float) -> Tuple[int, int]:
        px = margin_l + int((x - minx) / (maxx - minx) * map_w)
        py = margin_t + int((maxy - y) / (maxy - miny) * map_h)
        return px, py

    # Frequency-weighted effective wind speed
    # U_eff = sum(weight_k * ratio_k * Uref_k) / sum(weight_k)
    weights = []
    weighted_speed_grids = []
    for wname, r_grid in ratio_grids.items():
        w_stat = wind_stats[wname]
        freq = w_stat["frequency_pct"]
        uref = w_stat.get("mean_speed_10m", w_stat.get("uref_10m", 0.0))
        w_spd = r_grid * uref
        weights.append(freq)
        weighted_speed_grids.append(w_spd * freq)

    tot_w = sum(weights)
    u_eff = np.sum(np.stack(weighted_speed_grids, axis=0), axis=0) / tot_w

    grid_img = Image.new("RGB", (nx, ny), (242, 244, 248))
    grid_pixels = grid_img.load()

    for j in range(ny):
        for i in range(nx):
            v = float(u_eff[j, i])
            if v < 4.0:
                grid_pixels[i, ny - 1 - j] = (130, 215, 140)  # Sitting
            elif v < 6.0:
                grid_pixels[i, ny - 1 - j] = (230, 230, 110)  # Standing
            elif v < 8.0:
                grid_pixels[i, ny - 1 - j] = (245, 175, 75)   # Strolling
            elif v < 10.0:
                grid_pixels[i, ny - 1 - j] = (235, 105, 50)   # Business walking
            else:
                grid_pixels[i, ny - 1 - j] = (190, 40, 130)   # Uncomfortable

    grid_scaled = grid_img.resize((map_w, map_h), Image.Resampling.BILINEAR)

    canvas = Image.new("RGB", (W, H), (252, 253, 255))
    canvas.paste(grid_scaled, (margin_l, margin_t))
    draw = ImageDraw.Draw(canvas)

    is_en = (language == "en")
    f_title = get_font(24, language=language)
    f_subtitle = get_font(15, language=language)
    f_legend = get_font(13, language=language)
    f_disclaimer = get_font(12, language=language)

    # Site boundary
    if site_geom.geom_type == "Polygon":
        site_pts = [to_pixel(x, y) for x, y in site_geom.exterior.coords]
        draw.line(site_pts, fill=(20, 20, 20), width=3)
    elif site_geom.geom_type == "MultiPolygon":
        for poly in site_geom.geoms:
            site_pts = [to_pixel(x, y) for x, y in poly.exterior.coords]
            draw.line(site_pts, fill=(20, 20, 20), width=3)

    # Buildings
    for b in buildings:
        geom = b["geometry"].intersection(Polygon([(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy)]))
        if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            continue
        is_harb = b.get("is_harbour", False)
        fill_color = (40, 48, 60) if is_harb else (130, 135, 145)
        rings = [geom.exterior.coords] if geom.geom_type == "Polygon" else [p.exterior.coords for p in geom.geoms]
        for ring in rings:
            pts = [to_pixel(x, y) for x, y in ring]
            if len(pts) >= 3:
                draw.polygon(pts, fill=fill_color, outline=(20, 20, 20))

    draw.rectangle([margin_l, margin_t, margin_l + map_w, margin_t + map_h], outline=(100, 110, 125), width=2)

    # Header
    if is_en:
        draw.text((margin_l, 25), "Harbour Grain Lawson Pedestrian Wind Comfort Estimation (4 Winds Weighted)", fill=(20, 25, 35), font=f_title)
        sub = "Estimated comfort classes by EPW prevailing frequency weighting (SW 21.5%, W 20.5%, S 17.7%, NW 7.7%)"
    else:
        draw.text((margin_l, 25), "港埠方案 Lawson 行人風舒適度概估圖（4 風向頻率加權）", fill=(20, 25, 35), font=f_title)
        sub = "依 EPW 盛行風向頻率（SW 21.5%, W 20.5%, S 17.7%, NW 7.7%）加權計算等效風速之粗略舒適分級"
    draw.text((margin_l, 65), sub, fill=(70, 80, 95), font=f_subtitle)

    # Legend
    leg_x = margin_l + map_w + 25
    leg_y = margin_t + 40
    leg_title = "[Lawson Classes]" if is_en else "【Lawson 舒適等級】"
    draw.text((leg_x, leg_y), leg_title, fill=(20, 25, 35), font=f_legend)

    if is_en:
        classes = [
            ("Sitting (Long-term)", "< 4.0 m/s", (130, 215, 140)),
            ("Standing (Short-term)", "4.0 - 6.0 m/s", (230, 230, 110)),
            ("Strolling (Leisure walk)", "6.0 - 8.0 m/s", (245, 175, 75)),
            ("Business walking", "8.0 - 10.0 m/s", (235, 105, 50)),
            ("Uncomfortable", "> 10.0 m/s", (190, 40, 130)),
        ]
    else:
        classes = [
            ("戶外長坐 (Sitting)", "< 4.0 m/s", (130, 215, 140)),
            ("短暫站立 (Standing)", "4.0 - 6.0 m/s", (230, 230, 110)),
            ("悠閒漫步 (Strolling)", "6.0 - 8.0 m/s", (245, 175, 75)),
            ("快步行走 (Walking)", "8.0 - 10.0 m/s", (235, 105, 50)),
            ("不舒適區 (Uncomfortable)", "> 10.0 m/s", (190, 40, 130)),
        ]
    cur_y = leg_y + 35
    for cname, cdesc, ccolor in classes:
        draw.rectangle([leg_x, cur_y, leg_x + 25, cur_y + 20], fill=ccolor, outline=(50, 50, 50))
        draw.text((leg_x + 35, cur_y), cname, fill=(20, 25, 35), font=f_legend)
        draw.text((leg_x + 35, cur_y + 16), cdesc, fill=(90, 95, 105), font=f_disclaimer)
        cur_y += 46

    # Scale bar & Disclaimer
    scale_x = margin_l + 20
    scale_y = H - 55
    scale_m = 200.0
    scale_px = int(scale_m / (maxx - minx) * map_w)
    draw.line([(scale_x, scale_y), (scale_x + scale_px, scale_y)], fill=(30, 30, 30), width=4)
    draw.text((scale_x + scale_px // 2 - 20, scale_y - 20), f"{int(scale_m)} m", fill=(30, 30, 30), font=f_legend)

    if is_en:
        disclaimer = "[Note] Exploratory screening; estimated by 4-wind frequency weighting, not full 16-direction microclimate; spatial trends only."
    else:
        disclaimer = "【注意】探索性粗略篩選；依 4 風向頻率加權概估，非全年度 16 風向完整微氣候評估，僅看空間趨勢。"
    draw.text((margin_l + 220, H - 50), disclaimer, fill=(180, 40, 30), font=f_disclaimer)

    os.makedirs(os.path.dirname(output_png), exist_ok=True)
    canvas.save(output_png, quality=95)


def render_4winds_summary_panel(
    ratio_grids: Dict[str, np.ndarray],
    wind_stats: Dict[str, Dict[str, Any]],
    bounds: Tuple[float, float, float, float],
    buildings: Sequence[Dict[str, Any]],
    site_geom: Polygon,
    output_png: str,
    language: str = "zh-TW",
) -> None:
    """Render a 2x2 multi-panel comparison figure of all 4 wind directions."""
    minx, miny, maxx, maxy = bounds
    first_grid = next(iter(ratio_grids.values()))
    ny, nx = first_grid.shape

    W = 1600
    H = 1290
    header_h = 100
    footer_h = 130
    panel_w = (W - 120) // 2
    panel_h = (H - header_h - footer_h - 40) // 2

    canvas = Image.new("RGB", (W, H), (252, 253, 255))
    draw = ImageDraw.Draw(canvas)

    is_en = (language == "en")
    f_title = get_font(26, language=language)
    f_subtitle = get_font(15, language=language)
    f_panel_title = get_font(16, language=language)
    f_disclaimer = get_font(13, language=language)

    # Title
    if is_en:
        draw.text((50, 20), "Harbour Grain Pedestrian Wind Speed Ratio Summary Across 4 Prevailing Directions", fill=(20, 25, 35), font=f_title)
        sub = "Shared colour scale (0.0 to 1.6+); pedestrian level 1.5 m wind ratio U/Uref (OpenFOAM simpleFoam k-epsilon)"
    else:
        draw.text((50, 20), "港埠方案四大盛行風向行人風場模擬對比總覽", fill=(20, 25, 35), font=f_title)
        sub = "共用色階（0.0 至 1.6+）；行人高度 1.5 m 風速比 U/Uref 分布（OpenFOAM simpleFoam k-epsilon）"
    draw.text((50, 60), sub, fill=(70, 80, 95), font=f_subtitle)

    def to_panel_pixel(x: float, y: float, px_off: int, py_off: int) -> Tuple[int, int]:
        px = px_off + int((x - minx) / (maxx - minx) * panel_w)
        py = py_off + int((maxy - y) / (maxy - miny) * panel_h)
        return px, py

    positions = [
        ("SW", 50, header_h + 10),
        ("W", 50 + panel_w + 20, header_h + 10),
        ("S", 50, header_h + 20 + panel_h),
        ("NW", 50 + panel_w + 20, header_h + 20 + panel_h),
    ]

    for wname, off_x, off_y in positions:
        if wname not in ratio_grids or wname not in wind_stats:
            continue
        r_grid = ratio_grids[wname]
        w_stat = wind_stats[wname]

        grid_img = Image.new("RGB", (nx, ny))
        grid_pixels = grid_img.load()
        for j in range(ny):
            for i in range(nx):
                val = float(r_grid[j, i])
                grid_pixels[i, ny - 1 - j] = colormap_wind_ratio(val)
        grid_scaled = grid_img.resize((panel_w, panel_h), Image.Resampling.BILINEAR)
        canvas.paste(grid_scaled, (off_x, off_y))

        pdraw = ImageDraw.Draw(canvas)

        if site_geom.geom_type == "Polygon":
            s_pts = [to_panel_pixel(x, y, off_x, off_y) for x, y in site_geom.exterior.coords]
            pdraw.line(s_pts, fill=(20, 20, 20), width=2)
        elif site_geom.geom_type == "MultiPolygon":
            for poly in site_geom.geoms:
                s_pts = [to_panel_pixel(x, y, off_x, off_y) for x, y in poly.exterior.coords]
                pdraw.line(s_pts, fill=(20, 20, 20), width=2)

        from shapely.geometry import box as _box
        _frame = _box(minx, miny, maxx, maxy)
        for b in buildings:
            geom = b["geometry"].intersection(_frame)
            if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
                continue
            is_harb = b.get("is_harbour", False)
            fill_col = (40, 48, 60) if is_harb else (130, 135, 145)
            rings = [geom.exterior.coords] if geom.geom_type == "Polygon" else [p.exterior.coords for p in geom.geoms]
            for ring in rings:
                pts = [to_panel_pixel(x, y, off_x, off_y) for x, y in ring]
                if len(pts) >= 3:
                    pdraw.polygon(pts, fill=fill_col, outline=(30, 30, 30))

        pdraw.rectangle([off_x, off_y, off_x + panel_w, off_y + panel_h], outline=(80, 90, 105), width=2)

        deg_val = w_stat.get("center_deg", w_stat.get("wind_direction_deg", 0.0))
        spd_val = w_stat.get("mean_speed_10m", w_stat.get("uref_10m", 0.0))
        if is_en:
            tag = f"{wname} ({deg_val:.0f}°) | Freq {w_stat['frequency_pct']:.1f}% | Uref={spd_val:.2f} m/s"
        else:
            tag = f"{wname} 風向 ({deg_val:.0f}°) | 頻率 {w_stat['frequency_pct']:.1f}% | Uref={spd_val:.2f} m/s"
        pdraw.rectangle([off_x, off_y, off_x + 360, off_y + 30], fill=(255, 255, 255, 230), outline=(80, 90, 105))
        pdraw.text((off_x + 10, off_y + 5), tag, fill=(20, 25, 35), font=f_panel_title)

    bar_x0, bar_y0, bar_w, bar_h = 50, header_h + 30 + 2 * panel_h + 15, 600, 16
    for k in range(bar_w):
        draw.line([(bar_x0 + k, bar_y0), (bar_x0 + k, bar_y0 + bar_h)], fill=colormap_wind_ratio(1.6 * k / (bar_w - 1)))
    draw.rectangle([bar_x0, bar_y0, bar_x0 + bar_w, bar_y0 + bar_h], outline=(80, 90, 105))
    for v in (0.0, 0.3, 0.6, 0.9, 1.2, 1.6):
        tx = bar_x0 + int(v / 1.6 * (bar_w - 1))
        draw.line([(tx, bar_y0 + bar_h), (tx, bar_y0 + bar_h + 5)], fill=(60, 60, 60))
        draw.text((tx - 10, bar_y0 + bar_h + 7), f"{v:.1f}", fill=(40, 45, 55), font=f_disclaimer)
    cb_text = "Pedestrian level 1.5 m wind ratio U/Uref (<0.3 calm; >1.2 high wind acceleration)" if is_en else "行人高度 1.5 m 風速比 U/Uref（<0.3 靜風；>1.2 強風加速）"
    draw.text((bar_x0 + bar_w + 20, bar_y0 - 2), cb_text, fill=(40, 45, 55), font=f_subtitle)
    if is_en:
        disclaimer = "[Note] Exploratory coarse screening; mesh and domain sizes below research guidelines (COST 732/AIJ); log-law converted; spatial trends only. ≤ 400k cells."
    else:
        disclaimer = "【注意】探索性粗略篩選；網格與域尺寸低於研究等級（COST 732／AIJ 建議），行人層風速由近地網格以對數律換算，僅看趨勢。總格數 ≤ 40 萬格。"
    draw.text((50, H - 30), disclaimer, fill=(180, 40, 30), font=f_disclaimer)

    os.makedirs(os.path.dirname(output_png), exist_ok=True)
    canvas.save(output_png, quality=95)


# --- 9. Complete Orchestration Pipeline ---
def run_e5_harbour_screening(
    quick_test_one_wind: bool = False,
    override_target_cells: Optional[int] = None,
    output_dir: Optional[str] = None,
    language: str = "zh-TW",
) -> Dict[str, Any]:
    """Execute complete E5 OpenFOAM screening workflow."""
    print("=" * 60)
    print("OpenFOAM E5 風場粗略篩選（港埠方案、4 個風向、探索性）")
    print("=" * 60)

    if output_dir is None:
        utc_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = os.path.join(REPO_ROOT, "artifacts", "w8", f"e5-cfd-rerun-{utc_ts}")

    # Guard: never overwrite existing artifacts/w8/e5-cfd
    canonical_e5_cfd = os.path.abspath(os.path.join(REPO_ROOT, "artifacts", "w8", "e5-cfd"))
    if os.path.abspath(output_dir) == canonical_e5_cfd:
        raise ValueError("Overwriting artifacts/w8/e5-cfd is prohibited; rerun must write to a new directory.")

    case_base_dir = os.path.join(output_dir, "cases")
    grids_dir = os.path.join(output_dir, "grids")
    os.makedirs(case_base_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(grids_dir, exist_ok=True)

    # 1. Parse Weather Data
    print("\n[Step 1/6] 解析天氣檔 (EPW) 盛行風向與風速統計...")
    weather_info = parse_epw_wind_data(EPW_PATH)
    selected_winds = weather_info["selected_4_winds"]
    print(f"成功解析 EPW，篩選 4 大盛行風向：")
    for s, st in selected_winds.items():
        print(f"  - {s:2s} ({st['center_deg']:3.0f}°): 頻率 {st['frequency_pct']:4.1f}%, 10m 平均風速 {st['mean_speed_10m']:.2f} m/s")

    # 2. Load Buildings
    print("\n[Step 2/6] 讀取港埠方案建築與周邊 300 m 背景建築...")
    all_bldgs, site_geom, harbour_bldgs = load_harbour_and_context_buildings(
        HARBOUR_PLAN_PATH, CONTEXT_PATH, buffer_dist=300.0, default_height=12.0
    )
    print(f"  - 港埠方案建築數：{len(harbour_bldgs)} 棟")
    print(f"  - 總建築數（含周邊 300m 背景）：{len(all_bldgs)} 棟")

    wind_names = ["SW", "W", "S", "NW"]
    if quick_test_one_wind:
        wind_names = ["SW"]

    case_results: Dict[str, Any] = {}
    ratio_grids: Dict[str, np.ndarray] = {}
    master_bounds: Optional[Tuple[float, float, float, float]] = None

    # Determine cell cap
    target_cells = override_target_cells or MAX_GLOBAL_CELLS

    # 4. Loop Wind Directions
    for idx, wname in enumerate(wind_names, start=1):
        print(f"\n[Step 3.{idx}/6] 建立與執行風向 {wname} ({selected_winds[wname]['center_deg']}°)...")
        w_deg = selected_winds[wname]["center_deg"]
        uref = selected_winds[wname]["mean_speed_10m"]
        case_dir = os.path.join(case_base_dir, f"harbour_{wname.lower()}")

        # Flow angle and rotation
        rad = math.radians(w_deg)
        flow_vx = -math.sin(rad)
        flow_vy = -math.cos(rad)
        beta = math.atan2(flow_vy, flow_vx)
        alpha = -beta  # Rotate building coordinates by alpha so incoming wind aligns with +X

        cos_a = math.cos(alpha)
        sin_a = math.sin(alpha)
        x0, y0, _ = LOCAL_ORIGIN

        # Extrude and rotate buildings
        all_facets = []
        pts_rot = []
        for b in all_bldgs:
            geom = b["geometry"]
            h = b["height_m"]
            g_sim = geom.simplify(0.5, preserve_topology=True)
            rings = [g_sim.exterior.coords] if g_sim.geom_type == "Polygon" else [p.exterior.coords for p in g_sim.geoms]
            for ring in rings:
                r_coords = []
                for x, y in ring:
                    xr = (x - x0) * cos_a - (y - y0) * sin_a
                    yr = (x - x0) * sin_a + (y - y0) * cos_a
                    r_coords.append((xr, yr))
                    pts_rot.append((xr, yr))
                facets = extrude_polygon_to_stl_facets(r_coords, h, max_height_cap=100.0)
                all_facets.extend(facets)

        pts_rot_arr = np.array(pts_rot)
        domain = compute_domain_bounds(pts_rot_arr, H=DEFAULT_H)
        print(f"  - 幾何 STL 三角面數：{len(all_facets):,}")
        print(f"  - 計算域尺寸：Lx={domain['Lx']:.1f} m, Ly={domain['Ly']:.1f} m, Lz={domain['Lz']:.1f} m")

        # Write binary STL
        stl_path = os.path.join(case_dir, "constant", "triSurface", "buildings.stl")
        write_binary_stl(stl_path, all_facets)

        # Write OpenFOAM dictionaries
        mesh_meta = generate_openfoam_case(
            case_dir=case_dir,
            domain=domain,
            uref=uref,
            z0=DEFAULT_Z0,
            target_cells=target_cells,
        )
        print(f"  - blockMesh 基礎網格：{mesh_meta['nx']} x {mesh_meta['ny']} x {mesh_meta['nz']} = {mesh_meta['n_base_cells']:,} 格")

        # Run Docker OpenFOAM workflow
        print(f"  - 呼叫 Docker ({DOCKER_IMAGE}) 執行網格生成與 simpleFoam...")
        t0 = time.time()
        wf_res = run_openfoam_workflow(case_dir)
        dt = time.time() - t0
        print(f"  - 執行完成：耗時 {dt:.1f} 秒 | 最終網格數：{wf_res['mesh_cells']:,} 格 | 迭代數：{wf_res['iterations']} | 收斂：{wf_res['converged']}")

        # First wind timing guard: If single wind > 75 min (4500s), drop cells to 200k
        if idx == 1 and dt > 4500.0 and not os.environ.get("E5_NO_CELL_DOWNGRADE"):
            print(f"  [警示] 第一個風向耗時 {dt:.1f}s 超過 75 分鐘上限！降格至 20 萬格重試...")
            target_cells = 200000
            # Re-generate and re-run with 200k cells
            generate_openfoam_case(case_dir, domain, uref, DEFAULT_Z0, target_cells=200000)
            wf_res = run_openfoam_workflow(case_dir)

        # Extract Pedestrian Wind Field
        ped_data = extract_pedestrian_wind(case_dir, uref, rotation_angle_rad=alpha, local_origin=LOCAL_ORIGIN)
        r_grid, xg, yg, g_bounds = rasterize_wind_data(ped_data, site_geom)
        if master_bounds is None:
            master_bounds = g_bounds
        ratio_grids[wname] = r_grid

        # Save ratio_grid npz data
        npz_path = os.path.join(grids_dir, f"{wname}.npz")
        np.savez_compressed(
            npz_path,
            ratio_grid=r_grid,
            bounds=np.array(g_bounds, dtype=float),
            wind_deg=float(w_deg),
            uref=float(uref),
            frequency_pct=float(selected_winds[wname]["frequency_pct"]),
        )
        print(f"  - 儲存網格資料：{npz_path}")

        # Save buildings and site geometry GeoJSON once
        bldgs_geojson_path = os.path.join(grids_dir, "buildings.geojson")
        if not os.path.exists(bldgs_geojson_path):
            from shapely.geometry import mapping
            features = []
            for b in all_bldgs:
                features.append({
                    "type": "Feature",
                    "geometry": mapping(b["geometry"]),
                    "properties": {
                        "height_m": b.get("height_m"),
                        "is_harbour": b.get("is_harbour", False),
                        "id": b.get("id"),
                    },
                })
            with open(bldgs_geojson_path, "w", encoding="utf-8") as f:
                json.dump({"type": "FeatureCollection", "features": features}, f)
            print(f"  - 儲存建築圖層：{bldgs_geojson_path}")

        site_geojson_path = os.path.join(grids_dir, "site.geojson")
        if not os.path.exists(site_geojson_path):
            from shapely.geometry import mapping
            site_feat = {
                "type": "Feature",
                "geometry": mapping(site_geom),
                "properties": {},
            }
            with open(site_geojson_path, "w", encoding="utf-8") as f:
                json.dump(site_feat, f)
            print(f"  - 儲存基地邊界：{site_geojson_path}")

        # Area statistics specifically for outdoor pedestrian spaces (site + 100m buffer)
        # excluding all building footprints
        cell_area = 3.0 * 3.0
        outdoor_mask = get_site_outdoor_mask(site_geom, all_bldgs, g_bounds, r_grid.shape, buffer_dist=100.0)
        r_outdoor = r_grid[outdoor_mask]

        # Also get strictly on-site outdoor statistics
        site_only_mask = get_site_outdoor_mask(site_geom, all_bldgs, g_bounds, r_grid.shape, buffer_dist=0.0)
        r_site_only = r_grid[site_only_mask]

        if len(r_outdoor) > 0:
            max_ratio = float(np.max(r_outdoor))
            mean_ratio = float(np.mean(r_outdoor))
            median_ratio = float(np.median(r_outdoor))
            high_area = float(np.sum(r_outdoor > 1.2) * cell_area)
            stagnant_area = float(np.sum(r_outdoor < 0.3) * cell_area)
            comfortable_area = float(np.sum((r_outdoor >= 0.3) & (r_outdoor <= 1.2)) * cell_area)
            tot_outdoor_area = float(len(r_outdoor) * cell_area)
            high_pct = high_area / tot_outdoor_area * 100.0
            stagnant_pct = stagnant_area / tot_outdoor_area * 100.0
            comfortable_pct = comfortable_area / tot_outdoor_area * 100.0
        else:
            max_ratio = 0.0
            mean_ratio = 0.0
            median_ratio = 0.0
            high_area = 0.0
            stagnant_area = 0.0
            comfortable_area = 0.0
            tot_outdoor_area = 0.0
            high_pct = 0.0
            stagnant_pct = 0.0
            comfortable_pct = 0.0

        site_mean = float(np.mean(r_site_only)) if len(r_site_only) > 0 else mean_ratio
        site_median = float(np.median(r_site_only)) if len(r_site_only) > 0 else median_ratio

        case_results[wname] = {
            "wind_direction_deg": w_deg,
            "uref_10m": uref,
            "frequency_pct": selected_winds[wname]["frequency_pct"],
            "mesh_cells": wf_res["mesh_cells"],
            "iterations": wf_res["iterations"],
            "converged": wf_res["converged"],
            "final_residuals": wf_res["final_residuals"],
            "runtime_seconds": wf_res["execution_time_seconds"],
            "max_wind_ratio": round(max_ratio, 2),
            "mean_wind_ratio": round(mean_ratio, 2),
            "median_wind_ratio": round(median_ratio, 2),
            "site_only_mean_wind_ratio": round(site_mean, 2),
            "site_only_median_wind_ratio": round(site_median, 2),
            "high_wind_ratio_area_m2": round(high_area, 1),
            "high_wind_ratio_pct": round(high_pct, 1),
            "stagnant_wind_area_m2": round(stagnant_area, 1),
            "stagnant_wind_pct": round(stagnant_pct, 1),
            "comfortable_wind_area_m2": round(comfortable_area, 1),
            "comfortable_wind_pct": round(comfortable_pct, 1),
            "total_outdoor_pedestrian_area_m2": round(tot_outdoor_area, 1),
            "site_only_outdoor_area_m2": round(float(len(r_site_only) * cell_area), 1),
        }

        # Render individual wind maps (both zh-TW and en)
        png_path = os.path.join(output_dir, f"cfd_{wname.lower()}_wind_ratio.png")
        print(f"  - 輸出繁體中文風場圖：{png_path}")
        render_wind_field_map(
            ratio_grid=r_grid,
            bounds=g_bounds,
            buildings=all_bldgs,
            site_geom=site_geom,
            wind_name=wname,
            wind_deg=w_deg,
            uref=uref,
            freq_pct=selected_winds[wname]["frequency_pct"],
            output_png=png_path,
            language="zh-TW",
        )
        png_en_path = os.path.join(output_dir, f"cfd_{wname.lower()}_wind_ratio-en.png")
        print(f"  - 輸出英文風場圖：{png_en_path}")
        render_wind_field_map(
            ratio_grid=r_grid,
            bounds=g_bounds,
            buildings=all_bldgs,
            site_geom=site_geom,
            wind_name=wname,
            wind_deg=w_deg,
            uref=uref,
            freq_pct=selected_winds[wname]["frequency_pct"],
            output_png=png_en_path,
            language="en",
        )

    # 5. Composite and Comfort Maps (if multiple winds run)
    if len(wind_names) > 1:
        print("\n[Step 5/6] 輸出 4 風向總覽對比圖、強風與靜風風險分區圖、Lawson 舒適度概估圖 (中/英文)...")
        assert master_bounds is not None
        # 4-panel comparison
        render_4winds_summary_panel(ratio_grids, selected_winds, master_bounds, all_bldgs, site_geom, os.path.join(output_dir, "cfd_4winds_summary.png"), language="zh-TW")
        render_4winds_summary_panel(ratio_grids, selected_winds, master_bounds, all_bldgs, site_geom, os.path.join(output_dir, "cfd_4winds_summary-en.png"), language="en")

        # Risk zones map
        render_risk_zones_map(ratio_grids, master_bounds, all_bldgs, site_geom, os.path.join(output_dir, "cfd_wind_risk_zones.png"), language="zh-TW")
        render_risk_zones_map(ratio_grids, master_bounds, all_bldgs, site_geom, os.path.join(output_dir, "cfd_wind_risk_zones-en.png"), language="en")

        # Lawson comfort map
        render_lawson_comfort_map(ratio_grids, selected_winds, master_bounds, all_bldgs, site_geom, os.path.join(output_dir, "cfd_lawson_comfort.png"), language="zh-TW")
        render_lawson_comfort_map(ratio_grids, selected_winds, master_bounds, all_bldgs, site_geom, os.path.join(output_dir, "cfd_lawson_comfort-en.png"), language="en")
    else:
        print("\n[Step 5/6] 單一風向測試模式，跳過 4 風向總覽與複合分區圖。")

    # 6. Save Tables & Manifest
    print("\n[Step 6/6] 輸出結果表 (Markdown / JSON) 與 Manifest...")
    # Results Table
    results_json_path = os.path.join(output_dir, "results_table.json")
    with open(results_json_path, "w", encoding="utf-8") as f:
        json.dump(case_results, f, ensure_ascii=False, indent=2)

    results_md_path = os.path.join(output_dir, "results_table.md")
    with open(results_md_path, "w", encoding="utf-8") as f:
        f.write("# 港埠方案 OpenFOAM 行人風場粗略篩選結果表\n\n")
        f.write("> **探索性粗略篩選；網格與域尺寸低於研究等級（COST 732／AIJ 建議），僅看趨勢**\n\n")
        f.write("| 風向 | 入射角 (°) | 出現頻率 (%) | 參考風速 Uref (m/s) | 網格數 (格) | 迭代數 | 收斂狀態 | 耗時 (秒) | 最大風速比 | 平均風速比 | 強風區面積 (>1.2) | 靜風區面積 (<0.3) |\n")
        f.write("|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|\n")
        for w, res in case_results.items():
            conv_str = "收斂 (殘差<1e-4)" if res["converged"] else "達到最大迭代"
            f.write(
                f"| {w} | {res['wind_direction_deg']:.0f}° | {res['frequency_pct']:.1f}% | {res['uref_10m']:.2f} | "
                f"{res['mesh_cells']:,} | {res['iterations']} | {conv_str} | {res['runtime_seconds']:.1f}s | "
                f"{res['max_wind_ratio']:.2f} | {res['mean_wind_ratio']:.2f} | {res['high_wind_ratio_area_m2']:,} m² | "
                f"{res['stagnant_wind_area_m2']:,} m² |\n"
            )

    # Manifest
    manifest = {
        "task": "E5 風場第一部分：OpenFOAM 粗略篩選（港埠方案、4 個風向、探索性）",
        "date": "2026-10-16",
        "disclaimer": "探索性粗略篩選；網格與域尺寸低於研究等級（COST 732／AIJ 建議），僅看趨勢。",
        "docker_image": DOCKER_IMAGE,
        "docker_digest": DOCKER_DIGEST,
        "hardware_environment": {
            "docker_cpu_cores": 1,
            "docker_memory_limit": "1.5 GB",
            "architecture": "linux/arm64",
        },
        "simulation_parameters": {
            "turbulence_model": "k-epsilon (RANS)",
            "solver": "simpleFoam",
            "inlet_boundary_condition": "atmBoundaryLayerInletVelocity / K / Epsilon",
            "roughness_length_z0_m": DEFAULT_Z0,
            "characteristic_height_H_m": DEFAULT_H,
            "domain_dimensions": {
                "upstream": "5H (100 m)",
                "lateral": "5H (100 m)",
                "downstream": "15H (300 m)",
                "height": "6H (120 m)",
            },
            "convergence_criteria": f"Residual < {CONVERGENCE_TOL} or max {MAX_ITERATIONS} iterations",
        },
        "geometry_and_assumptions": [
            "方案輸入：artifacts/fab1/run-8/harbour_grain-plan.json（新建＋保留建築 footprint 與高度）。",
            "周邊背景：~/.local/share/urban-design-data/context/context-20260927T153054Z/buildings.geojson（基地外 300 m 內；無高度者設為 12.0 m）。",
            "局部原點平移：(89077.5, 435869.5, 0.0) EPSG:28992，消除高位坐標精度截斷誤差。",
            "建築高度截斷假設：少數遠端背景超高層建築截斷至 100 m，確保幾何完全容納於大氣邊界層計算域（120 m）內。",
            "旋轉建築坐標系：維持計算域長軸與網格正交，風向始終沿計算域 +X 方向吹入。",
        ],
        "cases": case_results,
        "generated_artifacts": [
            f"{output_dir}/cfd_sw_wind_ratio.png",
            f"{output_dir}/cfd_sw_wind_ratio-en.png",
            f"{output_dir}/cfd_w_wind_ratio.png",
            f"{output_dir}/cfd_w_wind_ratio-en.png",
            f"{output_dir}/cfd_s_wind_ratio.png",
            f"{output_dir}/cfd_s_wind_ratio-en.png",
            f"{output_dir}/cfd_nw_wind_ratio.png",
            f"{output_dir}/cfd_nw_wind_ratio-en.png",
            f"{output_dir}/cfd_4winds_summary.png",
            f"{output_dir}/cfd_4winds_summary-en.png",
            f"{output_dir}/cfd_wind_risk_zones.png",
            f"{output_dir}/cfd_wind_risk_zones-en.png",
            f"{output_dir}/cfd_lawson_comfort.png",
            f"{output_dir}/cfd_lawson_comfort-en.png",
            f"{output_dir}/results_table.json",
            f"{output_dir}/results_table.md",
            f"{output_dir}/manifest.json",
            f"{output_dir}/README_zh.md",
        ],
    }

    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # README_zh.md
    readme_path = os.path.join(output_dir, "README_zh.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("# E5 風場第一部分：OpenFOAM 港埠方案粗略篩選報告\n\n")
        f.write("> **免責與性質說明**：本報告屬於探索性粗略篩選（Exploratory Coarse Screening）；計算網格與計算域尺寸低於正式研究等級（COST 732 與 AIJ 行人風場指引建議），主要用於比較空間微氣候趨勢與辨識強風加速與靜風風險熱點。\n\n")
        f.write("## 1. 執行環境與配置\n")
        f.write(f"- **容器映像**：`{DOCKER_IMAGE}` (arm64 原生)\n")
        f.write(f"- **映像摘要**：`{DOCKER_DIGEST}`\n")
        f.write("- **資源約束**：Docker Desktop 1 CPU、1.5 GB 記憶體限制；嚴格維持總網格數 ≤ 40 萬格以內。\n")
        f.write(f"- **局部坐標原點**：`{LOCAL_ORIGIN}` (EPSG:28992)。\n")
        f.write("- **風向選取**：依鹿特丹 EPW 天氣檔統計，選取出現頻率最高的 4 個盛行海風風向：**SW (225°)**、**W (270°)**、**S (180°)**、**NW (315°)**，累計涵蓋 67.4% 全年時數。\n\n")
        f.write("## 2. 模擬結果彙整\n\n")
        with open(results_md_path, "r", encoding="utf-8") as rmf:
            f.write(rmf.read())
        f.write("\n## 3. 圖件清單\n")
        f.write("1. `cfd_sw_wind_ratio.png`：西南風（SW，225°）行人高度 1.5 m 風速比分布圖\n")
        f.write("2. `cfd_w_wind_ratio.png`：西風（W，270°）行人高度 1.5 m 風速比分布圖\n")
        f.write("3. `cfd_s_wind_ratio.png`：南風（S，180°）行人高度 1.5 m 風速比分布圖\n")
        f.write("4. `cfd_nw_wind_ratio.png`：西北風（NW，315°）行人高度 1.5 m 風速比分布圖\n")
        f.write("5. `cfd_4winds_summary.png`：4 風向 2x2 對比總覽面板（共用色階）\n")
        f.write("6. `cfd_wind_risk_zones.png`：強風加速區（>1.2）與靜風區（<0.3）複合分區圖\n")
        f.write("7. `cfd_lawson_comfort.png`：依 4 風向頻率加權之 Lawson 行人舒適度概估圖\n")

    print("\n[Done] 全部模擬與報告圖件生成完成！")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenFOAM E5 Wind Field Screening")
    parser.add_argument("--test-one-wind", action="store_true", help="Only run one wind direction for quick testing")
    parser.add_argument("--target-cells", type=int, default=MAX_GLOBAL_CELLS, help="Target global cell count")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory (defaults to artifacts/w8/e5-cfd-rerun-<UTC>)")
    args = parser.parse_args()

    run_e5_harbour_screening(
        quick_test_one_wind=args.test_one_wind,
        override_target_cells=args.target_cells,
        output_dir=args.output_dir,
    )
