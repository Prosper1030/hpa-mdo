from __future__ import annotations

from pathlib import Path

import pytest

from hpa_mdo.structure.dual_beam_mainline import AnalysisModeName, LinkMode
from scripts.phase22_bracing_sensitivity import (
    build_bracing_sensitivity_audit,
    clone_with_rear_stiffness_scale,
    write_bracing_sensitivity_package,
)
from tests.test_dual_beam_mainline import _simple_model


def test_clone_with_rear_stiffness_scale_preserves_loads_but_softens_rear_sections() -> None:
    model = _simple_model()
    softened = clone_with_rear_stiffness_scale(model, 0.05)

    assert softened is not model
    assert softened.lift_per_span_npm is not model.lift_per_span_npm
    assert softened.rear_iy_m4[0] == pytest.approx(model.rear_iy_m4[0] * 0.05)
    assert softened.rear_j_m4[0] == pytest.approx(model.rear_j_m4[0] * 0.05)
    assert softened.rear_area_m2[0] == pytest.approx(model.rear_area_m2[0] * 0.05)
    assert softened.lift_per_span_npm[1] == pytest.approx(model.lift_per_span_npm[1])


def test_bracing_sensitivity_audit_runs_required_report_only_variants() -> None:
    model = _simple_model(
        lift_per_span_npm=[0.0, 18.0, 36.0],
        torque_per_span_nmpm=[0.0, -4.0, -8.0],
        joint_node_indices=(1,),
        wire_node_indices=(1,),
    )

    audit = build_bracing_sensitivity_audit("sample", model)

    assert audit.overall_status == "report_only_bracing_sensitivity_not_signoff"
    assert [row.variant_id for row in audit.rows] == [
        "baseline_joint_only",
        "dense_rigid_links",
        "dense_finite_rib_surrogate",
        "rear_stiffness_5pct",
    ]
    baseline = audit.rows[0]
    assert baseline.mode == AnalysisModeName.DUAL_BEAM_PRODUCTION.value
    assert baseline.link_mode == LinkMode.JOINT_ONLY_OFFSET_RIGID.value
    assert baseline.tip_main_delta_vs_baseline_pct == pytest.approx(0.0)
    assert all(row.status == "solved_report_only" for row in audit.rows)


def test_write_bracing_sensitivity_package_creates_handoff_files(tmp_path: Path) -> None:
    model = _simple_model(
        lift_per_span_npm=[0.0, 18.0, 36.0],
        torque_per_span_nmpm=[0.0, -4.0, -8.0],
        joint_node_indices=(1,),
        wire_node_indices=(1,),
    )

    outputs = write_bracing_sensitivity_package(tmp_path, "sample", model)

    assert {path.name for path in outputs} == {
        "bracing_sensitivity.csv",
        "bracing_sensitivity.json",
        "bracing_sensitivity.md",
    }
    report = (tmp_path / "bracing_sensitivity.md").read_text(encoding="utf-8")
    assert "report-only sensitivity" in report
    assert "compare deltas only" in report
    assert "rear_stiffness_5pct" in report
    assert "not a full-wing FEM signoff" in report
