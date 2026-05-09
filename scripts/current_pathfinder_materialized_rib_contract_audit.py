#!/usr/bin/env python3
"""Materialized rib station/bay contract audit for the current pathfinder.

This runner does not tune hybrid rib stiffness. It freezes the current balsa
screening basis into a station/bay trace and marks the missing shape, bond,
collar, and local FEM evidence that must precede any hybrid pass claim.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

import numpy as np
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.phase15_candidate_load_factor_buckling_check import CANDIDATE_ID  # noqa: E402
from scripts.phase19_local_load_path_ledger import (  # noqa: E402
    load_current_spar_rows,
    load_current_wire_rigging,
)
from scripts.phase22_bracing_sensitivity import build_current_candidate_model  # noqa: E402
from scripts.phase24_rib_spacing_requirements import (  # noqa: E402
    RibSpacingRequirements,
    build_current_rib_spacing_requirements,
)


DEFAULT_SELECTED_BASIS_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_aware_rib_rear_spar_sensitivity.json"
)
DEFAULT_AEROELASTIC_CLOSURE_JSON = (
    REPO_ROOT / "docs" / "reports" / "2026-05-09_tail_aware_aeroelastic_closure.json"
)
DEFAULT_CONFIG = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "current_avl_compromise_conservative_closed_z_boundary"
    / "smooth_tier2_canonical_config.yaml"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "current_pathfinder_materialized_rib_contract_audit"
DEFAULT_REPORT_MD = (
    REPO_ROOT
    / "docs"
    / "reports"
    / "2026-05-09_current_pathfinder_materialized_rib_contract_audit.md"
)

SCHEMA_VERSION = "current_pathfinder_materialized_rib_contract_audit_v1"
OVERALL_VERDICT = "blocked_needs_materialized_bond_shape_data"
LOCAL_FEM_VERDICT = "local_fem_required_before_hybrid_pass_claim"
TORQUE_ZONE_RULE = "torque_critical_audit_zone"
TARGET_TWIST_BOUND_DEG = 3.0


def build_current_materialized_rib_contract_audit(
    *,
    selected_basis_json: Path = DEFAULT_SELECTED_BASIS_JSON,
    aeroelastic_closure_json: Path = DEFAULT_AEROELASTIC_CLOSURE_JSON,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Build the current pathfinder materialized rib contract audit payload."""

    selected_payload = _read_json(Path(selected_basis_json))
    selected_rib_basis = _selected_rib_basis(selected_payload)
    closure_payload = _read_json(Path(aeroelastic_closure_json))
    twist_basis = _twist_source_basis(closure_payload)
    spacing_requirements = build_current_rib_spacing_requirements()
    spar_rows = load_current_spar_rows()
    wire_rigging = load_current_wire_rigging()
    model = build_current_candidate_model()
    config = _read_yaml(Path(config_path))

    half_stations = _recommended_half_wing_stations(spacing_requirements)
    full_station_y = _mirror_half_stations(half_stations)
    mandatory_reason_by_y = _mandatory_reasons_by_positive_y(spar_rows, wire_rigging)
    station_mass = _scaled_full_wing_station_masses(
        full_station_y_m=full_station_y,
        selected_rib_basis=selected_rib_basis,
        config=config,
    )

    torque_zone_half_width_m = float(selected_rib_basis["spacing_m"])
    station_rows = _build_station_table(
        full_station_y_m=full_station_y,
        station_mass_kg=station_mass,
        selected_rib_basis=selected_rib_basis,
        mandatory_reason_by_y=mandatory_reason_by_y,
        model=model,
        config=config,
        twist_basis=twist_basis,
        torque_zone_half_width_m=torque_zone_half_width_m,
    )
    bay_rows = _build_bay_table(
        station_rows,
        config=config,
        selected_rib_basis=selected_rib_basis,
        twist_basis=twist_basis,
        torque_zone_half_width_m=torque_zone_half_width_m,
    )
    mandatory_rows = _build_mandatory_reason_rows(station_rows)
    skin_sag_rows = _build_skin_sag_rows(bay_rows)
    bond_rows = _build_bond_collar_rows(station_rows)
    rib_type_rows = _build_rib_type_rows(station_rows, selected_rib_basis)
    local_fem_report = _build_local_fem_trigger_report(
        station_rows=station_rows,
        bay_rows=bay_rows,
        selected_rib_basis=selected_rib_basis,
        twist_basis=twist_basis,
        torque_zone_half_width_m=torque_zone_half_width_m,
    )

    max_bay = max((float(row["bay_length_m"]) for row in bay_rows), default=0.0)
    material_role = classify_rib_material_structural_role(
        {
            "family_key": selected_rib_basis["family_key"],
            "family_category": _mapping_at(selected_rib_basis, "material_basis").get(
                "family_category",
                "",
            ),
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate_id": CANDIDATE_ID,
        "overall_verdict": OVERALL_VERDICT,
        "claim_boundary": (
            "Materialized station/bay audit only. This is not hybrid rib closure, "
            "not skin sag signoff, not bond/collar/tube-wall margin, and not FEM/APDL signoff."
        ),
        "selected_rib_basis": selected_rib_basis,
        "selected_material_role": material_role,
        "station_bay_trace": {
            "half_wing_station_count": len(half_stations),
            "full_wing_station_count": len(full_station_y),
            "full_wing_bay_count": len(bay_rows),
            "target_spacing_m": float(selected_rib_basis["spacing_m"]),
            "max_materialized_bay_m": round(float(max_bay), 6),
            "target_spacing_materialized": bool(
                max_bay <= float(selected_rib_basis["spacing_m"]) + 1.0e-9
            ),
            "trace_status": "physical_rib_stations_materialized",
        },
        "twist_blocker": twist_basis,
        "rib_station_table": station_rows,
        "rib_bay_table": bay_rows,
        "mandatory_rib_reason": mandatory_rows,
        "rib_type_by_station": rib_type_rows,
        "skin_sag_screening": skin_sag_rows,
        "bond_collar_risk_screening": bond_rows,
        "local_fem_trigger_report": local_fem_report,
        "engineering_read": (
            "The 0.30 m bay is materialized by physical ribs/stations, but the next "
            "hybrid stiffness sweep remains blocked by unknown skin sag, bond/collar/"
            "spar-contact detail, and local FEM evidence near the torque-critical station."
        ),
    }


def write_materialized_rib_contract_audit_package(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_md_path: Path = DEFAULT_REPORT_MD,
    selected_basis_json: Path = DEFAULT_SELECTED_BASIS_JSON,
    aeroelastic_closure_json: Path = DEFAULT_AEROELASTIC_CLOSURE_JSON,
    config_path: Path = DEFAULT_CONFIG,
) -> dict[str, Path]:
    """Build and write the materialized rib contract audit artifacts."""

    audit = build_current_materialized_rib_contract_audit(
        selected_basis_json=Path(selected_basis_json),
        aeroelastic_closure_json=Path(aeroelastic_closure_json),
        config_path=Path(config_path),
    )
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "rib_station_table_csv": output_dir / "rib_station_table.csv",
        "rib_bay_table_csv": output_dir / "rib_bay_table.csv",
        "mandatory_rib_reason_csv": output_dir / "mandatory_rib_reason.csv",
        "rib_type_by_station_csv": output_dir / "rib_type_by_station.csv",
        "skin_sag_screening_csv": output_dir / "skin_sag_screening.csv",
        "bond_collar_risk_screening_csv": output_dir / "bond_collar_risk_screening.csv",
        "local_fem_trigger_report_json": output_dir / "local_fem_trigger_report.json",
        "audit_json": output_dir / "materialized_rib_contract_audit.json",
        "report_md": Path(report_md_path),
    }
    _write_csv(paths["rib_station_table_csv"], audit["rib_station_table"])
    _write_csv(paths["rib_bay_table_csv"], audit["rib_bay_table"])
    _write_csv(paths["mandatory_rib_reason_csv"], audit["mandatory_rib_reason"])
    _write_csv(paths["rib_type_by_station_csv"], audit["rib_type_by_station"])
    _write_csv(paths["skin_sag_screening_csv"], audit["skin_sag_screening"])
    _write_csv(paths["bond_collar_risk_screening_csv"], audit["bond_collar_risk_screening"])
    _write_json(paths["local_fem_trigger_report_json"], audit["local_fem_trigger_report"])
    _write_json(paths["audit_json"], audit)
    paths["report_md"].parent.mkdir(parents=True, exist_ok=True)
    paths["report_md"].write_text(_render_markdown(audit, paths), encoding="utf-8")
    return paths


def classify_rib_material_structural_role(material_basis: Mapping[str, Any]) -> dict[str, str]:
    """Classify whether a rib family may take structural bracing credit."""

    family_key = str(material_basis.get("family_key", ""))
    category = str(material_basis.get("family_category", ""))
    category_l = category.lower()
    family_l = family_key.lower()
    if category_l.endswith("foam_only") or "foam_only" in category_l:
        return {
            "family_key": family_key,
            "family_category": category,
            "structural_bracing_credit": "not_allowed",
            "allowed_use": "shape_core_riblet_or_skin_support_only",
            "engineering_note": (
                "Foam-only EPS/XPS/structural foam rows may support shape or skin, "
                "but cannot be promoted to structural bracing pass without caps/faces/"
                "coupons and local FEM."
            ),
        }
    if "eps" in family_l and "hybrid" not in category_l and "cap" not in category_l:
        return {
            "family_key": family_key,
            "family_category": category,
            "structural_bracing_credit": "not_allowed",
            "allowed_use": "shape_core_riblet_or_skin_support_only",
            "engineering_note": (
                "EPS without explicit cap/face/balsa hybrid detail is treated as foam-only."
            ),
        }
    if "hybrid" in category_l or "cap" in category_l or "face" in category_l:
        return {
            "family_key": family_key,
            "family_category": category,
            "structural_bracing_credit": "candidate_only_not_pass",
            "allowed_use": "next_hybrid_stiffness_sweep_candidate",
            "engineering_note": (
                "Hybrid families are candidates for rerun, not closure results from this audit."
            ),
        }
    return {
        "family_key": family_key,
        "family_category": category,
        "structural_bracing_credit": "screening_baseline_not_final_signoff",
        "allowed_use": "current_screening_baseline",
        "engineering_note": (
            "Current balsa screening baseline can carry the materialized audit trace, "
            "but still needs local shape, bond, collar, and FEM closure."
        ),
    }


def _selected_rib_basis(payload: Mapping[str, Any]) -> dict[str, Any]:
    rib_basis = _mapping_at(payload, "rib_basis")
    if not rib_basis:
        raise ValueError("selected basis JSON does not contain rib_basis.")
    selected = _mapping_at(payload, "selected_basis")
    return {
        "family_key": str(rib_basis["family_key"]),
        "spacing_m": float(rib_basis["spacing_m"]),
        "max_recommended_subbay_m": float(rib_basis["max_recommended_subbay_m"]),
        "half_wing_station_count": int(rib_basis["half_wing_station_count"]),
        "full_wing_rib_count": int(rib_basis["full_wing_rib_count"]),
        "estimated_full_wing_rib_mass_kg": float(rib_basis["estimated_full_wing_rib_mass_kg"]),
        "estimated_rib_pack_cg_x_m": float(rib_basis["estimated_rib_pack_cg_x_m"]),
        "warping_knockdown": float(rib_basis["warping_knockdown"]),
        "rear_spar_participation": str(selected.get("rear_spar_participation", "")),
        "rear_stiffness_scale": float(selected.get("rear_stiffness_scale", 0.50)),
        "material_basis": dict(_mapping_at(rib_basis, "material_basis")),
        "mass_model": str(rib_basis.get("mass_model", "")),
        "basis_read": str(rib_basis.get("engineering_read", "")),
    }


def _twist_source_basis(payload: Mapping[str, Any]) -> dict[str, Any]:
    basis = _mapping_at(payload, "basis")
    aero = _mapping_at(basis, "aeroelastic_effects")
    source_audit = _mapping_at(basis, "aeroelastic_twist_source_audit")
    interpretation = _mapping_at(source_audit, "interpretation_summary")
    dominant = _mapping_at(source_audit, "dominant_source_at_direct_max_station")
    direct = _float_or_default(
        interpretation.get("direct_spar_pair_rotation_max_abs_deg"),
        _float_or_default(aero.get("direct_spar_pair_rotation_max_abs_deg"), 0.0),
    )
    bounded = _float_or_default(
        interpretation.get("conservative_bounded_physical_projection_max_abs_deg"),
        _float_or_default(
            aero.get("conservative_bounded_physical_projection_max_abs_deg"),
            direct,
        ),
    )
    peak_y = _float_or_default(
        interpretation.get("direct_spar_pair_rotation_max_station_y_m"),
        0.0,
    )
    twist_bound = _float_or_default(aero.get("elastic_twist_screening_bound_deg"), TARGET_TWIST_BOUND_DEG)
    return {
        "direct_spar_pair_rotation_max_abs_deg": float(direct),
        "conservative_bounded_physical_projection_max_abs_deg": float(bounded),
        "elastic_twist_screening_bound_deg": float(twist_bound),
        "peak_twist_station_y_m": float(peak_y),
        "dominant_twist_source": str(dominant.get("dominant_component", "")),
        "dominant_source_component_twist_deg": dict(dominant.get("component_twist_deg", {})),
        "twist_source_verdict": str(aero.get("twist_source_verdict", "")),
        "closure_verdict": str(payload.get("verdict", payload.get("engineering_verdict", ""))),
        "engineering_read": str(source_audit.get("engineering_read", "")),
    }


def _build_station_table(
    *,
    full_station_y_m: Sequence[float],
    station_mass_kg: Sequence[float],
    selected_rib_basis: Mapping[str, Any],
    mandatory_reason_by_y: Mapping[float, Sequence[str]],
    model,
    config: Mapping[str, Any],
    twist_basis: Mapping[str, Any],
    torque_zone_half_width_m: float,
) -> list[dict[str, Any]]:
    y_values = [float(y) for y in full_station_y_m]
    rows: list[dict[str, Any]] = []
    for idx, y_m in enumerate(y_values):
        abs_y = abs(float(y_m))
        reasons = _reasons_for_y(abs_y, mandatory_reason_by_y)
        in_torque_zone = _in_torque_zone(
            abs_y,
            float(twist_basis["peak_twist_station_y_m"]),
            float(torque_zone_half_width_m),
        )
        fem_reasons = _station_fem_trigger_reasons(reasons, in_torque_zone, twist_basis)
        bay_prev = None if idx == 0 else float(y_values[idx] - y_values[idx - 1])
        bay_next = None if idx == len(y_values) - 1 else float(y_values[idx + 1] - y_values[idx])
        chord = _chord_at_y(config, abs_y)
        main_x = float(np.interp(abs_y, np.asarray(model.y_nodes_m, dtype=float), np.asarray(model.nodes_main_m[:, 0], dtype=float)))
        rear_x = float(np.interp(abs_y, np.asarray(model.y_nodes_m, dtype=float), np.asarray(model.nodes_rear_m[:, 0], dtype=float)))
        row = {
            "rib_id": f"R{idx:03d}",
            "y_m": round(float(y_m), 6),
            "abs_y_m": round(abs_y, 6),
            "chord_m": round(float(chord), 6),
            "rib_type": _rib_type(reasons, in_torque_zone),
            "bay_prev_m": "" if bay_prev is None else round(bay_prev, 6),
            "bay_next_m": "" if bay_next is None else round(bay_next, 6),
            "main_spar_xc": round(main_x / max(chord, 1.0e-12), 6),
            "rear_spar_xc": round(rear_x / max(chord, 1.0e-12), 6),
            "mandatory_reason": ";".join(reasons) if reasons else "",
            "material_family": str(selected_rib_basis["family_key"]),
            "material_family_category": str(_mapping_at(selected_rib_basis, "material_basis").get("family_category", "")),
            "estimated_mass_kg": float(station_mass_kg[idx]),
            "shape_sag_status": (
                "unknown_requires_test_torque_zone" if in_torque_zone else "unknown_requires_test"
            ),
            "bond_risk_status": (
                "needs_data_torque_or_mandatory_zone"
                if in_torque_zone or reasons
                else "needs_data"
            ),
            "local_fem_required": "true" if fem_reasons else "false",
            "fem_trigger_reasons": ";".join(fem_reasons),
            "torque_critical_zone": "true" if in_torque_zone else "false",
        }
        rows.append(row)
    return rows


def _build_bay_table(
    station_rows: Sequence[Mapping[str, Any]],
    *,
    config: Mapping[str, Any],
    selected_rib_basis: Mapping[str, Any],
    twist_basis: Mapping[str, Any],
    torque_zone_half_width_m: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    target = float(selected_rib_basis["spacing_m"])
    for idx, (start, end) in enumerate(zip(station_rows[:-1], station_rows[1:], strict=True)):
        y_start = float(start["y_m"])
        y_end = float(end["y_m"])
        length = abs(y_end - y_start)
        y_mid = 0.5 * (y_start + y_end)
        abs_start = abs(y_start)
        abs_end = abs(y_end)
        chord_mid = _chord_at_y(config, abs(y_mid))
        torque_zone = _bay_intersects_torque_zone(
            abs_start,
            abs_end,
            float(twist_basis["peak_twist_station_y_m"]),
            float(torque_zone_half_width_m),
        )
        endpoint_mandatory = bool(start.get("mandatory_reason") or end.get("mandatory_reason"))
        fem_reasons: list[str] = []
        if torque_zone:
            fem_reasons.append(TORQUE_ZONE_RULE)
        if endpoint_mandatory:
            fem_reasons.append("mandatory_rib_boundary_load_transfer")
        rows.append(
            {
                "bay_id": f"B{idx:03d}",
                "start_rib_id": str(start["rib_id"]),
                "end_rib_id": str(end["rib_id"]),
                "y_start_m": round(y_start, 6),
                "y_end_m": round(y_end, 6),
                "y_mid_m": round(float(y_mid), 6),
                "bay_length_m": round(float(length), 6),
                "target_spacing_m": round(target, 6),
                "chord_mid_m": round(float(chord_mid), 6),
                "bay_length_over_chord": round(float(length / max(chord_mid, 1.0e-12)), 6),
                "materialized_physical_ribs": "true",
                "spacing_status": (
                    "target_spacing_materialized" if length <= target + 1.0e-9 else "exceeds_target_spacing"
                ),
                "shape_sag_status": (
                    "unknown_requires_test_torque_zone" if torque_zone else "unknown_requires_test"
                ),
                "bond_risk_status": (
                    "needs_data_torque_or_mandatory_zone"
                    if torque_zone or endpoint_mandatory
                    else "needs_data"
                ),
                "local_fem_required": "true" if fem_reasons else "false",
                "fem_trigger_reasons": ";".join(fem_reasons),
                "torque_critical_zone": "true" if torque_zone else "false",
            }
        )
    return rows


def _build_mandatory_reason_rows(station_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    materialized_items = (
        ("root", "root"),
        ("tip", "tip_boundary"),
        ("wire_attach", "wire_attach"),
        ("spar_joint", "spar_joint"),
    )
    for contract_item, reason_key in materialized_items:
        matching = [
            row
            for row in station_rows
            if reason_key in str(row.get("mandatory_reason", "")).split(";")
        ]
        rows.append(
            {
                "contract_item": contract_item,
                "status": "materialized_mandatory" if matching else "missing_contract",
                "rib_ids": ";".join(str(row["rib_id"]) for row in matching),
                "y_m": ";".join(f"{float(row['y_m']):.6f}" for row in matching),
                "mandatory_reason": reason_key,
                "source": "current spar rows / wire rigging / mirrored station table",
                "engineering_read": (
                    "Mandatory station is present in the materialized full-wing rib table."
                    if matching
                    else "Required mandatory station class is not present in current artifacts."
                ),
            }
        )
    for contract_item in (
        "transport_joint",
        "control_station",
        "airfoil_transition",
        "twist_transition",
    ):
        rows.append(
            {
                "contract_item": contract_item,
                "status": "missing_contract",
                "rib_ids": "",
                "y_m": "",
                "mandatory_reason": contract_item,
                "source": "no current pathfinder station/control/transition manifest found",
                "engineering_read": (
                    "Explicitly missing. Do not treat the current rib layout as passing this contract."
                ),
            }
        )
    return rows


def _build_skin_sag_rows(bay_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for bay in bay_rows:
        torque = str(bay.get("torque_critical_zone")) == "true"
        reasons = [
            "skin_tension_covering_modulus_pressure_delta_missing",
            "low_order_placeholder_only",
        ]
        if torque:
            reasons.append(TORQUE_ZONE_RULE)
        rows.append(
            {
                "bay_id": bay["bay_id"],
                "y_start_m": bay["y_start_m"],
                "y_end_m": bay["y_end_m"],
                "bay_length_m": bay["bay_length_m"],
                "chord_mid_m": bay["chord_mid_m"],
                "bay_length_over_chord": bay["bay_length_over_chord"],
                "placeholder_method": "low_order_membrane_plate_placeholder_not_calibrated",
                "shape_sag_status": (
                    "unknown_requires_test_torque_zone" if torque else "unknown_requires_test"
                ),
                "risk_reasons": ";".join(reasons),
                "data_needed": "skin material, pre-tension, pressure/suction envelope, rib cap contact, coupon or panel sag test",
            }
        )
    return rows


def _build_bond_collar_rows(station_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for station in station_rows:
        torque_or_mandatory = (
            str(station.get("torque_critical_zone")) == "true"
            or bool(station.get("mandatory_reason"))
        )
        reasons = [
            "bond_allowable_missing",
            "collar_geometry_missing",
            "tube_wall_crush_bearing_margin_missing",
            "spar_contact_detail_missing",
        ]
        if str(station.get("torque_critical_zone")) == "true":
            reasons.append(TORQUE_ZONE_RULE)
        if station.get("mandatory_reason"):
            reasons.append("mandatory_station_load_path")
        rows.append(
            {
                "rib_id": station["rib_id"],
                "y_m": station["y_m"],
                "rib_type": station["rib_type"],
                "mandatory_reason": station["mandatory_reason"],
                "material_family": station["material_family"],
                "bond_risk_status": (
                    "needs_data_torque_or_mandatory_zone"
                    if torque_or_mandatory
                    else "needs_data"
                ),
                "risk_reasons": ";".join(reasons),
                "local_fem_required": station["local_fem_required"],
                "data_needed": "bondline geometry, adhesive/collar material, spar tube wall local model, bearing/crush allowables",
            }
        )
    return rows


def _build_rib_type_rows(
    station_rows: Sequence[Mapping[str, Any]],
    selected_rib_basis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    material_role = classify_rib_material_structural_role(
        {
            "family_key": selected_rib_basis["family_key"],
            "family_category": _mapping_at(selected_rib_basis, "material_basis").get(
                "family_category",
                "",
            ),
        }
    )
    return [
        {
            "rib_id": row["rib_id"],
            "y_m": row["y_m"],
            "rib_type": row["rib_type"],
            "mandatory_reason": row["mandatory_reason"],
            "material_family": row["material_family"],
            "material_structural_role": material_role["structural_bracing_credit"],
            "hybrid_next_step_candidate": (
                "true" if row["local_fem_required"] == "true" else "false"
            ),
            "notes": (
                "Candidate local reinforcement station for hybrid rib stiffness sweep."
                if row["local_fem_required"] == "true"
                else "Materialized spacing rib; still not shape/bond signoff."
            ),
        }
        for row in station_rows
    ]


def _build_local_fem_trigger_report(
    *,
    station_rows: Sequence[Mapping[str, Any]],
    bay_rows: Sequence[Mapping[str, Any]],
    selected_rib_basis: Mapping[str, Any],
    twist_basis: Mapping[str, Any],
    torque_zone_half_width_m: float,
) -> dict[str, Any]:
    station_ids = [
        str(row["rib_id"])
        for row in station_rows
        if str(row.get("local_fem_required")) == "true"
    ]
    bay_ids = [
        str(row["bay_id"])
        for row in bay_rows
        if str(row.get("local_fem_required")) == "true"
    ]
    peak_y = float(twist_basis["peak_twist_station_y_m"])
    zones = [
        _zone_payload(
            "positive_torque_critical_hybrid_reinforcement_zone",
            max(0.0, peak_y - float(torque_zone_half_width_m)),
            peak_y + float(torque_zone_half_width_m),
            station_rows,
            bay_rows,
        ),
        _zone_payload(
            "negative_torque_critical_hybrid_reinforcement_zone",
            -(peak_y + float(torque_zone_half_width_m)),
            -max(0.0, peak_y - float(torque_zone_half_width_m)),
            station_rows,
            bay_rows,
        ),
    ]
    return {
        "schema_version": "local_fem_trigger_report_v1",
        "overall_verdict": LOCAL_FEM_VERDICT,
        "candidate_id": CANDIDATE_ID,
        "selected_rib_family": selected_rib_basis["family_key"],
        "selected_rear_spar_participation": selected_rib_basis["rear_spar_participation"],
        "warping_knockdown": selected_rib_basis["warping_knockdown"],
        "peak_twist_station_y_m": round(peak_y, 6),
        "direct_spar_pair_rotation_max_abs_deg": round(
            float(twist_basis["direct_spar_pair_rotation_max_abs_deg"]),
            6,
        ),
        "conservative_bounded_physical_projection_max_abs_deg": round(
            float(twist_basis["conservative_bounded_physical_projection_max_abs_deg"]),
            6,
        ),
        "elastic_twist_screening_bound_deg": round(
            float(twist_basis["elastic_twist_screening_bound_deg"]),
            6,
        ),
        "dominant_twist_source": twist_basis["dominant_twist_source"],
        "trigger_rules": [
            TORQUE_ZONE_RULE,
            "mandatory_root_tip_wire_spar_joint_detail",
            "skin_sag_unknown_requires_test",
            "bond_collar_spar_contact_needs_data",
            "do_not_tune_warping_knockdown_to_claim_pass",
        ],
        "local_fem_station_ids": station_ids,
        "local_fem_bay_ids": bay_ids,
        "recommended_hybrid_reinforcement_zones": zones,
        "next_sweep_guidance": {
            "use_zones": [zone["zone_id"] for zone in zones],
            "candidate_families": [
                "eps_balsa_cap_hybrid_10mm",
                "structural_foam_glass_face_10mm",
                "balsa_sheet_3mm_with_local_shear_cap_or_collar",
            ],
            "do_not_promote": [
                "eps_hd_foam_cnc_10mm foam-only",
                "xps_high_compressive_cnc_10mm foam-only",
                "structural_foam_cnc_10mm foam-only as bracing pass",
            ],
        },
        "engineering_read": (
            "Peak twist is torque-dominant and the bounded physical projection still "
            "exceeds the 3 deg screening bound. Local rib/spar/bond/collar FEM and "
            "skin-shape evidence are required before a hybrid row can be called closed."
        ),
    }


def _recommended_half_wing_stations(requirements: RibSpacingRequirements) -> tuple[float, ...]:
    stations: set[float] = set()
    for row in requirements.rows:
        stations.add(float(row.start_y_m))
        stations.add(float(row.end_y_m))
        stations.update(float(value) for value in row.recommended_intermediate_y_m)
    return tuple(sorted(stations))


def _mirror_half_stations(half_stations: Sequence[float]) -> tuple[float, ...]:
    positives = [float(y) for y in half_stations if abs(float(y)) > 1.0e-9]
    full = [-y for y in reversed(positives)] + [0.0] + positives
    return tuple(float(y) for y in full)


def _mandatory_reasons_by_positive_y(
    spar_rows: Sequence[Mapping[str, str]],
    wire_rigging: Sequence[Mapping[str, object]],
) -> dict[float, tuple[str, ...]]:
    reasons: dict[float, set[str]] = {}

    def add(y_m: float, reason: str) -> None:
        key = round(float(y_m), 6)
        reasons.setdefault(key, set()).add(reason)

    add(float(spar_rows[0]["Y_Position_m"]), "root")
    add(float(spar_rows[-1]["Y_Position_m"]), "tip_boundary")
    for row in spar_rows:
        y_m = float(row["Y_Position_m"])
        if int(float(row.get("Is_Joint", "0"))):
            add(y_m, "spar_joint")
        if int(float(row.get("Is_Wire_Attach", "0"))):
            add(y_m, "wire_attach")
    for row in wire_rigging:
        if "attach_y_m" in row:
            add(float(row["attach_y_m"]), "wire_attach")

    order = {
        "root": 0,
        "tip_boundary": 1,
        "wire_attach": 2,
        "spar_joint": 3,
    }
    return {
        y_m: tuple(sorted(values, key=lambda value: order.get(value, 99)))
        for y_m, values in reasons.items()
    }


def _reasons_for_y(
    positive_y_m: float,
    mandatory_reason_by_y: Mapping[float, Sequence[str]],
    *,
    tol_m: float = 1.0e-5,
) -> tuple[str, ...]:
    values: set[str] = set()
    for y_ref, reasons in mandatory_reason_by_y.items():
        if abs(float(positive_y_m) - float(y_ref)) <= tol_m:
            values.update(str(reason) for reason in reasons)
    order = {
        "root": 0,
        "tip_boundary": 1,
        "wire_attach": 2,
        "spar_joint": 3,
    }
    return tuple(sorted(values, key=lambda value: order.get(value, 99)))


def _station_fem_trigger_reasons(
    mandatory_reasons: Sequence[str],
    in_torque_zone: bool,
    twist_basis: Mapping[str, Any],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if in_torque_zone:
        reasons.append(TORQUE_ZONE_RULE)
        if (
            float(twist_basis["conservative_bounded_physical_projection_max_abs_deg"])
            > float(twist_basis["elastic_twist_screening_bound_deg"])
        ):
            reasons.append("bounded_physical_twist_exceeds_screening_bound")
    for reason in mandatory_reasons:
        if reason == "root":
            reasons.append("root_load_introduction_detail")
        elif reason == "tip_boundary":
            reasons.append("tip_boundary_airfoil_skin_closure_detail")
        elif reason == "wire_attach":
            reasons.append("wire_attach_local_load_path")
        elif reason == "spar_joint":
            reasons.append("spar_joint_load_transfer")
    return tuple(dict.fromkeys(reasons))


def _rib_type(mandatory_reasons: Sequence[str], in_torque_zone: bool) -> str:
    if mandatory_reasons and in_torque_zone:
        return "mandatory_torque_critical_rib"
    if in_torque_zone:
        return "torque_critical_reinforcement_candidate"
    if mandatory_reasons:
        return "mandatory_contract_rib"
    return "materialized_spacing_rib"


def _in_torque_zone(abs_y_m: float, peak_y_m: float, half_width_m: float) -> bool:
    return abs(float(abs_y_m) - float(peak_y_m)) <= float(half_width_m) + 1.0e-12


def _bay_intersects_torque_zone(
    abs_start_y_m: float,
    abs_end_y_m: float,
    peak_y_m: float,
    half_width_m: float,
) -> bool:
    lo = min(float(abs_start_y_m), float(abs_end_y_m))
    hi = max(float(abs_start_y_m), float(abs_end_y_m))
    zlo = max(0.0, float(peak_y_m) - float(half_width_m))
    zhi = float(peak_y_m) + float(half_width_m)
    return hi >= zlo - 1.0e-12 and lo <= zhi + 1.0e-12


def _zone_payload(
    zone_id: str,
    y_start_m: float,
    y_end_m: float,
    station_rows: Sequence[Mapping[str, Any]],
    bay_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    lo = min(float(y_start_m), float(y_end_m))
    hi = max(float(y_start_m), float(y_end_m))
    station_ids = [
        str(row["rib_id"])
        for row in station_rows
        if lo - 1.0e-12 <= float(row["y_m"]) <= hi + 1.0e-12
    ]
    bay_ids = [
        str(row["bay_id"])
        for row in bay_rows
        if not (float(row["y_end_m"]) < lo - 1.0e-12 or float(row["y_start_m"]) > hi + 1.0e-12)
    ]
    return {
        "zone_id": zone_id,
        "y_start_m": round(float(y_start_m), 6),
        "y_end_m": round(float(y_end_m), 6),
        "station_ids": station_ids,
        "bay_ids": bay_ids,
        "recommended_action": (
            "Run local rib-spar-bond/collar FEM and include this as a hybrid "
            "reinforcement zone in the next stiffness sweep."
        ),
    }


def _scaled_full_wing_station_masses(
    *,
    full_station_y_m: Sequence[float],
    selected_rib_basis: Mapping[str, Any],
    config: Mapping[str, Any],
) -> tuple[float, ...]:
    material_basis = _mapping_at(selected_rib_basis, "material_basis")
    thickness = float(material_basis.get("thickness_m", 0.003))
    density = float(material_basis.get("density_kgpm3", 160.0))
    weights: list[float] = []
    for y_m in full_station_y_m:
        abs_y = abs(float(y_m))
        chord = _chord_at_y(config, abs_y)
        tc = _tc_at_y(config, abs_y)
        side_area = 0.65 * tc * chord * chord
        weights.append(max(side_area * thickness * density * 0.55 * 1.15, 1.0e-12))
    total_weight = sum(weights)
    target_mass = float(selected_rib_basis["estimated_full_wing_rib_mass_kg"])
    scale = target_mass / total_weight if total_weight > 0.0 else 0.0
    masses = [weight * scale for weight in weights]
    if masses:
        masses[-1] += target_mass - sum(masses)
    return tuple(float(value) for value in masses)


def _chord_at_y(config: Mapping[str, Any], y_m: float) -> float:
    wing = _mapping_at(config, "wing")
    schedule = wing.get("chord_schedule")
    if isinstance(schedule, list) and schedule:
        xs = np.asarray([float(row[0]) for row in schedule], dtype=float)
        ys = np.asarray([float(row[1]) for row in schedule], dtype=float)
        return float(np.interp(float(y_m), xs, ys))
    half_span = 0.5 * float(wing["span"])
    root = float(wing["root_chord"])
    tip = float(wing["tip_chord"])
    return float(root + (tip - root) * min(max(float(y_m) / half_span, 0.0), 1.0))


def _tc_at_y(config: Mapping[str, Any], y_m: float) -> float:
    wing = _mapping_at(config, "wing")
    half_span = 0.5 * float(wing["span"])
    root_tc = float(wing.get("airfoil_root_tc", 0.14))
    tip_tc = float(wing.get("airfoil_tip_tc", root_tc))
    return float(root_tc + (tip_tc - root_tc) * min(max(float(y_m) / half_span, 0.0), 1.0))


def _read_json(path: Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be a mapping: {path}")
    return payload


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return payload


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    if not rows:
        path.write_text("", encoding="utf-8")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    return path


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _render_markdown(audit: Mapping[str, Any], paths: Mapping[str, Path]) -> str:
    trace = _mapping_at(audit, "station_bay_trace")
    rib = _mapping_at(audit, "selected_rib_basis")
    fem = _mapping_at(audit, "local_fem_trigger_report")
    missing = [
        row
        for row in audit["mandatory_rib_reason"]
        if row["status"] == "missing_contract"
    ]
    station_local = [
        row
        for row in audit["rib_station_table"]
        if row["local_fem_required"] == "true"
    ]
    bay_local = [
        row
        for row in audit["rib_bay_table"]
        if row["local_fem_required"] == "true"
    ]
    lines = [
        "# Current Pathfinder Materialized Rib Contract Audit",
        "",
        f"Candidate: `{audit['candidate_id']}`",
        f"Verdict: `{audit['overall_verdict']}`",
        f"Local FEM verdict: `{fem['overall_verdict']}`",
        "",
        "## Materialized Trace",
        "",
        f"- rib family: `{rib['family_key']}`; target spacing `{float(rib['spacing_m']):.3f}` m",
        f"- full-wing ribs/stations: `{trace['full_wing_station_count']}`; bays: `{trace['full_wing_bay_count']}`",
        f"- max materialized bay: `{float(trace['max_materialized_bay_m']):.6f}` m",
        f"- full-wing rib mass basis: `{float(rib['estimated_full_wing_rib_mass_kg']):.6f}` kg",
        f"- rear spar participation: `{rib['rear_spar_participation']}`; warping knockdown `{float(rib['warping_knockdown']):.6f}`",
        "",
        "The 0.30 m bay is materialized in the station/bay tables. That does not close skin sag, bond, collar, spar contact, or local FEM margins.",
        "",
        "## Mandatory Contract",
        "",
        "| item | status | y m | ribs |",
        "|---|---|---|---|",
    ]
    for row in audit["mandatory_rib_reason"]:
        lines.append(
            f"| {row['contract_item']} | `{row['status']}` | {row['y_m'] or 'n/a'} | {row['rib_ids'] or 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "Missing contract rows are intentional blockers, not assumed pass states.",
            "",
            "## Torque-Critical Zone",
            "",
            f"- peak twist station y: `{float(fem['peak_twist_station_y_m']):.6f}` m",
            f"- direct / bounded twist: `{float(fem['direct_spar_pair_rotation_max_abs_deg']):.6f}` deg / `{float(fem['conservative_bounded_physical_projection_max_abs_deg']):.6f}` deg",
            f"- screening bound: `{float(fem['elastic_twist_screening_bound_deg']):.3f}` deg",
            f"- dominant source: `{fem['dominant_twist_source']}`",
            f"- local FEM station count: `{len(station_local)}`; local FEM bay count: `{len(bay_local)}`",
            "",
            "Recommended hybrid reinforcement zones:",
            "",
        ]
    )
    for zone in fem["recommended_hybrid_reinforcement_zones"]:
        lines.append(
            f"- `{zone['zone_id']}`: y `{float(zone['y_start_m']):.3f}` to `{float(zone['y_end_m']):.3f}` m; stations `{';'.join(zone['station_ids'])}`"
        )
    lines.extend(
        [
            "",
            "## Shape / Bond Boundary",
            "",
            "- Skin sag is `unknown_requires_test` or `unknown_requires_test_torque_zone`; no bay is marked pass.",
            "- Bond/collar/spar contact is `needs_data`; torque or mandatory stations are elevated risk.",
            "- EPS/XPS foam-only rows remain shape-core/riblet/skin-support references, not structural bracing pass rows.",
            "- Hybrid rib rows are next rerun candidates only; this audit does not claim closure pass.",
            "",
            "## Artifacts",
            "",
        ]
    )
    for label, path in paths.items():
        lines.append(f"- `{label}`: `{path}`")
    lines.extend(
        [
            "",
            "## Engineering Read",
            "",
            str(audit["engineering_read"]),
            "",
            "The next hybrid stiffness sweep should use the torque-critical stations/bays above, plus mandatory root/tip/wire/spar-joint detail zones. Any result that still lacks skin sag evidence, bond/collar/tube-wall allowables, or local FEM should remain blocked or needs-data.",
            "",
        ]
    )
    if missing:
        lines.append("Missing contract items: " + ", ".join(row["contract_item"] for row in missing) + ".")
        lines.append("")
    return "\n".join(lines)


def _mapping_at(mapping: Mapping[str, Any], *path: str) -> dict[str, Any]:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key, {})
    return dict(current) if isinstance(current, Mapping) else {}


def _float_or_default(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-md", type=Path, default=DEFAULT_REPORT_MD)
    parser.add_argument("--selected-basis-json", type=Path, default=DEFAULT_SELECTED_BASIS_JSON)
    parser.add_argument("--aeroelastic-closure-json", type=Path, default=DEFAULT_AEROELASTIC_CLOSURE_JSON)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    paths = write_materialized_rib_contract_audit_package(
        output_dir=args.output_dir,
        report_md_path=args.report_md,
        selected_basis_json=args.selected_basis_json,
        aeroelastic_closure_json=args.aeroelastic_closure_json,
        config_path=args.config,
    )
    for path in paths.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
