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
    continuous_ply_count_step_margin_min,
    discretize_layup_per_segment,
    effective_layup_thickness_step_limit,
    enumerate_valid_stacks,
    format_layup_report,
    manufacturing_gate_summary,
    summarize_layup_results,
    summarize_discrete_layup_design,
    summarize_segment_tsai_wu,
    summarize_segment_tsai_wu_envelope,
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
        selection_mode="local",
    )

    assert [stack.total_plies() for stack in selected] == [12, 10]


def test_discretize_layup_limits_large_ply_count_increases(ply_mat) -> None:
    stacks = [
        PlyStack(n_0=1, n_45=1, n_90=0),  # 6 plies, half count 3
        PlyStack(n_0=2, n_45=1, n_90=0),  # 8 plies, half count 4
        PlyStack(n_0=4, n_45=1, n_90=0),  # 12 plies, half count 6
    ]

    selected = discretize_layup_per_segment(
        continuous_thicknesses=[0.70e-3, 1.50e-3],
        R_outer_per_seg=[0.03, 0.03],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=1,
        selection_mode="local",
    )

    assert [stack.total_plies() for stack in selected] == [6, 8]


def test_discretize_layup_defaults_to_spanwise_dp_search(ply_mat) -> None:
    stacks = [
        PlyStack(n_0=1, n_45=1, n_90=0),  # 6 plies
        PlyStack(n_0=2, n_45=1, n_90=0),  # 8 plies
        PlyStack(n_0=3, n_45=1, n_90=0),  # 10 plies
        PlyStack(n_0=4, n_45=1, n_90=0),  # 12 plies
    ]

    local_selected = discretize_layup_per_segment(
        continuous_thicknesses=[0.99e-3, 1.49e-3],
        R_outer_per_seg=[0.03, 0.03],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=1,
        selection_mode="local",
    )
    dp_selected = discretize_layup_per_segment(
        continuous_thicknesses=[0.99e-3, 1.49e-3],
        R_outer_per_seg=[0.03, 0.03],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=1,
    )

    assert [stack.total_plies() for stack in local_selected] == [8, 10]
    assert [stack.total_plies() for stack in dp_selected] == [10, 12]


def test_build_segment_layup_results_spanwise_dp_passes_manufacturing_gate(ply_mat) -> None:
    stacks = [
        PlyStack(n_0=1, n_45=1, n_90=0),  # 6 plies
        PlyStack(n_0=2, n_45=1, n_90=0),  # 8 plies
        PlyStack(n_0=3, n_45=1, n_90=0),  # 10 plies
        PlyStack(n_0=4, n_45=1, n_90=0),  # 12 plies
    ]

    results = build_segment_layup_results(
        segment_lengths_m=[1.0, 1.0, 1.0],
        continuous_thicknesses_m=[0.99e-3, 1.49e-3, 0.99e-3],
        outer_radii_m=[0.03, 0.03, 0.03],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=1,
    )

    gate = manufacturing_gate_summary(results, ply_drop_limit=1, min_run_length_m=0.0)
    assert [result.stack.total_plies() for result in results] == [10, 12, 10]
    assert gate["passed"] is True


def test_effective_layup_thickness_step_limit_tightens_to_one_half_layup_step(
    cfg,
    ply_mat,
) -> None:
    spar_cfg = cfg.main_spar.model_copy(update={"max_ply_drop_per_segment": 1})

    limit = effective_layup_thickness_step_limit(
        spar_cfg,
        solver_max_step_m=3.0e-3,
        materials_db=MaterialDB(REPO_ROOT / "data" / "materials.yaml"),
    )

    assert limit == pytest.approx(2 * ply_mat.t_ply)


def test_continuous_ply_count_step_margin_uses_half_layup_steps(cfg, ply_mat) -> None:
    spar_cfg = cfg.main_spar.model_copy(update={"max_ply_drop_per_segment": 1})

    margin = continuous_ply_count_step_margin_min(
        [1.00e-3, 0.75e-3, 0.25e-3],
        spar_cfg,
        MaterialDB(REPO_ROOT / "data" / "materials.yaml"),
    )

    assert margin == pytest.approx(-1.0)


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

    report = format_layup_report(
        results,
        ply_mat,
        ply_drop_limit=1,
        min_run_length_m=1.5,
    )

    assert "Segment 1 (y=0.0-1.5m):" in report
    assert "_s" in report
    assert "E_eff=" in report
    assert "G_eff=" in report
    assert "Manufacturing gates:" in report


def test_summarize_layup_results_reports_manufacturing_gate_margins(cfg, ply_mat) -> None:
    stacks = enumerate_valid_stacks(cfg.main_spar)
    results = build_segment_layup_results(
        segment_lengths_m=[1.5, 3.0],
        continuous_thicknesses_m=[1.10e-3, 0.90e-3],
        outer_radii_m=[0.03, 0.028],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=1,
    )

    gate = manufacturing_gate_summary(
        results,
        ply_drop_limit=1,
        min_run_length_m=1.5,
    )
    machine_summary = summarize_layup_results(
        results,
        ply_drop_limit=1,
        min_run_length_m=1.5,
    )

    assert gate["passed"] is True
    assert gate["ply_count_step_margin_min"] >= 0.0
    assert machine_summary["manufacturing_gates"]["passed"] is True


def test_summarize_discrete_layup_design_marks_discrete_output_as_final(cfg, ply_mat) -> None:
    stacks = enumerate_valid_stacks(cfg.main_spar)
    results = build_segment_layup_results(
        segment_lengths_m=[1.5, 3.0],
        continuous_thicknesses_m=[1.10e-3, 0.90e-3],
        outer_radii_m=[0.03, 0.028],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=1,
        strain_envelopes=[
            {
                "epsilon_x_absmax": 1.0e-4,
                "kappa_absmax": 1.0e-3,
                "torsion_rate_absmax": 2.0e-3,
            },
            {
                "epsilon_x_absmax": 1.2e-4,
                "kappa_absmax": 1.2e-3,
                "torsion_rate_absmax": 2.2e-3,
            },
        ],
    )
    machine_summary = summarize_layup_results(
        results,
        ply_drop_limit=1,
        min_run_length_m=1.5,
    )

    payload = summarize_discrete_layup_design(
        {
            "main_spar": {
                "ply_material": ply_mat.name,
                "results": results,
                "summary": machine_summary,
            }
        }
    )

    assert payload["design_layer"] == "discrete_final"
    assert payload["continuous_input_role"] == "warm_start_reference"
    assert payload["discrete_output_role"] == "final_design_candidate"
    assert payload["overall_status"] == "pass"
    assert payload["manufacturing_gates_passed"] is True
    assert payload["spars"]["main_spar"]["status"] == "pass"
    assert payload["spars"]["main_spar"]["design_role"] == "discrete_final_output"
    assert payload["critical_strength_ratio"]["spar"] == "main_spar"


def test_summarize_discrete_layup_design_warns_when_catalog_is_capped(cfg, ply_mat) -> None:
    stacks = enumerate_valid_stacks(cfg.main_spar)
    results = build_segment_layup_results(
        segment_lengths_m=[1.5],
        continuous_thicknesses_m=[10.0e-3],
        outer_radii_m=[0.03],
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=1,
        strain_envelopes=[
            {
                "epsilon_x_absmax": 1.0e-4,
                "kappa_absmax": 1.0e-3,
                "torsion_rate_absmax": 2.0e-3,
            }
        ],
    )
    machine_summary = summarize_layup_results(
        results,
        ply_drop_limit=1,
        min_run_length_m=0.0,
    )

    payload = summarize_discrete_layup_design(
        {
            "main_spar": {
                "ply_material": ply_mat.name,
                "results": results,
                "summary": machine_summary,
            }
        }
    )

    assert results[0].catalog_capped is True
    assert payload["overall_status"] == "warn"
    assert payload["spars"]["main_spar"]["status"] == "warn"
    assert payload["spars"]["main_spar"]["catalog_capped_segments"] == [1]


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


def test_tsai_wu_envelope_folds_beam_curvature_and_torsion_into_laminate_state(ply_mat) -> None:
    stack = PlyStack(n_0=1, n_45=1, n_90=0)

    summary, envelope = summarize_segment_tsai_wu_envelope(
        stack=stack,
        ply_mat=ply_mat,
        epsilon_x_absmax=2.0e-4,
        kappa_absmax=1.0e-2,
        torsion_rate_absmax=3.0e-2,
        outer_radius_m=0.03,
    )

    assert envelope.surface_epsilon_x_absmax == pytest.approx(5.0e-4)
    assert envelope.gamma_xy_absmax == pytest.approx(9.0e-4)
    assert summary.min_strength_ratio > 1.0
    assert summary.critical_midplane_strain is not None
    assert abs(summary.critical_midplane_strain[0]) == pytest.approx(5.0e-4)


def test_build_segment_layup_results_can_include_strain_envelope_artifact(cfg, ply_mat) -> None:
    stacks = enumerate_valid_stacks(cfg.main_spar)

    results = build_segment_layup_results(
        segment_lengths_m=[1.0],
        continuous_thicknesses_m=[0.90e-3],
        outer_radii_m=[0.03],
        stacks=stacks,
        ply_mat=ply_mat,
        strain_envelopes=[
            {
                "epsilon_x_absmax": 1.0e-4,
                "kappa_absmax": 2.0e-3,
                "torsion_rate_absmax": 4.0e-3,
            }
        ],
    )

    machine_summary = summarize_layup_results(results)
    segment = machine_summary["segments"][0]
    assert results[0].strain_envelope is not None
    assert results[0].tsai_wu_summary is not None
    assert segment["strain_envelope"]["surface_epsilon_x_absmax"] == pytest.approx(1.6e-4)
    assert segment["tsai_wu_summary"]["min_strength_ratio"] > 1.0


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
                },
                "strain_envelope": {
                    "epsilon_x_absmax": [
                        1.0e-4,
                        1.1e-4,
                        1.2e-4,
                        1.3e-4,
                        1.4e-4,
                        1.5e-4,
                    ],
                    "kappa_absmax": [
                        1.0e-3,
                        1.1e-3,
                        1.2e-3,
                        1.3e-3,
                        1.4e-3,
                        1.5e-3,
                    ],
                    "torsion_rate_absmax": [
                        2.0e-3,
                        2.1e-3,
                        2.2e-3,
                        2.3e-3,
                        2.4e-3,
                        2.5e-3,
                    ],
                },
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
    assert "Tsai-Wu FI=" in report_text
    assert "main_spar" in schedule["spars"]
    assert "rear_spar" in schedule["spars"]
    assert schedule["manufacturing_gates_passed"] is True
    assert schedule["spars"]["main_spar"]["manufacturing_gates"]["passed"] is True
    assert schedule["spars"]["main_spar"]["segments"][0]["strain_envelope"] is not None
    assert schedule["spars"]["main_spar"]["segments"][0]["tsai_wu_summary"] is not None
