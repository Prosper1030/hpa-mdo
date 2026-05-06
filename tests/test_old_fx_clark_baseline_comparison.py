from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "rerun_old_fx_clark_comparison_with_tier2.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "rerun_old_fx_clark_comparison_with_tier2",
        _SCRIPT_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_required_cl_and_power_math_use_current_mission_contract() -> None:
    module = _load_script_module()

    cl_required = module.compute_required_cl(
        weight_n=965.955025,
        density_kgpm3=1.135669,
        velocity_mps=6.6,
        sref_m2=35.175,
    )
    cd0 = module.compute_cd0_total_est(
        profile_cd=0.010,
        cda_nonwing_m2=0.13,
        sref_m2=35.175,
    )

    assert cl_required == pytest.approx(1.1102304984748252)
    assert cd0 == pytest.approx(0.013695806680881308)


def test_blackcat_avl_parser_detects_fx_inboard_and_clark_tip() -> None:
    module = _load_script_module()

    geometry = module.parse_wing_geometry_from_avl(
        _REPO_ROOT / "data" / "blackcat_004_full.avl"
    )

    assert geometry.sref_m2 == pytest.approx(35.175)
    assert geometry.bref_m == pytest.approx(33.0)
    assert len(geometry.sections) == 6
    assert geometry.sections[0].airfoil_id == "fx76mp140"
    assert geometry.sections[-1].airfoil_id == "clarkysm"
    assert geometry.sections[-1].eta == pytest.approx(1.0)


def test_tier2_hook_reuses_pre_tier2_avl_result_by_default() -> None:
    module = _load_script_module()

    reuse_path = module.resolve_avl_reuse_path(
        profile_db="tier2",
        reuse_avl_results=None,
    )
    pre_tier2_reuse = (
        _REPO_ROOT
        / "output"
        / "baseline_comparisons"
        / "old_fx_clark_vs_phase7_pre_tier2"
        / "old_design_avl_results.json"
    )

    assert reuse_path == pre_tier2_reuse
    assert module.resolve_avl_reuse_path(
        profile_db="pre_tier2",
        reuse_avl_results=None,
    ) is None


def test_pre_tier2_record_loader_supports_archive_record_dict() -> None:
    module = _load_script_module()

    records = module._load_pre_tier2_records(
        _REPO_ROOT
        / "output"
        / "airfoil_db"
        / "full_polar_archive"
        / "full_polar_build_report.json"
    )

    assert records["fx76mp140"]["safe_clmax"] == pytest.approx(1.4854704323985415)
    assert records["clarkysm"]["source_quality"] == "full_polar_mission_grade_candidate"


def test_policy_loader_supports_phase7_dual_baseline_schema() -> None:
    module = _load_script_module()

    rows = module._load_policy_rows(_REPO_ROOT / "phase7_dual_baseline" / "dual_baseline_summary.csv")

    assert rows["Policy A / D"]["policy_id"] == "A"
    assert rows["Policy C / E"]["policy_id"] == "C"


def test_phase7_geometry_loader_supports_current_manifest_schema() -> None:
    module = _load_script_module()

    geometry = module._load_phase7_geometry("policy_A_performance_candidate")

    assert geometry["sref_m2"] == pytest.approx(33.420058469)
    assert geometry["span_m"] == pytest.approx(34.332285818)
