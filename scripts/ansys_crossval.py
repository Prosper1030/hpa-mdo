#!/usr/bin/env python3
"""Generate ANSYS cross-validation package for Black Cat 004.

Outputs:
    output/blackcat_004/ansys/
        spar_model.mac          - APDL input deck
        spar_model.bdf          - NASTRAN bulk data
        spar_data.csv           - Workbench CSV
        crossval_report.txt     - Expected FEM results for comparison
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import numpy as np

# Allow running directly from the repository without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hpa_mdo.aero import LoadMapper, VSPAeroParser
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.core.config import HPAConfig, LoadCaseConfig
from hpa_mdo.structure import SparOptimizer
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.structure.optimizer import OptimizationResult


@dataclass
class CrossValidationPackage:
    """Artifacts and model objects produced by ANSYS cross-validation export."""

    config_path: Path
    ansys_dir: Path
    apdl_path: Path
    bdf_path: Path
    csv_path: Path
    report_path: Path
    cfg: HPAConfig
    aircraft: Aircraft
    result: OptimizationResult
    mapped_loads: dict[str, Any]
    export_loads: dict[str, Any]
    design_case: LoadCaseConfig
    exporter: ANSYSExporter
    cruise_aoa_deg: float


def _select_cruise_loads(cfg: HPAConfig, aircraft: Aircraft) -> tuple[float, dict[str, Any]]:
    """Select AoA case with full-span lift closest to aircraft weight."""
    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
    cases = parser.parse()
    if not cases:
        raise RuntimeError("No aerodynamic cases found in VSPAero data.")

    mapper = LoadMapper()
    target_weight = aircraft.weight_N

    best_case = None
    best_residual = float("inf")
    best_loads: dict[str, Any] | None = None

    for case in cases:
        loads = mapper.map_loads(
            case,
            aircraft.wing.y,
            actual_velocity=cfg.flight.velocity,
            actual_density=cfg.flight.air_density,
        )
        full_lift = 2.0 * float(loads["total_lift"])
        residual = abs(full_lift - target_weight)
        if residual < best_residual:
            best_residual = residual
            best_case = case
            best_loads = loads

    if best_case is None or best_loads is None:
        raise RuntimeError("Failed to determine cruise AoA from aerodynamic cases.")

    return float(best_case.aoa_deg), best_loads


def _format_target_pm5(value: float, unit: str, precision: int = 3) -> str:
    """Return +/-5% target range as text."""
    low = value * 0.95
    high = value * 1.05
    return f"{low:.{precision}f} to {high:.{precision}f} {unit}"


def _build_crossval_report(
    *,
    config_name: str,
    cfg: HPAConfig,
    aircraft: Aircraft,
    result: OptimizationResult,
    export_loads: dict[str, Any],
    mat_db: MaterialDB,
) -> str:
    """Build the human-readable expected-value report for ANSYS checks."""
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    design_case = cfg.structural_load_cases()[0]
    y = np.asarray(aircraft.wing.y, dtype=float)

    lift_per_span = np.asarray(export_loads["lift_per_span"], dtype=float)
    torque_per_span = np.asarray(export_loads["torque_per_span"], dtype=float)

    lift_idx = int(np.argmax(lift_per_span))
    torque_idx = int(np.argmax(np.abs(torque_per_span)))
    max_lift = float(lift_per_span[lift_idx])
    max_torque = float(torque_per_span[torque_idx])

    total_lift_half = float(export_loads.get("total_lift", np.trapezoid(lift_per_span, y)))
    root_reaction_fz = total_lift_half

    tip_uz_mm = float(result.tip_deflection_m) * 1000.0
    if result.disp is not None and result.disp.size > 0:
        uz_all_mm = np.asarray(result.disp, dtype=float)[:, 2] * 1000.0
        max_uz_mm = float(np.max(np.abs(uz_all_mm)))
    else:
        max_uz_mm = abs(tip_uz_mm)

    max_vm_main_mpa = float(result.max_stress_main_Pa) / 1e6
    max_vm_rear_mpa = float(result.max_stress_rear_Pa) / 1e6
    twist_deg = float(result.twist_max_deg)
    mass_full_kg = float(result.total_mass_full_kg)

    seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
    main_mat_key = cfg.main_spar.material
    rear_mat_key = cfg.rear_spar.material
    main_mat = mat_db.get(main_mat_key)
    rear_mat = mat_db.get(rear_mat_key)

    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("  HPA-MDO ANSYS Cross-Validation Report")
    lines.append(f"  Generated: {timestamp}")
    lines.append(f"  Config: {config_name}")
    lines.append("=" * 64)
    lines.append("")
    lines.append("--- DESIGN ---")
    lines.append(
        "  Main spar material : "
        f"{main_mat_key} (E={main_mat.E/1e9:.1f} GPa, G={main_mat.G/1e9:.1f} GPa)"
    )
    lines.append(
        "  Rear spar material : "
        f"{rear_mat_key} (E={rear_mat.E/1e9:.1f} GPa, G={rear_mat.G/1e9:.1f} GPa)"
    )
    lines.append(f"  Segments (half-span): {seg_lengths} m")
    lines.append("")
    lines.append("  Main spar:")
    for idx, (od_mm, t_mm) in enumerate(zip(result.main_r_seg_mm * 2.0, result.main_t_seg_mm)):
        lines.append(f"    Seg {idx + 1}: OD={od_mm:.2f}mm, t={t_mm:.2f}mm")

    lines.append("  Rear spar:")
    if result.rear_r_seg_mm is not None and result.rear_t_seg_mm is not None:
        for idx, (od_mm, t_mm) in enumerate(
            zip(result.rear_r_seg_mm * 2.0, result.rear_t_seg_mm)
        ):
            lines.append(f"    Seg {idx + 1}: OD={od_mm:.2f}mm, t={t_mm:.2f}mm")
    else:
        lines.append("    (rear spar metrics unavailable)")

    lines.append("")
    lines.append("--- BOUNDARY CONDITIONS ---")
    lines.append("  Root (y=0): fixed all 6 DOF (both spars)")
    if cfg.lift_wires.enabled and cfg.lift_wires.attachments:
        wire_ys = ", ".join(f"{att.y:.1f}" for att in cfg.lift_wires.attachments)
        lines.append(f"  Wire at y={wire_ys}m: UZ=0 (main spar only)")
    else:
        lines.append("  Wire constraint: disabled")

    lines.append("")
    lines.append("--- APPLIED LOADS ---")
    lines.append(f"  Load factor: {design_case.aero_scale:.3f}")
    lines.append(f"  Total half-span lift: {total_lift_half:.3f} N")
    lines.append(f"  Max lift per span: {max_lift:.3f} N/m  (at y={y[lift_idx]:.3f} m)")
    lines.append(
        f"  Max torque per span: {max_torque:.3f} N*m/m (at y={y[torque_idx]:.3f} m)"
    )

    lines.append("")
    lines.append("--- EXPECTED RESULTS (Internal FEM) ---")
    lines.append("  Metric                         Value          ANSYS Target (+/-5%)")
    lines.append("  -----------------------------  -------------  ----------------------")
    lines.append(
        f"  Tip deflection (uz, y={y[-1]:.1f}m)   {tip_uz_mm:11.3f} mm   "
        f"{_format_target_pm5(tip_uz_mm, 'mm', 3)}"
    )
    lines.append(
        f"  Max uz anywhere                {max_uz_mm:11.3f} mm   "
        f"{_format_target_pm5(max_uz_mm, 'mm', 3)}"
    )
    lines.append(
        f"  Max Von Mises (main spar)      {max_vm_main_mpa:11.3f} MPa  "
        f"{_format_target_pm5(max_vm_main_mpa, 'MPa', 3)}"
    )
    lines.append(
        f"  Max Von Mises (rear spar)      {max_vm_rear_mpa:11.3f} MPa  "
        f"{_format_target_pm5(max_vm_rear_mpa, 'MPa', 3)}"
    )
    lines.append(
        f"  Root reaction Fz               {root_reaction_fz:11.3f} N    "
        f"{_format_target_pm5(root_reaction_fz, 'N', 3)}"
    )
    lines.append(
        f"  Max twist angle                {twist_deg:11.3f} deg  "
        f"{_format_target_pm5(twist_deg, 'deg', 3)}"
    )
    lines.append(
        f"  Total spar mass (full-span)    {mass_full_kg:11.3f} kg   "
        "(check via APDL *GET)"
    )

    lines.append("")
    lines.append("--- PASS CRITERIA ---")
    lines.append("  All metrics within +/-5% of internal FEM values.")
    lines.append(
        "  If any metric exceeds 10%, investigate element formulation differences "
        "(Euler-Bernoulli vs Timoshenko, shear correction)."
    )

    tip_node = aircraft.wing.n_stations
    lines.append("")
    lines.append("--- APDL POST-PROCESSING COMMANDS ---")
    lines.append("  ! After running spar_model.mac:")
    lines.append("  /POST1")
    lines.append("  SET,LAST")
    lines.append(f"  *GET,TIP_UZ,NODE,{tip_node},U,Z")
    lines.append("  *GET,MAX_VM_MAIN,ELEM,0,SMISC,31   ! BEAM188 von Mises")
    lines.append("  PRRSOL,FZ                           ! Root reaction")
    lines.append("=" * 64)

    return "\n".join(lines) + "\n"


def generate_cross_validation_package(
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    *,
    n_beam_nodes: int | None = None,
    optimizer_maxiter: int | None = None,
) -> CrossValidationPackage:
    """Run optimization, export ANSYS files, and write cross-validation report."""
    repo_root = Path(__file__).resolve().parent.parent
    resolved_config = (
        Path(config_path).expanduser().resolve()
        if config_path is not None
        else repo_root / "configs" / "blackcat_004.yaml"
    )

    cfg = load_config(resolved_config)
    if output_dir is not None:
        cfg.io.output_dir = Path(output_dir).expanduser().resolve()
    if n_beam_nodes is not None:
        cfg.solver.n_beam_nodes = int(n_beam_nodes)
    if optimizer_maxiter is not None:
        cfg.solver.optimizer_maxiter = int(optimizer_maxiter)

    aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()

    cruise_aoa_deg, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)

    optimizer = SparOptimizer(cfg, aircraft, mapped_loads, mat_db)
    result = optimizer.optimize(method="auto")

    ansys_dir = Path(cfg.io.output_dir) / "ansys"
    ansys_dir.mkdir(parents=True, exist_ok=True)
    exporter = ANSYSExporter(cfg, aircraft, result, export_loads, mat_db)

    apdl_path = exporter.write_apdl(ansys_dir / "spar_model.mac")
    bdf_path = exporter.write_nastran_bdf(ansys_dir / "spar_model.bdf")
    csv_path = exporter.write_workbench_csv(ansys_dir / "spar_data.csv")

    report_path = ansys_dir / "crossval_report.txt"
    report_text = _build_crossval_report(
        config_name=resolved_config.name,
        cfg=cfg,
        aircraft=aircraft,
        result=result,
        export_loads=export_loads,
        mat_db=mat_db,
    )
    report_path.write_text(report_text, encoding="utf-8")

    return CrossValidationPackage(
        config_path=resolved_config,
        ansys_dir=ansys_dir,
        apdl_path=apdl_path,
        bdf_path=bdf_path,
        csv_path=csv_path,
        report_path=report_path,
        cfg=cfg,
        aircraft=aircraft,
        result=result,
        mapped_loads=mapped_loads,
        export_loads=export_loads,
        design_case=design_case,
        exporter=exporter,
        cruise_aoa_deg=cruise_aoa_deg,
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate APDL/BDF/CSV + report for ANSYS cross-validation."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
        help="Path to YAML configuration file.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory (default: use config io.output_dir).",
    )
    return parser


def main(argv: list[str] | None = None) -> CrossValidationPackage:
    """CLI entry point."""
    args = _build_arg_parser().parse_args(argv)
    package = generate_cross_validation_package(
        config_path=args.config,
        output_dir=args.output_dir,
    )

    print("ANSYS cross-validation package generated.")
    print(f"  Config       : {package.config_path}")
    print(f"  Cruise AoA   : {package.cruise_aoa_deg:.2f} deg")
    print(f"  Output dir   : {package.ansys_dir}")
    print(f"  APDL macro   : {package.apdl_path.name}")
    print(f"  NASTRAN BDF  : {package.bdf_path.name}")
    print(f"  Workbench CSV: {package.csv_path.name}")
    print(f"  Report       : {package.report_path.name}")

    return package


if __name__ == "__main__":
    main()
