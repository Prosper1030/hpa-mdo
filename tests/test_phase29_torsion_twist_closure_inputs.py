from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase29_torsion_twist_closure_inputs import (
    build_torsion_twist_closure_check,
    write_torsion_twist_closure_input_package,
)


def _torsion_audit() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        equivalent_twist_max_deg=0.18,
        max_spar_pair_line_angle_delta_deg=33.0,
    )


def test_torsion_twist_closure_check_accepts_tip_ring_or_aeroelastic_inputs_only() -> None:
    check = build_torsion_twist_closure_check(
        _torsion_audit(),
        closure_inputs=(
            {
                "case_id": "tip-ring-fem",
                "closure_method": "tip_ring_fem",
                "measured_twist_deg": "2.2",
                "twist_limit_deg": "5.0",
                "torque_balance_error_pct": "4.0",
                "max_allowed_torque_balance_error_pct": "10.0",
                "source": "FEM placeholder",
            },
            {
                "case_id": "single-node",
                "closure_method": "single_node_displacement",
                "measured_twist_deg": "1.0",
                "twist_limit_deg": "5.0",
                "torque_balance_error_pct": "2.0",
                "max_allowed_torque_balance_error_pct": "10.0",
                "source": "bad observable",
            },
        ),
    )

    assert check.overall_status == "torsion_twist_closure_not_closed"
    by_case = {row.case_id: row for row in check.rows}
    assert by_case["tip-ring-fem"].status == "margin_positive_input_check_only"
    assert by_case["tip-ring-fem"].twist_margin_deg == pytest.approx(2.8)
    assert by_case["tip-ring-fem"].torque_balance_margin_pct == pytest.approx(6.0)
    assert by_case["single-node"].status == "invalid_twist_observable"
    assert "tip-ring" in by_case["single-node"].engineering_note


def test_torsion_twist_closure_check_marks_missing_inputs() -> None:
    check = build_torsion_twist_closure_check(_torsion_audit(), closure_inputs=())

    assert check.overall_status == "torsion_twist_closure_not_closed"
    assert len(check.rows) == 1
    assert check.rows[0].status == "closure_input_missing"
    assert check.rows[0].measured_twist_deg is None
    assert check.rows[0].max_spar_pair_line_angle_delta_deg == pytest.approx(33.0)


def test_write_torsion_twist_closure_input_package_creates_template_and_report(tmp_path: Path) -> None:
    outputs = write_torsion_twist_closure_input_package(
        tmp_path,
        _torsion_audit(),
        closure_inputs=(),
    )

    assert {path.name for path in outputs} == {
        "torsion_twist_closure_check.csv",
        "torsion_twist_closure_check.json",
        "torsion_twist_closure_check.md",
        "torsion_twist_closure_inputs_template.csv",
    }
    template = (tmp_path / "torsion_twist_closure_inputs_template.csv").read_text(encoding="utf-8")
    assert "tip_ring_fem" in template
    assert "aeroelastic_loop" in template
    report = (tmp_path / "torsion_twist_closure_check.md").read_text(encoding="utf-8")
    assert "torsion/twist closure inputs" in report
    assert "not aeroelastic signoff" in report
