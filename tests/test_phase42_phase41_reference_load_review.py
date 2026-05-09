from __future__ import annotations

import json
from pathlib import Path

from scripts.phase41_braced_subassembly_fem_evidence import (
    BracedSubassemblyFemEvidence,
    BracedSubassemblyFemEvidenceRow,
)
from scripts.phase42_phase41_reference_load_review import (
    build_phase41_reference_load_review,
    write_phase41_reference_load_review_package,
)


def _write_case_files(tmp_path: Path) -> tuple[Path, Path]:
    deck_path = tmp_path / "braced_subassembly_1p50g_buckle.inp"
    deck_path.write_text(
        "\n".join(
            [
                "*STEP, NAME=reference_static",
                "*STATIC",
                "*CLOAD",
                "10, 3, 10.0",
                "10, 5, -4.0",
                "*END STEP",
                "*STEP, NAME=buckle",
                "*BUCKLE",
                "5",
                "*END STEP",
                "",
            ]
        ),
        encoding="utf-8",
    )
    dat_path = tmp_path / "braced_subassembly_1p50g_buckle.dat"
    dat_path.write_text(
        "\n".join(
            [
                " total force (fx,fy,fz) for set HPA_SUPPORT_ALL and time  0.1000000E+01",
                "  0.0000000E+00  0.0000000E+00 -9.8000000E+00",
                "",
                "     B U C K L I N G   F A C T O R   O U T P U T",
                "",
                " MODE NO       BUCKLING",
                "                FACTOR",
                "",
                "      1   0.2700000E+07",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return deck_path, dat_path


def _phase41_evidence(
    tmp_path: Path,
    *,
    first_eigen_multiplier: float = 2.7e6,
) -> BracedSubassemblyFemEvidence:
    deck_path, dat_path = _write_case_files(tmp_path)
    return BracedSubassemblyFemEvidence(
        candidate_id="sample",
        overall_status="braced_subassembly_reference_load_review_required",
        case_count=1,
        solver_ran_count=1,
        mode_reviewed_count=0,
        claim_load_factor_coverage="1.50",
        engineering_boundary="not a full-wing pass claim",
        rows=(
            BracedSubassemblyFemEvidenceRow(
                case_id="braced_subassembly_1p50g_buckle",
                model_scope="braced_subassembly_eigen",
                status="solver_ran_reference_load_review_required",
                claim_load_factor=1.5,
                deck_path=str(deck_path),
                dat_path=str(dat_path),
                frd_path="",
                log_path="",
                ccx_path="/opt/homebrew/bin/ccx_2.23",
                returncode=0,
                first_eigen_multiplier=first_eigen_multiplier,
                inferred_first_buckling_load_factor=1.5 * first_eigen_multiplier,
                eigenvalue_count=1,
                reference_load_status="unphysical_or_load_sign_review_required",
                joint_link_mode="offset_rigid",
                link_node_count=1,
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
                phase30_closure_status="mode_review_missing",
                engineering_note="huge lambda",
                next_action="review",
            ),
        ),
    )


def test_phase42_classifies_balanced_transverse_reference_as_not_rankable(
    tmp_path: Path,
) -> None:
    review = build_phase41_reference_load_review(_phase41_evidence(tmp_path))

    assert review.overall_status == "phase41_reference_load_formulation_not_rankable"
    assert review.row_count == 1
    row = review.rows[0]
    assert row.case_id == "braced_subassembly_1p50g_buckle"
    assert row.status == "reference_load_formulation_not_rankable"
    assert row.applied_fz_n == 10.0
    assert row.support_reaction_fz_n == -9.8
    assert row.fz_balance_error_pct == 2.0
    assert row.fz_balance_status == "balanced"
    assert row.axial_reference_load_status == "no_axial_compression_reference"
    assert row.lambda_plausibility_status == "implausibly_high_for_claim_margin"
    assert row.sign_convention_read == "support_reaction_opposes_applied_fz"
    assert "transverse lift/moment reference" in row.engineering_read


def test_phase42_separates_no_axial_reference_from_mode_shape_review(
    tmp_path: Path,
) -> None:
    review = build_phase41_reference_load_review(
        _phase41_evidence(tmp_path, first_eigen_multiplier=2.8)
    )

    assert (
        review.overall_status
        == "phase41_reference_load_compression_path_review_required"
    )
    assert review.not_rankable_count == 0
    assert review.compression_path_review_count == 1
    row = review.rows[0]
    assert row.status == "reference_load_compression_path_review_required"
    assert row.lambda_plausibility_status == "screening_range"
    assert row.axial_reference_load_status == "no_axial_compression_reference"
    assert "compressive reference path" in row.engineering_read


def test_phase42_writes_handoff_files(tmp_path: Path) -> None:
    outputs = write_phase41_reference_load_review_package(
        tmp_path / "out",
        _phase41_evidence(tmp_path),
    )

    assert {path.name for path in outputs} == {
        "phase41_reference_load_review.csv",
        "phase41_reference_load_review.json",
        "phase41_reference_load_review.md",
    }
    payload = json.loads(
        (tmp_path / "out" / "phase41_reference_load_review.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["overall_status"] == "phase41_reference_load_formulation_not_rankable"
    report = (tmp_path / "out" / "phase41_reference_load_review.md").read_text(
        encoding="utf-8"
    )
    assert "not usable buckling margin" in report
