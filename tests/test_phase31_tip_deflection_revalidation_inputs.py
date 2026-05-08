from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase31_tip_deflection_revalidation_inputs import (
    build_tip_deflection_revalidation_check,
    write_tip_deflection_revalidation_input_package,
)


def _reference() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        reference_load_factor=2.0,
        tip_deflection_m=1.5432,
        tip_deflection_limit_m=2.55,
    )


def test_tip_deflection_revalidation_allows_relaxed_exploration_but_not_submission_claim() -> None:
    check = build_tip_deflection_revalidation_check(
        _reference(),
        revalidation_inputs=(
            {
                "case_id": "explore-3m",
                "usage_context": "exploration",
                "proposed_raw_tip_limit_m": "3.0",
                "loaded_shape_rechecked": "false",
                "aeroelastic_rechecked": "false",
                "clearance_rechecked": "false",
                "load_path_rechecked": "false",
                "source": "trade-study placeholder",
            },
            {
                "case_id": "submission-3m-no-recheck",
                "usage_context": "submission",
                "proposed_raw_tip_limit_m": "3.0",
                "loaded_shape_rechecked": "true",
                "aeroelastic_rechecked": "false",
                "clearance_rechecked": "true",
                "load_path_rechecked": "true",
                "source": "incomplete submission placeholder",
            },
        ),
    )

    assert check.overall_status == "tip_deflection_submission_gate_not_revalidated"
    by_case = {row.case_id: row for row in check.rows}
    assert by_case["explore-3m"].status == "exploration_only_not_submission"
    assert by_case["explore-3m"].deflection_limit_load_factor == pytest.approx(3.9658, rel=1e-4)
    assert by_case["submission-3m-no-recheck"].status == "submission_revalidation_missing"
    assert by_case["submission-3m-no-recheck"].missing_rechecks == "aeroelastic_rechecked"


def test_tip_deflection_revalidation_accepts_submission_relaxation_only_with_all_rechecks() -> None:
    check = build_tip_deflection_revalidation_check(
        _reference(),
        revalidation_inputs=(
            {
                "case_id": "submission-2p75",
                "usage_context": "submission",
                "proposed_raw_tip_limit_m": "2.75",
                "loaded_shape_rechecked": "true",
                "aeroelastic_rechecked": "true",
                "clearance_rechecked": "true",
                "load_path_rechecked": "true",
                "source": "qualified recheck placeholder",
            },
        ),
    )

    assert check.overall_status == "tip_deflection_revalidation_inputs_pass_not_submission_signoff"
    row = check.rows[0]
    assert row.status == "submission_revalidation_input_check_only"
    assert row.proposed_effective_tip_limit_m == pytest.approx(2.805)
    assert row.deflection_limit_load_factor == pytest.approx(3.6353, rel=1e-4)


def test_tip_deflection_revalidation_marks_missing_input_as_current_gate_retained() -> None:
    check = build_tip_deflection_revalidation_check(_reference(), revalidation_inputs=())

    assert check.overall_status == "tip_deflection_current_submission_gate_retained"
    assert len(check.rows) == 1
    row = check.rows[0]
    assert row.status == "current_submission_gate_retained"
    assert row.current_raw_tip_limit_m == pytest.approx(2.5)
    assert row.proposed_raw_tip_limit_m == pytest.approx(2.5)


def test_write_tip_deflection_revalidation_input_package_creates_template_and_report(
    tmp_path: Path,
) -> None:
    outputs = write_tip_deflection_revalidation_input_package(
        tmp_path,
        _reference(),
        revalidation_inputs=(),
    )

    assert {path.name for path in outputs} == {
        "tip_deflection_revalidation_check.csv",
        "tip_deflection_revalidation_check.json",
        "tip_deflection_revalidation_check.md",
        "tip_deflection_revalidation_inputs_template.csv",
    }
    template = (tmp_path / "tip_deflection_revalidation_inputs_template.csv").read_text(
        encoding="utf-8"
    )
    assert "exploration" in template
    assert "submission" in template
    report = (tmp_path / "tip_deflection_revalidation_check.md").read_text(encoding="utf-8")
    assert "tip-deflection revalidation inputs" in report
    assert "not a fracture point" in report
