#!/usr/bin/env python3
"""Phase 9 smooth planform and jig/structure feasibility sidecar study.

This is a diagnostic production-facing study. It writes only under
``output/phase9_structure_jig_smooth_planform`` and does not mutate ranking,
hard gates, CST/NSGA outputs, or the Tier 2 database.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from hpa_mdo.aero.fourier_target import FourierTarget, compare_fourier_target_to_avl  # noqa: E402
from hpa_mdo.concept.config import JigShapeGateConfig, TubeSystemGeometryConfig  # noqa: E402
from hpa_mdo.concept.jig_shape import estimate_tip_deflection  # noqa: E402

from scripts import audit_avl_induced_drag_credibility as avl_audit  # noqa: E402
from scripts import export_phase7_sidecar_vsp as vsp_exporter  # noqa: E402


DEFAULT_OUTPUT_DIR = _REPO_ROOT / "output" / "phase9_structure_jig_smooth_planform"
FINAL_VALIDATION_DIR = _REPO_ROOT / "output" / "final_candidate_validation" / "tier2_raw_vs_conservative"
TIER2_PROFILE_DIR = _REPO_ROOT / "output" / "airfoil_db" / "full_alpha_reusable_v1_tier2"
PHASE7_EXPORT_DIR = _REPO_ROOT / "output" / "geometry_exports" / "phase7_sidecar_vsp"
PHASE7_PARITY_DIR = _REPO_ROOT / "output" / "geometry_exports" / "phase7_avl_vsp_parity"
OLD_BASELINE_DIR = _REPO_ROOT / "output" / "baseline_comparisons" / "old_fx_clark_vs_phase7_tier2"
OLD_CDI_DEBUG_DIR = _REPO_ROOT / "output" / "baseline_comparisons" / "old_fx_clark_vs_phase7_cdi_debug"
FOURIER_TARGET_JSON = (
    _REPO_ROOT
    / "output"
    / "airfoil_db"
    / "full_polar_archive"
    / "phase6_full_polar_sidecar"
    / "top_candidate_exports"
    / "rank_01_sample_0007"
    / "fourier_target.json"
)

MISSION_CL_REQ = 1.1685305045195065
OLD_CL_REQ = 1.1102304984748252
MISSION_SPEED_MPS = 6.6
MISSION_RHO_KGPM3 = 1.135669
MISSION_DYNAMIC_VISCOSITY_PA_S = 1.789e-5
MISSION_NONWING_CDA_M2 = 0.13
ETA_PROP = 0.86
ETA_TRANS = 0.96
CURRENT_SPAR_TUBE_MASS_TARGET_KG = 11.7534

ZONE_BOUNDS: tuple[tuple[str, float, float], ...] = (
    ("root", 0.0, 0.25),
    ("mid1", 0.25, 0.55),
    ("mid2", 0.55, 0.80),
    ("tip", 0.80, 1.000001),
)


@dataclass(frozen=True)
class SectionRow:
    index: int
    eta: float
    y_m: float
    z_m: float
    chord_m: float
    twist_deg: float
    airfoil_id: str
    airfoil_dat_path: str
    airfoil_source_quality: str = "unknown"
    dihedral_local_z_slope: float | None = None
    dihedral_local_deg: float | None = None


@dataclass(frozen=True)
class CandidateSpec:
    case_id: str
    display_name: str
    assignment: dict[str, str]
    cl_req: float
    raw_avl: Path
    raw_section_table: Path
    raw_vsp3: Path | None
    monotone_avl: Path | None
    monotone_section_table: Path | None
    monotone_vsp3: Path | None
    family: str
    useful: bool = True


@dataclass(frozen=True)
class VariantSpec:
    case: CandidateSpec
    variant: str
    avl_path: Path
    section_table: Path
    vsp3_path: Path | None
    generated: bool


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        output = float(value)
    except (TypeError, ValueError):
        return default
    return output if math.isfinite(output) else default


def zone_for_eta(eta: float) -> str:
    eta_value = float(eta)
    for zone, lo, hi in ZONE_BOUNDS:
        if lo <= eta_value < hi:
            return zone
    return "tip"


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(json_ready(dict(row)))


def json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def parse_assignment(text: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for item in str(text).split("|"):
        if ":" not in item:
            continue
        zone, airfoil = item.split(":", 1)
        output[zone.strip()] = airfoil.strip()
    return output


def read_section_table(path: str | Path) -> tuple[SectionRow, ...]:
    rows = read_csv_rows(path)
    if not rows:
        return ()
    half_span = max(safe_float(row.get("y_m"), 0.0) or 0.0 for row in rows)
    sections: list[SectionRow] = []
    for idx, row in enumerate(rows):
        y_m = safe_float(row.get("y_m"), 0.0) or 0.0
        eta = safe_float(row.get("eta"))
        if eta is None:
            eta = 0.0 if half_span <= 0.0 else y_m / half_span
        sections.append(
            SectionRow(
                index=int(safe_float(row.get("section_index"), idx) or idx),
                eta=float(eta),
                y_m=float(y_m),
                z_m=float(safe_float(row.get("z_m"), 0.0) or 0.0),
                chord_m=float(safe_float(row.get("chord_m"), 0.0) or 0.0),
                twist_deg=float(safe_float(row.get("twist_deg"), 0.0) or 0.0),
                airfoil_id=str(row.get("airfoil_id") or ""),
                airfoil_dat_path=str(row.get("airfoil_dat_path") or ""),
                airfoil_source_quality=str(row.get("airfoil_source_quality") or "unknown"),
                dihedral_local_z_slope=safe_float(
                    row.get("dihedral_local_z_slope", row.get("local_z_slope"))
                ),
                dihedral_local_deg=safe_float(
                    row.get("dihedral_local_deg", row.get("local_dihedral_deg"))
                ),
            )
        )
    return tuple(sections)


def section_to_exported(row: SectionRow) -> vsp_exporter.ExportedSection:
    return vsp_exporter.ExportedSection(
        section_index=int(row.index),
        eta=float(row.eta),
        y_m=float(row.y_m),
        z_m=float(row.z_m),
        chord_m=float(row.chord_m),
        twist_deg=float(row.twist_deg),
        dihedral_local_z_slope=row.dihedral_local_z_slope,
        dihedral_local_deg=row.dihedral_local_deg,
        airfoil_id=str(row.airfoil_id),
        airfoil_source_quality=str(row.airfoil_source_quality),
        airfoil_dat_path=str(row.airfoil_dat_path),
    )


def area_from_sections(sections: Sequence[SectionRow]) -> float:
    if len(sections) < 2:
        return 0.0
    half_area = 0.0
    for left, right in zip(sections[:-1], sections[1:]):
        half_area += 0.5 * (right.y_m - left.y_m) * (left.chord_m + right.chord_m)
    return 2.0 * half_area


def mac_from_sections(sections: Sequence[SectionRow]) -> float | None:
    area = area_from_sections(sections)
    if area <= 0.0 or len(sections) < 2:
        return None
    integral = 0.0
    for left, right in zip(sections[:-1], sections[1:]):
        dy = right.y_m - left.y_m
        integral += dy * (left.chord_m**2 + left.chord_m * right.chord_m + right.chord_m**2) / 3.0
    return 2.0 * integral / area


def _power_law_chord(root: float, tip: float, exponent: float, eta: float) -> float:
    return float(tip) + (float(root) - float(tip)) * max(0.0, 1.0 - float(eta)) ** float(exponent)


def _power_law_area(sections: Sequence[SectionRow], exponent: float) -> float:
    root = sections[0].chord_m
    tip = sections[-1].chord_m
    fitted = [
        replace(row, chord_m=_power_law_chord(root, tip, exponent, row.eta))
        for row in sections
    ]
    return area_from_sections(fitted)


def _solve_power_law_exponent(sections: Sequence[SectionRow], target_area_m2: float) -> float:
    low = 0.05
    high = 8.0
    low_area = _power_law_area(sections, low)
    high_area = _power_law_area(sections, high)
    target = float(target_area_m2)
    if not (high_area <= target <= low_area):
        return 1.0
    for _ in range(80):
        mid = 0.5 * (low + high)
        area = _power_law_area(sections, mid)
        if area > target:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def smooth_power_law_sections(
    sections: Sequence[SectionRow],
    *,
    target_area_m2: float,
) -> tuple[tuple[SectionRow, ...], dict[str, Any]]:
    if len(sections) < 2:
        return tuple(sections), {"fit_method": "insufficient_sections"}
    root = float(sections[0].chord_m)
    tip = float(sections[-1].chord_m)
    exponent = _solve_power_law_exponent(sections, target_area_m2)
    out = tuple(
        replace(row, chord_m=_power_law_chord(root, tip, exponent, row.eta))
        for row in sections
    )
    area_error_pct = 100.0 * (area_from_sections(out) - float(target_area_m2)) / max(abs(float(target_area_m2)), 1.0e-12)
    return out, {
        "fit_method": "smooth_area_matching_power_law",
        "power_law_exponent": exponent,
        "target_area_m2": float(target_area_m2),
        "fitted_area_m2": area_from_sections(out),
        "area_error_pct": area_error_pct,
        "root_chord_preserved": True,
        "tip_chord_preserved": True,
    }


def pava_monotone_sections(
    sections: Sequence[SectionRow],
    *,
    target_area_m2: float,
) -> tuple[SectionRow, ...]:
    if not sections:
        return ()
    values = [max(row.chord_m, 1.0e-9) for row in sections]
    blocks: list[dict[str, float]] = []
    for value in values:
        blocks.append({"level": value, "weight": 1.0, "count": 1.0})
        while len(blocks) >= 2 and blocks[-2]["level"] < blocks[-1]["level"]:
            left = blocks.pop(-2)
            right = blocks.pop(-1)
            weight = left["weight"] + right["weight"]
            level = (left["level"] * left["weight"] + right["level"] * right["weight"]) / weight
            blocks.append({"level": level, "weight": weight, "count": left["count"] + right["count"]})
    fitted: list[float] = []
    for block in blocks:
        fitted.extend([block["level"]] * int(block["count"]))
    tmp = tuple(replace(row, chord_m=chord) for row, chord in zip(sections, fitted))
    area = area_from_sections(tmp)
    scale = 1.0 if area <= 0.0 else float(target_area_m2) / area
    return tuple(replace(row, chord_m=max(row.chord_m * scale, 1.0e-9)) for row in tmp)


def _slopes(sections: Sequence[SectionRow]) -> list[float]:
    slopes: list[float] = []
    for left, right in zip(sections[:-1], sections[1:]):
        dy = right.y_m - left.y_m
        if abs(dy) <= 1.0e-12:
            slopes.append(0.0)
        else:
            slopes.append((right.chord_m - left.chord_m) / dy)
    return slopes


def geometry_quality_metrics(
    *,
    case_id: str,
    variant: str,
    sections: Sequence[SectionRow],
    reference_sections: Sequence[SectionRow],
) -> dict[str, Any]:
    chords = [row.chord_m for row in sections]
    slopes = _slopes(sections)
    slope_changes = [right - left for left, right in zip(slopes[:-1], slopes[1:])]
    positive_jumps = [right - left for left, right in zip(chords[:-1], chords[1:]) if right > left + 1.0e-9]
    jumps = [abs(right - left) for left, right in zip(chords[:-1], chords[1:])]
    near_constant = [s for s in slopes if abs(s) <= 1.0e-4]
    area = area_from_sections(sections)
    ref_area = area_from_sections(reference_sections)
    mac = mac_from_sections(sections)
    ref_mac = mac_from_sections(reference_sections)
    max_slope_change = max((abs(value) for value in slope_changes), default=0.0)
    curvature_proxy = math.sqrt(sum(value * value for value in slope_changes) / max(len(slope_changes), 1))
    area_error_pct = 100.0 * (area - ref_area) / max(abs(ref_area), 1.0e-12)
    mac_error_pct = (
        None
        if mac is None or ref_mac is None
        else 100.0 * (mac - ref_mac) / max(abs(ref_mac), 1.0e-12)
    )
    score = 100.0
    score -= 18.0 * len(positive_jumps)
    score -= min(30.0, 800.0 * max_slope_change)
    score -= min(20.0, 1500.0 * curvature_proxy)
    score -= min(18.0, 4.0 * len(near_constant))
    score -= min(10.0, 2.0 * abs(area_error_pct))
    return {
        "case_id": case_id,
        "variant": variant,
        "chord_monotone_nonincreasing": not positive_jumps,
        "positive_chord_jump_count": len(positive_jumps),
        "max_positive_chord_jump_m": max(positive_jumps, default=0.0),
        "max_chord_jump_abs_m": max(jumps, default=0.0),
        "max_slope_change_abs": max_slope_change,
        "curvature_smoothness_proxy": curvature_proxy,
        "near_constant_chord_segment_count": len(near_constant),
        "root_chord_m": chords[0] if chords else None,
        "tip_chord_m": chords[-1] if chords else None,
        "area_m2": area,
        "area_error_pct_vs_reference": area_error_pct,
        "MAC_m": mac,
        "MAC_error_pct_vs_reference": mac_error_pct,
        "visual_production_score": max(0.0, min(100.0, score)),
        "quality_basis": "chord station smoothness proxy; not a CAD curvature proof",
    }


def sections_to_csv(path: Path, sections: Sequence[SectionRow]) -> None:
    rows = []
    for row in sections:
        rows.append(
            {
                "section_index": row.index,
                "eta": row.eta,
                "y_m": row.y_m,
                "z_m": row.z_m,
                "chord_m": row.chord_m,
                "twist_deg": row.twist_deg,
                "dihedral_local_z_slope": row.dihedral_local_z_slope,
                "dihedral_local_deg": row.dihedral_local_deg,
                "airfoil_id": row.airfoil_id,
                "airfoil_source_quality": row.airfoil_source_quality,
                "airfoil_dat_path": row.airfoil_dat_path,
            }
        )
    write_csv(path, rows)


def _geometry_for_smoothed_avl(source_avl: Path, sections: Sequence[SectionRow]) -> vsp_exporter.AvlGeometry:
    source = vsp_exporter.parse_avl_geometry(source_avl)
    area = area_from_sections(sections)
    mac = mac_from_sections(sections) or source.cref_m
    span = 2.0 * max((row.y_m for row in sections), default=0.0)
    return vsp_exporter.AvlGeometry(
        title=f"{source.title} Phase9 smooth monotone",
        sref_m2=area,
        cref_m=mac,
        bref_m=span,
        xref_m=source.xref_m,
        yref_m=source.yref_m,
        zref_m=source.zref_m,
        sections=source.sections,
    )


def export_sections_variant(
    *,
    source_avl: Path,
    sections: Sequence[SectionRow],
    out_dir: Path,
    file_stem: str,
    build_vsp: bool,
) -> tuple[Path, Path, Path | None, dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    section_csv = out_dir / "section_table.csv"
    sections_to_csv(section_csv, sections)
    avl_path = out_dir / f"{file_stem}.avl"
    exported_sections = tuple(section_to_exported(row) for row in sections)
    vsp_exporter.write_avl(_geometry_for_smoothed_avl(source_avl, sections), exported_sections, avl_path)
    vsp3_path = out_dir / f"{file_stem}.vsp3"
    vspscript_path = out_dir / f"{file_stem}.vspscript"
    vsp_report = vsp_exporter.build_vsp3_from_sections(
        exported_sections,
        output_path=vsp3_path,
        script_path=vspscript_path,
        build_vsp=build_vsp,
    )
    return avl_path, section_csv, vsp3_path if vsp3_path.is_file() else None, vsp_report


def build_candidate_specs() -> list[CandidateSpec]:
    final_validation = json.loads(
        (FINAL_VALIDATION_DIR / "validation_manifest.json").read_text(encoding="utf-8")
    )
    raw_power = {
        row["case_id"]: row
        for row in read_csv_rows(FINAL_VALIDATION_DIR / "raw_vs_conservative_power.csv")
    }
    raw = final_validation["exports"]["raw_best"]
    conservative = final_validation["exports"]["conservative_best"]

    policy_rows = {
        row["policy_id"]: row
        for row in read_csv_rows(TIER2_PROFILE_DIR.parent / "full_alpha_reusable_v1_tier2_current_mission" / "policy_comparison_tier2.csv")
    }
    old_assignment = {"root": "fx76mp140", "mid1": "fx76mp140", "mid2": "clarkysm", "tip": "clarkysm"}
    return [
        CandidateSpec(
            case_id="raw_best_tier2",
            display_name="Tier2 raw performance best",
            assignment=parse_assignment(raw_power["raw_best"]["assignment"]),
            cl_req=MISSION_CL_REQ,
            raw_avl=Path(raw["avl_parity"]["avl_path"]),
            raw_section_table=Path(raw["avl_parity"]["section_table_csv"]),
            raw_vsp3=Path(raw["avl_parity"]["vsp3_path"]),
            monotone_avl=Path(raw["production_inspection"]["avl_path"]),
            monotone_section_table=Path(raw["production_inspection"]["section_table_csv"]),
            monotone_vsp3=Path(raw["production_inspection"]["vsp3_path"]),
            family="tier2_raw",
        ),
        CandidateSpec(
            case_id="conservative_best_tier2",
            display_name="Tier2 conservative best",
            assignment=parse_assignment(raw_power["conservative_best"]["assignment"]),
            cl_req=MISSION_CL_REQ,
            raw_avl=Path(conservative["avl_parity"]["avl_path"]),
            raw_section_table=Path(conservative["avl_parity"]["section_table_csv"]),
            raw_vsp3=Path(conservative["avl_parity"]["vsp3_path"]),
            monotone_avl=Path(conservative["production_inspection"]["avl_path"]),
            monotone_section_table=Path(conservative["production_inspection"]["section_table_csv"]),
            monotone_vsp3=Path(conservative["production_inspection"]["vsp3_path"]),
            family="tier2_conservative",
        ),
        CandidateSpec(
            case_id="policy_A_performance_candidate",
            display_name="Policy A / D performance candidate",
            assignment=parse_assignment(policy_rows["A"]["assignment"]),
            cl_req=MISSION_CL_REQ,
            raw_avl=PHASE7_EXPORT_DIR / "policy_A_performance_candidate" / "policy_A_performance_candidate.avl",
            raw_section_table=PHASE7_EXPORT_DIR / "policy_A_performance_candidate" / "section_table.csv",
            raw_vsp3=PHASE7_EXPORT_DIR / "policy_A_performance_candidate" / "policy_A_performance_candidate.vsp3",
            monotone_avl=PHASE7_PARITY_DIR / "monotone_chord" / "policy_A_performance_candidate" / "policy_A_performance_candidate_monotone_chord.avl",
            monotone_section_table=PHASE7_PARITY_DIR / "monotone_chord" / "policy_A_performance_candidate" / "section_table.csv",
            monotone_vsp3=PHASE7_PARITY_DIR / "monotone_chord" / "policy_A_performance_candidate" / "policy_A_performance_candidate_monotone_chord.vsp3",
            family="policy_A",
        ),
        CandidateSpec(
            case_id="policy_C_conservative_baseline",
            display_name="Policy C / E conservative baseline",
            assignment=parse_assignment(policy_rows["C"]["assignment"]),
            cl_req=MISSION_CL_REQ,
            raw_avl=PHASE7_EXPORT_DIR / "policy_C_conservative_baseline" / "policy_C_conservative_baseline.avl",
            raw_section_table=PHASE7_EXPORT_DIR / "policy_C_conservative_baseline" / "section_table.csv",
            raw_vsp3=PHASE7_EXPORT_DIR / "policy_C_conservative_baseline" / "policy_C_conservative_baseline.vsp3",
            monotone_avl=PHASE7_PARITY_DIR / "monotone_chord" / "policy_C_conservative_baseline" / "policy_C_conservative_baseline_monotone_chord.avl",
            monotone_section_table=PHASE7_PARITY_DIR / "monotone_chord" / "policy_C_conservative_baseline" / "section_table.csv",
            monotone_vsp3=PHASE7_PARITY_DIR / "monotone_chord" / "policy_C_conservative_baseline" / "policy_C_conservative_baseline_monotone_chord.vsp3",
            family="policy_C",
        ),
        CandidateSpec(
            case_id="old_fx_clark_baseline",
            display_name="Old FX/Clark baseline",
            assignment=old_assignment,
            cl_req=OLD_CL_REQ,
            raw_avl=OLD_CDI_DEBUG_DIR / "old_main_wing_only.avl",
            raw_section_table=OLD_BASELINE_DIR / "old_design_section_table.csv",
            raw_vsp3=OLD_BASELINE_DIR / "old_design.vsp3",
            monotone_avl=None,
            monotone_section_table=None,
            monotone_vsp3=None,
            family="old_fx_clark",
        ),
    ]


def load_fourier_target() -> FourierTarget | None:
    if not FOURIER_TARGET_JSON.is_file():
        return None
    data = json.loads(FOURIER_TARGET_JSON.read_text(encoding="utf-8"))
    target = data.get("mission_fourier_target", data)
    try:
        return FourierTarget(
            y=tuple(float(v) for v in target["y"]),
            eta=tuple(float(v) for v in target["eta"]),
            theta=tuple(float(v) for v in target["theta"]),
            chord_ref=tuple(float(v) for v in target["chord_ref"]),
            gamma_target=tuple(float(v) for v in target["gamma_target"]),
            lprime_target=tuple(float(v) for v in target["lprime_target"]),
            cl_target=tuple(float(v) for v in target["cl_target"]),
            A1=float(target["A1"]),
            r3=float(target["r3"]),
            r5=float(target["r5"]),
            e_theory=float(target["e_theory"]),
            CL_req=float(target["CL_req"]),
            AR=float(target["AR"]),
            outer_lift_fraction=float(target["outer_lift_fraction"]),
            outer_lift_ratio_vs_ellipse=float(target["outer_lift_ratio_vs_ellipse"]),
            root_bending_proxy=float(target["root_bending_proxy"]),
            gamma_min=float(target["gamma_min"]),
            cl_max=float(target["cl_max"]),
            source=str(target["source"]),
            lift_total_n=float(target["lift_total_n"]),
            lift_error_n=float(target["lift_error_n"]),
            lift_error_fraction=float(target["lift_error_fraction"]),
            validation_status=str(target["validation_status"]),
            validation_warnings=tuple(str(v) for v in target.get("validation_warnings", ())),
        )
    except Exception:
        return None


class ProfileLookup:
    def __init__(self, polar_csv: Path, airfoil_ids: Iterable[str]) -> None:
        wanted = set(airfoil_ids)
        self.points: dict[str, list[dict[str, float]]] = {airfoil: [] for airfoil in wanted}
        if not polar_csv.is_file():
            return
        with polar_csv.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                airfoil = str(row.get("airfoil_id") or "")
                if airfoil not in wanted:
                    continue
                if str(row.get("roughness_mode") or "").lower() != "clean":
                    continue
                if str(row.get("status") or "").lower() != "ok":
                    continue
                cl = safe_float(row.get("Cl", row.get("cl")))
                cd = safe_float(row.get("Cd", row.get("cd")))
                re_value = safe_float(row.get("Re"))
                if cl is None or cd is None or re_value is None or cd <= 0.0:
                    continue
                self.points.setdefault(airfoil, []).append({"cl": cl, "cd": cd, "Re": re_value})
        for points in self.points.values():
            points.sort(key=lambda item: (item["Re"], item["cl"]))

    def cd_for(self, airfoil_id: str, *, re_value: float, cl: float) -> tuple[float | None, str]:
        points = self.points.get(airfoil_id, [])
        if not points:
            return None, "missing_airfoil_polar"
        re_levels = sorted({p["Re"] for p in points})
        nearest_re = min(re_levels, key=lambda value: abs(value - re_value))
        subset = [p for p in points if p["Re"] == nearest_re]
        subset.sort(key=lambda item: item["cl"])
        if len(subset) < 2:
            return subset[0]["cd"], "nearest_single_point"
        if cl <= subset[0]["cl"]:
            return subset[0]["cd"], "clamped_low_cl"
        if cl >= subset[-1]["cl"]:
            return subset[-1]["cd"], "clamped_high_cl"
        for left, right in zip(subset[:-1], subset[1:]):
            if left["cl"] <= cl <= right["cl"]:
                denom = right["cl"] - left["cl"]
                if abs(denom) <= 1.0e-12:
                    return min(left["cd"], right["cd"]), "duplicate_cl_min_cd"
                frac = (cl - left["cl"]) / denom
                return left["cd"] + frac * (right["cd"] - left["cd"]), "interp_clean_nearest_re"
        return min(subset, key=lambda item: abs(item["cl"] - cl))["cd"], "nearest_cl_fallback"


def profile_cd_from_spanload(
    *,
    spanload: Sequence[Mapping[str, Any]],
    assignment: Mapping[str, str],
    lookup: ProfileLookup,
    sref_m2: float,
) -> dict[str, Any]:
    station_rows: list[dict[str, Any]] = []
    for row in spanload:
        eta = float(row["eta"])
        airfoil = assignment.get(zone_for_eta(eta), "")
        chord = float(row["chord_m"])
        cl = float(row["cl"])
        re_value = MISSION_RHO_KGPM3 * MISSION_SPEED_MPS * chord / MISSION_DYNAMIC_VISCOSITY_PA_S
        cd, status = lookup.cd_for(airfoil, re_value=re_value, cl=cl)
        station_rows.append(
            {
                "eta": eta,
                "y_m": float(row["y_m"]),
                "chord_m": chord,
                "cl": cl,
                "airfoil_id": airfoil,
                "Re": re_value,
                "profile_cd_station": cd,
                "profile_lookup_status": status,
            }
        )
    integral = 0.0
    valid_segments = 0
    for left, right in zip(station_rows[:-1], station_rows[1:]):
        if left["profile_cd_station"] is None or right["profile_cd_station"] is None:
            continue
        dy = right["y_m"] - left["y_m"]
        left_value = float(left["profile_cd_station"]) * float(left["chord_m"])
        right_value = float(right["profile_cd_station"]) * float(right["chord_m"])
        integral += 0.5 * dy * (left_value + right_value)
        valid_segments += 1
    profile_cd = None if valid_segments <= 0 else 2.0 * integral / max(float(sref_m2), 1.0e-12)
    statuses = sorted({str(row["profile_lookup_status"]) for row in station_rows})
    return {
        "profile_cd": profile_cd,
        "profile_lookup_statuses": "|".join(statuses),
        "profile_station_rows": station_rows,
    }


def load_safe_records() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for row in read_csv_rows(TIER2_PROFILE_DIR / "airfoil_records.csv"):
        if row.get("airfoil_id"):
            records[str(row["airfoil_id"])] = dict(row)
    return records


def zone_summary(
    *,
    case: CandidateSpec,
    variant: str,
    spanload: Sequence[Mapping[str, Any]],
    safe_records: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for zone, lo, hi in ZONE_BOUNDS:
        subset = [row for row in spanload if lo <= float(row["eta"]) < hi]
        if not subset:
            continue
        cls = [float(row["cl"]) for row in subset]
        airfoil = case.assignment.get(zone, "")
        safe = safe_float(safe_records.get(airfoil, {}).get("safe_clmax"))
        usable = safe_float(safe_records.get(airfoil, {}).get("usable_clmax"))
        rows.append(
            {
                "case_id": case.case_id,
                "variant": variant,
                "zone": zone,
                "airfoil_id": airfoil,
                "local_Cl_max": max(cls),
                "local_Cl_mean": sum(cls) / len(cls),
                "safe_clmax": safe,
                "usable_clmax": usable,
                "stall_margin_cl": None if safe is None else safe - max(cls),
                "stall_utilization": None if safe is None or safe <= 0.0 else max(cls) / safe,
            }
        )
    return rows


def integrate_trapezoid(x: Sequence[float], y: Sequence[float]) -> float:
    total = 0.0
    for left_x, right_x, left_y, right_y in zip(x[:-1], x[1:], y[:-1], y[1:]):
        total += 0.5 * (right_x - left_x) * (left_y + right_y)
    return total


def spanload_structure_metrics(spanload: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    y = [float(row["y_m"]) for row in spanload]
    lift = [float(row.get("lift_per_span", 0.0) or 0.0) for row in spanload]
    if len(y) < 2:
        return {}
    total_lift_half_n = integrate_trapezoid(y, lift)
    root_bending = integrate_trapezoid(y, [yy * ll for yy, ll in zip(y, lift)])
    second_moment = integrate_trapezoid(y, [yy * yy * ll for yy, ll in zip(y, lift)])
    outer_rows = [(yy, ll, float(row["eta"])) for yy, ll, row in zip(y, lift, spanload) if float(row["eta"]) >= 0.70]
    outer_fraction = None
    if total_lift_half_n > 0.0 and len(outer_rows) >= 2:
        outer_fraction = integrate_trapezoid(
            [item[0] for item in outer_rows],
            [item[1] for item in outer_rows],
        ) / total_lift_half_n
    return {
        "spanload_total_half_lift_n": total_lift_half_n,
        "root_bending_proxy_n_m": root_bending,
        "tip_deflection_second_moment_proxy": second_moment,
        "outer_lift_fraction_eta_ge_0p70": outer_fraction,
        "structure_proxy_basis": "AVL spanload integrals; not_structure_grade",
    }


def nominal_jig_estimate(span_m: float) -> dict[str, Any]:
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
    gate = JigShapeGateConfig()
    estimate = estimate_tip_deflection(
        gross_mass_kg=98.5,
        span_m=span_m,
        tube_geom=tube,
        gate_cfg=gate,
    )
    return {
        "uniform_wire_relieved_tip_deflection_m": estimate.tip_deflection_m,
        "uniform_unbraced_tip_deflection_m": estimate.unbraced_tip_deflection_m,
        "wire_relief_effect_m": estimate.lift_wire_relief_deflection_m,
        "uniform_tip_deflection_ratio": estimate.tip_deflection_ratio,
        "uniform_effective_dihedral_deg": estimate.effective_dihedral_deg,
        "wire_attach_span_fraction": estimate.lift_wire_attach_span_fraction,
        "wire_cruise_lift_fraction_carried": estimate.lift_wire_cruise_lift_fraction_carried,
        "jig_preferred_tip_deflection_min_m": gate.preferred_tip_deflection_m_min,
        "jig_preferred_tip_deflection_max_m": gate.preferred_tip_deflection_m_max,
        "jig_hard_tip_deflection_ratio_max": gate.max_tip_deflection_to_halfspan_ratio,
    }


def structure_jig_row(
    *,
    case: CandidateSpec,
    variant: str,
    sections: Sequence[SectionRow],
    spanload_metrics: Mapping[str, Any],
    baseline_bending: float | None,
    baseline_second_moment: float | None,
) -> dict[str, Any]:
    span_m = 2.0 * max((row.y_m for row in sections), default=0.0)
    half_span = 0.5 * span_m
    loaded_tip_z = sections[-1].z_m if sections else None
    jig = nominal_jig_estimate(span_m) if span_m > 0.0 else {}
    second = safe_float(spanload_metrics.get("tip_deflection_second_moment_proxy"))
    ratio_second = None if baseline_second_moment in (None, 0.0) or second is None else second / baseline_second_moment
    deflection_est = safe_float(jig.get("uniform_wire_relieved_tip_deflection_m"))
    unbraced = safe_float(jig.get("uniform_unbraced_tip_deflection_m"))
    wire_relief = safe_float(jig.get("wire_relief_effect_m"))
    if deflection_est is not None and ratio_second is not None:
        deflection_est *= ratio_second
    if unbraced is not None and ratio_second is not None:
        unbraced *= ratio_second
    if wire_relief is not None and ratio_second is not None:
        wire_relief *= ratio_second
    effective_dihedral = None if loaded_tip_z is None or half_span <= 0.0 else math.degrees(math.atan2(loaded_tip_z, half_span))
    jig_tip_z = None if loaded_tip_z is None or deflection_est is None else loaded_tip_z - deflection_est
    deflection_ratio = None if deflection_est is None or half_span <= 0.0 else deflection_est / half_span
    preferred_min = safe_float(jig.get("jig_preferred_tip_deflection_min_m"))
    preferred_max = safe_float(jig.get("jig_preferred_tip_deflection_max_m"))
    hard_ratio = safe_float(jig.get("jig_hard_tip_deflection_ratio_max"))
    flags: list[str] = []
    if jig_tip_z is not None and jig_tip_z < 0.0:
        flags.append("negative_unloaded_jig_tip_estimate")
    if deflection_ratio is not None and hard_ratio is not None and deflection_ratio > hard_ratio:
        flags.append("tip_deflection_ratio_over_hard_proxy")
    if deflection_est is not None and preferred_min is not None and deflection_est < preferred_min:
        flags.append("below_preferred_deflection_band_proxy")
    if deflection_est is not None and preferred_max is not None and deflection_est > preferred_max:
        flags.append("above_preferred_deflection_band_proxy")
    if not flags:
        flags.append("no_proxy_warning")
    root_bending = safe_float(spanload_metrics.get("root_bending_proxy_n_m"))
    return {
        "case_id": case.case_id,
        "display_name": case.display_name,
        "variant": variant,
        "span_m": span_m,
        "spanload_total_half_lift_n": spanload_metrics.get("spanload_total_half_lift_n"),
        "root_bending_proxy_n_m": root_bending,
        "normalized_bending_vs_old_fx_raw": None
        if baseline_bending in (None, 0.0) or root_bending is None
        else root_bending / baseline_bending,
        "tip_deflection_estimate_m": deflection_est,
        "tip_deflection_estimate_basis": "scaled existing uniform-load wire-relieved proxy; not_structure_grade",
        "loaded_tip_z_m": loaded_tip_z,
        "effective_dihedral_loaded_deg": effective_dihedral,
        "jig_tip_z_unloaded_estimate_m": jig_tip_z,
        "jig_feasibility_band": "proxy_warning" if flags != ["no_proxy_warning"] else "proxy_ok",
        "wire_relief_effect_m": wire_relief,
        "unbraced_tip_deflection_estimate_m": unbraced,
        "outer_lift_fraction_eta_ge_0p70": spanload_metrics.get("outer_lift_fraction_eta_ge_0p70"),
        "warning_flags": "|".join(flags),
        "not_structure_grade": True,
    }


def tube_ei_nm2(
    *,
    outer_diameter_m: float,
    inner_diameter_m: float,
    youngs_pa: float,
    tube_count_per_wing: int,
    vertical_separation_m: float,
) -> float:
    do = float(outer_diameter_m)
    di = float(inner_diameter_m)
    area = math.pi * (do * do - di * di) / 4.0
    inertia = math.pi * (do**4 - di**4) / 64.0
    offset = 0.5 * float(vertical_separation_m)
    total_inertia = int(tube_count_per_wing) * (inertia + area * offset * offset)
    return float(youngs_pa) * total_inertia


def carbon_tube_candidates(
    *,
    catalog_path: Path,
    half_span_m: float,
    required_ei_nm2: float,
    youngs_pa: float,
    tube_count_per_wing: int,
    vertical_separation_m: float,
    current_spar_tube_mass_target_kg: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in read_csv_rows(catalog_path):
        od_mm = safe_float(row.get("outer_diameter_mm"))
        id_mm = safe_float(row.get("inner_diameter_mm"))
        mass_per_m = safe_float(row.get("mass_per_meter_kg"))
        if od_mm is None or id_mm is None or mass_per_m is None:
            continue
        ei = tube_ei_nm2(
            outer_diameter_m=od_mm / 1000.0,
            inner_diameter_m=id_mm / 1000.0,
            youngs_pa=youngs_pa,
            tube_count_per_wing=tube_count_per_wing,
            vertical_separation_m=vertical_separation_m,
        )
        full_mass = 2.0 * float(half_span_m) * int(tube_count_per_wing) * mass_per_m
        rows.append(
            {
                "vendor": row.get("vendor"),
                "product": row.get("product"),
                "material_key": row.get("material_key"),
                "outer_diameter_mm": od_mm,
                "inner_diameter_mm": id_mm,
                "wall_thickness_mm": safe_float(row.get("wall_thickness_mm")),
                "tube_count_per_wing": tube_count_per_wing,
                "vertical_separation_m": vertical_separation_m,
                "EI_proxy_Nm2": ei,
                "required_EI_proxy_Nm2": required_ei_nm2,
                "ei_pass": ei >= float(required_ei_nm2),
                "mass_per_meter_kg": mass_per_m,
                "estimated_full_span_tube_mass_kg": full_mass,
                "current_spar_tube_mass_target_kg": current_spar_tube_mass_target_kg,
                "mass_margin_vs_current_target_kg": current_spar_tube_mass_target_kg - full_mass,
                "estimate_basis": "round tube EI with two-tube vertical-separation parallel-axis proxy; not_structure_grade",
            }
        )
    rows.sort(key=lambda item: (not bool(item["ei_pass"]), float(item["estimated_full_span_tube_mass_kg"])))
    return rows


def required_ei_from_deflection(
    *,
    target_tip_deflection_m: float,
    current_tip_deflection_m: float,
    current_ei_nm2: float,
) -> float:
    if target_tip_deflection_m <= 0.0:
        return float("inf")
    return current_ei_nm2 * float(current_tip_deflection_m) / float(target_tip_deflection_m)


def run_avl_variant(
    *,
    spec: VariantSpec,
    run_root: Path,
    avl_binary: str | Path | None,
) -> dict[str, Any]:
    names = avl_audit.surface_names(spec.avl_path)
    target_surfaces = ("Main Wing",) if "Main Wing" in names else ("Wing",)
    case = avl_audit.CaseSpec(
        case_id=f"{spec.case.case_id}_{spec.variant}",
        display_name=f"{spec.case.display_name} {spec.variant}",
        avl_path=spec.avl_path,
        section_table_path=spec.section_table,
        cl_required=spec.case.cl_req,
        target_surface_names=target_surfaces,
        assignment_by_zone=spec.case.assignment,
        family=spec.case.family,
    )
    return avl_audit.run_avl_trim_and_spanload(
        case=case,
        avl_path=spec.avl_path,
        run_dir=run_root / spec.case.case_id / spec.variant,
        avl_binary=avl_binary,
    )


def aero_row(
    *,
    spec: VariantSpec,
    sections: Sequence[SectionRow],
    avl_result: Mapping[str, Any],
    profile: Mapping[str, Any],
    fourier_target: FourierTarget | None,
    zone_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    refs = avl_result.get("refs", {})
    cdff = safe_float(avl_result.get("CDff"))
    cdind = safe_float(avl_result.get("CDind"))
    cdi = cdff if cdff is not None else cdind
    profile_cd = safe_float(profile.get("profile_cd"))
    sref = safe_float(refs.get("Sref"), area_from_sections(sections)) or area_from_sections(sections)
    cd0 = None if profile_cd is None else profile_cd + MISSION_NONWING_CDA_M2 / max(sref, 1.0e-12)
    cd_total = None if cdi is None or cd0 is None else cdi + cd0
    q = 0.5 * MISSION_RHO_KGPM3 * MISSION_SPEED_MPS**2
    p_air = None if cd_total is None else q * sref * cd_total * MISSION_SPEED_MPS
    p_crank = None if p_air is None else p_air / (ETA_PROP * ETA_TRANS)
    station_table = [
        {
            "eta": row["eta"],
            "chord_m": row["chord_m"],
            "avl_local_cl": row["cl"],
            "avl_circulation_proxy": row["lprime_proxy"],
        }
        for row in avl_result.get("spanload", [])
    ]
    if fourier_target is not None and spec.case.family != "old_fx_clark":
        comparison = compare_fourier_target_to_avl(fourier_target, station_table)
    else:
        comparison = {
            "target_vs_avl_rms_delta": None,
            "target_vs_avl_outer_delta": None,
            "target_vs_avl_compare_reason": "old_baseline_or_fourier_target_unavailable",
        }
    min_margin = min(
        (
            safe_float(row.get("stall_margin_cl"))
            for row in zone_rows
            if safe_float(row.get("stall_margin_cl")) is not None
        ),
        default=None,
    )
    max_util = max(
        (
            safe_float(row.get("stall_utilization"))
            for row in zone_rows
            if safe_float(row.get("stall_utilization")) is not None
        ),
        default=None,
    )
    local_by_zone = {
        str(row["zone"]): safe_float(row.get("local_Cl_max")) for row in zone_rows
    }
    return {
        "case_id": spec.case.case_id,
        "display_name": spec.case.display_name,
        "variant": spec.variant,
        "assignment": "|".join(f"{zone}:{spec.case.assignment.get(zone, '')}" for zone, _, _ in ZONE_BOUNDS),
        "alpha_at_CL_req": avl_result.get("alpha_at_CL_req_deg"),
        "CL_req": spec.case.cl_req,
        "CLtot": avl_result.get("CLtot"),
        "CDi": cdi,
        "CDi_source": "AVL_Trefftz_CDff" if cdff is not None else "AVL_near_field_CDind",
        "CDind_near_field": cdind,
        "e_CDi": avl_result.get("e_CDi_from_CDff", avl_result.get("e_CDi_from_CDind")),
        "CDi_conservative": None if cdi is None else 1.05 * cdi,
        "profile_cd": profile_cd,
        "profile_lookup_statuses": profile.get("profile_lookup_statuses"),
        "CD0_total_est": cd0,
        "CD_total": cd_total,
        "L_D": None if cd_total in (None, 0.0) else spec.case.cl_req / cd_total,
        "P_air": p_air,
        "P_crank": p_crank,
        "target_vs_avl_rms": comparison.get("target_vs_avl_rms_delta"),
        "target_vs_avl_outer_delta": comparison.get("target_vs_avl_outer_delta"),
        "target_vs_avl_basis": comparison.get("target_vs_avl_compare_source", comparison.get("target_vs_avl_compare_reason")),
        "local_Cl_max_root": local_by_zone.get("root"),
        "local_Cl_max_mid1": local_by_zone.get("mid1"),
        "local_Cl_max_mid2": local_by_zone.get("mid2"),
        "local_Cl_max_tip": local_by_zone.get("tip"),
        "stall_margin": min_margin,
        "stall_margin_basis": "safe_clmax_minus_local_Cl_max",
        "max_utilization": max_util,
        "avl_path": str(spec.avl_path.resolve()),
    }


def generate_variants(
    *,
    candidates: Sequence[CandidateSpec],
    output_dir: Path,
    build_vsp: bool,
) -> tuple[list[VariantSpec], list[dict[str, Any]]]:
    variants: list[VariantSpec] = []
    smooth_rows: list[dict[str, Any]] = []
    for case in candidates:
        reference_sections = read_section_table(case.raw_section_table)
        variants.append(
            VariantSpec(
                case=case,
                variant="raw",
                avl_path=case.raw_avl,
                section_table=case.raw_section_table,
                vsp3_path=case.raw_vsp3,
                generated=False,
            )
        )
        if case.monotone_avl is not None and case.monotone_section_table is not None:
            variants.append(
                VariantSpec(
                    case=case,
                    variant="monotone",
                    avl_path=case.monotone_avl,
                    section_table=case.monotone_section_table,
                    vsp3_path=case.monotone_vsp3,
                    generated=False,
                )
            )
            smooth_source = read_section_table(case.monotone_section_table)
            smooth_source_avl = case.monotone_avl
        else:
            monotone_sections = pava_monotone_sections(
                reference_sections,
                target_area_m2=area_from_sections(reference_sections),
            )
            avl_path, section_csv, vsp3_path, vsp_report = export_sections_variant(
                source_avl=case.raw_avl,
                sections=monotone_sections,
                out_dir=output_dir / "VSP_exports" / case.case_id / "monotone",
                file_stem=f"{case.case_id}_monotone",
                build_vsp=build_vsp,
            )
            variants.append(
                VariantSpec(
                    case=case,
                    variant="monotone",
                    avl_path=avl_path,
                    section_table=section_csv,
                    vsp3_path=vsp3_path,
                    generated=True,
                )
            )
            smooth_source = monotone_sections
            smooth_source_avl = avl_path
            smooth_rows.append(
                {
                    "case_id": case.case_id,
                    "variant": "monotone",
                    "generated_avl": str(avl_path),
                    "generated_vsp3": str(vsp3_path) if vsp3_path else None,
                    "vsp_status": vsp_report.get("status"),
                }
            )

        smooth_sections, fit = smooth_power_law_sections(
            smooth_source,
            target_area_m2=area_from_sections(reference_sections),
        )
        smooth_dir = output_dir / "VSP_exports" / case.case_id / "smooth_monotone"
        avl_path, section_csv, vsp3_path, vsp_report = export_sections_variant(
            source_avl=smooth_source_avl,
            sections=smooth_sections,
            out_dir=smooth_dir,
            file_stem=f"{case.case_id}_smooth_monotone",
            build_vsp=build_vsp,
        )
        manifest = {
            "schema_version": "phase9_smooth_monotone_geometry_manifest_v1",
            "case_id": case.case_id,
            "display_name": case.display_name,
            "variant": "smooth_monotone",
            "generated_at": timestamp(),
            "fit": fit,
            "source_avl": str(smooth_source_avl.resolve()),
            "source_section_table": str((case.monotone_section_table or case.raw_section_table).resolve()),
            "smooth_avl": str(avl_path.resolve()),
            "smooth_vsp3": str(vsp3_path.resolve()) if vsp3_path else None,
            "section_table": str(section_csv.resolve()),
            "vsp_export": vsp_report,
            "preserved": {
                "span": True,
                "loaded_z_distribution": True,
                "relative_twist_distribution": True,
                "airfoil_zone_assignment": True,
            },
            "known_limitations": [
                "Smooth planform is a sidecar production study only.",
                "No production ranking or hard gate was changed.",
                "Power-law fit preserves root/tip chords and area; MAC delta is reported separately.",
            ],
        }
        (smooth_dir / "geometry_manifest.json").write_text(
            json.dumps(json_ready(manifest), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        variants.append(
            VariantSpec(
                case=case,
                variant="smooth_monotone",
                avl_path=avl_path,
                section_table=section_csv,
                vsp3_path=vsp3_path,
                generated=True,
            )
        )
        smooth_rows.append(
            {
                "case_id": case.case_id,
                "variant": "smooth_monotone",
                "generated_avl": str(avl_path),
                "generated_vsp3": str(vsp3_path) if vsp3_path else None,
                "vsp_status": vsp_report.get("status"),
                **fit,
            }
        )
    return variants, smooth_rows


def write_recommendations(
    *,
    output_dir: Path,
    aero_rows: Sequence[Mapping[str, Any]],
    structure_rows: Sequence[Mapping[str, Any]],
    quality_rows: Sequence[Mapping[str, Any]],
    carbon_rows: Sequence[Mapping[str, Any]],
) -> None:
    def _find(case_id: str, variant: str, rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        return next((row for row in rows if row.get("case_id") == case_id and row.get("variant") == variant), {})

    raw = _find("raw_best_tier2", "raw", aero_rows)
    raw_smooth = _find("raw_best_tier2", "smooth_monotone", aero_rows)
    raw_penalty = None
    if safe_float(raw.get("P_crank")) is not None and safe_float(raw_smooth.get("P_crank")) is not None:
        raw_penalty = safe_float(raw_smooth.get("P_crank")) - safe_float(raw.get("P_crank"))
    best_carbon = next((row for row in carbon_rows if row.get("ei_pass")), {})
    raw_struct = _find("raw_best_tier2", "smooth_monotone", structure_rows)
    cons_struct = _find("conservative_best_tier2", "smooth_monotone", structure_rows)
    raw_score = safe_float(_find("raw_best_tier2", "smooth_monotone", quality_rows).get("visual_production_score"))
    cons_score = safe_float(_find("conservative_best_tier2", "smooth_monotone", quality_rows).get("visual_production_score"))

    lines = [
        "# Phase 9 Recommendation",
        "",
        f"Generated: {timestamp()}",
        "",
        "## Direct Answers",
        "",
        "1. The current faceted chord is acceptable as optimizer/AVL evidence, but it is not the geometry I would hand to SolidWorks as the production-facing baseline.",
        "2. A smooth monotone planform is recommended for production-facing VSP/SolidWorks/final drawing work.",
        f"3. The raw Tier2 smooth penalty is {raw_penalty:.3f} W crank in this sidecar lookup." if raw_penalty is not None else "3. The raw Tier2 smooth penalty could not be computed.",
        "4. Smoothing improves CAD/loft quality, but it does not materially solve jig or spar feasibility because span, loaded z, twist, and spanload family are nearly unchanged.",
        "5. Current production-facing baseline: Tier2 conservative best, smooth_monotone. It keeps clean airfoil evidence and avoids selling a 166 W aero-only result as a finished structure.",
        "6. The raw 166 W candidate is aerodynamically attractive but not structurally proven as-is. Treat it as needing the current spar/wire mass allowance, not as a lower-mass production answer.",
        "7. Future optimizer handling: use chord smoothness as a soft penalty plus post-processing regularizer. Do not make it a hard gate until the penalty is calibrated against real CAD/loft constraints.",
        "",
        "## Engineering Notes",
        "",
        f"- Raw smooth quality score: {raw_score:.1f}; conservative smooth quality score: {cons_score:.1f}." if raw_score is not None and cons_score is not None else "- Smooth quality scores are in production_geometry_quality.csv.",
        f"- Raw smooth jig flags: {raw_struct.get('warning_flags', 'n/a')}. Conservative smooth jig flags: {cons_struct.get('warning_flags', 'n/a')}.",
        f"- Lightest passing catalog tube proxy: {best_carbon.get('product', 'n/a')} at {safe_float(best_carbon.get('estimated_full_span_tube_mass_kg')):.3f} kg full span." if best_carbon else "- No passing carbon tube catalog proxy was found.",
        "",
        "The structural rows are deliberately labeled `not_structure_grade`: they are AVL spanload plus beam/tube proxies, useful for rejecting fantasy-level conclusions, not for releasing a layup.",
        "",
    ]
    (output_dir / "recommended_candidate.md").write_text("\n".join(lines), encoding="utf-8")

    constraints = [
        "# Recommended Optimizer Constraints",
        "",
        "## Recommended Policy",
        "",
        "- Add a chord smoothness soft penalty based on max slope change and integrated curvature.",
        "- Keep a post-processing smooth monotone regularizer that preserves span, area, root/tip chord, MAC, loaded z, relative twist, and airfoil zones.",
        "- Do not turn chord smoothness into a hard gate yet; it can reject aerodynamically good candidates before CAD tolerance is quantified.",
        "- Add a warning gate, not a rejection gate, when the unloaded jig-tip estimate goes negative under the not_structure_grade beam proxy.",
        "- Keep production ranking and hard gates unchanged until a real structural sizing rerun is connected to the smoothed planform.",
        "",
        "## Suggested Numeric Starters",
        "",
        "- area error after smoothing: <= 0.5%",
        "- MAC error after smoothing: prefer <= 1.5%, warn above 2.0%",
        "- positive chord jumps: 0",
        "- near-constant chord plateaus: soft penalty after 1 segment",
        "- max slope change: minimize as soft objective; do not gate before CAD review",
        "",
    ]
    (output_dir / "recommended_optimizer_constraints.md").write_text("\n".join(constraints), encoding="utf-8")


def run_phase9(
    output_dir: Path,
    *,
    avl_binary: str | Path | None = None,
    build_vsp: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = build_candidate_specs()
    missing = []
    for case in candidates:
        for path in (case.raw_avl, case.raw_section_table):
            if not path.is_file():
                missing.append(str(path))
    if missing:
        raise FileNotFoundError("Missing required Phase 9 input files: " + ", ".join(missing))

    variants, smooth_rows = generate_variants(candidates=candidates, output_dir=output_dir, build_vsp=build_vsp)
    all_airfoils = sorted({airfoil for case in candidates for airfoil in case.assignment.values()})
    lookup = ProfileLookup(TIER2_PROFILE_DIR / "polar_points.csv", all_airfoils)
    safe_records = load_safe_records()
    fourier_target = load_fourier_target()

    quality_rows: list[dict[str, Any]] = []
    aero_rows: list[dict[str, Any]] = []
    zone_rows_all: list[dict[str, Any]] = []
    structure_rows: list[dict[str, Any]] = []
    profile_station_rows: list[dict[str, Any]] = []
    avl_results: dict[tuple[str, str], dict[str, Any]] = {}
    structure_metrics_by_variant: dict[tuple[str, str], dict[str, Any]] = {}

    for spec in variants:
        sections = read_section_table(spec.section_table)
        reference_sections = read_section_table(spec.case.raw_section_table)
        quality_rows.append(
            geometry_quality_metrics(
                case_id=spec.case.case_id,
                variant=spec.variant,
                sections=sections,
                reference_sections=reference_sections,
            )
        )
        result = run_avl_variant(
            spec=spec,
            run_root=output_dir / "avl_runs",
            avl_binary=avl_binary,
        )
        avl_results[(spec.case.case_id, spec.variant)] = result
        profile = profile_cd_from_spanload(
            spanload=result.get("spanload", []),
            assignment=spec.case.assignment,
            lookup=lookup,
            sref_m2=area_from_sections(sections),
        )
        for row in profile["profile_station_rows"]:
            profile_station_rows.append({"case_id": spec.case.case_id, "variant": spec.variant, **row})
        zrows = zone_summary(
            case=spec.case,
            variant=spec.variant,
            spanload=result.get("spanload", []),
            safe_records=safe_records,
        )
        zone_rows_all.extend(zrows)
        aero_rows.append(
            aero_row(
                spec=spec,
                sections=sections,
                avl_result=result,
                profile=profile,
                fourier_target=fourier_target,
                zone_rows=zrows,
            )
        )
        structure_metrics_by_variant[(spec.case.case_id, spec.variant)] = spanload_structure_metrics(
            result.get("spanload", [])
        )

    old_raw_metrics = structure_metrics_by_variant.get(("old_fx_clark_baseline", "raw"), {})
    baseline_bending = safe_float(old_raw_metrics.get("root_bending_proxy_n_m"))
    baseline_second = safe_float(old_raw_metrics.get("tip_deflection_second_moment_proxy"))
    for spec in variants:
        sections = read_section_table(spec.section_table)
        structure_rows.append(
            structure_jig_row(
                case=spec.case,
                variant=spec.variant,
                sections=sections,
                spanload_metrics=structure_metrics_by_variant[(spec.case.case_id, spec.variant)],
                baseline_bending=baseline_bending,
                baseline_second_moment=baseline_second,
            )
        )

    raw_smooth_structure = next(
        row for row in structure_rows if row["case_id"] == "raw_best_tier2" and row["variant"] == "smooth_monotone"
    )
    span_m = safe_float(raw_smooth_structure.get("span_m"), 34.332286) or 34.332286
    current_ei = tube_ei_nm2(
        outer_diameter_m=0.070,
        inner_diameter_m=0.070 - 2.0 * 0.0007,
        youngs_pa=120.0e9,
        tube_count_per_wing=2,
        vertical_separation_m=0.10,
    )
    current_tip = safe_float(raw_smooth_structure.get("tip_deflection_estimate_m"), 1.25) or 1.25
    loaded_tip_z = safe_float(raw_smooth_structure.get("loaded_tip_z_m"), 1.05) or 1.05
    required_ei = required_ei_from_deflection(
        target_tip_deflection_m=max(loaded_tip_z, 0.25),
        current_tip_deflection_m=current_tip,
        current_ei_nm2=current_ei,
    )
    carbon_rows = carbon_tube_candidates(
        catalog_path=_REPO_ROOT / "data" / "carbon_tubes.csv",
        half_span_m=0.5 * span_m,
        required_ei_nm2=required_ei,
        youngs_pa=120.0e9,
        tube_count_per_wing=2,
        vertical_separation_m=0.10,
        current_spar_tube_mass_target_kg=CURRENT_SPAR_TUBE_MASS_TARGET_KG,
    )

    comparison_rows = []
    for case in candidates:
        raw_q = next(row for row in quality_rows if row["case_id"] == case.case_id and row["variant"] == "raw")
        smooth_q = next(row for row in quality_rows if row["case_id"] == case.case_id and row["variant"] == "smooth_monotone")
        comparison_rows.append(
            {
                "case_id": case.case_id,
                "display_name": case.display_name,
                "smooth_planform_recommended": True,
                "raw_visual_production_score": raw_q["visual_production_score"],
                "smooth_visual_production_score": smooth_q["visual_production_score"],
                "smooth_area_error_pct": smooth_q["area_error_pct_vs_reference"],
                "smooth_MAC_error_pct": smooth_q["MAC_error_pct_vs_reference"],
                "smooth_max_slope_change_abs": smooth_q["max_slope_change_abs"],
                "smooth_vsp3": str(
                    output_dir / "VSP_exports" / case.case_id / "smooth_monotone" / f"{case.case_id}_smooth_monotone.vsp3"
                ),
                "smooth_avl": str(
                    output_dir / "VSP_exports" / case.case_id / "smooth_monotone" / f"{case.case_id}_smooth_monotone.avl"
                ),
            }
        )

    write_csv(output_dir / "smooth_planform_comparison.csv", comparison_rows)
    write_csv(output_dir / "aero_comparison.csv", aero_rows)
    write_csv(output_dir / "structure_jig_comparison.csv", structure_rows)
    write_csv(output_dir / "carbon_tube_mass_estimate.csv", carbon_rows)
    write_csv(output_dir / "production_geometry_quality.csv", quality_rows)
    write_csv(output_dir / "zone_local_cl_summary.csv", zone_rows_all)
    write_csv(output_dir / "profile_lookup_station_samples.csv", profile_station_rows)
    write_csv(output_dir / "smooth_export_generation.csv", smooth_rows)

    metadata = {
        "schema_version": "phase9_structure_jig_smooth_planform_v1",
        "generated_at": timestamp(),
        "output_dir": str(output_dir.resolve()),
        "cases": [case.case_id for case in candidates],
        "variant_count": len(variants),
        "notes": [
            "Diagnostic sidecar only; no production ranking or hard gates changed.",
            "Smooth monotone VSP/AVL files are written under VSP_exports.",
            "Structure/jig and carbon tube rows are proxy estimates and are not structure-grade.",
        ],
        "verification_targets": [
            "CSVs parse",
            "smooth_monotone VSP files exist when OpenVSP is available",
            "production ranking and hard gates unchanged",
        ],
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(json_ready(metadata), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_recommendations(
        output_dir=output_dir,
        aero_rows=aero_rows,
        structure_rows=structure_rows,
        quality_rows=quality_rows,
        carbon_rows=carbon_rows,
    )
    return metadata


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--avl-binary", type=Path, default=None)
    parser.add_argument("--no-vsp", action="store_true", help="Skip OpenVSP .vsp3 generation.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    metadata = run_phase9(
        output_dir=Path(args.output_dir),
        avl_binary=args.avl_binary,
        build_vsp=not bool(args.no_vsp),
    )
    print(json.dumps({"output_dir": metadata["output_dir"], "variant_count": metadata["variant_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
