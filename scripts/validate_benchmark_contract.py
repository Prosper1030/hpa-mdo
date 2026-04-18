#!/usr/bin/env python3
"""Validate a locked benchmark case against the current AI structural baseline.

This script intentionally stays small and opinionated:

- AI side: read the current design JSON (for example discrete_layup_final_design.json)
- CalculiX side: read one static .inp + .dat + .frd case
- Compare only the frozen benchmark metrics
- Print a compact PASS / FAIL report
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any

import numpy as np

NUMBER_RE = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?"
SUPPORTED_TRI_TYPES = {"S3", "CPS3", "STRI3"}
SUPPORTED_QUAD_TYPES = {"S4", "CPS4", "S4R"}


@dataclass(frozen=True)
class BenchmarkMetrics:
    mass_half_wing_kg: float
    total_reaction_fz_n: float
    tip_deflection_m: float
    tip_twist_deg: float | None
    wall_thickness_m: float | None = None
    mass_definition: str = "unspecified"


@dataclass(frozen=True)
class MetricResult:
    label: str
    lhs_value: float | None
    rhs_value: float | None
    diff_abs: float | None
    diff_pct: float | None
    passed: bool
    unit: str
    pass_rule: str
    status_text: str
    note: str | None = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a frozen benchmark contract case.")
    parser.add_argument("--ai-json", required=True, help="AI metrics JSON path.")
    parser.add_argument("--ccx-inp", required=True, help="CalculiX static .inp path.")
    parser.add_argument("--ccx-dat", required=True, help="CalculiX static .dat path.")
    parser.add_argument("--ccx-frd", required=True, help="CalculiX static .frd path.")
    parser.add_argument(
        "--load-csv",
        default=None,
        help="Optional frozen load CSV. When provided, its total vertical load becomes the reaction reference.",
    )
    parser.add_argument(
        "--reaction-reference-n",
        type=float,
        default=None,
        help="Fallback reaction reference total |Fz| [N]. Required when --load-csv is omitted.",
    )
    parser.add_argument(
        "--main-tip-probe",
        default="0.12375,16.50000,0.891232",
        help="Main tip probe in meters as x,y,z.",
    )
    parser.add_argument(
        "--rear-tip-probe",
        default="0.31450,16.50000,0.890333",
        help="Rear tip probe in meters as x,y,z.",
    )
    parser.add_argument("--mass-threshold-pct", type=float, default=0.1)
    parser.add_argument(
        "--ai-mass-mode",
        choices=("auto", "tube", "total_structural", "continuous"),
        default="auto",
        help=(
            "Which AI mass definition to compare against the CalculiX deck. "
            "'tube' uses discrete/spar tube mass only, 'total_structural' uses "
            "the structural recheck total mass, and 'auto' refuses ambiguous payloads."
        ),
    )
    parser.add_argument("--reaction-threshold-pct", type=float, default=1.0)
    parser.add_argument("--deflection-threshold-pct", type=float, default=5.0)
    parser.add_argument("--twist-threshold-pct", type=float, default=10.0)
    parser.add_argument("--twist-threshold-deg", type=float, default=0.20)
    parser.add_argument(
        "--twist-sanity-limit-deg",
        type=float,
        default=15.0,
        help="Reject CalculiX twist readback beyond this absolute magnitude as invalid.",
    )
    parser.add_argument(
        "--rear-probe-uz-ratio-limit",
        type=float,
        default=5.0,
        help="Reject twist readback when rear tip |Uz| exceeds this multiple of main tip |Uz|.",
    )
    parser.add_argument(
        "--rear-probe-abs-uz-limit-m",
        type=float,
        default=5.0,
        help="Reject twist readback when rear tip |Uz| exceeds this absolute value.",
    )
    return parser


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_args()


def _parse_probe(text: str) -> tuple[float, float, float]:
    parts = [item.strip() for item in text.split(",")]
    if len(parts) != 3:
        raise ValueError(f"Probe must be x,y,z; got {text!r}")
    return tuple(float(item) for item in parts)  # type: ignore[return-value]


def _require_metric(value: Any, label: str) -> float:
    if value is None:
        raise ValueError(f"Missing required metric: {label}")
    return float(value)


def _resolve_ai_mass_definition(
    payload: dict[str, Any],
    recheck: dict[str, Any],
    *,
    mass_mode: str,
) -> tuple[float, str]:
    tube_mass_full = None
    for candidate in (
        payload.get("discrete_full_wing_mass_kg"),
        payload.get("spar_mass_full_kg"),
    ):
        if candidate is not None:
            tube_mass_full = float(candidate)
            break
    continuous_mass_full = payload.get("continuous_full_wing_mass_kg")
    if continuous_mass_full is not None:
        continuous_mass_full = float(continuous_mass_full)
    total_structural_mass_full = recheck.get("total_mass_full_kg")
    if total_structural_mass_full is not None:
        total_structural_mass_full = float(total_structural_mass_full)

    if mass_mode == "tube":
        if tube_mass_full is None:
            raise ValueError("AI JSON is missing discrete/spar tube mass for --ai-mass-mode tube.")
        return tube_mass_full, "tube"
    if mass_mode == "total_structural":
        if total_structural_mass_full is None:
            raise ValueError(
                "AI JSON is missing structural_recheck.total_mass_full_kg for "
                "--ai-mass-mode total_structural."
            )
        return total_structural_mass_full, "total_structural"
    if mass_mode == "continuous":
        if continuous_mass_full is None:
            raise ValueError(
                "AI JSON is missing continuous_full_wing_mass_kg for --ai-mass-mode continuous."
            )
        return continuous_mass_full, "continuous"

    available: list[tuple[str, float]] = []
    if tube_mass_full is not None:
        available.append(("tube", tube_mass_full))
    if total_structural_mass_full is not None:
        available.append(("total_structural", total_structural_mass_full))
    if continuous_mass_full is not None:
        available.append(("continuous", continuous_mass_full))
    if not available:
        raise ValueError("Could not find any AI full-wing mass in the JSON payload.")
    if len(available) == 1:
        return available[0][1], available[0][0]

    labels = ", ".join(f"{name}={value:.6f} kg" for name, value in available)
    raise ValueError(
        "AI JSON contains multiple mass definitions. Re-run with "
        f"--ai-mass-mode to choose one explicitly: {labels}"
    )


def load_ai_metrics(json_path: str | Path, *, mass_mode: str) -> BenchmarkMetrics:
    payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
    recheck = payload.get("structural_recheck", {}) if isinstance(payload, dict) else {}

    full_mass, mass_definition = _resolve_ai_mass_definition(
        payload,
        recheck if isinstance(recheck, dict) else {},
        mass_mode=mass_mode,
    )

    tip_deflection_m = None
    for candidate in (
        recheck.get("tip_deflection_m"),
        payload.get("tip_deflection_m"),
    ):
        if candidate is not None:
            tip_deflection_m = float(candidate)
            break
    if tip_deflection_m is None:
        raise ValueError("Could not find AI tip deflection in the JSON payload.")

    tip_twist_deg = None
    for candidate in (
        recheck.get("twist_max_deg"),
        payload.get("twist_max_deg"),
        payload.get("tip_twist_deg"),
    ):
        if candidate is not None:
            tip_twist_deg = float(candidate)
            break
    if tip_twist_deg is None:
        raise ValueError("Could not find AI tip twist in the JSON payload.")

    wall_thickness_values: list[float] = []
    spars = payload.get("spars", {})
    if isinstance(spars, dict):
        for spar_payload in spars.values():
            if not isinstance(spar_payload, dict):
                continue
            for segment in spar_payload.get("segments", []):
                if not isinstance(segment, dict):
                    continue
                equiv = segment.get("equivalent_properties", {})
                if isinstance(equiv, dict) and equiv.get("wall_thickness") is not None:
                    wall_thickness_values.append(float(equiv["wall_thickness"]))
    wall_thickness_m = None
    if wall_thickness_values:
        unique_values = {round(value, 9) for value in wall_thickness_values}
        if len(unique_values) == 1:
            wall_thickness_m = wall_thickness_values[0]

    return BenchmarkMetrics(
        mass_half_wing_kg=0.5 * float(full_mass),
        total_reaction_fz_n=float("nan"),
        tip_deflection_m=float(tip_deflection_m),
        tip_twist_deg=float(tip_twist_deg),
        wall_thickness_m=wall_thickness_m,
        mass_definition=mass_definition,
    )


def _load_reaction_reference(load_csv: str | Path | None, reaction_reference_n: float | None) -> float:
    if load_csv is not None:
        lines = Path(load_csv).read_text(encoding="utf-8").splitlines()
        if not lines:
            raise ValueError(f"Load CSV is empty: {load_csv}")
        header = [item.strip() for item in lines[0].split(",")]
        required = {"main_fz_n", "rear_fz_n"}
        if not required.issubset(header):
            raise ValueError(
                f"Load CSV must contain {sorted(required)} columns; got {header}"
            )
        main_idx = header.index("main_fz_n")
        rear_idx = header.index("rear_fz_n")
        total = 0.0
        for raw in lines[1:]:
            stripped = raw.strip()
            if not stripped:
                continue
            parts = [item.strip() for item in stripped.split(",")]
            total += float(parts[main_idx]) + float(parts[rear_idx])
        return abs(total)
    if reaction_reference_n is None:
        raise ValueError("Provide either --load-csv or --reaction-reference-n.")
    return abs(float(reaction_reference_n))


def _parse_total_force_from_dat(dat_path: str | Path, set_name: str = "HPA_SUPPORT_ALL") -> float:
    lines = Path(dat_path).read_text(encoding="utf-8", errors="ignore").splitlines()
    header = re.compile(
        rf"total force \(fx,fy,fz\) for set\s+{re.escape(set_name)}\s+and time",
        flags=re.IGNORECASE,
    )
    values = re.compile(
        rf"^\s*({NUMBER_RE})\s+({NUMBER_RE})\s+({NUMBER_RE})\s*$",
        flags=re.IGNORECASE,
    )
    for idx, raw in enumerate(lines):
        if not header.search(raw):
            continue
        for candidate in lines[idx + 1 : idx + 6]:
            match = values.match(candidate)
            if match is None:
                continue
            return abs(float(match.group(3).replace("D", "E")))
        break
    raise ValueError(f"Could not find total support reaction set {set_name} in {dat_path}")


def _numeric_tokens(line: str) -> list[float]:
    return [
        float(token.replace("D", "E"))
        for token in re.findall(NUMBER_RE, line)
    ]


def parse_displacement(frd_path: str | Path) -> np.ndarray:
    rows: list[list[float]] = []
    current_rows: list[list[float]] = []
    in_disp = False

    for raw in Path(frd_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("-4") and "DISP" in upper:
            in_disp = True
            current_rows = []
            continue
        if in_disp and upper.startswith("-4"):
            in_disp = False
            if current_rows:
                rows = current_rows
            continue
        if not in_disp:
            continue
        if stripped.startswith("-3"):
            in_disp = False
            if current_rows:
                rows = current_rows
            continue
        if stripped.startswith("-1"):
            values = _numeric_tokens(stripped)
            if len(values) >= 5:
                current_rows.append([values[1], values[2], values[3], values[4]])

    if not rows:
        return np.empty((0, 4), dtype=float)
    return np.asarray(rows, dtype=float)


def parse_nodal_coordinates(frd_path: str | Path) -> np.ndarray:
    rows: list[list[float]] = []
    in_coordinates = False

    for raw in Path(frd_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("2C"):
            in_coordinates = True
            rows = []
            continue
        if in_coordinates and stripped.startswith("-3"):
            break
        if not in_coordinates:
            continue
        if stripped.startswith("-1"):
            values = _numeric_tokens(stripped)
            if len(values) >= 5:
                rows.append([values[1], values[2], values[3], values[4]])

    if not rows:
        return np.empty((0, 4), dtype=float)
    return np.asarray(rows, dtype=float)


def _infer_length_scale_to_m(coords: np.ndarray) -> float:
    if coords.size == 0:
        raise ValueError("No coordinates were available to infer length scale.")
    max_abs = float(np.max(np.abs(coords[:, 1:4])))
    return 0.001 if max_abs > 100.0 else 1.0


def _nearest_probe(
    coords_m: np.ndarray,
    disp_m: np.ndarray,
    probe_m: tuple[float, float, float],
) -> tuple[int, float, np.ndarray, np.ndarray]:
    xyz = coords_m[:, 1:4]
    deltas = xyz - np.asarray(probe_m, dtype=float)
    distances = np.linalg.norm(deltas, axis=1)
    idx = int(np.argmin(distances))
    return (
        int(coords_m[idx, 0]),
        float(distances[idx]),
        xyz[idx],
        disp_m[idx, 1:4],
    )


def _tri_area(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray) -> float:
    return 0.5 * float(np.linalg.norm(np.cross(p2 - p1, p3 - p1)))


def _infer_inp_length_scale_to_m(nodes: dict[int, np.ndarray]) -> float:
    if not nodes:
        raise ValueError("Could not infer INP length scale without nodes.")
    max_abs = max(float(np.max(np.abs(coords))) for coords in nodes.values())
    return 0.001 if max_abs > 100.0 else 1.0


def _parse_shell_mass_and_section(inp_path: str | Path) -> tuple[float, float | None]:
    nodes: dict[int, np.ndarray] = {}
    shell_elements: list[tuple[str, list[int]]] = []
    density = None
    thickness = None
    mode = None
    current_element_type = None

    for raw in Path(inp_path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("**"):
            continue
        upper = line.upper()
        if line.startswith("*"):
            mode = None
            current_element_type = None
            if upper.startswith("*NODE") and "FILE" not in upper and "PRINT" not in upper:
                mode = "node"
            elif upper.startswith("*ELEMENT"):
                type_match = re.search(r"TYPE\s*=\s*([A-Z0-9]+)", upper)
                current_element_type = type_match.group(1) if type_match is not None else None
                if current_element_type in SUPPORTED_TRI_TYPES | SUPPORTED_QUAD_TYPES:
                    mode = "element"
            elif upper.startswith("*DENSITY"):
                mode = "density"
            elif upper.startswith("*SHELL SECTION"):
                mode = "shell_section"
            continue

        if mode == "node":
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 4:
                nodes[int(parts[0])] = np.asarray([float(parts[1]), float(parts[2]), float(parts[3])])
        elif mode == "element" and current_element_type is not None:
            parts = [part.strip() for part in line.split(",")]
            connectivity = [int(part) for part in parts[1:] if part]
            if connectivity:
                shell_elements.append((current_element_type, connectivity))
        elif mode == "density":
            density = float(line.split(",")[0].strip())
            mode = None
        elif mode == "shell_section":
            thickness = float(line.split(",")[0].strip())
            mode = None

    if density is None or thickness is None:
        raise ValueError(f"Could not parse density / shell thickness from {inp_path}")
    if not shell_elements:
        raise ValueError(f"Could not find supported shell elements in {inp_path}")

    area_total = 0.0
    for element_type, conn in shell_elements:
        if element_type in SUPPORTED_TRI_TYPES:
            if len(conn) < 3:
                continue
            p1, p2, p3 = (nodes[node_id] for node_id in conn[:3])
            area_total += _tri_area(p1, p2, p3)
        elif element_type in SUPPORTED_QUAD_TYPES:
            if len(conn) < 4:
                continue
            p1, p2, p3, p4 = (nodes[node_id] for node_id in conn[:4])
            area_total += _tri_area(p1, p2, p3) + _tri_area(p1, p3, p4)

    scale_to_m = _infer_inp_length_scale_to_m(nodes)
    shell_thickness_m = float(thickness) * scale_to_m
    return float(area_total * thickness * density), shell_thickness_m


def load_ccx_metrics(
    *,
    inp_path: str | Path,
    dat_path: str | Path,
    frd_path: str | Path,
    reaction_reference_n: float,
    main_tip_probe_m: tuple[float, float, float],
    rear_tip_probe_m: tuple[float, float, float],
    twist_sanity_limit_deg: float,
    rear_probe_uz_ratio_limit: float,
    rear_probe_abs_uz_limit_m: float,
) -> BenchmarkMetrics:
    mass_half_wing_kg, wall_thickness_m = _parse_shell_mass_and_section(inp_path)
    total_reaction_fz_n = _parse_total_force_from_dat(dat_path)

    coords_raw = parse_nodal_coordinates(frd_path)
    disp_raw = parse_displacement(frd_path)
    if coords_raw.size == 0 or disp_raw.size == 0:
        raise ValueError(f"Could not parse coordinates / displacements from {frd_path}")

    coord_map = {int(row[0]): row[1:4] for row in coords_raw}
    merged_rows: list[list[float]] = []
    for row in disp_raw:
        node_id = int(row[0])
        if node_id not in coord_map:
            continue
        merged_rows.append([node_id, *coord_map[node_id], *row[1:4]])
    if not merged_rows:
        raise ValueError("FRD displacement node ids did not match FRD coordinate node ids.")

    merged = np.asarray(merged_rows, dtype=float)
    coords_only = merged[:, 0:4]
    scale_to_m = _infer_length_scale_to_m(coords_only)
    coords_m = coords_only.copy()
    coords_m[:, 1:4] *= scale_to_m
    disp_m = np.column_stack([merged[:, 0], merged[:, 4:7] * scale_to_m])

    main_node, _main_dist, _main_xyz, main_disp = _nearest_probe(coords_m, disp_m, main_tip_probe_m)
    rear_node, _rear_dist, rear_xyz, rear_disp = _nearest_probe(
        coords_m, disp_m, rear_tip_probe_m
    )

    tip_deflection_m = abs(float(main_disp[2]))
    x_main = float(_main_xyz[0])
    x_rear = float(rear_xyz[0])
    dx = x_rear - x_main
    if abs(dx) <= 1.0e-9:
        raise ValueError("Rear and main tip probes collapsed to the same x coordinate.")
    tip_twist_deg = math.degrees(math.atan2(float(rear_disp[2] - main_disp[2]), dx))
    main_abs_uz = abs(float(main_disp[2]))
    rear_abs_uz = abs(float(rear_disp[2]))
    if rear_abs_uz > max(rear_probe_abs_uz_limit_m, main_abs_uz * rear_probe_uz_ratio_limit):
        tip_twist_deg = None
    elif abs(tip_twist_deg) > twist_sanity_limit_deg:
        tip_twist_deg = None

    _ = (main_node, rear_node, reaction_reference_n)
    return BenchmarkMetrics(
        mass_half_wing_kg=mass_half_wing_kg,
        total_reaction_fz_n=total_reaction_fz_n,
        tip_deflection_m=tip_deflection_m,
        tip_twist_deg=tip_twist_deg,
        wall_thickness_m=wall_thickness_m,
    )


def _pct_diff(lhs: float, rhs: float) -> float:
    denom = max(abs(rhs), 1.0e-12)
    return abs(lhs - rhs) / denom * 100.0


def _compare_metric(
    *,
    label: str,
    lhs_value: float,
    rhs_value: float,
    threshold_pct: float,
    unit: str,
) -> MetricResult:
    diff_abs = abs(lhs_value - rhs_value)
    diff_pct = _pct_diff(lhs_value, rhs_value)
    return MetricResult(
        label=label,
        lhs_value=lhs_value,
        rhs_value=rhs_value,
        diff_abs=diff_abs,
        diff_pct=diff_pct,
        passed=diff_pct <= threshold_pct,
        unit=unit,
        pass_rule=f"<= {threshold_pct:.2f}%",
        status_text="PASS" if diff_pct <= threshold_pct else "FAIL",
    )


def _compare_twist(
    *,
    ai_twist_deg: float,
    ccx_twist_deg: float,
    threshold_pct: float,
    threshold_deg: float,
) -> MetricResult:
    if ccx_twist_deg is None:
        return MetricResult(
            label="Tip twist",
            lhs_value=ai_twist_deg,
            rhs_value=None,
            diff_abs=None,
            diff_pct=None,
            passed=False,
            unit="deg",
            pass_rule=f"<= {threshold_pct:.2f}% or <= {threshold_deg:.3f} deg",
            status_text="INVALID",
            note="CalculiX rear tip probe response is unstable for this deck; twist readback rejected.",
        )
    diff_abs = abs(ccx_twist_deg - ai_twist_deg)
    diff_pct = _pct_diff(ccx_twist_deg, ai_twist_deg)
    passed = diff_abs <= threshold_deg or diff_pct <= threshold_pct
    return MetricResult(
        label="Tip twist",
        lhs_value=ai_twist_deg,
        rhs_value=ccx_twist_deg,
        diff_abs=diff_abs,
        diff_pct=diff_pct,
        passed=passed,
        unit="deg",
        pass_rule=f"<= {threshold_pct:.2f}% or <= {threshold_deg:.3f} deg",
        status_text="PASS" if passed else "FAIL",
    )


def _render_report(results: list[MetricResult]) -> str:
    has_note = any(result.note for result in results)
    lines = [
        "| Metric | AI / Reference | CalculiX | Diff abs | Diff % | Rule | Status |"
        + (" Note |" if has_note else ""),
        "|---|---:|---:|---:|---:|---|---|"
        + ("---|" if has_note else ""),
    ]
    for result in results:
        lhs_value = "—" if result.lhs_value is None else f"{result.lhs_value:.6f} {result.unit}"
        rhs_value = "—" if result.rhs_value is None else f"{result.rhs_value:.6f} {result.unit}"
        diff_abs = "—" if result.diff_abs is None else f"{result.diff_abs:.6f} {result.unit}"
        diff_pct = "—" if result.diff_pct is None else f"{result.diff_pct:.3f}%"
        lines.append(
            "| "
            f"{result.label} | "
            f"{lhs_value} | "
            f"{rhs_value} | "
            f"{diff_abs} | "
            f"{diff_pct} | "
            f"{result.pass_rule} | "
            f"{result.status_text} |"
            + (f" {result.note or '—'} |" if has_note else "")
        )
    overall = "PASS" if all(result.passed for result in results) else "FAIL"
    lines.append("")
    lines.append(f"**OVERALL: {overall}**")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args() if argv is None else _parse_args_from_list(argv)
    main_tip_probe_m = _parse_probe(args.main_tip_probe)
    rear_tip_probe_m = _parse_probe(args.rear_tip_probe)

    ai_metrics = load_ai_metrics(args.ai_json, mass_mode=args.ai_mass_mode)
    reaction_reference_n = _load_reaction_reference(args.load_csv, args.reaction_reference_n)
    ccx_metrics = load_ccx_metrics(
        inp_path=args.ccx_inp,
        dat_path=args.ccx_dat,
        frd_path=args.ccx_frd,
        reaction_reference_n=reaction_reference_n,
        main_tip_probe_m=main_tip_probe_m,
        rear_tip_probe_m=rear_tip_probe_m,
        twist_sanity_limit_deg=args.twist_sanity_limit_deg,
        rear_probe_uz_ratio_limit=args.rear_probe_uz_ratio_limit,
        rear_probe_abs_uz_limit_m=args.rear_probe_abs_uz_limit_m,
    )

    ai_with_reaction = BenchmarkMetrics(
        mass_half_wing_kg=ai_metrics.mass_half_wing_kg,
        total_reaction_fz_n=reaction_reference_n,
        tip_deflection_m=ai_metrics.tip_deflection_m,
        tip_twist_deg=ai_metrics.tip_twist_deg,
    )

    mass_result = _compare_metric(
            label=f"Mass (half-wing, {ai_metrics.mass_definition})",
            lhs_value=ai_with_reaction.mass_half_wing_kg,
            rhs_value=ccx_metrics.mass_half_wing_kg,
            threshold_pct=args.mass_threshold_pct,
            unit="kg",
        )
    if (
        ai_metrics.wall_thickness_m is not None
        and ccx_metrics.wall_thickness_m is not None
        and abs(ai_metrics.wall_thickness_m - ccx_metrics.wall_thickness_m) > 1.0e-9
    ):
        mass_result = MetricResult(
            label=mass_result.label,
            lhs_value=mass_result.lhs_value,
            rhs_value=mass_result.rhs_value,
            diff_abs=mass_result.diff_abs,
            diff_pct=mass_result.diff_pct,
            passed=mass_result.passed,
            unit=mass_result.unit,
            pass_rule=mass_result.pass_rule,
            status_text=mass_result.status_text,
            note=(
                "Contract mismatch: AI wall thickness "
                f"{ai_metrics.wall_thickness_m*1000.0:.3f} mm vs CCX shell section "
                f"{ccx_metrics.wall_thickness_m*1000.0:.3f} mm."
            ),
        )

    results = [
        mass_result,
        _compare_metric(
            label="Total reaction Fz",
            lhs_value=ai_with_reaction.total_reaction_fz_n,
            rhs_value=ccx_metrics.total_reaction_fz_n,
            threshold_pct=args.reaction_threshold_pct,
            unit="N",
        ),
        _compare_metric(
            label="Tip deflection",
            lhs_value=ai_with_reaction.tip_deflection_m,
            rhs_value=ccx_metrics.tip_deflection_m,
            threshold_pct=args.deflection_threshold_pct,
            unit="m",
        ),
        _compare_twist(
            ai_twist_deg=ai_with_reaction.tip_twist_deg,
            ccx_twist_deg=ccx_metrics.tip_twist_deg,
            threshold_pct=args.twist_threshold_pct,
            threshold_deg=args.twist_threshold_deg,
        ),
    ]

    print(_render_report(results))
    return 0 if all(result.passed for result in results) else 1


def _parse_args_from_list(argv: list[str]) -> argparse.Namespace:
    return _build_parser().parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
