from __future__ import annotations

from pathlib import Path

import pytest

from scripts.phase15_candidate_load_factor_buckling_check import (
    CandidateReference,
    DEFAULT_LOAD_FACTORS,
    build_phase15_rows,
    estimate_first_fail,
    write_phase15_package,
)


def _reference() -> CandidateReference:
    return CandidateReference(
        candidate_id="sample",
        reference_load_factor=2.0,
        failure_index=0.25 - 1.0,
        buckling_index=0.10 - 1.0,
        tip_deflection_m=0.9,
        tip_deflection_limit_m=2.5,
        twist_max_deg=0.2,
        twist_limit_deg=2.0,
        wire_tension_n=100.0,
        wire_allowable_n=250.0,
        root_reaction_fz_n=-10.0,
        root_bending_moment_n_m=1000.0,
        tube_allowable_stress_pa=1.0e9,
        young_pa=200.0e9,
        jig_main_tip_z_m=0.6,
        jig_rear_tip_z_m=0.4,
        loaded_main_tip_z_m=2.7,
        loaded_rear_tip_z_m=2.5,
        jig_min_z_m=0.04,
        loaded_min_z_m=0.08,
        fem_validated_max_load_factor=2.0,
        fem_tip_error_pct=3.74,
        fem_wire_reaction_error_pct=2.09,
        fem_root_reaction_error_pct=4.60,
        structured_shell_b2_error_pct=2.41,
        structured_shell_b5_torsion_error_pct=0.07,
    )


def test_phase15_rows_extend_requested_load_factors_and_mark_extrapolated_fem() -> None:
    rows = build_phase15_rows(_reference(), load_factors=DEFAULT_LOAD_FACTORS)

    assert [row.load_factor for row in rows] == [1.0, 1.5, 1.75, 2.0, 2.5, 3.0]
    assert rows[3].fem_basis == "repaired_candidate_equivalent_fem_ran_reference"
    assert rows[4].fem_basis == "internal_linear_extrapolation_beyond_fem_ran_reference"
    assert rows[-1].wire_utilization == pytest.approx(0.6)
    assert rows[-1].first_failure_mode == "none_with_margin"
    assert rows[-1].loaded_main_tip_z_m == pytest.approx(3.75)


def test_estimate_first_fail_selects_wire_before_deflection_and_stress() -> None:
    first_fail = estimate_first_fail(_reference())

    assert first_fail.mode == "wire_tension"
    assert first_fail.load_factor == pytest.approx(5.0)


def test_write_phase15_package_creates_required_submission_files(tmp_path: Path) -> None:
    outputs = write_phase15_package(tmp_path, _reference())

    expected = {
        "load_factor_summary.csv",
        "buckling_stress_check.csv",
        "wire_tension_margin.csv",
        "failure_mode_report.md",
        "candidate_limit_load_recommendation.md",
        "submission_numbers.md",
        "structural_claim_readiness.csv",
        "structural_claim_readiness.json",
        "structural_claim_readiness.md",
    }
    assert {path.name for path in outputs} == expected
    summary = (tmp_path / "load_factor_summary.csv").read_text(encoding="utf-8")
    assert "compression_side_risk" in summary
    assert "root_joint_wire_attach_rib_load_transfer_warning" in summary
    report = (tmp_path / "candidate_limit_load_recommendation.md").read_text(encoding="utf-8")
    assert "internal fixed-design load-factor boundary" in report
    assert "1.75G validated" not in report
    assert "checked range" not in report
    assert "FEM ran reference range" in report
    claim_gate = (tmp_path / "structural_claim_readiness.md").read_text(encoding="utf-8")
    assert "Do not claim `1.5G / 1.75G full-wing pass`" in claim_gate
