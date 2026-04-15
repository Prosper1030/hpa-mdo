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

import argparse
import sys
import shutil
from pathlib import Path
from typing import Optional

import numpy as np


# Allow running directly from the repository without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ── v2 imports ────────────────────────────────────────────────────────────
from hpa_mdo.core import load_config, Aircraft, MaterialDB
from hpa_mdo.aero import VSPAeroParser, LoadMapper
from hpa_mdo.structure import SparOptimizer
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.utils import compute_deformed_nodes, export_step_from_csv
from hpa_mdo.utils.visualization import (
    plot_beam_analysis,
    plot_spar_geometry,
    write_optimization_summary,
    print_optimization_summary,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Black Cat 004 spar optimization")
    parser.add_argument(
        "--discrete-od",
        action="store_true",
        default=False,
        help=(
            "Post-process continuous OD solution by snapping to the nearest "
            "commercial tube size (always round up). Re-evaluates the snapped "
            "design with the Phase I solver to verify constraints."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to an alternate HPAConfig YAML (e.g. one produced by "
            "scripts/analyze_vsp.py). Defaults to configs/blackcat_004.yaml."
        ),
    )
    parser.add_argument(
        "--discrete-layup",
        action="store_true",
        default=False,
        help=(
            "Post-process continuous wall-thickness design by snapping each "
            "segment to the nearest valid integer ply stack (0/+-45/90), "
            "re-evaluating Tsai-Wu FI per segment. Combines with --discrete-od "
            "(OD is snapped first, then layup)."
        ),
    )
    parser.add_argument(
        "--ply-material",
        default=None,
        help=(
            "Override ply material key in data/materials.yaml used for the "
            "discrete layup post-process (default: cfg.main_spar.ply_material)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> float:
    """Run the full pipeline and return total_mass_full_kg."""
    args = _parse_args(argv)

    # ====================================================================
    # Step 1 — Load configuration
    # ====================================================================
    # The YAML file specifies wing geometry, flight conditions, material
    # properties, segment definitions, and file paths for VSPAero data.
    if args.config:
        config_path = Path(args.config).resolve()
    else:
        config_path = (
            Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"
        )
    print(f"[1/10] Loading config: {config_path}")
    cfg = load_config(config_path)
    print(f"       Project : {cfg.project_name}")
    print(f"       Span    : {cfg.wing.span} m")
    print(f"       Velocity: {cfg.flight.velocity} m/s")

    # ====================================================================
    # Step 2 — Build aircraft geometry and material database
    # ====================================================================
    # Aircraft.from_config() constructs the wing planform, computes spanwise
    # node positions (ac.wing.y), reference areas, and operating weight.
    print("[2/10] Building aircraft geometry...")
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
    print("[3/10] Parsing VSPAero loads...")
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
    print("[4/10] Finding cruise angle of attack (L ≈ W)...")
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
    # Keep mapped aero loads at their raw physical level for SparOptimizer.
    # The structural case owns the aerodynamic maneuver scaling via
    # LoadCaseConfig.aero_scale inside the OpenMDAO model.
    print("[5/10] Preparing structural load case scaling...")
    mapped_loads = best_loads
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)
    design_full_lift = 2.0 * mapped_loads["total_lift"] * design_case.aero_scale
    print(f"       Load factor : {design_case.aero_scale}G")
    print(f"       Design lift : {design_full_lift:.1f} N (full span)")

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
    print("[6/10] Running spar optimization...")
    opt = SparOptimizer(cfg, ac, mapped_loads, mat_db)
    result = opt.optimize(method="auto")

    # Print a rich summary to stdout
    print_optimization_summary(result)

    val_weight_mass = result.total_mass_full_kg
    if args.discrete_od and result.success:
        from hpa_mdo.utils.discrete_od import apply_discrete_od, load_tube_catalog

        catalog_path = Path(__file__).resolve().parent.parent / "data" / "tube_catalog.yaml"
        catalog = load_tube_catalog(catalog_path)
        result_continuous = result
        try:
            result_discrete_preview = apply_discrete_od(result_continuous, catalog)
        except ValueError as exc:
            raise RuntimeError(
                "Discrete OD post-processing failed: the current tube catalog cannot "
                "conservatively round up this optimized design. Expand "
                "data/tube_catalog.yaml or rerun without --discrete-od."
            ) from exc

        print("\n" + "=" * 60)
        print("  DISCRETE OD POST-PROCESSING")
        print("=" * 60)
        print(f"  Continuous mass : {result_continuous.total_mass_full_kg:.3f} kg")
        print(
            f"  Preview mass    : {result_discrete_preview.total_mass_full_kg:.3f} kg (scaled estimate)"
        )

        main_od_cont = result_continuous.main_r_seg_mm * 2.0
        main_od_disc = result_discrete_preview.main_r_seg_mm * 2.0
        for i, (continuous_od, discrete_od) in enumerate(zip(main_od_cont, main_od_disc)):
            print(f"  Main seg {i + 1}: OD {continuous_od:.1f} mm -> {discrete_od:.1f} mm")

        if (
            result_continuous.rear_r_seg_mm is not None
            and result_discrete_preview.rear_r_seg_mm is not None
        ):
            rear_od_cont = result_continuous.rear_r_seg_mm * 2.0
            rear_od_disc = result_discrete_preview.rear_r_seg_mm * 2.0
            for i, (continuous_od, discrete_od) in enumerate(zip(rear_od_cont, rear_od_disc)):
                print(f"  Rear seg {i + 1}: OD {continuous_od:.1f} mm -> {discrete_od:.1f} mm")

        print("\n  Re-evaluating snapped design with the structural solver...")
        result = opt.analyze(
            main_t_seg=result_continuous.main_t_seg_mm / 1000.0,
            main_r_seg=result_discrete_preview.main_r_seg_mm / 1000.0,
            rear_t_seg=(
                result_continuous.rear_t_seg_mm / 1000.0
                if result_continuous.rear_t_seg_mm is not None
                else None
            ),
            rear_r_seg=(
                result_discrete_preview.rear_r_seg_mm / 1000.0
                if result_discrete_preview.rear_r_seg_mm is not None
                else None
            ),
        )
        result.message = "Discrete OD design re-verified with snapped catalog radii"
        print(f"  Verified mass   : {result.total_mass_full_kg:.3f} kg")
        print(f"  Verified failure: {result.failure_index:.5f}")
        print(f"  Verified buckling: {result.buckling_index:.5f}")
        print(f"  Verified twist  : {result.twist_max_deg:.3f} deg")
        print(f"  Verified defl.  : {result.tip_deflection_m:.5f} m")
        val_weight_mass = result.total_mass_full_kg

    if args.discrete_layup and result.success:
        from hpa_mdo.utils.discrete_layup import (
            build_segment_layup_results,
            enumerate_valid_stacks,
            summarize_layup_results,
        )

        print("\n" + "=" * 60)
        print("  DISCRETE LAYUP POST-PROCESSING")
        print("=" * 60)

        def _build_spar_layup(spar_cfg, t_seg_mm, r_seg_mm, label):
            ply_key = args.ply_material or getattr(spar_cfg, "ply_material", None)
            if ply_key is None:
                print(
                    f"  {label}: discrete layup skipped "
                    "(spar.ply_material not set in config)."
                )
                return None, None
            try:
                ply_mat = mat_db.get_ply(ply_key)
            except Exception as exc:
                print(f"  {label}: discrete layup skipped (ply '{ply_key}' not found: {exc}).")
                return None, None
            try:
                stacks = enumerate_valid_stacks(spar_cfg)
            except Exception as exc:
                print(f"  {label}: enumerate_valid_stacks failed ({exc}).")
                return None, None
            if not stacks:
                print(f"  {label}: no valid stacks enumerated from config limits; skipping.")
                return None, None

            seg_lengths = cfg.spar_segment_lengths(spar_cfg)
            n_seg = len(seg_lengths)
            t_seg_m = np.asarray(t_seg_mm, dtype=float) / 1000.0
            r_seg_m = np.asarray(r_seg_mm, dtype=float) / 1000.0

            env = result.strain_envelope or {}
            eps_arr = np.asarray(env.get("epsilon_x_absmax", np.zeros(n_seg)), dtype=float)
            kap_arr = np.asarray(env.get("kappa_absmax", np.zeros(n_seg)), dtype=float)
            tor_arr = np.asarray(env.get("torsion_rate_absmax", np.zeros(n_seg)), dtype=float)

            def _safe(a, i):
                return float(a[i]) if i < len(a) else 0.0

            strain_envs = [
                {
                    "epsilon_x_absmax": _safe(eps_arr, i),
                    "kappa_absmax": _safe(kap_arr, i),
                    "torsion_rate_absmax": _safe(tor_arr, i),
                }
                for i in range(n_seg)
            ]

            try:
                layup = build_segment_layup_results(
                    segment_lengths_m=seg_lengths,
                    continuous_thicknesses_m=t_seg_m.tolist(),
                    outer_radii_m=r_seg_m.tolist(),
                    stacks=stacks,
                    ply_mat=ply_mat,
                    ply_drop_limit=int(getattr(spar_cfg, "max_ply_drop_per_segment", 1)),
                    strain_envelopes=strain_envs,
                )
            except Exception as exc:
                print(f"  {label}: build_segment_layup_results failed ({exc}).")
                return None, None

            summary = summarize_layup_results(
                layup,
                ply_drop_limit=int(getattr(spar_cfg, "max_ply_drop_per_segment", 1)),
                min_run_length_m=float(getattr(spar_cfg, "min_layup_run_length_m", 0.0)),
            )
            return layup, summary

        layup_main, layup_main_summary = _build_spar_layup(
            cfg.main_spar, result.main_t_seg_mm, result.main_r_seg_mm, "main_spar"
        )
        layup_rear, layup_rear_summary = (None, None)
        if (
            getattr(cfg.rear_spar, "enabled", False)
            and result.rear_t_seg_mm is not None
            and result.rear_r_seg_mm is not None
        ):
            layup_rear, layup_rear_summary = _build_spar_layup(
                cfg.rear_spar, result.rear_t_seg_mm, result.rear_r_seg_mm, "rear_spar"
            )

        if layup_main is not None:
            result.layup_main = layup_main
            result.layup_main_summary = layup_main_summary
        if layup_rear is not None:
            result.layup_rear = layup_rear
            result.layup_rear_summary = layup_rear_summary

        # Re-analyze using the discrete-equivalent wall thicknesses so the
        # summary reports Tsai-Wu / failure / deflection under the stack we
        # actually plan to build.  OD is preserved (already snapped if
        # --discrete-od ran earlier).
        if layup_main is not None:
            main_t_equiv_m = np.array(
                [seg.equivalent_properties.wall_thickness for seg in layup_main],
                dtype=float,
            )
            if layup_rear is not None:
                rear_t_equiv_m = np.array(
                    [seg.equivalent_properties.wall_thickness for seg in layup_rear],
                    dtype=float,
                )
            else:
                rear_t_equiv_m = (
                    result.rear_t_seg_mm / 1000.0
                    if result.rear_t_seg_mm is not None
                    else None
                )

            print("  Re-evaluating snapped layup with the structural solver...")
            prev_layup_main = layup_main
            prev_layup_rear = layup_rear
            prev_layup_main_summary = layup_main_summary
            prev_layup_rear_summary = layup_rear_summary
            try:
                result = opt.analyze(
                    main_t_seg=main_t_equiv_m,
                    main_r_seg=result.main_r_seg_mm / 1000.0,
                    rear_t_seg=rear_t_equiv_m,
                    rear_r_seg=(
                        result.rear_r_seg_mm / 1000.0
                        if result.rear_r_seg_mm is not None
                        else None
                    ),
                )
                result.message = "Discrete layup design re-verified with integer ply stacks"
                result.layup_main = prev_layup_main
                result.layup_main_summary = prev_layup_main_summary
                if prev_layup_rear is not None:
                    result.layup_rear = prev_layup_rear
                    result.layup_rear_summary = prev_layup_rear_summary
                print(f"  Verified mass   : {result.total_mass_full_kg:.3f} kg")
                print(f"  Verified failure: {result.failure_index:.5f}")
                print(f"  Verified twist  : {result.twist_max_deg:.3f} deg")
                print(f"  Verified defl.  : {result.tip_deflection_m:.5f} m")
                val_weight_mass = result.total_mass_full_kg
            except Exception as exc:
                print(f"  Re-analyze skipped ({exc}); keeping continuous result.")

    # ====================================================================
    # Step 7 — Generate visualizations
    # ====================================================================
    # Two figures are saved to the output directory:
    #   beam_analysis.png  — deflection, twist, von Mises stress, mass summary
    #   spar_geometry.png  — OD, wall thickness, ID, cross-section area per segment
    print("[7/10] Generating visualizations...")
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
    print("[8/10] Writing optimization summary...")
    summary_path = output_dir / "optimization_summary.txt"
    write_optimization_summary(result, summary_path)
    print(f"       Saved: {summary_path}")

    # ====================================================================
    # Step 9 — Export STEP geometry for CAD inspection (jig + flight shape)
    # ====================================================================
    print("[9/10] Exporting STEP geometry for CAD inspection...")
    ansys_dir = output_dir / "ansys"
    ansys_dir.mkdir(parents=True, exist_ok=True)
    try:
        exporter = ANSYSExporter(cfg, ac, result, export_loads, mat_db)
        csv_path = exporter.write_workbench_csv(ansys_dir / "spar_data.csv")
        jig_step_path = output_dir / "spar_jig_shape.step"
        flight_step_path = output_dir / "spar_flight_shape.step"
        engine_name = export_step_from_csv(csv_path, jig_step_path, engine="auto")
        print(f"       Saved: {jig_step_path} ({engine_name})")

        if result.nodes is not None and result.disp is not None:
            deformed_nodes = compute_deformed_nodes(result)
            export_step_from_csv(
                csv_path,
                flight_step_path,
                engine=engine_name,
                deformed_nodes=deformed_nodes,
            )
            print(f"       Saved: {flight_step_path} ({engine_name})")
        else:
            print("       Skipped flight-shape STEP export: missing displacement output")
    except Exception as exc:
        print(f"       STEP export skipped: {exc}")

    # ── Cruise wing OML export ──────────────────────────────────────────
    # Deform the reference jig planform by the structural uz/θy field to
    # produce cruise.vsp3 (for CFD) and the jig counterpart.  This is the
    # geometry counterpart to the spar flight_shape STEP above — STEP is
    # the structural tube cores, cruise.vsp3 is the aero OML.
    if result.nodes is not None and result.disp is not None:
        try:
            from hpa_mdo.aero.cruise_vsp_builder import CruiseVSPBuilder
            from hpa_mdo.aero.vsp_builder import VSPBuilder

            y_nodes = np.asarray(result.nodes)[:, 1]
            uz = np.asarray(result.disp)[:, 2]
            theta_y = np.asarray(result.disp)[:, 4]

            jig_vsp_path = output_dir / "wing_jig.vsp3"
            cruise_vsp_path = output_dir / "wing_cruise.vsp3"

            VSPBuilder(cfg).build_vsp3(str(jig_vsp_path))
            print(f"       Saved: {jig_vsp_path}")

            cruise_info = CruiseVSPBuilder(cfg, y_nodes, uz, theta_y).build(cruise_vsp_path)
            if cruise_info.get("success"):
                print(
                    f"       Saved: {cruise_vsp_path} "
                    f"(tip z {cruise_info['tip_z_m']:+.3f} m, "
                    f"tip twist {cruise_info['tip_twist_deg']:+.3f} deg)"
                )
            else:
                print(f"       Cruise VSP skipped: {cruise_info.get('error')}")
        except Exception as exc:
            print(f"       Cruise VSP skipped: {exc}")

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

    # ====================================================================
    # Step 10 — Aircraft mass / CG / inertia budget (M14, non-invasive)
    # ====================================================================
    # Merges the post-process structural result with the aircraft-wide
    # mass_budget config.  Emits yaml / markdown / AVL artifacts without
    # affecting val_weight.
    print("[10/10] Exporting mass / CG / inertia budget...")
    try:
        from hpa_mdo.mass import build_mass_budget_from_config

        budget = build_mass_budget_from_config(
            cfg,
            result,
            aircraft=ac,
            materials_db=mat_db,
        )
        budget.to_yaml(output_dir / "mass_budget.yaml")
        budget.write_report(output_dir / "mass_budget_report.md")
        budget.to_avl_mass(output_dir / "avl_mass.mass", rho=float(cfg.flight.air_density))
        for warning in budget.warnings:
            print(f"       {warning}")

        cg = budget.center_of_gravity()
        gate = budget.sanity_check()
        gate_flag = "PASS" if gate["passed"] else "WARN"
        print(
            f"       Mass: {budget.total_mass():.3f} kg "
            f"(σ {budget.total_sigma():.3f} kg), "
            f"CG=[{cg[0]:+.3f}, {cg[1]:+.3f}, {cg[2]:+.3f}] m, "
            f"sanity {gate_flag}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"       WARN: mass budget skipped: {exc}")

    total_mass = val_weight_mass
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
    print(f"val_weight: {val_weight_mass:.6f}")

    return total_mass


if __name__ == "__main__":
    main()
