from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase37_torsion_twist_screening import (
    build_torsion_twist_screening,
    write_torsion_twist_screening_package,
)


def _torsion_audit() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        equivalent_twist_max_deg=0.1846,
        max_spar_pair_line_angle_delta_deg=33.662,
    )


def _bracing_audit() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(
                variant_id="baseline_joint_only",
                max_spar_pair_line_angle_delta_deg=13.39,
                angle_delta_vs_baseline_deg=0.0,
            ),
            SimpleNamespace(
                variant_id="dense_finite_rib_surrogate",
                max_spar_pair_line_angle_delta_deg=5.05,
                angle_delta_vs_baseline_deg=-8.34,
            ),
            SimpleNamespace(
                variant_id="rear_stiffness_5pct",
                max_spar_pair_line_angle_delta_deg=49.68,
                angle_delta_vs_baseline_deg=36.29,
            ),
        )
    )


def _closure_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="torsion_twist_closure_not_closed",
        accepted_closure_methods=("tip_ring_fem", "aeroelastic_loop", "apdl_tip_ring_fem"),
        rows=(
            SimpleNamespace(
                status="closure_input_missing",
                measured_twist_deg=None,
                twist_margin_deg=None,
                torque_balance_margin_pct=None,
            ),
        ),
    )


def _mixed_closure_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="torsion_twist_closure_not_closed",
        accepted_closure_methods=("tip_ring_fem", "aeroelastic_loop", "apdl_tip_ring_fem"),
        rows=(
            SimpleNamespace(
                status="margin_positive_input_check_only",
                measured_twist_deg=2.0,
                twist_margin_deg=1.0,
                torque_balance_margin_pct=3.0,
            ),
            SimpleNamespace(
                status="margin_negative",
                measured_twist_deg=6.0,
                twist_margin_deg=-1.0,
                torque_balance_margin_pct=3.0,
            ),
        ),
    )


def test_torsion_twist_screening_collects_internal_signals_without_signoff() -> None:
    screening = build_torsion_twist_screening(
        _torsion_audit(),
        bracing_audit=_bracing_audit(),
        closure_check=_closure_check(),
    )

    assert screening.overall_status == "torsion_twist_screening_not_aeroelastic_signoff"
    assert screening.internal_equivalent_twist_deg == pytest.approx(0.1846)
    assert screening.max_spar_pair_line_angle_delta_deg == pytest.approx(33.662)
    assert screening.dense_finite_rib_angle_delta_deg == pytest.approx(-8.34)
    assert screening.rear_soft_angle_delta_deg == pytest.approx(36.29)
    assert screening.closure_input_status == "closure_input_missing"
    assert screening.accepted_closure_methods == (
        "tip_ring_fem",
        "aeroelastic_loop",
        "apdl_tip_ring_fem",
    )

    by_key = {row.signal_key: row for row in screening.rows}
    assert by_key["internal_equivalent_twist"].status == (
        "internal_beam_twist_diagnostic_not_signoff"
    )
    assert by_key["spar_pair_line_angle"].value == pytest.approx(33.662)
    assert by_key["dense_finite_rib_angle_delta"].value == pytest.approx(-8.34)
    assert by_key["closure_input"].status == "closure_input_missing"
    assert "not aeroelastic signoff" in by_key["spar_pair_line_angle"].signoff_boundary
    assert "tip-ring FEM" in by_key["closure_input"].next_evidence


def test_torsion_twist_screening_reports_blocked_closure_row_not_first_positive() -> None:
    screening = build_torsion_twist_screening(
        _torsion_audit(),
        bracing_audit=_bracing_audit(),
        closure_check=_mixed_closure_check(),
    )

    assert screening.closure_input_status == "margin_negative"
    by_key = {row.signal_key: row for row in screening.rows}
    assert by_key["closure_input"].status == "margin_negative"


def test_write_torsion_twist_screening_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_torsion_twist_screening_package(
        tmp_path,
        _torsion_audit(),
        bracing_audit=_bracing_audit(),
        closure_check=_closure_check(),
    )

    assert {path.name for path in outputs} == {
        "torsion_twist_screening.csv",
        "torsion_twist_screening.json",
        "torsion_twist_screening.md",
    }
    report = (tmp_path / "torsion_twist_screening.md").read_text(encoding="utf-8")
    assert "torsion_twist_screening_not_aeroelastic_signoff" in report
    assert "spar-pair line angle is not aero twist" in report
    assert "tip_ring_fem; aeroelastic_loop; apdl_tip_ring_fem" in report
