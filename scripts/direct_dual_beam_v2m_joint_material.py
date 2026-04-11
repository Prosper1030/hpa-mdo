#!/usr/bin/env python3
"""Reduced joint geometry + promoted-material discrete search on top of V2.m++."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import product
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

# Allow running directly from repository root without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hpa_mdo.aero import LoadMapper
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.structure.material_proxy_catalog import build_default_material_proxy_catalog
from scripts.ansys_compare_results import parse_baseline_metrics
from scripts.ansys_crossval import _select_cruise_loads
from scripts.ansys_dual_beam_production_check import build_specimen_result_from_crossval_report
from scripts.direct_dual_beam_v2m import (
    DEFAULT_CATALOG_PROFILE,
    BaselineDesign,
    build_manufacturing_map_config,
)
from scripts.direct_dual_beam_v2m_material_proxy import (
    MaterialProxyCandidate,
    MaterialProxyEvaluator,
    build_geometry_seeds,
    catalog_to_summary_dict,
    candidate_to_summary_dict,
)


DEFAULT_V2M_SUMMARY_JSON = (
    Path(__file__).resolve().parent.parent
    / "output"
    / "direct_dual_beam_v2m_plusplus_compare"
    / "direct_dual_beam_v2m_summary.json"
)
DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parent.parent / "output" / "direct_dual_beam_v2m_joint_material"
)
TOP_K = 10


@dataclass(frozen=True)
class JointGeometryBestRow:
    geometry_label: str
    geometry_choice: tuple[int, int, int, int, int]
    joint_choice_indices: tuple[int, int, int, int, int, int, int]
    main_family_key: str
    rear_outboard_pkg_key: str
    tube_mass_kg: float
    psi_u_all_mm: float
    candidate_margin_mm: float
    candidate_feasible: bool


@dataclass(frozen=True)
class JointMaterialOutcome:
    success: bool
    feasible: bool
    message: str
    total_wall_time_s: float
    geometry_seed_count: int
    evaluated_candidate_count: int
    search_space_size: int
    equivalent_analysis_calls: int
    production_analysis_calls: int
    reference_candidate: MaterialProxyCandidate
    selected_candidate: MaterialProxyCandidate
    best_margin_candidate_feasible: MaterialProxyCandidate | None
    best_violation: MaterialProxyCandidate
    geometry_best_rows: tuple[JointGeometryBestRow, ...]
    top_candidate_feasible: tuple[MaterialProxyCandidate, ...]


def _mm(value_m: float | None) -> float:
    if value_m is None:
        return float("nan")
    return float(value_m) * 1000.0


def _signed_mm_delta(delta_m: float) -> float:
    return float(delta_m) * 1000.0


def _load_v2m_selected_choice(path: Path) -> tuple[int, int, int, int, int]:
    obj = json.loads(path.read_text())
    selected = obj["outcome"]["selected"]
    return tuple(int(value) for value in selected["choice_indices"])


def _load_v2m_reference(path: Path) -> dict[str, object]:
    obj = json.loads(path.read_text())
    outcome = obj["outcome"]
    selected = outcome["selected"]
    dual_limit = (
        None
        if selected.get("dual_displacement_limit_m") is None
        else float(selected["dual_displacement_limit_m"])
    )
    candidate_margin_m = (
        None
        if dual_limit is None
        else float(dual_limit) - float(selected["psi_u_all_m"])
    )
    return {
        "path": str(path),
        "success": bool(outcome["success"]),
        "feasible": bool(outcome["feasible"]),
        "total_wall_time_s": float(outcome["total_wall_time_s"]),
        "tube_mass_kg": float(selected["tube_mass_kg"]),
        "total_structural_mass_kg": float(selected["total_structural_mass_kg"]),
        "raw_main_tip_m": float(selected["raw_main_tip_m"]),
        "raw_rear_tip_m": float(selected["raw_rear_tip_m"]),
        "raw_max_uz_m": float(selected["raw_max_uz_m"]),
        "raw_max_location": str(selected["raw_max_location"]),
        "psi_u_all_m": float(selected["psi_u_all_m"]),
        "psi_u_rear_m": float(selected["psi_u_rear_m"]),
        "psi_u_rear_outboard_m": float(selected["psi_u_rear_outboard_m"]),
        "dual_displacement_limit_m": dual_limit,
        "candidate_margin_m": candidate_margin_m,
        "overall_hard_feasible": bool(selected["overall_hard_feasible"]),
        "overall_optimizer_candidate_feasible": bool(selected["overall_optimizer_candidate_feasible"]),
        "choice_indices": tuple(int(value) for value in selected["choice_indices"]),
        "manufacturing_variables": dict(selected["manufacturing_variables"]),
        "design_mm": dict(selected["design_mm"]),
    }


def build_joint_search_space(
    *,
    geometry_seeds,
    main_packages,
    rear_outboard_packages,
) -> tuple[tuple[object, object, object, int, int], ...]:
    rows = []
    for geometry_seed, (main_index, main_package), (outboard_index, rear_outboard_package) in product(
        geometry_seeds,
        enumerate(main_packages),
        enumerate(rear_outboard_packages),
    ):
        rows.append(
            (
                geometry_seed,
                main_package,
                rear_outboard_package,
                int(main_index),
                int(outboard_index),
            )
        )
    return tuple(rows)


def build_joint_choice_indices(
    *,
    geometry_choice: tuple[int, int, int, int, int],
    main_family_index: int,
    rear_outboard_index: int,
) -> tuple[int, int, int, int, int, int, int]:
    return (
        int(geometry_choice[0]),
        int(geometry_choice[1]),
        int(geometry_choice[2]),
        int(geometry_choice[3]),
        int(geometry_choice[4]),
        int(main_family_index),
        int(rear_outboard_index),
    )


def run_joint_material_search(
    *,
    cfg,
    aircraft,
    materials_db: MaterialDB,
    mapped_loads: dict,
    export_loads: dict,
    map_config,
    geometry_seeds,
):
    catalog = build_default_material_proxy_catalog()
    rear_ref = catalog.rear_spar_family[0]
    ref_main = catalog.main_spar_family[0]
    ref_outboard = catalog.rear_outboard_reinforcement_pkg[0]

    evaluator = MaterialProxyEvaluator(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        mapped_loads=mapped_loads,
        export_loads=export_loads,
        map_config=map_config,
        catalog=catalog,
    )
    search_space = build_joint_search_space(
        geometry_seeds=geometry_seeds,
        main_packages=catalog.main_spar_family,
        rear_outboard_packages=catalog.rear_outboard_reinforcement_pkg,
    )

    total_start = perf_counter()
    reference_candidate = evaluator.evaluate(
        geometry_seed=geometry_seeds[0],
        main_package=ref_main,
        rear_package=rear_ref,
        rear_outboard_package=ref_outboard,
        source="joint_reference:selected_v2m",
    )

    geometry_best_rows: list[JointGeometryBestRow] = []
    best_index_map: dict[
        tuple[str, str, str], tuple[int, int]
    ] = {}

    for geometry_seed, main_package, outboard_package, main_index, outboard_index in search_space:
        evaluator.evaluate(
            geometry_seed=geometry_seed,
            main_package=main_package,
            rear_package=rear_ref,
            rear_outboard_package=outboard_package,
            source="joint_promoted_grid",
        )
        best_index_map[(geometry_seed.label, main_package.key, outboard_package.key)] = (
            int(main_index),
            int(outboard_index),
        )

    for geometry_seed in geometry_seeds:
        subset = [cand for cand in evaluator.archive.candidates if cand.geometry_label == geometry_seed.label]
        feasible = [cand for cand in subset if cand.overall_optimizer_candidate_feasible]
        selected = (
            min(feasible, key=lambda cand: (cand.tube_mass_kg, cand.psi_u_all_m, -cand.candidate_margin_m))
            if feasible
            else min(subset, key=lambda cand: (cand.hard_violation_score, cand.tube_mass_kg))
        )
        main_index, outboard_index = best_index_map[
            (geometry_seed.label, selected.main_family_key, selected.rear_outboard_pkg_key)
        ]
        geometry_best_rows.append(
            JointGeometryBestRow(
                geometry_label=geometry_seed.label,
                geometry_choice=geometry_seed.choice,
                joint_choice_indices=build_joint_choice_indices(
                    geometry_choice=geometry_seed.choice,
                    main_family_index=main_index,
                    rear_outboard_index=outboard_index,
                ),
                main_family_key=selected.main_family_key,
                rear_outboard_pkg_key=selected.rear_outboard_pkg_key,
                tube_mass_kg=float(selected.tube_mass_kg),
                psi_u_all_mm=_mm(selected.psi_u_all_m),
                candidate_margin_mm=_mm(selected.candidate_margin_m),
                candidate_feasible=bool(selected.overall_optimizer_candidate_feasible),
            )
        )

    best_mass_candidate_feasible = evaluator.archive.best_mass_candidate_feasible
    best_margin_candidate_feasible = evaluator.archive.best_margin_candidate_feasible
    best_violation = evaluator.archive.best_violation
    if best_violation is None:  # pragma: no cover - impossible when reference exists
        raise RuntimeError("Joint geometry/material search produced no candidates.")
    selected_candidate = best_mass_candidate_feasible or best_violation

    top_candidate_feasible = tuple(
        sorted(
            (cand for cand in evaluator.archive.candidates if cand.overall_optimizer_candidate_feasible),
            key=lambda cand: (cand.tube_mass_kg, cand.psi_u_all_m, -cand.candidate_margin_m),
        )[:TOP_K]
    )

    return catalog, JointMaterialOutcome(
        success=bool(selected_candidate.overall_hard_feasible),
        feasible=bool(selected_candidate.overall_optimizer_candidate_feasible),
        message=str(selected_candidate.message),
        total_wall_time_s=float(perf_counter() - total_start),
        geometry_seed_count=len(geometry_seeds),
        evaluated_candidate_count=len(evaluator.archive.candidates),
        search_space_size=len(search_space),
        equivalent_analysis_calls=int(evaluator.equivalent_analysis_calls),
        production_analysis_calls=int(evaluator.production_analysis_calls),
        reference_candidate=reference_candidate,
        selected_candidate=selected_candidate,
        best_margin_candidate_feasible=best_margin_candidate_feasible,
        best_violation=best_violation,
        geometry_best_rows=tuple(geometry_best_rows),
        top_candidate_feasible=top_candidate_feasible,
    )


def build_report_text(
    *,
    config_path: Path,
    design_report: Path,
    v2m_summary_json: Path,
    v2m_reference: dict[str, object],
    geometry_seeds,
    catalog,
    cfg,
    materials_db: MaterialDB,
    outcome: JointMaterialOutcome,
) -> str:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    catalog_summary = catalog_to_summary_dict(catalog=catalog, cfg=cfg, materials_db=materials_db)
    selected = outcome.selected_candidate
    best_margin = outcome.best_margin_candidate_feasible

    main_packages = catalog_summary["main_spar_family"]["packages"]
    outboard_packages = catalog_summary["rear_outboard_reinforcement_pkg"]["packages"]
    main_index_map = {pkg["key"]: idx for idx, pkg in enumerate(main_packages)}
    outboard_index_map = {pkg["key"]: idx for idx, pkg in enumerate(outboard_packages)}
    selected_joint_choice = build_joint_choice_indices(
        geometry_choice=selected.geometry_choice,
        main_family_index=main_index_map[selected.main_family_key],
        rear_outboard_index=outboard_index_map[selected.rear_outboard_pkg_key],
    )

    lines: list[str] = []
    lines.append("=" * 120)
    lines.append("Direct Dual-Beam V2.m++ Joint Geometry + Promoted-Material Discrete Search")
    lines.append("=" * 120)
    lines.append(f"Generated                     : {timestamp}")
    lines.append(f"Config                        : {config_path}")
    lines.append(f"Design report                 : {design_report}")
    lines.append(f"Reference V2.m++ summary      : {v2m_summary_json}")
    lines.append(f"Geometry catalog profile      : {DEFAULT_CATALOG_PROFILE}")
    lines.append("")
    lines.append("Search strategy:")
    lines.append("  Promote only main_spar_family and rear_outboard_reinforcement_pkg to formal discrete axes.")
    lines.append("  Keep rear_spar_family fixed at rear_ref for this phase.")
    lines.append("  Search only the selected V2.m++ point plus a small nearby geometry neighborhood.")
    lines.append(
        f"  Search-space size            : {outcome.search_space_size} = {outcome.geometry_seed_count} geometry seeds x "
        f"{len(main_packages)} main families x {len(outboard_packages)} outboard packages"
    )
    lines.append("")
    lines.append("Promoted axes:")
    for axis_name in ("main_spar_family", "rear_outboard_reinforcement_pkg"):
        axis_summary = catalog_summary[axis_name]
        lines.append(
            f"  {axis_name}: integration={axis_summary['integration_mode']}  promotion={axis_summary['promotion_state']}"
        )
        for package in axis_summary["packages"]:
            lines.append(
                "    "
                f"{package['key']:24s} E={package['E_eff_pa'] / 1.0e9:7.2f} GPa  "
                f"G={package['G_eff_pa'] / 1.0e9:6.2f} GPa  "
                f"rho={package['density_eff_kgpm3']:7.1f}  "
                f"allow={package['allowable_eff_pa'] / 1.0e6:7.1f} MPa"
            )
            lines.append(f"      {package['description']}")
    lines.append("")
    lines.append("Geometry neighborhood:")
    for seed in geometry_seeds:
        lines.append(f"  {seed.label:22s} choice={seed.choice}  {seed.note}")
    lines.append("")
    lines.append("Reference pure-geometry V2.m++ selected point:")
    lines.append(f"  choice indices              : {v2m_reference['choice_indices']}")
    lines.append(f"  mass                        : {v2m_reference['tube_mass_kg']:11.3f} kg")
    lines.append(f"  raw main tip                : {_mm(v2m_reference['raw_main_tip_m']):11.3f} mm")
    lines.append(f"  raw rear tip                : {_mm(v2m_reference['raw_rear_tip_m']):11.3f} mm")
    lines.append(f"  raw max |UZ|                : {_mm(v2m_reference['raw_max_uz_m']):11.3f} mm")
    lines.append(f"  psi_u_all                   : {_mm(v2m_reference['psi_u_all_m']):11.3f} mm")
    lines.append(f"  candidate margin            : {_mm(v2m_reference['candidate_margin_m']):11.3f} mm")
    lines.append(
        f"  hard / candidate            : {v2m_reference['overall_hard_feasible']} / "
        f"{v2m_reference['overall_optimizer_candidate_feasible']}"
    )
    lines.append("")
    lines.append("Run summary:")
    lines.append(f"  success                     : {outcome.success}")
    lines.append(f"  feasible                    : {outcome.feasible}")
    lines.append(f"  total wall time             : {outcome.total_wall_time_s:.3f} s")
    lines.append(f"  evaluated candidates        : {outcome.evaluated_candidate_count}")
    lines.append(f"  equivalent analysis calls   : {outcome.equivalent_analysis_calls}")
    lines.append(f"  production analysis calls   : {outcome.production_analysis_calls}")
    lines.append("")
    lines.append("Selected joint candidate (mass-first among candidate-feasible points):")
    lines.append(f"  geometry seed               : {selected.geometry_label}")
    lines.append(f"  geometry choice             : {selected.geometry_choice}")
    lines.append(f"  joint choice indices        : {selected_joint_choice}")
    lines.append(f"  main_spar_family            : {selected.main_family_key}")
    lines.append(f"  rear_outboard_pkg           : {selected.rear_outboard_pkg_key}")
    lines.append(f"  mass                        : {selected.tube_mass_kg:11.3f} kg")
    lines.append(f"  total structural mass       : {selected.total_structural_mass_kg:11.3f} kg")
    lines.append(f"  raw main tip                : {_mm(selected.raw_main_tip_m):11.3f} mm")
    lines.append(f"  raw rear tip                : {_mm(selected.raw_rear_tip_m):11.3f} mm")
    lines.append(f"  raw max |UZ|                : {_mm(selected.raw_max_uz_m):11.3f} mm")
    lines.append(f"  raw max |UZ| location       : {selected.raw_max_location}")
    lines.append(f"  psi_u_all                   : {_mm(selected.psi_u_all_m):11.3f} mm")
    lines.append(f"  candidate margin            : {_mm(selected.candidate_margin_m):11.3f} mm")
    lines.append(f"  hard / candidate            : {selected.overall_hard_feasible} / {selected.overall_optimizer_candidate_feasible}")
    lines.append("")
    if best_margin is not None:
        lines.append("Best candidate-feasible by candidate margin:")
        lines.append(f"  geometry seed               : {best_margin.geometry_label}")
        lines.append(f"  geometry choice             : {best_margin.geometry_choice}")
        lines.append(f"  main_spar_family            : {best_margin.main_family_key}")
        lines.append(f"  rear_outboard_pkg           : {best_margin.rear_outboard_pkg_key}")
        lines.append(f"  mass                        : {best_margin.tube_mass_kg:11.3f} kg")
        lines.append(f"  psi_u_all                   : {_mm(best_margin.psi_u_all_m):11.3f} mm")
        lines.append(f"  candidate margin            : {_mm(best_margin.candidate_margin_m):11.3f} mm")
        lines.append("")
    lines.append("Best promoted-material combination by geometry seed:")
    lines.append("  geometry                 joint choice                  mass[kg]   psi[mm]   margin[mm]   cand")
    for row in outcome.geometry_best_rows:
        combo = f"{row.main_family_key}/{row.rear_outboard_pkg_key}"
        lines.append(
            f"  {row.geometry_label:22s} {combo:27s} {row.tube_mass_kg:8.3f} "
            f"{row.psi_u_all_mm:9.3f} {row.candidate_margin_mm:11.3f} {str(row.candidate_feasible):>5s}"
        )
    lines.append("")
    lines.append("Delta (selected joint candidate - pure-geometry V2.m++ selected point):")
    lines.append(
        f"  mass delta                   {selected.tube_mass_kg - float(v2m_reference['tube_mass_kg']):+11.3f} kg"
    )
    lines.append(
        f"  psi_u_all delta              {_signed_mm_delta(selected.psi_u_all_m - float(v2m_reference['psi_u_all_m'])):+11.3f} mm"
    )
    lines.append(
        f"  candidate margin delta       "
        f"{_signed_mm_delta(selected.candidate_margin_m - float(v2m_reference['candidate_margin_m'] or 0.0)):+11.3f} mm"
    )
    lines.append(
        f"  wall-time delta              {outcome.total_wall_time_s - float(v2m_reference['total_wall_time_s']):+11.3f} s"
    )
    return "\n".join(lines) + "\n"


def build_summary_json(
    *,
    config_path: Path,
    design_report: Path,
    v2m_summary_json: Path,
    v2m_reference: dict[str, object],
    geometry_seeds,
    catalog,
    cfg,
    materials_db: MaterialDB,
    outcome: JointMaterialOutcome,
) -> dict[str, object]:
    catalog_summary = catalog_to_summary_dict(catalog=catalog, cfg=cfg, materials_db=materials_db)
    main_packages = catalog_summary["main_spar_family"]["packages"]
    outboard_packages = catalog_summary["rear_outboard_reinforcement_pkg"]["packages"]
    main_index_map = {pkg["key"]: idx for idx, pkg in enumerate(main_packages)}
    outboard_index_map = {pkg["key"]: idx for idx, pkg in enumerate(outboard_packages)}
    selected = outcome.selected_candidate
    selected_joint_choice = build_joint_choice_indices(
        geometry_choice=selected.geometry_choice,
        main_family_index=main_index_map[selected.main_family_key],
        rear_outboard_index=outboard_index_map[selected.rear_outboard_pkg_key],
    )

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "config": str(config_path),
        "design_report": str(design_report),
        "v2m_summary_json": str(v2m_summary_json),
        "search_strategy": {
            "geometry_seed_strategy": "selected_plus_nearby_v2m_neighbors",
            "geometry_seed_count": len(geometry_seeds),
            "promoted_axes": ["main_spar_family", "rear_outboard_reinforcement_pkg"],
            "fixed_axes": {"rear_spar_family": "rear_ref"},
            "search_space_size": outcome.search_space_size,
        },
        "geometry_seeds": [
            {
                "label": seed.label,
                "choice": list(seed.choice),
                "note": seed.note,
            }
            for seed in geometry_seeds
        ],
        "promoted_catalog": {
            "main_spar_family": catalog_summary["main_spar_family"],
            "rear_outboard_reinforcement_pkg": catalog_summary["rear_outboard_reinforcement_pkg"],
        },
        "reference_v2m_selected": v2m_reference,
        "outcome": {
            "success": outcome.success,
            "feasible": outcome.feasible,
            "message": outcome.message,
            "total_wall_time_s": outcome.total_wall_time_s,
            "evaluated_candidate_count": outcome.evaluated_candidate_count,
            "equivalent_analysis_calls": outcome.equivalent_analysis_calls,
            "production_analysis_calls": outcome.production_analysis_calls,
            "reference_candidate": candidate_to_summary_dict(outcome.reference_candidate),
            "selected_candidate": {
                **candidate_to_summary_dict(outcome.selected_candidate),
                "joint_choice_indices": list(selected_joint_choice),
            },
            "best_margin_candidate_feasible": candidate_to_summary_dict(
                outcome.best_margin_candidate_feasible
            ),
            "best_violation": candidate_to_summary_dict(outcome.best_violation),
            "geometry_best_rows": [asdict(row) for row in outcome.geometry_best_rows],
            "top_candidate_feasible": [candidate_to_summary_dict(candidate) for candidate in outcome.top_candidate_feasible],
        },
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run reduced joint geometry + promoted-material discrete search on top of V2.m++."
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
    )
    parser.add_argument(
        "--design-report",
        default=str(
            Path(__file__).resolve().parent.parent
            / "output"
            / "blackcat_004_dual_beam_production_check"
            / "ansys"
            / "crossval_report.txt"
        ),
    )
    parser.add_argument(
        "--v2m-summary-json",
        default=str(DEFAULT_V2M_SUMMARY_JSON),
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()
    design_report = Path(args.design_report).expanduser().resolve()
    v2m_summary_json = Path(args.v2m_summary_json).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config(config_path)
    specimen_metrics = parse_baseline_metrics(design_report)
    cfg.solver.n_beam_nodes = int(specimen_metrics.nodes_per_spar)
    aircraft = Aircraft.from_config(cfg)
    materials_db = MaterialDB()
    baseline_result = build_specimen_result_from_crossval_report(design_report)
    v2m_reference = _load_v2m_reference(v2m_summary_json)

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
    selected_choice = _load_v2m_selected_choice(v2m_summary_json)
    geometry_seeds = build_geometry_seeds(
        selected_choice=selected_choice,
        baseline=baseline_design,
        map_config=map_config,
    )

    _, mapped_loads = _select_cruise_loads(cfg, aircraft)
    design_case = cfg.structural_load_cases()[0]
    export_loads = LoadMapper.apply_load_factor(mapped_loads, design_case.aero_scale)

    catalog, outcome = run_joint_material_search(
        cfg=cfg,
        aircraft=aircraft,
        materials_db=materials_db,
        mapped_loads=mapped_loads,
        export_loads=export_loads,
        map_config=map_config,
        geometry_seeds=geometry_seeds,
    )

    report_path = output_dir / "direct_dual_beam_v2m_joint_material_report.txt"
    report_path.write_text(
        build_report_text(
            config_path=config_path,
            design_report=design_report,
            v2m_summary_json=v2m_summary_json,
            v2m_reference=v2m_reference,
            geometry_seeds=geometry_seeds,
            catalog=catalog,
            cfg=cfg,
            materials_db=materials_db,
            outcome=outcome,
        ),
        encoding="utf-8",
    )

    json_path = output_dir / "direct_dual_beam_v2m_joint_material_summary.json"
    json_path.write_text(
        json.dumps(
            build_summary_json(
                config_path=config_path,
                design_report=design_report,
                v2m_summary_json=v2m_summary_json,
                v2m_reference=v2m_reference,
                geometry_seeds=geometry_seeds,
                catalog=catalog,
                cfg=cfg,
                materials_db=materials_db,
                outcome=outcome,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    selected = outcome.selected_candidate
    print("Direct dual-beam V2.m++ joint geometry + material search complete.")
    print(f"  Report              : {report_path}")
    print(f"  Summary JSON        : {json_path}")
    print(f"  Success / feasible  : {outcome.success} / {outcome.feasible}")
    print(f"  Total wall time     : {outcome.total_wall_time_s:.3f} s")
    print(f"  Search-space size   : {outcome.search_space_size}")
    print(f"  Mass                : {selected.tube_mass_kg:.3f} kg")
    print(f"  psi_u_all           : {_mm(selected.psi_u_all_m):.3f} mm")
    print(f"  Material choice     : {selected.main_family_key} / {selected.rear_outboard_pkg_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
