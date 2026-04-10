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
    export_mode: str = "unknown"


@dataclass
class AnsysMetrics:
    tip_deflection_mm: Optional[float] = None
    max_uz_mm: Optional[float] = None
    max_vm_main_mpa: Optional[float] = None
    max_vm_rear_mpa: Optional[float] = None
    root_reaction_fz_n: Optional[float] = None
    max_twist_deg: Optional[float] = None
    total_spar_mass_kg: Optional[float] = None
    root_only_reaction_fz_n: Optional[float] = None
    total_constrained_reaction_fz_n: Optional[float] = None
    total_input_fz_n: Optional[float] = None


def _extract_float(pattern: str, text: str, field_name: str) -> float:
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"Could not parse baseline metric: {field_name}")
    return float(match.group(1))


def parse_baseline_metrics(report_path: Path, mac_path: Optional[Path] = None) -> BaselineMetrics:
    text = report_path.read_text(encoding="utf-8")
    mode_match = re.search(r"Export mode:\s*([A-Za-z0-9_-]+)", text)
    export_mode = mode_match.group(1).lower().replace("-", "_") if mode_match else "unknown"

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
    # Backward compatibility:
    # - Old report label: "Total spar mass (full-span)"
    # - New report label: "Spar tube mass (full-span)"
    try:
        total_spar_mass_kg = _extract_float(
            r"Spar tube mass \(full-span\)\s+([+-]?\d+(?:\.\d+)?)\s+kg",
            text,
            "total_spar_mass_kg",
        )
    except ValueError:
        total_spar_mass_kg = _extract_float(
            r"Total spar mass \(full-span\)\s+([+-]?\d+(?:\.\d+)?)\s+kg",
            text,
            "total_spar_mass_kg",
        )

    tip_node = int(_extract_float(r"\*GET,TIP_UZ,NODE,(\d+),U,Z", text, "tip_node"))

    nodes_per_spar = tip_node
    if mac_path is not None and mac_path.exists():
        mac_text = mac_path.read_text(encoding="utf-8")
        match = re.search(r"!\s*Nodes/(?:spar|beam)\s*:\s*(\d+)", mac_text)
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
        export_mode=export_mode,
    )


def _extract_mass_from_out_files(ansys_dir: Path) -> Optional[float]:
    """Extract approximate total mass from MAPDL *.out files (if available)."""
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


def _extract_mass_from_mac(mac_path: Path) -> Optional[float]:
    """Compute full-span spar mass from APDL geometry/material cards.

    This is robust against distributed MAPDL runs where *.out mass summaries
    may be split across ranks and under-reported.
    """
    if not mac_path.exists():
        return None

    text = mac_path.read_text(encoding="utf-8", errors="ignore")

    dens_pattern = re.compile(
        r"^\s*MP,\s*DENS,\s*(\d+)\s*,\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)",
        flags=re.MULTILINE,
    )
    kp_pattern = re.compile(
        r"^\s*K,\s*(\d+)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)",
        flags=re.MULTILINE,
    )
    line_pattern = re.compile(r"^\s*L,\s*(\d+)\s*,\s*(\d+)\s*$", flags=re.MULTILINE)
    number = r"([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)"
    ctube_sec_pattern = re.compile(
        rf"SECTYPE,\s*(\d+)\s*,\s*BEAM\s*,\s*CTUBE\s*\n\s*SECDATA,\s*{number}\s*,\s*{number}",
        flags=re.MULTILINE,
    )
    asec_sec_pattern = re.compile(
        rf"SECTYPE,\s*(\d+)\s*,\s*BEAM\s*,\s*ASEC\s*\n\s*SECDATA,\s*{number}",
        flags=re.MULTILINE,
    )

    densities = {int(m.group(1)): float(m.group(2)) for m in dens_pattern.finditer(text)}
    keypoints = {
        int(m.group(1)): (float(m.group(2)), float(m.group(3)), float(m.group(4)))
        for m in kp_pattern.finditer(text)
    }

    # APDL line IDs are implicit in creation order in this exporter.
    line_id_to_nodes: dict[int, tuple[int, int]] = {}
    for idx, m in enumerate(line_pattern.finditer(text), start=1):
        line_id_to_nodes[idx] = (int(m.group(1)), int(m.group(2)))

    section_id_to_area: dict[int, float] = {}
    for m in ctube_sec_pattern.finditer(text):
        r_i = float(m.group(2))
        r_o = float(m.group(3))
        section_id_to_area[int(m.group(1))] = float(np.pi * max(r_o**2 - r_i**2, 0.0))
    for m in asec_sec_pattern.finditer(text):
        section_id_to_area[int(m.group(1))] = max(float(m.group(2)), 0.0)

    if not densities or not keypoints or not line_id_to_nodes or not section_id_to_area:
        return None

    mappings: list[tuple[int, int, int]] = []
    current_line_id: Optional[int] = None
    for ln in text.splitlines():
        line_match = re.match(r"^\s*LSEL,\s*S,\s*LINE,,\s*(\d+)\s*$", ln)
        if line_match:
            current_line_id = int(line_match.group(1))
            continue

        latt_match = re.match(r"^\s*LATT,\s*(\d+)\s*,,\s*\d+,,,,\s*(\d+)", ln)
        if latt_match and current_line_id is not None:
            mat_id = int(latt_match.group(1))
            sec_id = int(latt_match.group(2))
            mappings.append((current_line_id, mat_id, sec_id))

    if not mappings:
        return None

    half_mass_kg = 0.0
    for line_id, mat_id, sec_id in mappings:
        if mat_id not in densities or sec_id not in section_id_to_area or line_id not in line_id_to_nodes:
            continue
        n1, n2 = line_id_to_nodes[line_id]
        if n1 not in keypoints or n2 not in keypoints:
            continue

        x1, y1, z1 = keypoints[n1]
        x2, y2, z2 = keypoints[n2]
        length = float(np.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2))

        area = section_id_to_area[sec_id]
        half_mass_kg += area * length * densities[mat_id]

    # Model is half-span; crossval baseline mass is full-span.
    return 2.0 * half_mass_kg


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
    if baseline.export_mode == "equivalent_beam":
        main_mask = (pnnum >= 1) & (pnnum <= nn)
        rear_mask = np.zeros_like(main_mask, dtype=bool)
    else:
        main_mask = (pnnum >= 1) & (pnnum <= nn)
        rear_mask = (pnnum >= nn + 1) & (pnnum <= 2 * nn)

    max_vm_main_mpa = float(np.nanmax(seqv_pa[main_mask]) / 1e6) if np.any(main_mask) else None
    max_vm_rear_mpa = float(np.nanmax(seqv_pa[rear_mask]) / 1e6) if np.any(rear_mask) else None

    # Root reaction diagnostics:
    # - root_only_fz: main/rear root nodes only (1 and nn+1)
    # - total_reaction_fz: all constrained nodes (includes wire support)
    rforces, rnodes, rdof = result.nodal_reaction_forces(0)
    fz_mask = rdof == 3
    if baseline.export_mode == "equivalent_beam":
        root_mask = rnodes == 1
    else:
        root_mask = (rnodes == 1) | (rnodes == nn + 1)
    root_only_fz = float(np.sum(rforces[fz_mask & root_mask])) if np.any(fz_mask & root_mask) else None
    total_reaction_fz = float(np.sum(rforces[fz_mask])) if np.any(fz_mask) else None

    input_nodes, input_dof, input_force = result.nodal_input_force(0)
    input_fz = float(np.sum(input_force[input_dof == 3])) if np.any(input_dof == 3) else None

    mac_path = ansys_dir / "spar_model.mac"
    total_mass_kg = _extract_mass_from_mac(mac_path)
    if total_mass_kg is None:
        total_mass_kg = _extract_mass_from_out_files(ansys_dir)

    # Baseline "Root reaction Fz" is equilibrium-based (total applied lift).
    # For wire-supported models, compare against total constrained Fz magnitude.
    reaction_for_comparison = abs(total_reaction_fz) if total_reaction_fz is not None else None

    return AnsysMetrics(
        tip_deflection_mm=tip_uz_mm,
        max_uz_mm=max_uz_mm,
        max_vm_main_mpa=max_vm_main_mpa,
        max_vm_rear_mpa=max_vm_rear_mpa,
        root_reaction_fz_n=reaction_for_comparison,
        max_twist_deg=None,  # Not directly available from this RST/post setup.
        total_spar_mass_kg=total_mass_kg,
        root_only_reaction_fz_n=root_only_fz,
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
    return "PASS" if error_pct <= threshold else "FAIL"


def build_report_text(
    baseline: BaselineMetrics,
    ansys: AnsysMetrics,
    *,
    threshold_pct: float,
    ansys_dir: Path,
    rst_path: Path,
    stress_gating_confirmed: bool = False,
) -> str:
    is_equiv = baseline.export_mode == "equivalent_beam"
    stress_gate = bool(is_equiv and stress_gating_confirmed)
    rows = [
        ("Tip deflection @ tip node (mm)", baseline.tip_deflection_mm, ansys.tip_deflection_mm, 5.0, is_equiv, "gate"),
        ("Max |UZ| anywhere (mm)", baseline.max_uz_mm, ansys.max_uz_mm, 5.0, is_equiv, "gate"),
        (
            "Max Von Mises main spar (MPa)",
            baseline.max_vm_main_mpa,
            ansys.max_vm_main_mpa,
            threshold_pct,
            stress_gate,
            "stress provisional",
        ),
        (
            "Max Von Mises rear spar (MPa)",
            baseline.max_vm_rear_mpa,
            ansys.max_vm_rear_mpa,
            threshold_pct,
            stress_gate,
            "stress provisional",
        ),
        ("Root/support reaction Fz (N)", baseline.root_reaction_fz_n, ansys.root_reaction_fz_n, 1.0, is_equiv, "gate"),
        ("Max twist angle (deg)", baseline.max_twist_deg, ansys.max_twist_deg, threshold_pct, False, "info"),
        ("Total spar mass full-span (kg)", baseline.total_spar_mass_kg, ansys.total_spar_mass_kg, 1.0, is_equiv, "gate"),
    ]

    lines: list[str] = []
    lines.append("=" * 88)
    lines.append("ANSYS vs Internal FEM Cross-Validation Summary")
    lines.append("=" * 88)
    lines.append(f"ANSYS directory : {ansys_dir}")
    lines.append(f"RST file        : {rst_path}")
    lines.append(f"Baseline mode   : {baseline.export_mode}")
    if is_equiv:
        lines.append("Phase I gate    : equivalent-beam validation metrics only")
    else:
        lines.append("Phase I gate    : disabled (dual-spar inspection/model-form discrepancy mode)")
    lines.append("")
    lines.append(
        f"{'Metric':36} {'Baseline':>12} {'ANSYS':>12} {'Error %':>10} {'Role':>14} {'Status':>8}"
    )
    lines.append("-" * 88)

    failed_metrics: list[str] = []
    missing_gate_metrics: list[str] = []

    for metric, baseline_value, ansys_value, threshold, gate, role in rows:
        err = _error_percent(ansys_value, baseline_value)
        if gate:
            st = _status(err, threshold)
            if err is None:
                missing_gate_metrics.append(metric)
            elif err > threshold:
                failed_metrics.append(metric)
            role_text = f"gate <= {threshold:.1f}%"
        elif role.startswith("stress"):
            st = "GATED" if stress_gate else "PROV"
            role_text = "non-gating" if not stress_gate else f"gate <= {threshold:.1f}%"
        else:
            st = "INFO"
            role_text = "non-gating"
        lines.append(
            f"{metric:36} "
            f"{_fmt(baseline_value):>12} "
            f"{_fmt(ansys_value):>12} "
            f"{_fmt(err, unit='%', precision=2):>10} "
            f"{role_text:>14} "
            f"{st:>8}"
        )

    lines.append("-" * 88)
    lines.append(
        f"Aux: root-only reaction Fz (nodes 1 & nn+1) = {_fmt(ansys.root_only_reaction_fz_n)} N"
    )
    lines.append(
        f"Aux: total constrained reaction Fz = {_fmt(ansys.total_constrained_reaction_fz_n)} N"
    )
    lines.append(f"Aux: total input Fz from RST      = {_fmt(ansys.total_input_fz_n)} N")
    lines.append("")

    if not is_equiv:
        lines.append(
            "Overall verdict: INFO ONLY (dual-spar discrepancies are higher-fidelity/model-form "
            "differences, not Phase I validation failures)."
        )
    elif missing_gate_metrics:
        lines.append("Overall verdict: INCONCLUSIVE (one or more gating metrics were unavailable).")
    elif failed_metrics:
        lines.append("Overall verdict: FAIL (one or more equivalent-beam gating metrics exceed tolerance).")
    else:
        lines.append("Overall verdict: PASS (all equivalent-beam gating metrics are within tolerance).")

    lines.append("")
    lines.append(
        "Stress note: ANSYS beam stress extraction is provisional here. Do not claim a "
        "Python von Mises bug unless the BEAM188 beam/fiber extraction path has first "
        "been validated as apples-to-apples."
    )

    if missing_gate_metrics:
        lines.append("")
        lines.append("Unavailable gating metrics:")
        for metric in missing_gate_metrics:
            lines.append(f"- {metric}")

    if failed_metrics:
        lines.append("")
        lines.append("Likely causes to investigate:")
        if ansys.total_input_fz_n is not None and abs(ansys.total_input_fz_n) < 1e-6:
            lines.append(
                "- Applied FZ from RST sums to ~0 N, indicating lift loads may be overwritten "
                "by later FK commands on the same DOF."
            )
        lines.append("- Coordinate/sign convention mismatch (UZ or reaction sign).")
        lines.append("- Boundary condition mismatch (wire/root constraints).")
        lines.append("- Equivalent-section A/I/J or element material mapping mismatch.")
        lines.append("- Equivalent nodal load mismatch (lift, self-weight, or direct My torque).")
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
        help="Fallback pass threshold for optional stress gating.",
    )
    parser.add_argument(
        "--stress-gating-confirmed",
        action="store_true",
        help=(
            "Gate stress metrics too. Only use after ANSYS BEAM188 stress extraction "
            "has been confirmed apples-to-apples with the internal stress recovery."
        ),
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
        stress_gating_confirmed=bool(args.stress_gating_confirmed),
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
