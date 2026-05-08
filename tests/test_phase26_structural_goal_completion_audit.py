from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.phase18_structural_claim_readiness import REQUIRED_STRUCTURAL_CLAIM_KEYS
from scripts.phase26_structural_goal_completion_audit import (
    build_structural_goal_completion_audit,
    write_structural_goal_completion_audit_package,
)


def _closure_index() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        overall_status="engineering_not_signed_off",
        items=(
            SimpleNamespace(
                key="rear_spar_stiffness",
                evidence_artifacts="Phase20; Phase22",
                current_evidence="rear EI quantified; rear_stiffness_5pct moved response",
                remaining_blocker="Dual-spar FEM",
                next_action="Run rear-spar-on/off FEM",
            ),
            SimpleNamespace(
                key="rib_load_transfer",
                evidence_artifacts="Phase19; Phase22; Phase24; Phase43",
                current_evidence="added stations=53; dense finite rib surrogate only; Phase43: existing detail allowable triage status=existing_detail_allowables_do_not_close_goal; row status=rib_catalog_proxy_not_margin",
                remaining_blocker="Finite rib stiffness and allowables",
                next_action="Create finite-rib load transfer model",
            ),
            SimpleNamespace(
                key="wire_attach_local_load_path",
                evidence_artifacts="Phase19; Phase23; Phase43",
                current_evidence="required load=6048 N; Phase43: existing detail allowable triage status=existing_detail_allowables_do_not_close_goal; row status=local_subcomponent_allowables_missing",
                remaining_blocker="Local attach margins",
                next_action="Size lug/ring/insert",
            ),
            SimpleNamespace(
                key="root_joint",
                evidence_artifacts="Phase19; Phase23; Phase43",
                current_evidence="required moment=10833 N*m; Phase43: existing detail allowable triage status=existing_detail_allowables_do_not_close_goal; row status=local_subcomponent_allowables_missing",
                remaining_blocker="Root fitting margins",
                next_action="Size root fitting",
            ),
            SimpleNamespace(
                key="torsion_twist_coupling",
                evidence_artifacts="Phase20; Phase22; Phase29; Phase37",
                current_evidence="not aero twist; screening status=torsion_twist_screening_not_aeroelastic_signoff",
                remaining_blocker="Aeroelastic loop",
                next_action="Close twist loop",
            ),
            SimpleNamespace(
                key="wire_termination",
                evidence_artifacts="Phase19; Phase23; Phase43",
                current_evidence="required MBL=10080 N; body margin=-1466 N; Phase43: existing detail allowable triage status=existing_detail_allowables_do_not_close_goal; row status=material_body_strength_not_termination_allowable",
                remaining_blocker="Selected termination hardware",
                next_action="Pick termination",
            ),
            SimpleNamespace(
                key="rib_spacing_assumption",
                evidence_artifacts="Phase20; Phase24; Phase43",
                current_evidence="added stations=53; Phase43: existing detail allowable triage status=existing_detail_allowables_do_not_close_goal; row status=rib_catalog_proxy_not_margin",
                remaining_blocker="Physical rib stiffness",
                next_action="Place and verify bracing ribs",
            ),
            SimpleNamespace(
                key="tip_deflection_limit",
                evidence_artifacts="Phase18; Phase31; Phase39",
                current_evidence="Tip-deflection design-validity load factor=3.305; this is not a fracture point. claim boundary status=tip_deflection_claim_boundary_submission_gate_retained",
                remaining_blocker="Aeroelastic clearance recheck for relaxation",
                next_action="Keep 2.5 m gate",
            ),
            SimpleNamespace(
                key="full_wing_global_buckling",
                evidence_artifacts="Phase18; Phase30; Phase38; Phase41; Phase42",
                current_evidence="No full-wing global buckling eigen/FEM result; claim boundary status=full_wing_pass_claim_blocked_global_buckling_missing; Phase41: braced subassembly status=braced_subassembly_reference_load_review_required; reference-load review rows=2; Phase30 status=mode_review_missing. Phase42: reference review status=phase41_reference_load_formulation_not_rankable; not-rankable rows=2; no axial compression reference rows=2.",
                remaining_blocker="Full-wing buckling FEM",
                next_action="Replace Phase41 transverse lift/moment reference",
            ),
            SimpleNamespace(
                key="failure_mode_ordering",
                evidence_artifacts="Phase18; Phase25",
                current_evidence="unranked modes=7",
                remaining_blocker="Add real-structure modes to ranking",
                next_action="Rank after FEM and hardware margins",
            ),
        ),
    )


def _failure_mode_ordering() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="true_failure_order_not_closed",
        known_unranked_mode_count=7,
        modeled_first_limiter_with_current_wire="wire_tension_body_allowable",
        modeled_first_limiter_with_6kn_wire="tip_deflection",
    )


def test_goal_completion_audit_maps_every_goal_item_and_refuses_completion() -> None:
    audit = build_structural_goal_completion_audit(
        _closure_index(),
        failure_mode_ordering=_failure_mode_ordering(),
    )

    assert audit.overall_goal_status == "not_complete_engineering_signoff_missing"
    assert audit.total_requirements == len(REQUIRED_STRUCTURAL_CLAIM_KEYS)
    assert audit.closed_requirement_count == 1
    assert audit.blocked_requirement_count == len(REQUIRED_STRUCTURAL_CLAIM_KEYS) - 1
    assert [row.key for row in audit.rows] == list(REQUIRED_STRUCTURAL_CLAIM_KEYS)
    by_key = {row.key: row for row in audit.rows}
    assert by_key["wire_termination"].evidence_strength == "requirements_only"
    assert "required MBL=10080 N" in by_key["wire_termination"].evidence_summary
    assert "Phase43" in by_key["wire_termination"].evidence_artifacts
    assert "material_body_strength_not_termination_allowable" in by_key[
        "wire_termination"
    ].evidence_summary
    assert by_key["rib_spacing_assumption"].evidence_strength == "layout_requirement_only"
    assert "Phase43" in by_key["rib_spacing_assumption"].evidence_artifacts
    assert by_key["torsion_twist_coupling"].evidence_strength == (
        "screening_plus_closure_input_missing"
    )
    assert "Phase37" in by_key["torsion_twist_coupling"].evidence_artifacts
    assert by_key["tip_deflection_limit"].evidence_strength == (
        "claim_boundary_submission_gate_retained"
    )
    assert by_key["tip_deflection_limit"].completion_status == "closed"
    assert "Phase39" in by_key["tip_deflection_limit"].evidence_artifacts
    assert by_key["tip_deflection_limit"].completion_blocker == (
        "none_current_submission_gate_retained"
    )
    assert by_key["full_wing_global_buckling"].evidence_strength == (
        "claim_boundary_plus_braced_route_not_rankable"
    )
    assert "Phase38" in by_key["full_wing_global_buckling"].evidence_artifacts
    assert "Phase41" in by_key["full_wing_global_buckling"].evidence_artifacts
    assert "Phase42" in by_key["full_wing_global_buckling"].evidence_artifacts
    assert by_key["full_wing_global_buckling"].completion_blocker == (
        "braced_subassembly_reference_load_formulation_not_rankable"
    )
    assert by_key["failure_mode_ordering"].evidence_strength == (
        "detail_modes_listed_but_unranked"
    )
    assert "unranked real-structure modes=7" in by_key["failure_mode_ordering"].evidence_summary


def test_write_goal_completion_audit_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_structural_goal_completion_audit_package(
        tmp_path,
        _closure_index(),
        failure_mode_ordering=_failure_mode_ordering(),
    )

    assert {path.name for path in outputs} == {
        "structural_goal_completion_audit.csv",
        "structural_goal_completion_audit.json",
        "structural_goal_completion_audit.md",
    }
    report = (tmp_path / "structural_goal_completion_audit.md").read_text(encoding="utf-8")
    assert "not complete" in report
    assert "Do not mark the goal complete" in report
    assert "full-wing" in report
    assert "rear EI quantified; rear_stiffness_5pct moved response" in report
    assert "Run rear-spar-on/off FEM" in report
