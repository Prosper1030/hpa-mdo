from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from scripts.phase41_braced_subassembly_fem_evidence import (
    write_braced_subassembly_fem_evidence_package,
)
from tests.test_dual_beam_mainline import _simple_model


def test_phase41_generates_buckle_decks_and_report_only_evidence(tmp_path: Path) -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, -12.0, -6.0]),
        torque_per_span_nmpm=np.array([0.0, 1.5, 0.75]),
        joint_node_indices=(1,),
        wire_node_indices=(1,),
    )

    outputs = write_braced_subassembly_fem_evidence_package(
        tmp_path,
        "sample",
        model,
        claim_load_factors=(1.50, 1.75),
        run_solver=False,
    )

    assert {path.name for path in outputs} == {
        "braced_subassembly_1p50g_buckle.inp",
        "braced_subassembly_1p75g_buckle.inp",
        "braced_subassembly_fem_evidence.csv",
        "braced_subassembly_fem_evidence.json",
        "braced_subassembly_fem_evidence.md",
        "phase30_closure_inputs_from_phase41.csv",
    }
    deck_text = (tmp_path / "braced_subassembly_1p50g_buckle.inp").read_text(
        encoding="utf-8"
    )
    assert "joint_link_mode=offset_rigid" in deck_text
    assert "*STEP, NAME=buckle\n*BUCKLE" in deck_text
    assert "*NODE PRINT, NSET=HPA_SUPPORT_ROOT, TOTALS=ONLY" in deck_text
    assert "*NODE PRINT, NSET=HPA_SUPPORT_WIRE, TOTALS=ONLY" in deck_text

    payload = json.loads(
        (tmp_path / "braced_subassembly_fem_evidence.json").read_text(encoding="utf-8")
    )
    assert payload["overall_status"] == "braced_subassembly_route_generated_not_signoff"
    assert payload["case_count"] == 2
    assert payload["solver_ran_count"] == 0
    assert payload["mode_reviewed_count"] == 0
    assert payload["claim_load_factor_coverage"] == "1.50;1.75"
    assert "not a full-wing pass claim" in payload["engineering_boundary"]

    first = payload["rows"][0]
    assert first["case_id"] == "braced_subassembly_1p50g_buckle"
    assert first["model_scope"] == "braced_subassembly_eigen"
    assert first["status"] == "deck_generated_solver_not_run"
    assert first["includes_main_spar"] is True
    assert first["includes_rear_spar"] is True
    assert first["includes_finite_ribs"] is True
    assert first["includes_wire_attach_load_path"] is True
    assert first["includes_root_boundary"] is True
    assert first["missing_components"] == ""
    assert first["boundary_condition_status"] == "generated_unreviewed"
    assert first["mesh_convergence_status"] == "single_mesh_not_converged"
    assert first["solver_status"] == "not_run"
    assert first["mode_review_status"] == "unreviewed"
    assert first["phase30_closure_status"] == "closure_input_incomplete"

    closure_csv = (tmp_path / "phase30_closure_inputs_from_phase41.csv").read_text(
        encoding="utf-8"
    )
    assert "braced_subassembly_eigen" in closure_csv
    assert "generated_unreviewed" in closure_csv


def test_phase41_solver_result_keeps_mode_review_as_blocker(tmp_path: Path) -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, -12.0, -6.0]),
        joint_node_indices=(1,),
        wire_node_indices=(1,),
    )

    outputs = write_braced_subassembly_fem_evidence_package(
        tmp_path,
        "sample",
        model,
        claim_load_factors=(1.50,),
        run_solver=False,
        solver_results={
            "braced_subassembly_1p50g_buckle": {
                "status": "PASS_WITHOUT_REFERENCE",
                "returncode": 0,
                "lambda_1": 2.0,
                "eigenvalues": (2.0, 3.0),
                "dat_path": str(tmp_path / "fake.dat"),
                "frd_path": str(tmp_path / "fake.frd"),
                "log_path": str(tmp_path / "fake.log"),
                "ccx_path": "/opt/homebrew/bin/ccx_2.23",
            }
        },
    )

    assert (tmp_path / "braced_subassembly_fem_evidence.json") in outputs
    payload = json.loads(
        (tmp_path / "braced_subassembly_fem_evidence.json").read_text(encoding="utf-8")
    )
    row = payload["rows"][0]

    assert payload["solver_ran_count"] == 1
    assert row["status"] == "solver_ran_mode_review_required"
    assert row["solver_status"] == "pass"
    assert row["first_eigen_multiplier"] == 2.0
    assert row["inferred_first_buckling_load_factor"] == 3.0
    assert row["mode_review_status"] == "unreviewed"
    assert row["phase30_closure_status"] == "mode_review_missing"


def test_phase41_flags_huge_eigen_multiplier_as_reference_load_review(
    tmp_path: Path,
) -> None:
    model = _simple_model(
        lift_per_span_npm=np.array([0.0, -12.0, -6.0]),
        joint_node_indices=(1,),
        wire_node_indices=(1,),
    )

    write_braced_subassembly_fem_evidence_package(
        tmp_path,
        "sample",
        model,
        claim_load_factors=(1.50,),
        run_solver=False,
        solver_results={
            "braced_subassembly_1p50g_buckle": {
                "status": "PASS_WITHOUT_REFERENCE",
                "returncode": 0,
                "lambda_1": 2.7e6,
                "eigenvalues": (2.7e6,),
                "dat_path": str(tmp_path / "huge.dat"),
                "frd_path": str(tmp_path / "huge.frd"),
                "log_path": str(tmp_path / "huge.log"),
                "ccx_path": "/opt/homebrew/bin/ccx_2.23",
            }
        },
    )

    payload = json.loads(
        (tmp_path / "braced_subassembly_fem_evidence.json").read_text(encoding="utf-8")
    )
    row = payload["rows"][0]

    assert payload["overall_status"] == (
        "braced_subassembly_reference_load_review_required"
    )
    assert row["status"] == "solver_ran_reference_load_review_required"
    assert row["reference_load_status"] == "unphysical_or_load_sign_review_required"
    assert "reference load/sign convention" in row["engineering_note"]
