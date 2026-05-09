from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = (
    _REPO_ROOT / "scripts" / "current_pathfinder_positive_torque_zone_validation_package.py"
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_positive_torque_zone_validation_package",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_builds_positive_zone_contract_from_current_artifacts() -> None:
    module = _load_script_module()

    package = module.build_positive_zone_validation_package()

    assert package["package_verdict"] == (
        "positive_zone_ready_for_local_FEM_and_coupon_definition_not_margin_pass"
    )
    assert package["fem_margin_status"] == "not_run"
    assert package["selected_basis"]["rib_family"] == "eps_balsa_cap_hybrid_10mm"
    assert package["selected_basis"]["rear_spar_participation"] == "bounded_65pct_screening"
    assert package["closure_evidence"]["bounded_physical_twist_deg"] == pytest.approx(2.070316)
    assert package["closure_evidence"]["direct_spar_pair_stress_test_deg"] == pytest.approx(
        3.449294
    )
    assert "direct_spar_pair_stress_test_above_bound_conservative_mapping" in package["warnings"]

    zone = package["positive_zone"]
    assert zone["zone_id"] == "positive_torque_critical_hybrid_reinforcement_zone"
    assert zone["critical_station_id"] == "R068"
    assert zone["rib_ids"] == ["R067", "R068", "R069"]
    assert zone["bay_ids"] == ["B066", "B067", "B068", "B069"]
    assert zone["local_model_boundary_rib_ids"] == ["R066", "R067", "R068", "R069", "R070"]
    assert zone["critical_y_m"] == pytest.approx(2.327757, abs=5.0e-4)


def test_local_load_decomposition_maps_torque_to_collar_couple() -> None:
    module = _load_script_module()

    package = module.build_positive_zone_validation_package()

    load_rows = package["local_load_decomposition"]["station_load_rows"]
    critical = next(row for row in load_rows if row["rib_id"] == "R068")
    assert critical["aero_torque_component_direct_twist_deg"] == pytest.approx(4.787163)
    assert critical["kernel_lift_main_fz_n"] > 0.0
    assert critical["kernel_torque_my_nm"] < 0.0
    assert critical["local_torque_couple_main_fz_n"] == pytest.approx(
        -critical["local_torque_couple_rear_fz_n"]
    )
    assert critical["local_torque_couple_rear_fz_n"] > 0.0
    assert critical["local_total_main_fz_n"] == pytest.approx(
        critical["kernel_lift_main_fz_n"]
        + critical["kernel_main_self_weight_fz_n"]
        + critical["local_torque_couple_main_fz_n"]
    )
    assert package["local_load_decomposition"]["method"]["torque_to_couple_formula"] == (
        "F_couple_N = M_y_Nm / spar_separation_m; apply +F at main spar and -F at rear spar"
    )


def test_coupon_matrix_and_missing_data_register_keep_package_from_claiming_pass() -> None:
    module = _load_script_module()

    package = module.build_positive_zone_validation_package()

    coupon_ids = {row["coupon_id"] for row in package["coupon_test_matrix"]}
    assert {
        "C01_eps_balsa_cap_shear_transfer",
        "C02_main_spar_bond_shear",
        "C03_rear_spar_bond_shear",
        "C04_bond_peel",
        "C05_collar_bearing",
        "C06_tube_wall_crush_ovalization",
    } <= coupon_ids
    assert all(row["pass_status"] == "not_tested" for row in package["coupon_test_matrix"])

    missing = {row["data_key"]: row for row in package["missing_data_register"]}
    assert missing["adhesive_shear_allowable_pa"]["required_for"] == "rib-to-spar bond shear"
    assert missing["spar_tube_od_wall_material"]["required_for"] == (
        "collar bearing and local tube wall crush/ovalization"
    )
    assert package["next_blocker_if_not_closed"] == (
        "supplier/coupon allowables and collar/tube-wall detail are still missing; "
        "do not export a FEM/APDL margin package until these values replace guarded placeholders"
    )


def test_write_package_creates_runner_outputs(tmp_path: Path) -> None:
    module = _load_script_module()

    paths = module.write_positive_zone_validation_package(output_dir=tmp_path)

    expected = {
        "package_json",
        "package_md",
        "station_manifest_csv",
        "bay_manifest_csv",
        "load_decomposition_csv",
        "coupon_matrix_csv",
        "missing_data_register_csv",
        "apdl_skeleton",
    }
    assert expected <= set(paths)
    for key in expected:
        assert paths[key].exists(), key

    deck = paths["apdl_skeleton"].read_text(encoding="utf-8")
    assert "positive_torque_zone_local_fem_skeleton" in deck
    assert "M_TORQUE_CRITICAL_NM" in deck
    assert "SUPPLIER_DATA_REQUIRED" in deck

    report = paths["package_md"].read_text(encoding="utf-8")
    assert "R067 / R068 / R069" in report
    assert "B066 / B067 / B068 / B069" in report
    assert "No FEM margin is claimed" in report
