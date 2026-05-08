from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase27_detail_margin_inputs import (
    build_detail_margin_check,
    write_detail_margin_input_package,
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


def test_detail_margin_check_computes_margins_without_promoting_to_signoff() -> None:
    check = build_detail_margin_check(
        _requirements(),
        hardware_allowables=(
            {
                "key": "wire_attach_local_load_path",
                "component_id": "attach-ring-a",
                "allowable_load_n": "7200",
                "allowable_basis": "bench_coupon_limit_load",
                "source": "bench coupon placeholder",
            },
            {
                "key": "root_joint",
                "component_id": "root-fitting-a",
                "allowable_load_n": "50",
                "allowable_moment_n_m": "9500",
                "allowable_basis": "prelim_hand_calc_limit_load",
                "source": "prelim hand calc",
            },
            {
                "key": "wire_termination",
                "component_id": "termination-a",
                "allowable_load_n": "6500",
                "minimum_breaking_load_n": "12000",
                "allowable_basis": "vendor_mbl_with_swage_efficiency",
                "termination_efficiency": "0.60",
                "source": "vendor datasheet placeholder",
            },
        ),
    )

    assert check.overall_status == "hardware_input_margins_not_closed"
    by_key = {row.key: row for row in check.rows}
    assert by_key["wire_attach_local_load_path"].status == "margin_positive_input_check_only"
    assert by_key["wire_attach_local_load_path"].load_margin_n == pytest.approx(1200.0)
    assert by_key["root_joint"].status == "margin_negative"
    assert by_key["root_joint"].moment_margin_n_m == pytest.approx(-500.0)
    assert by_key["wire_termination"].status == "margin_positive_input_check_only"
    assert by_key["wire_termination"].mbl_margin_n == pytest.approx(2000.0)
    assert by_key["wire_termination"].traceability_status == "traceable_input"
    assert "not FEM signoff" in by_key["wire_termination"].engineering_note


def test_detail_margin_check_requires_traceable_hardware_inputs() -> None:
    check = build_detail_margin_check(
        _requirements(),
        hardware_allowables=(
            {
                "key": "wire_attach_local_load_path",
                "component_id": "",
                "allowable_load_n": "7200",
                "source": "bench coupon placeholder",
            },
            {
                "key": "root_joint",
                "component_id": "root-fitting-a",
                "allowable_load_n": "50",
                "allowable_moment_n_m": "12000",
                "allowable_basis": "prelim_hand_calc_limit_load",
                "source": "",
            },
            {
                "key": "wire_termination",
                "component_id": "termination-a",
                "allowable_load_n": "6500",
                "minimum_breaking_load_n": "12000",
                "allowable_basis": "vendor_mbl_without_process_efficiency",
                "source": "vendor datasheet placeholder",
            },
        ),
    )

    by_key = {row.key: row for row in check.rows}
    assert check.overall_status == "hardware_input_margins_not_closed"
    assert by_key["wire_attach_local_load_path"].status == "hardware_traceability_missing"
    assert by_key["wire_attach_local_load_path"].traceability_status == "component_id_missing"
    assert by_key["root_joint"].status == "hardware_traceability_missing"
    assert by_key["root_joint"].traceability_status == "source_missing"
    assert by_key["wire_termination"].status == "termination_derate_missing"
    assert by_key["wire_termination"].traceability_status == "termination_efficiency_or_derate_missing"


def test_detail_margin_check_marks_missing_hardware_inputs() -> None:
    check = build_detail_margin_check(_requirements(), hardware_allowables=())

    assert check.overall_status == "hardware_input_margins_not_closed"
    assert all(row.status == "hardware_allowable_missing" for row in check.rows)
    assert all(row.worst_margin is None for row in check.rows)


def test_write_detail_margin_input_package_creates_template_and_report(tmp_path: Path) -> None:
    outputs = write_detail_margin_input_package(
        tmp_path,
        _requirements(),
        hardware_allowables=(
            {
                "key": "wire_termination",
                "component_id": "termination-a",
                "allowable_load_n": "6500",
                "minimum_breaking_load_n": "12000",
                "allowable_basis": "vendor_mbl_with_swage_efficiency",
                "termination_efficiency": "0.60",
                "source": "vendor datasheet placeholder",
            },
        ),
    )

    assert {path.name for path in outputs} == {
        "detail_margin_check.csv",
        "detail_margin_check.json",
        "detail_margin_check.md",
        "detail_margin_inputs_template.csv",
    }
    template = (tmp_path / "detail_margin_inputs_template.csv").read_text(encoding="utf-8")
    assert "wire_attach_local_load_path" in template
    assert "required_allowable_load_n" in template
    report = (tmp_path / "detail_margin_check.md").read_text(encoding="utf-8")
    assert "hardware input margins" in report
    assert "not FEM signoff" in report
    assert "vendor_mbl_with_swage_efficiency" in report
    assert "0.600" in report
