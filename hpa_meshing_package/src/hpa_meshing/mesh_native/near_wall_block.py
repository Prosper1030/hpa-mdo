from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Sequence

from .wing_surface import Station, Vertex, WingSpec


Point2D = tuple[float, float]
CellMarker = Literal["boundary_layer", "trailing_edge_connector"]
BoundaryFaceMarker = Literal["wing_wall", "bl_outer_interface", "wake_cut", "span_cap"]


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
class HexCell:
    nodes: tuple[int, int, int, int, int, int, int, int]
    marker: CellMarker


@dataclass(frozen=True)
class BlockBoundaryFace:
    nodes: tuple[int, int, int, int]
    marker: BoundaryFaceMarker


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


@dataclass(frozen=True)
class WingBoundaryLayerBlock:
    vertices: list[Vertex]
    cells: list[HexCell]
    boundary_faces: list[BlockBoundaryFace]
    section_blocks: list[AirfoilBoundaryLayerBlock]
    metadata: dict[str, bool | float | int | str]
    quality: dict[str, float | int]

    def marker_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for cell in self.cells:
            counts[cell.marker] = counts.get(cell.marker, 0) + 1
        return counts

    def boundary_marker_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for face in self.boundary_faces:
            counts[face.marker] = counts.get(face.marker, 0) + 1
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


def build_wing_boundary_layer_block(
    wing: WingSpec,
    bl_spec: BoundaryLayerBlockSpec,
) -> WingBoundaryLayerBlock:
    stations = _ordered_stations(wing)
    section_blocks = [build_airfoil_boundary_layer_block(station, bl_spec) for station in stations]
    _validate_matching_section_blocks(section_blocks)

    section_vertex_count = len(section_blocks[0].vertices)
    section_cell_count = len(section_blocks[0].cells)
    vertices: list[Vertex] = []
    for station, section in zip(stations, section_blocks):
        vertices.extend(
            _transform_local_xz_to_station_xyz(point, station, wing.twist_axis_x)
            for point in section.vertices
        )

    def node(section_index: int, local_node: int) -> int:
        return section_index * section_vertex_count + local_node

    cells: list[HexCell] = []
    estimated_volumes: list[float] = []
    span_intervals: list[float] = []
    for station_index, (left_station, right_station) in enumerate(
        zip(stations[:-1], stations[1:])
    ):
        span_interval = right_station.y - left_station.y
        span_intervals.append(span_interval)
        left_section = section_blocks[station_index]
        right_section = section_blocks[station_index + 1]
        for cell_index, left_cell in enumerate(left_section.cells):
            right_cell = right_section.cells[cell_index]
            if left_cell.marker != right_cell.marker:
                raise ValueError("Boundary-layer section marker topology mismatch")
            cells.append(
                HexCell(
                    nodes=(
                        *(node(station_index, local) for local in left_cell.nodes),
                        *(node(station_index + 1, local) for local in right_cell.nodes),
                    ),
                    marker=left_cell.marker,
                )
            )
            left_area = _cell_signed_area(left_section.vertices, left_cell.nodes)
            right_area = _cell_signed_area(right_section.vertices, right_cell.nodes)
            estimated_volumes.append(0.5 * (left_area + right_area) * span_interval)

    wall_count = int(section_blocks[0].metadata["wall_node_count"])
    boundary_faces = _build_block_boundary_faces(
        section_count=len(stations),
        section_vertex_count=section_vertex_count,
        section_cells=section_blocks[0].cells,
        wall_count=wall_count,
        layer_count=bl_spec.layer_count,
    )
    unowned_boundary_count = _unowned_boundary_face_count(cells, boundary_faces)
    quality = {
        "cell_count": len(cells),
        "min_estimated_volume_m3": min(estimated_volumes) if estimated_volumes else 0.0,
        "non_positive_volume_count": sum(
            1 for volume in estimated_volumes if volume <= 0.0
        ),
        "min_span_interval_m": min(span_intervals) if span_intervals else 0.0,
        "max_span_interval_m": max(span_intervals) if span_intervals else 0.0,
        "min_section_first_layer_height_m": min(
            float(section.quality["min_first_layer_height_m"]) for section in section_blocks
        ),
        "max_section_first_layer_height_m": max(
            float(section.quality["max_first_layer_height_m"]) for section in section_blocks
        ),
        "boundary_face_count": len(boundary_faces),
        "unowned_boundary_face_count": unowned_boundary_count,
    }
    if quality["non_positive_volume_count"] != 0:
        raise ValueError("Wing boundary-layer block contains non-positive estimated volumes")
    if quality["unowned_boundary_face_count"] != 0:
        raise ValueError("Wing boundary-layer block contains unowned boundary faces")

    return WingBoundaryLayerBlock(
        vertices=vertices,
        cells=cells,
        boundary_faces=boundary_faces,
        section_blocks=section_blocks,
        metadata={
            "station_count": len(stations),
            "span_interval_count": len(stations) - 1,
            "section_vertex_count": section_vertex_count,
            "section_cell_count": section_cell_count,
            "layer_count": bl_spec.layer_count,
            "first_layer_height_m": bl_spec.first_layer_height_m,
            "growth_ratio": bl_spec.growth_ratio,
            "twist_axis_x": wing.twist_axis_x,
        },
        quality=quality,
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


def _ordered_stations(wing: WingSpec) -> list[Station]:
    if len(wing.stations) < 2:
        raise ValueError("At least two stations are required")
    stations = list(wing.stations)
    for left, right in zip(stations[:-1], stations[1:]):
        if right.y <= left.y:
            raise ValueError("Station y values must be strictly increasing")
    return stations


def _validate_matching_section_blocks(sections: Sequence[AirfoilBoundaryLayerBlock]) -> None:
    if not sections:
        raise ValueError("At least one section block is required")
    vertex_count = len(sections[0].vertices)
    markers = [cell.marker for cell in sections[0].cells]
    for section in sections[1:]:
        if len(section.vertices) != vertex_count:
            raise ValueError("Boundary-layer section vertex topology mismatch")
        if [cell.marker for cell in section.cells] != markers:
            raise ValueError("Boundary-layer section cell topology mismatch")


def _build_block_boundary_faces(
    *,
    section_count: int,
    section_vertex_count: int,
    section_cells: Sequence[QuadCell],
    wall_count: int,
    layer_count: int,
) -> list[BlockBoundaryFace]:
    faces: list[BlockBoundaryFace] = []
    wake_start = (layer_count + 1) * wall_count

    def section_node(section: int, local_node: int) -> int:
        return section * section_vertex_count + local_node

    def grid(section: int, layer: int, index: int) -> int:
        return section_node(section, layer * wall_count + index)

    def wake(section: int, layer: int, side: int) -> int:
        return section_node(section, wake_start + 2 * layer + side)

    for section in range(section_count - 1):
        for index in range(wall_count - 1):
            faces.append(
                BlockBoundaryFace(
                    nodes=(
                        grid(section, 0, index),
                        grid(section + 1, 0, index),
                        grid(section + 1, 0, index + 1),
                        grid(section, 0, index + 1),
                    ),
                    marker="wing_wall",
                )
            )
            faces.append(
                BlockBoundaryFace(
                    nodes=(
                        grid(section, layer_count, index),
                        grid(section, layer_count, index + 1),
                        grid(section + 1, layer_count, index + 1),
                        grid(section + 1, layer_count, index),
                    ),
                    marker="bl_outer_interface",
                )
            )

        faces.append(
            BlockBoundaryFace(
                nodes=(
                    grid(section, layer_count, 0),
                    grid(section + 1, layer_count, 0),
                    wake(section + 1, layer_count, 0),
                    wake(section, layer_count, 0),
                ),
                marker="bl_outer_interface",
            )
        )
        faces.append(
            BlockBoundaryFace(
                nodes=(
                    grid(section, layer_count, wall_count - 1),
                    wake(section, layer_count, 1),
                    wake(section + 1, layer_count, 1),
                    grid(section + 1, layer_count, wall_count - 1),
                ),
                marker="bl_outer_interface",
            )
        )

        faces.append(
            BlockBoundaryFace(
                nodes=(
                    grid(section, 0, 0),
                    wake(section, 0, 0),
                    wake(section + 1, 0, 0),
                    grid(section + 1, 0, 0),
                ),
                marker="wake_cut",
            )
        )
        faces.append(
            BlockBoundaryFace(
                nodes=(
                    grid(section, 0, wall_count - 1),
                    grid(section + 1, 0, wall_count - 1),
                    wake(section + 1, 0, 1),
                    wake(section, 0, 1),
                ),
                marker="wake_cut",
            )
        )

        for layer in range(layer_count):
            faces.append(
                BlockBoundaryFace(
                    nodes=(
                        wake(section, layer, 0),
                        wake(section + 1, layer, 0),
                        wake(section + 1, layer + 1, 0),
                        wake(section, layer + 1, 0),
                    ),
                    marker="wake_cut",
                )
            )
            faces.append(
                BlockBoundaryFace(
                    nodes=(
                        wake(section, layer, 1),
                        wake(section, layer + 1, 1),
                        wake(section + 1, layer + 1, 1),
                        wake(section + 1, layer, 1),
                    ),
                    marker="wake_cut",
                )
            )

    for section in (0, section_count - 1):
        for cell in section_cells:
            faces.append(
                BlockBoundaryFace(
                    nodes=tuple(section_node(section, node) for node in cell.nodes),
                    marker="span_cap",
                )
            )
    return faces


def _unowned_boundary_face_count(
    cells: Sequence[HexCell],
    boundary_faces: Sequence[BlockBoundaryFace],
) -> int:
    face_counts: dict[tuple[int, int, int, int], int] = {}
    for cell in cells:
        for face in _hex_faces(cell):
            key = _canonical_face(face)
            face_counts[key] = face_counts.get(key, 0) + 1
    actual_boundary = {face for face, count in face_counts.items() if count == 1}
    owned_boundary = {_canonical_face(face.nodes) for face in boundary_faces}
    return len(actual_boundary - owned_boundary)


def _hex_faces(cell: HexCell) -> tuple[tuple[int, int, int, int], ...]:
    a, b, c, d, e, f, g, h = cell.nodes
    return (
        (a, b, c, d),
        (e, f, g, h),
        (a, e, f, b),
        (b, f, g, c),
        (c, g, h, d),
        (d, h, e, a),
    )


def _canonical_face(face: Sequence[int]) -> tuple[int, int, int, int]:
    return tuple(sorted(face))


def _transform_local_xz_to_station_xyz(
    point: Point2D,
    station: Station,
    twist_axis_x: float,
) -> Vertex:
    x, z = point
    theta = math.radians(station.twist_deg)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    twist_axis = station.chord * twist_axis_x
    x_rot = twist_axis + cos_theta * (x - twist_axis) + sin_theta * z
    z_rot = -sin_theta * (x - twist_axis) + cos_theta * z
    return station.x_le + x_rot, station.y, station.z_le + z_rot


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
