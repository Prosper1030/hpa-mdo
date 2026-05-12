from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "current_pathfinder_p1_load_path_mass_closure.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "current_pathfinder_p1_load_path_mass_closure", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path: Path) -> tuple[dict, dict]:
    mod = _load_module()
    paths = mod.write_p1_load_path_mass_closure_package(
        output_dir=tmp_path / "output",
        report_json=tmp_path / "report.json",
        report_md=tmp_path / "report.md",
    )
    return json.loads(paths["report_json"].read_text()), paths


def test_outputs_written(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    for key, path in paths.items():
        assert path.exists(), f"missing output {key}: {path}"


def test_c04_fix_closes_local_load_path_for_coupon_fem(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    local = summary["local_load_path"]

    assert summary["final_verdict"] == "p1_local_load_path_ready_for_coupon_fem"
    assert local["station_y_m"] == pytest.approx(2.327757, abs=1.0e-3)
    assert local["baseline_c04_margin"] < 0.0
    assert local["installed_fix_type"] == "saddle_ring_yoke_plus_secondary_clamp"
    assert local["installed_fix_governing_margin"] > 0.0
    assert local["c04_status"] == "pass_with_saddle_ring_yoke_fix"
    assert local["claim_boundary"] == "local_surrogate_ready_for_coupon_and_local_fem"


def test_splice_and_collar_fix_mass_are_integrated_into_cg(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    mass = summary["mass_integration"]
    cg = summary["mass_cg_tail_closure"]["cg_management"]

    assert mass["additional_masses_kg"]["spar_splice_full_wing"] == pytest.approx(3.847)
    assert 0.05 < mass["additional_masses_kg"]["p1_c04_fix_full_wing"] < 0.25
    names = {item["name"] for item in mass["integrated_mass_items"]}
    assert "spar_splice_transport_joint_pack" in names
    assert "p1_c04_saddle_ring_yoke_clamp_pair" in names
    assert cg["status"] == "managed_final_cg_pass"
    assert cg["required_forward_rebalance_m"] <= cg["forward_rebalance_limit_m"]
    assert (
        summary["mass_cg_tail_closure"]["mass_drag_power"][
            "total_screening_mass_after_integrated_items_kg"
        ]
        == pytest.approx(mass["updated_total_mass_after_items_kg"])
    )


def test_tail_and_calibrated_closure_remain_inside_screening_bounds(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    closure = summary["mass_cg_tail_closure"]

    assert closure["source_closure_verdict"] == "ready_for_fem_apdl_loadcase_package"
    assert closure["updated_closure_verdict"] == "ready_for_fem_apdl_loadcase_package"
    assert closure["trim_static_directional"]["status"] == "pass"
    assert closure["aeroelastic_effects"]["conservative_bounded_physical_projection_max_abs_deg"] < 3.0
    assert closure["closure_ranking_effect"] == "no_change_conservative_best_remains_screening_closed"


def test_qprop_xrotor_stays_independent_propulsion_lane(tmp_path: Path) -> None:
    summary, _ = _run(tmp_path)
    policy = summary["propulsion_lane_policy"]

    assert policy["qprop_xrotor_role"] == "independent_propulsion_lane_only"
    assert policy["used_in_structural_blocker_verdict"] is False


def test_local_fem_surrogate_deck_contains_physical_load_path(tmp_path: Path) -> None:
    _, paths = _run(tmp_path)
    deck = paths["local_surrogate_apdl"].read_text()

    assert "SADDLE_RING_YOKE" in deck
    assert "FRICTION_CLAMP_SECONDARY" in deck
    assert "NO_OUTWARD_PEEL_PRIMARY_LOAD_PATH" in deck
