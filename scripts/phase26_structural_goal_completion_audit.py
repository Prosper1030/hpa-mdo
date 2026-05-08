#!/usr/bin/env python3
"""Audit the structural-signoff goal against concrete artifacts and remaining blockers."""
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

from scripts.phase18_structural_claim_readiness import REQUIRED_STRUCTURAL_CLAIM_KEYS  # noqa: E402
from scripts.phase21_structural_closure_index import (  # noqa: E402
    build_current_structural_closure_index,
)
from scripts.phase25_failure_mode_ordering import (  # noqa: E402
    build_current_failure_mode_ordering,
)


DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "phase26_structural_goal_completion_audit"


@dataclass(frozen=True)
class StructuralGoalCompletionRow:
    key: str
    prompt_requirement: str
    completion_status: str
    evidence_strength: str
    evidence_artifacts: str
    evidence_summary: str
    completion_blocker: str
    next_verification_step: str


@dataclass(frozen=True)
class StructuralGoalCompletionAudit:
    candidate_id: str
    overall_goal_status: str
    total_requirements: int
    closed_requirement_count: int
    blocked_requirement_count: int
    rows: tuple[StructuralGoalCompletionRow, ...]


PROMPT_REQUIREMENTS: dict[str, str] = {
    "rear_spar_stiffness": "rear spar stiffness must be proven as effective global bracing, not just present as a section property",
    "rib_load_transfer": "ribs must be shown to connect main and rear spars into an effective braced structure",
    "wire_attach_local_load_path": "wire tension must be traced through attach ring, bond, insert, and local tube wall",
    "root_joint": "root fitting, clamp, bonded joint, and insert strength must have FEM or engineering margin",
    "torsion_twist_coupling": "local buckling pass must not be treated as torsional stiffness or aeroelastic twist pass",
    "wire_termination": "wire end fittings and terminations must have allowables separate from cable-body tensile allowable",
    "rib_spacing_assumption": "0.30 m rib-bay local-wall assumption must be backed by physical bracing length and stiffness",
    "tip_deflection_limit": "2.5 m raw tip limit must remain a design-validity/submission gate, not a fracture point",
    "full_wing_global_buckling": "1.5G / 1.75G full-wing pass cannot be claimed without global buckling evidence",
    "failure_mode_ordering": "after 6 kN wire body, the next true failure mode must be ranked with global and detail modes included",
}

EVIDENCE_STRENGTH_BY_KEY: dict[str, str] = {
    "rear_spar_stiffness": "report_only_sensitivity",
    "rib_load_transfer": "surrogate_and_layout_only",
    "wire_attach_local_load_path": "requirements_only",
    "root_joint": "requirements_only",
    "torsion_twist_coupling": "report_only_sensitivity",
    "wire_termination": "requirements_only",
    "rib_spacing_assumption": "layout_requirement_only",
    "tip_deflection_limit": "claim_guardrail",
    "full_wing_global_buckling": "claim_guardrail",
    "failure_mode_ordering": "detail_modes_listed_but_unranked",
}

COMPLETION_BLOCKER_BY_KEY: dict[str, str] = {
    "rear_spar_stiffness": "dual_spar_finite_rib_global_fem_missing",
    "rib_load_transfer": "finite_rib_stiffness_and_allowable_missing",
    "wire_attach_local_load_path": "attach_detail_fem_or_hand_margin_missing",
    "root_joint": "root_fitting_clamp_bonded_insert_margin_missing",
    "torsion_twist_coupling": "aeroelastic_twist_or_torque_couple_fem_missing",
    "wire_termination": "selected_termination_hardware_allowable_missing",
    "rib_spacing_assumption": "physical_rib_stiffness_and_attachment_margin_missing",
    "tip_deflection_limit": "relaxed_submission_gate_revalidation_missing",
    "full_wing_global_buckling": "full_wing_or_braced_subassembly_buckling_fem_missing",
    "failure_mode_ordering": "unranked_real_structure_modes_still_missing",
}


def build_structural_goal_completion_audit(
    closure_index: Any,
    *,
    failure_mode_ordering: Any | None = None,
) -> StructuralGoalCompletionAudit:
    items = {str(item.key): item for item in getattr(closure_index, "items", ())}
    rows = tuple(
        _build_row(
            key,
            items[key],
            failure_mode_ordering=failure_mode_ordering,
        )
        for key in REQUIRED_STRUCTURAL_CLAIM_KEYS
    )
    closed_count = sum(1 for row in rows if row.completion_status == "closed")
    blocked_count = len(rows) - closed_count
    return StructuralGoalCompletionAudit(
        candidate_id=str(closure_index.candidate_id),
        overall_goal_status=(
            "complete" if blocked_count == 0 else "not_complete_engineering_signoff_missing"
        ),
        total_requirements=len(rows),
        closed_requirement_count=closed_count,
        blocked_requirement_count=blocked_count,
        rows=rows,
    )


def write_structural_goal_completion_audit_package(
    out_dir: Path,
    closure_index: Any,
    *,
    failure_mode_ordering: Any | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = build_structural_goal_completion_audit(
        closure_index,
        failure_mode_ordering=failure_mode_ordering,
    )
    outputs = [
        _write_csv(out_dir / "structural_goal_completion_audit.csv", audit),
        _write_json(out_dir / "structural_goal_completion_audit.json", audit),
        _write_markdown(out_dir / "structural_goal_completion_audit.md", audit),
    ]
    return outputs


def build_current_structural_goal_completion_audit() -> StructuralGoalCompletionAudit:
    closure_index = build_current_structural_closure_index()
    failure_mode_ordering = build_current_failure_mode_ordering()
    return build_structural_goal_completion_audit(
        closure_index,
        failure_mode_ordering=failure_mode_ordering,
    )


def _build_row(
    key: str,
    item: Any,
    *,
    failure_mode_ordering: Any | None,
) -> StructuralGoalCompletionRow:
    evidence_summary = str(item.current_evidence)
    if key == "failure_mode_ordering" and failure_mode_ordering is not None:
        evidence_summary = (
            f"{evidence_summary} unranked real-structure modes="
            f"{int(getattr(failure_mode_ordering, 'known_unranked_mode_count', 0))}."
        )
    return StructuralGoalCompletionRow(
        key=key,
        prompt_requirement=PROMPT_REQUIREMENTS[key],
        completion_status="blocked",
        evidence_strength=EVIDENCE_STRENGTH_BY_KEY[key],
        evidence_artifacts=str(item.evidence_artifacts),
        evidence_summary=evidence_summary,
        completion_blocker=COMPLETION_BLOCKER_BY_KEY[key],
        next_verification_step=str(item.next_action),
    )


def _write_csv(path: Path, audit: StructuralGoalCompletionAudit) -> Path:
    fields = list(asdict(audit.rows[0]).keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in audit.rows:
            writer.writerow(asdict(row))
    return path


def _write_json(path: Path, audit: StructuralGoalCompletionAudit) -> Path:
    path.write_text(
        json.dumps(asdict(audit), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_markdown(path: Path, audit: StructuralGoalCompletionAudit) -> Path:
    lines = [
        "# Structural Goal Completion Audit",
        "",
        f"Candidate: `{audit.candidate_id}`",
        f"Overall goal status: `{audit.overall_goal_status}`",
        "",
        "The goal is not complete. Current artifacts provide guardrails, requirements, and report-only sensitivities, but they do not replace hardware margins or full-wing FEM evidence.",
        "",
        "Do not mark the goal complete until every row below is closed with direct verification evidence.",
        "",
        "## Summary",
        "",
        f"- total requirements: `{audit.total_requirements}`",
        f"- closed requirements: `{audit.closed_requirement_count}`",
        f"- blocked requirements: `{audit.blocked_requirement_count}`",
        "",
        "## Checklist",
        "",
        "| requirement | status | evidence strength | artifacts | blocker |",
        "|---|---|---|---|---|",
    ]
    for row in audit.rows:
        lines.append(
            f"| {row.prompt_requirement} | `{row.completion_status}` | "
            f"`{row.evidence_strength}` | {row.evidence_artifacts} | "
            f"{row.completion_blocker} |"
        )
    lines.extend(
        [
            "",
            "## Engineering Readout",
            "",
            "- The current package is suitable for preventing unsafe claims.",
            "- It is not a drawing-release, hardware, aeroelastic, or full-wing global-buckling signoff.",
            "- Full-wing or braced-subassembly buckling FEM, finite-rib load transfer, selected hardware allowables, and aeroelastic twist closure remain required.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    audit = build_current_structural_goal_completion_audit()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        _write_csv(args.output_dir / "structural_goal_completion_audit.csv", audit),
        _write_json(args.output_dir / "structural_goal_completion_audit.json", audit),
        _write_markdown(args.output_dir / "structural_goal_completion_audit.md", audit),
    ]
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
