#!/usr/bin/env python3
"""MVP-1 outer-loop dihedral sweep using AVL stability filtering plus inverse design."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Iterable

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.core import Aircraft, load_config


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
OSCILLATORY_IMAG_TOL = 1.0e-9
SPIRAL_LATERAL_RATIO_MIN = 0.35
LATERAL_STATE_NAMES = ("v", "p", "r", "phi", "psi", "y")
LONGITUDINAL_STATE_NAMES = ("u", "w", "q", "the", "x", "z")
FLOAT_TOKEN = r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[Ee][-+]?\d+)?"


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
class AeroPerformanceEvaluation:
    cl_trim: float | None
    cd_induced: float | None
    cd_total_est: float | None
    ld_ratio: float | None
    aoa_trim_deg: float | None
    span_efficiency: float | None
    lift_total_n: float | None
    aero_power_w: float | None
    aero_performance_feasible: bool
    aero_performance_reason: str


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
    selected_output_dir: str | None
    summary_json_path: str | None
    wire_rigging_json_path: str | None
    error_message: str | None


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


def _slug(multiplier: float) -> str:
    return f"{multiplier:.3f}".replace("-", "m").replace(".", "p")


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
    normalized = surface_name.strip().casefold()
    targets = {name.strip().casefold() for name in target_surface_names}
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


def _empty_aero_performance(
    *,
    feasible: bool,
    reason: str,
) -> AeroPerformanceEvaluation:
    return AeroPerformanceEvaluation(
        cl_trim=None,
        cd_induced=None,
        cd_total_est=None,
        ld_ratio=None,
        aoa_trim_deg=None,
        span_efficiency=None,
        lift_total_n=None,
        aero_power_w=None,
        aero_performance_feasible=bool(feasible),
        aero_performance_reason=str(reason),
    )


def evaluate_aero_performance(
    *,
    trim_eval: AvlTrimEvaluation,
    dynamic_pressure_pa: float,
    reference_area_m2: float,
    cruise_velocity_mps: float,
    min_lift_n: float,
    min_ld_ratio: float,
    cd_profile_estimate: float,
    max_trim_aoa_deg: float,
) -> AeroPerformanceEvaluation:
    if not trim_eval.trim_converged:
        return _empty_aero_performance(feasible=False, reason=trim_eval.trim_status)

    cl_trim = trim_eval.cl_trim
    cd_induced = trim_eval.cd_induced
    aoa_trim_deg = trim_eval.aoa_trim_deg
    span_efficiency = trim_eval.span_efficiency
    if cl_trim is None or cd_induced is None or aoa_trim_deg is None:
        return _empty_aero_performance(feasible=False, reason="trim_output_incomplete")

    cd_total_est = float(cd_induced) + float(cd_profile_estimate)
    if cd_total_est <= 0.0:
        return AeroPerformanceEvaluation(
            cl_trim=float(cl_trim),
            cd_induced=float(cd_induced),
            cd_total_est=float(cd_total_est),
            ld_ratio=None,
            aoa_trim_deg=float(aoa_trim_deg),
            span_efficiency=None if span_efficiency is None else float(span_efficiency),
            lift_total_n=None,
            aero_power_w=None,
            aero_performance_feasible=False,
            aero_performance_reason="nonpositive_drag_estimate",
        )

    ld_ratio = float(cl_trim) / float(cd_total_est)
    lift_total_n = float(cl_trim) * float(dynamic_pressure_pa) * float(reference_area_m2)
    aero_power_w = None
    if ld_ratio > 0.0:
        aero_power_w = float(lift_total_n) * float(cruise_velocity_mps) / float(ld_ratio)

    feasible = True
    reason = "ok"
    if float(aoa_trim_deg) > float(max_trim_aoa_deg):
        feasible = False
        reason = "trim_aoa_exceeds_limit"
    elif float(ld_ratio) < float(min_ld_ratio):
        feasible = False
        reason = "ld_below_minimum"
    elif float(lift_total_n) < float(min_lift_n):
        feasible = False
        reason = "insufficient_lift"

    return AeroPerformanceEvaluation(
        cl_trim=float(cl_trim),
        cd_induced=float(cd_induced),
        cd_total_est=float(cd_total_est),
        ld_ratio=float(ld_ratio),
        aoa_trim_deg=float(aoa_trim_deg),
        span_efficiency=None if span_efficiency is None else float(span_efficiency),
        lift_total_n=float(lift_total_n),
        aero_power_w=None if aero_power_w is None else float(aero_power_w),
        aero_performance_feasible=bool(feasible),
        aero_performance_reason=str(reason),
    )


def estimate_reference_area(cfg) -> float:
    span = float(cfg.wing.span)
    root_chord = float(cfg.wing.root_chord)
    tip_chord = float(cfg.wing.tip_chord)
    return 0.5 * span * (root_chord + tip_chord)


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
    ]
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


def _build_result_row(
    *,
    multiplier: float,
    avl_eval: AvlEvaluation,
    aero_perf_eval: AeroPerformanceEvaluation,
    beta_eval: BetaSweepEvaluation | None,
    control_eval: ControlCouplingEvaluation | None,
    summary_payload: dict[str, object] | None,
    selected_output_dir: str | None,
    summary_json_path: str | None,
    error_message: str | None,
) -> SweepResult:
    if summary_payload is None:
        structure_status = "structural_failed" if error_message else "skipped"
        return SweepResult(
            dihedral_multiplier=float(multiplier),
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
            total_mass_kg=None,
            min_jig_clearance_mm=None,
            wire_tension_n=None,
            wire_margin_n=None,
            failure_index=None,
            buckling_index=None,
            selected_output_dir=selected_output_dir,
            summary_json_path=summary_json_path,
            wire_rigging_json_path=None,
            error_message=error_message,
        )

    iterations = summary_payload["iterations"]
    final = iterations[-1]
    selected = final["selected"]
    wire_tension_n, wire_margin_n, wire_json_path = _extract_wire_metrics(summary_payload)
    return SweepResult(
        dihedral_multiplier=float(multiplier),
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
        total_mass_kg=float(selected["total_structural_mass_kg"]),
        min_jig_clearance_mm=float(selected["jig_ground_clearance_min_m"]) * 1000.0,
        wire_tension_n=wire_tension_n,
        wire_margin_n=wire_margin_n,
        failure_index=float(selected["equivalent_failure_index"]),
        buckling_index=float(selected["equivalent_buckling_index"]),
        selected_output_dir=selected_output_dir,
        summary_json_path=summary_json_path,
        wire_rigging_json_path=wire_json_path,
        error_message=error_message,
    )


def _write_summary_csv(path: Path, rows: Iterable[SweepResult]) -> None:
    fieldnames = [
        "dihedral_multiplier",
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
        "total_mass_kg",
        "min_jig_clearance_mm",
        "wire_tension_n",
        "wire_margin_n",
        "failure_index",
        "buckling_index",
        "selected_output_dir",
        "summary_json_path",
        "wire_rigging_json_path",
        "error_message",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


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
    parser.add_argument("--avl-bin", default="avl")
    parser.add_argument("--multipliers", default="1.0,1.5,2.0,2.5")
    parser.add_argument("--main-plateau-grid", default="0.0,1.0")
    parser.add_argument("--main-taper-fill-grid", default="0.0,1.0")
    parser.add_argument("--rear-radius-grid", default="0.0,1.0")
    parser.add_argument("--rear-outboard-grid", default="0.0,1.0")
    parser.add_argument("--wall-thickness-grid", default="0.0,1.0")
    parser.add_argument("--refresh-steps", type=int, default=2, choices=(0, 1, 2))
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
    dihedral_exponent = float(cfg.wing.dihedral_scaling_exponent)
    if dihedral_exponent < 0.0:
        raise ValueError("wing.dihedral_scaling_exponent must be >= 0.0.")
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
    beta_sweep_values_deg = _resolve_beta_sweep_values(
        cfg.aero_gates.beta_sweep_values,
        max_sideslip_deg=float(max_sideslip_deg),
    )
    min_lift_n = float(min_lift_kg) * 9.81
    reference_area_m2 = estimate_reference_area(cfg)
    dynamic_pressure_pa = 0.5 * float(cfg.flight.air_density) * float(cfg.flight.velocity) ** 2
    if reference_area_m2 <= 0.0:
        raise ValueError("Computed wing reference area must be positive for aero-gate trim analysis.")
    if dynamic_pressure_pa <= 0.0:
        raise ValueError("Dynamic pressure must be positive for aero-gate trim analysis.")
    cl_required = (
        float(cfg.weight.max_takeoff_kg) * 9.81 / (float(dynamic_pressure_pa) * float(reference_area_m2))
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
    for multiplier in multipliers:
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
                    "aero_gate_settings": {
                        "cl_required": float(cl_required),
                    "min_lift_kg": float(min_lift_kg),
                    "min_lift_n": float(min_lift_n),
                    "min_ld_ratio": float(min_ld_ratio),
                    "cd_profile_estimate": float(cd_profile_estimate),
                    "max_trim_aoa_deg": float(max_trim_aoa_deg),
                    "skip_aero_gates": bool(args.skip_aero_gates),
                    "skip_beta_sweep": bool(args.skip_beta_sweep),
                    "max_sideslip_deg": float(max_sideslip_deg),
                    "min_spiral_time_to_double_s": float(min_spiral_time_to_double_s),
                    "beta_sweep_values_deg": [float(value) for value in beta_sweep_values_deg],
                },
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
        if not avl_eval.aero_feasible:
            aero_perf_eval = _empty_aero_performance(
                feasible=False,
                reason="stability_failed",
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
                cl_required=cl_required,
            )
            aero_perf_eval = evaluate_aero_performance(
                trim_eval=trim_eval,
                dynamic_pressure_pa=dynamic_pressure_pa,
                reference_area_m2=reference_area_m2,
                cruise_velocity_mps=float(cfg.flight.velocity),
                min_lift_n=min_lift_n,
                min_ld_ratio=min_ld_ratio,
                cd_profile_estimate=cd_profile_estimate,
                max_trim_aoa_deg=max_trim_aoa_deg,
            )

        beta_eval: BetaSweepEvaluation | None = None
        if avl_eval.aero_feasible and not args.skip_beta_sweep:
            beta_eval = run_avl_beta_sweep(
                avl_bin=avl_bin,
                case_avl_path=case_avl_path,
                case_dir=case_dir,
                cl_required=cl_required,
                beta_values_deg=beta_sweep_values_deg,
                mode_params=mode_params,
            )

        control_eval: ControlCouplingEvaluation | None = None
        if avl_eval.aero_feasible and aero_perf_eval.aero_performance_feasible:
            control_eval = run_avl_stability_derivatives_case(
                avl_bin=avl_bin,
                case_avl_path=case_avl_path,
                case_dir=case_dir,
                cl_required=cl_required,
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
        if avl_eval.aero_feasible and aero_perf_eval.aero_performance_feasible and beta_gate_passed:
            inverse_output_dir = case_dir / "inverse_design"
            selected_output_dir = str(inverse_output_dir.resolve())
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
                skip_step_export=bool(args.skip_step_export),
                strict=bool(args.strict),
            )
            if inverse_error_message:
                failed_cases.append((float(multiplier), inverse_error_message))
            elif summary_json_path is not None:
                summary_payload = _read_inverse_summary(Path(summary_json_path))

        rows.append(
            _build_result_row(
                multiplier=float(multiplier),
                avl_eval=avl_eval,
                aero_perf_eval=aero_perf_eval,
                beta_eval=beta_eval,
                control_eval=control_eval,
                summary_payload=summary_payload,
                selected_output_dir=selected_output_dir,
                summary_json_path=summary_json_path,
                error_message=inverse_error_message,
            )
        )

    csv_path = output_dir / "dihedral_sweep_summary.csv"
    json_path = output_dir / "dihedral_sweep_summary.json"
    _write_summary_csv(csv_path, rows)
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
                "aero_gate_settings": {
                    "cl_required": float(cl_required),
                    "min_lift_kg": float(min_lift_kg),
                    "min_lift_n": float(min_lift_n),
                    "min_ld_ratio": float(min_ld_ratio),
                    "cd_profile_estimate": float(cd_profile_estimate),
                    "max_trim_aoa_deg": float(max_trim_aoa_deg),
                    "skip_aero_gates": bool(args.skip_aero_gates),
                    "skip_beta_sweep": bool(args.skip_beta_sweep),
                    "max_sideslip_deg": float(max_sideslip_deg),
                    "min_spiral_time_to_double_s": float(min_spiral_time_to_double_s),
                    "beta_sweep_values_deg": [float(value) for value in beta_sweep_values_deg],
                },
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
    print(f"  Multipliers        : {', '.join(f'{value:.3f}' for value in multipliers)}")
    print(f"  Summary CSV        : {csv_path}")
    print(f"  Summary JSON       : {json_path}")
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
        print(
            "  "
            f"x{row.dihedral_multiplier:.3f}: aero={row.aero_status}, "
            f"perf={row.aero_performance_reason}, L/D={ld_text}, "
            f"beta={beta_text}, "
            f"rudder={rudder_text}, spiral={spiral_text}, "
            f"struct={row.structure_status}, mass={mass_text}, "
            f"clearance={clear_text}, wire={wire_text}"
        )
    if failed_cases:
        print("WARNING: inverse-design failed for one or more multipliers (marked structural_failed).")
        for failed_multiplier, message in failed_cases:
            print(f"  x{failed_multiplier:.3f}: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
