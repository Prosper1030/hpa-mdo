from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Literal


TERule = Literal["sharp", "finite_thickness", "blunt"]
TipRule = Literal["planar_cap", "rounded_cap", "pinched"]
RootRule = Literal["full", "symmetry", "wall_cap"]
SideRule = Literal["full", "half"]
Vertex = tuple[float, float, float]


@dataclass(frozen=True)
class Station:
    y: float
    airfoil_xz: list[tuple[float, float]]
    chord: float
    twist_deg: float
    x_le: float = 0.0
    z_le: float = 0.0


@dataclass(frozen=True)
class Reference:
    sref_full: float
    cref: float
    bref_full: float


@dataclass(frozen=True)
class WingSpec:
    stations: list[Station]
    side: SideRule
    te_rule: TERule
    tip_rule: TipRule
    root_rule: RootRule
    reference: Reference
    twist_axis_x: float = 0.25


@dataclass(frozen=True)
class Face:
    nodes: tuple[int, ...]
    marker: str


@dataclass
class SurfaceMesh:
    vertices: list[Vertex]
    faces: list[Face]
    metadata: dict[str, float | int | str] = field(default_factory=dict)

    def marker_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for face in self.faces:
            counts[face.marker] = counts.get(face.marker, 0) + 1
        return counts


def build_wing_surface(spec: WingSpec) -> SurfaceMesh:
    stations = _ordered_stations(spec)
    points_per_station = len(stations[0].airfoil_xz)
    vertices: list[Vertex] = []

    for station in stations:
        if len(station.airfoil_xz) != points_per_station:
            raise ValueError("All station loops must have the same point count")
        vertices.extend(_transform_station(station, spec.twist_axis_x))

    faces: list[Face] = []

    def vid(section: int, point: int) -> int:
        return section * points_per_station + (point % points_per_station)

    for section in range(len(stations) - 1):
        for point in range(points_per_station):
            next_point = (point + 1) % points_per_station
            faces.append(
                Face(
                    nodes=(
                        vid(section, point),
                        vid(section + 1, point),
                        vid(section + 1, next_point),
                        vid(section, next_point),
                    ),
                    marker="wing_wall",
                )
            )

    _append_section_cap(
        vertices,
        faces,
        [vid(0, point) for point in range(points_per_station)],
        marker="wing_wall",
        reverse=True,
    )
    _append_section_cap(
        vertices,
        faces,
        [vid(len(stations) - 1, point) for point in range(points_per_station)],
        marker="wing_wall",
        reverse=False,
    )

    return SurfaceMesh(
        vertices=vertices,
        faces=faces,
        metadata={
            "station_count": len(stations),
            "points_per_station": points_per_station,
            "span_m": stations[-1].y - stations[0].y,
            "planform_area_m2": _planform_area(stations),
            "side": spec.side,
            "te_rule": spec.te_rule,
            "tip_rule": spec.tip_rule,
            "root_rule": spec.root_rule,
        },
    )


def _ordered_stations(spec: WingSpec) -> list[Station]:
    if len(spec.stations) < 2:
        raise ValueError("At least two stations are required")
    if any(station.chord <= 0.0 for station in spec.stations):
        raise ValueError("Station chord must be positive")
    if not spec.stations[0].airfoil_xz:
        raise ValueError("Station airfoil loop must not be empty")
    return list(spec.stations)


def _transform_station(station: Station, twist_axis_x: float) -> list[Vertex]:
    theta = math.radians(station.twist_deg)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    twist_axis = station.chord * twist_axis_x
    transformed: list[Vertex] = []

    for x_norm, z_norm in station.airfoil_xz:
        x = station.chord * x_norm
        z = station.chord * z_norm
        x_rot = twist_axis + cos_theta * (x - twist_axis) + sin_theta * z
        z_rot = -sin_theta * (x - twist_axis) + cos_theta * z
        transformed.append((station.x_le + x_rot, station.y, station.z_le + z_rot))

    return transformed


def _append_section_cap(
    vertices: list[Vertex],
    faces: list[Face],
    boundary: list[int],
    *,
    marker: str,
    reverse: bool,
) -> None:
    center = _centroid([vertices[node] for node in boundary])
    center_index = len(vertices)
    vertices.append(center)

    for index, node in enumerate(boundary):
        next_node = boundary[(index + 1) % len(boundary)]
        tri = (center_index, next_node, node) if reverse else (center_index, node, next_node)
        faces.append(Face(nodes=tri, marker=marker))


def _centroid(points: list[Vertex]) -> Vertex:
    scale = 1.0 / len(points)
    return (
        sum(point[0] for point in points) * scale,
        sum(point[1] for point in points) * scale,
        sum(point[2] for point in points) * scale,
    )


def _planform_area(stations: list[Station]) -> float:
    area = 0.0
    for left, right in zip(stations[:-1], stations[1:]):
        area += (right.y - left.y) * 0.5 * (left.chord + right.chord)
    return area
