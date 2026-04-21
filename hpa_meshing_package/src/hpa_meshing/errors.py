class MeshingError(Exception):
    """Base error for hpa_meshing."""


class GeometryInvalidError(MeshingError):
    pass


class TopologyUnsupportedError(MeshingError):
    pass


class RouteResolutionError(MeshingError):
    pass


class MeshGenerationError(MeshingError):
    pass


class BoundaryLayerError(MeshingError):
    pass


class QualityGateError(MeshingError):
    pass


class ExportError(MeshingError):
    pass
