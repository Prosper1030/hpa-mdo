#!/usr/bin/env python3
"""Compare ANSYS MAPDL results against internal FEM cross-validation targets.

This script reads:
1. Baseline metrics from crossval_report.txt (internal FEM expectations)
2. ANSYS results from MAPDL result files in a result directory

Primary extraction path:
    - file.rst via ansys-mapdl-reader

Usage example:
    uv run --with ansys-mapdl-reader python scripts/ansys_compare_results.py \
        --ansys-dir "/Volumes/Samsung SSD/SyncFile/ANSYS_Result"
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Optional

import numpy as np


@dataclass
class BaselineMetrics:
    tip_deflection_mm: float
    max_uz_mm: float
    max_vm_main_mpa: float
    max_vm_rear_mpa: float
    root_reaction_fz_n: float
    max_twist_deg: float
    total_spar_mass_kg: float
    tip_node: int
    nodes_per_spar: int


@dataclass
class AnsysMetrics:
    tip_deflection_mm: Optional[float] = None
    max_uz_mm: Optional[float] = None
    max_vm_main_mpa: Optional[float] = None
    max_vm_rear_mpa: Optional[float] = None
    root_reaction_fz_n: Optional[float] = None
    max_twist_deg: Optional[float] = None
    total_spar_mass_kg: Optional[float] = None
    total_constrained_reaction_fz_n: Optional[float] = None
    total_input_fz_n: Optional[float] = None


def _extract_float(pattern: str, text: str, field_name: str) -> float:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"Could not parse baseline metric: {field_name}")
    return float(match.group(1))


def parse_baseline_metrics(report_path: Path, mac_path: Optional[Path] = None) -> BaselineMetrics:
    text = report_path.read_text(encoding="utf-8")

    tip_deflection_mm = _extract_float(
        r"Tip deflection \(uz, y=[^)]+\)\s+([+-]?\d+(?:\.\d+)?)\s+mm",
        text,
        "tip_deflection_mm",
    )
    max_uz_mm = _extract_float(
        r"Max uz anywhere\s+([+-]?\d+(?:\.\d+)?)\s+mm",
        text,
        "max_uz_mm",
    )
    max_vm_main_mpa = _extract_float(
        r"Max Von Mises \(main spar\)\s+([+-]?\d+(?:\.\d+)?)\s+MPa",
        text,
        "max_vm_main_mpa",
    )
    max_vm_rear_mpa = _extract_float(
        r"Max Von Mises \(rear spar\)\s+([+-]?\d+(?:\.\d+)?)\s+MPa",
        text,
        "max_vm_rear_mpa",
    )
    root_reaction_fz_n = _extract_float(
        r"Root reaction Fz\s+([+-]?\d+(?:\.\d+)?)\s+N",
        text,
        "root_reaction_fz_n",
    )
    max_twist_deg = _extract_float(
        r"Max twist angle\s+([+-]?\d+(?:\.\d+)?)\s+deg",
        text,
        "max_twist_deg",
    )
    total_spar_mass_kg = _extract_float(
        r"Total spar mass \(full-span\)\s+([+-]?\d+(?:\.\d+)?)\s+kg",
        text,
        "total_spar_mass_kg",
    )

    tip_node = int(_extract_float(r"\*GET,TIP_UZ,NODE,(\d+),U,Z", text, "tip_node"))

    nodes_per_spar = tip_node
    if mac_path is not None and mac_path.exists():
        mac_text = mac_path.read_text(encoding="utf-8")
        match = re.search(r"!\s*Nodes/spar\s*:\s*(\d+)", mac_text)
        if match:
            nodes_per_spar = int(match.group(1))

    return BaselineMetrics(
        tip_deflection_mm=tip_deflection_mm,
        max_uz_mm=max_uz_mm,
        max_vm_main_mpa=max_vm_main_mpa,
        max_vm_rear_mpa=max_vm_rear_mpa,
        root_reaction_fz_n=root_reaction_fz_n,
        max_twist_deg=max_twist_deg,
        total_spar_mass_kg=total_spar_mass_kg,
        tip_node=tip_node,
        nodes_per_spar=nodes_per_spar,
    )


def _extract_mass_from_out_files(ansys_dir: Path) -> Optional[float]:
    """Extract total mass from MAPDL *.out files (if available)."""
    type_mass: dict[int, float] = {}
    pattern = re.compile(
        r"\*\*\*\s*MASS SUMMARY BY ELEMENT TYPE\s*\*\*\*.*?^\s*TYPE\s+MASS\s*$"
        r"(.*?)^(?:\s*AN AVERAGE|\s*$)",
        flags=re.MULTILINE | re.DOTALL,
    )
    row_pattern = re.compile(r"^\s*(\d+)\s+([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s*$", re.MULTILINE)

    for out_path in sorted(ansys_dir.glob("*.out")):
        text = out_path.read_text(encoding="utf-8", errors="ignore")
        for block in pattern.findall(text):
            for mm in row_pattern.finditer(block):
                etype = int(mm.group(1))
                mass = float(mm.group(2))
                # Distributed runs may emit duplicate summaries; keep max per type.
                type_mass[etype] = max(type_mass.get(etype, 0.0), mass)

    if not type_mass:
        return None
    return float(sum(type_mass.values()))


def extract_ansys_metrics_from_rst(
    rst_path: Path,
    baseline: BaselineMetrics,
    ansys_dir: Path,
) -> AnsysMetrics:
    try:
        from ansys.mapdl import reader as pymapdl_reader
    except Exception as exc:
        raise RuntimeError(
            "ansys-mapdl-reader is required for RST parsing. "
            "Run with: uv run --with ansys-mapdl-reader python scripts/ansys_compare_results.py ..."
        ) from exc

    result = pymapdl_reader.read_binary(str(rst_path))

    nnum, disp = result.nodal_solution(0)
    node_to_idx = {int(node): i for i, node in enumerate(nnum)}

    if baseline.tip_node not in node_to_idx:
        raise RuntimeError(
            f"Tip node {baseline.tip_node} not found in RST nodal solution."
        )

    tip_uz_mm = float(abs(disp[node_to_idx[baseline.tip_node], 2]) * 1000.0)
    max_uz_mm = float(np.max(np.abs(disp[:, 2])) * 1000.0)

    pnnum, principal = result.principal_nodal_stress(0)
    seqv_pa = np.abs(principal[:, 4])

    nn = baseline.nodes_per_spar
    main_mask = (pnnum >= 1) & (pnnum <= nn)
    rear_mask = (pnnum >= nn + 1) & (pnnum <= 2 * nn)

    max_vm_main_mpa = float(np.nanmax(seqv_pa[main_mask]) / 1e6) if np.any(main_mask) else None
    max_vm_rear_mpa = float(np.nanmax(seqv_pa[rear_mask]) / 1e6) if np.any(rear_mask) else None

    # Root reaction Fz: use constrained root nodes only (main root=1, rear root=nn+1).
    rforces, rnodes, rdof = result.nodal_reaction_forces(0)
    fz_mask = rdof == 3
    root_mask = (rnodes == 1) | (rnodes == nn + 1)
    root_fz = float(np.sum(rforces[fz_mask & root_mask])) if np.any(fz_mask & root_mask) else None
    total_reaction_fz = float(np.sum(rforces[fz_mask])) if np.any(fz_mask) else None

    input_nodes, input_dof, input_force = result.nodal_input_force(0)
    input_fz = float(np.sum(input_force[input_dof == 3])) if np.any(input_dof == 3) else None

    total_mass_kg = _extract_mass_from_out_files(ansys_dir)

    return AnsysMetrics(
        tip_deflection_mm=tip_uz_mm,
        max_uz_mm=max_uz_mm,
        max_vm_main_mpa=max_vm_main_mpa,
        max_vm_rear_mpa=max_vm_rear_mpa,
        root_reaction_fz_n=root_fz,
        max_twist_deg=None,  # Not directly available from this RST/post setup.
        total_spar_mass_kg=total_mass_kg,
        total_constrained_reaction_fz_n=total_reaction_fz,
        total_input_fz_n=input_fz,
    )


def _error_percent(ansys_value: Optional[float], baseline_value: float) -> Optional[float]:
    if ansys_value is None:
        return None
    denom = max(abs(baseline_value), 1e-12)
    return abs(ansys_value - baseline_value) / denom * 100.0


def _fmt(v: Optional[float], unit: str = "", precision: int = 3) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{precision}f}{unit}"


def _status(error_pct: Optional[float], threshold: float = 5.0) -> str:
    if error_pct is None:
        return "N/A"
    return "PASS" if error_pct < threshold else "FAIL"


def build_report_text(
    baseline: BaselineMetrics,
    ansys: AnsysMetrics,
    *,
    threshold_pct: float,
    ansys_dir: Path,
    rst_path: Path,
) -> str:
    rows = [
        ("Tip deflection @ tip node (mm)", baseline.tip_deflection_mm, ansys.tip_deflection_mm),
        ("Max |UZ| anywhere (mm)", baseline.max_uz_mm, ansys.max_uz_mm),
        ("Max Von Mises main spar (MPa)", baseline.max_vm_main_mpa, ansys.max_vm_main_mpa),
        ("Max Von Mises rear spar (MPa)", baseline.max_vm_rear_mpa, ansys.max_vm_rear_mpa),
        ("Root reaction Fz (N)", baseline.root_reaction_fz_n, ansys.root_reaction_fz_n),
        ("Max twist angle (deg)", baseline.max_twist_deg, ansys.max_twist_deg),
        ("Total spar mass full-span (kg)", baseline.total_spar_mass_kg, ansys.total_spar_mass_kg),
    ]

    lines: list[str] = []
    lines.append("=" * 88)
    lines.append("ANSYS vs Internal FEM Cross-Validation Summary")
    lines.append("=" * 88)
    lines.append(f"ANSYS directory : {ansys_dir}")
    lines.append(f"RST file        : {rst_path}")
    lines.append(f"Pass threshold  : error < {threshold_pct:.1f}%")
    lines.append("")
    lines.append(
        f"{'Metric':36} {'Baseline':>12} {'ANSYS':>12} {'Error %':>10} {'Status':>8}"
    )
    lines.append("-" * 88)

    numeric_errors: list[float] = []
    failed_metrics: list[str] = []

    for metric, baseline_value, ansys_value in rows:
        err = _error_percent(ansys_value, baseline_value)
        st = _status(err, threshold_pct)
        if err is not None:
            numeric_errors.append(err)
            if err >= threshold_pct:
                failed_metrics.append(metric)
        lines.append(
            f"{metric:36} "
            f"{_fmt(baseline_value):>12} "
            f"{_fmt(ansys_value):>12} "
            f"{_fmt(err, unit='%', precision=2):>10} "
            f"{st:>8}"
        )

    lines.append("-" * 88)
    lines.append(
        f"Aux: total constrained reaction Fz = {_fmt(ansys.total_constrained_reaction_fz_n)} N"
    )
    lines.append(f"Aux: total input Fz from RST      = {_fmt(ansys.total_input_fz_n)} N")
    lines.append("")

    if not numeric_errors:
        lines.append("Overall verdict: INCONCLUSIVE (no comparable numeric ANSYS metrics found).")
    elif failed_metrics:
        lines.append("Overall verdict: FAIL (one or more key metrics exceed threshold).")
    else:
        lines.append("Overall verdict: PASS (all comparable metrics are within threshold).")

    if failed_metrics:
        lines.append("")
        lines.append("Likely causes to investigate:")
        # This specific run commonly fails because FK loads are overwritten in APDL.
        if ansys.total_input_fz_n is not None and abs(ansys.total_input_fz_n) < 1e-6:
            lines.append(
                "- Applied FZ from RST sums to ~0 N, indicating lift loads may be overwritten "
                "by later FK commands on the same DOF."
            )
        lines.append("- Coordinate/sign convention mismatch (UZ or reaction sign).")
        lines.append("- Boundary condition mismatch (wire/root constraints).")
        lines.append("- Stress extraction method mismatch (nodal-averaged vs element SMISC).")
        lines.append("- Unit mismatch (m vs mm, Pa vs MPa).")

    return "\n".join(lines) + "\n"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare ANSYS MAPDL results to internal FEM cross-validation report."
    )
    parser.add_argument(
        "--ansys-dir",
        default="/Volumes/Samsung SSD/SyncFile/ANSYS_Result",
        help="Directory containing ANSYS result files (file.rst, *.out, etc.).",
    )
    parser.add_argument(
        "--baseline-report",
        default="output/blackcat_004/ansys/crossval_report.txt",
        help="Path to internal FEM baseline crossval_report.txt.",
    )
    parser.add_argument(
        "--rst",
        default="file.rst",
        help="RST filename under --ansys-dir (default: file.rst).",
    )
    parser.add_argument(
        "--threshold-pct",
        type=float,
        default=5.0,
        help="Pass threshold for percentage error.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output text file path for the comparison report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    ansys_dir = Path(args.ansys_dir).expanduser().resolve()
    baseline_report = Path(args.baseline_report).expanduser().resolve()
    rst_path = ansys_dir / args.rst
    mac_path = ansys_dir / "spar_model.mac"

    if not ansys_dir.exists():
        raise FileNotFoundError(f"ANSYS directory not found: {ansys_dir}")
    if not baseline_report.exists():
        raise FileNotFoundError(f"Baseline report not found: {baseline_report}")
    if not rst_path.exists():
        raise FileNotFoundError(f"RST file not found: {rst_path}")

    baseline = parse_baseline_metrics(baseline_report, mac_path=mac_path)
    ansys = extract_ansys_metrics_from_rst(rst_path, baseline, ansys_dir)
    report = build_report_text(
        baseline,
        ansys,
        threshold_pct=float(args.threshold_pct),
        ansys_dir=ansys_dir,
        rst_path=rst_path,
    )

    print(report)
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"Saved comparison report: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
