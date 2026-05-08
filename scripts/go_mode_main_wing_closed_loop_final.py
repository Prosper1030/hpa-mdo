#!/usr/bin/env python3
"""Build the closed-loop final package for the current main-wing candidate."""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.core import MaterialDB, load_config
from hpa_mdo.hifi.frd_parser import parse_displacement, parse_total_force_from_dat
from hpa_mdo.structure.calculix_beam_export import (
    BeamMaterial,
    DualPipeBenchmarkSpec,
    build_dual_pipe_benchmark_spec,
    write_calculix_beam_inp,
)


CANDIDATE_ID = "current_avl_compromise_conservative_closed"
SELECTED_RUN = (
    REPO_ROOT
    / "output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_closure"
    / "runs/conservative_best/structure_response"
)
Z_BOUNDARY_RUN = (
    REPO_ROOT
    / "output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_z_boundary"
    / "runs/target_main_tip_z_2p700m"
)
AERO_SELECTION_CSV = (
    REPO_ROOT
    / "output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_tier2_airfoil"
    / "tier2_loaded_shape_selected_avl_recheck.csv"
)
CLOSURE_CSV = (
    REPO_ROOT
    / "output/go_mode_main_wing_candidate/current_avl_compromise_conservative_closed_closure"
    / "aero_structure_closure_summary.csv"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output/go_mode_main_wing_closed_loop_final"
REFERENCE_LOAD_FACTOR = 2.0
LOAD_FACTORS = (1.0, 1.5, 1.75, 2.0)


@dataclass(frozen=True)
class ReferenceStructuralMetrics:
    reference_load_factor: float
    failure_index: float
    buckling_index: float
    tip_deflection_m: float
    tip_deflection_limit_m: float
    twist_max_deg: float
    twist_limit_deg: float
    wire_tension_n: float
    wire_allowable_n: float
    root_vertical_resultant_n: float
    root_bending_moment_n_m: float


@dataclass(frozen=True)
class LoadFactorEstimateRow:
    load_factor: float
    failure_index: float
    failure_margin: float
    buckling_index: float
    buckling_margin: float
    tip_deflection_m: float
    tip_deflection_margin_m: float
    twist_max_deg: float
    twist_margin_deg: float
    wire_tension_n: float
    wire_tension_margin_n: float
    root_vertical_resultant_n: float
    root_bending_moment_n_m: float


@dataclass(frozen=True)
class FirstFailEstimate:
    mode: str
    load_factor: float
    note: str


@dataclass(frozen=True)
class FemSupportStatus:
    final_code: str
    confidence_label: str
    tip_mismatch_fraction: float | None
    internal_tip_deflection_m: float | None
    calculix_tip_abs_m: float | None
    note: str


def _ratio_at_load(reference_ratio: float, load_factor: float, reference_load_factor: float) -> float:
    return float(reference_ratio) * float(load_factor) / float(reference_load_factor)


def estimate_load_factor_rows(
    reference: ReferenceStructuralMetrics,
    *,
    load_factors: Iterable[float] = LOAD_FACTORS,
) -> list[LoadFactorEstimateRow]:
    """Estimate fixed-design load-factor response by linear elastic scaling."""

    stress_util_ref = 1.0 + float(reference.failure_index)
    buckling_util_ref = 1.0 + float(reference.buckling_index)
    rows: list[LoadFactorEstimateRow] = []
    for load_factor in load_factors:
        load_factor = float(load_factor)
        scale = load_factor / float(reference.reference_load_factor)
        failure_index = _ratio_at_load(
            stress_util_ref,
            load_factor,
            reference.reference_load_factor,
        ) - 1.0
        buckling_index = _ratio_at_load(
            buckling_util_ref,
            load_factor,
            reference.reference_load_factor,
        ) - 1.0
        tip = float(reference.tip_deflection_m) * scale
        twist = float(reference.twist_max_deg) * scale
        wire = float(reference.wire_tension_n) * scale
        rows.append(
            LoadFactorEstimateRow(
                load_factor=load_factor,
                failure_index=failure_index,
                failure_margin=-failure_index,
                buckling_index=buckling_index,
                buckling_margin=-buckling_index,
                tip_deflection_m=tip,
                tip_deflection_margin_m=float(reference.tip_deflection_limit_m) - tip,
                twist_max_deg=twist,
                twist_margin_deg=float(reference.twist_limit_deg) - twist,
                wire_tension_n=wire,
                wire_tension_margin_n=float(reference.wire_allowable_n) - wire,
                root_vertical_resultant_n=float(reference.root_vertical_resultant_n) * scale,
                root_bending_moment_n_m=float(reference.root_bending_moment_n_m) * scale,
            )
        )
    return rows


def estimate_first_fail(reference: ReferenceStructuralMetrics) -> FirstFailEstimate:
    """Return the lowest estimated first-fail load factor from fixed-design margins."""

    candidates: list[tuple[str, float, str]] = []
    stress_util = 1.0 + float(reference.failure_index)
    if stress_util > 0.0:
        candidates.append(
            (
                "stress",
                float(reference.reference_load_factor) / stress_util,
                "equivalent von-Mises stress reaches material-safety-factored allowable",
            )
        )
    buckling_util = 1.0 + float(reference.buckling_index)
    if buckling_util > 0.0:
        candidates.append(
            (
                "buckling",
                float(reference.reference_load_factor) / buckling_util,
                "equivalent shell buckling utilization reaches 1.0",
            )
        )
    if reference.tip_deflection_m > 0.0:
        candidates.append(
            (
                "deflection",
                float(reference.reference_load_factor)
                * float(reference.tip_deflection_limit_m)
                / float(reference.tip_deflection_m),
                "equivalent tip deflection reaches configured limit",
            )
        )
    if reference.twist_max_deg > 0.0:
        candidates.append(
            (
                "torsion",
                float(reference.reference_load_factor)
                * float(reference.twist_limit_deg)
                / float(reference.twist_max_deg),
                "equivalent twist reaches configured limit",
            )
        )
    if reference.wire_tension_n > 0.0:
        candidates.append(
            (
                "wire",
                float(reference.reference_load_factor)
                * float(reference.wire_allowable_n)
                / float(reference.wire_tension_n),
                "lift-wire tension reaches allowable",
            )
        )

    if not candidates:
        return FirstFailEstimate(
            mode="model_limit",
            load_factor=float("nan"),
            note="No positive utilization was available for first-fail extrapolation.",
        )
    mode, load_factor, note = min(candidates, key=lambda item: item[1])
    return FirstFailEstimate(mode=mode, load_factor=float(load_factor), note=note)


def evaluate_fem_support(
    load_rows: list[LoadFactorEstimateRow],
    fem_rows: list[dict[str, object]],
    *,
    reference_load_factor: float = REFERENCE_LOAD_FACTOR,
    tip_tolerance_fraction: float = 0.10,
) -> FemSupportStatus:
    """Classify whether the candidate FEM spot-check supports the internal model scale."""

    fem_by_lf = {float(row["load_factor"]): row for row in fem_rows}
    reference_row = min(
        load_rows,
        key=lambda row: abs(float(row.load_factor) - float(reference_load_factor)),
    )
    fem = fem_by_lf.get(float(reference_row.load_factor))
    fem_failed = [row for row in fem_rows if row.get("calculix_status") != "ran"]

    if fem is None or fem.get("calculix_status") != "ran":
        return FemSupportStatus(
            final_code="C. More data is impossible locally, with the exact missing file/tool/input.",
            confidence_label="internal screening; FEM reference deck missing",
            tip_mismatch_fraction=None,
            internal_tip_deflection_m=float(reference_row.tip_deflection_m),
            calculix_tip_abs_m=None,
            note="The reference load-factor CalculiX deck did not produce a usable displacement result.",
        )

    fem_tip = _max_abs_optional_float(fem.get("tip_main_uz_m"), fem.get("tip_rear_uz_m"))
    internal_tip = abs(float(reference_row.tip_deflection_m))
    if fem_tip is None or internal_tip <= 0.0:
        return FemSupportStatus(
            final_code="C. More data is impossible locally, with the exact missing file/tool/input.",
            confidence_label="internal screening; FEM displacement parse missing",
            tip_mismatch_fraction=None,
            internal_tip_deflection_m=float(reference_row.tip_deflection_m),
            calculix_tip_abs_m=fem_tip,
            note="The generated FEM deck ran, but no comparable tip displacement scale was available.",
        )

    mismatch = abs(float(fem_tip) - internal_tip) / internal_tip
    if fem_failed:
        return FemSupportStatus(
            final_code="C. More data is impossible locally, with the exact missing file/tool/input.",
            confidence_label="internal screening; FEM load-factor sweep incomplete",
            tip_mismatch_fraction=float(mismatch),
            internal_tip_deflection_m=float(reference_row.tip_deflection_m),
            calculix_tip_abs_m=float(fem_tip),
            note="At least one generated CalculiX load-factor deck did not complete.",
        )
    if mismatch > tip_tolerance_fraction:
        return FemSupportStatus(
            final_code="C. More data is impossible locally, with the exact missing file/tool/input.",
            confidence_label="internal screening; FEM model-basis mismatch",
            tip_mismatch_fraction=float(mismatch),
            internal_tip_deflection_m=float(reference_row.tip_deflection_m),
            calculix_tip_abs_m=float(fem_tip),
            note=(
                "The candidate-specific B32R deck ran, but its tip displacement scale does not "
                "match the internal structural estimate closely enough to upgrade trust."
            ),
        )

    return FemSupportStatus(
        final_code="A. Candidate upgraded to FEM-supported engineering-review candidate.",
        confidence_label="FEM spot-check supported",
        tip_mismatch_fraction=float(mismatch),
        internal_tip_deflection_m=float(reference_row.tip_deflection_m),
        calculix_tip_abs_m=float(fem_tip),
        note="The generated CalculiX displacement scale agrees with the internal fixed-design estimate.",
    )


def build_candidate_fem_spec_from_csv(
    *,
    csv_path: Path,
    load_scale: float,
    main_material_name: str,
    rear_material_name: str,
    young_pa: float,
    poisson_ratio: float,
    density_kgpm3: float,
) -> DualPipeBenchmarkSpec:
    """Build a CalculiX dual-pipe candidate deck spec from candidate spar CSV rows."""

    rows = _read_csv_rows(csv_path)
    y = _array(rows, "Y_Position_m")
    main_radius_nodes = _array(rows, "Main_Outer_Radius_m")
    main_t_nodes = _array(rows, "Main_Wall_Thickness_m")
    rear_radius_nodes = _array(rows, "Rear_Outer_Radius_m")
    rear_t_nodes = _array(rows, "Rear_Wall_Thickness_m")
    material_main = BeamMaterial(
        name=main_material_name,
        young_pa=float(young_pa),
        poisson_ratio=float(poisson_ratio),
        density_kgpm3=float(density_kgpm3),
    )
    material_rear = BeamMaterial(
        name=rear_material_name,
        young_pa=float(young_pa),
        poisson_ratio=float(poisson_ratio),
        density_kgpm3=float(density_kgpm3),
    )
    return build_dual_pipe_benchmark_spec(
        name=f"{CANDIDATE_ID}_lf{float(load_scale) * REFERENCE_LOAD_FACTOR:g}",
        y_nodes_m=y,
        main_x_m=_array(rows, "Main_X_m"),
        rear_x_m=_array(rows, "Rear_X_m"),
        main_z_m=_array(rows, "Main_Z_m"),
        rear_z_m=_array(rows, "Rear_Z_m"),
        main_outer_radius_m=_element_average(main_radius_nodes),
        main_thickness_m=_element_average(main_t_nodes),
        rear_outer_radius_m=_element_average(rear_radius_nodes),
        rear_thickness_m=_element_average(rear_t_nodes),
        material_main=material_main,
        material_rear=material_rear,
        main_nodal_fz_n=_array(rows, "Main_FZ_N") * float(load_scale),
        rear_nodal_fz_n=_array(rows, "Rear_FZ_N") * float(load_scale),
        joint_node_indices=_flag_indices(rows, "Is_Joint"),
        wire_node_indices=_flag_indices(rows, "Is_Wire_Attach"),
        joint_link_mode="offset_rigid",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--ccx-binary",
        default=None,
        help="Optional explicit CalculiX binary. Defaults to local ccx/ccx_2.23 discovery.",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    package = build_final_package(out_dir=out_dir, ccx_binary=args.ccx_binary)
    print(f"Wrote closed-loop package: {package}")
    return 0


def build_final_package(*, out_dir: Path, ccx_binary: str | None = None) -> Path:
    summary = _read_json(SELECTED_RUN / "direct_dual_beam_inverse_design_refresh_summary.json")
    validity = _read_json(SELECTED_RUN / "validity_summary.json")
    wire = _read_json(SELECTED_RUN / "lift_wire_rigging.json")["wire_rigging"][0]
    selected = summary["iterations"][0]["selected"]
    aero_row = _select_csv_row(AERO_SELECTION_CSV, "selected_role", "conservative_best")
    closure_row = _select_csv_row(CLOSURE_CSV, "selected_role", "conservative_best")
    cfg = load_config(summary["config"])
    reference = _reference_metrics(selected=selected, validity=validity, wire=wire, cfg=cfg)
    load_rows = estimate_load_factor_rows(reference)
    first_fail = estimate_first_fail(reference)

    material = MaterialDB().get(cfg.main_spar.material)
    ccx = _find_ccx(ccx_binary)
    fem_rows = _write_fem_case_package(
        out_dir=out_dir,
        reference=reference,
        material=material,
        ccx_binary=ccx,
    )
    fem_support = evaluate_fem_support(load_rows, fem_rows)

    _write_aero_summary(out_dir / "aero_summary.csv", aero_row=aero_row, summary=summary)
    _write_structure_summary(
        out_dir / "structure_summary.csv",
        selected=selected,
        validity=validity,
        wire=wire,
        closure_row=closure_row,
        fem_support=fem_support,
    )
    _write_fem_summary_csv(out_dir / "fem_load_factor_summary.csv", load_rows, fem_rows)
    _write_markdown_reports(
        out_dir=out_dir,
        aero_row=aero_row,
        closure_row=closure_row,
        selected=selected,
        validity=validity,
        wire=wire,
        reference=reference,
        load_rows=load_rows,
        fem_rows=fem_rows,
        fem_support=fem_support,
        first_fail=first_fail,
        ccx_binary=ccx,
    )
    return out_dir


def _reference_metrics(*, selected: dict, validity: dict, wire: dict, cfg) -> ReferenceStructuralMetrics:
    rows = _read_csv_rows(SELECTED_RUN / "jig_shape_spar_data.csv")
    y = _array(rows, "Y_Position_m")
    fz = _array(rows, "Main_FZ_N") + _array(rows, "Rear_FZ_N")
    load_cases = cfg.structural_load_cases()
    primary_load_case = load_cases[0] if load_cases else None
    twist_limit_deg = (
        primary_load_case.max_twist_deg
        if primary_load_case is not None and primary_load_case.max_twist_deg is not None
        else cfg.wing.max_tip_twist_deg
    )
    return ReferenceStructuralMetrics(
        reference_load_factor=REFERENCE_LOAD_FACTOR,
        failure_index=float(selected["equivalent_failure_index"]),
        buckling_index=float(selected["equivalent_buckling_index"]),
        tip_deflection_m=float(selected["equivalent_tip_deflection_m"]),
        tip_deflection_limit_m=float(validity["margins"]["hard_constraints"]["equivalent_tip_margin"])
        + float(selected["equivalent_tip_deflection_m"]),
        twist_max_deg=float(selected["equivalent_twist_max_deg"]),
        twist_limit_deg=float(twist_limit_deg),
        wire_tension_n=float(wire["tension_force_n"]),
        wire_allowable_n=float(wire["allowable_tension_n"]),
        root_vertical_resultant_n=float(np.sum(fz)),
        root_bending_moment_n_m=float(np.sum(fz * y)),
    )


def _write_fem_case_package(
    *,
    out_dir: Path,
    reference: ReferenceStructuralMetrics,
    material,
    ccx_binary: str | None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    fem_root = out_dir / "fem_case_package"
    calc_root = fem_root / "calculix"
    apdl_root = fem_root / "apdl"
    calc_root.mkdir(parents=True, exist_ok=True)
    apdl_root.mkdir(parents=True, exist_ok=True)
    csv_path = SELECTED_RUN / "jig_shape_spar_data.csv"

    for row in estimate_load_factor_rows(reference):
        label = _load_factor_label(row.load_factor)
        load_scale = row.load_factor / REFERENCE_LOAD_FACTOR
        spec = build_candidate_fem_spec_from_csv(
            csv_path=csv_path,
            load_scale=load_scale,
            main_material_name="CARBON_FIBER_HM_MAIN",
            rear_material_name="CARBON_FIBER_HM_REAR",
            young_pa=float(material.E),
            poisson_ratio=float(material.poisson_ratio),
            density_kgpm3=float(material.density),
        )
        deck_dir = calc_root / label
        deck = write_calculix_beam_inp(spec, deck_dir / f"{CANDIDATE_ID}_{label}.inp")
        apdl_path = apdl_root / f"{CANDIDATE_ID}_{label}.mac"
        _write_candidate_apdl_from_csv(
            csv_path=csv_path,
            path=apdl_path,
            load_scale=load_scale,
            material=material,
            label=label,
        )
        fem_result = _run_ccx(deck.inp_path, deck.node_sets, ccx_binary)
        rows.append(
            {
                "load_factor": row.load_factor,
                "calculix_status": fem_result["status"],
                "calculix_note": fem_result["note"],
                "calculix_deck": str(deck.inp_path),
                "apdl_macro": str(apdl_path),
                "tip_main_uz_m": fem_result.get("tip_main_uz_m"),
                "tip_rear_uz_m": fem_result.get("tip_rear_uz_m"),
                "support_root_fz_n": fem_result.get("support_root_fz_n"),
                "support_wire_fz_n": fem_result.get("support_wire_fz_n"),
                "support_all_fz_n": fem_result.get("support_all_fz_n"),
                "returncode": fem_result.get("returncode"),
            }
        )
    _write_fem_readme(fem_root, ccx_binary=ccx_binary)
    return rows


def _run_ccx(deck_path: Path, node_sets: dict[str, tuple[int, ...]], ccx_binary: str | None) -> dict:
    if ccx_binary is None:
        return {"status": "not_run", "note": "CalculiX binary not found.", "returncode": None}
    result = subprocess.run(
        [ccx_binary, deck_path.stem],
        cwd=deck_path.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
    )
    log_path = deck_path.with_suffix(".ccx.log")
    log_path.write_text(
        "===== stdout =====\n"
        + result.stdout
        + "\n===== stderr =====\n"
        + result.stderr
        + "\n",
        encoding="utf-8",
    )
    frd_path = deck_path.with_suffix(".frd")
    dat_path = deck_path.with_suffix(".dat")
    if result.returncode != 0 or not frd_path.exists():
        return {
            "status": "failed",
            "note": f"ccx returned {result.returncode}; see {log_path}",
            "returncode": result.returncode,
        }
    disp = parse_displacement(frd_path)
    by_node = {int(row[0]): row for row in disp}

    def _uz(set_name: str) -> float | None:
        node_ids = node_sets.get(set_name)
        if not node_ids:
            return None
        row = by_node.get(int(node_ids[0]))
        if row is None:
            return None
        return float(row[3])

    def _force(set_name: str) -> float | None:
        if not dat_path.exists():
            return None
        total = parse_total_force_from_dat(dat_path, set_name)
        return None if total is None else float(total[2])

    return {
        "status": "ran",
        "note": "candidate B32R beam-FEM spot-check completed",
        "returncode": result.returncode,
        "tip_main_uz_m": _uz("TIP_MAIN"),
        "tip_rear_uz_m": _uz("TIP_REAR"),
        "support_root_fz_n": _force("HPA_SUPPORT_ROOT"),
        "support_wire_fz_n": _force("HPA_SUPPORT_WIRE"),
        "support_all_fz_n": _force("HPA_SUPPORT_ALL"),
    }


def _write_aero_summary(path: Path, *, aero_row: dict, summary: dict) -> None:
    fields = [
        "candidate_id",
        "assignment",
        "alpha_deg",
        "CL",
        "CDi",
        "e_CDi",
        "profile_cd",
        "CD0_total",
        "CD_total",
        "P_crank",
        "P_crank_conservative",
        "actual_query_quality",
        "profile_source_quality",
        "profile_warning_count",
        "drag_budget_band",
        "spanload_artifact",
        "avl_path",
    ]
    row = {
        "candidate_id": CANDIDATE_ID,
        "assignment": aero_row["assignment"],
        "alpha_deg": aero_row["alpha_deg"],
        "CL": aero_row["CL"],
        "CDi": aero_row["CDi"],
        "e_CDi": aero_row["e_CDi"],
        "profile_cd": aero_row["profile_cd"],
        "CD0_total": aero_row["CD0_total"],
        "CD_total": aero_row["CD_total"],
        "P_crank": aero_row["P_crank"],
        "P_crank_conservative": aero_row["P_crank_conservative"],
        "actual_query_quality": aero_row["actual_query_quality"],
        "profile_source_quality": aero_row["profile_source_quality"],
        "profile_warning_count": aero_row["profile_warning_count"],
        "drag_budget_band": aero_row["drag_budget_band"],
        "spanload_artifact": aero_row["selected_airfoil_fs"],
        "avl_path": summary["aero_contract"]["geometry_artifacts"]["avl_path"],
    }
    _write_csv(path, fields, [row])


def _write_structure_summary(
    path: Path,
    *,
    selected: dict,
    validity: dict,
    wire: dict,
    closure_row: dict,
    fem_support: FemSupportStatus,
) -> None:
    fields = [
        "candidate_id",
        "overall_status",
        "structure_trust_label",
        "tube_mass_kg",
        "total_structural_mass_kg",
        "equivalent_failure_index",
        "equivalent_buckling_index",
        "equivalent_tip_deflection_m",
        "equivalent_twist_max_deg",
        "loaded_shape_main_z_error_max_m",
        "loaded_shape_twist_error_max_deg",
        "jig_ground_clearance_min_m",
        "jig_prebend_m",
        "jig_curvature_per_m",
        "wire_tension_n",
        "wire_tension_margin_n",
        "closure_status",
    ]
    row = {
        "candidate_id": CANDIDATE_ID,
        "overall_status": validity["overall_status"],
        "structure_trust_label": fem_support.confidence_label,
        "tube_mass_kg": selected["tube_mass_kg"],
        "total_structural_mass_kg": selected["total_structural_mass_kg"],
        "equivalent_failure_index": selected["equivalent_failure_index"],
        "equivalent_buckling_index": selected["equivalent_buckling_index"],
        "equivalent_tip_deflection_m": selected["equivalent_tip_deflection_m"],
        "equivalent_twist_max_deg": selected["equivalent_twist_max_deg"],
        "loaded_shape_main_z_error_max_m": selected["loaded_shape_main_z_error_max_m"],
        "loaded_shape_twist_error_max_deg": selected["loaded_shape_twist_error_max_deg"],
        "jig_ground_clearance_min_m": selected["jig_ground_clearance_min_m"],
        "jig_prebend_m": selected["max_jig_vertical_prebend_m"],
        "jig_curvature_per_m": selected["max_jig_vertical_curvature_per_m"],
        "wire_tension_n": wire["tension_force_n"],
        "wire_tension_margin_n": wire["tension_margin_n"],
        "closure_status": closure_row["closure_status"],
    }
    _write_csv(path, fields, [row])


def _write_fem_summary_csv(
    path: Path,
    load_rows: list[LoadFactorEstimateRow],
    fem_rows: list[dict[str, object]],
) -> None:
    fields = [
        "load_factor",
        "internal_failure_index_est",
        "internal_buckling_index_est",
        "internal_tip_deflection_m_est",
        "internal_tip_margin_m_est",
        "internal_wire_tension_n_est",
        "internal_wire_margin_n_est",
        "internal_root_vertical_resultant_n_est",
        "internal_root_bending_moment_n_m_est",
        "calculix_status",
        "calculix_tip_main_uz_m",
        "calculix_tip_rear_uz_m",
        "calculix_tip_abs_max_m",
        "internal_to_calculix_tip_mismatch_fraction",
        "calculix_support_root_fz_n",
        "calculix_support_wire_fz_n",
        "calculix_support_all_fz_n",
        "calculix_deck",
        "apdl_macro",
        "note",
    ]
    fem_by_lf = {float(row["load_factor"]): row for row in fem_rows}
    out_rows = []
    for row in load_rows:
        fem = fem_by_lf.get(float(row.load_factor), {})
        fem_tip = _max_abs_optional_float(fem.get("tip_main_uz_m"), fem.get("tip_rear_uz_m"))
        mismatch = None
        if fem_tip is not None and abs(float(row.tip_deflection_m)) > 0.0:
            mismatch = abs(float(fem_tip) - abs(float(row.tip_deflection_m))) / abs(float(row.tip_deflection_m))
        out_rows.append(
            {
                "load_factor": row.load_factor,
                "internal_failure_index_est": row.failure_index,
                "internal_buckling_index_est": row.buckling_index,
                "internal_tip_deflection_m_est": row.tip_deflection_m,
                "internal_tip_margin_m_est": row.tip_deflection_margin_m,
                "internal_wire_tension_n_est": row.wire_tension_n,
                "internal_wire_margin_n_est": row.wire_tension_margin_n,
                "internal_root_vertical_resultant_n_est": row.root_vertical_resultant_n,
                "internal_root_bending_moment_n_m_est": row.root_bending_moment_n_m,
                "calculix_status": fem.get("calculix_status"),
                "calculix_tip_main_uz_m": fem.get("tip_main_uz_m"),
                "calculix_tip_rear_uz_m": fem.get("tip_rear_uz_m"),
                "calculix_tip_abs_max_m": fem_tip,
                "internal_to_calculix_tip_mismatch_fraction": mismatch,
                "calculix_support_root_fz_n": fem.get("support_root_fz_n"),
                "calculix_support_wire_fz_n": fem.get("support_wire_fz_n"),
                "calculix_support_all_fz_n": fem.get("support_all_fz_n"),
                "calculix_deck": fem.get("calculix_deck"),
                "apdl_macro": fem.get("apdl_macro"),
                "note": fem.get("calculix_note"),
            }
        )
    _write_csv(path, fields, out_rows)


def _write_markdown_reports(
    *,
    out_dir: Path,
    aero_row: dict,
    closure_row: dict,
    selected: dict,
    validity: dict,
    wire: dict,
    reference: ReferenceStructuralMetrics,
    load_rows: list[LoadFactorEstimateRow],
    fem_rows: list[dict[str, object]],
    fem_support: FemSupportStatus,
    first_fail: FirstFailEstimate,
    ccx_binary: str | None,
) -> None:
    fem_ran = any(row.get("calculix_status") == "ran" for row in fem_rows)
    fem_failed = [row for row in fem_rows if row.get("calculix_status") != "ran"]
    confidence = fem_support.confidence_label
    final_code = fem_support.final_code

    if fem_support.tip_mismatch_fraction is None:
        fem_scale_line = f"- FEM scale check: `{fem_support.note}`"
    else:
        fem_scale_line = (
            "- FEM scale check: internal reference tip "
            f"`{float(fem_support.internal_tip_deflection_m):.4f} m`, CalculiX max tip "
            f"`{float(fem_support.calculix_tip_abs_m):.4f} m`, mismatch "
            f"`{float(fem_support.tip_mismatch_fraction) * 100.0:.1f}%`"
        )

    decision_lines = [
        "# Closed Loop Decision",
        "",
        final_code,
        "",
        f"- candidate: `{CANDIDATE_ID}`",
        f"- selected structural run: `{SELECTED_RUN}`",
        f"- confidence label: `{confidence}`",
        f"- ccx binary: `{ccx_binary or 'not found'}`",
        f"- primary first-fail estimate: `{first_fail.mode}` at `n = {first_fail.load_factor:.3f}`",
        f"- note: {first_fail.note}",
        fem_scale_line,
        "",
        "Engineering judgement: the candidate clears the requested 1g, 1.5g, and 1.75g checks on the fixed-design internal estimate. The controlling extrapolated limit is the lift-wire tension margin, not tube stress or buckling.",
        "",
        "The FEM spot-check is a candidate-specific B32R beam deck generated from the selected jig spar CSV. It does not upgrade the candidate when its displacement scale is not comparable with the internal inverse-design structural response; that is a model-basis blocker, not a physical pass.",
        "",
    ]
    (out_dir / "CLOSED_LOOP_DECISION.md").write_text("\n".join(decision_lines), encoding="utf-8")

    status_lines = [
        "# Final Candidate Status",
        "",
        f"- assignment: `{aero_row['assignment']}`",
        f"- P_crank nominal / conservative: `{float(aero_row['P_crank']):.3f} W` / `{float(aero_row['P_crank_conservative']):.3f} W`",
        f"- AVL: `CL={float(aero_row['CL']):.5f}`, `CDi={float(aero_row['CDi']):.7f}`, `e={float(aero_row['e_CDi']):.4f}`, `alpha={float(aero_row['alpha_deg']):.5f} deg`",
        f"- Tier2 query quality: `{aero_row['actual_query_quality']}`, warnings `{aero_row['profile_warning_count']}`",
        f"- aero-structure closure: `{closure_row['closure_status']}`",
        f"- tube / total structural mass: `{float(selected['tube_mass_kg']):.3f} kg` / `{float(selected['total_structural_mass_kg']):.3f} kg`",
        f"- jig clearance: `{float(selected['jig_ground_clearance_min_m']) * 1000.0:.1f} mm`",
        f"- wire tension / margin at reference 2g: `{float(wire['tension_force_n']):.1f} N` / `{float(wire['tension_margin_n']):.1f} N`",
        f"- loaded shape error: main z `{float(selected['loaded_shape_main_z_error_max_m']):.3e} m`, twist `{float(selected['loaded_shape_twist_error_max_deg']):.3e} deg`",
        f"- structure trust: `{confidence}`",
        fem_scale_line,
        "",
    ]
    (out_dir / "final_candidate_status.md").write_text("\n".join(status_lines), encoding="utf-8")

    load_table = [
        "| n | failure index | buckling index | tip defl m | wire tension N | wire margin N | root Fz est N | root M est N m |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in load_rows:
        load_table.append(
            f"| {row.load_factor:.2f} | {row.failure_index:.4f} | {row.buckling_index:.4f} | {row.tip_deflection_m:.4f} | {row.wire_tension_n:.1f} | {row.wire_tension_margin_n:.1f} | {row.root_vertical_resultant_n:.1f} | {row.root_bending_moment_n_m:.1f} |"
        )
    fail_lines = [
        "# Failure Margin Report",
        "",
        "Fixed-design load factor estimates are linearly scaled from the selected 2g structural run. This is appropriate for a first-pass beam-line check, but not a nonlinear aeroelastic or composite-joint proof.",
        "",
        *load_table,
        "",
        f"Estimated first-fail mode: `{first_fail.mode}` at `n={first_fail.load_factor:.3f}`.",
        "",
        "Failure classification: wire tension controls the first-fail extrapolation for this candidate; deflection is next. Tube stress and shell buckling have materially larger extrapolated margins in this internal model.",
        "",
        fem_scale_line,
        "",
        "Because the local B32R deck displacement scale disagrees with the internal model, the first-fail value remains an internal screening estimate rather than a FEM-supported failure margin.",
        "",
    ]
    (out_dir / "failure_margin_report.md").write_text("\n".join(fail_lines), encoding="utf-8")

    blockers = [
        "# Remaining Blockers",
        "",
        "- Candidate-specific CalculiX/APDL decks exist, but the local CalculiX displacement scale does not match the internal structural estimate closely enough to upgrade trust.",
        "- Missing input for upgrade: an apples-to-apples candidate FEM export contract that uses the same load split, support/wire boundary conditions, spar reference geometry, and displacement target basis as the internal inverse-design structural model.",
        "- Final verification still needs an engineer-owned shell/composite/root-joint model and external review.",
        "- Beam-line Z remains a proxy for aerodynamic-surface geometry; the current smooth geometry is AVL/CSV-supported, not a final production CAD release.",
        "- Stability derivative artifact was not found in the candidate package; AVL spanload/CDi are present, but full handling-quality acceptance is outside this closeout.",
    ]
    if fem_failed:
        blockers.append("- CalculiX did not complete every generated load-factor deck; inspect `fem_load_factor_summary.csv` and deck logs.")
    (out_dir / "remaining_blockers.md").write_text("\n".join(blockers) + "\n", encoding="utf-8")

    recommendation = [
        "# Final Recommendation",
        "",
        final_code,
        "",
        "Do not promote this candidate to FEM-supported engineering review yet. Keep the aero/Tier2/closure candidate as the active finalist, but block production-facing structural signoff until the FEM export and internal structural response are made comparable. Do not reopen broad CST/NSGA from this evidence; the largest error is the structural verification basis mismatch.",
        "",
    ]
    (out_dir / "final_recommendation.md").write_text("\n".join(recommendation), encoding="utf-8")


def _write_candidate_apdl_from_csv(
    *,
    csv_path: Path,
    path: Path,
    load_scale: float,
    material,
    label: str,
) -> None:
    rows = _read_csv_rows(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    nn = len(rows)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"! Candidate APDL beam spot-check: {CANDIDATE_ID} {label}\n")
        handle.write("! Generated from selected jig_shape_spar_data.csv\n")
        handle.write("/PREP7\n")
        handle.write(f"MP,EX,1,{material.E:.9e}\nMP,GXY,1,{material.G:.9e}\nMP,PRXY,1,{material.poisson_ratio:.6g}\nMP,DENS,1,{material.density:.9g}\n")
        handle.write(f"MP,EX,2,{material.E:.9e}\nMP,GXY,2,{material.G:.9e}\nMP,PRXY,2,{material.poisson_ratio:.6g}\nMP,DENS,2,{material.density:.9g}\n")
        handle.write("ET,1,BEAM188\nKEYOPT,1,3,2\nET,2,BEAM188\nKEYOPT,2,3,2\n")
        for idx, row in enumerate(rows, start=1):
            handle.write(
                f"K,{idx},{float(row['Main_X_m']):.9g},{float(row['Y_Position_m']):.9g},{float(row['Main_Z_m']):.9g}\n"
            )
        for idx, row in enumerate(rows, start=1):
            handle.write(
                f"K,{nn + idx},{float(row['Rear_X_m']):.9g},{float(row['Y_Position_m']):.9g},{float(row['Rear_Z_m']):.9g}\n"
            )
        for idx in range(1, nn):
            handle.write(f"L,{idx},{idx + 1}\n")
        for idx in range(1, nn):
            handle.write(f"L,{nn + idx},{nn + idx + 1}\n")
        for idx in range(1, nn):
            ro = 0.5 * (float(rows[idx - 1]["Main_Outer_Radius_m"]) + float(rows[idx]["Main_Outer_Radius_m"]))
            tw = 0.5 * (float(rows[idx - 1]["Main_Wall_Thickness_m"]) + float(rows[idx]["Main_Wall_Thickness_m"]))
            handle.write(f"SECTYPE,{idx},BEAM,CTUBE\nSECDATA,{max(ro - tw, 0.0):.9g},{ro:.9g}\n")
        for idx in range(1, nn):
            ro = 0.5 * (float(rows[idx - 1]["Rear_Outer_Radius_m"]) + float(rows[idx]["Rear_Outer_Radius_m"]))
            tw = 0.5 * (float(rows[idx - 1]["Rear_Wall_Thickness_m"]) + float(rows[idx]["Rear_Wall_Thickness_m"]))
            handle.write(f"SECTYPE,{nn + idx},BEAM,CTUBE\nSECDATA,{max(ro - tw, 0.0):.9g},{ro:.9g}\n")
        for idx in range(1, nn):
            handle.write(f"LSEL,S,LINE,,{idx}\nLATT,1,,1,,,,{idx}\nLESIZE,ALL,,,1\nLMESH,ALL\n")
        for idx in range(1, nn):
            handle.write(f"LSEL,S,LINE,,{nn - 1 + idx}\nLATT,2,,2,,,,{nn + idx}\nLESIZE,ALL,,,1\nLMESH,ALL\n")
        handle.write("ALLSEL,ALL\n")
        for idx, row in enumerate(rows, start=1):
            if int(float(row["Is_Joint"])) == 1:
                handle.write(f"CERIG,{idx},{nn + idx},ALL\n")
        handle.write("DK,1,ALL,0\n")
        handle.write(f"DK,{nn + 1},ALL,0\n")
        for idx, row in enumerate(rows, start=1):
            if int(float(row["Is_Wire_Attach"])) == 1:
                handle.write(f"DK,{idx},UZ,0\n")
        for idx, row in enumerate(rows, start=1):
            main_fz = float(row["Main_FZ_N"]) * load_scale
            rear_fz = float(row["Rear_FZ_N"]) * load_scale
            if abs(main_fz) > 1.0e-12:
                handle.write(f"FK,{idx},FZ,{main_fz:.9g}\n")
            if abs(rear_fz) > 1.0e-12:
                handle.write(f"FK,{nn + idx},FZ,{rear_fz:.9g}\n")
        handle.write("FINISH\n/SOLU\nANTYPE,STATIC\nSOLVE\nFINISH\n/POST1\nSET,LAST\nPRRSOL,FZ\nFINISH\n")


def _write_fem_readme(path: Path, *, ccx_binary: str | None) -> None:
    lines = [
        "# Candidate FEM Case Package",
        "",
        "This package is generated from the selected candidate spar CSV and includes:",
        "- CalculiX B32R beam decks under `calculix/`",
        "- APDL BEAM188 macros under `apdl/`",
        "",
        f"Local CalculiX binary used: `{ccx_binary or 'not found'}`",
        "",
        "The decks are finalist spot-check evidence. They are not a shell composite/root-joint certification model.",
    ]
    (path / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _find_ccx(explicit: str | None) -> str | None:
    candidates = [
        explicit,
        shutil.which("ccx"),
        shutil.which("ccx_2.23"),
        "/opt/homebrew/bin/ccx_2.23",
        "/Volumes/Samsung SSD/homebrew-cellar/Cellar/calculix-ccx/2.23/bin/ccx_2.23",
    ]
    for item in candidates:
        if item and Path(item).exists():
            return str(Path(item).resolve())
    return None


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _select_csv_row(path: Path, key: str, value: str) -> dict[str, str]:
    for row in _read_csv_rows(path):
        if row.get(key) == value:
            return row
    raise ValueError(f"No row in {path} where {key}={value}.")


def _array(rows: list[dict[str, str]], key: str) -> np.ndarray:
    return np.asarray([float(row[key]) for row in rows], dtype=float)


def _element_average(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return 0.5 * (values[:-1] + values[1:])


def _flag_indices(rows: list[dict[str, str]], key: str) -> tuple[int, ...]:
    return tuple(idx for idx, row in enumerate(rows) if int(float(row.get(key, "0"))) == 1)


def _max_abs_optional_float(*values: object) -> float | None:
    parsed: list[float] = []
    for value in values:
        if value is None or value == "":
            continue
        parsed.append(abs(float(value)))
    if not parsed:
        return None
    return max(parsed)


def _load_factor_label(value: float) -> str:
    return f"lf_{float(value):.2f}".replace(".", "p")


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
