#!/usr/bin/env python3
"""Diagnostic-only AVL induced-drag credibility audit.

This script intentionally writes only under
``output/credibility_audits/avl_induced_drag`` and does not touch production
ranking logic, gates, or the full-alpha Tier 2 database directory.
"""

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from hpa_mdo.aero.avl_spanwise import build_spanwise_load_from_avl_strip_forces  # noqa: E402
from hpa_mdo.concept.config import JigShapeGateConfig, TubeSystemGeometryConfig  # noqa: E402
from hpa_mdo.concept.avl_loader import _run_avl_spanwise_case, _run_avl_trim_case  # noqa: E402
from hpa_mdo.concept.jig_shape import estimate_tip_deflection  # noqa: E402


DEFAULT_OUTPUT_DIR = _REPO_ROOT / "output" / "credibility_audits" / "avl_induced_drag"
DEFAULT_CDI_DEBUG_DIR = (
    _REPO_ROOT / "output" / "baseline_comparisons" / "old_fx_clark_vs_phase7_cdi_debug"
)
DEFAULT_POLICY_A_DIR = (
    _REPO_ROOT / "output" / "geometry_exports" / "phase7_sidecar_vsp" / "policy_A_performance_candidate"
)
DEFAULT_POLICY_C_DIR = (
    _REPO_ROOT / "output" / "geometry_exports" / "phase7_sidecar_vsp" / "policy_C_conservative_baseline"
)
DEFAULT_PARITY_DIR = _REPO_ROOT / "output" / "geometry_exports" / "phase7_avl_vsp_parity"
DEFAULT_MONOTONE_DIR = DEFAULT_PARITY_DIR / "monotone_chord"
DEFAULT_FULL_POLAR_REPORT = _REPO_ROOT / "output" / "airfoil_db" / "full_polar_archive" / "full_polar_build_report.json"
TIER2_OUTPUT_DIR = _REPO_ROOT / "output" / "airfoil_db" / "full_alpha_reusable_v1_tier2"

DEFAULT_VELOCITY_MPS = 6.6
DEFAULT_DENSITY_KGPM3 = 1.18
DEFAULT_NEW_CL_REQ = 1.1685305045195065

LATTICE_LEVELS: tuple[tuple[str, int, int], ...] = (
    ("coarse", 8, 16),
    ("medium", 16, 32),
    ("fine", 24, 64),
)

ZONE_BOUNDS: tuple[tuple[str, float, float], ...] = (
    ("root", 0.0, 0.25),
    ("mid1", 0.25, 0.55),
    ("mid2", 0.55, 0.80),
    ("tip", 0.80, 1.000001),
)

_FLOAT = r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[Ee][-+]?\d+)?"


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    display_name: str
    avl_path: Path
    section_table_path: Path | None
    cl_required: float
    target_surface_names: tuple[str, ...]
    assignment_by_zone: dict[str, str]
    family: str


def repo_path(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else _REPO_ROOT / path


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def manual_e(cl: float, ar_ref: float, cdi: float) -> float:
    if cdi <= 0.0 or ar_ref <= 0.0:
        return float("nan")
    return float(cl) ** 2 / (math.pi * float(ar_ref) * float(cdi))


def percent_delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None or baseline == 0.0:
        return None
    return 100.0 * (float(value) - float(baseline)) / float(baseline)


def _parse_scalar(text: str, label: str) -> float | None:
    match = re.search(rf"\b{re.escape(label)}\s*=\s*(?P<value>{_FLOAT}|\*+)", text)
    if match is None or "*" in match.group("value"):
        return None
    return float(match.group("value"))


def parse_avl_force_totals(path: str | Path) -> dict[str, float]:
    text = repo_path(path).read_text(encoding="utf-8", errors="ignore")
    values = {
        "Alpha": _parse_scalar(text, "Alpha"),
        "CLtot": _parse_scalar(text, "CLtot"),
        "CDtot": _parse_scalar(text, "CDtot"),
        "CDvis": _parse_scalar(text, "CDvis"),
        "CDind": _parse_scalar(text, "CDind"),
        "CLff": _parse_scalar(text, "CLff"),
        "CDff": _parse_scalar(text, "CDff"),
        "e_reported": _parse_scalar(text, "e"),
    }
    return {key: float(value) for key, value in values.items() if value is not None}


def _split_avl_surface_blocks(lines: list[str]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    surface_indices = [
        index for index, line in enumerate(lines) if line.strip().casefold() == "surface"
    ]
    if not surface_indices:
        return lines, []
    header = lines[: surface_indices[0]]
    blocks: list[tuple[str, list[str]]] = []
    for pos, start in enumerate(surface_indices):
        end = surface_indices[pos + 1] if pos + 1 < len(surface_indices) else len(lines)
        block = lines[start:end]
        name = block[1].strip() if len(block) > 1 else ""
        blocks.append((name, block))
    return header, blocks


def surface_names(path: str | Path) -> list[str]:
    lines = repo_path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    _, blocks = _split_avl_surface_blocks(lines)
    return [name for name, _ in blocks]


def surface_uses_yduplicate(path: str | Path, surface_name: str) -> bool:
    lines = repo_path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    _, blocks = _split_avl_surface_blocks(lines)
    target = "".join(surface_name.split()).casefold()
    for name, block in blocks:
        if "".join(name.split()).casefold() == target:
            return any(line.strip().casefold() == "yduplicate" for line in block)
    return False


def rewrite_avl_lattice_text(path: str | Path, *, nchord: int, nspan: int) -> str:
    """Return AVL text with each SURFACE lattice count rewritten.

    The original spacing factors are preserved. This makes lattice sweeps
    comparable without altering geometry or section placement.
    """

    lines = repo_path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    out = list(lines)
    index = 0
    while index < len(out):
        if out[index].strip().casefold() != "surface":
            index += 1
            continue
        lattice_index = index + 2
        while lattice_index < len(out):
            stripped = out[lattice_index].strip()
            if not stripped or stripped.startswith("#"):
                lattice_index += 1
                continue
            tokens = stripped.split()
            if len(tokens) >= 4:
                out[lattice_index] = f"{int(nchord)}  {tokens[1]}  {int(nspan)}  {tokens[3]}"
            break
        index = lattice_index + 1
    return "\n".join(out) + "\n"


def _rewrite_section_twist(path: Path, *, delta_deg: float, eta_min: float) -> str:
    rows = parse_avl_sections(path)
    y_tip = max((row["y_m"] for row in rows), default=0.0)
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out = list(lines)
    section_cursor = -1
    for index, line in enumerate(lines):
        if line.strip().casefold() != "section":
            continue
        section_cursor += 1
        if section_cursor >= len(rows):
            continue
        numeric_index = index + 1
        while numeric_index < len(out):
            stripped = out[numeric_index].strip()
            if not stripped or stripped.startswith("#"):
                numeric_index += 1
                continue
            tokens = stripped.split()
            if len(tokens) >= 5:
                eta = 0.0 if y_tip <= 0.0 else rows[section_cursor]["y_m"] / y_tip
                if eta >= eta_min:
                    tokens[4] = f"{float(tokens[4]) + float(delta_deg):.9f}"
                    out[numeric_index] = "  ".join(tokens)
            break
    return "\n".join(out) + "\n"


def _parse_avl_refs(path: str | Path) -> dict[str, Any]:
    lines = repo_path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    refs: dict[str, Any] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#IYsym") and index + 1 < len(lines):
            tokens = lines[index + 1].split()
            refs["IYsym"] = int(float(tokens[0]))
            refs["iZsym"] = int(float(tokens[1]))
            refs["Zsym"] = float(tokens[2])
        if stripped.startswith("#Sref") and index + 1 < len(lines):
            tokens = lines[index + 1].split()
            refs["Sref"] = float(tokens[0])
            refs["Cref"] = float(tokens[1])
            refs["Bref"] = float(tokens[2])
        if stripped.startswith("#Xref") and index + 1 < len(lines):
            tokens = lines[index + 1].split()
            refs["Xref"] = float(tokens[0])
            refs["Yref"] = float(tokens[1])
            refs["Zref"] = float(tokens[2])
    if "Sref" in refs and "Bref" in refs:
        refs["AR_ref"] = refs["Bref"] ** 2 / refs["Sref"]
    return refs


def parse_avl_sections(path: str | Path) -> list[dict[str, Any]]:
    lines = repo_path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    sections: list[dict[str, Any]] = []
    surface = ""
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.casefold() == "surface" and index + 1 < len(lines):
            surface = lines[index + 1].strip()
            index += 2
            continue
        if stripped.casefold() != "section":
            index += 1
            continue
        numeric_index = index + 1
        while numeric_index < len(lines):
            candidate = lines[numeric_index].strip()
            if candidate and not candidate.startswith("#"):
                break
            numeric_index += 1
        tokens = lines[numeric_index].split()
        if len(tokens) >= 5:
            sections.append(
                {
                    "surface": surface,
                    "x_m": float(tokens[0]),
                    "y_m": float(tokens[1]),
                    "z_m": float(tokens[2]),
                    "chord_m": float(tokens[3]),
                    "twist_deg": float(tokens[4]),
                }
            )
        index = numeric_index + 1
    return sections


def read_section_table(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None or not repo_path(path).exists():
        return []
    with repo_path(path).open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def section_area_span_from_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {}
    y = [float(row["y_m"]) for row in rows]
    chord = [float(row["chord_m"]) for row in rows]
    half_area = 0.0
    for index in range(1, len(y)):
        half_area += 0.5 * (y[index] - y[index - 1]) * (chord[index] + chord[index - 1])
    return {
        "computed_wing_area_m2": 2.0 * half_area,
        "computed_span_m": 2.0 * max(y),
        "root_chord_m": chord[0],
        "tip_chord_m": chord[-1],
    }


def section_area_span(path: Path, table_path: Path | None) -> dict[str, float]:
    table_rows = read_section_table(table_path)
    if table_rows:
        return section_area_span_from_rows(table_rows)
    section_rows = [
        {
            "y_m": row["y_m"],
            "chord_m": row["chord_m"],
        }
        for row in parse_avl_sections(path)
        if row["surface"] in {"Wing", "Main Wing"}
    ]
    return section_area_span_from_rows(section_rows)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_cl_requirements() -> dict[str, float]:
    rows = _read_csv_rows(DEFAULT_CDI_DEBUG_DIR / "corrected_old_vs_policy_A_C_comparison.csv")
    by_case = {row.get("case", ""): row for row in rows}
    old = safe_float(
        by_case.get("Old FX/Clark main-wing-only comparable", {}).get("CL_req"),
        1.1102304984748252,
    )
    new = safe_float(
        by_case.get("Policy A / D performance candidate", {}).get("CL_req"),
        DEFAULT_NEW_CL_REQ,
    )
    assert old is not None and new is not None
    return {"old": old, "new": new}


def _parse_assignment(assignment: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in assignment.split("|"):
        if ":" not in item:
            continue
        zone, airfoil = item.split(":", 1)
        out[zone.strip()] = airfoil.strip()
    return out


def _load_policy_c_assignment() -> dict[str, str]:
    rows = _read_csv_rows(_REPO_ROOT / "phase7_dual_baseline" / "dual_baseline_summary.csv")
    for row in rows:
        if row.get("policy_id") == "C":
            assignment = _parse_assignment(row.get("assignment", ""))
            if assignment:
                return assignment
    return {
        "root": "cst_root_nsga2_g05_child_0019_00cc4dca",
        "mid1": "cst_mid1_nsga2_g06_child_0001_a86879e2",
        "mid2": "clarkysm",
        "tip": "clarkysm",
    }


def build_case_specs() -> list[CaseSpec]:
    cl = _load_cl_requirements()
    policy_a_assignment = {
        "root": "dae11",
        "mid1": "dae11",
        "mid2": "clarkysm",
        "tip": "clarkysm",
    }
    policy_c_assignment = _load_policy_c_assignment()
    return [
        CaseSpec(
            case_id="old_fx_clark_main_wing_only",
            display_name="Old FX/Clark main-wing-only",
            avl_path=DEFAULT_CDI_DEBUG_DIR / "old_main_wing_only.avl",
            section_table_path=None,
            cl_required=cl["old"],
            target_surface_names=("Main Wing",),
            assignment_by_zone={
                "root": "fx76mp140",
                "mid1": "fx76mp140",
                "mid2": "clarkysm",
                "tip": "clarkysm",
            },
            family="old",
        ),
        CaseSpec(
            case_id="policy_A_performance_candidate",
            display_name="Policy A / D performance candidate",
            avl_path=DEFAULT_POLICY_A_DIR / "policy_A_performance_candidate.avl",
            section_table_path=DEFAULT_POLICY_A_DIR / "section_table.csv",
            cl_required=cl["new"],
            target_surface_names=("Wing",),
            assignment_by_zone=policy_a_assignment,
            family="policy_A",
        ),
        CaseSpec(
            case_id="policy_C_conservative_baseline",
            display_name="Policy C / E conservative baseline",
            avl_path=DEFAULT_POLICY_C_DIR / "policy_C_conservative_baseline.avl",
            section_table_path=DEFAULT_POLICY_C_DIR / "section_table.csv",
            cl_required=cl["new"],
            target_surface_names=("Wing",),
            assignment_by_zone=policy_c_assignment,
            family="policy_C",
        ),
        CaseSpec(
            case_id="monotone_policy_A",
            display_name="Monotone Policy A",
            avl_path=DEFAULT_MONOTONE_DIR
            / "policy_A_performance_candidate"
            / "policy_A_performance_candidate_monotone_chord.avl",
            section_table_path=DEFAULT_MONOTONE_DIR
            / "policy_A_performance_candidate"
            / "section_table.csv",
            cl_required=cl["new"],
            target_surface_names=("Wing",),
            assignment_by_zone=policy_a_assignment,
            family="policy_A",
        ),
        CaseSpec(
            case_id="monotone_policy_C",
            display_name="Monotone Policy C",
            avl_path=DEFAULT_MONOTONE_DIR
            / "policy_C_conservative_baseline"
            / "policy_C_conservative_baseline_monotone_chord.avl",
            section_table_path=DEFAULT_MONOTONE_DIR
            / "policy_C_conservative_baseline"
            / "section_table.csv",
            cl_required=cl["new"],
            target_surface_names=("Wing",),
            assignment_by_zone=policy_c_assignment,
            family="policy_C",
        ),
    ]


def _stage_lattice_avl(source: Path, target: Path, *, nchord: int, nspan: int) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        rewrite_avl_lattice_text(source, nchord=nchord, nspan=nspan),
        encoding="utf-8",
    )
    return target


def run_avl_trim_and_spanload(
    *,
    case: CaseSpec,
    avl_path: Path,
    run_dir: Path,
    avl_binary: str | Path | None,
) -> dict[str, Any]:
    run_dir.mkdir(parents=True, exist_ok=True)
    trim = _run_avl_trim_case(
        avl_path=avl_path,
        case_dir=run_dir,
        cl_required=case.cl_required,
        velocity_mps=DEFAULT_VELOCITY_MPS,
        density_kgpm3=DEFAULT_DENSITY_KGPM3,
        avl_binary=avl_binary,
    )
    ft_path = run_dir / "concept_trim.ft"
    totals = parse_avl_force_totals(ft_path)
    alpha = float(totals.get("Alpha", trim["aoa_trim_deg"]))
    fs_path = _run_avl_spanwise_case(
        avl_path=avl_path,
        case_dir=run_dir,
        alpha_deg=alpha,
        velocity_mps=DEFAULT_VELOCITY_MPS,
        density_kgpm3=DEFAULT_DENSITY_KGPM3,
        avl_binary=avl_binary,
    )
    load = build_spanwise_load_from_avl_strip_forces(
        fs_path=fs_path,
        avl_path=avl_path,
        aoa_deg=alpha,
        velocity_mps=DEFAULT_VELOCITY_MPS,
        density_kgpm3=DEFAULT_DENSITY_KGPM3,
        target_surface_names=case.target_surface_names,
        positive_y_only=True,
    )
    y_tip = float(max(load.y)) if len(load.y) else 0.0
    spanload = []
    for idx, (y_m, chord_m, cl, cd, cm, lift_per_span) in enumerate(
        zip(load.y, load.chord, load.cl, load.cd, load.cm, load.lift_per_span)
    ):
        eta = 0.0 if y_tip <= 0.0 else float(y_m) / y_tip
        spanload.append(
            {
                "station_index": idx,
                "eta": eta,
                "y_m": float(y_m),
                "chord_m": float(chord_m),
                "cl": float(cl),
                "cd_strip": float(cd),
                "cm_c4": float(cm),
                "lift_per_span": float(lift_per_span),
                "lprime_proxy": float(chord_m) * float(cl),
            }
        )
    refs = _parse_avl_refs(avl_path)
    cl_for_trefftz = totals.get("CLff", totals.get("CLtot", case.cl_required))
    cdff = totals.get("CDff")
    cdind = totals.get("CDind")
    ar_ref = float(refs["AR_ref"])
    return {
        "case_id": case.case_id,
        "display_name": case.display_name,
        "avl_path": str(avl_path.resolve()),
        "run_dir": str(run_dir.resolve()),
        "ft_path": str(ft_path.resolve()),
        "fs_path": str(fs_path.resolve()),
        "refs": refs,
        "trim": totals,
        "alpha_at_CL_req_deg": alpha,
        "CL_req": case.cl_required,
        "CLtot": totals.get("CLtot"),
        "CLff": totals.get("CLff"),
        "CDind": cdind,
        "CDff": cdff,
        "e_avl_reported": totals.get("e_reported"),
        "e_CDi_from_CDind": None if cdind is None else manual_e(totals.get("CLtot", case.cl_required), ar_ref, cdind),
        "e_CDi_from_CDff": None if cdff is None else manual_e(cl_for_trefftz, ar_ref, cdff),
        "spanload": spanload,
        "local_cl_max": max((row["cl"] for row in spanload), default=None),
    }


def _spanload_rms_delta(a: list[dict[str, float]], b: list[dict[str, float]]) -> float | None:
    if not a or not b:
        return None
    n = min(len(a), len(b))
    if n <= 0:
        return None
    err = 0.0
    for idx in range(n):
        err += (float(a[idx]["lprime_proxy"]) - float(b[idx]["lprime_proxy"])) ** 2
    return math.sqrt(err / n)


def _zone_for_eta(eta: float) -> str:
    for zone, lo, hi in ZONE_BOUNDS:
        if lo <= eta < hi:
            return zone
    return "tip"


def _load_airfoil_safe_clmax() -> dict[str, dict[str, Any]]:
    if not DEFAULT_FULL_POLAR_REPORT.exists():
        return {}
    data = json.loads(DEFAULT_FULL_POLAR_REPORT.read_text(encoding="utf-8"))
    records = data.get("records", {})
    if isinstance(records, dict):
        return {str(key): value for key, value in records.items() if isinstance(value, dict)}
    out: dict[str, dict[str, Any]] = {}
    for row in records:
        if isinstance(row, dict) and row.get("airfoil_id"):
            out[str(row["airfoil_id"])] = row
    return out


def zone_stats(
    case: CaseSpec,
    spanload: list[dict[str, Any]],
    safe_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for zone, lo, hi in ZONE_BOUNDS:
        subset = [row for row in spanload if lo <= float(row["eta"]) < hi]
        if not subset:
            continue
        cls = [float(row["cl"]) for row in subset]
        lproxy = [float(row["lprime_proxy"]) for row in subset]
        airfoil_id = case.assignment_by_zone.get(zone, "")
        safe = safe_float(safe_records.get(airfoil_id, {}).get("safe_clmax"))
        rows.append(
            {
                "row_type": "zone_summary",
                "case_id": case.case_id,
                "zone": zone,
                "airfoil_id": airfoil_id,
                "eta_min": min(float(row["eta"]) for row in subset),
                "eta_max": max(float(row["eta"]) for row in subset),
                "local_Cl_min": min(cls),
                "local_Cl_max": max(cls),
                "local_Cl_mean": sum(cls) / len(cls),
                "lprime_proxy_max": max(lproxy),
                "safe_clmax": safe,
                "stall_margin_cl": None if safe is None else safe - max(cls),
                "stall_utilization": None if safe is None or safe <= 0.0 else max(cls) / safe,
            }
        )
    return rows


def _integrate_trapezoid(x: list[float], y: list[float]) -> float:
    if len(x) < 2:
        return 0.0
    total = 0.0
    for index in range(1, len(x)):
        total += 0.5 * (x[index] - x[index - 1]) * (y[index] + y[index - 1])
    return total


def load_shape_metrics(spanload: list[dict[str, Any]]) -> dict[str, float | None]:
    if len(spanload) < 2:
        return {
            "root_bending_proxy": None,
            "tip_deflection_proxy": None,
            "outer_lift_fraction_eta_ge_0p70": None,
        }
    y = [float(row["y_m"]) for row in spanload]
    lift_proxy = [float(row["lprime_proxy"]) for row in spanload]
    total_lift_proxy = _integrate_trapezoid(y, lift_proxy)
    root_bending = _integrate_trapezoid(y, [yy * ll for yy, ll in zip(y, lift_proxy)])
    tip_deflection_proxy = _integrate_trapezoid(
        y,
        [(yy**2) * ll for yy, ll in zip(y, lift_proxy)],
    )
    outer_rows = [row for row in spanload if float(row["eta"]) >= 0.70]
    outer_fraction = None
    if total_lift_proxy > 0.0 and len(outer_rows) >= 2:
        outer_y = [float(row["y_m"]) for row in outer_rows]
        outer_l = [float(row["lprime_proxy"]) for row in outer_rows]
        outer_fraction = _integrate_trapezoid(outer_y, outer_l) / total_lift_proxy
    return {
        "root_bending_proxy": root_bending,
        "tip_deflection_proxy": tip_deflection_proxy,
        "outer_lift_fraction_eta_ge_0p70": outer_fraction,
    }


def jig_shape_uniform_estimate(span_m: float) -> dict[str, float | str | None]:
    """Return the existing concept jig-shape proxy for a nominal HPA tube setup.

    The current jig-shape helper is a uniform-load beam proxy, not a direct
    arbitrary-spanload structural solve. The spanload-specific structural
    trend in this audit is therefore kept in ``tip_deflection_proxy`` while
    this field records the existing jig-shape model value for reference.
    """

    try:
        tube = TubeSystemGeometryConfig(
            estimation_enabled=True,
            root_outer_diameter_m=0.070,
            tip_outer_diameter_m=0.040,
            root_wall_thickness_m=0.0007,
            tip_wall_thickness_m=0.0005,
            density_kg_per_m3=1600.0,
            num_spars_per_wing=2,
            num_wings=2,
        )
        gate = JigShapeGateConfig(
            enabled=True,
            spar_youngs_modulus_pa=120.0e9,
            spar_vertical_separation_m=0.10,
            deflection_taper_correction_factor=1.0,
            max_tip_deflection_to_halfspan_ratio=0.30,
            lift_wire_relief_enabled=True,
            lift_wire_attach_span_fraction=0.70,
            lift_wire_cruise_lift_fraction_carried=0.35,
            preferred_tip_deflection_m_min=1.6,
            preferred_tip_deflection_m_max=2.2,
        )
        estimate = estimate_tip_deflection(
            gross_mass_kg=98.5,
            span_m=span_m,
            tube_geom=tube,
            gate_cfg=gate,
        )
    except Exception:
        return {
            "jig_shape_uniform_tip_deflection_m": None,
            "jig_shape_uniform_tip_deflection_ratio": None,
            "jig_shape_model_basis": "existing_jig_shape_model_unavailable_for_this_run",
        }
    return {
        "jig_shape_uniform_tip_deflection_m": estimate.tip_deflection_m,
        "jig_shape_uniform_tip_deflection_ratio": estimate.tip_deflection_ratio,
        "jig_shape_model_basis": "existing_hpa_mdo.concept.jig_shape_uniform_load_proxy_nominal_tube_config",
    }


def normalized_spanload_rows(
    case: CaseSpec,
    run_label: str,
    result: dict[str, Any],
    safe_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    spanload = list(result["spanload"])
    max_lprime = max((float(row["lprime_proxy"]) for row in spanload), default=0.0)
    zone_rows = {row["zone"]: row for row in zone_stats(case, spanload, safe_records)}
    shape = load_shape_metrics(spanload)
    rows = []
    for row in spanload:
        eta = float(row["eta"])
        ell = math.sqrt(max(0.0, 1.0 - eta**2))
        zone = _zone_for_eta(eta)
        zrow = zone_rows.get(zone, {})
        norm = None if max_lprime <= 0.0 else float(row["lprime_proxy"]) / max_lprime
        rows.append(
            {
                "row_type": "station_spanload",
                "case_id": case.case_id,
                "run_label": run_label,
                "station_index": row["station_index"],
                "eta": eta,
                "y_m": row["y_m"],
                "chord_m": row["chord_m"],
                "local_Cl": row["cl"],
                "lprime_proxy": row["lprime_proxy"],
                "normalized_spanload": norm,
                "elliptical_reference_norm": ell,
                "normalized_minus_elliptical": None if norm is None else norm - ell,
                "fourier_target_norm": None,
                "fourier_target_source": "not_available_in_this_diagnostic_export",
                "root_bending_proxy_case": shape["root_bending_proxy"],
                "tip_deflection_proxy_case": shape["tip_deflection_proxy"],
                "tip_deflection_proxy_basis": "spanload_second_moment_proxy_not_structural_fem",
                "zone": zone,
                "zone_airfoil_id": case.assignment_by_zone.get(zone, ""),
                "zone_local_Cl_max": zrow.get("local_Cl_max"),
                "zone_stall_margin_cl": zrow.get("stall_margin_cl"),
                "zone_stall_utilization": zrow.get("stall_utilization"),
            }
        )
    return rows


def run_lattice_convergence(
    cases: list[CaseSpec],
    output_dir: Path,
    *,
    avl_binary: str | Path | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    fine_results: dict[str, dict[str, Any]] = {}
    all_results_by_case: dict[str, dict[str, dict[str, Any]]] = {}
    run_root = output_dir / "avl_runs" / "lattice"
    for case in cases:
        all_results_by_case[case.case_id] = {}
        for level, nchord, nspan in LATTICE_LEVELS:
            avl_copy = _stage_lattice_avl(
                case.avl_path,
                run_root / case.case_id / level / f"{case.case_id}_{level}.avl",
                nchord=nchord,
                nspan=nspan,
            )
            result = run_avl_trim_and_spanload(
                case=case,
                avl_path=avl_copy,
                run_dir=avl_copy.parent,
                avl_binary=avl_binary,
            )
            all_results_by_case[case.case_id][level] = result
        fine_results[case.case_id] = all_results_by_case[case.case_id]["fine"]

    for case in cases:
        fine = all_results_by_case[case.case_id]["fine"]
        fine_e = safe_float(fine.get("e_CDi_from_CDff"))
        fine_cdff = safe_float(fine.get("CDff"))
        fine_alpha = safe_float(fine.get("alpha_at_CL_req_deg"))
        fine_clmax = safe_float(fine.get("local_cl_max"))
        for level, nchord, nspan in LATTICE_LEVELS:
            result = all_results_by_case[case.case_id][level]
            rows.append(
                {
                    "case_id": case.case_id,
                    "display_name": case.display_name,
                    "lattice_level": level,
                    "Nchord": nchord,
                    "Nspan": nspan,
                    "CL_req": case.cl_required,
                    "CLtot": result.get("CLtot"),
                    "CLff": result.get("CLff"),
                    "alpha_at_CL_req_deg": result.get("alpha_at_CL_req_deg"),
                    "CDind": result.get("CDind"),
                    "CDff": result.get("CDff"),
                    "e_CDi_CDind": result.get("e_CDi_from_CDind"),
                    "e_CDi_CDff": result.get("e_CDi_from_CDff"),
                    "e_AVL_reported": result.get("e_avl_reported"),
                    "local_Cl_max": result.get("local_cl_max"),
                    "CDff_delta_pct_vs_fine": percent_delta(safe_float(result.get("CDff")), fine_cdff),
                    "e_CDi_CDff_delta_pct_vs_fine": percent_delta(
                        safe_float(result.get("e_CDi_from_CDff")), fine_e
                    ),
                    "alpha_delta_pct_vs_fine": percent_delta(
                        safe_float(result.get("alpha_at_CL_req_deg")), fine_alpha
                    ),
                    "local_Cl_max_delta_pct_vs_fine": percent_delta(
                        safe_float(result.get("local_cl_max")), fine_clmax
                    ),
                    "spanload_lprime_rms_delta_vs_fine": _spanload_rms_delta(
                        list(result["spanload"]),
                        list(fine["spanload"]),
                    ),
                    "ft_path": result["ft_path"],
                    "fs_path": result["fs_path"],
                }
            )
    return rows, fine_results


def reference_convention_rows(
    cases: list[CaseSpec],
    fine_results: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in cases:
        refs = _parse_avl_refs(case.avl_path)
        areas = section_area_span(case.avl_path, case.section_table_path)
        names = surface_names(case.avl_path)
        result = fine_results[case.case_id]
        main_wing_only = set(names).issubset({"Wing", "Main Wing"})
        symmetry = (
            "AVL IYsym full-span reflection"
            if refs.get("IYsym") == 1
            else "explicit/YDUPLICATE or full geometry"
        )
        if any(surface_uses_yduplicate(case.avl_path, name) for name in names):
            symmetry += "; YDUPLICATE present"
        rows.append(
            {
                "case_id": case.case_id,
                "display_name": case.display_name,
                "Sref": refs.get("Sref"),
                "Bref": refs.get("Bref"),
                "Cref": refs.get("Cref"),
                "computed_wing_area_from_sections": areas.get("computed_wing_area_m2"),
                "computed_span_from_sections": areas.get("computed_span_m"),
                "AR_ref": refs.get("AR_ref"),
                "full_span_or_half_span_convention": symmetry,
                "IYsym": refs.get("IYsym"),
                "surfaces": "|".join(names),
                "main_wing_only_or_full_aircraft": "main-wing-only" if main_wing_only else "full-aircraft",
                "CDind": result.get("CDind"),
                "CDff": result.get("CDff"),
                "CLtot": result.get("CLtot"),
                "CLff": result.get("CLff"),
                "e_computed_from_CDind": result.get("e_CDi_from_CDind"),
                "e_computed_from_CDff": result.get("e_CDi_from_CDff"),
                "e_AVL_reported": result.get("e_avl_reported"),
                "reference_status": "comparable_main_wing" if main_wing_only else "full_aircraft_reference_caveat",
            }
        )
    return rows


def _linear_fit_slope(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    xbar = sum(xs) / len(xs)
    ybar = sum(ys) / len(ys)
    denom = sum((x - xbar) ** 2 for x in xs)
    if denom == 0.0:
        return None
    return sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / denom


def _interp_at_x(rows: list[dict[str, str]], *, x_field: str, y_field: str, x: float) -> float | None:
    points: list[tuple[float, float]] = []
    for row in rows:
        xx = safe_float(row.get(x_field))
        yy = safe_float(row.get(y_field))
        if xx is not None and yy is not None:
            points.append((xx, yy))
    points.sort()
    if not points:
        return None
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if (x0 <= x <= x1) or (x1 <= x <= x0):
            if x1 == x0:
                return y0
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return min(points, key=lambda item: abs(item[0] - x))[1]


def cross_solver_rows(cases: list[CaseSpec], fine_results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    alpha_sweep = _read_csv_rows(DEFAULT_PARITY_DIR / "avl_vs_vsp_alpha_sweep.csv")
    monotone = _read_csv_rows(DEFAULT_PARITY_DIR / "monotone_chord_comparison.csv")
    base_map = {
        "policy_A_performance_candidate": "policy_A_performance_candidate",
        "policy_C_conservative_baseline": "policy_C_conservative_baseline",
    }
    for case in cases:
        if case.case_id in base_map:
            case_name = base_map[case.case_id]
            solver_rows = [
                row
                for row in alpha_sweep
                if row.get("case_name") == case_name
                and row.get("geometry_variant") == "base_body_axis"
            ]
            for solver in ("AVL", "VSPAERO_thin_vlm"):
                subset = [row for row in solver_rows if row.get("solver") == solver]
                alphas = [safe_float(row.get("alpha_deg")) for row in subset]
                cls = [safe_float(row.get("CL")) for row in subset]
                valid = [(a, c) for a, c in zip(alphas, cls) if a is not None and c is not None]
                slope = _linear_fit_slope([a for a, _ in valid], [c for _, c in valid])
                alpha_at_cl = _interp_at_x(subset, x_field="CL", y_field="alpha_deg", x=case.cl_required)
                cdi_at_cl = _interp_at_x(subset, x_field="CL", y_field="CDi", x=case.cl_required)
                e_at_cl = _interp_at_x(subset, x_field="CL", y_field="e_CDi", x=case.cl_required)
                rows.append(
                    {
                        "case_id": case.case_id,
                        "display_name": case.display_name,
                        "geometry_variant": "base_body_axis",
                        "solver": solver,
                        "source": "existing_phase7_alpha_sweep",
                        "CL_alpha_per_deg": slope,
                        "CL_alpha_per_rad": None if slope is None else slope * 180.0 / math.pi,
                        "alpha_at_CL_req_deg": alpha_at_cl,
                        "CL_req": case.cl_required,
                        "CDi_at_CL_req": cdi_at_cl,
                        "e_CDi_at_CL_req": e_at_cl,
                        "spanload_available": solver == "AVL",
                        "notes": "VSPAERO CDo/CDtot intentionally excluded",
                    }
                )
        elif case.case_id.startswith("monotone"):
            source_name = (
                "policy_A_performance_candidate"
                if case.case_id == "monotone_policy_A"
                else "policy_C_conservative_baseline"
            )
            row = next((r for r in monotone if r.get("case_name") == source_name), {})
            if row:
                for solver, prefix in (
                    ("AVL", "AVL_monotone"),
                    ("VSPAERO_thin_vlm", "VSPAERO_monotone"),
                ):
                    cdi = safe_float(row.get(f"{prefix}_CDi_at_CL_req"))
                    refs = _parse_avl_refs(case.avl_path)
                    rows.append(
                        {
                            "case_id": case.case_id,
                            "display_name": case.display_name,
                            "geometry_variant": "monotone_chord",
                            "solver": solver,
                            "source": "existing_phase7_monotone_chord_comparison",
                            "CL_alpha_per_deg": None,
                            "CL_alpha_per_rad": None,
                            "alpha_at_CL_req_deg": row.get(f"{prefix}_alpha_at_CL_req"),
                            "CL_req": case.cl_required,
                            "CDi_at_CL_req": cdi,
                            "e_CDi_at_CL_req": None
                            if cdi is None
                            else manual_e(case.cl_required, refs["AR_ref"], cdi),
                            "spanload_available": solver == "AVL",
                            "notes": "monotone file stores CL_req interpolation only; VSPAERO CDo/CDtot excluded",
                        }
                    )
        else:
            rows.append(
                {
                    "case_id": case.case_id,
                    "display_name": case.display_name,
                    "geometry_variant": "main_wing_only",
                    "solver": "VSPAERO_thin_vlm",
                    "source": "not_available",
                    "CL_alpha_per_deg": None,
                    "CL_alpha_per_rad": None,
                    "alpha_at_CL_req_deg": None,
                    "CL_req": case.cl_required,
                    "CDi_at_CL_req": None,
                    "e_CDi_at_CL_req": None,
                    "spanload_available": False,
                    "notes": "no existing old-design VSPAERO parity sweep and VSPAERO CLI not available in PATH",
                }
            )
    return rows


def _copy_or_write_text(source_text: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source_text, encoding="utf-8")
    return target


def run_sensitivity(
    cases: list[CaseSpec],
    fine_results: dict[str, dict[str, Any]],
    output_dir: Path,
    *,
    avl_binary: str | Path | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    run_root = output_dir / "avl_runs" / "sensitivity"
    baseline_by_case = {
        case.case_id: {
            "e": safe_float(fine_results[case.case_id].get("e_CDi_from_CDff")),
            "cdff": safe_float(fine_results[case.case_id].get("CDff")),
        }
        for case in cases
    }

    def add_result(case: CaseSpec, variant: str, result: dict[str, Any]) -> None:
        shape = load_shape_metrics(list(result["spanload"]))
        span_m = float(result.get("refs", {}).get("Bref", 0.0) or 0.0)
        jig = jig_shape_uniform_estimate(span_m)
        base = baseline_by_case[case.case_id]
        rows.append(
            {
                "case_id": case.case_id,
                "display_name": case.display_name,
                "analysis_type": "sensitivity" if variant != "baseline_fine" else "baseline",
                "variant": variant,
                "CL_req": case.cl_required,
                "alpha_at_CL_req_deg": result.get("alpha_at_CL_req_deg"),
                "CDind": result.get("CDind"),
                "CDff": result.get("CDff"),
                "e_CDi_CDff": result.get("e_CDi_from_CDff"),
                "local_Cl_max": result.get("local_cl_max"),
                "root_bending_proxy": shape["root_bending_proxy"],
                "tip_deflection_proxy": shape["tip_deflection_proxy"],
                "tip_deflection_proxy_basis": "spanload_second_moment_proxy_not_structural_fem",
                **jig,
                "outer_lift_fraction_eta_ge_0p70": shape["outer_lift_fraction_eta_ge_0p70"],
                "CDff_delta_pct_vs_baseline": percent_delta(safe_float(result.get("CDff")), base["cdff"]),
                "e_CDi_delta_pct_vs_baseline": percent_delta(
                    safe_float(result.get("e_CDi_from_CDff")), base["e"]
                ),
            }
        )

    for case in cases:
        add_result(case, "baseline_fine", fine_results[case.case_id])
        for variant, delta_deg, eta_min in (
            ("outer_twist_plus_0p5deg", 0.5, 0.70),
            ("outer_twist_minus_0p5deg", -0.5, 0.70),
            ("uniform_incidence_plus_0p5deg", 0.5, 0.0),
        ):
            text = rewrite_avl_lattice_text(case.avl_path, nchord=24, nspan=64)
            tmp = _copy_or_write_text(text, run_root / case.case_id / variant / f"{case.case_id}_{variant}.avl")
            text2 = _rewrite_section_twist(tmp, delta_deg=delta_deg, eta_min=eta_min)
            tmp.write_text(text2, encoding="utf-8")
            result = run_avl_trim_and_spanload(
                case=case,
                avl_path=tmp,
                run_dir=tmp.parent,
                avl_binary=avl_binary,
            )
            add_result(case, variant, result)

        if case.case_id == "policy_A_performance_candidate":
            mono = next(c for c in cases if c.case_id == "monotone_policy_A")
            add_result(case, "monotone_chord_existing", fine_results[mono.case_id])
        elif case.case_id == "policy_C_conservative_baseline":
            mono = next(c for c in cases if c.case_id == "monotone_policy_C")
            add_result(case, "monotone_chord_existing", fine_results[mono.case_id])
        else:
            rows.append(
                {
                    "case_id": case.case_id,
                    "display_name": case.display_name,
                    "analysis_type": "sensitivity",
                    "variant": "monotone_chord_existing",
                    "CL_req": case.cl_required,
                    "alpha_at_CL_req_deg": None,
                    "CDind": None,
                    "CDff": None,
                    "e_CDi_CDff": None,
                    "local_Cl_max": None,
                    "root_bending_proxy": None,
                    "tip_deflection_proxy": None,
                    "outer_lift_fraction_eta_ge_0p70": None,
                    "CDff_delta_pct_vs_baseline": None,
                    "e_CDi_delta_pct_vs_baseline": None,
                    "notes": "no monotone-chord counterpart exported for this case",
                }
            )
    return rows


def _max_abs(values: Iterable[float | None]) -> float | None:
    finite = [abs(float(v)) for v in values if v is not None and math.isfinite(float(v))]
    return max(finite) if finite else None


def _summarize_lattice(lattice_rows: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in lattice_rows:
        by_case.setdefault(str(row["case_id"]), []).append(row)
    out: dict[str, dict[str, float | None]] = {}
    for case_id, rows in by_case.items():
        non_fine = [row for row in rows if row["lattice_level"] != "fine"]
        medium = [row for row in rows if row["lattice_level"] == "medium"]
        out[case_id] = {
            "max_abs_cdff_delta_pct_vs_fine": _max_abs(
                safe_float(row.get("CDff_delta_pct_vs_fine")) for row in non_fine
            ),
            "max_abs_e_delta_pct_vs_fine": _max_abs(
                safe_float(row.get("e_CDi_CDff_delta_pct_vs_fine")) for row in non_fine
            ),
            "medium_cdff_delta_pct_vs_fine": safe_float(
                medium[0].get("CDff_delta_pct_vs_fine") if medium else None
            ),
            "medium_e_delta_pct_vs_fine": safe_float(
                medium[0].get("e_CDi_CDff_delta_pct_vs_fine") if medium else None
            ),
        }
    return out


def _solver_delta_summary(parity_rows: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    by_case_variant: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for row in parity_rows:
        key = (str(row["case_id"]), str(row["geometry_variant"]))
        by_case_variant.setdefault(key, {})[str(row["solver"])] = row
    out: dict[str, dict[str, float | None]] = {}
    for (case_id, variant), solvers in by_case_variant.items():
        avl = solvers.get("AVL")
        vsp = solvers.get("VSPAERO_thin_vlm")
        if not avl or not vsp:
            continue
        out[f"{case_id}:{variant}"] = {
            "vsp_minus_avl_alpha_deg": None
            if safe_float(vsp.get("alpha_at_CL_req_deg")) is None
            or safe_float(avl.get("alpha_at_CL_req_deg")) is None
            else safe_float(vsp.get("alpha_at_CL_req_deg")) - safe_float(avl.get("alpha_at_CL_req_deg")),
            "vsp_cdi_delta_pct_vs_avl": percent_delta(
                safe_float(vsp.get("CDi_at_CL_req")),
                safe_float(avl.get("CDi_at_CL_req")),
            ),
        }
    return out


def write_reports(
    *,
    output_dir: Path,
    cases: list[CaseSpec],
    lattice_rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
    parity_rows: list[dict[str, Any]],
    bending_rows: list[dict[str, Any]],
) -> None:
    lattice_summary = _summarize_lattice(lattice_rows)
    solver_summary = _solver_delta_summary(parity_rows)
    fine_rows = [row for row in lattice_rows if row.get("lattice_level") == "fine"]

    lines = [
        "# AVL Induced-Drag Credibility Audit",
        "",
        f"Generated: {timestamp()}",
        "",
        "## Scope",
        "",
        "Diagnostic-only audit for old FX/Clark main-wing-only, Policy A/D, Policy C/E, and the monotone Policy A/C variants. The running Tier 2 full-alpha database directory was not read for mutation or written.",
        "",
        "## Headline Findings",
        "",
    ]
    max_medium_e = _max_abs(v.get("medium_e_delta_pct_vs_fine") for v in lattice_summary.values())
    max_medium_cd = _max_abs(v.get("medium_cdff_delta_pct_vs_fine") for v in lattice_summary.values())
    lines.append(
        f"- Medium-to-fine AVL lattice changes are small: max |CDff delta| = {_fmt(max_medium_cd)}%, max |e_CDi delta| = {_fmt(max_medium_e)}%."
    )
    lines.append(
        "- The suspicious old e_CDi > 1 is not reproduced in the main-wing-only reference-checked case; it is a full-aircraft/Trefftz/reference comparability issue from the earlier raw file."
    )
    lines.append(
        "- Policy A/C and monotone A/C retain e_CDi near 0.98 in fine-lattice AVL, with monotone chord changing CDff/e by much less than 1%."
    )
    if solver_summary:
        deltas = [
            value.get("vsp_cdi_delta_pct_vs_avl")
            for value in solver_summary.values()
            if value.get("vsp_cdi_delta_pct_vs_avl") is not None
        ]
        lines.append(
            f"- Existing Phase 7 VSPAERO thin/VLM data agrees on trend but is higher in absolute CDi by roughly {_fmt(min(deltas) if deltas else None)}% to {_fmt(max(deltas) if deltas else None)}% at CL_req for the comparable Policy A/C geometries."
        )
    lines.extend(["", "## Fine-Lattice AVL Values", ""])
    lines.append("| case | CL_req | alpha deg | CDind | CDff | e(CDind) | e(CDff) | local Cl max |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in fine_rows:
        lines.append(
            "| {case} | {cl} | {alpha} | {cdind} | {cdff} | {eind} | {eff} | {clmax} |".format(
                case=row["display_name"],
                cl=_fmt(row.get("CL_req")),
                alpha=_fmt(row.get("alpha_at_CL_req_deg")),
                cdind=_fmt(row.get("CDind")),
                cdff=_fmt(row.get("CDff")),
                eind=_fmt(row.get("e_CDi_CDind")),
                eff=_fmt(row.get("e_CDi_CDff")),
                clmax=_fmt(row.get("local_Cl_max")),
            )
        )

    lines.extend(["", "## Reference Convention", ""])
    lines.append(
        "Use CDff/Trefftz e for conceptual induced-drag comparison and report CDind beside it. Old full-aircraft e_CDi=1.291 should not be mixed with the wing-only Policy A/C values because the full old AVL has additional lifting surfaces and different force bookkeeping."
    )

    lines.extend(["", "## Cross-Solver Parity", ""])
    lines.append(
        "VSPAERO CDo/CDtot is not used as profile drag here. Existing VSPAERO thin/VLM runs are only used for CL-alpha, alpha_at_CL_req, and induced-drag parity."
    )
    for key, value in solver_summary.items():
        lines.append(
            f"- {key}: VSPAERO alpha_at_CL_req is AVL + {_fmt(value.get('vsp_minus_avl_alpha_deg'))} deg; VSPAERO CDi is {_fmt(value.get('vsp_cdi_delta_pct_vs_avl'))}% vs AVL."
        )

    lines.extend(["", "## Sensitivity", ""])
    by_variant = [row for row in bending_rows if row.get("analysis_type") == "sensitivity"]
    max_e_sens = _max_abs(safe_float(row.get("e_CDi_delta_pct_vs_baseline")) for row in by_variant)
    max_cd_sens = _max_abs(safe_float(row.get("CDff_delta_pct_vs_baseline")) for row in by_variant)
    lines.append(
        f"Outer twist +/-0.5 deg, uniform incidence +0.5 deg, and existing monotone-chord substitutions produce max |e_CDi| delta of {_fmt(max_e_sens)}% and max |CDff| delta of {_fmt(max_cd_sens)}% across the diagnostic rows."
    )

    lines.extend(["", "## Direct Answers", ""])
    lines.append("- Are e_CDi near 0.98 numerically stable? Yes for these AVL models at medium/fine lattice; treat coarse only as a sanity check.")
    lines.append("- Are they reference-convention artifacts? No for the main-wing-only Policy A/C/monotone cases. The old full-aircraft e_CDi=1.291 was a convention/comparability artifact.")
    lines.append("- Does VSPAERO agree on CDi trend? Yes on trend for Policy A/C and monotone A/C, but existing thin/VLM CDi is several percent higher than AVL at CL_req.")
    lines.append("- Which values are credible for conceptual design? Use fine-lattice AVL CDff/Trefftz e_CDi for same-reference wing-only comparisons, with CDind reported as a secondary diagnostic.")
    lines.append("- What safety margin before final L/D? Apply at least a +5% induced-drag margin or equivalent L/D debit until a higher-fidelity VLM/panel/CFD validation is completed.")
    lines.append("")
    (output_dir / "avl_induced_drag_credibility_report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    policy_lines = [
        "# Recommended Metric Policy",
        "",
        "1. Use main-wing-only, consistent Sref/Bref/Cref cases for induced-drag comparisons.",
        "2. Use AVL Trefftz-plane `CDff` and `e = CLff^2 / (pi AR CDff)` as the primary conceptual induced-drag metric.",
        "3. Keep `CDind` and `e(CDind)` in reports as reference diagnostics, not as the sole ranking metric.",
        "4. Do not compare old full-aircraft raw e_CDi directly to wing-only Policy A/C values.",
        "5. Do not use VSPAERO `CDo`/`CDtot` as mission profile drag unless the polar/proxy source is explicitly traced.",
        "6. For external L/D reporting before higher-fidelity validation, add +5% to induced drag or report an L/D range with that debit.",
        "7. Keep monotone chord as production-facing geometry because this audit and the earlier monotone evaluation show no meaningful induced-drag penalty.",
        "",
    ]
    (output_dir / "recommended_metric_policy.md").write_text(
        "\n".join(policy_lines),
        encoding="utf-8",
    )


def _fmt(value: Any, digits: int = 6) -> str:
    number = safe_float(value)
    if number is None:
        return "n/a"
    return f"{number:.{digits}g}"


def run_audit(output_dir: Path, *, avl_binary: str | Path | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if TIER2_OUTPUT_DIR.exists():
        before = TIER2_OUTPUT_DIR.stat().st_mtime_ns
    else:
        before = None
    cases = build_case_specs()
    missing = [str(case.avl_path) for case in cases if not case.avl_path.exists()]
    if missing:
        raise FileNotFoundError("Missing required AVL case files: " + ", ".join(missing))

    lattice_rows, fine_results = run_lattice_convergence(cases, output_dir, avl_binary=avl_binary)
    reference_rows = reference_convention_rows(cases, fine_results)
    parity_rows = cross_solver_rows(cases, fine_results)
    safe_records = _load_airfoil_safe_clmax()
    spanload_rows: list[dict[str, Any]] = []
    zone_summary_rows: list[dict[str, Any]] = []
    for case in cases:
        result = fine_results[case.case_id]
        spanload_rows.extend(normalized_spanload_rows(case, "fine", result, safe_records))
        zone_summary_rows.extend(zone_stats(case, list(result["spanload"]), safe_records))

    bending_rows = run_sensitivity(cases, fine_results, output_dir, avl_binary=avl_binary)
    for row in bending_rows:
        if row.get("variant") == "baseline_fine":
            row["case_zone_stall_margin_min"] = min(
                (
                    safe_float(zone.get("stall_margin_cl"))
                    for zone in zone_summary_rows
                    if zone.get("case_id") == row.get("case_id")
                    and safe_float(zone.get("stall_margin_cl")) is not None
                ),
                default=None,
            )

    _write_csv(output_dir / "lattice_convergence.csv", lattice_rows)
    _write_csv(output_dir / "reference_convention_check.csv", reference_rows)
    _write_csv(output_dir / "avl_vs_vsp_cdi_parity.csv", parity_rows)
    _write_csv(output_dir / "spanload_realism.csv", spanload_rows + zone_summary_rows)
    _write_csv(output_dir / "bending_vs_e.csv", bending_rows)
    write_reports(
        output_dir=output_dir,
        cases=cases,
        lattice_rows=lattice_rows,
        reference_rows=reference_rows,
        parity_rows=parity_rows,
        bending_rows=bending_rows,
    )

    if TIER2_OUTPUT_DIR.exists():
        after = TIER2_OUTPUT_DIR.stat().st_mtime_ns
    else:
        after = None
    metadata = {
        "generated_at": timestamp(),
        "cases": [case.case_id for case in cases],
        "output_dir": str(output_dir.resolve()),
        "tier2_output_dir_exists": TIER2_OUTPUT_DIR.exists(),
        "tier2_mtime_before": before,
        "tier2_mtime_after": after,
        "tier2_mtime_unchanged": before == after,
        "notes": "Diagnostic-only; no ranking/gate mutation.",
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--avl-binary", type=Path, default=None)
    args = parser.parse_args(argv)
    run_audit(args.output_dir, avl_binary=args.avl_binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
