from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "build_baseline_a_release.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_baseline_a_release", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(tmp_path: Path) -> tuple[dict[str, Path], Path]:
    mod = _load_module()
    output_dir = tmp_path / "baseline_A_team_release"
    paths = mod.write_baseline_a_release_package(output_dir=output_dir)
    return paths, output_dir


def test_release_builder_writes_required_team_package(tmp_path: Path) -> None:
    paths, output_dir = _run(tmp_path)

    required = {
        "baseline_A_team_release.md",
        "geometry_freeze.json",
        "mass_budget.csv",
        "cg_summary.json",
        "drag_power_budget.csv",
        "tail_trim_stability_summary.json",
        "structure_interface_pack.md",
        "control_interface_pack.md",
        "propulsion_interface_pack.md",
        "manufacturing_test_plan.md",
        "carbon_tube_rfq_spec.md",
        "change_control_rules.md",
        "team_work_packages.md",
    }

    assert required == {path.name for path in paths.values()}
    for name in required:
        assert (output_dir / name).exists(), name

    release_md = (output_dir / "baseline_A_team_release.md").read_text(encoding="utf-8")
    assert "Baseline A team release" in release_md
    assert "not final aircraft sign-off" in release_md
    assert "frozen / do not casually change" in release_md
    assert "controlled / can change with review" in release_md
    assert "open validation / assigned to team" in release_md
    assert "reopen trigger / would force major redesign" in release_md


def test_machine_artifacts_lock_pathfinder_numbers_and_boundaries(tmp_path: Path) -> None:
    _, output_dir = _run(tmp_path)

    geometry = json.loads((output_dir / "geometry_freeze.json").read_text(encoding="utf-8"))
    assert geometry["release_verdict"] == "baseline_A_release_system_ready"
    assert geometry["candidate_id"] == (
        "eps_balsa_cap_hybrid_10mm__t10p0mm__uniform_0p30__"
        "carbon_face_collar_y2p328__rear75"
    )
    assert geometry["frozen"]["rib_spacing_m"] == pytest.approx(0.30)
    assert geometry["controlled"]["c04_fix"] == "saddle_ring_yoke_plus_secondary_clamp"
    assert "coupon" in geometry["open_validation"]["p1_local_load_path"]
    assert "final aircraft sign-off" in geometry["claim_boundary"]

    with (output_dir / "mass_budget.csv").open(newline="", encoding="utf-8") as handle:
        rows = {row["item"]: row for row in csv.DictReader(handle)}
    assert float(rows["p1_c04_fix_full_wing"]["mass_kg"]) == pytest.approx(0.093839)
    assert float(rows["spar_splice_full_wing"]["mass_kg"]) == pytest.approx(3.847)
    assert float(rows["updated_screening_mass_basis"]["mass_kg"]) == pytest.approx(106.828608)
    assert rows["updated_screening_mass_basis"]["status"] == "screening_basis_not_measured_weight"

    cg = json.loads((output_dir / "cg_summary.json").read_text(encoding="utf-8"))
    assert cg["managed_final_cg_m"] == pytest.approx(0.75)
    assert cg["required_forward_rebalance_m"] == pytest.approx(0.057304)
    assert cg["uncompensated_cg_status"] == "explicitly_rejected"


def test_interface_packs_and_work_queue_keep_lanes_and_claims_separate(tmp_path: Path) -> None:
    _, output_dir = _run(tmp_path)

    propulsion = (output_dir / "propulsion_interface_pack.md").read_text(encoding="utf-8")
    assert "QPROP/XROTOR is an independent propulsion lane" in propulsion
    assert "not used to pass the P1 structural blocker" in propulsion

    structure = (output_dir / "structure_interface_pack.md").read_text(encoding="utf-8")
    assert "P1 is ready for coupon/local FEM" in structure
    assert "C04 original peel path fails" in structure
    assert "governing clamp margin `0.8876`" in structure

    work_packages = (output_dir / "team_work_packages.md").read_text(encoding="utf-8")
    for queue_item in (
        "design-space freeze audit",
        "main-wing SU2 baseline validation",
        "QPROP/XROTOR propulsion interface",
        "airfoil database CST/NSGA background lane",
        "report/CAD/export automation",
    ):
        assert queue_item in work_packages
    assert "Do not implement SU2/NSGA/propeller optimization in this release-builder task" in (
        work_packages
    )
