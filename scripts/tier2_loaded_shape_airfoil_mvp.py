#!/usr/bin/env python3
"""Pipeline v2 MVP 4: Tier2 airfoil selection on loaded-shape AVL Cl/Re.

This is a report-only MVP artifact. It reads the existing Tier2 full-alpha
database and the MVP3 loaded-shape AVL local Cl/Re envelope, then writes a
capped combo-search trace, profile-drag trace, and raw/conservative assignments.
It does not change production ranking, add hard gates, rerun CST/NSGA, run FEM,
or promote structural results to final truth.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hpa_mdo.aero.aswing_exporter import parse_avl  # noqa: E402
from hpa_mdo.aero.avl_spanwise import build_spanwise_load_from_avl_strip_forces  # noqa: E402
from hpa_mdo.airfoils.database import (  # noqa: E402
    AirfoilDatabase,
    AirfoilQuery,
    ZoneAirfoilAssignment,
    ZoneEnvelope,
    airfoil_coordinate_path_from_record,
    integrate_profile_drag_from_avl,
)
from hpa_mdo.airfoils.polar_builder import load_airfoil_database_artifact  # noqa: E402
from hpa_mdo.airfoils.sidecar import build_zone_envelopes  # noqa: E402
from hpa_mdo.concept.avl_loader import (  # noqa: E402
    _run_avl_spanwise_case,
    _run_avl_trim_case,
)


DEFAULT_STAGE6_DIR = REPO_ROOT / "output/pipeline_redesign_v2/loaded_shape_avl_recheck_mvp"
DEFAULT_TIER2_DIR = REPO_ROOT / "output/airfoil_db/full_alpha_reusable_v1_tier2"
DEFAULT_TIER2_DATABASE_JSON = DEFAULT_TIER2_DIR / "airfoil_database.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output/pipeline_redesign_v2/tier2_loaded_shape_airfoil_mvp"
SCHEMA_VERSION = "tier2_loaded_shape_airfoil_mvp_v1"
CL_RE_SOURCE = "stage6_loaded_shape_avl_actual_local_cl_re"
ZONE_BOUNDS: tuple[tuple[str, float, float], ...] = (
    ("root", 0.0, 0.25),
    ("mid1", 0.25, 0.55),
    ("mid2", 0.55, 0.80),
    ("tip", 0.80, 1.0),
)
SEED_REFERENCE_IDS = {"fx76mp140", "clarkysm", "dae11", "dae21", "dae31", "dae41"}
ETA_PROP = 0.88
ETA_TRANS = 0.96


@dataclass(frozen=True)
class Mvp4MissionContract:
    speed_mps: float
    rho: float
    dynamic_viscosity_pa_s: float
    wing_area_m2: float
    span_m: float
    CDA_nonwing_target_m2: float = 0.13
    CD_wing_profile_target: float = 0.0120
    CD_wing_profile_boundary: float = 0.0140
    CD0_total_target: float = 0.0160
    CD0_total_boundary: float = 0.0180
    CD0_total_rescue: float = 0.0240


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        if fieldnames:
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_value(row.get(key, "")) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list | tuple):
        return "; ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return value


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _required_float(row: Mapping[str, Any], key: str) -> float:
    parsed = _float_or_none(row.get(key))
    if parsed is None:
        raise ValueError(f"Missing required numeric field {key!r}.")
    return float(parsed)


def _fmt(value: Any, digits: int = 4) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:.{digits}f}"


def zone_for_eta(eta: float) -> str:
    eta_f = min(max(float(eta), 0.0), 1.0)
    for zone, lo, hi in ZONE_BOUNDS:
        if zone == "tip":
            if lo <= eta_f <= hi:
                return zone
        elif lo <= eta_f < hi:
            return zone
    return "tip"


def zone_assignments(assignment: Mapping[str, str]) -> tuple[ZoneAirfoilAssignment, ...]:
    return tuple(
        ZoneAirfoilAssignment(zone, str(assignment[zone]), lo, hi)
        for zone, lo, hi in ZONE_BOUNDS
    )


def assignment_label(assignment: Mapping[str, str]) -> str:
    return "|".join(f"{zone}:{assignment[zone]}" for zone, _, _ in ZONE_BOUNDS)


def parse_assignment_label(label: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for part in str(label).split("|"):
        if ":" not in part:
            continue
        zone, airfoil_id = part.split(":", 1)
        values[zone] = airfoil_id
    return values


def stage6_rows_for_airfoil_sidecar(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize MVP3 CSV rows to the AVL actual-Cl keys used by airfoil APIs."""

    converted: list[dict[str, Any]] = []
    for row in rows:
        eta = _float_or_none(row.get("eta"))
        y_m = _float_or_none(row.get("y_m"))
        chord = _float_or_none(row.get("chord_m"))
        local_cl = _float_or_none(
            row.get("local_cl", row.get("cl_actual_avl", row.get("avl_local_cl")))
        )
        reynolds = _float_or_none(row.get("reynolds", row.get("Re")))
        if eta is None or y_m is None or chord is None or local_cl is None:
            continue
        out = dict(row)
        out["eta"] = float(eta)
        out["y_m"] = float(y_m)
        out["chord_m"] = float(chord)
        out["avl_local_cl"] = float(local_cl)
        out["cl_actual_avl"] = float(local_cl)
        if reynolds is not None:
            out["reynolds"] = float(reynolds)
            out["Re"] = float(reynolds)
        for key in (
            "velocity_mps",
            "density_kgpm3",
            "dynamic_viscosity_pa_s",
            "local_cd",
            "cm_c4",
        ):
            parsed = _float_or_none(out.get(key))
            if parsed is not None:
                out[key] = float(parsed)
        converted.append(out)
    converted.sort(key=lambda item: (float(item["eta"]), float(item["y_m"])))
    return converted


def _load_stage6_inputs(stage6_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    summary_rows = _read_csv_rows(stage6_dir / "loaded_shape_avl_recheck.csv")
    local_rows = _read_csv_rows(stage6_dir / "loaded_shape_local_cl_re_envelope.csv")
    if not local_rows:
        raise FileNotFoundError(stage6_dir / "loaded_shape_local_cl_re_envelope.csv")
    converted = stage6_rows_for_airfoil_sidecar(local_rows)
    if not converted:
        raise ValueError("Stage6 local Cl/Re CSV did not contain usable local_cl rows.")
    return summary_rows, converted


def _span_and_area_from_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[float, float]:
    y = np.asarray([_required_float(row, "y_m") for row in rows], dtype=float)
    chord = np.asarray([_required_float(row, "chord_m") for row in rows], dtype=float)
    half_span = float(np.max(y)) if y.size else 0.0
    area = float(2.0 * np.trapezoid(chord, y)) if y.size >= 2 else 0.0
    return 2.0 * half_span, area


def _mission_contract(
    *,
    summary_row: Mapping[str, Any] | None,
    stage6_rows: Sequence[Mapping[str, Any]],
) -> Mvp4MissionContract:
    span_m, area_m2 = _span_and_area_from_rows(stage6_rows)
    if summary_row:
        loaded_avl = Path(str(summary_row.get("loaded_shape_avl") or ""))
        if loaded_avl.is_file():
            model = parse_avl(loaded_avl)
            if model.bref > 0.0:
                span_m = float(model.bref)
            if model.sref > 0.0:
                area_m2 = float(model.sref)
    first = stage6_rows[0]
    speed = _float_or_none(first.get("velocity_mps")) or 6.6
    rho = _float_or_none(first.get("density_kgpm3")) or 1.18
    mu = _float_or_none(first.get("dynamic_viscosity_pa_s")) or 1.7228e-5
    if span_m <= 0.0 or area_m2 <= 0.0:
        raise ValueError("Could not derive positive span/area from Stage6 rows or AVL file.")
    return Mvp4MissionContract(
        speed_mps=float(speed),
        rho=float(rho),
        dynamic_viscosity_pa_s=float(mu),
        wing_area_m2=float(area_m2),
        span_m=float(span_m),
    )


def _current_assignment_from_avl(
    summary_row: Mapping[str, Any] | None,
) -> dict[str, str]:
    fallback = {"root": "unknown", "mid1": "unknown", "mid2": "unknown", "tip": "unknown"}
    if not summary_row:
        return fallback
    loaded_avl = Path(str(summary_row.get("loaded_shape_avl") or ""))
    if not loaded_avl.is_file():
        return fallback
    model = parse_avl(loaded_avl)
    half_span = max(float(model.bref) * 0.5, 1.0e-12)
    counts: dict[str, dict[str, int]] = {zone: {} for zone, _, _ in ZONE_BOUNDS}
    for surface in model.surfaces:
        if surface.name.replace(" ", "").casefold() != "wing":
            continue
        for section in surface.sections:
            zone = zone_for_eta(float(section.y) / half_span)
            airfoil_id = Path(str(section.airfoil or "")).stem or "unknown"
            counts.setdefault(zone, {})
            counts[zone][airfoil_id] = counts[zone].get(airfoil_id, 0) + 1
    assignment: dict[str, str] = {}
    for zone, _, _ in ZONE_BOUNDS:
        zone_counts = counts.get(zone, {})
        assignment[zone] = (
            max(zone_counts.items(), key=lambda item: (item[1], item[0]))[0]
            if zone_counts
            else "unknown"
        )
    return assignment


def build_zone_requirement_rows(
    *,
    stage6_rows: Sequence[Mapping[str, Any]],
    mission_contract: Mvp4MissionContract,
    current_assignment: Mapping[str, str],
) -> tuple[ZoneEnvelope, ...]:
    definitions = tuple(
        ZoneAirfoilAssignment(zone, str(current_assignment.get(zone, "unknown")), lo, hi)
        for zone, lo, hi in ZONE_BOUNDS
    )
    return build_zone_envelopes(
        loaded_avl_spanwise_result=stage6_rows,
        chord_distribution=stage6_rows,
        mission_contract=mission_contract,
        fourier_target=None,
        zone_definitions=definitions,
    )


def _read_record_metadata(tier2_database_json: Path) -> dict[str, dict[str, str]]:
    records_csv = tier2_database_json.parent / "airfoil_records.csv"
    return {
        str(row.get("airfoil_id")): dict(row)
        for row in _read_csv_rows(records_csv)
        if row.get("airfoil_id")
    }


def _record_matches_zone(record: Any, zone_name: str, *, force_ids: set[str]) -> bool:
    airfoil_id = str(getattr(record, "airfoil_id", ""))
    if airfoil_id in force_ids or airfoil_id in SEED_REFERENCE_IDS:
        return True
    is_generated_cst = airfoil_id.startswith("cst_") or "cst_" in str(getattr(record, "source", ""))
    if not is_generated_cst:
        return True
    zone_hint = str(getattr(record, "zone_hint", "")).strip()
    if not zone_hint:
        return True
    hints = {item.strip() for item in zone_hint.replace(",", "|").split("|") if item.strip()}
    return str(zone_name) in hints


def _work_points(envelope: ZoneEnvelope) -> tuple[tuple[float, float, float], ...]:
    re_mid = _first_float(envelope.re_p50, envelope.re_min, envelope.re_max)
    cl_mid = _first_float(envelope.cl_p50, envelope.cl_min, envelope.cl_max)
    if re_mid is None or cl_mid is None:
        return tuple()
    re_min = _first_float(envelope.re_min, re_mid) or re_mid
    re_max = _first_float(envelope.re_max, re_mid) or re_mid
    cl_min = _first_float(envelope.cl_min, cl_mid) or cl_mid
    cl_p90 = _first_float(envelope.cl_p90, envelope.cl_max, cl_mid) or cl_mid
    cl_max = _first_float(envelope.cl_max, cl_p90) or cl_p90
    return (
        (float(re_mid), float(cl_mid), 1.0),
        (float(re_mid), float(cl_p90), 1.4),
        (float(re_min), float(cl_max), 1.2),
        (float(re_max), float(cl_min), 0.5),
    )


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return float(parsed)
    return None


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    clean = [float(value) for value in values if math.isfinite(float(value))]
    if not clean:
        return None
    return float(np.percentile(np.asarray(clean, dtype=float), float(percentile)))


def score_airfoil_for_zone(
    *,
    envelope: ZoneEnvelope,
    airfoil_id: str,
    database: AirfoilDatabase,
    metadata: Mapping[str, Mapping[str, str]],
    zone_area_weight: float,
) -> dict[str, Any] | None:
    record = database.records.get(str(airfoil_id))
    if record is None:
        return None
    points = _work_points(envelope)
    if not points:
        return None
    cd_values: list[float] = []
    cm_values: list[float] = []
    stall_margins: list[float] = []
    clmax_margins: list[float] = []
    warnings: list[str] = []
    weighted_cd = 0.0
    weight_sum = 0.0
    for re_value, cl_value, weight in points:
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
        warnings.extend(str(flag) for flag in result.warnings)
        weighted_cd += float(weight) * float(result.cd)
        weight_sum += float(weight)
    mean_cd = weighted_cd / max(weight_sum, 1.0e-12)
    warning_flags = tuple(sorted(set(warnings)))
    min_clmax = min(clmax_margins) if clmax_margins else None
    min_stall = min(stall_margins) if stall_margins else None
    cd_p90 = _percentile(cd_values, 90.0) or mean_cd
    cm_mean = float(sum(cm_values) / len(cm_values)) if cm_values else 0.0
    meta = metadata.get(str(airfoil_id), {})
    source_quality = str(meta.get("source_quality") or record.source_quality)
    archive_quality = str(meta.get("archive_source_quality") or source_quality)
    query_pass = (
        "not_mission_grade" not in source_quality
        and str(source_quality) == "full_polar_mission_grade_candidate"
        and not warning_flags
        and min_clmax is not None
        and min_clmax >= 0.0
    )
    fail_reasons: list[str] = list(warning_flags)
    if min_clmax is not None and min_clmax < 0.0:
        fail_reasons.append("insufficient_safe_clmax_margin")
    if "not_mission_grade" in source_quality:
        fail_reasons.append("record_not_mission_grade")
    balanced_score = (
        float(mean_cd)
        + 0.35 * max(0.0, float(cd_p90) - float(mean_cd))
        + 0.006 * abs(float(cm_mean))
        + 0.0015 * len(warning_flags)
        + 0.0005 * max(0.0, 3.0 - float(min_stall or 0.0))
        + 0.0100 * max(0.0, -float(min_clmax or 0.0))
    )
    if not query_pass:
        balanced_score += 0.010
    if min_clmax is not None and min_clmax < 0.0:
        balanced_score += 1.0
    return {
        "schema_version": SCHEMA_VERSION,
        "zone_name": envelope.zone_name,
        "airfoil_id": str(airfoil_id),
        "raw_score": float(mean_cd),
        "balanced_score": float(balanced_score),
        "mean_cd": float(mean_cd),
        "cd_p90": float(cd_p90),
        "min_stall_margin_deg": min_stall,
        "min_safe_clmax_margin": min_clmax,
        "safe_clmax": float(record.safe_clmax),
        "usable_clmax": float(record.usable_clmax),
        "cm_mean": float(cm_mean),
        "warning_count": len(warning_flags),
        "warning_flags": "; ".join(warning_flags),
        "actual_query_quality": "actual_loaded_shape_query_pass"
        if query_pass
        else "actual_loaded_shape_query_warning_not_mission_grade",
        "actual_query_pass": bool(query_pass),
        "actual_query_fail_reasons": "; ".join(sorted(set(fail_reasons))),
        "archive_quality": archive_quality,
        "record_full_alpha_quality": source_quality,
        "screening_quality": meta.get("screening_quality", ""),
        "coordinate_path": meta.get("coordinate_path") or str(record.coordinate_path or ""),
        "zone_area_weight": float(zone_area_weight),
        "work_point_count": len(points),
        "Re_min": envelope.re_min,
        "Re_p50": envelope.re_p50,
        "Re_max": envelope.re_max,
        "Cl_min": envelope.cl_min,
        "Cl_p50": envelope.cl_p50,
        "Cl_p90": envelope.cl_p90,
        "Cl_max": envelope.cl_max,
    }


def _zone_area_weights(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    weights = {zone: 0.0 for zone, _, _ in ZONE_BOUNDS}
    total = 0.0
    ordered = sorted(rows, key=lambda row: float(row["eta"]))
    for left, right in zip(ordered[:-1], ordered[1:]):
        dy = max(float(right["y_m"]) - float(left["y_m"]), 0.0)
        area = 0.5 * dy * (float(left["chord_m"]) + float(right["chord_m"]))
        zone = zone_for_eta(0.5 * (float(left["eta"]) + float(right["eta"])))
        weights[zone] = weights.get(zone, 0.0) + area
        total += area
    if total <= 0.0:
        return {zone: 0.25 for zone, _, _ in ZONE_BOUNDS}
    return {zone: value / total for zone, value in weights.items()}


def build_candidate_pool_rows(
    *,
    envelopes: Sequence[ZoneEnvelope],
    stage6_rows: Sequence[Mapping[str, Any]],
    database: AirfoilDatabase,
    metadata: Mapping[str, Mapping[str, str]],
    current_assignment: Mapping[str, str],
    top_k_per_zone: int,
) -> list[dict[str, Any]]:
    area_weights = _zone_area_weights(stage6_rows)
    force_ids = {str(value) for value in current_assignment.values() if value and value != "unknown"}
    force_ids |= SEED_REFERENCE_IDS
    pool_rows: list[dict[str, Any]] = []
    for envelope in envelopes:
        zone = str(envelope.zone_name)
        scored: list[dict[str, Any]] = []
        for airfoil_id, record in database.records.items():
            if not _record_matches_zone(record, zone, force_ids=force_ids):
                continue
            scored_row = score_airfoil_for_zone(
                envelope=envelope,
                airfoil_id=str(airfoil_id),
                database=database,
                metadata=metadata,
                zone_area_weight=area_weights.get(zone, 0.25),
            )
            if scored_row is not None:
                scored.append(scored_row)
        pool_rows.extend(_select_pool_for_zone(scored, top_k_per_zone=top_k_per_zone))
    return pool_rows


def _select_pool_for_zone(
    scored: Sequence[Mapping[str, Any]],
    *,
    top_k_per_zone: int,
) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}

    def add(rows: Iterable[Mapping[str, Any]], reason: str) -> None:
        for row in rows:
            airfoil_id = str(row.get("airfoil_id", ""))
            if not airfoil_id:
                continue
            out = selected.setdefault(airfoil_id, dict(row))
            reasons = {item for item in str(out.get("pool_reasons") or "").split("; ") if item}
            reasons.add(reason)
            out["pool_reasons"] = "; ".join(sorted(reasons))

    limit = max(1, int(top_k_per_zone))
    ranked_raw = sorted(scored, key=lambda row: (float(row.get("raw_score", 99.0)), str(row.get("airfoil_id", ""))))
    ranked_balanced = sorted(scored, key=lambda row: (float(row.get("balanced_score", 99.0)), str(row.get("airfoil_id", ""))))
    ranked_pass = [row for row in ranked_balanced if bool(row.get("actual_query_pass"))]
    seeds = [row for row in scored if str(row.get("airfoil_id", "")) in SEED_REFERENCE_IDS]
    add(ranked_raw[:limit], "top_raw_loaded_shape_cd")
    add(ranked_balanced[:limit], "top_balanced_loaded_shape_score")
    add(ranked_pass[:limit], "top_actual_loaded_shape_query_pass")
    add(seeds, "seed_reference")
    return sorted(
        selected.values(),
        key=lambda row: (
            float(row.get("balanced_score", 99.0)),
            float(row.get("raw_score", 99.0)),
            str(row.get("airfoil_id", "")),
        ),
    )


def predicted_combo_rows(
    *,
    pool_rows: Sequence[Mapping[str, Any]],
    max_combo_count: int,
) -> list[dict[str, Any]]:
    by_zone: dict[str, list[Mapping[str, Any]]] = {zone: [] for zone, _, _ in ZONE_BOUNDS}
    for row in pool_rows:
        by_zone.setdefault(str(row.get("zone_name", "")), []).append(row)
    all_rows: list[dict[str, Any]] = []
    for root, mid1, mid2, tip in itertools.product(
        by_zone.get("root", []),
        by_zone.get("mid1", []),
        by_zone.get("mid2", []),
        by_zone.get("tip", []),
    ):
        items = {"root": root, "mid1": mid1, "mid2": mid2, "tip": tip}
        assignment = {zone: str(item["airfoil_id"]) for zone, item in items.items()}
        weights = {
            zone: _float_or_none(item.get("zone_area_weight")) or 0.25
            for zone, item in items.items()
        }
        weight_sum = sum(weights.values()) or 1.0
        raw_proxy = sum(
            weights[zone] / weight_sum * float(items[zone].get("raw_score", 99.0))
            for zone in items
        )
        balanced_proxy = sum(
            weights[zone] / weight_sum * float(items[zone].get("balanced_score", 99.0))
            for zone in items
        )
        all_rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "combo_id": f"combo_{len(all_rows) + 1:04d}",
                "assignment": assignment_label(assignment),
                "root_airfoil": assignment["root"],
                "mid1_airfoil": assignment["mid1"],
                "mid2_airfoil": assignment["mid2"],
                "tip_airfoil": assignment["tip"],
                "predicted_raw_profile_cd_proxy": float(raw_proxy),
                "predicted_balanced_score": float(balanced_proxy),
                "predicted_min_stall_margin_deg": min(
                    float(items[zone].get("min_stall_margin_deg", -999.0)) for zone in items
                ),
                "predicted_min_safe_clmax_margin": min(
                    float(items[zone].get("min_safe_clmax_margin", -999.0)) for zone in items
                ),
                "predicted_actual_query_pass": all(bool(items[zone].get("actual_query_pass")) for zone in items),
                "actual_query_quality": "actual_loaded_shape_query_pass"
                if all(bool(items[zone].get("actual_query_pass")) for zone in items)
                else "actual_loaded_shape_query_warning_not_mission_grade",
                "archive_quality": "; ".join(
                    f"{zone}:{items[zone].get('archive_quality', '')}" for zone in items
                ),
                "candidate_warning_flags": "; ".join(
                    sorted(
                        {
                            str(flag).strip()
                            for zone in items
                            for flag in str(items[zone].get("warning_flags", "")).split(";")
                            if str(flag).strip()
                        }
                    )
                ),
            }
        )
    ranked = sorted(
        all_rows,
        key=lambda row: (
            float(row.get("predicted_raw_profile_cd_proxy", 99.0)),
            float(row.get("predicted_balanced_score", 99.0)),
            str(row.get("assignment", "")),
        ),
    )
    pass_rows = [row for row in ranked if bool(row.get("predicted_actual_query_pass"))]
    balanced = sorted(
        all_rows,
        key=lambda row: (
            float(row.get("predicted_balanced_score", 99.0)),
            float(row.get("predicted_raw_profile_cd_proxy", 99.0)),
            str(row.get("assignment", "")),
        ),
    )
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(rows: Iterable[Mapping[str, Any]], reason: str) -> None:
        for row in rows:
            if len(selected) >= max(1, int(max_combo_count)):
                return
            assignment = str(row.get("assignment") or "")
            if assignment in seen:
                continue
            out = dict(row)
            reasons = {item for item in str(out.get("selection_reasons") or "").split("; ") if item}
            reasons.add(reason)
            out["selection_reasons"] = "; ".join(sorted(reasons))
            selected.append(out)
            seen.add(assignment)

    add(ranked, "top_raw_profile_proxy")
    add(pass_rows, "top_actual_loaded_shape_query_pass")
    add(balanced, "top_balanced_score")
    return sorted(
        selected,
        key=lambda row: (
            float(row.get("predicted_raw_profile_cd_proxy", 99.0)),
            float(row.get("predicted_balanced_score", 99.0)),
            str(row.get("assignment", "")),
        ),
    )


def evaluate_combo_rows(
    *,
    combo_rows: Sequence[Mapping[str, Any]],
    stage6_rows: Sequence[Mapping[str, Any]],
    mission_contract: Mvp4MissionContract,
    database: AirfoilDatabase,
    stage6_cdi: float | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evaluated: list[dict[str, Any]] = []
    profile_rows: list[dict[str, Any]] = []
    for row in combo_rows:
        assignment = parse_assignment_label(str(row["assignment"]))
        try:
            profile = integrate_profile_drag_from_avl(
                mission_contract,
                stage6_rows,
                stage6_rows,
                zone_assignments(assignment),
                database,
                cl_source_shape_mode="loaded_dihedral_avl",
                cl_source_loaded_shape=True,
                cl_source_warning_count=0,
            )
            cdi = stage6_cdi
            cd_total = None if cdi is None else float(cdi) + float(profile.cd0_total_est)
            power = _power_w(mission_contract, cd_total)
            out = {
                **dict(row),
                "status": "evaluated_on_stage6_loaded_shape_cl_re",
                "cl_re_source": CL_RE_SOURCE,
                "cl_source_shape_mode": "loaded_dihedral_avl",
                "profile_cd": float(profile.CD_profile),
                "CD0_total": float(profile.cd0_total_est),
                "CDi_source": "" if cdi is None else float(cdi),
                "CD_total": "" if cd_total is None else float(cd_total),
                "P_crank": "" if power is None else float(power),
                "P_crank_conservative": ""
                if cdi is None
                else float(_power_w(mission_contract, 1.05 * float(cdi) + float(profile.cd0_total_est)) or 0.0),
                "stall_margin_min": profile.min_stall_margin_deg,
                "max_station_utilization": profile.max_station_cl_utilization,
                "actual_query_quality": _profile_query_quality(profile),
                "profile_source_quality": profile.source_quality,
                "profile_warning_count": profile.station_warning_count,
                "drag_budget_band": profile.drag_budget_band,
            }
            evaluated.append(out)
            for station in profile.station_rows:
                profile_rows.append(
                    {
                        "selected_role": "combo_search",
                        "combo_id": row.get("combo_id", ""),
                        "assignment": row.get("assignment", ""),
                        "profile_source": "stage6_loaded_shape_avl_actual_local_cl",
                        **station,
                    }
                )
        except Exception as exc:
            evaluated.append(
                {
                    **dict(row),
                    "status": "profile_drag_failed",
                    "error": str(exc),
                    "cl_re_source": CL_RE_SOURCE,
                    "cl_source_shape_mode": "loaded_dihedral_avl",
                }
            )
    return evaluated, profile_rows


def selected_profile_rows_from_stage6(
    *,
    role: str,
    selected_row: Mapping[str, Any],
    stage6_rows: Sequence[Mapping[str, Any]],
    mission_contract: Mvp4MissionContract,
    database: AirfoilDatabase,
) -> list[dict[str, Any]]:
    assignment = parse_assignment_label(str(selected_row["assignment"]))
    profile = integrate_profile_drag_from_avl(
        mission_contract,
        stage6_rows,
        stage6_rows,
        zone_assignments(assignment),
        database,
        cl_source_shape_mode="loaded_dihedral_avl",
        cl_source_loaded_shape=True,
        cl_source_warning_count=0,
    )
    return [
        {
            "selected_role": role,
            "combo_id": selected_row.get("combo_id", ""),
            "assignment": selected_row.get("assignment", ""),
            "profile_source": "stage6_loaded_shape_avl_actual_local_cl_selected_assignment",
            **station,
        }
        for station in profile.station_rows
    ]


def _profile_query_quality(profile: Any) -> str:
    if int(profile.station_warning_count) == 0 and "not_mission_grade" not in str(profile.source_quality):
        return "actual_loaded_shape_query_pass"
    return "actual_loaded_shape_query_warning_not_mission_grade"


def _power_w(contract: Mvp4MissionContract, cd_total: float | None) -> float | None:
    if cd_total is None:
        return None
    q = 0.5 * float(contract.rho) * float(contract.speed_mps) ** 2
    p_air = q * float(contract.wing_area_m2) * float(cd_total) * float(contract.speed_mps)
    return float(p_air / (ETA_PROP * ETA_TRANS))


def _select_best_roles(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    ok_rows = [dict(row) for row in rows if row.get("status") == "evaluated_on_stage6_loaded_shape_cl_re"]
    if not ok_rows:
        raise ValueError("No combo rows could be evaluated for profile drag.")
    raw_candidates = [
        row for row in ok_rows if (_float_or_none(row.get("stall_margin_min")) or -999.0) >= 0.0
    ] or ok_rows
    raw_best = min(
        raw_candidates,
        key=lambda row: (
            _float_or_none(row.get("profile_cd")) or float("inf"),
            _float_or_none(row.get("predicted_balanced_score")) or float("inf"),
            str(row.get("assignment", "")),
        ),
    )
    conservative_candidates = [
        row
        for row in raw_candidates
        if bool(row.get("predicted_actual_query_pass"))
        and str(row.get("actual_query_quality")) == "actual_loaded_shape_query_pass"
        and str(row.get("profile_source_quality")).find("not_mission_grade") < 0
    ]
    conservative_best = min(
        conservative_candidates or raw_candidates,
        key=lambda row: (
            _float_or_none(row.get("P_crank_conservative")) or float("inf"),
            _float_or_none(row.get("predicted_balanced_score")) or float("inf"),
            str(row.get("assignment", "")),
        ),
    )
    raw_best = dict(raw_best)
    conservative_best = dict(conservative_best)
    raw_best["selected_role"] = "raw_best"
    conservative_best["selected_role"] = "conservative_best"
    if not conservative_candidates:
        conservative_best["selection_warning"] = "no_full_production_quality_combo_found_in_cap"
    return raw_best, conservative_best


def _dat_path_for_airfoil(database: AirfoilDatabase, airfoil_id: str) -> Path:
    record = database.records[str(airfoil_id)]
    path = airfoil_coordinate_path_from_record(record, repo_root=REPO_ROOT)
    if path is None:
        raise FileNotFoundError(f"No coordinate .dat path found for airfoil {airfoil_id}.")
    return path


def write_selected_airfoil_avl(
    *,
    source_avl: Path,
    output_avl: Path,
    assignment: Mapping[str, str],
    database: AirfoilDatabase,
) -> Path:
    model = parse_avl(source_avl)
    half_span = max(0.5 * float(model.bref), 1.0e-12)
    lines = source_avl.read_text(encoding="utf-8").splitlines()
    out_lines = list(lines)
    current_surface = ""
    expect_surface_name = False
    expect_section_values = False
    pending_zone: str | None = None
    replace_next_afile = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        upper = stripped.upper()
        if expect_surface_name and stripped:
            current_surface = stripped.replace(" ", "").casefold()
            expect_surface_name = False
            continue
        if upper == "SURFACE":
            expect_surface_name = True
            current_surface = ""
            continue
        if expect_section_values:
            tokens = stripped.split()
            if len(tokens) >= 2:
                y_m = float(tokens[1])
                pending_zone = zone_for_eta(y_m / half_span)
                replace_next_afile = current_surface == "wing"
            expect_section_values = False
            continue
        if upper == "SECTION" and current_surface == "wing":
            expect_section_values = True
            continue
        if upper == "AFILE" and replace_next_afile and pending_zone is not None:
            airfoil_id = str(assignment[pending_zone])
            out_lines[idx + 1] = str(_dat_path_for_airfoil(database, airfoil_id))
            replace_next_afile = False
            pending_zone = None
    output_avl.parent.mkdir(parents=True, exist_ok=True)
    output_avl.write_text("\n".join(line.rstrip() for line in out_lines) + "\n", encoding="utf-8")
    return output_avl


def rerun_selected_assignment(
    *,
    role: str,
    selected_row: Mapping[str, Any],
    summary_row: Mapping[str, Any] | None,
    output_dir: Path,
    mission_contract: Mvp4MissionContract,
    database: AirfoilDatabase,
    avl_binary: str | Path | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not summary_row:
        raise ValueError("Stage6 summary row is required for AVL rerun.")
    source_avl = Path(str(summary_row.get("loaded_shape_avl") or ""))
    if not source_avl.is_file():
        raise FileNotFoundError(f"Stage6 loaded_shape_avl not found: {source_avl}")
    cl_required = _float_or_none(summary_row.get("pre_structure_cl"))
    if cl_required is None:
        raise ValueError("Stage6 summary lacks pre_structure_cl for AVL trim.")
    assignment = parse_assignment_label(str(selected_row["assignment"]))
    role_dir = output_dir / "runs" / role
    avl_path = write_selected_airfoil_avl(
        source_avl=source_avl,
        output_avl=role_dir / f"{role}_loaded_shape_airfoils.avl",
        assignment=assignment,
        database=database,
    )
    trim = _run_avl_trim_case(
        avl_path=avl_path,
        case_dir=role_dir / "avl_run",
        cl_required=float(cl_required),
        velocity_mps=float(mission_contract.speed_mps),
        density_kgpm3=float(mission_contract.rho),
        avl_binary=avl_binary,
    )
    fs_path = _run_avl_spanwise_case(
        avl_path=avl_path,
        case_dir=role_dir / "avl_run",
        alpha_deg=float(trim["aoa_trim_deg"]),
        velocity_mps=float(mission_contract.speed_mps),
        density_kgpm3=float(mission_contract.rho),
        avl_binary=avl_binary,
    )
    spanload = build_spanwise_load_from_avl_strip_forces(
        fs_path=fs_path,
        avl_path=avl_path,
        aoa_deg=float(trim["aoa_trim_deg"]),
        velocity_mps=float(mission_contract.speed_mps),
        density_kgpm3=float(mission_contract.rho),
        target_surface_names=("Wing",),
        positive_y_only=True,
    )
    rows = []
    for eta, y, chord, cl in zip(
        np.asarray(spanload.y, dtype=float) / max(0.5 * mission_contract.span_m, 1.0e-12),
        spanload.y,
        spanload.chord,
        spanload.cl,
        strict=True,
    ):
        rows.append(
            {
                "eta": float(eta),
                "y_m": float(y),
                "chord_m": float(chord),
                "avl_local_cl": float(cl),
                "cl_actual_avl": float(cl),
            }
        )
    profile = integrate_profile_drag_from_avl(
        mission_contract,
        rows,
        rows,
        zone_assignments(assignment),
        database,
        cl_source_shape_mode="selected_airfoil_loaded_shape_avl_rerun",
        cl_source_loaded_shape=True,
        cl_source_warning_count=0,
    )
    cdi = _float_or_none(trim.get("cd_induced"))
    cd_total = None if cdi is None else float(cdi) + float(profile.cd0_total_est)
    summary = {
        "selected_role": role,
        "assignment": selected_row.get("assignment", ""),
        "status": "selected_assignment_avl_rerun_ok",
        "selected_airfoil_avl": str(avl_path.resolve()),
        "selected_airfoil_fs": str(Path(fs_path).resolve()),
        "alpha_deg": trim.get("aoa_trim_deg", ""),
        "CL": trim.get("cl_trim", ""),
        "CDi": "" if cdi is None else float(cdi),
        "e_CDi": trim.get("span_efficiency", ""),
        "profile_cd": float(profile.CD_profile),
        "CD0_total": float(profile.cd0_total_est),
        "CD_total": "" if cd_total is None else float(cd_total),
        "P_crank": "" if cd_total is None else float(_power_w(mission_contract, cd_total) or 0.0),
        "P_crank_conservative": ""
        if cdi is None
        else float(_power_w(mission_contract, 1.05 * float(cdi) + float(profile.cd0_total_est)) or 0.0),
        "stall_margin_min": profile.min_stall_margin_deg,
        "max_station_utilization": profile.max_station_cl_utilization,
        "actual_query_quality": _profile_query_quality(profile),
        "profile_source_quality": profile.source_quality,
        "profile_warning_count": profile.station_warning_count,
        "drag_budget_band": profile.drag_budget_band,
    }
    station_rows = [
        {
            "selected_role": role,
            "combo_id": selected_row.get("combo_id", ""),
            "assignment": selected_row.get("assignment", ""),
            "profile_source": "selected_airfoil_loaded_shape_avl_rerun",
            **station,
        }
        for station in profile.station_rows
    ]
    return summary, station_rows


def _report_markdown(
    *,
    raw_best: Mapping[str, Any],
    conservative_best: Mapping[str, Any],
    assignment_payload: Mapping[str, Any],
    zone_rows: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "# Tier2 Loaded-Shape Airfoil MVP",
        "",
        "This is a report-only MVP4 artifact. It does not change production ranking, add hard gates, rerun broad CST/NSGA, run broad FEM, or promote structure to final truth.",
        "",
        "## Source",
        "",
        f"- Cl/Re source: `{CL_RE_SOURCE}`.",
        "- Airfoil source: existing Tier2 full-alpha reusable database.",
        "- No broad CST/NSGA rerun was performed.",
        "",
        "## Zone Requirements",
        "",
        "| zone | Re min | Re p50 | Re max | Cl p50 | Cl p90 | Cl max | current airfoil |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in zone_rows:
        lines.append(
            "| {zone} | {re_min} | {re_p50} | {re_max} | {cl_p50} | {cl_p90} | {cl_max} | {current} |".format(
                zone=row.get("zone_name", ""),
                re_min=_fmt(row.get("re_min"), 0),
                re_p50=_fmt(row.get("re_p50"), 0),
                re_max=_fmt(row.get("re_max"), 0),
                cl_p50=_fmt(row.get("cl_p50"), 3),
                cl_p90=_fmt(row.get("cl_p90"), 3),
                cl_max=_fmt(row.get("cl_max"), 3),
                current=row.get("current_airfoil_id", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Selected Assignments",
            "",
            "| role | assignment | profile CD | CD0 total | P crank | P crank cons. | stall margin min | query quality |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in (raw_best, conservative_best):
        lines.append(
            "| {role} | `{assignment}` | {profile} | {cd0} | {power} | {power_c} | {stall} | {quality} |".format(
                role=row.get("selected_role", ""),
                assignment=row.get("assignment", ""),
                profile=_fmt(row.get("profile_cd"), 6),
                cd0=_fmt(row.get("CD0_total"), 6),
                power=_fmt(row.get("P_crank"), 2),
                power_c=_fmt(row.get("P_crank_conservative"), 2),
                stall=_fmt(row.get("stall_margin_min"), 3),
                quality=row.get("actual_query_quality", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Engineering Read",
            "",
            "- The assignment is based on MVP3 loaded-shape AVL actual local Cl/Re, not Fourier target Cl.",
            "- Raw best and conservative production-quality best are intentionally separate; raw drag advantage is not a production decision by itself.",
            "- If the conservative row carries warnings, treat MVP4 as diagnostic and loop back through airfoil database coverage or loaded-shape definition instead of forcing a design decision.",
            "- MVP3 still uses a beam-line loaded-Z proxy, so this airfoil result is a screening input to MVP5 closure, not final wing truth.",
            "",
            "## Artifact Trace",
            "",
            f"- combo count: {assignment_payload.get('combo_count', '')}",
            f"- profile station rows: {assignment_payload.get('profile_station_row_count', '')}",
            "- required outputs: `tier2_loaded_shape_airfoil_assignment.json`, `tier2_loaded_shape_combo_search.csv`, `tier2_loaded_shape_profile_drag.csv`, `tier2_loaded_shape_airfoil_report.md`",
        ]
    )
    return "\n".join(lines) + "\n"


def run_mvp(
    *,
    stage6_dir: Path = DEFAULT_STAGE6_DIR,
    tier2_database_json: Path = DEFAULT_TIER2_DATABASE_JSON,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    rerun_avl: bool = True,
    top_k_per_zone: int = 5,
    max_combo_count: int = 240,
    avl_binary: str | Path | None = None,
) -> dict[str, Path]:
    summary_rows, stage6_rows = _load_stage6_inputs(Path(stage6_dir))
    summary_row = summary_rows[0] if summary_rows else None
    mission_contract = _mission_contract(summary_row=summary_row, stage6_rows=stage6_rows)
    current_assignment = _current_assignment_from_avl(summary_row)
    envelopes = build_zone_requirement_rows(
        stage6_rows=stage6_rows,
        mission_contract=mission_contract,
        current_assignment=current_assignment,
    )
    database = load_airfoil_database_artifact(Path(tier2_database_json))
    metadata = _read_record_metadata(Path(tier2_database_json))
    output_dir.mkdir(parents=True, exist_ok=True)

    zone_rows = [envelope.to_dict() for envelope in envelopes]
    pool_rows = build_candidate_pool_rows(
        envelopes=envelopes,
        stage6_rows=stage6_rows,
        database=database,
        metadata=metadata,
        current_assignment=current_assignment,
        top_k_per_zone=top_k_per_zone,
    )
    predicted = predicted_combo_rows(pool_rows=pool_rows, max_combo_count=max_combo_count)
    stage6_cdi = _float_or_none((summary_row or {}).get("loaded_shape_CDi"))
    evaluated, profile_rows = evaluate_combo_rows(
        combo_rows=predicted,
        stage6_rows=stage6_rows,
        mission_contract=mission_contract,
        database=database,
        stage6_cdi=stage6_cdi,
    )
    raw_best, conservative_best = _select_best_roles(evaluated)
    selected_rerun_rows: list[dict[str, Any]] = []
    if rerun_avl:
        for role, selected in (("raw_best", raw_best), ("conservative_best", conservative_best)):
            try:
                rerun_summary, station_rows = rerun_selected_assignment(
                    role=role,
                    selected_row=selected,
                    summary_row=summary_row,
                    output_dir=output_dir,
                    mission_contract=mission_contract,
                    database=database,
                    avl_binary=avl_binary,
                )
                selected_rerun_rows.append(rerun_summary)
                profile_rows.extend(station_rows)
                if role == "raw_best":
                    raw_best = {**raw_best, **rerun_summary}
                else:
                    conservative_best = {**conservative_best, **rerun_summary}
            except Exception as exc:  # pragma: no cover - external AVL/report path
                selected_rerun_rows.append(
                    {
                        "selected_role": role,
                        "assignment": selected.get("assignment", ""),
                        "status": "selected_assignment_avl_rerun_failed",
                        "error": str(exc),
                    }
                )
    else:
        profile_rows.extend(
            selected_profile_rows_from_stage6(
                role="raw_best",
                selected_row=raw_best,
                stage6_rows=stage6_rows,
                mission_contract=mission_contract,
                database=database,
            )
        )
        profile_rows.extend(
            selected_profile_rows_from_stage6(
                role="conservative_best",
                selected_row=conservative_best,
                stage6_rows=stage6_rows,
                mission_contract=mission_contract,
                database=database,
            )
        )

    assignment_payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage6_dir": str(Path(stage6_dir).resolve()),
        "tier2_database_json": str(Path(tier2_database_json).resolve()),
        "cl_re_source": CL_RE_SOURCE,
        "rerun_avl_requested": bool(rerun_avl),
        "mission_contract": {
            "speed_mps": mission_contract.speed_mps,
            "rho": mission_contract.rho,
            "dynamic_viscosity_pa_s": mission_contract.dynamic_viscosity_pa_s,
            "wing_area_m2": mission_contract.wing_area_m2,
            "span_m": mission_contract.span_m,
            "CDA_nonwing_target_m2": mission_contract.CDA_nonwing_target_m2,
        },
        "current_loaded_shape_assignment": dict(current_assignment),
        "raw_best": {
            "assignment": raw_best.get("assignment", ""),
            "summary": raw_best,
        },
        "conservative_best": {
            "assignment": conservative_best.get("assignment", ""),
            "summary": conservative_best,
        },
        "selected_avl_reruns": selected_rerun_rows,
        "combo_count": len(evaluated),
        "profile_station_row_count": len(profile_rows),
        "guardrails": [
            "production_ranking_unchanged",
            "no_hard_gates_added",
            "no_broad_cst_nsga_rerun",
            "no_broad_fem",
            "structure_not_final_truth",
        ],
    }

    paths = {
        "assignment": output_dir / "tier2_loaded_shape_airfoil_assignment.json",
        "combo_search": output_dir / "tier2_loaded_shape_combo_search.csv",
        "profile_drag": output_dir / "tier2_loaded_shape_profile_drag.csv",
        "report": output_dir / "tier2_loaded_shape_airfoil_report.md",
        "zone_requirements": output_dir / "tier2_loaded_shape_zone_requirements.csv",
        "zone_candidate_pool": output_dir / "tier2_loaded_shape_zone_candidate_pool.csv",
        "selected_avl_recheck": output_dir / "tier2_loaded_shape_selected_avl_recheck.csv",
    }
    paths["assignment"].write_text(
        json.dumps(assignment_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(paths["combo_search"], evaluated)
    _write_csv(paths["profile_drag"], profile_rows)
    _write_csv(paths["zone_requirements"], zone_rows)
    _write_csv(paths["zone_candidate_pool"], pool_rows)
    _write_csv(paths["selected_avl_recheck"], selected_rerun_rows)
    paths["report"].write_text(
        _report_markdown(
            raw_best=raw_best,
            conservative_best=conservative_best,
            assignment_payload=assignment_payload,
            zone_rows=zone_rows,
        ),
        encoding="utf-8",
    )
    return paths


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage6-dir", type=Path, default=DEFAULT_STAGE6_DIR)
    parser.add_argument("--tier2-database-json", type=Path, default=DEFAULT_TIER2_DATABASE_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-k-per-zone", type=int, default=5)
    parser.add_argument("--max-combo-count", type=int, default=240)
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument("--no-avl-rerun", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    paths = run_mvp(
        stage6_dir=args.stage6_dir,
        tier2_database_json=args.tier2_database_json,
        output_dir=args.output_dir,
        rerun_avl=not bool(args.no_avl_rerun),
        top_k_per_zone=int(args.top_k_per_zone),
        max_combo_count=int(args.max_combo_count),
        avl_binary=args.avl_binary,
    )
    print("[pipeline-v2] MVP4 Tier2 loaded-shape airfoil artifacts:")
    for path in paths.values():
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
