#!/usr/bin/env python3
"""HPA-MDO: End-to-end spar optimization pipeline.

Usage:
    python scripts/run_optimization.py [--config configs/blackcat_004.yaml]

Output:
    - Optimization results printed to stdout
    - ANSYS export files in output/ directory
    - Training data appended to database/
    - LAST LINE: val_weight: <float>

The ``val_weight:`` sentinel is machine-parseable by external AI agents
(autoresearch) — any exception causes ``val_weight: 99999`` so the outer
loop always receives a numeric value.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Optional

# Allow running directly from the repository without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# ---------------------------------------------------------------------------
# Entire script wrapped in try/except so that val_weight is ALWAYS printed.
# ---------------------------------------------------------------------------

def main(
    config_path: str,
    output_dir: Optional[str] = None,
    quiet: bool = False,
    no_export: bool = False,
    aoa_deg: Optional[float] = None,
) -> float:
    """Run the full HPA-MDO pipeline and return total_mass_full_kg."""


    from hpa_mdo.core import load_config, Aircraft, MaterialDB
    from hpa_mdo.aero import VSPAeroParser, LoadMapper
    from hpa_mdo.structure import SparOptimizer
    from hpa_mdo.utils.data_collector import DataCollector

    # ── 1. Load configuration ──────────────────────────────────────────
    print(f"[1/9] Loading config: {config_path}")
    cfg = load_config(config_path)
    if output_dir is not None:
        cfg.io.output_dir = Path(output_dir).expanduser().resolve()
        print(f"       Overriding output_dir -> {cfg.io.output_dir}")
    print(f"       Project: {cfg.project_name}")
    print(f"       Span: {cfg.wing.span} m  |  V={cfg.flight.velocity} m/s")

    # ── 2. Build aircraft geometry ─────────────────────────────────────
    print("[2/9] Building aircraft geometry...")
    ac = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    target_weight = ac.weight_N  # full-span weight [N]
    print(f"       Operating mass: {ac.mass_total_kg:.1f} kg  "
          f"({target_weight:.1f} N)")

    # ── 3. Parse VSPAero data ──────────────────────────────────────────
    print("[3/9] Parsing VSPAero loads...")
    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
    cases = parser.parse()
    print(f"       Found {len(cases)} AoA case(s)")

    # ── 4. Find cruise AoA (lift ~= weight) ───────────────────────────
    print("[4/9] Finding cruise angle of attack (L ~= W)...")
    mapper = LoadMapper()

    best_case: Optional[object] = None
    best_residual = float("inf")
    best_loads: Optional[dict] = None

    if aoa_deg is None:
        for case in cases:
            loads = mapper.map_loads(
                case, ac.wing.y,
                actual_velocity=cfg.flight.velocity,
                actual_density=cfg.flight.air_density,
            )
            # total_lift is half-span; full-span lift = 2 * total_lift
            full_lift = 2.0 * loads["total_lift"]
            residual = abs(full_lift - target_weight)
            if residual < best_residual:
                best_residual = residual
                best_case = case
                best_loads = loads
    else:
        best_case = min(cases, key=lambda c: abs(c.aoa_deg - aoa_deg))
        best_loads = mapper.map_loads(
            best_case,
            ac.wing.y,
            actual_velocity=cfg.flight.velocity,
            actual_density=cfg.flight.air_density,
        )

    if best_case is None or best_loads is None:
        raise RuntimeError("No valid AoA case found in VSPAero data")

    cruise_aoa = best_case.aoa_deg
    cruise_lift = 2.0 * best_loads["total_lift"]
    if aoa_deg is None:
        print(f"       Cruise AoA: {cruise_aoa:.2f} deg  "
              f"(lift={cruise_lift:.1f} N vs weight={target_weight:.1f} N)")
    else:
        print(
            f"       Requested AoA: {aoa_deg:.2f} deg -> using closest case "
            f"{cruise_aoa:.2f} deg (lift={cruise_lift:.1f} N)"
        )

    # ── 5. Map loads with aerodynamic load factor ──────────────────────
    print("[5/9] Mapping loads with safety factor...")
    design_loads = LoadMapper.apply_load_factor(
        best_loads, cfg.safety.aerodynamic_load_factor
    )
    print(f"       Load factor: {cfg.safety.aerodynamic_load_factor}G  "
          f"-> design lift = {2.0 * design_loads['total_lift']:.1f} N")

    # ── 6. Run structural optimization ─────────────────────────────────
    print("[6/9] Running spar optimization (method=scipy)...")
    opt = SparOptimizer(cfg, ac, design_loads, mat_db)
    result = opt.optimize(method="scipy")
    print(result.summary())

    # ── 7. Generate visualizations ─────────────────────────────────────────
    print("[7/9] Generating visualizations...")
    output_dir = Path(cfg.io.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        from hpa_mdo.utils.visualization import (
            plot_beam_analysis,
            plot_spar_geometry,
            write_optimization_summary,
        )

        seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
        plot_beam_analysis(result, ac.wing.y, output_dir)
        plot_spar_geometry(result, ac.wing.y, seg_lengths, output_dir)
        summary_path = output_dir / "optimization_summary.txt"
        write_optimization_summary(result, summary_path)
        print(
            "       Saved: beam_analysis.png, spar_geometry.png, optimization_summary.txt"
        )
        if quiet:
            print("       Quiet mode: plots were written to files only.")
    except Exception as exc:
        print(f"       Visualization skipped: {exc}")

    # ── 8. Export ANSYS files ──────────────────────────────────────────
    print("[8/9] Exporting analysis artifacts...")
    _export_design_summary(cfg, result, output_dir)
    if no_export:
        print("       ANSYS/STEP export skipped (--no-export).")
    else:
        try:
            from hpa_mdo.structure.ansys_export import ANSYSExporter

            ansys_dir = output_dir / "ansys"
            ansys_dir.mkdir(parents=True, exist_ok=True)
            exporter = ANSYSExporter(cfg, ac, result, design_loads, mat_db)

            apdl_path = exporter.write_apdl(ansys_dir / "spar_model.mac")
            csv_path = exporter.write_workbench_csv(ansys_dir / "spar_data.csv")
            bdf_path = exporter.write_nastran_bdf(ansys_dir / "spar_model.bdf")
            print(f"       Saved: {apdl_path.name}, {csv_path.name}, {bdf_path.name}")

            try:
                from hpa_mdo.utils.cad_export import export_step_from_csv

                step_path = output_dir / "spar_model.step"
                engine_name = export_step_from_csv(csv_path, step_path, engine="auto")
                print(f"       Saved: {step_path.name} ({engine_name})")
            except Exception as exc:
                print(f"       STEP export skipped: {exc}")
        except Exception as exc:
            print(f"       ANSYS export skipped: {exc}")

    print(f"       Output dir: {output_dir}")

    # ── 9. Record to training database ─────────────────────────────────
    print("[9/9] Recording to training database...")
    aero_info = {
        "aoa_deg": cruise_aoa,
        "total_lift_N": cruise_lift,
    }
    try:
        collector = DataCollector(str(cfg.io.training_db))
        db_path = collector.record(cfg, result, aero_info=aero_info)
        print(f"       Database: {db_path}")
    except Exception as exc:
        print(f"       Database write skipped: {exc}")

    # ── Done ───────────────────────────────────────────────────────────
    print("Done.")
    total_mass = result.total_mass_full_kg
    print(f"\n  Total spar system mass: {total_mass:.4f} kg")
    print(f"  Feasible: {result.failure_index <= 0}")
    print(f"  Converged: {result.success}")

    return total_mass


def _export_design_summary(cfg, result, output_dir: Path) -> None:
    """Write a small CSV with the optimised segment thicknesses."""
    import csv

    path = output_dir / "design_summary.csv"
    rows = []
    for i, t in enumerate(result.main_t_seg_mm):
        row = {"spar": "main", "segment": i + 1, "thickness_mm": f"{t:.4f}"}
        rows.append(row)
    if result.rear_t_seg_mm is not None:
        for i, t in enumerate(result.rear_t_seg_mm):
            row = {"spar": "rear", "segment": i + 1, "thickness_mm": f"{t:.4f}"}
            rows.append(row)

    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["spar", "segment", "thickness_mm"])
        writer.writeheader()
        writer.writerows(rows)


# ── Entry point ────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="HPA-MDO end-to-end spar optimisation pipeline."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory from config",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not display interactive plots; only write image/report files",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Skip ANSYS/STEP export",
    )
    parser.add_argument(
        "--aoa",
        default="auto",
        help="Target AoA in degrees, or 'auto' to pick closest L~=W case",
    )
    return parser


def _parse_aoa_value(aoa: str) -> Optional[float]:
    if aoa.lower() == "auto":
        return None
    return float(aoa)


def cli(argv: Optional[list[str]] = None) -> float:
    try:
        parser = _build_arg_parser()
        args = parser.parse_args(argv)
        aoa_deg = _parse_aoa_value(args.aoa)

        mass = main(
            config_path=args.config,
            output_dir=args.output_dir,
            quiet=args.quiet,
            no_export=args.no_export,
            aoa_deg=aoa_deg,
        )
        # LAST LINE — parseable by autoresearch agents
        # NOTE: This sentinel is only for top-level pipeline failures.
        # Internal optimizer evaluation failures are normalized separately.
        print(f"val_weight: {mass}")
        return mass

    except Exception:
        traceback.print_exc()
        # LAST LINE — parseable by autoresearch agents (sentinel for failure)
        print("val_weight: 99999")
        sys.exit(0)  # exit gracefully even on error


if __name__ == "__main__":
    cli()
