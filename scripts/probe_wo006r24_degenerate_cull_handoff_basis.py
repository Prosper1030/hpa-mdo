#!/usr/bin/env python3
"""Evaluate whether WO-006R23 degenerate star faces are safe to cull.

This is the bridge from "degenerate cells exist" to "the next blocker is the
mixed SU2 writer".  It only accepts culling when R22's global-star basis is
otherwise conformal and R23 proves every degenerate triangle is an unmarked
wake-receiver zero-area face.  It does not write the mixed mesh or run SU2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r24_degenerate_cull_handoff_basis_probe.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r24_degenerate_cull_handoff_basis_probe"
DEFAULT_R22_SUMMARY = WO006_ROOT / "wo006r22_global_star_split_basis_probe" / "summary.json"
DEFAULT_R23_SUMMARY = (
    WO006_ROOT / "wo006r23_degenerate_star_cell_localization_probe" / "summary.json"
)


def evaluate_degenerate_cull_basis(
    *,
    global_star_audit: Mapping[str, Any],
    localization: Mapping[str, Any],
) -> dict[str, Any]:
    blockers: list[str] = []
    degenerate_count = int(global_star_audit.get("degenerate_star_triangle_count") or 0)
    localized_count = int(localization.get("degenerate_star_triangle_count") or 0)
    records_by_role = {
        str(key): int(value)
        for key, value in dict(localization.get("records_by_role") or {}).items()
    }
    records_by_marker = {
        str(key): int(value)
        for key, value in dict(localization.get("records_by_marker") or {}).items()
    }

    if global_star_audit.get("status") != "global_star_split_basis_degenerate_reduction_required":
        blockers.append("global_star_basis_not_in_degenerate_reduction_state")
    if int(global_star_audit.get("unmatched_target_triangle_count") or 0) != 0:
        blockers.append("global_star_has_unmatched_target_triangles")
    if int(global_star_audit.get("internal_split_leak_face_count") or 0) != 0:
        blockers.append("global_star_has_internal_split_leaks")
    if int(global_star_audit.get("nonmanifold_split_face_count") or 0) != 0:
        blockers.append("global_star_has_nonmanifold_split_faces")
    if int(global_star_audit.get("non_positive_tet_count") or 0) != 0:
        blockers.append("global_star_has_non_positive_tets")
    if int(global_star_audit.get("matched_target_triangle_count") or 0) != int(
        global_star_audit.get("target_triangle_count") or -1
    ):
        blockers.append("global_star_target_triangles_not_fully_matched")
    if degenerate_count <= 0:
        blockers.append("global_star_has_no_degenerate_triangles_to_cull")
    if localized_count != degenerate_count:
        blockers.append("r23_localization_count_mismatch")
    if set(records_by_role) != {"wake_receiver"}:
        blockers.append("degenerate_records_include_non_wake_receiver_roles")
    if set(records_by_marker) != {""}:
        blockers.append("degenerate_records_include_owned_markers")
    if records_by_role.get("wake_receiver", 0) != degenerate_count:
        blockers.append("wake_receiver_degenerate_count_mismatch")
    if records_by_marker.get("", 0) != degenerate_count:
        blockers.append("empty_marker_degenerate_count_mismatch")

    ready = not blockers
    return {
        "schema_version": "wo006r24_degenerate_cull_basis.v1",
        "status": "degenerate_cull_basis_ready" if ready else "degenerate_cull_basis_blocked",
        "blockers": blockers,
        "culled_degenerate_triangle_count": degenerate_count if ready else 0,
        "degenerate_cell_count": int(localization.get("degenerate_cell_count") or 0),
        "records_by_role": records_by_role,
        "records_by_marker": records_by_marker,
        "engineering_read": (
            "All degenerate global-star triangles are unmarked wake-receiver zero-area "
            "faces, so the cull/reduction basis is ready for a mixed-mesh writer probe."
            if ready
            else "Degenerate global-star triangles are not yet proven safe to cull."
        ),
    }


def build_probe_summary(
    *,
    cull_basis: Mapping[str, Any],
    output_dir: Path,
    r22_summary_path: Path,
    r23_summary_path: Path,
) -> dict[str, Any]:
    ready = cull_basis.get("status") == "degenerate_cull_basis_ready"
    blockers = [
        "merged_mixed_bl_core_su2_mesh_missing",
        "near_wall_yplus_not_postprocessed",
        "solver_ladder_not_run",
    ]
    if not ready:
        blockers.insert(0, "degenerate_cull_basis_not_ready")
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": (
            "degenerate_cull_basis_ready_mixed_mesh_pending"
            if ready
            else "degenerate_cull_basis_blocked"
        ),
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "output_dir": str(output_dir),
        "r22_summary_path": str(r22_summary_path),
        "r23_summary_path": str(r23_summary_path),
        "degenerate_cull_basis": dict(cull_basis),
        "blockers": sorted(set(blockers)),
        "blocked_claims": [
            "merged BL+core SU2 handoff",
            "postprocessed near-wall y+",
            "SU2 coarse/medium/fine ladder",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
    }


def run_probe(
    *,
    output_dir: Path,
    r22_summary_path: Path = DEFAULT_R22_SUMMARY,
    r23_summary_path: Path = DEFAULT_R23_SUMMARY,
) -> dict[str, Any]:
    r22_summary = load_json(r22_summary_path)
    r23_summary = load_json(r23_summary_path)
    cull_basis = evaluate_degenerate_cull_basis(
        global_star_audit=r22_summary["global_star_split_basis"],
        localization=r23_summary,
    )
    summary = build_probe_summary(
        cull_basis=cull_basis,
        output_dir=output_dir,
        r22_summary_path=r22_summary_path,
        r23_summary_path=r23_summary_path,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "summary.json", summary)
    (output_dir / "degenerate_cull_handoff_basis_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def render_report(summary: Mapping[str, Any]) -> str:
    cull = summary["degenerate_cull_basis"]
    return "\n".join(
        [
            "# WO-006R24 Degenerate Cull Handoff Basis Probe",
            "",
            "This is pre-writer topology evidence, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- cull status: `{cull['status']}`",
            f"- culled degenerate triangles: `{cull['culled_degenerate_triangle_count']}`",
            f"- degenerate cells: `{cull['degenerate_cell_count']}`",
            f"- records by role: `{cull['records_by_role']}`",
            f"- records by marker: `{cull['records_by_marker']}`",
            f"- blockers: `{summary['blockers']}`",
            "",
            f"Engineering read: {cull['engineering_read']}",
            "",
        ]
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--r22-summary", type=Path, default=DEFAULT_R22_SUMMARY)
    parser.add_argument("--r23-summary", type=Path, default=DEFAULT_R23_SUMMARY)
    args = parser.parse_args(argv)
    summary = run_probe(
        output_dir=args.output_dir,
        r22_summary_path=args.r22_summary,
        r23_summary_path=args.r23_summary,
    )
    cull = summary["degenerate_cull_basis"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "cull_status": cull["status"],
                "culled_degenerate_triangles": cull["culled_degenerate_triangle_count"],
                "records_by_role": cull["records_by_role"],
                "records_by_marker": cull["records_by_marker"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
