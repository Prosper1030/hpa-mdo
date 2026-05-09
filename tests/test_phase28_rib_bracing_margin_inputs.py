from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase28_rib_bracing_margin_inputs import (
    build_rib_bracing_margin_check,
    write_rib_bracing_margin_input_package,
)

RIB_TRACEABLE_SOURCE = "output/phase28/rib_coupon_test_report.json"


def _spacing_requirements() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        target_bay_m=0.30,
        rows=(
            SimpleNamespace(
                bay_index=0,
                start_y_m=0.0,
                end_y_m=0.6,
                required_intermediate_stations=1,
                recommended_subbay_m=0.3,
                bay_vertical_load_scale_n=20.0,
            ),
            SimpleNamespace(
                bay_index=1,
                start_y_m=0.6,
                end_y_m=1.2,
                required_intermediate_stations=1,
                recommended_subbay_m=0.3,
                bay_vertical_load_scale_n=15.0,
            ),
        ),
    )


def _bracing_audit() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(variant_id="baseline_joint_only", link_force_max_n=3000.0),
            SimpleNamespace(variant_id="dense_finite_rib_surrogate", link_force_max_n=900.0),
        )
    )


def test_rib_bracing_margin_check_uses_finite_rib_surrogate_link_force_as_requirement() -> None:
    check = build_rib_bracing_margin_check(
        _spacing_requirements(),
        _bracing_audit(),
        rib_allowables=(
            {
                "bay_index": "0",
                "rib_family": "balsa_sheet_3mm",
                "allowable_link_force_n": "1200",
                "allowable_shear_force_n": "1000",
                "allowable_cap_force_n": "1050",
                "allowable_bond_force_n": "950",
                "allowable_main_spar_attach_force_n": "1100",
                "allowable_rear_spar_attach_force_n": "1150",
                "rib_lateral_stiffness_n_per_m": "25000",
                "allowable_basis": "rib_link_coupon_limit_load",
                "stiffness_basis": "finite_rib_beam_model",
                "evidence_type": "coupon_test",
                "attachment_basis": "bonded_spar_cap_shear_test",
                "covered_intermediate_station_count": "1",
                "covered_station_ids": "bay0-rib1",
                "covered_intermediate_station_y_m": "0.30",
                "source": RIB_TRACEABLE_SOURCE,
            },
            {
                "bay_index": "1",
                "rib_family": "balsa_sheet_3mm",
                "allowable_link_force_n": "1200",
                "allowable_shear_force_n": "1000",
                "allowable_cap_force_n": "1050",
                "allowable_bond_force_n": "800",
                "allowable_main_spar_attach_force_n": "1100",
                "allowable_rear_spar_attach_force_n": "1150",
                "rib_lateral_stiffness_n_per_m": "25000",
                "allowable_basis": "rib_link_coupon_limit_load",
                "stiffness_basis": "finite_rib_beam_model",
                "evidence_type": "coupon_test",
                "attachment_basis": "bonded_spar_cap_shear_test",
                "covered_intermediate_station_count": "1",
                "covered_station_ids": "bay1-rib1",
                "covered_intermediate_station_y_m": "0.90",
                "source": RIB_TRACEABLE_SOURCE,
            },
        ),
    )

    assert check.overall_status == "rib_bracing_margins_not_closed"
    assert check.required_link_force_n == pytest.approx(900.0)
    assert check.traceability_gap_count == 0
    assert check.station_coverage_gap_count == 0
    by_bay = {row.bay_index: row for row in check.rows}
    assert by_bay[0].status == "margin_positive_input_check_only"
    assert by_bay[0].bond_margin_n == pytest.approx(50.0)
    assert by_bay[0].cap_margin_n == pytest.approx(150.0)
    assert by_bay[0].main_spar_attach_margin_n == pytest.approx(200.0)
    assert by_bay[0].rear_spar_attach_margin_n == pytest.approx(250.0)
    assert by_bay[0].rib_lateral_stiffness_n_per_m == pytest.approx(25000.0)
    assert by_bay[0].covered_intermediate_station_count == 1
    assert by_bay[0].station_coverage_status == "station_coverage_satisfied"
    assert by_bay[0].max_unsupported_subbay_m == pytest.approx(0.3)
    assert by_bay[1].status == "margin_negative"
    assert by_bay[1].bond_margin_n == pytest.approx(-100.0)
    assert "not finite-rib FEM signoff" in by_bay[0].engineering_note


def test_rib_bracing_margin_check_marks_missing_allowables() -> None:
    check = build_rib_bracing_margin_check(
        _spacing_requirements(),
        _bracing_audit(),
        rib_allowables=(),
    )

    assert check.overall_status == "rib_bracing_margins_not_closed"
    assert all(row.status == "rib_stiffness_or_allowable_missing" for row in check.rows)
    assert all(row.worst_margin_n is None for row in check.rows)


def test_rib_bracing_margin_check_requires_stiffness_cap_and_spar_attach_inputs() -> None:
    check = build_rib_bracing_margin_check(
        _spacing_requirements(),
        _bracing_audit(),
        rib_allowables=(
            {
                "bay_index": "0",
                "rib_family": "balsa_sheet_3mm",
                "allowable_link_force_n": "1200",
                "allowable_shear_force_n": "1000",
                "allowable_bond_force_n": "950",
                "allowable_basis": "rib_link_coupon_limit_load",
                "evidence_type": "coupon_test",
                "attachment_basis": "bonded_spar_cap_shear_test",
                "covered_intermediate_station_count": "1",
                "covered_station_ids": "bay0-rib1",
                "covered_intermediate_station_y_m": "0.30",
                "source": RIB_TRACEABLE_SOURCE,
            },
        ),
    )

    by_bay = {row.bay_index: row for row in check.rows}
    assert by_bay[0].status == "rib_stiffness_or_allowable_missing"
    assert by_bay[0].allowable_cap_force_n is None
    assert by_bay[0].allowable_main_spar_attach_force_n is None
    assert by_bay[0].allowable_rear_spar_attach_force_n is None
    assert by_bay[0].rib_lateral_stiffness_n_per_m is None


def test_rib_bracing_margin_check_requires_traceable_rib_inputs() -> None:
    check = build_rib_bracing_margin_check(
        _spacing_requirements(),
        _bracing_audit(),
        rib_allowables=(
            {
                "bay_index": "0",
                "rib_family": "balsa_sheet_3mm",
                "allowable_link_force_n": "1200",
                "allowable_shear_force_n": "1000",
                "allowable_cap_force_n": "1050",
                "allowable_bond_force_n": "950",
                "allowable_main_spar_attach_force_n": "1100",
                "allowable_rear_spar_attach_force_n": "1150",
                "rib_lateral_stiffness_n_per_m": "25000",
                "source": RIB_TRACEABLE_SOURCE,
            },
            {
                "bay_index": "1",
                "rib_family": "",
                "allowable_link_force_n": "1200",
                "allowable_shear_force_n": "1000",
                "allowable_cap_force_n": "1050",
                "allowable_bond_force_n": "950",
                "allowable_main_spar_attach_force_n": "1100",
                "allowable_rear_spar_attach_force_n": "1150",
                "rib_lateral_stiffness_n_per_m": "25000",
                "allowable_basis": "rib_link_coupon_limit_load",
                "stiffness_basis": "finite_rib_beam_model",
                "evidence_type": "coupon_test",
                "attachment_basis": "bonded_spar_cap_shear_test",
                "source": RIB_TRACEABLE_SOURCE,
            },
        ),
    )

    by_bay = {row.bay_index: row for row in check.rows}
    assert check.overall_status == "rib_bracing_margins_not_closed"
    assert check.traceability_gap_count == 2
    assert by_bay[0].status == "rib_traceability_missing"
    assert by_bay[0].traceability_status == "allowable_basis_missing"
    assert by_bay[1].status == "rib_traceability_missing"
    assert by_bay[1].traceability_status == "rib_family_missing"


def test_rib_bracing_margin_check_rejects_placeholder_source_even_with_positive_margins() -> None:
    check = build_rib_bracing_margin_check(
        _spacing_requirements(),
        _bracing_audit(),
        rib_allowables=(
            {
                "bay_index": "0",
                "rib_family": "balsa_sheet_3mm",
                "allowable_link_force_n": "1200",
                "allowable_shear_force_n": "1000",
                "allowable_cap_force_n": "1050",
                "allowable_bond_force_n": "950",
                "allowable_main_spar_attach_force_n": "1100",
                "allowable_rear_spar_attach_force_n": "1150",
                "rib_lateral_stiffness_n_per_m": "25000",
                "allowable_basis": "rib_link_coupon_limit_load",
                "stiffness_basis": "finite_rib_beam_model",
                "evidence_type": "coupon_test",
                "attachment_basis": "bonded_spar_cap_shear_test",
                "covered_intermediate_station_count": "1",
                "covered_station_ids": "bay0-rib1",
                "covered_intermediate_station_y_m": "0.30",
                "source": "coupon placeholder",
            },
        ),
    )

    by_bay = {row.bay_index: row for row in check.rows}
    assert check.overall_status == "rib_bracing_margins_not_closed"
    assert check.traceability_gap_count == 1
    assert by_bay[0].status == "rib_traceability_missing"
    assert by_bay[0].traceability_status == "source_unqualified"


def test_rib_bracing_margin_check_requires_station_level_coverage() -> None:
    check = build_rib_bracing_margin_check(
        _spacing_requirements(),
        _bracing_audit(),
        rib_allowables=(
            {
                "bay_index": "0",
                "rib_family": "balsa_sheet_3mm",
                "allowable_link_force_n": "1200",
                "allowable_shear_force_n": "1000",
                "allowable_cap_force_n": "1050",
                "allowable_bond_force_n": "950",
                "allowable_main_spar_attach_force_n": "1100",
                "allowable_rear_spar_attach_force_n": "1150",
                "rib_lateral_stiffness_n_per_m": "25000",
                "allowable_basis": "rib_link_coupon_limit_load",
                "stiffness_basis": "finite_rib_beam_model",
                "evidence_type": "coupon_test",
                "attachment_basis": "bonded_spar_cap_shear_test",
                "source": RIB_TRACEABLE_SOURCE,
            },
        ),
    )

    by_bay = {row.bay_index: row for row in check.rows}
    assert check.overall_status == "rib_bracing_margins_not_closed"
    assert check.station_coverage_gap_count == 1
    assert by_bay[0].status == "rib_station_coverage_missing"
    assert by_bay[0].station_coverage_status == "station_coverage_count_missing"


def test_rib_bracing_margin_check_requires_physical_station_placement() -> None:
    check = build_rib_bracing_margin_check(
        _spacing_requirements(),
        _bracing_audit(),
        rib_allowables=(
            {
                "bay_index": "0",
                "rib_family": "balsa_sheet_3mm",
                "allowable_link_force_n": "1200",
                "allowable_shear_force_n": "1000",
                "allowable_cap_force_n": "1050",
                "allowable_bond_force_n": "950",
                "allowable_main_spar_attach_force_n": "1100",
                "allowable_rear_spar_attach_force_n": "1150",
                "rib_lateral_stiffness_n_per_m": "25000",
                "allowable_basis": "rib_link_coupon_limit_load",
                "stiffness_basis": "finite_rib_beam_model",
                "evidence_type": "coupon_test",
                "attachment_basis": "bonded_spar_cap_shear_test",
                "covered_intermediate_station_count": "1",
                "covered_station_ids": "bay0-rib1",
                "covered_intermediate_station_y_m": "0.10",
                "source": RIB_TRACEABLE_SOURCE,
            },
        ),
    )

    by_bay = {row.bay_index: row for row in check.rows}
    assert check.overall_status == "rib_bracing_margins_not_closed"
    assert check.station_coverage_gap_count == 1
    assert by_bay[0].status == "rib_station_coverage_missing"
    assert by_bay[0].station_coverage_status == "station_max_gap_exceeds_recommended"
    assert by_bay[0].max_unsupported_subbay_m == pytest.approx(0.5)


def test_write_rib_bracing_margin_input_package_creates_template_and_report(tmp_path: Path) -> None:
    outputs = write_rib_bracing_margin_input_package(
        tmp_path,
        _spacing_requirements(),
        _bracing_audit(),
        rib_allowables=(
            {
                "bay_index": "0",
                "rib_family": "balsa_sheet_3mm",
                "allowable_link_force_n": "1200",
                "allowable_shear_force_n": "1000",
                "allowable_cap_force_n": "1050",
                "allowable_bond_force_n": "950",
                "allowable_main_spar_attach_force_n": "1100",
                "allowable_rear_spar_attach_force_n": "1150",
                "rib_lateral_stiffness_n_per_m": "25000",
                "allowable_basis": "rib_link_coupon_limit_load",
                "stiffness_basis": "finite_rib_beam_model",
                "evidence_type": "coupon_test",
                "attachment_basis": "bonded_spar_cap_shear_test",
                "covered_intermediate_station_count": "1",
                "covered_station_ids": "bay0-rib1",
                "covered_intermediate_station_y_m": "0.30",
                "source": RIB_TRACEABLE_SOURCE,
            },
        ),
    )

    assert {path.name for path in outputs} == {
        "rib_bracing_margin_check.csv",
        "rib_bracing_margin_check.json",
        "rib_bracing_margin_check.md",
        "rib_bracing_margin_inputs_template.csv",
    }
    template = (tmp_path / "rib_bracing_margin_inputs_template.csv").read_text(encoding="utf-8")
    assert "required_link_force_n" in template
    assert "allowable_bond_force_n" in template
    assert "allowable_cap_force_n" in template
    assert "allowable_main_spar_attach_force_n" in template
    assert "allowable_rear_spar_attach_force_n" in template
    assert "rib_lateral_stiffness_n_per_m" in template
    assert "allowable_basis" in template
    assert "stiffness_basis" in template
    assert "attachment_basis" in template
    assert "covered_intermediate_station_count" in template
    assert "covered_intermediate_station_y_m" in template
    assert "max_unsupported_subbay_m" in template
    report = (tmp_path / "rib_bracing_margin_check.md").read_text(encoding="utf-8")
    assert "rib bracing input margins" in report
    assert "not finite-rib FEM signoff" in report
    assert "traceability-gap bays" in report
    assert "station-coverage-gap bays" in report
    assert "traceability" in report
    assert "rib_link_coupon_limit_load" in report
    assert "bay0-rib1" in report
    assert "0.30" in report
