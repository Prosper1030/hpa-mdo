from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "validate_smooth_tier2_production_baseline.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "validate_smooth_tier2_production_baseline",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_zone_extreme_work_points_choose_max_cl_by_zone() -> None:
    module = _load_script_module()

    points = module.zone_extreme_work_points(
        spanload=[
            {"eta": 0.10, "chord_m": 1.0, "cl": 1.1},
            {"eta": 0.20, "chord_m": 0.9, "cl": 1.3},
            {"eta": 0.40, "chord_m": 0.8, "cl": 1.2},
            {"eta": 0.70, "chord_m": 0.7, "cl": 1.0},
            {"eta": 0.95, "chord_m": 0.5, "cl": 0.8},
        ],
        assignment={
            "root": "dae31",
            "mid1": "dae31",
            "mid2": "dae31",
            "tip": "tip_cst",
        },
        rho=1.2,
        speed_mps=8.0,
        dynamic_viscosity_pa_s=1.8e-5,
    )

    by_zone = {row["zone"]: row for row in points}
    assert list(by_zone) == ["root", "mid1", "mid2", "tip"]
    assert by_zone["root"]["Cl"] == pytest.approx(1.3)
    assert by_zone["root"]["Re"] == pytest.approx(1.2 * 8.0 * 0.9 / 1.8e-5)
    assert by_zone["tip"]["airfoil_id"] == "tip_cst"


def test_structure_failure_modes_separate_jig_and_spar_mass() -> None:
    module = _load_script_module()

    status = module.structure_feasibility_status(
        structure_row={
            "jig_feasibility_band": "proxy_warning",
            "warning_flags": "negative_unloaded_jig_tip_estimate|above_preferred_deflection_band_proxy",
        },
        selected_tube={
            "ei_pass": True,
            "estimated_full_span_tube_mass_kg": 30.0,
            "current_spar_tube_mass_target_kg": 12.0,
        },
    )

    assert status["structure_proxy_pass"] is False
    assert "jig_shape_driven" in status["failure_modes"]
    assert "stiffness_mass_target_driven" in status["failure_modes"]
    assert status["dominant_blocker"] == "structure"


def test_power_comparison_marks_margin_wins() -> None:
    module = _load_script_module()

    rows = module.power_comparison_rows(
        new_summary={"case_id": "new", "P_crank": 171.0, "P_crank_conservative": 175.0},
        reference_rows=[
            {"case_id": "old_a", "P_crank": "180.0", "P_crank_conservative": "184.0"},
            {"case_id": "old_b", "P_crank": "170.0", "P_crank_conservative": "174.0"},
        ],
    )

    by_case = {row["case_id"]: row for row in rows}
    assert by_case["old_a"]["new_beats_reference_nominal"] is True
    assert by_case["old_a"]["new_beats_reference_with_5pct_CDi_margin"] is True
    assert by_case["old_b"]["new_beats_reference_nominal"] is False
