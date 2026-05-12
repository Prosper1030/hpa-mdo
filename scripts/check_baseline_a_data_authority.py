#!/usr/bin/env python3
"""Audit Baseline A data-authority claims and current-channel wording.

The checker is intentionally conservative and pattern-based. It is not the
final engineering authority; it is a guardrail that prevents stale screening
numbers from being promoted into the main docs, release docs, RFQ language, or
future work-order queue.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
from typing import Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RELEASE_DIR = REPO_ROOT / "output" / "baseline_A_team_release"
DEFAULT_REPORT_DIR = REPO_ROOT / "docs" / "reports"

AUTHORITY_CLASSES = {
    "user_authority",
    "current_pipeline_truth",
    "screening_estimate",
    "generated_output",
    "legacy_or_experiment",
    "unknown",
    "conflict_blocked",
}

CLAIM_FIELDS = [
    "claim_id",
    "file",
    "line",
    "raw_text",
    "extracted_value",
    "unit",
    "engineering_topic",
    "nearby_keywords",
    "inferred_meaning",
    "source_lane",
    "current_authority_class",
    "risk_level",
    "recommended_action",
]

CONFLICT_FIELDS = [
    "conflict_id",
    "category",
    "risk_level",
    "blocking_status",
    "wo006_unblock_classification",
    "summary",
    "affected_files",
    "conflicting_values",
    "authority_read",
    "required_repair",
]

AUTHORITY_FIELDS = [
    "authority_id",
    "engineering_topic",
    "important_number",
    "unit",
    "authority_class",
    "source_lane",
    "allowed_use",
    "disallowed_use",
    "may_appear_in_readme_current_mainline_release_docs",
    "may_be_used_for_procurement",
    "may_affect_baseline_A_reopen",
    "trust_upgrade_requirement",
]

TEXT_SUFFIXES = {
    "",
    ".avl",
    ".cfg",
    ".csv",
    ".dat",
    ".json",
    ".jsonl",
    ".log",
    ".mac",
    ".md",
    ".py",
    ".rst",
    ".st",
    ".txt",
    ".toml",
    ".tsv",
    ".yaml",
    ".yml",
}

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}

MAX_TEXT_BYTES = 3_000_000

NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", re.IGNORECASE)
VALUE_UNIT_RE = re.compile(
    r"(?<![\w.])(?P<value>-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*"
    r"(?P<unit>kg|m|mm|W|N\*m|N\\*m|N-m|N|deg|%|m/s|m\^2|m2|mm2|mm\^2)?",
    re.IGNORECASE,
)

TOPIC_KEYWORDS = {
    "mass / CG / rebalance": (
        "mass",
        "kg",
        "gross",
        "cg",
        "rebalance",
        "weight",
        "ledger",
        "balance",
    ),
    "span / half-span / station / rib spacing": (
        "span",
        "half-span",
        "station",
        "rib",
        "bay",
        "y=",
        "geometry",
    ),
    "spar / splice / RFQ / procurement": (
        "spar",
        "splice",
        "rfq",
        "procurement",
        "vendor",
        "tube",
        "shop",
        "purchase",
    ),
    "drag / power / mission margin": (
        "drag",
        "power",
        "mission",
        "margin",
        "cd0",
        "crank",
        "watt",
        "W",
    ),
    "structure margin / C04 / coupon FEM": (
        "structure",
        "structural",
        "margin",
        "c04",
        "coupon",
        "fem",
        "apdl",
        "buckling",
        "laminate",
        "adhesive",
        "sign-off",
        "signoff",
    ),
    "tail / trim / stability / control": (
        "tail",
        "trim",
        "stability",
        "control",
        "static",
        "directional",
        "vtail",
        "htail",
    ),
    "propulsion lane contamination": (
        "qprop",
        "xrotor",
        "propulsion",
        "propeller",
        "rpm",
        "shaft",
    ),
    "verdict / sign-off overclaim": (
        "verdict",
        "ready",
        "pass",
        "sign-off",
        "signoff",
        "final",
        "release",
        "truth",
    ),
    "tests that preserve stale constants": ("assert", "pytest", "approx", "test_"),
    "scripts that read old generated outputs as truth": (
        "output/",
        "read_json",
        "read_csv",
        "DEFAULT_",
        "phase",
    ),
}

BASELINE_FILTER_TERMS = {
    "98.5",
    "106.828608",
    "34.332286",
    "17.166143",
    "16.5",
    "-9",
    "baseline",
    "baseline a",
    "birdman",
    "c04",
    "cg",
    "current pathfinder",
    "fem",
    "mass",
    "mission",
    "procurement",
    "qprop",
    "rfq",
    "rib",
    "screening",
    "sign-off",
    "signoff",
    "span",
    "spar",
    "splice",
    "stability",
    "structure",
    "su2",
    "tail",
    "verdict",
    "wo-",
    "xrotor",
}

CHECK_SCOPE_FILES = {
    "README.md",
    "CURRENT_MAINLINE.md",
    "docs/README.md",
    "docs/AI_WORK_ORDER_PROTOCOL.md",
    "docs/work_orders/QUEUE.md",
}

REPAIRED_READY_VERDICTS = {
    "baseline_a_release_system_ready",
    "carbon_tube_rfq_pack_ready",
    "mass_cg_margin_ledger_ready",
}

GENERATED_AUDIT_ARTIFACTS = {
    "docs/reports/baseline_A_data_authority_audit.md",
    "docs/reports/baseline_A_data_authority_conflict_register.md",
    "docs/reports/baseline_A_gate_debt_register.md",
    "docs/reports/repo_channel_hygiene_plan.md",
    "output/baseline_A_team_release/data_authority_claim_inventory.csv",
    "output/baseline_A_team_release/data_authority_claim_inventory.json",
    "output/baseline_A_team_release/data_authority_conflict_register.csv",
    "output/baseline_A_team_release/data_authority_table.csv",
    "output/baseline_A_team_release/data_authority_table.json",
}


@dataclass(frozen=True)
class Claim:
    claim_id: str
    file: str
    line: int
    raw_text: str
    extracted_value: str
    unit: str
    engineering_topic: str
    nearby_keywords: str
    inferred_meaning: str
    source_lane: str
    current_authority_class: str
    risk_level: str
    recommended_action: str


@dataclass(frozen=True)
class AuthorityViolation:
    rule_id: str
    file: str
    line: int
    raw_text: str
    risk_level: str
    message: str


@dataclass(frozen=True)
class AuditRunResult:
    files_scanned: int
    claims_extracted: int
    skipped_paths: int
    violations: int


def check_authority_violations(repo_root: Path = REPO_ROOT) -> list[AuthorityViolation]:
    """Return blocking current-channel authority violations."""
    violations: list[AuthorityViolation] = []
    for path in _iter_check_scope_files(repo_root):
        rel = _rel(path, repo_root)
        lines = list(_iter_text_lines(path))
        for line_number, line in lines:
            for rule_id, message in _line_violations(line):
                violations.append(
                    AuthorityViolation(
                        rule_id=rule_id,
                        file=rel,
                        line=line_number,
                        raw_text=line.strip(),
                        risk_level="blocking",
                        message=message,
                    )
                )
        violations.extend(_file_sequence_violations(rel=rel, lines=lines))
    return violations


def write_audit_artifacts(repo_root: Path = REPO_ROOT) -> AuditRunResult:
    """Scan repo channels and write the requested audit artifacts."""
    release_dir = repo_root / "output" / "baseline_A_team_release"
    report_dir = repo_root / "docs" / "reports"
    release_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)

    scan_files, skipped = _scan_files(repo_root)
    claims: list[Claim] = []
    for path in scan_files:
        rel = _rel(path, repo_root)
        for line_number, line in _iter_text_lines(path):
            claim = _claim_from_line(
                rel=rel,
                line_number=line_number,
                line=line,
                claim_index=len(claims) + 1,
            )
            if claim is not None:
                claims.append(claim)

    conflicts = _conflict_rows(claims)
    authority_rows = _authority_rows()
    gate_debt_rows = _gate_debt_rows(claims)
    violations = check_authority_violations(repo_root)

    _write_claim_inventory(
        release_dir / "data_authority_claim_inventory.csv",
        release_dir / "data_authority_claim_inventory.json",
        claims,
        files_scanned=len(scan_files),
        skipped=skipped,
    )
    _write_csv_dicts(release_dir / "data_authority_conflict_register.csv", CONFLICT_FIELDS, conflicts)
    _write_csv_dicts(release_dir / "data_authority_table.csv", AUTHORITY_FIELDS, authority_rows)
    _write_json(
        release_dir / "data_authority_table.json",
        {
            "schema_version": "baseline_a_data_authority_table_v1",
            "authority_classes": sorted(AUTHORITY_CLASSES),
            "rows": authority_rows,
        },
    )
    _write_text(
        report_dir / "baseline_A_data_authority_conflict_register.md",
        _render_conflict_register_md(conflicts, violations),
    )
    _write_text(
        report_dir / "baseline_A_data_authority_audit.md",
        _render_authority_audit_md(
            claims=claims,
            conflicts=conflicts,
            authority_rows=authority_rows,
            files_scanned=len(scan_files),
            skipped=skipped,
            violations=violations,
        ),
    )
    _write_text(
        report_dir / "baseline_A_gate_debt_register.md",
        _render_gate_debt_md(gate_debt_rows),
    )
    _write_text(
        report_dir / "repo_channel_hygiene_plan.md",
        _render_channel_hygiene_md(skipped),
    )

    return AuditRunResult(
        files_scanned=len(scan_files),
        claims_extracted=len(claims),
        skipped_paths=len(skipped),
        violations=len(violations),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root to scan.",
    )
    parser.add_argument(
        "--write-audit",
        action="store_true",
        help="Write claim inventory, conflict register, authority table, and audit docs.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only run current-channel guardrail checks.",
    )
    args = parser.parse_args(argv)

    if args.write_audit and not args.check_only:
        result = write_audit_artifacts(args.repo_root)
        print(
            "data authority audit: "
            f"files_scanned={result.files_scanned} "
            f"claims_extracted={result.claims_extracted} "
            f"skipped_paths={result.skipped_paths} "
            f"violations={result.violations}"
        )

    violations = check_authority_violations(args.repo_root)
    if violations:
        print("Baseline A data-authority violations:")
        for violation in violations:
            print(
                f"- {violation.rule_id}: {violation.file}:{violation.line}: "
                f"{violation.raw_text}"
            )
        return 1
    print("Baseline A data-authority checker passed.")
    return 0


def _line_violations(line: str) -> list[tuple[str, str]]:
    normalized = _normalize(line)
    violations: list[tuple[str, str]] = []

    if "106.828608" in normalized and not _has_any(
        normalized,
        (
            "suspect",
            "screening aggregate",
            "screening mass",
            "screening estimate",
            "stage-0",
            "quick-screen",
            "not current",
            "not design",
            "not truth",
            "not design truth",
            "p1 screening",
            "p1_screening",
            "conflict-blocked",
            "conflict blocked",
            "authority repair",
            "legacy/pre-ledger",
            "screening_aggregate",
        ),
    ):
        violations.append(
            (
                "suspect_mass_as_current_truth",
                "106.828608 kg must not be promoted as current design gross mass truth.",
            )
        )

    if _mentions_16p5(normalized) and _has_any(
        normalized,
        (
            "current pipeline half-span",
            "procurement truth",
            "procurement basis",
            "purchase length control",
            "shop span",
            "shop/rfq",
            "drawing control",
            "controlled_for_rfq",
            "structural procurement",
            "rfq control",
            "rfq convention",
        ),
    ) and not _has_any(
        normalized,
        (
            "not current",
            "not procurement",
            "not purchase",
            "not yet",
            "not shop",
            "not drawing",
            "local/splice screening",
            "screening reference",
            "conflict-blocked",
            "conflict blocked",
            "draft/vendor-screening",
            "must not",
        ),
    ):
        violations.append(
            (
                "suspect_half_span_as_procurement_truth",
                "16.5 m must not be promoted as pipeline half-span, RFQ control, shop, or procurement truth.",
            )
        )

    if _mentions_minus_9_w(normalized) and _has_any(
        normalized,
        (
            "current full-pipeline mission verdict",
            "full-pipeline mission verdict",
            "latest mission verdict",
            "final mission",
            "mission sign-off",
            "mission pass",
        ),
    ) and not _has_any(normalized, ("not", "stage-0", "quick-screen", "warning")):
        violations.append(
            (
                "stage0_power_as_current_mission_verdict",
                "-9 W must stay Stage-0 quick-screen warning only.",
            )
        )

    if _has_any(normalized, ("coupon/fem readiness", "coupon/local fem", "screening readiness")) and _has_any(
        normalized, ("final aircraft sign-off", "aircraft sign-off", "final signoff")
    ) and not _has_any(normalized, ("not", "is not", "不是", "不是 final")):
        violations.append(
            (
                "screening_readiness_as_final_signoff",
                "Screening or coupon/FEM readiness cannot be final aircraft sign-off.",
            )
        )

    if _has_any(normalized, ("qprop", "xrotor")) and _has_any(
        normalized, ("structural blocker", "structure blocker", "c04", "rib structural")
    ) and _has_any(
        normalized,
        (
            "resolves",
            "resolve",
            "passes",
            "pass ",
            "pass/fail",
            "used to pass",
            "used in structural",
            "參與",
        ),
    ) and not _has_any(
        normalized,
        (
            "not used",
            "not used to pass",
            "independent",
            "不參與",
            "不用於",
            "不得",
            "不能",
            "must not",
        ),
    ):
        violations.append(
            (
                "propulsion_mixed_into_structure_verdict",
                "QPROP/XROTOR must remain independent from structural blocker verdicts.",
            )
        )

    if _has_any(normalized, ("rfq", "vendor")) and _has_any(
        normalized, ("purchase-ready", "purchase ready", "purchase authorization", "order authorization")
    ) and not _has_any(
        normalized,
        (
            "not purchase-ready",
            "not purchase ready",
            "not ready for purchase",
            "not purchase authorization",
            "not order authorization",
            "draft",
            "vendor-screening",
        ),
    ):
        violations.append(
            (
                "rfq_purchase_ready_while_conflict_blocked",
                "RFQ cannot be described as purchase-ready while mass/span authority is blocked.",
            )
        )

    if _has_active_repaired_ready_verdict(normalized):
        violations.append(
            (
                "active_ready_verdict_without_repair_boundary",
                "Old WO-001 to WO-005 ready verdicts must be labeled historical/generated evidence under data-authority repair, not active truth.",
            )
        )

    if _rfq_controls_16p5_span_station_splice(normalized):
        violations.append(
            (
                "rfq_controls_16p5_span_station_splice",
                "RFQ wording must not control span/station/splice language from the 16.5 m local/splice screening reference.",
            )
        )

    if _wo006_next_without_data_authority_prerequisite(normalized):
        violations.append(
            (
                "wo006_next_without_data_authority_prerequisite",
                "WO-006 cannot be described as next/recommended unless data-authority restoration is named as a prerequisite.",
            )
        )

    return violations


def _file_sequence_violations(
    *, rel: str, lines: Sequence[tuple[int, str]]
) -> list[AuthorityViolation]:
    """Catch contradictions that need file-order context."""
    saw_16p5_not_procurement: tuple[int, str] | None = None
    wo006_paused_line: tuple[int, str] | None = None
    next_recommended_goals: list[tuple[int, str]] = []
    violations: list[AuthorityViolation] = []
    for index, (line_number, line) in enumerate(lines):
        normalized = _normalize(line)
        if _line_marks_wo006_paused(normalized):
            wo006_paused_line = (line_number, line.strip())

        if _is_next_recommended_heading(normalized):
            for goal_line_number, goal_line in lines[index + 1 : index + 11]:
                goal_normalized = _normalize(goal_line)
                if not _is_wo006_goal_line(goal_normalized):
                    continue
                context = [text for _number, text in lines[index : index + 11]]
                if not _has_data_authority_prerequisite_context(context):
                    violations.append(
                        AuthorityViolation(
                            rule_id="wo006_next_recommended_goal_without_prerequisite",
                            file=rel,
                            line=goal_line_number,
                            raw_text=goal_line.strip(),
                            risk_level="blocking",
                            message=(
                                "A Next Recommended Work Order block cannot point "
                                "to a WO-006 goal unless data-authority restoration "
                                "is named as a prerequisite."
                            ),
                        )
                    )
                if _is_wo006_execute_goal_line(goal_normalized):
                    next_recommended_goals.append((goal_line_number, goal_line.strip()))
                break

        if _is_16p5_not_procurement_truth(normalized):
            saw_16p5_not_procurement = (line_number, line.strip())
            continue
        if saw_16p5_not_procurement is not None and _rfq_controls_16p5_span_station_splice(
            normalized
        ):
            previous_line, _previous_text = saw_16p5_not_procurement
            violations.append(
                AuthorityViolation(
                    rule_id="sixteenp5_not_procurement_truth_then_rfq_controls",
                    file=rel,
                    line=line_number,
                    raw_text=line.strip(),
                    risk_level="blocking",
                    message=(
                        "This file first labels 16.5 m as not procurement truth "
                        f"at line {previous_line}, then later lets RFQ control "
                        "span/station/splice language from it."
                    ),
                )
            )
            saw_16p5_not_procurement = None
    if wo006_paused_line is not None:
        paused_line_number, _paused_text = wo006_paused_line
        for goal_line_number, goal_line in _wo006_execute_goal_lines(lines):
            violations.append(
                AuthorityViolation(
                    rule_id="wo006_paste_ready_goal_while_paused",
                    file=rel,
                    line=goal_line_number,
                    raw_text=goal_line,
                    risk_level="blocking",
                    message=(
                        "A paste-ready /goal cannot execute WO-006 while the "
                        f"queue still marks WO-006 paused at line {paused_line_number}."
                    ),
                )
            )
        for goal_line_number, goal_line in next_recommended_goals:
            violations.append(
                AuthorityViolation(
                    rule_id="queue_paused_wo006_but_recommended_goal_executes_wo006",
                    file=rel,
                    line=goal_line_number,
                    raw_text=goal_line,
                    risk_level="blocking",
                    message=(
                        "The queue table marks WO-006 paused, but the recommended "
                        "goal still tells a worker to execute WO-006."
                    ),
                )
            )
    return violations


def _line_marks_wo006_paused(normalized: str) -> bool:
    return "wo-006" in normalized and _has_any(normalized, ("paused", "pause", "暫停"))


def _is_next_recommended_heading(normalized: str) -> bool:
    heading = normalized.lstrip("# ").strip()
    return heading in {
        "next recommended work order",
        "next recommended goal",
        "next recommended task",
    }


def _is_wo006_goal_line(normalized: str) -> bool:
    return normalized.startswith("/goal ") and "wo-006" in normalized


def _is_wo006_execute_goal_line(normalized: str) -> bool:
    return _is_wo006_goal_line(normalized) and _has_any(
        normalized,
        (
            "execute wo-006",
            "start wo-006",
            "run wo-006",
            "執行 wo-006",
            "開始 wo-006",
        ),
    )


def _wo006_execute_goal_lines(lines: Sequence[tuple[int, str]]) -> list[tuple[int, str]]:
    return [
        (line_number, line.strip())
        for line_number, line in lines
        if _is_wo006_execute_goal_line(_normalize(line))
    ]


def _has_data_authority_prerequisite_context(lines: Sequence[str]) -> bool:
    normalized = _normalize(" ".join(lines))
    return _has_any(
        normalized,
        (
            "data-authority restoration",
            "data authority restoration",
            "data-authority repair",
            "data authority repair",
            "data-authority restored",
            "data authority restored",
            "authority restoration",
            "authority restored",
            "checker passes",
            "checker/audit",
            "prerequisite",
            "remains paused",
            "stays paused",
            "until data authority",
            "until data-authority",
            "前提",
            "修復",
            "暫停",
        ),
    )


def _has_active_repaired_ready_verdict(normalized: str) -> bool:
    if not any(verdict in normalized for verdict in REPAIRED_READY_VERDICTS):
        return False
    if _is_historical_generated_repair_context(normalized):
        return False
    if _has_any(
        normalized,
        (
            "required verdict",
            "required final verdict",
            "required output verdict",
            "must return",
            "must output",
            "or `",
            "或 `",
        ),
    ):
        return False
    return _has_any(
        normalized,
        (
            "verdict",
            "release verdict",
            "ledger verdict",
            "final verdict",
            "目前",
            "current",
            "release",
            "rfq",
            "ledger",
            "mass",
            "next",
            "已建立",
            "completed",
            "done",
            "ready",
        ),
    )


def _is_historical_generated_repair_context(normalized: str) -> bool:
    return _has_any(
        normalized,
        (
            "historical/generated evidence",
            "historical generated evidence",
            "歷史/generated evidence",
            "歷史 generated evidence",
            "old wo-",
            "舊",
            "legacy",
        ),
    ) and (
        _has_any(
            normalized,
            (
                "data-authority repair",
                "data authority repair",
                "authority repair",
                "under repair",
                "repair gate",
            ),
        )
        or _has_any(
            normalized,
            (
                "not active",
                "not current",
                "not current truth",
                "not release",
                "not procurement",
                "not truth",
                "不是",
                "不得",
            ),
        )
    )


def _rfq_controls_16p5_span_station_splice(normalized: str) -> bool:
    if not _mentions_16p5(normalized) or "rfq" not in normalized:
        return False
    if _has_any(
        normalized,
        (
            "not rfq control",
            "not rfq-controlled",
            "not rfq controlled",
            "not current pipeline half-span and not procurement truth",
            "not procurement truth",
            "not purchase",
            "must not control",
            "must not be rfq",
            "不得",
            "不能",
            "不是",
            "不可",
        ),
    ):
        return False
    has_control_verb = bool(
        re.search(r"\brfq\b(?:\s+\w+){0,4}\s+controls\b", normalized)
        or re.search(r"\bcontrols\b(?:\s+\w+){0,4}\s+\brfq\b", normalized)
        or ("rfq" in normalized and "控制" in normalized)
    )
    if not has_control_verb:
        return False
    return _has_any(
        normalized,
        (
            "span",
            "station",
            "splice",
            "half-span",
            "structural",
            "站",
            "翼展",
            "接頭",
        ),
    )


def _wo006_next_without_data_authority_prerequisite(normalized: str) -> bool:
    if "wo-006" not in normalized:
        return False
    if not _has_any(
        normalized,
        (
            "next",
            "recommended",
            "recommend",
            "建議",
            "下一個",
            "next p1",
            "p1 is wo-006",
            "p1 是 wo-006",
            "queued",
        ),
    ):
        return False
    return not _has_any(
        normalized,
        (
            "data authority",
            "data-authority",
            "authority restored",
            "authority restoration",
            "restored",
            "restoration",
            "prerequisite",
            "checker",
            "paused",
            "暫停",
            "修復",
            "前提",
        ),
    )


def _is_16p5_not_procurement_truth(normalized: str) -> bool:
    return _mentions_16p5(normalized) and _has_any(
        normalized,
        (
            "not procurement truth",
            "not rfq control",
            "not shop span",
            "not purchase",
            "不是 current pipeline half-span",
            "不是 procurement truth",
            "不是 rfq",
            "不是 shop",
        ),
    )


def _claim_from_line(
    *, rel: str, line_number: int, line: str, claim_index: int
) -> Claim | None:
    stripped = line.strip()
    if not stripped:
        return None
    normalized = _normalize(stripped)
    if not _is_candidate_claim(normalized):
        return None

    value, unit = _extract_value_unit(stripped)
    topic = _topic_for_line(normalized)
    lane = _source_lane(rel)
    authority_class = _authority_class_for_line(rel, normalized, topic, value)
    risk = _risk_for_line(normalized, authority_class)
    keywords = _nearby_keywords(normalized)
    return Claim(
        claim_id=f"DA-{claim_index:05d}",
        file=rel,
        line=line_number,
        raw_text=stripped[:500],
        extracted_value=value,
        unit=unit,
        engineering_topic=topic,
        nearby_keywords=", ".join(keywords),
        inferred_meaning=_inferred_meaning(normalized, topic, value, unit),
        source_lane=lane,
        current_authority_class=authority_class,
        risk_level=risk,
        recommended_action=_recommended_action(authority_class, topic, normalized),
    )


def _is_candidate_claim(normalized: str) -> bool:
    has_baseline_term = _has_any(normalized, BASELINE_FILTER_TERMS)
    has_number = NUMBER_RE.search(normalized) is not None
    has_verdict_term = _has_any(
        normalized,
        (
            "verdict",
            "sign-off",
            "signoff",
            "purchase-ready",
            "purchase ready",
            "procurement",
            "rfq",
            "coupon",
            "fem",
            "qprop",
            "xrotor",
            "truth",
            "authority",
        ),
    )
    return has_baseline_term and (has_number or has_verdict_term)


def _extract_value_unit(text: str) -> tuple[str, str]:
    match = VALUE_UNIT_RE.search(text)
    if not match:
        return "", ""
    unit = match.group("unit") or ""
    return match.group("value"), unit.replace("\\*", "*")


def _topic_for_line(normalized: str) -> str:
    scores: list[tuple[int, str]] = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword.lower() in normalized)
        scores.append((score, topic))
    scores.sort(reverse=True)
    if scores and scores[0][0] > 0:
        return scores[0][1]
    return "verdict / sign-off overclaim"


def _source_lane(rel: str) -> str:
    if rel in {"README.md", "CURRENT_MAINLINE.md"}:
        return "front_door_mainline_docs"
    if rel == "AGENTS.md":
        return "agent_policy"
    if rel.startswith("docs/work_orders/") or rel == "docs/AI_WORK_ORDER_PROTOCOL.md":
        return "work_order_control_docs"
    if rel == "docs/README.md":
        return "docs_front_door"
    if rel.startswith("docs/reports/"):
        return "docs_reports"
    if rel.startswith("docs/"):
        return "docs_other"
    if rel.startswith("scripts/"):
        return "scripts"
    if rel.startswith("src/"):
        return "src"
    if rel.startswith("tests/"):
        return "tests"
    if rel.startswith("configs/") or rel.startswith("config/") or rel.startswith("data/"):
        return "config_or_data"
    if rel.startswith("output/baseline_A_team_release/"):
        return "baseline_A_release_output"
    if rel.startswith("output/current_pathfinder"):
        return "current_pathfinder_output"
    if rel.startswith("output/go_mode_main_wing_candidate/final_candidate_package/"):
        return "current_pipeline_package"
    if rel.startswith("output/phase"):
        return "legacy_phase_output"
    if rel.startswith("output/"):
        return "output_other"
    return "unknown"


def _authority_class_for_line(
    rel: str, normalized: str, topic: str, value: str
) -> str:
    lane = _source_lane(rel)
    if lane == "legacy_phase_output":
        return "legacy_or_experiment"
    if "98.5" in normalized and _has_any(normalized, ("authority", "design", "mass")):
        return "user_authority"
    if _has_any(normalized, ("34.332286", "17.166143")) and _has_any(
        normalized, ("span", "bref", "half-span", "pipeline")
    ):
        return "current_pipeline_truth"
    if "106.828608" in normalized:
        return "screening_estimate" if _is_safe_screening_context(normalized) else "conflict_blocked"
    if _mentions_16p5(normalized):
        if _has_any(normalized, ("procurement truth", "current pipeline half-span", "controlled_for_rfq")):
            return "conflict_blocked"
        return "screening_estimate"
    if _mentions_minus_9_w(normalized):
        return "screening_estimate"
    if lane in {"baseline_A_release_output", "current_pathfinder_output", "output_other"}:
        return "generated_output"
    if lane == "current_pipeline_package":
        return "current_pipeline_truth"
    if _has_any(normalized, ("screening", "estimate", "readiness", "coupon", "fem")):
        return "screening_estimate"
    if _has_any(normalized, ("unknown", "missing", "blocked", "needs")):
        return "unknown"
    if value:
        return "unknown"
    return "generated_output" if lane.startswith("output") else "unknown"


def _risk_for_line(normalized: str, authority_class: str) -> str:
    if authority_class == "conflict_blocked":
        return "blocking"
    if _line_violations(normalized):
        return "blocking"
    if authority_class in {"legacy_or_experiment", "unknown"}:
        return "medium"
    if _has_any(normalized, ("final aircraft", "procurement", "purchase", "rfq", "gross mass")):
        return "high"
    if authority_class in {"screening_estimate", "generated_output"}:
        return "medium"
    return "low"


def _nearby_keywords(normalized: str) -> list[str]:
    keywords: list[str] = []
    for topic_keywords in TOPIC_KEYWORDS.values():
        for keyword in topic_keywords:
            if keyword.lower() in normalized and keyword not in keywords:
                keywords.append(keyword)
    return keywords[:12]


def _inferred_meaning(normalized: str, topic: str, value: str, unit: str) -> str:
    if "106.828608" in normalized:
        return "P1 mass-closure aggregate that conflicts with the 98.5 kg design mass authority."
    if "98.5" in normalized:
        return "User-authorized current design gross mass standard."
    if _has_any(normalized, ("34.332286", "17.166143")):
        return "Current pipeline span evidence unless superseded by newer authority."
    if _mentions_16p5(normalized):
        return "Local structural/splice screening span; not current pipeline or procurement truth."
    if _mentions_minus_9_w(normalized):
        return "Stage-0 quick-screen power warning, not latest full-pipeline verdict."
    if value:
        return f"Numeric claim in {topic}: {value} {unit}".strip()
    return f"Verdict or authority wording in {topic}."


def _recommended_action(authority_class: str, topic: str, normalized: str) -> str:
    if authority_class == "conflict_blocked":
        return "Rewrite as conflict-blocked/screening only and add source reconciliation before use."
    if authority_class == "legacy_or_experiment":
        return "Keep only as legacy evidence; do not cite as current Baseline A truth."
    if authority_class == "user_authority":
        return "Preserve as the governing user authority until explicitly changed."
    if authority_class == "current_pipeline_truth":
        return "May cite as current pipeline evidence, with source and replacement condition."
    if "rfq" in normalized or "procurement" in normalized:
        return "Keep as draft/vendor-screening; block release/procurement use while allowing bounded WO-006 separately."
    if authority_class == "screening_estimate":
        return "Label as screening estimate/readiness; block final sign-off or procurement use."
    return "Review before repeating; classify source and allowed use in the authority table."


def _conflict_rows(claims: Sequence[Claim]) -> list[dict[str, str]]:
    evidence = _claim_evidence_by_category(claims)
    rows = [
        {
            "conflict_id": "C-001",
            "category": "mass / CG / rebalance",
            "risk_level": "blocking",
            "blocking_status": "blocks_release_claims_power_cg_and_procurement_truth",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "98.5 kg is current design mass authority; 106.828608 kg is a suspect P1 screening aggregate and cannot drive current design mass, mission, CG, or RFQ truth.",
            "affected_files": evidence.get("mass / CG / rebalance", ""),
            "conflicting_values": "98.5 kg vs 106.828608 kg",
            "authority_read": "Use 98.5 kg for design gross mass unless user changes it; quarantine 106.828608 kg as screening aggregate.",
            "required_repair": "Mass-basis reconciliation and measured/component ledger before any release, mission, CG, or procurement claim uses the aggregate.",
        },
        {
            "conflict_id": "C-002",
            "category": "span / half-span / station / rib spacing",
            "risk_level": "blocking",
            "blocking_status": "blocks_rfq_shop_and_station_control",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "Current pipeline evidence is 34.332286 m full span / 17.166143 m half-span; 16.5 m is local structural/splice screening only.",
            "affected_files": evidence.get("span / half-span / station / rib spacing", ""),
            "conflicting_values": "34.332286 m / 17.166143 m vs 16.5 m",
            "authority_read": "Pipeline span evidence may be cited; 16.5 m must not be RFQ/shop/procurement truth.",
            "required_repair": "Reconcile pipeline geometry, station manifest, splice local basis, and vendor-screening convention before RFQ restoration.",
        },
        {
            "conflict_id": "C-003",
            "category": "spar / splice / RFQ / procurement",
            "risk_level": "blocking",
            "blocking_status": "wo005_draft_only",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "WO-005 RFQ artifacts were built from screening/local span and generated outputs. They are vendor-screening only, not purchase-ready.",
            "affected_files": evidence.get("spar / splice / RFQ / procurement", ""),
            "conflicting_values": "carbon_tube_rfq_pack_ready vs draft/vendor-screening only",
            "authority_read": "RFQ may ask capability questions only after wording repair; it cannot authorize purchase or drawing release.",
            "required_repair": "Use authority table, conflict register, and station/span reconciliation before procurement use.",
        },
        {
            "conflict_id": "C-004",
            "category": "drag / power / mission margin",
            "risk_level": "high",
            "blocking_status": "blocks_full_pipeline_mission_verdict",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "WO-003 -9 W is only Stage-0 quick-screen warning, not latest full-pipeline mission truth.",
            "affected_files": evidence.get("drag / power / mission margin", ""),
            "conflicting_values": "-9 W quick-screen warning vs current full-pipeline verdict missing",
            "authority_read": "Use as a watch item only. WO-006 may proceed only as bounded aero calibration; it cannot be mission/release truth.",
            "required_repair": "Rebuild mission/power authority from the repaired mass/span basis before release claims.",
        },
        {
            "conflict_id": "C-005",
            "category": "structure margin / C04 / coupon FEM",
            "risk_level": "high",
            "blocking_status": "blocks_final_structure_signoff",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "P1/C04 evidence is coupon/local FEM readiness. It is not adhesive, laminate, buckling, hardware, or aircraft sign-off.",
            "affected_files": evidence.get("structure margin / C04 / coupon FEM", ""),
            "conflicting_values": "-0.893 original peel fail, 0.8876 installed-fix surrogate margin",
            "authority_read": "Installed fix may proceed to coupon/local FEM only.",
            "required_repair": "Coupon/local FEM, supplier allowables, tube-wall/collar/skin-sag evidence, and load-path review.",
        },
        {
            "conflict_id": "C-006",
            "category": "tail / trim / stability / control",
            "risk_level": "high",
            "blocking_status": "screening_only",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "Tail/CG/trim/stability claims remain screening assumptions, not measured CG, tail hardware, actuator, or flight-dynamics sign-off.",
            "affected_files": evidence.get("tail / trim / stability / control", ""),
            "conflicting_values": "managed CG row vs missing measured mass/CG/tail hardware authority",
            "authority_read": "Keep tail screening separate from aircraft-level sign-off.",
            "required_repair": "Measured mass/CG manifest, tailboom/pivot/actuator evidence, and control derivative validation.",
        },
        {
            "conflict_id": "C-007",
            "category": "propulsion lane contamination",
            "risk_level": "blocking",
            "blocking_status": "blocks_structural_verdict_language",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "QPROP/XROTOR must not pass or fail C04/rib/structural blockers.",
            "affected_files": evidence.get("propulsion lane contamination", ""),
            "conflicting_values": "propulsion sizing lane vs structural blocker verdict lane",
            "authority_read": "Propulsion is independent until WO-007 and cannot repair structure evidence.",
            "required_repair": "Keep all structural verdicts free of propulsion pass/fail language.",
        },
        {
            "conflict_id": "C-008",
            "category": "verdict / sign-off overclaim",
            "risk_level": "blocking",
            "blocking_status": "blocks_baseline_A_release_claims",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "Release, ready, pass, RFQ, and FEM-readiness verdicts were too easy to read as current truth or final aircraft sign-off.",
            "affected_files": evidence.get("verdict / sign-off overclaim", ""),
            "conflicting_values": "ready/release wording vs screening/readiness trust boundary",
            "authority_read": "All readiness language must state allowed and disallowed use.",
            "required_repair": "Use checker and authority table before adding release/work-order wording.",
        },
        {
            "conflict_id": "C-009",
            "category": "tests that preserve stale constants",
            "risk_level": "high",
            "blocking_status": "repair_needed",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "Some tests asserted stale constants as expected truth instead of checking authority classification.",
            "affected_files": evidence.get("tests that preserve stale constants", ""),
            "conflicting_values": "pytest approx(106.828608), 16.5 RFQ control fixtures",
            "authority_read": "Old constants may stay only as legacy/screening fixtures with explicit classification.",
            "required_repair": "Update tests to assert authority wording and safe classes.",
        },
        {
            "conflict_id": "C-010",
            "category": "scripts that read old generated outputs as truth",
            "risk_level": "high",
            "blocking_status": "repair_needed",
            "wo006_unblock_classification": "blocks_release_procurement_only",
            "summary": "Release/RFQ scripts read generated P1/splice/manufacturing outputs as if they were release authority.",
            "affected_files": evidence.get("scripts that read old generated outputs as truth", ""),
            "conflicting_values": "generated outputs vs authority table",
            "authority_read": "Generated outputs are evidence unless explicitly authorized in the authority table.",
            "required_repair": "Scripts must emit authority metadata and avoid promotion wording.",
        },
    ]
    return rows


def _claim_evidence_by_category(claims: Sequence[Claim]) -> dict[str, str]:
    by_topic: dict[str, list[str]] = {}
    for claim in claims:
        if claim.risk_level not in {"blocking", "high", "medium"}:
            continue
        bucket = by_topic.setdefault(claim.engineering_topic, [])
        if len(bucket) < 5:
            bucket.append(f"{claim.file}:{claim.line}")
    return {topic: "; ".join(paths) for topic, paths in by_topic.items()}


def _authority_rows() -> list[dict[str, str]]:
    return [
        _authority_row(
            "design_gross_mass_98p5",
            "mass / CG / rebalance",
            "98.5",
            "kg",
            "user_authority",
            "latest explicit user instruction",
            "Current design gross mass standard until the user explicitly changes it.",
            "Do not overwrite with P1 aggregate, release ledger sum, vendor response, or generated output.",
            "yes; it should appear as the governing design mass authority",
            "yes, but only as design standard input, not measured order mass",
            "yes; deviations from this standard may trigger user decision",
            "Only a new explicit user instruction or a formal mass-basis reconciliation can replace it.",
        ),
        _authority_row(
            "p1_screening_mass_106p828608",
            "mass / CG / rebalance",
            "106.828608",
            "kg",
            "screening_estimate",
            "P1 generated mass-closure aggregate",
            "May appear as suspect P1 screening aggregate evidence.",
            "Must not be current design gross mass, bounded WO-006 mass basis, mission mass, RFQ truth, or release truth.",
            "yes, only when labeled suspect/screening and contrasted with 98.5 kg",
            "no",
            "yes, but only as a conflict requiring reconciliation",
            "Rebuild component mass ledger against the 98.5 kg design standard and measured/quoted component data.",
        ),
        _authority_row(
            "pipeline_full_span_34p332286",
            "span / half-span / station / rib spacing",
            "34.332286",
            "m",
            "current_pipeline_truth",
            "current pipeline AVL/geometry manifests",
            "Current pipeline full-span evidence unless superseded by newer authority.",
            "Do not round or replace with local splice data for procurement.",
            "yes, with source and replacement condition",
            "not alone; procurement needs repaired station/span manifest",
            "yes, if newer geometry invalidates it",
            "Promoted geometry manifest and station schedule that reconciles aero, rib, splice, and shop bases.",
        ),
        _authority_row(
            "pipeline_half_span_17p166143",
            "span / half-span / station / rib spacing",
            "17.166143",
            "m",
            "current_pipeline_truth",
            "current pipeline AVL/geometry manifests",
            "Current pipeline half-span evidence unless superseded by newer authority.",
            "Do not replace with 16.5 m for RFQ/shop/procurement truth.",
            "yes, with source and replacement condition",
            "not alone; procurement needs repaired station/span manifest",
            "yes, if newer geometry invalidates it",
            "Promoted geometry manifest and station schedule that reconciles aero, rib, splice, and shop bases.",
        ),
        _authority_row(
            "local_splice_half_span_16p5",
            "span / half-span / station / rib spacing",
            "16.5",
            "m",
            "screening_estimate",
            "local structural/splice screening",
            "May appear as local/splice screening reference.",
            "Must not be current pipeline half-span, RFQ control span, shop span, or procurement truth.",
            "yes, only when labeled local/splice screening and not procurement truth",
            "no",
            "yes, as a conflict until reconciled",
            "Reconcile with 17.166143 m pipeline half-span and controlled station manifest.",
        ),
        _authority_row(
            "wo003_stage0_power_warning_minus9",
            "drag / power / mission margin",
            "-9",
            "W",
            "screening_estimate",
            "WO-003 Stage-0 quick-screen",
            "Power-budget watch item only.",
            "Must not be latest full-pipeline mission verdict, WO-006 conclusion, or release fail/pass.",
            "yes, only as Stage-0 warning",
            "no",
            "yes, only after repaired mission/power rerun",
            "Re-run mission/power after mass/span authority repair and propulsion/aero lane separation.",
        ),
        _authority_row(
            "p1_c04_original_peel_margin",
            "structure margin / C04 / coupon FEM",
            "-0.893",
            "margin",
            "screening_estimate",
            "P1 local load-path analytical screen",
            "Fail evidence for original eccentric peel path.",
            "Must not be hidden by installed-fix readiness language.",
            "yes, as fail evidence and local screening",
            "no",
            "yes, if local FEM/coupon shows unrecoverable blocker",
            "Coupon/local FEM, adhesive/tube-wall/collar allowables, and load-path review.",
        ),
        _authority_row(
            "p1_c04_installed_fix_margin",
            "structure margin / C04 / coupon FEM",
            "0.8876",
            "margin",
            "screening_estimate",
            "P1 installed-fix local surrogate",
            "May support coupon/local FEM readiness only.",
            "Must not be final aircraft, adhesive, laminate, buckling, or hardware sign-off.",
            "yes, only inside readiness boundary",
            "no",
            "yes, if coupon/local FEM fails",
            "Physical coupon/local FEM and supplier allowables.",
        ),
        _authority_row(
            "wo005_rfq_pack",
            "spar / splice / RFQ / procurement",
            "WO-005",
            "verdict",
            "conflict_blocked",
            "Baseline A release output",
            "Draft/vendor-screening only; does not block bounded WO-006 aero calibration.",
            "Must not be purchase-ready, supplier selection, shop drawing release, or procurement truth.",
            "yes, only as draft/vendor-screening and blocked for release/procurement",
            "no",
            "yes, vendor data can trigger review",
            "Mass/span authority reconciliation plus vendor response and station manifest repair.",
        ),
        _authority_row(
            "wo006_bounded_su2_validation",
            "drag / power / mission margin",
            "WO-006",
            "work_order",
            "current_pipeline_truth",
            "data-authority restoration review",
            "May proceed only as bounded main-wing aero calibration using 98.5 kg and current pipeline span authority unless explicitly labeled sensitivity.",
            "Must not be release truth, RFQ/procurement truth, full mission sign-off, structural sign-off, or final aircraft sign-off.",
            "yes, with bounded calibration caveats",
            "no",
            "yes, if bounded SU2 drag/power deltas exceed Baseline A reopen thresholds after review",
            "Upgrade only after full mission/aero/propulsion integration and authority review.",
        ),
    ]


def _authority_row(
    authority_id: str,
    topic: str,
    number: str,
    unit: str,
    authority_class: str,
    lane: str,
    allowed: str,
    disallowed: str,
    may_docs: str,
    may_procurement: str,
    may_reopen: str,
    upgrade: str,
) -> dict[str, str]:
    return {
        "authority_id": authority_id,
        "engineering_topic": topic,
        "important_number": number,
        "unit": unit,
        "authority_class": authority_class,
        "source_lane": lane,
        "allowed_use": allowed,
        "disallowed_use": disallowed,
        "may_appear_in_readme_current_mainline_release_docs": may_docs,
        "may_be_used_for_procurement": may_procurement,
        "may_affect_baseline_A_reopen": may_reopen,
        "trust_upgrade_requirement": upgrade,
    }


def _gate_debt_rows(claims: Sequence[Claim]) -> list[dict[str, str]]:
    rows = [
        {
            "item": "scripts/build_baseline_a_release.py",
            "classification": "keep_current",
            "reason": "Reads P1 generated mass/CG closure but emits authority metadata, keeps the aggregate as suspect screening evidence, and unblocks only bounded WO-006.",
            "recommended_action": "Keep the checker in CI/manual verification before release wording changes.",
        },
        {
            "item": "scripts/build_carbon_tube_rfq_pack.py",
            "classification": "keep_current",
            "reason": "RFQ pack stays draft/vendor-screening and labels 16.5 m as local/splice screening only while WO-006 proceeds separately.",
            "recommended_action": "Do not restore procurement wording without station/span and vendor evidence.",
        },
        {
            "item": "tests/test_baseline_a_release_builder.py",
            "classification": "keep_current",
            "reason": "Now asserts authority classification instead of stale current truth.",
            "recommended_action": "Keep authority assertions when release-builder wording changes.",
        },
        {
            "item": "tests/test_build_carbon_tube_rfq_pack.py",
            "classification": "keep_current",
            "reason": "Now asserts draft/vendor-screening and release/procurement-only blocker language.",
            "recommended_action": "Keep draft-only assertions until procurement authority is restored.",
        },
        {
            "item": "output/phase*",
            "classification": "legacy_only",
            "reason": "Old output phases can contain useful evidence but are not current Baseline A authority.",
            "recommended_action": "Cite only as legacy_or_experiment unless CURRENT_MAINLINE explicitly promotes a specific artifact.",
        },
    ]
    risky_tests = [
        claim for claim in claims if claim.source_lane == "tests" and claim.current_authority_class in {"conflict_blocked", "screening_estimate"}
    ]
    for claim in risky_tests[:20]:
        if claim.file in {
            "tests/test_baseline_a_data_authority.py",
            "tests/test_baseline_a_release_builder.py",
            "tests/test_build_carbon_tube_rfq_pack.py",
        }:
            continue
        rows.append(
            {
                "item": f"{claim.file}:{claim.line}",
                "classification": "repair_needed",
                "reason": f"Test references authority-sensitive value: {claim.raw_text[:160]}",
                "recommended_action": "Label as legacy/screening fixture or replace with authority-class assertion.",
            }
        )
    return rows


def _iter_check_scope_files(repo_root: Path) -> Iterable[Path]:
    for rel in sorted(CHECK_SCOPE_FILES):
        path = repo_root / rel
        if path.exists():
            yield path
    release = repo_root / "output" / "baseline_A_team_release"
    if release.exists():
        for path in _walk_text_files(release, repo_root):
            name = path.name
            if name.startswith("data_authority_"):
                continue
            yield path


def _scan_files(repo_root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    roots: list[Path] = []
    for rel in ("README.md", "CURRENT_MAINLINE.md", "AGENTS.md"):
        path = repo_root / rel
        if path.exists():
            roots.append(path)
    for rel in ("docs", "scripts", "src", "tests", "configs", "config", "data"):
        path = repo_root / rel
        if path.exists():
            roots.append(path)
    output = repo_root / "output"
    if output.exists():
        for pattern in (
            "baseline_A_team_release",
            "current_pathfinder*",
            "go_mode_main_wing_candidate/final_candidate_package",
            "phase*",
        ):
            roots.extend(sorted(output.glob(pattern)))

    files: list[Path] = []
    skipped: list[dict[str, str]] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            if _is_generated_audit_artifact(root, repo_root):
                continue
            if _is_text_candidate(root):
                resolved = root.resolve()
                if resolved not in seen:
                    files.append(root)
                    seen.add(resolved)
            else:
                skipped.append(_skip_row(root, repo_root, "non_text_or_binary"))
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name for name in dirnames if name not in SKIP_DIR_NAMES and not name.endswith(".egg-info")
            ]
            for skipped_dir in sorted(set(os.listdir(dirpath)) - set(dirnames) - set(filenames)):
                if skipped_dir in SKIP_DIR_NAMES or skipped_dir.endswith(".egg-info"):
                    skipped.append(_skip_row(Path(dirpath) / skipped_dir, repo_root, "cache_vendor_venv_or_git_internal"))
            for filename in filenames:
                path = Path(dirpath) / filename
                if _is_generated_audit_artifact(path, repo_root):
                    continue
                if not _is_text_candidate(path):
                    skipped.append(_skip_row(path, repo_root, "non_text_or_binary"))
                    continue
                if path.stat().st_size > MAX_TEXT_BYTES:
                    skipped.append(_skip_row(path, repo_root, "text_file_larger_than_scan_limit"))
                    continue
                resolved = path.resolve()
                if resolved not in seen:
                    files.append(path)
                    seen.add(resolved)
    files.sort(key=lambda p: _rel(p, repo_root))
    return files, skipped


def _is_generated_audit_artifact(path: Path, repo_root: Path) -> bool:
    return _rel(path, repo_root) in GENERATED_AUDIT_ARTIFACTS


def _walk_text_files(root: Path, repo_root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            if _is_text_candidate(path) and path.stat().st_size <= MAX_TEXT_BYTES:
                yield path


def _is_text_candidate(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    try:
        chunk = path.read_bytes()[:2048]
    except OSError:
        return False
    return b"\0" not in chunk


def _iter_text_lines(path: Path) -> Iterable[tuple[int, str]]:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                yield line_number, line.rstrip("\n")
    except OSError:
        return


def _write_claim_inventory(
    csv_path: Path,
    json_path: Path,
    claims: Sequence[Claim],
    *,
    files_scanned: int,
    skipped: Sequence[dict[str, str]],
) -> None:
    _write_csv_dicts(csv_path, CLAIM_FIELDS, [asdict(claim) for claim in claims])
    _write_json(
        json_path,
        {
            "schema_version": "baseline_a_data_authority_claim_inventory_v1",
            "files_scanned": files_scanned,
            "claims_extracted": len(claims),
            "skipped_paths": list(skipped),
            "claims": [asdict(claim) for claim in claims],
        },
    )


def _render_conflict_register_md(
    conflicts: Sequence[dict[str, str]], violations: Sequence[AuthorityViolation]
) -> str:
    lines = [
        "# Baseline A Data-Authority Conflict Register",
        "",
        "Verdict: `baseline_A_data_authority_restored_wo006_unblocked` for bounded aero calibration only.",
        "",
        "This register is an adversarial sweep result. It classifies old outputs and generated reports as evidence, not authority, unless the authority table says otherwise. Remaining conflicts block release/procurement/final-signoff claims, but do not block bounded WO-006 SU2 validation when it uses the authority table basis.",
        "",
        "## Remaining Conflict Classification",
        "",
        "| ID | Category | Risk | Blocking status | WO-006 classification | Summary | Required repair |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in conflicts:
        lines.append(
            "| {conflict_id} | {category} | {risk_level} | {blocking_status} | {wo006_unblock_classification} | {summary} | {required_repair} |".format(
                **row
            )
        )
    lines.extend(["", "## Current-Channel Violations"])
    if violations:
        for violation in violations:
            lines.append(
                f"- `{violation.rule_id}` at `{violation.file}:{violation.line}`: {violation.raw_text}"
            )
    else:
        lines.append("- None after current wording repair.")
    lines.append("")
    return "\n".join(lines)


def _render_authority_audit_md(
    *,
    claims: Sequence[Claim],
    conflicts: Sequence[dict[str, str]],
    authority_rows: Sequence[dict[str, str]],
    files_scanned: int,
    skipped: Sequence[dict[str, str]],
    violations: Sequence[AuthorityViolation],
) -> str:
    class_counts: dict[str, int] = {}
    for claim in claims:
        class_counts[claim.current_authority_class] = class_counts.get(claim.current_authority_class, 0) + 1
    lines = [
        "# Baseline A Data-Authority Audit",
        "",
        "Verdict: `baseline_A_data_authority_restored_wo006_unblocked`.",
        "",
        "WO-006 may proceed only as bounded aero calibration. It is not release truth, not RFQ/procurement truth, not final aircraft sign-off, and must use 98.5 kg plus current pipeline span authority unless explicitly studying sensitivity.",
        "",
        f"- Files scanned: `{files_scanned}`",
        f"- Claims extracted: `{len(claims)}`",
        f"- Blocking current-channel violations after repair: `{len(violations)}`",
        f"- Skipped paths recorded: `{len(skipped)}`",
        "",
        "## Authority Class Counts",
        "",
    ]
    for authority_class in sorted(class_counts):
        lines.append(f"- `{authority_class}`: {class_counts[authority_class]}")
    lines.extend(
        [
            "",
            "## Governing Authority Table",
            "",
            "| ID | Topic | Number | Class | Allowed use | Disallowed use | Procurement |",
            "|---|---|---:|---|---|---|---|",
        ]
    )
    for row in authority_rows:
        lines.append(
            f"| `{row['authority_id']}` | {row['engineering_topic']} | {row['important_number']} {row['unit']} | `{row['authority_class']}` | {row['allowed_use']} | {row['disallowed_use']} | {row['may_be_used_for_procurement']} |"
        )
    lines.extend(
        [
            "",
            "## Remaining Conflict Classification",
            "",
        ]
    )
    for row in conflicts:
        if row["risk_level"] in {"blocking", "high"}:
            lines.append(
                f"- `{row['conflict_id']}` {row['category']}: `{row['wo006_unblock_classification']}`. {row['summary']}"
            )
    lines.extend(["", "## Scan Boundaries"])
    if skipped:
        lines.append("Skipped paths were recorded because they were binary, cache/vendor/venv/git internals, or too large for safe text scan:")
        for row in skipped[:100]:
            lines.append(f"- `{row['path']}`: {row['reason']}")
        if len(skipped) > 100:
            lines.append(f"- plus `{len(skipped) - 100}` additional skipped paths in the JSON inventory metadata")
    else:
        lines.append("- No skipped paths.")
    lines.append("")
    return "\n".join(lines)


def _render_gate_debt_md(rows: Sequence[dict[str, str]]) -> str:
    lines = [
        "# Baseline A Gate Debt Register",
        "",
        "This register tracks docs/scripts/tests that encode stale assumptions or old constants.",
        "",
        "| Item | Classification | Reason | Recommended action |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['item']}` | `{row['classification']}` | {row['reason']} | {row['recommended_action']} |"
        )
    lines.append("")
    lines.extend(
        [
            "Classification key:",
            "",
            "- `keep_current`: safe current contract.",
            "- `repair_needed`: must be fixed before release/WO-006/RFQ use.",
            "- `legacy_only`: useful only as old evidence.",
            "- `delete_candidate_later`: do not delete now; consider after migration.",
            "- `needs_owner_decision`: requires user/project owner decision.",
            "",
        ]
    )
    return "\n".join(lines)


def _render_channel_hygiene_md(skipped: Sequence[dict[str, str]]) -> str:
    lines = [
        "# Repo Channel Hygiene Plan",
        "",
        "Baseline A data authority is restored only for bounded WO-006 aero calibration. Future AI agents must not treat arbitrary generated outputs as current truth.",
        "",
        "## Allowed Truth Sources",
        "",
        "- Latest explicit user instruction.",
        "- `CURRENT_MAINLINE.md`, after it names an authority table or current manifest.",
        "- `README.md` only as an entry point, not as a replacement for the authority table.",
        "- `output/baseline_A_team_release/data_authority_table.csv` and `.json` for the known contested numbers.",
        "- Current pipeline geometry manifests only when they are cited by the authority table or current mainline.",
        "",
        "## Evidence Only",
        "",
        "- `output/baseline_A_team_release/` generated reports and CSV/JSON files.",
        "- `output/current_pathfinder*/` generated pathfinder reports.",
        "- `output/go_mode_main_wing_candidate/final_candidate_package/` candidate artifacts.",
        "- `docs/reports/*` reports, unless `CURRENT_MAINLINE.md` promotes a specific report as current authority.",
        "",
        "## Legacy / Experiment Only",
        "",
        "- `output/phase*` folders unless the current mainline explicitly promotes a specific artifact.",
        "- Old medium-search, one-off design-space, or manually edited generated output.",
        "- External manuals, papers, and vendor references: useful background, not Baseline A authority.",
        "",
        "## Generated Outputs That Must Not Be Promoted Without Authority Table Entry",
        "",
        "- P1 mass-closure aggregate `106.828608 kg`.",
        "- Local/splice screening half-span `16.5 m`.",
        "- Stage-0 `-9 W` power warning.",
        "- Coupon/FEM readiness or analytical margin pass language.",
        "- RFQ/vendor screening artifacts.",
        "",
        "## Safe Citation Pattern For Old Outputs",
        "",
        "Use this shape: `old/path/file.ext reports X as legacy_or_experiment evidence for Y; it is not current Baseline A authority because Z.`",
        "",
        "## WO-005 / WO-006 Rule",
        "",
        "- WO-005 remains draft/vendor-screening only; RFQ/procurement remains blocked.",
        "- WO-006 SU2 may proceed only as bounded aero calibration using 98.5 kg and current pipeline span authority unless explicitly labeled sensitivity.",
        "- WO-006 output is not release truth, not RFQ/procurement truth, and not final aircraft sign-off.",
        "- QPROP/XROTOR must remain a propulsion lane and cannot pass C04/rib/structural blockers.",
        "",
        "## Recorded Skips",
        "",
    ]
    if skipped:
        lines.append("The scan recorded skipped paths in `data_authority_claim_inventory.json`; common reasons are binary files, cache/vendor/venv/git internals, or files over the safe text-scan limit.")
    else:
        lines.append("No skipped paths were recorded in this audit run.")
    lines.append("")
    return "\n".join(lines)


def _write_csv_dicts(path: Path, fields: Sequence[str], rows: Sequence[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _skip_row(path: Path, repo_root: Path, reason: str) -> dict[str, str]:
    return {"path": _rel(path, repo_root), "reason": reason}


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _normalize(line: str) -> str:
    return " ".join(line.lower().split())


def _has_any(text: str, patterns: Iterable[str]) -> bool:
    return any(pattern.lower() in text for pattern in patterns)


def _is_safe_screening_context(normalized: str) -> bool:
    return _has_any(
        normalized,
        (
            "suspect",
            "screening aggregate",
            "screening mass",
            "screening_mass",
            "p1 screening",
            "p1_screening",
            "legacy/pre-ledger",
            "not current",
            "not design",
            "not truth",
            "screening_aggregate",
        ),
    )


def _mentions_16p5(normalized: str) -> bool:
    return (
        "16.5" in normalized
        or "16.500" in normalized
        or "16p5" in normalized
    ) and _has_any(normalized, ("m", "span", "half", "rfq", "procurement", "shop"))


def _mentions_minus_9_w(normalized: str) -> bool:
    return "-9 w" in normalized or "-9w" in normalized or "−9 w" in normalized


if __name__ == "__main__":
    raise SystemExit(main())
