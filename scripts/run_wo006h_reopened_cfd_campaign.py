#!/usr/bin/env python3
"""Summarize the reopened WO-006H CFD campaign with strict engineering gates.

This script does not turn mesh/debug evidence into aerodynamic truth. It reads
local attempt summaries, checks whether the missing serious cases are covered by
an executable HPC package, and emits one final verdict for the reopened campaign.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_INPUT_DIR = WO006_ROOT / "wo006h_reopened_cfd_campaign"
DEFAULT_PRIOR_DIR = WO006_ROOT / "wo006h_cfd_limit_scaling"
DEFAULT_OUTPUT_DIR = DEFAULT_INPUT_DIR
DEFAULT_HPC_PACKAGE_DIR = DEFAULT_INPUT_DIR / "hpc_executable_case"
REQUIRED_HPC_CASE_IDS = {
    "mesh_h005_hxt",
    "mesh_h004_hxt",
    "mesh_h004_delaunay",
    "bl_core_preserve_alg1_32x2",
    "bl_core_preserve_alg10_32x2",
}
ACCEPTABLE_VERDICTS = {
    "su2_baseline_cfd_physical_result_ready",
    "su2_baseline_cfd_low_confidence_ready",
    "su2_local_hard_limit_proven_with_executable_hpc_case",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prior-dir", type=Path, default=DEFAULT_PRIOR_DIR)
    parser.add_argument("--hpc-package-dir", type=Path, default=DEFAULT_HPC_PACKAGE_DIR)
    args = parser.parse_args(argv)

    attempts = collect_attempts(args.input_dir, args.prior_dir)
    hpc_case_ids = load_hpc_case_ids(args.hpc_package_dir / "case_matrix.csv")
    verdict = classify_reopened_verdict(attempts=attempts, hpc_case_ids=hpc_case_ids)
    summary = build_summary(
        attempts=attempts,
        hpc_case_ids=hpc_case_ids,
        hpc_package_dir=args.hpc_package_dir,
        verdict=verdict,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "wo006h_reopened_cfd_campaign_summary.json", summary)
    (args.output_dir / "wo006h_reopened_cfd_campaign_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    print(json.dumps({"verdict": verdict, "output_dir": str(args.output_dir)}, indent=2))
    return 0 if verdict in ACCEPTABLE_VERDICTS else 2


def collect_attempts(*roots: Path) -> list[dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("attempt_summary.json")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            payload = load_json(path)
            if not isinstance(payload, dict):
                continue
            payload.setdefault("source_path", str(path))
            if not payload.get("attempt_id"):
                payload["attempt_id"] = path.parent.name
            attempts.append(payload)
    return attempts


def classify_reopened_verdict(
    *,
    attempts: Sequence[Mapping[str, Any]],
    hpc_case_ids: Iterable[str],
) -> str:
    if _has_physical_result(attempts):
        return "su2_baseline_cfd_physical_result_ready"
    if _has_low_confidence_result(attempts):
        return "su2_baseline_cfd_low_confidence_ready"

    case_ids = set(hpc_case_ids)
    if (
        _has_serious_no_bl_success(attempts)
        and _has_failed_finer_no_bl_rungs(attempts)
        and _has_serious_bl_core_blocker(attempts)
        and REQUIRED_HPC_CASE_IDS.issubset(case_ids)
    ):
        return "su2_local_hard_limit_proven_with_executable_hpc_case"
    return "campaign_incomplete_not_acceptable"


def build_summary(
    *,
    attempts: Sequence[Mapping[str, Any]],
    hpc_case_ids: set[str],
    hpc_package_dir: Path,
    verdict: str,
) -> dict[str, Any]:
    gates = {
        "physical_result": _has_physical_result(attempts),
        "low_confidence_result": _has_low_confidence_result(attempts),
        "serious_no_bl_success": _has_serious_no_bl_success(attempts),
        "failed_finer_no_bl_rungs": _has_failed_finer_no_bl_rungs(attempts),
        "serious_bl_core_blocker": _has_serious_bl_core_blocker(attempts),
        "hpc_targets_missing_cases": REQUIRED_HPC_CASE_IDS.issubset(hpc_case_ids),
    }
    return {
        "schema_version": "wo006h_reopened_cfd_campaign_summary.v1",
        "verdict": verdict,
        "acceptable_final_verdict": verdict in ACCEPTABLE_VERDICTS,
        "authority_basis": {
            "design_gross_mass_kg": 98.5,
            "full_span_m": 34.332286,
            "half_span_m": 17.166143,
            "blocked_legacy_mass_kg": "106.828608 kg is suspect screening only",
            "blocked_legacy_half_span_m": "16.5 m is local/splice screening only",
        },
        "gate_status": gates,
        "hpc_package_dir": str(hpc_package_dir),
        "required_hpc_case_ids": sorted(REQUIRED_HPC_CASE_IDS),
        "observed_hpc_case_ids": sorted(hpc_case_ids),
        "attempt_count": len(attempts),
        "attempts": list(attempts),
        "engineering_read": engineering_read(verdict, gates),
        "blocked_claims": [
            "grid-independent Baseline A SU2 CL/CD/Cm",
            "BL-resolved local postprocessed y+",
            "drag/power calibration",
            "Baseline A reopen evidence",
            "RFQ/procurement truth",
            "final aircraft sign-off",
        ],
    }


def engineering_read(verdict: str, gates: Mapping[str, bool]) -> str:
    if verdict == "su2_local_hard_limit_proven_with_executable_hpc_case":
        return (
            "Local evidence now separates two facts: no-BL HXT can mesh a serious "
            "3.8M-cell control case, but finer no-BL rungs and BL/core routes fail "
            "at current surface/PLC/topology gates before credible viscous CFD. The "
            "HPC package targets those missing finer and BL/viscous cases rather "
            "than rerunning only already-successful coarser no-BL meshes."
        )
    return (
        "The reopened campaign has not met an acceptable WO-006H final verdict. "
        f"Gate status: {dict(gates)}"
    )


def render_report(summary: Mapping[str, Any]) -> str:
    gates = summary["gate_status"]
    lines = [
        "# WO-006H Reopened CFD Campaign",
        "",
        f"Verdict: `{summary['verdict']}`",
        "",
        "## Authority",
        "",
        "- design mass: `98.5 kg`",
        "- span: `34.332286 m` full / `17.166143 m` half",
        "",
        "## Gate Status",
        "",
        *[f"- {key}: `{value}`" for key, value in gates.items()],
        "",
        "## Engineering Read",
        "",
        str(summary["engineering_read"]),
        "",
        "## HPC Target Cases",
        "",
        *[f"- `{case_id}`" for case_id in summary["required_hpc_case_ids"]],
        "",
        "## Attempt Summary",
        "",
        f"- attempts read: `{summary['attempt_count']}`",
        "- coefficients remain non-interpretable unless a later final mesh/solver gate says otherwise",
        "",
        "## Key Local Evidence",
        "",
        *_selected_attempt_bullets(summary["attempts"]),
        "",
    ]
    return "\n".join(lines)


def _selected_attempt_bullets(attempts: Sequence[Mapping[str, Any]]) -> list[str]:
    selected: list[Mapping[str, Any]] = []
    for attempt in attempts:
        if _is_key_attempt(attempt):
            selected.append(attempt)
    if not selected:
        return ["- no key attempt summaries matched the reopened-campaign gates"]
    return [_format_attempt_bullet(attempt) for attempt in selected]


def _is_key_attempt(attempt: Mapping[str, Any]) -> bool:
    if _has_serious_no_bl_success([attempt]):
        return True
    mesh_size = _float_or_none(attempt.get("mesh_size"))
    if attempt.get("status") in {"failed", "timeout", "terminated"} and mesh_size is not None and mesh_size <= 0.05:
        text = f"{attempt.get('failure_code') or ''} {attempt.get('error') or ''}".lower()
        if any(token in text for token in ("hxt", "plc", "overlapping", "boundary mesh")):
            return True
    text = f"{attempt.get('attempt_id') or ''} {attempt.get('route') or ''} {attempt.get('error') or ''}".lower()
    return ("bl" in text or "core" in text) and attempt.get("status") in {"failed", "meshed", "timeout"}


def _format_attempt_bullet(attempt: Mapping[str, Any]) -> str:
    parts = [
        f"`{attempt.get('attempt_id') or 'unknown'}`",
        f"status `{attempt.get('status')}`",
    ]
    if attempt.get("mesh_size") is not None:
        parts.append(f"h `{attempt.get('mesh_size')}`")
    if attempt.get("mesh_algorithm3d") is not None:
        parts.append(f"Gmsh alg `{attempt.get('mesh_algorithm3d')}`")
    if attempt.get("volume_element_count") is not None:
        parts.append(f"cells `{attempt.get('volume_element_count')}`")
    if attempt.get("node_count") is not None:
        parts.append(f"nodes `{attempt.get('node_count')}`")
    if attempt.get("elapsed_seconds") is not None:
        elapsed = _float_or_none(attempt.get("elapsed_seconds"))
        if elapsed is not None:
            parts.append(f"elapsed `{elapsed:.2f} s`")
    if attempt.get("mesh_quality_status") is not None:
        parts.append(f"quality `{attempt.get('mesh_quality_status')}`")
    if attempt.get("unmatched_core_interface_face_count") is not None:
        parts.append(f"unmatched core `{attempt.get('unmatched_core_interface_face_count')}`")
    if attempt.get("unmatched_bl_boundary_face_count") is not None:
        parts.append(f"unmatched BL `{attempt.get('unmatched_bl_boundary_face_count')}`")
    if attempt.get("error"):
        parts.append(f"error `{attempt.get('error')}`")
    return "- " + "; ".join(parts)


def load_hpc_case_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = csv.DictReader(handle)
        return {str(row.get("case_id") or "") for row in rows if row.get("case_id")}


def _has_physical_result(attempts: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        attempt.get("coefficient_interpretable") is True
        and attempt.get("grid_independence_status") == "pass"
        and attempt.get("wall_or_bl_status") == "pass"
        for attempt in attempts
    )


def _has_low_confidence_result(attempts: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        attempt.get("coefficient_interpretable") is True
        and attempt.get("force_sanity_status") == "pass"
        and attempt.get("wall_or_bl_status") in {"pass", "justified_wall_function"}
        for attempt in attempts
    )


def _has_serious_no_bl_success(attempts: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        attempt.get("status") == "meshed"
        and attempt.get("boundary_layer_present") is False
        and int(attempt.get("volume_element_count") or 0) >= 3_500_000
        for attempt in attempts
    )


def _has_failed_finer_no_bl_rungs(attempts: Sequence[Mapping[str, Any]]) -> bool:
    hxt_failure = False
    alternate_failure = False
    for attempt in attempts:
        if attempt.get("status") not in {"failed", "timeout", "terminated"}:
            continue
        mesh_size = _float_or_none(attempt.get("mesh_size"))
        if mesh_size is None or mesh_size > 0.05:
            continue
        algorithm = int(attempt.get("mesh_algorithm3d") or 10)
        text = f"{attempt.get('failure_code') or ''} {attempt.get('error') or ''}".lower()
        topology_like = any(token in text for token in ("hxt", "plc", "overlapping", "boundary mesh"))
        if algorithm == 10 and topology_like:
            hxt_failure = True
        if algorithm != 10 and topology_like:
            alternate_failure = True
    return hxt_failure and alternate_failure


def _has_serious_bl_core_blocker(attempts: Sequence[Mapping[str, Any]]) -> bool:
    for attempt in attempts:
        attempt_id = str(attempt.get("attempt_id") or "")
        text = f"{attempt_id} {attempt.get('route') or ''} {attempt.get('error') or ''}".lower()
        elapsed = _float_or_none(attempt.get("elapsed_seconds")) or 0.0
        timeout = _float_or_none(attempt.get("timeout_seconds")) or 0.0
        if "bl" not in text and "core" not in text:
            continue
        if attempt.get("status") == "timeout" and timeout >= 900.0:
            return True
        if attempt.get("status") == "failed" and elapsed >= 300.0 and "plc" in text:
            return True
        if (
            attempt.get("boundary_layer_present") is True
            and attempt.get("status") == "meshed"
            and (
                attempt.get("mesh_quality_status") != "pass"
                or attempt.get("can_merge_core_with_bl_block") is not True
            )
        ):
            return True
    return False


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
