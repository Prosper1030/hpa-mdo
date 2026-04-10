#!/usr/bin/env python3
"""Generate and summarize dual-spar ANSYS high-fidelity spot checks.

This workflow is intentionally not a Phase I validation gate.  The official
gate remains the equivalent-beam ANSYS model, which compares the same model
assumptions used by the internal optimizer.  The dual-spar path is an
inspection workflow for model-form adequacy: it helps identify whether the
simplified equivalent-beam model may be hiding a high-fidelity mechanism.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Optional

# Allow running directly from the repository without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ansys_compare_results import (  # noqa: E402
    AnsysMetrics,
    BaselineMetrics,
    _error_percent,
    extract_ansys_metrics_from_rst,
    parse_baseline_metrics,
)
from scripts.ansys_crossval import generate_cross_validation_package  # noqa: E402


CONSISTENT = "CONSISTENT"
NOTICEABLE = "NOTICEABLE DISCREPANCY"
MODEL_FORM_RISK = "MODEL-FORM RISK"


@dataclass(frozen=True)
class SpotCheckRow:
    name: str
    baseline: float
    ansys: Optional[float]
    error_pct: Optional[float]
    consistent_pct: float
    risk_pct: float
    note: str


def _classify_error(error_pct: Optional[float], consistent_pct: float, risk_pct: float) -> str:
    if error_pct is None:
        return NOTICEABLE
    if error_pct <= consistent_pct:
        return CONSISTENT
    if error_pct <= risk_pct:
        return NOTICEABLE
    return MODEL_FORM_RISK


def _overall_classification(rows: list[SpotCheckRow]) -> str:
    labels = [
        _classify_error(row.error_pct, row.consistent_pct, row.risk_pct)
        for row in rows
    ]
    if MODEL_FORM_RISK in labels:
        return MODEL_FORM_RISK
    if NOTICEABLE in labels:
        return NOTICEABLE
    return CONSISTENT


def _fmt(value: Optional[float], precision: int = 3) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{precision}f}"


def _build_rows(baseline: BaselineMetrics, ansys: AnsysMetrics) -> list[SpotCheckRow]:
    """Build non-gating adequacy rows for the dual-spar spot check."""
    return [
        SpotCheckRow(
            "Tip deflection @ tip node (mm)",
            baseline.tip_deflection_mm,
            ansys.tip_deflection_mm,
            _error_percent(ansys.tip_deflection_mm, baseline.tip_deflection_mm),
            consistent_pct=5.0,
            risk_pct=15.0,
            note="large change can indicate feasibility/order sensitivity",
        ),
        SpotCheckRow(
            "Max |UZ| anywhere (mm)",
            baseline.max_uz_mm,
            ansys.max_uz_mm,
            _error_percent(ansys.max_uz_mm, baseline.max_uz_mm),
            consistent_pct=5.0,
            risk_pct=15.0,
            note="watch for active deflection constraint flip",
        ),
        SpotCheckRow(
            "Support reaction Fz all supports (N)",
            baseline.root_reaction_fz_n,
            ansys.root_reaction_fz_n,
            _error_percent(ansys.root_reaction_fz_n, baseline.root_reaction_fz_n),
            consistent_pct=1.0,
            risk_pct=3.0,
            note="checks load/support mapping consistency",
        ),
        SpotCheckRow(
            "Spar mass full-span (kg)",
            baseline.total_spar_mass_kg,
            ansys.total_spar_mass_kg,
            _error_percent(ansys.total_spar_mass_kg, baseline.total_spar_mass_kg),
            consistent_pct=1.0,
            risk_pct=3.0,
            note="checks exported section/material mass",
        ),
    ]


def build_spotcheck_report(
    baseline: BaselineMetrics,
    ansys: AnsysMetrics,
    *,
    ansys_dir: Path,
    rst_path: Path,
) -> str:
    """Return the human-readable dual-spar adequacy spot-check report."""
    rows = _build_rows(baseline, ansys)
    overall = _overall_classification(rows)

    lines: list[str] = []
    lines.append("=" * 96)
    lines.append("Dual-Spar High-Fidelity Spot-Check Summary")
    lines.append("=" * 96)
    lines.append(f"ANSYS directory : {ansys_dir}")
    lines.append(f"RST file        : {rst_path}")
    lines.append(f"Baseline mode   : {baseline.export_mode}")
    lines.append("Phase I gate    : disabled for this workflow")
    lines.append("")
    lines.append("Purpose:")
    lines.append(
        "  Inspect model-form adequacy of the internal equivalent-beam optimizer "
        "against a higher-fidelity dual-spar + rigid-link ANSYS model."
    )
    lines.append("")
    lines.append(
        f"{'Metric':40} {'Baseline':>12} {'ANSYS':>12} "
        f"{'Error %':>10} {'Class':>24}"
    )
    lines.append("-" * 96)

    for row in rows:
        label = _classify_error(row.error_pct, row.consistent_pct, row.risk_pct)
        lines.append(
            f"{row.name:40} "
            f"{_fmt(row.baseline):>12} "
            f"{_fmt(row.ansys):>12} "
            f"{_fmt(row.error_pct, precision=2):>10} "
            f"{label:>24}"
        )
        lines.append(f"  Note: {row.note}")

    lines.append("-" * 96)
    lines.append(f"Overall model-form assessment: {overall}")
    lines.append("")
    lines.append("Interpretation:")
    lines.append("- CONSISTENT: dual-spar response is close enough for a non-gating spot check.")
    lines.append(
        "- NOTICEABLE DISCREPANCY: document the mechanism and consider more samples "
        "before relying on ranking."
    )
    lines.append(
        "- MODEL-FORM RISK: investigate whether active constraints, feasibility, "
        "or design ordering may change."
    )
    lines.append("")
    lines.append("Mechanisms to inspect manually in ANSYS:")
    lines.append("- Did the active constraint move away from tip deflection?")
    lines.append("- Did feasible/infeasible status appear to flip under the dual-spar model?")
    lines.append("- Are rear spar, rib transfer, or torsion/rib-link forces becoming dominant?")
    lines.append("- Would two nearby designs swap ranking under this higher-fidelity response?")
    lines.append("")
    lines.append("Stress remains provisional/non-gating unless beam stress extraction is validated.")
    return "\n".join(lines) + "\n"


def export_dual_spar_package(args: argparse.Namespace) -> int:
    """Generate a dual-spar ANSYS package for manual high-fidelity inspection."""
    package = generate_cross_validation_package(
        config_path=args.config,
        output_dir=args.output_dir,
        n_beam_nodes=args.n_beam_nodes,
        optimizer_maxiter=args.optimizer_maxiter,
        export_mode="dual_spar",
    )
    print("Dual-spar spot-check package generated.")
    print(f"  Config       : {package.config_path}")
    print(f"  Output dir   : {package.ansys_dir}")
    print(f"  APDL macro   : {package.apdl_path.name}")
    print(f"  NASTRAN BDF  : {package.bdf_path.name}")
    print(f"  Workbench CSV: {package.csv_path.name}")
    print(f"  Report       : {package.report_path.name}")
    print("  Classification: not run yet; run ANSYS manually, then use the compare subcommand.")
    return 0


def compare_dual_spar_results(args: argparse.Namespace) -> int:
    """Compare dual-spar ANSYS results and emit non-gating adequacy classification."""
    ansys_dir = Path(args.ansys_dir).expanduser().resolve()
    rst_path = ansys_dir / args.rst
    baseline_report = Path(args.baseline_report).expanduser().resolve()
    mac_path = ansys_dir / "spar_model.mac"

    baseline = parse_baseline_metrics(baseline_report, mac_path=mac_path)
    ansys = extract_ansys_metrics_from_rst(rst_path, baseline, ansys_dir)
    report = build_spotcheck_report(
        baseline,
        ansys,
        ansys_dir=ansys_dir,
        rst_path=rst_path,
    )

    print(report)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"Saved spot-check report: {output_path}")
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or summarize non-gating dual-spar ANSYS spot checks."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser(
        "export",
        help="Generate a dual-spar APDL/BDF/CSV package for manual ANSYS execution.",
    )
    export_parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parent.parent / "configs" / "blackcat_004.yaml"),
        help="Path to YAML configuration file.",
    )
    export_parser.add_argument(
        "--output-dir",
        default="output/blackcat_004_dual_spar_spotcheck",
        help="Output root; ANSYS files are written under <output-dir>/ansys.",
    )
    export_parser.add_argument("--n-beam-nodes", type=int, default=None)
    export_parser.add_argument("--optimizer-maxiter", type=int, default=None)
    export_parser.set_defaults(func=export_dual_spar_package)

    compare_parser = subparsers.add_parser(
        "compare",
        help="Classify manually-run dual-spar ANSYS results without changing Phase I gates.",
    )
    compare_parser.add_argument(
        "--ansys-dir",
        required=True,
        help="Directory containing dual-spar ANSYS result files.",
    )
    compare_parser.add_argument(
        "--baseline-report",
        required=True,
        help="The dual-spar export crossval_report.txt generated with this same design.",
    )
    compare_parser.add_argument(
        "--rst",
        default="file.rst",
        help="RST filename under --ansys-dir.",
    )
    compare_parser.add_argument(
        "--output",
        default=None,
        help="Optional text file path for the spot-check summary.",
    )
    compare_parser.set_defaults(func=compare_dual_spar_results)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
