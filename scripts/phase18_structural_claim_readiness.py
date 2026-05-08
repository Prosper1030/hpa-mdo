#!/usr/bin/env python3
"""Generate structural claim-readiness guardrails for the fixed candidate."""
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.phase15_candidate_load_factor_buckling_check import (  # noqa: E402
    CandidateReference,
    load_current_candidate_reference,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase18_structural_claim_readiness"

REQUIRED_STRUCTURAL_CLAIM_KEYS: tuple[str, ...] = (
    "rear_spar_stiffness",
    "rib_load_transfer",
    "wire_attach_local_load_path",
    "root_joint",
    "torsion_twist_coupling",
    "wire_termination",
    "rib_spacing_assumption",
    "tip_deflection_limit",
    "full_wing_global_buckling",
    "failure_mode_ordering",
)


@dataclass(frozen=True)
class StructuralClaimReadinessItem:
    key: str
    title: str
    status: str
    current_evidence: str
    allowed_claim: str
    blocked_claim: str
    required_next_evidence: str
    engineering_note: str


@dataclass(frozen=True)
class StructuralClaimReadinessReview:
    candidate_id: str
    overall_verdict: str
    summary_counts: dict[str, int]
    modeled_first_limiter_with_current_wire: str
    modeled_first_limiter_with_6kn_wire: str
    tip_deflection_limit_load_factor: float
    current_wire_body_limit_load_factor: float
    wire6_body_limit_load_factor: float
    items: tuple[StructuralClaimReadinessItem, ...]


@dataclass(frozen=True)
class _Limiter:
    mode: str
    load_factor: float


def build_structural_claim_readiness(
    reference: CandidateReference,
    *,
    upgraded_wire_allowable_n: float = 6000.0,
) -> StructuralClaimReadinessReview:
    current_first = _first_modeled_limiter(reference, wire_allowable_n=reference.wire_allowable_n)
    wire6_first = _first_modeled_limiter(reference, wire_allowable_n=upgraded_wire_allowable_n)
    tip_limit_n = _tip_deflection_limit_load_factor(reference)
    current_wire_limit_n = _wire_body_limit_load_factor(
        reference,
        wire_allowable_n=reference.wire_allowable_n,
    )
    wire6_limit_n = _wire_body_limit_load_factor(reference, wire_allowable_n=upgraded_wire_allowable_n)

    items = (
        StructuralClaimReadinessItem(
            key="rear_spar_stiffness",
            title="Rear spar stiffness",
            status="unresolved_blocker",
            current_evidence=(
                "The internal dual-beam model has rear-spar geometry and stiffness terms, "
                "but the candidate shell buckling route is still main-spar-only."
            ),
            allowed_claim="Rear spar stiffness is represented in the beam-line screening model.",
            blocked_claim="Do not claim rear spar stiffness is FEM-proven for torsion or lateral bracing.",
            required_next_evidence=(
                "Dual-spar FEM or equivalent braced model with main/rear stiffness, rib links, "
                "and twist/deflection comparison."
            ),
            engineering_note="A rear beam in the math is not the same as a load-transferring rear spar in hardware.",
        ),
        StructuralClaimReadinessItem(
            key="rib_load_transfer",
            title="Rib load transfer",
            status="unresolved_blocker",
            current_evidence=(
                "Rib catalog, rib-bay surrogate, and link constraints exist, but they are "
                "surrogate/report-grade evidence rather than rib finite-element load transfer."
            ),
            allowed_claim="Rib spacing and shape-retention risk are reportable diagnostics.",
            blocked_claim="Do not claim ribs have proven main/rear spar bracing load transfer.",
            required_next_evidence=(
                "Finite-stiffness rib/link load-transfer model with link forces and rib/fitting allowables."
            ),
            engineering_note="A constraint can move force in a solver without proving the rib can carry it.",
        ),
        StructuralClaimReadinessItem(
            key="wire_attach_local_load_path",
            title="Wire attach local load path",
            status="unresolved_blocker",
            current_evidence=(
                "Wire force reaches the beam/shell as a node or smeared ring load; lug, bond, insert, "
                "bearing, and local tube-wall details are not modeled."
            ),
            allowed_claim="The beam-line wire force vector and cable-body tension are available.",
            blocked_claim="Do not claim the attach ring, bond, insert, clamp, or local wall passes.",
            required_next_evidence=(
                "Local attach-detail FEM or hand margins for bearing, bond shear, insert pullout, "
                "tube-wall crushing, and load introduction."
            ),
            engineering_note="A clean global reaction is only the beginning of an attach design.",
        ),
        StructuralClaimReadinessItem(
            key="root_joint",
            title="Root joint",
            status="unresolved_blocker",
            current_evidence=(
                "Root reaction and root bending moment are reported, but the root fitting, clamp, "
                "bonded joint, and insert have no local strength margin."
            ),
            allowed_claim="Root loads are known input loads for detail design.",
            blocked_claim="Do not claim root fitting, clamp, bonded joint, or insert strength passes.",
            required_next_evidence=(
                "Root fitting/clamp/bonded-insert detail FEM or classical margins using recovered "
                "forces and moments."
            ),
            engineering_note="The support reaction tells us what the joint must carry, not whether it can carry it.",
        ),
        StructuralClaimReadinessItem(
            key="torsion_twist_coupling",
            title="Torsion and twist coupling",
            status="bounded_internal_check",
            current_evidence=(
                f"Fixed-design twist utilization is {_utilization(reference.twist_max_deg, reference.twist_limit_deg):.3f}; "
                "this is an internal beam-line/twist-limit check, not aeroelastic twist signoff."
            ),
            allowed_claim="Modeled fixed-design twist is below the configured internal limit.",
            blocked_claim="Do not claim aeroelastic twist coupling or torsional stiffness signoff.",
            required_next_evidence=(
                "Dual-spar/rib torsion FEM or aeroelastic loop that compares twist, torque ownership, "
                "and link reactions under the selected load path."
            ),
            engineering_note="Local wall buckling can pass while torsional stiffness remains a design blocker.",
        ),
        StructuralClaimReadinessItem(
            key="wire_termination",
            title="Wire termination",
            status="unresolved_blocker",
            current_evidence=(
                "The current checks compare cable-body tension to a scalar modeled allowable; "
                "terminations, splices, bend radius, knots, pins, and anchors are not credited."
            ),
            allowed_claim="Modeled cable-body tension allowable can be checked.",
            blocked_claim="wire body allowable is not termination allowable; do not claim wire termination pass.",
            required_next_evidence=(
                "Selected hardware spec with minimum breaking load, termination efficiency, bend-radius, "
                "creep/UV/abrasion reductions, and attach/fuselage anchor margins."
            ),
            engineering_note="A 6 kN cable-body allowable does not automatically survive the end detail.",
        ),
        StructuralClaimReadinessItem(
            key="rib_spacing_assumption",
            title="Rib spacing assumption",
            status="conditional_assumption",
            current_evidence=(
                "The 0.30 m rib-bay local-wall coupon is meaningful only if physical ribs provide "
                "approximately that bracing length and load-transfer stiffness."
            ),
            allowed_claim="Local-wall coupon checks are conditional on the assumed rib-bay bracing length.",
            blocked_claim="Do not claim 0.30 m braced wall behavior until the real bracing path is proven.",
            required_next_evidence=(
                "Rib layout, attachment stiffness, and load-transfer margin showing an effective bay "
                "length close to the assumed coupon length."
            ),
            engineering_note="The nice local-wall number depends on a real structure creating that boundary condition.",
        ),
        StructuralClaimReadinessItem(
            key="tip_deflection_limit",
            title="Tip deflection limit",
            status="bounded_design_gate",
            current_evidence=(
                f"The configured tip deflection gate is reached at about n={tip_limit_n:.3f} "
                "in the fixed-design linear estimate."
            ),
            allowed_claim="The 2.5 m limit is a design-validity gate, not a rupture point.",
            blocked_claim="Do not claim relaxing the tip limit is acceptable for submission without revalidation.",
            required_next_evidence=(
                "Loaded-shape, aeroelastic, clearance, and load-path recheck for any relaxed submission limit."
            ),
            engineering_note="Exploration can cross a validity gate; submission numbers should not quietly do that.",
        ),
        StructuralClaimReadinessItem(
            key="full_wing_global_buckling",
            title="Full-wing global buckling",
            status="unresolved_blocker",
            current_evidence=(
                "Current local wall checks and the main-spar shell coupon do not include full dual-spar, "
                "rib, joint, and wire-attach bracing."
            ),
            allowed_claim="Local/internal wall-buckling checks can be reported with their assumptions.",
            blocked_claim="Do not claim `1.5G / 1.75G full-wing pass` or full-wing global buckling pass.",
            required_next_evidence=(
                "Full-wing or representative dual-spar/rib/wire global buckling FEM with credible boundary "
                "conditions and mesh/solver checks."
            ),
            engineering_note="A local shell coupon passing is not a global wing stability proof.",
        ),
        StructuralClaimReadinessItem(
            key="failure_mode_ordering",
            title="Failure mode ordering",
            status="unresolved_blocker",
            current_evidence=(
                f"With current wire allowable the modeled first limiter is {current_first.mode} at n={current_first.load_factor:.3f}; "
                f"with 6 kN cable-body allowable it becomes {wire6_first.mode} at n={wire6_first.load_factor:.3f}. "
                "This ordering excludes global bracing and joint/detail failures."
            ),
            allowed_claim="The current fixed-design beam-line failure ordering can be reported as preliminary.",
            blocked_claim="Do not claim the true aircraft first failure mode is known.",
            required_next_evidence=(
                "Add global bracing, root joint, wire attach, termination, and rib load-transfer checks to "
                "the same ordering table."
            ),
            engineering_note="Once the wire body is no longer first, hardware and global modes are exactly where reality hides.",
        ),
    )
    _assert_complete(items)
    return StructuralClaimReadinessReview(
        candidate_id=reference.candidate_id,
        overall_verdict="not_ready_for_full_wing_or_hardware_signoff",
        summary_counts=_summary_counts(items),
        modeled_first_limiter_with_current_wire=current_first.mode,
        modeled_first_limiter_with_6kn_wire=wire6_first.mode,
        tip_deflection_limit_load_factor=tip_limit_n,
        current_wire_body_limit_load_factor=current_wire_limit_n,
        wire6_body_limit_load_factor=wire6_limit_n,
        items=items,
    )


def write_structural_claim_readiness_package(
    out_dir: Path,
    reference: CandidateReference,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    review = build_structural_claim_readiness(reference)
    outputs = [
        _write_csv(out_dir / "structural_claim_readiness.csv", review),
        _write_json(out_dir / "structural_claim_readiness.json", review),
        _write_markdown(out_dir / "structural_claim_readiness.md", review),
    ]
    return outputs


def _first_modeled_limiter(
    reference: CandidateReference,
    *,
    wire_allowable_n: float,
) -> _Limiter:
    candidates = [
        _Limiter(
            "cfrp_global_bending_stress",
            _inverse_utilization_load_factor(reference.reference_load_factor, reference.failure_index),
        ),
        _Limiter(
            "local_shell_buckling_estimate",
            _inverse_utilization_load_factor(reference.reference_load_factor, reference.buckling_index),
        ),
        _Limiter("tip_deflection", _tip_deflection_limit_load_factor(reference)),
        _Limiter("torsion_twist", _twist_limit_load_factor(reference)),
        _Limiter("wire_tension_body_allowable", _wire_body_limit_load_factor(reference, wire_allowable_n=wire_allowable_n)),
    ]
    finite = [candidate for candidate in candidates if candidate.load_factor == candidate.load_factor]
    return min(finite, key=lambda candidate: candidate.load_factor)


def _inverse_utilization_load_factor(reference_load_factor: float, index: float) -> float:
    utilization = max(0.0, 1.0 + float(index))
    if utilization <= 0.0:
        return float("inf")
    return float(reference_load_factor) / utilization


def _tip_deflection_limit_load_factor(reference: CandidateReference) -> float:
    if reference.tip_deflection_m <= 0.0:
        return float("inf")
    return (
        float(reference.reference_load_factor)
        * float(reference.tip_deflection_limit_m)
        / float(reference.tip_deflection_m)
    )


def _twist_limit_load_factor(reference: CandidateReference) -> float:
    if reference.twist_max_deg <= 0.0:
        return float("inf")
    return (
        float(reference.reference_load_factor)
        * float(reference.twist_limit_deg)
        / abs(float(reference.twist_max_deg))
    )


def _wire_body_limit_load_factor(
    reference: CandidateReference,
    *,
    wire_allowable_n: float,
) -> float:
    if reference.wire_tension_n <= 0.0:
        return float("inf")
    return (
        float(reference.reference_load_factor)
        * float(wire_allowable_n)
        / float(reference.wire_tension_n)
    )


def _utilization(value: float, limit: float) -> float:
    if limit <= 0.0:
        return float("inf")
    return abs(float(value)) / float(limit)


def _summary_counts(items: tuple[StructuralClaimReadinessItem, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return counts


def _assert_complete(items: tuple[StructuralClaimReadinessItem, ...]) -> None:
    keys = tuple(item.key for item in items)
    if keys != REQUIRED_STRUCTURAL_CLAIM_KEYS:
        raise RuntimeError(
            "Structural claim readiness matrix key drift: "
            f"expected {REQUIRED_STRUCTURAL_CLAIM_KEYS!r}, got {keys!r}."
        )


def _write_csv(path: Path, review: StructuralClaimReadinessReview) -> Path:
    fields = [
        "key",
        "title",
        "status",
        "current_evidence",
        "allowed_claim",
        "blocked_claim",
        "required_next_evidence",
        "engineering_note",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for item in review.items:
            writer.writerow(asdict(item))
    return path


def _write_json(path: Path, review: StructuralClaimReadinessReview) -> Path:
    payload = asdict(review)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _write_markdown(path: Path, review: StructuralClaimReadinessReview) -> Path:
    lines = [
        "# Structural Claim Readiness",
        "",
        f"Candidate: `{review.candidate_id}`",
        f"Overall verdict: `{review.overall_verdict}`",
        "",
        "## Claim Boundary",
        "",
        "- Do not claim `1.5G / 1.75G full-wing pass` from the current local/internal checks.",
        "- Modeled cable-body margin is useful, but wire body allowable is not termination allowable.",
        "- Local wall buckling checks are conditional on the assumed rib-bay bracing length and do not close global buckling.",
        "- Tip deflection is a design-validity gate, not a material rupture point.",
        "",
        "## Modeled Ordering",
        "",
        f"- Current wire allowable first limiter: `{review.modeled_first_limiter_with_current_wire}`.",
        f"- 6 kN cable-body allowable first limiter: `{review.modeled_first_limiter_with_6kn_wire}`.",
        f"- Tip deflection gate load factor: `n={review.tip_deflection_limit_load_factor:.3f}`.",
        f"- Current wire-body allowable load factor: `n={review.current_wire_body_limit_load_factor:.3f}`.",
        f"- 6 kN wire-body allowable load factor: `n={review.wire6_body_limit_load_factor:.3f}`.",
        "",
        "## Matrix",
        "",
        "| item | status | allowed claim | blocked claim | next evidence |",
        "|---|---|---|---|---|",
    ]
    for item in review.items:
        lines.append(
            f"| {item.title} | `{item.status}` | {item.allowed_claim} | "
            f"{item.blocked_claim} | {item.required_next_evidence} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Read",
            "",
            "The current package is useful for beam-line screening and for deciding what to analyze next. "
            "It is not yet a hardware release package. The next credible engineering step is a "
            "dual-spar/rib/wire/root-detail load-transfer model that turns these blockers into real margins.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    reference = load_current_candidate_reference()
    outputs = write_structural_claim_readiness_package(args.output_dir, reference)
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
