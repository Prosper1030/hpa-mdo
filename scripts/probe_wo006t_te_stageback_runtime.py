#!/usr/bin/env python3
"""Probe global TE stageback as a WO-006 BL/wake topology repair.

This is a bounded meshing probe, not CFD completion evidence. WO-006T exists
because WO-006R/S hotspot diagnosis shows the remaining worst BL elements at
the aft/TE band. The probe tests whether a full-span TE stageback can be a
simple Gmsh repair, and records runtime/failure evidence when it cannot.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import multiprocessing as mp
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
HPA_MESHING_SRC = REPO_ROOT / "hpa_meshing_package" / "src"
for path in (SCRIPT_DIR, HPA_MESHING_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hpa_meshing.mesh_native.gmsh_polyhedral import (  # noqa: E402
    write_faceted_volume_mesh_with_boundary_layer,
)
from hpa_meshing.mesh_native.wing_surface import build_farfield_box_surface  # noqa: E402
from run_wo006r1_go_baseline_a_cfd_bridge import build_current_go_wing_surface  # noqa: E402
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006t_te_stageback_runtime_probe"


@dataclass(frozen=True)
class TEStagebackCase:
    case_id: str
    x_over_chord_min: float
    mesh_algorithm3d: int
    x_reference: str = "max"
    points_per_side: int = 16
    spanwise_subdivisions: int = 1
    boundary_layer_layers: int = 12
    boundary_layer_growth_ratio: float = 1.18
    mesh_size: float = 0.5
    wing_mesh_size: float = 0.25
    farfield_mesh_size: float = 4.0


DEFAULT_CASES = (
    TEStagebackCase("global_te_xc099_hxt", 0.99, 10),
    TEStagebackCase("global_te_xc099_alg1", 0.99, 1),
)


def run_probe(
    *,
    output_dir: Path,
    cases: Sequence[TEStagebackCase] = DEFAULT_CASES,
    timeout_seconds: float = 240.0,
    clean: bool = True,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        run_case_with_timeout(
            case=case,
            case_dir=output_dir / case.case_id,
            timeout_seconds=timeout_seconds,
        )
        for case in cases
    ]
    summary = build_probe_summary(rows)
    summary.update(
        {
            "output_dir": str(output_dir),
            "timeout_seconds": float(timeout_seconds),
            "cases": rows,
        }
    )
    write_json(output_dir / "summary.json", summary)
    write_csv(output_dir / "case_table.csv", rows)
    (output_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def run_case_with_timeout(
    *,
    case: TEStagebackCase,
    case_dir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue: mp.Queue = context.Queue()
    case_dir.mkdir(parents=True, exist_ok=True)
    process = context.Process(
        target=te_stageback_case_worker,
        kwargs={"queue": queue, "payload": case.__dict__, "case_dir": str(case_dir)},
    )
    start = time.time()
    rss_samples: list[dict[str, float | int]] = []
    process.start()
    while process.is_alive() and time.time() - start < timeout_seconds:
        time.sleep(5.0)
        rss_kb = process_tree_rss_kb(process.pid)
        if rss_kb is not None:
            rss_samples.append({"elapsed_seconds": time.time() - start, "rss_kb": rss_kb})
    if process.is_alive():
        terminate_process_tree(process.pid)
        process.join(10.0)
        if process.is_alive():
            process.kill()
            process.join(5.0)
        return {
            "case_id": case.case_id,
            "status": "timeout",
            "failure_code": "local_timeout",
            "timeout_seconds": float(timeout_seconds),
            "elapsed_seconds": time.time() - start,
            "process_exitcode": process.exitcode,
            "rss_samples": rss_samples,
            "peak_sampled_rss_kb": peak_rss(rss_samples),
            **case.__dict__,
            "external_shape_changed": False,
            "coefficient_interpretable": False,
        }
    process.join()
    if queue.empty():
        return {
            "case_id": case.case_id,
            "status": "terminated",
            "failure_code": "worker_no_payload",
            "elapsed_seconds": time.time() - start,
            "process_exitcode": process.exitcode,
            "rss_samples": rss_samples,
            "peak_sampled_rss_kb": peak_rss(rss_samples),
            **case.__dict__,
            "external_shape_changed": False,
            "coefficient_interpretable": False,
        }
    row = dict(queue.get())
    row["elapsed_seconds"] = time.time() - start
    row["process_exitcode"] = process.exitcode
    row["rss_samples"] = rss_samples
    row["peak_sampled_rss_kb"] = peak_rss(rss_samples)
    return row


def te_stageback_case_worker(queue: Any, *, payload: Mapping[str, Any], case_dir: str) -> None:
    case = TEStagebackCase(**payload)
    case_path = Path(case_dir)
    start = time.time()
    try:
        geometry = load_campaign_geometry(
            points_per_side=case.points_per_side,
            spanwise_subdivisions=case.spanwise_subdivisions,
        )
        wing = build_current_go_wing_surface(geometry)
        farfield = build_farfield_box_surface(
            wing,
            upstream_factor=2.0,
            downstream_factor=4.0,
            lateral_factor=2.0,
            vertical_factor=2.0,
        )
        report = write_faceted_volume_mesh_with_boundary_layer(
            wing,
            farfield,
            case_path / "mesh.msh",
            mesh_size=case.mesh_size,
            wing_mesh_size=case.wing_mesh_size,
            farfield_mesh_size=case.farfield_mesh_size,
            boundary_layer_first_height=BL_FIRST_HEIGHT_M,
            boundary_layer_growth_ratio=case.boundary_layer_growth_ratio,
            boundary_layer_layers=case.boundary_layer_layers,
            boundary_layer_exclusion_x_over_chord_min=case.x_over_chord_min,
            boundary_layer_exclusion_x_reference=case.x_reference,
            gmsh_threads=4,
            mesh_algorithm3d=case.mesh_algorithm3d,
            surface_triangulation_policy="shorter_diagonal",
        )
        write_json(case_path / "mesh_report.json", report)
        queue.put(summarize_mesh_report(case, report, elapsed_seconds=time.time() - start))
    except Exception as exc:  # pragma: no cover - real Gmsh failures are data.
        queue.put(
            {
                "case_id": case.case_id,
                "status": "failed",
                "failure_code": classify_stageback_failure(str(exc)),
                "raw_failure_code": exc.__class__.__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "elapsed_seconds": time.time() - start,
                **case.__dict__,
                "external_shape_changed": False,
                "coefficient_interpretable": False,
            }
        )


def summarize_mesh_report(
    case: TEStagebackCase,
    report: Mapping[str, Any],
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    gate = report.get("mesh_quality_gate") or {}
    boundary_layer = report.get("boundary_layer") or {}
    bl_quality = boundary_layer.get("quality_metrics") or {}
    return {
        "case_id": case.case_id,
        "status": report.get("status"),
        "gate_status": gate.get("status"),
        "blockers": gate.get("blockers") or [],
        "warnings": gate.get("warnings") or [],
        "elapsed_seconds": elapsed_seconds,
        "points_per_side": case.points_per_side,
        "spanwise_subdivisions": case.spanwise_subdivisions,
        "mesh_algorithm3d": case.mesh_algorithm3d,
        "x_over_chord_min": case.x_over_chord_min,
        "x_reference": case.x_reference,
        "boundary_layer_layers": case.boundary_layer_layers,
        "boundary_layer_growth_ratio": case.boundary_layer_growth_ratio,
        "nodes": report.get("node_count"),
        "cells": report.get("volume_element_count"),
        "bl_cells": boundary_layer.get("element_count"),
        "bl_min_sicn": bl_quality.get("min_sicn"),
        "bl_p01_min_sicn": (bl_quality.get("min_sicn_percentiles") or {}).get("p01"),
        "bl_non_positive_sicn": bl_quality.get("non_positive_min_sicn_count"),
        "stageback_policy": boundary_layer.get("stageback_policy"),
        "mesh_path": report.get("mesh_path"),
        "external_shape_changed": False,
        "coefficient_interpretable": False,
    }


def classify_stageback_failure(message: str) -> str:
    if "only supports triangles" in message:
        return "stageback_hxt_requires_triangle_boundary_surfaces"
    if "Could not recover boundary mesh" in message:
        return "stageback_boundary_recovery_failed"
    if "PLC Error" in message and re.search(r"segment.*facet|facet.*segment", message, re.I):
        return "stageback_plc_segment_facet_intersection"
    if "Gmsh stageback BL/core mesh generation failed" in message:
        return "stageback_mesh_generation_failed"
    return "stageback_probe_failed"


def build_probe_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidates = [
        str(row.get("case_id"))
        for row in rows
        if row.get("status") == "meshed"
        and row.get("gate_status") == "pass"
        and row.get("external_shape_changed") is False
    ]
    runtime_limited = [
        str(row.get("case_id")) for row in rows if row.get("status") == "timeout"
    ]
    failure_families = sorted(
        {
            str(row.get("failure_code"))
            for row in rows
            if row.get("failure_code") and row.get("status") in {"failed", "timeout"}
        }
    )
    if candidates:
        verdict = "te_stageback_bl_gate_candidate_found"
        engineering_read = (
            "A global TE stageback case passed the BL quality gate without changing "
            "Baseline A external shape. It is only a mesh candidate; route-smoke SU2 "
            "and y+/wall-shear evidence are still required before any ladder."
        )
    else:
        verdict = "te_stageback_no_bl_gate_pass"
        engineering_read = (
            "Global TE stageback did not produce a BL quality gate candidate. This "
            "supports moving to an owned TE/wake receiver or BL/core envelope repair "
            "instead of rerunning medium/fine SU2 on the current stageback topology."
        )
    return {
        "schema_version": "wo006t_te_stageback_runtime_probe.v1",
        "verdict": verdict,
        "candidate_case_ids": candidates,
        "runtime_limited_case_ids": runtime_limited,
        "failure_families": failure_families,
        "engineering_read": engineering_read,
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
    }


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# WO-006T TE Stageback Runtime Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- failure families: `{summary['failure_families']}`",
        f"- engineering read: {summary['engineering_read']}",
        "",
        "| case | status | alg3d | x/c min | gate/failure | cells | BL p01 SICN | elapsed s | peak RSS KB |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for row in summary.get("cases") or []:
        lines.append(
            "| {case} | `{status}` | {alg} | {xc} | `{gate}` | {cells} | {p01} | {elapsed} | {rss} |".format(
                case=row.get("case_id"),
                status=row.get("status"),
                alg=row.get("mesh_algorithm3d"),
                xc=row.get("x_over_chord_min"),
                gate=row.get("gate_status") or row.get("failure_code"),
                cells=row.get("cells"),
                p01=row.get("bl_p01_min_sicn"),
                elapsed=row.get("elapsed_seconds"),
                rss=row.get("peak_sampled_rss_kb"),
            )
        )
    lines.extend(
        [
            "",
            "Blocked claims:",
            "- BL/y+ viscous drag calibration",
            "- medium/fine CFD ladder readiness",
            "- Baseline A drag or power truth",
        ]
    )
    return "\n".join(lines) + "\n"


def process_tree_rss_kb(pid: int | None) -> int | None:
    if pid is None:
        return None
    pids = [pid, *child_pids(pid)]
    total = 0
    observed = False
    for item in pids:
        try:
            output = subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(item)],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except subprocess.CalledProcessError:
            continue
        if not output:
            continue
        try:
            total += int(output.splitlines()[-1].strip())
            observed = True
        except ValueError:
            continue
    return total if observed else None


def child_pids(pid: int) -> list[int]:
    try:
        output = subprocess.check_output(
            ["pgrep", "-P", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    children: list[int] = []
    for line in output.splitlines():
        try:
            children.append(int(line.strip()))
        except ValueError:
            continue
    return children


def terminate_process_tree(pid: int | None) -> None:
    if pid is None:
        return
    for child in child_pids(pid):
        terminate_process_tree(child)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return
        time.sleep(1.0)


def peak_rss(samples: Sequence[Mapping[str, Any]]) -> int | None:
    values = [int(sample["rss_kb"]) for sample in samples if sample.get("rss_kb") is not None]
    return max(values) if values else None


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames and key != "rss_samples":
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def parse_cases(values: Sequence[str] | None) -> tuple[TEStagebackCase, ...]:
    if not values:
        return DEFAULT_CASES
    cases: list[TEStagebackCase] = []
    for value in values:
        parts = value.split(":")
        if len(parts) not in {2, 3}:
            raise ValueError("Case format must be x_over_chord_min:mesh_algorithm3d[:case_id]")
        x_min = float(parts[0])
        alg3d = int(parts[1])
        case_id = parts[2] if len(parts) == 3 else f"global_te_xc{str(x_min).replace('.', 'p')}_alg{alg3d}"
        cases.append(TEStagebackCase(case_id, x_min, alg3d))
    return tuple(cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument(
        "--case",
        action="append",
        help="Case as x_over_chord_min:mesh_algorithm3d[:case_id]. Defaults to xc=0.99 for HXT and alg1.",
    )
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args(argv)
    summary = run_probe(
        output_dir=args.output_dir,
        cases=parse_cases(args.case),
        timeout_seconds=args.timeout_seconds,
        clean=not args.no_clean,
    )
    print(
        json.dumps(
            {
                "verdict": summary["verdict"],
                "GOAL_STATUS": summary["goal_status"],
                "CFD_STATUS": summary["cfd_status"],
                "candidate_case_ids": summary["candidate_case_ids"],
                "failure_families": summary["failure_families"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
