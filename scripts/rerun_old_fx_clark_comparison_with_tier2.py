#!/usr/bin/env python3
"""Old FX/Clark baseline comparison against Phase 7 sidecar baselines.

The default run is intentionally pre-Tier2 and diagnostic-only.  Once the
Tier 2 full-alpha database is complete, run this script with
``--profile-db tier2`` to refresh only the profile-drag lookup and comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from hpa_mdo.aero.avl_spanwise import build_spanwise_load_from_avl_strip_forces
from hpa_mdo.concept.avl_loader import _run_avl_spanwise_case, _run_avl_trim_case


DEFAULT_OUTPUT_DIR = (
    _REPO_ROOT
    / "output"
    / "baseline_comparisons"
    / "old_fx_clark_vs_phase7_pre_tier2"
)
DEFAULT_MISSION_REPORT = (
    _REPO_ROOT
    / "output"
    / "airfoil_db"
    / "full_polar_archive"
    / "phase6_full_polar_sidecar"
    / "spanload_design_smoke_report.json"
)
DEFAULT_PRE_TIER2_POLAR_CSV = (
    _REPO_ROOT / "output" / "airfoil_db" / "full_polar_archive" / "polar_points.csv"
)
DEFAULT_PRE_TIER2_RECORDS = (
    _REPO_ROOT
    / "output"
    / "airfoil_db"
    / "full_polar_archive"
    / "full_polar_build_report.json"
)
DEFAULT_TIER2_ROOT = _REPO_ROOT / "output" / "airfoil_db" / "full_alpha_reusable_v1_tier2"
DEFAULT_PHASE7_SUMMARY = _REPO_ROOT / "phase7_dual_baseline" / "dual_baseline_summary.csv"
DEFAULT_OLD_AVL = _REPO_ROOT / "data" / "blackcat_004_full.avl"
DEFAULT_OLD_VSP = _REPO_ROOT / "data" / "blackcat_004_origin.vsp3"
DEFAULT_DYNAMIC_VISCOSITY_PA_S = 1.789e-5
TARGET_AIRFOILS = {"fx76mp140", "clarkysm"}
REFERENCE_AIRFOIL_PATHS = {
    "fx76mp140": _REPO_ROOT / "data" / "airfoils" / "fx76mp140.dat",
    "clarkysm": _REPO_ROOT / "data" / "airfoils" / "clarkysm.dat",
}


def _repo_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return _REPO_ROOT / path


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def _percentile(values: list[float], pct: float) -> float | None:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    idx = (len(clean) - 1) * pct / 100.0
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return clean[lo]
    return clean[lo] + (clean[hi] - clean[lo]) * (idx - lo)


def _trapz(y_values: list[float], x_values: list[float]) -> float:
    if len(y_values) != len(x_values) or len(y_values) < 2:
        return 0.0
    total = 0.0
    for index in range(1, len(y_values)):
        dx = float(x_values[index]) - float(x_values[index - 1])
        total += 0.5 * dx * (float(y_values[index]) + float(y_values[index - 1]))
    return total


def compute_required_cl(
    *,
    weight_n: float,
    density_kgpm3: float,
    velocity_mps: float,
    sref_m2: float,
) -> float:
    q = 0.5 * float(density_kgpm3) * float(velocity_mps) ** 2
    return float(weight_n) / (q * float(sref_m2))


def compute_cd0_total_est(
    *,
    profile_cd: float,
    cda_nonwing_m2: float,
    sref_m2: float,
) -> float:
    return float(profile_cd) + float(cda_nonwing_m2) / float(sref_m2)


def resolve_avl_reuse_path(
    *,
    profile_db: str,
    reuse_avl_results: str | Path | None,
) -> Path | None:
    if reuse_avl_results:
        return _repo_path(reuse_avl_results)
    if profile_db == "tier2":
        return DEFAULT_OUTPUT_DIR / "old_design_avl_results.json"
    return None


def _load_airfoil_points(path: Path) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if not path.exists():
        return points
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        tokens = raw.strip().split()
        if len(tokens) < 2:
            continue
        try:
            points.append((float(tokens[0]), float(tokens[1])))
        except ValueError:
            continue
    return points


def _infer_airfoil_id(points: list[tuple[float, float]]) -> str:
    if not points:
        return "unknown"
    best_id = "unknown"
    best_rms = float("inf")
    for airfoil_id, path in REFERENCE_AIRFOIL_PATHS.items():
        ref_points = _load_airfoil_points(path)
        if len(ref_points) != len(points):
            continue
        error_sum = 0.0
        for (x_a, y_a), (x_b, y_b) in zip(points, ref_points):
            error_sum += (x_a - x_b) ** 2 + (y_a - y_b) ** 2
        rms = math.sqrt(error_sum / max(len(points), 1))
        if rms < best_rms:
            best_rms = rms
            best_id = airfoil_id
    return best_id if best_rms <= 1.0e-5 else "unknown"


def _normalize_surface_name(name: str) -> str:
    normalized = "".join(str(name).split()).casefold()
    if normalized == "mainwing":
        return "wing"
    return normalized


def _parse_reference_values(lines: list[str]) -> dict[str, float]:
    for index, raw in enumerate(lines):
        if "Sref" in raw and "Cref" in raw and "Bref" in raw:
            if index + 1 >= len(lines):
                break
            tokens = lines[index + 1].split()
            if len(tokens) >= 3:
                return {
                    "sref_m2": float(tokens[0]),
                    "cref_m": float(tokens[1]),
                    "bref_m": float(tokens[2]),
                }
    raise ValueError("Could not parse AVL Sref/Cref/Bref reference values.")


def _parse_airfoil_after_section(lines: list[str], start_index: int) -> tuple[str, int]:
    index = start_index
    while index < len(lines):
        token = lines[index].strip().split()[0].casefold() if lines[index].strip() else ""
        if token in {"airfoil", "afile", "naca"}:
            break
        if token in {"section", "surface"}:
            return "unknown", index
        index += 1

    if index >= len(lines):
        return "unknown", index
    tokens = lines[index].strip().split()
    keyword = tokens[0].casefold()
    if keyword == "afile" and len(tokens) >= 2:
        return Path(tokens[1]).stem.casefold(), index + 1
    if keyword == "naca":
        return "naca_" + ("".join(tokens[1:]) if len(tokens) > 1 else "unknown"), index + 1
    if keyword != "airfoil":
        return "unknown", index + 1

    points: list[tuple[float, float]] = []
    index += 1
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("#"):
            break
        head = stripped.split()[0].casefold()
        if head in {"section", "surface", "control", "angle", "component", "translate"}:
            break
        tokens = stripped.split()
        if len(tokens) < 2:
            break
        try:
            points.append((float(tokens[0]), float(tokens[1])))
        except ValueError:
            break
        index += 1
    return _infer_airfoil_id(points), index


def parse_wing_geometry_from_avl(avl_path: str | Path) -> SimpleNamespace:
    path = _repo_path(avl_path)
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    refs = _parse_reference_values(lines)
    sections: list[SimpleNamespace] = []

    index = 0
    in_target_surface = False
    target_seen = False
    while index < len(lines):
        stripped = lines[index].strip()
        keyword = stripped.split()[0].casefold() if stripped else ""
        if keyword == "surface":
            surface_name = lines[index + 1].strip() if index + 1 < len(lines) else ""
            normalized = _normalize_surface_name(surface_name)
            if target_seen and in_target_surface:
                break
            in_target_surface = normalized == "wing"
            target_seen = target_seen or in_target_surface
            index += 2
            continue
        if not in_target_surface or keyword != "section":
            index += 1
            continue

        if index + 1 >= len(lines):
            break
        values = lines[index + 1].split()
        if len(values) < 5:
            raise ValueError(f"Malformed AVL SECTION line near line {index + 2}: {lines[index + 1]}")
        x_le, y_le, z_le, chord, twist = [float(value) for value in values[:5]]
        airfoil_id, next_index = _parse_airfoil_after_section(lines, index + 2)
        sections.append(
            SimpleNamespace(
                section_index=len(sections),
                x_le_m=x_le,
                y_m=y_le,
                z_m=z_le,
                chord_m=chord,
                twist_deg=twist,
                airfoil_id=airfoil_id,
            )
        )
        index = max(next_index, index + 2)

    if not sections:
        raise ValueError(f"No main wing sections found in {path}")
    half_span = max(section.y_m for section in sections)
    previous_section: SimpleNamespace | None = None
    for section in sections:
        section.eta = 0.0 if half_span <= 0.0 else float(section.y_m) / float(half_span)
        if previous_section is None or section.y_m == previous_section.y_m:
            section.local_z_slope = None
            section.local_dihedral_deg = None
        else:
            slope = (section.z_m - previous_section.z_m) / (section.y_m - previous_section.y_m)
            section.local_z_slope = slope
            section.local_dihedral_deg = math.degrees(math.atan(slope))
        previous_section = section

    return SimpleNamespace(
        avl_path=str(path.resolve()),
        sref_m2=refs["sref_m2"],
        cref_m=refs["cref_m"],
        bref_m=refs["bref_m"],
        span_m=refs["bref_m"],
        half_span_m=half_span,
        aspect_ratio=refs["bref_m"] ** 2 / refs["sref_m2"],
        root_chord_m=sections[0].chord_m,
        tip_chord_m=sections[-1].chord_m,
        loaded_tip_z_m=sections[-1].z_m,
        sections=sections,
    )


def _airfoil_for_eta(eta: float) -> str:
    return "fx76mp140" if float(eta) < 0.55 else "clarkysm"


def _zone_for_eta(eta: float) -> str:
    if eta < 0.25:
        return "root"
    if eta < 0.55:
        return "mid1"
    if eta < 0.80:
        return "mid2"
    return "tip"


def _load_mission_contract(path: str | Path) -> dict[str, float]:
    report_path = _repo_path(path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates") or []
    mission = dict((candidates[0] if candidates else {}).get("mission_contract") or {})
    if not mission:
        mission = dict(payload.get("mission_contract") or {})
    if not mission:
        raise ValueError(f"No mission contract found in {report_path}")
    mission.setdefault("weight_n", mission.get("mass_kg", 98.5) * 9.80665)
    mission.setdefault("speed_mps", mission.get("speed", 6.6))
    mission.setdefault("rho", mission.get("density_kgpm3", 1.135669))
    mission.setdefault("CDA_nonwing_target_m2", 0.13)
    mission.setdefault("CD0_total_target", 0.017)
    mission.setdefault("CD0_total_boundary", 0.018)
    mission.setdefault("CD0_total_rescue", 0.020)
    mission.setdefault("dynamic_viscosity_pa_s", DEFAULT_DYNAMIC_VISCOSITY_PA_S)
    mission.setdefault("eta_prop", 0.86)
    mission.setdefault("eta_trans", 0.96)
    return {
        "weight_n": float(mission["weight_n"]),
        "mass_kg": float(mission.get("mass_kg", float(mission["weight_n"]) / 9.80665)),
        "speed_mps": float(mission["speed_mps"]),
        "rho": float(mission["rho"]),
        "CDA_nonwing_target_m2": float(mission["CDA_nonwing_target_m2"]),
        "CD0_total_target": float(mission["CD0_total_target"]),
        "CD0_total_boundary": float(mission["CD0_total_boundary"]),
        "CD0_total_rescue": float(mission["CD0_total_rescue"]),
        "dynamic_viscosity_pa_s": float(mission["dynamic_viscosity_pa_s"]),
        "eta_prop": float(mission["eta_prop"]),
        "eta_trans": float(mission["eta_trans"]),
    }


def _load_pre_tier2_records(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records: dict[str, dict[str, Any]] = {}
    raw_records = payload.get("records", [])
    if isinstance(raw_records, dict):
        iterable = []
        for airfoil_id, record in raw_records.items():
            if isinstance(record, dict):
                item = dict(record)
                item.setdefault("airfoil_id", airfoil_id)
                iterable.append(item)
    else:
        iterable = [record for record in raw_records if isinstance(record, dict)]
    for record in iterable:
        airfoil_id = str(record.get("airfoil_id", "")).casefold()
        if airfoil_id in TARGET_AIRFOILS:
            records[airfoil_id] = {
                "source_quality": record.get("source_quality", ""),
                "safe_clmax": _safe_float(record.get("safe_clmax")),
                "usable_clmax": _safe_float(record.get("usable_clmax")),
                "quality_warnings": (
                    record.get("quality_warnings")
                    or record.get("warnings")
                    or record.get("issues")
                    or []
                ),
            }
    return records


def _load_tier2_records(root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    json_path = root / "airfoil_records.json"
    csv_path = root / "airfoil_records.csv"
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        items = payload.values() if isinstance(payload, dict) else payload
        for item in items:
            if not isinstance(item, dict):
                continue
            airfoil_id = str(item.get("airfoil_id", "")).casefold()
            if airfoil_id in TARGET_AIRFOILS:
                records[airfoil_id] = {
                    "source_quality": item.get("source_quality")
                    or item.get("archive_source_quality")
                    or item.get("quality")
                    or "",
                    "safe_clmax": _safe_float(item.get("safe_clmax")),
                    "usable_clmax": _safe_float(item.get("usable_clmax")),
                    "quality_warnings": item.get("quality_warnings") or item.get("warning_flags") or [],
                }
        return records
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                airfoil_id = str(row.get("airfoil_id", "")).casefold()
                if airfoil_id in TARGET_AIRFOILS:
                    records[airfoil_id] = {
                        "source_quality": row.get("source_quality")
                        or row.get("archive_source_quality")
                        or row.get("quality")
                        or "",
                        "safe_clmax": _safe_float(row.get("safe_clmax")),
                        "usable_clmax": _safe_float(row.get("usable_clmax")),
                        "quality_warnings": row.get("quality_warnings", ""),
                    }
    return records


def _row_value(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and row[name] != "":
            return row[name]
    return ""


def _load_polar_points(
    csv_path: Path,
    *,
    roughness_mode: str,
    target_airfoils: set[str] = TARGET_AIRFOILS,
) -> dict[str, dict[float, list[dict[str, float]]]]:
    points: dict[str, dict[float, list[dict[str, float]]]] = {
        airfoil_id: defaultdict(list) for airfoil_id in target_airfoils
    }
    with csv_path.open(newline="", encoding="utf-8", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            airfoil_id = str(row.get("airfoil_id", "")).casefold()
            if airfoil_id not in target_airfoils:
                continue
            roughness = (
                row.get("roughness_mode")
                or row.get("roughness")
                or row.get("surface_condition")
                or "clean"
            )
            if str(roughness).casefold() != roughness_mode.casefold():
                continue
            cl = _safe_float(_row_value(row, "Cl", "cl", "CL"))
            cd = _safe_float(_row_value(row, "Cd", "cd", "CD"))
            re_value = _safe_float(_row_value(row, "Re", "re", "reynolds"))
            alpha = _safe_float(_row_value(row, "alpha_deg", "alpha", "Alpha"))
            cm = _safe_float(_row_value(row, "Cm", "cm", "CM"), 0.0)
            if cl is None or cd is None or re_value is None or alpha is None:
                continue
            if cd <= 0.0:
                continue
            converged_raw = str(row.get("converged", "true")).strip().casefold()
            converged = converged_raw not in {"false", "0", "no"}
            points[airfoil_id][float(re_value)].append(
                {
                    "cl": float(cl),
                    "cd": float(cd),
                    "cm": float(cm if cm is not None else 0.0),
                    "alpha_deg": float(alpha),
                    "converged": 1.0 if converged else 0.0,
                }
            )
    for re_map in points.values():
        for re_value, rows in re_map.items():
            rows.sort(key=lambda item: item["cl"])
    return points


def load_profile_database(
    *,
    profile_db: str,
    pre_tier2_polar_csv: str | Path,
    pre_tier2_records: str | Path,
    tier2_root: str | Path,
    roughness_mode: str,
) -> SimpleNamespace:
    if profile_db == "pre_tier2":
        polar_csv = _repo_path(pre_tier2_polar_csv)
        record_path = _repo_path(pre_tier2_records)
        if not polar_csv.exists() or not record_path.exists():
            raise FileNotFoundError("Pre-Tier2 full-polar archive files are missing.")
        return SimpleNamespace(
            profile_db="pre_tier2",
            label="provisional_pre_tier2",
            polar_points=_load_polar_points(polar_csv, roughness_mode=roughness_mode),
            records=_load_pre_tier2_records(record_path),
            source_path=str(polar_csv.resolve()),
            record_path=str(record_path.resolve()),
            roughness_mode=roughness_mode,
        )

    tier2_dir = _repo_path(tier2_root)
    polar_csv = tier2_dir / "polar_points.csv"
    if not polar_csv.exists():
        raise FileNotFoundError(
            f"Tier2 polar_points.csv is not available yet: {polar_csv}. "
            "Leave the running Tier2 job alone and rerun this hook after completion."
        )
    return SimpleNamespace(
        profile_db="tier2",
        label="tier2_full_alpha_refresh",
        polar_points=_load_polar_points(polar_csv, roughness_mode=roughness_mode),
        records=_load_tier2_records(tier2_dir),
        source_path=str(polar_csv.resolve()),
        record_path=str((tier2_dir / "airfoil_records.csv").resolve()),
        roughness_mode=roughness_mode,
    )


def _interp_pair(x0: float, y0: float, x1: float, y1: float, x: float) -> float:
    if abs(x1 - x0) <= 1.0e-12:
        return y0
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def _lookup_at_re(rows: list[dict[str, float]], cl: float) -> tuple[dict[str, float], list[str]]:
    warnings: list[str] = []
    if not rows:
        raise ValueError("No polar rows available for interpolation.")
    if cl <= rows[0]["cl"]:
        warnings.append("cl_below_polar_range")
        return dict(rows[0]), warnings
    if cl >= rows[-1]["cl"]:
        warnings.append("cl_above_polar_range")
        return dict(rows[-1]), warnings
    for index in range(1, len(rows)):
        low = rows[index - 1]
        high = rows[index]
        if low["cl"] <= cl <= high["cl"]:
            return (
                {
                    "cl": cl,
                    "cd": _interp_pair(low["cl"], low["cd"], high["cl"], high["cd"], cl),
                    "cm": _interp_pair(low["cl"], low["cm"], high["cl"], high["cm"], cl),
                    "alpha_deg": _interp_pair(
                        low["cl"], low["alpha_deg"], high["cl"], high["alpha_deg"], cl
                    ),
                    "converged": min(low["converged"], high["converged"]),
                },
                warnings,
            )
    warnings.append("cl_lookup_fell_through")
    return dict(rows[-1]), warnings


def interpolate_polar(
    polar_points: dict[str, dict[float, list[dict[str, float]]]],
    *,
    airfoil_id: str,
    re_value: float,
    cl: float,
) -> tuple[dict[str, float], list[str]]:
    airfoil_id = str(airfoil_id).casefold()
    re_map = polar_points.get(airfoil_id) or {}
    if not re_map:
        raise ValueError(f"No polar data for airfoil {airfoil_id}")
    re_values = sorted(re_map)
    warnings: list[str] = []
    if re_value <= re_values[0]:
        warnings.append("re_below_polar_range")
        point, cl_warnings = _lookup_at_re(re_map[re_values[0]], cl)
        warnings.extend(cl_warnings)
        point["Re_query"] = float(re_value)
        point["Re_used_low"] = float(re_values[0])
        point["Re_used_high"] = float(re_values[0])
        return point, warnings
    if re_value >= re_values[-1]:
        warnings.append("re_above_polar_range")
        point, cl_warnings = _lookup_at_re(re_map[re_values[-1]], cl)
        warnings.extend(cl_warnings)
        point["Re_query"] = float(re_value)
        point["Re_used_low"] = float(re_values[-1])
        point["Re_used_high"] = float(re_values[-1])
        return point, warnings

    for index in range(1, len(re_values)):
        re_low = re_values[index - 1]
        re_high = re_values[index]
        if re_low <= re_value <= re_high:
            low_point, low_warnings = _lookup_at_re(re_map[re_low], cl)
            high_point, high_warnings = _lookup_at_re(re_map[re_high], cl)
            warnings.extend(low_warnings)
            warnings.extend(high_warnings)
            return (
                {
                    "cl": cl,
                    "cd": _interp_pair(re_low, low_point["cd"], re_high, high_point["cd"], re_value),
                    "cm": _interp_pair(re_low, low_point["cm"], re_high, high_point["cm"], re_value),
                    "alpha_deg": _interp_pair(
                        re_low, low_point["alpha_deg"], re_high, high_point["alpha_deg"], re_value
                    ),
                    "converged": min(low_point["converged"], high_point["converged"]),
                    "Re_query": float(re_value),
                    "Re_used_low": float(re_low),
                    "Re_used_high": float(re_high),
                },
                warnings,
            )
    raise ValueError(f"Could not bracket Re={re_value} for airfoil {airfoil_id}")


def _load_policy_rows(path: str | Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with _repo_path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            label = str(
                row.get("baseline_label")
                or row.get("baseline_role")
                or row.get("policy_name")
                or row.get("policy")
                or row.get("name")
                or ""
            )
            policy_id = str(row.get("policy_id") or row.get("policy") or "").strip().upper()
            if "performance" in label.casefold() or policy_id in {"A", "D"}:
                rows["Policy A / D"] = row
            if "conservative" in label.casefold() or policy_id in {"C", "E"}:
                rows["Policy C / E"] = row
    if "Policy A / D" not in rows or "Policy C / E" not in rows:
        raise ValueError(f"Could not find Policy A/D and Policy C/E rows in {path}")
    return rows


def _load_phase7_geometry(case_name: str) -> dict[str, float]:
    manifest_path = (
        _REPO_ROOT / "output" / "geometry_exports" / "phase7_sidecar_vsp" / case_name / "geometry_manifest.json"
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    computed_span = payload.get("computed_span", payload.get("computed_span_m", payload["Bref"]))
    return {
        "sref_m2": float(payload["Sref"]),
        "bref_m": float(payload["Bref"]),
        "cref_m": float(payload["Cref"]),
        "span_m": float(computed_span),
        "area_m2": float(payload["computed_wing_area_m2"]),
        "loaded_tip_z_m": float(payload["loaded_tip_z_m"]),
        "aspect_ratio": float(payload["Bref"]) ** 2 / float(payload["Sref"]),
    }


def _mission_drag_budget_band(cd0_total: float, mission: dict[str, float]) -> str:
    if cd0_total <= mission["CD0_total_target"]:
        return "target"
    if cd0_total <= mission["CD0_total_boundary"]:
        return "boundary"
    if cd0_total <= mission["CD0_total_rescue"]:
        return "rescue"
    return "above_rescue"


def _run_old_avl(
    *,
    avl_path: Path,
    output_dir: Path,
    geometry: SimpleNamespace,
    mission: dict[str, float],
    avl_binary: str | Path | None,
) -> dict[str, Any]:
    cl_required = compute_required_cl(
        weight_n=mission["weight_n"],
        density_kgpm3=mission["rho"],
        velocity_mps=mission["speed_mps"],
        sref_m2=geometry.sref_m2,
    )
    case_dir = output_dir / "avl_run"
    trim = _run_avl_trim_case(
        avl_path=avl_path,
        case_dir=case_dir,
        cl_required=cl_required,
        velocity_mps=mission["speed_mps"],
        density_kgpm3=mission["rho"],
        avl_binary=avl_binary,
    )
    alpha_at_cl = float(trim["aoa_trim_deg"])
    fs_path = _run_avl_spanwise_case(
        avl_path=avl_path,
        case_dir=case_dir,
        alpha_deg=alpha_at_cl,
        velocity_mps=mission["speed_mps"],
        density_kgpm3=mission["rho"],
        avl_binary=avl_binary,
    )
    load = build_spanwise_load_from_avl_strip_forces(
        fs_path=fs_path,
        avl_path=avl_path,
        aoa_deg=alpha_at_cl,
        velocity_mps=mission["speed_mps"],
        density_kgpm3=mission["rho"],
        target_surface_names=("Wing", "Main Wing"),
        positive_y_only=True,
    )
    cl_values = [float(value) for value in load.cl]
    y_values = [float(value) for value in load.y]
    chord_values = [float(value) for value in load.chord]
    max_index = max(range(len(cl_values)), key=lambda idx: cl_values[idx])
    spanwise_rows: list[dict[str, Any]] = []
    for idx, (y_m, chord_m, cl, cd, cm, lps, dps) in enumerate(
        zip(
            y_values,
            chord_values,
            load.cl,
            load.cd,
            load.cm,
            load.lift_per_span,
            load.drag_per_span,
        )
    ):
        eta = 0.0 if geometry.half_span_m <= 0.0 else y_m / geometry.half_span_m
        spanwise_rows.append(
            {
                "station_index": idx,
                "eta": float(eta),
                "y_m": y_m,
                "chord_m": chord_m,
                "zone_name": _zone_for_eta(float(eta)),
                "profile_airfoil_id": _airfoil_for_eta(float(eta)),
                "avl_cl": float(cl),
                "avl_cd_strip": float(cd),
                "avl_cm_c4": float(cm),
                "lift_per_span_npm": float(lps),
                "drag_per_span_npm": float(dps),
            }
        )
    e_cdi = _safe_float(trim.get("span_efficiency"))
    if e_cdi is None:
        cd_induced = _safe_float(trim.get("cd_induced"), 0.0)
        e_cdi = cl_required**2 / (math.pi * geometry.aspect_ratio * cd_induced)

    return {
        "source_avl_path": str(avl_path.resolve()),
        "cl_required": cl_required,
        "alpha_at_cl_req_deg": alpha_at_cl,
        "cl_trim": float(trim["cl_trim"]),
        "cd_induced": float(trim["cd_induced"]),
        "e_CDi": float(e_cdi),
        "geometry": {
            "Sref": geometry.sref_m2,
            "Bref": geometry.bref_m,
            "Cref": geometry.cref_m,
            "AR": geometry.aspect_ratio,
            "root_chord_m": geometry.root_chord_m,
            "tip_chord_m": geometry.tip_chord_m,
            "loaded_tip_z_m": geometry.loaded_tip_z_m,
        },
        "mission": mission,
        "local_cl_distribution": {
            "Cl_min": _percentile(cl_values, 0.0),
            "Cl_p50": _percentile(cl_values, 50.0),
            "Cl_p90": _percentile(cl_values, 90.0),
            "Cl_max": _percentile(cl_values, 100.0),
            "eta_at_Cl_max": float(spanwise_rows[max_index]["eta"]),
            "y_at_Cl_max_m": y_values[max_index],
        },
        "max_station_cl": max(cl_values),
        "spanwise_rows": spanwise_rows,
        "avl_artifacts": {
            "case_dir": str(case_dir.resolve()),
            "trim_force_path": str((case_dir / "concept_trim.ft").resolve()),
            "trim_stdout_log_path": str((case_dir / "concept_trim_stdout.log").resolve()),
            "spanwise_fs_path": str(fs_path.resolve()),
            "spanwise_stdout_log_path": str((case_dir / "concept_spanwise_stdout.log").resolve()),
        },
    }


def _write_section_table(geometry: SimpleNamespace, output_dir: Path) -> None:
    path = output_dir / "old_design_section_table.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = [
            "section_index",
            "eta",
            "y_m",
            "z_m",
            "chord_m",
            "twist_deg",
            "local_z_slope",
            "local_dihedral_deg",
            "airfoil_id",
            "airfoil_dat_path",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for section in geometry.sections:
            dat_path = REFERENCE_AIRFOIL_PATHS.get(section.airfoil_id)
            writer.writerow(
                {
                    "section_index": section.section_index,
                    "eta": f"{section.eta:.9f}",
                    "y_m": f"{section.y_m:.9f}",
                    "z_m": f"{section.z_m:.9f}",
                    "chord_m": f"{section.chord_m:.9f}",
                    "twist_deg": f"{section.twist_deg:.9f}",
                    "local_z_slope": ""
                    if section.local_z_slope is None
                    else f"{section.local_z_slope:.9f}",
                    "local_dihedral_deg": ""
                    if section.local_dihedral_deg is None
                    else f"{section.local_dihedral_deg:.9f}",
                    "airfoil_id": section.airfoil_id,
                    "airfoil_dat_path": "" if dat_path is None else str(dat_path.resolve()),
                }
            )


def _compute_profile_drag(
    *,
    avl_result: dict[str, Any],
    geometry: SimpleNamespace,
    mission: dict[str, float],
    profile_db: SimpleNamespace,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    station_rows: list[dict[str, Any]] = []
    densities: list[float] = []
    y_values: list[float] = []
    min_margin: float | None = None
    max_utilization: float | None = None
    warning_counter: Counter[str] = Counter()
    for row in avl_result["spanwise_rows"]:
        y_m = float(row["y_m"])
        eta = float(row["eta"])
        chord_m = float(row["chord_m"])
        cl = float(row["avl_cl"])
        airfoil_id = str(row["profile_airfoil_id"]).casefold()
        re_value = mission["rho"] * mission["speed_mps"] * chord_m / mission["dynamic_viscosity_pa_s"]
        polar, warnings = interpolate_polar(
            profile_db.polar_points,
            airfoil_id=airfoil_id,
            re_value=re_value,
            cl=cl,
        )
        warning_counter.update(warnings)
        record = profile_db.records.get(airfoil_id, {})
        safe_clmax = record.get("safe_clmax")
        margin = None if safe_clmax is None else float(safe_clmax) - cl
        utilization = None if safe_clmax in {None, 0.0} else cl / float(safe_clmax)
        if margin is not None:
            min_margin = margin if min_margin is None else min(min_margin, margin)
        if utilization is not None:
            max_utilization = (
                utilization if max_utilization is None else max(max_utilization, utilization)
            )
        density = chord_m * float(polar["cd"])
        densities.append(density)
        y_values.append(y_m)
        station_rows.append(
            {
                "station_index": row["station_index"],
                "eta": eta,
                "y_m": y_m,
                "chord_m": chord_m,
                "zone_name": row["zone_name"],
                "airfoil_id": airfoil_id,
                "source_quality": record.get("source_quality", ""),
                "profile_db_label": profile_db.label,
                "roughness_mode": profile_db.roughness_mode,
                "Re_query": re_value,
                "Cl_query": cl,
                "Cd_interp": float(polar["cd"]),
                "Cm_interp": float(polar["cm"]),
                "alpha_interp_deg": float(polar["alpha_deg"]),
                "safe_clmax": "" if safe_clmax is None else float(safe_clmax),
                "stall_margin_cl": "" if margin is None else margin,
                "station_utilization": "" if utilization is None else utilization,
                "profile_integrand_chord_cd": density,
                "warnings": ";".join(sorted(set(warnings))),
            }
        )

    profile_cd = 2.0 / geometry.sref_m2 * _trapz(densities, y_values)
    cd0_total = compute_cd0_total_est(
        profile_cd=profile_cd,
        cda_nonwing_m2=mission["CDA_nonwing_target_m2"],
        sref_m2=geometry.sref_m2,
    )
    summary = {
        "profile_cd": profile_cd,
        "CD0_total_est": cd0_total,
        "mission_drag_budget_band": _mission_drag_budget_band(cd0_total, mission),
        "min_stall_margin": min_margin,
        "max_station_utilization": max_utilization,
        "profile_db_label": profile_db.label,
        "profile_db_source_path": profile_db.source_path,
        "profile_lookup_warning_counts": dict(warning_counter),
        "profile_assignment_note": (
            "Old AVL stores FX76MP140 on most inboard sections and ClarkY at the tip; "
            "profile drag uses the established FX inboard / Clark outer zone proxy "
            "(eta < 0.55 FX76MP140, eta >= 0.55 ClarkY) because no blended-airfoil "
            "full-polar records exist."
        ),
    }
    return summary, station_rows


def _write_profile_drag_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _phase7_comparison_row(
    *,
    name: str,
    policy_row: dict[str, str],
    geometry: dict[str, float],
    mission: dict[str, float],
) -> dict[str, Any]:
    cl_required = compute_required_cl(
        weight_n=mission["weight_n"],
        density_kgpm3=mission["rho"],
        velocity_mps=mission["speed_mps"],
        sref_m2=geometry["sref_m2"],
    )
    e_cdi = float(policy_row["e_CDi"])
    cdi = cl_required**2 / (math.pi * geometry["aspect_ratio"] * e_cdi)
    profile_cd = float(policy_row["profile_cd"])
    cd0_total = float(policy_row["CD0_total_est"])
    cd_total = cdi + cd0_total
    q = 0.5 * mission["rho"] * mission["speed_mps"] ** 2
    drag_n = q * geometry["sref_m2"] * cd_total
    p_air = drag_n * mission["speed_mps"]
    p_crank = p_air / (mission["eta_prop"] * mission["eta_trans"])
    return {
        "case": name,
        "assignment": policy_row.get("assignment", ""),
        "Sref": geometry["sref_m2"],
        "Bref": geometry["bref_m"],
        "Cref": geometry["cref_m"],
        "AR": geometry["aspect_ratio"],
        "CL_req": cl_required,
        "alpha_at_CL_req_deg": "",
        "CDi": cdi,
        "e_CDi": e_cdi,
        "profile_cd": profile_cd,
        "CD0_total_est": cd0_total,
        "CD_total": cd_total,
        "L_over_D": cl_required / cd_total,
        "drag_n": drag_n,
        "P_air_w": p_air,
        "P_crank_w": p_crank,
        "target_vs_avl_rms": policy_row.get("target_vs_avl_rms", ""),
        "target_vs_avl_outer_delta": policy_row.get("target_vs_avl_outer_delta", ""),
        "mission_drag_budget_band": policy_row.get("mission_drag_budget_band", ""),
        "min_stall_margin": policy_row.get("min_stall_margin", ""),
        "max_station_utilization": policy_row.get("max_station_utilization", ""),
        "archive_source_quality": policy_row.get("archive_source_quality", ""),
        "actual_sidecar_query_quality": policy_row.get("actual_sidecar_query_quality", ""),
        "source_quality": policy_row.get("actual_sidecar_query_quality", ""),
        "profile_source_label": "phase7_reported_profile_cd",
        "notes": "Phase 7 reported sidecar result; CDi recomputed from reported e_CDi.",
    }


def _old_comparison_row(
    *,
    avl_result: dict[str, Any],
    profile_summary: dict[str, Any],
    geometry: SimpleNamespace,
    mission: dict[str, float],
) -> dict[str, Any]:
    cd_total = avl_result["cd_induced"] + profile_summary["CD0_total_est"]
    q = 0.5 * mission["rho"] * mission["speed_mps"] ** 2
    drag_n = q * geometry.sref_m2 * cd_total
    p_air = drag_n * mission["speed_mps"]
    p_crank = p_air / (mission["eta_prop"] * mission["eta_trans"])
    return {
        "case": "Old FX/Clark VSP baseline",
        "assignment": "FX76MP140 inboard / ClarkY outer zone proxy",
        "Sref": geometry.sref_m2,
        "Bref": geometry.bref_m,
        "Cref": geometry.cref_m,
        "AR": geometry.aspect_ratio,
        "CL_req": avl_result["cl_required"],
        "alpha_at_CL_req_deg": avl_result["alpha_at_cl_req_deg"],
        "CDi": avl_result["cd_induced"],
        "e_CDi": avl_result["e_CDi"],
        "profile_cd": profile_summary["profile_cd"],
        "CD0_total_est": profile_summary["CD0_total_est"],
        "CD_total": cd_total,
        "L_over_D": avl_result["cl_required"] / cd_total,
        "drag_n": drag_n,
        "P_air_w": p_air,
        "P_crank_w": p_crank,
        "target_vs_avl_rms": "",
        "target_vs_avl_outer_delta": "",
        "mission_drag_budget_band": profile_summary["mission_drag_budget_band"],
        "min_stall_margin": profile_summary["min_stall_margin"],
        "max_station_utilization": profile_summary["max_station_utilization"],
        "archive_source_quality": "mixed_reference_archive_quality",
        "actual_sidecar_query_quality": "",
        "source_quality": profile_summary["profile_db_label"],
        "profile_source_label": profile_summary["profile_db_label"],
        "notes": (
            "AVL CDi/e_CDi uses current mission trim. Profile drag is provisional "
            "when profile_source_label=provisional_pre_tier2."
        ),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _fmt(value: Any, digits: int = 6) -> str:
    if value in {None, ""}:
        return ""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _write_comparison_markdown(path: Path, rows: list[dict[str, Any]], profile_db_label: str) -> None:
    by_case = {row["case"]: row for row in rows}
    old = by_case["Old FX/Clark VSP baseline"]
    policy_a = by_case["Policy A / D performance candidate"]
    policy_c = by_case["Policy C / E conservative baseline"]
    lines = [
        "# Old FX/Clark vs Phase 7 Policy A/C",
        "",
        f"Generated: {_timestamp()}",
        "",
        "This comparison is diagnostic only. It does not change aircraft ranking or hard gates.",
        "",
    ]
    if profile_db_label == "provisional_pre_tier2":
        lines.extend(
            [
                "## Status",
                "",
                "Profile drag is provisional because it uses the current pre-Tier2 full-polar archive. "
                "The AVL CDi/e_CDi trim result is already meaningful for the old geometry at the "
                "current mission condition.",
                "",
            ]
        )
    lines.extend(
        [
            "## Headline Table",
            "",
            "| Case | Sref | CL_req | alpha_at_CL | CDi | e_CDi | profile_cd | CD0_total | CD_total | L/D | P_crank W |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in [old, policy_a, policy_c]:
        lines.append(
            "| {case} | {sref} | {cl} | {alpha} | {cdi} | {e} | {profile} | {cd0} | {cdtot} | {ld} | {power} |".format(
                case=row["case"],
                sref=_fmt(row["Sref"], 3),
                cl=_fmt(row["CL_req"], 6),
                alpha=_fmt(row["alpha_at_CL_req_deg"], 3),
                cdi=_fmt(row["CDi"], 6),
                e=_fmt(row["e_CDi"], 6),
                profile=_fmt(row["profile_cd"], 6),
                cd0=_fmt(row["CD0_total_est"], 6),
                cdtot=_fmt(row["CD_total"], 6),
                ld=_fmt(row["L_over_D"], 2),
                power=_fmt(row["P_crank_w"], 1),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- The old design has larger Sref ({_fmt(old['Sref'], 3)} m2), so its current-mission CL_req "
            f"is lower than Phase 7 ({_fmt(old['CL_req'], 6)} vs {_fmt(policy_a['CL_req'], 6)}).",
            f"- Old AVL trim reaches CL_req at alpha={_fmt(old['alpha_at_CL_req_deg'], 3)} deg. "
            "That is plausible for the old file because its wing sections carry +3 deg incidence and "
            "cambered FX/Clark airfoils.",
            f"- Old AVL reports e_CDi={_fmt(old['e_CDi'], 6)}. Because this is a full-aircraft AVL/Trefftz "
            "diagnostic with the old reference setup, treat values above 1.0 as a parity/reference caveat; "
            "use CDi and power deltas as the safer comparison quantities.",
            f"- Old profile drag source quality is `{old['source_quality']}`. Refresh this term after "
            "Tier2 full-alpha DB completion.",
            "- Policy A remains the performance candidate from Phase 7; Policy C remains the conservative "
            "reporting baseline.",
            "- VSPAERO/OpenVSP CDo is not used here; wing profile drag comes from the same 2D-polar "
            "workflow family used for the sidecar comparisons.",
            "",
            "## Rerun Hook",
            "",
            "After Tier2 completes, refresh only the profile lookup/comparison with:",
            "",
            "```bash",
            ".venv/bin/python scripts/rerun_old_fx_clark_comparison_with_tier2.py --profile-db tier2",
            "```",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_recommended_interpretation(
    *,
    path: Path,
    comparison_rows: list[dict[str, Any]],
    avl_result: dict[str, Any],
    profile_summary: dict[str, Any],
) -> None:
    old = comparison_rows[0]
    policy_a = comparison_rows[1]
    policy_c = comparison_rows[2]
    profile_status = (
        "provisional pre-Tier2"
        if profile_summary["profile_db_label"] == "provisional_pre_tier2"
        else "Tier2 refreshed"
    )
    lines = [
        "# Recommended Interpretation",
        "",
        "## Bottom Line",
        "",
        f"The old FX/Clark baseline trim is meaningful now on the AVL side: alpha_at_CL_req is "
        f"{_fmt(old['alpha_at_CL_req_deg'], 3)} deg, CDi is {_fmt(old['CDi'], 6)}, and e_CDi is "
        f"{_fmt(old['e_CDi'], 6)}. The profile term is {profile_status}.",
        "",
        "## Engineering Read",
        "",
        f"- Old Sref is {_fmt(old['Sref'], 3)} m2 versus Phase 7 Sref {_fmt(policy_a['Sref'], 3)} m2, "
        f"so old CL_req is lower ({_fmt(old['CL_req'], 6)} vs {_fmt(policy_a['CL_req'], 6)}). "
        "Do not interpret lower local Cl by itself as better span efficiency.",
        f"- Old max station Cl is {_fmt(avl_result['max_station_cl'], 6)}. The provisional stall utilization "
        f"is {_fmt(old['max_station_utilization'], 3)} using available seed polar safe_clmax.",
        f"- Old AVL reports e_CDi={_fmt(old['e_CDi'], 6)}, which is above the usual planar-wing intuition. "
        "Treat that as a full-aircraft/reference-convention caveat, not as evidence that the old wing has "
        "physically super-elliptic efficiency.",
        f"- The negative trim alpha ({_fmt(old['alpha_at_CL_req_deg'], 3)} deg) is not automatically a problem; "
        "the old wing file has +3 deg section incidence and cambered airfoils.",
        f"- Old CD0_total_est is {_fmt(old['CD0_total_est'], 6)} and the mission drag band is "
        f"`{old['mission_drag_budget_band']}` with the current provisional profile data.",
        f"- Compared with Policy A, old crank power is {_fmt(old['P_crank_w'], 1)} W vs "
        f"{_fmt(policy_a['P_crank_w'], 1)} W on the same mission/power assumptions.",
        f"- Compared with Policy C, old crank power is {_fmt(old['P_crank_w'], 1)} W vs "
        f"{_fmt(policy_c['P_crank_w'], 1)} W.",
        "",
        "## Caveats",
        "",
        "- The old AVL contains FX76MP140 on most inboard sections and ClarkY at the tip; the profile "
        "integration uses a discrete FX-inboard / Clark-outer proxy because no full-polar blended-section "
        "records exist.",
        "- The current profile comparison must be refreshed once Tier2 finishes. The rerun hook only reads "
        "the completed Tier2 database and reuses the already saved old AVL trim result.",
        "- No production ranking, hard gates, Fourier settings, CST/NSGA outputs, or Tier2 running files "
        "were modified by this diagnostic.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _copy_old_inputs(old_avl: Path, old_vsp: Path, output_dir: Path) -> None:
    shutil.copy2(old_avl, output_dir / "old_design.avl")
    if old_vsp.exists():
        shutil.copy2(old_vsp, output_dir / "old_design.vsp3")


def run_comparison(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    profile_db: str = "pre_tier2",
    old_avl: str | Path = DEFAULT_OLD_AVL,
    old_vsp: str | Path = DEFAULT_OLD_VSP,
    phase7_summary: str | Path = DEFAULT_PHASE7_SUMMARY,
    mission_report: str | Path = DEFAULT_MISSION_REPORT,
    pre_tier2_polar_csv: str | Path = DEFAULT_PRE_TIER2_POLAR_CSV,
    pre_tier2_records: str | Path = DEFAULT_PRE_TIER2_RECORDS,
    tier2_root: str | Path = DEFAULT_TIER2_ROOT,
    roughness_mode: str = "clean",
    avl_binary: str | Path | None = None,
    reuse_avl_results: str | Path | None = None,
) -> dict[str, Any]:
    out_dir = _repo_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    old_avl_path = _repo_path(old_avl)
    old_vsp_path = _repo_path(old_vsp)
    geometry = parse_wing_geometry_from_avl(old_avl_path)
    mission = _load_mission_contract(mission_report)
    profile = load_profile_database(
        profile_db=profile_db,
        pre_tier2_polar_csv=pre_tier2_polar_csv,
        pre_tier2_records=pre_tier2_records,
        tier2_root=tier2_root,
        roughness_mode=roughness_mode,
    )
    _copy_old_inputs(old_avl_path, old_vsp_path, out_dir)
    _write_section_table(geometry, out_dir)

    reuse_path = resolve_avl_reuse_path(profile_db=profile_db, reuse_avl_results=reuse_avl_results)
    if reuse_path is not None and reuse_path.exists():
        avl_result = json.loads(reuse_path.read_text(encoding="utf-8"))
    elif reuse_path is not None and profile_db == "tier2":
        raise FileNotFoundError(
            f"Tier2 profile rerun expects pre-Tier2 AVL result at {reuse_path}; "
            "run the default pre-Tier2 comparison first."
        )
    else:
        avl_result = _run_old_avl(
            avl_path=old_avl_path,
            output_dir=out_dir,
            geometry=geometry,
            mission=mission,
            avl_binary=avl_binary,
        )
    avl_result["generated_at"] = _timestamp()
    avl_result["source_vsp_path"] = str(old_vsp_path.resolve())
    avl_result["section_table_path"] = str((out_dir / "old_design_section_table.csv").resolve())
    (out_dir / "old_design_avl_results.json").write_text(
        json.dumps(avl_result, indent=2),
        encoding="utf-8",
    )

    profile_summary, profile_rows = _compute_profile_drag(
        avl_result=avl_result,
        geometry=geometry,
        mission=mission,
        profile_db=profile,
    )
    _write_profile_drag_csv(out_dir / "old_design_profile_drag.csv", profile_rows)

    policy_rows = _load_policy_rows(phase7_summary)
    policy_a_geometry = _load_phase7_geometry("policy_A_performance_candidate")
    policy_c_geometry = _load_phase7_geometry("policy_C_conservative_baseline")
    comparison_rows = [
        _old_comparison_row(
            avl_result=avl_result,
            profile_summary=profile_summary,
            geometry=geometry,
            mission=mission,
        ),
        _phase7_comparison_row(
            name="Policy A / D performance candidate",
            policy_row=policy_rows["Policy A / D"],
            geometry=policy_a_geometry,
            mission=mission,
        ),
        _phase7_comparison_row(
            name="Policy C / E conservative baseline",
            policy_row=policy_rows["Policy C / E"],
            geometry=policy_c_geometry,
            mission=mission,
        ),
    ]
    _write_csv(out_dir / "old_vs_policy_A_C_comparison.csv", comparison_rows)
    _write_csv(
        out_dir / "power_comparison.csv",
        [
            {
                "case": row["case"],
                "CL_req": row["CL_req"],
                "CDi": row["CDi"],
                "CD0_total_est": row["CD0_total_est"],
                "CD_total": row["CD_total"],
                "L_over_D": row["L_over_D"],
                "drag_n": row["drag_n"],
                "P_air_w": row["P_air_w"],
                "eta_prop": mission["eta_prop"],
                "eta_trans": mission["eta_trans"],
                "P_crank_w": row["P_crank_w"],
                "profile_source_label": row["profile_source_label"],
            }
            for row in comparison_rows
        ],
    )
    _write_comparison_markdown(
        out_dir / "old_vs_policy_A_C_comparison.md",
        comparison_rows,
        profile.profile_db if profile.profile_db != "pre_tier2" else profile.label,
    )
    _write_recommended_interpretation(
        path=out_dir / "recommended_interpretation.md",
        comparison_rows=comparison_rows,
        avl_result=avl_result,
        profile_summary=profile_summary,
    )
    run_metadata = {
        "generated_at": _timestamp(),
        "profile_db": profile.profile_db,
        "profile_db_label": profile.label,
        "profile_db_source_path": profile.source_path,
        "roughness_mode": roughness_mode,
        "tier2_root_not_written": str(_repo_path(tier2_root).resolve()),
        "outputs": sorted(str(path.name) for path in out_dir.iterdir()),
        "notes": [
            "Diagnostic-only comparison.",
            "No ranking or hard gates changed.",
            "Tier2 directory is only read when --profile-db tier2 is requested.",
        ],
    }
    (out_dir / "run_metadata.json").write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")
    return {
        "output_dir": str(out_dir.resolve()),
        "old_design": comparison_rows[0],
        "policy_a": comparison_rows[1],
        "policy_c": comparison_rows[2],
        "profile_summary": profile_summary,
        "run_metadata": run_metadata,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--profile-db", choices=("pre_tier2", "tier2"), default="pre_tier2")
    parser.add_argument("--old-avl", type=Path, default=DEFAULT_OLD_AVL)
    parser.add_argument("--old-vsp", type=Path, default=DEFAULT_OLD_VSP)
    parser.add_argument("--phase7-summary", type=Path, default=DEFAULT_PHASE7_SUMMARY)
    parser.add_argument("--mission-report", type=Path, default=DEFAULT_MISSION_REPORT)
    parser.add_argument("--pre-tier2-polar-csv", type=Path, default=DEFAULT_PRE_TIER2_POLAR_CSV)
    parser.add_argument("--pre-tier2-records", type=Path, default=DEFAULT_PRE_TIER2_RECORDS)
    parser.add_argument("--tier2-root", type=Path, default=DEFAULT_TIER2_ROOT)
    parser.add_argument("--roughness-mode", default="clean")
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument(
        "--reuse-avl-results",
        type=Path,
        default=None,
        help=(
            "Reuse an existing old_design_avl_results.json. Defaults to the pre-Tier2 "
            "output when --profile-db tier2 is selected."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    summary = run_comparison(
        output_dir=args.output_dir,
        profile_db=args.profile_db,
        old_avl=args.old_avl,
        old_vsp=args.old_vsp,
        phase7_summary=args.phase7_summary,
        mission_report=args.mission_report,
        pre_tier2_polar_csv=args.pre_tier2_polar_csv,
        pre_tier2_records=args.pre_tier2_records,
        tier2_root=args.tier2_root,
        roughness_mode=args.roughness_mode,
        avl_binary=args.avl_binary,
        reuse_avl_results=args.reuse_avl_results,
    )
    old = summary["old_design"]
    print(f"Wrote comparison artifacts to {summary['output_dir']}")
    print(
        "Old FX/Clark: "
        f"CL_req={old['CL_req']:.6f}, alpha={old['alpha_at_CL_req_deg']:.3f} deg, "
        f"CDi={old['CDi']:.6f}, e_CDi={old['e_CDi']:.6f}, "
        f"profile_cd={old['profile_cd']:.6f}, P_crank={old['P_crank_w']:.1f} W"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
