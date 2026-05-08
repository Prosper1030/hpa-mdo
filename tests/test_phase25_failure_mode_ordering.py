from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import phase25_failure_mode_ordering as phase25
from scripts.phase25_failure_mode_ordering import (
    build_failure_mode_ordering,
    write_failure_mode_ordering_package,
)


def _claim_review() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        modeled_first_limiter_with_current_wire="wire_tension_body_allowable",
        modeled_first_limiter_with_6kn_wire="tip_deflection",
        current_wire_body_limit_load_factor=3.0,
        tip_deflection_limit_load_factor=4.0,
        wire6_body_limit_load_factor=12.0,
    )


def _detail_requirements() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(
                key="wire_attach_local_load_path",
                required_allowable_load_n=6000.0,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=None,
                body_allowable_margin_n=None,
            ),
            SimpleNamespace(
                key="root_joint",
                required_allowable_load_n=20.0,
                required_allowable_moment_n_m=10000.0,
                required_minimum_breaking_load_n=None,
                body_allowable_margin_n=None,
            ),
            SimpleNamespace(
                key="wire_termination",
                required_allowable_load_n=6000.0,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=10000.0,
                body_allowable_margin_n=-1000.0,
            ),
        )
    )


def _rib_spacing_requirements() -> SimpleNamespace:
    return SimpleNamespace(
        total_added_bracing_stations=53,
        recommended_station_count=61,
        max_recommended_subbay_m=0.297,
    )


def test_failure_mode_ordering_keeps_ranked_model_modes_separate_from_unranked_hardware_modes() -> None:
    ordering = build_failure_mode_ordering(
        _claim_review(),
        detail_requirements=_detail_requirements(),
        rib_spacing_requirements=_rib_spacing_requirements(),
    )

    assert ordering.overall_status == "true_failure_order_not_closed"
    assert ordering.modeled_first_limiter_with_current_wire == "wire_tension_body_allowable"
    assert ordering.modeled_first_limiter_with_6kn_wire == "tip_deflection"
    assert ordering.known_unranked_mode_count == 7
    by_key = {row.mode_key: row for row in ordering.rows}
    assert by_key["wire_tension_body_allowable_current"].load_factor == pytest.approx(3.0)
    assert by_key["tip_deflection_limit"].status == "design_validity_gate_not_fracture"
    assert by_key["wire_termination"].order_bucket == "unranked_real_structure_mode"
    assert by_key["wire_termination"].required_minimum_breaking_load_n == pytest.approx(10000.0)
    assert by_key["wire_termination"].body_allowable_margin_n == pytest.approx(-1000.0)
    assert "added stations=53" in by_key["rib_load_transfer"].evidence
    assert by_key["full_wing_global_buckling"].load_factor is None


def test_write_failure_mode_ordering_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_failure_mode_ordering_package(
        tmp_path,
        _claim_review(),
        detail_requirements=_detail_requirements(),
        rib_spacing_requirements=_rib_spacing_requirements(),
    )

    assert {path.name for path in outputs} == {
        "failure_mode_ordering.csv",
        "failure_mode_ordering.json",
        "failure_mode_ordering.md",
    }
    report = (tmp_path / "failure_mode_ordering.md").read_text(encoding="utf-8")
    assert "true failure order is not closed" in report
    assert "Ranked Internal Modes" in report
    assert "Unranked Real-Structure Modes" in report


def test_main_creates_requested_output_directory_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        phase25,
        "build_current_failure_mode_ordering",
        lambda: build_failure_mode_ordering(
            _claim_review(),
            detail_requirements=_detail_requirements(),
            rib_spacing_requirements=_rib_spacing_requirements(),
        ),
    )
    out_dir = tmp_path / "nested" / "phase25"

    assert phase25.main(["--output-dir", str(out_dir)]) == 0

    assert (out_dir / "failure_mode_ordering.md").exists()
