from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .wing_surface import (
    Reference,
    Station,
    SurfaceMesh,
    WingSpec,
    build_farfield_box_surface,
    build_wing_surface,
)


_SEVERE_QUALITY_WARNINGS = frozenset({"very_low_min_gamma", "very_low_min_sicn"})


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
    spanwise_subdivisions: int = 1,
) -> WingSpec:
    """Build a mesh-native full-span main-wing spec from the Black Cat AVL file.

    The AVL file is used here as a repository-owned geometry/reference source:
    it already carries the main-wing section stations, inline airfoil
    coordinates, incidence, and Sref/Cref/Bref. No STEP/BREP/VSP repair route is
    involved.
    """
    if points_per_side < 3:
        raise ValueError("points_per_side must be at least 3")
    if spanwise_subdivisions < 1:
        raise ValueError("spanwise_subdivisions must be at least 1")

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
    stations = _subdivide_spanwise_stations(stations, spanwise_subdivisions)

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
    spanwise_subdivisions: int = 1,
    farfield_upstream_factor: float = 1.5,
    farfield_downstream_factor: float = 2.0,
    farfield_lateral_factor: float = 1.2,
    farfield_vertical_factor: float = 1.2,
) -> tuple[WingSpec, SurfaceMesh, SurfaceMesh]:
    spec = load_blackcat_main_wing_spec_from_avl(
        avl_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
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
    farfield_mesh_size: float | None = None,
    wing_refinement_radius: float | None = None,
    feature_refinement_size: float | None = None,
    write_su2: bool = True,
    farfield_upstream_factor: float = 1.5,
    farfield_downstream_factor: float = 2.0,
    farfield_lateral_factor: float = 1.2,
    farfield_vertical_factor: float = 1.2,
) -> dict:
    from .gmsh_polyhedral import (
        build_wing_feature_refinement_boxes,
        run_faceted_volume_refinement_ladder,
    )

    spec, wing, farfield = build_blackcat_main_wing_surfaces_from_avl(
        avl_path,
        points_per_side=points_per_side,
        farfield_upstream_factor=farfield_upstream_factor,
        farfield_downstream_factor=farfield_downstream_factor,
        farfield_lateral_factor=farfield_lateral_factor,
        farfield_vertical_factor=farfield_vertical_factor,
    )
    refinement_boxes = (
        build_wing_feature_refinement_boxes(wing, mesh_size=feature_refinement_size)
        if feature_refinement_size is not None
        else None
    )
    report = run_faceted_volume_refinement_ladder(
        wing,
        farfield,
        case_dir,
        mesh_sizes=mesh_sizes,
        target_volume_elements=target_volume_elements,
        max_volume_elements=max_volume_elements,
        farfield_mesh_size=farfield_mesh_size,
        wing_refinement_radius=wing_refinement_radius,
        refinement_boxes=refinement_boxes,
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
            "feature_refinement_size": feature_refinement_size,
            "feature_refinement_box_count": (
                0 if refinement_boxes is None else len(refinement_boxes)
            ),
        },
    }
    Path(report["report_path"]).write_text(
        json.dumps(enriched_report, indent=2),
        encoding="utf-8",
    )
    return enriched_report


def run_blackcat_main_wing_coupled_refinement_ladder(
    avl_path: Path | str,
    case_dir: Path | str,
    *,
    points_per_side_values: Sequence[int] = (6, 8, 12),
    spanwise_subdivision_values: Sequence[int] = (1,),
    mesh_sizes: Sequence[float] = (10.0, 8.0, 6.0),
    target_volume_elements: int = 1_000_000,
    max_volume_elements: int = 250_000,
    farfield_mesh_size: float | None = None,
    wing_refinement_radius: float | None = None,
    feature_refinement_size: float | None = None,
    feature_refinement_size_values: Sequence[float | None] | None = None,
    write_su2: bool = True,
    farfield_upstream_factor: float = 1.5,
    farfield_downstream_factor: float = 2.0,
    farfield_lateral_factor: float = 1.2,
    farfield_vertical_factor: float = 1.2,
) -> dict[str, Any]:
    from .gmsh_polyhedral import (
        build_wing_feature_refinement_boxes,
        write_faceted_volume_mesh,
    )

    if target_volume_elements <= 0:
        raise ValueError("target_volume_elements must be positive")
    if max_volume_elements <= 0:
        raise ValueError("max_volume_elements must be positive")

    ordered_points = sorted(int(value) for value in points_per_side_values)
    ordered_spanwise = sorted(int(value) for value in spanwise_subdivision_values)
    ordered_mesh_sizes = sorted((float(value) for value in mesh_sizes), reverse=True)
    if not ordered_points:
        raise ValueError("points_per_side_values must not be empty")
    if not ordered_spanwise:
        raise ValueError("spanwise_subdivision_values must not be empty")
    if not ordered_mesh_sizes:
        raise ValueError("mesh_sizes must not be empty")
    if any(value < 3 for value in ordered_points):
        raise ValueError("points_per_side_values must all be at least 3")
    if any(value < 1 for value in ordered_spanwise):
        raise ValueError("spanwise_subdivision_values must all be at least 1")
    if any(value <= 0.0 for value in ordered_mesh_sizes):
        raise ValueError("mesh_sizes must all be positive")
    ordered_feature_sizes = _feature_refinement_size_ladder(
        feature_refinement_size=feature_refinement_size,
        feature_refinement_size_values=feature_refinement_size_values,
    )

    ladder_path = Path(case_dir)
    ladder_path.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    selected_case: dict[str, Any] | None = None
    status = "target_not_reached"
    stop = False
    reference_payload: dict[str, Any] | None = None

    for spanwise_subdivisions in ordered_spanwise:
        for points_per_side in ordered_points:
            spec, wing, farfield = build_blackcat_main_wing_surfaces_from_avl(
                avl_path,
                points_per_side=points_per_side,
                spanwise_subdivisions=spanwise_subdivisions,
                farfield_upstream_factor=farfield_upstream_factor,
                farfield_downstream_factor=farfield_downstream_factor,
                farfield_lateral_factor=farfield_lateral_factor,
                farfield_vertical_factor=farfield_vertical_factor,
            )
            if reference_payload is None:
                reference_payload = {
                    "sref_full": spec.reference.sref_full,
                    "cref": spec.reference.cref,
                    "bref_full": spec.reference.bref_full,
                }
            for feature_size in ordered_feature_sizes:
                refinement_boxes = (
                    build_wing_feature_refinement_boxes(wing, mesh_size=feature_size)
                    if feature_size is not None
                    else None
                )

                for mesh_size in ordered_mesh_sizes:
                    case_index = len(cases)
                    mesh_case_path = (
                        ladder_path
                        / (
                            f"{case_index:02d}_span_{spanwise_subdivisions}"
                            f"_pps_{points_per_side}"
                            f"_feat_{_feature_size_slug(feature_size)}"
                            f"_h_{_value_slug(mesh_size)}"
                        )
                    )
                    mesh_case_path.mkdir(parents=True, exist_ok=True)
                    su2_path = mesh_case_path / "mesh.su2" if write_su2 else None
                    mesh_report = write_faceted_volume_mesh(
                        wing,
                        farfield,
                        mesh_case_path / "mesh.msh",
                        su2_path=su2_path,
                        mesh_size=mesh_size,
                        wing_mesh_size=mesh_size,
                        farfield_mesh_size=farfield_mesh_size,
                        wing_refinement_radius=wing_refinement_radius,
                        refinement_boxes=refinement_boxes,
                        production_target_volume_elements=target_volume_elements,
                    )
                    case_report = {
                        **mesh_report,
                        "case_dir": str(mesh_case_path),
                        "spanwise_subdivisions": spanwise_subdivisions,
                        "points_per_side": points_per_side,
                        "points_per_station": len(spec.stations[0].airfoil_xz),
                        "mesh_size": mesh_size,
                        "surface_metadata": wing.metadata,
                        "farfield_metadata": farfield.metadata,
                        "feature_refinement_size": feature_size,
                        "feature_refinement_box_count": (
                            0 if refinement_boxes is None else len(refinement_boxes)
                        ),
                    }
                    cases.append(case_report)

                    if int(case_report["volume_element_count"]) > max_volume_elements:
                        status = "blocked_by_volume_element_guard"
                        stop = True
                        break
                    if int(case_report["volume_element_count"]) >= target_volume_elements:
                        selected_case = case_report
                        status = "target_reached"
                        stop = True
                        break
                if stop:
                    break
            if stop:
                break
        if stop:
            break

    report = {
        "route": "blackcat_main_wing_mesh_native_coupled_refinement_ladder",
        "status": status,
        "report_path": str(ladder_path / "coupled_refinement_ladder_report.json"),
        "target_volume_elements": int(target_volume_elements),
        "max_volume_elements": int(max_volume_elements),
        "points_per_side_values": ordered_points,
        "spanwise_subdivision_values": ordered_spanwise,
        "mesh_sizes": ordered_mesh_sizes,
        "feature_refinement_size": ordered_feature_sizes[0]
        if len(ordered_feature_sizes) == 1
        else None,
        "feature_refinement_size_values": ordered_feature_sizes,
        "selected_case": selected_case,
        "recommended_quality_candidate": _recommended_quality_candidate(cases),
        "quality_warning_cases": _quality_warning_cases(cases),
        "cases": cases,
        "engineering_assessment": {
            "surface_and_volume_refinement_coupled": True,
            "production_scale_target_volume_elements": int(target_volume_elements),
            "budget_guard_volume_elements": int(max_volume_elements),
            "selected_for_cfd_interpretation": status == "target_reached",
            "quality_warnings_present": any(
                case.get("mesh_quality_gate", {}).get("warnings", []) for case in cases
            ),
            "aero_coefficients_interpretable": False,
            "reason": "coupled_refinement_ladder_only_no_converged_su2_solution",
        },
        "blackcat_source": {
            "avl_path": str(avl_path),
            "reference": reference_payload,
            "farfield_factors": {
                "upstream": farfield_upstream_factor,
                "downstream": farfield_downstream_factor,
                "lateral": farfield_lateral_factor,
                "vertical": farfield_vertical_factor,
            },
        },
        "caveats": [
            "spanwise station interpolation is linear between AVL sections",
            "feature boxes are axis-aligned first-pass TE/tip/wake sizing regions",
            "no boundary-layer prism strategy yet",
            "million-scale target is an engineering credibility gate, not a convergence proof",
        ],
    }
    Path(report["report_path"]).write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    return report


def run_blackcat_main_wing_su2_stability_ladder(
    avl_path: Path | str,
    case_dir: Path | str,
    *,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 4,
    mesh_sizes: Sequence[float] = (0.14, 0.09, 0.06),
    feature_refinement_size: float | None = 3.0,
    target_volume_elements: int = 100_000,
    max_volume_elements: int = 500_000,
    farfield_mesh_size: float | None = 18.0,
    wing_refinement_radius: float | None = 12.0,
    coefficient_tolerances: Mapping[str, float] | None = None,
    velocity_mps: float = 6.5,
    alpha_deg: float = 0.0,
    max_iterations: int = 20,
    solver: str = "INC_EULER",
    solver_command: str = "SU2_CFD",
    threads: int = 1,
    case_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from .gmsh_polyhedral import (
        build_wing_feature_refinement_boxes,
        infer_wing_feature_extents,
        run_faceted_volume_su2_smoke,
    )
    from .mesh_stability import select_cheapest_stable_mesh

    if target_volume_elements <= 0:
        raise ValueError("target_volume_elements must be positive")
    if max_volume_elements <= 0:
        raise ValueError("max_volume_elements must be positive")
    ordered_mesh_sizes = sorted((float(value) for value in mesh_sizes), reverse=True)
    if not ordered_mesh_sizes:
        raise ValueError("mesh_sizes must not be empty")
    if any(value <= 0.0 for value in ordered_mesh_sizes):
        raise ValueError("mesh_sizes must all be positive")

    spec, wing, farfield = build_blackcat_main_wing_surfaces_from_avl(
        avl_path,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    refinement_boxes = (
        build_wing_feature_refinement_boxes(wing, mesh_size=feature_refinement_size)
        if feature_refinement_size is not None
        else None
    )
    runner = run_faceted_volume_su2_smoke if case_runner is None else case_runner

    ladder_path = Path(case_dir)
    ladder_path.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for index, mesh_size in enumerate(ordered_mesh_sizes):
        mesh_case_path = ladder_path / (
            f"{index:02d}_span_{spanwise_subdivisions}"
            f"_pps_{points_per_side}"
            f"_feat_{_feature_size_slug(feature_refinement_size)}"
            f"_h_{_value_slug(mesh_size)}"
        )
        run_report = runner(
            wing,
            farfield,
            mesh_case_path,
            ref_area=spec.reference.sref_full,
            ref_length=spec.reference.cref,
            mesh_size=mesh_size,
            wing_mesh_size=mesh_size,
            farfield_mesh_size=farfield_mesh_size,
            wing_refinement_radius=wing_refinement_radius,
            refinement_boxes=refinement_boxes,
            velocity_mps=velocity_mps,
            alpha_deg=alpha_deg,
            max_iterations=max_iterations,
            solver=solver,
            solver_command=solver_command,
            threads=threads,
        )
        mesh_report = run_report.get("mesh_report", {})
        case_report = {
            **run_report,
            "case_name": mesh_case_path.name,
            "case_dir": str(mesh_case_path),
            "mesh_size": mesh_size,
            "spanwise_subdivisions": spanwise_subdivisions,
            "points_per_side": points_per_side,
            "feature_refinement_size": feature_refinement_size,
            "volume_element_count": int(mesh_report.get("volume_element_count", 0)),
            "node_count": int(mesh_report.get("node_count", 0)),
            "mesh_quality_gate": mesh_report.get("mesh_quality_gate"),
        }
        cases.append(case_report)
        if case_report["volume_element_count"] > max_volume_elements:
            break

    stability_selection = select_cheapest_stable_mesh(
        cases,
        coefficient_tolerances=coefficient_tolerances,
    )
    status = (
        "stable_mesh_selected"
        if stability_selection["status"] == "stable_pair_found"
        else "no_stable_mesh"
    )
    report = {
        "route": "blackcat_main_wing_mesh_native_su2_stability_ladder",
        "status": status,
        "report_path": str(ladder_path / "su2_stability_ladder_report.json"),
        "target_volume_elements": int(target_volume_elements),
        "max_volume_elements": int(max_volume_elements),
        "mesh_sizes": ordered_mesh_sizes,
        "feature_extents": infer_wing_feature_extents(wing),
        "size_field_policy": {
            "spanwise_subdivisions": spanwise_subdivisions,
            "points_per_side": points_per_side,
            "feature_refinement_size": feature_refinement_size,
            "farfield_mesh_size": farfield_mesh_size,
            "wing_refinement_radius": wing_refinement_radius,
            "feature_refinement_box_count": (
                0 if refinement_boxes is None else len(refinement_boxes)
            ),
        },
        "runtime": {
            "solver": solver,
            "velocity_mps": velocity_mps,
            "alpha_deg": alpha_deg,
            "max_iterations": max_iterations,
            "threads": threads,
        },
        "stability_selection": stability_selection,
        "cases": cases,
        "engineering_assessment": {
            "aero_coefficients_interpretable": status == "stable_mesh_selected",
            "reason": (
                "adjacent_mesh_coefficients_within_tolerance"
                if status == "stable_mesh_selected"
                else "no_adjacent_mesh_pair_with_stable_coefficients"
            ),
        },
    }
    Path(report["report_path"]).write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )
    return report


def _recommended_quality_candidate(cases: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        gate = case.get("mesh_quality_gate", {})
        warnings = set(gate.get("warnings", []))
        if gate.get("status") != "pass":
            continue
        if warnings.intersection(_SEVERE_QUALITY_WARNINGS):
            continue
        candidates.append(
            {
                **case,
                "case_index": index,
                "selection_policy": "densest_case_without_blockers_or_severe_warnings",
                "excluded_warnings": sorted(_SEVERE_QUALITY_WARNINGS),
            }
        )
    if not candidates:
        return None
    return max(candidates, key=lambda case: int(case["volume_element_count"]))


def _quality_warning_cases(cases: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    warning_cases: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        warnings = case.get("mesh_quality_gate", {}).get("warnings", [])
        if not warnings:
            continue
        quality = case.get("quality_metrics", {})
        gamma_percentiles = quality.get("gamma_percentiles", {})
        warning_cases.append(
            {
                "case_index": index,
                "spanwise_subdivisions": case.get("spanwise_subdivisions"),
                "points_per_side": case.get("points_per_side"),
                "mesh_size": case.get("mesh_size"),
                "volume_element_count": case.get("volume_element_count"),
                "warnings": list(warnings),
                "min_gamma": quality.get("min_gamma"),
                "p01_gamma": gamma_percentiles.get("p01"),
            }
        )
    return warning_cases


def _feature_refinement_size_ladder(
    *,
    feature_refinement_size: float | None,
    feature_refinement_size_values: Sequence[float | None] | None,
) -> list[float | None]:
    if feature_refinement_size_values is None:
        if feature_refinement_size is None:
            return [None]
        if feature_refinement_size <= 0.0:
            raise ValueError("feature_refinement_size must be positive")
        return [float(feature_refinement_size)]
    if feature_refinement_size is not None:
        raise ValueError(
            "Use either feature_refinement_size or feature_refinement_size_values, not both"
        )
    ordered: list[float | None] = []
    numeric_values: list[float] = []
    include_none = False
    for value in feature_refinement_size_values:
        if value is None:
            include_none = True
            continue
        numeric = float(value)
        if numeric <= 0.0:
            raise ValueError("feature_refinement_size_values must be positive or None")
        numeric_values.append(numeric)
    if include_none:
        ordered.append(None)
    ordered.extend(sorted(set(numeric_values), reverse=True))
    if not ordered:
        raise ValueError("feature_refinement_size_values must not be empty")
    return ordered


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


def _subdivide_spanwise_stations(
    stations: list[Station],
    spanwise_subdivisions: int,
) -> list[Station]:
    if spanwise_subdivisions == 1:
        return stations

    refined: list[Station] = []
    for left, right in zip(stations[:-1], stations[1:]):
        refined.append(left)
        for step in range(1, spanwise_subdivisions):
            eta = step / spanwise_subdivisions
            refined.append(_interpolate_station(left, right, eta))
    refined.append(stations[-1])
    return refined


def _interpolate_station(left: Station, right: Station, eta: float) -> Station:
    if len(left.airfoil_xz) != len(right.airfoil_xz):
        raise ValueError("Cannot interpolate stations with different airfoil point counts")
    return Station(
        y=_lerp(left.y, right.y, eta),
        airfoil_xz=[
            (_lerp(left_point[0], right_point[0], eta), _lerp(left_point[1], right_point[1], eta))
            for left_point, right_point in zip(left.airfoil_xz, right.airfoil_xz)
        ],
        chord=_lerp(left.chord, right.chord, eta),
        twist_deg=_lerp(left.twist_deg, right.twist_deg, eta),
        x_le=_lerp(left.x_le, right.x_le, eta),
        z_le=_lerp(left.z_le, right.z_le, eta),
    )


def _lerp(left: float, right: float, eta: float) -> float:
    return float(left) + (float(right) - float(left)) * float(eta)


def _distance_2d(
    left: tuple[float, float],
    right: tuple[float, float],
) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def _value_slug(value: float) -> str:
    return f"{float(value):.6g}".replace("-", "m").replace(".", "p")


def _feature_size_slug(value: float | None) -> str:
    return "none" if value is None else _value_slug(float(value))
