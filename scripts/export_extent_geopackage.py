"""Export one immutable extent-fetch manifest without starting QGIS."""
import argparse
import json
from pathlib import Path
from urban_design.extent_export import export_geopackage

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_geopackage(args.manifest, args.output), indent=2))
