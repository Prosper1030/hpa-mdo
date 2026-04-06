#!/usr/bin/env python3
"""
Black Cat 004 — Full Spar Optimization Pipeline
================================================

This example demonstrates the complete HPA-MDO workflow:

    1. Load configuration from YAML
    2. Parse VSPAero aerodynamic data
    3. Map loads onto structural beam nodes
    4. Run spar optimization (minimize mass subject to stress + deflection)
    5. Visualize results
    6. Export to ANSYS (APDL, CSV, NASTRAN)

Usage:
    cd /Users/linyuan/hpa-mdo
    python examples/blackcat_004_optimize.py
"""

import sys
from pathlib import Path

# Add src to path for development
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from hpa_mdo.core.config import load_config
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.aero.vsp_aero import VSPAeroParser
from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.structure.beam_model import EulerBernoulliBeam
from hpa_mdo.structure.spar import TubularSpar
from hpa_mdo.structure.optimizer import SparOptimizer
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.utils.visualization import (
    plot_beam_result,
    plot_spar_geometry,
    print_optimization_summary,
)


def main():
    # ====================================================================
    # Step 1: Load configuration
    # ====================================================================
    config_path = Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path)
    print(f"Project: {cfg.project_name}")
    print(f"Wing span: {cfg.wing.span} m, Cruise: {cfg.flight.velocity} m/s")
    print(f"Total mass: {cfg.weight.operating_kg} kg, Load factor: {cfg.flight.load_factor}")
    print()

    # ====================================================================
    # Step 2: Build aircraft model
    # ====================================================================
    aircraft = Aircraft.from_config(cfg)
    db = MaterialDB()
    material = db.get(cfg.spar.material)
    print(f"Material: {material.name}")
    print(f"  E = {material.E/1e9:.1f} GPa, σ_ult = {material.tensile_strength/1e6:.0f} MPa")
    print(f"  Allowable stress (SF={cfg.spar.safety_factor}): "
          f"{material.tensile_strength/cfg.spar.safety_factor/1e6:.0f} MPa")
    print()

    # ====================================================================
    # Step 3: Parse VSPAero aerodynamic data
    # ====================================================================
    lod_path = cfg.io.vsp_lod
    polar_path = cfg.io.vsp_polar
    print(f"Parsing VSPAero data: {lod_path}")

    parser = VSPAeroParser(lod_path, polar_path)
    cases = parser.parse()
    print(f"  Found {len(cases)} AoA cases")

    # Select design AoA — find the case where CL produces enough lift at
    # our actual flight conditions (V=6.5 m/s, rho=1.225 kg/m³).
    # VSPAero was run at different reference conditions so we must
    # re-dimensionalise: L = q_actual * S * CL_total.
    target_lift_half = aircraft.weight_N / 2.0  # half-span lift at 1G
    q_actual = aircraft.flight.dynamic_pressure
    wing_area_half = aircraft.wing.area_half
    CL_required = target_lift_half / (q_actual * wing_area_half)
    print(f"  Target half-span lift (1G): {target_lift_half:.1f} N")
    print(f"  q_actual = {q_actual:.2f} Pa, wing area (half) = {wing_area_half:.2f} m²")
    print(f"  Required CL = {CL_required:.4f}")

    # Compute total CL for each case from Cl distribution
    best_case = None
    best_diff = float("inf")
    for case in cases:
        # Total CL = integral(Cl * c dy) / (S/2)
        case_CL = float(np.trapz(case.cl * case.chord, case.y)) / wing_area_half
        case_lift_actual = q_actual * wing_area_half * case_CL
        diff = abs(case_lift_actual - target_lift_half)
        if diff < best_diff:
            best_diff = diff
            best_case = case
            best_CL = case_CL
            best_lift_actual = case_lift_actual

    if best_case is None:
        print("ERROR: No valid aero cases found.")
        sys.exit(1)

    print(f"  Selected AoA = {best_case.aoa_deg}° "
          f"(CL = {best_CL:.4f}, "
          f"actual lift = {best_lift_actual:.1f} N, "
          f"target = {target_lift_half:.1f} N)")
    print()

    # ====================================================================
    # Step 4: Map aero loads onto structural nodes
    # ====================================================================
    spar = TubularSpar.from_wing_geometry(aircraft.wing, cfg.spar, material)
    mapper = LoadMapper(method="cubic")

    # Map loads: re-dimensionalise Cl using actual flight conditions,
    # then scale by the design load factor
    mapped = mapper.map_loads(
        best_case,
        spar.y,
        scale_factor=cfg.flight.load_factor,
        actual_velocity=cfg.flight.velocity,
        actual_density=cfg.flight.air_density,
    )
    print(f"Load mapping: {best_case.n_stations} aero stations → {spar.n_nodes} struct nodes")
    print(f"  Mapped total half-span lift (at n={cfg.flight.load_factor}): "
          f"{mapped['total_lift']:.1f} N")
    print()

    # ====================================================================
    # Step 5: Compute target tip deflection from dihedral
    # ====================================================================
    half_span = aircraft.wing.half_span
    target_tip_defl = half_span * np.tan(np.radians(cfg.wing.dihedral_tip_deg))
    print(f"Half-span: {half_span:.2f} m")
    print(f"Target tip deflection (for {cfg.wing.dihedral_tip_deg}° dihedral): "
          f"{target_tip_defl:.3f} m ({target_tip_defl*1000:.1f} mm)")
    print()

    # ====================================================================
    # Step 6: Run spar optimization
    # ====================================================================
    print("Running spar optimization...")
    beam = EulerBernoulliBeam()

    optimizer = SparOptimizer(
        spar=spar,
        beam_solver=beam,
        f_ext=mapped["lift_per_span"],
        safety_factor=cfg.spar.safety_factor,
        max_tip_deflection=target_tip_defl,
    )

    result = optimizer.optimize(
        method=cfg.solver.optimizer_method,
        tol=cfg.solver.optimizer_tol,
        maxiter=cfg.solver.optimizer_maxiter,
    )

    # Print summary
    summary = print_optimization_summary(result)
    print(summary)
    print()

    # ====================================================================
    # Step 7: Visualize results
    # ====================================================================
    output_dir = Path(cfg.io.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if result.beam_result:
        sigma_allow = material.tensile_strength / cfg.spar.safety_factor

        plot_beam_result(
            result.beam_result,
            E=material.E,
            sigma_allow=sigma_allow,
            title=f"{cfg.project_name} — Beam Analysis (AoA={best_case.aoa_deg}°, n={cfg.flight.load_factor})",
            save_path=output_dir / "beam_analysis.png",
        )
        print(f"Saved: {output_dir / 'beam_analysis.png'}")

    if result.spar_props:
        plot_spar_geometry(
            y=spar.y,
            outer_d=spar.outer_diameter,
            inner_d=result.spar_props["inner_diameter"],
            wall_thickness=result.spar_props["wall_thickness"],
            title=f"{cfg.project_name} — Optimized Spar Geometry",
            save_path=output_dir / "spar_geometry.png",
        )
        print(f"Saved: {output_dir / 'spar_geometry.png'}")

    # ====================================================================
    # Step 8: Export to ANSYS
    # ====================================================================
    if result.beam_result and result.spar_props:
        exporter = ANSYSExporter(spar, result.spar_props, result.beam_result, material)

        apdl_path = exporter.write_apdl(output_dir / "ansys" / "spar_model.mac")
        print(f"Saved ANSYS APDL: {apdl_path}")

        csv_path = exporter.write_workbench_csv(output_dir / "ansys" / "spar_data.csv")
        print(f"Saved Workbench CSV: {csv_path}")

        bdf_path = exporter.write_nastran_bdf(output_dir / "ansys" / "spar_model.bdf")
        print(f"Saved NASTRAN BDF: {bdf_path}")

    # Save text summary
    with open(output_dir / "optimization_summary.txt", "w") as f:
        f.write(summary)
    print(f"\nSaved summary: {output_dir / 'optimization_summary.txt'}")

    print("\nDone!")


if __name__ == "__main__":
    main()
