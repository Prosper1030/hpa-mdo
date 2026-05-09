from __future__ import annotations

import json
from pathlib import Path

from scripts.phase41_braced_subassembly_fem_evidence import (
    BracedSubassemblyFemEvidence,
    BracedSubassemblyFemEvidenceRow,
)
from scripts.phase44_phase41_mode_shape_review import (
    build_phase41_mode_shape_review,
    write_phase41_mode_shape_review_package,
)


def _write_mode_frd(path: Path) -> None:
    path.write_text(
        """
    1C
    2C                             4                                     1
 -1         1  3.00000E-01  0.00000E+00  0.00000E+00
 -1         2  3.00000E-01  1.00000E+01  0.00000E+00
 -1         3  1.00000E-01  0.00000E+00  0.00000E+00
 -1         4  1.00000E-01  1.00000E+01  0.00000E+00
 -3
    1PSTEP                         1           1           1
  100CL  101 0.00000E+00           4                     4    1           1
 -4  DISP        4    1
 -5  D1          1    2    1    0
 -5  D2          1    2    2    0
 -5  D3          1    2    3    0
 -1         1  1.00000E-01  0.00000E+00  0.00000E+00
 -1         2  2.00000E-01  0.00000E+00  0.00000E+00
 -1         3  1.00000E-01  0.00000E+00  0.00000E+00
 -1         4  2.00000E-01  0.00000E+00  0.00000E+00
 -3
    1PSTEP                         2           1           1
  100CL  102 2.50000E+00           4                     4    2           1
 -4  DISP        4    1
 -5  D1          1    2    1    0
 -5  D2          1    2    2    0
 -5  D3          1    2    3    0
 -1         1  0.00000E+00  1.00000E-03  0.00000E+00
 -1         2  0.00000E+00  4.00000E-03  0.00000E+00
 -1         3  0.00000E+00  1.50000E-03  0.00000E+00
 -1         4  0.00000E+00  3.00000E-03  0.00000E+00
 -3
""",
        encoding="utf-8",
    )


def _phase41_evidence(tmp_path: Path, *, frd_path: str) -> BracedSubassemblyFemEvidence:
    return BracedSubassemblyFemEvidence(
        candidate_id="sample",
        overall_status="braced_subassembly_solver_ran_mode_review_required",
        case_count=1,
        solver_ran_count=1,
        mode_reviewed_count=0,
        claim_load_factor_coverage="1.50",
        engineering_boundary="route evidence only",
        rows=(
            BracedSubassemblyFemEvidenceRow(
                case_id="braced_subassembly_1p50g_buckle",
                model_scope="braced_subassembly_eigen",
                status="solver_ran_mode_review_required",
                claim_load_factor=1.5,
                deck_path=str(tmp_path / "case.inp"),
                dat_path=str(tmp_path / "case.dat"),
                frd_path=frd_path,
                log_path=str(tmp_path / "case.log"),
                ccx_path="/opt/homebrew/bin/ccx_2.23",
                returncode=0,
                first_eigen_multiplier=2.5,
                inferred_first_buckling_load_factor=3.75,
                eigenvalue_count=1,
                reference_load_status="screening_range",
                joint_link_mode="offset_rigid",
                link_node_count=2,
                wire_support_count=1,
                includes_main_spar=True,
                includes_rear_spar=True,
                includes_finite_ribs=True,
                includes_wire_attach_load_path=True,
                includes_root_boundary=True,
                missing_components="",
                boundary_condition_status="generated_unreviewed",
                mesh_convergence_status="single_mesh_not_converged",
                solver_status="pass",
                mode_review_status="unreviewed",
                phase30_closure_status="reference_load_review_missing",
                engineering_note="needs mode review",
                next_action="review first mode",
            ),
        ),
    )


def test_phase44_reviews_first_eigenmode_block_not_static_block(tmp_path: Path) -> None:
    frd = tmp_path / "case.frd"
    _write_mode_frd(frd)

    review = build_phase41_mode_shape_review(
        _phase41_evidence(tmp_path, frd_path=str(frd))
    )

    assert review.overall_status == "phase41_mode_shape_engineering_review_required"
    assert review.row_count == 1
    assert review.review_required_count == 1
    row = review.rows[0]
    assert row.status == "mode_shape_engineering_review_required"
    assert row.mode_block_count == 2
    assert row.selected_mode_step_number == 2
    assert row.selected_mode_result_set == 102
    assert row.selected_mode_analysis_value == 2.5
    assert row.node_count == 4
    assert row.max_mode_node_id == 2
    assert row.max_mode_y_m == 10.0
    assert row.tip_to_max_ratio == 1.0
    assert row.root_to_max_ratio == 0.375
    assert row.spar_mean_participation_ratio == 0.9
    assert "Automated mode screening only" in row.engineering_read


def test_phase44_missing_frd_stays_incomplete(tmp_path: Path) -> None:
    review = build_phase41_mode_shape_review(_phase41_evidence(tmp_path, frd_path=""))

    assert review.overall_status == "phase41_mode_shape_review_incomplete"
    assert review.missing_count == 1
    assert review.rows[0].status == "frd_missing"
    assert "Run Phase41 with CalculiX" in review.rows[0].next_action


def test_phase44_writes_handoff_files(tmp_path: Path) -> None:
    frd = tmp_path / "case.frd"
    _write_mode_frd(frd)

    outputs = write_phase41_mode_shape_review_package(
        tmp_path / "out",
        _phase41_evidence(tmp_path, frd_path=str(frd)),
    )

    assert {path.name for path in outputs} == {
        "phase41_mode_shape_review.csv",
        "phase41_mode_shape_review.json",
        "phase41_mode_shape_review.md",
    }
    payload = json.loads(
        (tmp_path / "out" / "phase41_mode_shape_review.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["overall_status"] == "phase41_mode_shape_engineering_review_required"
    report = (tmp_path / "out" / "phase41_mode_shape_review.md").read_text(
        encoding="utf-8"
    )
    assert "not a full-wing pass claim" in report
