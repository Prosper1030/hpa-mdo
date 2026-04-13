from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from hpa_mdo.core import MaterialDB, load_config
from hpa_mdo.structure.laminate import PlyStack
from hpa_mdo.utils.discrete_layup import (
    build_segment_layup_results,
    discretize_layup_per_segment,
    enumerate_valid_stacks,
    format_layup_report,
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
