from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_materialized_rib_contract_audit.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_materialized_rib_contract_audit",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_current_audit_materializes_full_wing_station_and_bay_trace() -> None:
    module = _load_script_module()

    audit = module.build_current_materialized_rib_contract_audit()

    assert audit["candidate_id"] == "current_avl_compromise_conservative_closed"
    assert audit["selected_rib_basis"]["family_key"] == "balsa_sheet_3mm"
    assert audit["selected_rib_basis"]["full_wing_rib_count"] == 121
    assert len(audit["rib_station_table"]) == 121
    assert len(audit["rib_bay_table"]) == 120
    assert audit["station_bay_trace"]["full_wing_station_count"] == 121
    assert audit["station_bay_trace"]["max_materialized_bay_m"] == pytest.approx(
        0.297063,
        abs=5.0e-7,
    )
    assert audit["station_bay_trace"]["max_materialized_bay_m"] <= 0.30

    required_columns = {
        "rib_id",
        "y_m",
        "chord_m",
        "rib_type",
        "bay_prev_m",
        "bay_next_m",
        "main_spar_xc",
        "rear_spar_xc",
        "mandatory_reason",
        "material_family",
        "estimated_mass_kg",
        "shape_sag_status",
        "bond_risk_status",
        "local_fem_required",
        "fem_trigger_reasons",
    }
    assert required_columns <= set(audit["rib_station_table"][0])
    assert sum(float(row["estimated_mass_kg"]) for row in audit["rib_station_table"]) == pytest.approx(
        3.029671,
        rel=2.0e-6,
    )


def test_mandatory_ribs_are_identified_and_missing_contracts_are_explicit() -> None:
    module = _load_script_module()

    audit = module.build_current_materialized_rib_contract_audit()
    mandatory = audit["mandatory_rib_reason"]
    by_item = {row["contract_item"]: row for row in mandatory}

    assert by_item["root"]["status"] == "materialized_mandatory"
    assert by_item["tip"]["status"] == "materialized_mandatory"
    assert by_item["wire_attach"]["status"] == "materialized_mandatory"
    assert by_item["spar_joint"]["status"] == "materialized_mandatory"
    assert by_item["transport_joint"]["status"] == "missing_contract"
    assert by_item["control_station"]["status"] == "missing_contract"
    assert by_item["airfoil_transition"]["status"] == "missing_contract"
    assert by_item["twist_transition"]["status"] == "missing_contract"
    assert audit["overall_verdict"] in {
        "blocked_needs_materialized_bond_shape_data",
        "needs_data_before_hybrid_stiffness_rework",
    }


def test_peak_twist_station_becomes_torque_critical_local_fem_zone() -> None:
    module = _load_script_module()

    audit = module.build_current_materialized_rib_contract_audit()
    fem_report = audit["local_fem_trigger_report"]

    assert fem_report["peak_twist_station_y_m"] == pytest.approx(2.328, abs=5.0e-3)
    assert fem_report["dominant_twist_source"] == "aerodynamic_torque_only"
    assert fem_report["overall_verdict"] == "local_fem_required_before_hybrid_pass_claim"
    assert "torque_critical_audit_zone" in fem_report["trigger_rules"]
    assert fem_report["recommended_hybrid_reinforcement_zones"]

    torque_station_rows = [
        row
        for row in audit["rib_station_table"]
        if "torque_critical_audit_zone" in row["fem_trigger_reasons"]
    ]
    assert torque_station_rows
    assert any(abs(abs(float(row["y_m"])) - 2.328) <= 0.30 for row in torque_station_rows)
    assert all(row["local_fem_required"] == "true" for row in torque_station_rows)


def test_shape_and_bond_screening_do_not_silently_pass_or_promote_foam_only() -> None:
    module = _load_script_module()

    audit = module.build_current_materialized_rib_contract_audit()

    sag_statuses = {row["shape_sag_status"] for row in audit["skin_sag_screening"]}
    bond_statuses = {row["bond_risk_status"] for row in audit["bond_collar_risk_screening"]}
    assert sag_statuses <= {"unknown_requires_test", "unknown_requires_test_torque_zone"}
    assert bond_statuses <= {"needs_data", "needs_data_torque_or_mandatory_zone"}
    assert "pass" not in sag_statuses
    assert "pass" not in bond_statuses

    eps_role = module.classify_rib_material_structural_role(
        {
            "family_key": "eps_hd_foam_cnc_10mm",
            "family_category": "eps_foam_only",
        }
    )
    assert eps_role["structural_bracing_credit"] == "not_allowed"
    assert eps_role["allowed_use"] == "shape_core_riblet_or_skin_support_only"
