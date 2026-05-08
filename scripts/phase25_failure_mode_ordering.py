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
    build_current_full_wing_buckling_closure_check,
)
from scripts.phase31_tip_deflection_revalidation_inputs import (  # noqa: E402
    build_tip_deflection_revalidation_check,
)
from scripts.phase22_bracing_sensitivity import (  # noqa: E402
    build_bracing_sensitivity_audit,
    build_current_candidate_model,
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
    rib_bracing_margin_check: Any | None = None,
    torsion_twist_closure_check: Any | None = None,
    full_wing_buckling_closure_check: Any | None = None,
    tip_deflection_revalidation_check: Any | None = None,
) -> FailureModeOrdering:
    ranked = _ranked_internal_rows(
        claim_review,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
    )
    unranked = _unranked_real_structure_rows(
        detail_requirements=detail_requirements,
        rib_spacing_requirements=rib_spacing_requirements,
        detail_margin_check=detail_margin_check,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
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
    rib_bracing_margin_check: Any | None = None,
    torsion_twist_closure_check: Any | None = None,
    full_wing_buckling_closure_check: Any | None = None,
    tip_deflection_revalidation_check: Any | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ordering = build_failure_mode_ordering(
        claim_review,
        detail_requirements=detail_requirements,
        rib_spacing_requirements=rib_spacing_requirements,
        detail_margin_check=detail_margin_check,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=torsion_twist_closure_check,
        full_wing_buckling_closure_check=full_wing_buckling_closure_check,
        tip_deflection_revalidation_check=tip_deflection_revalidation_check,
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
    rib_bracing_margin_check = build_rib_bracing_margin_check(
        rib_spacing_requirements,
        bracing_audit,
        rib_allowables=[],
    )
    return build_failure_mode_ordering(
        claim_review,
        detail_requirements=detail_requirements,
        rib_spacing_requirements=rib_spacing_requirements,
        detail_margin_check=detail_margin_check,
        rib_bracing_margin_check=rib_bracing_margin_check,
        torsion_twist_closure_check=build_current_torsion_twist_closure_check(),
        full_wing_buckling_closure_check=build_current_full_wing_buckling_closure_check(),
        tip_deflection_revalidation_check=build_tip_deflection_revalidation_check(
            reference,
            revalidation_inputs=[],
        ),
    )


def _ranked_internal_rows(
    claim_review: Any,
    *,
    tip_deflection_revalidation_check: Any | None,
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
                f"; {_tip_gate_evidence(tip_deflection_revalidation_check)}"
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
    rib_bracing_margin_check: Any | None,
    torsion_twist_closure_check: Any | None,
    full_wing_buckling_closure_check: Any | None,
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
            next_evidence="Local lug/ring/insert/bond/tube-wall bearing and crushing margins.",
        ),
        _detail_row(
            "root_joint",
            "Root fitting / clamp / bonded insert",
            root_joint,
            detail_margin=detail_margins.get("root_joint"),
            next_evidence="Root fitting, clamp, bonded insert, bearing, and tube-wall load-introduction margins.",
        ),
        _detail_row(
            "wire_termination",
            "Wire termination / end fitting",
            wire_termination,
            detail_margin=detail_margins.get("wire_termination"),
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
                f"{_closure_evidence(torsion_twist_closure_check)}"
            ),
            next_evidence="Torque-couple FEM or aeroelastic twist loop with load redistribution.",
        ),
        _row(
            mode_key="full_wing_global_buckling",
            title="Full-wing global buckling",
            order_bucket="unranked_real_structure_mode",
            load_factor=None,
            status="unranked_global_buckling_fem_missing",
            basis="local/internal buckling checks only",
            evidence=(
                "no full-wing dual-spar/rib/wire global buckling eigen/FEM result is present. "
                f"{_closure_evidence(full_wing_buckling_closure_check)}"
            ),
            next_evidence="Full-wing or credible braced-subassembly buckling FEM with mesh and boundary checks.",
        ),
    )


def _detail_row(
    mode_key: str,
    title: str,
    detail: Any | None,
    *,
    detail_margin: Any | None,
    next_evidence: str,
) -> FailureModeOrderingRow:
    return _row(
        mode_key=mode_key,
        title=title,
        order_bucket="unranked_real_structure_mode",
        load_factor=None,
        status="unranked_detail_allowable_missing",
        basis="service load converted to requirement; no selected hardware allowable",
        required_allowable_load_n=_attr_float(detail, "required_allowable_load_n"),
        required_allowable_moment_n_m=_attr_float(detail, "required_allowable_moment_n_m"),
        required_minimum_breaking_load_n=_attr_float(detail, "required_minimum_breaking_load_n"),
        body_allowable_margin_n=_attr_float(detail, "body_allowable_margin_n"),
        evidence=f"{_detail_evidence(detail)} {_detail_margin_evidence(detail_margin)}",
        next_evidence=next_evidence,
    )


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


def _rib_bracing_margin_evidence(check: Any | None) -> str:
    if check is None:
        return "rib bracing margin input is not available."
    rows = tuple(getattr(check, "rows", ()))
    missing = sum(1 for row in rows if getattr(row, "status", "") == "rib_allowable_missing")
    negative = sum(1 for row in rows if getattr(row, "status", "") == "margin_negative")
    return (
        "required link force="
        f"{_fmt(_attr_float(check, 'required_link_force_n'))} N; "
        "rib allowables missing="
        f"{missing}; "
        "negative rib margins="
        f"{negative}."
    )


def _closure_evidence(check: Any | None) -> str:
    if check is None:
        return "closure input is not available."
    rows = tuple(getattr(check, "rows", ()))
    first = rows[0] if rows else None
    return (
        "closure status="
        f"{getattr(first, 'status', 'missing') if first is not None else 'missing'}; "
        "overall="
        f"{getattr(check, 'overall_status', 'unknown')}."
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
