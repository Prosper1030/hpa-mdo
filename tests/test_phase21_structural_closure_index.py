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


def test_closure_index_covers_requested_blockers_and_keeps_not_signed_off() -> None:
    index = build_structural_closure_index(
        _claim_review(),
        local_ledger=_local_ledger(),
        torsion_audit=_torsion_audit(),
    )

    assert index.overall_status == "engineering_not_signed_off"
    assert [item.key for item in index.items] == list(REQUIRED_STRUCTURAL_CLAIM_KEYS)
    by_key = {item.key: item for item in index.items}
    assert by_key["wire_attach_local_load_path"].status == "load_quantified_detail_not_closed"
    assert by_key["rear_spar_stiffness"].status == "stiffness_quantified_global_role_not_closed"
    assert by_key["tip_deflection_limit"].status == "claim_guarded_not_physical_failure"
    assert "Phase19" in by_key["wire_attach_local_load_path"].evidence_artifacts
    assert "Phase20" in by_key["rear_spar_stiffness"].evidence_artifacts
    assert "tip_deflection" in by_key["failure_mode_ordering"].current_evidence


def test_write_structural_closure_index_package_creates_handoff_files(tmp_path: Path) -> None:
    outputs = write_structural_closure_index_package(
        tmp_path,
        _claim_review(),
        local_ledger=_local_ledger(),
        torsion_audit=_torsion_audit(),
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
