#!/usr/bin/env python3
"""Probe WO-006R10 near-wall core-interface closure policy.

WO-006AD now produces a watertight near-wall external boundary after the
layer-0 sharp-TE seam stitch. This probe checks the next question before any
Gmsh/SU2 ladder attempt: can the core-facing portion of that near-wall boundary
be used as a valid core inner surface without borrowing physical wall faces as
closure?

It is topology/policy evidence only, not CFD coefficient evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    WingBoundaryLayerBlock,
    build_wing_boundary_layer_block,
)
from probe_wo006ad_near_wall_merged_volume_candidate import (  # noqa: E402
    MergedVolumeCandidate,
    build_near_wall_merged_volume_candidate,
    merged_boundary_face_rows,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r10_near_wall_core_closure_probe"
CORE_EXCLUDED_PHYSICAL_ROLES = frozenset({"wing_wall", "physical_wall_edge_receiver"})


def summarize_near_wall_core_closure(
    block: WingBoundaryLayerBlock,
    candidate: MergedVolumeCandidate,
) -> dict[str, Any]:
    boundary_rows = merged_boundary_face_rows(block, candidate)
    full_topology = boundary_topology(boundary_rows)
    core_rows = [
        row for row in boundary_rows
        if str(row.get("role")) not in CORE_EXCLUDED_PHYSICAL_ROLES
    ]
    core_topology = boundary_topology(core_rows)
    core_wall_edge_gap = core_wall_edge_gap_audit(
        boundary_rows=boundary_rows,
        core_rows=core_rows,
    )
    full_shell_policy = full_shell_core_interface_policy(boundary_rows)

    blockers: list[str] = []
    if full_topology.get("status") != "watertight":
        blockers.append("near_wall_full_boundary_not_watertight")
    if core_topology.get("status") != "watertight":
        blockers.append("core_facing_surface_not_watertight")
    if full_shell_policy.get("status") != "allowed":
        blockers.append("full_shell_contains_physical_wall_roles")
    if blockers:
        blockers.append("core_interface_not_materialized")
    blockers.extend(
        [
            "core_farfield_mesh_not_generated",
            "merged_mesh_quality_not_run",
            "su2_marker_readability_not_run",
            "near_wall_yplus_not_postprocessed",
            "solver_ladder_not_run",
        ]
    )

    can_generate_core_mesh = (
        full_topology.get("status") == "watertight"
        and core_topology.get("status") == "watertight"
        and full_shell_policy.get("status") == "allowed"
    )
    return {
        "schema_version": "wo006r10_near_wall_core_closure.v1",
        "status": (
            "core_interface_closure_ready_mesh_pending"
            if can_generate_core_mesh
            else "core_interface_closure_blocked"
        ),
        "can_generate_core_mesh": can_generate_core_mesh,
        "boundary_face_count": len(boundary_rows),
        "core_facing_boundary_face_count": len(core_rows),
        "boundary_role_counts": dict(sorted(_counts(row["role"] for row in boundary_rows).items())),
        "core_facing_role_counts": dict(sorted(_counts(row["role"] for row in core_rows).items())),
        "full_boundary_topology": full_topology,
        "core_facing_topology": core_topology,
        "core_wall_edge_gap_audit": core_wall_edge_gap,
        "full_shell_core_interface_policy": full_shell_policy,
        "blockers": blockers,
        "engineering_read": (
            "The repaired near-wall candidate is watertight as a full external shell, "
            "but the core-facing subset is still open unless physical-wall-adjacent "
            "faces are borrowed as closure. That would mis-own the wall for a core "
            "mesh, so the next repair must materialize a true core-interface closure "
            "before any mixed SU2 handoff or solver ladder."
            if not can_generate_core_mesh
            else "Core-facing near-wall surface closure is ready for a core/farfield mesh probe."
        ),
    }


def core_wall_edge_gap_audit(
    *,
    boundary_rows: Sequence[Mapping[str, Any]],
    core_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    full_edge_roles = edge_role_map(boundary_rows)
    core_edge_roles = edge_role_map(core_rows)
    bad_edges = {
        edge: roles
        for edge, roles in core_edge_roles.items()
        if len(roles) != 2
    }

    role_pair_counts: dict[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]], int] = {}
    sample_edges: list[dict[str, Any]] = []
    unexplained_edges: list[tuple[int, int]] = []
    physical_wall_edge_dependency_count = 0
    for edge in sorted(bad_edges):
        core_roles = tuple(sorted(str(role) for role in core_edge_roles.get(edge, [])))
        full_roles = tuple(sorted(str(role) for role in full_edge_roles.get(edge, [])))
        excluded_roles = tuple(
            sorted(
                str(role)
                for role in full_edge_roles.get(edge, [])
                if str(role) in CORE_EXCLUDED_PHYSICAL_ROLES
            )
        )
        pair_key = (core_roles, excluded_roles, full_roles)
        role_pair_counts[pair_key] = role_pair_counts.get(pair_key, 0) + 1
        explained_by_physical_wall_edge = "physical_wall_edge_receiver" in excluded_roles
        if explained_by_physical_wall_edge:
            physical_wall_edge_dependency_count += 1
        else:
            unexplained_edges.append(edge)
        if len(sample_edges) < 12:
            sample_edges.append(
                {
                    "edge_nodes": list(edge),
                    "core_roles": list(core_roles),
                    "excluded_physical_roles": list(excluded_roles),
                    "full_shell_roles": list(full_roles),
                    "explained_by_physical_wall_edge_receiver": explained_by_physical_wall_edge,
                }
            )

    unexplained_count = len(unexplained_edges)
    if not bad_edges:
        status = "pass"
    elif unexplained_count == 0 and physical_wall_edge_dependency_count == len(bad_edges):
        status = "blocked_by_physical_wall_edge_dependency"
    else:
        status = "blocked_unexplained_core_gap_edges"

    return {
        "schema_version": "wo006r10_core_wall_edge_gap_audit.v1",
        "status": status,
        "bad_edge_count": len(bad_edges),
        "core_bad_edge_incidence_counts": dict(
            sorted(_counts(len(roles) for roles in bad_edges.values()).items())
        ),
        "physical_wall_edge_dependency_count": physical_wall_edge_dependency_count,
        "unexplained_bad_edge_count": unexplained_count,
        "all_bad_edges_explained_by_physical_wall_edge_receiver": (
            bool(bad_edges)
            and unexplained_count == 0
            and physical_wall_edge_dependency_count == len(bad_edges)
        ),
        "role_pair_counts": [
            {
                "core_roles": list(core_roles),
                "excluded_physical_roles": list(excluded_roles),
                "full_shell_roles": list(full_roles),
                "count": count,
            }
            for (core_roles, excluded_roles, full_roles), count in sorted(
                role_pair_counts.items()
            )
        ],
        "sample_edges": sample_edges,
        "engineering_read": (
            "Every core-facing open edge is paired with a physical_wall_edge_receiver "
            "face in the full near-wall shell. This means the core closure blocker "
            "is a wall-edge ownership/materialization issue, not random Gmsh leakage."
            if status == "blocked_by_physical_wall_edge_dependency"
            else "Some core-facing open edges are not explained by the current physical-wall receiver accounting."
        ),
    }


def edge_role_map(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[int, int], list[str]]:
    edge_roles: dict[tuple[int, int], list[str]] = {}
    for row in rows:
        nodes = [int(node) for node in row.get("nodes", [])]
        role = str(row.get("role") or "unknown")
        for left, right in zip(nodes, [*nodes[1:], nodes[0]]):
            if left == right:
                continue
            edge = tuple(sorted((left, right)))
            edge_roles.setdefault(edge, []).append(role)
    return edge_roles


def boundary_topology(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    edge_counts: dict[tuple[int, int], int] = {}
    role_counts: dict[str, int] = {}
    for row in rows:
        nodes = [int(node) for node in row.get("nodes", [])]
        role = str(row.get("role") or "unknown")
        for left, right in zip(nodes, [*nodes[1:], nodes[0]]):
            if left == right:
                continue
            edge = tuple(sorted((left, right)))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    bad_edges = {
        edge: count
        for edge, count in edge_counts.items()
        if count != 2
    }
    for row in rows:
        nodes = [int(node) for node in row.get("nodes", [])]
        role = str(row.get("role") or "unknown")
        for left, right in zip(nodes, [*nodes[1:], nodes[0]]):
            if left == right:
                continue
            edge = tuple(sorted((left, right)))
            if edge in bad_edges:
                role_counts[role] = role_counts.get(role, 0) + 1
    return {
        "status": "watertight" if not bad_edges else "not_watertight",
        "edge_count": len(edge_counts),
        "bad_edge_count": len(bad_edges),
        "bad_edge_incidence_counts": dict(sorted(_counts(bad_edges.values()).items())),
        "bad_edge_role_touch_counts": dict(sorted(role_counts.items())),
    }


def full_shell_core_interface_policy(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    role_counts = _counts(row["role"] for row in rows)
    physical_roles_present = {
        role: int(role_counts.get(role, 0))
        for role in sorted(CORE_EXCLUDED_PHYSICAL_ROLES)
        if int(role_counts.get(role, 0)) > 0
    }
    return {
        "status": "forbidden" if physical_roles_present else "allowed",
        "physical_roles_present": physical_roles_present,
        "policy": (
            "Do not use the full near-wall external shell as a core interface when "
            "it includes physical wall or wall-edge receiver faces. Core mesh "
            "closure must be materialized on the core-facing side without changing "
            "the Baseline A external wall shape."
        ),
    }


def build_probe_summary(*, core_closure: Mapping[str, Any]) -> dict[str, Any]:
    ready = core_closure.get("status") == "core_interface_closure_ready_mesh_pending"
    return {
        "schema_version": "wo006r10_near_wall_core_closure_probe.v1",
        "verdict": (
            "near_wall_core_interface_closure_ready_not_handoff"
            if ready
            else "near_wall_core_interface_closure_blocked"
        ),
        "core_closure": dict(core_closure),
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "blocked_claims": [
            "full BL/core/farfield Gmsh mesh readiness",
            "SU2 marker/readability readiness",
            "medium/fine CFD ladder readiness",
            "CL/CD/Cm interpretation",
            "Baseline A drag or power truth",
        ],
        "engineering_read": core_closure.get("engineering_read"),
    }


def run_probe(
    *,
    output_dir: Path,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    geometry = load_campaign_geometry(
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )
    block = build_wing_boundary_layer_block(
        geometry.spec.wing_spec,
        BoundaryLayerBlockSpec(
            first_layer_height_m=BL_FIRST_HEIGHT_M,
            growth_ratio=BL_GROWTH_RATIO,
            layer_count=BL_LAYERS,
        ),
    )
    candidate = build_near_wall_merged_volume_candidate(block)
    core_closure = summarize_near_wall_core_closure(block, candidate)
    summary = build_probe_summary(core_closure=core_closure)
    summary.update(
        {
            "output_dir": str(output_dir),
            "geometry_source": str(geometry.section_table_path),
            "points_per_side": int(points_per_side),
            "spanwise_subdivisions": int(spanwise_subdivisions),
            "owned_bl_block": {
                "cell_count": len(block.cells),
                "boundary_marker_counts": block.boundary_marker_counts(),
                "quality": block.quality,
            },
        }
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "core_closure_rows.csv", core_closure_rows(core_closure))
    write_csv(
        output_dir / "core_wall_edge_gap_audit.csv",
        core_wall_edge_gap_rows(core_closure),
    )
    (output_dir / "near_wall_core_closure_report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    return summary


def core_closure_rows(core_closure: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "surface_set": "full_near_wall_boundary",
            "status": (core_closure.get("full_boundary_topology") or {}).get("status"),
            "bad_edge_count": (core_closure.get("full_boundary_topology") or {}).get(
                "bad_edge_count"
            ),
            "role_counts": core_closure.get("boundary_role_counts"),
        },
        {
            "surface_set": "core_facing_without_physical_roles",
            "status": (core_closure.get("core_facing_topology") or {}).get("status"),
            "bad_edge_count": (core_closure.get("core_facing_topology") or {}).get(
                "bad_edge_count"
            ),
            "role_counts": core_closure.get("core_facing_role_counts"),
        },
        {
            "surface_set": "full_shell_core_interface_policy",
            "status": (core_closure.get("full_shell_core_interface_policy") or {}).get(
                "status"
            ),
            "bad_edge_count": "",
            "role_counts": (
                core_closure.get("full_shell_core_interface_policy") or {}
            ).get("physical_roles_present"),
        },
    ]


def core_wall_edge_gap_rows(core_closure: Mapping[str, Any]) -> list[dict[str, Any]]:
    audit = core_closure.get("core_wall_edge_gap_audit") or {}
    rows: list[dict[str, Any]] = []
    for pair in audit.get("role_pair_counts") or []:
        rows.append(
            {
                "row_type": "role_pair_count",
                "status": audit.get("status"),
                "count": pair.get("count"),
                "core_roles": pair.get("core_roles"),
                "excluded_physical_roles": pair.get("excluded_physical_roles"),
                "full_shell_roles": pair.get("full_shell_roles"),
                "edge_nodes": "",
                "explained_by_physical_wall_edge_receiver": "",
            }
        )
    for sample in audit.get("sample_edges") or []:
        rows.append(
            {
                "row_type": "sample_edge",
                "status": audit.get("status"),
                "count": "",
                "core_roles": sample.get("core_roles"),
                "excluded_physical_roles": sample.get("excluded_physical_roles"),
                "full_shell_roles": sample.get("full_shell_roles"),
                "edge_nodes": sample.get("edge_nodes"),
                "explained_by_physical_wall_edge_receiver": sample.get(
                    "explained_by_physical_wall_edge_receiver"
                ),
            }
        )
    if not rows:
        rows.append(
            {
                "row_type": "summary",
                "status": audit.get("status"),
                "count": audit.get("bad_edge_count"),
                "core_roles": "",
                "excluded_physical_roles": "",
                "full_shell_roles": "",
                "edge_nodes": "",
                "explained_by_physical_wall_edge_receiver": audit.get(
                    "all_bad_edges_explained_by_physical_wall_edge_receiver"
                ),
            }
        )
    return rows


def render_report(summary: Mapping[str, Any]) -> str:
    closure = summary["core_closure"]
    gap_audit = closure.get("core_wall_edge_gap_audit") or {}
    return "\n".join(
        [
            "# WO-006R10 Near-Wall Core Closure Probe",
            "",
            "This is topology/policy evidence only, not CFD coefficient evidence.",
            "",
            f"GOAL_STATUS: `{summary['goal_status']}`",
            f"CFD_STATUS: `{summary['cfd_status']}`",
            f"- verdict: `{summary['verdict']}`",
            f"- geometry source: `{summary['geometry_source']}`",
            f"- points per side: `{summary['points_per_side']}`",
            f"- spanwise subdivisions: `{summary['spanwise_subdivisions']}`",
            f"- full boundary topology: `{(closure.get('full_boundary_topology') or {}).get('status')}`",
            f"- core-facing topology: `{(closure.get('core_facing_topology') or {}).get('status')}`",
            f"- core-facing bad edges: `{(closure.get('core_facing_topology') or {}).get('bad_edge_count')}`",
            f"- wall-edge gap audit: `{gap_audit.get('status')}`",
            f"- wall-edge dependency count: `{gap_audit.get('physical_wall_edge_dependency_count')}`",
            f"- unexplained core-facing bad edges: `{gap_audit.get('unexplained_bad_edge_count')}`",
            f"- full-shell policy: `{(closure.get('full_shell_core_interface_policy') or {}).get('status')}`",
            f"- can generate core mesh: `{closure.get('can_generate_core_mesh')}`",
            f"- blockers: `{closure.get('blockers')}`",
            f"- engineering read: {summary['engineering_read']}",
            "",
            "Blocked claims:",
            "- full BL/core/farfield Gmsh mesh readiness",
            "- SU2 marker/readability readiness",
            "- medium/fine CFD ladder readiness",
            "- CL/CD/Cm interpretation",
            "- Baseline A drag or power truth",
        ]
    ) + "\n"


def _counts(values: Sequence[Any]) -> dict[Any, int]:
    counts: dict[Any, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    args = parser.parse_args(argv)
    summary = run_probe(
        output_dir=args.output_dir,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
    )
    closure = summary["core_closure"]
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "full_boundary_status": closure["full_boundary_topology"]["status"],
                "core_facing_status": closure["core_facing_topology"]["status"],
                "core_wall_edge_gap_status": closure["core_wall_edge_gap_audit"]["status"],
                "can_generate_core_mesh": closure["can_generate_core_mesh"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
