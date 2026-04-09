#!/usr/bin/env python3
"""Black Cat 004 — Full Spar Optimization Pipeline (v2 API)
===========================================================

This example demonstrates the complete HPA-MDO v2 workflow:

    1. Load configuration from YAML
    2. Build aircraft geometry and material database
    3. Parse VSPAero aerodynamic data
    4. Find cruise angle of attack (lift ≈ weight)
    5. Map loads with aerodynamic safety factor
    6. Run spar optimization (minimize mass subject to stress + deflection)
    7. Generate visualizations (beam analysis, spar geometry)
    8. Write optimization summary text file

This script mirrors ``scripts/run_optimization.py`` but with more verbose
comments at each step for educational purposes.  All imports use the v2 API
— the legacy EulerBernoulliBeam, TubularSpar, BeamResult, and plot_beam_result
interfaces have been removed.

Usage
-----
    cd /Volumes/Samsung\ SSD/hpa-mdo
    python examples/blackcat_004_optimize.py
"""

from __future__ import annotations

import sys
import shutil
from pathlib import Path
from typing import Optional


# Allow running directly from the repository without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── v2 imports ────────────────────────────────────────────────────────────
from hpa_mdo.core import load_config, Aircraft, MaterialDB
from hpa_mdo.aero import VSPAeroParser, LoadMapper
from hpa_mdo.structure import SparOptimizer
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.utils import export_step_from_csv
from hpa_mdo.utils.visualization import (
    plot_beam_analysis,
    plot_spar_geometry,
    write_optimization_summary,
    print_optimization_summary,
)


def main() -> float:
    """Run the full pipeline and return total_mass_full_kg."""

    # ====================================================================
    # Step 1 — Load configuration
    # ====================================================================
    # The YAML file specifies wing geometry, flight conditions, material
    # properties, segment definitions, and file paths for VSPAero data.
    config_path = (
        Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"
    )
    print(f"[1/8] Loading config: {config_path}")
    cfg = load_config(config_path)
    print(f"       Project : {cfg.project_name}")
    print(f"       Span    : {cfg.wing.span} m")
    print(f"       Velocity: {cfg.flight.velocity} m/s")

    # ====================================================================
    # Step 2 — Build aircraft geometry and material database
    # ====================================================================
    # Aircraft.from_config() constructs the wing planform, computes spanwise
    # node positions (ac.wing.y), reference areas, and operating weight.
    print("[2/8] Building aircraft geometry...")
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
    print("[3/8] Parsing VSPAero loads...")
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
    print("[4/8] Finding cruise angle of attack (L ≈ W)...")
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
    # Step 5 — Apply aerodynamic load factor
    # ====================================================================
    # The aerodynamic load factor (e.g. 1.5× for 1G cruise with 50% margin)
    # scales the distributed lift to the design limit loads.
    # Note: this is distinct from the material safety factor, which is applied
    # inside the optimizer when comparing stress to the allowable.
    print("[5/8] Applying aerodynamic load factor...")
    design_loads = LoadMapper.apply_load_factor(
        best_loads, cfg.safety.aerodynamic_load_factor
    )
    print(f"       Load factor : {cfg.safety.aerodynamic_load_factor}G")
    print(f"       Design lift : {2.0 * design_loads['total_lift']:.1f} N (full span)")

    # ====================================================================
    # Step 6 — Run spar optimization
    # ====================================================================
    # SparOptimizer wraps an OpenMDAO structural FEM problem.
    # The "auto" method prioritizes OpenMDAO's gradient-based optimizer
    # and falls back to scipy when needed.
    #
    # Design variables : segment wall thicknesses (main + rear spar)
    # Objective        : minimize total spar system mass
    # Constraints      : von Mises stress ≤ allowable,
    #                    max twist ≤ cfg.wing.max_tip_twist_deg,
    #                    tip deflection ≤ limit (encoded in failure_index)
    print("[6/8] Running spar optimization...")
    opt = SparOptimizer(cfg, ac, design_loads, mat_db)
    result = opt.optimize(method="auto")

    # Print a rich summary to stdout
    print_optimization_summary(result)

    # ====================================================================
    # Step 7 — Generate visualizations
    # ====================================================================
    # Two figures are saved to the output directory:
    #   beam_analysis.png  — deflection, twist, von Mises stress, mass summary
    #   spar_geometry.png  — OD, wall thickness, ID, cross-section area per segment
    print("[7/8] Generating visualizations...")
    output_dir = Path(cfg.io.output_dir)
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
    # Step 9 — Export STEP geometry for CAD inspection
    # ====================================================================
    print("[9/9] Exporting STEP geometry for CAD inspection...")
    ansys_dir = output_dir / "ansys"
    ansys_dir.mkdir(parents=True, exist_ok=True)
    try:
        exporter = ANSYSExporter(cfg, ac, result, design_loads, mat_db)
        csv_path = exporter.write_workbench_csv(ansys_dir / "spar_data.csv")
        step_path = output_dir / "spar_geometry.step"
        engine_name = export_step_from_csv(csv_path, step_path, engine="auto")
        print(f"       Saved: {step_path} ({engine_name})")
    except Exception as exc:
        print(f"       STEP export skipped: {exc}")

    # Keep docs/examples snapshots in sync so teammates can inspect baseline
    # outputs without rerunning optimization locally.
    docs_examples_dir = Path(__file__).resolve().parent.parent / "docs" / "examples"
    docs_examples_dir.mkdir(parents=True, exist_ok=True)

    docs_summary_path = docs_examples_dir / "optimization_summary.txt"
    shutil.copy2(summary_path, docs_summary_path)
    print(f"       Synced: {docs_summary_path}")

    beam_plot_path = output_dir / "beam_analysis.png"
    if beam_plot_path.exists():
        docs_beam_plot_path = docs_examples_dir / "beam_analysis.png"
        shutil.copy2(beam_plot_path, docs_beam_plot_path)
        print(f"       Synced: {docs_beam_plot_path}")
    else:
        print(f"       Skip sync (missing): {beam_plot_path}")

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
