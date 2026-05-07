#!/usr/bin/env python3
"""Re-optimize Tier2 zone airfoil combos on Phase 9 smooth-monotone geometry.

This is a diagnostic sidecar. It reads Phase 9 smooth-monotone AVL/VSP exports
and the existing Tier2 full-alpha database, then writes only under
``output/phase9_smooth_geometry_combo_reoptimization``.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import itertools
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

from hpa_mdo.aero.fourier_target import compare_fourier_target_to_avl  # noqa: E402
from hpa_mdo.airfoils.database import (  # noqa: E402
    AirfoilDatabase,
    AirfoilQuery,
    ZoneAirfoilAssignment,
    airfoil_coordinate_path_from_record,
    integrate_profile_drag_from_avl,
)
from hpa_mdo.airfoils.polar_builder import load_airfoil_database_artifact  # noqa: E402

from scripts import audit_avl_induced_drag_credibility as avl_audit  # noqa: E402
from scripts import export_phase7_sidecar_vsp as vsp_exporter  # noqa: E402
from scripts import phase9_structure_jig_smooth_planform as phase9  # noqa: E402


DEFAULT_OUTPUT_DIR = _REPO_ROOT / "output" / "phase9_smooth_geometry_combo_reoptimization"
PHASE9_OUTPUT_DIR = _REPO_ROOT / "output" / "phase9_structure_jig_smooth_planform"
TIER2_DIR = _REPO_ROOT / "output" / "airfoil_db" / "full_alpha_reusable_v1_tier2"
TIER2_CURRENT_MISSION_DIR = (
    _REPO_ROOT / "output" / "airfoil_db" / "full_alpha_reusable_v1_tier2_current_mission"
)
FINAL_VALIDATION_DIR = (
    _REPO_ROOT / "output" / "final_candidate_validation" / "tier2_raw_vs_conservative"
)

MISSION_CL_REQ = phase9.MISSION_CL_REQ
MISSION_SPEED_MPS = phase9.MISSION_SPEED_MPS
MISSION_RHO_KGPM3 = phase9.MISSION_RHO_KGPM3
MISSION_DYNAMIC_VISCOSITY_PA_S = phase9.MISSION_DYNAMIC_VISCOSITY_PA_S
MISSION_NONWING_CDA_M2 = phase9.MISSION_NONWING_CDA_M2
ETA_PROP = phase9.ETA_PROP
ETA_TRANS = phase9.ETA_TRANS

ZONE_BOUNDS: tuple[tuple[str, float, float], ...] = (
    ("root", 0.0, 0.25),
    ("mid1", 0.25, 0.55),
    ("mid2", 0.55, 0.80),
    ("tip", 0.80, 1.000001),
)
SEED_REFERENCE_IDS = {"fx76mp140", "clarkysm", "dae11", "dae21", "dae31", "dae41"}
PRIMARY_CASE_IDS = ("raw_best_tier2", "conservative_best_tier2")
OPTIONAL_CASE_IDS = ("policy_A_performance_candidate", "policy_C_conservative_baseline")


@dataclass(frozen=True)
class SmoothCase:
    case_id: str
    display_name: str
    assignment: dict[str, str]
    avl_path: Path
    section_table: Path
    vsp3_path: Path | None
    cl_req: float = MISSION_CL_REQ


@dataclass(frozen=True)
class MissionContract:
    speed_mps: float
    rho: float
    dynamic_viscosity_pa_s: float
    wing_area_m2: float
    span_m: float
    CDA_nonwing_target_m2: float
    CD_wing_profile_target: float = 0.0120
    CD_wing_profile_boundary: float = 0.0140
    CD0_total_target: float = 0.0160
    CD0_total_boundary: float = 0.0180
    CD0_total_rescue: float = 0.0240


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def safe_float(value: Any, default: float | None = None) -> float | None:
    return phase9.safe_float(value, default)


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    return phase9.read_csv_rows(path)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(json_ready(dict(row)))


def json_ready(value: Any) -> Any:
    return phase9.json_ready(value)


def percentile(values: Sequence[float], pct: float) -> float | None:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = (len(clean) - 1) * float(pct) / 100.0
    lo = int(math.floor(position))
    hi = int(math.ceil(position))
    if lo == hi:
        return clean[lo]
    frac = position - lo
    return clean[lo] + frac * (clean[hi] - clean[lo])


def mean(values: Sequence[float]) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    return None if not clean else sum(clean) / len(clean)


def parse_assignment(text: str) -> dict[str, str]:
    return phase9.parse_assignment(text)


def assignment_label(assignment: Mapping[str, str]) -> str:
    return "|".join(f"{zone}:{assignment.get(zone, '')}" for zone, _, _ in ZONE_BOUNDS)


def zone_for_eta(eta: float) -> str:
    return phase9.zone_for_eta(eta)


def zone_assignments(assignment: Mapping[str, str]) -> tuple[ZoneAirfoilAssignment, ...]:
    return tuple(
        ZoneAirfoilAssignment(zone, str(assignment.get(zone, "")), lo, min(hi, 1.0))
        for zone, lo, hi in ZONE_BOUNDS
    )


def load_record_metadata(tier2_dir: Path = TIER2_DIR) -> dict[str, dict[str, str]]:
    rows = read_csv_rows(tier2_dir / "airfoil_records.csv")
    return {str(row["airfoil_id"]): row for row in rows if row.get("airfoil_id")}


def load_previous_assignments() -> dict[str, dict[str, str]]:
    assignments: dict[str, dict[str, str]] = {}
    for row in read_csv_rows(FINAL_VALIDATION_DIR / "raw_vs_conservative_power.csv"):
        case_id = str(row.get("case_id") or "")
        if case_id and row.get("assignment"):
            assignments[case_id] = parse_assignment(str(row["assignment"]))
    for row in read_csv_rows(TIER2_CURRENT_MISSION_DIR / "policy_comparison_tier2.csv"):
        policy_id = str(row.get("policy_id") or "")
        if policy_id and row.get("assignment"):
            assignments[f"policy_{policy_id}"] = parse_assignment(str(row["assignment"]))
    assignments["old_fx_clark_baseline"] = {
        "root": "fx76mp140",
        "mid1": "fx76mp140",
        "mid2": "clarkysm",
        "tip": "clarkysm",
    }
    return assignments


def load_smooth_cases(
    *,
    phase9_output_dir: Path = PHASE9_OUTPUT_DIR,
    include_policy_ac: bool = True,
) -> list[SmoothCase]:
    specs = {case.case_id: case for case in phase9.build_candidate_specs()}
    selected = list(PRIMARY_CASE_IDS)
    if include_policy_ac:
        selected.extend(OPTIONAL_CASE_IDS)
    cases: list[SmoothCase] = []
    for case_id in selected:
        spec = specs[case_id]
        smooth_dir = phase9_output_dir / "VSP_exports" / case_id / "smooth_monotone"
        cases.append(
            SmoothCase(
                case_id=case_id,
                display_name=spec.display_name,
                assignment=dict(spec.assignment),
                avl_path=smooth_dir / f"{case_id}_smooth_monotone.avl",
                section_table=smooth_dir / "section_table.csv",
                vsp3_path=smooth_dir / f"{case_id}_smooth_monotone.vsp3",
                cl_req=spec.cl_req,
            )
        )
    return cases


def run_base_avl(
    *,
    case: SmoothCase,
    output_dir: Path,
    avl_binary: str | Path | None,
) -> dict[str, Any]:
    names = avl_audit.surface_names(case.avl_path)
    target_surfaces = ("Main Wing",) if "Main Wing" in names else ("Wing",)
    spec = avl_audit.CaseSpec(
        case_id=f"{case.case_id}_smooth_base",
        display_name=f"{case.display_name} smooth base",
        avl_path=case.avl_path,
        section_table_path=case.section_table,
        cl_required=case.cl_req,
        target_surface_names=target_surfaces,
        assignment_by_zone=case.assignment,
        family=case.case_id,
    )
    return avl_audit.run_avl_trim_and_spanload(
        case=spec,
        avl_path=case.avl_path,
        run_dir=output_dir / "avl_runs" / case.case_id / "base",
        avl_binary=avl_binary,
    )


def mission_contract_for_sections(sections: Sequence[phase9.SectionRow]) -> MissionContract:
    return MissionContract(
        speed_mps=MISSION_SPEED_MPS,
        rho=MISSION_RHO_KGPM3,
        dynamic_viscosity_pa_s=MISSION_DYNAMIC_VISCOSITY_PA_S,
        wing_area_m2=phase9.area_from_sections(sections),
        span_m=2.0 * max((row.y_m for row in sections), default=0.0),
        CDA_nonwing_target_m2=MISSION_NONWING_CDA_M2,
    )


def spanload_with_avl_cl(spanload: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in spanload:
        copied = dict(row)
        if "avl_local_cl" not in copied and "cl" in copied:
            copied["avl_local_cl"] = copied["cl"]
        if "cl_actual_avl" not in copied and "cl" in copied:
            copied["cl_actual_avl"] = copied["cl"]
        rows.append(copied)
    return rows


def build_zone_envelope_rows(
    *,
    case: SmoothCase,
    sections: Sequence[phase9.SectionRow],
    spanload: Sequence[Mapping[str, Any]],
    records_metadata: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    q = 0.5 * MISSION_RHO_KGPM3 * MISSION_SPEED_MPS**2
    del q
    rows: list[dict[str, Any]] = []
    for zone, lo, hi in ZONE_BOUNDS:
        subset = [row for row in spanload if lo <= float(row.get("eta", 0.0)) < hi]
        if zone == "tip":
            subset = [row for row in spanload if lo <= float(row.get("eta", 0.0)) <= hi]
        re_values = []
        cl_values = []
        for row in subset:
            chord = safe_float(row.get("chord_m"))
            cl = safe_float(row.get("cl"), safe_float(row.get("avl_local_cl")))
            if chord is None or cl is None:
                continue
            re_values.append(MISSION_RHO_KGPM3 * MISSION_SPEED_MPS * chord / MISSION_DYNAMIC_VISCOSITY_PA_S)
            cl_values.append(cl)
        current_airfoil = str(case.assignment.get(zone, ""))
        meta = records_metadata.get(current_airfoil, {})
        rows.append(
            {
                "case_id": case.case_id,
                "display_name": case.display_name,
                "zone_name": zone,
                "eta_min": lo,
                "eta_max": min(hi, 1.0),
                "Re_min": min(re_values) if re_values else None,
                "Re_p50": percentile(re_values, 50.0),
                "Re_max": max(re_values) if re_values else None,
                "Cl_min": min(cl_values) if cl_values else None,
                "Cl_p50": percentile(cl_values, 50.0),
                "Cl_p90": percentile(cl_values, 90.0),
                "Cl_max": max(cl_values) if cl_values else None,
                "current_baseline_airfoil": current_airfoil,
                "current_actual_query_quality": meta.get("actual_sidecar_query_quality", ""),
                "current_archive_source_quality": meta.get("source_quality", ""),
                "station_count": len(subset),
                "envelope_source": "phase9_smooth_monotone_avl_actual_cl",
                "section_table": str(case.section_table),
                "smooth_avl": str(case.avl_path),
                "smooth_vsp3": None if case.vsp3_path is None else str(case.vsp3_path),
            }
        )
    return rows


def zone_area_weights(sections: Sequence[phase9.SectionRow]) -> dict[str, float]:
    weights = {zone: 0.0 for zone, _, _ in ZONE_BOUNDS}
    total = 0.0
    for left, right in zip(sections[:-1], sections[1:]):
        dy = max(float(right.y_m) - float(left.y_m), 0.0)
        area = 0.5 * dy * (float(left.chord_m) + float(right.chord_m))
        eta_mid = 0.5 * (float(left.eta) + float(right.eta))
        zone = zone_for_eta(eta_mid)
        weights[zone] = weights.get(zone, 0.0) + area
        total += area
    if total <= 0.0:
        return {zone: 0.25 for zone, _, _ in ZONE_BOUNDS}
    return {zone: value / total for zone, value in weights.items()}


def work_points_for_envelope(envelope: Mapping[str, Any]) -> tuple[tuple[float, float, float], ...]:
    re_mid = safe_float(envelope.get("Re_p50"))
    cl_mid = safe_float(envelope.get("Cl_p50"))
    if re_mid is None or cl_mid is None:
        return tuple()
    re_min = safe_float(envelope.get("Re_min"), re_mid) or re_mid
    re_max = safe_float(envelope.get("Re_max"), re_mid) or re_mid
    cl_min = safe_float(envelope.get("Cl_min"), cl_mid) or cl_mid
    cl_p90 = safe_float(envelope.get("Cl_p90"), safe_float(envelope.get("Cl_max"), cl_mid)) or cl_mid
    cl_max = safe_float(envelope.get("Cl_max"), cl_p90) or cl_p90
    return (
        (re_mid, cl_mid, 1.0),
        (re_mid, cl_p90, 1.4),
        (re_min, cl_max, 1.2),
        (re_max, cl_min, 0.5),
    )


def record_matches_zone(record: Any, zone_name: str) -> bool:
    airfoil_id = str(getattr(record, "airfoil_id", ""))
    if airfoil_id in SEED_REFERENCE_IDS:
        return True
    is_generated_cst = airfoil_id.startswith("cst_") or "cst_" in str(getattr(record, "source", ""))
    if not is_generated_cst:
        return True
    zone_hint = str(getattr(record, "zone_hint", "")).strip()
    if not zone_hint:
        return True
    hints = {item.strip() for item in zone_hint.replace(",", "|").split("|") if item.strip()}
    return str(zone_name) in hints


def score_airfoil_for_zone(
    *,
    case_id: str,
    envelope: Mapping[str, Any],
    zone_area_weight: float,
    airfoil_id: str,
    database: AirfoilDatabase,
    records_metadata: Mapping[str, Mapping[str, str]],
) -> dict[str, Any] | None:
    record = database.records.get(str(airfoil_id))
    if record is None:
        return None
    work_points = work_points_for_envelope(envelope)
    if not work_points:
        return None
    cd_values: list[float] = []
    cm_values: list[float] = []
    stall_margins: list[float] = []
    clmax_margins: list[float] = []
    warnings: list[str] = []
    weighted_cd_sum = 0.0
    weight_sum = 0.0
    for re_value, cl_value, weight in work_points:
        result = database.lookup(
            AirfoilQuery(
                airfoil_id=str(airfoil_id),
                Re=float(re_value),
                cl=float(cl_value),
                allow_extrapolation=False,
            )
        )
        cd_values.append(float(result.cd))
        cm_values.append(float(result.cm))
        stall_margins.append(float(result.stall_margin_deg))
        clmax_margins.append(float(result.clmax_margin))
        warnings.extend(str(warning) for warning in result.warnings)
        weighted_cd_sum += float(weight) * float(result.cd)
        weight_sum += float(weight)
    mean_cd = weighted_cd_sum / max(weight_sum, 1.0e-12)
    cd_p90 = percentile(cd_values, 90.0)
    cm_mean = mean(cm_values) or 0.0
    min_stall = min(stall_margins) if stall_margins else None
    min_clmax = min(clmax_margins) if clmax_margins else None
    warning_flags = sorted(set(warnings))
    warning_count = len(warning_flags)
    meta = records_metadata.get(str(airfoil_id), {})
    source_quality = str(meta.get("source_quality") or record.source_quality)
    archive_source_quality = str(meta.get("archive_source_quality") or source_quality)
    actual_quality = str(meta.get("actual_sidecar_query_quality") or "")
    balanced = (
        float(mean_cd)
        + 0.35 * max(0.0, float(cd_p90 or mean_cd) - float(mean_cd))
        + 0.006 * abs(float(cm_mean))
        + 0.0015 * warning_count
        + 0.0005 * max(0.0, 3.0 - float(min_stall or 0.0))
        + 0.0100 * max(0.0, -float(min_clmax or 0.0))
    )
    if "mission_grade" not in source_quality or "not_mission_grade" in source_quality:
        balanced += 0.010
    if min_clmax is not None and min_clmax < 0.0:
        balanced += 1.0
    archive_pass = (
        source_quality == "full_polar_mission_grade_candidate"
        and min_clmax is not None
        and min_clmax >= 0.0
        and warning_count == 0
    )
    actual_query_pass = (
        actual_quality == "actual_sidecar_query_grade"
        and min_clmax is not None
        and min_clmax >= 0.0
        and warning_count == 0
    )
    fail_reasons: list[str] = []
    if min_clmax is not None and min_clmax < 0.0:
        fail_reasons.append("insufficient_safe_clmax_margin")
    fail_reasons.extend(warning_flags)
    return {
        "case_id": case_id,
        "zone_name": str(envelope["zone_name"]),
        "airfoil_id": str(airfoil_id),
        "balanced_score": balanced,
        "mean_cd": mean_cd,
        "cd_p90": cd_p90,
        "min_stall_margin_deg": min_stall,
        "safe_clmax_margin": min_clmax,
        "safe_clmax": float(record.safe_clmax),
        "usable_clmax": float(record.usable_clmax),
        "cm_mean": cm_mean,
        "actual_sidecar_query_quality": actual_quality,
        "actual_query_pass": actual_query_pass,
        "actual_query_fail_reasons": "|".join(sorted(set(fail_reasons))),
        "archive_source_quality": archive_source_quality,
        "archive_pass": archive_pass,
        "record_full_alpha_quality": source_quality,
        "screening_quality": meta.get("screening_quality", ""),
        "repair_worthy_flag": meta.get("repair_worthy_flag", ""),
        "inclusion_reason_manifest": meta.get("inclusion_reason", ""),
        "warning_count": warning_count,
        "warning_flags": "|".join(warning_flags),
        "work_point_count": len(work_points),
        "Re_min": envelope.get("Re_min"),
        "Re_p50": envelope.get("Re_p50"),
        "Re_max": envelope.get("Re_max"),
        "Cl_min": envelope.get("Cl_min"),
        "Cl_p50": envelope.get("Cl_p50"),
        "Cl_p90": envelope.get("Cl_p90"),
        "Cl_max": envelope.get("Cl_max"),
        "zone_area_weight": zone_area_weight,
        "pool_reasons": "",
    }


def select_zone_pool_candidates(
    *,
    zone_name: str,
    scored_candidates: Sequence[Mapping[str, Any]],
    seed_reference_ids: Iterable[str],
    previous_assignment_ids: Iterable[str],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}

    def add(row: Mapping[str, Any], reason: str) -> None:
        airfoil_id = str(row.get("airfoil_id") or "")
        if not airfoil_id:
            return
        out = by_id.setdefault(airfoil_id, dict(row))
        reasons = {item for item in str(out.get("pool_reasons") or "").split(";") if item}
        reasons.add(reason)
        out["pool_reasons"] = ";".join(sorted(reasons))
        out.setdefault("zone_name", zone_name)

    ranked_balanced = sorted(scored_candidates, key=lambda row: (safe_float(row.get("balanced_score"), float("inf")), str(row.get("airfoil_id", ""))))
    ranked_mean = sorted(scored_candidates, key=lambda row: (safe_float(row.get("mean_cd"), float("inf")), str(row.get("airfoil_id", ""))))
    ranked_p90 = sorted(scored_candidates, key=lambda row: (safe_float(row.get("cd_p90"), float("inf")), str(row.get("airfoil_id", ""))))
    ranked_actual = [row for row in ranked_balanced if bool(row.get("actual_query_pass"))]
    ranked_archive = [row for row in ranked_balanced if bool(row.get("archive_pass"))]
    for row in ranked_balanced[:10]:
        add(row, "top10_balanced_score")
    for row in ranked_mean[:5]:
        add(row, "top5_mean_cd")
    for row in ranked_p90[:5]:
        add(row, "top5_cd_p90")
    for row in ranked_actual[:5]:
        add(row, "top5_actual_query_pass")
    for row in ranked_archive[:5]:
        add(row, "top5_archive_pass")
    for airfoil_id in sorted({str(value) for value in seed_reference_ids if str(value)}):
        if airfoil_id in records_by_id:
            add(records_by_id[airfoil_id], "seed_dae_clarky_fx_reference")
    for airfoil_id in sorted({str(value) for value in previous_assignment_ids if str(value)}):
        if airfoil_id in records_by_id:
            add(records_by_id[airfoil_id], "previous_raw_or_conservative_best_airfoil")
    return sorted(
        by_id.values(),
        key=lambda row: (
            safe_float(row.get("balanced_score"), float("inf")),
            safe_float(row.get("mean_cd"), float("inf")),
            str(row.get("airfoil_id", "")),
        ),
    )


def build_candidate_pools(
    *,
    case: SmoothCase,
    envelopes: Sequence[Mapping[str, Any]],
    sections: Sequence[phase9.SectionRow],
    database: AirfoilDatabase,
    records_metadata: Mapping[str, Mapping[str, str]],
    previous_assignments: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    area_weights = zone_area_weights(sections)
    previous_ids = {
        airfoil_id
        for key in ("raw_best", "conservative_best")
        for airfoil_id in previous_assignments.get(key, {}).values()
    }
    pool_rows: list[dict[str, Any]] = []
    for envelope in envelopes:
        zone = str(envelope["zone_name"])
        scored: list[dict[str, Any]] = []
        force_ids = set(SEED_REFERENCE_IDS) | previous_ids | set(case.assignment.values())
        for airfoil_id, record in database.records.items():
            if not record_matches_zone(record, zone) and airfoil_id not in force_ids:
                continue
            scored_row = score_airfoil_for_zone(
                case_id=case.case_id,
                envelope=envelope,
                zone_area_weight=area_weights.get(zone, 0.25),
                airfoil_id=airfoil_id,
                database=database,
                records_metadata=records_metadata,
            )
            if scored_row is not None:
                scored.append(scored_row)
        records_by_id = {row["airfoil_id"]: row for row in scored}
        selected = select_zone_pool_candidates(
            zone_name=zone,
            scored_candidates=scored,
            seed_reference_ids=SEED_REFERENCE_IDS,
            previous_assignment_ids=previous_ids,
            records_by_id=records_by_id,
        )
        pool_rows.extend(selected)
    return pool_rows


def predicted_combo_rows(
    *,
    case: SmoothCase,
    pool_rows: Sequence[Mapping[str, Any]],
    previous_assignments: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    by_zone: dict[str, list[Mapping[str, Any]]] = {zone: [] for zone, _, _ in ZONE_BOUNDS}
    for row in pool_rows:
        if row.get("case_id") == case.case_id:
            by_zone.setdefault(str(row["zone_name"]), []).append(row)
    rows: list[dict[str, Any]] = []
    for root, mid1, mid2, tip in itertools.product(
        by_zone.get("root", []),
        by_zone.get("mid1", []),
        by_zone.get("mid2", []),
        by_zone.get("tip", []),
    ):
        zone_items = {"root": root, "mid1": mid1, "mid2": mid2, "tip": tip}
        assignment = {zone: str(item["airfoil_id"]) for zone, item in zone_items.items()}
        weights = {zone: safe_float(item.get("zone_area_weight"), 0.25) or 0.25 for zone, item in zone_items.items()}
        total_weight = sum(weights.values()) or 1.0
        profile_proxy = sum((weights[zone] / total_weight) * (safe_float(item.get("mean_cd"), 99.0) or 99.0) for zone, item in zone_items.items())
        balanced_proxy = sum((weights[zone] / total_weight) * (safe_float(item.get("balanced_score"), 99.0) or 99.0) for zone, item in zone_items.items())
        p90_proxy = sum((weights[zone] / total_weight) * (safe_float(item.get("cd_p90"), 99.0) or 99.0) for zone, item in zone_items.items())
        tags: list[str] = []
        label = assignment_label(assignment)
        for key, previous in previous_assignments.items():
            if label == assignment_label(previous):
                tags.append(key)
        ids = set(assignment.values())
        rows.append(
            {
                "case_id": case.case_id,
                "assignment": label,
                "root_airfoil": assignment["root"],
                "mid1_airfoil": assignment["mid1"],
                "mid2_airfoil": assignment["mid2"],
                "tip_airfoil": assignment["tip"],
                "predicted_balanced_score": balanced_proxy,
                "predicted_profile_cd_proxy": profile_proxy,
                "predicted_cd_p90_proxy": p90_proxy,
                "predicted_min_stall_margin_deg": min(safe_float(item.get("min_stall_margin_deg"), -999.0) or -999.0 for item in zone_items.values()),
                "predicted_min_safe_clmax_margin": min(safe_float(item.get("safe_clmax_margin"), -999.0) or -999.0 for item in zone_items.values()),
                "predicted_actual_query_pass": all(bool(item.get("actual_query_pass")) for item in zone_items.values()),
                "predicted_archive_pass": all(bool(item.get("archive_pass")) for item in zone_items.values()),
                "has_seed_reference": any(airfoil_id in SEED_REFERENCE_IDS for airfoil_id in ids),
                "is_cst_only": all(airfoil_id.startswith("cst_") for airfoil_id in ids),
                "no_ClarkY": "clarkysm" not in ids,
                "no_DAE": not any(airfoil_id.startswith("dae") for airfoil_id in ids),
                "known_policy_tags": ";".join(tags),
            }
        )
    return rows


def shortlist_combinations(
    predicted_rows: Sequence[Mapping[str, Any]],
    *,
    max_count: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    limit = max(0, int(max_count))

    def add(rows: Iterable[Mapping[str, Any]], reason: str, *, force: bool = False) -> None:
        for row in rows:
            if len(selected) >= limit and not force:
                return
            assignment = str(row.get("assignment") or "")
            if not assignment or assignment in seen:
                continue
            out = dict(row)
            reasons = {item for item in str(out.get("selection_reasons") or "").split(";") if item}
            reasons.add(reason)
            out["selection_reasons"] = ";".join(sorted(reasons))
            selected.append(out)
            seen.add(assignment)

    ranked_profile = sorted(predicted_rows, key=lambda row: (safe_float(row.get("predicted_profile_cd_proxy"), float("inf")), safe_float(row.get("predicted_balanced_score"), float("inf")), str(row.get("assignment", ""))))
    ranked_balanced = sorted(predicted_rows, key=lambda row: (safe_float(row.get("predicted_balanced_score"), float("inf")), safe_float(row.get("predicted_profile_cd_proxy"), float("inf")), str(row.get("assignment", ""))))
    known = [row for row in predicted_rows if str(row.get("known_policy_tags") or "")]
    actual = [row for row in ranked_profile if bool(row.get("predicted_actual_query_pass"))]
    archive = [row for row in ranked_profile if bool(row.get("predicted_archive_pass"))]
    cst_only = [row for row in ranked_profile if bool(row.get("is_cst_only"))]
    no_seed = [row for row in ranked_profile if not bool(row.get("has_seed_reference"))]
    add(ranked_profile[: max(limit, 1)], "top_predicted_profile_proxy")
    add(ranked_balanced[: max(20, limit // 2)], "top_predicted_balanced_score")
    add(actual[: max(20, limit // 3)], "top_actual_query_pass")
    add(archive[: max(20, limit // 3)], "top_archive_pass")
    add(cst_only[: max(10, limit // 5)], "top_cst_only")
    add(no_seed[: max(10, limit // 5)], "top_no_seed_reference")
    add(known, "known_policy_or_baseline", force=True)
    if len(selected) > limit:
        known_assignments = {str(row.get("assignment")) for row in known}
        keep_known = [row for row in selected if str(row.get("assignment")) in known_assignments]
        others = [row for row in selected if str(row.get("assignment")) not in known_assignments]
        others = sorted(
            others,
            key=lambda row: (
                safe_float(row.get("predicted_profile_cd_proxy"), float("inf")),
                safe_float(row.get("predicted_balanced_score"), float("inf")),
                str(row.get("assignment", "")),
            ),
        )
        selected = others[: max(0, limit - len(keep_known))] + keep_known
    return sorted(
        selected[:limit],
        key=lambda row: (
            safe_float(row.get("predicted_profile_cd_proxy"), float("inf")),
            safe_float(row.get("predicted_balanced_score"), float("inf")),
            str(row.get("assignment", "")),
        ),
    )


def dat_path_for_airfoil(database: AirfoilDatabase, airfoil_id: str) -> Path:
    record = database.records[str(airfoil_id)]
    path = airfoil_coordinate_path_from_record(record, repo_root=_REPO_ROOT)
    if path is None:
        raise FileNotFoundError(f"No coordinate path for airfoil {airfoil_id}")
    return path


def write_combo_avl(
    *,
    source_avl: Path,
    source_sections: Sequence[phase9.SectionRow],
    assignment: Mapping[str, str],
    database: AirfoilDatabase,
    output_path: Path,
) -> Path:
    sections = []
    for row in source_sections:
        zone = zone_for_eta(float(row.eta))
        airfoil_id = str(assignment[zone])
        record = database.records[airfoil_id]
        sections.append(
            replace(
                row,
                airfoil_id=airfoil_id,
                airfoil_dat_path=str(dat_path_for_airfoil(database, airfoil_id)),
                airfoil_source_quality=str(record.source_quality),
            )
        )
    exported = tuple(phase9.section_to_exported(row) for row in sections)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return vsp_exporter.write_avl(
        phase9._geometry_for_smoothed_avl(source_avl, sections),
        exported,
        output_path,
    )


def quality_summary(
    assignment: Mapping[str, str],
    records_metadata: Mapping[str, Mapping[str, str]],
    *,
    field: str,
) -> str:
    parts = []
    for zone, _, _ in ZONE_BOUNDS:
        airfoil_id = str(assignment.get(zone, ""))
        parts.append(f"{zone}:{records_metadata.get(airfoil_id, {}).get(field, '')}")
    return ";".join(parts)


def actual_query_fail_summary(
    assignment: Mapping[str, str],
    profile_rows: Sequence[Mapping[str, Any]],
) -> str:
    failures: dict[str, set[str]] = {zone: set() for zone, _, _ in ZONE_BOUNDS}
    for row in profile_rows:
        zone = zone_for_eta(float(row.get("eta", 0.0)))
        for warning in row.get("warning_flags", []) or []:
            failures.setdefault(zone, set()).add(str(warning))
        margin = safe_float(row.get("clmax_margin"))
        if margin is not None and margin < 0.0:
            failures.setdefault(zone, set()).add("insufficient_safe_clmax_margin")
    return "|".join(
        f"{zone}:{','.join(sorted(items))}"
        for zone, items in failures.items()
        if items
    )


def run_combo(
    *,
    combo_index: int,
    case: SmoothCase,
    predicted: Mapping[str, Any],
    sections: Sequence[phase9.SectionRow],
    database: AirfoilDatabase,
    records_metadata: Mapping[str, Mapping[str, str]],
    fourier_target: Any,
    output_dir: Path,
    avl_binary: str | Path | None,
) -> dict[str, Any]:
    assignment = {
        "root": str(predicted["root_airfoil"]),
        "mid1": str(predicted["mid1_airfoil"]),
        "mid2": str(predicted["mid2_airfoil"]),
        "tip": str(predicted["tip_airfoil"]),
    }
    combo_id = f"combo_{combo_index:04d}"
    combo_dir = output_dir / "avl_inputs" / case.case_id / combo_id
    avl_path = write_combo_avl(
        source_avl=case.avl_path,
        source_sections=sections,
        assignment=assignment,
        database=database,
        output_path=combo_dir / f"{case.case_id}_{combo_id}.avl",
    )
    names = avl_audit.surface_names(avl_path)
    target_surfaces = ("Main Wing",) if "Main Wing" in names else ("Wing",)
    case_spec = avl_audit.CaseSpec(
        case_id=f"{case.case_id}_{combo_id}",
        display_name=f"{case.display_name} {combo_id}",
        avl_path=avl_path,
        section_table_path=case.section_table,
        cl_required=case.cl_req,
        target_surface_names=target_surfaces,
        assignment_by_zone=assignment,
        family=case.case_id,
    )
    result = avl_audit.run_avl_trim_and_spanload(
        case=case_spec,
        avl_path=avl_path,
        run_dir=output_dir / "avl_runs" / case.case_id / combo_id,
        avl_binary=avl_binary,
    )
    spanload = spanload_with_avl_cl(result.get("spanload", []))
    contract = mission_contract_for_sections(sections)
    profile = integrate_profile_drag_from_avl(
        contract,
        spanload,
        [row.__dict__ for row in sections],
        zone_assignments(assignment),
        database,
        cl_source_shape_mode="phase9_smooth_monotone_avl",
        cl_source_loaded_shape=True,
        cl_source_warning_count=0,
    )
    refs = result.get("refs", {})
    sref = safe_float(refs.get("Sref"), contract.wing_area_m2) or contract.wing_area_m2
    cdi = safe_float(result.get("CDff"), safe_float(result.get("CDind")))
    cd0 = float(profile.cd0_total_est)
    cd_total = None if cdi is None else cdi + cd0
    q = 0.5 * MISSION_RHO_KGPM3 * MISSION_SPEED_MPS**2
    p_air = None if cd_total is None else q * sref * cd_total * MISSION_SPEED_MPS
    p_crank = None if p_air is None else p_air / (ETA_PROP * ETA_TRANS)
    cd_total_cons = None if cdi is None else 1.05 * cdi + cd0
    p_air_cons = None if cd_total_cons is None else q * sref * cd_total_cons * MISSION_SPEED_MPS
    p_crank_cons = None if p_air_cons is None else p_air_cons / (ETA_PROP * ETA_TRANS)
    station_table = [
        {
            "eta": row["eta"],
            "chord_m": row["chord_m"],
            "avl_local_cl": row["cl"],
            "avl_circulation_proxy": row["lprime_proxy"],
        }
        for row in result.get("spanload", [])
    ]
    if fourier_target is not None:
        target_compare = compare_fourier_target_to_avl(fourier_target, station_table)
    else:
        target_compare = {
            "target_vs_avl_rms_delta": None,
            "target_vs_avl_outer_delta": None,
        }
    local_by_zone: dict[str, list[float]] = {zone: [] for zone, _, _ in ZONE_BOUNDS}
    for row in spanload:
        local_by_zone[zone_for_eta(float(row["eta"]))].append(float(row["cl"]))
    profile_rows = list(profile.station_rows)
    actual_fail = actual_query_fail_summary(assignment, profile_rows)
    actual_quality = (
        "actual_sidecar_query_grade_sidecar"
        if not actual_fail and int(profile.station_warning_count) == 0
        else "actual_sidecar_query_not_mission_grade_sidecar"
    )
    archive_summary = quality_summary(assignment, records_metadata, field="source_quality")
    archive_quality = (
        "archive_mission_grade_sidecar"
        if all(
            records_metadata.get(airfoil_id, {}).get("source_quality") == "full_polar_mission_grade_candidate"
            for airfoil_id in assignment.values()
        )
        else "archive_not_mission_grade_sidecar"
    )
    ids = set(assignment.values())
    return {
        "combo_index": combo_index,
        "case_id": case.case_id,
        "assignment": assignment_label(assignment),
        "root_airfoil": assignment["root"],
        "mid1_airfoil": assignment["mid1"],
        "mid2_airfoil": assignment["mid2"],
        "tip_airfoil": assignment["tip"],
        "status": "ok",
        "error": "",
        "known_policy_tags": predicted.get("known_policy_tags", ""),
        "selection_reasons": predicted.get("selection_reasons", ""),
        "predicted_profile_cd_proxy": predicted.get("predicted_profile_cd_proxy"),
        "predicted_balanced_score": predicted.get("predicted_balanced_score"),
        "predicted_archive_pass": predicted.get("predicted_archive_pass"),
        "predicted_actual_query_pass": predicted.get("predicted_actual_query_pass"),
        "alpha_at_CL_req": result.get("alpha_at_CL_req_deg"),
        "CL_req": case.cl_req,
        "CL": result.get("CLtot"),
        "CDi": cdi,
        "CDi_conservative": None if cdi is None else 1.05 * cdi,
        "e_CDi": result.get("e_CDi_from_CDff", result.get("e_CDi_from_CDind")),
        "profile_cd": profile.CD_profile,
        "CD0_total_est": cd0,
        "CD_total": cd_total,
        "L_D": None if cd_total in (None, 0.0) else case.cl_req / cd_total,
        "P_air": p_air,
        "P_crank": p_crank,
        "P_crank_conservative": p_crank_cons,
        "CD_total_conservative": cd_total_cons,
        "L_D_conservative": None if cd_total_cons in (None, 0.0) else case.cl_req / cd_total_cons,
        "local_Cl_max_root": max(local_by_zone["root"], default=None),
        "local_Cl_max_mid1": max(local_by_zone["mid1"], default=None),
        "local_Cl_max_mid2": max(local_by_zone["mid2"], default=None),
        "local_Cl_max_tip": max(local_by_zone["tip"], default=None),
        "stall_margin": profile.min_stall_margin_deg,
        "max_utilization": profile.max_station_cl_utilization,
        "archive_source_quality": archive_quality,
        "archive_source_quality_summary": archive_summary,
        "actual_sidecar_query_quality": actual_quality,
        "actual_sidecar_query_quality_summary": quality_summary(assignment, records_metadata, field="actual_sidecar_query_quality"),
        "actual_sidecar_query_fail_reasons": actual_fail,
        "target_vs_avl_rms": target_compare.get("target_vs_avl_rms_delta"),
        "target_vs_avl_outer_delta": target_compare.get("target_vs_avl_outer_delta"),
        "has_seed_reference": any(airfoil_id in SEED_REFERENCE_IDS for airfoil_id in ids),
        "is_cst_only": all(airfoil_id.startswith("cst_") for airfoil_id in ids),
        "no_ClarkY": "clarkysm" not in ids,
        "no_DAE": not any(airfoil_id.startswith("dae") for airfoil_id in ids),
        "avl_path": str(avl_path.resolve()),
        "run_dir": result.get("run_dir"),
    }


def run_failed_combo_row(
    *,
    combo_index: int,
    case: SmoothCase,
    predicted: Mapping[str, Any],
    exc: Exception,
) -> dict[str, Any]:
    return {
        "combo_index": combo_index,
        "case_id": case.case_id,
        "assignment": predicted.get("assignment"),
        "root_airfoil": predicted.get("root_airfoil"),
        "mid1_airfoil": predicted.get("mid1_airfoil"),
        "mid2_airfoil": predicted.get("mid2_airfoil"),
        "tip_airfoil": predicted.get("tip_airfoil"),
        "status": "error",
        "error": repr(exc),
        "known_policy_tags": predicted.get("known_policy_tags", ""),
        "selection_reasons": predicted.get("selection_reasons", ""),
    }


def best_rows(
    *,
    combo_rows: Sequence[Mapping[str, Any]],
    phase9_aero_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    ok = [row for row in combo_rows if row.get("status") == "ok" and safe_float(row.get("P_crank")) is not None]
    output: list[dict[str, Any]] = []

    def add(label: str, row: Mapping[str, Any], source: str) -> None:
        output.append({"ranking_view": label, "source": source, **dict(row)})

    for case_id in PRIMARY_CASE_IDS + OPTIONAL_CASE_IDS:
        subset = [row for row in ok if row.get("case_id") == case_id]
        if subset:
            add(f"{case_id}_performance_best", min(subset, key=lambda row: safe_float(row.get("P_crank"), float("inf")) or float("inf")), "smooth_reoptimized_combo")
            clean = [
                row
                for row in subset
                if row.get("actual_sidecar_query_quality") == "actual_sidecar_query_grade_sidecar"
                and row.get("archive_source_quality") == "archive_mission_grade_sidecar"
            ]
            if clean:
                add(f"{case_id}_clean_best", min(clean, key=lambda row: safe_float(row.get("P_crank"), float("inf")) or float("inf")), "smooth_reoptimized_combo")
    if ok:
        add("smooth_reoptimized_overall_best", min(ok, key=lambda row: safe_float(row.get("P_crank"), float("inf")) or float("inf")), "smooth_reoptimized_combo")
        clean_all = [
            row
            for row in ok
            if row.get("actual_sidecar_query_quality") == "actual_sidecar_query_grade_sidecar"
            and row.get("archive_source_quality") == "archive_mission_grade_sidecar"
        ]
        if clean_all:
            add("smooth_reoptimized_clean_overall_best", min(clean_all, key=lambda row: safe_float(row.get("P_crank"), float("inf")) or float("inf")), "smooth_reoptimized_combo")
    for wanted in [
        ("phase9_raw_faceted_original", "raw_best_tier2", "raw"),
        ("phase9_raw_smoothed_without_reselect", "raw_best_tier2", "smooth_monotone"),
        ("phase9_conservative_smooth_baseline", "conservative_best_tier2", "smooth_monotone"),
        ("phase9_policy_A_smooth", "policy_A_performance_candidate", "smooth_monotone"),
        ("phase9_policy_C_smooth", "policy_C_conservative_baseline", "smooth_monotone"),
        ("phase9_old_fx_clark_baseline", "old_fx_clark_baseline", "raw"),
    ]:
        label, case_id, variant = wanted
        match = next((row for row in phase9_aero_rows if row.get("case_id") == case_id and row.get("variant") == variant), None)
        if match:
            add(label, match, "phase9_reference")
    return output


def penalty_recovery_summary(
    *,
    raw_faceted_power_w: float,
    raw_smoothed_without_reselect_power_w: float,
    best_reoptimized_smooth_power_w: float,
    old_fx_clark_power_w: float,
) -> dict[str, Any]:
    smoothing_penalty = float(raw_smoothed_without_reselect_power_w) - float(raw_faceted_power_w)
    recovered = float(raw_smoothed_without_reselect_power_w) - float(best_reoptimized_smooth_power_w)
    remaining = float(best_reoptimized_smooth_power_w) - float(raw_faceted_power_w)
    return {
        "smoothing_penalty_w": smoothing_penalty,
        "recovered_by_reoptimization_w": recovered,
        "remaining_penalty_after_reoptimization_w": remaining,
        "recovered_fraction_of_smoothing_penalty": None if smoothing_penalty == 0.0 else recovered / smoothing_penalty,
        "best_smooth_beats_old_fx_clark": float(best_reoptimized_smooth_power_w) < float(old_fx_clark_power_w),
    }


def write_reports(
    *,
    output_dir: Path,
    combo_rows: Sequence[Mapping[str, Any]],
    best_policy_rows: Sequence[Mapping[str, Any]],
    phase9_aero_rows: Sequence[Mapping[str, Any]],
) -> None:
    best_reopt = next((row for row in best_policy_rows if row.get("ranking_view") == "smooth_reoptimized_overall_best"), {})
    best_clean = next((row for row in best_policy_rows if row.get("ranking_view") == "smooth_reoptimized_clean_overall_best"), {})
    raw_faceted = next((row for row in phase9_aero_rows if row.get("case_id") == "raw_best_tier2" and row.get("variant") == "raw"), {})
    raw_smooth = next((row for row in phase9_aero_rows if row.get("case_id") == "raw_best_tier2" and row.get("variant") == "smooth_monotone"), {})
    cons_smooth = next((row for row in phase9_aero_rows if row.get("case_id") == "conservative_best_tier2" and row.get("variant") == "smooth_monotone"), {})
    policy_a = next((row for row in phase9_aero_rows if row.get("case_id") == "policy_A_performance_candidate" and row.get("variant") == "smooth_monotone"), {})
    policy_c = next((row for row in phase9_aero_rows if row.get("case_id") == "policy_C_conservative_baseline" and row.get("variant") == "smooth_monotone"), {})
    old = next((row for row in phase9_aero_rows if row.get("case_id") == "old_fx_clark_baseline" and row.get("variant") == "raw"), {})
    accounting = penalty_recovery_summary(
        raw_faceted_power_w=safe_float(raw_faceted.get("P_crank"), 0.0) or 0.0,
        raw_smoothed_without_reselect_power_w=safe_float(raw_smooth.get("P_crank"), 0.0) or 0.0,
        best_reoptimized_smooth_power_w=safe_float(best_reopt.get("P_crank"), 0.0) or 0.0,
        old_fx_clark_power_w=safe_float(old.get("P_crank"), 0.0) or 0.0,
    )
    best_power = safe_float(best_reopt.get("P_crank"))
    clean_power = safe_float(best_clean.get("P_crank"))
    clean_accounting = None
    if clean_power is not None:
        clean_accounting = penalty_recovery_summary(
            raw_faceted_power_w=safe_float(raw_faceted.get("P_crank"), 0.0) or 0.0,
            raw_smoothed_without_reselect_power_w=safe_float(raw_smooth.get("P_crank"), 0.0) or 0.0,
            best_reoptimized_smooth_power_w=clean_power,
            old_fx_clark_power_w=safe_float(old.get("P_crank"), 0.0) or 0.0,
        )
    cons_power = safe_float(cons_smooth.get("P_crank"))
    policy_a_power = safe_float(policy_a.get("P_crank"))
    policy_c_power = safe_float(policy_c.get("P_crank"))
    lines = [
        "# Smooth Geometry Combo Re-optimization Summary",
        "",
        f"Generated: {timestamp()}",
        "",
        "## Direct Answers",
        "",
        f"- Smoothing penalty without airfoil reselection: {accounting['smoothing_penalty_w']:.3f} W crank.",
        f"- Recovered by smooth-geometry Tier2 reselection: {accounting['recovered_by_reoptimization_w']:.3f} W crank.",
        f"- Remaining penalty versus original faceted raw best: {accounting['remaining_penalty_after_reoptimization_w']:.3f} W crank.",
        f"- Recovered by archive+actual-pass production-quality reselection: {clean_accounting['recovered_by_reoptimization_w']:.3f} W crank." if clean_accounting else "- Archive+actual-pass production-quality recovery could not be computed.",
        f"- Remaining archive+actual-pass penalty versus original faceted raw best: {clean_accounting['remaining_penalty_after_reoptimization_w']:.3f} W crank." if clean_accounting else "- Archive+actual-pass remaining penalty could not be computed.",
        f"- Best smooth-monotone performance assignment: `{best_reopt.get('assignment', 'n/a')}` at {best_power:.3f} W crank." if best_power is not None else "- Best smooth-monotone performance assignment could not be computed.",
        f"- Best smooth-monotone production-quality assignment: `{best_clean.get('assignment', 'n/a')}` at {clean_power:.3f} W crank." if clean_power is not None else "- Best smooth-monotone production-quality assignment could not be computed.",
        f"- Smooth reoptimized beats old FX/Clark: {bool(accounting['best_smooth_beats_old_fx_clark'])}.",
        f"- Beats previous Policy A smooth: {best_power < policy_a_power if best_power is not None and policy_a_power is not None else 'n/a'}.",
        f"- Beats previous Policy C smooth: {best_power < policy_c_power if best_power is not None and policy_c_power is not None else 'n/a'}.",
        f"- Production-facing aero baseline: {'new archive+actual-pass smooth combo wins' if clean_power is not None and cons_power is not None and clean_power < cons_power else 'conservative best smooth remains preferred'}; keep structural/jig caveats from Phase 9.",
        "",
        "## Engineering Read",
        "",
        "This is still a sidecar aerodynamic re-optimization. It updates airfoil assignments for the smooth production geometry, but does not change production ranking, hard gates, Fourier settings, or structural feasibility status. The absolute performance winner is useful evidence; the archive+actual-pass winner is the safer production-facing aero recommendation.",
        "",
    ]
    (output_dir / "smooth_reoptimization_summary.md").write_text("\n".join(lines), encoding="utf-8")

    production_row = best_clean or best_reopt
    rec = [
        "# Recommended Production Assignment",
        "",
        f"Recommended assignment: `{production_row.get('assignment', 'n/a')}`",
        "",
        f"- `P_crank`: {production_row.get('P_crank')}",
        f"- `P_crank_conservative`: {production_row.get('P_crank_conservative')}",
        f"- `archive_source_quality`: {production_row.get('archive_source_quality')}",
        f"- `actual_sidecar_query_quality`: {production_row.get('actual_sidecar_query_quality')}",
        f"- `stall_margin`: {production_row.get('stall_margin')}",
        f"- `max_utilization`: {production_row.get('max_utilization')}",
        "",
        "Use this as the production-geometry aero sidecar candidate. Do not promote it through main ranking or hard gates until structure/jig and tube mass are rechecked with the new assignment.",
        "",
    ]
    (output_dir / "recommended_production_assignment.md").write_text("\n".join(rec), encoding="utf-8")


def run_reoptimization(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    avl_binary: str | Path | None = None,
    include_policy_ac: bool = True,
    max_combos_total: int = 240,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = load_smooth_cases(include_policy_ac=include_policy_ac)
    missing = [str(path) for case in cases for path in (case.avl_path, case.section_table) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing Phase 9 smooth inputs: " + ", ".join(missing))
    database = load_airfoil_database_artifact(TIER2_DIR / "airfoil_database.json")
    records_metadata = load_record_metadata(TIER2_DIR)
    previous_assignments = load_previous_assignments()
    fourier_target = phase9.load_fourier_target()
    phase9_aero_rows = read_csv_rows(PHASE9_OUTPUT_DIR / "aero_comparison.csv")

    all_envelope_rows: list[dict[str, Any]] = []
    all_pool_rows: list[dict[str, Any]] = []
    all_predicted_shortlist: list[dict[str, Any]] = []
    combo_rows: list[dict[str, Any]] = []
    combos_per_case = max(1, int(max_combos_total) // max(len(cases), 1))

    combo_index = 1
    for case in cases:
        sections = phase9.read_section_table(case.section_table)
        base_result = run_base_avl(case=case, output_dir=output_dir, avl_binary=avl_binary)
        spanload = spanload_with_avl_cl(base_result.get("spanload", []))
        envelopes = build_zone_envelope_rows(
            case=case,
            sections=sections,
            spanload=spanload,
            records_metadata=records_metadata,
        )
        all_envelope_rows.extend(envelopes)
        pool_rows = build_candidate_pools(
            case=case,
            envelopes=envelopes,
            sections=sections,
            database=database,
            records_metadata=records_metadata,
            previous_assignments=previous_assignments,
        )
        all_pool_rows.extend(pool_rows)
        predicted = predicted_combo_rows(
            case=case,
            pool_rows=pool_rows,
            previous_assignments=previous_assignments,
        )
        shortlist = shortlist_combinations(predicted, max_count=combos_per_case)
        for rank, row in enumerate(shortlist, start=1):
            row["shortlist_rank"] = rank
            all_predicted_shortlist.append(row)
            try:
                combo_rows.append(
                    run_combo(
                        combo_index=combo_index,
                        case=case,
                        predicted=row,
                        sections=sections,
                        database=database,
                        records_metadata=records_metadata,
                        fourier_target=fourier_target,
                        output_dir=output_dir,
                        avl_binary=avl_binary,
                    )
                )
            except Exception as exc:
                combo_rows.append(
                    run_failed_combo_row(
                        combo_index=combo_index,
                        case=case,
                        predicted=row,
                        exc=exc,
                    )
                )
            combo_index += 1

    best_policy = best_rows(combo_rows=combo_rows, phase9_aero_rows=phase9_aero_rows)
    write_csv(output_dir / "smooth_geometry_zone_envelopes.csv", all_envelope_rows)
    write_csv(output_dir / "smooth_combo_candidate_pools.csv", all_pool_rows)
    write_csv(output_dir / "smooth_combo_predicted_shortlist.csv", all_predicted_shortlist)
    write_csv(output_dir / "smooth_combo_results.csv", combo_rows)
    write_csv(output_dir / "best_smooth_by_policy.csv", best_policy)
    write_reports(
        output_dir=output_dir,
        combo_rows=combo_rows,
        best_policy_rows=best_policy,
        phase9_aero_rows=phase9_aero_rows,
    )
    metadata = {
        "schema_version": "phase9_smooth_geometry_combo_reoptimization_v1",
        "generated_at": timestamp(),
        "output_dir": str(output_dir.resolve()),
        "case_ids": [case.case_id for case in cases],
        "max_combos_total": int(max_combos_total),
        "combos_per_case": combos_per_case,
        "combo_rows": len(combo_rows),
        "ok_combo_rows": sum(1 for row in combo_rows if row.get("status") == "ok"),
        "notes": [
            "Diagnostic sidecar only.",
            "No CST/NSGA rerun.",
            "No production hard gates or main ranking changed.",
            "Phase 9 outputs are read-only inputs and are not deleted.",
        ],
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(json_ready(metadata), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--avl-binary", type=Path, default=None)
    parser.add_argument("--max-combos-total", type=int, default=240)
    parser.add_argument("--primary-only", action="store_true", help="Skip optional Policy A/C smooth cases.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    metadata = run_reoptimization(
        output_dir=Path(args.output_dir),
        avl_binary=args.avl_binary,
        include_policy_ac=not bool(args.primary_only),
        max_combos_total=int(args.max_combos_total),
    )
    print(
        json.dumps(
            {
                "output_dir": metadata["output_dir"],
                "combo_rows": metadata["combo_rows"],
                "ok_combo_rows": metadata["ok_combo_rows"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
