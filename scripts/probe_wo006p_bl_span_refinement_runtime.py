#!/usr/bin/env python3
"""Probe whether spanwise refinement can clear the WO-006 BL quality gate.

This is a bounded meshing/runtime probe, not CFD completion evidence. It exists
because the DAE31 -> CST tip transition hotspot improves with span subdivision,
but larger subdivisions can also stall Gmsh. Every case therefore runs with a
timeout and sampled RSS evidence.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import multiprocessing as mp
import os
from pathlib import Path
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
from run_wo006r1_go_baseline_a_cfd_bridge import (  # noqa: E402
    build_current_go_wing_surface,
)
from run_wo006r2_cfd_recovery_campaign import (  # noqa: E402
    BL_FIRST_HEIGHT_M,
    load_campaign_geometry,
)
from run_wo006r4_bl_ownership_repair import WO006_ROOT  # noqa: E402


DEFAULT_OUTPUT_DIR = WO006_ROOT / "wo006p_bl_span_refinement_runtime_probe"


@dataclass(frozen=True)
class SpanRefinementCase:
    case_id: str
    points_per_side: int
    spanwise_subdivisions: int
    boundary_layer_layers: int = 12
    boundary_layer_growth_ratio: float = 1.18
    mesh_size: float = 0.5
    wing_mesh_size: float = 0.25
    farfield_mesh_size: float = 4.0
    mesh_algorithm3d: int = 10


DEFAULT_CASES = (
    SpanRefinementCase("pps16_span8_thin12_g118", 16, 8),
    SpanRefinementCase("pps16_span16_thin12_g118", 16, 16),
)


def run_probe(
    *,
    output_dir: Path,
    cases: Sequence[SpanRefinementCase] = DEFAULT_CASES,
    timeout_seconds: float = 420.0,
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
    case: SpanRefinementCase,
    case_dir: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue: mp.Queue = context.Queue()
    case_dir.mkdir(parents=True, exist_ok=True)
    process = context.Process(
        target=span_case_worker,
        kwargs={"queue": queue, "payload": case.__dict__, "case_dir": str(case_dir)},
    )
    start = time.time()
    rss_samples: list[dict[str, float | int]] = []
    process.start()
    while process.is_alive() and time.time() - start < timeout_seconds:
        time.sleep(5.0)
        rss_kb = process_tree_rss_kb(process.pid)
        if rss_kb is not None:
            rss_samples.append(
                {
                    "elapsed_seconds": time.time() - start,
                    "rss_kb": rss_kb,
                }
            )
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
            "engineering_read": (
                "Gmsh did not return inside the bounded local runtime. This is runtime "
                "evidence only; it is not a hardware limit unless RSS/runtime traces "
                "show resource exhaustion."
            ),
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
        }
    row = dict(queue.get())
    row["elapsed_seconds"] = time.time() - start
    row["process_exitcode"] = process.exitcode
    row["rss_samples"] = rss_samples
    row["peak_sampled_rss_kb"] = peak_rss(rss_samples)
    return row


def span_case_worker(queue: Any, *, payload: Mapping[str, Any], case_dir: str) -> None:
    case = SpanRefinementCase(**payload)
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
                "failure_code": exc.__class__.__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "elapsed_seconds": time.time() - start,
                **case.__dict__,
            }
        )


def summarize_mesh_report(
    case: SpanRefinementCase,
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
        "full_station_count": (report.get("source_geometry") or {}).get("station_count"),
        "boundary_layer_layers": case.boundary_layer_layers,
        "boundary_layer_growth_ratio": case.boundary_layer_growth_ratio,
        "nodes": report.get("node_count"),
        "cells": report.get("volume_element_count"),
        "bl_cells": boundary_layer.get("element_count"),
        "bl_min_sicn": bl_quality.get("min_sicn"),
        "bl_p01_min_sicn": (bl_quality.get("min_sicn_percentiles") or {}).get("p01"),
        "bl_non_positive_sicn": bl_quality.get("non_positive_min_sicn_count"),
        "mesh_path": report.get("mesh_path"),
        "engineering_read": (
            "Spanwise refinement BL quality probe. This is eligible to become a "
            "candidate only if the BL quality gate passes; it is not SU2 CFD evidence."
        ),
    }


def build_probe_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidates = [
        str(row.get("case_id"))
        for row in rows
        if row.get("status") == "meshed" and row.get("gate_status") == "pass"
    ]
    runtime_limited = [
        str(row.get("case_id"))
        for row in rows
        if row.get("status") == "timeout"
    ]
    if candidates:
        verdict = "span_refinement_bl_gate_candidate_found"
        engineering_read = (
            "At least one spanwise-refined BL mesh passed the quality gate. It can be "
            "considered for a bounded SU2 route smoke before any medium/fine ladder."
        )
    elif runtime_limited:
        verdict = "span_refinement_runtime_limited_no_bl_gate_pass"
        engineering_read = (
            "Spanwise refinement has not cleared the BL quality gate, and at least one "
            "case hit the local runtime guard. Do not promote this route to CFD."
        )
    else:
        verdict = "span_refinement_no_bl_gate_pass"
        engineering_read = (
            "Spanwise refinement returned locally but did not clear the BL quality gate. "
            "The next repair should target topology/near-wall shape, not SU2 iterations."
        )
    return {
        "schema_version": "wo006p_bl_span_refinement_runtime_probe.v1",
        "verdict": verdict,
        "candidate_case_ids": candidates,
        "runtime_limited_case_ids": runtime_limited,
        "engineering_read": engineering_read,
        "coefficient_interpretable": False,
        "goal_status": "INCOMPLETE",
        "cfd_status": "mesh_ladder_incomplete",
    }


def render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# WO-006P BL Span-Refinement Runtime Probe",
        "",
        f"GOAL_STATUS: `{summary['goal_status']}`",
        f"CFD_STATUS: `{summary['cfd_status']}`",
        f"- verdict: `{summary['verdict']}`",
        f"- engineering read: {summary['engineering_read']}",
        "",
        "| case | status | span subdiv | gate | cells | BL cells | BL min SICN | BL p01 SICN | elapsed s | peak RSS KB |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.get("cases") or []:
        lines.append(
            "| {case} | `{status}` | {span} | `{gate}` | {cells} | {bl_cells} | "
            "{min_sicn} | {p01_sicn} | {elapsed} | {rss} |".format(
                case=row.get("case_id"),
                status=row.get("status"),
                span=row.get("spanwise_subdivisions"),
                gate=row.get("gate_status") or row.get("failure_code"),
                cells=row.get("cells"),
                bl_cells=row.get("bl_cells"),
                min_sicn=row.get("bl_min_sicn"),
                p01_sicn=row.get("bl_p01_min_sicn"),
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
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def parse_cases(values: Sequence[str] | None) -> tuple[SpanRefinementCase, ...]:
    if not values:
        return DEFAULT_CASES
    cases: list[SpanRefinementCase] = []
    for value in values:
        span = int(value)
        cases.append(SpanRefinementCase(f"pps16_span{span}_thin12_g118", 16, span))
    return tuple(cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=420.0)
    parser.add_argument("--span", action="append", help="Spanwise subdivision count.")
    parser.add_argument("--no-clean", action="store_true")
    args = parser.parse_args(argv)

    summary = run_probe(
        output_dir=args.output_dir,
        cases=parse_cases(args.span),
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
                "runtime_limited_case_ids": summary["runtime_limited_case_ids"],
                "output_dir": str(args.output_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
