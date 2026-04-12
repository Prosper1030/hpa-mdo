#!/usr/bin/env python3
"""Export grouped/discrete dual-beam summary geometry to STEP."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys

import numpy as np

# Allow running directly from the repository without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.structure.optimizer import OptimizationResult
from hpa_mdo.utils.cad_export import export_step_from_csv
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_crossval import _select_cruise_loads
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report
from scripts.direct_dual_beam_v2m import (
    DEFAULT_CATALOG_PROFILE,
    BaselineDesign,
    build_manufacturing_map_config,
    design_from_manufacturing_choice,
)


DEFAULT_SUMMARY_JSON = (
    Path(__file__).resolve().parent.parent
    / "output"
    / "direct_dual_beam_v2m_plusplus_compare"
    / "direct_dual_beam_v2m_summary.json"
)
LEGACY_SELECTION_NAMES = ("selected", "baseline")
FORMAL_SELECTION_NAMES = ("primary", "balanced", "conservative")
SUPPORTED_SELECTION_NAMES = LEGACY_SELECTION_NAMES + FORMAL_SELECTION_NAMES


@dataclass(frozen=True)
class DualBeamStepSelection:
    summary_path: Path
    config_path: Path
    design_report_path: Path
    selection_name: str
    selection_label: str
    selection_status: str
    selection_source: str
    geometry_choice: tuple[int, int, int, int, int] | None
    opt_result: OptimizationResult


def _as_mm_array(design_mm: dict[str, object], key: str) -> np.ndarray:
    values = design_mm.get(key)
    if values is None:
        raise ValueError(f"Summary design_mm is missing '{key}'.")

    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        raise ValueError(f"Summary design_mm['{key}'] must not be empty.")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"Summary design_mm['{key}'] contains non-finite values.")
    return arr


def build_opt_result_from_summary_selection(
    selection: dict[str, object],
    *,
    selection_name: str = "selected",
) -> OptimizationResult:
    """Rebuild an OptimizationResult-like design from a grouped/discrete summary."""

    design_mm = selection.get("design_mm")
    if not isinstance(design_mm, dict):
        raise ValueError("Summary selection must include a 'design_mm' object.")

    main_t_mm = _as_mm_array(design_mm, "main_t")
    main_r_mm = _as_mm_array(design_mm, "main_r")
    rear_t_mm = _as_mm_array(design_mm, "rear_t")
    rear_r_mm = _as_mm_array(design_mm, "rear_r")

    seg_count = main_t_mm.size
    for name, arr in (
        ("main_r", main_r_mm),
        ("rear_t", rear_t_mm),
        ("rear_r", rear_r_mm),
    ):
        if arr.size != seg_count:
            raise ValueError(
                "Grouped/discrete summary must provide the same segment count for "
                f"all spar arrays; expected {seg_count} from main_t, got {arr.size} for {name}."
            )

    tip_deflection_m = float(
        selection.get(
            "equivalent_tip_deflection_m",
            selection.get("raw_main_tip_m", 0.0),
        )
    )
    twist_max_deg = float(selection.get("equivalent_twist_max_deg", 0.0))
    failure_index = float(selection.get("equivalent_failure_index", 0.0))
    buckling_index = float(selection.get("equivalent_buckling_index", 0.0))
    spar_mass_full_kg = float(selection.get("tube_mass_kg", 0.0))
    total_mass_full_kg = float(selection.get("total_structural_mass_kg", spar_mass_full_kg))
    max_tip_deflection_m_raw = selection.get("dual_displacement_limit_m")
    max_tip_deflection_m = (
        None if max_tip_deflection_m_raw is None else float(max_tip_deflection_m_raw)
    )
    selection_source = str(selection.get("source", "summary"))
    selection_message = str(selection.get("message", "analysis complete"))
    success = bool(selection.get("analysis_succeeded", True))

    return OptimizationResult(
        success=success,
        message=(
            f"reconstructed from {selection_name} ({selection_source}) grouped/discrete summary: "
            f"{selection_message}"
        ),
        spar_mass_half_kg=0.5 * spar_mass_full_kg,
        spar_mass_full_kg=spar_mass_full_kg,
        total_mass_full_kg=total_mass_full_kg,
        max_stress_main_Pa=0.0,
        max_stress_rear_Pa=0.0,
        allowable_stress_main_Pa=1.0,
        allowable_stress_rear_Pa=1.0,
        failure_index=failure_index,
        buckling_index=buckling_index,
        tip_deflection_m=tip_deflection_m,
        max_tip_deflection_m=max_tip_deflection_m,
        twist_max_deg=twist_max_deg,
        main_t_seg_mm=main_t_mm,
        main_r_seg_mm=main_r_mm,
        rear_t_seg_mm=rear_t_mm,
        rear_r_seg_mm=rear_r_mm,
        disp=None,
        vonmises_main=None,
        vonmises_rear=None,
    )


def build_opt_result_from_formal_selection(
    selection: dict[str, object],
    *,
    selection_name: str,
    cfg,
    design_report_path: Path,
) -> tuple[OptimizationResult, tuple[int, int, int, int, int], str]:
    """Rebuild an OptimizationResult-like design from a formal workflow slot."""

    selected_candidate = selection.get("selected_candidate")
    if not isinstance(selected_candidate, dict):
        raise ValueError(
            f"Formal selection '{selection_name}' must include a selected_candidate object."
        )

    geometry_choice_raw = selected_candidate.get("geometry_choice")
    if not isinstance(geometry_choice_raw, list) or len(geometry_choice_raw) != 5:
        raise ValueError(
            f"Formal selection '{selection_name}' must include a 5-axis geometry_choice."
        )
    geometry_choice = tuple(int(value) for value in geometry_choice_raw)

    baseline_result = build_specimen_result_from_crossval_report(design_report_path)
    if baseline_result.rear_t_seg_mm is None or baseline_result.rear_r_seg_mm is None:
        raise ValueError("Crossval report must provide both main and rear spar segment geometry.")

    baseline_design = BaselineDesign(
        main_t_seg_m=np.asarray(baseline_result.main_t_seg_mm, dtype=float) * 1.0e-3,
        main_r_seg_m=np.asarray(baseline_result.main_r_seg_mm, dtype=float) * 1.0e-3,
        rear_t_seg_m=np.asarray(baseline_result.rear_t_seg_mm, dtype=float) * 1.0e-3,
        rear_r_seg_m=np.asarray(baseline_result.rear_r_seg_mm, dtype=float) * 1.0e-3,
    )
    map_config = build_manufacturing_map_config(
        baseline=baseline_design,
        cfg=cfg,
        catalog_profile=DEFAULT_CATALOG_PROFILE,
    )
    main_t_m, main_r_m, rear_t_m, rear_r_m = design_from_manufacturing_choice(
        baseline=baseline_design,
        choice=geometry_choice,
        map_config=map_config,
    )

    tip_deflection_m = float(
        selected_candidate.get(
            "equivalent_tip_deflection_m",
            selected_candidate.get("raw_main_tip_m", 0.0),
        )
    )
    twist_max_deg = float(selected_candidate.get("equivalent_twist_max_deg", 0.0))
    failure_index = float(selected_candidate.get("equivalent_failure_index", 0.0))
    buckling_index = float(selected_candidate.get("equivalent_buckling_index", 0.0))
    spar_mass_full_kg = float(selected_candidate.get("tube_mass_kg", 0.0))
    total_mass_full_kg = float(
        selected_candidate.get("total_structural_mass_kg", spar_mass_full_kg)
    )
    dual_displacement_limit_m = selected_candidate.get("dual_displacement_limit_m")
    max_tip_deflection_m = (
        None
        if dual_displacement_limit_m is None
        else float(dual_displacement_limit_m)
    )
    selection_source = str(selected_candidate.get("source", "formal_design_selection"))

    result = OptimizationResult(
        success=True,
        message=(
            f"reconstructed from {selection_name} ({selection_source}) "
            f"formal workflow selection"
        ),
        spar_mass_half_kg=0.5 * spar_mass_full_kg,
        spar_mass_full_kg=spar_mass_full_kg,
        total_mass_full_kg=total_mass_full_kg,
        max_stress_main_Pa=0.0,
        max_stress_rear_Pa=0.0,
        allowable_stress_main_Pa=1.0,
        allowable_stress_rear_Pa=1.0,
        failure_index=failure_index,
        buckling_index=buckling_index,
        tip_deflection_m=tip_deflection_m,
        max_tip_deflection_m=max_tip_deflection_m,
        twist_max_deg=twist_max_deg,
        main_t_seg_mm=np.asarray(main_t_m, dtype=float) * 1000.0,
        main_r_seg_mm=np.asarray(main_r_m, dtype=float) * 1000.0,
        rear_t_seg_mm=np.asarray(rear_t_m, dtype=float) * 1000.0,
        rear_r_seg_mm=np.asarray(rear_r_m, dtype=float) * 1000.0,
        disp=None,
        vonmises_main=None,
        vonmises_rear=None,
    )
    return result, geometry_choice, selection_source


def _load_summary_paths(obj: dict[str, object], summary_path: Path) -> tuple[Path, Path]:
    config_raw = obj.get("config")
    design_report_raw = obj.get("design_report")
    if not isinstance(config_raw, str) or not config_raw.strip():
        raise ValueError(f"Summary JSON {summary_path} is missing a valid 'config' path.")
    if not isinstance(design_report_raw, str) or not design_report_raw.strip():
        raise ValueError(f"Summary JSON {summary_path} is missing a valid 'design_report' path.")
    return (
        Path(config_raw).expanduser().resolve(),
        Path(design_report_raw).expanduser().resolve(),
    )


def _load_formal_selection(
    *,
    summary_path: Path,
    obj: dict[str, object],
    selection_name: str,
) -> DualBeamStepSelection:
    outcome = obj.get("outcome")
    if not isinstance(outcome, dict):
        raise ValueError(f"Summary JSON {summary_path} is missing an 'outcome' object.")

    formal_design_selections = outcome.get("formal_design_selections")
    if not isinstance(formal_design_selections, dict):
        raise ValueError(
            f"Summary JSON {summary_path} is missing outcome.formal_design_selections."
        )

    selection = formal_design_selections.get(selection_name)
    if not isinstance(selection, dict):
        raise ValueError(
            f"Summary JSON {summary_path} is missing outcome.formal_design_selections.{selection_name}."
        )

    config_path, design_report_path = _load_summary_paths(obj, summary_path)
    cfg = load_config(config_path)
    opt_result, geometry_choice, selection_source = build_opt_result_from_formal_selection(
        selection,
        selection_name=selection_name,
        cfg=cfg,
        design_report_path=design_report_path,
    )
    selection_label = str(selection.get("label", selection_name))
    selection_status = str(selection.get("selection_status", "selected"))

    return DualBeamStepSelection(
        summary_path=summary_path,
        config_path=config_path,
        design_report_path=design_report_path,
        selection_name=selection_name,
        selection_label=selection_label,
        selection_status=selection_status,
        selection_source=selection_source,
        geometry_choice=geometry_choice,
        opt_result=opt_result,
    )


def load_dual_beam_step_selection(
    summary_json: str | Path,
    *,
    selection_name: str = "selected",
) -> DualBeamStepSelection:
    """Load one grouped/discrete design selection from a summary JSON file."""

    summary_path = Path(summary_json).expanduser().resolve()
    obj = json.loads(summary_path.read_text(encoding="utf-8"))
    outcome = obj.get("outcome")
    if not isinstance(outcome, dict):
        raise ValueError(f"Summary JSON {summary_path} is missing an 'outcome' object.")

    config_path, design_report_path = _load_summary_paths(obj, summary_path)

    if selection_name in FORMAL_SELECTION_NAMES:
        return _load_formal_selection(
            summary_path=summary_path,
            obj=obj,
            selection_name=selection_name,
        )

    selection = outcome.get(selection_name)
    if not isinstance(selection, dict):
        raise ValueError(f"Summary JSON {summary_path} is missing outcome.{selection_name}.")

    return DualBeamStepSelection(
        summary_path=summary_path,
        config_path=config_path,
        design_report_path=design_report_path,
        selection_name=selection_name,
        selection_label=selection_name,
        selection_status="selected",
        selection_source=str(selection.get("source", "summary")),
        geometry_choice=None,
        opt_result=build_opt_result_from_summary_selection(
            selection,
            selection_name=selection_name,
        ),
    )


def export_dual_beam_step(
    summary_json: str | Path,
    step_path: str | Path,
    *,
    selection_name: str = "selected",
    engine: str = "auto",
    csv_path: str | Path | None = None,
) -> tuple[Path, Path, str, DualBeamStepSelection]:
    """Export STEP geometry from a grouped/discrete dual-beam summary."""

    selection = load_dual_beam_step_selection(
        summary_json,
        selection_name=selection_name,
    )

    cfg = load_config(selection.config_path)
    specimen_metrics = parse_baseline_metrics(selection.design_report_path)
    cfg.solver.n_beam_nodes = int(specimen_metrics.nodes_per_spar)

    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    _, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)

    step_output = Path(step_path).expanduser().resolve()
    step_output.parent.mkdir(parents=True, exist_ok=True)
    if csv_path is None:
        csv_output = step_output.with_name(f"{step_output.stem}_spar_data.csv")
    else:
        csv_output = Path(csv_path).expanduser().resolve()
    csv_output.parent.mkdir(parents=True, exist_ok=True)

    exporter = ANSYSExporter(
        cfg,
        aircraft,
        selection.opt_result,
        export_loads,
        materials_db,
        mode="dual_beam_production",
    )
    csv_output = exporter.write_workbench_csv(csv_output)
    engine_name = export_step_from_csv(csv_output, step_output, engine=engine)
    return step_output, csv_output, engine_name, selection


def _default_step_output(summary_json: Path, selection_name: str) -> Path:
    stem = summary_json.stem
    return summary_json.with_name(f"{stem}_{selection_name}.step")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export grouped/discrete dual-beam geometry summary to STEP/STP.",
    )
    parser.add_argument(
        "--summary-json",
        default=str(DEFAULT_SUMMARY_JSON),
        help="Path to a summary JSON with outcome.selected.design_mm.",
    )
    parser.add_argument(
        "--selection",
        choices=SUPPORTED_SELECTION_NAMES,
        default="selected",
        help="Which legacy outcome block or formal workflow slot to export.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output STEP/STP path. Defaults beside the summary JSON.",
    )
    parser.add_argument(
        "--csv-output",
        default=None,
        help="Optional intermediate dual-spar CSV path.",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "cadquery", "build123d"),
        default="auto",
        help="CAD engine used by the existing STEP exporter.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary_json = Path(args.summary_json).expanduser().resolve()
    output = (
        Path(args.output).expanduser().resolve()
        if args.output is not None
        else _default_step_output(summary_json, args.selection)
    )

    step_output, csv_output, engine_name, selection = export_dual_beam_step(
        summary_json,
        output,
        selection_name=args.selection,
        engine=args.engine,
        csv_path=args.csv_output,
    )

    print("Dual-beam STEP export complete.")
    print(f"  Summary JSON  : {selection.summary_path}")
    print(
        "  Selection     : "
        f"{selection.selection_name} [{selection.selection_label}] "
        f"status={selection.selection_status} "
        f"source={selection.selection_source}"
    )
    if selection.geometry_choice is not None:
        print(f"  Geometry      : {selection.geometry_choice}")
    print(f"  Config        : {selection.config_path}")
    print(f"  Design report : {selection.design_report_path}")
    print(f"  CSV           : {csv_output}")
    print(f"  STEP          : {step_output}")
    print(f"  Engine        : {engine_name}")
    print(f"  Message       : {selection.opt_result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
