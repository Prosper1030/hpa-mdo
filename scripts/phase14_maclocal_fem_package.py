#!/usr/bin/env python3
"""Phase 14 Mac-local shell FEM route plus APDL Windows handoff package."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
import math
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.phase14_calculix_beam_benchmarks as phase14_bench
from hpa_mdo.hifi.calculix_runner import find_ccx, run_static
from hpa_mdo.hifi.frd_parser import (
    parse_displacement,
    parse_last_field_block,
    parse_nodal_coordinates,
    parse_total_force_from_dat,
)
from hpa_mdo.hifi.gmsh_runner import find_gmsh
from hpa_mdo.structure.calculix_beam_export import (
    BeamMaterial,
    SinglePipeCantileverSpec,
    build_single_pipe_cantilever_spec,
    write_calculix_beam_inp,
)
from hpa_mdo.structure.spar_model import tube_J


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase14_dual_beam_calibration"
DEFAULT_MANIFEST = DEFAULT_OUTPUT_DIR / "benchmark_manifest.csv"


@dataclass(frozen=True)
class TubeShellMeshSpec:
    name: str
    span_m: float
    root_outer_radius_m: float
    tip_outer_radius_m: float
    n_span: int
    n_circumference: int
    mesh_size_m: float


@dataclass(frozen=True)
class ShellElement:
    element_id: int
    element_type: str
    node_ids: tuple[int, ...]


@dataclass(frozen=True)
class TipTorqueLoad:
    node_id: int
    x_m: float
    z_m: float
    force_x_n: float
    force_z_n: float


@dataclass(frozen=True)
class B2ComparisonInputs:
    internal_tip_uz_m: float
    calculix_pipe_tip_uz_m: float
    shell_tip_uz_m: float


@dataclass(frozen=True)
class B2Agreement:
    closer_to: str
    shell_vs_internal_error_pct: float
    shell_vs_calculix_pipe_error_pct: float


@dataclass(frozen=True)
class Phase14ExpectedValue:
    case_id: str
    metric: str
    value: float
    source: str
    tolerance_pct: float
    note: str


@dataclass(frozen=True)
class ApdlWindowsPackage:
    directory: Path
    files: tuple[Path, ...]


@dataclass(frozen=True)
class B2ShellRunRow:
    mesh_id: str
    n_span: int
    n_circumference: int
    shell_element_count: int
    applied_total_fz_n: float
    internal_tip_uz_m: float
    calculix_pipe_tip_uz_m: float | None
    shell_tip_uz_m: float | None
    root_reaction_fz_n: float | None
    reaction_residual_n: float | None
    max_von_mises_pa: float | None
    shell_vs_internal_error_pct: float | None
    shell_vs_calculix_pipe_error_pct: float | None
    convergence_to_fine_pct: float | None
    status: str
    note: str


@dataclass(frozen=True)
class B5TorsionRunRow:
    route: str
    n_span: int | None
    n_circumference: int | None
    applied_torque_n_m: float
    theory_theta_rad: float
    fem_theta_rad: float | None
    theta_error_pct: float | None
    section_force_torque_root_n_m: float | None
    section_force_torque_error_pct: float | None
    max_von_mises_pa: float | None
    status: str
    note: str


@dataclass(frozen=True)
class ConstantTubeVerificationRow:
    case_id: str
    mesh_id: str
    n_span: int
    n_circumference: int
    element_count: int
    load_or_torque: float
    theory_value: float | None
    fem_value: float | None
    error_pct: float | None
    reaction_or_moment_residual: float | None
    mesh_delta_vs_previous_pct: float | None
    mesh_delta_vs_finest_pct: float | None
    max_von_mises_pa: float | None
    status: str
    engineering_note: str


@dataclass(frozen=True)
class B5ShellTorsionHardeningRow:
    variant: str
    mesh_id: str
    n_span: int
    n_circumference: int
    applied_torque_n_m: float
    recovered_torque_n_m: float | None
    theory_theta_rad: float | None
    shell_theta_rad: float | None
    theta_error_pct: float | None
    mesh_delta_vs_previous_pct: float | None
    max_von_mises_pa: float | None
    status: str
    engineering_note: str


@dataclass(frozen=True)
class B2TaperedShellHardeningRow:
    variant: str
    mesh_id: str
    n_span: int
    n_circumference: int
    element_count: int
    tip_uz_avg_m: float | None
    tip_uz_min_m: float | None
    tip_uz_max_m: float | None
    root_reaction_fz_n: float | None
    reaction_residual_n: float | None
    max_von_mises_pa: float | None
    error_vs_internal_pct: float | None
    error_vs_b32r_pipe_pct: float | None
    mesh_delta_vs_previous_pct: float | None
    mesh_delta_vs_finest_pct: float | None
    status: str
    engineering_note: str


def tube_second_moment_i(
    *,
    outer_radius_m: float,
    thickness_m: float,
) -> float:
    inner_radius_m = max(float(outer_radius_m) - float(thickness_m), 0.0)
    return math.pi / 4.0 * (float(outer_radius_m) ** 4 - inner_radius_m**4)


def tube_bending_tip_load_delta(
    *,
    force_n: float,
    span_m: float,
    young_pa: float,
    outer_radius_m: float,
    thickness_m: float,
) -> float:
    inertia_m4 = tube_second_moment_i(
        outer_radius_m=outer_radius_m,
        thickness_m=thickness_m,
    )
    return float(force_n) * float(span_m) ** 3 / (3.0 * float(young_pa) * inertia_m4)


def tube_bending_uniform_load_delta(
    *,
    q_n_per_m: float,
    span_m: float,
    young_pa: float,
    outer_radius_m: float,
    thickness_m: float,
) -> float:
    inertia_m4 = tube_second_moment_i(
        outer_radius_m=outer_radius_m,
        thickness_m=thickness_m,
    )
    return float(q_n_per_m) * float(span_m) ** 4 / (8.0 * float(young_pa) * inertia_m4)


def tube_torsion_theta(
    *,
    torque_n_m: float,
    span_m: float,
    young_pa: float,
    poisson_ratio: float,
    outer_radius_m: float,
    thickness_m: float,
) -> float:
    shear_pa = float(young_pa) / (2.0 * (1.0 + float(poisson_ratio)))
    polar_m4 = float(tube_J(np.asarray([outer_radius_m]), np.asarray([thickness_m]))[0])
    return float(torque_n_m) * float(span_m) / (shear_pa * polar_m4)


def build_structured_tube_shell_mesh(
    spec: TubeShellMeshSpec,
) -> tuple[np.ndarray, list[ShellElement]]:
    """Build a structured quad shell tube mesh with shared ring nodes."""

    if spec.n_span < 1:
        raise ValueError("n_span must be >= 1.")
    if spec.n_circumference < 6:
        raise ValueError("n_circumference must be >= 6.")

    nodes: list[tuple[float, float, float, float]] = []
    node_ids: dict[tuple[int, int], int] = {}
    node_id = 1
    for i_span in range(spec.n_span + 1):
        eta = i_span / spec.n_span
        y_m = eta * spec.span_m
        radius_m = (1.0 - eta) * spec.root_outer_radius_m + eta * spec.tip_outer_radius_m
        for i_circ in range(spec.n_circumference):
            theta = 2.0 * math.pi * i_circ / spec.n_circumference
            x_m = radius_m * math.cos(theta)
            z_m = radius_m * math.sin(theta)
            node_ids[(i_span, i_circ)] = node_id
            nodes.append((float(node_id), x_m, y_m, z_m))
            node_id += 1

    elements: list[ShellElement] = []
    element_id = 1
    for i_span in range(spec.n_span):
        for i_circ in range(spec.n_circumference):
            j_next = (i_circ + 1) % spec.n_circumference
            elements.append(
                ShellElement(
                    element_id=element_id,
                    element_type="S4",
                    node_ids=(
                        node_ids[(i_span, i_circ)],
                        node_ids[(i_span + 1, i_circ)],
                        node_ids[(i_span + 1, j_next)],
                        node_ids[(i_span, j_next)],
                    ),
                )
            )
            element_id += 1
    return np.asarray(nodes, dtype=float), elements


def classify_constant_tube_status(
    *,
    theory_value: float | None,
    fem_value: float | None,
    error_pct: float | None,
    mesh_delta_vs_finest_pct: float | None,
    reaction_or_moment_residual: float | None,
    load_or_torque: float,
) -> str:
    if theory_value is None or fem_value is None or error_pct is None:
        return "SKIP"
    if float(theory_value) * float(fem_value) < 0.0:
        return "FAIL"
    residual = abs(float(reaction_or_moment_residual or 0.0))
    residual_limit = max(1.0e-6, abs(float(load_or_torque)) * 1.0e-3)
    if residual > residual_limit:
        return "FAIL"
    if float(error_pct) <= 5.0 and float(mesh_delta_vs_finest_pct or 0.0) <= 5.0:
        return "PASS"
    if float(error_pct) <= 10.0:
        return "WARN"
    return "FAIL"


def classify_b5_shell_torsion_status(
    *,
    applied_torque_n_m: float,
    recovered_torque_n_m: float | None,
    theta_error_pct: float | None,
    mesh_delta_vs_previous_pct: float | None,
) -> str:
    if theta_error_pct is None:
        return "SKIP"
    if recovered_torque_n_m is not None:
        torque_error = phase14_bench._pct_error(recovered_torque_n_m, applied_torque_n_m)
        if torque_error > 1.0:
            return "FAIL"
    if float(theta_error_pct) <= 10.0 and float(mesh_delta_vs_previous_pct or 0.0) <= 5.0:
        return "PASS"
    if float(theta_error_pct) <= 25.0:
        return "WARN"
    return "FAIL"


def recovered_torque_y_from_tip_loads(loads: Iterable[TipTorqueLoad]) -> float:
    return float(sum(load.z_m * load.force_x_n - load.x_m * load.force_z_n for load in loads))


def _hardening_mesh_specs(
    *,
    prefix: str,
    span_m: float,
    root_outer_radius_m: float,
    tip_outer_radius_m: float,
) -> list[TubeShellMeshSpec]:
    return [
        TubeShellMeshSpec(
            name=f"{prefix}_coarse",
            span_m=span_m,
            root_outer_radius_m=root_outer_radius_m,
            tip_outer_radius_m=tip_outer_radius_m,
            n_span=32,
            n_circumference=32,
            mesh_size_m=0.20,
        ),
        TubeShellMeshSpec(
            name=f"{prefix}_medium",
            span_m=span_m,
            root_outer_radius_m=root_outer_radius_m,
            tip_outer_radius_m=tip_outer_radius_m,
            n_span=64,
            n_circumference=64,
            mesh_size_m=0.10,
        ),
        TubeShellMeshSpec(
            name=f"{prefix}_fine",
            span_m=span_m,
            root_outer_radius_m=root_outer_radius_m,
            tip_outer_radius_m=tip_outer_radius_m,
            n_span=96,
            n_circumference=96,
            mesh_size_m=0.07,
        ),
    ]


def _vertical_tip_ring_loads(
    *,
    nodes: np.ndarray,
    tip_nodes: Iterable[int],
    total_fz_n: float,
) -> list[tuple[int, int, float]]:
    node_ids = [int(node_id) for node_id in tip_nodes]
    if not node_ids:
        raise ValueError("Tip-ring load requires at least one tip node.")
    per_node = float(total_fz_n) / len(node_ids)
    return [(node_id, 3, per_node) for node_id in node_ids]


def _distributed_vertical_loads_by_span_tributary(
    *,
    nodes: np.ndarray,
    root_nodes: set[int],
    total_fz_n: float,
) -> list[tuple[int, int, float]]:
    y_values = sorted({round(float(row[2]), 12) for row in nodes})
    if len(y_values) < 2:
        raise ValueError("Distributed shell loading requires at least two spanwise rings.")
    ring_weights: dict[float, float] = {}
    for idx, y_m in enumerate(y_values):
        if idx == 0:
            width = 0.5 * (y_values[1] - y_values[0])
        elif idx == len(y_values) - 1:
            width = 0.5 * (y_values[-1] - y_values[-2])
        else:
            width = 0.5 * (y_values[idx + 1] - y_values[idx - 1])
        ring_weights[y_m] = width
    non_root_rows = [row for row in nodes if int(row[0]) not in root_nodes]
    active_weight = sum(ring_weights[round(float(row[2]), 12)] for row in non_root_rows)
    if active_weight <= 0.0:
        raise ValueError("No non-root shell nodes available for tributary loading.")
    scale = float(total_fz_n) / active_weight
    return [
        (int(row[0]), 3, scale * ring_weights[round(float(row[2]), 12)])
        for row in non_root_rows
    ]


def _tip_uz_stats_at_y(frd_path: Path, y_m: float) -> tuple[float, float, float]:
    coordinates = parse_nodal_coordinates(frd_path)
    displacements = parse_displacement(frd_path)
    if coordinates.size == 0 or displacements.size == 0:
        raise ValueError(f"No coordinate/displacement output available in {frd_path}.")
    disp_map = {int(row[0]): row for row in displacements}
    offsets = np.abs(coordinates[:, 2] - float(y_m))
    tolerance = max(1.0e-8, float(np.min(offsets)) + 1.0e-8)
    values = [float(disp_map[int(row[0])][3]) for row in coordinates[offsets <= tolerance] if int(row[0]) in disp_map]
    if not values:
        raise ValueError(f"No tip-ring UZ rows found near y={y_m:g} in {frd_path}.")
    return float(np.mean(values)), float(np.min(values)), float(np.max(values))


def _pct_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    denom = max(abs(float(previous)), 1.0e-12)
    return abs(float(current) - float(previous)) / denom * 100.0


def tip_torque_loads_for_ring(nodes: np.ndarray, *, torque_n_m: float) -> list[TipTorqueLoad]:
    """Return self-equilibrated nodal forces that create a torque about +Y."""

    rows = np.asarray(nodes, dtype=float)
    radii = np.hypot(rows[:, 1], rows[:, 3])
    mean_radius = float(np.mean(radii))
    if mean_radius <= 0.0:
        raise ValueError("Tip torque ring radius must be positive.")
    force_per_node = float(torque_n_m) / (rows.shape[0] * mean_radius)
    loads: list[TipTorqueLoad] = []
    for node_id, x_m, _y_m, z_m in rows:
        radius = math.hypot(float(x_m), float(z_m))
        if radius <= 0.0:
            continue
        sin_theta = float(z_m) / radius
        cos_theta = float(x_m) / radius
        loads.append(
            TipTorqueLoad(
                node_id=int(node_id),
                x_m=float(x_m),
                z_m=float(z_m),
                force_x_n=force_per_node * sin_theta,
                force_z_n=-force_per_node * cos_theta,
            )
        )
    return loads


def classify_b2_shell_agreement(inputs: B2ComparisonInputs) -> B2Agreement:
    shell_vs_internal = phase14_bench._pct_error(
        abs(inputs.shell_tip_uz_m),
        abs(inputs.internal_tip_uz_m),
    )
    shell_vs_pipe = phase14_bench._pct_error(
        abs(inputs.shell_tip_uz_m),
        abs(inputs.calculix_pipe_tip_uz_m),
    )
    closer_to = "internal_beam" if shell_vs_internal <= shell_vs_pipe else "calculix_b32r_pipe"
    return B2Agreement(
        closer_to=closer_to,
        shell_vs_internal_error_pct=shell_vs_internal,
        shell_vs_calculix_pipe_error_pct=shell_vs_pipe,
    )


def write_tube_shell_geo(spec: TubeShellMeshSpec, path: str | Path) -> Path:
    """Write a closed triangular shell surface mesh recipe for Gmsh."""

    if spec.n_span < 1:
        raise ValueError("n_span must be >= 1.")
    if spec.n_circumference < 6:
        raise ValueError("n_circumference must be >= 6.")

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    point_ids: dict[tuple[int, int], int] = {}
    lines: list[str] = [
        'SetFactory("Built-in");',
        f"Mesh.CharacteristicLengthMin = {float(spec.mesh_size_m):.9g};",
        f"Mesh.CharacteristicLengthMax = {float(spec.mesh_size_m):.9g};",
        "",
    ]
    point_id = 1
    for i_span in range(spec.n_span + 1):
        eta = i_span / spec.n_span
        y_m = eta * spec.span_m
        radius_m = (1.0 - eta) * spec.root_outer_radius_m + eta * spec.tip_outer_radius_m
        for i_circ in range(spec.n_circumference):
            theta = 2.0 * math.pi * i_circ / spec.n_circumference
            x_m = radius_m * math.cos(theta)
            z_m = radius_m * math.sin(theta)
            point_ids[(i_span, i_circ)] = point_id
            lines.append(
                f"Point({point_id}) = "
                f"{{{x_m:.9g}, {y_m:.9g}, {z_m:.9g}, {float(spec.mesh_size_m):.9g}}};"
            )
            point_id += 1

    edge_ids: dict[tuple[int, int], int] = {}
    line_id = 1

    def oriented_line(a: int, b: int) -> int:
        nonlocal line_id
        key = (min(a, b), max(a, b))
        if key not in edge_ids:
            edge_ids[key] = line_id
            lines.append(f"Line({line_id}) = {{{key[0]}, {key[1]}}};")
            line_id += 1
        signed = edge_ids[key]
        return signed if (a, b) == key else -signed

    surface_ids: list[int] = []
    loop_id = 1
    surface_id = 1
    for i_span in range(spec.n_span):
        for i_circ in range(spec.n_circumference):
            j_next = (i_circ + 1) % spec.n_circumference
            p00 = point_ids[(i_span, i_circ)]
            p10 = point_ids[(i_span + 1, i_circ)]
            p11 = point_ids[(i_span + 1, j_next)]
            p01 = point_ids[(i_span, j_next)]
            for tri in ((p00, p10, p11), (p00, p11, p01)):
                tri_lines = [
                    oriented_line(tri[0], tri[1]),
                    oriented_line(tri[1], tri[2]),
                    oriented_line(tri[2], tri[0]),
                ]
                lines.append(f"Line Loop({loop_id}) = {{{', '.join(str(item) for item in tri_lines)}}};")
                lines.append(f"Plane Surface({surface_id}) = {{{loop_id}}};")
                surface_ids.append(surface_id)
                loop_id += 1
                surface_id += 1

    lines.append("")
    lines.append(f'Physical Surface("TUBE_SHELL") = {{{", ".join(str(item) for item in surface_ids)}}};')
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def write_apdl_windows_package(
    *,
    output_dir: str | Path,
    material: BeamMaterial,
    expected_values: Iterable[Phase14ExpectedValue],
) -> ApdlWindowsPackage:
    """Create the Windows APDL package for non-expert reruns."""

    package_dir = Path(output_dir)
    package_dir.mkdir(parents=True, exist_ok=True)
    expected_rows = tuple(expected_values)

    files = [
        _write_run_all_macro(package_dir),
        _write_apdl_b2_tapered_tube(package_dir, material),
        _write_apdl_b5_single_torsion(package_dir, material),
        _write_apdl_b5_dual_direct_my(package_dir, material),
        _write_apdl_b5_dual_force_couple(package_dir, material),
        _write_apdl_readme(package_dir),
        _write_expected_values_csv(package_dir, expected_rows),
    ]
    return ApdlWindowsPackage(directory=package_dir, files=tuple(files))


def run_phase14_maclocal_fem_route(
    *,
    config_path: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Path]:
    """Run shell-FEM sanity checks and generate APDL handoff artifacts."""

    cfg = phase14_bench.load_config(Path(config_path).resolve())
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    route_dir = output_root / "maclocal_fem_route"
    route_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = phase14_bench._load_manifest_rows(Path(manifest_path).resolve())
    cases = phase14_bench._build_benchmark_cases(cfg=cfg, manifest_rows=manifest_rows)
    b2_case = next(case for case in cases if case.benchmark_id == "B2")
    if not isinstance(b2_case.spec, SinglePipeCantileverSpec):
        raise TypeError("B2 Mac-local shell FEM route expects a single pipe benchmark.")
    material = b2_case.spec.material

    b2_rows = _run_b2_shell_route(cfg=cfg, route_dir=route_dir, b2_spec=b2_case.spec)
    b5_rows = _run_b5_torsion_route(cfg=cfg, route_dir=route_dir, material=material)
    expected_values = _expected_values_from_rows(b2_rows=b2_rows, b5_rows=b5_rows)
    package = write_apdl_windows_package(
        output_dir=output_root / "apdl_windows_package",
        material=material,
        expected_values=expected_values,
    )

    b2_csv = output_root / "b2_shell_fem_convergence.csv"
    b5_csv = output_root / "b5_torsion_fem.csv"
    summary_md = output_root / "phase14_maclocal_fem_summary.md"
    _write_b2_shell_csv(b2_csv, b2_rows)
    _write_b5_torsion_csv(b5_csv, b5_rows)
    _write_route_summary(summary_md, b2_rows=b2_rows, b5_rows=b5_rows, package=package)

    return {
        "b2_csv": b2_csv,
        "b5_csv": b5_csv,
        "summary_md": summary_md,
        "apdl_package_dir": package.directory,
        "expected_values_csv": package.directory / "expected_values.csv",
        "apdl_runner": package.directory / "run_all_phase14.mac",
    }


def run_phase14_maclocal_fem_hardening(
    *,
    config_path: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Path]:
    """Run the Phase 14 Mac-local shell FEM hardening workflow."""

    cfg = phase14_bench.load_config(Path(config_path).resolve())
    output_root = Path(output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    hardening_dir = output_root / "maclocal_fem_hardening"
    hardening_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows = phase14_bench._load_manifest_rows(Path(manifest_path).resolve())
    cases = phase14_bench._build_benchmark_cases(cfg=cfg, manifest_rows=manifest_rows)
    b2_case = next(case for case in cases if case.benchmark_id == "B2")
    if not isinstance(b2_case.spec, SinglePipeCantileverSpec):
        raise TypeError("Phase 14 hardening expects B2 to be a single pipe benchmark.")
    material = b2_case.spec.material

    bending_rows = _run_constant_tube_bending_verification(
        cfg=cfg,
        hardening_dir=hardening_dir,
        material=material,
    )
    torsion_rows = _run_constant_tube_torsion_verification(
        cfg=cfg,
        hardening_dir=hardening_dir,
        material=material,
    )
    b5_rows = _run_b5_shell_torsion_hardening(
        cfg=cfg,
        hardening_dir=hardening_dir,
        material=material,
        constant_torsion_rows=torsion_rows,
    )
    b2_rows = _run_b2_tapered_shell_hardening(
        cfg=cfg,
        hardening_dir=hardening_dir,
        b2_spec=b2_case.spec,
    )

    bending_csv = hardening_dir / "constant_tube_bending.csv"
    bending_md = hardening_dir / "constant_tube_bending.md"
    torsion_csv = hardening_dir / "constant_tube_torsion.csv"
    torsion_md = hardening_dir / "constant_tube_torsion.md"
    b5_csv = hardening_dir / "b5_shell_torsion_hardening.csv"
    b5_md = hardening_dir / "b5_shell_torsion_hardening.md"
    b2_csv = hardening_dir / "b2_tapered_shell_hardening.csv"
    b2_md = hardening_dir / "b2_tapered_shell_hardening.md"
    overnight_md = hardening_dir / "overnight_summary.md"
    write_constant_tube_verification_csv(bending_csv, bending_rows)
    write_constant_tube_markdown(
        bending_md,
        title="Phase 14 Constant Tube Shell Bending Verification",
        rows=bending_rows,
        engineering_summary=(
            "Constant circular tube shell bending benchmark using the Phase 14 material scale. "
            "Closed-form comparisons use cantilever beam formulas and root reaction closure."
        ),
    )
    write_constant_tube_verification_csv(torsion_csv, torsion_rows)
    write_constant_tube_markdown(
        torsion_md,
        title="Phase 14 Constant Tube Shell Torsion Verification",
        rows=torsion_rows,
        engineering_summary=(
            "Constant circular tube shell torsion benchmark using theta = T L / GJ. "
            "The residual column records applied torque reconstruction from the nodal force ring."
        ),
    )
    _write_dataclass_csv(b5_csv, b5_rows, B5ShellTorsionHardeningRow)
    write_b5_shell_torsion_hardening_markdown(b5_md, b5_rows)
    _write_dataclass_csv(b2_csv, b2_rows, B2TaperedShellHardeningRow)
    write_b2_tapered_shell_hardening_markdown(b2_md, b2_rows)
    write_overnight_hardening_summary(
        overnight_md,
        bending_rows=bending_rows,
        torsion_rows=torsion_rows,
        b5_rows=b5_rows,
        b2_rows=b2_rows,
        apdl_package_dir=output_root / "apdl_windows_package",
    )
    return {
        "constant_tube_bending_csv": bending_csv,
        "constant_tube_bending_md": bending_md,
        "constant_tube_torsion_csv": torsion_csv,
        "constant_tube_torsion_md": torsion_md,
        "b5_shell_torsion_hardening_csv": b5_csv,
        "b5_shell_torsion_hardening_md": b5_md,
        "b2_tapered_shell_hardening_csv": b2_csv,
        "b2_tapered_shell_hardening_md": b2_md,
        "overnight_summary_md": overnight_md,
    }


def _constant_tube_mesh_specs() -> list[tuple[str, int, int]]:
    return [
        ("coarse", 32, 32),
        ("medium", 64, 64),
        ("fine", 96, 96),
    ]


def _run_constant_tube_bending_verification(
    *,
    cfg: Any,
    hardening_dir: Path,
    material: BeamMaterial,
) -> list[ConstantTubeVerificationRow]:
    span_m = 10.0
    outer_radius_m = 0.03
    thickness_m = 0.0015
    tip_load_n = -80.0
    q_n_per_m = -8.0
    rows: list[ConstantTubeVerificationRow] = []
    for mesh_id, n_span, n_circ in _constant_tube_mesh_specs():
        spec = TubeShellMeshSpec(
            name=f"constant_tube_{mesh_id}",
            span_m=span_m,
            root_outer_radius_m=outer_radius_m,
            tip_outer_radius_m=outer_radius_m,
            n_span=n_span,
            n_circumference=n_circ,
            mesh_size_m=span_m / n_span,
        )
        rows.append(
            _run_constant_tube_shell_case(
                cfg=cfg,
                case_dir=hardening_dir / "constant_tube_bending" / "tip_load" / mesh_id,
                case_id="A1_constant_tube_tip_load",
                mesh_id=mesh_id,
                mesh_spec=spec,
                material=material,
                root_thickness_m=thickness_m,
                tip_thickness_m=thickness_m,
                loads_builder=lambda nodes, root_nodes, tip_nodes, total=tip_load_n: [
                    (node_id, 3, total / len(tip_nodes)) for node_id in tip_nodes
                ],
                theory_value=tube_bending_tip_load_delta(
                    force_n=tip_load_n,
                    span_m=span_m,
                    young_pa=material.young_pa,
                    outer_radius_m=outer_radius_m,
                    thickness_m=thickness_m,
                ),
                load_or_torque=tip_load_n,
                result_kind="tip_uz",
                engineering_note="Tip-ring load distributed equally over all free-end ring nodes.",
            )
        )
    for mesh_id, n_span, n_circ in _constant_tube_mesh_specs():
        spec = TubeShellMeshSpec(
            name=f"constant_tube_uniform_{mesh_id}",
            span_m=span_m,
            root_outer_radius_m=outer_radius_m,
            tip_outer_radius_m=outer_radius_m,
            n_span=n_span,
            n_circumference=n_circ,
            mesh_size_m=span_m / n_span,
        )
        rows.append(
            _run_constant_tube_shell_case(
                cfg=cfg,
                case_dir=hardening_dir / "constant_tube_bending" / "uniform_load" / mesh_id,
                case_id="A2_constant_tube_uniform_load",
                mesh_id=mesh_id,
                mesh_spec=spec,
                material=material,
                root_thickness_m=thickness_m,
                tip_thickness_m=thickness_m,
                loads_builder=lambda nodes, root_nodes, tip_nodes, total=q_n_per_m * span_m: (
                    _distributed_vertical_loads_for_shell_nodes(
                        nodes=nodes,
                        root_nodes=set(root_nodes),
                        total_fz_n=total,
                    )
                ),
                theory_value=tube_bending_uniform_load_delta(
                    q_n_per_m=q_n_per_m,
                    span_m=span_m,
                    young_pa=material.young_pa,
                    outer_radius_m=outer_radius_m,
                    thickness_m=thickness_m,
                ),
                load_or_torque=q_n_per_m * span_m,
                result_kind="tip_uz",
                engineering_note=(
                    "Uniform span load represented by equivalent nodal vertical loads on non-root shell nodes."
                ),
            )
        )
    return _add_constant_tube_mesh_deltas(rows)


def _run_constant_tube_torsion_verification(
    *,
    cfg: Any,
    hardening_dir: Path,
    material: BeamMaterial,
) -> list[ConstantTubeVerificationRow]:
    span_m = 10.0
    outer_radius_m = 0.03
    thickness_m = 0.0015
    torque_n_m = 100.0
    rows: list[ConstantTubeVerificationRow] = []
    for mesh_id, n_span, n_circ in _constant_tube_mesh_specs():
        spec = TubeShellMeshSpec(
            name=f"constant_tube_torsion_{mesh_id}",
            span_m=span_m,
            root_outer_radius_m=outer_radius_m,
            tip_outer_radius_m=outer_radius_m,
            n_span=n_span,
            n_circumference=n_circ,
            mesh_size_m=span_m / n_span,
        )

        def build_torque_loads(
            nodes: np.ndarray,
            root_nodes: list[int],
            tip_nodes: list[int],
            *,
            torque: float = torque_n_m,
        ) -> list[tuple[int, int, float]]:
            _ = root_nodes
            ring_loads = tip_torque_loads_for_ring(_rows_for_node_ids(nodes, tip_nodes), torque_n_m=torque)
            loads: list[tuple[int, int, float]] = []
            for load in ring_loads:
                loads.append((load.node_id, 1, load.force_x_n))
                loads.append((load.node_id, 3, load.force_z_n))
            return loads

        rows.append(
            _run_constant_tube_shell_case(
                cfg=cfg,
                case_dir=hardening_dir / "constant_tube_torsion" / mesh_id,
                case_id="A3_constant_tube_tip_torque",
                mesh_id=mesh_id,
                mesh_spec=spec,
                material=material,
                root_thickness_m=thickness_m,
                tip_thickness_m=thickness_m,
                loads_builder=build_torque_loads,
                theory_value=tube_torsion_theta(
                    torque_n_m=torque_n_m,
                    span_m=span_m,
                    young_pa=material.young_pa,
                    poisson_ratio=material.poisson_ratio,
                    outer_radius_m=outer_radius_m,
                    thickness_m=thickness_m,
                ),
                load_or_torque=torque_n_m,
                result_kind="tip_twist",
                engineering_note=(
                    "Tip torque applied as self-equilibrated tangential force ring; twist uses all tip-ring nodes."
                ),
            )
        )
    return _add_constant_tube_mesh_deltas(rows)


def _run_constant_tube_shell_case(
    *,
    cfg: Any,
    case_dir: Path,
    case_id: str,
    mesh_id: str,
    mesh_spec: TubeShellMeshSpec,
    material: BeamMaterial,
    root_thickness_m: float,
    tip_thickness_m: float,
    loads_builder: Any,
    theory_value: float,
    load_or_torque: float,
    result_kind: str,
    engineering_note: str,
) -> ConstantTubeVerificationRow:
    nodes, elements = build_structured_tube_shell_mesh(mesh_spec)
    if find_ccx(cfg) is None:
        return ConstantTubeVerificationRow(
            case_id=case_id,
            mesh_id=mesh_id,
            n_span=mesh_spec.n_span,
            n_circumference=mesh_spec.n_circumference,
            element_count=len(elements),
            load_or_torque=load_or_torque,
            theory_value=theory_value,
            fem_value=None,
            error_pct=None,
            reaction_or_moment_residual=None,
            mesh_delta_vs_previous_pct=None,
            mesh_delta_vs_finest_pct=None,
            max_von_mises_pa=None,
            status="SKIP",
            engineering_note="CalculiX unavailable; structured shell deck was not run.",
        )

    root_nodes = _nodes_at_y(nodes, 0.0)
    tip_nodes = _nodes_at_y(nodes, mesh_spec.span_m)
    loads = list(loads_builder(nodes, root_nodes, tip_nodes))
    static_inp = case_dir / f"{case_id}_{mesh_id}.inp"
    _write_shell_static_inp(
        static_inp,
        nodes=nodes,
        elements=elements,
        material=material,
        root_nodes=root_nodes,
        loads=loads,
        span_m=mesh_spec.span_m,
        root_thickness_m=root_thickness_m,
        tip_thickness_m=tip_thickness_m,
        output_stress=True,
    )
    payload = run_static(static_inp, cfg)
    if payload.get("error"):
        return ConstantTubeVerificationRow(
            case_id=case_id,
            mesh_id=mesh_id,
            n_span=mesh_spec.n_span,
            n_circumference=mesh_spec.n_circumference,
            element_count=len(elements),
            load_or_torque=load_or_torque,
            theory_value=theory_value,
            fem_value=None,
            error_pct=None,
            reaction_or_moment_residual=None,
            mesh_delta_vs_previous_pct=None,
            mesh_delta_vs_finest_pct=None,
            max_von_mises_pa=None,
            status="WARN",
            engineering_note=f"{engineering_note} Solver failed: {payload['error']}",
        )

    frd_path = Path(payload["frd"])
    dat_path = Path(payload["dat"])
    if result_kind == "tip_uz":
        fem_value = _average_uz_at_y(frd_path, mesh_spec.span_m)
        root_force = parse_total_force_from_dat(dat_path, "ROOT")
        root_reaction_fz_n = None if root_force is None else float(root_force[2])
        applied_total = float(sum(value for _node_id, dof, value in loads if dof == 3))
        residual = None if root_reaction_fz_n is None else root_reaction_fz_n + applied_total
    elif result_kind == "tip_twist":
        fem_value = _tip_ring_twist_from_frd(frd_path, span_m=mesh_spec.span_m)
        tip_force_rows = {
            (node_id, dof): value
            for node_id, dof, value in loads
            if dof in {1, 3}
        }
        tip_rows = _rows_for_node_ids(nodes, tip_nodes)
        recovered_torque = 0.0
        for node_id, x_m, _y_m, z_m in tip_rows:
            fx = float(tip_force_rows.get((int(node_id), 1), 0.0))
            fz = float(tip_force_rows.get((int(node_id), 3), 0.0))
            recovered_torque += float(z_m) * fx - float(x_m) * fz
        residual = recovered_torque - load_or_torque
    else:
        raise ValueError(f"Unsupported constant tube result kind: {result_kind}")

    error_pct = phase14_bench._pct_error(abs(fem_value), abs(theory_value))
    status = classify_constant_tube_status(
        theory_value=theory_value,
        fem_value=fem_value,
        error_pct=error_pct,
        mesh_delta_vs_finest_pct=None,
        reaction_or_moment_residual=residual,
        load_or_torque=load_or_torque,
    )
    return ConstantTubeVerificationRow(
        case_id=case_id,
        mesh_id=mesh_id,
        n_span=mesh_spec.n_span,
        n_circumference=mesh_spec.n_circumference,
        element_count=len(elements),
        load_or_torque=load_or_torque,
        theory_value=theory_value,
        fem_value=fem_value,
        error_pct=error_pct,
        reaction_or_moment_residual=residual,
        mesh_delta_vs_previous_pct=None,
        mesh_delta_vs_finest_pct=None,
        max_von_mises_pa=_max_von_mises_from_frd(frd_path),
        status=status,
        engineering_note=engineering_note,
    )


def _add_constant_tube_mesh_deltas(
    rows: list[ConstantTubeVerificationRow],
) -> list[ConstantTubeVerificationRow]:
    finest_by_case: dict[str, float] = {}
    for row in rows:
        if row.fem_value is not None:
            finest_by_case[row.case_id] = row.fem_value

    previous_by_case: dict[str, float] = {}
    updated: list[ConstantTubeVerificationRow] = []
    for row in rows:
        previous = previous_by_case.get(row.case_id)
        finest = finest_by_case.get(row.case_id)
        delta_previous = (
            None
            if previous is None or row.fem_value is None
            else phase14_bench._pct_error(abs(row.fem_value), abs(previous))
        )
        delta_finest = (
            None
            if finest is None or row.fem_value is None
            else phase14_bench._pct_error(abs(row.fem_value), abs(finest))
        )
        status = classify_constant_tube_status(
            theory_value=row.theory_value,
            fem_value=row.fem_value,
            error_pct=row.error_pct,
            mesh_delta_vs_finest_pct=delta_finest,
            reaction_or_moment_residual=row.reaction_or_moment_residual,
            load_or_torque=row.load_or_torque,
        )
        updated.append(
            ConstantTubeVerificationRow(
                **{
                    **row.__dict__,
                    "mesh_delta_vs_previous_pct": delta_previous,
                    "mesh_delta_vs_finest_pct": delta_finest,
                    "status": status,
                }
            )
        )
        if row.fem_value is not None:
            previous_by_case[row.case_id] = row.fem_value
    return updated


def _run_b5_shell_torsion_hardening(
    *,
    cfg: Any,
    hardening_dir: Path,
    material: BeamMaterial,
    constant_torsion_rows: list[ConstantTubeVerificationRow],
) -> list[B5ShellTorsionHardeningRow]:
    rows: list[B5ShellTorsionHardeningRow] = []
    for row in constant_torsion_rows:
        recovered_torque = (
            None
            if row.reaction_or_moment_residual is None
            else row.load_or_torque + row.reaction_or_moment_residual
        )
        rows.append(
            B5ShellTorsionHardeningRow(
                variant="structured_s4_end_ring_tangential_root_ring",
                mesh_id=row.mesh_id,
                n_span=row.n_span,
                n_circumference=row.n_circumference,
                applied_torque_n_m=row.load_or_torque,
                recovered_torque_n_m=recovered_torque,
                theory_theta_rad=row.theory_value,
                shell_theta_rad=row.fem_value,
                theta_error_pct=row.error_pct,
                mesh_delta_vs_previous_pct=row.mesh_delta_vs_previous_pct,
                max_von_mises_pa=row.max_von_mises_pa,
                status=classify_b5_shell_torsion_status(
                    applied_torque_n_m=row.load_or_torque,
                    recovered_torque_n_m=recovered_torque,
                    theta_error_pct=row.error_pct,
                    mesh_delta_vs_previous_pct=row.mesh_delta_vs_previous_pct,
                ),
                engineering_note=(
                    "Same controlled S4 constant-tube torsion route as A3; this is the "
                    "physically meaningful replacement for the old single-value shell twist diagnostic."
                ),
            )
        )

    legacy = _run_b5_shell_torsion_case(
        cfg=cfg,
        route_dir=hardening_dir / "_b5_legacy_gmsh_tri_runs",
        material=material,
        span_m=10.0,
        outer_radius_m=0.03,
        thickness_m=0.0015,
        torque_n_m=100.0,
        theory_theta=tube_torsion_theta(
            torque_n_m=100.0,
            span_m=10.0,
            young_pa=material.young_pa,
            poisson_ratio=material.poisson_ratio,
            outer_radius_m=0.03,
            thickness_m=0.0015,
        ),
    )
    rows.append(
        B5ShellTorsionHardeningRow(
            variant="legacy_gmsh_tri_tip_torque_root_ring",
            mesh_id="legacy_32x64",
            n_span=0 if legacy.n_span is None else legacy.n_span,
            n_circumference=0 if legacy.n_circumference is None else legacy.n_circumference,
            applied_torque_n_m=legacy.applied_torque_n_m,
            recovered_torque_n_m=None,
            theory_theta_rad=legacy.theory_theta_rad,
            shell_theta_rad=legacy.fem_theta_rad,
            theta_error_pct=legacy.theta_error_pct,
            mesh_delta_vs_previous_pct=None,
            max_von_mises_pa=legacy.max_von_mises_pa,
            status=classify_b5_shell_torsion_status(
                applied_torque_n_m=legacy.applied_torque_n_m,
                recovered_torque_n_m=None,
                theta_error_pct=legacy.theta_error_pct,
                mesh_delta_vs_previous_pct=None,
            ),
            engineering_note=(
                "Current Gmsh triangular shell route retained as the diagnosed bad baseline; "
                "it uses ring twist measurement but remains far too stiff in torsion."
            ),
        )
    )
    return rows


def _run_b2_tapered_shell_hardening(
    *,
    cfg: Any,
    hardening_dir: Path,
    b2_spec: SinglePipeCantileverSpec,
) -> list[B2TaperedShellHardeningRow]:
    route_dir = hardening_dir / "_b2_gmsh_tri_runs"
    gmsh_rows = _run_b2_shell_route(cfg=cfg, route_dir=route_dir, b2_spec=b2_spec)
    rows = _convert_b2_shell_rows_to_hardening(
        variant="gmsh_tri_root_ring_equal_nonroot_load",
        route_dir=route_dir,
        source_rows=gmsh_rows,
        span_m=float(b2_spec.y_nodes_m[-1] - b2_spec.y_nodes_m[0]),
    )
    rows.extend(
        _run_b2_structured_s4_tapered_rows(
            cfg=cfg,
            hardening_dir=hardening_dir,
            b2_spec=b2_spec,
            internal_tip_uz_m=float(phase14_bench._solve_single_beam_internal(b2_spec)["tip_main_m"]),
            pipe_tip_uz_m=_run_b2_pipe_reference(
                cfg=cfg,
                route_dir=hardening_dir / "_b2_structured_s4_runs",
                b2_spec=b2_spec,
            ),
        )
    )
    return _with_b2_hardening_mesh_deltas(rows)


def _convert_b2_shell_rows_to_hardening(
    *,
    variant: str,
    route_dir: Path,
    source_rows: list[B2ShellRunRow],
    span_m: float,
) -> list[B2TaperedShellHardeningRow]:
    out: list[B2TaperedShellHardeningRow] = []
    previous_tip: float | None = None
    for row in source_rows:
        stats = (row.shell_tip_uz_m, row.shell_tip_uz_m, row.shell_tip_uz_m)
        frd_path = route_dir / "b2_shell" / row.mesh_id / f"{row.mesh_id}_static.frd"
        if frd_path.exists():
            try:
                stats = _tip_uz_stats_at_y(frd_path, span_m)
            except ValueError:
                stats = (row.shell_tip_uz_m, row.shell_tip_uz_m, row.shell_tip_uz_m)
        out.append(
            B2TaperedShellHardeningRow(
                variant=variant,
                mesh_id=row.mesh_id,
                n_span=row.n_span,
                n_circumference=row.n_circumference,
                element_count=row.shell_element_count,
                tip_uz_avg_m=stats[0],
                tip_uz_min_m=stats[1],
                tip_uz_max_m=stats[2],
                root_reaction_fz_n=row.root_reaction_fz_n,
                reaction_residual_n=row.reaction_residual_n,
                max_von_mises_pa=row.max_von_mises_pa,
                error_vs_internal_pct=row.shell_vs_internal_error_pct,
                error_vs_b32r_pipe_pct=row.shell_vs_calculix_pipe_error_pct,
                mesh_delta_vs_previous_pct=_pct_delta(row.shell_tip_uz_m, previous_tip),
                mesh_delta_vs_finest_pct=row.convergence_to_fine_pct,
                status=row.status,
                engineering_note=(
                    "Existing Gmsh triangular tapered shell route. It preserves the current diagnostic baseline "
                    "and uses equal load over all non-root shell nodes."
                ),
            )
        )
        if row.shell_tip_uz_m is not None:
            previous_tip = row.shell_tip_uz_m
    return out


def _run_b2_structured_s4_tapered_rows(
    *,
    cfg: Any,
    hardening_dir: Path,
    b2_spec: SinglePipeCantileverSpec,
    internal_tip_uz_m: float,
    pipe_tip_uz_m: float | None,
) -> list[B2TaperedShellHardeningRow]:
    span_m = float(b2_spec.y_nodes_m[-1] - b2_spec.y_nodes_m[0])
    total_fz_n = float(np.sum(b2_spec.nodal_fz_n))
    specs = _hardening_mesh_specs(
        prefix="b2_structured_s4",
        span_m=span_m,
        root_outer_radius_m=float(b2_spec.outer_radius_m[0]),
        tip_outer_radius_m=float(b2_spec.outer_radius_m[-1]),
    )
    rows = [
        _run_b2_structured_s4_tapered_case(
            cfg=cfg,
            hardening_dir=hardening_dir,
            mesh_spec=spec,
            b2_spec=b2_spec,
            internal_tip_uz_m=internal_tip_uz_m,
            pipe_tip_uz_m=pipe_tip_uz_m,
            total_fz_n=total_fz_n,
        )
        for spec in specs
    ]
    return rows


def _run_b2_structured_s4_tapered_case(
    *,
    cfg: Any,
    hardening_dir: Path,
    mesh_spec: TubeShellMeshSpec,
    b2_spec: SinglePipeCantileverSpec,
    internal_tip_uz_m: float,
    pipe_tip_uz_m: float | None,
    total_fz_n: float,
) -> B2TaperedShellHardeningRow:
    nodes, elements = build_structured_tube_shell_mesh(mesh_spec)
    if find_ccx(cfg) is None:
        return B2TaperedShellHardeningRow(
            variant="structured_s4_root_ring_tributary_load",
            mesh_id=mesh_spec.name,
            n_span=mesh_spec.n_span,
            n_circumference=mesh_spec.n_circumference,
            element_count=len(elements),
            tip_uz_avg_m=None,
            tip_uz_min_m=None,
            tip_uz_max_m=None,
            root_reaction_fz_n=None,
            reaction_residual_n=None,
            max_von_mises_pa=None,
            error_vs_internal_pct=None,
            error_vs_b32r_pipe_pct=None,
            mesh_delta_vs_previous_pct=None,
            mesh_delta_vs_finest_pct=None,
            status="SKIP",
            engineering_note="CalculiX unavailable; structured S4 tapered shell deck was not run.",
        )
    root_nodes = _nodes_at_y(nodes, 0.0)
    loads = _distributed_vertical_loads_by_span_tributary(
        nodes=nodes,
        root_nodes=set(root_nodes),
        total_fz_n=total_fz_n,
    )
    case_dir = hardening_dir / "_b2_structured_s4_runs" / "b2_shell" / mesh_spec.name
    static_inp = case_dir / f"{mesh_spec.name}_static.inp"
    _write_shell_static_inp(
        static_inp,
        nodes=nodes,
        elements=elements,
        material=b2_spec.material,
        root_nodes=root_nodes,
        loads=loads,
        span_m=mesh_spec.span_m,
        root_thickness_m=float(b2_spec.thickness_m[0]),
        tip_thickness_m=float(b2_spec.thickness_m[-1]),
        output_stress=True,
    )
    payload = run_static(static_inp, cfg)
    if payload.get("error"):
        return B2TaperedShellHardeningRow(
            variant="structured_s4_root_ring_tributary_load",
            mesh_id=mesh_spec.name,
            n_span=mesh_spec.n_span,
            n_circumference=mesh_spec.n_circumference,
            element_count=len(elements),
            tip_uz_avg_m=None,
            tip_uz_min_m=None,
            tip_uz_max_m=None,
            root_reaction_fz_n=None,
            reaction_residual_n=None,
            max_von_mises_pa=None,
            error_vs_internal_pct=None,
            error_vs_b32r_pipe_pct=None,
            mesh_delta_vs_previous_pct=None,
            mesh_delta_vs_finest_pct=None,
            status="WARN",
            engineering_note=f"Structured S4 tapered shell run failed: {payload['error']}",
        )
    frd_path = Path(payload["frd"])
    dat_path = Path(payload["dat"])
    tip_avg, tip_min, tip_max = _tip_uz_stats_at_y(frd_path, mesh_spec.span_m)
    root_force = parse_total_force_from_dat(dat_path, "ROOT")
    root_reaction_fz_n = None if root_force is None else float(root_force[2])
    applied_total = float(sum(value for _nid, dof, value in loads if dof == 3))
    reaction_residual = None if root_reaction_fz_n is None else root_reaction_fz_n + applied_total
    error_vs_internal = phase14_bench._pct_error(abs(tip_avg), abs(internal_tip_uz_m))
    error_vs_pipe = None if pipe_tip_uz_m is None else phase14_bench._pct_error(abs(tip_avg), abs(pipe_tip_uz_m))
    best_error = min(error_vs_internal, float("inf") if error_vs_pipe is None else error_vs_pipe)
    status = "PASS" if best_error <= 10.0 else "WARN"
    return B2TaperedShellHardeningRow(
        variant="structured_s4_root_ring_tributary_load",
        mesh_id=mesh_spec.name,
        n_span=mesh_spec.n_span,
        n_circumference=mesh_spec.n_circumference,
        element_count=len(elements),
        tip_uz_avg_m=tip_avg,
        tip_uz_min_m=tip_min,
        tip_uz_max_m=tip_max,
        root_reaction_fz_n=root_reaction_fz_n,
        reaction_residual_n=reaction_residual,
        max_von_mises_pa=_max_von_mises_from_frd(frd_path),
        error_vs_internal_pct=error_vs_internal,
        error_vs_b32r_pipe_pct=error_vs_pipe,
        mesh_delta_vs_previous_pct=None,
        mesh_delta_vs_finest_pct=None,
        status=status,
        engineering_note=(
            "Structured S4 tapered shell route with root-ring clamp and span-tributary vertical load. "
            "This tests whether the old Gmsh triangular shell result was element/load-form sensitive."
        ),
    )


def _with_b2_hardening_mesh_deltas(
    rows: list[B2TaperedShellHardeningRow],
) -> list[B2TaperedShellHardeningRow]:
    finest_by_variant: dict[str, float] = {}
    for row in rows:
        if row.tip_uz_avg_m is not None:
            finest_by_variant[row.variant] = row.tip_uz_avg_m
    previous_by_variant: dict[str, float] = {}
    updated: list[B2TaperedShellHardeningRow] = []
    for row in rows:
        previous = previous_by_variant.get(row.variant)
        finest = finest_by_variant.get(row.variant)
        delta_previous = _pct_delta(row.tip_uz_avg_m, previous)
        delta_finest = _pct_delta(row.tip_uz_avg_m, finest)
        best_error = min(
            float("inf") if row.error_vs_internal_pct is None else row.error_vs_internal_pct,
            float("inf") if row.error_vs_b32r_pipe_pct is None else row.error_vs_b32r_pipe_pct,
        )
        reaction_bad = (
            row.reaction_residual_n is not None
            and abs(row.reaction_residual_n) > max(1.0e-6, abs(float(row.root_reaction_fz_n or 0.0)) * 1.0e-3)
        )
        if row.tip_uz_avg_m is None:
            status = row.status
        elif reaction_bad:
            status = "FAIL"
        elif delta_finest is not None and delta_finest <= 5.0 and best_error <= 10.0:
            status = "PASS"
        else:
            status = "WARN"
        updated.append(
            replace(
                row,
                mesh_delta_vs_previous_pct=delta_previous,
                mesh_delta_vs_finest_pct=delta_finest,
                status=status,
            )
        )
        if row.tip_uz_avg_m is not None:
            previous_by_variant[row.variant] = row.tip_uz_avg_m
    return updated


def _run_b2_shell_route(*, cfg: Any, route_dir: Path, b2_spec: SinglePipeCantileverSpec) -> list[B2ShellRunRow]:
    applied_total_fz_n = float(np.sum(b2_spec.nodal_fz_n))
    internal_tip_uz_m = float(phase14_bench._solve_single_beam_internal(b2_spec)["tip_main_m"])
    pipe_tip_uz_m = _run_b2_pipe_reference(cfg=cfg, route_dir=route_dir, b2_spec=b2_spec)

    mesh_specs = [
        TubeShellMeshSpec(
            name="b2_shell_coarse",
            span_m=float(b2_spec.y_nodes_m[-1] - b2_spec.y_nodes_m[0]),
            root_outer_radius_m=float(b2_spec.outer_radius_m[0]),
            tip_outer_radius_m=float(b2_spec.outer_radius_m[-1]),
            n_span=32,
            n_circumference=32,
            mesh_size_m=0.22,
        ),
        TubeShellMeshSpec(
            name="b2_shell_medium",
            span_m=float(b2_spec.y_nodes_m[-1] - b2_spec.y_nodes_m[0]),
            root_outer_radius_m=float(b2_spec.outer_radius_m[0]),
            tip_outer_radius_m=float(b2_spec.outer_radius_m[-1]),
            n_span=64,
            n_circumference=64,
            mesh_size_m=0.12,
        ),
        TubeShellMeshSpec(
            name="b2_shell_fine",
            span_m=float(b2_spec.y_nodes_m[-1] - b2_spec.y_nodes_m[0]),
            root_outer_radius_m=float(b2_spec.outer_radius_m[0]),
            tip_outer_radius_m=float(b2_spec.outer_radius_m[-1]),
            n_span=96,
            n_circumference=96,
            mesh_size_m=0.08,
        ),
    ]
    rows: list[B2ShellRunRow] = []
    gmsh_path = find_gmsh(cfg)
    ccx_path = find_ccx(cfg)
    for mesh_spec in mesh_specs:
        if gmsh_path is None or ccx_path is None:
            rows.append(
                B2ShellRunRow(
                    mesh_id=mesh_spec.name,
                    n_span=mesh_spec.n_span,
                    n_circumference=mesh_spec.n_circumference,
                    shell_element_count=0,
                    applied_total_fz_n=applied_total_fz_n,
                    internal_tip_uz_m=internal_tip_uz_m,
                    calculix_pipe_tip_uz_m=pipe_tip_uz_m,
                    shell_tip_uz_m=None,
                    root_reaction_fz_n=None,
                    reaction_residual_n=None,
                    max_von_mises_pa=None,
                    shell_vs_internal_error_pct=None,
                    shell_vs_calculix_pipe_error_pct=None,
                    convergence_to_fine_pct=None,
                    status="SKIP",
                    note="Gmsh or CalculiX unavailable; shell FEM deck was not run.",
                )
            )
            continue
        rows.append(
            _run_b2_shell_case(
                cfg=cfg,
                gmsh_path=gmsh_path,
                route_dir=route_dir,
                mesh_spec=mesh_spec,
                b2_spec=b2_spec,
                internal_tip_uz_m=internal_tip_uz_m,
                pipe_tip_uz_m=pipe_tip_uz_m,
            )
        )

    fine_tip = next((row.shell_tip_uz_m for row in reversed(rows) if row.shell_tip_uz_m is not None), None)
    if fine_tip is None:
        return rows
    updated: list[B2ShellRunRow] = []
    for row in rows:
        convergence = (
            None
            if row.shell_tip_uz_m is None
            else phase14_bench._pct_error(abs(row.shell_tip_uz_m), abs(fine_tip))
        )
        updated.append(
            B2ShellRunRow(
                **{
                    **row.__dict__,
                    "convergence_to_fine_pct": convergence,
                }
            )
        )
    return updated


def _run_b2_pipe_reference(*, cfg: Any, route_dir: Path, b2_spec: SinglePipeCantileverSpec) -> float | None:
    if find_ccx(cfg) is None:
        return None
    pipe_dir = route_dir / "b2_pipe_reference"
    deck = write_calculix_beam_inp(b2_spec, pipe_dir / "b2_tapered_b32r_pipe.inp")
    payload = run_static(deck.inp_path, cfg)
    if payload.get("error"):
        return None
    disp = parse_displacement(Path(payload["frd"]))
    return phase14_bench._nodal_uz(disp, deck.node_sets["TIP_MAIN"][0])


def _run_b2_shell_case(
    *,
    cfg: Any,
    gmsh_path: str,
    route_dir: Path,
    mesh_spec: TubeShellMeshSpec,
    b2_spec: SinglePipeCantileverSpec,
    internal_tip_uz_m: float,
    pipe_tip_uz_m: float | None,
) -> B2ShellRunRow:
    case_dir = route_dir / "b2_shell" / mesh_spec.name
    case_dir.mkdir(parents=True, exist_ok=True)
    geo = write_tube_shell_geo(mesh_spec, case_dir / f"{mesh_spec.name}.geo")
    mesh_inp = case_dir / f"{mesh_spec.name}_mesh.inp"
    _run_gmsh_shell_mesh(gmsh_path=gmsh_path, geo_path=geo, mesh_path=mesh_inp)
    nodes, elements = _read_surface_mesh(mesh_inp)
    root_nodes = _nodes_at_y(nodes, 0.0)
    tip_nodes = _nodes_at_y(nodes, mesh_spec.span_m)
    loads = _distributed_vertical_loads_for_shell_nodes(
        nodes=nodes,
        root_nodes=set(root_nodes),
        total_fz_n=float(np.sum(b2_spec.nodal_fz_n)),
    )
    static_inp = case_dir / f"{mesh_spec.name}_static.inp"
    _write_shell_static_inp(
        static_inp,
        nodes=nodes,
        elements=elements,
        material=b2_spec.material,
        root_nodes=root_nodes,
        loads=loads,
        span_m=mesh_spec.span_m,
        root_thickness_m=float(b2_spec.thickness_m[0]),
        tip_thickness_m=float(b2_spec.thickness_m[-1]),
        output_stress=True,
    )
    payload = run_static(static_inp, cfg)
    if payload.get("error"):
        return B2ShellRunRow(
            mesh_id=mesh_spec.name,
            n_span=mesh_spec.n_span,
            n_circumference=mesh_spec.n_circumference,
            shell_element_count=len(elements),
            applied_total_fz_n=float(np.sum(b2_spec.nodal_fz_n)),
            internal_tip_uz_m=internal_tip_uz_m,
            calculix_pipe_tip_uz_m=pipe_tip_uz_m,
            shell_tip_uz_m=None,
            root_reaction_fz_n=None,
            reaction_residual_n=None,
            max_von_mises_pa=None,
            shell_vs_internal_error_pct=None,
            shell_vs_calculix_pipe_error_pct=None,
            convergence_to_fine_pct=None,
            status="WARN",
            note=f"Shell CalculiX run failed: {payload['error']}",
        )
    shell_tip_uz_m = _average_uz_at_y(Path(payload["frd"]), mesh_spec.span_m)
    root_force = parse_total_force_from_dat(Path(payload["dat"]), "ROOT")
    root_reaction_fz_n = None if root_force is None else float(root_force[2])
    applied_total = float(sum(value for _nid, _dof, value in loads if _dof == 3))
    reaction_residual = None if root_reaction_fz_n is None else root_reaction_fz_n + applied_total
    stress = _max_von_mises_from_frd(Path(payload["frd"]))
    shell_vs_internal = phase14_bench._pct_error(abs(shell_tip_uz_m), abs(internal_tip_uz_m))
    shell_vs_pipe = (
        None
        if pipe_tip_uz_m is None
        else phase14_bench._pct_error(abs(shell_tip_uz_m), abs(pipe_tip_uz_m))
    )
    note = "Gmsh shell surface FEM run with spanwise variable shell thickness."
    reaction_closes = reaction_residual is None or abs(reaction_residual) <= max(
        1.0e-6,
        abs(applied_total) * 1.0e-4,
    )
    best_reference_error = min(
        shell_vs_internal,
        float("inf") if shell_vs_pipe is None else shell_vs_pipe,
    )
    status = "PASS" if reaction_closes and best_reference_error <= 10.0 else "WARN"
    if best_reference_error > 10.0:
        note += " Deflection remains warning-grade versus both beam references."
    return B2ShellRunRow(
        mesh_id=mesh_spec.name,
        n_span=mesh_spec.n_span,
        n_circumference=mesh_spec.n_circumference,
        shell_element_count=len(elements),
        applied_total_fz_n=applied_total,
        internal_tip_uz_m=internal_tip_uz_m,
        calculix_pipe_tip_uz_m=pipe_tip_uz_m,
        shell_tip_uz_m=shell_tip_uz_m,
        root_reaction_fz_n=root_reaction_fz_n,
        reaction_residual_n=reaction_residual,
        max_von_mises_pa=stress,
        shell_vs_internal_error_pct=shell_vs_internal,
        shell_vs_calculix_pipe_error_pct=shell_vs_pipe,
        convergence_to_fine_pct=None,
        status=status,
        note=note,
    )


def _run_b5_torsion_route(*, cfg: Any, route_dir: Path, material: BeamMaterial) -> list[B5TorsionRunRow]:
    span_m = 10.0
    outer_radius_m = 0.03
    thickness_m = 0.0015
    torque_n_m = 100.0
    theory_theta = tube_torsion_theta(
        torque_n_m=torque_n_m,
        span_m=span_m,
        young_pa=material.young_pa,
        poisson_ratio=material.poisson_ratio,
        outer_radius_m=outer_radius_m,
        thickness_m=thickness_m,
    )
    rows = [
        _run_b5_shell_torsion_case(
            cfg=cfg,
            route_dir=route_dir,
            material=material,
            span_m=span_m,
            outer_radius_m=outer_radius_m,
            thickness_m=thickness_m,
            torque_n_m=torque_n_m,
            theory_theta=theory_theta,
        ),
        _run_b5_pipe_section_force_case(
            cfg=cfg,
            route_dir=route_dir,
            material=material,
            span_m=span_m,
            outer_radius_m=outer_radius_m,
            thickness_m=thickness_m,
            torque_n_m=torque_n_m,
            theory_theta=theory_theta,
        ),
    ]
    return rows


def _run_b5_shell_torsion_case(
    *,
    cfg: Any,
    route_dir: Path,
    material: BeamMaterial,
    span_m: float,
    outer_radius_m: float,
    thickness_m: float,
    torque_n_m: float,
    theory_theta: float,
) -> B5TorsionRunRow:
    gmsh_path = find_gmsh(cfg)
    if gmsh_path is None or find_ccx(cfg) is None:
        return B5TorsionRunRow(
            route="shell_fem_tip_torque",
            n_span=32,
            n_circumference=64,
            applied_torque_n_m=torque_n_m,
            theory_theta_rad=theory_theta,
            fem_theta_rad=None,
            theta_error_pct=None,
            section_force_torque_root_n_m=None,
            section_force_torque_error_pct=None,
            max_von_mises_pa=None,
            status="SKIP",
            note="Gmsh or CalculiX unavailable.",
        )
    spec = TubeShellMeshSpec(
        name="b5_single_tube_torsion_shell",
        span_m=span_m,
        root_outer_radius_m=outer_radius_m,
        tip_outer_radius_m=outer_radius_m,
        n_span=32,
        n_circumference=64,
        mesh_size_m=0.16,
    )
    case_dir = route_dir / "b5_torsion_shell"
    case_dir.mkdir(parents=True, exist_ok=True)
    geo = write_tube_shell_geo(spec, case_dir / f"{spec.name}.geo")
    mesh_inp = case_dir / f"{spec.name}_mesh.inp"
    _run_gmsh_shell_mesh(gmsh_path=gmsh_path, geo_path=geo, mesh_path=mesh_inp)
    nodes, elements = _read_surface_mesh(mesh_inp)
    root_nodes = _nodes_at_y(nodes, 0.0)
    tip_nodes = _nodes_at_y(nodes, span_m)
    torque_loads = tip_torque_loads_for_ring(_rows_for_node_ids(nodes, tip_nodes), torque_n_m=torque_n_m)
    loads: list[tuple[int, int, float]] = []
    for load in torque_loads:
        loads.append((load.node_id, 1, load.force_x_n))
        loads.append((load.node_id, 3, load.force_z_n))
    static_inp = case_dir / f"{spec.name}_static.inp"
    _write_shell_static_inp(
        static_inp,
        nodes=nodes,
        elements=elements,
        material=material,
        root_nodes=root_nodes,
        loads=loads,
        span_m=span_m,
        root_thickness_m=thickness_m,
        tip_thickness_m=thickness_m,
        output_stress=True,
    )
    payload = run_static(static_inp, cfg)
    if payload.get("error"):
        return B5TorsionRunRow(
            route="shell_fem_tip_torque",
            n_span=spec.n_span,
            n_circumference=spec.n_circumference,
            applied_torque_n_m=torque_n_m,
            theory_theta_rad=theory_theta,
            fem_theta_rad=None,
            theta_error_pct=None,
            section_force_torque_root_n_m=None,
            section_force_torque_error_pct=None,
            max_von_mises_pa=None,
            status="WARN",
            note=f"Shell torsion CalculiX run failed: {payload['error']}",
        )
    theta_fem = _tip_ring_twist_from_frd(Path(payload["frd"]), span_m=span_m)
    theta_error = phase14_bench._pct_error(theta_fem, theory_theta)
    return B5TorsionRunRow(
        route="shell_fem_tip_torque",
        n_span=spec.n_span,
        n_circumference=spec.n_circumference,
        applied_torque_n_m=torque_n_m,
        theory_theta_rad=theory_theta,
        fem_theta_rad=theta_fem,
        theta_error_pct=theta_error,
        section_force_torque_root_n_m=None,
        section_force_torque_error_pct=None,
        max_von_mises_pa=_max_von_mises_from_frd(Path(payload["frd"])),
        status="PASS" if theta_error <= 15.0 else "WARN",
        note="Gmsh shell FEM twist compared against theta = T L / GJ.",
    )


def _run_b5_pipe_section_force_case(
    *,
    cfg: Any,
    route_dir: Path,
    material: BeamMaterial,
    span_m: float,
    outer_radius_m: float,
    thickness_m: float,
    torque_n_m: float,
    theory_theta: float,
) -> B5TorsionRunRow:
    if find_ccx(cfg) is None:
        return B5TorsionRunRow(
            route="calculix_b32r_pipe_section_forces",
            n_span=20,
            n_circumference=None,
            applied_torque_n_m=torque_n_m,
            theory_theta_rad=theory_theta,
            fem_theta_rad=None,
            theta_error_pct=None,
            section_force_torque_root_n_m=None,
            section_force_torque_error_pct=None,
            max_von_mises_pa=None,
            status="SKIP",
            note="CalculiX unavailable.",
        )
    y_nodes_m = np.linspace(0.0, span_m, 21)
    nodal_my = np.zeros(y_nodes_m.size)
    nodal_my[-1] = torque_n_m
    spec = build_single_pipe_cantilever_spec(
        name="b5_single_tube_torsion_b32r_pipe",
        y_nodes_m=y_nodes_m,
        outer_radius_m=np.full(y_nodes_m.size - 1, outer_radius_m),
        thickness_m=np.full(y_nodes_m.size - 1, thickness_m),
        material=material,
        nodal_fz_n=np.zeros(y_nodes_m.size),
        nodal_my_nm=nodal_my,
    )
    case_dir = route_dir / "b5_torsion_pipe"
    deck = write_calculix_beam_inp(spec, case_dir / "b5_single_tube_torsion_b32r_pipe.inp")
    _inject_section_force_output(deck.inp_path)
    payload = run_static(deck.inp_path, cfg)
    if payload.get("error"):
        return B5TorsionRunRow(
            route="calculix_b32r_pipe_section_forces",
            n_span=20,
            n_circumference=None,
            applied_torque_n_m=torque_n_m,
            theory_theta_rad=theory_theta,
            fem_theta_rad=None,
            theta_error_pct=None,
            section_force_torque_root_n_m=None,
            section_force_torque_error_pct=None,
            max_von_mises_pa=None,
            status="WARN",
            note=f"B32R section-force run failed: {payload['error']}",
        )
    field = parse_last_field_block(Path(payload["frd"]), "STRESS")
    torque = None
    if field is not None and field.rows.size:
        try:
            torque_series = _component_series(field.rows, field.labels, "SXY")
            torque = float(torque_series[0])
        except KeyError:
            torque = None
    torque_error = None if torque is None else phase14_bench._pct_error(torque, torque_n_m)
    return B5TorsionRunRow(
        route="calculix_b32r_pipe_section_forces",
        n_span=20,
        n_circumference=None,
        applied_torque_n_m=torque_n_m,
        theory_theta_rad=theory_theta,
        fem_theta_rad=None,
        theta_error_pct=None,
        section_force_torque_root_n_m=torque,
        section_force_torque_error_pct=torque_error,
        max_von_mises_pa=None,
        status="PASS" if torque_error is not None and torque_error <= 1.0 else "WARN",
        note="B32R PIPE section forces compared against the applied tip torque.",
    )


def _run_gmsh_shell_mesh(*, gmsh_path: str, geo_path: Path, mesh_path: Path) -> None:
    result = subprocess.run(
        [
            gmsh_path,
            str(geo_path),
            "-2",
            "-format",
            "inp",
            "-o",
            str(mesh_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    log_path = mesh_path.with_suffix(".gmsh.log")
    log_path.write_text(
        "\n".join(["===== gmsh stdout =====", result.stdout, "===== gmsh stderr =====", result.stderr]),
        encoding="utf-8",
    )
    if result.returncode != 0 or not mesh_path.exists():
        raise RuntimeError(f"Gmsh shell mesh failed for {geo_path}: {result.stderr or result.stdout}")


def _read_surface_mesh(path: Path) -> tuple[np.ndarray, list[ShellElement]]:
    nodes: list[tuple[float, float, float, float]] = []
    elements: list[ShellElement] = []
    in_nodes = False
    current_type = ""
    in_elements = False
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        upper = line.upper()
        if upper.startswith("*NODE"):
            in_nodes = True
            in_elements = False
            continue
        if upper.startswith("*ELEMENT"):
            in_nodes = False
            in_elements = True
            current_type = _element_type_from_card(line)
            continue
        if line.startswith("*"):
            in_nodes = False
            in_elements = False
            continue
        if in_nodes:
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 4:
                nodes.append(tuple(float(part) for part in parts[:4]))
            continue
        if in_elements:
            shell_type = {"CPS3": "S3", "CPS4": "S4", "CPE3": "S3", "CPE4": "S4"}.get(
                current_type.upper(),
                current_type.upper(),
            )
            if shell_type not in {"S3", "S4"}:
                continue
            parts = [part.strip() for part in line.split(",") if part.strip()]
            if len(parts) >= 4:
                elements.append(
                    ShellElement(
                        element_id=int(parts[0]),
                        element_type=shell_type,
                        node_ids=tuple(int(part) for part in parts[1:]),
                    )
                )
    if not nodes:
        raise ValueError(f"No nodes found in {path}.")
    if not elements:
        raise ValueError(f"No shell elements found in {path}.")
    return np.asarray(nodes, dtype=float), elements


def _write_shell_static_inp(
    path: Path,
    *,
    nodes: np.ndarray,
    elements: list[ShellElement],
    material: BeamMaterial,
    root_nodes: list[int],
    loads: list[tuple[int, int, float]],
    span_m: float,
    root_thickness_m: float,
    tip_thickness_m: float,
    output_stress: bool,
) -> Path:
    element_by_type: dict[str, list[ShellElement]] = {}
    for element in elements:
        element_by_type.setdefault(element.element_type, []).append(element)
    thickness_sets: dict[int, list[int]] = {}
    node_map = {int(row[0]): row for row in nodes}
    n_bands = 12
    for element in elements:
        centroid_y = float(np.mean([node_map[node_id][2] for node_id in element.node_ids]))
        band = min(n_bands - 1, max(0, int((centroid_y / max(span_m, 1.0e-12)) * n_bands)))
        thickness_sets.setdefault(band, []).append(element.element_id)

    lines = [
        "*HEADING",
        "Phase 14 Mac-local shell FEM benchmark generated by phase14_maclocal_fem_package.py",
        "*NODE",
    ]
    for node_id, x_m, y_m, z_m in nodes:
        lines.append(f"{int(node_id)}, {x_m:.9g}, {y_m:.9g}, {z_m:.9g}")
    for element_type, items in sorted(element_by_type.items()):
        lines.append(f"*ELEMENT, TYPE={element_type}")
        for element in items:
            lines.append(
                f"{element.element_id}, " + ", ".join(str(node_id) for node_id in element.node_ids)
            )
    lines.extend(
        [
            "*MATERIAL, NAME=HPA_SHELL_MATERIAL",
            "*ELASTIC",
            f"{material.young_pa:.9g}, {material.poisson_ratio:.9g}",
            "*DENSITY",
            f"{material.density_kgpm3:.9g}",
        ]
    )
    for band, element_ids in sorted(thickness_sets.items()):
        elset = f"SHELL_BAND_{band:02d}"
        lines.append(f"*ELSET, ELSET={elset}")
        lines.extend(_format_int_chunks(element_ids))
        eta = (band + 0.5) / n_bands
        thickness = (1.0 - eta) * root_thickness_m + eta * tip_thickness_m
        lines.append(f"*SHELL SECTION, ELSET={elset}, MATERIAL=HPA_SHELL_MATERIAL")
        lines.append(f"{thickness:.9g}")
    lines.append("*NSET, NSET=ROOT")
    lines.extend(_format_int_chunks(root_nodes))
    lines.append("*BOUNDARY")
    for node_id in root_nodes:
        for dof in range(1, 7):
            lines.append(f"{node_id}, {dof}, {dof}, 0.0")
    lines.extend(
        [
            "*STEP, NAME=phase14_static",
            "*STATIC",
            "1.0, 1.0",
            "*CLOAD",
        ]
    )
    for node_id, dof, value in loads:
        if abs(value) > 0.0:
            lines.append(f"{node_id}, {dof}, {value:.9g}")
    lines.extend(
        [
            "*NODE PRINT, NSET=ROOT, TOTALS=ONLY",
            "RF",
            "*NODE FILE, OUTPUT=3D",
            "U",
        ]
    )
    if output_stress:
        lines.extend(["*EL FILE, OUTPUT=3D", "S"])
    lines.extend(["*END STEP", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _distributed_vertical_loads_for_shell_nodes(
    *,
    nodes: np.ndarray,
    root_nodes: set[int],
    total_fz_n: float,
) -> list[tuple[int, int, float]]:
    non_root = [int(row[0]) for row in nodes if int(row[0]) not in root_nodes]
    if not non_root:
        raise ValueError("No non-root shell nodes available for distributed load.")
    per_node = float(total_fz_n) / len(non_root)
    return [(node_id, 3, per_node) for node_id in non_root]


def _nodes_at_y(nodes: np.ndarray, y_m: float, *, atol: float = 1.0e-8) -> list[int]:
    y = nodes[:, 2]
    offsets = np.abs(y - float(y_m))
    tolerance = max(atol, float(np.min(offsets)) + atol)
    return [int(row[0]) for row in nodes[offsets <= tolerance]]


def _rows_for_node_ids(nodes: np.ndarray, node_ids: Iterable[int]) -> np.ndarray:
    wanted = {int(node_id) for node_id in node_ids}
    return np.asarray([row for row in nodes if int(row[0]) in wanted], dtype=float)


def _average_uz(displacements: np.ndarray, node_ids: Iterable[int]) -> float:
    wanted = {int(node_id) for node_id in node_ids}
    rows = [row for row in displacements if int(row[0]) in wanted]
    if not rows:
        raise ValueError("No requested tip nodes found in displacement output.")
    return float(np.mean([row[3] for row in rows]))


def estimate_ring_twist_rad(*, nodes: np.ndarray, displacements: np.ndarray) -> float:
    """Estimate rigid twist of an end ring about +Y from all ring nodes.

    The x-z ring centroid is removed before comparing angles, so a pure rigid
    translation does not masquerade as torsion.
    """

    reference_rows = np.asarray(nodes, dtype=float)
    displacement_rows = np.asarray(displacements, dtype=float)
    disp_map = {int(row[0]): row for row in displacement_rows}
    matched: list[tuple[float, float, float, float]] = []
    for node_id, x_m, _y_m, z_m in reference_rows:
        disp = disp_map.get(int(node_id))
        if disp is None:
            continue
        matched.append((float(x_m), float(z_m), float(x_m + disp[1]), float(z_m + disp[3])))
    if not matched:
        raise ValueError("No matching ring nodes/displacements available for twist estimation.")

    values = np.asarray(matched, dtype=float)
    x0 = values[:, 0] - float(np.mean(values[:, 0]))
    z0 = values[:, 1] - float(np.mean(values[:, 1]))
    x1 = values[:, 2] - float(np.mean(values[:, 2]))
    z1 = values[:, 3] - float(np.mean(values[:, 3]))
    radius = np.hypot(x0, z0)
    valid = radius > max(1.0e-12, float(np.max(radius)) * 1.0e-6)
    if not np.any(valid):
        raise ValueError("Ring twist estimation requires non-coincident x-z nodes.")

    cross = x0[valid] * z1[valid] - z0[valid] * x1[valid]
    dot = x0[valid] * x1[valid] + z0[valid] * z1[valid]
    angles = np.arctan2(-cross, dot)
    return float(math.atan2(float(np.mean(np.sin(angles))), float(np.mean(np.cos(angles)))))


def _tip_ring_twist_from_displacement(*, nodes: np.ndarray, displacements: np.ndarray) -> float:
    return estimate_ring_twist_rad(nodes=nodes, displacements=displacements)


def _average_uz_at_y(frd_path: Path, y_m: float) -> float:
    coordinates = parse_nodal_coordinates(frd_path)
    displacements = parse_displacement(frd_path)
    if coordinates.size == 0 or displacements.size == 0:
        raise ValueError(f"No coordinate/displacement output available in {frd_path}.")
    disp_map = {int(row[0]): row for row in displacements}
    offsets = np.abs(coordinates[:, 2] - float(y_m))
    tolerance = max(1.0e-8, float(np.min(offsets)) + 1.0e-8)
    rows = [row for row in coordinates[offsets <= tolerance] if int(row[0]) in disp_map]
    if not rows:
        raise ValueError(f"No displacement rows found near y={y_m:g} in {frd_path}.")
    return float(np.mean([disp_map[int(row[0])][3] for row in rows]))


def _tip_ring_twist_from_frd(frd_path: Path, *, span_m: float) -> float:
    coordinates = parse_nodal_coordinates(frd_path)
    displacements = parse_displacement(frd_path)
    if coordinates.size == 0 or displacements.size == 0:
        raise ValueError(f"No coordinate/displacement output available in {frd_path}.")
    offsets = np.abs(coordinates[:, 2] - float(span_m))
    tolerance = max(1.0e-8, float(np.min(offsets)) + 1.0e-8)
    disp_map = {int(row[0]): row for row in displacements}
    tip_rows = np.asarray([row for row in coordinates[offsets <= tolerance] if int(row[0]) in disp_map])
    if tip_rows.size == 0:
        raise ValueError(f"No tip-ring twist rows found near y={span_m:g} in {frd_path}.")
    return estimate_ring_twist_rad(nodes=tip_rows, displacements=displacements)


def _max_von_mises_from_frd(frd_path: Path) -> float | None:
    field = parse_last_field_block(frd_path, "STRESS")
    if field is None or field.rows.size == 0:
        return None
    labels = [label.upper() for label in field.labels]
    values = field.rows[:, 1:]

    def component(*names: str) -> np.ndarray:
        for name in names:
            if name.upper() in labels:
                return values[:, labels.index(name.upper())]
        return np.zeros(values.shape[0], dtype=float)

    sx = component("SXX", "S11")
    sy = component("SYY", "S22")
    sz = component("SZZ", "S33")
    txy = component("SXY", "S12")
    tyz = component("SYZ", "S23")
    tzx = component("SZX", "SXZ", "S13")
    vm = np.sqrt(
        0.5 * ((sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2)
        + 3.0 * (txy**2 + tyz**2 + tzx**2)
    )
    if vm.size == 0:
        return None
    return float(np.max(np.abs(vm)))


def _inject_section_force_output(inp_path: Path) -> None:
    text = inp_path.read_text(encoding="utf-8")
    target = "*NODE FILE, OUTPUT=2D\nU"
    replacement = "*NODE FILE, OUTPUT=2D\nU\n*EL FILE, SECTION FORCES\nS,NOE"
    if replacement in text:
        return
    if target not in text:
        raise ValueError(f"Expected node output block not found in {inp_path}.")
    inp_path.write_text(text.replace(target, replacement), encoding="utf-8")


def _component_series(rows: np.ndarray, labels: tuple[str, ...], label: str) -> np.ndarray:
    label_upper = label.upper()
    lookup = [item.upper() for item in labels]
    if label_upper not in lookup:
        raise KeyError(label)
    return np.asarray(rows[:, lookup.index(label_upper) + 1], dtype=float)


def _element_type_from_card(card_line: str) -> str:
    for token in card_line.split(","):
        stripped = token.strip()
        if stripped.upper().startswith("TYPE="):
            return stripped.split("=", 1)[1].strip().upper()
    return ""


def _format_int_chunks(values: Iterable[int], *, chunk_size: int = 12) -> list[str]:
    items = [int(value) for value in values]
    return [
        ", ".join(str(value) for value in items[idx : idx + chunk_size])
        for idx in range(0, len(items), chunk_size)
    ]


def _write_run_all_macro(package_dir: Path) -> Path:
    path = package_dir / "run_all_phase14.mac"
    lines = [
        "! Phase 14 Windows APDL runner.",
        "! Open ANSYS Mechanical APDL, set the working directory to this folder, then run:",
        "! /INPUT,run_all_phase14,mac",
        "/CLEAR,NOSTART",
        "HEADER='case_id,route,status,tip_uz_m,theta_rad,root_reaction_fz_n,root_torque_n_m,max_stress_pa,note'",
        "*CFOPEN,phase14_apdl_results,csv",
        "*VWRITE,HEADER",
        "(A)",
        "*CFCLOS",
        "/INPUT,phase14_b2_tapered_tube,mac",
        "/INPUT,phase14_b5_single_torsion,mac",
        "/INPUT,phase14_b5_dual_direct_my,mac",
        "/INPUT,phase14_b5_dual_force_couple,mac",
        "FINISH",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_apdl_b2_tapered_tube(package_dir: Path, material: BeamMaterial) -> Path:
    path = package_dir / "phase14_b2_tapered_tube.mac"
    span_m = 10.0
    n_elem = 20
    q_npm = 8.0
    lines = _apdl_common_header("B2 tapered hollow tube", material)
    lines.extend(
        [
            "ET,1,BEAM188",
            "KEYOPT,1,3,2",
            "",
            "! Keypoints along spanwise Y.",
        ]
    )
    for idx in range(n_elem + 1):
        y = span_m * idx / n_elem
        lines.append(f"K,{idx + 1},0,{y:.9g},0")
    for idx in range(1, n_elem + 1):
        lines.append(f"L,{idx},{idx + 1}")
    for idx in range(n_elem):
        eta = (idx + 0.5) / n_elem
        outer = (1.0 - eta) * 0.04 + eta * 0.025
        thick = (1.0 - eta) * 0.0018 + eta * 0.0012
        inner = max(outer - thick, 0.0)
        lines.extend(
            [
                f"SECTYPE,{idx + 1},BEAM,CTUBE",
                f"SECDATA,{inner:.9e},{outer:.9e}",
                f"LSEL,S,LINE,,{idx + 1}",
                f"LATT,1,,1,,,,{idx + 1}",
                "LESIZE,ALL,,,1",
                "LMESH,ALL",
            ]
        )
    lines.extend(["ALLSEL,ALL", "DK,1,ALL,0", ""])
    total = 0.0
    for idx in range(n_elem + 1):
        tributary = span_m / n_elem
        if idx in {0, n_elem}:
            tributary *= 0.5
        load = -q_npm * tributary
        total += load
        lines.append(f"FK,{idx + 1},FZ,{load:.9e}")
    lines.extend(
        [
            "FINISH",
            "/SOLU",
            "ANTYPE,STATIC",
            "SOLVE",
            "FINISH",
            "/POST1",
            "SET,LAST",
            f"*GET,TIP_UZ,NODE,{n_elem + 1},U,Z",
            "*GET,ROOT_RFZ,NODE,1,RF,FZ",
            "ETABLE,SEQV,S,EQV",
            "*GET,MAXSEQV,ETAB,SEQV,MAX",
            "CASEID='B2_TAPERED_TUBE'",
            "ROUTE='APDL_BEAM188_CTUBE'",
            "STATUS='RAN'",
            "NOTE='root fixed distributed vertical load'",
            "*CFOPEN,phase14_apdl_results,csv,,APPEND",
            "*VWRITE,CASEID,ROUTE,STATUS,TIP_UZ,0,ROOT_RFZ,0,MAXSEQV,NOTE",
            "(A32,',',A32,',',A12,',',E16.8,',',E16.8,',',E16.8,',',E16.8,',',E16.8,',',A64)",
            "*CFCLOS",
            "FINISH",
            f"! Applied total FZ [N] = {total:.9e}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_apdl_b5_single_torsion(package_dir: Path, material: BeamMaterial) -> Path:
    path = package_dir / "phase14_b5_single_torsion.mac"
    span_m = 10.0
    n_elem = 20
    torque = 100.0
    outer = 0.03
    inner = outer - 0.0015
    lines = _apdl_common_header("B5 single tube torsion", material)
    lines.extend(["ET,1,BEAM188", "KEYOPT,1,3,2"])
    for idx in range(n_elem + 1):
        y = span_m * idx / n_elem
        lines.append(f"K,{idx + 1},0,{y:.9g},0")
    for idx in range(1, n_elem + 1):
        lines.append(f"L,{idx},{idx + 1}")
    lines.extend(
        [
            "SECTYPE,1,BEAM,CTUBE",
            f"SECDATA,{inner:.9e},{outer:.9e}",
            "LSEL,ALL",
            "LATT,1,,1,,,,1",
            "LESIZE,ALL,,,1",
            "LMESH,ALL",
            "ALLSEL,ALL",
            "DK,1,ALL,0",
            f"FK,{n_elem + 1},MY,{torque:.9e}",
            "FINISH",
            "/SOLU",
            "ANTYPE,STATIC",
            "SOLVE",
            "FINISH",
            "/POST1",
            "SET,LAST",
            f"*GET,TIP_ROTY,NODE,{n_elem + 1},ROT,Y",
            "*GET,ROOT_TORQUE,NODE,1,RF,MY",
            "ETABLE,SEQV,S,EQV",
            "*GET,MAXSEQV,ETAB,SEQV,MAX",
            "CASEID='B5_SINGLE_TORSION'",
            "ROUTE='APDL_BEAM188_CTUBE'",
            "STATUS='RAN'",
            "NOTE='tip MY torque compare theta TL over GJ'",
            "*CFOPEN,phase14_apdl_results,csv,,APPEND",
            "*VWRITE,CASEID,ROUTE,STATUS,0,TIP_ROTY,0,ROOT_TORQUE,MAXSEQV,NOTE",
            "(A32,',',A32,',',A12,',',E16.8,',',E16.8,',',E16.8,',',E16.8,',',E16.8,',',A64)",
            "*CFCLOS",
            "FINISH",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_apdl_b5_dual_direct_my(package_dir: Path, material: BeamMaterial) -> Path:
    return _write_apdl_dual_b5(
        package_dir / "phase14_b5_dual_direct_my.mac",
        material=material,
        case_id="B5_DUAL_DIRECT_MY",
        route="APDL_DUAL_BEAM_DIRECT_MY",
        use_force_couple=False,
    )


def _write_apdl_b5_dual_force_couple(package_dir: Path, material: BeamMaterial) -> Path:
    return _write_apdl_dual_b5(
        package_dir / "phase14_b5_dual_force_couple.mac",
        material=material,
        case_id="B5_DUAL_FORCE_COUPLE",
        route="APDL_DUAL_BEAM_FORCE_COUPLE",
        use_force_couple=True,
    )


def _write_apdl_dual_b5(
    path: Path,
    *,
    material: BeamMaterial,
    case_id: str,
    route: str,
    use_force_couple: bool,
) -> Path:
    span_m = 10.0
    n_elem = 12
    spacing_m = 0.35
    total_torque = 40.0
    lines = _apdl_common_header(case_id, material)
    lines.extend(["ET,1,BEAM188", "KEYOPT,1,3,2"])
    for idx in range(n_elem + 1):
        y = span_m * idx / n_elem
        lines.append(f"K,{idx + 1},0,{y:.9g},0")
        lines.append(f"K,{100 + idx + 1},{spacing_m:.9g},{y:.9g},0")
    for idx in range(1, n_elem + 1):
        lines.append(f"L,{idx},{idx + 1}")
        lines.append(f"L,{100 + idx},{100 + idx + 1}")
    lines.extend(
        [
            "SECTYPE,1,BEAM,CTUBE",
            "SECDATA,2.82e-2,3.0e-2",
            "LSEL,ALL",
            "LATT,1,,1,,,,1",
            "LESIZE,ALL,,,1",
            "LMESH,ALL",
            "ALLSEL,ALL",
            "DK,1,ALL,0",
            "DK,101,ALL,0",
            "! Equal-DOF links approximate rigid rib stations.",
        ]
    )
    for idx in (2, 4, 6, 8, 10):
        main = idx + 1
        rear = 100 + idx + 1
        for dof in ("UX", "UY", "UZ", "ROTX", "ROTY", "ROTZ"):
            lines.append(f"CE,NEXT,0,{main},{dof},1,{rear},{dof},-1")
    if use_force_couple:
        couple_force = total_torque / spacing_m
        lines.append(f"FK,{n_elem + 1},FZ,{couple_force:.9e}")
        lines.append(f"FK,{100 + n_elem + 1},FZ,{-couple_force:.9e}")
        note = "vertical couple is a surrogate; compare against direct MY"
    else:
        lines.append(f"FK,{n_elem + 1},MY,{total_torque:.9e}")
        note = "direct MY torque ownership case"
    lines.extend(
        [
            "FINISH",
            "/SOLU",
            "ANTYPE,STATIC",
            "SOLVE",
            "FINISH",
            "/POST1",
            "SET,LAST",
            f"*GET,MAIN_TIP_UZ,NODE,{n_elem + 1},U,Z",
            f"*GET,REAR_TIP_UZ,NODE,{100 + n_elem + 1},U,Z",
            "*GET,ROOT_TORQUE,NODE,1,RF,MY",
            "ETABLE,SEQV,S,EQV",
            "*GET,MAXSEQV,ETAB,SEQV,MAX",
            f"CASEID='{case_id}'",
            f"ROUTE='{route}'",
            "STATUS='RAN'",
            f"NOTE='{note}'",
            "*CFOPEN,phase14_apdl_results,csv,,APPEND",
            "*VWRITE,CASEID,ROUTE,STATUS,MAIN_TIP_UZ,0,0,ROOT_TORQUE,MAXSEQV,NOTE",
            "(A32,',',A32,',',A12,',',E16.8,',',E16.8,',',E16.8,',',E16.8,',',E16.8,',',A64)",
            "*CFCLOS",
            "FINISH",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _apdl_common_header(title: str, material: BeamMaterial) -> list[str]:
    return [
        f"! {title}",
        "! Phase 14 validation-only APDL deck. Do not feed results into aero ranking or gates.",
        "/CLEAR,NOSTART",
        "/PREP7",
        f"MP,EX,1,{material.young_pa:.9e}",
        f"MP,PRXY,1,{material.poisson_ratio:.9g}",
        f"MP,DENS,1,{material.density_kgpm3:.9g}",
        "",
    ]


def _write_apdl_readme(package_dir: Path) -> Path:
    path = package_dir / "README_windows_run.md"
    text = """# Phase 14 APDL Windows Package

This package is validation tooling only. Do not use these results to change aerodynamic ranking, hard gates, dual_beam_production physics, or calibration factors.

## Steps

1. Copy this whole folder to the Windows machine that has ANSYS Mechanical APDL.
2. Open ANSYS Mechanical APDL.
3. In APDL, set working directory to this folder.
4. Run `run_all_phase14.mac`.
5. Wait until all four decks finish.
6. Send back `phase14_apdl_results.csv`.

## Files

- `run_all_phase14.mac`: one-click runner.
- `phase14_b2_tapered_tube.mac`: B2 tapered hollow tube BEAM188/CTUBE check.
- `phase14_b5_single_torsion.mac`: B5 single tube torsion check.
- `phase14_b5_dual_direct_my.mac`: simplified dual-beam direct MY case.
- `phase14_b5_dual_force_couple.mac`: simplified dual-beam vertical-force-couple case.
- `expected_values.csv`: Mac-local references to compare against.

The runner recreates `phase14_apdl_results.csv` automatically in the same folder.
`expected_values.csv` may include several references for the same APDL metric:
beam/theory rows are the primary APDL comparison targets, while rows whose
source contains `shell_fem` are Mac-local sanity evidence and should not be used
as calibration factors.
"""
    path.write_text(text, encoding="utf-8")
    return path


def _write_expected_values_csv(package_dir: Path, rows: Iterable[Phase14ExpectedValue]) -> Path:
    path = package_dir / "expected_values.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case_id", "metric", "value", "source", "tolerance_pct", "note"],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)
    return path


def _expected_values_from_rows(
    *,
    b2_rows: list[B2ShellRunRow],
    b5_rows: list[B5TorsionRunRow],
) -> list[Phase14ExpectedValue]:
    values: list[Phase14ExpectedValue] = []
    fine_b2 = next((row for row in reversed(b2_rows) if row.shell_tip_uz_m is not None), None)
    if fine_b2 is not None:
        values.extend(
            [
                Phase14ExpectedValue(
                    case_id="B2_TAPERED_TUBE",
                    metric="tip_uz_m",
                    value=float(fine_b2.internal_tip_uz_m),
                    source="mac_internal_beam",
                    tolerance_pct=10.0,
                    note="Primary beam-theory reference for the APDL BEAM188 deck.",
                ),
                *(
                    []
                    if fine_b2.calculix_pipe_tip_uz_m is None
                    else [
                        Phase14ExpectedValue(
                            case_id="B2_TAPERED_TUBE",
                            metric="tip_uz_m",
                            value=float(fine_b2.calculix_pipe_tip_uz_m),
                            source="mac_calculix_b32r_pipe",
                            tolerance_pct=10.0,
                            note="CalculiX PIPE beam reference from the Mac-local route.",
                        )
                    ]
                ),
                Phase14ExpectedValue(
                    case_id="B2_TAPERED_TUBE",
                    metric="tip_uz_m",
                    value=float(fine_b2.shell_tip_uz_m),
                    source="mac_shell_fem_fine_sanity",
                    tolerance_pct=20.0,
                    note="Shell FEM sanity reference; not calibration truth.",
                ),
                Phase14ExpectedValue(
                    case_id="B2_TAPERED_TUBE",
                    metric="root_reaction_fz_n",
                    value=0.0 if fine_b2.root_reaction_fz_n is None else float(fine_b2.root_reaction_fz_n),
                    source="mac_shell_fem_fine",
                    tolerance_pct=2.0,
                    note="Sign convention should close against applied FZ.",
                ),
            ]
        )
    pipe_b5 = next((row for row in b5_rows if row.section_force_torque_root_n_m is not None), None)
    shell_b5 = next((row for row in b5_rows if row.fem_theta_rad is not None), None)
    if shell_b5 is not None:
        values.append(
            Phase14ExpectedValue(
                case_id="B5_SINGLE_TORSION",
                metric="theta_rad",
                value=float(shell_b5.theory_theta_rad),
                source="theta_equals_tl_over_gj",
                tolerance_pct=10.0,
                note="Primary torsion reference for APDL BEAM188.",
            )
        )
        values.append(
            Phase14ExpectedValue(
                case_id="B5_SINGLE_TORSION",
                metric="theta_rad",
                value=float(shell_b5.fem_theta_rad),
                source="mac_shell_fem_tip_torque_sanity",
                tolerance_pct=25.0,
                note="Observed shell FEM twist; warning-grade versus closed form.",
            )
        )
    if pipe_b5 is not None:
        values.append(
            Phase14ExpectedValue(
                case_id="B5_SINGLE_TORSION",
                metric="root_torque_n_m",
                value=float(pipe_b5.section_force_torque_root_n_m),
                source="mac_calculix_b32r_section_forces",
                tolerance_pct=2.0,
                note="Root section-force torque should recover applied torque.",
            )
        )
    values.extend(
        [
            Phase14ExpectedValue(
                case_id="B5_DUAL_DIRECT_MY",
                metric="root_torque_n_m",
                value=40.0,
                source="deck_applied_load",
                tolerance_pct=10.0,
                note="Simplified dual-beam direct moment case.",
            ),
            Phase14ExpectedValue(
                case_id="B5_DUAL_FORCE_COUPLE",
                metric="root_torque_n_m",
                value=40.0,
                source="deck_applied_load",
                tolerance_pct=10.0,
                note="Force couple has same external moment but is only a surrogate load path.",
            ),
        ]
    )
    return values


def _write_b2_shell_csv(path: Path, rows: list[B2ShellRunRow]) -> None:
    _write_dataclass_csv(path, rows, B2ShellRunRow)


def _write_b5_torsion_csv(path: Path, rows: list[B5TorsionRunRow]) -> None:
    _write_dataclass_csv(path, rows, B5TorsionRunRow)


def _write_dataclass_csv(path: Path, rows: list[Any], cls: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(cls.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.__dict__)


def write_constant_tube_verification_csv(
    path: str | Path,
    rows: list[ConstantTubeVerificationRow],
) -> None:
    _write_dataclass_csv(Path(path), rows, ConstantTubeVerificationRow)


def write_b5_shell_torsion_hardening_csv(
    path: str | Path,
    rows: list[B5ShellTorsionHardeningRow],
) -> None:
    _write_dataclass_csv(Path(path), rows, B5ShellTorsionHardeningRow)


def write_b2_tapered_shell_hardening_csv(
    path: str | Path,
    rows: list[B2TaperedShellHardeningRow],
) -> None:
    _write_dataclass_csv(Path(path), rows, B2TaperedShellHardeningRow)


def write_constant_tube_markdown(
    path: str | Path,
    *,
    title: str,
    rows: list[ConstantTubeVerificationRow],
    engineering_summary: str,
) -> None:
    lines = [
        f"# {title}",
        "",
        engineering_summary,
        "",
        "| case_id | mesh_id | n_span | n_circumference | element_count | load_or_torque | theory_value | fem_value | error_pct | reaction_or_moment_residual | mesh_delta_vs_previous_pct | mesh_delta_vs_finest_pct | max_von_mises_pa | status | engineering_note |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row.case_id} | {row.mesh_id} | {row.n_span} | {row.n_circumference} | "
            f"{row.element_count} | {_fmt(row.load_or_torque)} | {_fmt(row.theory_value)} | "
            f"{_fmt(row.fem_value)} | {_fmt(row.error_pct)} | "
            f"{_fmt(row.reaction_or_moment_residual)} | "
            f"{_fmt(row.mesh_delta_vs_previous_pct)} | {_fmt(row.mesh_delta_vs_finest_pct)} | "
            f"{_fmt(row.max_von_mises_pa)} | {row.status} | {row.engineering_note} |"
        )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_b5_shell_torsion_hardening_markdown(
    path: str | Path,
    rows: list[B5ShellTorsionHardeningRow],
    engineering_summary: str | None = None,
) -> None:
    best = _best_b5_hardening_row(rows)
    lines = [
        "# B5 Shell Torsion Hardening",
        "",
        engineering_summary
        or "Validation tooling only. The old single shell-torsion number is kept as a diagnosed baseline, not a truth source.",
        "",
        "| variant | mesh_id | n_span | n_circumference | applied_torque_n_m | recovered_torque_n_m | theory_theta_rad | shell_theta_rad | theta_error_pct | mesh_delta_vs_previous_pct | max_von_mises_pa | status | engineering_note |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row.variant} | {row.mesh_id} | {row.n_span} | {row.n_circumference} | "
            f"{_fmt(row.applied_torque_n_m)} | {_fmt(row.recovered_torque_n_m)} | "
            f"{_fmt(row.theory_theta_rad)} | {_fmt(row.shell_theta_rad)} | "
            f"{_fmt(row.theta_error_pct)} | {_fmt(row.mesh_delta_vs_previous_pct)} | "
            f"{_fmt(row.max_von_mises_pa)} | {row.status} | {row.engineering_note} |"
        )
    lines.extend(["", "## Engineering Readout", ""])
    if best is None:
        lines.append("- No B5 shell torsion run produced a usable theta value.")
    else:
        lines.append(
            f"- Best current B5 shell torsion route: `{best.variant}` / `{best.mesh_id}` "
            f"theta {best.shell_theta_rad:.6e} rad vs theory {best.theory_theta_rad:.6e} rad "
            f"(error {best.theta_error_pct:.3f}%)."
        )
        lines.append(
            "- This is improved enough for a directional diagnostic, but it is still not a final GJ truth route unless the constant-tube shell bias is accepted explicitly."
        )
    lines.append("- Reference-node / root-cap coupling was not promoted here; the controlled root-ring S4 route is the bounded Mac-safe diagnostic.")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_b2_tapered_shell_hardening_markdown(
    path: str | Path,
    rows: list[B2TaperedShellHardeningRow],
) -> None:
    best = _best_b2_hardening_row(rows)
    lines = [
        "# B2 Tapered Shell Hardening",
        "",
        "Validation tooling only. These rows compare shell formulation/load variants against the internal beam and B32R PIPE references without changing production physics.",
        "",
        "| variant | mesh_id | n_span | n_circumference | element_count | tip_uz_avg_m | tip_uz_min_m | tip_uz_max_m | root_reaction_fz_n | reaction_residual_n | max_von_mises_pa | error_vs_internal_pct | error_vs_b32r_pipe_pct | mesh_delta_vs_previous_pct | mesh_delta_vs_finest_pct | status | engineering_note |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            f"{row.variant} | {row.mesh_id} | {row.n_span} | {row.n_circumference} | "
            f"{row.element_count} | {_fmt(row.tip_uz_avg_m)} | {_fmt(row.tip_uz_min_m)} | "
            f"{_fmt(row.tip_uz_max_m)} | {_fmt(row.root_reaction_fz_n)} | "
            f"{_fmt(row.reaction_residual_n)} | {_fmt(row.max_von_mises_pa)} | "
            f"{_fmt(row.error_vs_internal_pct)} | {_fmt(row.error_vs_b32r_pipe_pct)} | "
            f"{_fmt(row.mesh_delta_vs_previous_pct)} | {_fmt(row.mesh_delta_vs_finest_pct)} | "
            f"{row.status} | {row.engineering_note} |"
        )
    lines.extend(["", "## Engineering Readout", ""])
    if best is None:
        lines.append("- No B2 tapered shell run produced a usable tip displacement.")
    else:
        lines.append(
            f"- Best current B2 shell row by reference error: `{best.variant}` / `{best.mesh_id}` "
            f"tip UZ {best.tip_uz_avg_m:.6e} m, error vs internal {_fmt(best.error_vs_internal_pct)}%, "
            f"error vs B32R {_fmt(best.error_vs_b32r_pipe_pct)}%."
        )
        lines.append(
            "- Treat B2 as shell diagnostic unless the selected variant is both mesh-converged and within the comparison tolerance."
        )
    lines.append("- Root-cap/reference-node variants remain an APDL or future equation-coupling follow-up; no calibration factor was introduced.")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_overnight_hardening_summary(
    path: str | Path,
    *,
    bending_rows: list[ConstantTubeVerificationRow],
    torsion_rows: list[ConstantTubeVerificationRow],
    b5_rows: list[B5ShellTorsionHardeningRow],
    b2_rows: list[B2TaperedShellHardeningRow],
    apdl_package_dir: Path,
) -> None:
    bending_tip = _finest_constant_row(bending_rows, "A1_constant_tube_tip_load")
    bending_uniform = _finest_constant_row(bending_rows, "A2_constant_tube_uniform_load")
    torsion = _finest_constant_row(torsion_rows, "A3_constant_tube_tip_torque")
    b5_best = _best_b5_hardening_row(b5_rows)
    b2_best = _best_b2_hardening_row(b2_rows)
    lines = [
        "# Phase 14 Mac-local FEM Overnight Hardening Summary",
        "",
        "This is validation tooling only. It does not change aerodynamic ranking, hard gates, dual_beam_production physics, or calibration factors.",
        "",
        "## Direct Answers",
        "",
        f"1. Constant tube shell bending: {_constant_answer(bending_tip)} for tip load; {_constant_answer(bending_uniform)} for uniform load.",
        f"2. Constant tube shell torsion: {_constant_answer(torsion)}.",
        f"3. B5 shell torsion: {_b5_answer(b5_best)}.",
        f"4. B2 tapered shell convergence: {_b2_convergence_answer(b2_best)}.",
        "5. Mac-local FEM does not yet replace APDL for B2 truth; use it as a bounded diagnostic until APDL checks the tapered beam/shell question.",
        "6. Mac-local FEM supports B5 torque ownership through section forces and now has an improved shell twist diagnostic, but APDL remains the external twist/GJ truth check.",
        f"7. Tomorrow APDL: run `{apdl_package_dir}/run_all_phase14.mac` on Windows and return `phase14_apdl_results.csv`.",
        "",
        "## Trust Policy",
        "",
        "- trusted daily gate: CalculiX beam parity for B1/B3 and B5 direct-MY section-force torque ownership.",
        "- directional diagnostic: Mac-local constant shell WARN rows, improved B5 structured S4 shell torsion, and B2 shell variant comparisons.",
        "- not trustworthy yet: legacy Gmsh triangular B5 shell torsion and any B2 shell value that remains non-converged or outside reference tolerance.",
        "- APDL-required: final B2 tapered truth, final B5 twist/GJ truth, and any root-cap/reference-node shell coupling claim.",
        "",
        "## Stop-Condition Judgment",
        "",
        "- Constant shell benchmarks are stable but not strict PASS against the 5% closed-form threshold; this blocks any claim that Mac-local shell FEM is high-fidelity truth.",
        "- The useful deliverable is therefore diagnosis plus bounded trust policy, not a forced pass.",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _finest_constant_row(
    rows: list[ConstantTubeVerificationRow],
    case_id: str,
) -> ConstantTubeVerificationRow | None:
    matches = [row for row in rows if row.case_id == case_id and row.fem_value is not None]
    return matches[-1] if matches else None


def _constant_answer(row: ConstantTubeVerificationRow | None) -> str:
    if row is None:
        return "SKIP (no usable run)"
    return (
        f"{row.status} at `{row.mesh_id}`: FEM {_fmt(row.fem_value)} vs theory {_fmt(row.theory_value)}, "
        f"error {_fmt(row.error_pct)}%, mesh-to-finest {_fmt(row.mesh_delta_vs_finest_pct)}%"
    )


def _best_b5_hardening_row(rows: list[B5ShellTorsionHardeningRow]) -> B5ShellTorsionHardeningRow | None:
    usable = [row for row in rows if row.theta_error_pct is not None and row.variant.startswith("structured_s4")]
    if not usable:
        usable = [row for row in rows if row.theta_error_pct is not None]
    return max(usable, key=lambda row: (row.n_span, row.n_circumference)) if usable else None


def _b5_answer(row: B5ShellTorsionHardeningRow | None) -> str:
    if row is None:
        return "still bad/no usable shell theta"
    label = "improved" if row.theta_error_pct is not None and row.theta_error_pct <= 10.0 else "still bad"
    return (
        f"{label}: `{row.variant}` theta {_fmt(row.shell_theta_rad)} rad vs theory "
        f"{_fmt(row.theory_theta_rad)} rad, error {_fmt(row.theta_error_pct)}%"
    )


def _best_b2_hardening_row(rows: list[B2TaperedShellHardeningRow]) -> B2TaperedShellHardeningRow | None:
    usable = [row for row in rows if row.tip_uz_avg_m is not None]
    if not usable:
        return None
    finest_by_variant: dict[str, B2TaperedShellHardeningRow] = {}
    for row in usable:
        current = finest_by_variant.get(row.variant)
        if current is None or (row.n_span, row.n_circumference) > (current.n_span, current.n_circumference):
            finest_by_variant[row.variant] = row
    return min(
        finest_by_variant.values(),
        key=lambda row: min(
            float("inf") if row.error_vs_internal_pct is None else row.error_vs_internal_pct,
            float("inf") if row.error_vs_b32r_pipe_pct is None else row.error_vs_b32r_pipe_pct,
        ),
    )


def _b2_convergence_answer(row: B2TaperedShellHardeningRow | None) -> str:
    if row is None:
        return "not converged/no usable shell run"
    label = "converged" if row.mesh_delta_vs_finest_pct is not None and row.mesh_delta_vs_finest_pct <= 5.0 else "not converged"
    return (
        f"{label}: `{row.variant}` / `{row.mesh_id}` tip UZ {_fmt(row.tip_uz_avg_m)} m, "
        f"mesh-to-finest {_fmt(row.mesh_delta_vs_finest_pct)}%, error vs internal "
        f"{_fmt(row.error_vs_internal_pct)}%, error vs B32R {_fmt(row.error_vs_b32r_pipe_pct)}%"
    )


def _write_route_summary(
    path: Path,
    *,
    b2_rows: list[B2ShellRunRow],
    b5_rows: list[B5TorsionRunRow],
    package: ApdlWindowsPackage,
) -> None:
    fine_b2 = next((row for row in reversed(b2_rows) if row.shell_tip_uz_m is not None), None)
    pipe_b5 = next((row for row in b5_rows if row.section_force_torque_root_n_m is not None), None)
    shell_b5 = next((row for row in b5_rows if row.fem_theta_rad is not None), None)
    agreement = None
    if fine_b2 and fine_b2.calculix_pipe_tip_uz_m is not None:
        agreement = classify_b2_shell_agreement(
            B2ComparisonInputs(
                internal_tip_uz_m=fine_b2.internal_tip_uz_m,
                calculix_pipe_tip_uz_m=fine_b2.calculix_pipe_tip_uz_m,
                shell_tip_uz_m=fine_b2.shell_tip_uz_m or 0.0,
            )
        )
    lines = [
        "# Phase 14 Mac-local FEM + APDL Windows Package Summary",
        "",
        "Validation tooling only. This route does not change aerodynamic ranking, hard gates, dual_beam_production physics, or calibration factors.",
        "",
        "## B2 Shell FEM Convergence",
        "",
        "| Mesh | Elements | Tip UZ [m] | Root RFZ [N] | Max VM [Pa] | Conv to fine [%] |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in b2_rows:
        lines.append(
            "| "
            f"{row.mesh_id} | {row.shell_element_count} | {_fmt(row.shell_tip_uz_m)} | "
            f"{_fmt(row.root_reaction_fz_n)} | {_fmt(row.max_von_mises_pa)} | "
            f"{_fmt(row.convergence_to_fine_pct)} |"
        )
    lines.extend(["", "## B2 Comparison", ""])
    if agreement is None or fine_b2 is None:
        lines.append("- B2 shell FEM did not produce a complete fine-mesh comparison.")
    else:
        lines.append(
            f"- Fine shell FEM is closer to `{agreement.closer_to}` "
            f"(shell-vs-internal {agreement.shell_vs_internal_error_pct:.3f}%, "
            f"shell-vs-B32R {agreement.shell_vs_calculix_pipe_error_pct:.3f}%)."
        )
        if min(
            agreement.shell_vs_internal_error_pct,
            agreement.shell_vs_calculix_pipe_error_pct,
        ) > 10.0:
            lines.append(
                "- This is a directionally useful sanity comparison, but not an agreement-quality shell validation yet."
            )
    lines.extend(
        [
            "",
            "## B5 Torsion",
            "",
            "| Route | Theta FEM [rad] | Theta theory [rad] | Theta err [%] | Root section torque [N m] | Torque err [%] |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in b5_rows:
        lines.append(
            "| "
            f"{row.route} | {_fmt(row.fem_theta_rad)} | {row.theory_theta_rad:.6e} | "
            f"{_fmt(row.theta_error_pct)} | {_fmt(row.section_force_torque_root_n_m)} | "
            f"{_fmt(row.section_force_torque_error_pct)} |"
        )
    lines.extend(["", "## Engineering Interpretation", ""])
    if shell_b5 is not None:
        lines.append(
            f"- B5 shell torsion theta is {_fmt(shell_b5.fem_theta_rad)} rad versus "
            f"{shell_b5.theory_theta_rad:.6e} rad from T L / GJ."
        )
    if pipe_b5 is not None:
        lines.append(
            f"- B5 B32R PIPE section-force torque is {_fmt(pipe_b5.section_force_torque_root_n_m)} N m "
            f"for a {pipe_b5.applied_torque_n_m:.3f} N m applied torque."
        )
    lines.append(
        "- The simplified dual-beam vertical force couple has the same external moment as direct MY, but it remains a load-path surrogate because it introduces bending/shear coupling in the linked dual-beam topology."
    )
    lines.extend(
        [
            "",
            "## APDL Windows Package",
            "",
            f"- Package directory: `{package.directory}`",
            "- Copy the entire `apdl_windows_package` folder to Windows.",
            "- Run `run_all_phase14.mac` from ANSYS Mechanical APDL and send back `phase14_apdl_results.csv`.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{float(value):.6e}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(REPO_ROOT / "configs" / "blackcat_004.yaml"))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--task",
        choices=("package", "hardening"),
        default="package",
        help="Run the original APDL handoff package route or the Mac-local FEM hardening workflow.",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    if args.task == "hardening":
        artifacts = run_phase14_maclocal_fem_hardening(
            config_path=args.config,
            output_dir=args.output_dir,
            manifest_path=args.manifest,
        )
    else:
        artifacts = run_phase14_maclocal_fem_route(
            config_path=args.config,
            output_dir=args.output_dir,
            manifest_path=args.manifest,
        )
    for name, path in artifacts.items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
