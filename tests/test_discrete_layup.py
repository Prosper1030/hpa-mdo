from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from hpa_mdo.core import MaterialDB, load_config
from hpa_mdo.structure.laminate import PlyStack, ply_Q_matrix
from hpa_mdo.utils.discrete_layup import (
    build_segment_layup_results,
    discretize_layup_per_segment,
    effective_layup_thickness_step_limit,
    enumerate_valid_stacks,
    format_layup_report,
    summarize_layup_results,
    summarize_segment_tsai_wu,
    thickness_step_margin_min,
    snap_to_nearest_stack,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG_PATH)


@pytest.fixture(scope="module")
def ply_mat():
    return MaterialDB(REPO_ROOT / "data" / "materials.yaml").get_ply("cfrp_ply_hm")


def test_enumerate_valid_stacks_returns_reasonable_catalog_size(cfg) -> None:
    stacks = enumerate_valid_stacks(cfg.main_spar)

    assert 20 <= len(stacks) <= 30
    assert stacks == sorted(stacks, key=lambda stack: stack.total_plies())


def test_snap_to_nearest_stack_rounds_up(cfg, ply_mat) -> None:
    stacks = enumerate_valid_stacks(cfg.main_spar)

    snapped = snap_to_nearest_stack(0.90e-3, stacks, ply_mat)

    assert snapped.total_plies() == 8
    assert snapped.wall_thickness(ply_mat.t_ply) == pytest.approx(1.0e-3)


def test_discretize_layup_applies_ply_drop_limit(ply_mat) -> None:
    stacks = [
        PlyStack(n_0=1, n_45=1, n_90=0),  # 6 plies
        PlyStack(n_0=3, n_45=1, n_90=0),  # 10 plies
        PlyStack(n_0=4, n_45=1, n_90=0),  # 12 plies
    ]

    selected = discretize_layup_per_segment(
        continuous_thicknesses=[1.50e-3, 0.70e-3],
        R_outer_per_seg=[0.03, 0.03],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=2,
    )

    assert [stack.total_plies() for stack in selected] == [12, 10]


def test_effective_layup_thickness_step_limit_tightens_discrete_clt(cfg, ply_mat) -> None:
    spar_cfg = cfg.main_spar.model_copy(
        update={"layup_mode": "discrete_clt", "max_ply_drop_per_segment": 2}
    )

    limit = effective_layup_thickness_step_limit(
        spar_cfg,
        solver_max_step_m=3.0e-3,
        materials_db=MaterialDB(REPO_ROOT / "data" / "materials.yaml"),
    )

    assert limit == pytest.approx(2 * ply_mat.t_ply)


def test_thickness_step_margin_reports_ply_drop_violation() -> None:
    margin = thickness_step_margin_min([1.00e-3, 0.60e-3], max_step_m=0.25e-3)

    assert margin == pytest.approx(-0.15e-3)


def test_format_layup_report_contains_schedule_and_effective_properties(cfg, ply_mat) -> None:
    stacks = enumerate_valid_stacks(cfg.main_spar)
    results = build_segment_layup_results(
        segment_lengths_m=[1.5, 3.0],
        continuous_thicknesses_m=[1.10e-3, 0.90e-3],
        outer_radii_m=[0.03, 0.028],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=2,
    )

    report = format_layup_report(results, ply_mat)

    assert "Segment 1 (y=0.0-1.5m):" in report
    assert "_s" in report
    assert "E_eff=" in report
    assert "G_eff=" in report


def test_summarize_segment_tsai_wu_reports_critical_ply(ply_mat) -> None:
    stack = PlyStack(n_0=1, n_45=0, n_90=0)
    Q = ply_Q_matrix(
        E1=ply_mat.E1,
        E2=ply_mat.E2,
        G12=ply_mat.G12,
        nu12=ply_mat.nu12,
    )
    midplane_strain = np.linalg.solve(Q, np.array([0.5 * ply_mat.F1t, 0.0, 0.0]))

    summary = summarize_segment_tsai_wu(
        stack=stack,
        ply_mat=ply_mat,
        midplane_strain=midplane_strain,
    )

    assert summary.max_failure_index < 1.0
    assert summary.min_strength_ratio == pytest.approx(2.0)
    assert summary.critical_ply_angle_deg == pytest.approx(0.0)


def test_build_segment_layup_results_can_include_tsai_wu_report(ply_mat) -> None:
    stack = PlyStack(n_0=1, n_45=0, n_90=0)
    Q = ply_Q_matrix(
        E1=ply_mat.E1,
        E2=ply_mat.E2,
        G12=ply_mat.G12,
        nu12=ply_mat.nu12,
    )
    midplane_strain = np.linalg.solve(Q, np.array([0.5 * ply_mat.F1t, 0.0, 0.0]))

    results = build_segment_layup_results(
        segment_lengths_m=[1.0],
        continuous_thicknesses_m=[0.10e-3],
        outer_radii_m=[0.03],
        stacks=[stack],
        ply_mat=ply_mat,
        midplane_strains=[midplane_strain],
    )

    report = format_layup_report(results, ply_mat)
    machine_summary = summarize_layup_results(results)
    summary = results[0].tsai_wu_summary
    assert results[0].tsai_wu_summary is not None
    assert summary is not None
    assert summary.min_strength_ratio == pytest.approx(2.0)
    assert "Tsai-Wu FI=" in report
    assert "SR=2.00" in report
    assert machine_summary["segments"][0]["tsai_wu_summary"]["min_strength_ratio"] == pytest.approx(
        2.0
    )


def test_discrete_layup_postprocess_script_writes_report_and_schedule(tmp_path) -> None:
    summary_path = tmp_path / "inverse_design_summary.json"
    report_path = tmp_path / "layup_report.txt"
    payload = {
        "config": str(CONFIG_PATH),
        "outcome": {
            "selected": {
                "design_mm": {
                    "main_t": [1.20, 1.10, 1.00, 0.95, 0.90, 0.85],
                    "main_r": [35.0, 34.0, 33.0, 32.0, 31.0, 30.0],
                    "rear_t": [0.90, 0.85, 0.80, 0.80, 0.80, 0.80],
                    "rear_r": [22.0, 21.5, 21.0, 20.5, 20.0, 19.5],
                }
            }
        },
    }
    summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "discrete_layup_postprocess.py"),
            "--summary",
            str(summary_path),
            "--ply-material",
            "cfrp_ply_hm",
            "--output",
            str(report_path),
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    schedule_path = report_path.with_name("layup_schedule.json")
    assert report_path.exists()
    assert schedule_path.exists()

    report_text = report_path.read_text(encoding="utf-8")
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
    assert "Discrete Layup Post-Process" in report_text
    assert "main_spar" in schedule["spars"]
    assert "rear_spar" in schedule["spars"]
