from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase32_rear_spar_rib_bracing_diagnostic import (
    build_rear_spar_rib_bracing_diagnostic,
    write_rear_spar_rib_bracing_diagnostic_package,
)


def _row(
    variant_id: str,
    *,
    tip_delta_pct: float,
    max_vertical_delta_pct: float,
    angle_delta_deg: float,
    link_force_max_n: float,
) -> SimpleNamespace:
    return SimpleNamespace(
        variant_id=variant_id,
        tip_main_delta_vs_baseline_pct=tip_delta_pct,
        max_vertical_delta_vs_baseline_pct=max_vertical_delta_pct,
        angle_delta_vs_baseline_deg=angle_delta_deg,
        link_force_max_n=link_force_max_n,
    )


def _audit() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        rows=(
            _row(
                "baseline_joint_only",
                tip_delta_pct=0.0,
                max_vertical_delta_pct=0.0,
                angle_delta_deg=0.0,
                link_force_max_n=3055.2,
            ),
            _row(
                "dense_finite_rib_surrogate",
                tip_delta_pct=-17.7,
                max_vertical_delta_pct=-17.2,
                angle_delta_deg=-8.3,
                link_force_max_n=934.5,
            ),
            _row(
                "rear_stiffness_5pct",
                tip_delta_pct=292.6,
                max_vertical_delta_pct=295.8,
                angle_delta_deg=36.3,
                link_force_max_n=1201.8,
            ),
        ),
    )


def test_rear_spar_rib_bracing_diagnostic_extracts_engineering_signals_without_signoff() -> None:
    diagnostic = build_rear_spar_rib_bracing_diagnostic(_audit())

    assert diagnostic.overall_status == "bracing_sensitivity_present_not_signoff"
    by_key = {row.key: row for row in diagnostic.rows}
    assert by_key["rear_spar_stiffness"].status == "strong_model_sensitivity_not_signoff"
    assert by_key["rear_spar_stiffness"].tip_delta_pct == pytest.approx(292.6)
    assert by_key["rear_spar_stiffness"].model_bias_guardrail == "internal_model_bias_guardrail_required"
    assert "rear spar cannot be ignored" in by_key["rear_spar_stiffness"].engineering_read
    assert by_key["rib_load_transfer"].status == "surrogate_load_transfer_not_signoff"
    assert by_key["rib_load_transfer"].link_force_max_n == pytest.approx(934.5)
    assert "finite-rib surrogate" in by_key["rib_load_transfer"].engineering_read


def test_rear_spar_rib_bracing_diagnostic_does_not_claim_effective_when_variants_missing() -> None:
    diagnostic = build_rear_spar_rib_bracing_diagnostic(
        SimpleNamespace(candidate_id="sample", rows=())
    )

    assert diagnostic.overall_status == "bracing_sensitivity_missing_not_signed_off"
    assert {row.status for row in diagnostic.rows} == {
        "model_sensitivity_weak_or_missing",
        "surrogate_load_transfer_missing",
    }


def test_write_rear_spar_rib_bracing_diagnostic_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_rear_spar_rib_bracing_diagnostic_package(
        tmp_path,
        _audit(),
    )

    assert {path.name for path in outputs} == {
        "rear_spar_rib_bracing_diagnostic.csv",
        "rear_spar_rib_bracing_diagnostic.json",
        "rear_spar_rib_bracing_diagnostic.md",
    }
    report = (tmp_path / "rear_spar_rib_bracing_diagnostic.md").read_text(encoding="utf-8")
    assert "bracing_sensitivity_present_not_signoff" in report
    assert "internal model bias" in report
    assert "not a full-wing FEM signoff" in report
