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
    return _format_target_pct(value, unit, 5.0, precision)


def _format_target_pct(value: float, unit: str, pct: float, precision: int = 3) -> str:
    """Return +/-pct target range as text."""
    frac = pct / 100.0
    low = value * (1.0 - frac)
    high = value * (1.0 + frac)
    return f"{low:.{precision}f} to {high:.{precision}f} {unit}"


def _build_crossval_report(
    *,
    config_name: str,
    cfg: HPAConfig,
    aircraft: Aircraft,
    result: OptimizationResult,
    export_loads: dict[str, Any],
    exporter: ANSYSExporter,
    export_mode: str,
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
    spar_mass_half_kg = float(result.spar_mass_half_kg)
    spar_mass_full_kg = float(result.spar_mass_full_kg)
    total_mass_full_kg = float(result.total_mass_full_kg)
    is_equivalent_validation = export_mode == "equivalent_beam"
    if is_equivalent_validation:
        root_reaction_fz = abs(exporter.equivalent_total_fz_n)

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
    lines.append(f"  Export mode: {export_mode}")
    lines.append("=" * 64)
    lines.append("")
    lines.append("--- VALIDATION MODE ---")
    if is_equivalent_validation:
        lines.append("  equivalent-beam validation mode")
        lines.append("  Phase I gate: YES")
        lines.append(
            "  ANSYS uses one BEAM188 line with the same equivalent A/I/J, "
            "nodal Fz/My loads, support nodes, and wire UZ constraint as the internal FEM."
        )
    else:
        lines.append("  dual-spar inspection mode")
        lines.append("  Phase I gate: NO")
        lines.append(
            "  This keeps the higher-fidelity two-spar + rigid-link export for "
            "model-form discrepancy checks only."
        )
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
    if is_equivalent_validation:
        lines.append("  Root (y=0): fixed all 6 DOF on the equivalent FEM beam")
    else:
        lines.append("  Root (y=0): fixed all 6 DOF (both spars)")
    if cfg.lift_wires.enabled and cfg.lift_wires.attachments:
        wire_ys = ", ".join(f"{att.y:.1f}" for att in cfg.lift_wires.attachments)
        if is_equivalent_validation:
            lines.append(f"  Wire at y={wire_ys}m: UZ=0 on equivalent beam")
        else:
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
    if is_equivalent_validation:
        lines.append(
            f"  Total equivalent nodal Fz: {exporter.equivalent_total_fz_n:.3f} N "
            "(lift plus spar self-weight/inertia)"
        )
        lines.append(
            f"  Total equivalent nodal My: {exporter.equivalent_total_my_nm:.3f} N*m "
            "(aero torque plus rear-spar gravity torque)"
        )

    lines.append("")
    lines.append("--- EXPECTED RESULTS (Internal FEM) ---")
    lines.append("  Metric                         Value          ANSYS Target / Role")
    lines.append("  -----------------------------  -------------  -----------------------------")
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
        "provisional / non-gating"
    )
    lines.append(
        f"  Max Von Mises (rear spar)      {max_vm_rear_mpa:11.3f} MPa  "
        "provisional / non-gating"
    )
    lines.append(
        f"  Root reaction Fz               {root_reaction_fz:11.3f} N    "
        f"{_format_target_pct(root_reaction_fz, 'N', 1.0, 3)}"
    )
    lines.append(
        f"  Max twist angle                {twist_deg:11.3f} deg  "
        "informative / non-gating"
    )
    lines.append(
        f"  Spar tube mass (half-span)     {spar_mass_half_kg:11.3f} kg   "
        "(compare with APDL element mass)"
    )
    lines.append(
        f"  Spar tube mass (full-span)     {spar_mass_full_kg:11.3f} kg   "
        f"{_format_target_pct(spar_mass_full_kg, 'kg', 1.0, 3)}"
    )
    lines.append(
        f"  Total optimized mass (full)    {total_mass_full_kg:11.3f} kg   "
        "(includes joint/penalty terms; not APDL beam-only)"
    )

    lines.append("")
    lines.append("--- PASS CRITERIA ---")
    if is_equivalent_validation:
        lines.append("  Phase I validation gate uses equivalent-beam ANSYS vs internal FEM only:")
        lines.append("    - tip deflection error <= 5%")
        lines.append("    - max vertical displacement error <= 5%")
        lines.append("    - root/support reaction Fz error <= 1%")
        lines.append("    - spar beam mass error <= 1%")
    else:
        lines.append(
            "  Dual-spar ANSYS differences are model-form / higher-fidelity discrepancies, "
            "not Phase I validation failures."
        )
    lines.append(
        "  Stress is non-gating until the ANSYS BEAM188 beam/fiber stress extraction "
        "is explicitly confirmed apples-to-apples with the internal tube stress recovery."
    )

    tip_node = aircraft.wing.n_stations
    lines.append("")
    lines.append("--- APDL POST-PROCESSING COMMANDS ---")
    lines.append("  ! After running spar_model.mac:")
    lines.append("  /POST1")
    lines.append("  SET,LAST")
    lines.append(f"  *GET,TIP_UZ,NODE,{tip_node},U,Z")
    if is_equivalent_validation:
        lines.append("  PRRSOL,FZ                           ! Support reactions")
        lines.append("  ! Stress comparison is intentionally omitted from Phase I gating.")
    else:
        lines.append("  ! CTUBE SMISC stress extraction is provisional; do not gate Phase I on it.")
        lines.append("  ETABLE,VM_I,SMISC,31")
        lines.append("  ETABLE,VM_J,SMISC,36")
        lines.append("  *GET,VM_I_MAX,ETAB,VM_I,MAX")
        lines.append("  *GET,VM_J_MAX,ETAB,VM_J,MAX")
        lines.append("  PRRSOL,FZ                           ! Support reactions")
    lines.append("=" * 64)

    return "\n".join(lines) + "\n"


def export_cross_validation_package_from_result(
    *,
    config_path: str | Path,
    cfg: HPAConfig,
    aircraft: Aircraft,
    result: OptimizationResult,
    mapped_loads: dict[str, Any],
    export_loads: dict[str, Any],
    mat_db: MaterialDB,
    cruise_aoa_deg: float,
    output_dir: str | Path | None = None,
    export_mode: str = "equivalent_beam",
    ansys_subdir: str = "ansys",
) -> CrossValidationPackage:
    """Export ANSYS files and report from an already available design result."""
    resolved_config = Path(config_path).expanduser().resolve()
    if output_dir is not None:
        cfg.io.output_dir = Path(output_dir).expanduser().resolve()

    subdir = str(ansys_subdir).strip()
    if not subdir:
        raise ValueError("ansys_subdir must be a non-empty path segment.")

    design_case = cfg.structural_load_cases()[0]
    ansys_dir = Path(cfg.io.output_dir) / subdir
    ansys_dir.mkdir(parents=True, exist_ok=True)
    exporter = ANSYSExporter(cfg, aircraft, result, export_loads, mat_db, mode=export_mode)

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
        exporter=exporter,
        export_mode=exporter.mode,
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
        cruise_aoa_deg=float(cruise_aoa_deg),
    )


def generate_cross_validation_package(
    config_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    *,
    n_beam_nodes: int | None = None,
    optimizer_maxiter: int | None = None,
    export_mode: str = "equivalent_beam",
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

    return export_cross_validation_package_from_result(
        config_path=resolved_config,
        cfg=cfg,
        aircraft=aircraft,
        result=result,
        mapped_loads=mapped_loads,
        export_loads=export_loads,
        mat_db=mat_db,
        cruise_aoa_deg=cruise_aoa_deg,
        output_dir=None,
        export_mode=export_mode,
        ansys_subdir="ansys",
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
    parser.add_argument(
        "--export-mode",
        choices=("equivalent_beam", "dual_spar"),
        default="equivalent_beam",
        help=(
            "ANSYS export mode. equivalent_beam is a legacy Phase I parity / "
            "regression path retained for comparison; it is not the current "
            "production sign-off basis. dual_spar is higher-fidelity inspection only."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> CrossValidationPackage:
    """CLI entry point."""
    args = _build_arg_parser().parse_args(argv)
    package = generate_cross_validation_package(
        config_path=args.config,
        output_dir=args.output_dir,
        export_mode=args.export_mode,
    )

    print("ANSYS cross-validation package generated.")
    print(f"  Config       : {package.config_path}")
    print(f"  Cruise AoA   : {package.cruise_aoa_deg:.2f} deg")
    print(f"  Export mode  : {package.exporter.mode}")
    print(f"  Output dir   : {package.ansys_dir}")
    print(f"  APDL macro   : {package.apdl_path.name}")
    print(f"  NASTRAN BDF  : {package.bdf_path.name}")
    print(f"  Workbench CSV: {package.csv_path.name}")
    print(f"  Report       : {package.report_path.name}")

    return package


if __name__ == "__main__":
    main()
