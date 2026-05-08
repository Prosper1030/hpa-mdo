from __future__ import annotations

from pathlib import Path

import pytest

from scripts.phase15_candidate_load_factor_buckling_check import CandidateReference
from scripts.phase16_ccx_buckling_wire6_ramp import (
    DEFAULT_WIRE6_ALLOWABLE_N,
    FixedFreeColumnSpec,
    build_wire6_ramp_rows,
    euler_fixed_free_pcr_n,
    tube_second_moment_m4,
    write_fixed_free_b32r_buckle_deck,
    write_phase16_package,
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


def test_fixed_free_column_closed_form_uses_pipe_second_moment() -> None:
    inertia = tube_second_moment_m4(outer_radius_m=0.03, wall_thickness_m=0.0015)
    pcr = euler_fixed_free_pcr_n(young_pa=230.0e9, second_moment_m4=inertia, length_m=2.0)

    assert inertia > 0.0
    assert pcr == pytest.approx(16742.171, rel=1.0e-4)


def test_fixed_free_b32r_deck_contains_real_buckle_step(tmp_path: Path) -> None:
    spec = FixedFreeColumnSpec()
    deck = write_fixed_free_b32r_buckle_deck(tmp_path / "column_buckle.inp", spec)
    text = deck.read_text(encoding="utf-8")

    assert "*ELEMENT, TYPE=B32R" in text
    assert "*BEAM SECTION, ELSET=EALL, MATERIAL=CARBON_FIBER_HM, SECTION=PIPE" in text
    assert "1, 1, 6" in text
    assert f"{spec.top_endpoint_node_id}, 2, {-spec.reference_compression_n:.9g}" in text
    assert "*STEP, NAME=buckle\n*BUCKLE\n5" in text


def test_wire6_ramp_identifies_deflection_then_wire_then_stress() -> None:
    rows = build_wire6_ramp_rows(_reference(), load_factors=(3.0, 3.4, 4.0, 8.2))

    assert rows[0].event == "within_model_margins"
    assert rows[0].wire_utilization == pytest.approx(0.75)
    assert rows[1].event == "tip_deflection_limit_exceeded"
    assert rows[2].event == "wire_allowable_exceeded"
    assert rows[3].event == "cfrp_global_bending_stress_exceeded"


def test_write_phase16_package_without_ccx_result_creates_reports(tmp_path: Path) -> None:
    outputs = write_phase16_package(
        tmp_path,
        _reference(),
        ccx_result=None,
        wire_allowable_n=DEFAULT_WIRE6_ALLOWABLE_N,
    )

    assert {path.name for path in outputs} == {
        "ccx_buckling_capability.csv",
        "ccx_buckling_capability_report.md",
        "wire6_load_factor_ramp.csv",
        "wire6_load_factor_ramp_report.md",
    }
    assert "CalculiX BUCKLE" in (tmp_path / "ccx_buckling_capability_report.md").read_text(
        encoding="utf-8"
    )
    ramp_report = (tmp_path / "wire6_load_factor_ramp_report.md").read_text(encoding="utf-8")
    assert "modeled cable-body tension allowable is not exceeded" in ramp_report
    assert "wire does not snap" not in ramp_report
