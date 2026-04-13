#!/usr/bin/env python3
"""MVP-1 outer-loop dihedral sweep using AVL stability filtering plus inverse design."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
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
DEFAULT_DESIGN_REPORT = (
    REPO_ROOT
    / "output"
    / "blackcat_004_dual_beam_production_check"
    / "ansys"
    / "crossval_report.txt"
)
OSCILLATORY_IMAG_TOL = 1.0e-9
LATERAL_STATE_NAMES = ("v", "p", "r", "phi", "psi", "y")
LONGITUDINAL_STATE_NAMES = ("u", "w", "q", "the", "x", "z")


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


def scale_avl_dihedral_text(text: str, *, multiplier: float) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    out = list(lines)
    scaled = 0
    idx = 0
    while idx < len(out):
        if out[idx].strip().upper() == "SECTION":
            scan = idx + 1
            while scan < len(out):
                stripped = out[scan].strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                    scan += 1
                    continue
                values = _try_parse_section_data(out[scan])
                if values is not None:
                    values[2] *= float(multiplier)
                    _, comment = _split_comment(out[scan])
                    numeric = "  ".join(f"{value:.9f}" for value in values)
                    suffix = f" {comment}" if comment else ""
                    out[scan] = f"{numeric}{suffix}\n"
                    scaled += 1
                break
        idx += 1
    return "".join(out), scaled


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
    mean_chord = 0.5 * (float(cfg.wing.root_chord) + float(cfg.wing.tip_chord))
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
        x_cg=0.0,
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


def run_avl_stability_case(
    *,
    avl_bin: Path,
    case_avl_path: Path,
    case_dir: Path,
    mode_params: AvlModeParameters,
    allow_missing_mode: bool,
) -> AvlEvaluation:
    mode_file = case_dir / "case_modes.st"
    stdout_log = case_dir / "avl_mode_stdout.log"
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
    )


def run_inverse_design_case(
    *,
    inverse_script: Path,
    config_path: Path,
    design_report: Path,
    output_dir: Path,
    target_shape_z_scale: float,
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
    parser.add_argument("--base-avl", default=None, help="Path to the baseline AVL geometry file.")
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
        if not base_avl_path.exists():
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
        scaled_text, scaled_sections = scale_avl_dihedral_text(base_text, multiplier=float(multiplier))
        case_avl_path = case_dir / "case.avl"
        case_avl_path.write_text(scaled_text, encoding="utf-8")
        (case_dir / "case_metadata.json").write_text(
            json.dumps(
                {
                    "dihedral_multiplier": float(multiplier),
                    "base_avl_source": base_avl_source,
                    "base_avl_path": str(base_avl_path),
                    "scaled_section_count": int(scaled_sections),
                    "mode_parameters": asdict(mode_params),
                    "allow_missing_dutch_roll": bool(args.allow_missing_dutch_roll),
                    "structural_weight_n": float(aircraft.weight_N),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        avl_eval = run_avl_stability_case(
            avl_bin=avl_bin,
            case_avl_path=case_avl_path,
            case_dir=case_dir,
            mode_params=mode_params,
            allow_missing_mode=bool(args.allow_missing_dutch_roll),
        )

        summary_payload: dict[str, object] | None = None
        selected_output_dir: str | None = None
        summary_json_path: str | None = None
        inverse_error_message: str | None = None
        if avl_eval.aero_feasible:
            inverse_output_dir = case_dir / "inverse_design"
            selected_output_dir = str(inverse_output_dir.resolve())
            summary_json_path, _, inverse_error_message = run_inverse_design_case(
                inverse_script=inverse_script,
                config_path=config_path,
                design_report=design_report,
                output_dir=inverse_output_dir,
                target_shape_z_scale=float(multiplier),
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
                "multipliers": [float(value) for value in multipliers],
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
        print(
            "  "
            f"x{row.dihedral_multiplier:.3f}: aero={row.aero_status}, "
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
