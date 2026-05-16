from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Sequence

from hpa_meshing.mesh_native.wing_surface import Station

from cfd_rescue.baseline_geometry import interpolate_station


Point2 = tuple[float, float]
Point3 = tuple[float, float, float]


@dataclass(frozen=True)
class SectionOGrid:
    station: Station
    points: tuple[tuple[Point2, ...], ...]
    segment_markers: tuple[str, ...]
    radial_distances_m: tuple[float, ...]
    farfield_distance_m: float

    @property
    def n_perim(self) -> int:
        return len(self.points[0])

    @property
    def n_radial(self) -> int:
        return len(self.points) - 1


def build_section_ogrid(
    station: Station,
    *,
    first_layer_height_m: float = 5.0e-5,
    n_radial: int = 64,
    farfield_chords: float = 10.0,
    near_wall_growth: float = 1.12,
    near_wall_layers: int | None = None,
) -> SectionOGrid:
    if n_radial < 2:
        raise ValueError("n_radial must be at least 2")
    if first_layer_height_m <= 0.0:
        raise ValueError("first_layer_height_m must be positive")
    if farfield_chords <= 0.0:
        raise ValueError("farfield_chords must be positive")
    if len(station.airfoil_xz) < 16:
        raise ValueError("station airfoil loop is too coarse")

    inner = tuple((x * station.chord, z * station.chord) for x, z in station.airfoil_xz)
    center = (0.25 * station.chord, _mean(z for _, z in inner))
    farfield_distance_m = farfield_chords * station.chord
    radial_dist = tuple(
        radial_distances(
            radial_layers=n_radial,
            near_wall_layers=near_wall_layers
            if near_wall_layers is not None
            else max(1, min(n_radial // 2, 40)),
            first_layer_height_m=first_layer_height_m,
            near_wall_growth=near_wall_growth,
            farfield_distance_m=farfield_distance_m,
        )
    )

    normal_directions = tuple(_outward_vertex_directions(inner, center))
    radial_directions = tuple(_circle_param_directions(station.airfoil_xz))
    levels: list[tuple[Point2, ...]] = []
    for distance in radial_dist:
        blend = 0.0 if distance <= first_layer_height_m * 1.01 else _smoothstep(
            distance / farfield_distance_m
        )
        levels.append(
            tuple(
                (
                    (1.0 - blend) * (point[0] + normal[0] * distance)
                    + blend * (center[0] + radial[0] * distance),
                    (1.0 - blend) * (point[1] + normal[1] * distance)
                    + blend * (center[1] + radial[1] * distance),
                )
                for point, normal, radial in zip(
                    inner,
                    normal_directions,
                    radial_directions,
                )
            )
        )

    return SectionOGrid(
        station=station,
        points=tuple(levels),
        segment_markers=tuple(segment_markers(station.airfoil_xz)),
        radial_distances_m=radial_dist,
        farfield_distance_m=farfield_distance_m,
    )


def segment_markers(airfoil_xz: Sequence[tuple[float, float]]) -> list[str]:
    n = len(airfoil_xz)
    le_index = min(range(n), key=lambda idx: airfoil_xz[idx][0])
    markers: list[str] = []
    for index in range(n):
        if index == n - 1:
            markers.append("te_wall")
        elif index < le_index:
            markers.append("wing_upper")
        else:
            markers.append("wing_lower")
    return markers


def section_grid_quality(grid: SectionOGrid) -> dict[str, Any]:
    signed_areas: list[float] = []
    collapsed = 0
    sign: float | None = None
    for radial in range(grid.n_radial):
        for perim in range(grid.n_perim):
            quad = (
                grid.points[radial][perim],
                grid.points[radial][(perim + 1) % grid.n_perim],
                grid.points[radial + 1][(perim + 1) % grid.n_perim],
                grid.points[radial + 1][perim],
            )
            area = _quad_area(quad)
            signed_areas.append(area)
            if sign is None and abs(area) > 1.0e-14:
                sign = 1.0 if area > 0.0 else -1.0
            if abs(area) <= 1.0e-14:
                collapsed += 1
    if sign is None:
        sign = 1.0
    orientation_flips = sum(1 for area in signed_areas if sign * area <= 1.0e-14)
    first_layer = [
        _distance(grid.points[0][idx], grid.points[1][idx])
        for idx in range(grid.n_perim)
    ]
    blockers = []
    if collapsed:
        blockers.append("collapsed_section_cells")
    if _self_intersection_count(grid.points[0]):
        blockers.append("inner_airfoil_self_intersections")
    if _self_intersection_count(grid.points[-1]):
        blockers.append("outer_boundary_self_intersections")
    return {
        "status": "pass" if not blockers else "fail",
        "blockers": blockers,
        "n_perim": grid.n_perim,
        "n_radial": grid.n_radial,
        "negative_or_collapsed_cell_count": collapsed,
        "collapsed_cell_count": collapsed,
        "signed_area_orientation_flip_count": orientation_flips,
        "min_abs_area_m2": min((abs(area) for area in signed_areas), default=0.0),
        "max_abs_area_m2": max((abs(area) for area in signed_areas), default=0.0),
        "first_layer_min_m": min(first_layer),
        "first_layer_max_m": max(first_layer),
        "first_layer_mean_m": sum(first_layer) / len(first_layer),
        "inner_self_intersection_count": _self_intersection_count(grid.points[0]),
        "outer_self_intersection_count": _self_intersection_count(grid.points[-1]),
    }


def transform_section_point(station: Station, point: Point2) -> Point3:
    theta = math.radians(station.twist_deg)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    twist_axis = station.chord * 0.25
    x, z = point
    x_rot = twist_axis + cos_theta * (x - twist_axis) + sin_theta * z
    z_rot = -sin_theta * (x - twist_axis) + cos_theta * z
    return (station.x_le + x_rot, station.y, station.z_le + z_rot)


def radial_distances(
    *,
    radial_layers: int,
    near_wall_layers: int,
    first_layer_height_m: float,
    near_wall_growth: float,
    farfield_distance_m: float,
) -> list[float]:
    near_count = min(max(1, near_wall_layers), radial_layers)
    increments = [first_layer_height_m * (near_wall_growth**idx) for idx in range(near_count)]
    remaining_count = radial_layers - near_count
    near_distance = sum(increments)
    if remaining_count > 0:
        remaining_distance = farfield_distance_m - near_distance
        if remaining_distance <= 0.0:
            raise ValueError("farfield distance must exceed near-wall distance")
        start = increments[-1]
        growth = _solve_growth_for_distance(
            first_increment=start,
            count=remaining_count,
            total_distance=remaining_distance,
        )
        increments.extend(start * (growth ** (idx + 1)) for idx in range(remaining_count))
    distances = [0.0]
    total = 0.0
    for increment in increments:
        total += increment
        distances.append(total)
    return distances


def _solve_growth_for_distance(
    *,
    first_increment: float,
    count: int,
    total_distance: float,
) -> float:
    if count <= 0:
        return 1.0
    if count == 1:
        return total_distance / first_increment
    lo = 1.0
    hi = 2.0
    while _geometric_sum(first_increment, hi, count) < total_distance:
        hi *= 1.5
        if hi > 100.0:
            break
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _geometric_sum(first_increment, mid, count) < total_distance:
            lo = mid
        else:
            hi = mid
    return hi


def _geometric_sum(first: float, ratio: float, count: int) -> float:
    if abs(ratio - 1.0) < 1.0e-12:
        return first * count
    return first * ratio * (ratio**count - 1.0) / (ratio - 1.0)


def _ray_direction(point: Point2, center: Point2) -> Point2:
    dx = point[0] - center[0]
    dz = point[1] - center[1]
    length = math.hypot(dx, dz)
    if length <= 1.0e-14:
        return (1.0, 0.0)
    return (dx / length, dz / length)


def _circle_param_directions(airfoil_xz: Sequence[tuple[float, float]]) -> list[Point2]:
    n = len(airfoil_xz)
    le_index = min(range(n), key=lambda idx: airfoil_xz[idx][0])
    directions: list[Point2] = []
    for index in range(n):
        if index <= le_index:
            theta = math.pi * index / max(le_index, 1)
        else:
            theta = math.pi + math.pi * (index - le_index) / max(n - le_index, 1)
        directions.append((math.cos(theta), math.sin(theta)))
    return directions


def _smoothstep(value: float) -> float:
    x = min(1.0, max(0.0, value))
    return x * x * (3.0 - 2.0 * x)


def _outward_vertex_directions(points: Sequence[Point2], center: Point2) -> list[Point2]:
    area = _quad_area(points)
    outward_sign = 1.0 if area > 0.0 else -1.0
    directions: list[Point2] = []
    n = len(points)
    for index in range(n):
        prev_point = points[(index - 1) % n]
        point = points[index]
        next_point = points[(index + 1) % n]
        normals = []
        for a, b in ((prev_point, point), (point, next_point)):
            tx = b[0] - a[0]
            tz = b[1] - a[1]
            length = math.hypot(tx, tz)
            if length <= 1.0e-14:
                continue
            # For a CCW loop the fluid-side normal is the right-hand normal.
            if outward_sign > 0.0:
                normals.append((tz / length, -tx / length))
            else:
                normals.append((-tz / length, tx / length))
        nx = sum(normal[0] for normal in normals)
        nz = sum(normal[1] for normal in normals)
        length = math.hypot(nx, nz)
        if length <= 1.0e-14:
            directions.append(_ray_direction(point, center))
            continue
        candidate = (nx / length, nz / length)
        radial = _ray_direction(point, center)
        if candidate[0] * radial[0] + candidate[1] * radial[1] < 0.0:
            candidate = (-candidate[0], -candidate[1])
        directions.append(candidate)
    return directions


def _quad_area(points: Sequence[Point2]) -> float:
    return 0.5 * sum(
        a[0] * b[1] - b[0] * a[1]
        for a, b in zip(points, [*points[1:], points[0]])
    )


def _self_intersection_count(points: Sequence[Point2]) -> int:
    count = 0
    n = len(points)
    for i in range(n):
        a0 = points[i]
        a1 = points[(i + 1) % n]
        for j in range(i + 1, n):
            if abs(i - j) <= 1 or {i, j} == {0, n - 1}:
                continue
            b0 = points[j]
            b1 = points[(j + 1) % n]
            if _segments_intersect(a0, a1, b0, b1):
                count += 1
    return count


def _segments_intersect(a0: Point2, a1: Point2, b0: Point2, b1: Point2) -> bool:
    def orient(p: Point2, q: Point2, r: Point2) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1 = orient(a0, a1, b0)
    o2 = orient(a0, a1, b1)
    o3 = orient(b0, b1, a0)
    o4 = orient(b0, b1, a1)
    return (o1 * o2 < -1.0e-14) and (o3 * o4 < -1.0e-14)


def _distance(left: Point2, right: Point2) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def _mean(values: Sequence[float] | Any) -> float:
    values_list = list(values)
    return sum(values_list) / len(values_list)
