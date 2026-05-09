from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.phase38_full_wing_buckling_claim_boundary import (
    build_full_wing_buckling_claim_boundary,
    write_full_wing_buckling_claim_boundary_package,
)


def _row(load_factor: float, local_wall_util: float, stress_util: float) -> SimpleNamespace:
    return SimpleNamespace(
        load_factor=load_factor,
        fem_basis="repaired_candidate_equivalent_fem_checked",
        local_wall_buckling_utilization=local_wall_util,
        tube_stress_utilization=stress_util,
        wire_utilization=0.50,
        first_failure_mode="none_with_margin",
    )


def _closure_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="full_wing_global_buckling_not_closed",
        missing_required_claim_load_factors="1.50;1.75",
        rows=(
            SimpleNamespace(
                status="closure_input_missing",
                missing_components="main_spar;rear_spar;finite_ribs;wire_attach_load_path;root_boundary",
            ),
        ),
    )


def _partial_claim_closure_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="full_wing_global_buckling_not_closed",
        missing_required_claim_load_factors="1.75",
        rows=(
            SimpleNamespace(
                status="margin_positive_input_check_only",
                missing_components="",
            ),
        ),
    )


def _mixed_component_closure_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="full_wing_global_buckling_not_closed",
        missing_required_claim_load_factors="1.75",
        rows=(
            SimpleNamespace(
                status="margin_positive_input_check_only",
                claim_load_factor=1.50,
                missing_components="",
            ),
            SimpleNamespace(
                status="required_structural_components_missing",
                claim_load_factor=1.75,
                missing_components="finite_ribs",
            ),
        ),
    )


def test_full_wing_buckling_claim_boundary_separates_internal_pass_from_global_claim() -> None:
    boundary = build_full_wing_buckling_claim_boundary(
        "sample",
        phase15_rows=(
            _row(1.5, 0.121, 0.269),
            _row(1.75, 0.141, 0.313),
        ),
        closure_check=_closure_check(),
    )

    assert boundary.overall_status == "full_wing_pass_claim_blocked_global_buckling_missing"
    assert boundary.global_buckling_closure_status == "full_wing_global_buckling_not_closed"
    assert boundary.missing_required_claim_load_factors == "1.50;1.75"
    assert boundary.required_claim_load_factors == (1.5, 1.75)
    by_load = {row.claim_load_factor: row for row in boundary.rows}
    assert by_load[1.5].status == "internal_local_pass_global_claim_blocked"
    assert by_load[1.75].local_wall_buckling_utilization == pytest.approx(0.141)
    assert "1.75G internal fixed-design modeled limits clear" in by_load[1.75].allowed_statement
    assert "Do not claim 1.75G full-wing pass" in by_load[1.75].blocked_statement
    assert "global buckling eigen/FEM" in by_load[1.75].required_evidence


def test_full_wing_buckling_claim_boundary_uses_whole_closure_check_not_first_row() -> None:
    boundary = build_full_wing_buckling_claim_boundary(
        "sample",
        phase15_rows=(
            _row(1.5, 0.121, 0.269),
            _row(1.75, 0.141, 0.313),
        ),
        closure_check=_partial_claim_closure_check(),
    )

    assert boundary.overall_status == "full_wing_pass_claim_blocked_global_buckling_missing"
    assert boundary.global_buckling_closure_status == "full_wing_global_buckling_not_closed"
    assert boundary.missing_required_claim_load_factors == "1.75"
    assert {row.status for row in boundary.rows} == {
        "internal_local_pass_global_claim_blocked"
    }


def test_full_wing_buckling_claim_boundary_reports_missing_components_across_rows() -> None:
    boundary = build_full_wing_buckling_claim_boundary(
        "sample",
        phase15_rows=(
            _row(1.5, 0.121, 0.269),
            _row(1.75, 0.141, 0.313),
        ),
        closure_check=_mixed_component_closure_check(),
    )

    assert {row.missing_global_components for row in boundary.rows} == {"finite_ribs"}


def test_write_full_wing_buckling_claim_boundary_package_creates_handoff_files(
    tmp_path: Path,
) -> None:
    outputs = write_full_wing_buckling_claim_boundary_package(
        tmp_path,
        "sample",
        phase15_rows=(
            _row(1.5, 0.121, 0.269),
            _row(1.75, 0.141, 0.313),
        ),
        closure_check=_closure_check(),
    )

    assert {path.name for path in outputs} == {
        "full_wing_buckling_claim_boundary.csv",
        "full_wing_buckling_claim_boundary.json",
        "full_wing_buckling_claim_boundary.md",
    }
    report = (tmp_path / "full_wing_buckling_claim_boundary.md").read_text(encoding="utf-8")
    assert "full_wing_pass_claim_blocked_global_buckling_missing" in report
    assert "1.75G internal fixed-design modeled limits clear" in report
    assert "Do not claim 1.75G full-wing pass" in report
