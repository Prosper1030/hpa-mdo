#!/usr/bin/env python3
"""Positive torque-zone local FEM / coupon package for the current pathfinder.

This runner turns the closure-owned hybrid rib screening result into a local
validation handoff for the positive y~=2.328 m torque-critical zone. It does not
run FEM and it does not claim local margins.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_REWORK_VERDICT_JSON = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_rib_torsion_rework_verdict"
    / "rib_torsion_rework_verdict.json"
)
DEFAULT_SELECTED_BASIS_JSON = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_rib_torsion_rework_verdict"
    / "selected_basis_for_tail_aware_closure_rerun.json"
)
DEFAULT_STATION_TABLE_CSV = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_materialized_rib_contract_audit"
    / "rib_station_table.csv"
)
DEFAULT_BAY_TABLE_CSV = (
    REPO_ROOT
    / "output"
    / "current_pathfinder_materialized_rib_contract_audit"
    / "rib_bay_table.csv"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_positive_torque_zone_validation"
DEFAULT_REPORT_JSON = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_positive_torque_zone_local_validation_package.json"
)
DEFAULT_REPORT_MD = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_positive_torque_zone_local_validation_package.md"
)

SCHEMA_VERSION = "current_pathfinder_positive_torque_zone_validation_package_v1"
PACKAGE_VERDICT = "positive_zone_ready_for_local_FEM_and_coupon_definition_not_margin_pass"
FEM_MARGIN_STATUS = "not_run"


def build_positive_zone_validation_package(
    *,
    rework_verdict_json: Path = DEFAULT_REWORK_VERDICT_JSON,
    selected_basis_json: Path = DEFAULT_SELECTED_BASIS_JSON,
    station_table_csv: Path = DEFAULT_STATION_TABLE_CSV,
    bay_table_csv: Path = DEFAULT_BAY_TABLE_CSV,
) -> dict[str, Any]:
    """Build the positive-zone local validation package from committed artifacts."""

    rework = _read_json(Path(rework_verdict_json))
    selected_basis_payload = _read_json(Path(selected_basis_json))
    station_rows_all = _read_csv(Path(station_table_csv))
    bay_rows_all = _read_csv(Path(bay_table_csv))

    zone = _positive_zone_from_rework(rework)
    station_rows = _station_manifest_rows(
        all_station_rows=station_rows_all,
        all_bay_rows=bay_rows_all,
        zone=zone,
        selected_basis_payload=selected_basis_payload,
    )
    bay_rows = _bay_manifest_rows(all_bay_rows=bay_rows_all, zone=zone)
    load_rows, load_method = _positive_zone_load_rows(
        rework=rework,
        selected_basis_payload=selected_basis_payload,
        zone_station_rows=station_rows,
    )
    critical_row = min(
        load_rows,
        key=lambda row: abs(float(row["y_m"]) - float(zone["critical_y_m"])),
    )
    closure_evidence = _closure_evidence(rework)
    warnings = _warnings_from_rework(rework)
    missing_data = _missing_data_register()
    coupon_matrix = _coupon_test_matrix()

    package = {
        "schema_version": SCHEMA_VERSION,
        "package_verdict": PACKAGE_VERDICT,
        "fem_margin_status": FEM_MARGIN_STATUS,
        "fem_margin_claim": "No FEM margin is claimed; this is a guarded input package.",
        "candidate_id": rework.get("candidate_id"),
        "selected_basis": {
            "rib_family": _mapping_at(selected_basis_payload, "rib_basis").get("family_key")
            or _mapping_at(rework, "selected_rework_candidate").get("family_key"),
            "rear_spar_participation": _mapping_at(selected_basis_payload, "selected_basis").get(
                "rear_spar_participation"
            )
            or _mapping_at(rework, "selected_rework_candidate").get(
                "rear_spar_participation"
            ),
            "rear_spar_participation_role": (
                "bounded stiffness participation, not a direct load-split fraction"
            ),
            "structural_kernel_stiffness_override": _mapping_at(
                _mapping_at(selected_basis_payload, "selected_basis"),
                "structural_kernel_stiffness_override",
            ),
            "eps_core_role": (
                "shape/core support only; balsa cap, collar, adhesive, and tube "
                "contact own structural bracing credit"
            ),
        },
        "closure_evidence": closure_evidence,
        "warnings": warnings,
        "positive_zone": _positive_zone_payload(zone, station_rows, bay_rows),
        "station_manifest_rows": station_rows,
        "bay_manifest_rows": bay_rows,
        "load_path_decomposition": _load_path_decomposition(),
        "local_load_decomposition": {
            "method": load_method,
            "station_load_rows": load_rows,
            "critical_station_load_row": critical_row,
        },
        "local_fem_model_contract": _local_fem_model_contract(zone, station_rows, bay_rows),
        "coupon_test_matrix": coupon_matrix,
        "missing_data_register": missing_data,
        "available_data_register": _available_data_register(
            rework=rework,
            station_rows=station_rows,
            bay_rows=bay_rows,
            load_rows=load_rows,
        ),
        "do_not_promote": [
            "do_not_claim_FEM_pass_without_solver_margins",
            "do_not_use_rear_spar_participation_1p00_as_selected_basis",
            "do_not_credit_EPS_or_XPS_foam_only_as_structural_bracing",
            "do_not_hide_direct_spar_pair_stress_test_warning",
        ],
        "next_blocker_if_not_closed": (
            "supplier/coupon allowables and collar/tube-wall detail are still missing; "
            "do not export a FEM/APDL margin package until these values replace guarded placeholders"
        ),
        "next_recommended_task": (
            "Fill supplier/coupon allowables for the positive zone APDL skeleton, run "
            "local bond/collar/tube-wall FEM or hand/FEM margins, then mirror the same "
            "contract to the negative torque-critical zone."
        ),
        "claim_boundary": (
            "This package validates the local load path for the already selected "
            "screening-closed hybrid rib basis. It does not retune full-wing twist and "
            "does not certify hardware."
        ),
    }
    return package


def write_positive_zone_validation_package(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_json: Path | None = None,
    report_md: Path | None = None,
    rework_verdict_json: Path = DEFAULT_REWORK_VERDICT_JSON,
    selected_basis_json: Path = DEFAULT_SELECTED_BASIS_JSON,
    station_table_csv: Path = DEFAULT_STATION_TABLE_CSV,
    bay_table_csv: Path = DEFAULT_BAY_TABLE_CSV,
) -> dict[str, Path]:
    """Write the positive-zone package artifacts."""

    package = build_positive_zone_validation_package(
        rework_verdict_json=Path(rework_verdict_json),
        selected_basis_json=Path(selected_basis_json),
        station_table_csv=Path(station_table_csv),
        bay_table_csv=Path(bay_table_csv),
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: dict[str, Path] = {
        "package_json": output_dir / "positive_zone_local_validation_package.json",
        "package_md": output_dir / "positive_zone_local_validation_package.md",
        "station_manifest_csv": output_dir / "positive_zone_station_manifest.csv",
        "bay_manifest_csv": output_dir / "positive_zone_bay_manifest.csv",
        "load_decomposition_csv": output_dir / "positive_zone_load_decomposition.csv",
        "coupon_matrix_csv": output_dir / "positive_zone_coupon_matrix.csv",
        "missing_data_register_csv": output_dir / "positive_zone_missing_data_register.csv",
        "apdl_skeleton": output_dir / "positive_zone_local_fem_skeleton.mac",
    }

    _write_json(paths["package_json"], package)
    paths["package_md"].write_text(_render_package_markdown(package, paths), encoding="utf-8")
    _write_csv(paths["station_manifest_csv"], package["station_manifest_rows"])
    _write_csv(paths["bay_manifest_csv"], package["bay_manifest_rows"])
    _write_csv(
        paths["load_decomposition_csv"],
        package["local_load_decomposition"]["station_load_rows"],
    )
    _write_csv(paths["coupon_matrix_csv"], package["coupon_test_matrix"])
    _write_csv(paths["missing_data_register_csv"], package["missing_data_register"])
    paths["apdl_skeleton"].write_text(_render_apdl_skeleton(package), encoding="utf-8")

    if report_json is not None:
        paths["report_json"] = Path(report_json)
        _write_json(paths["report_json"], package)
    if report_md is not None:
        paths["report_md"] = Path(report_md)
        paths["report_md"].parent.mkdir(parents=True, exist_ok=True)
        paths["report_md"].write_text(_render_package_markdown(package, paths), encoding="utf-8")
    return paths


def _positive_zone_from_rework(rework: Mapping[str, Any]) -> dict[str, Any]:
    zones = _mapping_at(rework, "local_fem_coupon_validation_package").get(
        "local_fem_zones"
    ) or _mapping_at(rework, "local_fem_coupon_requirements").get(
        "recommended_hybrid_reinforcement_zones"
    )
    for zone in zones or []:
        if str(zone.get("zone_id")) == "positive_torque_critical_hybrid_reinforcement_zone":
            payload = dict(zone)
            payload.setdefault(
                "critical_y_m",
                _mapping_at(rework, "materialized_contract_assessment").get(
                    "torque_critical_y_m"
                )
                or _mapping_at(rework, "baseline_state").get("torque_critical_y_m"),
            )
            payload["critical_y_m"] = float(payload["critical_y_m"])
            payload["station_ids"] = list(payload.get("station_ids") or [])
            payload["bay_ids"] = list(payload.get("bay_ids") or [])
            return payload
    raise ValueError("positive torque-critical reinforcement zone is missing from rework verdict.")


def _station_manifest_rows(
    *,
    all_station_rows: Sequence[Mapping[str, str]],
    all_bay_rows: Sequence[Mapping[str, str]],
    zone: Mapping[str, Any],
    selected_basis_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_station = {str(row["rib_id"]): row for row in all_station_rows}
    bay_by_id = {str(row["bay_id"]): row for row in all_bay_rows}
    zone_ribs = [str(item) for item in zone.get("station_ids") or []]
    boundary_ids = _boundary_rib_ids(
        zone_ribs=zone_ribs,
        zone_bays=[str(item) for item in zone.get("bay_ids") or []],
        bay_by_id=bay_by_id,
    )
    selected_family = str(_mapping_at(selected_basis_payload, "rib_basis").get("family_key") or "")
    selected_category = str(
        _mapping_at(_mapping_at(selected_basis_payload, "rib_basis"), "material_basis").get(
            "family_category"
        )
        or _mapping_at(selected_basis_payload, "rib_basis").get("material_category")
        or ""
    )
    rows: list[dict[str, Any]] = []
    for rib_id in boundary_ids:
        raw = by_station[rib_id]
        role = (
            "torque_critical_validation_rib"
            if rib_id in zone_ribs
            else "local_model_boundary_rib"
        )
        rows.append(
            {
                "rib_id": rib_id,
                "zone_role": role,
                "y_m": _round(_float(raw.get("y_m")), 6),
                "chord_m": _round(_float(raw.get("chord_m")), 6),
                "main_spar_xc": _round(_float(raw.get("main_spar_xc")), 6),
                "rear_spar_xc": _round(_float(raw.get("rear_spar_xc")), 6),
                "bay_prev_m": _round(_float_or_none(raw.get("bay_prev_m")), 6),
                "bay_next_m": _round(_float_or_none(raw.get("bay_next_m")), 6),
                "existing_audit_material_family": raw.get("material_family"),
                "validation_material_family": selected_family,
                "validation_material_category": selected_category,
                "shape_sag_status": raw.get("shape_sag_status"),
                "bond_risk_status": raw.get("bond_risk_status"),
                "local_fem_required": raw.get("local_fem_required"),
                "fem_trigger_reasons": raw.get("fem_trigger_reasons"),
                "torque_critical_zone": raw.get("torque_critical_zone"),
            }
        )
    return rows


def _boundary_rib_ids(
    *,
    zone_ribs: Sequence[str],
    zone_bays: Sequence[str],
    bay_by_id: Mapping[str, Mapping[str, str]],
) -> list[str]:
    rib_ids: list[str] = []
    for bay_id in zone_bays:
        row = bay_by_id[str(bay_id)]
        rib_ids.extend([str(row["start_rib_id"]), str(row["end_rib_id"])])
    if not rib_ids:
        rib_ids = list(zone_ribs)
    return _sort_rib_ids(_dedupe(rib_ids))


def _bay_manifest_rows(
    *,
    all_bay_rows: Sequence[Mapping[str, str]],
    zone: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_bay = {str(row["bay_id"]): row for row in all_bay_rows}
    rows: list[dict[str, Any]] = []
    for bay_id in [str(item) for item in zone.get("bay_ids") or []]:
        raw = by_bay[bay_id]
        rows.append(
            {
                "bay_id": bay_id,
                "start_rib_id": raw.get("start_rib_id"),
                "end_rib_id": raw.get("end_rib_id"),
                "y_start_m": _round(_float(raw.get("y_start_m")), 6),
                "y_end_m": _round(_float(raw.get("y_end_m")), 6),
                "y_mid_m": _round(_float(raw.get("y_mid_m")), 6),
                "bay_length_m": _round(_float(raw.get("bay_length_m")), 6),
                "chord_mid_m": _round(_float(raw.get("chord_mid_m")), 6),
                "bay_length_over_chord": _round(_float(raw.get("bay_length_over_chord")), 6),
                "shape_sag_status": raw.get("shape_sag_status"),
                "bond_risk_status": raw.get("bond_risk_status"),
                "local_fem_required": raw.get("local_fem_required"),
                "fem_trigger_reasons": raw.get("fem_trigger_reasons"),
                "torque_critical_zone": raw.get("torque_critical_zone"),
            }
        )
    return rows


def _positive_zone_payload(
    zone: Mapping[str, Any],
    station_rows: Sequence[Mapping[str, Any]],
    bay_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    zone_ribs = [row["rib_id"] for row in station_rows if row["zone_role"] == "torque_critical_validation_rib"]
    boundary_ribs = [row["rib_id"] for row in station_rows]
    critical_station = min(
        [row for row in station_rows if row["rib_id"] in zone_ribs],
        key=lambda row: abs(float(row["y_m"]) - float(zone["critical_y_m"])),
    )
    return {
        "zone_id": zone.get("zone_id"),
        "critical_y_m": _round(float(zone["critical_y_m"]), 6),
        "critical_station_id": critical_station["rib_id"],
        "y_start_m": _round(_float(zone.get("y_start_m")), 6),
        "y_end_m": _round(_float(zone.get("y_end_m")), 6),
        "rib_ids": zone_ribs,
        "bay_ids": [row["bay_id"] for row in bay_rows],
        "local_model_boundary_rib_ids": boundary_ribs,
        "local_model_boundary_y_m": [
            _round(float(station_rows[0]["y_m"]), 6),
            _round(float(station_rows[-1]["y_m"]), 6),
        ],
        "engineering_scope": (
            "Positive torque-critical hybrid rib zone only; negative zone should be "
            "mirrored after this contract is stable."
        ),
    }


def _positive_zone_load_rows(
    *,
    rework: Mapping[str, Any],
    selected_basis_payload: Mapping[str, Any],
    zone_station_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    load_split, model, diagnostics = _extract_selected_kernel_load_split(
        rework=rework,
        selected_basis_payload=selected_basis_payload,
    )
    component_rows = _read_csv(Path(_closure_artifact_path(rework, "final_twist_source_components_csv")))
    load_rows: list[dict[str, Any]] = []
    for station in zone_station_rows:
        y_m = float(station["y_m"])
        idx = int(np.argmin(np.abs(np.asarray(model.y_nodes_m, dtype=float) - y_m)))
        separation = float(model.spar_separation_nodes_m[idx])
        torque_my = float(load_split.torque_main_my_n[idx] + load_split.torque_rear_my_n[idx])
        couple_main = torque_my / separation if abs(separation) > 1.0e-12 else 0.0
        couple_rear = -couple_main
        component_at_station = _component_twist_at_y(component_rows, float(model.y_nodes_m[idx]))
        load_rows.append(
            {
                "rib_id": station["rib_id"],
                "zone_role": station["zone_role"],
                "y_m": _round(y_m, 6),
                "nearest_kernel_y_m": _round(float(model.y_nodes_m[idx]), 6),
                "spar_separation_m": _round(separation, 6),
                "kernel_lift_main_fz_n": _round(float(load_split.lift_main_fz_n[idx]), 6),
                "kernel_main_self_weight_fz_n": _round(
                    float(load_split.main_self_weight_fz_n[idx]), 6
                ),
                "kernel_rear_self_weight_fz_n": _round(
                    float(load_split.rear_self_weight_fz_n[idx]), 6
                ),
                "kernel_torque_my_nm": _round(torque_my, 6),
                "local_torque_couple_main_fz_n": _round(couple_main, 6),
                "local_torque_couple_rear_fz_n": _round(couple_rear, 6),
                "local_total_main_fz_n": _round(
                    float(load_split.lift_main_fz_n[idx])
                    + float(load_split.main_self_weight_fz_n[idx])
                    + couple_main,
                    6,
                ),
                "local_total_rear_fz_n": _round(
                    float(load_split.rear_self_weight_fz_n[idx]) + couple_rear,
                    6,
                ),
                "aero_torque_component_direct_twist_deg": _round(
                    component_at_station.get("aerodynamic_torque_only", 0.0), 6
                ),
                "lift_component_direct_twist_deg": _round(
                    component_at_station.get("lift_only", 0.0), 6
                ),
                "self_weight_component_direct_twist_deg": _round(
                    component_at_station.get("self_weight_only", 0.0), 6
                ),
                "load_application_note": (
                    "Apply lift/self-weight vertical loads to spar collar regions and "
                    "replace kernel My with equal/opposite main/rear collar force couple."
                ),
            }
        )
    method = {
        "source": "closure-owned selected dual-beam kernel plus final AVL spanload ratio",
        "load_update_basis": diagnostics["load_update_basis"],
        "ratio_bounds": [
            diagnostics["ratio_lower_bound"],
            diagnostics["ratio_upper_bound"],
        ],
        "relaxation_for_local_package": diagnostics["relaxation"],
        "min_relaxed_ratio": _round(diagnostics["min_relaxed_ratio"], 6),
        "max_relaxed_ratio": _round(diagnostics["max_relaxed_ratio"], 6),
        "torque_to_couple_formula": (
            "F_couple_N = M_y_Nm / spar_separation_m; apply +F at main spar and -F at rear spar"
        ),
        "engineering_boundary": (
            "These are screening nodal loads for the local model contract. Final FEM "
            "loads must be regenerated if the closure load owner or selected stiffness changes."
        ),
    }
    return load_rows, method


def _extract_selected_kernel_load_split(
    *,
    rework: Mapping[str, Any],
    selected_basis_payload: Mapping[str, Any],
):
    from hpa_mdo.structure.dual_beam_mainline.load_split import build_dual_beam_load_split
    from hpa_mdo.structure.dual_beam_mainline.types import (
        AnalysisModeName,
        get_analysis_mode_definition,
    )
    from scripts.phase22_bracing_sensitivity import (
        build_current_candidate_model,
        clone_with_rear_stiffness_scale,
    )
    from scripts.tail_aware_aeroelastic_closure import (
        apply_selected_stiffness_overrides,
        rescale_structural_loads_by_avl_ratio,
    )

    selected_basis = _mapping_at(selected_basis_payload, "selected_basis")
    rib_basis = _mapping_at(selected_basis_payload, "rib_basis")
    model = clone_with_rear_stiffness_scale(
        build_current_candidate_model(),
        float(selected_basis.get("rear_stiffness_scale", 0.50)),
    )
    model, _diagnostics = apply_selected_stiffness_overrides(
        model,
        selected_basis=selected_basis,
        rib_basis=rib_basis,
    )
    spanload_rows = _read_csv(Path(_closure_artifact_path(rework, "final_wing_spanload_redistribution_csv")))
    avl_y = np.asarray([_float(row["y_m"]) for row in spanload_rows], dtype=float)
    baseline = np.asarray(
        [_float(row["baseline_lift_per_span_npm"]) for row in spanload_rows],
        dtype=float,
    )
    updated = np.asarray(
        [_float(row["updated_lift_per_span_npm"]) for row in spanload_rows],
        dtype=float,
    )
    scaled_lift, scaled_torque, diagnostics = rescale_structural_loads_by_avl_ratio(
        model_y_m=model.y_nodes_m,
        baseline_structural_lift_npm=model.lift_per_span_npm,
        baseline_structural_torque_nmpm=model.torque_per_span_nmpm,
        avl_y_m=avl_y,
        baseline_avl_lift_npm=baseline,
        updated_avl_lift_npm=updated,
        relaxation=1.0,
        ratio_bounds=(0.70, 1.30),
    )
    model = replace(
        model,
        lift_per_span_npm=scaled_lift,
        torque_per_span_nmpm=scaled_torque,
    )
    load_split = build_dual_beam_load_split(
        model=model,
        mode_definition=get_analysis_mode_definition(AnalysisModeName.DUAL_BEAM_ROBUSTNESS),
    )
    return load_split, model, diagnostics


def _component_twist_at_y(rows: Sequence[Mapping[str, str]], y_m: float) -> dict[str, float]:
    values: dict[str, float] = {}
    for component in ("lift_only", "aerodynamic_torque_only", "self_weight_only"):
        component_rows = [row for row in rows if row.get("component") == component]
        if not component_rows:
            values[component] = 0.0
            continue
        nearest = min(component_rows, key=lambda row: abs(_float(row["y_m"]) - y_m))
        values[component] = _float(nearest["direct_spar_pair_rotation_deg"])
    return values


def _closure_artifact_path(rework: Mapping[str, Any], key: str) -> str:
    manifest = _mapping_at(_mapping_at(rework, "closure_rerun_assessment"), "artifact_manifest")
    value = manifest.get(key)
    if not value:
        raise ValueError(f"closure artifact manifest is missing {key}.")
    return str(value)


def _closure_evidence(rework: Mapping[str, Any]) -> dict[str, Any]:
    closure = _mapping_at(rework, "closure_rerun_assessment")
    selected = _mapping_at(rework, "selected_rework_candidate")
    mass = _mapping_at(selected, "mass_cg_tail_trim_impact")
    return {
        "closure_verdict": closure.get("closure_verdict"),
        "bounded_physical_twist_deg": _round(
            _float(closure.get("conservative_bounded_physical_projection_max_abs_deg")),
            6,
        ),
        "direct_spar_pair_stress_test_deg": _round(
            _float(closure.get("direct_spar_pair_rotation_max_abs_deg")),
            6,
        ),
        "direct_stress_test_status": closure.get("direct_stress_test_status"),
        "final_cg_x_m": _round(
            _float(mass.get("final_screening_cg_x_m") or mass.get("final_cg_x_m")),
            6,
        ),
        "required_forward_rebalance_m": _round(
            _float(mass.get("required_forward_rebalance_m")),
            6,
        ),
        "static_margin": 0.094301,
        "C_n_beta": 0.01403,
        "H_tail_reserve_deg": 4.792985,
        "V_tail_reserve_deg": 16.716831,
        "claim_boundary": (
            "Bounded twist closure is a screening pass; direct stress-test and local "
            "bond/collar/tube-wall validation remain open."
        ),
    }


def _warnings_from_rework(rework: Mapping[str, Any]) -> list[str]:
    warnings = list(_mapping_at(rework, "closure_rerun_assessment").get("warnings") or [])
    if "direct_spar_pair_stress_test_above_bound_conservative_mapping" not in warnings:
        warnings.append("direct_spar_pair_stress_test_above_bound_conservative_mapping")
    return _dedupe([str(item) for item in warnings])


def _load_path_decomposition() -> dict[str, Any]:
    return {
        "steps": [
            {
                "step_id": "aero_lift_owner",
                "description": (
                    "Final closure spanload supplies vertical lift. The current kernel "
                    "places lift on the main spar line; the local model applies it at "
                    "main collar/rib web entry points as a conservative load-owner basis."
                ),
            },
            {
                "step_id": "aero_torque_owner",
                "description": (
                    "Span-axis aerodynamic torque is converted from kernel My into a "
                    "main/rear vertical force couple at each collar: F=M/d."
                ),
            },
            {
                "step_id": "rib_cap_shear_transfer",
                "description": (
                    "Balsa/cap faces transfer rib web shear between skin, main collar, "
                    "rear collar, and cap strip. EPS is shape support only."
                ),
            },
            {
                "step_id": "bond_collar_tube_wall",
                "description": (
                    "Adhesive and collar transfer shear/peel/bearing into main and rear "
                    "spar tubes; tube walls must clear bearing, local crush, and ovalization."
                ),
            },
        ],
        "load_path_read": (
            "The desired structural bracing credit is owned by cap/collar/bond/tube-wall "
            "details. Foam-only stiffness is explicitly not credited."
        ),
    }


def _local_fem_model_contract(
    zone: Mapping[str, Any],
    station_rows: Sequence[Mapping[str, Any]],
    bay_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "analysis_type": "local static bond/collar/tube-wall check",
        "recommended_solver_route": "APDL shell/solid local model or equivalent CalculiX model",
        "model_extent": {
            "spanwise_boundary_ribs": [station_rows[0]["rib_id"], station_rows[-1]["rib_id"]],
            "spanwise_y_range_m": [
                _round(float(station_rows[0]["y_m"]), 6),
                _round(float(station_rows[-1]["y_m"]), 6),
            ],
            "active_validation_ribs": list(zone.get("station_ids") or []),
            "active_bays": [row["bay_id"] for row in bay_rows],
        },
        "boundary_conditions": [
            {
                "bc_id": "spar_tube_remote_section_boundaries",
                "application": (
                    "At R066 and R070 spar cross-sections, constrain only rigid body "
                    "modes through remote section nodes; carry axial/torsion/bending "
                    "resultants from the global beam if available."
                ),
            },
            {
                "bc_id": "collar_bonded_contact",
                "application": (
                    "Tie or bonded contact from collar inner surface to spar tube outer "
                    "surface; run a peel-sensitive variant if adhesive thickness data exists."
                ),
            },
            {
                "bc_id": "rib_cap_to_collar_transfer",
                "application": (
                    "Bond rib cap/face strips to collar tabs and rib web; do not bond EPS "
                    "core directly as a structural bracing member."
                ),
            },
            {
                "bc_id": "skin_shape_sag_panel",
                "application": (
                    "Include bay skin panel or equivalent pressure/handling load if the "
                    "coupon plan is used to clear shape keeping."
                ),
            },
        ],
        "loads": [
            "main collar vertical lift/self-weight nodal loads",
            "main/rear equal-opposite torque force couple from kernel My",
            "optional handling/skin-sag panel pressure after skin material is supplied",
        ],
        "contacts_and_bonds": [
            "main spar tube to main collar",
            "rear spar tube to rear collar",
            "collar tab to balsa/cap strip",
            "cap strip to rib web/core",
            "skin panel to rib cap if skin sag is modeled",
        ],
        "materials_needed": [
            "spar tube material, OD, wall thickness, and local laminate/metal allowables",
            "collar material and thickness",
            "adhesive shear/peel allowables and cured bondline thickness",
            "balsa/cap face material, grain/fiber direction, and thickness",
            "EPS density/modulus only for shape support, not structural bracing credit",
            "skin material/thickness for bay sag variant",
        ],
    }


def _coupon_test_matrix() -> list[dict[str, Any]]:
    return [
        {
            "coupon_id": "C01_eps_balsa_cap_shear_transfer",
            "purpose": "EPS+balsa cap shear transfer",
            "specimen": "representative hybrid rib web with balsa/cap strips and EPS core",
            "load_mode": "in-plane shear / diagonal shear",
            "measured_outputs": "shear stiffness, peak shear load, debond initiation",
            "minimum_data_needed": "cap dimensions, adhesive, EPS density, balsa grain direction",
            "pass_status": "not_tested",
        },
        {
            "coupon_id": "C02_main_spar_bond_shear",
            "purpose": "rib-to-main-spar bond shear",
            "specimen": "main collar/bondline coupon on representative tube section",
            "load_mode": "lap/shear with local collar load introduction",
            "measured_outputs": "ultimate shear, stiffness, failure mode",
            "minimum_data_needed": "bond width, adhesive, tube OD/wall/material, collar material",
            "pass_status": "not_tested",
        },
        {
            "coupon_id": "C03_rear_spar_bond_shear",
            "purpose": "rib-to-rear-spar bond shear",
            "specimen": "rear collar/bondline coupon on representative tube section",
            "load_mode": "lap/shear with torque-couple load direction",
            "measured_outputs": "ultimate shear, stiffness, failure mode",
            "minimum_data_needed": "rear bond width, adhesive, tube OD/wall/material, collar material",
            "pass_status": "not_tested",
        },
        {
            "coupon_id": "C04_bond_peel",
            "purpose": "peel",
            "specimen": "collar tab to cap/bondline peel coupon",
            "load_mode": "peel / mixed-mode opening",
            "measured_outputs": "peel load, crack initiation, process sensitivity",
            "minimum_data_needed": "adhesive system, fillet radius, cure/process notes",
            "pass_status": "not_tested",
        },
        {
            "coupon_id": "C05_collar_bearing",
            "purpose": "collar bearing",
            "specimen": "collar on spar tube with representative contact footprint",
            "load_mode": "bearing/compression through collar tab",
            "measured_outputs": "bearing margin, collar local buckling, slip",
            "minimum_data_needed": "collar thickness/material, contact width, tube material",
            "pass_status": "not_tested",
        },
        {
            "coupon_id": "C06_tube_wall_crush_ovalization",
            "purpose": "local tube wall crushing / ovalization",
            "specimen": "spar tube segment under collar point/patch load",
            "load_mode": "radial crush plus torque-couple vertical load",
            "measured_outputs": "ovalization, local buckling, residual deformation",
            "minimum_data_needed": "tube OD/wall/layup or alloy, collar footprint",
            "pass_status": "not_tested",
        },
        {
            "coupon_id": "C07_skin_sag_shape_keeping_panel",
            "purpose": "0.30 m bay skin sag / shape keeping",
            "specimen": "B067/B068 representative bay panel with rib cap support",
            "load_mode": "pressure/handling load panel deflection",
            "measured_outputs": "sag, shape tolerance, post-load recovery",
            "minimum_data_needed": "skin material/thickness, attachment, allowable airfoil tolerance",
            "pass_status": "not_tested",
        },
    ]


def _missing_data_register() -> list[dict[str, Any]]:
    return [
        {
            "data_key": "adhesive_shear_allowable_pa",
            "status": "supplier_or_coupon_missing",
            "required_for": "rib-to-spar bond shear",
            "blocks": "FEM/APDL margin claim",
        },
        {
            "data_key": "adhesive_peel_allowable_pa",
            "status": "supplier_or_coupon_missing",
            "required_for": "bond peel / mixed-mode opening",
            "blocks": "collar tab peel margin",
        },
        {
            "data_key": "bondline_width_thickness_fillet",
            "status": "geometry_missing",
            "required_for": "bond shear/peel stress extraction",
            "blocks": "mesh and stress concentration definition",
        },
        {
            "data_key": "collar_material_thickness_contact_width",
            "status": "geometry_and_allowable_missing",
            "required_for": "collar bearing and tab load transfer",
            "blocks": "collar bearing margin",
        },
        {
            "data_key": "spar_tube_od_wall_material",
            "status": "supplier_or_design_missing",
            "required_for": "collar bearing and local tube wall crush/ovalization",
            "blocks": "tube-wall local FEM margin",
        },
        {
            "data_key": "balsa_cap_face_properties",
            "status": "supplier_or_coupon_missing",
            "required_for": "EPS+balsa cap shear transfer",
            "blocks": "hybrid effective-GJ credit",
        },
        {
            "data_key": "eps_core_properties",
            "status": "supplier_missing_for_shape_only_role",
            "required_for": "shape support and process repeatability",
            "blocks": "skin sag and manufacturing repeatability read",
        },
        {
            "data_key": "skin_material_thickness_attachment",
            "status": "design_missing",
            "required_for": "0.30 m bay skin sag / shape keeping",
            "blocks": "shape-keeping validation",
        },
    ]


def _available_data_register(
    *,
    rework: Mapping[str, Any],
    station_rows: Sequence[Mapping[str, Any]],
    bay_rows: Sequence[Mapping[str, Any]],
    load_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "data_key": "station_and_bay_ids",
            "status": "available",
            "value": f"{[row['rib_id'] for row in station_rows]} / {[row['bay_id'] for row in bay_rows]}",
        },
        {
            "data_key": "closure_twist_evidence",
            "status": "available",
            "value": str(_closure_evidence(rework)),
        },
        {
            "data_key": "screening_local_load_rows",
            "status": "available",
            "value": f"{len(load_rows)} station rows with lift/self-weight/torque-couple loads",
        },
        {
            "data_key": "selected_hybrid_basis",
            "status": "available",
            "value": "eps_balsa_cap_hybrid_10mm + bounded_65pct_screening",
        },
    ]


def _render_package_markdown(package: Mapping[str, Any], paths: Mapping[str, Path]) -> str:
    zone = _mapping_at(package, "positive_zone")
    closure = _mapping_at(package, "closure_evidence")
    critical = _mapping_at(_mapping_at(package, "local_load_decomposition"), "critical_station_load_row")
    lines = [
        "# Positive Torque-Zone Local FEM / Coupon Validation Package",
        "",
        f"Verdict: `{package.get('package_verdict')}`",
        f"FEM margin status: `{package.get('fem_margin_status')}`. No FEM margin is claimed.",
        "",
        "## Selected Closure Basis",
        "",
        f"- Rib / rear-spar basis: `{_mapping_at(package, 'selected_basis').get('rib_family')}` / `{_mapping_at(package, 'selected_basis').get('rear_spar_participation')}`.",
        f"- Bounded physical twist: `{closure.get('bounded_physical_twist_deg')}` deg.",
        f"- Direct spar-pair stress-test: `{closure.get('direct_spar_pair_stress_test_deg')}` deg; status `{closure.get('direct_stress_test_status')}`.",
        f"- Final CG / rebalance: `{closure.get('final_cg_x_m')}` m / `{closure.get('required_forward_rebalance_m')}` m.",
        "",
        "## Positive Zone",
        "",
        f"- Active ribs: {' / '.join(zone.get('rib_ids') or [])}.",
        f"- Active bays: {' / '.join(zone.get('bay_ids') or [])}.",
        f"- Boundary ribs for local model: {' / '.join(zone.get('local_model_boundary_rib_ids') or [])}.",
        f"- Critical station: `{zone.get('critical_station_id')}` at y=`{zone.get('critical_y_m')}` m.",
        "",
        "## Critical Load Row",
        "",
        f"- Main lift Fz: `{critical.get('kernel_lift_main_fz_n')}` N.",
        f"- Kernel torque My: `{critical.get('kernel_torque_my_nm')}` N*m.",
        f"- Local torque couple main/rear Fz: `{critical.get('local_torque_couple_main_fz_n')}` / `{critical.get('local_torque_couple_rear_fz_n')}` N.",
        f"- Local total main/rear Fz: `{critical.get('local_total_main_fz_n')}` / `{critical.get('local_total_rear_fz_n')}` N.",
        "",
        "## Load Path",
        "",
    ]
    for row in _mapping_at(package, "load_path_decomposition").get("steps") or []:
        lines.append(f"- `{row.get('step_id')}`: {row.get('description')}")
    lines.extend(["", "## Coupon Matrix", ""])
    for row in package.get("coupon_test_matrix") or []:
        lines.append(
            f"- `{row.get('coupon_id')}`: {row.get('purpose')} ({row.get('load_mode')}); status `{row.get('pass_status')}`."
        )
    lines.extend(["", "## Missing Data", ""])
    for row in package.get("missing_data_register") or []:
        lines.append(
            f"- `{row.get('data_key')}`: {row.get('status')}; required for {row.get('required_for')}."
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
        ]
    )
    for label in (
        "station_manifest_csv",
        "bay_manifest_csv",
        "load_decomposition_csv",
        "coupon_matrix_csv",
        "missing_data_register_csv",
        "apdl_skeleton",
        "package_json",
    ):
        if label in paths:
            lines.append(f"- `{label}`: `{paths[label]}`")
    lines.extend(
        [
            "",
            "## Next Blocker",
            "",
            str(package.get("next_blocker_if_not_closed")),
            "",
            "## Claim Boundary",
            "",
            str(package.get("claim_boundary")),
            "",
        ]
    )
    return "\n".join(lines)


def _render_apdl_skeleton(package: Mapping[str, Any]) -> str:
    zone = _mapping_at(package, "positive_zone")
    critical = _mapping_at(_mapping_at(package, "local_load_decomposition"), "critical_station_load_row")
    return f"""! positive_torque_zone_local_fem_skeleton
! Current pathfinder local FEM input skeleton for positive y~=2.328 m.
! This file is guarded: it is not a margin-running deck until supplier/coupon data
! replace the negative placeholder parameters below.
/PREP7
/COM, Selected basis: eps_balsa_cap_hybrid_10mm + bounded_65pct_screening
/COM, Active ribs: {' / '.join(zone.get('rib_ids') or [])}
/COM, Active bays: {' / '.join(zone.get('bay_ids') or [])}
/COM, Boundary ribs: {' / '.join(zone.get('local_model_boundary_rib_ids') or [])}

SUPPLIER_DATA_REQUIRED = 1
MAIN_SPAR_OD_M = -1
MAIN_SPAR_WALL_M = -1
REAR_SPAR_OD_M = -1
REAR_SPAR_WALL_M = -1
COLLAR_THICKNESS_M = -1
BONDLINE_WIDTH_M = -1
BONDLINE_THICKNESS_M = -1
ADHESIVE_SHEAR_ALLOWABLE_PA = -1
ADHESIVE_PEEL_ALLOWABLE_PA = -1
COLLAR_BEARING_ALLOWABLE_PA = -1
TUBE_CRUSH_ALLOWABLE_PA = -1
BALSACAP_SHEAR_ALLOWABLE_PA = -1
SKIN_THICKNESS_M = -1

*IF,MAIN_SPAR_OD_M,LE,0,THEN
  /COM,SUPPLIER_DATA_REQUIRED: spar/collar/bond/coupon data missing. Stop before solve.
  FINISH
  *EXIT
*ENDIF
*IF,ADHESIVE_SHEAR_ALLOWABLE_PA,LE,0,THEN
  /COM,SUPPLIER_DATA_REQUIRED: adhesive shear allowable missing. Stop before solve.
  FINISH
  *EXIT
*ENDIF

Y_START_M = {zone.get('local_model_boundary_y_m', [0.0, 0.0])[0]}
Y_END_M = {zone.get('local_model_boundary_y_m', [0.0, 0.0])[1]}
Y_TORQUE_CRITICAL_M = {zone.get('critical_y_m')}
M_TORQUE_CRITICAL_NM = {critical.get('kernel_torque_my_nm')}
F_MAIN_TOTAL_R068_N = {critical.get('local_total_main_fz_n')}
F_REAR_TOTAL_R068_N = {critical.get('local_total_rear_fz_n')}
F_MAIN_TORQUE_COUPLE_R068_N = {critical.get('local_torque_couple_main_fz_n')}
F_REAR_TORQUE_COUPLE_R068_N = {critical.get('local_torque_couple_rear_fz_n')}

! Geometry to create after supplier data is filled:
! - Main/rear spar tube shell/solid sections from R066 to R070.
! - Collar patches at R067/R068/R069 on main and rear spar tubes.
! - Rib web/cap/collar tab surfaces for EPS+balsa cap hybrid path.
! - Optional B067/B068 skin panel for skin-sag variant.

! Named components expected by the load step:
! CM,MAIN_COLLAR_R068,NODE
! CM,REAR_COLLAR_R068,NODE
! CM,BOUNDARY_R066_MAIN,NODE
! CM,BOUNDARY_R070_MAIN,NODE
! CM,BOUNDARY_R066_REAR,NODE
! CM,BOUNDARY_R070_REAR,NODE

! Boundary condition intent:
! Use remote section nodes at R066/R070 to remove rigid body motion only.
! Do not fully clamp the local bay unless running a deliberately conservative bracket.

! Load application intent:
! CMSEL,S,MAIN_COLLAR_R068
! F,ALL,FZ,F_MAIN_TOTAL_R068_N
! CMSEL,S,REAR_COLLAR_R068
! F,ALL,FZ,F_REAR_TOTAL_R068_N
! ALLSEL,ALL

! Required postprocessing:
! - adhesive shear and peel margin
! - collar bearing margin
! - tube wall crush/ovalization margin
! - rib cap/web shear transfer margin
! - optional skin sag deflection margin
FINISH
"""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _mapping_at(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _float(value: Any) -> float:
    if value in (None, ""):
        raise ValueError("expected finite numeric value")
    return float(value)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _round(value: float | None, ndigits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), ndigits)


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _sort_rib_ids(values: Sequence[str]) -> list[str]:
    def key(value: str) -> int:
        text = value.strip().upper().removeprefix("R")
        return int(text)

    return sorted(values, key=key)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    args = parser.parse_args(argv)

    paths = write_positive_zone_validation_package(
        output_dir=args.output_dir,
        report_json=args.report_json,
        report_md=args.report_md,
    )
    for key, path in paths.items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
