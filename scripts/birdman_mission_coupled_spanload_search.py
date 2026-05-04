#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config  # noqa: E402
from hpa_mdo.concept.geometry import GeometryConcept  # noqa: E402

import scripts.birdman_spanload_design_smoke as spanload_smoke  # noqa: E402


DEFAULT_DESIGN_SPEEDS_MPS = (6.0, 6.2, 6.4, 6.6, 6.8, 7.0)
DEFAULT_MISSION_SPEED_GRID_MPS = (6.4, 6.6, 6.8, 7.0, 7.2)


def allocate_stage1_budget(
    *,
    design_speeds_mps: tuple[float, ...],
    stage1_top_k: int,
) -> dict[float, int]:
    speeds = tuple(float(speed) for speed in design_speeds_mps)
    if not speeds:
        return {}
    total = max(0, int(stage1_top_k))
    base = total // len(speeds)
    remainder = total % len(speeds)
    return {
        speed: base + (1 if index < remainder else 0)
        for index, speed in enumerate(speeds)
    }


def _induced_cd_from_e(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    speed_mps: float,
    avl_e_cdi: float,
) -> tuple[float, float]:
    air = spanload_smoke._air_properties(cfg)
    q_pa = 0.5 * float(air.density_kg_per_m3) * float(speed_mps) ** 2
    cl = (
        float(cfg.mass.design_gross_mass_kg)
        * spanload_smoke.G_MPS2
        / max(q_pa * float(concept.wing_area_m2), 1.0e-9)
    )
    induced_cd = cl**2 / max(
        math.pi * float(concept.aspect_ratio) * float(avl_e_cdi),
        1.0e-9,
    )
    return float(cl), float(induced_cd)


def _max_duration_for_power_s(
    cfg: BirdmanConceptConfig,
    *,
    power_required_w: float,
    target_duration_s: float,
) -> float:
    if power_required_w <= spanload_smoke._pilot_available_power_w(
        cfg,
        duration_s=target_duration_s,
    ):
        return float(target_duration_s)
    one_minute_s = 60.0
    if power_required_w > spanload_smoke._pilot_available_power_w(cfg, duration_s=one_minute_s):
        return 0.0
    low = one_minute_s
    high = float(target_duration_s)
    for _ in range(40):
        mid = 0.5 * (low + high)
        if spanload_smoke._pilot_available_power_w(cfg, duration_s=mid) >= power_required_w:
            low = mid
        else:
            high = mid
    return float(low)


def mission_speed_sweep(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    avl_e_cdi: float | None,
    speed_grid_mps: tuple[float, ...] = DEFAULT_MISSION_SPEED_GRID_MPS,
) -> dict[str, Any]:
    points: list[dict[str, Any]] = []
    if avl_e_cdi is None or float(avl_e_cdi) <= 0.0:
        return {
            "model": "fixed_airfoil_avl_e_cdi_scaled_power_proxy_v1",
            "status": "invalid_no_avl_e_cdi",
            "speed_grid_mps": [float(speed) for speed in speed_grid_mps],
            "points": [],
            "v_complete_max_mps": None,
            "t_complete_min_s": None,
            "best_complete_point": None,
            "max_range_if_not_complete_m": 0.0,
        }
    route_distance_m = float(cfg.mission.target_distance_km) * 1000.0
    for speed_mps in speed_grid_mps:
        cl, induced_cd = _induced_cd_from_e(
            cfg=cfg,
            concept=concept,
            speed_mps=float(speed_mps),
            avl_e_cdi=float(avl_e_cdi),
        )
        power = spanload_smoke._power_proxy_from_cdi(
            cfg=cfg,
            concept=concept,
            design_speed_mps=float(speed_mps),
            induced_cd=float(induced_cd),
            model="fixed_airfoil_avl_e_cdi_scaled_mission_power_proxy_v1",
        )
        duration_s = route_distance_m / max(float(speed_mps), 1.0e-9)
        complete = float(power["power_margin_w"]) >= 0.0
        max_duration_s = _max_duration_for_power_s(
            cfg,
            power_required_w=float(power["power_required_w"]),
            target_duration_s=duration_s,
        )
        points.append(
            {
                "speed_mps": float(speed_mps),
                "duration_s": float(duration_s),
                "duration_min": float(duration_s / 60.0),
                "complete": bool(complete),
                "available_power_w": float(power["available_power_w"]),
                "power_required_w": float(power["power_required_w"]),
                "power_margin_w": float(power["power_margin_w"]),
                "cl": float(cl),
                "cd_induced": float(induced_cd),
                "cd_total": float(power["total_cd"]),
                "profile_cd": float(power["profile_cd"]),
                "misc_cd": float(power["misc_cd"]),
                "rigging_cd": float(power["rigging_cd"]),
                "max_range_if_not_complete_m": min(
                    route_distance_m,
                    float(speed_mps) * float(max_duration_s),
                ),
            }
        )
    complete_points = [point for point in points if bool(point["complete"])]
    best_complete = (
        max(
            complete_points,
            key=lambda point: (
                float(point["speed_mps"]),
                float(point["power_margin_w"]),
            ),
        )
        if complete_points
        else None
    )
    return {
        "model": "fixed_airfoil_avl_e_cdi_scaled_power_proxy_v1",
        "profile_drag_note": "fixed_airfoil_no_xfoil_not_final_profile_drag",
        "speed_grid_mps": [float(speed) for speed in speed_grid_mps],
        "points": points,
        "v_complete_max_mps": None if best_complete is None else float(best_complete["speed_mps"]),
        "t_complete_min_s": None if best_complete is None else float(best_complete["duration_s"]),
        "best_complete_power_margin_w": None
        if best_complete is None
        else float(best_complete["power_margin_w"]),
        "best_complete_point": best_complete,
        "max_range_if_not_complete_m": max(
            (float(point["max_range_if_not_complete_m"]) for point in points),
            default=0.0,
        ),
    }


def _mission_tier(record: dict[str, Any]) -> tuple[int, str]:
    e_cdi = _record_avl_e_cdi(record)
    physical = bool(record.get("physical_acceptance", {}).get("physically_acceptable", False))
    if physical and e_cdi is not None and float(e_cdi) >= 0.88:
        return 0, "e_cdi_ge_0p88_primary"
    if physical and e_cdi is not None and float(e_cdi) >= 0.85:
        return 1, "e_cdi_0p85_to_0p88_diagnostic"
    return 2, "not_physically_accepted_or_e_below_0p85"


def rank_mission_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for record in records:
        tier, tier_name = _mission_tier(record)
        item = dict(record)
        item["mission_ranking_tier"] = tier_name
        item["_mission_rank_tier_index"] = tier
        enriched.append(item)
    ranked = sorted(
        enriched,
        key=lambda record: (
            int(record["_mission_rank_tier_index"]),
            -float(record.get("mission_speed_sweep", {}).get("v_complete_max_mps") or -1.0),
            -float(record.get("mission_speed_sweep", {}).get("best_complete_power_margin_w") or -1.0e9),
            _record_power_required_w(record),
            _record_mass_proxy_budget_warning(record),
            int(record.get("sample_index") or 0),
        ),
    )
    for record in ranked:
        record.pop("_mission_rank_tier_index", None)
    return ranked


def _record_geometry(record: dict[str, Any]) -> dict[str, Any]:
    geometry = record.get("geometry")
    if isinstance(geometry, dict):
        return geometry
    keys = ("span_m", "wing_area_m2", "aspect_ratio", "root_chord_m", "tip_chord_m", "taper_ratio")
    return {key: record.get(key) for key in keys if record.get(key) is not None}


def _record_avl_e_cdi(record: dict[str, Any]) -> float | None:
    value = record.get("avl_reference_case", {}).get("avl_e_cdi")
    if value is None:
        value = record.get("avl_e_cdi")
    return None if value is None else float(value)


def _record_power_required_w(record: dict[str, Any]) -> float:
    value = record.get("avl_cdi_power_proxy", {}).get("power_required_w")
    if value is None:
        value = record.get("avl_cdi_power_required_w")
    return float(value or float("inf"))


def _record_failure_reasons(record: dict[str, Any]) -> list[str]:
    reasons = record.get("physical_acceptance", {}).get("failure_reasons", record.get("failure_reasons", []))
    return [str(reason) for reason in reasons] if isinstance(reasons, list) else []


def _record_mass_proxy_budget_warning(record: dict[str, Any]) -> bool:
    value = record.get("mass_authority", {}).get("proxy_budget_warning")
    if value is None:
        value = record.get("mass_proxy_budget_warning", True)
    return bool(value)


def _records_matching_failure(records: list[dict[str, Any]], needles: tuple[str, ...]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for record in records:
        reasons = _record_failure_reasons(record)
        twist_failures = record.get("twist_gate_metrics", {}).get("twist_gate_failures", [])
        drivers = record.get("outer_loading_diagnostics", {}).get("e_cdi_loss_diagnosis", {}).get("drivers", [])
        haystack = " ".join([*reasons, *[str(item) for item in twist_failures], *[str(item) for item in drivers]])
        if any(needle in haystack for needle in needles):
            matched.append(record)
    return matched


def _compact_record(record: dict[str, Any]) -> dict[str, Any]:
    geometry = _record_geometry(record)
    outer_diagnostics = record.get("outer_loading_diagnostics") or {}
    mission_sweep = record.get("mission_speed_sweep") or {}
    chord_redistribution = record.get("outer_chord_redistribution") or {}
    trim_cd_induced = record.get("avl_reference_case", {}).get("trim_cd_induced")
    if trim_cd_induced is None:
        trim_cd_induced = record.get("trim_cd_induced")
    power_required_w = _record_power_required_w(record)
    return {
        "sample_index": record.get("sample_index"),
        "design_speed_mps": record.get("design_speed_mps"),
        "status": record.get("status"),
        "mission_ranking_tier": record.get("mission_ranking_tier"),
        "span_m": geometry.get("span_m"),
        "wing_area_m2": geometry.get("wing_area_m2"),
        "aspect_ratio": geometry.get("aspect_ratio"),
        "root_chord_m": geometry.get("root_chord_m"),
        "tip_chord_m": geometry.get("tip_chord_m"),
        "taper_ratio": geometry.get("taper_ratio"),
        "geometry": record.get("geometry"),
        "avl_e_cdi": _record_avl_e_cdi(record),
        "trim_cd_induced": trim_cd_induced,
        "avl_cdi_power_required_w": None if not math.isfinite(power_required_w) else power_required_w,
        "mission_speed_sweep": mission_sweep,
        "v_complete_max_mps": mission_sweep.get("v_complete_max_mps"),
        "t_complete_min_s": mission_sweep.get("t_complete_min_s"),
        "max_range_if_not_complete_m": mission_sweep.get("max_range_if_not_complete_m"),
        "best_complete_power_margin_w": mission_sweep.get("best_complete_power_margin_w"),
        "outer_underloaded": outer_diagnostics.get("outer_underloaded"),
        "outer_loading_diagnostics": record.get("outer_loading_diagnostics"),
        "outer_chord_bump_amp": record.get("outer_chord_bump_amp"),
        "outer_chord_redistribution": chord_redistribution,
        "min_chord_m": chord_redistribution.get("min_chord_m"),
        "chord_area_error_m2": chord_redistribution.get("half_area_error_m2"),
        "max_adjacent_chord_ratio": chord_redistribution.get("max_adjacent_chord_ratio"),
        "max_chord_second_difference_m": chord_redistribution.get("max_chord_second_difference_m"),
        "twist_gate_metrics": record.get("twist_gate_metrics"),
        "tip_gate_summary": record.get("tip_gate_summary"),
        "physical_acceptance": record.get("physical_acceptance"),
        "failure_reasons": _record_failure_reasons(record),
        "mass_proxy_budget_warning": _record_mass_proxy_budget_warning(record),
    }


def build_leaderboards(records: list[dict[str, Any]], *, count: int = 5) -> dict[str, list[dict[str, Any]]]:
    physical = [
        record
        for record in records
        if bool(record.get("physical_acceptance", {}).get("physically_acceptable", False))
    ]
    rejected = [record for record in records if record not in physical]
    mission_ranked = rank_mission_candidates(records)
    e85_diagnostic = [
        record
        for record in physical
        if (_record_avl_e_cdi(record) is not None and 0.85 <= float(_record_avl_e_cdi(record)) < 0.88)
    ]
    twist_rejected = _records_matching_failure(rejected, ("twist", "washout", "washin", "jump"))
    tip_local_rejected = _records_matching_failure(
        rejected,
        ("tip", "local", "outer_cl", "cl_utilization", "spanload_local_or_outer"),
    )

    def by_e_desc(record: dict[str, Any]) -> tuple[float, int]:
        return (float(_record_avl_e_cdi(record) or -1.0), -int(record.get("sample_index") or 0))

    def compact_many(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [_compact_record(record) for record in items[: int(count)]]

    return {
        "best_mission_candidate": compact_many(mission_ranked),
        "highest_AR_engineering_candidate": compact_many(
            sorted(physical, key=lambda record: float(_record_geometry(record).get("aspect_ratio") or -1.0), reverse=True)
        ),
        "best_AVL_e_CDi_candidate": compact_many(sorted(physical, key=by_e_desc, reverse=True)),
        "best_AVL_CDi_power_proxy_candidate": compact_many(sorted(physical, key=_record_power_required_w)),
        "diagnostic_e85_to_e88_candidate": compact_many(sorted(e85_diagnostic, key=by_e_desc, reverse=True)),
        "closest_rejected_due_to_twist": compact_many(sorted(twist_rejected, key=by_e_desc, reverse=True)),
        "closest_rejected_due_to_tip_local_cl": compact_many(sorted(tip_local_rejected, key=by_e_desc, reverse=True)),
    }


def _evaluate_metric(
    *,
    cfg: BirdmanConceptConfig,
    metric: dict[str, Any],
    design_speed_mps: float,
    output_dir: Path,
    avl_binary: str | None,
    optimizer_maxfev: int,
    optimizer_maxiter: int,
    optimize_spanload_coefficients: bool,
    mission_speed_grid_mps: tuple[float, ...],
) -> dict[str, Any]:
    record = spanload_smoke._optimize_regularized_twist_candidate(
        cfg=cfg,
        stage0_metric=metric,
        output_dir=output_dir,
        design_speed_mps=float(design_speed_mps),
        avl_binary=avl_binary,
        optimizer_maxfev=int(optimizer_maxfev),
        optimizer_maxiter=int(optimizer_maxiter),
        optimize_spanload_coefficients=bool(optimize_spanload_coefficients),
    )
    record["design_speed_mps"] = float(design_speed_mps)
    record["mission_speed_sweep"] = mission_speed_sweep(
        cfg=cfg,
        concept=metric["concept"],
        avl_e_cdi=record.get("avl_reference_case", {}).get("avl_e_cdi"),
        speed_grid_mps=mission_speed_grid_mps,
    )
    return record


def run_search(
    *,
    cfg: BirdmanConceptConfig,
    output_dir: Path,
    design_speeds_mps: tuple[float, ...],
    mission_speed_grid_mps: tuple[float, ...],
    stage0_samples: int,
    stage1_top_k: int,
    optimizer_maxfev: int,
    optimizer_maxiter: int,
    optimize_spanload_coefficients: bool,
    workers: int,
    avl_binary: str | None,
    enable_outer_chord_bump: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    allocation = allocate_stage1_budget(
        design_speeds_mps=design_speeds_mps,
        stage1_top_k=stage1_top_k,
    )
    all_records: list[dict[str, Any]] = []
    stage0_by_speed: dict[str, Any] = {}
    for speed_index, design_speed_mps in enumerate(design_speeds_mps):
        speed_output_dir = output_dir / f"design_speed_{design_speed_mps:.1f}mps"
        stage0 = spanload_smoke._stage0_inverse_chord_sobol_prefilter(
            cfg=cfg,
            sample_count=int(stage0_samples),
            design_speed_mps=float(design_speed_mps),
            seed=20260503 + speed_index,
            enable_outer_chord_bump=bool(enable_outer_chord_bump),
        )
        stage0_by_speed[f"{design_speed_mps:.1f}"] = stage0["counts"]
        selected = spanload_smoke._select_stage1_inputs(
            list(stage0["accepted"]),
            top_k=int(allocation.get(float(design_speed_mps), 0)),
        )
        print(
            json.dumps(
                {
                    "event": "stage1_speed_start",
                    "design_speed_mps": float(design_speed_mps),
                    "selected": len(selected),
                    "stage0_counts": stage0["counts"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if workers > 1 and len(selected) > 1:
            with ThreadPoolExecutor(max_workers=int(workers)) as executor:
                futures = {
                    executor.submit(
                        _evaluate_metric,
                        cfg=cfg,
                        metric=metric,
                        design_speed_mps=float(design_speed_mps),
                        output_dir=speed_output_dir,
                        avl_binary=avl_binary,
                        optimizer_maxfev=int(optimizer_maxfev),
                        optimizer_maxiter=int(optimizer_maxiter),
                        optimize_spanload_coefficients=optimize_spanload_coefficients,
                        mission_speed_grid_mps=mission_speed_grid_mps,
                    ): metric
                    for metric in selected
                }
                for completed, future in enumerate(as_completed(futures), start=1):
                    metric = futures[future]
                    record = future.result()
                    all_records.append(record)
                    print(
                        json.dumps(
                            {
                                "event": "stage1_candidate_done",
                                "design_speed_mps": float(design_speed_mps),
                                "completed": completed,
                                "selected": len(selected),
                                "sample_index": metric.get("sample_index"),
                                "status": record.get("status"),
                                "avl_e_cdi": record.get("avl_reference_case", {}).get("avl_e_cdi"),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
        else:
            for completed, metric in enumerate(selected, start=1):
                record = _evaluate_metric(
                    cfg=cfg,
                    metric=metric,
                    design_speed_mps=float(design_speed_mps),
                    output_dir=speed_output_dir,
                    avl_binary=avl_binary,
                    optimizer_maxfev=int(optimizer_maxfev),
                    optimizer_maxiter=int(optimizer_maxiter),
                    optimize_spanload_coefficients=optimize_spanload_coefficients,
                    mission_speed_grid_mps=mission_speed_grid_mps,
                )
                all_records.append(record)
                print(
                    json.dumps(
                        {
                            "event": "stage1_candidate_done",
                            "design_speed_mps": float(design_speed_mps),
                            "completed": completed,
                            "selected": len(selected),
                            "sample_index": metric.get("sample_index"),
                            "status": record.get("status"),
                            "avl_e_cdi": record.get("avl_reference_case", {}).get("avl_e_cdi"),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

    ranked = rank_mission_candidates(all_records)
    top_for_export = ranked[:10]
    for record in top_for_export:
        record["leaderboard_memberships"] = ["mission_coupled_top_candidate"]
    export_artifacts = spanload_smoke._export_top_candidates(
        cfg=cfg,
        records=top_for_export,
        output_dir=output_dir,
        count=10,
    )
    physically_accepted = [
        record
        for record in all_records
        if bool(record.get("physical_acceptance", {}).get("physically_acceptable", False))
    ]
    e88 = [
        record
        for record in physically_accepted
        if float(record.get("avl_reference_case", {}).get("avl_e_cdi") or 0.0) >= 0.88
    ]
    report = {
        "schema_version": "birdman_mission_coupled_spanload_search_v1",
        "route": "inverse_chord_residual_twist_mission_coupled_no_cst",
        "search_parameters": {
            "stage0_samples_per_design_speed": int(stage0_samples),
            "stage1_top_k_total": int(stage1_top_k),
            "stage1_budget_by_design_speed": {f"{key:.1f}": value for key, value in allocation.items()},
            "optimizer_maxfev": int(optimizer_maxfev),
            "optimizer_maxiter": int(optimizer_maxiter),
            "optimize_spanload_coefficients": bool(optimize_spanload_coefficients),
            "workers": int(workers),
            "design_speeds_mps": [float(speed) for speed in design_speeds_mps],
            "mission_speed_grid_mps": [float(speed) for speed in mission_speed_grid_mps],
        },
        "stage0_counts_by_design_speed": stage0_by_speed,
        "stage1_counts": {
            "evaluated": len(all_records),
            "physically_accepted": len(physically_accepted),
            "e_cdi_ge_0p88": len(e88),
            "status_counts": dict(Counter(str(record.get("status")) for record in all_records)),
        },
        "ranking_rule": (
            "Pass geometry/local/twist/tip gates; e_CDi >= 0.88 primary tier, "
            "0.85-0.88 diagnostic tier; maximize V_complete_max, then power margin."
        ),
        "fixed_profile_drag_note": "fixed_airfoil_no_xfoil_not_final_profile_drag",
        "leaderboards": build_leaderboards(ranked),
        "ranked_records_compact": [_compact_record(record) for record in ranked],
        "top_candidates": ranked[:10],
        "export_artifacts": export_artifacts,
    }
    report["engineering_read"] = _engineering_read(report)
    return report


def _engineering_read(report: dict[str, Any]) -> list[str]:
    read: list[str] = []
    counts = report["stage1_counts"]
    if counts["e_cdi_ge_0p88"] > 0:
        read.append("Found at least one e_CDi >= 0.88 physically accepted candidate; inspect mission ranking before any CST/XFOIL escalation.")
    elif counts["physically_accepted"] > 0:
        read.append("Only diagnostic e_CDi 0.85-0.88 candidates were found; this is not yet a first-version HPA wing candidate.")
    else:
        read.append("No physically accepted e_CDi >= 0.85 candidate was found in this no-CST mission-coupled run.")
    top = report.get("top_candidates", [])
    if top:
        best = top[0]
        sweep = best.get("mission_speed_sweep", {})
        read.append(
            "Top mission-ranked record: "
            f"sample {best.get('sample_index')} at design speed {best.get('design_speed_mps')} m/s, "
            f"e_CDi={best.get('avl_reference_case', {}).get('avl_e_cdi')}, "
            f"V_complete_max={sweep.get('v_complete_max_mps')}, "
            f"max_range_if_not_complete={sweep.get('max_range_if_not_complete_m')} m."
        )
        if sweep.get("v_complete_max_mps") is None:
            read.append(
                "Current fixed-profile proxy does not support a 42.195 km completion claim for the top record; the reported gap is still proxy-level until CST/XFOIL profile drag is connected."
            )
    underloaded = [
        record
        for record in report.get("ranked_records_compact", [])
        if bool(record.get("outer_loading_diagnostics", {}).get("outer_underloaded", False))
    ]
    if underloaded:
        read.append(
            f"{len(underloaded)} ranked records are outer-underloaded, so the next geometry move is cl schedule/chord/Ainc redistribution rather than AR chasing."
        )
    accepted_records = [
        record
        for record in report.get("ranked_records_compact", [])
        if bool(record.get("physical_acceptance", {}).get("physically_acceptable", False))
    ]
    if accepted_records:
        bump_amps = [
            float(record.get("outer_chord_bump_amp"))
            for record in accepted_records
            if record.get("outer_chord_bump_amp") is not None
        ]
        if bump_amps:
            non_zero = [amp for amp in bump_amps if amp > 1.0e-3]
            best_e_record = max(
                accepted_records,
                key=lambda record: float(record.get("avl_e_cdi") or 0.0),
            )
            read.append(
                "Outer chord bump usage in accepted candidates: "
                f"{len(non_zero)}/{len(accepted_records)} active "
                f"(amp range {min(bump_amps):.3f}-{max(bump_amps):.3f}); "
                f"best e_CDi accepted = {best_e_record.get('avl_e_cdi')} "
                f"with outer_chord_bump_amp = {best_e_record.get('outer_chord_bump_amp')}."
            )
    return read


def _parse_float_tuple(text: str) -> tuple[float, ...]:
    return tuple(float(part.strip()) for part in str(text).split(",") if part.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/birdman_upstream_concept_baseline.yaml"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/birdman_mission_coupled_spanload_search"))
    parser.add_argument("--stage0-samples", type=int, default=2048)
    parser.add_argument("--stage1-top-k", type=int, default=80)
    parser.add_argument("--optimizer-maxfev", type=int, default=40)
    parser.add_argument("--optimizer-maxiter", type=int, default=8)
    parser.add_argument("--design-speeds-mps", default="6.0,6.2,6.4,6.6,6.8,7.0")
    parser.add_argument("--mission-speed-grid-mps", default="6.4,6.6,6.8,7.0,7.2")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument("--optimize-spanload-coefficients", action="store_true")
    parser.add_argument(
        "--enable-outer-chord-bump",
        action="store_true",
        help=(
            "Use the legacy outer chord bump (default: disabled). "
            "Stage-1 generation switched to the MIT-like closed-loop architecture "
            "in birdman_mit_like_closed_loop_search.py; this flag is kept for "
            "regression comparison only."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_concept_config(args.config)
    report = run_search(
        cfg=cfg,
        output_dir=args.output_dir,
        design_speeds_mps=_parse_float_tuple(args.design_speeds_mps),
        mission_speed_grid_mps=_parse_float_tuple(args.mission_speed_grid_mps),
        stage0_samples=int(args.stage0_samples),
        stage1_top_k=int(args.stage1_top_k),
        optimizer_maxfev=int(args.optimizer_maxfev),
        optimizer_maxiter=int(args.optimizer_maxiter),
        optimize_spanload_coefficients=bool(args.optimize_spanload_coefficients),
        workers=max(1, int(args.workers)),
        avl_binary=args.avl_binary,
        enable_outer_chord_bump=bool(args.enable_outer_chord_bump),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "mission_coupled_spanload_search_report.json"
    json_path.write_text(json.dumps(spanload_smoke._round(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path = args.output_dir / "mission_coupled_spanload_search_report.md"
    _write_markdown(report=spanload_smoke._round(report), path=md_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


def _write_markdown(*, report: dict[str, Any], path: Path) -> None:
    lines = [
        "# Birdman Mission-Coupled Spanload Search",
        "",
        f"- Route: {report['route']}",
        f"- Stage 1 evaluated: {report['stage1_counts']['evaluated']}",
        f"- Physically accepted: {report['stage1_counts']['physically_accepted']}",
        f"- e_CDi >= 0.88: {report['stage1_counts']['e_cdi_ge_0p88']}",
        f"- Fixed profile note: {report['fixed_profile_drag_note']}",
        "",
        "## Engineering Read",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("engineering_read", []))
    for name, records in report.get("leaderboards", {}).items():
        lines.extend(
            [
                "",
                f"## {name}",
                "",
                "| rank | sample | design V | tier | span | S | AR | e_CDi | P req | V complete | max range m | bump | outer_min[0.80-0.92] | min chord | outer underloaded |",
                "|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            ]
        )
        for rank, record in enumerate(records, start=1):
            outer = record.get("outer_loading_diagnostics") or {}
            outer_samples = outer.get("eta_samples") or {}
            outer_min = outer.get("min_outer_avl_to_target_circulation_ratio")
            if outer_min is None:
                ratios = []
                for sample in outer_samples.values():
                    requested = sample.get("requested_eta")
                    if requested is None:
                        continue
                    if 0.80 <= float(requested) <= 0.92:
                        value = sample.get("avl_to_target_circulation_ratio")
                        if value is not None:
                            ratios.append(float(value))
                outer_min = min(ratios) if ratios else None
            lines.append(
                "| "
                f"{rank} | "
                f"{record.get('sample_index')} | "
                f"{record.get('design_speed_mps')} | "
                f"{record.get('mission_ranking_tier')} | "
                f"{record.get('span_m')} | "
                f"{record.get('wing_area_m2')} | "
                f"{record.get('aspect_ratio')} | "
                f"{record.get('avl_e_cdi')} | "
                f"{record.get('avl_cdi_power_required_w')} | "
                f"{record.get('v_complete_max_mps')} | "
                f"{record.get('max_range_if_not_complete_m')} | "
                f"{record.get('outer_chord_bump_amp')} | "
                f"{outer_min} | "
                f"{record.get('min_chord_m')} | "
                f"{record.get('outer_underloaded')} |"
            )
    lines.extend(
        [
            "",
            "## Top Candidates",
            "",
            "| rank | sample | design V | tier | e_CDi | V_complete | T_complete s | max range m | bump | outer underloaded |",
            "|---:|---:|---:|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for rank, record in enumerate(report.get("ranked_records_compact", [])[:20], start=1):
        sweep = record.get("mission_speed_sweep", {})
        lines.append(
            "| "
            f"{rank} | "
            f"{record.get('sample_index')} | "
            f"{record.get('design_speed_mps')} | "
            f"{record.get('mission_ranking_tier')} | "
            f"{record.get('avl_e_cdi')} | "
            f"{sweep.get('v_complete_max_mps')} | "
            f"{sweep.get('t_complete_min_s')} | "
            f"{sweep.get('max_range_if_not_complete_m')} | "
            f"{record.get('outer_chord_bump_amp')} | "
            f"{record.get('outer_loading_diagnostics', {}).get('outer_underloaded')} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
