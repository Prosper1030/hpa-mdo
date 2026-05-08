from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import phase25_failure_mode_ordering as phase25
from scripts.phase25_failure_mode_ordering import (
    build_failure_mode_ordering,
    write_failure_mode_ordering_package,
)


def _claim_review() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        modeled_first_limiter_with_current_wire="wire_tension_body_allowable",
        modeled_first_limiter_with_6kn_wire="tip_deflection",
        current_wire_body_limit_load_factor=3.0,
        tip_deflection_limit_load_factor=4.0,
        wire6_body_limit_load_factor=12.0,
    )


def _detail_requirements() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(
                key="wire_attach_local_load_path",
                required_allowable_load_n=6000.0,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=None,
                body_allowable_margin_n=None,
            ),
            SimpleNamespace(
                key="root_joint",
                required_allowable_load_n=20.0,
                required_allowable_moment_n_m=10000.0,
                required_minimum_breaking_load_n=None,
                body_allowable_margin_n=None,
            ),
            SimpleNamespace(
                key="wire_termination",
                required_allowable_load_n=6000.0,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=10000.0,
                body_allowable_margin_n=-1000.0,
            ),
        )
    )


def _rib_spacing_requirements() -> SimpleNamespace:
    return SimpleNamespace(
        total_added_bracing_stations=53,
        recommended_station_count=61,
        max_recommended_subbay_m=0.297,
    )


def _detail_margin_check() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(
                key="wire_attach_local_load_path",
                status="hardware_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
            SimpleNamespace(
                key="root_joint",
                status="hardware_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
            SimpleNamespace(
                key="wire_termination",
                status="hardware_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
        )
    )


def _local_detail_subcomponent_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="local_detail_subcomponent_margins_not_closed",
        total_subcomponent_count=11,
        missing_subcomponent_count=9,
        negative_margin_count=1,
        rows=(
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                subcomponent_key="attach_ring_or_lug",
                status="margin_negative",
                load_margin_n=-200.0,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                subcomponent_key="bonded_load_path",
                status="subcomponent_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
            SimpleNamespace(
                parent_key="root_joint",
                subcomponent_key="root_fitting_or_clamp",
                status="subcomponent_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
            SimpleNamespace(
                parent_key="wire_termination",
                subcomponent_key="termination_process_efficiency",
                status="margin_positive_input_check_only",
                load_margin_n=1000.0,
                moment_margin_n_m=None,
                mbl_margin_n=2000.0,
            ),
        ),
    )


def _wire_attach_load_decomposition() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="wire_attach_load_components_defined_not_signoff",
        max_resultant_design_load_n=6048.0,
        rows=(
            SimpleNamespace(component_key="spanwise_y", design_load_n=5839.2),
            SimpleNamespace(component_key="transverse_xz", design_load_n=1576.2),
        ),
    )


def _root_joint_load_envelope() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="root_joint_load_envelope_defined_not_signoff",
        design_root_force_n=18.3,
        design_root_bending_moment_n_m=10833.2,
        force_only_check_is_misleading=True,
        rows=(
            SimpleNamespace(
                load_case_key="moment_couple_arm_0p100m",
                required_couple_force_n=108332.0,
            ),
        ),
    )


def _wire_termination_efficiency_sensitivity() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="termination_efficiency_sensitivity_defined_not_signoff",
        body_allowable_margin_n=-1000.0,
        rows=(
            SimpleNamespace(
                termination_efficiency=0.6,
                required_minimum_breaking_load_n=10000.0,
            ),
            SimpleNamespace(
                termination_efficiency=0.8,
                required_minimum_breaking_load_n=7500.0,
            ),
        ),
    )


def _rib_bracing_margin_check() -> SimpleNamespace:
    return SimpleNamespace(
        required_link_force_n=934.5,
        rows=(
            SimpleNamespace(status="rib_allowable_missing"),
            SimpleNamespace(status="rib_allowable_missing"),
            SimpleNamespace(status="rib_traceability_missing"),
            SimpleNamespace(status="rib_station_coverage_missing"),
        ),
    )


def _torsion_twist_closure_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="torsion_twist_closure_not_closed",
        rows=(SimpleNamespace(status="closure_input_missing"),),
    )


def _torsion_twist_screening() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="torsion_twist_screening_not_aeroelastic_signoff",
        internal_equivalent_twist_deg=0.1846,
        max_spar_pair_line_angle_delta_deg=33.662,
        dense_finite_rib_angle_delta_deg=-8.3,
        rear_soft_angle_delta_deg=36.3,
        closure_input_status="closure_input_missing",
        accepted_closure_methods=("tip_ring_fem", "aeroelastic_loop", "apdl_tip_ring_fem"),
    )


def _full_wing_buckling_closure_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="full_wing_global_buckling_not_closed",
        missing_required_claim_load_factors="1.50;1.75",
        rows=(SimpleNamespace(status="closure_input_missing"),),
    )


def _full_wing_buckling_claim_boundary() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="full_wing_pass_claim_blocked_global_buckling_missing",
        global_buckling_closure_status="closure_input_missing",
        rows=(
            SimpleNamespace(
                claim_load_factor=1.5,
                local_wall_buckling_utilization=0.121,
                tube_stress_utilization=0.269,
                allowed_statement="1.5G internal fixed-design modeled limits clear",
                blocked_statement="Do not claim 1.5G full-wing pass",
            ),
            SimpleNamespace(
                claim_load_factor=1.75,
                local_wall_buckling_utilization=0.141,
                tube_stress_utilization=0.313,
                allowed_statement="1.75G internal fixed-design modeled limits clear",
                blocked_statement="Do not claim 1.75G full-wing pass",
            ),
        ),
    )


def _braced_subassembly_fem_evidence() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="braced_subassembly_reference_load_review_required",
        case_count=2,
        solver_ran_count=2,
        mode_reviewed_count=0,
        claim_load_factor_coverage="1.50;1.75",
        rows=(
            SimpleNamespace(
                status="solver_ran_reference_load_review_required",
                first_eigen_multiplier=2.7e6,
                reference_load_status="unphysical_or_load_sign_review_required",
                phase30_closure_status="mode_review_missing",
            ),
            SimpleNamespace(
                status="solver_ran_reference_load_review_required",
                first_eigen_multiplier=2.7e6,
                reference_load_status="unphysical_or_load_sign_review_required",
                phase30_closure_status="mode_review_missing",
            ),
        ),
    )


def _tip_deflection_revalidation_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="tip_deflection_current_submission_gate_retained",
        rows=(
            SimpleNamespace(
                status="current_submission_gate_retained",
                proposed_raw_tip_limit_m=2.5,
            ),
        ),
    )


def _tip_deflection_claim_boundary() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="tip_deflection_claim_boundary_submission_gate_retained",
        current_raw_tip_limit_m=2.5,
        current_effective_tip_limit_m=2.55,
        deflection_limit_load_factor=3.3049,
        revalidation_status="current_submission_gate_retained",
        rows=(
            SimpleNamespace(
                policy_key="current_submission_gate",
                status="design_validity_gate_not_fracture",
                allowed_statement="2.5 m raw tip limit remains a design-validity/submission gate",
                blocked_statement="Do not treat the 2.5 m raw gate as a fracture point",
            ),
            SimpleNamespace(
                policy_key="exploration_relaxation",
                status="exploration_only_not_submission",
                allowed_statement="Exploration-only relaxation may be used for trade studies",
                blocked_statement="Do not use exploration relaxation for submission",
            ),
            SimpleNamespace(
                policy_key="submission_relaxation",
                status="submission_relaxation_requires_rechecks",
                allowed_statement="Submission relaxation requires rechecks",
                blocked_statement="Do not relax submission gate without rechecks",
            ),
        ),
    )


def test_failure_mode_ordering_keeps_ranked_model_modes_separate_from_unranked_hardware_modes() -> None:
    ordering = build_failure_mode_ordering(
        _claim_review(),
        detail_requirements=_detail_requirements(),
        rib_spacing_requirements=_rib_spacing_requirements(),
        detail_margin_check=_detail_margin_check(),
        local_detail_subcomponent_check=_local_detail_subcomponent_check(),
        wire_attach_load_decomposition=_wire_attach_load_decomposition(),
        root_joint_load_envelope=_root_joint_load_envelope(),
        wire_termination_efficiency_sensitivity=_wire_termination_efficiency_sensitivity(),
        rib_bracing_margin_check=_rib_bracing_margin_check(),
        torsion_twist_closure_check=_torsion_twist_closure_check(),
        torsion_twist_screening=_torsion_twist_screening(),
        full_wing_buckling_closure_check=_full_wing_buckling_closure_check(),
        full_wing_buckling_claim_boundary=_full_wing_buckling_claim_boundary(),
        braced_subassembly_fem_evidence=_braced_subassembly_fem_evidence(),
        tip_deflection_revalidation_check=_tip_deflection_revalidation_check(),
        tip_deflection_claim_boundary=_tip_deflection_claim_boundary(),
    )

    assert ordering.overall_status == "true_failure_order_not_closed"
    assert ordering.modeled_first_limiter_with_current_wire == "wire_tension_body_allowable"
    assert ordering.modeled_first_limiter_with_6kn_wire == "tip_deflection"
    assert ordering.known_unranked_mode_count == 7
    by_key = {row.mode_key: row for row in ordering.rows}
    assert by_key["wire_tension_body_allowable_current"].load_factor == pytest.approx(3.0)
    assert by_key["tip_deflection_limit"].status == "design_validity_gate_not_fracture"
    assert "claim boundary status=tip_deflection_claim_boundary_submission_gate_retained" in by_key[
        "tip_deflection_limit"
    ].evidence
    assert "submission policy=submission_relaxation_requires_rechecks" in by_key[
        "tip_deflection_limit"
    ].evidence
    assert by_key["wire_termination"].order_bucket == "unranked_real_structure_mode"
    assert by_key["wire_termination"].required_minimum_breaking_load_n == pytest.approx(10000.0)
    assert by_key["wire_termination"].body_allowable_margin_n == pytest.approx(-1000.0)
    assert by_key["wire_attach_local_load_path"].status == (
        "unranked_detail_subcomponent_margin_negative"
    )
    assert "hardware status=hardware_allowable_missing" in by_key["wire_attach_local_load_path"].evidence
    assert "local subcomponents missing=1" in by_key[
        "wire_attach_local_load_path"
    ].evidence
    assert "local subcomponent negative margins=1" in by_key[
        "wire_attach_local_load_path"
    ].evidence
    assert "attach max resultant design=6048.0000 N" in by_key[
        "wire_attach_local_load_path"
    ].evidence
    assert "attach spanwise design=5839.2000 N" in by_key[
        "wire_attach_local_load_path"
    ].evidence
    assert "attach transverse design=1576.2000 N" in by_key[
        "wire_attach_local_load_path"
    ].evidence
    assert "root design moment=10833.2000 N*m" in by_key["root_joint"].evidence
    assert "root max couple force=108332.0000 N" in by_key["root_joint"].evidence
    assert "root max couple case=moment_couple_arm_0p100m" in by_key["root_joint"].evidence
    assert "force-only misleading=True" in by_key["root_joint"].evidence
    assert "termination eta 0.60 MBL=10000.0000 N" in by_key["wire_termination"].evidence
    assert "termination eta 0.80 MBL=7500.0000 N" in by_key["wire_termination"].evidence
    assert "gate status=current_submission_gate_retained" in by_key["tip_deflection_limit"].evidence
    assert "added stations=53" in by_key["rib_load_transfer"].evidence
    assert "rib allowables missing=2" in by_key["rib_load_transfer"].evidence
    assert "rib traceability gaps=1" in by_key["rib_load_transfer"].evidence
    assert "rib station coverage gaps=1" in by_key["rib_load_transfer"].evidence
    assert "closure status=closure_input_missing" in by_key["torsion_twist_coupling"].evidence
    assert "missing claim n=unknown" not in by_key["torsion_twist_coupling"].evidence
    assert "screening status=torsion_twist_screening_not_aeroelastic_signoff" in by_key[
        "torsion_twist_coupling"
    ].evidence
    assert "internal equivalent twist=0.1846 deg" in by_key[
        "torsion_twist_coupling"
    ].evidence
    assert "accepted methods=tip_ring_fem; aeroelastic_loop; apdl_tip_ring_fem" in by_key[
        "torsion_twist_coupling"
    ].evidence
    assert by_key["full_wing_global_buckling"].load_factor is None
    assert by_key["full_wing_global_buckling"].status == (
        "unranked_global_buckling_reference_load_review_required"
    )
    assert "closure status=closure_input_missing" in by_key["full_wing_global_buckling"].evidence
    assert "missing claim n=1.50;1.75" in by_key[
        "full_wing_global_buckling"
    ].evidence
    assert "claim boundary status=full_wing_pass_claim_blocked_global_buckling_missing" in by_key[
        "full_wing_global_buckling"
    ].evidence
    assert "1.75G local wall util=0.1410" in by_key[
        "full_wing_global_buckling"
    ].evidence
    assert "braced subassembly status=braced_subassembly_reference_load_review_required" in by_key[
        "full_wing_global_buckling"
    ].evidence
    assert "reference-load review rows=2" in by_key[
        "full_wing_global_buckling"
    ].evidence
    assert "Phase30 status=mode_review_missing" in by_key[
        "full_wing_global_buckling"
    ].evidence
    assert "reference-load/sign" in by_key["full_wing_global_buckling"].next_evidence


def test_failure_mode_ordering_surfaces_local_subcomponent_traceability_gaps() -> None:
    check = SimpleNamespace(
        rows=(
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                subcomponent_key="attach_ring_or_lug",
                status="subcomponent_traceability_missing",
                load_margin_n=1000.0,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                subcomponent_key="bonded_load_path",
                status="margin_positive_input_check_only",
                load_margin_n=1200.0,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
        )
    )

    assert phase25._local_detail_subcomponent_status(  # noqa: SLF001
        "wire_attach_local_load_path",
        check,
    ) == "unranked_detail_subcomponent_traceability_missing"
    evidence = phase25._local_detail_subcomponent_evidence(  # noqa: SLF001
        "wire_attach_local_load_path",
        check,
    )
    assert "local subcomponent traceability gaps=1" in evidence
    assert "local subcomponent positive input rows=1" in evidence


def test_failure_mode_ordering_surfaces_local_moment_allowable_gaps() -> None:
    check = SimpleNamespace(
        rows=(
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                subcomponent_key="attach_ring_or_lug",
                status="subcomponent_moment_allowable_missing",
                load_margin_n=1000.0,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
        )
    )

    assert phase25._local_detail_subcomponent_status(  # noqa: SLF001
        "wire_attach_local_load_path",
        check,
    ) == "unranked_detail_subcomponent_moment_allowable_missing"
    evidence = phase25._local_detail_subcomponent_evidence(  # noqa: SLF001
        "wire_attach_local_load_path",
        check,
    )
    assert "local moment allowable gaps=1" in evidence


def test_failure_mode_ordering_includes_derated_termination_margin_in_worst_local_margin() -> None:
    check = SimpleNamespace(
        rows=(
            SimpleNamespace(
                parent_key="wire_termination",
                subcomponent_key="termination_process_efficiency",
                status="margin_negative",
                load_margin_n=1000.0,
                moment_margin_n_m=None,
                mbl_margin_n=2000.0,
                effective_termination_load_margin_n=-600.0,
            ),
        )
    )

    evidence = phase25._local_detail_subcomponent_evidence(  # noqa: SLF001
        "wire_termination",
        check,
    )
    assert "worst local margin=-600.0000" in evidence


def test_failure_mode_ordering_aggregates_duplicate_wire_attach_components() -> None:
    decomposition = SimpleNamespace(
        overall_status="wire_attach_load_components_defined_not_signoff",
        max_resultant_design_load_n=9000.0,
        rows=(
            SimpleNamespace(component_key="spanwise_y", design_load_n=7200.0),
            SimpleNamespace(component_key="spanwise_y", design_load_n=5800.0),
            SimpleNamespace(component_key="transverse_xz", design_load_n=1100.0),
            SimpleNamespace(component_key="transverse_xz", design_load_n=1800.0),
        ),
    )

    evidence = phase25._wire_attach_load_decomposition_evidence(decomposition)  # noqa: SLF001

    assert "attach spanwise design=7200.0000 N" in evidence
    assert "attach transverse design=1800.0000 N" in evidence


def test_failure_mode_ordering_reports_worst_root_couple_row() -> None:
    envelope = SimpleNamespace(
        overall_status="root_joint_load_envelope_defined_not_signoff",
        design_root_force_n=18.3,
        design_root_bending_moment_n_m=10000.0,
        force_only_check_is_misleading=True,
        rows=(
            SimpleNamespace(
                load_case_key="moment_couple_arm_0p100m",
                required_couple_force_n=100000.0,
            ),
            SimpleNamespace(
                load_case_key="moment_couple_arm_0p050m",
                required_couple_force_n=200000.0,
            ),
        ),
    )

    evidence = phase25._root_joint_load_envelope_evidence(envelope)  # noqa: SLF001

    assert "root max couple force=200000.0000 N" in evidence
    assert "root max couple case=moment_couple_arm_0p050m" in evidence


def test_write_failure_mode_ordering_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_failure_mode_ordering_package(
        tmp_path,
        _claim_review(),
        detail_requirements=_detail_requirements(),
        rib_spacing_requirements=_rib_spacing_requirements(),
        detail_margin_check=_detail_margin_check(),
        local_detail_subcomponent_check=_local_detail_subcomponent_check(),
        wire_attach_load_decomposition=_wire_attach_load_decomposition(),
        root_joint_load_envelope=_root_joint_load_envelope(),
        wire_termination_efficiency_sensitivity=_wire_termination_efficiency_sensitivity(),
        rib_bracing_margin_check=_rib_bracing_margin_check(),
        torsion_twist_closure_check=_torsion_twist_closure_check(),
        torsion_twist_screening=_torsion_twist_screening(),
        full_wing_buckling_closure_check=_full_wing_buckling_closure_check(),
        full_wing_buckling_claim_boundary=_full_wing_buckling_claim_boundary(),
        tip_deflection_revalidation_check=_tip_deflection_revalidation_check(),
        tip_deflection_claim_boundary=_tip_deflection_claim_boundary(),
    )

    assert {path.name for path in outputs} == {
        "failure_mode_ordering.csv",
        "failure_mode_ordering.json",
        "failure_mode_ordering.md",
    }
    report = (tmp_path / "failure_mode_ordering.md").read_text(encoding="utf-8")
    assert "true failure order is not closed" in report
    assert "Ranked Internal Modes" in report
    assert "Unranked Real-Structure Modes" in report
    assert "gate status=current_submission_gate_retained" in report


def test_main_creates_requested_output_directory_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        phase25,
        "build_current_failure_mode_ordering",
        lambda: build_failure_mode_ordering(
            _claim_review(),
            detail_requirements=_detail_requirements(),
            rib_spacing_requirements=_rib_spacing_requirements(),
            detail_margin_check=_detail_margin_check(),
            local_detail_subcomponent_check=_local_detail_subcomponent_check(),
            wire_attach_load_decomposition=_wire_attach_load_decomposition(),
            root_joint_load_envelope=_root_joint_load_envelope(),
            wire_termination_efficiency_sensitivity=_wire_termination_efficiency_sensitivity(),
            rib_bracing_margin_check=_rib_bracing_margin_check(),
            torsion_twist_closure_check=_torsion_twist_closure_check(),
            torsion_twist_screening=_torsion_twist_screening(),
            full_wing_buckling_closure_check=_full_wing_buckling_closure_check(),
            full_wing_buckling_claim_boundary=_full_wing_buckling_claim_boundary(),
            tip_deflection_revalidation_check=_tip_deflection_revalidation_check(),
            tip_deflection_claim_boundary=_tip_deflection_claim_boundary(),
        ),
    )
    out_dir = tmp_path / "nested" / "phase25"

    assert phase25.main(["--output-dir", str(out_dir)]) == 0

    assert (out_dir / "failure_mode_ordering.md").exists()
