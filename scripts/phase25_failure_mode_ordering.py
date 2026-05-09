#!/usr/bin/env python3
"""Separate ranked internal limiters from unranked real-structure failure modes."""
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
    load_current_candidate_reference,
)
from scripts.phase18_structural_claim_readiness import (  # noqa: E402
    build_structural_claim_readiness,
)
from scripts.phase19_local_load_path_ledger import (  # noqa: E402
    build_local_load_path_ledger,
    load_current_spar_rows,
    load_current_wire_rigging,
)
from scripts.phase23_detail_sizing_requirements import (  # noqa: E402
    build_detail_sizing_requirements,
)
from scripts.phase24_rib_spacing_requirements import (  # noqa: E402
    build_rib_spacing_requirements,
)
from scripts.phase27_detail_margin_inputs import (  # noqa: E402
    build_detail_margin_check,
)
from scripts.phase28_rib_bracing_margin_inputs import (  # noqa: E402
    build_rib_bracing_margin_check,
)
from scripts.phase29_torsion_twist_closure_inputs import (  # noqa: E402
    build_current_torsion_twist_closure_check,
)
from scripts.phase30_full_wing_buckling_closure_inputs import (  # noqa: E402
    build_full_wing_buckling_closure_check,
)
from scripts.phase31_tip_deflection_revalidation_inputs import (  # noqa: E402
    build_tip_deflection_revalidation_check,
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
    build_current_torsion_twist_screening,
)
from scripts.phase38_full_wing_buckling_claim_boundary import (  # noqa: E402
    build_current_full_wing_buckling_claim_boundary,
)
from scripts.phase39_tip_deflection_claim_boundary import (  # noqa: E402
    build_current_tip_deflection_claim_boundary,
)
from scripts.phase22_bracing_sensitivity import (  # noqa: E402
    build_bracing_sensitivity_audit,
    build_current_candidate_model,
)
from scripts.phase41_braced_subassembly_fem_evidence import (  # noqa: E402
    load_current_braced_subassembly_fem_evidence,
    phase30_closure_inputs_from_evidence,
)
from scripts.phase42_phase41_reference_load_review import (  # noqa: E402
    build_current_phase41_reference_load_review,
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


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase25_failure_mode_ordering"


@dataclass(frozen=True)
class FailureModeOrderingRow:
    mode_key: str
    title: str
    order_bucket: str
    rank_index: int | None
    load_factor: float | None
    status: str
    basis: str
    required_allowable_load_n: float | None
    required_allowable_moment_n_m: float | None
    required_minimum_breaking_load_n: float | None
    body_allowable_margin_n: float | None
    evidence: str
    next_evidence: str


@dataclass(frozen=True)
class FailureModeOrdering:
    candidate_id: str
    overall_status: str
    modeled_first_limiter_with_current_wire: str
    modeled_first_limiter_with_6kn_wire: str
    known_unranked_mode_count: int
    rows: tuple[FailureModeOrderingRow, ...]


def build_failure_mode_ordering(
    claim_review: Any,
    *,
    detail_requirements: Any | None = None,
    rib_spacing_requirements: Any | None = None,
    detail_margin_check: Any | None = None,
    local_detail_subcomponent_check: Any | None = None,
    wire_attach_load_decomposition: Any | None = None,
    root_joint_load_envelope: Any | None = None,
    wire_termination_efficiency_sensitivity: Any | None = None,
    local_detail_criticality_ordering: Any | None = None,
    rib_bracing_margin_check: Any | None = None,
    torsion_twist_closure_check: Any | None = None,
    torsion_twist_screening: Any | None = None,
    full_wing_buckling_closure_check: Any | None = None,
    full_wing_buckling_claim_boundary: Any | None = None,
    braced_subassembly_fem_evidence: Any | None = None,
    phase41_reference_load_review: Any | None = None,
    phase41_mode_shape_review: Any | None = None,
    phase41_rib_spacing_link_review: Any | None = None,
    tip_deflection_revalidation_check: Any | None = None,
    tip_deflection_claim_boundary: Any | None = None,
) -> FailureModeOrdering:
    ranked = _ranked_internal_rows(
        claim_review,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
        tip_deflection_claim_boundary=tip_deflection_claim_boundary,
    )
    unranked = _unranked_real_structure_rows(
        detail_requirements=detail_requirements,
        rib_spacing_requirements=rib_spacing_requirements,
        detail_margin_check=detail_margin_check,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        local_detail_criticality_ordering=local_detail_criticality_ordering,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        torsion_twist_screening=torsion_twist_screening,
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
        braced_subassembly_fem_evidence=braced_subassembly_fem_evidence,
        phase41_reference_load_review=phase41_reference_load_review,
        phase41_mode_shape_review=phase41_mode_shape_review,
        phase41_rib_spacing_link_review=phase41_rib_spacing_link_review,
    )
    rows = (*ranked, *unranked)
    return FailureModeOrdering(
        candidate_id=str(claim_review.candidate_id),
        overall_status="true_failure_order_not_closed",
        modeled_first_limiter_with_current_wire=str(
            claim_review.modeled_first_limiter_with_current_wire
        ),
        modeled_first_limiter_with_6kn_wire=str(claim_review.modeled_first_limiter_with_6kn_wire),
        known_unranked_mode_count=sum(
            1 for row in rows if row.order_bucket == "unranked_real_structure_mode"
        ),
        rows=rows,
    )


def write_failure_mode_ordering_package(
    out_dir: Path,
    claim_review: Any,
    *,
    detail_requirements: Any | None = None,
    rib_spacing_requirements: Any | None = None,
    detail_margin_check: Any | None = None,
    local_detail_subcomponent_check: Any | None = None,
    wire_attach_load_decomposition: Any | None = None,
    root_joint_load_envelope: Any | None = None,
    wire_termination_efficiency_sensitivity: Any | None = None,
    local_detail_criticality_ordering: Any | None = None,
    rib_bracing_margin_check: Any | None = None,
    torsion_twist_closure_check: Any | None = None,
    torsion_twist_screening: Any | None = None,
    full_wing_buckling_closure_check: Any | None = None,
    full_wing_buckling_claim_boundary: Any | None = None,
    braced_subassembly_fem_evidence: Any | None = None,
    phase41_reference_load_review: Any | None = None,
    phase41_mode_shape_review: Any | None = None,
    phase41_rib_spacing_link_review: Any | None = None,
    tip_deflection_revalidation_check: Any | None = None,
    tip_deflection_claim_boundary: Any | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ordering = build_failure_mode_ordering(
        claim_review,
        detail_requirements=detail_requirements,
        rib_spacing_requirements=rib_spacing_requirements,
        detail_margin_check=detail_margin_check,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        local_detail_criticality_ordering=local_detail_criticality_ordering,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        torsion_twist_screening=torsion_twist_screening,
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
        braced_subassembly_fem_evidence=braced_subassembly_fem_evidence,
        phase41_reference_load_review=phase41_reference_load_review,
        phase41_mode_shape_review=phase41_mode_shape_review,
        phase41_rib_spacing_link_review=phase41_rib_spacing_link_review,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
        tip_deflection_claim_boundary=tip_deflection_claim_boundary,
    )
    outputs = [
        _write_csv(out_dir / "failure_mode_ordering.csv", ordering),
        _write_json(out_dir / "failure_mode_ordering.json", ordering),
        _write_markdown(out_dir / "failure_mode_ordering.md", ordering),
    ]
    return outputs


def build_current_failure_mode_ordering() -> FailureModeOrdering:
    reference = load_current_candidate_reference()
    claim_review = build_structural_claim_readiness(reference)
    local_ledger = build_local_load_path_ledger(
        reference,
        wire_rigging=load_current_wire_rigging(),
        spar_rows=load_current_spar_rows(),
    )
    detail_requirements = build_detail_sizing_requirements(local_ledger)
    rib_spacing_requirements = build_rib_spacing_requirements(
        reference.candidate_id,
        spar_rows=load_current_spar_rows(),
        wire_rigging=load_current_wire_rigging(),
    )
    candidate_model = build_current_candidate_model()
    bracing_audit = build_bracing_sensitivity_audit(reference.candidate_id, candidate_model)
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
    wire_termination_efficiency_sensitivity = build_wire_termination_efficiency_sensitivity(
        detail_requirements
    )
    local_detail_criticality_ordering = build_local_detail_criticality_ordering(
        reference.candidate_id,
        detail_requirements=detail_requirements,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
    )
    rib_bracing_margin_check = build_rib_bracing_margin_check(
        rib_spacing_requirements,
        bracing_audit,
        rib_allowables=[],
    )
    braced_subassembly_fem_evidence = load_current_braced_subassembly_fem_evidence()
    full_wing_buckling_closure_check = build_full_wing_buckling_closure_check(
        reference.candidate_id,
        closure_inputs=phase30_closure_inputs_from_evidence(
            braced_subassembly_fem_evidence
        ),
    )
    phase41_reference_load_review = build_current_phase41_reference_load_review()
    phase41_mode_shape_review = build_current_phase41_mode_shape_review()
    phase41_rib_spacing_link_review = build_current_phase41_rib_spacing_link_review()
    return build_failure_mode_ordering(
        claim_review,
        detail_requirements=detail_requirements,
        rib_spacing_requirements=rib_spacing_requirements,
        detail_margin_check=detail_margin_check,
        local_detail_subcomponent_check=local_detail_subcomponent_check,
        wire_attach_load_decomposition=wire_attach_load_decomposition,
        root_joint_load_envelope=root_joint_load_envelope,
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        local_detail_criticality_ordering=local_detail_criticality_ordering,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=build_current_torsion_twist_closure_check(),
        torsion_twist_screening=build_current_torsion_twist_screening(),
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=build_current_full_wing_buckling_claim_boundary(),
        braced_subassembly_fem_evidence=braced_subassembly_fem_evidence,
        phase41_reference_load_review=phase41_reference_load_review,
        phase41_mode_shape_review=phase41_mode_shape_review,
        phase41_rib_spacing_link_review=phase41_rib_spacing_link_review,
        tip_deflection_revalidation_check=build_tip_deflection_revalidation_check(
            reference,
            revalidation_inputs=[],
        ),
        tip_deflection_claim_boundary=build_current_tip_deflection_claim_boundary(),
    )


def _ranked_internal_rows(
    claim_review: Any,
    *,
    tip_deflection_revalidation_check: Any | None,
    tip_deflection_claim_boundary: Any | None,
) -> tuple[FailureModeOrderingRow, ...]:
    raw = (
        _row(
            mode_key="wire_tension_body_allowable_current",
            title="Wire body tension allowable, current cable",
            order_bucket="ranked_internal_mode",
            load_factor=_float_or_none(claim_review.current_wire_body_limit_load_factor),
            status="modeled_limiter_current_body_allowable",
            basis="beam-line cable-body scalar allowable; termination excluded",
            evidence=(
                "current modeled wire-body limit factor="
                f"{_fmt(_float_or_none(claim_review.current_wire_body_limit_load_factor))}"
            ),
            next_evidence="Replace body-only allowable with selected cable plus termination/anchor allowable.",
        ),
        _row(
            mode_key="tip_deflection_limit",
            title="Tip deflection design-validity gate",
            order_bucket="ranked_internal_mode",
            load_factor=_float_or_none(claim_review.tip_deflection_limit_load_factor),
            status="design_validity_gate_not_fracture",
            basis="configured loaded-shape/design-validity limit; not a rupture mode",
            evidence=(
                "tip-deflection gate factor="
                f"{_fmt(_float_or_none(claim_review.tip_deflection_limit_load_factor))}"
                f"; {_tip_gate_evidence(tip_deflection_revalidation_check)}; "
                f"{_tip_deflection_claim_boundary_evidence(tip_deflection_claim_boundary)}"
            ),
            next_evidence="Keep as submission validity gate unless an aeroelastic/clearance requirement changes.",
        ),
        _row(
            mode_key="wire_tension_body_allowable_6kn",
            title="Wire body tension allowable, 6 kN cable",
            order_bucket="ranked_internal_mode",
            load_factor=_float_or_none(claim_review.wire6_body_limit_load_factor),
            status="modeled_limiter_upgraded_body_allowable",
            basis="beam-line cable-body scalar allowable upgraded to 6 kN; termination excluded",
            evidence=(
                "6 kN wire-body limit factor="
                f"{_fmt(_float_or_none(claim_review.wire6_body_limit_load_factor))}"
            ),
            next_evidence="Do not use this as termination proof; add actual end-detail allowable.",
        ),
    )
    sorted_rows = sorted(
        raw,
        key=lambda row: float("inf") if row.load_factor is None else row.load_factor,
    )
    return tuple(
        FailureModeOrderingRow(
            **{
                **asdict(row),
                "rank_index": idx,
            }
        )
        for idx, row in enumerate(sorted_rows, start=1)
    )


def _unranked_real_structure_rows(
    *,
    detail_requirements: Any | None,
    rib_spacing_requirements: Any | None,
    detail_margin_check: Any | None,
    local_detail_subcomponent_check: Any | None,
    wire_attach_load_decomposition: Any | None,
    root_joint_load_envelope: Any | None,
    wire_termination_efficiency_sensitivity: Any | None,
    local_detail_criticality_ordering: Any | None,
    rib_bracing_margin_check: Any | None,
    torsion_twist_closure_check: Any | None,
    torsion_twist_screening: Any | None,
    full_wing_buckling_closure_check: Any | None,
    full_wing_buckling_claim_boundary: Any | None,
    braced_subassembly_fem_evidence: Any | None,
    phase41_reference_load_review: Any | None,
    phase41_mode_shape_review: Any | None,
    phase41_rib_spacing_link_review: Any | None,
) -> tuple[FailureModeOrderingRow, ...]:
    details = _detail_entries(detail_requirements)
    detail_margins = _detail_entries(detail_margin_check)
    wire_attach = details.get("wire_attach_local_load_path")
    root_joint = details.get("root_joint")
    wire_termination = details.get("wire_termination")
    return (
        _detail_row(
            "wire_attach_local_load_path",
            "Wire attach local load path",
            wire_attach,
            detail_margin=detail_margins.get("wire_attach_local_load_path"),
            local_detail_subcomponent_check=local_detail_subcomponent_check,
            local_detail_criticality_ordering=local_detail_criticality_ordering,
            extra_evidence=_wire_attach_load_decomposition_evidence(
                wire_attach_load_decomposition
            ),
            next_evidence="Local lug/ring/insert/bond/tube-wall bearing and crushing margins.",
        ),
        _detail_row(
            "root_joint",
            "Root fitting / clamp / bonded insert",
            root_joint,
            detail_margin=detail_margins.get("root_joint"),
            local_detail_subcomponent_check=local_detail_subcomponent_check,
            local_detail_criticality_ordering=local_detail_criticality_ordering,
            extra_evidence=_root_joint_load_envelope_evidence(root_joint_load_envelope),
            next_evidence="Root fitting, clamp, bonded insert, bearing, and tube-wall load-introduction margins.",
        ),
        _detail_row(
            "wire_termination",
            "Wire termination / end fitting",
            wire_termination,
            detail_margin=detail_margins.get("wire_termination"),
            local_detail_subcomponent_check=local_detail_subcomponent_check,
            local_detail_criticality_ordering=local_detail_criticality_ordering,
            extra_evidence=_wire_termination_efficiency_evidence(
                wire_termination_efficiency_sensitivity
            ),
            next_evidence="Selected termination hardware/process with efficiency, bend, anchor, and creep/abrasion reductions.",
        ),
        _row(
            mode_key="rib_load_transfer",
            title="Rib load transfer and bracing",
            order_bucket="unranked_real_structure_mode",
            load_factor=None,
            status="unranked_stiffness_and_allowable_missing",
            basis="layout and surrogate link evidence only; no rib hardware allowable",
            evidence=(
                f"{_rib_spacing_evidence(rib_spacing_requirements)} "
                f"{_rib_bracing_margin_evidence(rib_bracing_margin_check)}"
                f" {_phase41_rib_spacing_link_review_evidence(phase41_rib_spacing_link_review)}"
            ),
            next_evidence="Finite-stiffness rib/link model plus rib shear, cap, bond, and spar-attach allowables.",
        ),
        _row(
            mode_key="rear_spar_global_bracing",
            title="Rear spar global bracing participation",
            order_bucket="unranked_real_structure_mode",
            load_factor=None,
            status="unranked_global_role_fem_missing",
            basis="rear section stiffness quantified, but global bracing role is not signed off",
            evidence="rear spar stiffness changes beam response, but no dual-spar braced FEM pass exists.",
            next_evidence="Rear-spar-on/off or finite-rib dual-spar FEM with load sharing and deformation comparison.",
        ),
        _row(
            mode_key="torsion_twist_coupling",
            title="Torsion / aeroelastic twist coupling",
            order_bucket="unranked_real_structure_mode",
            load_factor=None,
            status="unranked_aeroelastic_loop_missing",
            basis="fixed-design internal twist check only",
            evidence=(
                "local wall and beam twist checks do not close aeroelastic torque/twist coupling. "
                f"{_closure_evidence(torsion_twist_closure_check)} "
                f"{_torsion_twist_screening_evidence(torsion_twist_screening)}"
            ),
            next_evidence="Torque-couple FEM or aeroelastic twist loop with load redistribution.",
        ),
        _row(
            mode_key="full_wing_global_buckling",
            title="Full-wing global buckling",
            order_bucket="unranked_real_structure_mode",
            load_factor=None,
            status=_full_wing_global_buckling_status(
                braced_subassembly_fem_evidence,
                phase41_reference_load_review,
                phase41_mode_shape_review,
            ),
            basis="local/internal buckling checks only",
            evidence=(
                "no full-wing dual-spar/rib/wire global buckling eigen/FEM result is present. "
                f"{_closure_evidence(full_wing_buckling_closure_check)}"
                f" {_full_wing_buckling_claim_boundary_evidence(full_wing_buckling_claim_boundary)}"
                f" {_braced_subassembly_fem_evidence(braced_subassembly_fem_evidence)}"
                f" {_phase41_reference_load_review_evidence(phase41_reference_load_review)}"
                f" {_phase41_mode_shape_review_evidence(phase41_mode_shape_review)}"
            ),
            next_evidence=_full_wing_global_buckling_next_evidence(
                phase41_reference_load_review,
                phase41_mode_shape_review,
            ),
        ),
    )


def _detail_row(
    mode_key: str,
    title: str,
    detail: Any | None,
    *,
    detail_margin: Any | None,
    local_detail_subcomponent_check: Any | None,
    local_detail_criticality_ordering: Any | None,
    extra_evidence: str,
    next_evidence: str,
) -> FailureModeOrderingRow:
    subcomponent_status = _local_detail_subcomponent_status(mode_key, local_detail_subcomponent_check)
    return _row(
        mode_key=mode_key,
        title=title,
        order_bucket="unranked_real_structure_mode",
        load_factor=None,
        status=subcomponent_status,
        basis="service load converted to requirement; no selected hardware allowable",
        required_allowable_load_n=_attr_float(detail, "required_allowable_load_n"),
        required_allowable_moment_n_m=_attr_float(detail, "required_allowable_moment_n_m"),
        required_minimum_breaking_load_n=_attr_float(detail, "required_minimum_breaking_load_n"),
        body_allowable_margin_n=_attr_float(detail, "body_allowable_margin_n"),
        evidence=(
            f"{_detail_evidence(detail)} {_detail_margin_evidence(detail_margin)} "
            f"{_local_detail_subcomponent_evidence(mode_key, local_detail_subcomponent_check)} "
            f"{_local_detail_criticality_evidence(mode_key, local_detail_criticality_ordering)} "
            f"{extra_evidence}"
        ),
        next_evidence=next_evidence,
    )


def _full_wing_global_buckling_status(
    braced_subassembly_fem_evidence: Any | None,
    phase41_reference_load_review: Any | None,
    phase41_mode_shape_review: Any | None,
) -> str:
    if _phase41_reference_not_rankable_count(phase41_reference_load_review) > 0:
        return "unranked_global_buckling_reference_load_formulation_not_rankable"
    if _braced_reference_load_review_count(braced_subassembly_fem_evidence) > 0:
        return "unranked_global_buckling_reference_load_review_required"
    if _phase41_mode_shape_review_required(phase41_mode_shape_review):
        return "unranked_global_buckling_mode_screened_manual_mesh_review_required"
    return "unranked_global_buckling_fem_missing"


def _full_wing_global_buckling_next_evidence(
    phase41_reference_load_review: Any | None,
    phase41_mode_shape_review: Any | None,
) -> str:
    if _phase41_reference_not_rankable_count(phase41_reference_load_review) > 0:
        return (
            "Replace Phase41's transverse lift/moment reference with a qualified "
            "global/prestress buckling load case, then repeat mode review, "
            "mesh/link sensitivity, and braced/full-wing promotion."
        )
    if _phase41_mode_shape_review_required(phase41_mode_shape_review):
        return (
            "Complete manual mode identity review, boundary-condition review, "
            "mesh/link sensitivity, and then promote a qualified braced/full-wing row."
        )
    return (
        "Resolve Phase41 reference-load/sign convention, mode review, "
        "mesh/link sensitivity, and then promote a qualified braced/full-wing row."
    )


def _braced_subassembly_fem_evidence(evidence: Any | None) -> str:
    if evidence is None:
        return "braced subassembly evidence is not available."
    rows = tuple(getattr(evidence, "rows", ()))
    phase30_statuses = sorted(
        {
            str(getattr(row, "phase30_closure_status", "")).strip()
            for row in rows
            if str(getattr(row, "phase30_closure_status", "")).strip()
        }
    )
    eigenvalues = [
        _attr_float(row, "first_eigen_multiplier")
        for row in rows
        if _attr_float(row, "first_eigen_multiplier") is not None
    ]
    return (
        "braced subassembly status="
        f"{getattr(evidence, 'overall_status', 'unknown')}; "
        "solver ran="
        f"{int(getattr(evidence, 'solver_ran_count', 0))}; "
        "mode reviewed="
        f"{int(getattr(evidence, 'mode_reviewed_count', 0))}; "
        "claim coverage="
        f"{getattr(evidence, 'claim_load_factor_coverage', 'unknown')}; "
        "reference-load review rows="
        f"{_braced_reference_load_review_count(evidence)}; "
        "max lambda="
        f"{_fmt(max(eigenvalues) if eigenvalues else None)}; "
        "Phase30 status="
        f"{';'.join(phase30_statuses) if phase30_statuses else 'unknown'}."
    )


def _braced_reference_load_review_count(evidence: Any | None) -> int:
    if evidence is None:
        return 0
    return sum(
        1
        for row in getattr(evidence, "rows", ())
        if getattr(row, "reference_load_status", "")
        == "unphysical_or_load_sign_review_required"
    )


def _phase41_reference_load_review_evidence(review: Any | None) -> str:
    if review is None:
        return "phase41 reference load review is not available."
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
        "phase41 reference review status="
        f"{getattr(review, 'overall_status', 'unknown')}; "
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


def _phase41_mode_shape_review_evidence(review: Any | None) -> str:
    if review is None:
        return "phase41 mode shape review is not available."
    rows = tuple(getattr(review, "rows", ()))
    spar_balances = [
        _attr_float(row, "spar_mean_participation_ratio")
        for row in rows
        if _attr_float(row, "spar_mean_participation_ratio") is not None
    ]
    tip_ratios = [
        _attr_float(row, "tip_to_max_ratio")
        for row in rows
        if _attr_float(row, "tip_to_max_ratio") is not None
    ]
    root_ratios = [
        _attr_float(row, "root_to_max_ratio")
        for row in rows
        if _attr_float(row, "root_to_max_ratio") is not None
    ]
    return (
        "phase41 mode shape review status="
        f"{getattr(review, 'overall_status', 'unknown')}; "
        "review-required rows="
        f"{int(getattr(review, 'review_required_count', 0))}; "
        "missing rows="
        f"{int(getattr(review, 'missing_count', 0))}; "
        "min spar balance="
        f"{_fmt(min(spar_balances) if spar_balances else None)}; "
        "max tip/max="
        f"{_fmt(max(tip_ratios) if tip_ratios else None)}; "
        "max root/max="
        f"{_fmt(max(root_ratios) if root_ratios else None)}."
    )


def _phase41_mode_shape_review_required(review: Any | None) -> bool:
    return (
        review is not None
        and getattr(review, "overall_status", "")
        == "phase41_mode_shape_engineering_review_required"
        and int(getattr(review, "missing_count", 0)) == 0
    )


def _phase41_rib_spacing_link_review_evidence(review: Any | None) -> str:
    if review is None:
        return "phase41 rib spacing link review is not available."
    rows = tuple(getattr(review, "rows", ()))
    subbays = [
        _attr_float(row, "max_model_link_subbay_m")
        for row in rows
        if _attr_float(row, "max_model_link_subbay_m") is not None
    ]
    margins = [
        _attr_float(row, "link_spacing_margin_m")
        for row in rows
        if _attr_float(row, "link_spacing_margin_m") is not None
    ]
    return (
        "rib spacing link review status="
        f"{getattr(review, 'overall_status', 'unknown')}; "
        "nominal spacing met rows="
        f"{int(getattr(review, 'nominal_spacing_met_count', 0))}; "
        "physical signoff rows="
        f"{int(getattr(review, 'physical_signoff_count', 0))}; "
        "max model subbay="
        f"{_fmt(max(subbays) if subbays else None)} m; "
        "min spacing margin="
        f"{_fmt(min(margins) if margins else None)} m."
    )


def _phase41_reference_not_rankable_count(review: Any | None) -> int:
    if review is None:
        return 0
    return int(getattr(review, "not_rankable_count", 0))


def _row(
    *,
    mode_key: str,
    title: str,
    order_bucket: str,
    load_factor: float | None,
    status: str,
    basis: str,
    evidence: str,
    next_evidence: str,
    rank_index: int | None = None,
    required_allowable_load_n: float | None = None,
    required_allowable_moment_n_m: float | None = None,
    required_minimum_breaking_load_n: float | None = None,
    body_allowable_margin_n: float | None = None,
) -> FailureModeOrderingRow:
    return FailureModeOrderingRow(
        mode_key=mode_key,
        title=title,
        order_bucket=order_bucket,
        rank_index=rank_index,
        load_factor=load_factor,
        status=status,
        basis=basis,
        required_allowable_load_n=required_allowable_load_n,
        required_allowable_moment_n_m=required_allowable_moment_n_m,
        required_minimum_breaking_load_n=required_minimum_breaking_load_n,
        body_allowable_margin_n=body_allowable_margin_n,
        evidence=evidence,
        next_evidence=next_evidence,
    )


def _detail_entries(detail_requirements: Any | None) -> dict[str, Any]:
    if detail_requirements is None:
        return {}
    return {
        str(row.key): row
        for row in getattr(detail_requirements, "rows", ())
    }


def _detail_evidence(detail: Any | None) -> str:
    if detail is None:
        return "detail sizing requirement is not available."
    parts = [
        "required load="
        f"{_fmt(_attr_float(detail, 'required_allowable_load_n'))} N",
    ]
    moment = _attr_float(detail, "required_allowable_moment_n_m")
    if moment is not None:
        parts.append(f"required moment={_fmt(moment)} N*m")
    mbl = _attr_float(detail, "required_minimum_breaking_load_n")
    if mbl is not None:
        parts.append(f"required MBL={_fmt(mbl)} N")
    body_margin = _attr_float(detail, "body_allowable_margin_n")
    if body_margin is not None:
        parts.append(f"body margin={_fmt(body_margin)} N")
    return "; ".join(parts) + "."


def _rib_spacing_evidence(requirements: Any | None) -> str:
    if requirements is None:
        return "rib spacing requirement is not available."
    return (
        "added stations="
        f"{int(getattr(requirements, 'total_added_bracing_stations', 0))}; "
        "recommended stations="
        f"{int(getattr(requirements, 'recommended_station_count', 0))}; "
        "max recommended subbay="
        f"{_fmt(_attr_float(requirements, 'max_recommended_subbay_m'))} m."
    )


def _detail_margin_evidence(detail_margin: Any | None) -> str:
    if detail_margin is None:
        return "hardware margin input is not available."
    return (
        "hardware status="
        f"{getattr(detail_margin, 'status', 'unknown')}; "
        "load margin="
        f"{_fmt(_attr_float(detail_margin, 'load_margin_n'))} N; "
        "moment margin="
        f"{_fmt(_attr_float(detail_margin, 'moment_margin_n_m'))} N*m; "
        "MBL margin="
        f"{_fmt(_attr_float(detail_margin, 'mbl_margin_n'))} N."
    )


def _local_detail_subcomponent_status(parent_key: str, check: Any | None) -> str:
    if check is None:
        return "unranked_detail_allowable_missing"
    rows = [
        row
        for row in getattr(check, "rows", ())
        if getattr(row, "parent_key", "") == parent_key
    ]
    if any(getattr(row, "status", "") == "margin_negative" for row in rows):
        return "unranked_detail_subcomponent_margin_negative"
    if any(
        getattr(row, "status", "") == "subcomponent_moment_allowable_missing"
        for row in rows
    ):
        return "unranked_detail_subcomponent_moment_allowable_missing"
    if any(getattr(row, "status", "") == "subcomponent_allowable_missing" for row in rows):
        return "unranked_detail_subcomponent_allowable_missing"
    if any(getattr(row, "status", "") == "subcomponent_traceability_missing" for row in rows):
        return "unranked_detail_subcomponent_traceability_missing"
    if rows and all(
        getattr(row, "status", "") == "margin_positive_input_check_only" for row in rows
    ):
        return "unranked_detail_subcomponent_inputs_positive_not_fem_signoff"
    return "unranked_detail_allowable_missing"


def _local_detail_subcomponent_evidence(parent_key: str, check: Any | None) -> str:
    if check is None:
        return "local detail subcomponent check is not available."
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
        "local subcomponents="
        f"{len(rows)}; "
        "local subcomponents missing="
        f"{missing}; "
        "local moment allowable gaps="
        f"{moment_missing}; "
        "local subcomponent negative margins="
        f"{negative}; "
        "local subcomponent traceability gaps="
        f"{traceability_gap}; "
        "local subcomponent positive input rows="
        f"{positive}; "
        "worst local margin="
        f"{_fmt(min(worst_values) if worst_values else None)}."
    )


def _local_detail_criticality_evidence(parent_key: str, ordering: Any | None) -> str:
    if ordering is None:
        return "local detail criticality ordering is not available."
    rows = {
        str(getattr(row, "blocker_key", "")): row
        for row in getattr(ordering, "rows", ())
    }
    row = rows.get(parent_key)
    if row is None:
        return (
            "local detail criticality status="
            f"{getattr(ordering, 'overall_status', 'unknown')}; "
            "local detail priority row=missing."
        )
    boundary = str(getattr(row, "ordering_boundary", "unknown"))
    return (
        "local detail criticality status="
        f"{getattr(ordering, 'overall_status', 'unknown')}; "
        "local detail priority rank="
        f"{int(getattr(row, 'work_priority_rank', 0))}; "
        "governing screen="
        f"{getattr(row, 'governing_screen', 'unknown')}; "
        "severity N-equivalent="
        f"{_fmt(_attr_float(row, 'design_severity_n_equivalent'))}; "
        "priority status="
        f"{getattr(row, 'status', 'unknown')}; "
        "closes margin="
        f"{bool(getattr(row, 'closes_engineering_margin', False))}; "
        "boundary="
        f"{boundary}; "
        "work priority only, not failure-load rank."
    )


def _wire_attach_load_decomposition_evidence(decomposition: Any | None) -> str:
    if decomposition is None:
        return "wire attach load decomposition is not available."
    rows = tuple(getattr(decomposition, "rows", ()))
    spanwise_design = _component_design_load_max(rows, "spanwise_y")
    transverse_design = _component_design_load_max(rows, "transverse_xz")
    return (
        "attach decomposition status="
        f"{getattr(decomposition, 'overall_status', 'unknown')}; "
        "attach max resultant design="
        f"{_fmt(_attr_float(decomposition, 'max_resultant_design_load_n'))} N; "
        "attach spanwise design="
        f"{_fmt(spanwise_design)} N; "
        "attach transverse design="
        f"{_fmt(transverse_design)} N."
    )


def _component_design_load_max(rows: tuple[Any, ...], component_key: str) -> float | None:
    values = [
        _attr_float(row, "design_load_n")
        for row in rows
        if str(getattr(row, "component_key", "")) == component_key
    ]
    finite_values = [value for value in values if value is not None]
    return max(finite_values) if finite_values else None


def _root_joint_load_envelope_evidence(envelope: Any | None) -> str:
    if envelope is None:
        return "root joint load envelope is not available."
    rows = tuple(getattr(envelope, "rows", ()))
    max_couple = _max_root_couple_row(rows)
    return (
        "root envelope status="
        f"{getattr(envelope, 'overall_status', 'unknown')}; "
        "root design force="
        f"{_fmt(_attr_float(envelope, 'design_root_force_n'))} N; "
        "root design moment="
        f"{_fmt(_attr_float(envelope, 'design_root_bending_moment_n_m'))} N*m; "
        "force-only misleading="
        f"{getattr(envelope, 'force_only_check_is_misleading', 'unknown')}; "
        "root max couple force="
        f"{_fmt(max_couple[0])} N; "
        "root max couple case="
        f"{max_couple[1]}."
    )


def _max_root_couple_row(rows: tuple[Any, ...]) -> tuple[float | None, str]:
    values = [
        (_attr_float(row, "required_couple_force_n"), str(getattr(row, "load_case_key", "unknown")))
        for row in rows
        if _attr_float(row, "required_couple_force_n") is not None
    ]
    return max(values, key=lambda value: value[0] or float("-inf")) if values else (None, "n/a")


def _wire_termination_efficiency_evidence(sensitivity: Any | None) -> str:
    if sensitivity is None:
        return "wire termination efficiency sensitivity is not available."
    rows = {float(row.termination_efficiency): row for row in getattr(sensitivity, "rows", ())}
    eta_060 = rows.get(0.6)
    eta_080 = rows.get(0.8)
    return (
        "termination efficiency status="
        f"{getattr(sensitivity, 'overall_status', 'unknown')}; "
        "termination body margin="
        f"{_fmt(_attr_float(sensitivity, 'body_allowable_margin_n'))} N; "
        "termination eta 0.60 MBL="
        f"{_fmt(_attr_float(eta_060, 'required_minimum_breaking_load_n') if eta_060 is not None else None)} N; "
        "termination eta 0.80 MBL="
        f"{_fmt(_attr_float(eta_080, 'required_minimum_breaking_load_n') if eta_080 is not None else None)} N."
    )


def _rib_bracing_margin_evidence(check: Any | None) -> str:
    if check is None:
        return "rib bracing margin input is not available."
    rows = tuple(getattr(check, "rows", ()))
    missing = sum(1 for row in rows if getattr(row, "status", "") == "rib_allowable_missing")
    negative = sum(1 for row in rows if getattr(row, "status", "") == "margin_negative")
    traceability_gap = sum(1 for row in rows if getattr(row, "status", "") == "rib_traceability_missing")
    station_coverage_gap = sum(
        1 for row in rows if getattr(row, "status", "") == "rib_station_coverage_missing"
    )
    return (
        "required link force="
        f"{_fmt(_attr_float(check, 'required_link_force_n'))} N; "
        "rib allowables missing="
        f"{missing}; "
        "negative rib margins="
        f"{negative}; "
        "rib traceability gaps="
        f"{traceability_gap}; "
        "rib station coverage gaps="
        f"{station_coverage_gap}."
    )


def _closure_evidence(check: Any | None) -> str:
    if check is None:
        return "closure input is not available."
    rows = tuple(getattr(check, "rows", ()))
    first = rows[0] if rows else None
    parts = [
        "closure status="
        f"{getattr(first, 'status', 'missing') if first is not None else 'missing'}",
        f"overall={getattr(check, 'overall_status', 'unknown')}",
    ]
    missing_claims = getattr(check, "missing_required_claim_load_factors", None)
    if missing_claims is not None:
        parts.append(f"missing claim n={missing_claims}")
    return "; ".join(parts) + "."


def _torsion_twist_screening_evidence(screening: Any | None) -> str:
    if screening is None:
        return "torsion/twist screening is not available."
    return (
        "screening status="
        f"{getattr(screening, 'overall_status', 'unknown')}; "
        "internal equivalent twist="
        f"{_fmt(_attr_float(screening, 'internal_equivalent_twist_deg'))} deg; "
        "spar-pair angle="
        f"{_fmt(_attr_float(screening, 'max_spar_pair_line_angle_delta_deg'))} deg; "
        "dense finite rib angle delta="
        f"{_fmt(_attr_float(screening, 'dense_finite_rib_angle_delta_deg'))} deg; "
        "rear-soft angle delta="
        f"{_fmt(_attr_float(screening, 'rear_soft_angle_delta_deg'))} deg; "
        "accepted methods="
        f"{'; '.join(str(method) for method in getattr(screening, 'accepted_closure_methods', ()))}."
    )


def _tip_gate_evidence(check: Any | None) -> str:
    if check is None:
        return "tip gate revalidation input is not available"
    rows = tuple(getattr(check, "rows", ()))
    first = rows[0] if rows else None
    return (
        "gate status="
        f"{getattr(first, 'status', 'missing') if first is not None else 'missing'}; "
        "proposed raw limit="
        f"{_fmt(_attr_float(first, 'proposed_raw_tip_limit_m') if first is not None else None)} m; "
        "overall="
        f"{getattr(check, 'overall_status', 'unknown')}"
    )


def _tip_deflection_claim_boundary_evidence(boundary: Any | None) -> str:
    if boundary is None:
        return "tip-deflection claim boundary is not available."
    rows = {str(row.policy_key): row for row in getattr(boundary, "rows", ())}
    submission = rows.get("submission_relaxation")
    exploration = rows.get("exploration_relaxation")
    return (
        "claim boundary status="
        f"{getattr(boundary, 'overall_status', 'unknown')}; "
        "raw gate="
        f"{_fmt(_attr_float(boundary, 'current_raw_tip_limit_m'))} m; "
        "exploration policy="
        f"{getattr(exploration, 'status', 'unknown') if exploration is not None else 'unknown'}; "
        "submission policy="
        f"{getattr(submission, 'status', 'unknown') if submission is not None else 'unknown'}."
    )


def _full_wing_buckling_claim_boundary_evidence(boundary: Any | None) -> str:
    if boundary is None:
        return "full-wing buckling claim boundary is not available."
    rows = {float(row.claim_load_factor): row for row in getattr(boundary, "rows", ())}
    row_15 = rows.get(1.5)
    row_175 = rows.get(1.75)
    return (
        "claim boundary status="
        f"{getattr(boundary, 'overall_status', 'unknown')}; "
        "1.5G local wall util="
        f"{_fmt(_attr_float(row_15, 'local_wall_buckling_utilization') if row_15 is not None else None)}; "
        "1.75G local wall util="
        f"{_fmt(_attr_float(row_175, 'local_wall_buckling_utilization') if row_175 is not None else None)}; "
        "blocked statement="
        f"{getattr(row_175, 'blocked_statement', 'unknown') if row_175 is not None else 'unknown'}"
    )


def _attr_float(obj: Any | None, name: str) -> float | None:
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value is None:
        return None
    return float(value)


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def _write_csv(path: Path, ordering: FailureModeOrdering) -> Path:
    fields = list(asdict(ordering.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in ordering.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, ordering: FailureModeOrdering) -> Path:
    path.write_text(
        json.dumps(asdict(ordering), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, ordering: FailureModeOrdering) -> Path:
    ranked = [row for row in ordering.rows if row.order_bucket == "ranked_internal_mode"]
    unranked = [
        row for row in ordering.rows if row.order_bucket == "unranked_real_structure_mode"
    ]
    lines = [
        "# Failure Mode Ordering",
        "",
        f"Candidate: `{ordering.candidate_id}`",
        f"Overall status: `{ordering.overall_status}`",
        "",
        "The true failure order is not closed. Ranked rows are internal modeled limiters only; unranked rows are real-structure modes without the FEM or hardware allowable needed for ordering.",
        "",
        "## Modeled First Limiters",
        "",
        f"- current wire-body allowable: `{ordering.modeled_first_limiter_with_current_wire}`",
        f"- 6 kN wire-body allowable: `{ordering.modeled_first_limiter_with_6kn_wire}`",
        f"- unranked real-structure modes: `{ordering.known_unranked_mode_count}`",
        "",
        "## Ranked Internal Modes",
        "",
        "| rank | mode | n | status | basis | evidence |",
        "|---:|---|---:|---|---|---|",
    ]
    for row in ranked:
        lines.append(
            f"| {row.rank_index} | {row.title} | {_fmt(row.load_factor)} | "
            f"`{row.status}` | {row.basis} | {row.evidence} |"
        )
    lines.extend(
        [
            "",
            "## Unranked Real-Structure Modes",
            "",
            "| mode | status | evidence | next evidence |",
            "|---|---|---|---|",
        ]
    )
    for row in unranked:
        lines.append(
            f"| {row.title} | `{row.status}` | {row.evidence} | {row.next_evidence} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    ordering = build_current_failure_mode_ordering()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        _write_csv(args.output_dir / "failure_mode_ordering.csv", ordering),
        _write_json(args.output_dir / "failure_mode_ordering.json", ordering),
        _write_markdown(args.output_dir / "failure_mode_ordering.md", ordering),
    ]
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
