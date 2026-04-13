#!/usr/bin/env python3
"""Compare static vs dynamic design-space refresh runs for Phase 9f."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATIC_SUMMARY = (
    REPO_ROOT
    / "output"
    / "dynamic_design_space_phase9f_static"
    / "direct_dual_beam_inverse_design_refresh_summary.json"
)
DEFAULT_DYNAMIC_SUMMARY = (
    REPO_ROOT
    / "output"
    / "dynamic_design_space_phase9f_dynamic"
    / "direct_dual_beam_inverse_design_refresh_summary.json"
)
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "dynamic_design_space_phase9f_report.md"


def _load_summary(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _final_selected(summary: dict[str, object]) -> dict[str, object]:
    iterations = summary["iterations"]
    return iterations[-1]["selected"]


def _iteration_trace(summary: dict[str, object]) -> list[dict[str, object]]:
    trace: list[dict[str, object]] = []
    for iteration in summary["iterations"]:
        map_cfg = iteration.get("map_config") or {}
        trace.append(
            {
                "iteration_index": int(iteration["iteration_index"]),
                "load_source": str(iteration["load_source"]),
                "dynamic_design_space_applied": bool(iteration.get("dynamic_design_space_applied")),
                "main_plateau_scale_upper": float(map_cfg.get("main_plateau_scale_upper", float("nan"))),
                "main_taper_fill_upper": float(map_cfg.get("main_taper_fill_upper", float("nan"))),
                "rear_radius_scale_upper": float(map_cfg.get("rear_radius_scale_upper", float("nan"))),
                "delta_t_global_max_m": float(map_cfg.get("delta_t_global_max_m", float("nan"))),
                "delta_t_rear_outboard_max_m": float(map_cfg.get("delta_t_rear_outboard_max_m", float("nan"))),
            }
        )
    return trace


def build_report(
    *,
    static_summary_path: Path,
    dynamic_summary_path: Path,
) -> str:
    static = _load_summary(static_summary_path)
    dynamic = _load_summary(dynamic_summary_path)
    static_final = _final_selected(static)
    dynamic_final = _final_selected(dynamic)
    dynamic_trace = _iteration_trace(dynamic)
    static_def = static["refinement_definition"]
    dynamic_def = dynamic["refinement_definition"]

    lines: list[str] = []
    lines.append("# Phase 9f Dynamic Design Space Report")
    lines.append("")
    lines.append("## Scope")
    lines.append(
        "- Phase 9f compares the existing lightweight load-refresh workflow against the new `--dynamic-design-space` mode."
    )
    lines.append(
        "- The new mode rebuilds the reduced V2 search map after each feasible refresh iteration, using the previous selected design as the new local baseline."
    )
    lines.append("")
    lines.append("## Static vs Dynamic")
    lines.append("")
    lines.append(
        "| Mode | Dynamic Map | Rebuilds | Final Mass (kg) | Clearance (mm) | Tip Deflection (m) | Failure Index | Buckling Index |"
    )
    lines.append(
        "|------|-------------|----------|-----------------|----------------|--------------------|---------------|----------------|"
    )
    lines.append(
        "| static | "
        + " | ".join(
            [
                "off",
                str(int(static_def["dynamic_design_space_rebuilds"])),
                f"{float(static_final['total_structural_mass_kg']):.3f}",
                f"{float(static_final['jig_ground_clearance_min_m']) * 1000.0:.3f}",
                f"{float(static_final['equivalent_tip_deflection_m']):.6f}",
                f"{float(static_final['equivalent_failure_index']):.6f}",
                f"{float(static_final['equivalent_buckling_index']):.6f}",
            ]
        )
        + " |"
    )
    lines.append(
        "| dynamic | "
        + " | ".join(
            [
                "on",
                str(int(dynamic_def["dynamic_design_space_rebuilds"])),
                f"{float(dynamic_final['total_structural_mass_kg']):.3f}",
                f"{float(dynamic_final['jig_ground_clearance_min_m']) * 1000.0:.3f}",
                f"{float(dynamic_final['equivalent_tip_deflection_m']):.6f}",
                f"{float(dynamic_final['equivalent_failure_index']):.6f}",
                f"{float(dynamic_final['equivalent_buckling_index']):.6f}",
            ]
        )
        + " |"
    )
    lines.append("")
    lines.append("## Dynamic Map Trace")
    lines.append("")
    lines.append(
        "| Iter | Rebuilt | Plateau Cap | Taper Cap | Rear Cap | dT Global (mm) | dT Rear Outboard (mm) | Source |"
    )
    lines.append(
        "|------|---------|-------------|-----------|----------|----------------|-----------------------|--------|"
    )
    for item in dynamic_trace:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item["iteration_index"]),
                    "yes" if item["dynamic_design_space_applied"] else "no",
                    f"{float(item['main_plateau_scale_upper']):.4f}",
                    f"{float(item['main_taper_fill_upper']):.4f}",
                    f"{float(item['rear_radius_scale_upper']):.4f}",
                    f"{float(item['delta_t_global_max_m']) * 1000.0:.3f}",
                    f"{float(item['delta_t_rear_outboard_max_m']) * 1000.0:.3f}",
                    str(item["load_source"]),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    mass_delta = float(dynamic_final["total_structural_mass_kg"]) - float(
        static_final["total_structural_mass_kg"]
    )
    clearance_delta_mm = 1000.0 * (
        float(dynamic_final["jig_ground_clearance_min_m"])
        - float(static_final["jig_ground_clearance_min_m"])
    )
    lines.append(
        f"- Dynamic design space changed final mass by {mass_delta:+.3f} kg and final jig clearance by {clearance_delta_mm:+.3f} mm relative to the static reduced map."
    )
    lines.append(
        f"- Dynamic mode rebuilt the map {int(dynamic_def['dynamic_design_space_rebuilds'])} time(s), so later refresh iterations were no longer constrained by the original specimen-only caps."
    )
    lines.append(
        "- This closes one of the three explicit gaps previously called out in the refresh report: the workflow now supports dynamic design-space rewrite, while trim update and full aero reruns still remain outside this lightweight path."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Phase 9f dynamic design-space comparison report."
    )
    parser.add_argument("--static-summary", default=str(DEFAULT_STATIC_SUMMARY))
    parser.add_argument("--dynamic-summary", default=str(DEFAULT_DYNAMIC_SUMMARY))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    static_summary = Path(args.static_summary).expanduser().resolve()
    dynamic_summary = Path(args.dynamic_summary).expanduser().resolve()
    report_path = Path(args.report_path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        build_report(
            static_summary_path=static_summary,
            dynamic_summary_path=dynamic_summary,
        ),
        encoding="utf-8",
    )
    print(f"Wrote report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
