from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "tail_aware_aeroelastic_closure.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "tail_aware_aeroelastic_closure",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_final_cg_gate_requires_committed_rebalance_not_uncompensated_aft_cg() -> None:
    module = _load_script_module()

    gate = module.assess_final_cg_management(
        {
            "cg_impact": {
                "cg_range_x_m": [0.68, 0.75],
                "final_screening_cg_x_m": 0.75,
                "uncompensated_cg_x_m": 0.801026,
                "required_forward_rebalance_m": 0.091302,
                "forward_rebalance_mass_kg": 56.0,
                "screening_status": "final_cg_screening_row_remains_available_with_rebalance",
            }
        }
    )

    assert gate["status"] == "managed_final_cg_pass"
    assert gate["final_cg_x_m"] == pytest.approx(0.75)
    assert gate["uncompensated_cg_status"] == "explicitly_rejected"
    assert gate["required_forward_rebalance_m"] == pytest.approx(0.091302)


def test_elastic_twist_rows_use_main_rear_loaded_spar_pair_rotation() -> None:
    module = _load_script_module()

    y = np.asarray([0.0, 1.0])
    main_nodes = np.asarray([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    rear_nodes = np.asarray([[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
    disp_main = np.zeros((2, 6))
    disp_rear = np.zeros((2, 6))
    disp_rear[1, 2] = 0.10

    rows, summary = module.elastic_twist_distribution_rows(
        y_nodes_m=y,
        nodes_main_m=main_nodes,
        nodes_rear_m=rear_nodes,
        disp_main_m=disp_main,
        disp_rear_m=disp_rear,
        trim_alpha_deg=1.5,
    )

    assert rows[0]["elastic_twist_deg"] == pytest.approx(0.0)
    assert rows[1]["elastic_twist_deg"] == pytest.approx(np.degrees(np.arctan2(0.10, 1.0)))
    assert rows[1]["alpha_eff_deg"] == pytest.approx(1.5 + rows[1]["elastic_twist_deg"])
    assert summary["elastic_twist_max_abs_deg"] == pytest.approx(rows[1]["elastic_twist_deg"])


def test_structural_load_rescale_uses_avl_ratio_with_relaxation_and_bounds() -> None:
    module = _load_script_module()

    scaled_lift, scaled_torque, diagnostics = module.rescale_structural_loads_by_avl_ratio(
        model_y_m=np.asarray([0.0, 1.0, 2.0]),
        baseline_structural_lift_npm=np.asarray([0.0, 100.0, 100.0]),
        baseline_structural_torque_nmpm=np.asarray([0.0, -20.0, -20.0]),
        avl_y_m=np.asarray([0.0, 1.0, 2.0]),
        baseline_avl_lift_npm=np.asarray([10.0, 10.0, 10.0]),
        updated_avl_lift_npm=np.asarray([10.0, 14.0, 24.0]),
        relaxation=0.5,
        ratio_bounds=(0.5, 1.5),
    )

    assert scaled_lift == pytest.approx([0.0, 120.0, 125.0])
    assert scaled_torque == pytest.approx([0.0, -24.0, -25.0])
    assert diagnostics["max_relaxed_ratio"] == pytest.approx(1.25)
    assert diagnostics["max_raw_ratio"] == pytest.approx(2.4)
    assert diagnostics["ratio_clipped"]


def test_closure_verdict_ready_requires_tail_trim_cg_load_mass_and_ranking() -> None:
    module = _load_script_module()

    ready = module.classify_aeroelastic_closure(
        {
            "coupling": {"converged": True},
            "cg_management": {"status": "managed_final_cg_pass"},
            "trim_static_directional": {
                "status": "pass",
                "delta_H_margin_to_limit_deg": 4.2,
                "static_margin": 0.081,
                "C_n_beta": 0.016,
                "delta_V_margin_to_limit_deg": 15.0,
            },
            "aeroelastic_effects": {
                "elastic_twist_max_abs_deg": 0.42,
                "stall_margin_min": 0.18,
                "root_bending_moment_ratio_loaded_vs_baseline": 1.03,
                "closure_ranking_effect": "no_change_conservative_best_remains_screening_closed",
            },
            "selected_stiffness_basis": {"status": "pass_screening_sensitivity"},
            "mass_drag_power": {"status": "charged_to_screening_read"},
            "load_remap_diagnostics": {"status": "conserved"},
        }
    )
    assert ready["verdict"] == "ready_for_fem_apdl_loadcase_package"
    assert ready["warnings"] == []

    not_ready = module.classify_aeroelastic_closure(
        {
            **ready["basis"],
            "aeroelastic_effects": {
                **ready["basis"]["aeroelastic_effects"],
                "closure_ranking_effect": "ranking_changed_by_aeroelastic_loads",
            },
        }
    )
    assert not_ready["verdict"] == "needs_aeroelastic_geometry_or_stiffness_rework"
    assert "aeroelastic_loads_change_closure_ranking" in not_ready["blockers"]


def test_negative_diagnostic_stall_margin_is_reported_but_not_a_hard_closure_gate() -> None:
    module = _load_script_module()

    result = module.classify_aeroelastic_closure(
        {
            "coupling": {"converged": True},
            "cg_management": {"status": "managed_final_cg_pass"},
            "trim_static_directional": {
                "status": "pass",
                "delta_H_margin_to_limit_deg": 4.2,
                "static_margin": 0.081,
                "C_n_beta": 0.016,
                "delta_V_margin_to_limit_deg": 15.0,
            },
            "aeroelastic_effects": {
                "elastic_twist_max_abs_deg": 0.42,
                "stall_margin_min": -0.08,
                "root_bending_moment_ratio_loaded_vs_baseline": 1.03,
                "closure_ranking_effect": "no_change_conservative_best_remains_screening_closed",
            },
            "selected_stiffness_basis": {"status": "pass_screening_sensitivity"},
            "mass_drag_power": {"status": "charged_to_screening_read"},
            "load_remap_diagnostics": {"status": "conserved"},
        }
    )

    assert result["verdict"] == "ready_for_fem_apdl_loadcase_package"
    assert result["warnings"] == ["negative_diagnostic_stall_margin_not_gate"]
