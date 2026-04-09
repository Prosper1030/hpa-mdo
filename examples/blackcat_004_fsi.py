#!/usr/bin/env python3
"""Black Cat 004 — One-Way FSI Production Pipeline (v2 API)
===========================================================

This example demonstrates the complete HPA-MDO v2 workflow:

    1. Load configuration from YAML
    2. Build aircraft geometry and material database
    3. Parse VSPAero aerodynamic data
    4. Find cruise angle of attack (lift ≈ weight)
    5. Map loads with aerodynamic safety factor
    6. Run one-way FSI coupling (aero -> structure single pass)
    7. Generate visualizations (beam analysis, spar geometry)
    8. Write optimization summary text file

This script mirrors ``scripts/run_optimization.py`` but with more verbose
comments at each step for educational purposes.  All imports use the v2 API
— the legacy EulerBernoulliBeam, TubularSpar, BeamResult, and plot_beam_result
interfaces have been removed.

Usage
-----
    cd /Volumes/Samsung\ SSD/hpa-mdo
    python examples/blackcat_004_fsi.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


# Allow running directly from the repository without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── v2 imports ────────────────────────────────────────────────────────────
from hpa_mdo.core import load_config, Aircraft, MaterialDB
from hpa_mdo.aero import VSPAeroParser, LoadMapper
from hpa_mdo.fsi.coupling import FSICoupling
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.utils import compute_deformed_nodes, export_step_from_csv
from hpa_mdo.utils.visualization import (
    plot_beam_analysis,
    plot_spar_geometry,
    write_optimization_summary,
    print_optimization_summary,
)


def main() -> float:
    """Run the one-way FSI pipeline and return total_mass_full_kg."""

    # ====================================================================
    # Step 1 — Load configuration
    # ====================================================================
    # The YAML file specifies wing geometry, flight conditions, material
    # properties, segment definitions, and file paths for VSPAero data.
    config_path = (
        Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"
    )
    print(f"[1/9] Loading config: {config_path}")
    cfg = load_config(config_path)
    print(f"       Project : {cfg.project_name}")
    print(f"       Span    : {cfg.wing.span} m")
    print(f"       Velocity: {cfg.flight.velocity} m/s")

    # ====================================================================
    # Step 2 — Build aircraft geometry and material database
    # ====================================================================
    # Aircraft.from_config() constructs the wing planform, computes spanwise
    # node positions (ac.wing.y), reference areas, and operating weight.
    print("[2/9] Building aircraft geometry...")
    ac = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    target_weight = ac.weight_N  # full-span weight [N]
    print(f"       Operating mass  : {ac.mass_total_kg:.1f} kg ({target_weight:.1f} N)")

    # ====================================================================
    # Step 3 — Parse VSPAero aerodynamic data
    # ====================================================================
    # VSPAeroParser reads the .lod (spanwise lift distribution) and .polar
    # (integrated coefficients) files produced by OpenVSP's VSPAERO solver.
    # It returns a list of AeroCase objects, one per angle of attack.
    print("[3/9] Parsing VSPAero loads...")
    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
    cases = parser.parse()
    print(f"       Found {len(cases)} AoA case(s)")

    # ====================================================================
    # Step 4 — Find cruise angle of attack (lift ≈ weight)
    # ====================================================================
    # LoadMapper.map_loads() re-dimensionalises the VSPAero coefficients to
    # actual flight conditions (velocity, air density) and interpolates the
    # distributed lift onto the structural node positions (ac.wing.y).
    #
    # We loop over all AoA cases, compute the total full-span lift for each,
    # and select the case whose lift most closely equals the aircraft weight.
    print("[4/9] Finding cruise angle of attack (L ≈ W)...")
    mapper = LoadMapper()

    best_case: Optional[object] = None
    best_residual = float("inf")
    best_loads: Optional[dict] = None

    for case in cases:
        loads = mapper.map_loads(
            case, ac.wing.y,
            actual_velocity=cfg.flight.velocity,
            actual_density=cfg.flight.air_density,
        )
        # map_loads returns half-span quantities; full-span lift = 2×
        full_lift = 2.0 * loads["total_lift"]
        residual = abs(full_lift - target_weight)
        if residual < best_residual:
            best_residual = residual
            best_case = case
            best_loads = loads

    if best_case is None or best_loads is None:
        raise RuntimeError("No valid AoA case found in VSPAero data")

    cruise_aoa = best_case.aoa_deg
    cruise_lift = 2.0 * best_loads["total_lift"]
    print(f"       Cruise AoA  : {cruise_aoa:.2f} deg")
    print(f"       Full lift   : {cruise_lift:.1f} N  (target = {target_weight:.1f} N)")

    # ====================================================================
    # Step 5 — Prepare structural load case scaling
    # ====================================================================
    # Keep mapped aero loads raw; the structural case in cfg owns the design
    # maneuver scaling for both aerodynamic and gravity loads.
    print("[5/9] Preparing structural load case scaling...")
    mapped_loads = best_loads
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)
    print(f"       Load factor : {design_case.aero_scale}G")
    print(
        f"       Design lift : "
        f"{2.0 * mapped_loads['total_lift'] * design_case.aero_scale:.1f} N (full span)"
    )

    # ====================================================================
    # Step 6 — Run one-way FSI coupling
    # ====================================================================
    # One-way FSI performs a single aero->structure pass:
    #   Spanwise aero load -> mapped structural loads -> structural optimization
    # Load scaling comes from cfg.structural_load_cases(); keep the FSI call
    # itself at unit load factor to avoid split ownership.
    print("[6/9] Running one-way FSI coupling...")
    fsi = FSICoupling(cfg, ac, mat_db)
    fsi_result = fsi.run_one_way(
        aero_load=best_case,
        load_factor=1.0,
        optimizer_method="auto",
    )
    result = fsi_result.optimization_result
    print(f"       FSI converged : {fsi_result.converged}")
    print(f"       Iterations    : {fsi_result.n_iterations}")
    print(
        "       Tip defl hist : "
        + ", ".join(f"{v:.6f}" for v in fsi_result.tip_deflection_history)
    )

    # Print a rich summary to stdout
    print_optimization_summary(result)

    # ====================================================================
    # Step 7 — Generate visualizations
    # ====================================================================
    # Two figures are saved to the output directory:
    #   beam_analysis.png  — deflection, twist, von Mises stress, mass summary
    #   spar_geometry.png  — OD, wall thickness, ID, cross-section area per segment
    print("[7/9] Generating visualizations...")
    output_dir = Path(cfg.io.output_dir) / "fsi_one_way"
    output_dir.mkdir(parents=True, exist_ok=True)

    # seg_lengths lists the spanwise extent [m] of each segment definition,
    # e.g. [1.5, 3.0, 3.0, 3.0, 3.0, 3.0] for a 15 m half-span with 6 segments.
    seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)

    try:
        plot_beam_analysis(result, ac.wing.y, output_dir)
        plot_spar_geometry(result, ac.wing.y, seg_lengths, output_dir)
        print(f"       Saved: {output_dir / 'beam_analysis.png'}")
        print(f"       Saved: {output_dir / 'spar_geometry.png'}")
    except Exception as exc:
        print(f"       Visualization skipped: {exc}")

    # ====================================================================
    # Step 8 — Write optimization summary text file
    # ====================================================================
    # A human-readable plain-text file with full mass breakdown, structural
    # performance metrics, and per-segment OD/thickness tables.
    print("[8/9] Writing optimization summary...")
    summary_path = output_dir / "optimization_summary.txt"
    write_optimization_summary(result, summary_path)
    print(f"       Saved: {summary_path}")

    # ====================================================================
    # Step 9 — Export STEP geometry for CAD inspection (jig + flight shape)
    # ====================================================================
    print("[9/9] Exporting STEP geometry for CAD inspection...")
    ansys_dir = output_dir / "ansys"
    ansys_dir.mkdir(parents=True, exist_ok=True)
    try:
        exporter = ANSYSExporter(cfg, ac, result, export_loads, mat_db)
        csv_path = exporter.write_workbench_csv(ansys_dir / "spar_data.csv")
        jig_step_path = output_dir / "spar_jig_shape.step"
        flight_step_path = output_dir / "spar_flight_shape.step"
        engine_name = export_step_from_csv(csv_path, jig_step_path, engine="auto")
        deformed_nodes = compute_deformed_nodes(result)
        export_step_from_csv(
            csv_path,
            flight_step_path,
            engine=engine_name,
            deformed_nodes=deformed_nodes,
        )
        print(f"       Saved: {jig_step_path} ({engine_name})")
        print(f"       Saved: {flight_step_path} ({engine_name})")
    except Exception as exc:
        print(f"       STEP export skipped: {exc}")

    total_mass = result.total_mass_full_kg
    tip_defl_limit = cfg.wing.max_tip_deflection_m
    print(f"\nDone.  Total spar system mass = {total_mass:.4f} kg")
    print(f"       Feasible  : {result.failure_index <= 0}")
    print(f"       Converged : {result.success}")
    if tip_defl_limit is not None:
        print(
            "       tip_defl<=1.02*limit : "
            f"{result.tip_deflection_m:.6f} <= {tip_defl_limit * 1.02:.6f}"
        )
    print(f"       failure<=0           : {result.failure_index:.6f} <= 0")
    print(f"val_weight: {total_mass:.6f}")

    return total_mass


if __name__ == "__main__":
    main()
