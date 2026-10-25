"""Constraint-selected FAR basis; geometry and source validation stay at callers."""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Literal, Protocol
from shapely.geometry.base import BaseGeometry

class FarConstraint(Protocol):
    denominator: str | None

@dataclass(frozen=True)
class FarSiteContext:
    design_area: BaseGeometry
    water_geometry: BaseGeometry | None = None

def resolve_far_denominator(
    constraint: FarConstraint | None, site_context: FarSiteContext, *,
    legacy_basis: Literal["land_area", "exploration_design_area"] = "exploration_design_area",
) -> tuple[float, str]:
    specified = constraint.denominator if constraint is not None else None
    basis = specified or legacy_basis
    if basis not in {"land_area", "exploration_design_area"}:
        raise ValueError("unsupported FAR denominator")
    geometry = site_context.design_area
    if basis == "land_area":
        if site_context.water_geometry is None:
            raise ValueError("land FAR requires verified BGT water geometry (empty is allowed)")
        geometry = geometry.difference(site_context.water_geometry)
    area = float(geometry.area)
    if not math.isfinite(area) or area <= 0:
        raise ValueError("FAR denominator must be a positive finite area")
    label = basis if specified else "legacy/unspecified:" + basis
    return area, label
