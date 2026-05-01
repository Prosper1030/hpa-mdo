from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .wing_surface import (
    Reference,
    Station,
    SurfaceMesh,
    WingSpec,
    build_farfield_box_surface,
    build_wing_surface,
)


@dataclass(frozen=True)
class _AvlMainWingSection:
    x_le: float
    y_le: float
    z_le: float
    chord: float
    incidence_deg: float
    airfoil_xz: tuple[tuple[float, float], ...]


def load_blackcat_main_wing_spec_from_avl(
    avl_path: Path | str,
    *,
    points_per_side: int = 16,
) -> WingSpec:
    """Build a mesh-native full-span main-wing spec from the Black Cat AVL file.

    The AVL file is used here as a repository-owned geometry/reference source:
    it already carries the main-wing section stations, inline airfoil
    coordinates, incidence, and Sref/Cref/Bref. No STEP/BREP/VSP repair route is
    involved.
    """
    if points_per_side < 3:
        raise ValueError("points_per_side must be at least 3")

    path = Path(avl_path)
    lines = _clean_avl_lines(path.read_text(encoding="utf-8"))
    sref, cref, bref = _parse_avl_reference(lines)
    half_sections = _parse_main_wing_sections(lines)
    if len(half_sections) < 2:
        raise ValueError("Main Wing surface must contain at least two sections")
    if abs(half_sections[0].y_le) > 1.0e-9:
        raise ValueError("Expected Black Cat main-wing AVL sections to start at y=0")

    resampled = [
        (
            section,
            _resample_airfoil_loop(section.airfoil_xz, points_per_side=points_per_side),
        )
        for section in half_sections
    ]

    stations: list[Station] = []
    for section, loop in reversed(resampled[1:]):
        stations.append(_station_from_avl_section(section, loop, y=-section.y_le))
    for section, loop in resampled:
        stations.append(_station_from_avl_section(section, loop, y=section.y_le))

    return WingSpec(
        stations=stations,
        side="full",
        te_rule="sharp",
        tip_rule="planar_cap",
        root_rule="full",
        reference=Reference(sref_full=sref, cref=cref, bref_full=bref),
        twist_axis_x=0.25,
    )


def build_blackcat_main_wing_surfaces_from_avl(
    avl_path: Path | str,
    *,
    points_per_side: int = 16,
    farfield_upstream_factor: float = 1.5,
    farfield_downstream_factor: float = 2.0,
    farfield_lateral_factor: float = 1.2,
    farfield_vertical_factor: float = 1.2,
) -> tuple[WingSpec, SurfaceMesh, SurfaceMesh]:
    spec = load_blackcat_main_wing_spec_from_avl(
        avl_path,
        points_per_side=points_per_side,
    )
    wing = build_wing_surface(spec)
    farfield = build_farfield_box_surface(
        wing,
        upstream_factor=farfield_upstream_factor,
        downstream_factor=farfield_downstream_factor,
        lateral_factor=farfield_lateral_factor,
        vertical_factor=farfield_vertical_factor,
    )
    return spec, wing, farfield


def run_blackcat_main_wing_faceted_su2_smoke(
    avl_path: Path | str,
    case_dir: Path | str,
    *,
    points_per_side: int = 8,
    mesh_size: float = 8.0,
    velocity_mps: float = 6.5,
    alpha_deg: float = 0.0,
    max_iterations: int = 3,
    solver: str = "INC_EULER",
    solver_command: str = "SU2_CFD",
    threads: int = 1,
    farfield_upstream_factor: float = 1.5,
    farfield_downstream_factor: float = 2.0,
    farfield_lateral_factor: float = 1.2,
    farfield_vertical_factor: float = 1.2,
) -> dict:
    from .gmsh_polyhedral import run_faceted_volume_su2_smoke

    spec, wing, farfield = build_blackcat_main_wing_surfaces_from_avl(
        avl_path,
        points_per_side=points_per_side,
        farfield_upstream_factor=farfield_upstream_factor,
        farfield_downstream_factor=farfield_downstream_factor,
        farfield_lateral_factor=farfield_lateral_factor,
        farfield_vertical_factor=farfield_vertical_factor,
    )
    report = run_faceted_volume_su2_smoke(
        wing,
        farfield,
        case_dir,
        ref_area=spec.reference.sref_full,
        ref_length=spec.reference.cref,
        mesh_size=mesh_size,
        velocity_mps=velocity_mps,
        alpha_deg=alpha_deg,
        max_iterations=max_iterations,
        solver=solver,
        solver_command=solver_command,
        threads=threads,
    )
    enriched_report = {
        **report,
        "route": "blackcat_main_wing_mesh_native_faceted_su2_smoke",
        "blackcat_source": {
            "avl_path": str(avl_path),
            "points_per_side": points_per_side,
            "station_count": len(spec.stations),
            "points_per_station": len(spec.stations[0].airfoil_xz),
            "reference": {
                "sref_full": spec.reference.sref_full,
                "cref": spec.reference.cref,
                "bref_full": spec.reference.bref_full,
            },
            "surface_metadata": wing.metadata,
            "farfield_metadata": farfield.metadata,
            "farfield_factors": {
                "upstream": farfield_upstream_factor,
                "downstream": farfield_downstream_factor,
                "lateral": farfield_lateral_factor,
                "vertical": farfield_vertical_factor,
            },
        },
    }
    Path(report["report_path"]).write_text(
        json.dumps(enriched_report, indent=2),
        encoding="utf-8",
    )
    return enriched_report


def run_blackcat_main_wing_faceted_refinement_ladder(
    avl_path: Path | str,
    case_dir: Path | str,
    *,
    points_per_side: int = 8,
    mesh_sizes: Sequence[float] = (14.0, 10.0, 8.0),
    target_volume_elements: int = 1_000_000,
    max_volume_elements: int = 250_000,
    write_su2: bool = True,
    farfield_upstream_factor: float = 1.5,
    farfield_downstream_factor: float = 2.0,
    farfield_lateral_factor: float = 1.2,
    farfield_vertical_factor: float = 1.2,
) -> dict:
    from .gmsh_polyhedral import run_faceted_volume_refinement_ladder

    spec, wing, farfield = build_blackcat_main_wing_surfaces_from_avl(
        avl_path,
        points_per_side=points_per_side,
        farfield_upstream_factor=farfield_upstream_factor,
        farfield_downstream_factor=farfield_downstream_factor,
        farfield_lateral_factor=farfield_lateral_factor,
        farfield_vertical_factor=farfield_vertical_factor,
    )
    report = run_faceted_volume_refinement_ladder(
        wing,
        farfield,
        case_dir,
        mesh_sizes=mesh_sizes,
        target_volume_elements=target_volume_elements,
        max_volume_elements=max_volume_elements,
        write_su2=write_su2,
    )
    enriched_report = {
        **report,
        "route": "blackcat_main_wing_mesh_native_faceted_refinement_ladder",
        "blackcat_source": {
            "avl_path": str(avl_path),
            "points_per_side": points_per_side,
            "station_count": len(spec.stations),
            "points_per_station": len(spec.stations[0].airfoil_xz),
            "reference": {
                "sref_full": spec.reference.sref_full,
                "cref": spec.reference.cref,
                "bref_full": spec.reference.bref_full,
            },
            "surface_metadata": wing.metadata,
            "farfield_metadata": farfield.metadata,
            "farfield_factors": {
                "upstream": farfield_upstream_factor,
                "downstream": farfield_downstream_factor,
                "lateral": farfield_lateral_factor,
                "vertical": farfield_vertical_factor,
            },
        },
    }
    Path(report["report_path"]).write_text(
        json.dumps(enriched_report, indent=2),
        encoding="utf-8",
    )
    return enriched_report


def _clean_avl_lines(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.split("!", maxsplit=1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _parse_avl_reference(lines: Sequence[str]) -> tuple[float, float, float]:
    for index, line in enumerate(lines):
        if line.upper().startswith("#SREF"):
            return _float_values(lines[index + 1], 3)
    raise ValueError("AVL reference block #Sref Cref Bref was not found")


def _parse_main_wing_sections(lines: Sequence[str]) -> list[_AvlMainWingSection]:
    sections: list[_AvlMainWingSection] = []
    index = 0
    while index < len(lines):
        if lines[index].upper() != "SURFACE":
            index += 1
            continue
        if index + 1 >= len(lines):
            raise ValueError("AVL SURFACE block is missing a name")
        surface_name = lines[index + 1].strip()
        index += 2
        in_main_wing = surface_name == "Main Wing"

        while index < len(lines) and lines[index].upper() != "SURFACE":
            if in_main_wing and lines[index].upper() == "SECTION":
                section, index = _parse_section(lines, index + 1)
                sections.append(section)
            else:
                index += 1

        if in_main_wing:
            return sections

    raise ValueError("AVL Main Wing surface was not found")


def _parse_section(
    lines: Sequence[str],
    index: int,
) -> tuple[_AvlMainWingSection, int]:
    x_le, y_le, z_le, chord, incidence_deg = _float_values(lines[index], 5)
    index += 1
    airfoil: list[tuple[float, float]] = []

    while index < len(lines) and lines[index].upper() not in {"SECTION", "SURFACE"}:
        token = lines[index].upper()
        if token == "AIRFOIL":
            index += 1
            while index < len(lines):
                coordinate = _try_coordinate(lines[index])
                if coordinate is None:
                    break
                airfoil.append(coordinate)
                index += 1
        else:
            index += 1

    if len(airfoil) < 4:
        raise ValueError("Main Wing SECTION must include inline AIRFOIL coordinates")
    return (
        _AvlMainWingSection(
            x_le=x_le,
            y_le=y_le,
            z_le=z_le,
            chord=chord,
            incidence_deg=incidence_deg,
            airfoil_xz=tuple(airfoil),
        ),
        index,
    )


def _float_values(line: str, count: int) -> tuple[float, ...]:
    values = tuple(float(value) for value in line.split()[:count])
    if len(values) != count:
        raise ValueError(f"Expected {count} numeric values, got: {line!r}")
    return values


def _try_coordinate(line: str) -> tuple[float, float] | None:
    parts = line.split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _resample_airfoil_loop(
    raw_points: Sequence[tuple[float, float]],
    *,
    points_per_side: int,
) -> list[tuple[float, float]]:
    points = _without_trailing_duplicate(raw_points)
    leading_edge_index = min(range(len(points)), key=lambda idx: points[idx][0])
    if leading_edge_index == 0 or leading_edge_index == len(points) - 1:
        raise ValueError("Airfoil loop must run TE-upper -> LE -> TE-lower")

    upper = points[: leading_edge_index + 1]
    lower = points[leading_edge_index:]
    upper_x = _cosine_space_te_to_le(points_per_side)
    lower_x = list(reversed(upper_x))

    upper_loop = [(x, _interp_z(upper, x)) for x in upper_x]
    lower_loop = [(x, _interp_z(lower, x)) for x in lower_x[1:-1]]
    loop = upper_loop + lower_loop
    if len(loop) != 2 * points_per_side - 2:
        raise ValueError("Internal airfoil resampling count mismatch")
    return loop


def _without_trailing_duplicate(
    points: Sequence[tuple[float, float]],
    *,
    tolerance: float = 1.0e-12,
) -> list[tuple[float, float]]:
    cleaned = [(float(x), float(z)) for x, z in points]
    if len(cleaned) >= 2 and _distance_2d(cleaned[0], cleaned[-1]) <= tolerance:
        return cleaned[:-1]
    return cleaned


def _cosine_space_te_to_le(count: int) -> list[float]:
    return [0.5 * (1.0 + math.cos(math.pi * i / (count - 1))) for i in range(count)]


def _interp_z(points: Sequence[tuple[float, float]], x_query: float) -> float:
    ordered = sorted(points, key=lambda item: item[0])
    if x_query <= ordered[0][0]:
        return ordered[0][1]
    if x_query >= ordered[-1][0]:
        return ordered[-1][1]
    for left, right in zip(ordered[:-1], ordered[1:]):
        x_left, z_left = left
        x_right, z_right = right
        if x_left <= x_query <= x_right:
            if abs(x_right - x_left) <= 1.0e-14:
                return 0.5 * (z_left + z_right)
            eta = (x_query - x_left) / (x_right - x_left)
            return z_left + eta * (z_right - z_left)
    raise ValueError(f"Could not interpolate airfoil x-coordinate: {x_query}")


def _station_from_avl_section(
    section: _AvlMainWingSection,
    airfoil_xz: list[tuple[float, float]],
    *,
    y: float,
) -> Station:
    return Station(
        y=y,
        airfoil_xz=airfoil_xz,
        chord=section.chord,
        twist_deg=section.incidence_deg,
        x_le=section.x_le,
        z_le=section.z_le,
    )


def _distance_2d(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])
