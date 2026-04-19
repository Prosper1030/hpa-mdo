#!/usr/bin/env python3
"""MVP-1 outer-loop dihedral sweep using AVL stability filtering plus inverse design."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field, replace
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Callable, Iterable, Sequence

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.core import Aircraft, load_config
from hpa_mdo.aero import (
    AeroPerformanceEvaluation,
    VSPBuilder,
    VSPAeroParser,
    build_avl_aero_gate_settings,
    build_fixed_alpha_dihedral_corrector_artifact,
    empty_aero_performance,
    evaluate_aero_performance,
    stage_avl_airfoil_files,
    write_candidate_avl_spanwise_artifact,
)
from hpa_mdo.mission import FakeAnchorCurve, MissionEvaluationInputs, evaluate_mission_objective


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "dihedral_sweep_campaign"
DEFAULT_INVERSE_SCRIPT = REPO_ROOT / "scripts" / "direct_dual_beam_inverse_design.py"
DEFAULT_CONFIG = REPO_ROOT / "configs" / "blackcat_004.yaml"
DEFAULT_BASE_AVL = REPO_ROOT / "data" / "blackcat_004_full.avl"
DEFAULT_DESIGN_REPORT = (
    REPO_ROOT
    / "output"
    / "blackcat_004_dual_beam_production_check"
    / "ansys"
    / "crossval_report.txt"
)
LEGACY_AERO_SOURCE_MODE = "legacy_refresh"
CANDIDATE_RERUN_AERO_SOURCE_MODE = "candidate_rerun_vspaero"
CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE = "candidate_avl_spanwise"
ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE = "origin_vsp_fixed_alpha_corrector"
DEFAULT_VSPAERO_ANALYSIS_METHOD = "vlm"
VSPAERO_ANALYSIS_METHOD_CHOICES = ("vlm", "panel")
OSCILLATORY_IMAG_TOL = 1.0e-9
SPIRAL_LATERAL_RATIO_MIN = 0.35
LATERAL_STATE_NAMES = ("v", "p", "r", "phi", "psi", "y")
LONGITUDINAL_STATE_NAMES = ("u", "w", "q", "the", "x", "z")
FLOAT_TOKEN = r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[Ee][-+]?\d+)?"
CAMPAIGN_GATE_PENALTIES_KG = {
    "aero_stability": 8000.0,
    "aero_performance": 6000.0,
    "beta_sideslip": 4000.0,
    "spiral": 2000.0,
    "inverse_design_subprocess": 1000.0,
    "structural": 500.0,
}


@dataclass(frozen=True)
class AvlModeParameters:
    velocity: float
    density: float
    gravity: float
    mass_kg: float
    ixx: float
    iyy: float
    izz: float
    x_cg: float
    y_cg: float
    z_cg: float
    cdo: float = 0.0
    dcl_a: float = 0.0
    dcl_u: float = 0.0
    dcm_a: float = 0.0
    dcm_u: float = 0.0


@dataclass(frozen=True)
class AvlEigenvalue:
    mode_index: int
    real: float
    imag: float


@dataclass(frozen=True)
class AvlModeBlock:
    mode_index: int
    real: float
    imag: float
    states: dict[str, float]
    lateral_ratio: float


@dataclass(frozen=True)
class SpiralModeEvaluation:
    mode_found: bool
    selection: str
    real: float | None
    time_to_double_s: float | None
    time_to_half_s: float | None
    feasible: bool | None
    reason: str


def _unavailable_spiral_mode_evaluation(
    reason: str = "spiral_mode_unavailable",
) -> SpiralModeEvaluation:
    return SpiralModeEvaluation(
        mode_found=False,
        selection="spiral_mode_unavailable",
        real=None,
        time_to_double_s=None,
        time_to_half_s=None,
        feasible=None,
        reason=str(reason),
    )


@dataclass(frozen=True)
class AvlEvaluation:
    avl_case_path: str
    mode_file_path: str | None
    stdout_log_path: str | None
    dutch_roll_found: bool
    dutch_roll_selection: str
    dutch_roll_real: float | None
    dutch_roll_imag: float | None
    aero_status: str
    aero_feasible: bool
    eigenvalue_count: int
    spiral_eval: SpiralModeEvaluation = field(default_factory=_unavailable_spiral_mode_evaluation)


@dataclass(frozen=True)
class AvlTrimEvaluation:
    trim_file_path: str | None
    stdout_log_path: str | None
    trim_status: str
    trim_converged: bool
    cl_trim: float | None
    cd_induced: float | None
    aoa_trim_deg: float | None
    span_efficiency: float | None


@dataclass(frozen=True)
class AvlSpanwiseLoadCase:
    aoa_deg: float
    fs_file_path: str | None
    stdout_log_path: str | None
    run_completed: bool
    run_status: str


@dataclass(frozen=True)
class ControlCouplingEvaluation:
    st_file_path: str | None
    stdout_log_path: str | None
    cl_rudder_derivative: float | None
    cn_rudder_derivative: float | None
    roll_to_yaw_ratio: float | None
    coupling_reason: str


@dataclass(frozen=True)
class BetaSweepPoint:
    beta_deg: float
    cl_trim: float | None
    cd_induced: float | None
    aoa_trim_deg: float | None
    cn_total: float | None
    cl_roll_total: float | None
    trim_converged: bool


@dataclass(frozen=True)
class BetaSweepEvaluation:
    beta_values_deg: tuple[float, ...]
    points: tuple[BetaSweepPoint, ...]
    max_trimmed_beta_deg: float | None
    cn_beta_per_rad: float | None
    cl_beta_per_rad: float | None
    directional_stable: bool
    sideslip_feasible: bool
    sideslip_reason: str


@dataclass(frozen=True)
class SweepResult:
    dihedral_multiplier: float
    dihedral_exponent: float
    avl_case_path: str
    mode_file_path: str | None
    dutch_roll_found: bool
    dutch_roll_selection: str
    dutch_roll_real: float | None
    dutch_roll_imag: float | None
    aero_status: str
    aero_performance_feasible: bool
    aero_performance_reason: str
    cl_trim: float | None
    cd_induced: float | None
    cd_total_est: float | None
    ld_ratio: float | None
    aoa_trim_deg: float | None
    span_efficiency: float | None
    lift_total_n: float | None
    aero_power_w: float | None
    beta_sweep_max_beta_deg: float | None
    beta_sweep_cn_beta_per_rad: float | None
    beta_sweep_cl_beta_per_rad: float | None
    beta_sweep_directional_stable: bool | None
    beta_sweep_sideslip_feasible: bool | None
    rudder_cl_derivative: float | None
    rudder_cn_derivative: float | None
    rudder_roll_to_yaw_ratio: float | None
    rudder_coupling_reason: str | None
    spiral_mode_real: float | None
    spiral_time_to_double_s: float | None
    spiral_time_to_half_s: float | None
    spiral_check_ok: bool | None
    spiral_reason: str | None
    structure_status: str
    total_mass_kg: float | None
    min_jig_clearance_mm: float | None
    wire_tension_n: float | None
    wire_margin_n: float | None
    failure_index: float | None
    buckling_index: float | None
    objective_value_kg: float | None
    realizable_mismatch_max_mm: float | None
    structural_reject_reason: str | None
    selected_output_dir: str | None
    summary_json_path: str | None
    wire_rigging_json_path: str | None
    error_message: str | None
    mission_objective_mode: str | None = None
    mission_feasible: bool | None = None
    target_range_km: float | None = None
    target_range_passed: bool | None = None
    target_range_margin_m: float | None = None
    best_range_m: float | None = None
    best_range_speed_mps: float | None = None
    best_endurance_s: float | None = None
    min_power_w: float | None = None
    min_power_speed_mps: float | None = None
    mission_score: float | None = None
    mission_score_reason: str | None = None
    pilot_power_model: str | None = None
    pilot_power_anchor: str | None = None
    tube_mass_kg: float | None = None
    candidate_score: float | None = None
    reject_reason: str = "unranked"
    selection_status: str = "unranked"
    winner_evidence: str | None = None
    aero_source_mode: str | None = None
    baseline_load_source: str | None = None
    refresh_load_source: str | None = None
    load_ownership: str | None = None
    artifact_ownership: str | None = None
    selected_cruise_aoa_deg: float | None = None
    aero_contract_json_path: str | None = None


@dataclass(frozen=True)
class DihedralScaleSample:
    y_section_m: float
    z_old_m: float
    z_new_m: float
    local_factor: float


def _parse_multiplier_list(text: str) -> tuple[float, ...]:
    values = tuple(float(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise ValueError("Need at least one dihedral multiplier.")
    return values


def _grid_point_count(text: str) -> int:
    return len(tuple(part.strip() for part in text.split(",") if part.strip()))


def _build_campaign_search_budget(args) -> dict[str, object]:
    coarse_axes = {
        "main_plateau_grid_points": _grid_point_count(args.main_plateau_grid),
        "main_taper_fill_grid_points": _grid_point_count(args.main_taper_fill_grid),
        "rear_radius_grid_points": _grid_point_count(args.rear_radius_grid),
        "rear_outboard_grid_points": _grid_point_count(args.rear_outboard_grid),
        "wall_thickness_grid_points": _grid_point_count(args.wall_thickness_grid),
    }
    coarse_grid_points = 1
    for count in coarse_axes.values():
        coarse_grid_points *= max(1, int(count))
    return {
        "coarse_axes": coarse_axes,
        "coarse_grid_points_per_case": int(coarse_grid_points),
        "refresh_steps": int(args.refresh_steps),
        "cobyla_maxiter": int(args.cobyla_maxiter),
        "cobyla_rhobeg": float(args.cobyla_rhobeg),
        "skip_local_refine": bool(args.skip_local_refine),
        "skip_step_export": bool(args.skip_step_export),
        "local_refine_feasible_seeds": int(args.local_refine_feasible_seeds),
        "local_refine_near_feasible_seeds": int(args.local_refine_near_feasible_seeds),
        "local_refine_max_starts": int(args.local_refine_max_starts),
        "local_refine_early_stop_patience": int(args.local_refine_early_stop_patience),
        "local_refine_early_stop_abs_improvement_kg": float(
            args.local_refine_early_stop_abs_improvement_kg
        ),
        "aero_source_mode": str(args.aero_source_mode),
        "vspaero_analysis_method": (
            "panel"
            if str(args.aero_source_mode) == ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE
            else str(args.vspaero_analysis_method)
        ),
        "fixed_design_alpha_deg": float(args.fixed_design_alpha_deg),
        "auto_first_pass_refine": bool(args.auto_first_pass_refine),
        "first_pass_refine_target_width": float(args.first_pass_refine_target_width),
        "first_pass_refine_max_rounds": int(args.first_pass_refine_max_rounds),
        "max_tube_mass_kg": (
            None if args.max_tube_mass_kg is None else float(args.max_tube_mass_kg)
        ),
        "rib_zonewise_mode": str(args.rib_zonewise_mode),
    }


def _aero_source_label(source_mode: str | None) -> str:
    if source_mode == ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE:
        return "origin VSP fixed-alpha corrector"
    if source_mode == CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE:
        return "candidate AVL spanwise"
    if source_mode == CANDIDATE_RERUN_AERO_SOURCE_MODE:
        return "candidate rerun-aero"
    if source_mode == LEGACY_AERO_SOURCE_MODE:
        return "legacy refresh"
    if source_mode is None:
        return "unknown"
    return str(source_mode)


def _slug(multiplier: float) -> str:
    return f"{multiplier:.3f}".replace("-", "m").replace(".", "p")


def _select_vspaero_case_by_aoa(
    aero_cases: Iterable,
    *,
    target_aoa_deg: float,
):
    cases = list(aero_cases)
    if not cases:
        raise RuntimeError("No VSPAero cases were available for fixed-alpha baseline selection.")
    return min(
        cases,
        key=lambda case: abs(float(case.aoa_deg) - float(target_aoa_deg)),
    )


def _build_origin_fixed_alpha_panel_baseline(
    *,
    cfg,
    output_dir: Path,
    fixed_design_alpha_deg: float,
    base_avl_path: Path,
) -> tuple[object, dict[str, object]]:
    baseline_dir = (output_dir / "origin_vsp_panel_fixed_alpha_baseline").resolve()
    builder = VSPBuilder(
        cfg,
        dihedral_multiplier=1.0,
        dihedral_exponent=float(cfg.wing.dihedral_scaling_exponent),
        vspaero_analysis_method="panel",
    )
    build_result = builder.build_and_run(str(baseline_dir), aoa_list=[float(fixed_design_alpha_deg)])
    if not bool(build_result.get("success")):
        error = build_result.get("error") or "unknown VSPBuilder failure"
        raise RuntimeError(f"Origin fixed-alpha panel baseline failed: {error}")
    lod_path = build_result.get("lod_path")
    if lod_path is None:
        raise RuntimeError("Origin fixed-alpha panel baseline produced no VSPAero .lod artifact.")
    cases = VSPAeroParser(
        lod_path,
        build_result.get("polar_path"),
        component_ids=[1],
    ).parse()
    baseline_case = _select_vspaero_case_by_aoa(cases, target_aoa_deg=float(fixed_design_alpha_deg))
    metadata = {
        "baseline_output_dir": str(baseline_dir),
        "origin_vsp3_path": str(Path(cfg.io.vsp_model).expanduser().resolve()),
        "baseline_lod_path": str(Path(lod_path).expanduser().resolve()),
        "baseline_polar_path": (
            None
            if build_result.get("polar_path") is None
            else str(Path(str(build_result["polar_path"])).expanduser().resolve())
        ),
        "baseline_avl_path": str(base_avl_path.resolve()),
        "analysis_method": "panel",
        "solver_backend": str(build_result.get("solver_backend") or "unknown"),
        "fixed_design_alpha_deg": float(fixed_design_alpha_deg),
        "baseline_selected_case_aoa_deg": float(baseline_case.aoa_deg),
        "baseline_selected_full_lift_n": float(2.0 * baseline_case.total_lift),
    }
    return baseline_case, metadata


def _build_fixed_alpha_aero_performance(
    *,
    fixed_design_alpha_deg: float,
    full_lift_n: float,
    min_lift_n: float,
    skip_aero_gates: bool,
) -> AeroPerformanceEvaluation:
    feasible = True
    reason = "fixed_design_alpha_ok"
    if skip_aero_gates:
        reason = "skipped"
    elif (
        not math.isclose(float(full_lift_n), float(min_lift_n), rel_tol=1.0e-6, abs_tol=1.0e-6)
        and float(full_lift_n) < float(min_lift_n)
    ):
        feasible = False
        reason = "fixed_design_alpha_insufficient_lift"
    return AeroPerformanceEvaluation(
        cl_trim=None,
        cd_induced=None,
        cd_total_est=None,
        ld_ratio=None,
        aoa_trim_deg=float(fixed_design_alpha_deg),
        span_efficiency=None,
        lift_total_n=float(full_lift_n),
        aero_power_w=None,
        aero_performance_feasible=bool(feasible),
        aero_performance_reason=str(reason),
    )


def _split_comment(line: str) -> tuple[str, str]:
    if "!" not in line:
        return line.rstrip("\n"), ""
    body, comment = line.rstrip("\n").split("!", 1)
    return body.rstrip(), "!" + comment


def _try_parse_section_data(line: str) -> list[float] | None:
    body, _ = _split_comment(line)
    tokens = body.split()
    if len(tokens) < 5:
        return None
    values: list[float] = []
    for token in tokens[:5]:
        try:
            values.append(float(token))
        except ValueError:
            return None
    return values


def _surface_name_from_lines(lines: list[str], start_index: int) -> str | None:
    scan = start_index + 1
    while scan < len(lines):
        stripped = lines[scan].strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("!"):
            scan += 1
            continue
        return stripped
    return None


def _surface_matches(surface_name: str | None, target_surface_names: Iterable[str]) -> bool:
    if surface_name is None:
        return False
    aliases = {
        "mainwing": "wing",
    }
    normalized = aliases.get("".join(surface_name.strip().split()).casefold(), surface_name.strip().casefold())
    targets = {
        aliases.get("".join(name.strip().split()).casefold(), name.strip().casefold())
        for name in target_surface_names
    }
    return normalized in targets


def _progressive_dihedral_factor(
    *,
    multiplier: float,
    y_section_m: float,
    half_span: float,
    dihedral_exponent: float,
) -> float:
    span = float(half_span)
    if span <= 0.0:
        eta = 0.0
    else:
        eta = min(max(abs(float(y_section_m)) / span, 0.0), 1.0)
    return 1.0 + (float(multiplier) - 1.0) * (eta ** float(dihedral_exponent))


def scale_avl_dihedral_text(
    text: str,
    *,
    multiplier: float,
    target_surface_names: Iterable[str] = ("wing",),
    half_span: float = 16.5,
    dihedral_exponent: float = 1.0,
    sample_limit: int = 5,
) -> tuple[str, int, tuple[DihedralScaleSample, ...]]:
    lines = text.splitlines(keepends=True)
    out = list(lines)
    scaled = 0
    samples: list[DihedralScaleSample] = []
    idx = 0
    current_surface_name: str | None = None
    while idx < len(out):
        stripped = out[idx].strip().upper()
        if stripped == "SURFACE":
            current_surface_name = _surface_name_from_lines(out, idx)
        if stripped == "SECTION" and _surface_matches(current_surface_name, target_surface_names):
            scan = idx + 1
            while scan < len(out):
                stripped = out[scan].strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                    scan += 1
                    continue
                values = _try_parse_section_data(out[scan])
                if values is not None:
                    y_section_m = float(values[1])
                    z_old_m = float(values[2])
                    local_factor = _progressive_dihedral_factor(
                        multiplier=float(multiplier),
                        y_section_m=y_section_m,
                        half_span=float(half_span),
                        dihedral_exponent=float(dihedral_exponent),
                    )
                    values[2] *= float(local_factor)
                    if len(samples) < max(0, int(sample_limit)):
                        samples.append(
                            DihedralScaleSample(
                                y_section_m=y_section_m,
                                z_old_m=z_old_m,
                                z_new_m=float(values[2]),
                                local_factor=float(local_factor),
                            )
                        )
                    _, comment = _split_comment(out[scan])
                    numeric = "  ".join(f"{value:.9f}" for value in values)
                    suffix = f" {comment}" if comment else ""
                    out[scan] = f"{numeric}{suffix}\n"
                    scaled += 1
                break
        idx += 1
    return "".join(out), scaled, tuple(samples)


def generate_wing_only_avl_from_config(*, cfg, path: Path) -> Path:
    half_span = 0.5 * float(cfg.wing.span)
    y_stations = [0.0]
    cumulative = 0.0
    for segment in cfg.main_spar.segments:
        cumulative += float(segment)
        y_stations.append(min(cumulative, half_span))
    if y_stations[-1] < half_span - 1.0e-9:
        y_stations.append(half_span)
    y_values = []
    for value in y_stations:
        if not y_values or abs(value - y_values[-1]) > 1.0e-9:
            y_values.append(value)

    root_chord = float(cfg.wing.root_chord)
    tip_chord = float(cfg.wing.tip_chord)
    tip_dihedral_rad = math.radians(float(cfg.wing.dihedral_tip_deg))

    def chord_at(y_m: float) -> float:
        eta = 0.0 if half_span <= 0.0 else min(max(y_m / half_span, 0.0), 1.0)
        return root_chord + eta * (tip_chord - root_chord)

    def z_at(y_m: float) -> float:
        return math.tan(tip_dihedral_rad) * y_m

    s_ref = 0.5 * float(cfg.wing.span) * (root_chord + tip_chord)
    c_ref = 0.5 * (root_chord + tip_chord)
    lines = [
        f"{cfg.project_name} wing-only fallback",
        "#Mach",
        "0.000000",
        "#IYsym  iZsym  Zsym",
        "1  0  0.000000",
        "#Sref  Cref  Bref",
        f"{s_ref:.9f}  {c_ref:.9f}  {float(cfg.wing.span):.9f}",
        "#Xref  Yref  Zref",
        "0.000000  0.000000  0.000000",
        "#CDp",
        "0.000000",
        "#",
        "SURFACE",
        "Wing",
        "24  1.0  24  -2.0",
        "#",
    ]
    for y_m in y_values:
        lines.extend(
            [
                "SECTION",
                f"0.000000000  {y_m:.9f}  {z_at(y_m):.9f}  {chord_at(y_m):.9f}  0.000000000",
                "NACA",
                "0012",
                "#",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def estimate_mode_parameters(cfg) -> AvlModeParameters:
    mass_kg = float(cfg.weight.max_takeoff_kg)
    span = float(cfg.wing.span)
    half_span = 0.5 * span
    root_chord = float(cfg.wing.root_chord)
    tip_chord = float(cfg.wing.tip_chord)
    taper_ratio = tip_chord / max(root_chord, 1.0e-12)
    mean_chord = (2.0 / 3.0) * root_chord * (
        (1.0 + taper_ratio + taper_ratio ** 2) / max(1.0 + taper_ratio, 1.0e-12)
    )
    fuselage_length = max(3.0 * mean_chord, 3.0)
    roll_radius = max(0.35 * half_span, 1.0)
    pitch_radius = max(0.35 * fuselage_length, 0.5)
    yaw_radius = math.sqrt(roll_radius ** 2 + pitch_radius ** 2)
    return AvlModeParameters(
        velocity=float(cfg.flight.velocity),
        density=float(cfg.flight.air_density),
        gravity=9.81,
        mass_kg=mass_kg,
        ixx=mass_kg * roll_radius ** 2,
        iyy=mass_kg * pitch_radius ** 2,
        izz=mass_kg * yaw_radius ** 2,
        x_cg=0.25 * mean_chord,
        y_cg=0.0,
        z_cg=0.0,
    )


def parse_avl_eigenvalue_file(path: Path) -> tuple[AvlEigenvalue, ...]:
    pattern = re.compile(
        r"^\s*(?P<run>\d+)\s+(?P<real>[-+0-9.Ee]+)\s+(?P<imag>[-+0-9.Ee]+)\s*$"
    )
    eigenvalues: list[AvlEigenvalue] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        eigenvalues.append(
            AvlEigenvalue(
                mode_index=len(eigenvalues) + 1,
                real=float(match.group("real")),
                imag=float(match.group("imag")),
            )
        )
    return tuple(eigenvalues)


def parse_avl_mode_stdout(stdout_text: str) -> tuple[AvlModeBlock, ...]:
    lines = stdout_text.splitlines()
    mode_header = re.compile(
        r"^\s*mode\s+(?P<mode>\d+):\s+(?P<real>[-+0-9.Ee]+)\s+(?P<imag>[-+0-9.Ee]+)"
    )
    state_pattern = re.compile(
        r"([A-Za-z]+)\s*:\s*([-+0-9.Ee]+)\s+([-+0-9.Ee]+)"
    )
    blocks: list[AvlModeBlock] = []
    idx = 0
    while idx < len(lines):
        header_match = mode_header.match(lines[idx])
        if header_match is None:
            idx += 1
            continue
        states: dict[str, float] = {}
        scan = idx + 1
        while scan < len(lines):
            line = lines[scan]
            if not line.strip():
                break
            if mode_header.match(line):
                break
            for name, real_text, imag_text in state_pattern.findall(line):
                amp = math.hypot(float(real_text), float(imag_text))
                states[name.lower()] = amp
            scan += 1
        lateral = math.sqrt(sum(states.get(name, 0.0) ** 2 for name in LATERAL_STATE_NAMES))
        longitudinal = math.sqrt(sum(states.get(name, 0.0) ** 2 for name in LONGITUDINAL_STATE_NAMES))
        lateral_ratio = lateral / max(lateral + longitudinal, 1.0e-12)
        blocks.append(
            AvlModeBlock(
                mode_index=int(header_match.group("mode")),
                real=float(header_match.group("real")),
                imag=float(header_match.group("imag")),
                states=states,
                lateral_ratio=float(lateral_ratio),
            )
        )
        idx = scan
    return tuple(blocks)


def select_dutch_roll_mode(
    *,
    eigenvalues: tuple[AvlEigenvalue, ...],
    mode_blocks: tuple[AvlModeBlock, ...],
    allow_missing_mode: bool,
) -> tuple[bool, str, float | None, float | None]:
    oscillatory_blocks = [
        block
        for block in mode_blocks
        if abs(float(block.imag)) > OSCILLATORY_IMAG_TOL
    ]
    if oscillatory_blocks:
        ranked = sorted(
            oscillatory_blocks,
            key=lambda block: (
                float(block.lateral_ratio),
                abs(float(block.imag)),
                float(block.real),
            ),
            reverse=True,
        )
        selected = ranked[0]
        return True, "oscillatory_lateral_mode", float(selected.real), float(selected.imag)

    if allow_missing_mode and eigenvalues:
        fallback = max(eigenvalues, key=lambda eig: float(eig.real))
        return False, "least_damped_fallback", float(fallback.real), float(fallback.imag)

    return False, "mode_not_found", None, None


def select_spiral_mode(
    *,
    mode_blocks: tuple[AvlModeBlock, ...],
    min_time_to_double_s: float,
) -> SpiralModeEvaluation:
    candidates = [
        block
        for block in mode_blocks
        if abs(float(block.imag)) <= OSCILLATORY_IMAG_TOL
        and float(block.lateral_ratio) >= SPIRAL_LATERAL_RATIO_MIN
    ]
    if not candidates:
        return _unavailable_spiral_mode_evaluation()

    selected = max(
        candidates,
        key=lambda block: (float(block.real), float(block.lateral_ratio)),
    )
    real = float(selected.real)
    if real > OSCILLATORY_IMAG_TOL:
        time_to_double_s = math.log(2.0) / real
        feasible = time_to_double_s >= float(min_time_to_double_s)
        reason = "ok" if feasible else "time_to_double_below_limit"
        return SpiralModeEvaluation(
            mode_found=True,
            selection="least_stable_aperiodic_lateral_mode",
            real=real,
            time_to_double_s=float(time_to_double_s),
            time_to_half_s=None,
            feasible=bool(feasible),
            reason=reason,
        )
    if real < -OSCILLATORY_IMAG_TOL:
        time_to_half_s = math.log(2.0) / abs(real)
        return SpiralModeEvaluation(
            mode_found=True,
            selection="least_stable_aperiodic_lateral_mode",
            real=real,
            time_to_double_s=None,
            time_to_half_s=float(time_to_half_s),
            feasible=True,
            reason="stable",
        )
    return SpiralModeEvaluation(
        mode_found=True,
        selection="least_stable_aperiodic_lateral_mode",
        real=real,
        time_to_double_s=None,
        time_to_half_s=None,
        feasible=False,
        reason="neutral_spiral_mode",
    )


def run_avl_stability_case(
    *,
    avl_bin: Path,
    case_avl_path: Path,
    case_dir: Path,
    mode_params: AvlModeParameters,
    allow_missing_mode: bool,
    min_spiral_time_to_double_s: float,
) -> AvlEvaluation:
    mode_file = case_dir / "case_modes.st"
    stdout_log = case_dir / "avl_mode_stdout.log"
    if mode_file.exists():
        mode_file.unlink()
    command_text = "\n".join(
        [
            "plop",
            "g",
            "",
            f"load {case_avl_path.name}",
            "mode",
            "m",
            f"v {mode_params.velocity:.9f}",
            f"d {mode_params.density:.9f}",
            f"g {mode_params.gravity:.9f}",
            f"m {mode_params.mass_kg:.9f}",
            f"ix {mode_params.ixx:.9f}",
            f"iy {mode_params.iyy:.9f}",
            f"iz {mode_params.izz:.9f}",
            f"x {mode_params.x_cg:.9f}",
            f"y {mode_params.y_cg:.9f}",
            f"z {mode_params.z_cg:.9f}",
            f"cd {mode_params.cdo:.9f}",
            f"la {mode_params.dcl_a:.9f}",
            f"lu {mode_params.dcl_u:.9f}",
            f"ma {mode_params.dcm_a:.9f}",
            f"mu {mode_params.dcm_u:.9f}",
            "",
            "n",
            "w",
            mode_file.name,
            "",
            "quit",
            "",
        ]
    )
    proc = subprocess.run(
        [str(avl_bin)],
        input=command_text,
        text=True,
        capture_output=True,
        cwd=case_dir,
        check=False,
    )
    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")

    eigenvalues = parse_avl_eigenvalue_file(mode_file) if mode_file.exists() else ()
    mode_blocks = parse_avl_mode_stdout(stdout_text)
    dutch_roll_found, selection, dutch_real, dutch_imag = select_dutch_roll_mode(
        eigenvalues=eigenvalues,
        mode_blocks=mode_blocks,
        allow_missing_mode=allow_missing_mode,
    )
    spiral_eval = select_spiral_mode(
        mode_blocks=mode_blocks,
        min_time_to_double_s=float(min_spiral_time_to_double_s),
    )
    aero_status = "mode_not_found"
    aero_feasible = False
    if dutch_real is not None:
        aero_feasible = bool(dutch_real <= 0.0)
        if dutch_roll_found:
            aero_status = "stable" if aero_feasible else "unstable"
        else:
            aero_status = "stable_fallback" if aero_feasible else "unstable_fallback"

    return AvlEvaluation(
        avl_case_path=str(case_avl_path.resolve()),
        mode_file_path=str(mode_file.resolve()) if mode_file.exists() else None,
        stdout_log_path=str(stdout_log.resolve()),
        dutch_roll_found=bool(dutch_roll_found),
        dutch_roll_selection=str(selection),
        dutch_roll_real=dutch_real,
        dutch_roll_imag=dutch_imag,
        aero_status=aero_status,
        aero_feasible=aero_feasible,
        eigenvalue_count=len(eigenvalues),
        spiral_eval=spiral_eval,
    )


def _parse_avl_scalar(text: str, label: str, *, ignore_case: bool = False) -> float | None:
    pattern = re.compile(
        rf"\b{re.escape(label)}\s*=\s*(?P<value>{FLOAT_TOKEN}|\*{{3,}})",
        flags=re.IGNORECASE if ignore_case else 0,
    )
    match = pattern.search(text)
    if match is None:
        return None
    value_text = match.group("value")
    if "*" in value_text:
        return None
    return float(value_text)


def parse_avl_force_totals(path: Path) -> dict[str, float] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    cl_trim = _parse_avl_scalar(text, "CLtot")
    cd_induced = _parse_avl_scalar(text, "CDind")
    aoa_trim_deg = _parse_avl_scalar(text, "Alpha")
    span_efficiency = _parse_avl_scalar(text, "e")
    cl_roll_total = _parse_avl_scalar(text, "Cltot")
    cn_total = _parse_avl_scalar(text, "Cntot")
    if (
        cl_trim is None
        and cd_induced is None
        and aoa_trim_deg is None
        and span_efficiency is None
        and cl_roll_total is None
        and cn_total is None
    ):
        return None
    payload: dict[str, float] = {}
    if cl_trim is not None:
        payload["cl_trim"] = float(cl_trim)
    if cd_induced is not None:
        payload["cd_induced"] = float(cd_induced)
    if aoa_trim_deg is not None:
        payload["aoa_trim_deg"] = float(aoa_trim_deg)
    if span_efficiency is not None:
        payload["span_efficiency"] = float(span_efficiency)
    if cl_roll_total is not None:
        payload["cl_roll_total"] = float(cl_roll_total)
    if cn_total is not None:
        payload["cn_total"] = float(cn_total)
    return payload


def parse_avl_stability_derivatives(path: Path) -> dict[str, float | None] | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="ignore")
    keys = ("clb", "cnb", "cld02", "cnd02")
    payload = {key: _parse_avl_scalar(text, key, ignore_case=True) for key in keys}
    if all(value is None for value in payload.values()):
        return None
    return payload


def run_avl_stability_derivatives_case(
    *,
    avl_bin: Path,
    case_avl_path: Path,
    case_dir: Path,
    cl_required: float,
) -> ControlCouplingEvaluation:
    st_file = case_dir / "case_trim_derivatives.st"
    stdout_log = case_dir / "avl_trim_derivatives_stdout.log"
    if st_file.exists():
        st_file.unlink()
    command_text = "\n".join(
        [
            "plop",
            "g",
            "",
            f"load {case_avl_path.name}",
            "oper",
            "c1",
            f"c {float(cl_required):.9f}",
            "",
            "x",
            "st",
            st_file.name,
            "",
            "quit",
            "",
        ]
    )
    proc = subprocess.run(
        [str(avl_bin)],
        input=command_text,
        text=True,
        capture_output=True,
        cwd=case_dir,
        check=False,
    )
    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")

    derivatives = parse_avl_stability_derivatives(st_file)
    if proc.returncode != 0:
        return ControlCouplingEvaluation(
            st_file_path=str(st_file.resolve()) if st_file.exists() else None,
            stdout_log_path=str(stdout_log.resolve()),
            cl_rudder_derivative=None,
            cn_rudder_derivative=None,
            roll_to_yaw_ratio=None,
            coupling_reason="stability_derivative_runtime_error",
        )
    if derivatives is None:
        return ControlCouplingEvaluation(
            st_file_path=str(st_file.resolve()) if st_file.exists() else None,
            stdout_log_path=str(stdout_log.resolve()),
            cl_rudder_derivative=None,
            cn_rudder_derivative=None,
            roll_to_yaw_ratio=None,
            coupling_reason="stability_derivatives_missing",
        )

    cl_rudder = derivatives.get("cld02")
    cn_rudder = derivatives.get("cnd02")
    if cn_rudder is None:
        ratio = None
        reason = "rudder_yaw_derivative_missing"
    elif abs(float(cn_rudder)) <= 1.0e-12:
        ratio = None
        reason = "rudder_yaw_authority_zero"
    elif cl_rudder is None:
        ratio = None
        reason = "rudder_roll_derivative_missing"
    else:
        ratio = abs(float(cl_rudder)) / abs(float(cn_rudder))
        reason = "ok"

    return ControlCouplingEvaluation(
        st_file_path=str(st_file.resolve()) if st_file.exists() else None,
        stdout_log_path=str(stdout_log.resolve()),
        cl_rudder_derivative=None if cl_rudder is None else float(cl_rudder),
        cn_rudder_derivative=None if cn_rudder is None else float(cn_rudder),
        roll_to_yaw_ratio=None if ratio is None else float(ratio),
        coupling_reason=reason,
    )


def run_avl_trim_case(
    *,
    avl_bin: Path,
    case_avl_path: Path,
    case_dir: Path,
    cl_required: float,
    beta_deg: float | None = None,
    output_stem: str = "trim",
) -> AvlTrimEvaluation:
    trim_file = case_dir / f"case_{output_stem}.ft"
    stdout_log = case_dir / f"avl_{output_stem}_stdout.log"
    if trim_file.exists():
        trim_file.unlink()
    oper_lines = [
        "oper",
        "c1",
        f"c {float(cl_required):.9f}",
        "",
    ]
    if beta_deg is not None:
        oper_lines.append(f"b b {float(beta_deg):.9f}")
    command_text = "\n".join(
        [
            "plop",
            "g",
            "",
            f"load {case_avl_path.name}",
            *oper_lines,
            "x",
            "ft",
            trim_file.name,
            "",
            "",
            "quit",
            "",
        ]
    )
    proc = subprocess.run(
        [str(avl_bin)],
        input=command_text,
        text=True,
        capture_output=True,
        cwd=case_dir,
        check=False,
    )
    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")

    parsed = parse_avl_force_totals(trim_file)
    trim_status = "trim_output_missing"
    trim_converged = False
    if proc.returncode != 0:
        trim_status = "avl_runtime_error"
    elif "Cannot trim." in stdout_text:
        trim_status = "trim_not_converged"
    elif parsed is None:
        trim_status = "trim_output_missing"
    elif {"cl_trim", "aoa_trim_deg"} - set(parsed):
        trim_status = "trim_output_incomplete"
    else:
        trim_status = "trim_converged"
        trim_converged = True

    return AvlTrimEvaluation(
        trim_file_path=str(trim_file.resolve()) if trim_file.exists() else None,
        stdout_log_path=str(stdout_log.resolve()),
        trim_status=trim_status,
        trim_converged=trim_converged,
        cl_trim=None if parsed is None else parsed.get("cl_trim"),
        cd_induced=None if parsed is None else parsed.get("cd_induced"),
        aoa_trim_deg=None if parsed is None else parsed.get("aoa_trim_deg"),
        span_efficiency=None if parsed is None else parsed.get("span_efficiency"),
    )


def run_avl_spanwise_load_case(
    *,
    avl_bin: Path,
    case_avl_path: Path,
    case_dir: Path,
    alpha_deg: float,
    velocity_mps: float,
    density_kgpm3: float,
    output_stem: str,
    airfoil_dir: Path | str | None = None,
) -> AvlSpanwiseLoadCase:
    case_dir.mkdir(parents=True, exist_ok=True)
    staged_avl_path = case_dir / case_avl_path.name
    if staged_avl_path.resolve() != case_avl_path.resolve():
        staged_avl_path.write_bytes(case_avl_path.read_bytes())
    stage_avl_airfoil_files(staged_avl_path, airfoil_dir=airfoil_dir)
    fs_file = case_dir / f"{output_stem}.fs"
    stdout_log = case_dir / f"avl_{output_stem}_stdout.log"
    if fs_file.exists():
        fs_file.unlink()
    command_text = "\n".join(
        [
            "plop",
            "g",
            "",
            f"load {staged_avl_path.name}",
            "oper",
            "m",
            f"v {float(velocity_mps):.9f}",
            f"d {float(density_kgpm3):.9f}",
            "",
            "a",
            "a",
            f"{float(alpha_deg):.9f}",
            "x",
            "fs",
            fs_file.name,
            "",
            "",
            "quit",
            "",
        ]
    )
    proc = subprocess.run(
        [str(avl_bin)],
        input=command_text,
        text=True,
        capture_output=True,
        cwd=case_dir,
        check=False,
    )
    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")
    if proc.returncode != 0:
        return AvlSpanwiseLoadCase(
            aoa_deg=float(alpha_deg),
            fs_file_path=str(fs_file.resolve()) if fs_file.exists() else None,
            stdout_log_path=str(stdout_log.resolve()),
            run_completed=False,
            run_status="avl_runtime_error",
        )
    if not fs_file.exists():
        return AvlSpanwiseLoadCase(
            aoa_deg=float(alpha_deg),
            fs_file_path=None,
            stdout_log_path=str(stdout_log.resolve()),
            run_completed=False,
            run_status="strip_force_output_missing",
        )
    return AvlSpanwiseLoadCase(
        aoa_deg=float(alpha_deg),
        fs_file_path=str(fs_file.resolve()),
        stdout_log_path=str(stdout_log.resolve()),
        run_completed=True,
        run_status="ok",
    )


def _resolve_beta_sweep_values(
    configured_values_deg: Iterable[float],
    *,
    max_sideslip_deg: float,
) -> tuple[float, ...]:
    unique_values = {0.0}
    limit = float(max_sideslip_deg)
    if limit < 0.0:
        raise ValueError("max_sideslip_deg must be >= 0.0.")
    for value in configured_values_deg:
        beta = float(value)
        if beta < 0.0:
            raise ValueError("aero_gates.beta_sweep_values must be non-negative.")
        if beta <= limit + 1.0e-12:
            unique_values.add(beta)
    unique_values.add(limit)
    return tuple(sorted(unique_values))


def _evaluate_beta_sweep_points(
    points: tuple[BetaSweepPoint, ...],
    *,
    required_max_beta_deg: float,
) -> BetaSweepEvaluation:
    if not points:
        return BetaSweepEvaluation(
            beta_values_deg=(),
            points=(),
            max_trimmed_beta_deg=None,
            cn_beta_per_rad=None,
            cl_beta_per_rad=None,
            directional_stable=False,
            sideslip_feasible=False,
            sideslip_reason="no_beta_points",
        )

    ordered_points = tuple(sorted(points, key=lambda point: float(point.beta_deg)))
    max_trimmed_beta_deg: float | None = None
    for point in ordered_points:
        if not point.trim_converged:
            break
        max_trimmed_beta_deg = float(point.beta_deg)

    sideslip_feasible = (
        max_trimmed_beta_deg is not None
        and max_trimmed_beta_deg >= float(required_max_beta_deg) - 1.0e-9
    )

    converged_nonzero = [
        point
        for point in ordered_points
        if point.trim_converged and abs(float(point.beta_deg)) > 1.0e-9
    ]
    cn_beta_per_rad = _fit_beta_derivative_per_rad(
        ordered_points,
        response_getter=lambda point: point.cn_total,
    )
    cl_beta_per_rad = _fit_beta_derivative_per_rad(
        ordered_points,
        response_getter=lambda point: point.cl_roll_total,
    )
    directional_stable = True
    stability_reason = "ok"
    if not converged_nonzero:
        directional_stable = False
        stability_reason = "no_converged_nonzero_beta_points"
    elif cn_beta_per_rad is None:
        directional_stable = False
        stability_reason = "cn_beta_unavailable"
    elif cn_beta_per_rad >= -1.0e-9:
        directional_stable = False
        stability_reason = "cn_beta_positive"
    else:
        zero_beta_point = next(
            (point for point in ordered_points if abs(float(point.beta_deg)) <= 1.0e-9),
            None,
        )
        baseline_cn = (
            0.0
            if zero_beta_point is None or zero_beta_point.cn_total is None
            else float(zero_beta_point.cn_total)
        )
        for point in converged_nonzero:
            if point.cn_total is None:
                directional_stable = False
                stability_reason = f"cntot_missing_at_beta_{point.beta_deg:.1f}"
                break
            delta_cn = float(point.cn_total) - baseline_cn
            if delta_cn * float(point.beta_deg) > 1.0e-9:
                directional_stable = False
                stability_reason = "cn_beta_positive"
                break

    reason = stability_reason
    if not sideslip_feasible:
        reason = f"trim_not_converged_at_beta_{float(required_max_beta_deg):.1f}"
    elif not directional_stable:
        reason = stability_reason

    return BetaSweepEvaluation(
        beta_values_deg=tuple(float(point.beta_deg) for point in ordered_points),
        points=ordered_points,
        max_trimmed_beta_deg=max_trimmed_beta_deg,
        cn_beta_per_rad=cn_beta_per_rad,
        cl_beta_per_rad=cl_beta_per_rad,
        directional_stable=bool(directional_stable),
        sideslip_feasible=bool(sideslip_feasible),
        sideslip_reason=reason,
    )


def _fit_beta_derivative_per_rad(
    points: tuple[BetaSweepPoint, ...],
    *,
    response_getter,
) -> float | None:
    sample_pairs: list[tuple[float, float]] = []
    for point in points:
        if not point.trim_converged:
            continue
        response = response_getter(point)
        if response is None:
            continue
        beta_rad = math.radians(float(point.beta_deg))
        sample_pairs.append((beta_rad, float(response)))

    if len(sample_pairs) < 2:
        return None

    beta_mean = sum(beta for beta, _ in sample_pairs) / len(sample_pairs)
    response_mean = sum(response for _, response in sample_pairs) / len(sample_pairs)
    denominator = sum((beta - beta_mean) ** 2 for beta, _ in sample_pairs)
    if denominator <= 1.0e-18:
        return None

    numerator = sum(
        (beta - beta_mean) * (response - response_mean)
        for beta, response in sample_pairs
    )
    return numerator / denominator


def run_avl_beta_sweep(
    *,
    avl_bin: str | Path,
    case_avl_path: Path,
    case_dir: Path,
    cl_required: float,
    beta_values_deg: tuple[float, ...] = (0.0, 5.0, 10.0, 12.0),
    mode_params: AvlModeParameters,
) -> BetaSweepEvaluation:
    del mode_params
    avl_bin_path = Path(avl_bin).expanduser().resolve()
    points: list[BetaSweepPoint] = []
    ordered_betas = tuple(sorted(float(value) for value in beta_values_deg))
    for beta_deg in ordered_betas:
        output_stem = f"beta_{_slug(beta_deg)}"
        trim_eval = run_avl_trim_case(
            avl_bin=avl_bin_path,
            case_avl_path=case_avl_path,
            case_dir=case_dir,
            cl_required=cl_required,
            beta_deg=float(beta_deg),
            output_stem=output_stem,
        )
        parsed = None
        if trim_eval.trim_file_path is not None:
            parsed = parse_avl_force_totals(Path(trim_eval.trim_file_path))
        points.append(
            BetaSweepPoint(
                beta_deg=float(beta_deg),
                cl_trim=trim_eval.cl_trim,
                cd_induced=trim_eval.cd_induced,
                aoa_trim_deg=trim_eval.aoa_trim_deg,
                cn_total=None if parsed is None else parsed.get("cn_total"),
                cl_roll_total=None if parsed is None else parsed.get("cl_roll_total"),
                trim_converged=bool(trim_eval.trim_converged),
            )
        )

    required_max_beta_deg = max(ordered_betas) if ordered_betas else 0.0
    return _evaluate_beta_sweep_points(
        tuple(points),
        required_max_beta_deg=float(required_max_beta_deg),
    )


_empty_aero_performance = empty_aero_performance


def _resolve_candidate_avl_aoa_seed(cfg) -> tuple[float, ...]:
    lod_path = getattr(getattr(cfg, "io", None), "vsp_lod", None)
    if lod_path is None:
        return ()
    lod_file = Path(lod_path).expanduser()
    if not lod_file.is_file():
        return ()
    try:
        cases = VSPAeroParser(lod_file, getattr(cfg.io, "vsp_polar", None)).parse()
    except Exception:
        return ()
    values = sorted({round(float(case.aoa_deg), 9) for case in cases})
    return tuple(float(value) for value in values)


def _build_candidate_avl_aoa_sweep(
    *,
    trim_aoa_deg: float,
    seed_values_deg: Iterable[float],
) -> tuple[float, ...]:
    values = {round(float(trim_aoa_deg), 9)}
    seed_values = tuple(float(value) for value in seed_values_deg)
    if seed_values:
        values.update(round(value, 9) for value in seed_values)
    else:
        for offset_deg in (-4.0, -2.0, 0.0, 2.0, 4.0):
            values.add(round(float(trim_aoa_deg) + offset_deg, 9))
    return tuple(sorted(float(value) for value in values))


def run_inverse_design_case(
    *,
    inverse_script: Path,
    config_path: Path,
    design_report: Path,
    output_dir: Path,
    target_shape_z_scale: float,
    dihedral_exponent: float,
    python_executable: Path,
    main_plateau_grid: str,
    main_taper_fill_grid: str,
    rear_radius_grid: str,
    rear_outboard_grid: str,
    wall_thickness_grid: str,
    refresh_steps: int,
    cobyla_maxiter: int,
    cobyla_rhobeg: float,
    skip_local_refine: bool,
    local_refine_feasible_seeds: int,
    local_refine_near_feasible_seeds: int,
    local_refine_max_starts: int,
    local_refine_early_stop_patience: int,
    local_refine_early_stop_abs_improvement_kg: float,
    aero_source_mode: str,
    vspaero_analysis_method: str,
    candidate_avl_spanwise_loads_json: Path | None,
    candidate_fixed_alpha_loads_json: Path | None,
    rib_zonewise_mode: str,
    skip_step_export: bool,
    strict: bool = False,
) -> tuple[str | None, str | None, str | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(python_executable),
        str(inverse_script),
        "--config",
        str(config_path),
        "--design-report",
        str(design_report),
        "--output-dir",
        str(output_dir),
        "--target-shape-z-scale",
        f"{float(target_shape_z_scale):.9f}",
        "--dihedral-exponent",
        f"{float(dihedral_exponent):.9f}",
        "--loaded-shape-mode",
        "exact_nodal",
        "--main-plateau-grid",
        main_plateau_grid,
        "--main-taper-fill-grid",
        main_taper_fill_grid,
        "--rear-radius-grid",
        rear_radius_grid,
        "--rear-outboard-grid",
        rear_outboard_grid,
        "--wall-thickness-grid",
        wall_thickness_grid,
        "--refresh-steps",
        str(int(refresh_steps)),
        "--cobyla-maxiter",
        str(int(cobyla_maxiter)),
        "--cobyla-rhobeg",
        f"{float(cobyla_rhobeg):.9f}",
        "--local-refine-feasible-seeds",
        str(int(local_refine_feasible_seeds)),
        "--local-refine-near-feasible-seeds",
        str(int(local_refine_near_feasible_seeds)),
        "--local-refine-max-starts",
        str(int(local_refine_max_starts)),
        "--local-refine-early-stop-patience",
        str(int(local_refine_early_stop_patience)),
        "--local-refine-early-stop-abs-improvement-kg",
        f"{float(local_refine_early_stop_abs_improvement_kg):.9f}",
        "--aero-source-mode",
        str(aero_source_mode),
        "--vspaero-analysis-method",
        str(vspaero_analysis_method),
        "--rib-zonewise-mode",
        str(rib_zonewise_mode),
    ]
    if (
        str(aero_source_mode) == CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE
        and candidate_avl_spanwise_loads_json is not None
    ):
        cmd.extend(
            [
                "--candidate-avl-spanwise-loads-json",
                str(candidate_avl_spanwise_loads_json),
            ]
        )
    if (
        str(aero_source_mode) == ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE
        and candidate_fixed_alpha_loads_json is not None
    ):
        cmd.extend(
            [
                "--candidate-fixed-alpha-loads-json",
                str(candidate_fixed_alpha_loads_json),
            ]
        )
    if skip_local_refine:
        cmd.append("--skip-local-refine")
    if skip_step_export:
        cmd.append("--skip-step-export")
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        check=False,
    )
    stdout_log = output_dir / "inverse_design_stdout.log"
    stdout_text = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    stdout_log.write_text(stdout_text, encoding="utf-8")
    summary_path = output_dir / "direct_dual_beam_inverse_design_refresh_summary.json"
    if proc.returncode != 0 or not summary_path.exists():
        error_message = (
            f"inverse-design subprocess failed (rc={proc.returncode}); see {stdout_log}"
        )
        if strict:
            raise RuntimeError(error_message)
        return None, str(stdout_log.resolve()), error_message
    return str(summary_path.resolve()), str(stdout_log.resolve()), None


def _extract_wire_metrics(summary_payload: dict[str, object]) -> tuple[float | None, float | None, str | None]:
    artifacts = summary_payload.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return None, None, None
    wire_json = artifacts.get("wire_rigging_json")
    if not wire_json:
        return None, None, None
    wire_path = Path(str(wire_json))
    if not wire_path.exists():
        return None, None, str(wire_path)
    payload = json.loads(wire_path.read_text(encoding="utf-8"))
    records = payload.get("wire_rigging") or []
    if not records:
        return None, None, str(wire_path)
    first = records[0]
    return (
        None if first.get("tension_force_n") is None else float(first["tension_force_n"]),
        None if first.get("tension_margin_n") is None else float(first["tension_margin_n"]),
        str(wire_path.resolve()),
    )


def _read_inverse_summary(summary_path: Path) -> dict[str, object]:
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _extract_aero_contract_snapshot(summary_payload: dict[str, object]) -> dict[str, object]:
    contract = summary_payload.get("aero_contract")
    artifacts = summary_payload.get("artifacts")
    if not isinstance(contract, dict):
        return {
            "aero_source_mode": None,
            "baseline_load_source": None,
            "refresh_load_source": None,
            "load_ownership": None,
            "artifact_ownership": None,
            "selected_cruise_aoa_deg": None,
            "aero_contract_json_path": None,
        }
    return {
        "aero_source_mode": (
            None if contract.get("source_mode") is None else str(contract["source_mode"])
        ),
        "baseline_load_source": (
            None
            if contract.get("baseline_load_source") is None
            else str(contract["baseline_load_source"])
        ),
        "refresh_load_source": (
            None
            if contract.get("refresh_load_source") is None
            else str(contract["refresh_load_source"])
        ),
        "load_ownership": (
            None if contract.get("load_ownership") is None else str(contract["load_ownership"])
        ),
        "artifact_ownership": (
            None
            if contract.get("artifact_ownership") is None
            else str(contract["artifact_ownership"])
        ),
        "selected_cruise_aoa_deg": (
            None
            if contract.get("selected_cruise_aoa_deg") is None
            else float(contract["selected_cruise_aoa_deg"])
        ),
        "aero_contract_json_path": (
            None
            if not isinstance(artifacts, dict) or artifacts.get("aero_contract_json") is None
            else str(artifacts["aero_contract_json"])
        ),
    }


def _empty_mission_snapshot() -> dict[str, object]:
    return {
        "mission_objective_mode": None,
        "mission_feasible": None,
        "target_range_km": None,
        "target_range_passed": None,
        "target_range_margin_m": None,
        "best_range_m": None,
        "best_range_speed_mps": None,
        "best_endurance_s": None,
        "min_power_w": None,
        "min_power_speed_mps": None,
        "mission_score": None,
        "mission_score_reason": None,
        "pilot_power_model": None,
        "pilot_power_anchor": None,
    }


def _mission_snapshot_from_payload(mission: dict[str, object]) -> dict[str, object]:
    return {
        "mission_objective_mode": (
            None if mission.get("mission_objective_mode") is None else str(mission["mission_objective_mode"])
        ),
        "mission_feasible": (
            None if mission.get("mission_feasible") is None else bool(mission["mission_feasible"])
        ),
        "target_range_km": (
            None if mission.get("target_range_km") is None else float(mission["target_range_km"])
        ),
        "target_range_passed": (
            None if mission.get("target_range_passed") is None else bool(mission["target_range_passed"])
        ),
        "target_range_margin_m": (
            None if mission.get("target_range_margin_m") is None else float(mission["target_range_margin_m"])
        ),
        "best_range_m": None if mission.get("best_range_m") is None else float(mission["best_range_m"]),
        "best_range_speed_mps": (
            None if mission.get("best_range_speed_mps") is None else float(mission["best_range_speed_mps"])
        ),
        "best_endurance_s": (
            None if mission.get("best_endurance_s") is None else float(mission["best_endurance_s"])
        ),
        "min_power_w": None if mission.get("min_power_w") is None else float(mission["min_power_w"]),
        "min_power_speed_mps": (
            None if mission.get("min_power_speed_mps") is None else float(mission["min_power_speed_mps"])
        ),
        "mission_score": None if mission.get("mission_score") is None else float(mission["mission_score"]),
        "mission_score_reason": (
            None if mission.get("mission_score_reason") is None else str(mission["mission_score_reason"])
        ),
        "pilot_power_model": (
            None if mission.get("pilot_power_model") is None else str(mission["pilot_power_model"])
        ),
        "pilot_power_anchor": (
            None if mission.get("pilot_power_anchor") is None else str(mission["pilot_power_anchor"])
        ),
    }


def _build_campaign_mission_snapshot(
    *,
    cfg: object,
    aero_perf_eval: AeroPerformanceEvaluation,
) -> dict[str, object]:
    flight_cfg = getattr(cfg, "flight", None)
    mission_cfg = getattr(cfg, "mission", None)
    if flight_cfg is None or mission_cfg is None:
        return _empty_mission_snapshot()

    ref_speed_mps = getattr(flight_cfg, "velocity", None)
    ref_power_w = aero_perf_eval.aero_power_w
    target_range_km = getattr(mission_cfg, "target_range_km", None)
    objective_mode = getattr(mission_cfg, "objective_mode", None)
    rider_model = getattr(mission_cfg, "rider_model", None)
    if rider_model != "fake_anchor_curve":
        return _empty_mission_snapshot()
    if not (
        isinstance(ref_speed_mps, (int, float))
        and math.isfinite(float(ref_speed_mps))
        and float(ref_speed_mps) > 0.0
        and isinstance(ref_power_w, (int, float))
        and math.isfinite(float(ref_power_w))
        and float(ref_power_w) > 0.0
        and isinstance(target_range_km, (int, float))
        and math.isfinite(float(target_range_km))
        and float(target_range_km) > 0.0
        and objective_mode in {"max_range", "min_power"}
    ):
        return _empty_mission_snapshot()

    min_speed = getattr(mission_cfg, "speed_sweep_min_mps", None)
    max_speed = getattr(mission_cfg, "speed_sweep_max_mps", None)
    points = getattr(mission_cfg, "speed_sweep_points", None)
    anchor_power_w = getattr(mission_cfg, "anchor_power_w", None)
    anchor_duration_min = getattr(mission_cfg, "anchor_duration_min", None)
    if not (
        isinstance(min_speed, (int, float))
        and isinstance(max_speed, (int, float))
        and isinstance(points, int)
        and math.isfinite(float(min_speed))
        and math.isfinite(float(max_speed))
        and math.isfinite(float(points))
        and float(min_speed) > 0.0
        and float(max_speed) > float(min_speed)
        and points >= 2
        and isinstance(anchor_power_w, (int, float))
        and math.isfinite(float(anchor_power_w))
        and float(anchor_power_w) > 0.0
        and isinstance(anchor_duration_min, (int, float))
        and math.isfinite(float(anchor_duration_min))
        and float(anchor_duration_min) > 0.0
    ):
        return _empty_mission_snapshot()

    speeds_mps = tuple(
        float(min_speed) + (float(max_speed) - float(min_speed)) * idx / (points - 1)
        for idx in range(points)
    )
    reference_power_w = float(ref_power_w)
    reference_speed_mps = float(ref_speed_mps)
    power_required_w: list[float]
    cd_total_est = aero_perf_eval.cd_total_est
    cd_induced = aero_perf_eval.cd_induced
    if (
        isinstance(cd_total_est, (int, float))
        and isinstance(cd_induced, (int, float))
        and math.isfinite(float(cd_total_est))
        and math.isfinite(float(cd_induced))
        and float(cd_total_est) > 0.0
        and float(cd_induced) >= 0.0
    ):
        cd_profile = max(float(cd_total_est) - float(cd_induced), 0.0)
        total_split = float(cd_induced) + cd_profile
        if total_split > 0.0:
            induced_ref_power = reference_power_w * (float(cd_induced) / total_split)
            profile_ref_power = reference_power_w * (cd_profile / total_split)
            power_required_w = [
                induced_ref_power * (reference_speed_mps / speed_mps)
                + profile_ref_power * (speed_mps / reference_speed_mps) ** 3
                for speed_mps in speeds_mps
            ]
        else:
            power_required_w = [
                reference_power_w * (speed_mps / reference_speed_mps) ** 3
                for speed_mps in speeds_mps
            ]
    else:
        power_required_w = [
            reference_power_w * (speed_mps / reference_speed_mps) ** 3 for speed_mps in speeds_mps
        ]

    try:
        mission_result = evaluate_mission_objective(
            MissionEvaluationInputs(
                objective_mode=str(objective_mode),
                target_range_km=float(target_range_km),
                speed_mps=speeds_mps,
                power_required_w=tuple(float(value) for value in power_required_w),
                rider_curve=FakeAnchorCurve(
                    anchor_power_w=float(anchor_power_w),
                    anchor_duration_min=float(anchor_duration_min),
                ),
            )
        )
    except Exception:
        return _empty_mission_snapshot()

    return {
        "mission_objective_mode": mission_result.mission_objective_mode,
        "mission_feasible": mission_result.mission_feasible,
        "target_range_km": mission_result.target_range_km,
        "target_range_passed": mission_result.target_range_passed,
        "target_range_margin_m": mission_result.target_range_margin_m,
        "best_range_m": mission_result.best_range_m,
        "best_range_speed_mps": mission_result.best_range_speed_mps,
        "best_endurance_s": mission_result.best_endurance_s,
        "min_power_w": mission_result.min_power_w,
        "min_power_speed_mps": mission_result.min_power_speed_mps,
        "mission_score": mission_result.mission_score,
        "mission_score_reason": mission_result.mission_score_reason,
        "pilot_power_model": mission_result.pilot_power_model,
        "pilot_power_anchor": mission_result.pilot_power_anchor,
    }


def _mission_snapshot_from_summary(
    summary_payload: dict[str, object] | None,
    *,
    cfg: object | None = None,
    aero_perf_eval: AeroPerformanceEvaluation | None = None,
) -> dict[str, object]:
    mission = None if summary_payload is None else summary_payload.get("mission")
    if isinstance(mission, dict):
        return _mission_snapshot_from_payload(mission)
    if cfg is None or aero_perf_eval is None:
        return _empty_mission_snapshot()
    return _build_campaign_mission_snapshot(cfg=cfg, aero_perf_eval=aero_perf_eval)


def _structural_reject_reason(selected: dict[str, object]) -> str:
    failures = selected.get("failures") or []
    if isinstance(failures, list) and failures:
        return str(failures[0])
    hard_margins = selected.get("hard_margins") or {}
    if isinstance(hard_margins, dict) and hard_margins:
        return str(min(hard_margins.items(), key=lambda item: float(item[1]))[0])
    return "inverse_design_infeasible"


def _build_result_row(
    *,
    multiplier: float,
    dihedral_exponent: float,
    avl_eval: AvlEvaluation,
    aero_perf_eval: AeroPerformanceEvaluation,
    beta_eval: BetaSweepEvaluation | None,
    control_eval: ControlCouplingEvaluation | None,
    summary_payload: dict[str, object] | None,
    selected_output_dir: str | None,
    summary_json_path: str | None,
    error_message: str | None,
    cfg: object | None = None,
) -> SweepResult:
    if summary_payload is None:
        structure_status = "structural_failed" if error_message else "skipped"
        return SweepResult(
            dihedral_multiplier=float(multiplier),
            dihedral_exponent=float(dihedral_exponent),
            avl_case_path=avl_eval.avl_case_path,
            mode_file_path=avl_eval.mode_file_path,
            dutch_roll_found=avl_eval.dutch_roll_found,
            dutch_roll_selection=avl_eval.dutch_roll_selection,
            dutch_roll_real=avl_eval.dutch_roll_real,
            dutch_roll_imag=avl_eval.dutch_roll_imag,
            aero_status=avl_eval.aero_status,
            aero_performance_feasible=aero_perf_eval.aero_performance_feasible,
            aero_performance_reason=aero_perf_eval.aero_performance_reason,
            cl_trim=aero_perf_eval.cl_trim,
            cd_induced=aero_perf_eval.cd_induced,
            cd_total_est=aero_perf_eval.cd_total_est,
            ld_ratio=aero_perf_eval.ld_ratio,
            aoa_trim_deg=aero_perf_eval.aoa_trim_deg,
            span_efficiency=aero_perf_eval.span_efficiency,
            lift_total_n=aero_perf_eval.lift_total_n,
            aero_power_w=aero_perf_eval.aero_power_w,
            beta_sweep_max_beta_deg=None if beta_eval is None else beta_eval.max_trimmed_beta_deg,
            beta_sweep_cn_beta_per_rad=None if beta_eval is None else beta_eval.cn_beta_per_rad,
            beta_sweep_cl_beta_per_rad=None if beta_eval is None else beta_eval.cl_beta_per_rad,
            beta_sweep_directional_stable=None if beta_eval is None else beta_eval.directional_stable,
            beta_sweep_sideslip_feasible=None if beta_eval is None else beta_eval.sideslip_feasible,
            rudder_cl_derivative=None if control_eval is None else control_eval.cl_rudder_derivative,
            rudder_cn_derivative=None if control_eval is None else control_eval.cn_rudder_derivative,
            rudder_roll_to_yaw_ratio=None if control_eval is None else control_eval.roll_to_yaw_ratio,
            rudder_coupling_reason=None if control_eval is None else control_eval.coupling_reason,
            spiral_mode_real=avl_eval.spiral_eval.real,
            spiral_time_to_double_s=avl_eval.spiral_eval.time_to_double_s,
            spiral_time_to_half_s=avl_eval.spiral_eval.time_to_half_s,
            spiral_check_ok=avl_eval.spiral_eval.feasible,
            spiral_reason=avl_eval.spiral_eval.reason,
            structure_status=structure_status,
            tube_mass_kg=None,
            total_mass_kg=None,
            min_jig_clearance_mm=None,
            wire_tension_n=None,
            wire_margin_n=None,
            failure_index=None,
            buckling_index=None,
            objective_value_kg=None,
            realizable_mismatch_max_mm=None,
            structural_reject_reason=None,
            selected_output_dir=selected_output_dir,
            summary_json_path=summary_json_path,
            wire_rigging_json_path=None,
            error_message=error_message,
            **_mission_snapshot_from_summary(None, cfg=cfg, aero_perf_eval=aero_perf_eval),
        )

    iterations = summary_payload["iterations"]
    final = iterations[-1]
    selected = final["selected"]
    wire_tension_n, wire_margin_n, wire_json_path = _extract_wire_metrics(summary_payload)
    aero_snapshot = _extract_aero_contract_snapshot(summary_payload)
    mission_snapshot = _mission_snapshot_from_summary(
        summary_payload,
        cfg=cfg,
        aero_perf_eval=aero_perf_eval,
    )
    return SweepResult(
        dihedral_multiplier=float(multiplier),
        dihedral_exponent=float(dihedral_exponent),
        avl_case_path=avl_eval.avl_case_path,
        mode_file_path=avl_eval.mode_file_path,
        dutch_roll_found=avl_eval.dutch_roll_found,
        dutch_roll_selection=avl_eval.dutch_roll_selection,
        dutch_roll_real=avl_eval.dutch_roll_real,
        dutch_roll_imag=avl_eval.dutch_roll_imag,
        aero_status=avl_eval.aero_status,
        aero_performance_feasible=aero_perf_eval.aero_performance_feasible,
        aero_performance_reason=aero_perf_eval.aero_performance_reason,
        cl_trim=aero_perf_eval.cl_trim,
        cd_induced=aero_perf_eval.cd_induced,
        cd_total_est=aero_perf_eval.cd_total_est,
        ld_ratio=aero_perf_eval.ld_ratio,
        aoa_trim_deg=aero_perf_eval.aoa_trim_deg,
        span_efficiency=aero_perf_eval.span_efficiency,
        lift_total_n=aero_perf_eval.lift_total_n,
        aero_power_w=aero_perf_eval.aero_power_w,
        beta_sweep_max_beta_deg=None if beta_eval is None else beta_eval.max_trimmed_beta_deg,
        beta_sweep_cn_beta_per_rad=None if beta_eval is None else beta_eval.cn_beta_per_rad,
        beta_sweep_cl_beta_per_rad=None if beta_eval is None else beta_eval.cl_beta_per_rad,
        beta_sweep_directional_stable=None if beta_eval is None else beta_eval.directional_stable,
        beta_sweep_sideslip_feasible=None if beta_eval is None else beta_eval.sideslip_feasible,
        rudder_cl_derivative=None if control_eval is None else control_eval.cl_rudder_derivative,
        rudder_cn_derivative=None if control_eval is None else control_eval.cn_rudder_derivative,
        rudder_roll_to_yaw_ratio=None if control_eval is None else control_eval.roll_to_yaw_ratio,
        rudder_coupling_reason=None if control_eval is None else control_eval.coupling_reason,
        spiral_mode_real=avl_eval.spiral_eval.real,
        spiral_time_to_double_s=avl_eval.spiral_eval.time_to_double_s,
        spiral_time_to_half_s=avl_eval.spiral_eval.time_to_half_s,
        spiral_check_ok=avl_eval.spiral_eval.feasible,
        spiral_reason=avl_eval.spiral_eval.reason,
        structure_status="feasible" if bool(selected["overall_feasible"]) else "infeasible",
        tube_mass_kg=(
            None if selected.get("tube_mass_kg") is None else float(selected["tube_mass_kg"])
        ),
        total_mass_kg=float(selected["total_structural_mass_kg"]),
        min_jig_clearance_mm=float(selected["jig_ground_clearance_min_m"]) * 1000.0,
        wire_tension_n=wire_tension_n,
        wire_margin_n=wire_margin_n,
        failure_index=float(selected["equivalent_failure_index"]),
        buckling_index=float(selected["equivalent_buckling_index"]),
        objective_value_kg=float(selected["objective_value_kg"]),
        realizable_mismatch_max_mm=float(selected["target_shape_error_max_m"]) * 1000.0,
        structural_reject_reason=(
            None if bool(selected["overall_feasible"]) else _structural_reject_reason(selected)
        ),
        selected_output_dir=selected_output_dir,
        summary_json_path=summary_json_path,
        wire_rigging_json_path=wire_json_path,
        error_message=error_message,
        **mission_snapshot,
        **aero_snapshot,
    )


def _campaign_reject_reason(
    row: SweepResult,
    *,
    max_tube_mass_kg: float | None = None,
    mission_objective_mode: str | None = None,
) -> str:
    if row.aero_status not in {"stable", "stable_fallback"}:
        return f"aero_stability:{row.aero_status}"
    if not row.aero_performance_feasible:
        return f"aero_performance:{row.aero_performance_reason}"
    if row.beta_sweep_directional_stable is False or row.beta_sweep_sideslip_feasible is False:
        return "beta_sideslip:trim_or_directional_gate_failed"
    if row.spiral_check_ok is False:
        return f"spiral:{row.spiral_reason or 'failed'}"
    if row.error_message is not None or row.structure_status == "structural_failed":
        return "inverse_design_subprocess:failed"
    if (
        max_tube_mass_kg is not None
        and row.tube_mass_kg is not None
        and float(row.tube_mass_kg) > float(max_tube_mass_kg)
    ):
        return "structural:tube_mass_exceeds_limit"
    if row.structure_status == "infeasible":
        detail = row.structural_reject_reason or "inverse_design_infeasible"
        return f"structural:{detail}"
    if mission_objective_mode is not None:
        if row.mission_feasible is False:
            return "mission:mission_infeasible"
        if row.target_range_passed is False:
            return "mission:target_range_not_passed"
    return "none"


def _campaign_row_passes(
    row: SweepResult,
    *,
    max_tube_mass_kg: float | None = None,
) -> bool:
    return (
        _campaign_reject_reason(
            row,
            max_tube_mass_kg=max_tube_mass_kg,
        )
        == "none"
    )


def _find_first_pass_boundary_interval(
    rows: Sequence[SweepResult],
    *,
    max_tube_mass_kg: float | None = None,
) -> tuple[float, float] | None:
    ordered = sorted(rows, key=lambda row: float(row.dihedral_multiplier))
    if len(ordered) < 2:
        return None
    previous = ordered[0]
    previous_pass = _campaign_row_passes(
        previous,
        max_tube_mass_kg=max_tube_mass_kg,
    )
    for current in ordered[1:]:
        current_pass = _campaign_row_passes(
            current,
            max_tube_mass_kg=max_tube_mass_kg,
        )
        if (not previous_pass) and current_pass:
            return (float(previous.dihedral_multiplier), float(current.dihedral_multiplier))
        previous = current
        previous_pass = current_pass
    return None


def _summarize_first_pass_boundary(
    rows: Sequence[SweepResult],
    *,
    max_tube_mass_kg: float | None = None,
    refined_multipliers: Sequence[float] = (),
) -> dict[str, object]:
    boundary = _find_first_pass_boundary_interval(
        rows,
        max_tube_mass_kg=max_tube_mass_kg,
    )
    if boundary is None:
        return {
            "boundary_found": False,
            "final_fail_multiplier": None,
            "first_pass_multiplier": None,
            "interval_width": None,
            "refined_multipliers": [float(value) for value in refined_multipliers],
        }
    lower, upper = boundary
    return {
        "boundary_found": True,
        "final_fail_multiplier": float(lower),
        "first_pass_multiplier": float(upper),
        "interval_width": float(upper - lower),
        "refined_multipliers": [float(value) for value in refined_multipliers],
    }


def _auto_refine_first_pass_boundary(
    rows: Sequence[SweepResult],
    *,
    run_multiplier_case: Callable[[float], SweepResult],
    max_tube_mass_kg: float | None = None,
    target_width: float = 0.1,
    max_rounds: int = 4,
) -> tuple[list[SweepResult], list[float]]:
    working_rows = sorted(rows, key=lambda row: float(row.dihedral_multiplier))
    refined_multipliers: list[float] = []
    seen_multipliers = {float(row.dihedral_multiplier) for row in working_rows}
    for _ in range(max(0, int(max_rounds))):
        boundary = _find_first_pass_boundary_interval(
            working_rows,
            max_tube_mass_kg=max_tube_mass_kg,
        )
        if boundary is None:
            break
        lower, upper = boundary
        if float(upper - lower) <= float(target_width):
            break
        midpoint = 0.5 * (float(lower) + float(upper))
        if any(math.isclose(midpoint, existing, rel_tol=0.0, abs_tol=1e-9) for existing in seen_multipliers):
            break
        working_rows.append(run_multiplier_case(float(midpoint)))
        working_rows.sort(key=lambda row: float(row.dihedral_multiplier))
        refined_multipliers.append(float(midpoint))
        seen_multipliers.add(float(midpoint))
    return working_rows, refined_multipliers


def _campaign_gate_penalty_kg(reject_reason: str) -> float:
    if reject_reason == "none":
        return 0.0
    for prefix, penalty in CAMPAIGN_GATE_PENALTIES_KG.items():
        if reject_reason.startswith(prefix):
            return float(penalty)
    return float(CAMPAIGN_GATE_PENALTIES_KG["structural"])


def _campaign_mission_objective_mode(rows: Iterable[SweepResult]) -> str | None:
    rows = list(rows)
    if not rows:
        return None
    modes = {row.mission_objective_mode for row in rows}
    if len(modes) == 1 and None not in modes and all(row.mission_score is not None for row in rows):
        return next(iter(modes))
    return None


def _campaign_base_score(
    row: SweepResult,
    *,
    mission_objective_mode: str | None,
) -> float:
    if mission_objective_mode is not None and row.mission_score is not None:
        return float(row.mission_score)
    if row.objective_value_kg is not None:
        return float(row.objective_value_kg)
    return float("inf")


def _campaign_score_formula_label(mission_objective_mode: str | None) -> str:
    if mission_objective_mode is None:
        return "rank by gate tier, then objective_value_kg; candidate_score = objective_value_kg + gate penalty"
    return (
        f"rank by gate tier, then mission_score ({mission_objective_mode}) "
        "if available else objective_value_kg; candidate_score = base score + gate penalty"
    )


def _build_campaign_winner_evidence(row: SweepResult, *, passing_pool_exists: bool) -> str:
    mismatch_text = (
        "n/a" if row.realizable_mismatch_max_mm is None else f"{row.realizable_mismatch_max_mm:.3f} mm"
    )
    clearance_text = (
        "n/a" if row.min_jig_clearance_mm is None else f"{row.min_jig_clearance_mm:.3f} mm"
    )
    mass_text = "n/a" if row.total_mass_kg is None else f"{row.total_mass_kg:.3f} kg"
    prefix = (
        "lowest fully-passing campaign score"
        if passing_pool_exists
        else "no fully-passing candidate; lowest penalized campaign score"
    )
    mission_text = (
        ""
        if row.mission_objective_mode is None or row.mission_score is None
        else f", mission={row.mission_objective_mode}:{row.mission_score:.3f}"
    )
    return (
        f"{prefix}; score={row.candidate_score:.3f}, "
        f"mass={mass_text}, mismatch={mismatch_text}, clearance={clearance_text}, "
        f"aero source={_aero_source_label(row.aero_source_mode)}{mission_text}"
    )


def _campaign_non_mission_gate_reject_reason(
    row: SweepResult,
    *,
    max_tube_mass_kg: float | None = None,
) -> str:
    return _campaign_reject_reason(
        row,
        max_tube_mass_kg=max_tube_mass_kg,
        mission_objective_mode=None,
    )


def _campaign_selection_key(
    row: SweepResult,
    *,
    mission_objective_mode: str | None,
) -> tuple[float, float, float, float, float]:
    return (
        _campaign_gate_penalty_kg(row.reject_reason),
        _campaign_base_score(
            row,
            mission_objective_mode=mission_objective_mode,
        ),
        float(row.objective_value_kg if row.objective_value_kg is not None else float("inf")),
        float(row.total_mass_kg if row.total_mass_kg is not None else float("inf")),
        float(
            row.realizable_mismatch_max_mm
            if row.realizable_mismatch_max_mm is not None
            else float("inf")
        ),
    )


def _annotate_campaign_selection(
    rows: list[SweepResult],
    *,
    max_tube_mass_kg: float | None = None,
    mission_objective_mode: str | None = None,
) -> tuple[list[SweepResult], dict[str, object] | None]:
    if not rows:
        return [], None

    effective_mission_objective_mode = (
        mission_objective_mode
        if mission_objective_mode is not None
        else _campaign_mission_objective_mode(rows)
    )

    def _row_reject_reason(row: SweepResult) -> str:
        return _campaign_reject_reason(
            row,
            max_tube_mass_kg=max_tube_mass_kg,
            mission_objective_mode=effective_mission_objective_mode,
        )

    scored_rows = [
        replace(
            row,
            reject_reason=_row_reject_reason(row),
            candidate_score=float(
                _campaign_base_score(
                    row,
                    mission_objective_mode=effective_mission_objective_mode,
                )
                + _campaign_gate_penalty_kg(_row_reject_reason(row))
            ),
        )
        for row in rows
    ]
    passing_rows = [row for row in scored_rows if row.reject_reason == "none"]
    non_mission_gated_rows = [
        row
        for row in scored_rows
        if _campaign_non_mission_gate_reject_reason(
            row,
            max_tube_mass_kg=max_tube_mass_kg,
        )
        == "none"
    ]
    winner_pool = (
        passing_rows
        if passing_rows
        else non_mission_gated_rows
        if non_mission_gated_rows
        else scored_rows
    )
    winner = min(
        winner_pool,
        key=lambda row: _campaign_selection_key(
            row,
            mission_objective_mode=effective_mission_objective_mode,
        ),
    )
    winner_evidence_text = _build_campaign_winner_evidence(
        winner,
        passing_pool_exists=bool(passing_rows),
    )

    annotated: list[SweepResult] = []
    for row in scored_rows:
        if row is winner:
            selection_status = "winner" if passing_rows else "nearest_candidate"
            winner_evidence = winner_evidence_text
        elif row.reject_reason == "none":
            selection_status = "feasible_runner_up"
            winner_evidence = None
        else:
            selection_status = "rejected"
            winner_evidence = None
        annotated.append(
            replace(
                row,
                selection_status=selection_status,
                winner_evidence=winner_evidence,
            )
        )

    winner_summary = {
        "selection_status": "winner" if passing_rows else "nearest_candidate",
        "mission_objective_mode": (
            winner.mission_objective_mode
            if winner.mission_objective_mode is not None
            else effective_mission_objective_mode
        ),
        "mission_feasible": winner.mission_feasible,
        "target_range_km": winner.target_range_km,
        "target_range_passed": winner.target_range_passed,
        "target_range_margin_m": winner.target_range_margin_m,
        "best_range_m": winner.best_range_m,
        "best_range_speed_mps": winner.best_range_speed_mps,
        "best_endurance_s": winner.best_endurance_s,
        "min_power_w": winner.min_power_w,
        "min_power_speed_mps": winner.min_power_speed_mps,
        "mission_score": winner.mission_score,
        "mission_score_reason": winner.mission_score_reason,
        "pilot_power_model": winner.pilot_power_model,
        "pilot_power_anchor": winner.pilot_power_anchor,
        "requested_knobs": {
            "dihedral_multiplier": float(winner.dihedral_multiplier),
            "dihedral_exponent": float(winner.dihedral_exponent),
        },
        "candidate_score": float(winner.candidate_score),
        "reject_reason": winner.reject_reason,
        "tube_mass_kg": None if winner.tube_mass_kg is None else float(winner.tube_mass_kg),
        "total_mass_kg": None if winner.total_mass_kg is None else float(winner.total_mass_kg),
        "realizable_mismatch_max_mm": (
            None if winner.realizable_mismatch_max_mm is None else float(winner.realizable_mismatch_max_mm)
        ),
        "jig_ground_clearance_min_mm": (
            None if winner.min_jig_clearance_mm is None else float(winner.min_jig_clearance_mm)
        ),
        "summary_json_path": winner.summary_json_path,
        "aero_source_mode": winner.aero_source_mode,
        "baseline_load_source": winner.baseline_load_source,
        "refresh_load_source": winner.refresh_load_source,
        "load_ownership": winner.load_ownership,
        "artifact_ownership": winner.artifact_ownership,
        "selected_cruise_aoa_deg": winner.selected_cruise_aoa_deg,
        "aero_contract_json_path": winner.aero_contract_json_path,
        "winner_evidence": winner_evidence_text,
    }
    return annotated, winner_summary


def _write_summary_csv(path: Path, rows: Iterable[SweepResult]) -> None:
    fieldnames = [
        "dihedral_multiplier",
        "dihedral_exponent",
        "avl_case_path",
        "mode_file_path",
        "dutch_roll_found",
        "dutch_roll_selection",
        "dutch_roll_real",
        "dutch_roll_imag",
        "aero_status",
        "aero_performance_feasible",
        "aero_performance_reason",
        "cl_trim",
        "cd_induced",
        "cd_total_est",
        "ld_ratio",
        "aoa_trim_deg",
        "span_efficiency",
        "lift_total_n",
        "aero_power_w",
        "beta_sweep_max_beta_deg",
        "beta_sweep_cn_beta_per_rad",
        "beta_sweep_cl_beta_per_rad",
        "beta_sweep_directional_stable",
        "beta_sweep_sideslip_feasible",
        "rudder_cl_derivative",
        "rudder_cn_derivative",
        "rudder_roll_to_yaw_ratio",
        "rudder_coupling_reason",
        "spiral_mode_real",
        "spiral_time_to_double_s",
        "spiral_time_to_half_s",
        "spiral_check_ok",
        "spiral_reason",
        "structure_status",
        "tube_mass_kg",
        "total_mass_kg",
        "min_jig_clearance_mm",
        "wire_tension_n",
        "wire_margin_n",
        "failure_index",
        "buckling_index",
        "objective_value_kg",
        "realizable_mismatch_max_mm",
        "structural_reject_reason",
        "selected_output_dir",
        "summary_json_path",
        "wire_rigging_json_path",
        "error_message",
        "mission_objective_mode",
        "mission_feasible",
        "target_range_km",
        "target_range_passed",
        "target_range_margin_m",
        "best_range_m",
        "best_range_speed_mps",
        "best_endurance_s",
        "min_power_w",
        "min_power_speed_mps",
        "mission_score",
        "mission_score_reason",
        "pilot_power_model",
        "pilot_power_anchor",
        "aero_source_mode",
        "baseline_load_source",
        "refresh_load_source",
        "load_ownership",
        "artifact_ownership",
        "selected_cruise_aoa_deg",
        "aero_contract_json_path",
        "candidate_score",
        "reject_reason",
        "selection_status",
        "winner_evidence",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _build_campaign_report_text(
    *,
    output_dir: Path,
    rows: list[SweepResult],
    search_budget: dict[str, object],
    winner_summary: dict[str, object] | None,
    first_pass_boundary: dict[str, object] | None,
) -> str:
    mission_objective_mode = _campaign_mission_objective_mode(rows)
    lines = [
        "=" * 108,
        "Outer-Loop Dihedral Sweep Campaign",
        "=" * 108,
        f"Output dir                    : {output_dir}",
        "",
        "Score contract:",
        "  score name                  : outer_loop_candidate_score",
        "  direction                   : lower_is_better",
        f"  formula                     : {_campaign_score_formula_label(mission_objective_mode)}",
        (
            "  mission objective mode      : "
            + ("n/a" if mission_objective_mode is None else str(mission_objective_mode))
        ),
        (
            "  gate penalties              : "
            f"aero_stability={CAMPAIGN_GATE_PENALTIES_KG['aero_stability']:.0f}, "
            f"aero_performance={CAMPAIGN_GATE_PENALTIES_KG['aero_performance']:.0f}, "
            f"beta_sideslip={CAMPAIGN_GATE_PENALTIES_KG['beta_sideslip']:.0f}, "
            f"spiral={CAMPAIGN_GATE_PENALTIES_KG['spiral']:.0f}, "
            f"inverse_subprocess={CAMPAIGN_GATE_PENALTIES_KG['inverse_design_subprocess']:.0f}, "
            f"structural={CAMPAIGN_GATE_PENALTIES_KG['structural']:.0f} kg"
        ),
        "",
        "Search budget:",
        (
            "  coarse grid points / case   : "
            f"{int(search_budget['coarse_grid_points_per_case'])}"
        ),
        (
            "  coarse axes                 : "
            f"plateau={search_budget['coarse_axes']['main_plateau_grid_points']}, "
            f"taper={search_budget['coarse_axes']['main_taper_fill_grid_points']}, "
            f"rear_radius={search_budget['coarse_axes']['rear_radius_grid_points']}, "
            f"rear_outboard={search_budget['coarse_axes']['rear_outboard_grid_points']}, "
            f"wall={search_budget['coarse_axes']['wall_thickness_grid_points']}"
        ),
        f"  refresh steps               : {search_budget['refresh_steps']}",
        f"  COBYLA maxiter / rhobeg     : {search_budget['cobyla_maxiter']} / {search_budget['cobyla_rhobeg']:.3f}",
        (
            "  local refine                : "
            + (
                "skipped"
                if search_budget["skip_local_refine"]
                else (
                    f"feasible={search_budget['local_refine_feasible_seeds']}, "
                    f"near={search_budget['local_refine_near_feasible_seeds']}, "
                    f"max_starts={search_budget['local_refine_max_starts']}, "
                    f"patience={search_budget['local_refine_early_stop_patience']}, "
                    f"abs_improve={search_budget['local_refine_early_stop_abs_improvement_kg']:.3f} kg"
                )
            )
        ),
        (
            "  aero source mode            : "
            f"{search_budget['aero_source_mode']} ({_aero_source_label(search_budget['aero_source_mode'])})"
        ),
        (
            "  spar tube mass limit        : "
            + (
                "disabled"
                if search_budget["max_tube_mass_kg"] is None
                else f"{float(search_budget['max_tube_mass_kg']):.3f} kg"
            )
        ),
        "",
    ]
    if first_pass_boundary is not None:
        lines.append("First-pass boundary:")
        if bool(first_pass_boundary.get("boundary_found")):
            lines.extend(
                [
                    (
                        "  final fail multiplier       : "
                        f"{float(first_pass_boundary['final_fail_multiplier']):.6f}"
                    ),
                    (
                        "  first pass multiplier       : "
                        f"{float(first_pass_boundary['first_pass_multiplier']):.6f}"
                    ),
                    (
                        "  interval width              : "
                        f"{float(first_pass_boundary['interval_width']):.6f}"
                    ),
                ]
            )
        else:
            lines.append("  boundary                    : not found")
        refined = list(first_pass_boundary.get("refined_multipliers") or [])
        lines.append(
            "  refined multipliers         : "
            + (", ".join(f"{float(value):.6f}" for value in refined) if refined else "none")
        )
        lines.append("")
    if winner_summary is not None:
        lines.extend(
            [
                "Winner summary:",
                f"  status                       : {winner_summary['selection_status']}",
                (
                    "  requested knobs              : "
                    f"dihedral_multiplier={winner_summary['requested_knobs']['dihedral_multiplier']:.3f}, "
                    f"dihedral_exponent={winner_summary['requested_knobs']['dihedral_exponent']:.3f}"
                ),
                f"  candidate score              : {winner_summary['candidate_score']:.3f}",
                (
                    "  mission objective mode       : "
                    + (
                        "n/a"
                        if winner_summary["mission_objective_mode"] is None
                        else str(winner_summary["mission_objective_mode"])
                    )
                ),
                (
                    "  mission feasible             : "
                    + (
                        "n/a"
                        if winner_summary["mission_feasible"] is None
                        else str(bool(winner_summary["mission_feasible"])).lower()
                    )
                ),
                (
                    "  target range / passed        : "
                    + (
                        "n/a"
                        if winner_summary["target_range_km"] is None
                        else f"{float(winner_summary['target_range_km']):.3f} km / {bool(winner_summary['target_range_passed'])}"
                    )
                ),
                (
                    "  target range margin          : "
                    + (
                        "n/a"
                        if winner_summary["target_range_margin_m"] is None
                        else f"{float(winner_summary['target_range_margin_m']):.3f} m"
                    )
                ),
                (
                    "  best range / speed           : "
                    + (
                        "n/a"
                        if winner_summary["best_range_m"] is None
                        else f"{float(winner_summary['best_range_m']):.3f} m @ {float(winner_summary['best_range_speed_mps']):.3f} m/s"
                    )
                ),
                (
                    "  best endurance               : "
                    + (
                        "n/a"
                        if winner_summary["best_endurance_s"] is None
                        else f"{float(winner_summary['best_endurance_s']):.3f} s"
                    )
                ),
                (
                    "  min power / speed            : "
                    + (
                        "n/a"
                        if winner_summary["min_power_w"] is None
                        else f"{float(winner_summary['min_power_w']):.3f} W @ {float(winner_summary['min_power_speed_mps']):.3f} m/s"
                    )
                ),
                (
                    "  mission score / reason       : "
                    + (
                        "n/a"
                        if winner_summary["mission_score"] is None
                        else f"{float(winner_summary['mission_score']):.3f} ({winner_summary['mission_score_reason']})"
                    )
                ),
                (
                    "  pilot power model / anchor   : "
                    + (
                        "n/a"
                        if winner_summary["pilot_power_model"] is None
                        else f"{winner_summary['pilot_power_model']} / {winner_summary['pilot_power_anchor']}"
                    )
                ),
                (
                    "  spar tube mass               : "
                    + (
                        "n/a"
                        if winner_summary["tube_mass_kg"] is None
                        else f"{float(winner_summary['tube_mass_kg']):.3f} kg"
                    )
                ),
                (
                    "  total mass                   : "
                    + (
                        "n/a"
                        if winner_summary["total_mass_kg"] is None
                        else f"{float(winner_summary['total_mass_kg']):.3f} kg"
                    )
                ),
                (
                    "  realizable mismatch max      : "
                    + (
                        "n/a"
                        if winner_summary["realizable_mismatch_max_mm"] is None
                        else f"{float(winner_summary['realizable_mismatch_max_mm']):.3f} mm"
                    )
                ),
                (
                    "  jig ground clearance min     : "
                    + (
                        "n/a"
                        if winner_summary["jig_ground_clearance_min_mm"] is None
                        else f"{float(winner_summary['jig_ground_clearance_min_mm']):.3f} mm"
                    )
                ),
                (
                    "  aero source mode            : "
                    + (
                        "unknown"
                        if winner_summary["aero_source_mode"] is None
                        else f"{winner_summary['aero_source_mode']} "
                        f"({_aero_source_label(winner_summary['aero_source_mode'])})"
                    )
                ),
                (
                    "  refresh load source         : "
                    + (
                        "n/a"
                        if winner_summary["refresh_load_source"] is None
                        else str(winner_summary["refresh_load_source"])
                    )
                ),
                (
                    "  load ownership              : "
                    + (
                        "n/a"
                        if winner_summary["load_ownership"] is None
                        else str(winner_summary["load_ownership"])
                    )
                ),
                f"  reject reason                : {winner_summary['reject_reason']}",
                (
                    "  aero contract JSON          : "
                    + (
                        "n/a"
                        if winner_summary["aero_contract_json_path"] is None
                        else str(winner_summary["aero_contract_json_path"])
                    )
                ),
                f"  winner evidence              : {winner_summary['winner_evidence']}",
                "",
            ]
        )
    lines.append(
        "multiplier | score | selection | aero source | reject reason | tube kg | mass kg | mismatch mm | clearance mm | mission | aero | struct"
    )
    for row in rows:
        mission_text = (
            "n/a"
            if row.mission_objective_mode is None or row.mission_score is None
            else f"{row.mission_objective_mode}:{row.mission_score:.3f}"
        )
        lines.append(
            f"{row.dihedral_multiplier:10.3f} | "
            f"{(f'{row.candidate_score:.3f}' if row.candidate_score is not None else 'n/a'):5s} | "
            f"{row.selection_status:14s} | "
            f"{_aero_source_label(row.aero_source_mode):17s} | "
            f"{row.reject_reason:28s} | "
            f"{(f'{row.tube_mass_kg:.3f}' if row.tube_mass_kg is not None else 'n/a'):7s} | "
            f"{(f'{row.total_mass_kg:.3f}' if row.total_mass_kg is not None else 'n/a'):7s} | "
            f"{(f'{row.realizable_mismatch_max_mm:.3f}' if row.realizable_mismatch_max_mm is not None else 'n/a'):11s} | "
            f"{(f'{row.min_jig_clearance_mm:.3f}' if row.min_jig_clearance_mm is not None else 'n/a'):12s} | "
            f"{mission_text:24s} | "
            f"{row.aero_status:5s} | "
            f"{row.structure_status}"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a lightweight outer-loop dihedral sweep campaign with AVL filtering plus inverse design."
    )
    parser.add_argument(
        "--base-avl",
        default=str(DEFAULT_BASE_AVL),
        help="Path to the baseline AVL geometry file.",
    )
    parser.add_argument(
        "--generate-wing-only-avl-fallback",
        action="store_true",
        help="If no --base-avl is given, generate a simple wing-only AVL from the current config for smoke testing.",
    )
    parser.add_argument(
        "--allow-missing-dutch-roll",
        action="store_true",
        help="If AVL exposes no oscillatory lateral mode, fall back to the least-damped eigenvalue instead of stopping the campaign.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--design-report", default=str(DEFAULT_DESIGN_REPORT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--inverse-script", default=str(DEFAULT_INVERSE_SCRIPT))
    parser.add_argument(
        "--aero-source-mode",
        default=CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
        choices=(
            LEGACY_AERO_SOURCE_MODE,
            CANDIDATE_RERUN_AERO_SOURCE_MODE,
            CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
            ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE,
        ),
        help=(
            "Choose whether each structural follow-on run keeps using the legacy shared refresh loads "
            "or consumes candidate-owned rerun-aero / corrected-load artifacts from the inverse-design core."
        ),
    )
    parser.add_argument(
        "--vspaero-analysis-method",
        default=DEFAULT_VSPAERO_ANALYSIS_METHOD,
        choices=VSPAERO_ANALYSIS_METHOD_CHOICES,
        help=(
            "Pass through the VSPAero solver method used when the inverse-design "
            "follow-on runs candidate_rerun_vspaero (vlm or panel)."
        ),
    )
    parser.add_argument(
        "--fixed-design-alpha-deg",
        type=float,
        default=0.0,
        help=(
            "Fixed design alpha used by origin_vsp_fixed_alpha_corrector. "
            "This mode keeps alpha fixed instead of solving L=W."
        ),
    )
    parser.add_argument(
        "--max-tube-mass-kg",
        type=float,
        default=None,
        help=(
            "Optional hard gate on spar tube mass [kg]. "
            "If set, candidates above this limit are rejected at campaign ranking time."
        ),
    )
    parser.add_argument(
        "--auto-first-pass-refine",
        action="store_true",
        help=(
            "After the coarse sweep, automatically bisect the first fail-to-pass "
            "multiplier interval until the target width is reached."
        ),
    )
    parser.add_argument(
        "--first-pass-refine-target-width",
        type=float,
        default=0.1,
        help="Target multiplier interval width for automatic first-pass boundary refinement.",
    )
    parser.add_argument(
        "--first-pass-refine-max-rounds",
        type=int,
        default=4,
        help="Maximum number of automatic midpoint refinement rounds for the first-pass boundary.",
    )
    parser.add_argument(
        "--rib-zonewise-mode",
        default="limited_zonewise",
        choices=("off", "limited_zonewise"),
        help="Pass through the rib contract mode used by the inverse-design structural follow-on.",
    )
    parser.add_argument("--avl-bin", default="avl")
    parser.add_argument("--multipliers", default="1.0,1.5,2.0,2.5")
    parser.add_argument(
        "--dihedral-exponent",
        type=float,
        default=None,
        help=(
            "Override the progressive dihedral scaling exponent used when generating "
            "candidate AVL geometry. Defaults to cfg.wing.dihedral_scaling_exponent."
        ),
    )
    parser.add_argument("--main-plateau-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--main-taper-fill-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--rear-radius-grid", default="0.0,0.33,0.67,1.0")
    parser.add_argument("--rear-outboard-grid", default="0.0,0.5,1.0")
    parser.add_argument("--wall-thickness-grid", default="0.0,0.35,0.70")
    parser.add_argument("--refresh-steps", type=int, default=2, choices=(0, 1, 2))
    parser.add_argument("--cobyla-maxiter", type=int, default=160)
    parser.add_argument("--cobyla-rhobeg", type=float, default=0.18)
    parser.add_argument("--skip-local-refine", action="store_true")
    parser.add_argument("--local-refine-feasible-seeds", type=int, default=1)
    parser.add_argument("--local-refine-near-feasible-seeds", type=int, default=2)
    parser.add_argument("--local-refine-max-starts", type=int, default=4)
    parser.add_argument("--local-refine-early-stop-patience", type=int, default=2)
    parser.add_argument("--local-refine-early-stop-abs-improvement-kg", type=float, default=0.05)
    parser.add_argument("--skip-step-export", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Abort the campaign on the first inverse-design subprocess failure.",
    )
    parser.add_argument(
        "--min-lift-kg",
        type=float,
        default=None,
        help="Override minimum required lift gate [kg]. Defaults to config aero_gates.min_lift_kg.",
    )
    parser.add_argument(
        "--min-ld-ratio",
        type=float,
        default=None,
        help="Override minimum L/D gate. Defaults to config aero_gates.min_ld_ratio.",
    )
    parser.add_argument(
        "--skip-aero-gates",
        action="store_true",
        help="Skip AVL trim-derived aero performance gates and keep stability-only filtering.",
    )
    parser.add_argument(
        "--skip-beta-sweep",
        action="store_true",
        help="Skip AVL beta-sweep sideslip checks for faster smoke testing.",
    )
    parser.add_argument(
        "--max-sideslip-deg",
        type=float,
        default=None,
        help="Override the maximum required trimmed sideslip [deg]. Defaults to config.",
    )
    parser.add_argument(
        "--min-spiral-time-to-double-s",
        type=float,
        default=None,
        help="Override the minimum acceptable spiral-mode time-to-double [s]. Defaults to config.",
    )
    parser.add_argument("--avl-velocity", type=float, default=None)
    parser.add_argument("--avl-density", type=float, default=None)
    parser.add_argument("--avl-gravity", type=float, default=None)
    parser.add_argument("--avl-mass-kg", type=float, default=None)
    parser.add_argument("--avl-ixx", type=float, default=None)
    parser.add_argument("--avl-iyy", type=float, default=None)
    parser.add_argument("--avl-izz", type=float, default=None)
    parser.add_argument("--avl-xcg", type=float, default=None)
    parser.add_argument("--avl-ycg", type=float, default=None)
    parser.add_argument("--avl-zcg", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    config_path = Path(args.config).expanduser().resolve()
    design_report = Path(args.design_report).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    inverse_script = Path(args.inverse_script).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    search_budget = _build_campaign_search_budget(args)

    cfg = load_config(config_path)
    aircraft = Aircraft.from_config(cfg)
    base_avl_path: Path | None = None
    base_avl_source = "provided"
    if args.base_avl:
        base_avl_path = Path(args.base_avl).expanduser().resolve()
        if not base_avl_path.exists() and args.generate_wing_only_avl_fallback:
            base_avl_source = "generated_wing_only_fallback"
            base_avl_path = output_dir / "generated_base_wing_only.avl"
            generate_wing_only_avl_from_config(cfg=cfg, path=base_avl_path)
        elif not base_avl_path.exists():
            raise FileNotFoundError(f"Base AVL file not found: {base_avl_path}")
    elif args.generate_wing_only_avl_fallback:
        base_avl_source = "generated_wing_only_fallback"
        base_avl_path = output_dir / "generated_base_wing_only.avl"
        generate_wing_only_avl_from_config(cfg=cfg, path=base_avl_path)
    else:
        raise FileNotFoundError("Need --base-avl, or pass --generate-wing-only-avl-fallback for a smoke baseline.")

    default_mode_params = estimate_mode_parameters(cfg)
    mode_params = AvlModeParameters(
        velocity=default_mode_params.velocity if args.avl_velocity is None else float(args.avl_velocity),
        density=default_mode_params.density if args.avl_density is None else float(args.avl_density),
        gravity=default_mode_params.gravity if args.avl_gravity is None else float(args.avl_gravity),
        mass_kg=default_mode_params.mass_kg if args.avl_mass_kg is None else float(args.avl_mass_kg),
        ixx=default_mode_params.ixx if args.avl_ixx is None else float(args.avl_ixx),
        iyy=default_mode_params.iyy if args.avl_iyy is None else float(args.avl_iyy),
        izz=default_mode_params.izz if args.avl_izz is None else float(args.avl_izz),
        x_cg=default_mode_params.x_cg if args.avl_xcg is None else float(args.avl_xcg),
        y_cg=default_mode_params.y_cg if args.avl_ycg is None else float(args.avl_ycg),
        z_cg=default_mode_params.z_cg if args.avl_zcg is None else float(args.avl_zcg),
    )
    wing_half_span = 0.5 * float(cfg.wing.span)
    dihedral_exponent = (
        float(cfg.wing.dihedral_scaling_exponent)
        if args.dihedral_exponent is None
        else float(args.dihedral_exponent)
    )
    if dihedral_exponent < 0.0:
        source = (
            "wing.dihedral_scaling_exponent"
            if args.dihedral_exponent is None
            else "--dihedral-exponent"
        )
        raise ValueError(f"{source} must be >= 0.0.")
    min_lift_kg = (
        float(cfg.aero_gates.min_lift_kg)
        if args.min_lift_kg is None
        else float(args.min_lift_kg)
    )
    min_ld_ratio = (
        float(cfg.aero_gates.min_ld_ratio)
        if args.min_ld_ratio is None
        else float(args.min_ld_ratio)
    )
    cd_profile_estimate = float(cfg.aero_gates.cd_profile_estimate)
    max_trim_aoa_deg = float(cfg.aero_gates.max_trim_aoa_deg)
    soft_trim_aoa_deg = float(cfg.aero_gates.soft_trim_aoa_deg)
    stall_alpha_deg = float(cfg.aero_gates.stall_alpha_deg)
    min_stall_margin_deg = float(cfg.aero_gates.min_stall_margin_deg)
    max_sideslip_deg = (
        float(cfg.aero_gates.max_sideslip_deg)
        if args.max_sideslip_deg is None
        else float(args.max_sideslip_deg)
    )
    min_spiral_time_to_double_s = (
        float(cfg.aero_gates.min_spiral_time_to_double_s)
        if args.min_spiral_time_to_double_s is None
        else float(args.min_spiral_time_to_double_s)
    )
    fixed_design_alpha_deg = float(args.fixed_design_alpha_deg)
    beta_sweep_values_deg = _resolve_beta_sweep_values(
        cfg.aero_gates.beta_sweep_values,
        max_sideslip_deg=float(max_sideslip_deg),
    )
    multipliers = _parse_multiplier_list(args.multipliers)
    base_text = base_avl_path.read_text(encoding="utf-8", errors="ignore")
    avl_bin = (
        Path(args.avl_bin).expanduser().resolve()
        if any(sep in args.avl_bin for sep in ("/", "\\"))
        else Path(shutil.which(args.avl_bin) or args.avl_bin)
    )
    if not avl_bin.exists():
        raise FileNotFoundError(f"AVL executable not found: {args.avl_bin}")

    rows: list[SweepResult] = []
    failed_cases: list[tuple[float, str]] = []
    candidate_avl_aoa_seed = _resolve_candidate_avl_aoa_seed(cfg)
    campaign_aero_gate_settings: dict[str, object] | None = None
    origin_fixed_alpha_baseline_case = None
    origin_fixed_alpha_baseline_metadata: dict[str, object] | None = None
    max_tube_mass_kg = None if args.max_tube_mass_kg is None else float(args.max_tube_mass_kg)
    first_pass_refined_multipliers: list[float] = []
    if str(args.aero_source_mode) == ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE:
        origin_fixed_alpha_baseline_case, origin_fixed_alpha_baseline_metadata = (
            _build_origin_fixed_alpha_panel_baseline(
                cfg=cfg,
                output_dir=output_dir,
                fixed_design_alpha_deg=float(fixed_design_alpha_deg),
                base_avl_path=base_avl_path,
            )
        )

    def _run_multiplier_case(multiplier: float) -> SweepResult:
        nonlocal campaign_aero_gate_settings
        case_dir = output_dir / f"mult_{_slug(multiplier)}"
        case_dir.mkdir(parents=True, exist_ok=True)
        scaled_text, scaled_sections, scale_samples = scale_avl_dihedral_text(
            base_text,
            multiplier=float(multiplier),
            half_span=float(wing_half_span),
            dihedral_exponent=float(dihedral_exponent),
        )
        case_avl_path = case_dir / "case.avl"
        case_avl_path.write_text(scaled_text, encoding="utf-8")
        stage_avl_airfoil_files(case_avl_path, airfoil_dir=cfg.io.airfoil_dir)
        gate_settings = build_avl_aero_gate_settings(
            cfg=cfg,
            case_avl_path=case_avl_path,
            min_lift_kg=min_lift_kg,
            min_ld_ratio=min_ld_ratio,
            cd_profile_estimate=cd_profile_estimate,
            max_trim_aoa_deg=max_trim_aoa_deg,
            soft_trim_aoa_deg=soft_trim_aoa_deg,
            stall_alpha_deg=stall_alpha_deg,
            min_stall_margin_deg=min_stall_margin_deg,
        )
        gate_metadata = gate_settings.to_metadata(
            skip_aero_gates=bool(args.skip_aero_gates),
            skip_beta_sweep=bool(args.skip_beta_sweep),
            max_sideslip_deg=float(max_sideslip_deg),
            min_spiral_time_to_double_s=float(min_spiral_time_to_double_s),
            beta_sweep_values_deg=beta_sweep_values_deg,
        )
        if campaign_aero_gate_settings is None:
            campaign_aero_gate_settings = dict(gate_metadata)
        sample_payload = [
            {
                "y_section_m": float(sample.y_section_m),
                "z_old_m": float(sample.z_old_m),
                "z_new_m": float(sample.z_new_m),
                "local_factor": float(sample.local_factor),
            }
            for sample in scale_samples
        ]
        (case_dir / "case_metadata.json").write_text(
            json.dumps(
                {
                    "dihedral_multiplier": float(multiplier),
                    "base_avl_source": base_avl_source,
                    "base_avl_path": str(base_avl_path),
                    "scaled_section_count": int(scaled_sections),
                    "dihedral_scaling_half_span_m": float(wing_half_span),
                    "dihedral_scaling_exponent": float(dihedral_exponent),
                    "dihedral_scaling_samples": sample_payload,
                    "mode_parameters": asdict(mode_params),
                    "allow_missing_dutch_roll": bool(args.allow_missing_dutch_roll),
                    "structural_weight_n": float(aircraft.weight_N),
                    "aero_gate_settings": gate_metadata,
                    "inverse_design_search_budget": search_budget,
                    "inverse_design_aero_source_mode_requested": str(args.aero_source_mode),
                    "fixed_design_alpha_deg": float(fixed_design_alpha_deg),
                    "origin_fixed_alpha_baseline": origin_fixed_alpha_baseline_metadata,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if scale_samples:
            print(f"  x{float(multiplier):.3f} progressive dihedral samples (y, z_old, z_new, factor):")
            for sample in scale_samples[:5]:
                print(
                    "    "
                    f"y={sample.y_section_m:.3f} m, "
                    f"z_old={sample.z_old_m:.6f} m, "
                    f"z_new={sample.z_new_m:.6f} m, "
                    f"factor={sample.local_factor:.6f}"
                )
        avl_eval = run_avl_stability_case(
            avl_bin=avl_bin,
            case_avl_path=case_avl_path,
            case_dir=case_dir,
            mode_params=mode_params,
            allow_missing_mode=bool(args.allow_missing_dutch_roll),
            min_spiral_time_to_double_s=float(min_spiral_time_to_double_s),
        )
        trim_eval: AvlTrimEvaluation | None = None
        candidate_avl_spanwise_loads_json: Path | None = None
        candidate_fixed_alpha_loads_json: Path | None = None
        candidate_aero_artifact_error: str | None = None
        if not avl_eval.aero_feasible:
            aero_perf_eval = _empty_aero_performance(
                feasible=False,
                reason="stability_failed",
            )
        elif str(args.aero_source_mode) == ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE:
            if origin_fixed_alpha_baseline_case is None or origin_fixed_alpha_baseline_metadata is None:
                candidate_aero_artifact_error = "origin fixed-alpha panel baseline was unavailable."
                aero_perf_eval = _empty_aero_performance(
                    feasible=False,
                    reason="fixed_alpha_baseline_unavailable",
                )
            else:
                try:
                    candidate_fixed_alpha_dir = case_dir / ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE
                    candidate_fixed_alpha_dir.mkdir(parents=True, exist_ok=True)
                    artifact = build_fixed_alpha_dihedral_corrector_artifact(
                        baseline_case=origin_fixed_alpha_baseline_case,
                        baseline_avl_path=base_avl_path,
                        candidate_avl_path=case_avl_path,
                        requested_knobs={
                            "target_shape_z_scale": float(multiplier),
                            "dihedral_multiplier": float(multiplier),
                            "dihedral_exponent": float(dihedral_exponent),
                        },
                        fixed_design_alpha_deg=float(fixed_design_alpha_deg),
                        origin_vsp3_path=origin_fixed_alpha_baseline_metadata.get("origin_vsp3_path"),
                        baseline_output_dir=origin_fixed_alpha_baseline_metadata.get("baseline_output_dir"),
                        baseline_lod_path=origin_fixed_alpha_baseline_metadata.get("baseline_lod_path"),
                        baseline_polar_path=origin_fixed_alpha_baseline_metadata.get("baseline_polar_path"),
                        source_mode=ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE,
                        notes=(
                            "Loads come from the origin .vsp3 main-wing panel baseline at fixed design alpha.",
                            "Candidate screening does not rebuild OpenVSP geometry; only a dihedral vertical-load correction is applied.",
                            "Drag and pitching-moment ownership remain on the origin fixed-alpha panel baseline.",
                        ),
                    )
                    candidate_fixed_alpha_loads_json = (
                        candidate_fixed_alpha_dir / "candidate_fixed_alpha_loads.json"
                    )
                    candidate_fixed_alpha_loads_json.write_text(
                        json.dumps(artifact, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    aero_perf_eval = _build_fixed_alpha_aero_performance(
                        fixed_design_alpha_deg=float(fixed_design_alpha_deg),
                        full_lift_n=float(artifact["total_full_lift_n"]),
                        min_lift_n=float(gate_settings.min_lift_n),
                        skip_aero_gates=bool(args.skip_aero_gates),
                    )
                except Exception as exc:
                    candidate_aero_artifact_error = str(exc)
                    aero_perf_eval = _empty_aero_performance(
                        feasible=False,
                        reason="fixed_alpha_corrector_build_failed",
                    )
        elif args.skip_aero_gates:
            aero_perf_eval = _empty_aero_performance(
                feasible=True,
                reason="skipped",
            )
        else:
            trim_eval = run_avl_trim_case(
                avl_bin=avl_bin,
                case_avl_path=case_avl_path,
                case_dir=case_dir,
                cl_required=gate_settings.cl_required,
            )
            aero_perf_eval = evaluate_aero_performance(
                trim_eval=trim_eval,
                gate_settings=gate_settings,
            )

        beta_eval: BetaSweepEvaluation | None = None
        if avl_eval.aero_feasible and not args.skip_beta_sweep:
            beta_eval = run_avl_beta_sweep(
                avl_bin=avl_bin,
                case_avl_path=case_avl_path,
                case_dir=case_dir,
                cl_required=gate_settings.cl_required,
                beta_values_deg=beta_sweep_values_deg,
                mode_params=mode_params,
            )

        control_eval: ControlCouplingEvaluation | None = None
        if avl_eval.aero_feasible and aero_perf_eval.aero_performance_feasible:
            control_eval = run_avl_stability_derivatives_case(
                avl_bin=avl_bin,
                case_avl_path=case_avl_path,
                case_dir=case_dir,
                cl_required=gate_settings.cl_required,
            )

        beta_gate_passed = (
            True
            if beta_eval is None
            else beta_eval.sideslip_feasible and beta_eval.directional_stable
        )

        summary_payload: dict[str, object] | None = None
        selected_output_dir: str | None = None
        summary_json_path: str | None = None
        inverse_error_message: str | None = None
        if avl_eval.aero_feasible and str(args.aero_source_mode) == CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE:
            candidate_trim_eval = trim_eval
            if candidate_trim_eval is None:
                candidate_trim_eval = run_avl_trim_case(
                    avl_bin=avl_bin,
                    case_avl_path=case_avl_path,
                    case_dir=case_dir,
                    cl_required=gate_settings.cl_required,
                    output_stem="trim_for_candidate_avl",
                )
            if (
                candidate_trim_eval is None
                or not candidate_trim_eval.trim_converged
                or candidate_trim_eval.aoa_trim_deg is None
            ):
                candidate_aero_artifact_error = (
                    "candidate_avl_spanwise requires a converged AVL trim AoA before building spanwise loads."
                )
            else:
                candidate_avl_dir = case_dir / "candidate_avl_spanwise"
                candidate_avl_dir.mkdir(parents=True, exist_ok=True)
                aoa_sweep_deg = _build_candidate_avl_aoa_sweep(
                    trim_aoa_deg=float(candidate_trim_eval.aoa_trim_deg),
                    seed_values_deg=candidate_avl_aoa_seed,
                )
                load_case_specs: list[dict[str, object]] = []
                skipped_aoa_notes: list[str] = []
                for aoa_deg in aoa_sweep_deg:
                    spanwise_case = run_avl_spanwise_load_case(
                        avl_bin=avl_bin,
                        case_avl_path=case_avl_path,
                        case_dir=candidate_avl_dir,
                        alpha_deg=float(aoa_deg),
                        velocity_mps=float(cfg.flight.velocity),
                        density_kgpm3=float(cfg.flight.air_density),
                        output_stem=f"aoa_{_slug(float(aoa_deg))}",
                        airfoil_dir=cfg.io.airfoil_dir,
                    )
                    if not spanwise_case.run_completed or spanwise_case.fs_file_path is None:
                        skipped_aoa_notes.append(
                            f"Skipped AoA {float(aoa_deg):.3f} deg because AVL did not emit strip forces ({spanwise_case.run_status})."
                        )
                        continue
                    load_case_specs.append(
                        {
                            "aoa_deg": float(aoa_deg),
                            "fs_path": spanwise_case.fs_file_path,
                            "stdout_log_path": spanwise_case.stdout_log_path,
                        }
                    )
                if len(load_case_specs) < 2:
                    candidate_aero_artifact_error = (
                        "candidate AVL spanwise load extraction produced fewer than 2 usable AoA cases."
                    )
                else:
                    candidate_avl_spanwise_loads_json = write_candidate_avl_spanwise_artifact(
                        candidate_avl_dir / "candidate_avl_spanwise_loads.json",
                        avl_path=case_avl_path,
                        candidate_output_dir=candidate_avl_dir,
                        requested_knobs={
                            "target_shape_z_scale": float(multiplier),
                            "dihedral_multiplier": float(multiplier),
                            "dihedral_exponent": float(dihedral_exponent),
                        },
                        selected_cruise_aoa_deg=float(candidate_trim_eval.aoa_trim_deg),
                        selected_cruise_aoa_source="outer_loop_avl_trim",
                        selected_load_state_owner="outer_loop_avl_trim_and_gates",
                        velocity_mps=float(cfg.flight.velocity),
                        density_kgpm3=float(cfg.flight.air_density),
                        load_case_specs=load_case_specs,
                        trim_force_path=candidate_trim_eval.trim_file_path,
                        trim_stdout_log_path=candidate_trim_eval.stdout_log_path,
                        source_mode=CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE,
                        notes=(
                            "Spanwise loads come from AVL strip-force output on the candidate-owned deformed geometry.",
                            "Root/tip boundary stations are padded from the nearest strip coefficients with AVL geometry chords.",
                            "Artifact generation is allowed even when aero gates later reject the candidate; this preserves a no-bootstrap compare path without changing gate semantics.",
                            *tuple(skipped_aoa_notes),
                        ),
                    )

        if avl_eval.aero_feasible and aero_perf_eval.aero_performance_feasible and beta_gate_passed:
            if (
                str(args.aero_source_mode) == CANDIDATE_AVL_SPANWISE_AERO_SOURCE_MODE
                and candidate_aero_artifact_error is not None
            ):
                inverse_error_message = candidate_aero_artifact_error
            if (
                str(args.aero_source_mode) == ORIGIN_VSP_FIXED_ALPHA_CORRECTOR_AERO_SOURCE_MODE
                and candidate_aero_artifact_error is not None
            ):
                inverse_error_message = candidate_aero_artifact_error
            inverse_output_dir = case_dir / "inverse_design"
            selected_output_dir = str(inverse_output_dir.resolve())
            if inverse_error_message is None:
                summary_json_path, _, inverse_error_message = run_inverse_design_case(
                    inverse_script=inverse_script,
                    config_path=config_path,
                    design_report=design_report,
                    output_dir=inverse_output_dir,
                    target_shape_z_scale=float(multiplier),
                    dihedral_exponent=float(dihedral_exponent),
                    python_executable=Path(sys.executable),
                    main_plateau_grid=str(args.main_plateau_grid),
                    main_taper_fill_grid=str(args.main_taper_fill_grid),
                    rear_radius_grid=str(args.rear_radius_grid),
                    rear_outboard_grid=str(args.rear_outboard_grid),
                    wall_thickness_grid=str(args.wall_thickness_grid),
                    refresh_steps=int(args.refresh_steps),
                    cobyla_maxiter=int(args.cobyla_maxiter),
                    cobyla_rhobeg=float(args.cobyla_rhobeg),
                    skip_local_refine=bool(args.skip_local_refine),
                    local_refine_feasible_seeds=int(args.local_refine_feasible_seeds),
                    local_refine_near_feasible_seeds=int(args.local_refine_near_feasible_seeds),
                    local_refine_max_starts=int(args.local_refine_max_starts),
                    local_refine_early_stop_patience=int(args.local_refine_early_stop_patience),
                    local_refine_early_stop_abs_improvement_kg=float(
                        args.local_refine_early_stop_abs_improvement_kg
                    ),
                    aero_source_mode=str(args.aero_source_mode),
                    vspaero_analysis_method=str(args.vspaero_analysis_method),
                    candidate_avl_spanwise_loads_json=candidate_avl_spanwise_loads_json,
                    candidate_fixed_alpha_loads_json=candidate_fixed_alpha_loads_json,
                    rib_zonewise_mode=str(args.rib_zonewise_mode),
                    skip_step_export=bool(args.skip_step_export),
                    strict=bool(args.strict),
                )
            if inverse_error_message:
                failed_cases.append((float(multiplier), inverse_error_message))
            elif summary_json_path is not None:
                summary_payload = _read_inverse_summary(Path(summary_json_path))

        return _build_result_row(
            multiplier=float(multiplier),
            dihedral_exponent=float(dihedral_exponent),
            avl_eval=avl_eval,
            aero_perf_eval=aero_perf_eval,
            beta_eval=beta_eval,
            control_eval=control_eval,
            summary_payload=summary_payload,
            selected_output_dir=selected_output_dir,
            summary_json_path=summary_json_path,
            error_message=inverse_error_message,
            cfg=cfg,
        )

    rows = [_run_multiplier_case(float(multiplier)) for multiplier in multipliers]
    if bool(args.auto_first_pass_refine):
        rows, first_pass_refined_multipliers = _auto_refine_first_pass_boundary(
            rows,
            run_multiplier_case=_run_multiplier_case,
            max_tube_mass_kg=max_tube_mass_kg,
            target_width=float(args.first_pass_refine_target_width),
            max_rounds=int(args.first_pass_refine_max_rounds),
        )

    csv_path = output_dir / "dihedral_sweep_summary.csv"
    json_path = output_dir / "dihedral_sweep_summary.json"
    report_path = output_dir / "dihedral_sweep_report.txt"
    first_pass_boundary = _summarize_first_pass_boundary(
        rows,
        max_tube_mass_kg=max_tube_mass_kg,
        refined_multipliers=first_pass_refined_multipliers,
    )
    rows = sorted(rows, key=lambda row: float(row.dihedral_multiplier))
    mission_objective_mode = _campaign_mission_objective_mode(rows)
    rows, winner_summary = _annotate_campaign_selection(
        rows,
        max_tube_mass_kg=max_tube_mass_kg,
        mission_objective_mode=mission_objective_mode,
    )
    _write_summary_csv(csv_path, rows)
    report_path.write_text(
        _build_campaign_report_text(
            output_dir=output_dir,
            rows=rows,
            search_budget=search_budget,
            winner_summary=winner_summary,
            first_pass_boundary=first_pass_boundary,
        ),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(
            {
                "config": str(config_path),
                "design_report": str(design_report),
                "base_avl_path": str(base_avl_path),
                "base_avl_source": base_avl_source,
                "mode_parameters": asdict(mode_params),
                "dihedral_scaling_half_span_m": float(wing_half_span),
                "dihedral_scaling_exponent": float(dihedral_exponent),
                "multipliers": [float(value) for value in multipliers],
                "score_contract": {
                    "score_name": "outer_loop_candidate_score",
                    "direction": "lower_is_better",
                    "formula": _campaign_score_formula_label(mission_objective_mode),
                    "mission_objective_mode": mission_objective_mode,
                    "gate_penalties_kg": CAMPAIGN_GATE_PENALTIES_KG,
                },
                "search_budget": search_budget,
                "aero_gate_settings": campaign_aero_gate_settings,
                "first_pass_boundary": first_pass_boundary,
                "winner": winner_summary,
                "cases": [asdict(row) for row in rows],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Dihedral sweep campaign complete.")
    print(f"  Base AVL           : {base_avl_path}")
    print(f"  Base source        : {base_avl_source}")
    print(
        "  Aero source mode   : "
        f"{args.aero_source_mode} ({_aero_source_label(args.aero_source_mode)})"
    )
    print(f"  Multipliers        : {', '.join(f'{value:.3f}' for value in multipliers)}")
    print(f"  Report             : {report_path}")
    print(f"  Summary CSV        : {csv_path}")
    print(f"  Summary JSON       : {json_path}")
    if winner_summary is not None:
        winner_mission_mode = (
            "n/a"
            if winner_summary["mission_objective_mode"] is None
            else str(winner_summary["mission_objective_mode"])
        )
        print(
            "  Winner             : "
            f"x{winner_summary['requested_knobs']['dihedral_multiplier']:.3f} "
            f"(score={winner_summary['candidate_score']:.3f}, "
            f"status={winner_summary['selection_status']}, "
            f"mission={winner_mission_mode})"
        )
    if bool(first_pass_boundary.get("boundary_found")):
        print(
            "  First-pass boundary: "
            f"({float(first_pass_boundary['final_fail_multiplier']):.6f}, "
            f"{float(first_pass_boundary['first_pass_multiplier']):.6f}] "
            f"width={float(first_pass_boundary['interval_width']):.6f}"
        )
    elif first_pass_boundary is not None:
        print("  First-pass boundary: not found")
    for row in rows:
        mass_text = "n/a" if row.total_mass_kg is None else f"{row.total_mass_kg:.3f} kg"
        clear_text = "n/a" if row.min_jig_clearance_mm is None else f"{row.min_jig_clearance_mm:.3f} mm"
        wire_text = "n/a" if row.wire_tension_n is None else f"{row.wire_tension_n:.1f} N"
        ld_text = "n/a" if row.ld_ratio is None else f"{row.ld_ratio:.2f}"
        cn_beta_text = (
            "n/a"
            if row.beta_sweep_cn_beta_per_rad is None
            else f"{row.beta_sweep_cn_beta_per_rad:.3f}/rad"
        )
        cl_beta_text = (
            "n/a"
            if row.beta_sweep_cl_beta_per_rad is None
            else f"{row.beta_sweep_cl_beta_per_rad:.3f}/rad"
        )
        rudder_text = (
            "n/a"
            if row.rudder_coupling_reason is None
            else (
                f"Cl_dR={row.rudder_cl_derivative:.3f}, "
                f"Cn_dR={row.rudder_cn_derivative:.3f}, "
                f"|Cl/Cn|={row.rudder_roll_to_yaw_ratio:.3f}"
                if (
                    row.rudder_cl_derivative is not None
                    and row.rudder_cn_derivative is not None
                    and row.rudder_roll_to_yaw_ratio is not None
                )
                else row.rudder_coupling_reason
            )
        )
        spiral_text = (
            row.spiral_reason or "n/a"
            if row.spiral_mode_real is None
            else (
                f"real={row.spiral_mode_real:.4f}, "
                f"ttd={row.spiral_time_to_double_s:.2f}s"
                if row.spiral_time_to_double_s is not None
                else (
                    f"real={row.spiral_mode_real:.4f}, "
                    f"t_half={row.spiral_time_to_half_s:.2f}s"
                    if row.spiral_time_to_half_s is not None
                    else f"real={row.spiral_mode_real:.4f}, {row.spiral_reason}"
                )
            )
        )
        beta_text = (
            "n/a"
            if row.beta_sweep_max_beta_deg is None
            else (
                f"beta<={row.beta_sweep_max_beta_deg:.1f}, "
                f"Cn_beta={cn_beta_text}, "
                f"Cl_beta={cl_beta_text}, "
                f"dir={'ok' if row.beta_sweep_directional_stable else 'fail'}, "
                f"trim={'ok' if row.beta_sweep_sideslip_feasible else 'fail'}"
            )
        )
        mission_text = (
            "n/a"
            if row.mission_objective_mode is None or row.mission_score is None
            else f"{row.mission_objective_mode}:{row.mission_score:.3f}"
        )
        print(
            "  "
            f"x{row.dihedral_multiplier:.3f}: aero={row.aero_status}, "
            f"perf={row.aero_performance_reason}, L/D={ld_text}, "
            f"beta={beta_text}, "
            f"rudder={rudder_text}, spiral={spiral_text}, "
            f"aero_source={_aero_source_label(row.aero_source_mode)}, "
            f"struct={row.structure_status}, mass={mass_text}, "
            f"clearance={clear_text}, wire={wire_text}, "
            f"score={row.candidate_score if row.candidate_score is not None else float('nan'):.3f}, "
            f"selection={row.selection_status}, reject={row.reject_reason}, "
            f"mission={mission_text}"
        )
    if failed_cases:
        print("WARNING: inverse-design failed for one or more multipliers (marked structural_failed).")
        for failed_multiplier, message in failed_cases:
            print(f"  x{failed_multiplier:.3f}: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
