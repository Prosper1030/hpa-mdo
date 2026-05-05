from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    analyze_cst_geometry,
    build_seedless_cst_template,
    generate_cst_coordinates,
)
from hpa_mdo.concept.airfoil_selection import (
    _metrics_from_worker_result,
    _quantize_cl_for_screening,
    _quantize_reynolds_for_screening,
    _representative_cl_samples,
    _representative_reynolds,
    _run_batched_zone_candidate_queries,
    _zone_candidate_metrics,
)
from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker
from hpa_mdo.concept.config import load_concept_config
from hpa_mdo.concept.stall_model import compute_safe_local_clmax

from scripts.audit_seedless_selection_behavior import (
    CONFIG_PATH,
    HISTORICAL_FIT_JSON,
    REPORT_DIR,
    ZONE_NAMES,
    _markdown_table,
    _sanitize_airfoil_name,
    _write_csv,
    build_reference_zone_requirements,
)

PHASE6_REPORT = REPORT_DIR / "root_mid_requirement_sanity_phase6.md"
HISTORICAL_AIRFOILS = (
    "FX 76-MP-140",
    "DAE11",
    "DAE21",
    "DAE31",
    "DAE41",
)
SUCCESS_STATUSES = {"ok", "stubbed_ok", "mini_sweep_fallback"}


def _weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    if not values:
        return 0.0
    if not weights or len(weights) != len(values):
        weights = [1.0 for _ in values]
    total = sum(max(float(weight), 0.0) for weight in weights)
    if total <= 0.0:
        return sum(float(value) for value in values) / float(len(values))
    return sum(float(value) * max(float(weight), 0.0) for value, weight in zip(values, weights, strict=True)) / total


def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * min(max(float(q), 0.0), 1.0)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _scoring_weighted_cl(points: Sequence[Mapping[str, object]]) -> float:
    if not points:
        return 0.0
    weights = [max(float(point.get("weight", 1.0)), 0.0) for point in points]
    chords = [max(float(point.get("chord_m", 1.0)), 1.0e-9) for point in points]
    chord_reference = max(max(chords), _weighted_mean(chords, weights))
    effective_weights = [
        weight * chord / chord_reference
        for weight, chord in zip(weights, chords, strict=True)
    ]
    return _weighted_mean(
        [float(point["cl_target"]) for point in points],
        effective_weights,
    )


def summarize_design_points(
    zone_requirements: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for zone_name in ZONE_NAMES:
        payload = zone_requirements.get(zone_name, {})
        points = list(payload.get("points", []))
        y_values = [float(point.get("station_y_m", 0.0)) for point in points]
        re_values = [float(point["reynolds"]) for point in points]
        cl_values = [float(point["cl_target"]) for point in points]
        weights = [float(point.get("weight", 1.0)) for point in points]
        if not points:
            rows.append(
                {
                    "zone": zone_name,
                    "y_range_m": "",
                    "re_min": "",
                    "re_max": "",
                    "cl_min": "",
                    "cl_mean": "",
                    "cl_max": "",
                    "cl_target_samples": "",
                    "xfoil_representative_re": "",
                    "xfoil_target_cl_samples": "",
                    "source_file_function": (
                        "src/hpa_mdo/concept/zone_requirements.py::build_zone_requirements; "
                        "scripts/audit_seedless_selection_behavior.py::build_reference_zone_requirements"
                    ),
                }
            )
            continue
        xfoil_cl_samples = sorted(
            {
                _quantize_cl_for_screening(value)
                for value in _representative_cl_samples([dict(point) for point in points])
            }
        )
        rows.append(
            {
                "zone": zone_name,
                "y_range_m": f"{min(y_values):.3f}-{max(y_values):.3f}",
                "re_min": min(re_values),
                "re_max": max(re_values),
                "cl_min": min(cl_values),
                "cl_mean": _weighted_mean(cl_values, weights),
                "cl_max": max(cl_values),
                "cl_target_samples": ", ".join(f"{value:.3f}" for value in cl_values),
                "xfoil_representative_re": _quantize_reynolds_for_screening(
                    _representative_reynolds([dict(point) for point in points])
                ),
                "xfoil_target_cl_samples": ", ".join(f"{value:.2f}" for value in xfoil_cl_samples),
                "source_file_function": (
                    "production: src/hpa_mdo/concept/zone_requirements.py::build_zone_requirements; "
                    "phase6 artifact: scripts/audit_seedless_selection_behavior.py::build_reference_zone_requirements"
                ),
            }
        )
    return rows


def scale_zone_points_for_speed_weight(
    points: Sequence[Mapping[str, object]],
    *,
    speed_factor: float,
    weight_factor: float,
) -> tuple[dict[str, object], ...]:
    speed_factor = float(speed_factor)
    weight_factor = float(weight_factor)
    if speed_factor <= 0.0:
        raise ValueError("speed_factor must be positive.")
    if weight_factor <= 0.0:
        raise ValueError("weight_factor must be positive.")
    cl_scale = weight_factor / (speed_factor**2)
    scaled: list[dict[str, object]] = []
    for point in points:
        scaled.append(
            {
                **dict(point),
                "reynolds": float(point["reynolds"]) * speed_factor,
                "cl_target": float(point["cl_target"]) * cl_scale,
            }
        )
    return tuple(scaled)


def count_stall_passes_by_zone(
    feasibility_rows: Sequence[Mapping[str, object]],
    *,
    utilization_limit: float,
    utilization_field: str = "utilization",
) -> dict[str, int]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in feasibility_rows:
        grouped[(str(row["zone"]), str(row["airfoil"]))].append(row)

    counts: dict[str, int] = defaultdict(int)
    for (zone_name, _airfoil), rows in grouped.items():
        max_utilization = max(float(row[utilization_field]) for row in rows)
        status_ok = all(str(row.get("status", "ok")) in SUCCESS_STATUSES for row in rows)
        if status_ok and max_utilization <= float(utilization_limit):
            counts[zone_name] += 1
        else:
            counts.setdefault(zone_name, counts.get(zone_name, 0))
    return dict(counts)


def _historical_fit_rows() -> dict[str, Mapping[str, object]]:
    rows = json.loads(HISTORICAL_FIT_JSON.read_text(encoding="utf-8"))
    return {
        str(row["airfoil"]): row
        for row in rows
        if int(row["degree"]) == 6 and str(row["airfoil"]) in HISTORICAL_AIRFOILS
    }


def _load_all_historical_templates(zone_name: str) -> tuple[CSTAirfoilTemplate, ...]:
    by_name = _historical_fit_rows()
    templates: list[CSTAirfoilTemplate] = []
    for airfoil_name in HISTORICAL_AIRFOILS:
        row = by_name[airfoil_name]
        templates.append(
            build_seedless_cst_template(
                zone_name=zone_name,
                upper_coefficients=tuple(float(value) for value in row["upper_coefficients"]),
                lower_coefficients=tuple(float(value) for value in row["lower_coefficients"]),
                te_thickness_m=max(float(row["te_thickness"]), 1.0e-9),
                candidate_role=f"historical_{_sanitize_airfoil_name(airfoil_name)}",
            )
        )
    return tuple(templates)


def _historical_name_from_role(candidate_role: str) -> str:
    prefix = "historical_"
    role = str(candidate_role)
    if not role.startswith(prefix):
        return role
    slug = role[len(prefix) :]
    for name in HISTORICAL_AIRFOILS:
        if _sanitize_airfoil_name(name) == slug:
            return name
    return role


def _worker_metrics_by_mode(
    raw_results: Sequence[Mapping[str, object]],
) -> dict[str, list[dict[str, object]]]:
    by_mode: dict[str, list[dict[str, object]]] = defaultdict(list)
    for result in raw_results:
        metrics = _metrics_from_worker_result(result)
        if metrics is None:
            continue
        mode = str(result.get("roughness_mode", "unknown"))
        by_mode[mode].append({**metrics, "raw_result": result})
    return dict(by_mode)


def _min_usable_clmax(metrics: Sequence[Mapping[str, object]]) -> float:
    values = [
        float(item["usable_clmax"])
        for item in metrics
        if isinstance(item.get("usable_clmax"), int | float)
    ]
    return min(values) if values else 0.0


def _mode_raw_clmax(
    mode_metrics: Mapping[str, Sequence[Mapping[str, object]]],
    mode: str,
) -> float:
    clean = _min_usable_clmax(mode_metrics.get("clean", ()))
    rough = _min_usable_clmax(mode_metrics.get("rough", ()))
    if mode == "clean":
        return clean
    if mode == "rough":
        return rough
    if mode == "weighted":
        if clean <= 0.0:
            return rough
        if rough <= 0.0:
            return clean
        return 0.70 * clean + 0.30 * rough
    positive = [value for value in (clean, rough) if value > 0.0]
    return min(positive) if positive else 0.0


def _lower_bound_count(metrics: Sequence[Mapping[str, object]]) -> int:
    count = 0
    for item in metrics:
        raw_result = item.get("raw_result")
        if not isinstance(raw_result, Mapping):
            continue
        sweep_summary = raw_result.get("sweep_summary")
        if isinstance(sweep_summary, Mapping) and bool(sweep_summary.get("clmax_is_lower_bound")):
            count += 1
    return count


def _safe_clmax_for_point(*, raw_clmax: float, point: Mapping[str, object], cfg: Any) -> float:
    result = compute_safe_local_clmax(
        raw_clmax=float(raw_clmax),
        raw_source="airfoil_observed",
        span_fraction=float(point.get("span_fraction", 0.5)),
        taper_ratio=float(point.get("taper_ratio", 0.35)),
        washout_deg=float(point.get("washout_deg", 0.0)),
        safe_scale=float(cfg.stall_model.safe_clmax_scale),
        safe_delta=float(cfg.stall_model.safe_clmax_delta),
        tip_3d_penalty_start_eta=float(cfg.stall_model.tip_3d_penalty_start_eta),
        tip_3d_penalty_max=float(cfg.stall_model.tip_3d_penalty_max),
        tip_taper_penalty_weight=float(cfg.stall_model.tip_taper_penalty_weight),
        washout_relief_deg=float(cfg.stall_model.washout_relief_deg),
        washout_relief_max=float(cfg.stall_model.washout_relief_max),
    )
    return float(result.safe_clmax)


def _zone_points_with_cl_mode(
    points: Sequence[Mapping[str, object]],
    mode: str,
) -> tuple[dict[str, object], ...]:
    points_tuple = tuple(dict(point) for point in points)
    if mode == "current":
        return points_tuple
    cl_values = [float(point["cl_target"]) for point in points_tuple]
    if mode == "mean":
        target = sum(cl_values) / float(len(cl_values)) if cl_values else 0.0
    elif mode == "q75":
        target = _quantile(cl_values, 0.75)
    elif mode == "max":
        target = max(cl_values) if cl_values else 0.0
    elif mode == "weighted":
        target = _scoring_weighted_cl(points_tuple)
    else:
        raise ValueError(f"unsupported cl target mode: {mode!r}")
    return tuple({**point, "cl_target": target} for point in points_tuple)


def _raw_results_by_zone_role(
    worker_results: Iterable[Mapping[str, object]],
) -> dict[tuple[str, str], list[Mapping[str, object]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for result in worker_results:
        grouped[(str(result.get("zone_name")), str(result.get("candidate_role")))].append(result)
    return dict(grouped)


def build_historical_stall_rows(
    *,
    zone_requirements: Mapping[str, Mapping[str, object]],
    historical_templates_by_zone: Mapping[str, Sequence[CSTAirfoilTemplate]],
    historical_results_by_zone: Mapping[str, Mapping[str, Mapping[str, object]]],
    worker_results: Sequence[Mapping[str, object]],
    cfg: Any,
    clmax_mode: str = "min",
    cl_target_mode: str = "current",
    speed_factor: float = 1.0,
    weight_factor: float = 1.0,
) -> list[dict[str, object]]:
    raw_by_zone_role = _raw_results_by_zone_role(worker_results)
    rows: list[dict[str, object]] = []
    for zone_name in ZONE_NAMES:
        points = list(zone_requirements[zone_name]["points"])
        points = list(_zone_points_with_cl_mode(points, cl_target_mode))
        points = list(
            scale_zone_points_for_speed_weight(
                points,
                speed_factor=speed_factor,
                weight_factor=weight_factor,
            )
        )
        for template in historical_templates_by_zone[zone_name]:
            airfoil_name = _historical_name_from_role(template.candidate_role)
            candidate_result = historical_results_by_zone.get(zone_name, {}).get(
                template.candidate_role,
                {},
            )
            raw_results = raw_by_zone_role.get((zone_name, template.candidate_role), ())
            mode_metrics = _worker_metrics_by_mode(raw_results)
            clean_clmax = _mode_raw_clmax(mode_metrics, "clean")
            rough_clmax = _mode_raw_clmax(mode_metrics, "rough")
            raw_clmax = _mode_raw_clmax(mode_metrics, clmax_mode)
            status = "ok" if raw_clmax > 0.0 else "analysis_failed"
            if clmax_mode == "min":
                status = str(candidate_result.get("status", status))
            geometry = analyze_cst_geometry(template)
            coordinates = generate_cst_coordinates(template)
            metrics = (
                _zone_candidate_metrics(
                    zone_points=[dict(point) for point in points],
                    mean_cd=float(candidate_result.get("mean_cd", float("inf"))),
                    mean_cm=float(candidate_result.get("mean_cm", 0.0)),
                    usable_clmax=float(raw_clmax),
                    zone_min_tc_ratio=float(zone_requirements[zone_name]["min_tc_ratio"]),
                    coordinates=coordinates,
                    polar_points=(
                        candidate_result.get("polar_points")
                        if isinstance(candidate_result.get("polar_points"), list)
                        else None
                    ),
                    safe_clmax_scale=float(cfg.stall_model.safe_clmax_scale),
                    safe_clmax_delta=float(cfg.stall_model.safe_clmax_delta),
                    tip_3d_penalty_start_eta=float(cfg.stall_model.tip_3d_penalty_start_eta),
                    tip_3d_penalty_max=float(cfg.stall_model.tip_3d_penalty_max),
                    tip_taper_penalty_weight=float(cfg.stall_model.tip_taper_penalty_weight),
                    washout_relief_deg=float(cfg.stall_model.washout_relief_deg),
                    washout_relief_max=float(cfg.stall_model.washout_relief_max),
                    launch_stall_utilization_limit=float(cfg.stall_model.launch_utilization_limit),
                    turn_stall_utilization_limit=float(cfg.stall_model.turn_utilization_limit),
                    local_stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
                )
                if raw_clmax > 0.0
                else {}
            )
            cm_pass = float(candidate_result.get("mean_cm", 0.0)) >= float(
                cfg.cst_search.cm_hard_lower_bound
            )
            tc_pass = float(geometry.max_thickness_ratio) >= float(
                zone_requirements[zone_name]["min_tc_ratio"]
            )
            for point_index, point in enumerate(points, start=1):
                safe_clmax = _safe_clmax_for_point(
                    raw_clmax=raw_clmax,
                    point=point,
                    cfg=cfg,
                )
                utilization = float(point["cl_target"]) / max(safe_clmax, 1.0e-9)
                pass_fail = (
                    "pass"
                    if status in SUCCESS_STATUSES
                    and utilization <= float(cfg.stall_model.local_stall_utilization_limit)
                    else "fail"
                )
                rows.append(
                    {
                        "zone": zone_name,
                        "airfoil": airfoil_name,
                        "point": point_index,
                        "Re": float(point["reynolds"]),
                        "cl_target": float(point["cl_target"]),
                        "clean_clmax": clean_clmax,
                        "rough_clmax": rough_clmax,
                        "raw_clmax_mode": clmax_mode,
                        "safe_clmax": safe_clmax,
                        "utilization": utilization,
                        "required_utilization_limit": float(cfg.stall_model.local_stall_utilization_limit),
                        "pass_fail": pass_fail,
                        "status": status,
                        "robust_pass_rate": float(candidate_result.get("robust_pass_rate", 0.0)),
                        "mean_cd": float(candidate_result.get("mean_cd", float("inf"))),
                        "mean_cm": float(candidate_result.get("mean_cm", 0.0)),
                        "tc": float(geometry.max_thickness_ratio),
                        "cm_pass": cm_pass,
                        "tc_pass": tc_pass,
                        "zone_worst_utilization": float(metrics.get("stall_utilization", utilization))
                        if metrics
                        else utilization,
                        "zone_worst_margin": float(metrics.get("worst_case_margin", float("nan")))
                        if metrics
                        else float("nan"),
                        "clean_clmax_lower_bound_count": _lower_bound_count(
                            mode_metrics.get("clean", ())
                        ),
                        "rough_clmax_lower_bound_count": _lower_bound_count(
                            mode_metrics.get("rough", ())
                        ),
                    }
                )
    return rows


def _scenario_row(
    name: str,
    rows: Sequence[Mapping[str, object]],
    *,
    utilization_limit: float,
    interpretation: str,
) -> dict[str, object]:
    counts = count_stall_passes_by_zone(rows, utilization_limit=utilization_limit)
    return {
        "scenario": name,
        "root_pass_count": counts.get("root", 0),
        "mid1_pass_count": counts.get("mid1", 0),
        "mid2_pass_count": counts.get("mid2", 0),
        "tip_pass_count": counts.get("tip", 0),
        "interpretation": interpretation,
    }


def build_counterfactual_rows(
    *,
    zone_requirements: Mapping[str, Mapping[str, object]],
    historical_templates_by_zone: Mapping[str, Sequence[CSTAirfoilTemplate]],
    historical_results_by_zone: Mapping[str, Mapping[str, Mapping[str, object]]],
    worker_results: Sequence[Mapping[str, object]],
    cfg: Any,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    current_rows = build_historical_stall_rows(
        zone_requirements=zone_requirements,
        historical_templates_by_zone=historical_templates_by_zone,
        historical_results_by_zone=historical_results_by_zone,
        worker_results=worker_results,
        cfg=cfg,
        clmax_mode="min",
    )
    for limit in (0.75, 0.80, 0.85, 0.90):
        rows.append(
            _scenario_row(
                f"A utilization <= {limit:.2f}",
                current_rows,
                utilization_limit=limit,
                interpretation="Threshold-only sweep on historical reference set.",
            )
        )

    for mode, label in (
        ("clean", "B clean-only clmax"),
        ("rough", "B rough-only clmax"),
        ("min", "B min(clean,rough) clmax"),
        ("weighted", "B 70/30 clean/rough clmax"),
    ):
        scenario_rows = build_historical_stall_rows(
            zone_requirements=zone_requirements,
            historical_templates_by_zone=historical_templates_by_zone,
            historical_results_by_zone=historical_results_by_zone,
            worker_results=worker_results,
            cfg=cfg,
            clmax_mode=mode,
        )
        rows.append(
            _scenario_row(
                label,
                scenario_rows,
                utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
                interpretation="Checks whether rough-mode robust min is the blocker.",
            )
        )

    for mode, label in (
        ("mean", "C mean zone cl"),
        ("q75", "C 75% quantile zone cl"),
        ("max", "C max station cl"),
        ("weighted", "C scoring-weighted zone cl"),
    ):
        scenario_rows = build_historical_stall_rows(
            zone_requirements=zone_requirements,
            historical_templates_by_zone=historical_templates_by_zone,
            historical_results_by_zone=historical_results_by_zone,
            worker_results=worker_results,
            cfg=cfg,
            clmax_mode="min",
            cl_target_mode=mode,
        )
        rows.append(
            _scenario_row(
                label,
                scenario_rows,
                utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
                interpretation="Checks whether a high local station dominates the zone representative demand.",
            )
        )

    for speed_factor, weight_factor, label in (
        (1.05, 1.0, "D cruise speed +5%"),
        (1.10, 1.0, "D cruise speed +10%"),
        (1.0, 0.95, "D weight -5%"),
        (1.0, 1.05, "D weight +5%"),
    ):
        scenario_rows = build_historical_stall_rows(
            zone_requirements=zone_requirements,
            historical_templates_by_zone=historical_templates_by_zone,
            historical_results_by_zone=historical_results_by_zone,
            worker_results=worker_results,
            cfg=cfg,
            clmax_mode="min",
            speed_factor=speed_factor,
            weight_factor=weight_factor,
        )
        rows.append(
            _scenario_row(
                label,
                scenario_rows,
                utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
                interpretation=(
                    "Demand-only approximation: cl_target scales with W/V^2; "
                    "XFOIL clmax was not rerun at the scaled Reynolds."
                ),
            )
        )

    return rows


def stall_gate_formula_rows(cfg: Any) -> list[dict[str, object]]:
    return [
        {
            "item": "safe_clmax source",
            "current_formula_value": (
                "raw usable_clmax comes from XFOIL full_alpha_sweep; robust aggregate uses "
                "min usable_clmax across successful Re/roughness conditions"
            ),
            "source_file_function": (
                "src/hpa_mdo/concept/airfoil_selection.py::_aggregate_worker_condition_metrics"
            ),
            "notes": "Phase 6 tables split clean and rough raw clmax before this min aggregation.",
        },
        {
            "item": "safe_clmax model",
            "current_formula_value": (
                f"safe = max(0.10, adjusted_scale*raw - adjusted_delta - tip_3d_penalty); "
                f"airfoil_observed adjusted_scale={min(1.0, float(cfg.stall_model.safe_clmax_scale) + 0.02):.2f}, "
                f"adjusted_delta={max(0.0, float(cfg.stall_model.safe_clmax_delta) - 0.01):.2f}"
            ),
            "source_file_function": "src/hpa_mdo/concept/stall_model.py::compute_safe_local_clmax",
            "notes": "Config values are safe_clmax_scale=0.90 and safe_clmax_delta=0.05 before airfoil_observed adjustment.",
        },
        {
            "item": "local utilization gate",
            "current_formula_value": (
                f"utilization = cl_target / safe_clmax; pass when utilization <= "
                f"{float(cfg.stall_model.local_stall_utilization_limit):.2f}"
            ),
            "source_file_function": "src/hpa_mdo/concept/airfoil_selection.py::_zone_candidate_metrics",
            "notes": "worst_case_margin = case_limit - utilization; hard gate fails when margin < 0.",
        },
        {
            "item": "clean vs rough",
            "current_formula_value": (
                f"production factors={tuple(cfg.cst_search.robust_reynolds_factors)}, "
                f"roughness_modes={tuple(cfg.cst_search.robust_roughness_modes)}"
            ),
            "source_file_function": "src/hpa_mdo/concept/airfoil_selection.py::_zone_queries_for_candidates",
            "notes": "Clean uses ncrit=9 xtrip=(1,1); rough uses ncrit=5 xtrip=(0.05,0.05).",
        },
        {
            "item": "XFOIL sweep range",
            "current_formula_value": (
                "full_alpha_sweep alpha = -4:0.5:alpha_max; "
                "alpha_max = min(18, max(12, 5 + 14*max_abs_cl_sample))"
            ),
            "source_file_function": "tools/julia/xfoil_worker/xfoil_worker.jl::alpha_grid",
            "notes": "Root/mid target CL pushes alpha_max to the 18 deg cap; clmax_is_lower_bound flags are reported.",
        },
        {
            "item": "target CL samples",
            "current_formula_value": (
                "XFOIL cl_samples are unique zone cl_target values rounded to 0.01; "
                "Re is a weighted representative zone Reynolds rounded to 5000"
            ),
            "source_file_function": (
                "src/hpa_mdo/concept/airfoil_selection.py::_zone_queries_for_candidates"
            ),
            "notes": "Station Re min/max are retained in the requirement table but not queried one-by-one.",
        },
    ]


def _load_phase5_feasibility_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_phase6_report(
    *,
    output_dir: Path,
    design_rows: Sequence[Mapping[str, object]],
    formula_rows: Sequence[Mapping[str, object]],
    historical_rows: Sequence[Mapping[str, object]],
    counterfactual_rows: Sequence[Mapping[str, object]],
    phase5_rows: Sequence[Mapping[str, object]],
    cfg: Any,
    worker_result_count: int,
) -> None:
    root_mid_hist = [
        row for row in historical_rows if row.get("zone") in {"root", "mid1", "mid2"}
    ]
    current_counts = count_stall_passes_by_zone(
        historical_rows,
        utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
    )
    best_by_zone: list[dict[str, object]] = []
    for zone_name in ZONE_NAMES:
        zone_rows = [row for row in historical_rows if row.get("zone") == zone_name]
        if not zone_rows:
            continue
        grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
        for row in zone_rows:
            grouped[str(row["airfoil"])].append(row)
        best_airfoil = min(
            grouped.items(),
            key=lambda item: max(float(row["utilization"]) for row in item[1]),
        )
        best_by_zone.append(
            {
                "zone": zone_name,
                "best_historical_airfoil": best_airfoil[0],
                "best_utilization": max(float(row["utilization"]) for row in best_airfoil[1]),
                "best_safe_clmax": min(float(row["safe_clmax"]) for row in best_airfoil[1]),
                "best_status": "; ".join(sorted({str(row["status"]) for row in best_airfoil[1]})),
                "current_pass_count": current_counts.get(zone_name, 0),
            }
        )

    phase5_medium_rows = [
        row for row in phase5_rows if str(row.get("scale")) == "medium"
    ] or phase5_rows

    lines: list[str] = [
        "# Phase 6 Root/Mid Zone Requirement Sanity Audit",
        "",
        "This audit keeps CST degree, seedless bounds, and stall defaults unchanged. It asks whether the current root/mid local CL demand is compatible with historical low-Re sections before changing the optimizer.",
        "",
        "## Design Point Source",
        "",
        "Production zone requirements are built from `SpanwiseLoad` and stations via `src/hpa_mdo/concept/zone_requirements.py::build_zone_requirements`, then attached to concept evaluation in `src/hpa_mdo/concept/pipeline.py`. This Phase 6 artifact uses the same representative station rows embedded by Phase 4/5 in `scripts/audit_seedless_selection_behavior.py::build_reference_zone_requirements` so the audit is reproducible without rerunning AVL.",
        "",
    ]
    lines.extend(
        _markdown_table(
            design_rows,
            (
                "zone",
                "y_range_m",
                "re_min",
                "re_max",
                "cl_min",
                "cl_mean",
                "cl_max",
                "cl_target_samples",
                "xfoil_representative_re",
                "xfoil_target_cl_samples",
                "source_file_function",
            ),
        )
    )
    lines.extend(["", "## Stall Gate Math", ""])
    lines.extend(
        _markdown_table(
            formula_rows,
            ("item", "current_formula_value", "source_file_function", "notes"),
        )
    )
    lines.extend(
        [
            "",
            "## Phase 5 Seedless Feasibility Context",
            "",
            "These rows are read from the existing Phase 5 artifact; Phase 6 does not rerun a seedless campaign.",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            phase5_medium_rows,
            (
                "scale",
                "zone",
                "feasible_geometry_candidates",
                "coarse_scored",
                "robust_scored",
                "hard_gate_pass_count",
                "stall_pass_count",
                "cm_pass_count",
                "tc_pass_count",
                "spar_pass_count",
                "best_stall_margin",
                "dominant_failures",
            ),
        )
    )
    lines.extend(["", "## Historical Root/Mid Stall Feasibility", ""])
    lines.extend(
        _markdown_table(
            root_mid_hist,
            (
                "zone",
                "airfoil",
                "point",
                "Re",
                "cl_target",
                "clean_clmax",
                "rough_clmax",
                "safe_clmax",
                "utilization",
                "required_utilization_limit",
                "pass_fail",
                "status",
                "tc",
                "tc_pass",
                "mean_cm",
                "cm_pass",
            ),
        )
    )
    lines.extend(["", "## Best Historical Utilization", ""])
    lines.extend(
        _markdown_table(
            best_by_zone,
            (
                "zone",
                "best_historical_airfoil",
                "best_utilization",
                "best_safe_clmax",
                "best_status",
                "current_pass_count",
            ),
        )
    )
    lines.extend(["", "## Counterfactual Sweeps", ""])
    lines.extend(
        _markdown_table(
            counterfactual_rows,
            (
                "scenario",
                "root_pass_count",
                "mid1_pass_count",
                "mid2_pass_count",
                "tip_pass_count",
                "interpretation",
            ),
        )
    )

    lines.extend(
        [
            "",
            "## Engineering Judgment",
            "",
            "- Root/mid fail is primarily a local-CL demand versus safe-clmax contract issue, not a CST coverage issue. The Phase 5 seedless set and the historical references both fail root/mid mainly by stall utilization.",
            "- The most effective counterfactual in this historical-reference set is demand reduction from speed +10%: it recovers one root reference and three mid2 references, while mid1 still has zero passes. The mean/weighted CL representative-point tests mainly help the tip; they do not rescue root or mid1 at the current 0.75 utilization limit.",
            "- Rough mode is not the sole cause. Clean-only helps tip count but leaves root/mid at zero passes, so the blocker is not just forced transition being too conservative.",
            "- A fixed 0.75 utilization limit across root and tip may be overly blunt for stall sequencing. From an aircraft-design perspective, tip should usually retain the stricter margin; root/mid may tolerate higher utilization only if 3D screening confirms root-first stall, acceptable trim, and enough maneuver margin.",
            "- Root remains a special conflict zone: `t/c >= 0.14`, high local CL, and Cm limit can reject historically plausible thin sections even when their aerodynamics are otherwise useful.",
            "- Tip/outboard sanity remains intact in the historical reference set: DAE21 and DAE31 pass the current tip stall utilization check, so the evidence still points inward rather than to a global XFOIL or CST failure.",
            "- Do not relax the default stall gate from this audit alone. First inspect the 3D loading source: twist, chord, spanload target, and whether the zone representative CL should be max-station or weighted mission demand.",
            "- Limited 3D combination screening can proceed for outboard/tip and as a diagnostic for root/mid, but root/mid should carry `NO FEASIBLE CANDIDATE` or `infeasible_best_effort` labels until the loading/gate contract is settled.",
            "",
            "## Artifacts",
            "",
            f"- `root_mid_design_points_phase6.csv`",
            f"- `root_mid_stall_formula_phase6.csv`",
            f"- `root_mid_historical_stall_feasibility_phase6.csv`",
            f"- `root_mid_counterfactuals_phase6.csv`",
            f"- `run_summary_phase6.json`",
            "",
            f"Worker result count: {worker_result_count}",
        ]
    )
    (output_dir / PHASE6_REPORT.name).write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def run_audit(args: argparse.Namespace) -> dict[str, object]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_concept_config(args.config)
    zone_requirements = build_reference_zone_requirements()
    historical_templates_by_zone = {
        zone_name: _load_all_historical_templates(zone_name)
        for zone_name in ZONE_NAMES
    }
    zone_points_by_name = {
        zone_name: [dict(point) for point in payload["points"]]
        for zone_name, payload in zone_requirements.items()
    }
    worker = JuliaXFoilWorker(
        project_dir=Path("."),
        cache_dir=output_dir / "polar_db",
        persistent_mode=not args.no_persistent_worker,
        persistent_worker_count=int(args.worker_count),
        xfoil_max_iter=int(cfg.polar_worker.xfoil_max_iter),
        xfoil_panel_count=int(cfg.polar_worker.xfoil_panel_count),
    )
    try:
        historical_results_by_zone, worker_results = _run_batched_zone_candidate_queries(
            zone_candidates=historical_templates_by_zone,
            zone_points_by_name=zone_points_by_name,
            worker=worker,
            robust_evaluation_enabled=True,
            robust_reynolds_factors=tuple(cfg.cst_search.robust_reynolds_factors),
            robust_roughness_modes=tuple(cfg.cst_search.robust_roughness_modes),
            robust_min_pass_rate=float(cfg.cst_search.robust_min_pass_rate),
            stage_label="phase6_historical_baseline",
        )
    finally:
        worker.close()

    design_rows = summarize_design_points(zone_requirements)
    formula_rows = stall_gate_formula_rows(cfg)
    historical_rows = build_historical_stall_rows(
        zone_requirements=zone_requirements,
        historical_templates_by_zone=historical_templates_by_zone,
        historical_results_by_zone=historical_results_by_zone,
        worker_results=worker_results,
        cfg=cfg,
    )
    counterfactual_rows = build_counterfactual_rows(
        zone_requirements=zone_requirements,
        historical_templates_by_zone=historical_templates_by_zone,
        historical_results_by_zone=historical_results_by_zone,
        worker_results=worker_results,
        cfg=cfg,
    )
    phase5_rows = _load_phase5_feasibility_rows(output_dir / "phase5_feasibility_stats.csv")

    _write_csv(output_dir / "root_mid_design_points_phase6.csv", design_rows)
    _write_csv(output_dir / "root_mid_stall_formula_phase6.csv", formula_rows)
    _write_csv(
        output_dir / "root_mid_historical_stall_feasibility_phase6.csv",
        historical_rows,
    )
    _write_csv(output_dir / "root_mid_counterfactuals_phase6.csv", counterfactual_rows)
    _write_phase6_report(
        output_dir=output_dir,
        design_rows=design_rows,
        formula_rows=formula_rows,
        historical_rows=historical_rows,
        counterfactual_rows=counterfactual_rows,
        phase5_rows=phase5_rows,
        cfg=cfg,
        worker_result_count=len(worker_results),
    )
    payload = {
        "config": str(args.config),
        "historical_airfoils": list(HISTORICAL_AIRFOILS),
        "robust_reynolds_factors": list(cfg.cst_search.robust_reynolds_factors),
        "robust_roughness_modes": list(cfg.cst_search.robust_roughness_modes),
        "design_rows": design_rows,
        "stall_formula_rows": formula_rows,
        "historical_rows": historical_rows,
        "counterfactual_rows": counterfactual_rows,
        "phase5_feasibility_rows": phase5_rows,
        "worker_result_count": len(worker_results),
    }
    (output_dir / "run_summary_phase6.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit root/mid low-Re airfoil requirement sanity without changing defaults.",
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--worker-count", type=int, default=4)
    parser.add_argument("--no-persistent-worker", action="store_true")
    return parser.parse_args()


def main() -> None:
    run_audit(parse_args())


if __name__ == "__main__":
    main()
