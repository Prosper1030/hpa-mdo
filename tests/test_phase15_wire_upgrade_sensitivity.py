from __future__ import annotations

from pathlib import Path

import pytest

from scripts.phase15_candidate_load_factor_buckling_check import CandidateReference
from scripts.phase15_wire_upgrade_sensitivity import (
    DEFAULT_WIRE_ALLOWABLE_SWEEP_N,
    build_wire_allowable_sweep,
    non_wire_first_fail,
    write_wire_upgrade_package,
)


def _reference() -> CandidateReference:
    return CandidateReference(
        candidate_id="sample",
        reference_load_factor=2.0,
        failure_index=0.25 - 1.0,
        buckling_index=0.10 - 1.0,
        tip_deflection_m=1.0,
        tip_deflection_limit_m=1.65,
        twist_max_deg=0.2,
        twist_limit_deg=2.0,
        wire_tension_n=3000.0,
        wire_allowable_n=4500.0,
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


def test_wire_sweep_includes_requested_allowables_and_load_factors() -> None:
    rows = build_wire_allowable_sweep(_reference())

    assert [row.allowable_case for row in rows] == ["current", "5kN", "6kN", "8kN", "10kN"]
    assert [allowable for _, allowable in DEFAULT_WIRE_ALLOWABLE_SWEEP_N] == [None, 5000.0, 6000.0, 8000.0, 10000.0]
    assert rows[0].wire_tension_n_1p0g == pytest.approx(1500.0)
    assert rows[0].wire_tension_n_1p75g == pytest.approx(2625.0)
    assert rows[0].wire_tension_n_3p0g == pytest.approx(4500.0)


def test_upgraded_wire_moves_first_failure_to_next_non_wire_mode() -> None:
    rows = build_wire_allowable_sweep(_reference())
    upgraded = next(row for row in rows if row.allowable_case == "6kN")

    assert rows[0].first_fail_mode == "wire_tension"
    assert rows[0].estimated_first_fail_load_factor == pytest.approx(3.0)
    assert non_wire_first_fail(_reference()).mode == "tip_deflection"
    assert upgraded.first_fail_mode == "tip_deflection"
    assert upgraded.next_failure_mode_after_wire == "tip_deflection"
    assert upgraded.estimated_first_fail_load_factor == pytest.approx(3.3)


def test_three_g_comfort_requires_wire_margin_not_just_pass() -> None:
    rows = build_wire_allowable_sweep(_reference())
    five = next(row for row in rows if row.allowable_case == "5kN")
    six = next(row for row in rows if row.allowable_case == "6kN")

    assert five.three_g_wire_comfortable == "no"
    assert six.three_g_wire_comfortable == "yes"
    assert six.wire_utilization_3p0g == pytest.approx(0.75)


def test_write_wire_upgrade_package_creates_required_files(tmp_path: Path) -> None:
    outputs = write_wire_upgrade_package(tmp_path, _reference())

    assert {path.name for path in outputs} == {
        "wire_allowable_sweep.csv",
        "wire_upgrade_summary.md",
        "recommended_wire_spec.md",
    }
    summary = (tmp_path / "wire_upgrade_summary.md").read_text(encoding="utf-8")
    assert "Does upgrading wire remove the current first-fail blocker?" in summary
    spec = (tmp_path / "recommended_wire_spec.md").read_text(encoding="utf-8")
    assert "minimum breaking load" in spec
