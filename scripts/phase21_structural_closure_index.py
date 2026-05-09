#!/usr/bin/env python3
"""Build a one-page closure index for the current structural signoff blockers."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    build_phase15_rows,
    load_current_candidate_reference,
)
from scripts.phase18_structural_claim_readiness import (  # noqa: E402
    REQUIRED_STRUCTURAL_CLAIM_KEYS,
    build_structural_claim_readiness,
)
from scripts.phase19_local_load_path_ledger import (  # noqa: E402
    build_local_load_path_ledger,
    load_current_spar_rows,
    load_current_wire_rigging,
)
from scripts.phase20_rear_spar_torsion_audit import (  # noqa: E402
    build_rear_spar_torsion_audit,
    load_current_equivalent_twist_max_deg,
    load_current_material_stiffness,
    load_current_rows,
)
from scripts.phase22_bracing_sensitivity import (  # noqa: E402
    build_bracing_sensitivity_audit,
    build_current_candidate_model,
)
from scripts.phase23_detail_sizing_requirements import (  # noqa: E402
    build_detail_sizing_requirements,
)
from scripts.phase24_rib_spacing_requirements import (  # noqa: E402
    build_rib_spacing_requirements,
)
from scripts.phase25_failure_mode_ordering import (  # noqa: E402
    build_failure_mode_ordering,
)
from scripts.phase27_detail_margin_inputs import (  # noqa: E402
    build_detail_margin_check,
)
from scripts.phase28_rib_bracing_margin_inputs import (  # noqa: E402
    build_rib_bracing_margin_check,
)
from scripts.phase29_torsion_twist_closure_inputs import (  # noqa: E402
    build_torsion_twist_closure_check,
)
from scripts.phase30_full_wing_buckling_closure_inputs import (  # noqa: E402
    build_full_wing_buckling_closure_check,
)
from scripts.phase31_tip_deflection_revalidation_inputs import (  # noqa: E402
    build_tip_deflection_revalidation_check,
)
from scripts.phase32_rear_spar_rib_bracing_diagnostic import (  # noqa: E402
    build_rear_spar_rib_bracing_diagnostic,
)
from scripts.phase33_local_detail_subcomponent_margins import (  # noqa: E402
    build_local_detail_subcomponent_margin_check,
)
from scripts.phase34_wire_attach_load_decomposition import (  # noqa: E402
    build_wire_attach_load_decomposition,
)
from scripts.phase35_root_joint_load_envelope import (  # noqa: E402
    build_root_joint_load_envelope,
)
from scripts.phase36_wire_termination_efficiency_sensitivity import (  # noqa: E402
    build_wire_termination_efficiency_sensitivity,
)
from scripts.phase37_torsion_twist_screening import (  # noqa: E402
    build_torsion_twist_screening,
)
from scripts.phase38_full_wing_buckling_claim_boundary import (  # noqa: E402
    build_full_wing_buckling_claim_boundary,
)
from scripts.phase39_tip_deflection_claim_boundary import (  # noqa: E402
    build_tip_deflection_claim_boundary,
)
from scripts.phase40_existing_fem_evidence_triage import (  # noqa: E402
    build_current_existing_fem_evidence_triage,
)
from scripts.phase41_braced_subassembly_fem_evidence import (  # noqa: E402
    load_current_braced_subassembly_fem_evidence,
    phase30_closure_inputs_from_evidence,
)
from scripts.phase42_phase41_reference_load_review import (  # noqa: E402
    build_current_phase41_reference_load_review,
)
from scripts.phase43_existing_detail_allowable_evidence_triage import (  # noqa: E402
    build_current_existing_detail_allowable_evidence_triage,
)
from scripts.phase44_phase41_mode_shape_review import (  # noqa: E402
    build_current_phase41_mode_shape_review,
)
from scripts.phase45_phase41_rib_spacing_link_review import (  # noqa: E402
    build_current_phase41_rib_spacing_link_review,
)
from scripts.phase46_local_detail_criticality_ordering import (  # noqa: E402
    build_local_detail_criticality_ordering,
)
from scripts.phase47_existing_torsion_twist_evidence_triage import (  # noqa: E402
    build_current_existing_torsion_twist_evidence_triage,
)
from scripts.phase48_root_joint_detail_feasibility_screen import (  # noqa: E402
    build_current_root_joint_detail_feasibility_screen,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase21_structural_closure_index"


@dataclass(frozen=True)
class StructuralClosureItem:
    key: str
    title: str
    status: str
    evidence_artifacts: str
    current_evidence: str
    remaining_blocker: str
    next_action: str


@dataclass(frozen=True)
class StructuralClosureIndex:
    candidate_id: str
    overall_status: str
    modeled_first_limiter_with_current_wire: str
    modeled_first_limiter_with_6kn_wire: str
    items: tuple[StructuralClosureItem, ...]


def build_structural_closure_index(
    claim_review: Any,
    *,
    local_ledger: Any | None = None,
    torsion_audit: Any | None = None,
    bracing_audit: Any | None = None,
    bracing_diagnostic: Any | None = None,
    detail_requirements: Any | None = None,
    detail_margin_check: Any | None = None,
    local_detail_subcomponent_check: Any | None = None,
    wire_attach_load_decomposition: Any | None = None,
    root_joint_load_envelope: Any | None = None,
    root_joint_detail_feasibility_screen: Any | None = None,
    wire_termination_efficiency_sensitivity: Any | None = None,
    local_detail_criticality_ordering: Any | None = None,
    rib_spacing_requirements: Any | None = None,
    rib_bracing_margin_check: Any | None = None,
    torsion_twist_closure_check: Any | None = None,
    torsion_twist_screening: Any | None = None,
    existing_torsion_twist_evidence_triage: Any | None = None,
    full_wing_buckling_closure_check: Any | None = None,
    full_wing_buckling_claim_boundary: Any | None = None,
    tip_deflection_revalidation_check: Any | None = None,
    tip_deflection_claim_boundary: Any | None = None,
    failure_mode_ordering: Any | None = None,
    existing_fem_evidence_triage: Any | None = None,
    braced_subassembly_fem_evidence: Any | None = None,
    phase41_reference_load_review: Any | None = None,
    phase41_mode_shape_review: Any | None = None,
    phase41_rib_spacing_link_review: Any | None = None,
    existing_detail_allowable_evidence_triage: Any | None = None,
) -> StructuralClosureIndex:
    claim_by_key = _entry_map(claim_review.items)
    local_by_key = _entry_map(getattr(local_ledger, "entries", ()))
    torsion_by_key = _entry_map(getattr(torsion_audit, "entries", ()))

    items = tuple(
        _build_item(
            key,
            claim_by_key[key],
            claim_review=claim_review,
            local_entry=local_by_key.get(key),
            torsion_entry=torsion_by_key.get(key),
            torsion_audit=torsion_audit,
            bracing_audit=bracing_audit,
            bracing_diagnostic=bracing_diagnostic,
            detail_requirements=detail_requirements,
            detail_margin_check=detail_margin_check,
            local_detail_subcomponent_check=local_detail_subcomponent_check,
            wire_attach_load_decomposition=wire_attach_load_decomposition,
            root_joint_load_envelope=root_joint_load_envelope,
            root_joint_detail_feasibility_screen=(
                root_joint_detail_feasibility_screen
            ),
            wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
            local_detail_criticality_ordering=local_detail_criticality_ordering,
            rib_spacing_requirements=rib_spacing_requirements,
            rib_bracing_margin_check=rib_bracing_margin_check,
            torsion_twist_closure_check=torsion_twist_closure_check,
            torsion_twist_screening=torsion_twist_screening,
            existing_torsion_twist_evidence_triage=(
                existing_torsion_twist_evidence_triage
            ),
            full_wing_buckling_closure_check=full_wing_buckling_closure_check,
            full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
            tip_deflection_revalidation_check=tip_deflection_revalidation_check,
            tip_deflection_claim_boundary=tip_deflection_claim_boundary,
            failure_mode_ordering=failure_mode_ordering,
            existing_fem_evidence_triage=existing_fem_evidence_triage,
            braced_subassembly_fem_evidence=braced_subassembly_fem_evidence,
            phase41_reference_load_review=phase41_reference_load_review,
            phase41_mode_shape_review=phase41_mode_shape_review,
            phase41_rib_spacing_link_review=phase41_rib_spacing_link_review,
            existing_detail_allowable_evidence_triage=(
                existing_detail_allowable_evidence_triage
            ),
        )
        for key in REQUIRED_STRUCTURAL_CLAIM_KEYS
    )
    _assert_complete(items)
    return StructuralClosureIndex(
        candidate_id=str(claim_review.candidate_id),
        overall_status="engineering_not_signed_off",
        modeled_first_limiter_with_current_wire=str(
            claim_review.modeled_first_limiter_with_current_wire
        ),
        modeled_first_limiter_with_6kn_wire=str(claim_review.modeled_first_limiter_with_6kn_wire),
        items=items,
    )


def write_structural_closure_index_package(
    out_dir: Path,
    claim_review: Any,
    *,
    local_ledger: Any | None = None,
    torsion_audit: Any | None = None,
    bracing_audit: Any | None = None,
    bracing_diagnostic: Any | None = None,
    detail_requirements: Any | None = None,
    detail_margin_check: Any | None = None,
    local_detail_subcomponent_check: Any | None = None,
    wire_attach_load_decomposition: Any | None = None,
    root_joint_load_envelope: Any | None = None,
    root_joint_detail_feasibility_screen: Any | None = None,
    wire_termination_efficiency_sensitivity: Any | None = None,
    local_detail_criticality_ordering: Any | None = None,
    rib_spacing_requirements: Any | None = None,
    rib_bracing_margin_check: Any | None = None,
    torsion_twist_closure_check: Any | None = None,
    torsion_twist_screening: Any | None = None,
    existing_torsion_twist_evidence_triage: Any | None = None,
    full_wing_buckling_closure_check: Any | None = None,
    full_wing_buckling_claim_boundary: Any | None = None,
    tip_deflection_revalidation_check: Any | None = None,
    tip_deflection_claim_boundary: Any | None = None,
    failure_mode_ordering: Any | None = None,
    existing_fem_evidence_triage: Any | None = None,
    braced_subassembly_fem_evidence: Any | None = None,
    phase41_reference_load_review: Any | None = None,
    phase41_mode_shape_review: Any | None = None,
    phase41_rib_spacing_link_review: Any | None = None,
    existing_detail_allowable_evidence_triage: Any | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    index = build_structural_closure_index(
        claim_review,
        local_ledger=local_ledger,
        torsion_audit=torsion_audit,
        bracing_audit=bracing_audit,
        bracing_diagnostic=bracing_diagnostic,
        detail_requirements=detail_requirements,
        detail_margin_check=detail_margin_check,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        root_joint_detail_feasibility_screen=root_joint_detail_feasibility_screen,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        local_detail_criticality_ordering=local_detail_criticality_ordering,
        rib_spacing_requirements=rib_spacing_requirements,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        torsion_twist_screening=torsion_twist_screening,
        existing_torsion_twist_evidence_triage=existing_torsion_twist_evidence_triage,
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
        tip_deflection_claim_boundary=tip_deflection_claim_boundary,
        failure_mode_ordering=failure_mode_ordering,
        existing_fem_evidence_triage=existing_fem_evidence_triage,
        braced_subassembly_fem_evidence=braced_subassembly_fem_evidence,
        phase41_reference_load_review=phase41_reference_load_review,
        phase41_mode_shape_review=phase41_mode_shape_review,
        phase41_rib_spacing_link_review=phase41_rib_spacing_link_review,
        existing_detail_allowable_evidence_triage=existing_detail_allowable_evidence_triage,
    )
    outputs = [
        _write_csv(out_dir / "structural_closure_index.csv", index),
        _write_json(out_dir / "structural_closure_index.json", index),
        _write_markdown(out_dir / "structural_closure_index.md", index),
    ]
    return outputs


def build_current_structural_closure_index() -> StructuralClosureIndex:
    reference = load_current_candidate_reference()
    review = build_structural_claim_readiness(reference)
    local_ledger = build_local_load_path_ledger(
        reference,
        wire_rigging=load_current_wire_rigging(),
        spar_rows=load_current_spar_rows(),
    )
    jig_rows, loaded_rows = load_current_rows()
    main_e, main_g, rear_e, rear_g = load_current_material_stiffness()
    torsion_audit = build_rear_spar_torsion_audit(
        reference.candidate_id,
        jig_rows=jig_rows,
        loaded_rows=loaded_rows,
        young_pa=main_e,
        shear_pa=main_g,
        rear_young_pa=rear_e,
        rear_shear_pa=rear_g,
        equivalent_twist_max_deg=load_current_equivalent_twist_max_deg(),
    )
    detail_requirements = build_detail_sizing_requirements(local_ledger)
    detail_margin_check = build_detail_margin_check(detail_requirements, hardware_allowables=[])
    wire_attach_load_decomposition = build_wire_attach_load_decomposition(
        reference.candidate_id,
        wire_rigging=load_current_wire_rigging(),
    )
    local_detail_subcomponent_check = build_local_detail_subcomponent_margin_check(
        detail_requirements,
        subcomponent_allowables=[],
        wire_attach_load_decomposition=wire_attach_load_decomposition,
    )
    root_joint_load_envelope = build_root_joint_load_envelope(reference)
    root_joint_detail_feasibility_screen = (
        build_current_root_joint_detail_feasibility_screen()
    )
    wire_termination_efficiency_sensitivity = build_wire_termination_efficiency_sensitivity(
        detail_requirements
    )
    rib_spacing_requirements = build_rib_spacing_requirements(
        reference.candidate_id,
        spar_rows=load_current_spar_rows(),
        wire_rigging=load_current_wire_rigging(),
    )
    candidate_model = build_current_candidate_model()
    bracing_audit = build_bracing_sensitivity_audit(reference.candidate_id, candidate_model)
    bracing_diagnostic = build_rear_spar_rib_bracing_diagnostic(bracing_audit)
    rib_bracing_margin_check = build_rib_bracing_margin_check(
        rib_spacing_requirements,
        bracing_audit,
        rib_allowables=[],
    )
    torsion_twist_closure_check = build_torsion_twist_closure_check(
        torsion_audit,
        closure_inputs=[],
    )
    torsion_twist_screening = build_torsion_twist_screening(
        torsion_audit,
        bracing_audit=bracing_audit,
        closure_check=torsion_twist_closure_check,
    )
    braced_subassembly_fem_evidence = load_current_braced_subassembly_fem_evidence()
    phase41_reference_load_review = build_current_phase41_reference_load_review()
    phase41_mode_shape_review = build_current_phase41_mode_shape_review()
    phase41_rib_spacing_link_review = build_current_phase41_rib_spacing_link_review()
    existing_detail_allowable_evidence_triage = (
        build_current_existing_detail_allowable_evidence_triage()
    )
    existing_torsion_twist_evidence_triage = (
        build_current_existing_torsion_twist_evidence_triage()
    )
    local_detail_criticality_ordering = build_local_detail_criticality_ordering(
        reference.candidate_id,
        detail_requirements=detail_requirements,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        existing_detail_allowable_evidence_triage=(
            existing_detail_allowable_evidence_triage
        ),
    )
    full_wing_buckling_closure_check = build_full_wing_buckling_closure_check(
        reference.candidate_id,
        closure_inputs=phase30_closure_inputs_from_evidence(
            braced_subassembly_fem_evidence
        ),
    )
    full_wing_buckling_claim_boundary = build_full_wing_buckling_claim_boundary(
        reference.candidate_id,
        phase15_rows=build_phase15_rows(reference),
        closure_check=full_wing_buckling_closure_check,
    )
    tip_deflection_revalidation_check = build_tip_deflection_revalidation_check(
        reference,
        revalidation_inputs=[],
    )
    tip_deflection_claim_boundary = build_tip_deflection_claim_boundary(
        reference,
        revalidation_check=tip_deflection_revalidation_check,
    )
    existing_fem_evidence_triage = build_current_existing_fem_evidence_triage()
    failure_mode_ordering = build_failure_mode_ordering(
        review,
        detail_requirements=detail_requirements,
        rib_spacing_requirements=rib_spacing_requirements,
        detail_margin_check=detail_margin_check,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        root_joint_detail_feasibility_screen=root_joint_detail_feasibility_screen,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        local_detail_criticality_ordering=local_detail_criticality_ordering,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        torsion_twist_screening=torsion_twist_screening,
        existing_torsion_twist_evidence_triage=(
            existing_torsion_twist_evidence_triage
        ),
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
        braced_subassembly_fem_evidence=braced_subassembly_fem_evidence,
        phase41_reference_load_review=phase41_reference_load_review,
        phase41_mode_shape_review=phase41_mode_shape_review,
        phase41_rib_spacing_link_review=phase41_rib_spacing_link_review,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
        tip_deflection_claim_boundary=tip_deflection_claim_boundary,
    )
    return build_structural_closure_index(
        review,
        local_ledger=local_ledger,
        torsion_audit=torsion_audit,
        bracing_audit=bracing_audit,
        bracing_diagnostic=bracing_diagnostic,
        detail_requirements=detail_requirements,
        detail_margin_check=detail_margin_check,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        root_joint_detail_feasibility_screen=root_joint_detail_feasibility_screen,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        local_detail_criticality_ordering=local_detail_criticality_ordering,
        rib_spacing_requirements=rib_spacing_requirements,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        torsion_twist_screening=torsion_twist_screening,
        existing_torsion_twist_evidence_triage=(
            existing_torsion_twist_evidence_triage
        ),
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
        tip_deflection_claim_boundary=tip_deflection_claim_boundary,
        failure_mode_ordering=failure_mode_ordering,
        existing_fem_evidence_triage=existing_fem_evidence_triage,
        braced_subassembly_fem_evidence=braced_subassembly_fem_evidence,
        phase41_reference_load_review=phase41_reference_load_review,
        phase41_mode_shape_review=phase41_mode_shape_review,
        phase41_rib_spacing_link_review=phase41_rib_spacing_link_review,
        existing_detail_allowable_evidence_triage=existing_detail_allowable_evidence_triage,
    )


def _build_item(
    key: str,
    claim: Any,
    *,
    claim_review: Any,
    local_entry: Any | None,
    torsion_entry: Any | None,
    torsion_audit: Any | None,
    bracing_audit: Any | None,
    bracing_diagnostic: Any | None,
    detail_requirements: Any | None,
    detail_margin_check: Any | None,
    local_detail_subcomponent_check: Any | None,
    wire_attach_load_decomposition: Any | None,
    root_joint_load_envelope: Any | None,
    root_joint_detail_feasibility_screen: Any | None,
    wire_termination_efficiency_sensitivity: Any | None,
    local_detail_criticality_ordering: Any | None,
    rib_spacing_requirements: Any | None,
    rib_bracing_margin_check: Any | None,
    torsion_twist_closure_check: Any | None,
    torsion_twist_screening: Any | None,
    existing_torsion_twist_evidence_triage: Any | None,
    full_wing_buckling_closure_check: Any | None,
    full_wing_buckling_claim_boundary: Any | None,
    tip_deflection_revalidation_check: Any | None,
    tip_deflection_claim_boundary: Any | None,
    failure_mode_ordering: Any | None,
    existing_fem_evidence_triage: Any | None,
    braced_subassembly_fem_evidence: Any | None,
    phase41_reference_load_review: Any | None,
    phase41_mode_shape_review: Any | None,
    phase41_rib_spacing_link_review: Any | None,
    existing_detail_allowable_evidence_triage: Any | None,
) -> StructuralClosureItem:
    detail_entry = _detail_entry_for_key(key, detail_requirements)
    detail_margin_entry = _detail_margin_entry_for_key(key, detail_margin_check)
    evidence_artifacts = _evidence_artifacts(
        key,
        local_entry,
        torsion_entry,
        bracing_audit,
        bracing_diagnostic,
        detail_entry,
        detail_margin_entry,
        local_detail_subcomponent_check,
        wire_attach_load_decomposition,
        root_joint_load_envelope,
        root_joint_detail_feasibility_screen,
        wire_termination_efficiency_sensitivity,
        local_detail_criticality_ordering,
        rib_spacing_requirements,
        rib_bracing_margin_check,
        torsion_twist_closure_check,
        torsion_twist_screening,
        existing_torsion_twist_evidence_triage,
        full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary,
        tip_deflection_revalidation_check,
        tip_deflection_claim_boundary,
        failure_mode_ordering,
        existing_fem_evidence_triage,
        braced_subassembly_fem_evidence,
        phase41_reference_load_review,
        phase41_mode_shape_review,
        phase41_rib_spacing_link_review,
        existing_detail_allowable_evidence_triage,
    )
    status = _status_for_key(key, local_entry, torsion_entry)
    evidence = _evidence_for_key(
        key,
        claim,
        claim_review=claim_review,
        local_entry=local_entry,
        torsion_entry=torsion_entry,
        torsion_audit=torsion_audit,
        bracing_audit=bracing_audit,
        bracing_diagnostic=bracing_diagnostic,
        detail_entry=detail_entry,
        detail_margin_entry=detail_margin_entry,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        root_joint_detail_feasibility_screen=root_joint_detail_feasibility_screen,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        local_detail_criticality_ordering=local_detail_criticality_ordering,
        rib_spacing_requirements=rib_spacing_requirements,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        torsion_twist_screening=torsion_twist_screening,
        existing_torsion_twist_evidence_triage=(
            existing_torsion_twist_evidence_triage
        ),
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
        tip_deflection_claim_boundary=tip_deflection_claim_boundary,
        failure_mode_ordering=failure_mode_ordering,
        existing_fem_evidence_triage=existing_fem_evidence_triage,
        braced_subassembly_fem_evidence=braced_subassembly_fem_evidence,
        phase41_reference_load_review=phase41_reference_load_review,
        phase41_mode_shape_review=phase41_mode_shape_review,
        phase41_rib_spacing_link_review=phase41_rib_spacing_link_review,
        existing_detail_allowable_evidence_triage=(
            existing_detail_allowable_evidence_triage
        ),
    )
    return StructuralClosureItem(
        key=key,
        title=str(claim.title),
        status=status,
        evidence_artifacts=evidence_artifacts,
        current_evidence=evidence,
        remaining_blocker=str(claim.required_next_evidence),
        next_action=_next_action_for_key(key),
    )


def _status_for_key(key: str, local_entry: Any | None, torsion_entry: Any | None) -> str:
    if key in {
        "wire_attach_local_load_path",
        "root_joint",
        "wire_termination",
        "rib_load_transfer",
    } and local_entry is not None:
        return "load_quantified_detail_not_closed"
    if key == "rear_spar_stiffness" and torsion_entry is not None:
        return "stiffness_quantified_global_role_not_closed"
    if key == "torsion_twist_coupling" and torsion_entry is not None:
        return "geometry_quantified_aeroelastic_loop_not_closed"
    if key == "rib_spacing_assumption" and torsion_entry is not None:
        return "bay_quantified_physical_bracing_not_closed"
    if key == "tip_deflection_limit":
        return "claim_guarded_not_physical_failure"
    if key == "full_wing_global_buckling":
        return "claim_guarded_global_buckling_not_closed"
    if key == "failure_mode_ordering":
        return "modeled_order_known_true_order_not_closed"
    return "claim_guarded_not_closed"


def _evidence_artifacts(
    key: str,
    local_entry: Any | None,
    torsion_entry: Any | None,
    bracing_audit: Any | None,
    bracing_diagnostic: Any | None,
    detail_entry: Any | None,
    detail_margin_entry: Any | None,
    local_detail_subcomponent_check: Any | None,
    wire_attach_load_decomposition: Any | None,
    root_joint_load_envelope: Any | None,
    root_joint_detail_feasibility_screen: Any | None,
    wire_termination_efficiency_sensitivity: Any | None,
    local_detail_criticality_ordering: Any | None,
    rib_spacing_requirements: Any | None,
    rib_bracing_margin_check: Any | None,
    torsion_twist_closure_check: Any | None,
    torsion_twist_screening: Any | None,
    existing_torsion_twist_evidence_triage: Any | None,
    full_wing_buckling_closure_check: Any | None,
    full_wing_buckling_claim_boundary: Any | None,
    tip_deflection_revalidation_check: Any | None,
    tip_deflection_claim_boundary: Any | None,
    failure_mode_ordering: Any | None,
    existing_fem_evidence_triage: Any | None,
    braced_subassembly_fem_evidence: Any | None,
    phase41_reference_load_review: Any | None,
    phase41_mode_shape_review: Any | None,
    phase41_rib_spacing_link_review: Any | None,
    existing_detail_allowable_evidence_triage: Any | None,
) -> str:
    artifacts = ["Phase18 structural_claim_readiness"]
    if local_entry is not None:
        artifacts.append("Phase19 local_load_path_ledger")
    if torsion_entry is not None or key == "rib_load_transfer":
        artifacts.append("Phase20 rear_spar_torsion_audit")
    if bracing_audit is not None and key in {
        "rear_spar_stiffness",
        "rib_load_transfer",
        "torsion_twist_coupling",
        "failure_mode_ordering",
    }:
        artifacts.append("Phase22 bracing_sensitivity")
    if bracing_diagnostic is not None and key in {"rear_spar_stiffness", "rib_load_transfer"}:
        artifacts.append("Phase32 rear_spar_rib_bracing_diagnostic")
    if detail_entry is not None:
        artifacts.append("Phase23 detail_sizing_requirements")
    if detail_margin_entry is not None:
        artifacts.append("Phase27 detail_margin_inputs")
    if local_detail_subcomponent_check is not None and key in {
        "wire_attach_local_load_path",
        "root_joint",
        "wire_termination",
    }:
        artifacts.append("Phase33 local_detail_subcomponent_margins")
    if wire_attach_load_decomposition is not None and key == "wire_attach_local_load_path":
        artifacts.append("Phase34 wire_attach_load_decomposition")
    if root_joint_load_envelope is not None and key == "root_joint":
        artifacts.append("Phase35 root_joint_load_envelope")
    if root_joint_detail_feasibility_screen is not None and key == "root_joint":
        artifacts.append("Phase48 root_joint_detail_feasibility_screen")
    if wire_termination_efficiency_sensitivity is not None and key == "wire_termination":
        artifacts.append("Phase36 wire_termination_efficiency_sensitivity")
    if local_detail_criticality_ordering is not None and key in {
        "wire_attach_local_load_path",
        "root_joint",
        "wire_termination",
        "failure_mode_ordering",
    }:
        artifacts.append("Phase46 local_detail_criticality_ordering")
    if rib_spacing_requirements is not None and key in {
        "rib_load_transfer",
        "rib_spacing_assumption",
    }:
        artifacts.append("Phase24 rib_spacing_requirements")
    if rib_bracing_margin_check is not None and key in {
        "rib_load_transfer",
        "rib_spacing_assumption",
    }:
        artifacts.append("Phase28 rib_bracing_margin_inputs")
    if torsion_twist_closure_check is not None and key == "torsion_twist_coupling":
        artifacts.append("Phase29 torsion_twist_closure_inputs")
    if torsion_twist_screening is not None and key == "torsion_twist_coupling":
        artifacts.append("Phase37 torsion_twist_screening")
    if (
        existing_torsion_twist_evidence_triage is not None
        and key == "torsion_twist_coupling"
    ):
        artifacts.append("Phase47 existing_torsion_twist_evidence_triage")
    if full_wing_buckling_closure_check is not None and key == "full_wing_global_buckling":
        artifacts.append("Phase30 full_wing_buckling_closure_inputs")
    if full_wing_buckling_claim_boundary is not None and key == "full_wing_global_buckling":
        artifacts.append("Phase38 full_wing_buckling_claim_boundary")
    if tip_deflection_revalidation_check is not None and key == "tip_deflection_limit":
        artifacts.append("Phase31 tip_deflection_revalidation_inputs")
    if tip_deflection_claim_boundary is not None and key == "tip_deflection_limit":
        artifacts.append("Phase39 tip_deflection_claim_boundary")
    if failure_mode_ordering is not None and key == "failure_mode_ordering":
        artifacts.append("Phase25 failure_mode_ordering")
    if existing_fem_evidence_triage is not None and key in {
        "rear_spar_stiffness",
        "rib_load_transfer",
        "full_wing_global_buckling",
        "failure_mode_ordering",
    }:
        artifacts.append("Phase40 existing_fem_evidence_triage")
    if braced_subassembly_fem_evidence is not None and key in {
        "rear_spar_stiffness",
        "rib_load_transfer",
        "full_wing_global_buckling",
        "failure_mode_ordering",
    }:
        artifacts.append("Phase41 braced_subassembly_fem_evidence")
    if phase41_reference_load_review is not None and key in {
        "full_wing_global_buckling",
        "failure_mode_ordering",
    }:
        artifacts.append("Phase42 phase41_reference_load_review")
    if phase41_mode_shape_review is not None and key in {
        "rear_spar_stiffness",
        "rib_load_transfer",
        "full_wing_global_buckling",
        "failure_mode_ordering",
    }:
        artifacts.append("Phase44 phase41_mode_shape_review")
    if phase41_rib_spacing_link_review is not None and key in {
        "rib_load_transfer",
        "rib_spacing_assumption",
    }:
        artifacts.append("Phase45 phase41_rib_spacing_link_review")
    if existing_detail_allowable_evidence_triage is not None and key in {
        "wire_attach_local_load_path",
        "root_joint",
        "wire_termination",
        "rib_load_transfer",
        "rib_spacing_assumption",
    }:
        artifacts.append("Phase43 existing_detail_allowable_evidence_triage")
    return "; ".join(artifacts)


def _evidence_for_key(
    key: str,
    claim: Any,
    *,
    claim_review: Any,
    local_entry: Any | None,
    torsion_entry: Any | None,
    torsion_audit: Any | None,
    bracing_audit: Any | None,
    bracing_diagnostic: Any | None,
    detail_entry: Any | None,
    detail_margin_entry: Any | None,
    local_detail_subcomponent_check: Any | None,
    wire_attach_load_decomposition: Any | None,
    root_joint_load_envelope: Any | None,
    root_joint_detail_feasibility_screen: Any | None,
    wire_termination_efficiency_sensitivity: Any | None,
    local_detail_criticality_ordering: Any | None,
    rib_spacing_requirements: Any | None,
    rib_bracing_margin_check: Any | None,
    torsion_twist_closure_check: Any | None,
    torsion_twist_screening: Any | None,
    existing_torsion_twist_evidence_triage: Any | None,
    full_wing_buckling_closure_check: Any | None,
    full_wing_buckling_claim_boundary: Any | None,
    tip_deflection_revalidation_check: Any | None,
    tip_deflection_claim_boundary: Any | None,
    failure_mode_ordering: Any | None,
    existing_fem_evidence_triage: Any | None,
    braced_subassembly_fem_evidence: Any | None,
    phase41_reference_load_review: Any | None,
    phase41_mode_shape_review: Any | None,
    phase41_rib_spacing_link_review: Any | None,
    existing_detail_allowable_evidence_triage: Any | None,
) -> str:
    parts = [str(claim.current_evidence)]
    if local_entry is not None:
        parts.append(
            "Phase19: "
            f"{local_entry.evidence}; "
            f"load={_fmt(getattr(local_entry, 'primary_load_n', None))} N; "
            f"moment={_fmt(getattr(local_entry, 'primary_moment_n_m', None))} N*m; "
            f"util={_fmt(getattr(local_entry, 'utilization', None))}; "
            f"bay={_fmt(getattr(local_entry, 'max_effective_bay_m', None))} m."
        )
    if torsion_entry is not None:
        parts.append(f"Phase20: {torsion_entry.evidence}")
    if key == "rear_spar_stiffness" and torsion_audit is not None:
        parts.append(
            "Rear EI mean fraction="
            f"{_fmt(getattr(torsion_audit, 'rear_bending_stiffness_fraction_mean', None))}."
        )
    if key == "torsion_twist_coupling" and torsion_audit is not None:
        parts.append(
            "Equivalent twist="
            f"{_fmt(getattr(torsion_audit, 'equivalent_twist_max_deg', None))} deg; "
            "spar-pair line angle delta="
            f"{_fmt(getattr(torsion_audit, 'max_spar_pair_line_angle_delta_deg', None))} deg "
            "(not aero twist)."
        )
    if key == "rib_spacing_assumption" and torsion_audit is not None:
        parts.append(
            "Mandatory bay="
            f"{_fmt(getattr(torsion_audit, 'max_effective_bay_m', None))} m vs "
            f"{_fmt(getattr(torsion_audit, 'nominal_rib_bay_m', None))} m nominal."
        )
    if key == "tip_deflection_limit":
        parts.append(
            "Tip-deflection design-validity load factor="
            f"{claim_review.tip_deflection_limit_load_factor:.3f}; this is not a fracture point."
        )
    if key == "failure_mode_ordering":
        parts.append(
            "Modeled first limiter: current wire="
            f"{claim_review.modeled_first_limiter_with_current_wire}; 6 kN wire="
            f"{claim_review.modeled_first_limiter_with_6kn_wire}."
        )
    if key == "full_wing_global_buckling":
        parts.append("No full-wing global buckling eigen/FEM result is present in these artifacts.")
    if bracing_audit is not None and key in {
        "rear_spar_stiffness",
        "rib_load_transfer",
        "torsion_twist_coupling",
        "failure_mode_ordering",
    }:
        parts.append(f"Phase22: {_bracing_summary_for_key(key, bracing_audit)}")
    if bracing_diagnostic is not None and key in {"rear_spar_stiffness", "rib_load_transfer"}:
        parts.append(f"Phase32: {_bracing_diagnostic_summary_for_key(key, bracing_diagnostic)}")
    if detail_entry is not None:
        parts.append(f"Phase23: {_detail_summary(detail_entry)}")
    if detail_margin_entry is not None:
        parts.append(f"Phase27: {_detail_margin_summary(detail_margin_entry)}")
    if local_detail_subcomponent_check is not None and key in {
        "wire_attach_local_load_path",
        "root_joint",
        "wire_termination",
    }:
        parts.append(
            f"Phase33: {_local_detail_subcomponent_summary(key, local_detail_subcomponent_check)}"
        )
    if wire_attach_load_decomposition is not None and key == "wire_attach_local_load_path":
        parts.append(f"Phase34: {_wire_attach_load_decomposition_summary(wire_attach_load_decomposition)}")
    if root_joint_load_envelope is not None and key == "root_joint":
        parts.append(f"Phase35: {_root_joint_load_envelope_summary(root_joint_load_envelope)}")
    if root_joint_detail_feasibility_screen is not None and key == "root_joint":
        parts.append(
            "Phase48: "
            f"{_root_joint_detail_feasibility_summary(root_joint_detail_feasibility_screen)}"
        )
    if wire_termination_efficiency_sensitivity is not None and key == "wire_termination":
        parts.append(
            "Phase36: "
            f"{_wire_termination_efficiency_summary(wire_termination_efficiency_sensitivity)}"
        )
    if local_detail_criticality_ordering is not None and key in {
        "wire_attach_local_load_path",
        "root_joint",
        "wire_termination",
    }:
        parts.append(
            "Phase46: "
            f"{_local_detail_criticality_summary(key, local_detail_criticality_ordering)}"
        )
    if rib_spacing_requirements is not None and key in {
        "rib_load_transfer",
        "rib_spacing_assumption",
    }:
        parts.append(f"Phase24: {_rib_spacing_summary(rib_spacing_requirements)}")
    if rib_bracing_margin_check is not None and key in {
        "rib_load_transfer",
        "rib_spacing_assumption",
    }:
        parts.append(f"Phase28: {_rib_bracing_summary(rib_bracing_margin_check)}")
    if torsion_twist_closure_check is not None and key == "torsion_twist_coupling":
        parts.append(f"Phase29: {_torsion_twist_closure_summary(torsion_twist_closure_check)}")
    if torsion_twist_screening is not None and key == "torsion_twist_coupling":
        parts.append(f"Phase37: {_torsion_twist_screening_summary(torsion_twist_screening)}")
    if (
        existing_torsion_twist_evidence_triage is not None
        and key == "torsion_twist_coupling"
    ):
        parts.append(
            "Phase47: "
            f"{_existing_torsion_twist_evidence_triage_summary(existing_torsion_twist_evidence_triage)}"
        )
    if full_wing_buckling_closure_check is not None and key == "full_wing_global_buckling":
        parts.append(
            f"Phase30: {_full_wing_buckling_closure_summary(full_wing_buckling_closure_check)}"
        )
    if full_wing_buckling_claim_boundary is not None and key == "full_wing_global_buckling":
        parts.append(
            f"Phase38: {_full_wing_buckling_claim_boundary_summary(full_wing_buckling_claim_boundary)}"
        )
    if tip_deflection_revalidation_check is not None and key == "tip_deflection_limit":
        parts.append(
            f"Phase31: {_tip_deflection_revalidation_summary(tip_deflection_revalidation_check)}"
        )
    if tip_deflection_claim_boundary is not None and key == "tip_deflection_limit":
        parts.append(f"Phase39: {_tip_deflection_claim_boundary_summary(tip_deflection_claim_boundary)}")
    if failure_mode_ordering is not None and key == "failure_mode_ordering":
        parts.append(f"Phase25: {_failure_ordering_summary(failure_mode_ordering)}")
    if local_detail_criticality_ordering is not None and key == "failure_mode_ordering":
        parts.append(
            "Phase46: "
            f"{_local_detail_criticality_overall_summary(local_detail_criticality_ordering)}"
        )
    if existing_fem_evidence_triage is not None and key in {
        "rear_spar_stiffness",
        "rib_load_transfer",
        "full_wing_global_buckling",
        "failure_mode_ordering",
    }:
        parts.append(f"Phase40: {_existing_fem_evidence_triage_summary(existing_fem_evidence_triage)}")
    if braced_subassembly_fem_evidence is not None and key in {
        "rear_spar_stiffness",
        "rib_load_transfer",
        "full_wing_global_buckling",
        "failure_mode_ordering",
    }:
        parts.append(
            f"Phase41: {_braced_subassembly_fem_evidence_summary(braced_subassembly_fem_evidence)}"
        )
    if phase41_reference_load_review is not None and key in {
        "full_wing_global_buckling",
        "failure_mode_ordering",
    }:
        parts.append(
            f"Phase42: {_phase41_reference_load_review_summary(phase41_reference_load_review)}"
        )
    if phase41_mode_shape_review is not None and key in {
        "rear_spar_stiffness",
        "rib_load_transfer",
        "full_wing_global_buckling",
        "failure_mode_ordering",
    }:
        parts.append(
            f"Phase44: {_phase41_mode_shape_review_summary(phase41_mode_shape_review)}"
        )
    if phase41_rib_spacing_link_review is not None and key in {
        "rib_load_transfer",
        "rib_spacing_assumption",
    }:
        parts.append(
            "Phase45: "
            f"{_phase41_rib_spacing_link_review_summary(phase41_rib_spacing_link_review)}"
        )
    if existing_detail_allowable_evidence_triage is not None and key in {
        "wire_attach_local_load_path",
        "root_joint",
        "wire_termination",
        "rib_load_transfer",
        "rib_spacing_assumption",
    }:
        parts.append(
            "Phase43: "
            f"{_existing_detail_allowable_evidence_triage_summary(key, existing_detail_allowable_evidence_triage)}"
        )
    return " ".join(parts)


def _detail_entry_for_key(key: str, detail_requirements: Any | None) -> Any | None:
    if detail_requirements is None:
        return None
    entries = {
        str(entry.key): entry
        for entry in getattr(detail_requirements, "rows", ())
    }
    return entries.get(key)


def _detail_margin_entry_for_key(key: str, detail_margin_check: Any | None) -> Any | None:
    if detail_margin_check is None:
        return None
    entries = {
        str(entry.key): entry
        for entry in getattr(detail_margin_check, "rows", ())
    }
    return entries.get(key)


def _detail_summary(entry: Any) -> str:
    parts = [
        f"required load={_fmt(getattr(entry, 'required_allowable_load_n', None))} N"
    ]
    moment = getattr(entry, "required_allowable_moment_n_m", None)
    if moment is not None:
        parts.append(f"required moment={_fmt(moment)} N*m")
    mbl = getattr(entry, "required_minimum_breaking_load_n", None)
    if mbl is not None:
        parts.append(f"required MBL={_fmt(mbl)} N")
    body_margin = getattr(entry, "body_allowable_margin_n", None)
    if body_margin is not None:
        parts.append(f"body margin={_fmt(body_margin)} N")
    return "; ".join(parts) + "."


def _detail_margin_summary(entry: Any) -> str:
    return (
        "hardware status="
        f"{getattr(entry, 'status', 'unknown')}; "
        "load margin="
        f"{_fmt(getattr(entry, 'load_margin_n', None))} N; "
        "moment margin="
        f"{_fmt(getattr(entry, 'moment_margin_n_m', None))} N*m; "
        "MBL margin="
        f"{_fmt(getattr(entry, 'mbl_margin_n', None))} N."
    )


def _local_detail_subcomponent_summary(parent_key: str, check: Any) -> str:
    rows = [
        row
        for row in getattr(check, "rows", ())
        if getattr(row, "parent_key", "") == parent_key
    ]
    missing = sum(1 for row in rows if getattr(row, "status", "") == "subcomponent_allowable_missing")
    moment_missing = sum(
        1
        for row in rows
        if getattr(row, "status", "") == "subcomponent_moment_allowable_missing"
    )
    negative = sum(1 for row in rows if getattr(row, "status", "") == "margin_negative")
    traceability_gap = sum(
        1 for row in rows if getattr(row, "status", "") == "subcomponent_traceability_missing"
    )
    positive = sum(
        1 for row in rows if getattr(row, "status", "") == "margin_positive_input_check_only"
    )
    worst_values = [
        value
        for row in rows
        for value in (
            getattr(row, "load_margin_n", None),
            getattr(row, "moment_margin_n_m", None),
            getattr(row, "mbl_margin_n", None),
            getattr(row, "effective_termination_load_margin_n", None),
        )
        if value is not None
    ]
    return (
        "overall="
        f"{getattr(check, 'overall_status', 'unknown')}; "
        "subcomponents="
        f"{len(rows)}; "
        "subcomponents missing="
        f"{missing}; "
        "moment allowable gaps="
        f"{moment_missing}; "
        "negative margins="
        f"{negative}; "
        "traceability gaps="
        f"{traceability_gap}; "
        "positive input rows="
        f"{positive}; "
        "worst margin="
        f"{_fmt(min(worst_values) if worst_values else None)}."
    )


def _wire_attach_load_decomposition_summary(decomposition: Any) -> str:
    rows = tuple(getattr(decomposition, "rows", ()))
    spanwise_design = _component_design_load_max(rows, "spanwise_y")
    transverse_design = _component_design_load_max(rows, "transverse_xz")
    vertical_design = _component_design_load_max(rows, "vertical_z")
    return (
        "overall="
        f"{getattr(decomposition, 'overall_status', 'unknown')}; "
        "max resultant design="
        f"{_fmt(getattr(decomposition, 'max_resultant_design_load_n', None))} N; "
        "spanwise design="
        f"{_fmt(spanwise_design)} N; "
        "transverse design="
        f"{_fmt(transverse_design)} N; "
        "vertical design="
        f"{_fmt(vertical_design)} N."
    )


def _component_design_load_max(rows: tuple[Any, ...], component_key: str) -> float | None:
    values = [
        _optional_float(getattr(row, "design_load_n", None))
        for row in rows
        if str(getattr(row, "component_key", "")) == component_key
    ]
    finite_values = [value for value in values if value is not None]
    return max(finite_values) if finite_values else None


def _root_joint_load_envelope_summary(envelope: Any) -> str:
    max_couple = _max_root_couple_row(tuple(getattr(envelope, "rows", ())))
    return (
        "overall="
        f"{getattr(envelope, 'overall_status', 'unknown')}; "
        "design force="
        f"{_fmt(getattr(envelope, 'design_root_force_n', None))} N; "
        "design moment="
        f"{_fmt(getattr(envelope, 'design_root_bending_moment_n_m', None))} N*m; "
        "force-only misleading="
        f"{getattr(envelope, 'force_only_check_is_misleading', 'unknown')}; "
        "max couple force="
        f"{_fmt(max_couple[0])} N; "
        "max couple case="
        f"{max_couple[1]}."
    )


def _root_joint_detail_feasibility_summary(screen: Any) -> str:
    return (
        "root joint detail feasibility status="
        f"{getattr(screen, 'overall_status', 'unknown')}; "
        "concept rows="
        f"{int(getattr(screen, 'concept_count', 0))}; "
        "positive concept rows="
        f"{int(getattr(screen, 'positive_input_concept_count', 0))}; "
        "negative concept rows="
        f"{int(getattr(screen, 'negative_margin_concept_count', 0))}; "
        "missing concept rows="
        f"{int(getattr(screen, 'missing_input_concept_count', 0))}; "
        "traceability gap concept rows="
        f"{int(getattr(screen, 'traceability_gap_concept_count', 0))}; "
        "max required couple="
        f"{_fmt(getattr(screen, 'envelope_worst_couple_force_n', None))} N; "
        "max required case="
        f"{getattr(screen, 'envelope_worst_couple_case', 'unknown')}."
    )


def _max_root_couple_row(rows: tuple[Any, ...]) -> tuple[float | None, str]:
    values = [
        (
            _optional_float(getattr(row, "required_couple_force_n", None)),
            str(getattr(row, "load_case_key", "unknown")),
        )
        for row in rows
        if _optional_float(getattr(row, "required_couple_force_n", None)) is not None
    ]
    return max(values, key=lambda value: value[0] or float("-inf")) if values else (None, "n/a")


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _wire_termination_efficiency_summary(sensitivity: Any) -> str:
    rows = {float(row.termination_efficiency): row for row in getattr(sensitivity, "rows", ())}
    eta_060 = rows.get(0.6)
    eta_080 = rows.get(0.8)
    return (
        "overall="
        f"{getattr(sensitivity, 'overall_status', 'unknown')}; "
        "body margin="
        f"{_fmt(getattr(sensitivity, 'body_allowable_margin_n', None))} N; "
        "MBL at eta 0.60="
        f"{_fmt(getattr(eta_060, 'required_minimum_breaking_load_n', None) if eta_060 is not None else None)} N; "
        "MBL at eta 0.80="
        f"{_fmt(getattr(eta_080, 'required_minimum_breaking_load_n', None) if eta_080 is not None else None)} N."
    )


def _local_detail_criticality_summary(key: str, ordering: Any) -> str:
    rows = {
        str(getattr(row, "blocker_key", "")): row
        for row in getattr(ordering, "rows", ())
    }
    row = rows.get(key)
    return (
        "local detail criticality status="
        f"{getattr(ordering, 'overall_status', 'unknown')}; "
        "priority rank="
        f"{int(getattr(row, 'work_priority_rank', 0)) if row is not None else 0}; "
        "governing screen="
        f"{getattr(row, 'governing_screen', 'missing') if row is not None else 'missing'}; "
        "severity N-equivalent="
        f"{_fmt(getattr(row, 'design_severity_n_equivalent', None) if row is not None else None)}; "
        "closes margin="
        f"{bool(getattr(row, 'closes_engineering_margin', False)) if row is not None else False}; "
        "boundary="
        f"{getattr(row, 'ordering_boundary', 'missing') if row is not None else 'missing'}."
    )


def _local_detail_criticality_overall_summary(ordering: Any) -> str:
    top_key = str(getattr(ordering, "highest_priority_key", "unknown"))
    rows = {
        str(getattr(row, "blocker_key", "")): row
        for row in getattr(ordering, "rows", ())
    }
    top = rows.get(top_key)
    return (
        "local detail priority top="
        f"{top_key}; "
        "top governing screen="
        f"{getattr(top, 'governing_screen', 'unknown') if top is not None else 'unknown'}; "
        "unclosed details="
        f"{int(getattr(ordering, 'unclosed_detail_count', 0))}; "
        "boundary="
        f"{getattr(top, 'ordering_boundary', 'unknown') if top is not None else 'unknown'}."
    )


def _rib_spacing_summary(requirements: Any) -> str:
    return (
        "current max bay="
        f"{_fmt(getattr(requirements, 'current_max_bay_m', None))} m; "
        "target bay="
        f"{_fmt(getattr(requirements, 'target_bay_m', None))} m; "
        "added stations="
        f"{int(getattr(requirements, 'total_added_bracing_stations', 0))}; "
        "recommended stations="
        f"{int(getattr(requirements, 'recommended_station_count', 0))}; "
        "max recommended subbay="
        f"{_fmt(getattr(requirements, 'max_recommended_subbay_m', None))} m."
    )


def _rib_bracing_summary(check: Any) -> str:
    rows = tuple(getattr(check, "rows", ()))
    missing = sum(1 for row in rows if getattr(row, "status", "") == "rib_allowable_missing")
    negative = sum(1 for row in rows if getattr(row, "status", "") == "margin_negative")
    traceability_gap = sum(1 for row in rows if getattr(row, "status", "") == "rib_traceability_missing")
    station_coverage_gap = sum(
        1 for row in rows if getattr(row, "status", "") == "rib_station_coverage_missing"
    )
    return (
        "required link force="
        f"{_fmt(getattr(check, 'required_link_force_n', None))} N; "
        "missing bays="
        f"{missing}; "
        "negative-margin bays="
        f"{negative}; "
        "traceability-gap bays="
        f"{traceability_gap}; "
        "station-coverage-gap bays="
        f"{station_coverage_gap}."
    )


def _bracing_diagnostic_summary_for_key(key: str, diagnostic: Any) -> str:
    rows = {str(row.key): row for row in getattr(diagnostic, "rows", ())}
    row = rows.get(key)
    if row is None:
        return "diagnostic row unavailable."
    return (
        "diagnostic status="
        f"{getattr(row, 'status', 'unknown')}; "
        "tip delta="
        f"{_fmt(getattr(row, 'tip_delta_pct', None))}%; "
        "max vertical delta="
        f"{_fmt(getattr(row, 'max_vertical_delta_pct', None))}%; "
        "angle delta="
        f"{_fmt(getattr(row, 'angle_delta_deg', None))} deg; "
        "link force="
        f"{_fmt(getattr(row, 'link_force_max_n', None))} N; "
        "guardrail="
        f"{getattr(row, 'model_bias_guardrail', 'unknown')}."
    )


def _torsion_twist_closure_summary(check: Any) -> str:
    rows = tuple(getattr(check, "rows", ()))
    representative = _first_blocking_or_first_row(rows)
    status = (
        "missing"
        if representative is None
        else getattr(representative, "status", "unknown")
    )
    return (
        "closure status="
        f"{status}; "
        "overall="
        f"{getattr(check, 'overall_status', 'unknown')}; "
        "twist margin="
        f"{_fmt(getattr(representative, 'twist_margin_deg', None) if representative is not None else None)} deg; "
        "torque margin="
        f"{_fmt(getattr(representative, 'torque_balance_margin_pct', None) if representative is not None else None)}%."
    )


def _torsion_twist_screening_summary(screening: Any) -> str:
    return (
        "screening status="
        f"{getattr(screening, 'overall_status', 'unknown')}; "
        "internal equivalent twist="
        f"{_fmt(getattr(screening, 'internal_equivalent_twist_deg', None))} deg; "
        "spar-pair angle="
        f"{_fmt(getattr(screening, 'max_spar_pair_line_angle_delta_deg', None))} deg; "
        "dense finite rib angle delta="
        f"{_fmt(getattr(screening, 'dense_finite_rib_angle_delta_deg', None))} deg; "
        "rear-soft angle delta="
        f"{_fmt(getattr(screening, 'rear_soft_angle_delta_deg', None))} deg; "
        "closure input="
        f"{getattr(screening, 'closure_input_status', 'unknown')}; "
        "accepted methods="
        f"{'; '.join(str(method) for method in getattr(screening, 'accepted_closure_methods', ()))}."
    )


def _existing_torsion_twist_evidence_triage_summary(triage: Any) -> str:
    direct_my_status = "missing"
    for row in getattr(triage, "rows", ()):
        if str(getattr(row, "evidence_key", "")) == "phase14_b5_solution_hunt":
            direct_my_status = str(getattr(row, "status", "unknown"))
            break
    return (
        "existing torsion/twist evidence status="
        f"{getattr(triage, 'overall_status', 'unknown')}; "
        "rows="
        f"{int(getattr(triage, 'row_count', 0))}; "
        "torque-observable rows="
        f"{int(getattr(triage, 'torque_observable_evidence_count', 0))}; "
        "aeroelastic closure rows="
        f"{int(getattr(triage, 'aeroelastic_closure_evidence_count', 0))}; "
        "closing rows="
        f"{int(getattr(triage, 'closing_evidence_count', 0))}; "
        "direct MY row status="
        f"{direct_my_status}."
    )


def _full_wing_buckling_closure_summary(check: Any) -> str:
    rows = tuple(getattr(check, "rows", ()))
    representative = _first_blocking_or_first_row(rows)
    status = (
        "missing"
        if representative is None
        else getattr(representative, "status", "unknown")
    )
    return (
        "closure status="
        f"{status}; "
        "overall="
        f"{getattr(check, 'overall_status', 'unknown')}; "
        "claim n="
        f"{_fmt(getattr(representative, 'claim_load_factor', None) if representative is not None else None)}; "
        "first buckling n="
        f"{_fmt(getattr(representative, 'first_global_buckling_load_factor', None) if representative is not None else None)}; "
        "margin n="
        f"{_fmt(getattr(representative, 'load_factor_margin', None) if representative is not None else None)}; "
        "missing components="
        f"{getattr(representative, 'missing_components', 'unknown') if representative is not None else 'unknown'}; "
        "missing claim n="
        f"{getattr(check, 'missing_required_claim_load_factors', 'unknown')}."
    )


def _first_blocking_or_first_row(rows: tuple[Any, ...]) -> Any | None:
    if not rows:
        return None
    return next(
        (
            row
            for row in rows
            if getattr(row, "status", "") != "margin_positive_input_check_only"
        ),
        rows[0],
    )


def _full_wing_buckling_claim_boundary_summary(boundary: Any) -> str:
    rows = {float(row.claim_load_factor): row for row in getattr(boundary, "rows", ())}
    row_15 = rows.get(1.5)
    row_175 = rows.get(1.75)
    return (
        "claim boundary status="
        f"{getattr(boundary, 'overall_status', 'unknown')}; "
        "closure status="
        f"{getattr(boundary, 'global_buckling_closure_status', 'unknown')}; "
        "1.5G local wall util="
        f"{_fmt(getattr(row_15, 'local_wall_buckling_utilization', None) if row_15 is not None else None)}; "
        "1.75G local wall util="
        f"{_fmt(getattr(row_175, 'local_wall_buckling_utilization', None) if row_175 is not None else None)}; "
        "blocked 1.75G statement="
        f"{getattr(row_175, 'blocked_statement', 'unknown') if row_175 is not None else 'unknown'}"
    )


def _tip_deflection_revalidation_summary(check: Any) -> str:
    rows = tuple(getattr(check, "rows", ()))
    first = rows[0] if rows else None
    status = "missing" if first is None else getattr(first, "status", "unknown")
    return (
        "gate status="
        f"{status}; "
        "overall="
        f"{getattr(check, 'overall_status', 'unknown')}; "
        "current raw limit="
        f"{_fmt(getattr(first, 'current_raw_tip_limit_m', None) if first is not None else None)} m; "
        "proposed raw limit="
        f"{_fmt(getattr(first, 'proposed_raw_tip_limit_m', None) if first is not None else None)} m; "
        "deflection-limit n="
        f"{_fmt(getattr(first, 'deflection_limit_load_factor', None) if first is not None else None)}; "
        "missing rechecks="
        f"{(getattr(first, 'missing_rechecks', '') or 'none') if first is not None else 'unknown'}."
    )


def _tip_deflection_claim_boundary_summary(boundary: Any) -> str:
    rows = {str(row.policy_key): row for row in getattr(boundary, "rows", ())}
    submission = rows.get("submission_relaxation")
    exploration = rows.get("exploration_relaxation")
    return (
        "claim boundary status="
        f"{getattr(boundary, 'overall_status', 'unknown')}; "
        "raw gate="
        f"{_fmt(getattr(boundary, 'current_raw_tip_limit_m', None))} m; "
        "limit n="
        f"{_fmt(getattr(boundary, 'deflection_limit_load_factor', None))}; "
        "exploration policy="
        f"{getattr(exploration, 'status', 'unknown') if exploration is not None else 'unknown'}; "
        "submission policy="
        f"{getattr(submission, 'status', 'unknown') if submission is not None else 'unknown'}."
    )


def _failure_ordering_summary(ordering: Any) -> str:
    rows = {
        str(getattr(row, "mode_key", "")): row
        for row in getattr(ordering, "rows", ())
    }
    return (
        "status="
        f"{getattr(ordering, 'overall_status', 'unknown')}; "
        "unranked modes="
        f"{int(getattr(ordering, 'known_unranked_mode_count', 0))}; "
        "current wire first="
        f"{getattr(ordering, 'modeled_first_limiter_with_current_wire', 'unknown')}; "
        "6 kN wire first="
        f"{getattr(ordering, 'modeled_first_limiter_with_6kn_wire', 'unknown')}; "
        "full-wing row status="
        f"{getattr(rows.get('full_wing_global_buckling'), 'status', 'unknown')}; "
        "rib row status="
        f"{getattr(rows.get('rib_load_transfer'), 'status', 'unknown')}; "
        "wire-attach row status="
        f"{getattr(rows.get('wire_attach_local_load_path'), 'status', 'unknown')}; "
        "root row status="
        f"{getattr(rows.get('root_joint'), 'status', 'unknown')}; "
        "termination row status="
        f"{getattr(rows.get('wire_termination'), 'status', 'unknown')}."
    )


def _existing_fem_evidence_triage_summary(triage: Any) -> str:
    rows = tuple(getattr(triage, "rows", ()))
    full_wing_closure_count = sum(
        1 for row in rows if bool(getattr(row, "closes_full_wing_buckling_claim", False))
    )
    rear_rib_closure_count = sum(
        1 for row in rows if bool(getattr(row, "closes_rear_spar_rib_bracing", False))
    )
    hardware_closure_count = sum(
        1 for row in rows if bool(getattr(row, "closes_local_detail_hardware", False))
    )
    candidate_static_coverages = [
        str(getattr(row, "claim_load_factor_coverage", "")).strip()
        for row in rows
        if str(getattr(row, "claim_load_factor_coverage", "")).strip()
    ]
    limited_hifi_count = sum(
        1
        for row in rows
        if getattr(row, "status", "") == "limited_hifi_buckle_not_phase30_closure"
    )
    return (
        "existing FEM triage status="
        f"{getattr(triage, 'overall_status', 'unknown')}; "
        "rows="
        f"{int(getattr(triage, 'row_count', len(rows)))}; "
        "closing rows="
        f"{int(getattr(triage, 'closing_evidence_count', 0))}; "
        "full-wing closure rows="
        f"{full_wing_closure_count}; "
        "rear/rib closure rows="
        f"{rear_rib_closure_count}; "
        "hardware closure rows="
        f"{hardware_closure_count}; "
        "candidate static coverage="
        f"{candidate_static_coverages[0] if candidate_static_coverages else 'n/a'}; "
        "limited hifi rows="
        f"{limited_hifi_count}."
    )


def _braced_subassembly_fem_evidence_summary(evidence: Any) -> str:
    rows = tuple(getattr(evidence, "rows", ()))
    phase30_statuses = sorted(
        {
            str(getattr(row, "phase30_closure_status", "")).strip()
            for row in rows
            if str(getattr(row, "phase30_closure_status", "")).strip()
        }
    )
    reference_review_count = sum(
        1
        for row in rows
        if getattr(row, "reference_load_status", "")
        == "unphysical_or_load_sign_review_required"
    )
    link_node_counts = [
        int(getattr(row, "link_node_count", 0))
        for row in rows
        if getattr(row, "link_node_count", None) is not None
    ]
    wire_support_counts = [
        int(getattr(row, "wire_support_count", 0))
        for row in rows
        if getattr(row, "wire_support_count", None) is not None
    ]
    eigenvalues = [
        _optional_float(getattr(row, "first_eigen_multiplier", None))
        for row in rows
    ]
    finite_eigenvalues = [value for value in eigenvalues if value is not None]
    return (
        "braced subassembly status="
        f"{getattr(evidence, 'overall_status', 'unknown')}; "
        "cases="
        f"{int(getattr(evidence, 'case_count', len(rows)))}; "
        "solver ran="
        f"{int(getattr(evidence, 'solver_ran_count', 0))}; "
        "mode reviewed="
        f"{int(getattr(evidence, 'mode_reviewed_count', 0))}; "
        "claim coverage="
        f"{getattr(evidence, 'claim_load_factor_coverage', 'unknown')}; "
        "reference-load review rows="
        f"{reference_review_count}; "
        "max link nodes="
        f"{max(link_node_counts) if link_node_counts else 0}; "
        "max wire supports="
        f"{max(wire_support_counts) if wire_support_counts else 0}; "
        "max lambda="
        f"{_fmt(max(finite_eigenvalues) if finite_eigenvalues else None)}; "
        "Phase30 status="
        f"{';'.join(phase30_statuses) if phase30_statuses else 'unknown'}."
    )


def _phase41_reference_load_review_summary(review: Any) -> str:
    rows = tuple(getattr(review, "rows", ()))
    no_axial = sum(
        1
        for row in rows
        if getattr(row, "axial_reference_load_status", "")
        == "no_axial_compression_reference"
    )
    support_opposes = sum(
        1
        for row in rows
        if getattr(row, "sign_convention_read", "")
        == "support_reaction_opposes_applied_fz"
    )
    implausible_lambda = sum(
        1
        for row in rows
        if getattr(row, "lambda_plausibility_status", "")
        == "implausibly_high_for_claim_margin"
    )
    return (
        "reference review status="
        f"{getattr(review, 'overall_status', 'unknown')}; "
        "rows="
        f"{int(getattr(review, 'row_count', len(rows)))}; "
        "not-rankable rows="
        f"{int(getattr(review, 'not_rankable_count', 0))}; "
        "balanced rows="
        f"{int(getattr(review, 'balanced_count', 0))}; "
        "no axial compression reference rows="
        f"{no_axial}; "
        "implausible lambda rows="
        f"{implausible_lambda}; "
        "support-opposes rows="
        f"{support_opposes}."
    )


def _phase41_mode_shape_review_summary(review: Any) -> str:
    rows = tuple(getattr(review, "rows", ()))
    spar_balances = [
        _optional_float(getattr(row, "spar_mean_participation_ratio", None))
        for row in rows
    ]
    tip_ratios = [
        _optional_float(getattr(row, "tip_to_max_ratio", None))
        for row in rows
    ]
    root_ratios = [
        _optional_float(getattr(row, "root_to_max_ratio", None))
        for row in rows
    ]
    finite_spar_balances = [value for value in spar_balances if value is not None]
    finite_tip_ratios = [value for value in tip_ratios if value is not None]
    finite_root_ratios = [value for value in root_ratios if value is not None]
    return (
        "mode shape review status="
        f"{getattr(review, 'overall_status', 'unknown')}; "
        "rows="
        f"{int(getattr(review, 'row_count', len(rows)))}; "
        "review-required rows="
        f"{int(getattr(review, 'review_required_count', 0))}; "
        "missing rows="
        f"{int(getattr(review, 'missing_count', 0))}; "
        "min spar balance="
        f"{_fmt(min(finite_spar_balances) if finite_spar_balances else None)}; "
        "max tip/max="
        f"{_fmt(max(finite_tip_ratios) if finite_tip_ratios else None)}; "
        "max root/max="
        f"{_fmt(max(finite_root_ratios) if finite_root_ratios else None)}."
    )


def _phase41_rib_spacing_link_review_summary(review: Any) -> str:
    rows = tuple(getattr(review, "rows", ()))
    subbays = [
        _optional_float(getattr(row, "max_model_link_subbay_m", None))
        for row in rows
    ]
    margins = [
        _optional_float(getattr(row, "link_spacing_margin_m", None))
        for row in rows
    ]
    station_deltas = [
        int(getattr(row, "station_count_delta", 0))
        for row in rows
        if getattr(row, "station_count_delta", None) is not None
    ]
    finite_subbays = [value for value in subbays if value is not None]
    finite_margins = [value for value in margins if value is not None]
    return (
        "rib spacing link review status="
        f"{getattr(review, 'overall_status', 'unknown')}; "
        "rows="
        f"{int(getattr(review, 'row_count', len(rows)))}; "
        "nominal spacing met rows="
        f"{int(getattr(review, 'nominal_spacing_met_count', 0))}; "
        "physical signoff rows="
        f"{int(getattr(review, 'physical_signoff_count', 0))}; "
        "max model subbay="
        f"{_fmt(max(finite_subbays) if finite_subbays else None)} m; "
        "min spacing margin="
        f"{_fmt(min(finite_margins) if finite_margins else None)} m; "
        "min station delta="
        f"{min(station_deltas) if station_deltas else 0}."
    )


def _existing_detail_allowable_evidence_triage_summary(key: str, triage: Any) -> str:
    rows = {
        str(getattr(row, "blocker_key", "")): row
        for row in getattr(triage, "rows", ())
    }
    row = rows.get(key)
    return (
        "existing detail allowable triage status="
        f"{getattr(triage, 'overall_status', 'unknown')}; "
        "rows="
        f"{int(getattr(triage, 'row_count', len(rows)))}; "
        "closing rows="
        f"{int(getattr(triage, 'closing_evidence_count', 0))}; "
        "row status="
        f"{getattr(row, 'status', 'missing') if row is not None else 'missing'}; "
        "closes margin="
        f"{bool(getattr(row, 'closes_engineering_margin', False)) if row is not None else False}; "
        "missing allowable rows="
        f"{int(getattr(row, 'missing_allowable_rows', 0)) if row is not None else 0}; "
        "station coverage gaps="
        f"{int(getattr(row, 'station_coverage_gap_rows', 0)) if row is not None else 0}."
    )


def _bracing_summary_for_key(key: str, bracing_audit: Any) -> str:
    rows = {str(row.variant_id): row for row in getattr(bracing_audit, "rows", ())}
    rear_soft = rows.get("rear_stiffness_5pct")
    dense_finite = rows.get("dense_finite_rib_surrogate")
    dense_rigid = rows.get("dense_rigid_links")
    if key == "rear_spar_stiffness" and rear_soft is not None:
        return (
            "rear_stiffness_5pct changed tip by "
            f"{_fmt(getattr(rear_soft, 'tip_main_delta_vs_baseline_pct', None))}% "
            "and spar-pair angle by "
            f"{_fmt(getattr(rear_soft, 'angle_delta_vs_baseline_deg', None))} deg."
        )
    if key == "rib_load_transfer" and dense_finite is not None:
        return (
            "dense_finite_rib_surrogate changed max vertical by "
            f"{_fmt(getattr(dense_finite, 'max_vertical_delta_vs_baseline_pct', None))}% "
            "with max link force "
            f"{_fmt(getattr(dense_finite, 'link_force_max_n', None))} N."
        )
    if key == "torsion_twist_coupling" and dense_finite is not None:
        return (
            "dense_finite_rib_surrogate changed spar-pair angle by "
            f"{_fmt(getattr(dense_finite, 'angle_delta_vs_baseline_deg', None))} deg."
        )
    if key == "failure_mode_ordering" and rear_soft is not None:
        return (
            "rear_stiffness_5pct and dense-link variants show bracing assumptions move global response; "
            "detail modes are listed as unranked while global bracing modes still lack sortable FEM evidence."
        )
    if dense_rigid is not None:
        return (
            "dense_rigid_links changed max vertical by "
            f"{_fmt(getattr(dense_rigid, 'max_vertical_delta_vs_baseline_pct', None))}%."
        )
    return "bracing sensitivity rows unavailable."


def _next_action_for_key(key: str) -> str:
    actions = {
        "rear_spar_stiffness": "Run rear-spar-on/off or finite-rib dual-spar FEM to quantify load sharing and lateral/torsional stiffness.",
        "rib_load_transfer": "Replace/report beside constraint-only links with finite rib stiffness plus rib shear/cap/bond/spar-attach allowables.",
        "wire_attach_local_load_path": "Create attach-ring/lug/insert/bond local FEM or hand margins using the Phase19 force vector.",
        "root_joint": "Size root fitting, clamp, bonded insert, bearing, and tube-wall load introduction against Phase19 root moment.",
        "torsion_twist_coupling": "Close an aeroelastic twist loop or torque-couple FEM before using twist as a pass/fail claim.",
        "wire_termination": "Apply termination efficiency and hardware allowable, not just cable-body tensile allowable.",
        "rib_spacing_assumption": "Prove physical rib/bracing station spacing and stiffness before using the 0.30 m local-buckling bay.",
        "tip_deflection_limit": "Keep 2.5 m as a design-validity/submission gate unless a separate aeroelastic requirement changes it.",
        "full_wing_global_buckling": "Review Phase41 mode shape, boundary conditions, reference-load physics, and mesh/link sensitivity before any 1.5G/1.75G global pass claim.",
        "failure_mode_ordering": "Re-rank with global bracing, joints, attachments, root fitting, and terminations included.",
    }
    return actions[key]


def _entry_map(entries: Any) -> dict[str, Any]:
    return {str(entry.key): entry for entry in entries}


def _assert_complete(items: tuple[StructuralClosureItem, ...]) -> None:
    keys = tuple(item.key for item in items)
    if keys != REQUIRED_STRUCTURAL_CLAIM_KEYS:
        raise RuntimeError(
            "Structural closure index key drift: "
            f"expected {REQUIRED_STRUCTURAL_CLAIM_KEYS!r}, got {keys!r}."
        )


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.4f}"


def _write_csv(path: Path, index: StructuralClosureIndex) -> Path:
    fields = [
        "key",
        "title",
        "status",
        "evidence_artifacts",
        "current_evidence",
        "remaining_blocker",
        "next_action",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for item in index.items:
            writer.writerow(asdict(item))
    return path


def _write_json(path: Path, index: StructuralClosureIndex) -> Path:
    path.write_text(json.dumps(asdict(index), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, index: StructuralClosureIndex) -> Path:
    lines = [
        "# Structural Closure Index",
        "",
        f"Candidate: `{index.candidate_id}`",
        f"Overall status: `{index.overall_status}`",
        "",
        "This is not a hardware signoff. It is a blocker map linking each requested issue to current evidence and the next engineering closure step.",
        "",
        "## Modeled Ordering",
        "",
        f"- current wire modeled first limiter: `{index.modeled_first_limiter_with_current_wire}`",
        f"- 6 kN wire-body modeled first limiter: `{index.modeled_first_limiter_with_6kn_wire}`",
        "",
        "## Index",
        "",
        "| item | status | evidence artifacts | remaining blocker | next action |",
        "|---|---|---|---|---|",
    ]
    for item in index.items:
        lines.append(
            f"| {item.title} | `{item.status}` | {item.evidence_artifacts} | "
            f"{item.remaining_blocker} | {item.next_action} |"
        )
    lines.extend(
        [
            "",
            "## Evidence Notes",
            "",
        ]
    )
    for item in index.items:
        lines.append(f"- **{item.title}**: {item.current_evidence}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    index = build_current_structural_closure_index()
    out_dir = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        _write_csv(out_dir / "structural_closure_index.csv", index),
        _write_json(out_dir / "structural_closure_index.json", index),
        _write_markdown(out_dir / "structural_closure_index.md", index),
    ]
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
