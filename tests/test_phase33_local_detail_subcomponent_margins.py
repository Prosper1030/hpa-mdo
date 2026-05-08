from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase33_local_detail_subcomponent_margins import (
    build_local_detail_subcomponent_margin_check,
    write_local_detail_subcomponent_margin_package,
)


def _requirements() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        rows=(
            SimpleNamespace(
                key="wire_attach_local_load_path",
                title="Wire attach local load path",
                required_allowable_load_n=6000.0,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=None,
            ),
            SimpleNamespace(
                key="root_joint",
                title="Root joint",
                required_allowable_load_n=20.0,
                required_allowable_moment_n_m=10000.0,
                required_minimum_breaking_load_n=None,
            ),
            SimpleNamespace(
                key="wire_termination",
                title="Wire termination",
                required_allowable_load_n=6000.0,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=10000.0,
            ),
        ),
    )


def test_subcomponent_margin_check_expands_detail_requirements_without_signoff() -> None:
    check = build_local_detail_subcomponent_margin_check(
        _requirements(),
        subcomponent_allowables=(
            {
                "parent_key": "wire_attach_local_load_path",
                "subcomponent_key": "attach_ring_or_lug",
                "component_id": "ring-a",
                "allowable_load_n": "7200",
                "allowable_basis": "coupon_limit_load",
                "evidence_type": "coupon_test",
                "source": "coupon placeholder",
            },
            {
                "parent_key": "wire_attach_local_load_path",
                "subcomponent_key": "bonded_load_path",
                "component_id": "bond-a",
                "allowable_load_n": "5800",
                "allowable_basis": "bond_coupon_limit_load",
                "evidence_type": "coupon_test",
                "source": "coupon placeholder",
            },
            {
                "parent_key": "root_joint",
                "subcomponent_key": "root_fitting_or_clamp",
                "component_id": "root-clamp-a",
                "allowable_load_n": "50",
                "allowable_moment_n_m": "12000",
                "allowable_basis": "root_clamp_hand_calc",
                "evidence_type": "hand_calc",
                "source": "prelim hand calc",
            },
            {
                "parent_key": "wire_termination",
                "subcomponent_key": "termination_process_efficiency",
                "component_id": "swage-a",
                "allowable_load_n": "7000",
                "minimum_breaking_load_n": "13000",
                "allowable_basis": "vendor_mbl_with_process_efficiency",
                "evidence_type": "vendor_datasheet",
                "source": "vendor placeholder",
            },
        ),
    )

    assert check.overall_status == "local_detail_subcomponent_margins_not_closed"
    assert check.total_subcomponent_count == 11
    assert check.missing_subcomponent_count == 7
    assert check.negative_margin_count == 1
    assert check.traceability_gap_count == 0
    by_key = {(row.parent_key, row.subcomponent_key): row for row in check.rows}
    assert by_key[("wire_attach_local_load_path", "attach_ring_or_lug")].status == (
        "margin_positive_input_check_only"
    )
    assert by_key[("wire_attach_local_load_path", "attach_ring_or_lug")].load_margin_n == (
        pytest.approx(1200.0)
    )
    assert by_key[("wire_attach_local_load_path", "bonded_load_path")].status == (
        "margin_negative"
    )
    assert by_key[("wire_attach_local_load_path", "bonded_load_path")].load_margin_n == (
        pytest.approx(-200.0)
    )
    root = by_key[("root_joint", "root_fitting_or_clamp")]
    assert root.moment_margin_n_m == pytest.approx(2000.0)
    termination = by_key[("wire_termination", "termination_process_efficiency")]
    assert termination.mbl_margin_n == pytest.approx(3000.0)
    assert "not local FEM signoff" in termination.engineering_note


def test_subcomponent_margin_check_marks_every_required_segment_missing() -> None:
    check = build_local_detail_subcomponent_margin_check(
        _requirements(),
        subcomponent_allowables=(),
    )

    assert check.overall_status == "local_detail_subcomponent_margins_not_closed"
    assert check.total_subcomponent_count == 11
    assert check.missing_subcomponent_count == 11
    assert check.negative_margin_count == 0
    assert all(row.status == "subcomponent_allowable_missing" for row in check.rows)
    assert all(row.worst_margin is None for row in check.rows)


def test_subcomponent_margin_check_requires_traceable_subcomponent_inputs() -> None:
    check = build_local_detail_subcomponent_margin_check(
        _requirements(),
        subcomponent_allowables=(
            {
                "parent_key": "wire_attach_local_load_path",
                "subcomponent_key": "attach_ring_or_lug",
                "component_id": "",
                "allowable_load_n": "7200",
                "source": "coupon placeholder",
            },
            {
                "parent_key": "root_joint",
                "subcomponent_key": "root_fitting_or_clamp",
                "component_id": "root-clamp-a",
                "allowable_load_n": "50",
                "allowable_moment_n_m": "12000",
                "allowable_basis": "root_clamp_hand_calc",
                "source": "",
            },
        ),
    )

    by_key = {(row.parent_key, row.subcomponent_key): row for row in check.rows}
    assert check.overall_status == "local_detail_subcomponent_margins_not_closed"
    assert check.traceability_gap_count == 2
    ring = by_key[("wire_attach_local_load_path", "attach_ring_or_lug")]
    assert ring.status == "subcomponent_traceability_missing"
    assert ring.traceability_status == "component_id_missing"
    root = by_key[("root_joint", "root_fitting_or_clamp")]
    assert root.status == "subcomponent_traceability_missing"
    assert root.traceability_status == "source_missing"


def test_subcomponent_margin_check_can_pass_inputs_without_promoting_to_fem_signoff() -> None:
    allowables = []
    for parent_key, subcomponent_key in (
        ("wire_attach_local_load_path", "attach_ring_or_lug"),
        ("wire_attach_local_load_path", "bonded_load_path"),
        ("wire_attach_local_load_path", "insert_pullout_bearing"),
        ("wire_attach_local_load_path", "local_tube_wall_crushing"),
        ("root_joint", "root_fitting_or_clamp"),
        ("root_joint", "bonded_joint"),
        ("root_joint", "root_insert"),
        ("root_joint", "root_tube_wall_bearing"),
        ("wire_termination", "termination_process_efficiency"),
        ("wire_termination", "end_anchor_or_pin"),
        ("wire_termination", "bend_radius_creep_abrasion"),
    ):
        allowables.append(
            {
                "parent_key": parent_key,
                "subcomponent_key": subcomponent_key,
                "component_id": f"{subcomponent_key}-a",
                "allowable_load_n": "8000",
                "allowable_moment_n_m": "12000",
                "minimum_breaking_load_n": "13000",
                "allowable_basis": "positive_input_fixture",
                "evidence_type": "hand_calc",
                "source": "placeholder positive input",
            }
        )

    check = build_local_detail_subcomponent_margin_check(
        _requirements(),
        subcomponent_allowables=allowables,
    )

    assert check.overall_status == "local_detail_subcomponent_inputs_pass_not_fem_signoff"
    assert check.missing_subcomponent_count == 0
    assert check.negative_margin_count == 0
    assert check.traceability_gap_count == 0
    assert all(row.status == "margin_positive_input_check_only" for row in check.rows)


def test_write_subcomponent_margin_package_creates_template_and_report(tmp_path: Path) -> None:
    outputs = write_local_detail_subcomponent_margin_package(
        tmp_path,
        _requirements(),
        subcomponent_allowables=(
            {
                "parent_key": "wire_attach_local_load_path",
                "subcomponent_key": "attach_ring_or_lug",
                "component_id": "ring-a",
                "allowable_load_n": "7200",
                "allowable_basis": "coupon_limit_load",
                "evidence_type": "coupon_test",
                "source": "coupon placeholder",
            },
        ),
    )

    assert {path.name for path in outputs} == {
        "local_detail_subcomponent_margin_check.csv",
        "local_detail_subcomponent_margin_check.json",
        "local_detail_subcomponent_margin_check.md",
        "local_detail_subcomponent_margin_inputs_template.csv",
    }
    template = (tmp_path / "local_detail_subcomponent_margin_inputs_template.csv").read_text(
        encoding="utf-8"
    )
    assert "attach_ring_or_lug" in template
    assert "local_tube_wall_crushing" in template
    assert "allowable_basis" in template
    assert "evidence_type" in template
    report = (tmp_path / "local_detail_subcomponent_margin_check.md").read_text(
        encoding="utf-8"
    )
    assert "local detail subcomponent margins" in report
    assert "not local FEM signoff" in report
    assert "traceability-gap subcomponents" in report
    assert "traceability" in report
    assert "coupon_limit_load" in report
