"""QGIS entry point for the Urban Design Study Area companion plugin."""


def classFactory(iface):
    """Return the plugin instance created by QGIS."""
    from .plugin import UrbanDesignStudyAreaPlugin

    return UrbanDesignStudyAreaPlugin(iface)
