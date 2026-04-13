#!/usr/bin/env python3
"""Build the Phase 9g higher-fidelity load-coupling comparison report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE_SUMMARY = (
    REPO_ROOT
    / "output"
    / "dynamic_design_space_phase9f_dynamic"
    / "direct_dual_beam_inverse_design_refresh_summary.json"
)
DEFAULT_CONVERGED_SUMMARY = (
    REPO_ROOT
    / "output"
    / "higher_fidelity_load_coupling_phase9g"
    / "direct_dual_beam_inverse_design_refresh_summary.json"
)
DEFAULT_REPORT_PATH = REPO_ROOT / "docs" / "higher_fidelity_load_coupling_phase9g_report.md"


def _load_summary(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _final(summary: dict[str, object]) -> dict[str, object]:
    return summary["iterations"][-1]["selected"]


def build_report(*, baseline_summary: Path, converged_summary: Path) -> str:
    base = _load_summary(baseline_summary)
    conv = _load_summary(converged_summary)
    base_def = base["refinement_definition"]
    conv_def = conv["refinement_definition"]
    base_final = _final(base)
    conv_final = _final(conv)

    lines: list[str] = []
    lines.append("# Phase 9g Higher-Fidelity Load Coupling Report")
    lines.append("")
    lines.append("## Scope")
    lines.append(
        "- Phase 9g extends the lightweight refresh path from a fixed-step outer loop to a convergence-driven outer load-coupling loop."
    )
    lines.append(
        "- This comparison uses the 9f dynamic-design-space run as the baseline and compares it against the converged higher-fidelity variant."
    )
    lines.append("")
    lines.append("## Fixed Step vs Converged")
    lines.append("")
    lines.append(
        "| Mode | Steps Requested | Steps Completed | Converged | Reason | Final Mass (kg) | Clearance (mm) | Tip Deflection (m) |"
    )
    lines.append(
        "|------|-----------------|-----------------|-----------|--------|-----------------|----------------|--------------------|"
    )
    lines.append(
        "| 9f dynamic | "
        + " | ".join(
            [
                str(int(base_def["refresh_steps_requested"])),
                str(int(base_def["refresh_steps_completed"])),
                str(bool(base_def.get("converged"))),
                str(base_def.get("convergence_reason") or "fixed_step"),
                f"{float(base_final['total_structural_mass_kg']):.3f}",
                f"{float(base_final['jig_ground_clearance_min_m']) * 1000.0:.3f}",
                f"{float(base_final['equivalent_tip_deflection_m']):.6f}",
            ]
        )
        + " |"
    )
    lines.append(
        "| 9g converged | "
        + " | ".join(
            [
                str(int(conv_def["refresh_steps_requested"])),
                str(int(conv_def["refresh_steps_completed"])),
                str(bool(conv_def.get("converged"))),
                str(conv_def.get("convergence_reason") or "n/a"),
                f"{float(conv_final['total_structural_mass_kg']):.3f}",
                f"{float(conv_final['jig_ground_clearance_min_m']) * 1000.0:.3f}",
                f"{float(conv_final['equivalent_tip_deflection_m']):.6f}",
            ]
        )
        + " |"
    )
    lines.append("")
    lines.append("## Iteration Trace")
    lines.append("")
    lines.append("| Iter | Dynamic Map | Lift RMS Delta (N/m) | Torque RMS Delta (N*m/m) | Mass Delta (kg) |")
    lines.append("|------|-------------|----------------------|--------------------------|-----------------|")
    for iteration in conv["iterations"]:
        delta = iteration["deltas_vs_previous"]
        lines.append(
            "| "
            + " | ".join(
                [
                    str(iteration["iteration_index"]),
                    "yes" if iteration.get("dynamic_design_space_applied") else "no",
                    "n/a" if delta["lift_rms_delta_npm"] is None else f"{float(delta['lift_rms_delta_npm']):.3f}",
                    "n/a"
                    if delta["torque_rms_delta_nmpm"] is None
                    else f"{float(delta['torque_rms_delta_nmpm']):.3f}",
                    "n/a" if delta["mass_delta_kg"] is None else f"{float(delta['mass_delta_kg']):+.3f}",
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    mass_delta = float(conv_final["total_structural_mass_kg"]) - float(
        base_final["total_structural_mass_kg"]
    )
    lines.append(
        f"- Higher-fidelity load coupling changed final mass by {mass_delta:+.3f} kg relative to the fixed 9f dynamic run."
    )
    lines.append(
        f"- The converged run completed {int(conv_def['refresh_steps_completed'])} outer refresh step(s) and reported `converged={bool(conv_def.get('converged'))}`."
    )
    lines.append(
        "- This closes the second explicit gap in the lightweight refresh path: the workflow can now iterate until its own load/mass deltas settle, even though it still does not rerun external aerodynamics each step."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the Phase 9g higher-fidelity load-coupling report."
    )
    parser.add_argument("--baseline-summary", default=str(DEFAULT_BASELINE_SUMMARY))
    parser.add_argument("--converged-summary", default=str(DEFAULT_CONVERGED_SUMMARY))
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    baseline_summary = Path(args.baseline_summary).expanduser().resolve()
    converged_summary = Path(args.converged_summary).expanduser().resolve()
    report_path = Path(args.report_path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        build_report(
            baseline_summary=baseline_summary,
            converged_summary=converged_summary,
        ),
        encoding="utf-8",
    )
    print(f"Wrote report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
