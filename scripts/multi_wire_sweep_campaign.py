#!/usr/bin/env python3
"""Outer-loop multi-wire sweep over dihedral multiplier and wire layout."""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import sys
from typing import Iterable

import yaml

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.core import Aircraft, load_config
from hpa_mdo.aero import build_avl_aero_gate_settings
from scripts.dihedral_sweep_campaign import (
    _empty_aero_performance,
    _parse_multiplier_list,
    _read_inverse_summary,
    _slug,
    estimate_mode_parameters,
    evaluate_aero_performance,
    run_avl_stability_case,
    run_avl_trim_case,
    run_inverse_design_case,
    scale_avl_dihedral_text,
)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "multi_wire_sweep_campaign"
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
DEFAULT_WIRE_LAYOUTS = "single=7.5;dual=4.5|10.5;triple=4.5|7.5|10.5"
DEFAULT_MULTIPLIERS = "1.0,2.5,3.0,3.1,3.2,3.3,3.4,3.5"


@dataclass(frozen=True)
class WireLayout:
    label: str
    attachment_positions_m: tuple[float, ...]

    @property
    def wire_count(self) -> int:
        return len(self.attachment_positions_m)


@dataclass(frozen=True)
class MultiWireSweepResult:
    wire_layout_label: str
    wire_count: int
    wire_positions_m: tuple[float, ...]
    dihedral_multiplier: float
    wire_drag_cd_increment: float
    effective_cd_profile_estimate: float
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
    structure_status: str
    total_mass_kg: float | None
    min_jig_clearance_mm: float | None
    wire_tension_total_n: float | None
    wire_tension_max_n: float | None
    wire_margin_min_n: float | None
    failure_index: float | None
    buckling_index: float | None
    selected_output_dir: str | None
    summary_json_path: str | None
    wire_rigging_json_path: str | None
    error_message: str | None


def _parse_wire_layouts(text: str) -> tuple[WireLayout, ...]:
    layouts: list[WireLayout] = []
    for chunk in text.split(";"):
        spec = chunk.strip()
        if not spec:
            continue
        if "=" in spec:
            label_raw, pos_text = spec.split("=", 1)
            label = label_raw.strip()
        else:
            label = f"layout_{len(layouts) + 1}"
            pos_text = spec
        positions = tuple(
            sorted(float(part.strip()) for part in pos_text.split("|") if part.strip())
        )
        if not label:
            raise ValueError("Wire layout labels must be non-empty.")
        if not positions:
            raise ValueError(f"Wire layout '{label}' needs at least one attachment position.")
        layouts.append(
            WireLayout(
                label=label,
                attachment_positions_m=positions,
            )
        )
    if not layouts:
        raise ValueError("Need at least one wire layout.")
    return tuple(layouts)


def _load_yaml_mapping(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def _build_layout_config_payload(
    *,
    base_payload: dict,
    layout: WireLayout,
    base_fuselage_z: float,
    base_wire_angle_deg: float,
    wire_drag_cd_per_wire: float,
) -> dict:
    payload = copy.deepcopy(base_payload)
    payload.setdefault("lift_wires", {})
    payload["lift_wires"]["enabled"] = True
    payload["lift_wires"]["wire_angle_deg"] = float(base_wire_angle_deg)
    payload["lift_wires"]["attachments"] = [
        {
            "y": float(y_m),
            "fuselage_z": float(base_fuselage_z),
            "label": f"wire-{idx + 1}",
        }
        for idx, y_m in enumerate(layout.attachment_positions_m)
    ]
    payload.setdefault("aero_gates", {})
    base_cd = float(payload["aero_gates"]["cd_profile_estimate"])
    payload["aero_gates"]["cd_profile_estimate"] = (
        base_cd + float(wire_drag_cd_per_wire) * float(layout.wire_count)
    )
    return payload


def _write_layout_config(
    *,
    path: Path,
    payload: dict,
) -> Path:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return path


def _extract_multi_wire_metrics(summary_payload: dict[str, object]) -> tuple[
    float | None,
    float | None,
    float | None,
    str | None,
]:
    artifacts = summary_payload.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return None, None, None, None
    wire_json = artifacts.get("wire_rigging_json")
    if not wire_json:
        return None, None, None, None
    wire_path = Path(str(wire_json))
    if not wire_path.exists():
        return None, None, None, str(wire_path)
    payload = json.loads(wire_path.read_text(encoding="utf-8"))
    records = payload.get("wire_rigging") or []
    if not records:
        return None, None, None, str(wire_path.resolve())
    tensions = [
        float(record["tension_force_n"])
        for record in records
        if record.get("tension_force_n") is not None
    ]
    margins = [
        float(record["tension_margin_n"])
        for record in records
        if record.get("tension_margin_n") is not None
    ]
    return (
        None if not tensions else float(sum(tensions)),
        None if not tensions else float(max(tensions)),
        None if not margins else float(min(margins)),
        str(wire_path.resolve()),
    )


def _build_result_row(
    *,
    layout: WireLayout,
    cd_increment: float,
    effective_cd_profile_estimate: float,
    multiplier: float,
    avl_eval,
    aero_perf_eval,
    summary_payload: dict[str, object] | None,
    selected_output_dir: str | None,
    summary_json_path: str | None,
    error_message: str | None,
) -> MultiWireSweepResult:
    if summary_payload is None:
        structure_status = "structural_failed" if error_message else "skipped"
        return MultiWireSweepResult(
            wire_layout_label=layout.label,
            wire_count=layout.wire_count,
            wire_positions_m=layout.attachment_positions_m,
            dihedral_multiplier=float(multiplier),
            wire_drag_cd_increment=float(cd_increment),
            effective_cd_profile_estimate=float(effective_cd_profile_estimate),
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
            structure_status=structure_status,
            total_mass_kg=None,
            min_jig_clearance_mm=None,
            wire_tension_total_n=None,
            wire_tension_max_n=None,
            wire_margin_min_n=None,
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
    wire_total_n, wire_max_n, wire_margin_min_n, wire_json_path = _extract_multi_wire_metrics(
        summary_payload
    )
    return MultiWireSweepResult(
        wire_layout_label=layout.label,
        wire_count=layout.wire_count,
        wire_positions_m=layout.attachment_positions_m,
        dihedral_multiplier=float(multiplier),
        wire_drag_cd_increment=float(cd_increment),
        effective_cd_profile_estimate=float(effective_cd_profile_estimate),
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
        structure_status="feasible" if bool(selected["overall_feasible"]) else "infeasible",
        total_mass_kg=float(selected["total_structural_mass_kg"]),
        min_jig_clearance_mm=float(selected["jig_ground_clearance_min_m"]) * 1000.0,
        wire_tension_total_n=wire_total_n,
        wire_tension_max_n=wire_max_n,
        wire_margin_min_n=wire_margin_min_n,
        failure_index=float(selected["equivalent_failure_index"]),
        buckling_index=float(selected["equivalent_buckling_index"]),
        selected_output_dir=selected_output_dir,
        summary_json_path=summary_json_path,
        wire_rigging_json_path=wire_json_path,
        error_message=error_message,
    )


def _write_summary_csv(path: Path, rows: Iterable[MultiWireSweepResult]) -> None:
    fieldnames = [
        "wire_layout_label",
        "wire_count",
        "wire_positions_m",
        "dihedral_multiplier",
        "wire_drag_cd_increment",
        "effective_cd_profile_estimate",
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
        "structure_status",
        "total_mass_kg",
        "min_jig_clearance_mm",
        "wire_tension_total_n",
        "wire_tension_max_n",
        "wire_margin_min_n",
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
            payload = asdict(row)
            payload["wire_positions_m"] = "|".join(f"{value:.3f}" for value in row.wire_positions_m)
            writer.writerow(payload)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a multi-wire outer-loop sweep over dihedral and wire layouts."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--design-report", default=str(DEFAULT_DESIGN_REPORT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--inverse-script", default=str(DEFAULT_INVERSE_SCRIPT))
    parser.add_argument("--base-avl", default=str(DEFAULT_BASE_AVL))
    parser.add_argument("--avl-bin", default="avl")
    parser.add_argument("--multipliers", default=DEFAULT_MULTIPLIERS)
    parser.add_argument("--wire-layouts", default=DEFAULT_WIRE_LAYOUTS)
    parser.add_argument(
        "--wire-drag-cd-per-wire",
        type=float,
        default=0.003,
        help="Additional CD profile estimate applied per lift wire.",
    )
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    config_path = Path(args.config).expanduser().resolve()
    design_report = Path(args.design_report).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    inverse_script = Path(args.inverse_script).expanduser().resolve()
    base_avl_path = Path(args.base_avl).expanduser().resolve()
    if not base_avl_path.exists():
        raise FileNotFoundError(f"Base AVL file not found: {base_avl_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    base_cfg = load_config(config_path)
    base_payload = _load_yaml_mapping(config_path)
    base_attachment = (
        base_cfg.lift_wires.attachments[0]
        if base_cfg.lift_wires.attachments
        else None
    )
    base_fuselage_z = -1.5 if base_attachment is None else float(base_attachment.fuselage_z)
    wire_drag_cd_per_wire = float(args.wire_drag_cd_per_wire)
    if wire_drag_cd_per_wire < 0.0:
        raise ValueError("--wire-drag-cd-per-wire must be >= 0.0.")

    multipliers = _parse_multiplier_list(args.multipliers)
    layouts = _parse_wire_layouts(args.wire_layouts)
    base_text = base_avl_path.read_text(encoding="utf-8", errors="ignore")
    avl_bin = (
        Path(args.avl_bin).expanduser().resolve()
        if any(sep in args.avl_bin for sep in ("/", "\\"))
        else Path(shutil.which(args.avl_bin) or args.avl_bin)
    )
    if not avl_bin.exists():
        raise FileNotFoundError(f"AVL executable not found: {args.avl_bin}")

    rows: list[MultiWireSweepResult] = []
    failed_cases: list[tuple[str, float, str]] = []
    for layout in layouts:
        layout_dir = output_dir / layout.label
        layout_dir.mkdir(parents=True, exist_ok=True)
        layout_payload = _build_layout_config_payload(
            base_payload=base_payload,
            layout=layout,
            base_fuselage_z=base_fuselage_z,
            base_wire_angle_deg=float(base_cfg.lift_wires.wire_angle_deg),
            wire_drag_cd_per_wire=wire_drag_cd_per_wire,
        )
        layout_payload.setdefault("io", {})
        for field_name in (
            "sync_root",
            "vsp_model",
            "vsp_lod",
            "vsp_polar",
            "airfoil_dir",
            "output_dir",
            "training_db",
        ):
            resolved_value = getattr(base_cfg.io, field_name)
            layout_payload["io"][field_name] = (
                None if resolved_value is None else str(resolved_value)
            )
        layout_config_path = _write_layout_config(
            path=layout_dir / "case_config.yaml",
            payload=layout_payload,
        )
        cfg = load_config(layout_config_path)
        aircraft = Aircraft.from_config(cfg)
        mode_params = estimate_mode_parameters(cfg)
        wing_half_span = 0.5 * float(cfg.wing.span)
        dihedral_exponent = float(cfg.wing.dihedral_scaling_exponent)
        effective_cd_profile_estimate = float(cfg.aero_gates.cd_profile_estimate)
        cd_increment = float(wire_drag_cd_per_wire) * float(layout.wire_count)

        (layout_dir / "layout_metadata.json").write_text(
            json.dumps(
                {
                    "wire_layout_label": layout.label,
                    "wire_count": layout.wire_count,
                    "wire_positions_m": [float(value) for value in layout.attachment_positions_m],
                    "wire_drag_cd_per_wire": float(wire_drag_cd_per_wire),
                    "wire_drag_cd_increment": float(cd_increment),
                    "effective_cd_profile_estimate": float(effective_cd_profile_estimate),
                    "case_config_path": str(layout_config_path),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        for multiplier in multipliers:
            case_dir = layout_dir / f"mult_{_slug(multiplier)}"
            case_dir.mkdir(parents=True, exist_ok=True)
            scaled_text, scaled_sections, scale_samples = scale_avl_dihedral_text(
                base_text,
                multiplier=float(multiplier),
                half_span=float(wing_half_span),
                dihedral_exponent=float(dihedral_exponent),
            )
            case_avl_path = case_dir / "case.avl"
            case_avl_path.write_text(scaled_text, encoding="utf-8")
            gate_settings = build_avl_aero_gate_settings(
                cfg=cfg,
                case_avl_path=case_avl_path,
                cd_profile_estimate=effective_cd_profile_estimate,
            )
            (case_dir / "case_metadata.json").write_text(
                json.dumps(
                    {
                        "wire_layout_label": layout.label,
                        "wire_positions_m": [float(value) for value in layout.attachment_positions_m],
                        "wire_drag_cd_increment": float(cd_increment),
                        "effective_cd_profile_estimate": float(effective_cd_profile_estimate),
                        "dihedral_multiplier": float(multiplier),
                        "scaled_section_count": int(scaled_sections),
                        "dihedral_scaling_exponent": float(dihedral_exponent),
                        "dihedral_scaling_half_span_m": float(wing_half_span),
                        "dihedral_scaling_samples": [asdict(sample) for sample in scale_samples],
                        "mode_parameters": asdict(mode_params),
                        "structural_weight_n": float(aircraft.weight_N),
                        "aero_gate_settings": gate_settings.to_metadata(
                            skip_aero_gates=False,
                            skip_beta_sweep=True,
                            max_sideslip_deg=float(cfg.aero_gates.max_sideslip_deg),
                            min_spiral_time_to_double_s=float(cfg.aero_gates.min_spiral_time_to_double_s),
                            beta_sweep_values_deg=(),
                        ),
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
                allow_missing_mode=False,
            )
            if not avl_eval.aero_feasible:
                aero_perf_eval = _empty_aero_performance(
                    feasible=False,
                    reason="stability_failed",
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

            summary_payload: dict[str, object] | None = None
            selected_output_dir: str | None = None
            summary_json_path: str | None = None
            inverse_error_message: str | None = None
            if avl_eval.aero_feasible and aero_perf_eval.aero_performance_feasible:
                inverse_output_dir = case_dir / "inverse_design"
                selected_output_dir = str(inverse_output_dir.resolve())
                summary_json_path, _, inverse_error_message = run_inverse_design_case(
                    inverse_script=inverse_script,
                    config_path=layout_config_path,
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
                    failed_cases.append((layout.label, float(multiplier), inverse_error_message))
                elif summary_json_path is not None:
                    summary_payload = _read_inverse_summary(Path(summary_json_path))

            rows.append(
                _build_result_row(
                    layout=layout,
                    cd_increment=float(cd_increment),
                    effective_cd_profile_estimate=float(effective_cd_profile_estimate),
                    multiplier=float(multiplier),
                    avl_eval=avl_eval,
                    aero_perf_eval=aero_perf_eval,
                    summary_payload=summary_payload,
                    selected_output_dir=selected_output_dir,
                    summary_json_path=summary_json_path,
                    error_message=inverse_error_message,
                )
            )

    csv_path = output_dir / "multi_wire_sweep_summary.csv"
    json_path = output_dir / "multi_wire_sweep_summary.json"
    _write_summary_csv(csv_path, rows)
    json_path.write_text(
        json.dumps(
            {
                "config": str(config_path),
                "design_report": str(design_report),
                "base_avl_path": str(base_avl_path),
                "wire_layouts": [asdict(layout) for layout in layouts],
                "wire_drag_cd_per_wire": float(wire_drag_cd_per_wire),
                "multipliers": [float(value) for value in multipliers],
                "aero_gate_contract": {
                    "reference_area_source": "generated_avl_sref",
                    "cd_profile_estimate_policy": "layout_specific_base_plus_wire_drag_increment",
                },
                "cases": [asdict(row) for row in rows],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("Multi-wire sweep campaign complete.")
    print(f"  Base AVL           : {base_avl_path}")
    print(f"  Layouts            : {', '.join(layout.label for layout in layouts)}")
    print(f"  Multipliers        : {', '.join(f'{value:.3f}' for value in multipliers)}")
    print(f"  Summary CSV        : {csv_path}")
    print(f"  Summary JSON       : {json_path}")
    for row in rows:
        mass_text = "n/a" if row.total_mass_kg is None else f"{row.total_mass_kg:.3f} kg"
        ld_text = "n/a" if row.ld_ratio is None else f"{row.ld_ratio:.2f}"
        margin_text = (
            "n/a"
            if row.wire_margin_min_n is None
            else f"{row.wire_margin_min_n:.1f} N"
        )
        print(
            "  "
            f"{row.wire_layout_label} x{row.dihedral_multiplier:.3f}: "
            f"aero={row.aero_status}, perf={row.aero_performance_reason}, "
            f"L/D={ld_text}, struct={row.structure_status}, "
            f"mass={mass_text}, min wire margin={margin_text}"
        )
    if failed_cases:
        print("WARNING: inverse-design failed for one or more cases (marked structural_failed).")
        for layout_label, multiplier, message in failed_cases:
            print(f"  {layout_label} x{multiplier:.3f}: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
