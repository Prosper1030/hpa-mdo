from __future__ import annotations

from dataclasses import replace
import math
from typing import Any, Mapping, Sequence

from hpa_meshing.mesh_native.wing_surface import Station

from cfd_rescue.section_cgrid import build_section_cgrid, section_cgrid_quality
from cfd_rescue.section_ogrid import transform_section_point
from cfd_rescue.swept_hexa import (
    HEX_FACE_NODE_ORDERS,
    FaceRecord,
    Point3,
    SweptHexaMesh,
    _best_positive_hex_orientation,
)


CGRID_PATCH_ORDER = (
    "airfoil_upper",
    "airfoil_lower",
    "te_wall",
    "outlet",
    "farfield",
    "tip_left",
    "tip_right",
)
CGRID_PATCH_TYPES = {
    "airfoil_upper": "wall",
    "airfoil_lower": "wall",
    "te_wall": "wall",
    "outlet": "patch",
    "farfield": "patch",
    "tip_left": "patch",
    "tip_right": "patch",
}
SECTION_CGRID_PATCH_TYPES = {
    **CGRID_PATCH_TYPES,
    "tip_left": "empty",
    "tip_right": "empty",
}


def build_extruded_section_cgrid_mesh(
    station: Station,
    *,
    n_radial: int,
    first_layer_height_m: float,
    farfield_chords: float,
    wake_length_chords: float,
    case_id: str,
    near_wall_growth: float = 1.12,
    wake_cross_cells: int = 4,
    te_normal_blend_points: int | None = None,
    wake_te_splay_factor: float = 0.0,
    wake_te_splay_layers: int = 4,
) -> SweptHexaMesh:
    if wake_cross_cells < 1:
        raise ValueError("wake_cross_cells must be at least 1")
    grid = build_section_cgrid(
        station,
        first_layer_height_m=first_layer_height_m,
        n_radial=n_radial,
        farfield_chords=farfield_chords,
        wake_length_chords=wake_length_chords,
        near_wall_growth=near_wall_growth,
        te_normal_blend_points=te_normal_blend_points,
    )
    dy = max(20.0 * first_layer_height_m, 1.0e-3)
    span_stations = [
        replace(station, y=station.y - 0.5 * dy),
        replace(station, y=station.y + 0.5 * dy),
    ]
    points: list[Point3] = []
    cgrid_point_count = (grid.n_radial + 1) * grid.n_path
    wake_interior_count = (grid.n_radial + 1) * (wake_cross_cells - 1)
    section_stride = cgrid_point_count + wake_interior_count
    for span_station in span_stations:
        for radial in range(grid.n_radial + 1):
            for index in range(grid.n_path):
                points.append(transform_section_point(span_station, grid.points[radial][index]))
        for radial in range(grid.n_radial + 1):
            for cross in range(1, wake_cross_cells):
                point = _wake_interior_point(
                    grid,
                    radial=radial,
                    cross=cross,
                    wake_cross_cells=wake_cross_cells,
                    first_layer_height_m=first_layer_height_m,
                    wake_te_splay_factor=wake_te_splay_factor,
                    wake_te_splay_layers=wake_te_splay_layers,
                )
                points.append(
                    transform_section_point(
                        span_station,
                        point,
                    )
                )

    def node(span: int, radial: int, index: int) -> int:
        return span * section_stride + radial * grid.n_path + index

    def wake_node(span: int, radial: int, cross: int) -> int:
        if cross == 0:
            return node(span, radial, 0)
        if cross == wake_cross_cells:
            return node(span, radial, grid.n_path - 1)
        return (
            span * section_stride
            + cgrid_point_count
            + radial * (wake_cross_cells - 1)
            + cross
            - 1
        )

    cells: list[tuple[int, int, int, int, int, int, int, int]] = []
    patch_by_key: dict[tuple[int, ...], str] = {}
    for radial in range(grid.n_radial):
        for index in range(grid.n_path - 1):
            lower = (
                node(0, radial, index),
                node(0, radial, index + 1),
                node(0, radial + 1, index + 1),
                node(0, radial + 1, index),
            )
            upper = (
                node(1, radial, index),
                node(1, radial, index + 1),
                node(1, radial + 1, index + 1),
                node(1, radial + 1, index),
            )
            cell = _best_positive_cgrid_hex_orientation(points, lower, upper)
            cells.append(cell)
            if radial == 0:
                patch_by_key[tuple(sorted((node(0, 0, index), node(1, 0, index), node(1, 0, index + 1), node(0, 0, index + 1))))] = grid.segment_markers[index]
            if radial == grid.n_radial - 1:
                patch_by_key[tuple(sorted((node(0, radial + 1, index), node(1, radial + 1, index), node(1, radial + 1, index + 1), node(0, radial + 1, index + 1))))] = "farfield"
            patch_by_key[tuple(sorted((node(0, radial, index), node(0, radial, index + 1), node(0, radial + 1, index + 1), node(0, radial + 1, index))))] = "tip_left"
            patch_by_key[tuple(sorted((node(1, radial, index), node(1, radial, index + 1), node(1, radial + 1, index + 1), node(1, radial + 1, index))))] = "tip_right"

    for radial in range(grid.n_radial):
        for cross in range(wake_cross_cells):
            lower = (
                wake_node(0, radial, cross),
                wake_node(0, radial + 1, cross),
                wake_node(0, radial + 1, cross + 1),
                wake_node(0, radial, cross + 1),
            )
            upper = (
                wake_node(1, radial, cross),
                wake_node(1, radial + 1, cross),
                wake_node(1, radial + 1, cross + 1),
                wake_node(1, radial, cross + 1),
            )
            cell = _best_positive_cgrid_hex_orientation(points, lower, upper)
            cells.append(cell)
            if radial == 0:
                patch_by_key[
                    tuple(
                        sorted(
                            (
                                wake_node(0, 0, cross),
                                wake_node(1, 0, cross),
                                wake_node(1, 0, cross + 1),
                                wake_node(0, 0, cross + 1),
                            )
                        )
                    )
                ] = "te_wall"
            if radial == grid.n_radial - 1:
                patch_by_key[
                    tuple(
                        sorted(
                            (
                                wake_node(0, grid.n_radial, cross),
                                wake_node(1, grid.n_radial, cross),
                                wake_node(1, grid.n_radial, cross + 1),
                                wake_node(0, grid.n_radial, cross + 1),
                            )
                        )
                    )
                ] = "outlet"
            patch_by_key[
                tuple(
                    sorted(
                        (
                            wake_node(0, radial, cross),
                            wake_node(0, radial + 1, cross),
                            wake_node(0, radial + 1, cross + 1),
                            wake_node(0, radial, cross + 1),
                        )
                    )
                )
            ] = "tip_left"
            patch_by_key[
                tuple(
                    sorted(
                        (
                            wake_node(1, radial, cross),
                            wake_node(1, radial + 1, cross),
                            wake_node(1, radial + 1, cross + 1),
                            wake_node(1, radial, cross + 1),
                        )
                    )
                )
            ] = "tip_right"

    metadata = {
        "schema_version": "wo006_true_airfoil_extruded_section_cgrid.v1",
        "case_id": case_id,
        "station_count": 2,
        "span_cells": 1,
        "n_path": grid.n_path,
        "n_radial": grid.n_radial,
        "wake_cross_cells": wake_cross_cells,
        "first_layer_height_m": first_layer_height_m,
        "farfield_chords": farfield_chords,
        "wake_length_chords": wake_length_chords,
        "near_wall_growth": near_wall_growth,
        "station_wise_grid": "2d_wake_cgrid_open_te_thin_extrusion",
        "wake_block": {
            "status": "internal_fluid_block",
            "streamwise_cells": grid.n_radial,
            "cross_wake_cells": wake_cross_cells,
            "te_wall_from_true_finite_te_gap": grid.metadata["te_gap_m"] > 1.0e-10,
            "near_te_downstream_splay_factor": wake_te_splay_factor,
            "near_te_downstream_splay_layers": wake_te_splay_layers,
        },
        "section_cgrid": grid.metadata,
        "section_quality": section_cgrid_quality(grid),
        "boundary_patch_order": list(CGRID_PATCH_ORDER),
        "boundary_patch_types": SECTION_CGRID_PATCH_TYPES,
    }
    return _assemble_hexa_mesh(
        points=points,
        cells=cells,
        patch_by_key=patch_by_key,
        boundary_patch_order=CGRID_PATCH_ORDER,
        metadata=metadata,
    )


def build_swept_cgrid_mesh(
    stations: Sequence[Station],
    *,
    n_radial: int,
    first_layer_height_m: float,
    farfield_chords: float,
    wake_length_chords: float,
    case_id: str,
    near_wall_growth: float = 1.12,
    wake_cross_cells: int = 4,
    te_normal_blend_points: int | None = None,
    wake_te_splay_factor: float = 0.0,
    wake_te_splay_layers: int = 4,
) -> SweptHexaMesh:
    if len(stations) < 2:
        raise ValueError("at least two stations are required")
    if wake_cross_cells < 1:
        raise ValueError("wake_cross_cells must be at least 1")
    grids = [
        build_section_cgrid(
            station,
            first_layer_height_m=first_layer_height_m,
            n_radial=n_radial,
            farfield_chords=farfield_chords,
            wake_length_chords=wake_length_chords,
            near_wall_growth=near_wall_growth,
            te_normal_blend_points=te_normal_blend_points,
        )
        for station in stations
    ]
    n_path = grids[0].n_path
    if any(grid.n_path != n_path for grid in grids):
        raise ValueError("all swept C-grid stations must share n_path")

    points: list[Point3] = []
    cgrid_point_count = (n_radial + 1) * n_path
    wake_interior_count = (n_radial + 1) * (wake_cross_cells - 1)
    section_stride = cgrid_point_count + wake_interior_count
    for station, grid in zip(stations, grids):
        for radial in range(n_radial + 1):
            for index in range(n_path):
                points.append(transform_section_point(station, grid.points[radial][index]))
        for radial in range(n_radial + 1):
            for cross in range(1, wake_cross_cells):
                point = _wake_interior_point(
                    grid,
                    radial=radial,
                    cross=cross,
                    wake_cross_cells=wake_cross_cells,
                    first_layer_height_m=first_layer_height_m,
                    wake_te_splay_factor=wake_te_splay_factor,
                    wake_te_splay_layers=wake_te_splay_layers,
                )
                points.append(
                    transform_section_point(
                        station,
                        point,
                    )
                )

    def node(section: int, radial: int, index: int) -> int:
        return section * section_stride + radial * n_path + index

    def wake_node(section: int, radial: int, cross: int) -> int:
        if cross == 0:
            return node(section, radial, 0)
        if cross == wake_cross_cells:
            return node(section, radial, n_path - 1)
        return (
            section * section_stride
            + cgrid_point_count
            + radial * (wake_cross_cells - 1)
            + cross
            - 1
        )

    cells: list[tuple[int, int, int, int, int, int, int, int]] = []
    patch_by_key: dict[tuple[int, ...], str] = {}
    for section in range(len(stations) - 1):
        for radial in range(n_radial):
            for index in range(n_path - 1):
                lower = (
                    node(section, radial, index),
                    node(section, radial, index + 1),
                    node(section, radial + 1, index + 1),
                    node(section, radial + 1, index),
                )
                upper = (
                    node(section + 1, radial, index),
                    node(section + 1, radial, index + 1),
                    node(section + 1, radial + 1, index + 1),
                    node(section + 1, radial + 1, index),
                )
                cell = _best_positive_cgrid_hex_orientation(points, lower, upper)
                cells.append(cell)
                if radial == 0:
                    patch_by_key[
                        tuple(
                            sorted(
                                (
                                    node(section, 0, index),
                                    node(section + 1, 0, index),
                                    node(section + 1, 0, index + 1),
                                    node(section, 0, index + 1),
                                )
                            )
                        )
                    ] = grids[section].segment_markers[index]
                if radial == n_radial - 1:
                    patch_by_key[
                        tuple(
                            sorted(
                                (
                                    node(section, radial + 1, index),
                                    node(section + 1, radial + 1, index),
                                    node(section + 1, radial + 1, index + 1),
                                    node(section, radial + 1, index + 1),
                                )
                            )
                        )
                    ] = "farfield"
                if section == 0:
                    patch_by_key[
                        tuple(
                            sorted(
                                (
                                    node(0, radial, index),
                                    node(0, radial, index + 1),
                                    node(0, radial + 1, index + 1),
                                    node(0, radial + 1, index),
                                )
                            )
                        )
                    ] = "tip_left"
                if section == len(stations) - 2:
                    last = len(stations) - 1
                    patch_by_key[
                        tuple(
                            sorted(
                                (
                                    node(last, radial, index),
                                    node(last, radial, index + 1),
                                    node(last, radial + 1, index + 1),
                                    node(last, radial + 1, index),
                                )
                            )
                        )
                    ] = "tip_right"
        for radial in range(n_radial):
            for cross in range(wake_cross_cells):
                lower = (
                    wake_node(section, radial, cross),
                    wake_node(section, radial + 1, cross),
                    wake_node(section, radial + 1, cross + 1),
                    wake_node(section, radial, cross + 1),
                )
                upper = (
                    wake_node(section + 1, radial, cross),
                    wake_node(section + 1, radial + 1, cross),
                    wake_node(section + 1, radial + 1, cross + 1),
                    wake_node(section + 1, radial, cross + 1),
                )
                cell = _best_positive_cgrid_hex_orientation(points, lower, upper)
                cells.append(cell)
                if radial == 0:
                    patch_by_key[
                        tuple(
                            sorted(
                                (
                                    wake_node(section, 0, cross),
                                    wake_node(section + 1, 0, cross),
                                    wake_node(section + 1, 0, cross + 1),
                                    wake_node(section, 0, cross + 1),
                                )
                            )
                        )
                    ] = "te_wall"
                if radial == n_radial - 1:
                    patch_by_key[
                        tuple(
                            sorted(
                                (
                                    wake_node(section, n_radial, cross),
                                    wake_node(section + 1, n_radial, cross),
                                    wake_node(section + 1, n_radial, cross + 1),
                                    wake_node(section, n_radial, cross + 1),
                                )
                            )
                        )
                    ] = "outlet"
                if section == 0:
                    patch_by_key[
                        tuple(
                            sorted(
                                (
                                    wake_node(0, radial, cross),
                                    wake_node(0, radial + 1, cross),
                                    wake_node(0, radial + 1, cross + 1),
                                    wake_node(0, radial, cross + 1),
                                )
                            )
                        )
                    ] = "tip_left"
                if section == len(stations) - 2:
                    last = len(stations) - 1
                    patch_by_key[
                        tuple(
                            sorted(
                                (
                                    wake_node(last, radial, cross),
                                    wake_node(last, radial + 1, cross),
                                    wake_node(last, radial + 1, cross + 1),
                                    wake_node(last, radial, cross + 1),
                                )
                            )
                        )
                    ] = "tip_right"

    metadata = {
        "schema_version": "wo006_true_airfoil_swept_section_cgrid.v1",
        "case_id": case_id,
        "station_count": len(stations),
        "span_cells": len(stations) - 1,
        "n_path": n_path,
        "n_radial": n_radial,
        "wake_cross_cells": wake_cross_cells,
        "first_layer_height_m": first_layer_height_m,
        "farfield_chords": farfield_chords,
        "wake_length_chords": wake_length_chords,
        "near_wall_growth": near_wall_growth,
        "station_wise_grid": "2d_wake_cgrid_swept_bay_by_bay",
        "wake_block": {
            "status": "internal_fluid_block",
            "streamwise_cells": n_radial,
            "cross_wake_cells": wake_cross_cells,
            "te_wall_from_true_finite_te_gap": grids[0].metadata["te_gap_m"] > 1.0e-10,
            "near_te_downstream_splay_factor": wake_te_splay_factor,
            "near_te_downstream_splay_layers": wake_te_splay_layers,
        },
        "section_cgrid": grids[0].metadata,
        "boundary_patch_order": list(CGRID_PATCH_ORDER),
        "boundary_patch_types": CGRID_PATCH_TYPES,
    }
    return _assemble_hexa_mesh(
        points=points,
        cells=cells,
        patch_by_key=patch_by_key,
        boundary_patch_order=CGRID_PATCH_ORDER,
        metadata=metadata,
    )


def _wake_interior_point(
    grid: Any,
    *,
    radial: int,
    cross: int,
    wake_cross_cells: int,
    first_layer_height_m: float,
    wake_te_splay_factor: float,
    wake_te_splay_layers: int,
) -> tuple[float, float]:
    upper = grid.points[radial][0]
    lower = grid.points[radial][-1]
    t = cross / wake_cross_cells
    x = upper[0] + t * (lower[0] - upper[0])
    z = upper[1] + t * (lower[1] - upper[1])
    if radial > 0 and wake_te_splay_factor > 0.0 and wake_te_splay_layers > 0:
        radial_weight = max(0.0, 1.0 - (radial - 1) / wake_te_splay_layers)
        cross_weight = math.sin(math.pi * t)
        x += wake_te_splay_factor * first_layer_height_m * radial_weight * cross_weight
    return (x, z)


def _assemble_hexa_mesh(
    *,
    points: Sequence[Point3],
    cells: Sequence[tuple[int, int, int, int, int, int, int, int]],
    patch_by_key: Mapping[tuple[int, ...], str],
    boundary_patch_order: Sequence[str],
    metadata: dict[str, Any],
) -> SweptHexaMesh:
    face_map: dict[tuple[int, ...], dict[str, Any]] = {}
    nonmanifold_face_count = 0
    for cell_index, cell in enumerate(cells):
        for order in HEX_FACE_NODE_ORDERS:
            face_nodes = tuple(cell[idx] for idx in order)
            key = tuple(sorted(face_nodes))
            patch = patch_by_key.get(key)
            existing = face_map.get(key)
            if existing is None:
                face_map[key] = {
                    "nodes": face_nodes,
                    "owner": cell_index,
                    "neighbour": None,
                    "patch": patch,
                    "count": 1,
                }
                continue
            existing["count"] = int(existing["count"]) + 1
            if existing["neighbour"] is None:
                existing["neighbour"] = cell_index
                existing["patch"] = None
            else:
                nonmanifold_face_count += 1

    records = [
        FaceRecord(
            nodes=tuple(payload["nodes"]),
            owner=int(payload["owner"]),
            neighbour=None if payload["neighbour"] is None else int(payload["neighbour"]),
            patch=None if payload["patch"] is None else str(payload["patch"]),
        )
        for payload in face_map.values()
    ]
    internal = [record for record in records if record.neighbour is not None]
    boundary_by_patch: dict[str, list[FaceRecord]] = {patch: [] for patch in boundary_patch_order}
    unmarked_boundary_face_count = 0
    for record in records:
        if record.neighbour is not None:
            continue
        if record.patch not in boundary_by_patch:
            unmarked_boundary_face_count += 1
            continue
        boundary_by_patch[str(record.patch)].append(record)

    faces: list[tuple[int, ...]] = []
    owner: list[int] = []
    neighbour: list[int] = []
    boundary_ranges: dict[str, dict[str, int]] = {}
    for record in sorted(internal, key=lambda item: (item.owner, item.neighbour or -1)):
        faces.append(record.nodes)
        owner.append(record.owner)
        assert record.neighbour is not None
        neighbour.append(record.neighbour)
    for patch in boundary_patch_order:
        start = len(faces)
        for record in boundary_by_patch[patch]:
            faces.append(record.nodes)
            owner.append(record.owner)
        boundary_ranges[patch] = {
            "startFace": start,
            "nFaces": len(boundary_by_patch[patch]),
        }

    return SweptHexaMesh(
        points=list(points),
        cells=list(cells),
        faces=faces,
        owner=owner,
        neighbour=neighbour,
        boundary_ranges=boundary_ranges,
        boundary_face_counts={patch: boundary_ranges[patch]["nFaces"] for patch in boundary_patch_order},
        metadata=metadata,
        nonmanifold_face_count=nonmanifold_face_count,
        unmarked_boundary_face_count=unmarked_boundary_face_count,
    )


def _best_positive_cgrid_hex_orientation(
    points: Sequence[Point3],
    lower: Sequence[int],
    upper: Sequence[int],
) -> tuple[int, int, int, int, int, int, int, int]:
    direct = _best_positive_hex_orientation(points, lower, upper)
    swapped = _best_positive_hex_orientation(points, upper, lower)
    return max(
        (direct, swapped),
        key=lambda cell: _signed_volume_for_choice(points, cell),
    )


def _signed_volume_for_choice(points: Sequence[Point3], cell: Sequence[int]) -> float:
    # Keep this local instead of exporting the old helper; it is only used to
    # choose between equivalent lower/upper section orderings before face assembly.
    volume = 0.0
    for order in HEX_FACE_NODE_ORDERS:
        face_nodes = [cell[index] for index in order]
        for a, b, c in (
            (face_nodes[0], face_nodes[1], face_nodes[2]),
            (face_nodes[0], face_nodes[2], face_nodes[3]),
        ):
            volume += (
                points[a][0] * (points[b][1] * points[c][2] - points[b][2] * points[c][1])
                - points[a][1] * (points[b][0] * points[c][2] - points[b][2] * points[c][0])
                + points[a][2] * (points[b][0] * points[c][1] - points[b][1] * points[c][0])
            ) / 6.0
    return volume


def _orient_face_outward(
    points: Sequence[Point3],
    cell: Sequence[int],
    face_nodes: tuple[int, ...],
) -> tuple[int, ...]:
    face_center = _centroid([points[index] for index in face_nodes])
    cell_center = _centroid([points[index] for index in cell])
    normal = _face_normal([points[index] for index in face_nodes])
    direction = (
        face_center[0] - cell_center[0],
        face_center[1] - cell_center[1],
        face_center[2] - cell_center[2],
    )
    if _dot(normal, direction) < 0.0:
        return tuple(reversed(face_nodes))
    return face_nodes


def _face_normal(points: Sequence[Point3]) -> Point3:
    nx = ny = nz = 0.0
    for left, right in zip(points, [*points[1:], points[0]]):
        nx += (left[1] - right[1]) * (left[2] + right[2])
        ny += (left[2] - right[2]) * (left[0] + right[0])
        nz += (left[0] - right[0]) * (left[1] + right[1])
    return (nx, ny, nz)


def _centroid(points: Sequence[Point3]) -> Point3:
    inv = 1.0 / len(points)
    return (
        sum(point[0] for point in points) * inv,
        sum(point[1] for point in points) * inv,
        sum(point[2] for point in points) * inv,
    )


def _dot(left: Point3, right: Point3) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]
