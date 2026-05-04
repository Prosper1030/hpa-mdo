"""Shadow-mode mission drag budget evaluation on concept pipeline candidates.

Reads an existing concept_ranked_pool.json, attaches drag budget evaluation
to each candidate, and writes mission_drag_budget_shadow.csv and
mission_drag_budget_shadow_summary.json alongside the ranked pool.

This module is purely additive: it never alters ranking, objective, or gate
logic — it only produces diagnostic shadow outputs for later analysis.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Optional

from .drag_budget import (
    MissionDragBudget,
    MissionDragBudgetInputs,
    MissionDragBudgetResult,
    evaluate_drag_budget_candidate,
    load_mission_drag_budget,
)
from .objective import CsvPowerCurve, FakeAnchorCurve
from .quick_screen import MissionQuickScreenResult, evaluate_quick_screen, MissionQuickScreenInputs

RiderCurve = FakeAnchorCurve | CsvPowerCurve

SHADOW_CSV_FILENAME = "mission_drag_budget_shadow.csv"
SHADOW_SUMMARY_JSON_FILENAME = "mission_drag_budget_shadow_summary.json"

_FALLBACK_CL_MAX = 1.55
_FALLBACK_AIR_DENSITY = 1.1357
_FALLBACK_OSWALD_E = 0.90
_MIN_PLAUSIBLE_CL_MAX = 0.5


@dataclass
class ShadowRow:
    """One row of the shadow CSV output."""

    candidate_id: str
    evaluation_status: str

    # Inputs actually used (may differ from candidate_id metadata if fallback applied)
    speed_mps: Optional[float] = None
    span_m: Optional[float] = None
    aspect_ratio: Optional[float] = None
    wing_area_m2: Optional[float] = None
    mass_kg: Optional[float] = None
    cd0_wing_profile: Optional[float] = None
    cda_nonwing_m2: Optional[float] = None
    cd0_nonwing_equivalent: Optional[float] = None
    cd0_total_est: Optional[float] = None
    cd0_total_target_margin: Optional[float] = None
    cd0_total_boundary_margin: Optional[float] = None
    cd0_wing_profile_target_margin: Optional[float] = None
    cd0_wing_profile_boundary_margin: Optional[float] = None
    drag_budget_band: Optional[str] = None
    mission_power_margin_crank_w: Optional[float] = None
    power_passed: Optional[bool] = None
    robust_passed: Optional[bool] = None
    cl_required: Optional[float] = None
    cl_to_clmax_ratio: Optional[float] = None
    stall_band: Optional[str] = None
    cl_band: Optional[str] = None
    notes: str = ""


def _get_float(d: dict[str, Any], *keys: str, default: float | None = None) -> float | None:
    for key in keys:
        val = d.get(key)
        if val is not None:
            try:
                f = float(val)
                if isfinite(f):
                    return f
            except (TypeError, ValueError):
                pass
    return default


def _extract_air_density(output_dir: Path) -> tuple[float, str]:
    """Try to read air density from concept_summary.json in the same directory."""
    summary_path = output_dir / "concept_summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            env = summary.get("environment_air_properties", {})
            density = _get_float(env, "density_kg_per_m3")
            if density is not None and density > 0.5:
                return density, "concept_summary_json"
        except Exception:
            pass
    return _FALLBACK_AIR_DENSITY, "fallback:hardcoded_isa_sea_level"


def _extract_rider_curve_from_config(
    config_path_str: str | None,
    repo_root: Path | None = None,
) -> tuple[RiderCurve | None, float, str]:
    """Try to reconstruct the rider curve from the concept config.

    Returns (rider_curve, thermal_derate_factor, source_tag).
    """
    if not config_path_str:
        return None, 1.0, "unavailable:no_config_path"
    try:
        import yaml
        from .objective import (
            build_rider_power_curve,
            load_rider_power_curve_metadata,
            thermal_power_derate_factor,
            RiderPowerEnvironment,
        )

        config_path = Path(config_path_str)
        if not config_path.exists() and repo_root is not None:
            config_path = repo_root / config_path_str

        if not config_path.exists():
            return None, 1.0, "unavailable:config_not_found"

        cfg_raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        mission_cfg = cfg_raw.get("mission", {})
        env_cfg = cfg_raw.get("environment", {})

        csv_rel = mission_cfg.get("rider_power_curve_csv")
        if csv_rel is None:
            return None, 1.0, "unavailable:no_rider_csv_in_config"

        # Resolve CSV path relative to repo root or config dir
        csv_path = Path(csv_rel)
        if not csv_path.is_absolute():
            for base in filter(None, [repo_root, config_path.parent]):
                candidate = base / csv_rel
                if candidate.exists():
                    csv_path = candidate
                    break

        if not csv_path.exists():
            return None, 1.0, f"unavailable:csv_not_found:{csv_rel}"

        duration_col = str(mission_cfg.get("rider_power_curve_duration_column", "secs"))
        power_col = str(mission_cfg.get("rider_power_curve_power_column", "watts"))

        rider_curve = build_rider_power_curve(
            anchor_power_w=float(mission_cfg.get("anchor_power_w", 213.0)),
            anchor_duration_min=float(mission_cfg.get("anchor_duration_min", 30.0)),
            rider_power_curve_csv=str(csv_path),
            duration_column=duration_col,
            power_column=power_col,
            thermal_adjustment_enabled=False,
        )

        # Compute thermal derate factor
        metadata_yaml = mission_cfg.get("rider_power_curve_metadata_yaml")
        derate = 1.0
        derate_source = "no_thermal_adjustment"
        if metadata_yaml and bool(mission_cfg.get("rider_power_curve_thermal_adjustment_enabled", True)):
            meta_path = Path(metadata_yaml)
            if not meta_path.is_absolute() and repo_root is not None:
                meta_path = repo_root / metadata_yaml
            if meta_path.exists():
                meta = load_rider_power_curve_metadata(meta_path)
                env_raw = meta.get("measurement_environment", {})
                test_env = RiderPowerEnvironment(
                    temperature_c=float(env_raw.get("temperature_c", 26.0)),
                    relative_humidity_percent=float(
                        env_raw.get("relative_humidity_percent", 70.0)
                    ),
                )
                target_env = RiderPowerEnvironment(
                    temperature_c=float(env_cfg.get("temperature_c", 33.0)),
                    relative_humidity_percent=float(env_cfg.get("relative_humidity", 80.0)),
                )
                derate = thermal_power_derate_factor(
                    test_environment=test_env,
                    target_environment=target_env,
                    heat_loss_coefficient_per_h_c=float(
                        mission_cfg.get(
                            "rider_power_curve_heat_loss_coefficient_per_h_c", 0.008
                        )
                    ),
                )
                derate_source = "config_thermal_adjustment"

        return rider_curve, derate, f"csv_with_{derate_source}"
    except Exception:
        return None, 1.0, "error:rider_curve_load_failed"


def _extract_shadow_inputs(
    candidate: dict[str, Any],
    budget: MissionDragBudget,
    air_density: float,
    rider_curve: RiderCurve | None,
    thermal_derate_factor: float,
    target_range_km: float = 42.195,
) -> tuple[MissionDragBudgetInputs | None, str, list[str]]:
    """Extract inputs for shadow evaluation from a ranked-pool candidate dict.

    Returns (inputs, evaluation_status, notes).
    """
    notes: list[str] = []
    mission = candidate.get("mission", {})

    # cd0_wing_profile — mandatory, sourced from profile_cd_proxy
    cd0_wing_profile_raw = _get_float(mission, "profile_cd_proxy")
    if cd0_wing_profile_raw is None or cd0_wing_profile_raw <= 0.0:
        return None, "missing_cd0_wing_profile", [
            "profile_cd_proxy is None or non-positive in mission summary"
        ]

    # speed_mps — prefer midpoint of speed_sweep_window_mps
    speed_source = "actual"
    speed_mps: float | None = None
    speed_window = mission.get("speed_sweep_window_mps")
    if isinstance(speed_window, list) and len(speed_window) == 2:
        try:
            speed_mps = 0.5 * (float(speed_window[0]) + float(speed_window[1]))
            speed_source = "midpoint_speed_sweep_window"
        except (TypeError, ValueError):
            pass
    if speed_mps is None:
        speed_mps = 6.5
        speed_source = "fallback:6.5mps"
        notes.append(f"speed_mps source={speed_source}")

    # mass_kg
    mass_kg = _get_float(mission, "evaluated_gross_mass_kg", "primary_gross_mass_kg")
    if mass_kg is None:
        mass_kg = 98.5
        notes.append("mass_kg source=fallback:98.5kg")

    # span_m / aspect_ratio
    span_m = _get_float(candidate, "span_m")
    if span_m is None:
        return None, "missing_span_m", ["span_m not found in candidate"]
    aspect_ratio = _get_float(candidate, "aspect_ratio")
    if aspect_ratio is None:
        return None, "missing_aspect_ratio", ["aspect_ratio not found in candidate"]

    # oswald_e
    oswald_e = _get_float(mission, "oswald_efficiency")
    oswald_source = "oswald_efficiency"
    if oswald_e is None or not (0.0 < oswald_e <= 1.2):
        oswald_e = _get_float(mission, "drag_oswald_efficiency")
        oswald_source = "drag_oswald_efficiency"
    if oswald_e is None or not (0.0 < oswald_e <= 1.2):
        oswald_e = _get_float(mission, "oswald_efficiency_proxy")
        oswald_source = "oswald_efficiency_proxy"
    if oswald_e is None or not (0.0 < oswald_e <= 1.2):
        oswald_e = _FALLBACK_OSWALD_E
        oswald_source = f"fallback:{_FALLBACK_OSWALD_E}"
        notes.append(f"oswald_e source={oswald_source}")
    elif oswald_source != "oswald_efficiency":
        notes.append(f"oswald_e source={oswald_source}")

    # cl_max_effective — use local_stall.raw_clmax if plausible
    cl_max_effective = _FALLBACK_CL_MAX
    cl_max_source = f"fallback:{_FALLBACK_CL_MAX}"
    local_stall = candidate.get("local_stall", {})
    if isinstance(local_stall, dict):
        raw_clmax = _get_float(local_stall, "raw_clmax")
        if raw_clmax is not None and raw_clmax >= _MIN_PLAUSIBLE_CL_MAX:
            cl_max_effective = raw_clmax
            cl_max_source = "local_stall.raw_clmax"
    if cl_max_source != "local_stall.raw_clmax":
        notes.append(f"cl_max_effective source={cl_max_source}")

    # eta_prop / eta_trans
    prop_eff = mission.get("propulsion_efficiency_assumptions", {})
    eta_prop = _get_float(prop_eff, "eta_prop_design")
    if eta_prop is None:
        eta_prop = budget.eta_prop_sizing
        notes.append("eta_prop source=fallback:budget.eta_prop_sizing")
    eta_trans = _get_float(prop_eff, "eta_transmission")
    if eta_trans is None:
        eta_trans = budget.eta_trans
        notes.append("eta_trans source=fallback:budget.eta_trans")

    inputs = MissionDragBudgetInputs(
        speed_mps=speed_mps,
        span_m=span_m,
        aspect_ratio=aspect_ratio,
        mass_kg=mass_kg,
        cd0_wing_profile=cd0_wing_profile_raw,
        oswald_e=oswald_e,
        cl_max_effective=cl_max_effective,
        air_density_kg_m3=air_density,
        eta_prop=eta_prop,
        eta_trans=eta_trans,
        target_range_km=target_range_km,
        rider_curve=rider_curve,
        thermal_derate_factor=thermal_derate_factor,
    )
    return inputs, "ok", notes


def evaluate_shadow_candidate(
    candidate: dict[str, Any],
    budget: MissionDragBudget,
    air_density: float = _FALLBACK_AIR_DENSITY,
    rider_curve: RiderCurve | None = None,
    thermal_derate_factor: float = 1.0,
    target_range_km: float = 42.195,
    reserve_mode: str = "target",
) -> ShadowRow:
    """Evaluate one ranked-pool candidate in shadow mode."""
    candidate_id = str(candidate.get("concept_id", candidate.get("evaluation_id", "unknown")))

    inputs, status, notes = _extract_shadow_inputs(
        candidate=candidate,
        budget=budget,
        air_density=air_density,
        rider_curve=rider_curve,
        thermal_derate_factor=thermal_derate_factor,
        target_range_km=target_range_km,
    )

    row = ShadowRow(
        candidate_id=candidate_id,
        evaluation_status=status,
        span_m=_get_float(candidate, "span_m"),
        aspect_ratio=_get_float(candidate, "aspect_ratio"),
        notes="; ".join(notes),
    )

    if inputs is None:
        return row

    try:
        result = evaluate_drag_budget_candidate(budget, inputs, reserve_mode=reserve_mode)

        # Also run quick_screen independently to get CL metrics
        qs_inputs = MissionQuickScreenInputs(
            speed_mps=inputs.speed_mps,
            span_m=inputs.span_m,
            aspect_ratio=inputs.aspect_ratio,
            mass_kg=inputs.mass_kg,
            cd0_total=result.cd0_total_est,
            oswald_e=inputs.oswald_e,
            air_density_kg_m3=inputs.air_density_kg_m3,
            eta_prop=inputs.eta_prop,
            eta_trans=inputs.eta_trans,
            target_range_km=inputs.target_range_km,
            rider_curve=inputs.rider_curve,
            thermal_derate_factor=inputs.thermal_derate_factor,
            cl_max_effective=inputs.cl_max_effective,
        )
        qsr = evaluate_quick_screen(qs_inputs)

        return ShadowRow(
            candidate_id=candidate_id,
            evaluation_status="ok",
            speed_mps=inputs.speed_mps,
            span_m=inputs.span_m,
            aspect_ratio=inputs.aspect_ratio,
            wing_area_m2=result.wing_area_m2,
            mass_kg=inputs.mass_kg,
            cd0_wing_profile=result.cd0_wing_profile,
            cda_nonwing_m2=result.cda_nonwing_m2,
            cd0_nonwing_equivalent=result.cd0_nonwing_equivalent,
            cd0_total_est=result.cd0_total_est,
            cd0_total_target_margin=result.cd0_total_target_margin,
            cd0_total_boundary_margin=result.cd0_total_boundary_margin,
            cd0_wing_profile_target_margin=result.cd0_wing_profile_target_margin,
            cd0_wing_profile_boundary_margin=result.cd0_wing_profile_boundary_margin,
            drag_budget_band=result.drag_budget_band,
            mission_power_margin_crank_w=result.mission_power_margin_crank_w,
            power_passed=result.power_passed,
            robust_passed=result.robust_passed,
            cl_required=qsr.cl_required,
            cl_to_clmax_ratio=qsr.cl_to_clmax_ratio,
            stall_band=qsr.stall_band,
            cl_band=qsr.cl_band,
            notes="; ".join(notes),
        )
    except Exception as exc:
        return ShadowRow(
            candidate_id=candidate_id,
            evaluation_status=f"error:{type(exc).__name__}",
            span_m=inputs.span_m,
            aspect_ratio=inputs.aspect_ratio,
            cd0_wing_profile=inputs.cd0_wing_profile,
            notes=f"exception: {exc}; " + "; ".join(notes),
        )


def run_shadow_on_ranked_pool_json(
    ranked_pool_json_path: Path,
    budget_config_path: Path,
    output_dir: Path,
    *,
    rider_curve: RiderCurve | None = None,
    thermal_derate_factor: float = 1.0,
    reserve_mode: str = "target",
    auto_load_rider_curve: bool = True,
) -> dict[str, Any]:
    """Run shadow evaluation on a concept_ranked_pool.json.

    Args:
        ranked_pool_json_path: Path to concept_ranked_pool.json.
        budget_config_path: Path to mission_drag_budget YAML.
        output_dir: Directory for shadow CSV and JSON outputs.
        rider_curve: Pre-loaded rider curve. If None and auto_load_rider_curve,
            will attempt to load from the concept config path in the ranked pool.
        thermal_derate_factor: Applied to the rider curve power.
        reserve_mode: ``"target"`` or ``"boundary"``.
        auto_load_rider_curve: If True, try to load rider curve from config.

    Returns:
        Summary dict (same content as the JSON file).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ranked_pool_data = json.loads(
        Path(ranked_pool_json_path).read_text(encoding="utf-8")
    )
    candidates: list[dict[str, Any]] = ranked_pool_data.get("ranked_pool", [])
    config_path_str: str | None = ranked_pool_data.get("config_path")

    budget = load_mission_drag_budget(budget_config_path)

    # Air density from concept_summary.json in the same directory
    pool_dir = Path(ranked_pool_json_path).parent
    air_density, air_density_source = _extract_air_density(pool_dir)

    # Rider curve
    rider_curve_source = "provided"
    actual_rider_curve = rider_curve
    actual_derate = thermal_derate_factor
    if actual_rider_curve is None and auto_load_rider_curve:
        repo_root = Path(ranked_pool_json_path).resolve().parents[2]  # output/run/file → repo
        actual_rider_curve, actual_derate, rider_curve_source = _extract_rider_curve_from_config(
            config_path_str, repo_root=repo_root
        )

    # Get target_range_km from budget YAML mission_reference section
    try:
        import yaml as _yaml
        raw_budget_yaml = _yaml.safe_load(
            Path(budget_config_path).read_text(encoding="utf-8")
        )
        target_range_km = float(
            raw_budget_yaml.get("mission_reference", {}).get("target_range_km", 42.195)
        )
    except Exception:
        target_range_km = 42.195

    # Evaluate all candidates
    rows: list[ShadowRow] = []
    for candidate in candidates:
        row = evaluate_shadow_candidate(
            candidate=candidate,
            budget=budget,
            air_density=air_density,
            rider_curve=actual_rider_curve,
            thermal_derate_factor=actual_derate,
            target_range_km=target_range_km,
            reserve_mode=reserve_mode,
        )
        rows.append(row)

    # Write CSV
    csv_path = output_dir / SHADOW_CSV_FILENAME
    _write_shadow_csv(rows, csv_path)

    # Build and write summary
    summary = _build_shadow_summary(
        rows=rows,
        config_paths={
            "mission_drag_budget_config": str(budget_config_path),
            "ranked_pool_json": str(ranked_pool_json_path),
            "mission_design_space_summary": str(
                Path(ranked_pool_json_path).parent.parent / "mission_design_space" / "summary.json"
            ),
            "optimizer_handoff_json": str(
                Path(ranked_pool_json_path).parent.parent
                / "mission_design_space"
                / "optimizer_handoff.json"
            ),
        },
        budget=budget,
        air_density_source=air_density_source,
        rider_curve_source=rider_curve_source,
        reserve_mode=reserve_mode,
    )
    summary_path = output_dir / SHADOW_SUMMARY_JSON_FILENAME
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def _write_shadow_csv(rows: list[ShadowRow], path: Path) -> None:
    fieldnames = [
        "candidate_id",
        "speed_mps",
        "span_m",
        "aspect_ratio",
        "wing_area_m2",
        "mass_kg",
        "cd0_wing_profile",
        "cda_nonwing_m2",
        "cd0_nonwing_equivalent",
        "cd0_total_est",
        "cd0_total_target_margin",
        "cd0_total_boundary_margin",
        "cd0_wing_profile_target_margin",
        "cd0_wing_profile_boundary_margin",
        "drag_budget_band",
        "mission_power_margin_crank_w",
        "power_passed",
        "robust_passed",
        "cl_required",
        "cl_to_clmax_ratio",
        "stall_band",
        "cl_band",
        "evaluation_status",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "candidate_id": row.candidate_id,
                    "speed_mps": _fmt(row.speed_mps),
                    "span_m": _fmt(row.span_m),
                    "aspect_ratio": _fmt(row.aspect_ratio),
                    "wing_area_m2": _fmt(row.wing_area_m2),
                    "mass_kg": _fmt(row.mass_kg),
                    "cd0_wing_profile": _fmt(row.cd0_wing_profile),
                    "cda_nonwing_m2": _fmt(row.cda_nonwing_m2),
                    "cd0_nonwing_equivalent": _fmt(row.cd0_nonwing_equivalent),
                    "cd0_total_est": _fmt(row.cd0_total_est),
                    "cd0_total_target_margin": _fmt(row.cd0_total_target_margin),
                    "cd0_total_boundary_margin": _fmt(row.cd0_total_boundary_margin),
                    "cd0_wing_profile_target_margin": _fmt(row.cd0_wing_profile_target_margin),
                    "cd0_wing_profile_boundary_margin": _fmt(
                        row.cd0_wing_profile_boundary_margin
                    ),
                    "drag_budget_band": row.drag_budget_band or "",
                    "mission_power_margin_crank_w": _fmt(row.mission_power_margin_crank_w),
                    "power_passed": "" if row.power_passed is None else str(row.power_passed),
                    "robust_passed": (
                        "" if row.robust_passed is None else str(row.robust_passed)
                    ),
                    "cl_required": _fmt(row.cl_required),
                    "cl_to_clmax_ratio": _fmt(row.cl_to_clmax_ratio),
                    "stall_band": row.stall_band or "",
                    "cl_band": row.cl_band or "",
                    "evaluation_status": row.evaluation_status,
                    "notes": row.notes,
                }
            )


def _build_shadow_summary(
    rows: list[ShadowRow],
    config_paths: dict[str, str],
    budget: MissionDragBudget,
    air_density_source: str,
    rider_curve_source: str,
    reserve_mode: str,
) -> dict[str, Any]:
    total = len(rows)
    evaluated = [r for r in rows if r.evaluation_status == "ok"]
    missing_input = [r for r in rows if r.evaluation_status != "ok"]

    band_counts: dict[str, int] = {}
    for row in evaluated:
        band = str(row.drag_budget_band or "unknown")
        band_counts[band] = band_counts.get(band, 0) + 1

    power_passed_count = sum(1 for r in evaluated if r.power_passed is True)
    robust_passed_count = sum(1 for r in evaluated if r.robust_passed is True)

    best_candidate_id = None
    worst_candidate_id = None
    if evaluated:
        ok_with_margin = [
            r for r in evaluated if r.mission_power_margin_crank_w is not None
        ]
        if ok_with_margin:
            best = max(ok_with_margin, key=lambda r: r.mission_power_margin_crank_w or float("-inf"))
            worst = min(ok_with_margin, key=lambda r: r.mission_power_margin_crank_w or float("inf"))
            best_candidate_id = best.candidate_id
            worst_candidate_id = worst.candidate_id
        else:
            # Fall back to best band
            for band in ("target", "boundary", "rescue", "over_budget"):
                band_rows = [r for r in evaluated if r.drag_budget_band == band]
                if band_rows:
                    best_candidate_id = band_rows[0].candidate_id
                    break

    # Best cd0_total_est
    best_cd0 = None
    if evaluated:
        cd0_rows = [r for r in evaluated if r.cd0_total_est is not None]
        if cd0_rows:
            best_cd0 = min(r.cd0_total_est for r in cd0_rows if r.cd0_total_est is not None)

    return {
        "total_candidates": total,
        "evaluated_candidates": len(evaluated),
        "missing_input_candidates": len(missing_input),
        "missing_input_statuses": [r.evaluation_status for r in missing_input],
        "count_by_drag_budget_band": band_counts,
        "count_power_passed": power_passed_count,
        "count_robust_passed": robust_passed_count,
        "best_margin_candidate_id": best_candidate_id,
        "worst_margin_candidate_id": worst_candidate_id,
        "best_cd0_total_est": best_cd0,
        "budget_thresholds": {
            "cd0_total_target": budget.cd0_total_target,
            "cd0_total_boundary": budget.cd0_total_boundary,
            "cd0_total_rescue": budget.cd0_total_rescue,
            "cd0_wing_profile_target": budget.cd0_wing_profile_target,
            "cd0_wing_profile_boundary": budget.cd0_wing_profile_boundary,
            "cda_nonwing_target_m2": budget.cda_nonwing_target_m2,
            "cda_nonwing_boundary_m2": budget.cda_nonwing_boundary_m2,
        },
        "reserve_mode": reserve_mode,
        "air_density_source": air_density_source,
        "rider_curve_source": rider_curve_source,
        "config_paths": config_paths,
    }


def _fmt(val: float | None) -> str:
    if val is None:
        return ""
    return f"{val:.6g}"
