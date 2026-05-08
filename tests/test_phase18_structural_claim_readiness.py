from __future__ import annotations

import json
from pathlib import Path

from scripts.phase15_candidate_load_factor_buckling_check import CandidateReference
from scripts.phase18_structural_claim_readiness import (
    REQUIRED_STRUCTURAL_CLAIM_KEYS,
    build_structural_claim_readiness,
    write_structural_claim_readiness_package,
)


def _reference() -> CandidateReference:
    return CandidateReference(
        candidate_id="sample",
        reference_load_factor=2.0,
        failure_index=0.25 - 1.0,
        buckling_index=0.10 - 1.0,
        tip_deflection_m=1.0,
        tip_deflection_limit_m=1.65,
        twist_max_deg=0.2,
        twist_limit_deg=2.0,
        wire_tension_n=3000.0,
        wire_allowable_n=6000.0,
        root_reaction_fz_n=-10.0,
        root_bending_moment_n_m=1000.0,
        tube_allowable_stress_pa=1.0e9,
        young_pa=200.0e9,
        jig_main_tip_z_m=0.6,
        jig_rear_tip_z_m=0.4,
        loaded_main_tip_z_m=2.7,
        loaded_rear_tip_z_m=2.5,
        jig_min_z_m=0.04,
        loaded_min_z_m=0.08,
        fem_validated_max_load_factor=2.0,
        fem_tip_error_pct=3.74,
        fem_wire_reaction_error_pct=2.09,
        fem_root_reaction_error_pct=4.60,
        structured_shell_b2_error_pct=2.41,
        structured_shell_b5_torsion_error_pct=0.07,
    )


def test_readiness_matrix_covers_all_structural_claim_blockers() -> None:
    review = build_structural_claim_readiness(_reference())

    assert [item.key for item in review.items] == list(REQUIRED_STRUCTURAL_CLAIM_KEYS)
    assert len(review.items) == 10
    assert review.overall_verdict == "not_ready_for_full_wing_or_hardware_signoff"


def test_readiness_matrix_blocks_full_wing_claims_even_when_internal_margins_pass() -> None:
    review = build_structural_claim_readiness(_reference())

    blocked = {item.key: item for item in review.items}
    assert blocked["rear_spar_stiffness"].status == "unresolved_blocker"
    assert blocked["rib_load_transfer"].status == "unresolved_blocker"
    assert blocked["wire_termination"].status == "unresolved_blocker"
    assert blocked["tip_deflection_limit"].status == "bounded_design_gate"
    assert blocked["torsion_twist_coupling"].status == "bounded_internal_check"
    assert blocked["full_wing_global_buckling"].status == "unresolved_blocker"
    assert "full-wing pass" in blocked["full_wing_global_buckling"].blocked_claim
    assert "design-validity gate" in blocked["tip_deflection_limit"].allowed_claim


def test_write_structural_claim_readiness_package_creates_machine_and_markdown_outputs(
    tmp_path: Path,
) -> None:
    outputs = write_structural_claim_readiness_package(tmp_path, _reference())

    assert {path.name for path in outputs} == {
        "structural_claim_readiness.csv",
        "structural_claim_readiness.json",
        "structural_claim_readiness.md",
    }
    payload = json.loads((tmp_path / "structural_claim_readiness.json").read_text(encoding="utf-8"))
    assert payload["overall_verdict"] == "not_ready_for_full_wing_or_hardware_signoff"
    assert payload["summary_counts"]["unresolved_blocker"] >= 7
    report = (tmp_path / "structural_claim_readiness.md").read_text(encoding="utf-8")
    assert "Do not claim `1.5G / 1.75G full-wing pass`" in report
    assert "wire body allowable is not termination allowable" in report
