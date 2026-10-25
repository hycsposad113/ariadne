"""Headless QGIS smoke. Run with the QGIS LTR Python, then call exitQgis()."""

from __future__ import annotations

import json
import os
import platform
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from qgis.core import (
        Qgis,
        QgsApplication,
        QgsCoordinateTransformContext,
        QgsFeature,
        QgsGeometry,
        QgsVectorFileWriter,
        QgsVectorLayer,
    )

    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(json.dumps({"ok": False, "reason": "output geopackage path is required"}))
        return 2
    output = Path(args[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    QgsApplication.setPrefixPath("/Applications/QGIS-LTR.app/Contents/MacOS", True)
    app = QgsApplication([], False)
    app.initQgis()
    result = {"ok": False, "exit_qgis_called": False, "feature_count": 0}
    try:
        layer = QgsVectorLayer("Polygon?crs=EPSG:28992", "c1-proxy-extent", "memory")
        if not layer.isValid():
            result["reason"] = "EPSG:28992 memory layer is invalid"
        else:
            feature = QgsFeature()
            feature.setGeometry(
                QgsGeometry.fromWkt("POLYGON((-10 -10, 10 -10, 10 10, -10 10, -10 -10))")
            )
            added, _ = layer.dataProvider().addFeatures([feature])
            layer.updateExtents()
            extent = layer.extent()
            bbox = [
                round(extent.xMinimum(), 6),
                round(extent.yMinimum(), 6),
                round(extent.xMaximum(), 6),
                round(extent.yMaximum(), 6),
            ]
            result["memory_feature_count"] = layer.featureCount()
            result["memory_bbox"] = bbox
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.fileEncoding = "UTF-8"
            written = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                str(output),
                QgsCoordinateTransformContext(),
                options,
            )
            error = written[0] if isinstance(written, tuple) else written
            if not added or error != QgsVectorFileWriter.NoError:
                result["reason"] = f"geopackage write failed: {written}"
            else:
                reread = QgsVectorLayer(str(output), "c1-proxy-reread", "ogr")
                reread_extent = reread.extent()
                result["feature_count"] = reread.featureCount()
                result["bbox"] = [
                    round(reread_extent.xMinimum(), 6),
                    round(reread_extent.yMinimum(), 6),
                    round(reread_extent.xMaximum(), 6),
                    round(reread_extent.yMaximum(), 6),
                ]
                result["qgis_version"] = QgsApplication.applicationVersion() or Qgis.QGIS_VERSION
                result["qgis_architecture"] = platform.machine()
                result["ok"] = (
                    reread.isValid()
                    and result["feature_count"] == 1
                    and result["bbox"] == [-10.0, -10.0, 10.0, 10.0]
                )
                if not result["ok"]:
                    result["reason"] = "reread feature count or bbox did not match the memory layer"
    finally:
        app.exitQgis()
        result["exit_qgis_called"] = True
    print(json.dumps(result, ensure_ascii=False), flush=True)
    # exitQgis() has already run. A normal interpreter shutdown then raises
    # SIGSEGV inside Qt static teardown, which hides the smoke status.
    os._exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    sys.exit(main())
