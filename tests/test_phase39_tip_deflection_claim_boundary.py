from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase39_tip_deflection_claim_boundary import (
    build_tip_deflection_claim_boundary,
    write_tip_deflection_claim_boundary_package,
)


def _reference() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        reference_load_factor=2.0,
        tip_deflection_m=1.5432,
        tip_deflection_limit_m=2.55,
    )


def _revalidation_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="tip_deflection_current_submission_gate_retained",
        current_raw_tip_limit_m=2.5,
        current_effective_tip_limit_m=2.55,
        rows=(
            SimpleNamespace(
                status="current_submission_gate_retained",
                proposed_raw_tip_limit_m=2.5,
                proposed_effective_tip_limit_m=2.55,
                deflection_limit_load_factor=3.3049,
                missing_rechecks="",
            ),
        ),
    )


def _mixed_revalidation_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="tip_deflection_submission_gate_not_revalidated",
        current_raw_tip_limit_m=2.5,
        current_effective_tip_limit_m=2.55,
        rows=(
            SimpleNamespace(
                case_id="current_2p5m_submission_gate",
                usage_context="submission",
                status="current_submission_gate_retained",
                proposed_raw_tip_limit_m=2.5,
                proposed_effective_tip_limit_m=2.55,
                deflection_limit_load_factor=3.3049,
                missing_rechecks="",
            ),
            SimpleNamespace(
                case_id="relaxed_submission_gate",
                usage_context="submission",
                status="submission_revalidation_missing",
                proposed_raw_tip_limit_m=2.75,
                proposed_effective_tip_limit_m=2.805,
                deflection_limit_load_factor=3.6354,
                missing_rechecks="aeroelastic_rechecked;clearance_rechecked;load_path_rechecked",
            ),
        ),
    )


def test_tip_deflection_claim_boundary_keeps_gate_as_design_validity_not_fracture() -> None:
    boundary = build_tip_deflection_claim_boundary(
        _reference(),
        revalidation_check=_revalidation_check(),
    )

    assert boundary.overall_status == "tip_deflection_claim_boundary_submission_gate_retained"
    assert boundary.current_raw_tip_limit_m == pytest.approx(2.5)
    assert boundary.current_effective_tip_limit_m == pytest.approx(2.55)
    assert boundary.deflection_limit_load_factor == pytest.approx(3.3049)
    assert boundary.revalidation_status == "tip_deflection_current_submission_gate_retained"
    assert boundary.missing_submission_rechecks == ""

    by_key = {row.policy_key: row for row in boundary.rows}
    assert by_key["current_submission_gate"].status == "design_validity_gate_not_fracture"
    assert "2.5 m raw tip limit remains" in by_key["current_submission_gate"].allowed_statement
    assert "Do not treat the 2.5 m raw gate as a fracture point" in by_key[
        "current_submission_gate"
    ].blocked_statement
    assert by_key["exploration_relaxation"].status == "exploration_only_not_submission"
    assert by_key["submission_relaxation"].status == "submission_relaxation_requires_rechecks"
    assert "loaded-shape; aeroelastic; clearance; load-path" in by_key[
        "submission_relaxation"
    ].required_evidence


def test_tip_deflection_claim_boundary_uses_whole_revalidation_check_not_first_row() -> None:
    boundary = build_tip_deflection_claim_boundary(
        _reference(),
        revalidation_check=_mixed_revalidation_check(),
    )

    assert boundary.overall_status == "tip_deflection_claim_boundary_revalidation_required"
    assert boundary.revalidation_status == "tip_deflection_submission_gate_not_revalidated"
    assert "relaxed_submission_gate" in boundary.missing_submission_rechecks
    assert "aeroelastic_rechecked" in boundary.missing_submission_rechecks


def test_write_tip_deflection_claim_boundary_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_tip_deflection_claim_boundary_package(
        tmp_path,
        _reference(),
        revalidation_check=_revalidation_check(),
    )

    assert {path.name for path in outputs} == {
        "tip_deflection_claim_boundary.csv",
        "tip_deflection_claim_boundary.json",
        "tip_deflection_claim_boundary.md",
    }
    report = (tmp_path / "tip_deflection_claim_boundary.md").read_text(encoding="utf-8")
    assert "tip_deflection_claim_boundary_submission_gate_retained" in report
    assert "not a fracture point" in report
    assert "Exploration-only" in report
