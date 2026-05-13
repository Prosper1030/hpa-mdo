from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_wo006f_su2_engineering_result.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("wo006f", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_history(path: Path, rows: list[dict[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Inner_Iter", "CD", "CL", "CMy"])
        writer.writeheader()
        writer.writerows(rows)


def test_rejects_positive_lift_when_drag_is_far_above_sanity_bounds(tmp_path: Path) -> None:
    mod = _load_module()
    case = tmp_path / "attempt_06_medium_no_bl_inc_rans_sa_alpha5_zpos_no_wallfn"
    _write_history(case / "history.csv", [{"Inner_Iter": 159, "CD": 0.5555, "CL": 1.2894, "CMy": -0.27}])
    (case / "solver.log").write_text(
        "Maximum number of iterations reached (ITER = 160) before convergence.\n"
        "| Cauchy[CD]|    0.00261144|       < 1e-12|          No|\n"
        "Exit Success\n",
        encoding="utf-8",
    )

    rows = mod.build_attempt_summaries(tmp_path)
    attempt = {row["attempt_id"]: row for row in rows}[
        "attempt_06_medium_no_bl_inc_rans_sa_alpha5_zpos_no_wallfn"
    ]

    assert attempt["solver_status"] == "exit_success"
    assert attempt["classification"] == "reject_drag_far_above_sanity_bounds"


def test_choose_campaign_incomplete_when_multizone_probe_launches(tmp_path: Path) -> None:
    mod = _load_module()
    case = tmp_path / "attempt_10_r6_two_zone_multizone_probe"
    _write_history(case / "history_0.csv", [{"Inner_Iter": 0, "CD": 0.0, "CL": 0.0, "CMy": 0.0}])
    (case / "solver.log").write_text("Simulation Run using the Multizone Driver\nExit Success\n", encoding="utf-8")

    summary = mod.build_campaign_summary(tmp_path)

    assert summary["verdict"] == "wo006f_campaign_incomplete"
    assert summary["route_evidence"]["r6_multizone"].startswith("attempt_10 launched")


def test_low_confidence_physical_requires_final_positive_reasonable_coefficients(tmp_path: Path) -> None:
    mod = _load_module()
    case = tmp_path / "attempt_08_medium_no_bl_inc_euler_alpha5_zpos_low_cfl"
    _write_history(case / "history.csv", [{"Inner_Iter": 60, "CD": 0.045, "CL": 1.12, "CMy": -0.2}])
    (case / "solver.log").write_text("Exit Success\n", encoding="utf-8")

    rows = mod.build_attempt_summaries(tmp_path)
    attempt = {row["attempt_id"]: row for row in rows}[
        "attempt_08_medium_no_bl_inc_euler_alpha5_zpos_low_cfl"
    ]

    assert attempt["classification"] == "candidate_low_confidence_physical"
    assert mod.choose_verdict(rows) == "wo006f_su2_result_low_confidence_but_physical"
