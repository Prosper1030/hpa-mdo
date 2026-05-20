from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

from hpa_meshing.mesh_native.wing_surface import Station

from cfd_rescue.section_ogrid import radial_distances


Point2 = tuple[float, float]


@dataclass(frozen=True)
class SectionCGrid:
    station: Station
    points: tuple[tuple[Point2, ...], ...]
    segment_markers: tuple[str, ...]
    radial_distances_m: tuple[float, ...]
    farfield_distance_m: float
    wake_length_m: float
    first_layer_stats: dict[str, float]
    metadata: dict[str, Any]

    @property
    def n_path(self) -> int:
        return len(self.points[0])

    @property
    def n_radial(self) -> int:
        return len(self.points) - 1


def build_section_cgrid(
    station: Station,
    *,
    first_layer_height_m: float = 5.0e-5,
    n_radial: int = 64,
    farfield_chords: float = 10.0,
    wake_length_chords: float = 10.0,
    near_wall_growth: float = 1.12,
    near_wall_layers: int | None = None,
    te_normal_blend_points: int | None = None,
    te_corner_first_layer_growth: float = 2.0,
    te_corner_radial_blend_layers: int = 6,
    te_corner_perim_blend_cells: int = 3,
    lower_te_radial_chord_shift_factor: float = 0.4,
    lower_te_radial_chord_shift_layers: int = 4,
    lower_te_radial_chord_shift_plateau_layers: int = 2,
) -> SectionCGrid:
    if n_radial < 2:
        raise ValueError("n_radial must be at least 2")
    if first_layer_height_m <= 0.0:
        raise ValueError("first_layer_height_m must be positive")
    if farfield_chords <= 0.0 or wake_length_chords <= 0.0:
        raise ValueError("farfield and wake length must be positive")
    if len(station.airfoil_xz) < 16:
        raise ValueError("station airfoil loop is too coarse")
    if te_corner_first_layer_growth < 1.0:
        raise ValueError("te_corner_first_layer_growth must be >= 1.0")
    if te_corner_radial_blend_layers < 0 or te_corner_perim_blend_cells < 0:
        raise ValueError("te_corner_blend_layers and te_corner_perim_blend_cells must be >= 0")
    if lower_te_radial_chord_shift_factor < 0.0:
        raise ValueError("lower_te_radial_chord_shift_factor must be >= 0.0")
    if lower_te_radial_chord_shift_layers < 0:
        raise ValueError("lower_te_radial_chord_shift_layers must be >= 0")
    if lower_te_radial_chord_shift_plateau_layers < 0:
        raise ValueError("lower_te_radial_chord_shift_plateau_layers must be >= 0")

    wall = tuple((x * station.chord, z * station.chord) for x, z in station.airfoil_xz)
    le_index = min(range(len(wall)), key=lambda idx: wall[idx][0])
    farfield_distance_m = farfield_chords * station.chord
    wake_length_m = wake_length_chords * station.chord
    outer = tuple(_c_outer_point(index, len(wall), le_index, station.chord, farfield_distance_m, wake_length_m) for index in range(len(wall)))
    te_blend_points = (
        te_normal_blend_points
        if te_normal_blend_points is not None
        else 1
    )
    normals = tuple(_open_wall_normals(wall, le_index, outer, te_blend_points=te_blend_points))
    radial_dist = tuple(
        radial_distances(
            radial_layers=n_radial,
            near_wall_layers=near_wall_layers if near_wall_layers is not None else max(1, min(n_radial // 2, 40)),
            first_layer_height_m=first_layer_height_m,
            near_wall_growth=near_wall_growth,
            farfield_distance_m=farfield_distance_m,
        )
    )
    normal_stack_layers = min(n_radial - 1, max(8, n_radial // 4))
    normal_stack_distance = radial_dist[normal_stack_layers]

    # WO-006 TE-corner rebalance: at the TE wrap ends the first
    # body/wake interface layer can collapse into a non-planar sliver
    # and fail OpenFOAM's face-pyramid orientation check. Keep the wall
    # coordinates fixed, but widen/blend the first few radial layers at
    # the TE corners so the adjacent owner/neighbour centroids remain
    # on opposite sides of the shared face plane.
    perim_count = len(wall)

    def _te_corner_factor(perim_index: int, radial_index: int) -> float:
        if te_corner_first_layer_growth <= 1.0 + 1e-12:
            return 1.0
        if radial_index <= 0 or radial_index > te_corner_radial_blend_layers:
            return 1.0
        te_distance = min(perim_index, perim_count - 1 - perim_index)
        if te_distance > te_corner_perim_blend_cells:
            return 1.0
        perim_w = (
            (te_corner_perim_blend_cells + 1 - te_distance)
            / (te_corner_perim_blend_cells + 1)
        )
        radial_w = max(
            0.0,
            1.0 - (radial_index - 1) / max(te_corner_radial_blend_layers, 1),
        )
        return 1.0 + perim_w * radial_w * (te_corner_first_layer_growth - 1.0)

    def _lower_te_chord_shift(radial_index: int) -> float:
        if (
            lower_te_radial_chord_shift_factor <= 0.0
            or lower_te_radial_chord_shift_layers <= 0
            or radial_index <= 0
            or radial_index > lower_te_radial_chord_shift_layers
        ):
            return 0.0
        plateau = min(
            max(lower_te_radial_chord_shift_plateau_layers, 0),
            lower_te_radial_chord_shift_layers,
        )
        if radial_index <= plateau:
            radial_w = 1.0
        else:
            radial_w = 0.5 ** (radial_index - plateau)
        return first_layer_height_m * lower_te_radial_chord_shift_factor * max(0.0, radial_w)

    levels: list[tuple[Point2, ...]] = []
    for radial_index in range(n_radial + 1):
        if radial_index == 0:
            levels.append(tuple(wall))
            continue
        if radial_index <= normal_stack_layers:
            level_points: list[Point2] = []
            base_dist = radial_dist[radial_index]
            for perim_idx, (point, normal) in enumerate(zip(wall, normals)):
                factor = _te_corner_factor(perim_idx, radial_index)
                d = base_dist * factor
                x = point[0] + normal[0] * d
                z = point[1] + normal[1] * d
                # WO-006 lower-TE strict-checkMesh fix: the failing
                # face is the first radial column at the lower TE path
                # end. A tiny upstream shift of only O(first layer
                # height) moves the airfoil-perim owner centroid back
                # to the opposite side of the body/wake interface face
                # without changing the wall point or flow definition.
                if perim_idx == perim_count - 1:
                    x -= _lower_te_chord_shift(radial_index)
                level_points.append((x, z))
            levels.append(tuple(level_points))
            continue
        level: list[Point2] = []
        q = (radial_dist[radial_index] - normal_stack_distance) / max(
            radial_dist[-1] - normal_stack_distance,
            first_layer_height_m,
        )
        q = min(max(q, 0.0), 1.0)
        for point, normal, outer_point in zip(wall, normals, outer):
            stack_point = (
                point[0] + normal[0] * normal_stack_distance,
                point[1] + normal[1] * normal_stack_distance,
            )
            level.append(
                (
                    stack_point[0] + q * (outer_point[0] - stack_point[0]),
                    stack_point[1] + q * (outer_point[1] - stack_point[1]),
                )
            )
        levels.append(tuple(level))

    # `first_layer_stats` reports the FIRST-CELL wall-layer thickness per
    # perimeter index. With the TE-corner rebalance active, the first-layer
    # at the TE wrap ends (`index ∈ {0, n_path-1}`) is wider than the
    # base `first_layer_height_m`. Both base and TE-corner values are
    # reported so callers can audit the local widening.
    first_layer = [
        math.hypot(levels[1][idx][0] - levels[0][idx][0], levels[1][idx][1] - levels[0][idx][1])
        for idx in range(len(wall))
    ]
    te_corner_first_layer_max = max(
        first_layer[0], first_layer[-1]
    )
    te_gap = math.hypot(wall[0][0] - wall[-1][0], wall[0][1] - wall[-1][1])
    markers = tuple("airfoil_upper" if index < le_index else "airfoil_lower" for index in range(len(wall) - 1))
    return SectionCGrid(
        station=station,
        points=tuple(levels),
        segment_markers=markers,
        radial_distances_m=radial_dist,
        farfield_distance_m=farfield_distance_m,
        wake_length_m=wake_length_m,
        first_layer_stats={
            "min_m": min(first_layer),
            "max_m": max(first_layer),
            "mean_m": sum(first_layer) / len(first_layer),
            "te_corner_max_m": te_corner_first_layer_max,
            "base_first_layer_height_m": first_layer_height_m,
        },
        metadata={
            "schema_version": "wo006_true_airfoil_section_cgrid.v2",
            "topology": "wake_cgrid_open_te_with_te_corner_rebalance",
            "source_airfoil": "true_baseline_authority",
            "closed_single_loop_ogrid": False,
            "n_path": len(wall),
            "n_segments": len(wall) - 1,
            "n_radial": n_radial,
            "le_index": le_index,
            "te_gap_m": te_gap,
            "te_gap_over_chord": te_gap / station.chord,
            "first_layer_height_m": first_layer_height_m,
            "farfield_chords": farfield_chords,
            "wake_length_chords": wake_length_chords,
            "near_wall_growth": near_wall_growth,
            "normal_stack_layers": normal_stack_layers,
            "te_normal_blend_points": te_blend_points,
            "te_corner_first_layer_growth": te_corner_first_layer_growth,
            "te_corner_radial_blend_layers": te_corner_radial_blend_layers,
            "te_corner_perim_blend_cells": te_corner_perim_blend_cells,
            "lower_te_radial_chord_shift_factor": lower_te_radial_chord_shift_factor,
            "lower_te_radial_chord_shift_layers": lower_te_radial_chord_shift_layers,
            "lower_te_radial_chord_shift_plateau_layers": lower_te_radial_chord_shift_plateau_layers,
            "radial_mapping": "wall_normal_near_wall_stack_then_straight_c_farfield_rays",
        },
    )


def section_cgrid_quality(grid: SectionCGrid) -> dict[str, Any]:
    areas: list[float] = []
    collapsed = 0
    sign: float | None = None
    for radial in range(grid.n_radial):
        for index in range(grid.n_path - 1):
            quad = (
                grid.points[radial][index],
                grid.points[radial][index + 1],
                grid.points[radial + 1][index + 1],
                grid.points[radial + 1][index],
            )
            area = _quad_area(quad)
            areas.append(area)
            if sign is None and abs(area) > 1.0e-14:
                sign = 1.0 if area > 0.0 else -1.0
            if abs(area) <= 1.0e-14:
                collapsed += 1
    if sign is None:
        sign = 1.0
    flips = sum(1 for area in areas if sign * area <= 1.0e-14)
    blockers = []
    if collapsed:
        blockers.append("collapsed_section_cells")
    if flips:
        blockers.append("section_cell_orientation_flips")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "n_path": grid.n_path,
        "n_radial": grid.n_radial,
        "collapsed_cell_count": collapsed,
        "signed_area_orientation_flip_count": flips,
        "min_abs_area_m2": min((abs(area) for area in areas), default=0.0),
        "max_abs_area_m2": max((abs(area) for area in areas), default=0.0),
        "first_layer": grid.first_layer_stats,
        "metadata": grid.metadata,
    }


def _c_outer_point(
    index: int,
    count: int,
    le_index: int,
    chord: float,
    farfield_distance_m: float,
    wake_length_m: float,
) -> Point2:
    x_upstream = -farfield_distance_m
    x_downstream = chord + wake_length_m
    height = farfield_distance_m
    if index <= le_index:
        t = index / max(le_index, 1)
        theta = 0.5 * math.pi * t
        return (
            x_downstream - (x_downstream - x_upstream) * math.sin(theta),
            height * math.cos(theta),
        )
    t = (index - le_index) / max(count - 1 - le_index, 1)
    theta = 0.5 * math.pi * t
    return (
        x_upstream + (x_downstream - x_upstream) * (1.0 - math.cos(theta)),
        -height * math.sin(theta),
    )


def _open_wall_normals(
    points: Sequence[Point2],
    le_index: int,
    outer: Sequence[Point2],
    *,
    te_blend_points: int = 0,
) -> list[Point2]:
    normals: list[Point2] = []
    for index, point in enumerate(points):
        if index == 0:
            tangent = _unit(points[1][0] - point[0], points[1][1] - point[1])
        elif index == len(points) - 1:
            tangent = _unit(point[0] - points[index - 1][0], point[1] - points[index - 1][1])
        else:
            tangent = _unit(points[index + 1][0] - points[index - 1][0], points[index + 1][1] - points[index - 1][1])
        normal = _unit(tangent[1], -tangent[0])
        radial = _unit(outer[index][0] - point[0], outer[index][1] - point[1])
        if index in {0, len(points) - 1}:
            normal = radial
        else:
            te_distance = min(index, len(points) - 1 - index)
            if te_distance <= te_blend_points:
                radial_weight = (te_blend_points + 1 - te_distance) / max(
                    te_blend_points + 1,
                    1,
                )
                normal = _unit(
                    radial_weight * radial[0] + (1.0 - radial_weight) * normal[0],
                    radial_weight * radial[1] + (1.0 - radial_weight) * normal[1],
                )
        if normal[0] * radial[0] + normal[1] * radial[1] < 0.0:
            normal = (-normal[0], -normal[1])
        if index == le_index and normal[0] > 0.0:
            normal = (-normal[0], normal[1])
        normals.append(normal)
    return normals


def _unit(x: float, z: float) -> Point2:
    length = math.hypot(x, z)
    if length <= 1.0e-14:
        return (1.0, 0.0)
    return (x / length, z / length)


def _quad_area(points: Sequence[Point2]) -> float:
    return 0.5 * sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(points, [*points[1:], points[0]])
    )
