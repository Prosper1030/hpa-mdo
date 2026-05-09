from __future__ import annotations

from pathlib import Path

from scripts.phase47_existing_torsion_twist_evidence_triage import (
    build_existing_torsion_twist_evidence_triage,
    write_existing_torsion_twist_evidence_triage_package,
)


def _phase13_rows() -> tuple[dict[str, str], ...]:
    return (
        {
            "mode_id": "front_rear_vertical_couple",
            "physically_interpretable": "True",
            "xy_moment_residual_nm": "105.773",
            "total_moment_residual_nm": "1525.861",
            "hard_failures": "moment_closure",
        },
        {
            "mode_id": "main_beam_my_about_main_spar",
            "physically_interpretable": "False",
            "xy_moment_residual_nm": "944.217",
            "total_moment_residual_nm": "1707.206",
            "hard_failures": "moment_closure",
        },
    )


def _b5_solution_rows() -> tuple[dict[str, str], ...]:
    return (
        {
            "torque_mode": "main_beam_my_about_main_spar",
            "applied_spanwise_moment_n_m": "40.0",
            "main_section_torque_root_n_m": "38.3337",
            "main_section_torque_max_abs_n_m": "38.3337",
            "rear_section_torque_max_abs_n_m": "0.0",
            "expected_main_root_section_torque_n_m": "38.3333",
            "root_torque_error_pct": "0.001",
        },
        {
            "torque_mode": "front_rear_vertical_couple",
            "applied_spanwise_moment_n_m": "40.0",
            "main_section_torque_root_n_m": "0.0",
            "main_section_torque_max_abs_n_m": "0.0",
            "rear_section_torque_max_abs_n_m": "0.0",
            "expected_main_root_section_torque_n_m": "0.0",
            "root_torque_error_pct": "",
        },
    )


def _single_beam_rows() -> tuple[dict[str, str], ...]:
    return (
        {
            "case_id": "single_tip_my_100nm",
            "applied_tip_my_nm": "100.0",
            "section_force_torque_root_nm": "99.999",
            "section_force_torque_tip_nm": "100.120",
            "max_abs_section_force_torque_nm": "100.120",
        },
        {
            "case_id": "single_control_0nm",
            "applied_tip_my_nm": "0.0",
            "section_force_torque_root_nm": "0.0",
            "section_force_torque_tip_nm": "0.0",
            "max_abs_section_force_torque_nm": "0.0",
        },
    )


def _b5_parity_rows() -> tuple[dict[str, str], ...]:
    return (
        {
            "torque_mode": "main_beam_my_about_main_spar",
            "twist_error_pct": "92.687",
            "twist_proxy_deg": "0.0769",
            "engineering_note": "centerline twist proxy cannot prove beam-axis rotation ownership",
        },
        {
            "torque_mode": "front_rear_vertical_couple",
            "twist_error_pct": "93.258",
            "twist_proxy_deg": "-0.1802",
            "engineering_note": "magnitude still differs materially from the internal beam model",
        },
    )


def test_existing_torsion_twist_evidence_triage_keeps_torque_observability_below_signoff() -> None:
    triage = build_existing_torsion_twist_evidence_triage(
        "sample",
        phase13_rows=_phase13_rows(),
        b5_solution_rows=_b5_solution_rows(),
        single_beam_torsion_rows=_single_beam_rows(),
        b5_parity_rows=_b5_parity_rows(),
    )

    assert triage.overall_status == "existing_torsion_twist_evidence_does_not_close_goal"
    assert triage.row_count == 4
    assert triage.closing_evidence_count == 0
    assert triage.torque_observable_evidence_count == 2
    assert triage.aeroelastic_closure_evidence_count == 0

    by_key = {row.evidence_key: row for row in triage.rows}
    assert by_key["phase14_b5_solution_hunt"].status == (
        "direct_my_torque_observable_surrogate_policy_open"
    )
    assert by_key["phase14_b5_solution_hunt"].supports_torque_observable
    assert not by_key["phase14_b5_solution_hunt"].supports_aeroelastic_twist
    assert "root torque error=0.0010%" in by_key["phase14_b5_solution_hunt"].key_metric
    assert "front/rear couple is not truth-equivalent" in by_key[
        "phase14_b5_solution_hunt"
    ].remaining_blocker

    assert by_key["phase14_single_beam_torsion_probe"].status == (
        "section_force_torque_observable_not_candidate_closure"
    )
    assert "max |torque|=100.1200 N*m" in by_key[
        "phase14_single_beam_torsion_probe"
    ].key_metric

    assert by_key["phase13_torque_ownership_ab_test"].status == (
        "torque_ownership_diagnostic_not_aeroelastic_signoff"
    )
    assert "best interpretable mode=front_rear_vertical_couple" in by_key[
        "phase13_torque_ownership_ab_test"
    ].key_metric
    assert by_key["phase14_b5_twist_proxy_parity"].status == (
        "centerline_twist_proxy_mismatch_not_closure"
    )
    assert "max twist proxy error=93.2580%" in by_key[
        "phase14_b5_twist_proxy_parity"
    ].key_metric


def test_write_existing_torsion_twist_evidence_triage_package_creates_reports(
    tmp_path: Path,
) -> None:
    outputs = write_existing_torsion_twist_evidence_triage_package(
        tmp_path,
        "sample",
        phase13_rows=_phase13_rows(),
        b5_solution_rows=_b5_solution_rows(),
        single_beam_torsion_rows=_single_beam_rows(),
        b5_parity_rows=_b5_parity_rows(),
    )

    assert {path.name for path in outputs} == {
        "existing_torsion_twist_evidence_triage.csv",
        "existing_torsion_twist_evidence_triage.json",
        "existing_torsion_twist_evidence_triage.md",
    }
    report = (tmp_path / "existing_torsion_twist_evidence_triage.md").read_text(
        encoding="utf-8"
    )
    assert "Existing Torsion/Twist Evidence Triage" in report
    assert "not aeroelastic signoff" in report
    assert "direct_my_torque_observable_surrogate_policy_open" in report
