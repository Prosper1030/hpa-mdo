from __future__ import annotations

from pathlib import Path

import pytest

from scripts.phase30_full_wing_buckling_closure_inputs import (
    build_full_wing_buckling_closure_check,
    write_full_wing_buckling_closure_input_package,
)


def test_full_wing_buckling_closure_accepts_global_or_braced_eigen_inputs_only() -> None:
    check = build_full_wing_buckling_closure_check(
        "sample",
        closure_inputs=(
            {
                "case_id": "full-wing-1p75",
                "model_scope": "full_wing_global_eigen",
                "claim_load_factor": "1.75",
                "first_global_buckling_load_factor": "2.10",
                "reference_load_status": "pass",
                "includes_main_spar": "true",
                "includes_rear_spar": "true",
                "includes_finite_ribs": "true",
                "includes_wire_attach_load_path": "true",
                "includes_root_boundary": "true",
                "boundary_condition_status": "pass",
                "mesh_convergence_status": "pass",
                "solver_status": "pass",
                "mode_review_status": "pass",
                "source": "qualified FEM placeholder",
            },
            {
                "case_id": "coupon-only",
                "model_scope": "local_shell_coupon",
                "claim_load_factor": "1.75",
                "first_global_buckling_load_factor": "3.00",
                "reference_load_status": "pass",
                "includes_main_spar": "true",
                "includes_rear_spar": "false",
                "includes_finite_ribs": "false",
                "includes_wire_attach_load_path": "false",
                "includes_root_boundary": "false",
                "boundary_condition_status": "pass",
                "mesh_convergence_status": "pass",
                "solver_status": "pass",
                "mode_review_status": "pass",
                "source": "local coupon",
            },
        ),
    )

    assert check.overall_status == "full_wing_global_buckling_not_closed"
    by_case = {row.case_id: row for row in check.rows}
    assert by_case["full-wing-1p75"].status == "margin_positive_input_check_only"
    assert by_case["full-wing-1p75"].load_factor_margin == pytest.approx(0.35)
    assert by_case["coupon-only"].status == "invalid_buckling_model_scope"
    assert "local shell coupon" in by_case["coupon-only"].engineering_note


def test_full_wing_buckling_closure_rejects_missing_braced_structure_components() -> None:
    check = build_full_wing_buckling_closure_check(
        "sample",
        closure_inputs=(
            {
                "case_id": "rear-spar-missing",
                "model_scope": "braced_subassembly_eigen",
                "claim_load_factor": "1.50",
                "first_global_buckling_load_factor": "2.00",
                "reference_load_status": "pass",
                "includes_main_spar": "true",
                "includes_rear_spar": "false",
                "includes_finite_ribs": "true",
                "includes_wire_attach_load_path": "true",
                "includes_root_boundary": "true",
                "boundary_condition_status": "pass",
                "mesh_convergence_status": "pass",
                "solver_status": "pass",
                "mode_review_status": "pass",
                "source": "subassembly placeholder",
            },
        ),
    )

    assert check.overall_status == "full_wing_global_buckling_not_closed"
    row = check.rows[0]
    assert row.status == "required_structural_components_missing"
    assert row.missing_components == "rear_spar"


def test_full_wing_buckling_closure_requires_both_claim_load_factors() -> None:
    check = build_full_wing_buckling_closure_check(
        "sample",
        closure_inputs=(
            {
                "case_id": "full-wing-1p75",
                "model_scope": "full_wing_global_eigen",
                "claim_load_factor": "1.75",
                "first_global_buckling_load_factor": "2.10",
                "reference_load_status": "pass",
                "includes_main_spar": "true",
                "includes_rear_spar": "true",
                "includes_finite_ribs": "true",
                "includes_wire_attach_load_path": "true",
                "includes_root_boundary": "true",
                "boundary_condition_status": "pass",
                "mesh_convergence_status": "pass",
                "solver_status": "pass",
                "mode_review_status": "pass",
                "source": "qualified FEM placeholder",
            },
        ),
    )

    assert check.overall_status == "full_wing_global_buckling_not_closed"
    assert check.required_claim_load_factors == pytest.approx((1.50, 1.75))
    assert check.missing_required_claim_load_factors == "1.50"


def test_full_wing_buckling_closure_can_pass_input_margins_when_both_claims_are_covered() -> None:
    base = {
        "model_scope": "full_wing_global_eigen",
        "first_global_buckling_load_factor": "2.10",
        "reference_load_status": "pass",
        "includes_main_spar": "true",
        "includes_rear_spar": "true",
        "includes_finite_ribs": "true",
        "includes_wire_attach_load_path": "true",
        "includes_root_boundary": "true",
        "boundary_condition_status": "pass",
        "mesh_convergence_status": "pass",
        "solver_status": "pass",
        "mode_review_status": "pass",
        "source": "qualified FEM placeholder",
    }
    check = build_full_wing_buckling_closure_check(
        "sample",
        closure_inputs=(
            {**base, "case_id": "full-wing-1p50", "claim_load_factor": "1.50"},
            {**base, "case_id": "full-wing-1p75", "claim_load_factor": "1.75"},
        ),
    )

    assert check.overall_status == "buckling_input_margins_pass_not_full_aircraft_signoff"
    assert check.missing_required_claim_load_factors == ""


def test_full_wing_buckling_closure_requires_source_and_mode_review() -> None:
    base = {
        "case_id": "unreviewed-global",
        "model_scope": "full_wing_global_eigen",
        "claim_load_factor": "1.75",
        "first_global_buckling_load_factor": "2.10",
        "reference_load_status": "pass",
        "includes_main_spar": "true",
        "includes_rear_spar": "true",
        "includes_finite_ribs": "true",
        "includes_wire_attach_load_path": "true",
        "includes_root_boundary": "true",
        "boundary_condition_status": "pass",
        "mesh_convergence_status": "pass",
        "solver_status": "pass",
    }
    check = build_full_wing_buckling_closure_check(
        "sample",
        closure_inputs=(
            {
                **base,
                "source": "",
                "mode_review_status": "pass",
            },
            {
                **base,
                "case_id": "mode-unreviewed-global",
                "source": "qualified FEM placeholder",
                "mode_review_status": "",
            },
        ),
    )

    by_case = {row.case_id: row for row in check.rows}
    assert check.overall_status == "full_wing_global_buckling_not_closed"
    assert by_case["unreviewed-global"].status == "source_missing"
    assert by_case["mode-unreviewed-global"].status == "mode_review_missing"


def test_full_wing_buckling_closure_requires_qualified_reference_load_review() -> None:
    base = {
        "case_id": "reference-load-unreviewed",
        "model_scope": "full_wing_global_eigen",
        "claim_load_factor": "1.75",
        "first_global_buckling_load_factor": "2.10",
        "includes_main_spar": "true",
        "includes_rear_spar": "true",
        "includes_finite_ribs": "true",
        "includes_wire_attach_load_path": "true",
        "includes_root_boundary": "true",
        "boundary_condition_status": "pass",
        "mesh_convergence_status": "pass",
        "solver_status": "pass",
        "mode_review_status": "pass",
        "source": "qualified FEM placeholder",
    }
    check = build_full_wing_buckling_closure_check(
        "sample",
        closure_inputs=(
            base,
            {
                **base,
                "case_id": "reference-load-screening",
                "reference_load_status": "screening_range",
            },
        ),
    )

    by_case = {row.case_id: row for row in check.rows}
    assert by_case["reference-load-unreviewed"].status == (
        "reference_load_review_missing"
    )
    assert by_case["reference-load-screening"].status == (
        "reference_load_review_missing"
    )
    assert "qualified reference-load review" in by_case[
        "reference-load-screening"
    ].engineering_note


def test_full_wing_buckling_closure_rejects_unusable_reference_load_factor() -> None:
    check = build_full_wing_buckling_closure_check(
        "sample",
        closure_inputs=(
            {
                "case_id": "phase41-huge-lambda",
                "model_scope": "braced_subassembly_eigen",
                "claim_load_factor": "1.50",
                "first_global_buckling_load_factor": "4088644.50",
                "reference_load_status": "unphysical_or_load_sign_review_required",
                "includes_main_spar": "true",
                "includes_rear_spar": "true",
                "includes_finite_ribs": "true",
                "includes_wire_attach_load_path": "true",
                "includes_root_boundary": "true",
                "boundary_condition_status": "generated_unreviewed",
                "mesh_convergence_status": "single_mesh_not_converged",
                "solver_status": "pass",
                "mode_review_status": "unreviewed",
                "source": "phase41 deck",
            },
        ),
    )

    row = check.rows[0]
    assert row.status == "reference_load_formulation_not_rankable"
    assert row.reference_load_status == "unphysical_or_load_sign_review_required"
    assert row.first_global_buckling_load_factor is None
    assert row.load_factor_margin is None
    assert "reference load formulation" in row.engineering_note


def test_full_wing_buckling_closure_marks_missing_inputs() -> None:
    check = build_full_wing_buckling_closure_check("sample", closure_inputs=())

    assert check.overall_status == "full_wing_global_buckling_not_closed"
    assert len(check.rows) == 1
    assert check.rows[0].status == "closure_input_missing"
    assert check.rows[0].case_id == "full_wing_global_buckling_input_required"


def test_write_full_wing_buckling_closure_input_package_creates_template_and_report(
    tmp_path: Path,
) -> None:
    outputs = write_full_wing_buckling_closure_input_package(
        tmp_path,
        "sample",
        closure_inputs=(),
    )

    assert {path.name for path in outputs} == {
        "full_wing_buckling_closure_check.csv",
        "full_wing_buckling_closure_check.json",
        "full_wing_buckling_closure_check.md",
        "full_wing_buckling_closure_inputs_template.csv",
    }
    template = (tmp_path / "full_wing_buckling_closure_inputs_template.csv").read_text(
        encoding="utf-8"
    )
    assert "full_wing_global_eigen" in template
    assert "braced_subassembly_eigen" in template
    assert "1.50" in template
    report = (tmp_path / "full_wing_buckling_closure_check.md").read_text(encoding="utf-8")
    assert "full-wing global buckling closure inputs" in report
    assert "not a full aircraft signoff" in report
    assert "required claim load factors" in report
