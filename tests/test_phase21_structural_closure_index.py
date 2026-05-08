from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import phase21_structural_closure_index as phase21
from scripts.phase18_structural_claim_readiness import REQUIRED_STRUCTURAL_CLAIM_KEYS
from scripts.phase21_structural_closure_index import (
    build_structural_closure_index,
    write_structural_closure_index_package,
)


def _item(key: str) -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        title=key.replace("_", " ").title(),
        status="unresolved_blocker",
        current_evidence=f"{key} phase18 evidence",
        required_next_evidence=f"{key} next evidence",
    )


def _claim_review() -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="sample",
        overall_verdict="not_ready_for_full_wing_or_hardware_signoff",
        modeled_first_limiter_with_current_wire="wire_tension_body_allowable",
        modeled_first_limiter_with_6kn_wire="tip_deflection",
        tip_deflection_limit_load_factor=3.305,
        current_wire_body_limit_load_factor=3.030,
        wire6_body_limit_load_factor=3.968,
        items=tuple(_item(key) for key in REQUIRED_STRUCTURAL_CLAIM_KEYS),
    )


def _local_ledger() -> SimpleNamespace:
    return SimpleNamespace(
        entries=(
            SimpleNamespace(
                key="wire_attach_local_load_path",
                title="Wire attach local load path",
                primary_load_n=3024.0,
                primary_moment_n_m=None,
                utilization=None,
                max_effective_bay_m=None,
                evidence="attach force vector is known",
                missing_evidence="attach allowable missing",
            ),
            SimpleNamespace(
                key="root_joint",
                title="Root joint",
                primary_load_n=9.2,
                primary_moment_n_m=5416.6,
                utilization=None,
                max_effective_bay_m=None,
                evidence="root moment is known",
                missing_evidence="root fitting allowable missing",
            ),
            SimpleNamespace(
                key="wire_termination",
                title="Wire termination",
                primary_load_n=3024.0,
                primary_moment_n_m=None,
                utilization=0.66,
                max_effective_bay_m=None,
                evidence="body utilization is known",
                missing_evidence="termination allowable missing",
            ),
            SimpleNamespace(
                key="rib_load_transfer",
                title="Rib load transfer",
                primary_load_n=21.3,
                primary_moment_n_m=None,
                utilization=None,
                max_effective_bay_m=3.862,
                evidence="mandatory bay is known",
                missing_evidence="rib stiffness missing",
            ),
        )
    )


def _torsion_audit() -> SimpleNamespace:
    return SimpleNamespace(
        rear_bending_stiffness_fraction_mean=0.0455,
        rear_torsion_tube_stiffness_fraction_mean=0.0455,
        equivalent_twist_max_deg=0.1846,
        max_spar_pair_line_angle_delta_deg=33.662,
        max_effective_bay_m=3.862,
        nominal_rib_bay_m=0.30,
        entries=(
            SimpleNamespace(
                key="rear_spar_stiffness",
                evidence="rear EI fraction known",
                missing_evidence="global role unproven",
            ),
            SimpleNamespace(
                key="torsion_twist_coupling",
                evidence="spar-pair angle known",
                missing_evidence="aeroelastic loop missing",
            ),
            SimpleNamespace(
                key="rib_spacing_assumption",
                evidence="bay exceeds nominal rib bay",
                missing_evidence="physical bracing missing",
            ),
        ),
    )


def _bracing_audit() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(
                variant_id="baseline_joint_only",
                tip_main_delta_vs_baseline_pct=0.0,
                max_vertical_delta_vs_baseline_pct=0.0,
                angle_delta_vs_baseline_deg=0.0,
                link_force_max_n=3055.0,
            ),
            SimpleNamespace(
                variant_id="dense_finite_rib_surrogate",
                tip_main_delta_vs_baseline_pct=-17.7,
                max_vertical_delta_vs_baseline_pct=-17.2,
                angle_delta_vs_baseline_deg=-8.3,
                link_force_max_n=934.5,
            ),
            SimpleNamespace(
                variant_id="rear_stiffness_5pct",
                tip_main_delta_vs_baseline_pct=292.6,
                max_vertical_delta_vs_baseline_pct=295.8,
                angle_delta_vs_baseline_deg=36.3,
                link_force_max_n=1201.8,
            ),
        )
    )


def _bracing_diagnostic() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="bracing_effective_but_not_signed_off",
        rows=(
            SimpleNamespace(
                key="rear_spar_stiffness",
                status="strong_model_sensitivity_not_signoff",
                tip_delta_pct=292.6,
                max_vertical_delta_pct=295.8,
                angle_delta_deg=36.3,
                link_force_max_n=1201.8,
                model_bias_guardrail="internal_model_bias_guardrail_required",
            ),
            SimpleNamespace(
                key="rib_load_transfer",
                status="surrogate_load_transfer_not_signoff",
                tip_delta_pct=-17.7,
                max_vertical_delta_pct=-17.2,
                angle_delta_deg=-8.3,
                link_force_max_n=934.5,
                model_bias_guardrail="internal_model_bias_guardrail_required",
            ),
        ),
    )


def _detail_requirements() -> SimpleNamespace:
    return SimpleNamespace(
        rows=(
            SimpleNamespace(
                key="wire_attach_local_load_path",
                required_allowable_load_n=6048.2,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=None,
                body_allowable_margin_n=None,
            ),
            SimpleNamespace(
                key="root_joint",
                required_allowable_load_n=18.3,
                required_allowable_moment_n_m=10833.2,
                required_minimum_breaking_load_n=None,
                body_allowable_margin_n=None,
            ),
            SimpleNamespace(
                key="wire_termination",
                required_allowable_load_n=6048.2,
                required_allowable_moment_n_m=None,
                required_minimum_breaking_load_n=10080.3,
                body_allowable_margin_n=-1466.7,
            ),
        )
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
        missing_subcomponent_count=11,
        negative_margin_count=0,
        rows=(
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                subcomponent_key="attach_ring_or_lug",
                status="subcomponent_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
            SimpleNamespace(
                parent_key="wire_attach_local_load_path",
                subcomponent_key="bonded_load_path",
                status="subcomponent_traceability_missing",
                load_margin_n=1200.0,
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
                status="subcomponent_allowable_missing",
                load_margin_n=None,
                moment_margin_n_m=None,
                mbl_margin_n=None,
            ),
        ),
    )


def _wire_attach_load_decomposition() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="wire_attach_load_components_defined_not_signoff",
        max_resultant_service_load_n=3024.0,
        max_resultant_design_load_n=6048.0,
        rows=(
            SimpleNamespace(
                wire_identifier="wire-1",
                component_key="spanwise_y",
                service_load_n=2919.6,
                design_load_n=5839.2,
            ),
            SimpleNamespace(
                wire_identifier="wire-1",
                component_key="transverse_xz",
                service_load_n=788.1,
                design_load_n=1576.2,
            ),
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
            SimpleNamespace(
                load_case_key="moment_couple_arm_0p050m",
                required_couple_force_n=216664.0,
            ),
        ),
    )


def _wire_termination_efficiency_sensitivity() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="termination_efficiency_sensitivity_defined_not_signoff",
        body_allowable_margin_n=-1466.7,
        rows=(
            SimpleNamespace(
                termination_efficiency=0.6,
                required_minimum_breaking_load_n=10080.3,
            ),
            SimpleNamespace(
                termination_efficiency=0.8,
                required_minimum_breaking_load_n=7560.2,
            ),
        ),
    )


def _rib_spacing_requirements() -> SimpleNamespace:
    return SimpleNamespace(
        current_max_bay_m=3.86,
        target_bay_m=0.30,
        total_added_bracing_stations=15,
        recommended_station_count=22,
        max_recommended_subbay_m=0.297,
    )


def _rib_bracing_margin_check() -> SimpleNamespace:
    return SimpleNamespace(
        required_link_force_n=934.5,
        rows=(
            SimpleNamespace(
                bay_index=0,
                status="rib_allowable_missing",
                link_margin_n=None,
                shear_margin_n=None,
                bond_margin_n=None,
            ),
            SimpleNamespace(
                bay_index=1,
                status="rib_allowable_missing",
                link_margin_n=None,
                shear_margin_n=None,
                bond_margin_n=None,
            ),
            SimpleNamespace(
                bay_index=2,
                status="rib_traceability_missing",
                link_margin_n=200.0,
                shear_margin_n=100.0,
                bond_margin_n=50.0,
            ),
            SimpleNamespace(
                bay_index=3,
                status="rib_station_coverage_missing",
                link_margin_n=200.0,
                shear_margin_n=100.0,
                bond_margin_n=50.0,
            ),
        ),
    )


def _torsion_twist_closure_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="torsion_twist_closure_not_closed",
        rows=(
            SimpleNamespace(
                case_id="torsion_twist_closure_input_required",
                status="closure_input_missing",
                measured_twist_deg=None,
                twist_margin_deg=None,
                torque_balance_margin_pct=None,
            ),
        ),
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
        required_claim_load_factors=(1.5, 1.75),
        missing_required_claim_load_factors="1.50;1.75",
        rows=(
            SimpleNamespace(
                case_id="full_wing_global_buckling_input_required",
                status="closure_input_missing",
                model_scope="",
                claim_load_factor=None,
                first_global_buckling_load_factor=None,
                load_factor_margin=None,
                missing_components="main_spar;rear_spar;finite_ribs;wire_attach_load_path;root_boundary",
            ),
        ),
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


def _tip_deflection_revalidation_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="tip_deflection_current_submission_gate_retained",
        rows=(
            SimpleNamespace(
                case_id="current_2p5m_submission_gate",
                status="current_submission_gate_retained",
                usage_context="submission",
                current_raw_tip_limit_m=2.5,
                proposed_raw_tip_limit_m=2.5,
                deflection_limit_load_factor=3.305,
                missing_rechecks="",
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


def _failure_mode_ordering() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="true_failure_order_not_closed",
        known_unranked_mode_count=7,
        modeled_first_limiter_with_current_wire="wire_tension_body_allowable",
        modeled_first_limiter_with_6kn_wire="tip_deflection",
    )


def test_closure_index_covers_requested_blockers_and_keeps_not_signed_off() -> None:
    index = build_structural_closure_index(
        _claim_review(),
        local_ledger=_local_ledger(),
        torsion_audit=_torsion_audit(),
        bracing_audit=_bracing_audit(),
        bracing_diagnostic=_bracing_diagnostic(),
        detail_requirements=_detail_requirements(),
        detail_margin_check=_detail_margin_check(),
        local_detail_subcomponent_check=_local_detail_subcomponent_check(),
        wire_attach_load_decomposition=_wire_attach_load_decomposition(),
        root_joint_load_envelope=_root_joint_load_envelope(),
        wire_termination_efficiency_sensitivity=_wire_termination_efficiency_sensitivity(),
        rib_spacing_requirements=_rib_spacing_requirements(),
        rib_bracing_margin_check=_rib_bracing_margin_check(),
        torsion_twist_closure_check=_torsion_twist_closure_check(),
        torsion_twist_screening=_torsion_twist_screening(),
        full_wing_buckling_closure_check=_full_wing_buckling_closure_check(),
        full_wing_buckling_claim_boundary=_full_wing_buckling_claim_boundary(),
        tip_deflection_revalidation_check=_tip_deflection_revalidation_check(),
        tip_deflection_claim_boundary=_tip_deflection_claim_boundary(),
        failure_mode_ordering=_failure_mode_ordering(),
    )

    assert index.overall_status == "engineering_not_signed_off"
    assert [item.key for item in index.items] == list(REQUIRED_STRUCTURAL_CLAIM_KEYS)
    by_key = {item.key: item for item in index.items}
    assert by_key["wire_attach_local_load_path"].status == "load_quantified_detail_not_closed"
    assert by_key["rear_spar_stiffness"].status == "stiffness_quantified_global_role_not_closed"
    assert by_key["tip_deflection_limit"].status == "claim_guarded_not_physical_failure"
    assert "Phase19" in by_key["wire_attach_local_load_path"].evidence_artifacts
    assert "Phase23" in by_key["wire_attach_local_load_path"].evidence_artifacts
    assert "Phase27" in by_key["wire_attach_local_load_path"].evidence_artifacts
    assert "Phase33" in by_key["wire_attach_local_load_path"].evidence_artifacts
    assert "required load=6048.2000 N" in by_key["wire_attach_local_load_path"].current_evidence
    assert "hardware status=hardware_allowable_missing" in by_key["wire_attach_local_load_path"].current_evidence
    assert "subcomponents missing=1" in by_key[
        "wire_attach_local_load_path"
    ].current_evidence
    assert "traceability gaps=1" in by_key[
        "wire_attach_local_load_path"
    ].current_evidence
    assert "Phase34" in by_key["wire_attach_local_load_path"].evidence_artifacts
    assert "spanwise design=5839.2000 N" in by_key[
        "wire_attach_local_load_path"
    ].current_evidence
    assert "transverse design=1576.2000 N" in by_key[
        "wire_attach_local_load_path"
    ].current_evidence
    assert "Phase35" in by_key["root_joint"].evidence_artifacts
    assert "required moment=10833.2000 N*m" in by_key["root_joint"].current_evidence
    assert "subcomponents missing=1" in by_key["root_joint"].current_evidence
    assert "design moment=10833.2000 N*m" in by_key["root_joint"].current_evidence
    assert "max couple force=216664.0000 N" in by_key["root_joint"].current_evidence
    assert "max couple case=moment_couple_arm_0p050m" in by_key["root_joint"].current_evidence
    assert "required MBL=10080.3000 N" in by_key["wire_termination"].current_evidence
    assert "body margin=-1466.7000 N" in by_key["wire_termination"].current_evidence
    assert "subcomponents missing=1" in by_key["wire_termination"].current_evidence
    assert "Phase36" in by_key["wire_termination"].evidence_artifacts
    assert "MBL at eta 0.60=10080.3000 N" in by_key[
        "wire_termination"
    ].current_evidence
    assert "MBL at eta 0.80=7560.2000 N" in by_key[
        "wire_termination"
    ].current_evidence
    assert "Phase20" in by_key["rear_spar_stiffness"].evidence_artifacts
    assert "Phase22" in by_key["rear_spar_stiffness"].evidence_artifacts
    assert "Phase29" in by_key["torsion_twist_coupling"].evidence_artifacts
    assert "Phase37" in by_key["torsion_twist_coupling"].evidence_artifacts
    assert "rear_stiffness_5pct" in by_key["rear_spar_stiffness"].current_evidence
    assert "Phase32" in by_key["rear_spar_stiffness"].evidence_artifacts
    assert "diagnostic status=strong_model_sensitivity_not_signoff" in by_key[
        "rear_spar_stiffness"
    ].current_evidence
    assert "closure status=closure_input_missing" in by_key["torsion_twist_coupling"].current_evidence
    assert "screening status=torsion_twist_screening_not_aeroelastic_signoff" in by_key[
        "torsion_twist_coupling"
    ].current_evidence
    assert "dense finite rib angle delta=-8.3000 deg" in by_key[
        "torsion_twist_coupling"
    ].current_evidence
    assert "dense_finite_rib_surrogate" in by_key["rib_load_transfer"].current_evidence
    assert "Phase32" in by_key["rib_load_transfer"].evidence_artifacts
    assert "diagnostic status=surrogate_load_transfer_not_signoff" in by_key[
        "rib_load_transfer"
    ].current_evidence
    assert "Phase24" in by_key["rib_spacing_assumption"].evidence_artifacts
    assert "Phase28" in by_key["rib_load_transfer"].evidence_artifacts
    assert "added stations=15" in by_key["rib_spacing_assumption"].current_evidence
    assert "max recommended subbay=0.2970 m" in by_key["rib_load_transfer"].current_evidence
    assert "required link force=934.5000 N" in by_key["rib_load_transfer"].current_evidence
    assert "traceability-gap bays=1" in by_key["rib_load_transfer"].current_evidence
    assert "station-coverage-gap bays=1" in by_key["rib_load_transfer"].current_evidence
    assert "missing bays=2" in by_key["rib_spacing_assumption"].current_evidence
    assert "Phase25" in by_key["failure_mode_ordering"].evidence_artifacts
    assert "unranked modes=7" in by_key["failure_mode_ordering"].current_evidence
    assert "tip_deflection" in by_key["failure_mode_ordering"].current_evidence
    assert "detail modes are listed as unranked" in by_key[
        "failure_mode_ordering"
    ].current_evidence
    assert "Phase30" in by_key["full_wing_global_buckling"].evidence_artifacts
    assert "Phase38" in by_key["full_wing_global_buckling"].evidence_artifacts
    assert "closure status=closure_input_missing" in by_key["full_wing_global_buckling"].current_evidence
    assert "missing claim n=1.50;1.75" in by_key[
        "full_wing_global_buckling"
    ].current_evidence
    assert "claim boundary status=full_wing_pass_claim_blocked_global_buckling_missing" in by_key[
        "full_wing_global_buckling"
    ].current_evidence
    assert "1.75G local wall util=0.1410" in by_key[
        "full_wing_global_buckling"
    ].current_evidence
    assert "missing components=main_spar;rear_spar;finite_ribs;wire_attach_load_path;root_boundary" in by_key[
        "full_wing_global_buckling"
    ].current_evidence
    assert "Phase31" in by_key["tip_deflection_limit"].evidence_artifacts
    assert "Phase39" in by_key["tip_deflection_limit"].evidence_artifacts
    assert "gate status=current_submission_gate_retained" in by_key["tip_deflection_limit"].current_evidence
    assert "proposed raw limit=2.5000 m" in by_key["tip_deflection_limit"].current_evidence
    assert "claim boundary status=tip_deflection_claim_boundary_submission_gate_retained" in by_key[
        "tip_deflection_limit"
    ].current_evidence
    assert "submission policy=submission_relaxation_requires_rechecks" in by_key[
        "tip_deflection_limit"
    ].current_evidence


def test_closure_index_summaries_use_first_blocking_row_not_first_row() -> None:
    torsion_summary = phase21._torsion_twist_closure_summary(  # noqa: SLF001
        SimpleNamespace(
            overall_status="torsion_twist_closure_not_closed",
            rows=(
                SimpleNamespace(
                    status="margin_positive_input_check_only",
                    twist_margin_deg=1.0,
                    torque_balance_margin_pct=5.0,
                ),
                SimpleNamespace(
                    status="margin_negative",
                    twist_margin_deg=-0.1,
                    torque_balance_margin_pct=2.0,
                ),
            ),
        )
    )
    assert "closure status=margin_negative" in torsion_summary
    assert "twist margin=-0.1000 deg" in torsion_summary

    buckling_summary = phase21._full_wing_buckling_closure_summary(  # noqa: SLF001
        SimpleNamespace(
            overall_status="full_wing_global_buckling_not_closed",
            missing_required_claim_load_factors="1.75",
            rows=(
                SimpleNamespace(
                    status="margin_positive_input_check_only",
                    claim_load_factor=1.5,
                    first_global_buckling_load_factor=2.0,
                    load_factor_margin=0.5,
                    missing_components="",
                ),
                SimpleNamespace(
                    status="required_structural_components_missing",
                    claim_load_factor=1.75,
                    first_global_buckling_load_factor=2.1,
                    load_factor_margin=0.35,
                    missing_components="rear_spar",
                ),
            ),
        )
    )
    assert "closure status=required_structural_components_missing" in buckling_summary
    assert "claim n=1.7500" in buckling_summary
    assert "missing components=rear_spar" in buckling_summary


def test_write_structural_closure_index_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_structural_closure_index_package(
        tmp_path,
        _claim_review(),
        local_ledger=_local_ledger(),
        torsion_audit=_torsion_audit(),
        bracing_audit=_bracing_audit(),
        bracing_diagnostic=_bracing_diagnostic(),
        detail_requirements=_detail_requirements(),
        detail_margin_check=_detail_margin_check(),
        local_detail_subcomponent_check=_local_detail_subcomponent_check(),
        wire_attach_load_decomposition=_wire_attach_load_decomposition(),
        root_joint_load_envelope=_root_joint_load_envelope(),
        wire_termination_efficiency_sensitivity=_wire_termination_efficiency_sensitivity(),
        rib_spacing_requirements=_rib_spacing_requirements(),
        rib_bracing_margin_check=_rib_bracing_margin_check(),
        torsion_twist_closure_check=_torsion_twist_closure_check(),
        torsion_twist_screening=_torsion_twist_screening(),
        full_wing_buckling_closure_check=_full_wing_buckling_closure_check(),
        full_wing_buckling_claim_boundary=_full_wing_buckling_claim_boundary(),
        tip_deflection_revalidation_check=_tip_deflection_revalidation_check(),
        tip_deflection_claim_boundary=_tip_deflection_claim_boundary(),
        failure_mode_ordering=_failure_mode_ordering(),
    )

    assert {path.name for path in outputs} == {
        "structural_closure_index.csv",
        "structural_closure_index.json",
        "structural_closure_index.md",
    }
    report = (tmp_path / "structural_closure_index.md").read_text(encoding="utf-8")
    assert "engineering_not_signed_off" in report
    assert "not a hardware signoff" in report
    assert "wire_tension_body_allowable" in report
