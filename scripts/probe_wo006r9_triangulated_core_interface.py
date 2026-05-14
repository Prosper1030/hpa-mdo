#!/usr/bin/env python3
"""Probe WO-006R9 Baseline A preserved-triangulated core interface.

R7 localized the preserved-core quality failure to bad pyramids attached to
native preserved BL outer-interface quads.  This probe uses the same Baseline A
owned BL block but preserves the core boundary as triangles so Gmsh HXT can tet
fill the core without quad-to-pyramid transition elements.

This is still mesh-handoff evidence only.  It must not emit a CFD completion
claim or a Baseline A coefficient.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    evaluate_boundary_layer_core_merge_gate,
    write_boundary_layer_block_core_tet_mesh,
)
from hpa_meshing.mesh_native.near_wall_block import (  # noqa: E402
    BoundaryLayerBlockSpec,
    build_boundary_layer_core_interface_surface,
    build_wing_boundary_layer_block,
)
from hpa_meshing.mesh_native.wing_surface import (  # noqa: E402
    SurfaceMesh,
    build_farfield_box_surface,
    validate_surface_mesh,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    BL_GROWTH_RATIO,
    BL_LAYERS,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


SCHEMA_VERSION = "wo006r9_triangulated_core_interface.v1"
DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006r9_triangulated_core_interface_probe"


def summarize_triangulated_core_probe(
    core_report: Mapping[str, Any],
    *,
    merge_gate: Mapping[str, Any],
) -> dict[str, Any]:
    quality_gate = core_report.get("mesh_quality_gate") or {}
    quality_metrics = core_report.get("quality_metrics") or {}
    coupling = core_report.get("bl_block_coupling") or {}
    conformality = core_report.get("interface_conformality") or {}
    sizing = core_report.get("mesh_sizing") or {}

    blockers: list[str] = []
    evidence_flags: list[str] = []
    if core_report.get("status") != "meshed":
        blockers.append("core_probe_not_meshed")
    if sizing.get("preserved_boundary_representation") != "triangulated":
        blockers.append("core_boundary_not_triangulated")
    if quality_gate.get("status") != "pass":
        blockers.append("core_mesh_quality_not_pass")
    elif (
        int(quality_metrics.get("pyramid_element_count") or 0) == 0
        and int(quality_metrics.get("non_positive_min_sicn_count") or 0) == 0
        and int(quality_metrics.get("non_positive_min_sige_count") or 0) == 0
        and int(quality_metrics.get("non_positive_volume_count") or 0) == 0
    ):
        evidence_flags.append("core_quality_repaired_by_triangulated_interface")
    if conformality.get("can_merge_with_owned_bl_block") is not True:
        blockers.append("core_interface_not_preserved")
    if coupling.get("can_merge_core_with_bl_block") is not True:
        blockers.append("bl_core_coupling_incomplete")
    if merge_gate.get("can_write_bl_mesh_handoff") is not True:
        blockers.extend(str(item) for item in merge_gate.get("blockers") or [])

    blockers = _dedupe(blockers)
    status = "pass" if not blockers else "blocked"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
        "coefficient_interpretable": False,
        "core_quality_repair_status": str(quality_gate.get("status") or "unknown"),
        "blockers": blockers,
        "evidence_flags": evidence_flags,
        "core_probe": {
            "mesh_path": core_report.get("mesh_path"),
            "su2_path": core_report.get("su2_path"),
            "node_count": core_report.get("node_count"),
            "volume_element_count": core_report.get("volume_element_count"),
            "volume_element_type_counts": core_report.get("volume_element_type_counts"),
            "mesh_quality_gate": quality_gate,
            "quality_metrics": {
                "tetra_element_count": quality_metrics.get("tetra_element_count"),
                "pyramid_element_count": quality_metrics.get("pyramid_element_count"),
                "non_positive_min_sicn_count": quality_metrics.get(
                    "non_positive_min_sicn_count"
                ),
                "non_positive_min_sige_count": quality_metrics.get(
                    "non_positive_min_sige_count"
                ),
                "non_positive_volume_count": quality_metrics.get(
                    "non_positive_volume_count"
                ),
                "min_sicn": quality_metrics.get("min_sicn"),
                "min_sige": quality_metrics.get("min_sige"),
                "min_volume": quality_metrics.get("min_volume"),
            },
            "interface_conformality": conformality,
            "bl_block_coupling": coupling,
            "mesh_sizing": sizing,
        },
        "merge_gate": dict(merge_gate),
        "engineering_read": (
            "Triangulated preserved core boundary removes the R7 bad-pyramid family, "
            "but Baseline A still lacks a merged BL+core SU2 handoff."
            if "core_quality_repaired_by_triangulated_interface" in evidence_flags
            else "Triangulated preserved core boundary did not clear core quality; keep "
            "debugging mesh topology before any SU2 ladder."
        ),
        "trust_boundary": (
            "This probe is mesh-interface evidence only. It runs no SU2 solver and "
            "does not provide CL/CD/Cm or grid-convergence evidence."
        ),
    }


def run_triangulated_core_probe(
    *,
    block: Any,
    core_interface: SurfaceMesh,
    output_dir: Path,
    mesh_size: float,
    farfield_mesh_size: float,
    gmsh_threads: int = 4,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    probe_dir = output_dir / "core_probe_artifacts" / "triangulated_interface_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    farfield = build_farfield_box_surface(
        core_interface,
        upstream_factor=2.0,
        downstream_factor=4.0,
        lateral_factor=2.0,
        vertical_factor=2.0,
    )
    start = time.monotonic()
    core_report = write_boundary_layer_block_core_tet_mesh(
        block,
        farfield,
        probe_dir / "core_triangulated_interface_probe.msh",
        su2_path=probe_dir / "core_triangulated_interface_probe.su2",
        mesh_size=mesh_size,
        farfield_mesh_size=farfield_mesh_size,
        preserve_boundary_mesh=True,
        preserved_boundary_representation="triangulated",
        gmsh_threads=gmsh_threads,
        mesh_algorithm3d=10,
    )
    _write_json(probe_dir / "core_triangulated_interface_probe_report.json", core_report)
    merge_gate = evaluate_boundary_layer_core_merge_gate(core_report, merged_mesh_path=None)
    summary = summarize_triangulated_core_probe(core_report, merge_gate=merge_gate)
    summary["elapsed_s"] = time.monotonic() - start
    summary["output_dir"] = str(output_dir)
    summary["report_path"] = str(output_dir / "triangulated_core_interface_summary.json")
    _write_json(output_dir / "triangulated_core_interface_summary.json", summary)
    (output_dir / "triangulated_core_interface_report.md").write_text(
        render_markdown_report(summary),
        encoding="utf-8",
    )
    return summary


def run_campaign(
    *,
    output_dir: Path,
    clean: bool = True,
    points_per_side: int = 16,
    spanwise_subdivisions: int = 2,
    mesh_size: float = 1.0,
    farfield_mesh_size: float = 8.0,
    gmsh_threads: int = 4,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
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
    core_interface = build_boundary_layer_core_interface_surface(block)
    validate_surface_mesh(
        core_interface,
        allowed_markers=frozenset({"bl_outer_interface", "wake_cut", "span_cap"}),
        required_markers=("bl_outer_interface", "wake_cut", "span_cap"),
    )
    summary = run_triangulated_core_probe(
        block=block,
        core_interface=core_interface,
        output_dir=output_dir,
        mesh_size=mesh_size,
        farfield_mesh_size=farfield_mesh_size,
        gmsh_threads=gmsh_threads,
    )
    summary["baseline_a_authority"] = {
        "source": "current GO Baseline A geometry via load_campaign_geometry",
        "points_per_side": int(points_per_side),
        "spanwise_subdivisions": int(spanwise_subdivisions),
        "bl_first_height_m": BL_FIRST_HEIGHT_M,
        "bl_growth_ratio": BL_GROWTH_RATIO,
        "bl_layers": BL_LAYERS,
    }
    _write_json(output_dir / "triangulated_core_interface_summary.json", summary)
    (output_dir / "triangulated_core_interface_report.md").write_text(
        render_markdown_report(summary),
        encoding="utf-8",
    )
    return summary


def render_markdown_report(summary: Mapping[str, Any]) -> str:
    core = summary.get("core_probe") or {}
    quality = core.get("quality_metrics") or {}
    coupling = core.get("bl_block_coupling") or {}
    return "\n".join(
        [
            "# WO-006R9 Triangulated Core Interface Probe",
            "",
            "This is Baseline A mesh-interface evidence only, not CFD coefficient evidence.",
            "",
            "## Result",
            "",
            f"- status: `{summary.get('status')}`",
            f"- GOAL_STATUS: `{summary.get('goal_status')}`",
            f"- CFD_STATUS: `{summary.get('cfd_status')}`",
            f"- coefficient interpretable: `{summary.get('coefficient_interpretable')}`",
            f"- blockers: `{summary.get('blockers')}`",
            f"- evidence flags: `{summary.get('evidence_flags')}`",
            "",
            "## Core Mesh",
            "",
            f"- nodes: `{core.get('node_count')}`",
            f"- volume elements: `{core.get('volume_element_count')}`",
            f"- volume element types: `{core.get('volume_element_type_counts')}`",
            f"- tetra count: `{quality.get('tetra_element_count')}`",
            f"- pyramid count: `{quality.get('pyramid_element_count')}`",
            f"- non-positive SICN/SIGE/volume: `{quality.get('non_positive_min_sicn_count')}` / `{quality.get('non_positive_min_sige_count')}` / `{quality.get('non_positive_volume_count')}`",
            "",
            "## Coupling",
            "",
            f"- coupling status: `{coupling.get('status')}`",
            f"- unmatched core faces: `{coupling.get('unmatched_core_interface_face_count')}`",
            f"- unmatched BL faces: `{coupling.get('unmatched_bl_boundary_face_count')}`",
            "",
            "## Engineering Read",
            "",
            str(summary.get("engineering_read")),
            "",
        ]
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--points-per-side", type=int, default=16)
    parser.add_argument("--spanwise-subdivisions", type=int, default=2)
    parser.add_argument("--mesh-size", type=float, default=1.0)
    parser.add_argument("--farfield-mesh-size", type=float, default=8.0)
    parser.add_argument("--gmsh-threads", type=int, default=4)
    args = parser.parse_args(argv)
    summary = run_campaign(
        output_dir=args.output_dir,
        clean=not args.no_clean,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        mesh_size=args.mesh_size,
        farfield_mesh_size=args.farfield_mesh_size,
        gmsh_threads=args.gmsh_threads,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
