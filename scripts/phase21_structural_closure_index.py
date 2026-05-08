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
    wire_termination_efficiency_sensitivity: Any | None = None,
    rib_spacing_requirements: Any | None = None,
    rib_bracing_margin_check: Any | None = None,
    torsion_twist_closure_check: Any | None = None,
    torsion_twist_screening: Any | None = None,
    full_wing_buckling_closure_check: Any | None = None,
    full_wing_buckling_claim_boundary: Any | None = None,
    tip_deflection_revalidation_check: Any | None = None,
    tip_deflection_claim_boundary: Any | None = None,
    failure_mode_ordering: Any | None = None,
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
            wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
            rib_spacing_requirements=rib_spacing_requirements,
            rib_bracing_margin_check=rib_bracing_margin_check,
            torsion_twist_closure_check=torsion_twist_closure_check,
            torsion_twist_screening=torsion_twist_screening,
            full_wing_buckling_closure_check=full_wing_buckling_closure_check,
            full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
            tip_deflection_revalidation_check=tip_deflection_revalidation_check,
            tip_deflection_claim_boundary=tip_deflection_claim_boundary,
            failure_mode_ordering=failure_mode_ordering,
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
    wire_termination_efficiency_sensitivity: Any | None = None,
    rib_spacing_requirements: Any | None = None,
    rib_bracing_margin_check: Any | None = None,
    torsion_twist_closure_check: Any | None = None,
    torsion_twist_screening: Any | None = None,
    full_wing_buckling_closure_check: Any | None = None,
    full_wing_buckling_claim_boundary: Any | None = None,
    tip_deflection_revalidation_check: Any | None = None,
    tip_deflection_claim_boundary: Any | None = None,
    failure_mode_ordering: Any | None = None,
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
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        rib_spacing_requirements=rib_spacing_requirements,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        torsion_twist_screening=torsion_twist_screening,
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
        tip_deflection_claim_boundary=tip_deflection_claim_boundary,
        failure_mode_ordering=failure_mode_ordering,
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
    wire_termination_efficiency_sensitivity = build_wire_termination_efficiency_sensitivity(
        detail_requirements
    )
    rib_spacing_requirements = build_rib_spacing_requirements(
        reference.candidate_id,
        spar_rows=load_current_spar_rows(),
        wire_rigging=load_current_wire_rigging(),
    )
    failure_mode_ordering = build_failure_mode_ordering(
        review,
        detail_requirements=detail_requirements,
        rib_spacing_requirements=rib_spacing_requirements,
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
    full_wing_buckling_closure_check = build_full_wing_buckling_closure_check(
        reference.candidate_id,
        closure_inputs=[],
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
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        rib_spacing_requirements=rib_spacing_requirements,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        torsion_twist_screening=torsion_twist_screening,
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
        tip_deflection_claim_boundary=tip_deflection_claim_boundary,
        failure_mode_ordering=failure_mode_ordering,
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
    wire_termination_efficiency_sensitivity: Any | None,
    rib_spacing_requirements: Any | None,
    rib_bracing_margin_check: Any | None,
    torsion_twist_closure_check: Any | None,
    torsion_twist_screening: Any | None,
    full_wing_buckling_closure_check: Any | None,
    full_wing_buckling_claim_boundary: Any | None,
    tip_deflection_revalidation_check: Any | None,
    tip_deflection_claim_boundary: Any | None,
    failure_mode_ordering: Any | None,
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
        wire_termination_efficiency_sensitivity,
        rib_spacing_requirements,
        rib_bracing_margin_check,
        torsion_twist_closure_check,
        torsion_twist_screening,
        full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary,
        tip_deflection_revalidation_check,
        tip_deflection_claim_boundary,
        failure_mode_ordering,
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
        wire_termination_efficiency_sensitivity=wire_termination_efficiency_sensitivity,
        rib_spacing_requirements=rib_spacing_requirements,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        torsion_twist_screening=torsion_twist_screening,
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        full_wing_buckling_claim_boundary=full_wing_buckling_claim_boundary,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
        tip_deflection_claim_boundary=tip_deflection_claim_boundary,
        failure_mode_ordering=failure_mode_ordering,
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
    wire_termination_efficiency_sensitivity: Any | None,
    rib_spacing_requirements: Any | None,
    rib_bracing_margin_check: Any | None,
    torsion_twist_closure_check: Any | None,
    torsion_twist_screening: Any | None,
    full_wing_buckling_closure_check: Any | None,
    full_wing_buckling_claim_boundary: Any | None,
    tip_deflection_revalidation_check: Any | None,
    tip_deflection_claim_boundary: Any | None,
    failure_mode_ordering: Any | None,
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
    if wire_termination_efficiency_sensitivity is not None and key == "wire_termination":
        artifacts.append("Phase36 wire_termination_efficiency_sensitivity")
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
    wire_termination_efficiency_sensitivity: Any | None,
    rib_spacing_requirements: Any | None,
    rib_bracing_margin_check: Any | None,
    torsion_twist_closure_check: Any | None,
    torsion_twist_screening: Any | None,
    full_wing_buckling_closure_check: Any | None,
    full_wing_buckling_claim_boundary: Any | None,
    tip_deflection_revalidation_check: Any | None,
    tip_deflection_claim_boundary: Any | None,
    failure_mode_ordering: Any | None,
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
    if wire_termination_efficiency_sensitivity is not None and key == "wire_termination":
        parts.append(
            "Phase36: "
            f"{_wire_termination_efficiency_summary(wire_termination_efficiency_sensitivity)}"
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
    rows = {str(row.component_key): row for row in getattr(decomposition, "rows", ())}
    spanwise = rows.get("spanwise_y")
    transverse = rows.get("transverse_xz")
    vertical = rows.get("vertical_z")
    return (
        "overall="
        f"{getattr(decomposition, 'overall_status', 'unknown')}; "
        "max resultant design="
        f"{_fmt(getattr(decomposition, 'max_resultant_design_load_n', None))} N; "
        "spanwise design="
        f"{_fmt(getattr(spanwise, 'design_load_n', None) if spanwise is not None else None)} N; "
        "transverse design="
        f"{_fmt(getattr(transverse, 'design_load_n', None) if transverse is not None else None)} N; "
        "vertical design="
        f"{_fmt(getattr(vertical, 'design_load_n', None) if vertical is not None else None)} N."
    )


def _root_joint_load_envelope_summary(envelope: Any) -> str:
    rows = {str(row.load_case_key): row for row in getattr(envelope, "rows", ())}
    couple_010 = rows.get("moment_couple_arm_0p100m")
    return (
        "overall="
        f"{getattr(envelope, 'overall_status', 'unknown')}; "
        "design force="
        f"{_fmt(getattr(envelope, 'design_root_force_n', None))} N; "
        "design moment="
        f"{_fmt(getattr(envelope, 'design_root_bending_moment_n_m', None))} N*m; "
        "force-only misleading="
        f"{getattr(envelope, 'force_only_check_is_misleading', 'unknown')}; "
        "0.10 m couple force="
        f"{_fmt(getattr(couple_010, 'required_couple_force_n', None) if couple_010 is not None else None)} N."
    )


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
    return (
        "status="
        f"{getattr(ordering, 'overall_status', 'unknown')}; "
        "unranked modes="
        f"{int(getattr(ordering, 'known_unranked_mode_count', 0))}; "
        "current wire first="
        f"{getattr(ordering, 'modeled_first_limiter_with_current_wire', 'unknown')}; "
        "6 kN wire first="
        f"{getattr(ordering, 'modeled_first_limiter_with_6kn_wire', 'unknown')}."
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
        "full_wing_global_buckling": "Run a full-wing or credible braced subassembly buckling route before any 1.5G/1.75G global pass claim.",
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
