from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Sequence

from .wing_surface import Station


Point2D = tuple[float, float]
CellMarker = Literal["boundary_layer", "trailing_edge_connector"]


@dataclass(frozen=True)
class AirfoilWallSplit:
    upper_path: list[Point2D]
    lower_path: list[Point2D]
    leading_edge_index: int
    added_lower_trailing_edge: bool
    sharp_trailing_edge: bool

    @property
    def wall_path(self) -> list[Point2D]:
        return self.upper_path + self.lower_path[1:]


@dataclass(frozen=True)
class BoundaryLayerBlockSpec:
    first_layer_height_m: float
    growth_ratio: float
    layer_count: int
    te_wake_length_m: float | None = None


@dataclass(frozen=True)
class QuadCell:
    nodes: tuple[int, int, int, int]
    marker: CellMarker


@dataclass(frozen=True)
class WallNodeIndices:
    upper_te: int
    leading_edge: int
    lower_te: int


@dataclass(frozen=True)
class AirfoilBoundaryLayerBlock:
    vertices: list[Point2D]
    cells: list[QuadCell]
    wall_nodes: WallNodeIndices
    metadata: dict[str, bool | float | int | str]
    quality: dict[str, float | int]

    def marker_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for cell in self.cells:
            counts[cell.marker] = counts.get(cell.marker, 0) + 1
        return counts


def split_airfoil_wall_loop(
    airfoil_xz: Sequence[Point2D],
    *,
    tolerance: float = 1.0e-9,
) -> AirfoilWallSplit:
    """Split a TE-upper -> LE -> TE-lower airfoil loop for owned BL topology.

    The current VSP resampler intentionally drops the duplicated lower trailing
    edge in the closed airfoil loop. That is acceptable for a faceted inviscid
    shell, but it leaves a hidden terminal segment for boundary-layer extrusion.
    This splitter restores a distinct lower-TE wall node when the lower path
    stops upstream of the upper TE, so later BL cells are grown only along the
    open airfoil wall and not from a closed TE cap.
    """
    points = _clean_points(airfoil_xz)
    if len(points) < 4:
        raise ValueError("Airfoil loop must contain at least four points")

    leading_edge_index = min(range(len(points)), key=lambda index: points[index][0])
    if leading_edge_index == 0 or leading_edge_index == len(points) - 1:
        raise ValueError("Airfoil loop must run TE-upper -> LE -> TE-lower")

    upper = points[: leading_edge_index + 1]
    lower = points[leading_edge_index:]
    upper_te = upper[0]
    lower_te = lower[-1]
    added_lower_te = False

    if lower_te[0] < upper_te[0] - tolerance:
        lower = [*lower, upper_te]
        lower_te = lower[-1]
        added_lower_te = True

    sharp_te = _distance(lower_te, upper_te) <= tolerance
    wall_path = upper + lower[1:]
    if _closed_signed_area(wall_path) <= 0.0:
        raise ValueError("Airfoil loop must have positive TE-upper -> LE -> TE-lower area")

    return AirfoilWallSplit(
        upper_path=upper,
        lower_path=lower,
        leading_edge_index=leading_edge_index,
        added_lower_trailing_edge=added_lower_te,
        sharp_trailing_edge=sharp_te,
    )


def build_airfoil_boundary_layer_block(
    station: Station,
    spec: BoundaryLayerBlockSpec,
) -> AirfoilBoundaryLayerBlock:
    _validate_block_spec(spec)
    split = split_airfoil_wall_loop(station.airfoil_xz)
    wall = [(station.chord * x, station.chord * z) for x, z in split.wall_path]
    offsets = _layer_offsets(spec)
    normals = _outward_vertex_normals(wall)

    vertices: list[Point2D] = []
    for offset in offsets:
        for point, normal in zip(wall, normals):
            vertices.append(
                (
                    point[0] + offset * normal[0],
                    point[1] + offset * normal[1],
                )
            )

    wall_count = len(wall)

    def node(layer: int, index: int) -> int:
        return layer * wall_count + index

    te_wake_length = (
        max(20.0 * spec.first_layer_height_m, 0.02 * station.chord)
        if spec.te_wake_length_m is None
        else spec.te_wake_length_m
    )
    if te_wake_length <= 0.0 or not math.isfinite(te_wake_length):
        raise ValueError("te_wake_length_m must be a positive finite value")
    wake_start = len(vertices)
    for layer in range(spec.layer_count + 1):
        upper_te = vertices[node(layer, 0)]
        lower_te = vertices[node(layer, wall_count - 1)]
        wake_x = max(upper_te[0], lower_te[0]) + te_wake_length
        vertices.append((wake_x, upper_te[1]))
        vertices.append((wake_x, lower_te[1]))

    def wake_upper(layer: int) -> int:
        return wake_start + 2 * layer

    def wake_lower(layer: int) -> int:
        return wake_start + 2 * layer + 1

    cells: list[QuadCell] = []
    for layer in range(spec.layer_count):
        for index in range(wall_count - 1):
            cells.append(
                _oriented_cell(
                    vertices,
                    (
                        node(layer, index),
                        node(layer, index + 1),
                        node(layer + 1, index + 1),
                        node(layer + 1, index),
                    ),
                    "boundary_layer",
                )
            )

    for layer in range(spec.layer_count):
        cells.append(
            _oriented_cell(
                vertices,
                (
                    node(layer, 0),
                    wake_upper(layer),
                    wake_upper(layer + 1),
                    node(layer + 1, 0),
                ),
                "trailing_edge_connector",
            )
        )
        cells.append(
            _oriented_cell(
                vertices,
                (
                    node(layer, wall_count - 1),
                    node(layer + 1, wall_count - 1),
                    wake_lower(layer + 1),
                    wake_lower(layer),
                ),
                "trailing_edge_connector",
            )
        )

    quality = _quality_summary(vertices, cells, wall_count)
    if quality["non_positive_area_count"] != 0:
        raise ValueError("Airfoil boundary-layer block contains non-positive cells")

    return AirfoilBoundaryLayerBlock(
        vertices=vertices,
        cells=cells,
        wall_nodes=WallNodeIndices(
            upper_te=node(0, 0),
            leading_edge=node(0, split.leading_edge_index),
            lower_te=node(0, wall_count - 1),
        ),
        metadata={
            "station_y_m": station.y,
            "station_chord_m": station.chord,
            "wall_node_count": wall_count,
            "leading_edge_wall_index": split.leading_edge_index,
            "layer_count": spec.layer_count,
            "first_layer_height_m": spec.first_layer_height_m,
            "growth_ratio": spec.growth_ratio,
            "total_thickness_m": offsets[-1],
            "te_wake_length_m": te_wake_length,
            "added_lower_trailing_edge": split.added_lower_trailing_edge,
            "sharp_trailing_edge": split.sharp_trailing_edge,
            "te_cap_extrusion_cells": 0,
        },
        quality=quality,
    )


def _validate_block_spec(spec: BoundaryLayerBlockSpec) -> None:
    if spec.first_layer_height_m <= 0.0 or not math.isfinite(spec.first_layer_height_m):
        raise ValueError("first_layer_height_m must be a positive finite value")
    if spec.growth_ratio < 1.0 or not math.isfinite(spec.growth_ratio):
        raise ValueError("growth_ratio must be a finite value >= 1")
    if spec.layer_count < 1:
        raise ValueError("layer_count must be at least 1")


def _clean_points(points: Sequence[Point2D], *, tolerance: float = 1.0e-12) -> list[Point2D]:
    cleaned = [(float(x), float(z)) for x, z in points]
    if len(cleaned) >= 2 and _distance(cleaned[0], cleaned[-1]) <= tolerance:
        return cleaned[:-1]
    return cleaned


def _layer_offsets(spec: BoundaryLayerBlockSpec) -> list[float]:
    offsets = [0.0]
    thickness = spec.first_layer_height_m
    total = 0.0
    for _ in range(spec.layer_count):
        total += thickness
        offsets.append(total)
        thickness *= spec.growth_ratio
    return offsets


def _outward_vertex_normals(wall: Sequence[Point2D]) -> list[Point2D]:
    normals: list[Point2D] = []
    for index, point in enumerate(wall):
        if index == 0:
            tangent = _sub(wall[1], point)
        elif index == len(wall) - 1:
            tangent = _sub(point, wall[index - 1])
        else:
            tangent = _sub(wall[index + 1], wall[index - 1])
        unit_tangent = _unit(tangent)
        # For a positive TE-upper -> LE -> TE-lower airfoil loop, the solid is
        # on the left side of the path. The outward side is therefore right.
        normals.append((unit_tangent[1], -unit_tangent[0]))
    return normals


def _oriented_cell(
    vertices: Sequence[Point2D],
    nodes: tuple[int, int, int, int],
    marker: CellMarker,
) -> QuadCell:
    if _cell_signed_area(vertices, nodes) < 0.0:
        nodes = (nodes[0], nodes[3], nodes[2], nodes[1])
    return QuadCell(nodes=nodes, marker=marker)


def _quality_summary(
    vertices: Sequence[Point2D],
    cells: Sequence[QuadCell],
    wall_count: int,
) -> dict[str, float | int]:
    areas = [_cell_signed_area(vertices, cell.nodes) for cell in cells]
    first_layer_heights = [
        _distance(vertices[index], vertices[wall_count + index]) for index in range(wall_count)
    ]
    return {
        "cell_count": len(cells),
        "min_area_m2": min(areas) if areas else 0.0,
        "max_area_m2": max(areas) if areas else 0.0,
        "non_positive_area_count": sum(1 for area in areas if area <= 0.0),
        "min_first_layer_height_m": min(first_layer_heights),
        "max_first_layer_height_m": max(first_layer_heights),
    }


def _closed_signed_area(points: Sequence[Point2D]) -> float:
    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, [*points[1:], points[0]])
    )


def _cell_signed_area(vertices: Sequence[Point2D], nodes: tuple[int, int, int, int]) -> float:
    points = [vertices[node] for node in nodes]
    return _closed_signed_area(points)


def _sub(left: Point2D, right: Point2D) -> Point2D:
    return left[0] - right[0], left[1] - right[1]


def _unit(vector: Point2D) -> Point2D:
    length = math.hypot(vector[0], vector[1])
    if length <= 1.0e-14:
        raise ValueError("Cannot compute normal for duplicate airfoil points")
    return vector[0] / length, vector[1] / length


def _distance(left: Point2D, right: Point2D) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])
