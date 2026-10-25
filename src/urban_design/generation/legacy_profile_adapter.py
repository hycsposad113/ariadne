"""Footprint-only capability adapter to the preserved W5 template operators.

Catalogue floor ranges describe typological precedents. Formal floor counts
are separate authored recipes bounded by D2, not claims of those precedents.
No source loading or historical preview authority is imported here.
"""
from types import MappingProxyType
from functools import lru_cache
from shapely.ops import unary_union
from shapely.geometry import Polygon, MultiPolygon
from urban_design.generation.type_registry import GeneratedMorphology
from urban_design.morphology.dictionary_generator import _template_geometry, _validate_dictionary_parameters
from urban_design.morphology_dictionary import load_dictionary

TYPES = frozenset({'building.courtyard_closed', 'building.l_block', 'building.i_slab', 'building.point_array'})
VERSION = 'w5-template-footprint-adapter-v1'


@lru_cache(maxsize=1)
def _entries():
    return {e['id']:e for e in load_dictionary()['entries']}

def generate_legacy_profile(type_id, site, parameters, *, crs, coordinate_unit):
    if type_id not in TYPES or crs != 'EPSG:28992' or coordinate_unit != 'm':
        raise ValueError('unsupported legacy footprint capability or coordinate frame')
    if set(parameters) != {'rotation_deg'} or parameters['rotation_deg'] != 0:
        raise ValueError('legacy profiles require a local unrotated complete envelope')
    if not isinstance(site, Polygon) or len(site.interiors) or site.symmetric_difference(site.envelope).area > 1e-6:
        raise ValueError('legacy footprint requires a complete rectangular envelope; no clipped type')
    entry = _entries()[type_id]
    shapes, values = _template_geometry(site.envelope, entry, seed_text=VERSION,
                                        recipe={'building_edge_setback_m': 2.0})
    if not shapes or _validate_dictionary_parameters(entry, values):
        raise ValueError('legacy template cannot satisfy dictionary footprint parameters')
    geometry = unary_union(shapes)
    if not geometry.is_valid or geometry.is_empty or not site.buffer(1e-7).covers(geometry):
        raise ValueError('legacy footprint fails containment')
    if type_id == 'building.courtyard_closed' and (not isinstance(geometry, Polygon) or len(geometry.interiors) != 1):
        raise ValueError('courtyard must preserve one enclosed void')
    if type_id == 'building.point_array' and (not isinstance(geometry, MultiPolygon) or len(geometry.geoms) != 4):
        raise ValueError('point array must preserve four separated complete footprints')
    if type_id == 'building.l_block' and (not isinstance(geometry, Polygon) or len(geometry.interiors) or geometry.equals(geometry.envelope)):
        raise ValueError('L must preserve a connected concave corner')
    if type_id == 'building.i_slab' and not geometry.equals(geometry.envelope):
        raise ValueError('bar must remain rectangular')
    return GeneratedMorphology(type_id, 'footprint-only', VERSION, VERSION, crs, coordinate_unit,
                               MappingProxyType(values), geometry)
