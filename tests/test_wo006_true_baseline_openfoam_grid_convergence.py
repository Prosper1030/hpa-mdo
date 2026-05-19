from __future__ import annotations

import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_wo006_true_baseline_openfoam_grid_convergence as module  # noqa: E402


def test_build_grid_ladder_specs_scales_structured_resolution_systematically() -> None:
    specs = module.build_grid_ladder_specs()

    assert [spec.case_id for spec in specs] == ["coarse", "medium", "fine"]
    assert [spec.scale for spec in specs] == [0.75, 1.0, 1.25]
    assert [spec.n_perim for spec in specs] == [144, 192, 240]
    assert [spec.n_radial for spec in specs] == [48, 64, 80]
    assert [spec.span_cells for spec in specs] == [61, 78, 95]
    assert [sum(spec.station_plan) for spec in specs] == [61, 78, 95]


def test_build_force_groups_keeps_existing_diagnostics_and_adds_total_physical() -> None:
    groups = module.build_force_groups(
        (
            "airfoil_upper",
            "airfoil_lower",
            "physical_tip_left",
            "physical_tip_right",
            "te_wall",
            "farfield",
            "outlet",
        )
    )

    assert groups["primary"] == ("airfoil_upper", "airfoil_lower")
    assert groups["total"] == (
        "airfoil_upper",
        "airfoil_lower",
        "physical_tip_left",
        "physical_tip_right",
        "te_wall",
    )
    assert groups["total_physical"] == ("airfoil_upper", "airfoil_lower", "te_wall")
    assert groups["physical_tip_left"] == ("physical_tip_left",)
    assert groups["physical_tip_right"] == ("physical_tip_right",)
    assert groups["te_wall"] == ("te_wall",)


def test_build_boundary_contract_marks_artificial_tip_closures_as_symmetry_planes() -> None:
    contract = module.build_boundary_contract(
        (
            "airfoil_upper",
            "airfoil_lower",
            "physical_tip_left",
            "physical_tip_right",
            "te_wall",
            "farfield",
            "outlet",
        )
    )

    assert contract["wall_patches"] == ("airfoil_upper", "airfoil_lower", "te_wall")
    assert contract["artificial_symmetry_patches"] == (
        "physical_tip_left",
        "physical_tip_right",
    )
    assert contract["flow_patches"] == ("farfield", "outlet")


def test_should_extend_after_first_run_only_when_window_is_not_yet_stable() -> None:
    stable = {"route_smoke_stable": True}
    unstable = {"route_smoke_stable": False}
    finite_coeffs = {
        "functions": {
            "primary": {
                "rows": [
                    {"Cd": 0.031, "Cl": 1.11},
                ]
            }
        }
    }

    assert module.should_extend_after_first_run(finite_coeffs, stable) is False
    assert module.should_extend_after_first_run(finite_coeffs, unstable) is True


def test_should_extend_after_first_run_rejects_missing_or_non_finite_force_rows() -> None:
    stable = {"route_smoke_stable": False}

    assert module.should_extend_after_first_run({}, stable) is False
    assert module.should_extend_after_first_run(
        {"functions": {"primary": {"rows": [{"Cd": None, "Cl": 1.0}]}}},
        stable,
    ) is False
    assert module.should_extend_after_first_run(
        {"functions": {"primary": {"rows": [{"Cd": float("nan"), "Cl": 1.0}]}}},
        stable,
    ) is False
    assert module.should_extend_after_first_run(
        {
            "functions": {
                "primary": {
                    "rows": [
                        {"Time": 10, "Cd": 0.03, "Cl": 1.1},
                        {"Time": 11, "Cd": 1.2, "Cl": 1.5},
                    ]
                }
            }
        },
        stable,
    ) is False


def test_load_existing_rung_result_uses_per_rung_manifest(tmp_path: Path) -> None:
    rung_dir = tmp_path / "openfoam_cases" / "medium"
    rung_dir.mkdir(parents=True)
    expected = {"spec": {"case_id": "medium"}, "summary": {"CD_primary": 0.03}}
    (rung_dir / "rung_result.json").write_text(json.dumps(expected), encoding="utf-8")

    loaded = module.load_existing_rung_result(tmp_path, "medium")

    assert loaded == expected


def test_load_existing_rung_result_returns_none_when_missing(tmp_path: Path) -> None:
    assert module.load_existing_rung_result(tmp_path, "fine") is None


def test_force_runaway_detected_uses_solver_stability_thresholds() -> None:
    assert module.force_runaway_detected(
        {
            "functions": {
                "primary": {
                    "rows": [
                        {"Time": 10, "Cd": 0.03, "Cl": 1.2},
                        {"Time": 11, "Cd": 1.01, "Cl": 1.5},
                    ]
                }
            }
        }
    ) is True
    assert module.force_runaway_detected(
        {
            "functions": {
                "primary": {
                    "rows": [
                        {"Time": 10, "Cd": 0.03, "Cl": 1.2},
                        {"Time": 11, "Cd": 0.2, "Cl": 2.5},
                    ]
                }
            }
        }
    ) is False


def test_gate_force_window_stability_marks_runaway_case_unstable() -> None:
    gated = module.gate_force_window_stability(
        {
            "status": "available",
            "route_smoke_stable": True,
            "window": 2,
        },
        {
            "returncode": "stopped_by_runaway_guard",
            "stopped_by_runaway_guard": True,
            "runaway_time": 1,
        },
    )

    assert gated["route_smoke_stable"] is False
    assert gated["status"] == "runaway_guard_triggered"
    assert gated["runaway_time"] == 1
