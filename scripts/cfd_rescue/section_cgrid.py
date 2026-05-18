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
) -> SectionCGrid:
    if n_radial < 2:
        raise ValueError("n_radial must be at least 2")
    if first_layer_height_m <= 0.0:
        raise ValueError("first_layer_height_m must be positive")
    if farfield_chords <= 0.0 or wake_length_chords <= 0.0:
        raise ValueError("farfield and wake length must be positive")
    if len(station.airfoil_xz) < 16:
        raise ValueError("station airfoil loop is too coarse")

    wall = tuple((x * station.chord, z * station.chord) for x, z in station.airfoil_xz)
    le_index = min(range(len(wall)), key=lambda idx: wall[idx][0])
    farfield_distance_m = farfield_chords * station.chord
    wake_length_m = wake_length_chords * station.chord
    outer = tuple(_c_outer_point(index, len(wall), le_index, station.chord, farfield_distance_m, wake_length_m) for index in range(len(wall)))
    normals = tuple(_open_wall_normals(wall, le_index, outer))
    radial_dist = tuple(
        radial_distances(
            radial_layers=n_radial,
            near_wall_layers=near_wall_layers if near_wall_layers is not None else max(1, min(n_radial // 2, 40)),
            first_layer_height_m=first_layer_height_m,
            near_wall_growth=near_wall_growth,
            farfield_distance_m=farfield_distance_m,
        )
    )

    levels: list[tuple[Point2, ...]] = []
    first_layer_points = [
        (
            point[0] + normal[0] * first_layer_height_m,
            point[1] + normal[1] * first_layer_height_m,
        )
        for point, normal in zip(wall, normals)
    ]
    tail_distances = [
        radial_distances(
            radial_layers=n_radial - 1,
            near_wall_layers=max(
                1,
                (near_wall_layers if near_wall_layers is not None else max(1, min(n_radial // 2, 40))) - 1,
            ),
            first_layer_height_m=first_layer_height_m * near_wall_growth,
            near_wall_growth=near_wall_growth,
            farfield_distance_m=max(
                math.hypot(outer_point[0] - first_point[0], outer_point[1] - first_point[1]),
                first_layer_height_m * 2.0,
            ),
        )
        for first_point, outer_point in zip(first_layer_points, outer)
    ]
    for radial_index in range(n_radial + 1):
        if radial_index == 0:
            levels.append(tuple(wall))
            continue
        if radial_index == 1:
            levels.append(tuple(first_layer_points))
            continue
        level: list[Point2] = []
        for first_point, outer_point, distances in zip(first_layer_points, outer, tail_distances):
            line_length = max(
                math.hypot(outer_point[0] - first_point[0], outer_point[1] - first_point[1]),
                first_layer_height_m,
            )
            q = distances[radial_index - 1] / line_length
            level.append(
                (
                    first_point[0] + q * (outer_point[0] - first_point[0]),
                    first_point[1] + q * (outer_point[1] - first_point[1]),
                )
            )
        levels.append(tuple(level))

    first_layer = [
        math.hypot(levels[1][idx][0] - levels[0][idx][0], levels[1][idx][1] - levels[0][idx][1])
        for idx in range(len(wall))
    ]
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
        },
        metadata={
            "schema_version": "wo006_true_airfoil_section_cgrid.v1",
            "topology": "wake_cgrid_open_te",
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
            "radial_mapping": "wall_normal_first_layer_then_straight_c_farfield_rays",
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


def _open_wall_normals(points: Sequence[Point2], le_index: int, outer: Sequence[Point2]) -> list[Point2]:
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
            normal = _unit(0.7 * normal[0] + 0.3 * radial[0], 0.7 * normal[1] + 0.3 * radial[1])
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
