from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase46_local_detail_criticality_ordering import (
    build_local_detail_criticality_ordering,
    write_local_detail_criticality_ordering_package,
)


def _detail_requirements() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(
                key="wire_attach_local_load_path",
                required_allowable_load_n=6048.2,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=None,
                body_allowable_margin_n=None,
            ),
            SimpleNamespace(
                key="root_joint",
                required_allowable_load_n=18.3,
                required_allowable_moment_n_m=10833.2,
                required_minimum_breaking_load_n=None,
                body_allowable_margin_n=None,
            ),
            SimpleNamespace(
                key="wire_termination",
                required_allowable_load_n=6048.2,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=10080.3,
                body_allowable_margin_n=-1466.7,
            ),
        )
    )


def _local_detail_subcomponent_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="local_detail_subcomponent_margins_not_closed",
        rows=(
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                subcomponent_key="attach_ring_or_lug",
                status="subcomponent_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
                effective_termination_load_margin_n=None,
            ),
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                subcomponent_key="bonded_load_path",
                status="subcomponent_moment_allowable_missing",
                load_margin_n=1200.0,
                moment_margin_n_m=None,
                mbl_margin_n=None,
                effective_termination_load_margin_n=None,
            ),
            SimpleNamespace(
                parent_key="root_joint",
                subcomponent_key="root_fitting_or_clamp",
                status="subcomponent_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
                effective_termination_load_margin_n=None,
            ),
            SimpleNamespace(
                parent_key="root_joint",
                subcomponent_key="bonded_joint",
                status="subcomponent_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
                effective_termination_load_margin_n=None,
            ),
            SimpleNamespace(
                parent_key="wire_termination",
                subcomponent_key="termination_process_efficiency",
                status="margin_negative",
                load_margin_n=100.0,
                moment_margin_n_m=None,
                mbl_margin_n=-500.0,
                effective_termination_load_margin_n=-800.0,
            ),
        ),
    )


def _wire_attach_load_decomposition() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="wire_attach_force_and_local_moment_defined_not_signoff",
        max_resultant_design_load_n=6048.2,
        max_resultant_design_local_moment_n_m=72.0,
        rows=(
            SimpleNamespace(component_key="spanwise_y", design_load_n=5839.2),
            SimpleNamespace(component_key="transverse_xz", design_load_n=1576.2),
            SimpleNamespace(component_key="vertical_z", design_load_n=1200.0),
        ),
    )


def _root_joint_load_envelope() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="root_joint_load_envelope_defined_not_signoff",
        design_root_force_n=18.3,
        design_root_bending_moment_n_m=10833.2,
        force_only_check_is_misleading=True,
        rows=(
            SimpleNamespace(
                load_case_key="moment_couple_arm_0p100m",
                required_couple_force_n=108332.0,
            ),
            SimpleNamespace(
                load_case_key="moment_couple_arm_0p050m",
                required_couple_force_n=216664.0,
            ),
        ),
    )


def _wire_termination_efficiency_sensitivity() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="termination_efficiency_sensitivity_defined_not_signoff",
        body_allowable_margin_n=-1466.7,
        rows=(
            SimpleNamespace(
                termination_efficiency=0.6,
                required_minimum_breaking_load_n=10080.3,
            ),
            SimpleNamespace(
                termination_efficiency=0.8,
                required_minimum_breaking_load_n=7560.2,
            ),
        ),
    )


def _existing_detail_allowable_evidence_triage() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="existing_detail_allowables_do_not_close_goal",
        row_count=5,
        closing_evidence_count=0,
        rows=(
            SimpleNamespace(
                blocker_key="wire_attach_local_load_path",
                status="local_subcomponent_allowables_missing",
                closes_engineering_margin=False,
                missing_allowable_rows=2,
                negative_margin_rows=0,
                traceability_gap_rows=0,
            ),
            SimpleNamespace(
                blocker_key="root_joint",
                status="local_subcomponent_allowables_missing",
                closes_engineering_margin=False,
                missing_allowable_rows=2,
                negative_margin_rows=0,
                traceability_gap_rows=0,
            ),
            SimpleNamespace(
                blocker_key="wire_termination",
                status="material_body_strength_not_termination_allowable",
                closes_engineering_margin=False,
                missing_allowable_rows=0,
                negative_margin_rows=1,
                traceability_gap_rows=0,
            ),
        ),
    )


def test_local_detail_criticality_ranks_work_priority_without_signoff() -> None:
    ordering = build_local_detail_criticality_ordering(
        "sample",
        detail_requirements=_detail_requirements(),
        local_detail_subcomponent_check=_local_detail_subcomponent_check(),
        wire_attach_load_decomposition=_wire_attach_load_decomposition(),
        root_joint_load_envelope=_root_joint_load_envelope(),
        wire_termination_efficiency_sensitivity=_wire_termination_efficiency_sensitivity(),
        existing_detail_allowable_evidence_triage=_existing_detail_allowable_evidence_triage(),
    )

    assert ordering.overall_status == "local_detail_work_priority_ranked_allowables_missing"
    assert ordering.row_count == 3
    assert ordering.unclosed_detail_count == 3
    assert ordering.highest_priority_key == "root_joint"

    by_key = {row.blocker_key: row for row in ordering.rows}
    assert by_key["root_joint"].work_priority_rank == 1
    assert by_key["wire_termination"].work_priority_rank == 2
    assert by_key["wire_attach_local_load_path"].work_priority_rank == 3

    root = by_key["root_joint"]
    assert root.governing_screen == "root_moment_couple_force"
    assert root.design_severity_n_equivalent == pytest.approx(216664.0)
    assert "root design moment=10833.2000 N*m" in root.demand_summary
    assert "max couple force=216664.0000 N" in root.demand_summary
    assert "force-only check is misleading" in root.engineering_read

    termination = by_key["wire_termination"]
    assert termination.governing_screen == "termination_required_mbl_eta_0p60"
    assert termination.design_severity_n_equivalent == pytest.approx(10080.3)
    assert "eta 0.60 MBL=10080.3000 N" in termination.demand_summary
    assert "body margin=-1466.7000 N" in termination.demand_summary
    assert termination.status == "work_priority_ranked_negative_or_missing_margin"

    attach = by_key["wire_attach_local_load_path"]
    assert attach.governing_screen == "wire_attach_resultant_design_load"
    assert attach.design_severity_n_equivalent == pytest.approx(6048.2)
    assert "spanwise design=5839.2000 N" in attach.demand_summary
    assert "transverse design=1576.2000 N" in attach.demand_summary
    assert "moment allowable gaps=1" in attach.local_allowable_gap_summary

    assert all(not row.closes_engineering_margin for row in ordering.rows)
    assert all(
        row.ordering_boundary == "work_priority_only_not_failure_load_factor_rank"
        for row in ordering.rows
    )


def test_write_local_detail_criticality_ordering_package_creates_handoff_files(
    tmp_path: Path,
) -> None:
    outputs = write_local_detail_criticality_ordering_package(
        tmp_path,
        "sample",
        detail_requirements=_detail_requirements(),
        local_detail_subcomponent_check=_local_detail_subcomponent_check(),
        wire_attach_load_decomposition=_wire_attach_load_decomposition(),
        root_joint_load_envelope=_root_joint_load_envelope(),
        wire_termination_efficiency_sensitivity=_wire_termination_efficiency_sensitivity(),
        existing_detail_allowable_evidence_triage=_existing_detail_allowable_evidence_triage(),
    )

    assert {path.name for path in outputs} == {
        "local_detail_criticality_ordering.csv",
        "local_detail_criticality_ordering.json",
        "local_detail_criticality_ordering.md",
    }
    report = (tmp_path / "local_detail_criticality_ordering.md").read_text(
        encoding="utf-8"
    )
    assert "Local Detail Criticality Ordering" in report
    assert "work_priority_only_not_failure_load_factor_rank" in report
    assert "root_moment_couple_force" in report
    assert "This is not local-detail signoff" in report
