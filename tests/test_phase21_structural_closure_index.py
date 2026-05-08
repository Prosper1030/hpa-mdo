from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


def _full_wing_buckling_closure_check() -> SimpleNamespace:
    return SimpleNamespace(
        overall_status="full_wing_global_buckling_not_closed",
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
        detail_requirements=_detail_requirements(),
        detail_margin_check=_detail_margin_check(),
        rib_spacing_requirements=_rib_spacing_requirements(),
        rib_bracing_margin_check=_rib_bracing_margin_check(),
        torsion_twist_closure_check=_torsion_twist_closure_check(),
        full_wing_buckling_closure_check=_full_wing_buckling_closure_check(),
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
    assert "required load=6048.2000 N" in by_key["wire_attach_local_load_path"].current_evidence
    assert "hardware status=hardware_allowable_missing" in by_key["wire_attach_local_load_path"].current_evidence
    assert "required moment=10833.2000 N*m" in by_key["root_joint"].current_evidence
    assert "required MBL=10080.3000 N" in by_key["wire_termination"].current_evidence
    assert "body margin=-1466.7000 N" in by_key["wire_termination"].current_evidence
    assert "Phase20" in by_key["rear_spar_stiffness"].evidence_artifacts
    assert "Phase22" in by_key["rear_spar_stiffness"].evidence_artifacts
    assert "Phase29" in by_key["torsion_twist_coupling"].evidence_artifacts
    assert "rear_stiffness_5pct" in by_key["rear_spar_stiffness"].current_evidence
    assert "closure status=closure_input_missing" in by_key["torsion_twist_coupling"].current_evidence
    assert "dense_finite_rib_surrogate" in by_key["rib_load_transfer"].current_evidence
    assert "Phase24" in by_key["rib_spacing_assumption"].evidence_artifacts
    assert "Phase28" in by_key["rib_load_transfer"].evidence_artifacts
    assert "added stations=15" in by_key["rib_spacing_assumption"].current_evidence
    assert "max recommended subbay=0.2970 m" in by_key["rib_load_transfer"].current_evidence
    assert "required link force=934.5000 N" in by_key["rib_load_transfer"].current_evidence
    assert "missing bays=2" in by_key["rib_spacing_assumption"].current_evidence
    assert "Phase25" in by_key["failure_mode_ordering"].evidence_artifacts
    assert "unranked modes=7" in by_key["failure_mode_ordering"].current_evidence
    assert "tip_deflection" in by_key["failure_mode_ordering"].current_evidence
    assert "Phase30" in by_key["full_wing_global_buckling"].evidence_artifacts
    assert "closure status=closure_input_missing" in by_key["full_wing_global_buckling"].current_evidence
    assert "missing components=main_spar;rear_spar;finite_ribs;wire_attach_load_path;root_boundary" in by_key[
        "full_wing_global_buckling"
    ].current_evidence


def test_write_structural_closure_index_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_structural_closure_index_package(
        tmp_path,
        _claim_review(),
        local_ledger=_local_ledger(),
        torsion_audit=_torsion_audit(),
        bracing_audit=_bracing_audit(),
        detail_requirements=_detail_requirements(),
        detail_margin_check=_detail_margin_check(),
        rib_spacing_requirements=_rib_spacing_requirements(),
        rib_bracing_margin_check=_rib_bracing_margin_check(),
        torsion_twist_closure_check=_torsion_twist_closure_check(),
        full_wing_buckling_closure_check=_full_wing_buckling_closure_check(),
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
