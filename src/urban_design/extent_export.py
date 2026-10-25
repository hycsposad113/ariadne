"""Verified extent-fetch layers → portable GeoPackage; no QGIS process."""
from pathlib import Path
import json
import sqlite3
import struct
from pyproj import CRS
from shapely.geometry import shape
from .site_extents import digest, utc


def verified_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_bytes())
    root = path.parent.resolve()
    for item in manifest['files']:
        file = Path(item['path']).resolve()
        if file.parent != root or file.is_symlink():
            raise ValueError('manifest artifact escapes fetch directory')
        data = file.read_bytes()
        if len(data) != item['bytes'] or digest(data) != item['sha256']:
            raise ValueError('extent artifact hash/size mismatch')
    return manifest


def export_geopackage(manifest_path: Path, output: Path) -> dict:
    manifest = verified_manifest(manifest_path)
    if output.exists():
        raise FileExistsError(output)
    layers = {'extent': 'extent.geojson', 'buildings': 'buildings.geojson', 'osm_buildings': 'osm-buildings.geojson',
              'landuse': 'landuse.geojson', 'plans': 'plans.geojson',
              'transit': 'transit.geojson', 'pois': 'pois.geojson', 'bag_uses': 'bag-uses.geojson',
              **{f'roads_{mode}': f'network-{mode}.geojson' for mode in ('pedestrian', 'bicycle', 'motor_vehicle')}}
    verified = {Path(item['path']).name for item in manifest['files']}
    heights_path = manifest_path.parent / 'heights.json'
    heights = {}
    if 'heights.json' in verified:
        from .three_d_bag import load_3dbag_height_table
        heights = load_3dbag_height_table(heights_path).records
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents an accidental overwrite between exists/connect.
    with output.open('xb'):
        pass
    counts = {}
    with sqlite3.connect(output) as connection:
        connection.executescript('''
        PRAGMA application_id=1196444487;
        PRAGMA user_version=10300;
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL,srs_id INTEGER PRIMARY KEY,organization TEXT NOT NULL,organization_coordsys_id INTEGER NOT NULL,definition TEXT NOT NULL,description TEXT);
        CREATE TABLE gpkg_contents (table_name TEXT PRIMARY KEY,data_type TEXT NOT NULL,identifier TEXT UNIQUE,description TEXT DEFAULT '',last_change TEXT NOT NULL,min_x DOUBLE,min_y DOUBLE,max_x DOUBLE,max_y DOUBLE,srs_id INTEGER);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL,column_name TEXT NOT NULL,geometry_type_name TEXT NOT NULL,srs_id INTEGER NOT NULL,z TINYINT NOT NULL,m TINYINT NOT NULL,PRIMARY KEY(table_name,column_name));
        ''')
        for sid, name in ((-1, 'Undefined Cartesian'), (0, 'Undefined Geographic')):
            connection.execute('INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)', (name, sid, 'NONE', sid, 'undefined', ''))
        for sid in (4326, 28992):
            crs = CRS.from_epsg(sid)
            connection.execute('INSERT INTO gpkg_spatial_ref_sys VALUES (?,?,?,?,?,?)', (crs.name, sid, 'EPSG', sid, crs.to_wkt('WKT1_GDAL'), ''))
        for name, filename in layers.items():
            if filename not in verified:
                continue
            doc = json.loads((manifest_path.parent / filename).read_bytes())
            sid = int(doc['crs']['properties']['name'].split(':')[1])
            geometries = [shape(feature['geometry']) for feature in doc['features']]
            if any(not geometry.is_valid or geometry.is_empty for geometry in geometries):
                raise ValueError('invalid export geometry')
            connection.execute(f'CREATE TABLE "{name}" (fid INTEGER PRIMARY KEY,geom BLOB NOT NULL,properties TEXT NOT NULL)')
            bounds = [None] * 4 if not geometries else [min(g.bounds[0] for g in geometries), min(g.bounds[1] for g in geometries), max(g.bounds[2] for g in geometries), max(g.bounds[3] for g in geometries)]
            connection.execute('INSERT INTO gpkg_contents VALUES (?,?,?,?,?,?,?,?,?,?)', (name, 'features', name, 'Acquisition draft; not approved site', utc().replace('Z', '.000Z'), *bounds, sid))
            connection.execute('INSERT INTO gpkg_geometry_columns VALUES (?,?,?,?,?,?)', (name, 'geom', 'GEOMETRY', sid, 0, 0))
            for feature, geometry in zip(doc['features'], geometries):
                blob = b'GP' + bytes([0, 1]) + struct.pack('<i', sid) + geometry.wkb
                properties = dict(feature.get('properties', {}))
                if name == 'buildings' and heights:
                    from .three_d_bag import normalize_bag_identificatie
                    raw_id = properties.get('identificatie')
                    try:
                        height = heights.get(normalize_bag_identificatie(str(raw_id)))
                    except ValueError:
                        height = None
                    properties.update(height_above_ground_m=height.height_above_ground_m if height else None,
                                      height_source='3D BAG', height_status=height.status if height else 'UNAVAILABLE',
                                      vertical_reference='height difference in m; source roof/ground NAP EPSG:5709')
                connection.execute(f'INSERT INTO "{name}" (geom,properties) VALUES (?,?)', (blob, json.dumps(properties, ensure_ascii=False)))
            counts[name] = len(geometries)
    return {'path': str(output), 'sha256': digest(output.read_bytes()), 'layers': counts, 'source_manifest_sha256': digest(manifest_path.read_bytes())}
