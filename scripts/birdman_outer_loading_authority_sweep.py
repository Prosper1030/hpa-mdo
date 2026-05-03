#!/usr/bin/env python3
"""Birdman outer loading authority sweep.

Diagnoses why the Birdman inverse-chord mixed-airfoil candidates are outer
underloaded and tests low-order interventions on the AVL realised circulation:

  * outer Ainc bump (extra incidence on a smooth eta=0.65-0.98 cosine bump)
  * outer chord redistribution (chord +amp*bump, with inner-chord area
    compensation so total wing area is preserved)
  * realisable target loading repair (taper the target Fourier shape past
    eta=0.90 so the diagnostic ratio is not tip-dominated)

The script loads a saved baseline candidate from the medium mission-coupled
search (e.g. rank_01_sample_1476), re-runs AVL on the baseline geometry, then
re-runs AVL for each intervention.  The reports include the eta-window outer
ratio metrics that the engineering brief asks for.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config  # noqa: E402
from hpa_mdo.concept.geometry import (  # noqa: E402
    GeometryConcept,
    WingStation,
    build_segment_plan,
)
from hpa_mdo.concept.outer_loading import (  # noqa: E402, F401
    OUTER_BUMP_HI_ETA,
    OUTER_BUMP_LO_ETA,
    OUTER_BUMP_PEAK_ETA,
    apply_outer_ainc_bump,
    apply_outer_chord_redistribution as _apply_outer_chord_redistribution,
    outer_smooth_bump,
)

import scripts.birdman_spanload_design_smoke as spanload_smoke  # noqa: E402


DEFAULT_AINC_AMPS_DEG = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5)
DEFAULT_CHORD_AMPS = (0.0, 0.10, 0.20, 0.30, 0.40)
DEFAULT_TARGET_OUTER_TAPER_FRACTIONS = (0.0, 0.30, 0.50, 0.70)

OUTER_RATIO_WINDOWS_ETA = (
    (0.70, 0.95),
    (0.80, 0.92),
)

EXPORT_DIAGNOSTIC_ETAS = (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)


def apply_outer_chord_redistribution(
    *,
    stations: tuple[WingStation, ...],
    amplitude: float,
) -> tuple[WingStation, ...]:
    """Backward-compatible wrapper around the shared module.

    The shared module returns a ``(stations, diagnostic)`` pair; the legacy
    sweep harness only needs the redistributed stations.
    """

    redistributed, _ = _apply_outer_chord_redistribution(
        stations=stations,
        amplitude=float(amplitude),
    )
    return redistributed


def apply_outer_target_taper(
    *,
    a3_over_a1: float,
    a5_over_a1: float,
    outer_taper_fraction: float,
) -> tuple[float, float]:
    """Bias target Fourier shape further toward inboard loading.

    The target spanload shape factors (a3, a5) ride alongside the elliptic a1
    term.  Pushing a3 more negative adds a small inboard cosine bump that
    reduces the demanded outer circulation.  This is the closed-form 'easier
    target loading' knob without rewriting the spanload solver.
    """

    fraction = max(0.0, min(1.0, float(outer_taper_fraction)))
    a3_extra = -0.06 * fraction
    a5_extra = +0.02 * fraction
    new_a3 = float(a3_over_a1) + a3_extra
    new_a5 = float(a5_over_a1) + a5_extra
    new_a3 = max(-0.5, min(0.5, new_a3))
    new_a5 = max(-0.5, min(0.5, new_a5))
    return float(new_a3), float(new_a5)


def load_baseline_from_export(
    *,
    cfg: BirdmanConceptConfig,
    export_dir: Path,
) -> dict[str, Any]:
    metadata_path = export_dir / "concept_openvsp_metadata.json"
    station_table_path = export_dir / "station_table.json"
    if not metadata_path.exists() or not station_table_path.exists():
        raise FileNotFoundError(
            "Baseline export must contain concept_openvsp_metadata.json and station_table.json: "
            f"{export_dir}"
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    raw_stations = json.loads(station_table_path.read_text(encoding="utf-8"))
    stations = tuple(
        WingStation(
            y_m=float(row["y_m"]),
            chord_m=float(row["chord_m"]),
            twist_deg=float(row.get("twist_deg", row.get("ainc_deg", 0.0))),
            dihedral_deg=float(row.get("dihedral_deg", 0.0)),
        )
        for row in raw_stations
    )
    geometry = metadata.get("geometry") or {}
    span_m = float(geometry.get("span_m") or (2.0 * stations[-1].y_m))
    half_span_m = 0.5 * span_m
    summary = metadata.get("concept_summary") or {}
    fourier = summary.get("spanload_fourier") or {}
    a3 = float(fourier.get("a3_over_a1", -0.05))
    a5 = float(fourier.get("a5_over_a1", 0.0))
    segment_lengths_m = build_segment_plan(
        half_span_m=float(half_span_m),
        min_segment_length_m=float(cfg.segmentation.min_segment_length_m),
        max_segment_length_m=float(cfg.segmentation.max_segment_length_m),
    )
    twist_root_deg = float(stations[0].twist_deg)
    twist_tip_deg = float(stations[-1].twist_deg)
    twist_control_points = tuple(
        (float(station.y_m) / max(half_span_m, 1.0e-9), float(station.twist_deg))
        for station in stations
    )
    if not math.isclose(twist_control_points[0][0], 0.0, abs_tol=1.0e-9):
        twist_control_points = ((0.0, twist_root_deg),) + twist_control_points
    if not math.isclose(twist_control_points[-1][0], 1.0, abs_tol=1.0e-9):
        twist_control_points = twist_control_points + ((1.0, twist_tip_deg),)
    wing_area_m2 = float(geometry.get("wing_area_m2") or spanload_smoke._integrate_station_chords(stations))
    concept = GeometryConcept(
        span_m=float(span_m),
        wing_area_m2=float(wing_area_m2),
        root_chord_m=float(geometry.get("root_chord_m", stations[0].chord_m)),
        tip_chord_m=float(geometry.get("tip_chord_m", stations[-1].chord_m)),
        twist_root_deg=float(twist_root_deg),
        twist_tip_deg=float(twist_tip_deg),
        twist_control_points=twist_control_points,
        tail_area_m2=float(cfg.geometry_family.tail_area_candidates_m2[0]),
        cg_xc=float(cfg.geometry_family.cg_xc),
        segment_lengths_m=segment_lengths_m,
        spanload_a3_over_a1=float(a3),
        spanload_a5_over_a1=float(a5),
        wing_loading_target_Npm2=float(cfg.design_gross_weight_n / max(wing_area_m2, 1.0e-9)),
        mean_chord_target_m=float(wing_area_m2 / max(span_m, 1.0e-9)),
        wing_area_is_derived=True,
        planform_parameterization="spanload_inverse_chord",
        design_gross_mass_kg=float(cfg.mass.design_gross_mass_kg),
        dihedral_root_deg=float(stations[0].dihedral_deg),
        dihedral_tip_deg=float(stations[-1].dihedral_deg),
    )
    zone_paths = _resolve_zone_airfoil_paths(metadata=metadata, export_dir=export_dir)
    design_speed_mps = _baseline_design_speed_mps(metadata=metadata, default=6.2)
    return {
        "concept": concept,
        "stations": stations,
        "zone_airfoil_paths": zone_paths,
        "design_speed_mps": float(design_speed_mps),
        "metadata": metadata,
        "baseline_avl_e_cdi": float(
            summary.get("avl_reference_case", {}).get("avl_e_cdi", 0.0)
        ),
        "baseline_sample_index": int(summary.get("sample_index") or 0),
    }


def _resolve_zone_airfoil_paths(
    *,
    metadata: dict[str, Any],
    export_dir: Path,
) -> dict[str, Path]:
    files = metadata.get("openvsp_airfoil_files") or {}
    paths: dict[str, Path] = {}
    for zone_name, raw_path in files.items():
        candidate = Path(str(raw_path))
        if not candidate.is_absolute():
            candidate = export_dir / candidate
        if candidate.exists():
            paths[str(zone_name)] = candidate.resolve()
            continue
        # Fallback to selected_airfoils dir.
        local = export_dir / "selected_airfoils"
        if local.is_dir():
            for entry in local.iterdir():
                if entry.name.startswith(f"{zone_name}-") and entry.suffix == ".dat":
                    paths[str(zone_name)] = entry.resolve()
                    break
    if paths:
        return paths
    return spanload_smoke._seed_zone_airfoil_paths()


def _baseline_design_speed_mps(*, metadata: dict[str, Any], default: float) -> float:
    summary = metadata.get("concept_summary") or {}
    avl_case = summary.get("avl_reference_case") or {}
    speed = avl_case.get("evaluation_speed_mps")
    if speed is None:
        speed = avl_case.get("design_speed_mps")
    return float(speed) if speed is not None else float(default)


def evaluate_intervention(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    output_dir: Path,
    design_speed_mps: float,
    avl_binary: str | None,
    case_tag: str,
    zone_airfoil_paths: dict[str, Path] | None,
    a3_over_a1: float | None = None,
    a5_over_a1: float | None = None,
) -> dict[str, Any]:
    a3_value = float(concept.spanload_a3_over_a1 if a3_over_a1 is None else a3_over_a1)
    a5_value = float(concept.spanload_a5_over_a1 if a5_over_a1 is None else a5_over_a1)
    twist_control_points = tuple(
        (float(station.y_m) / max(0.5 * float(concept.span_m), 1.0e-9), float(station.twist_deg))
        for station in stations
    )
    if not math.isclose(twist_control_points[0][0], 0.0, abs_tol=1.0e-9):
        twist_control_points = ((0.0, float(stations[0].twist_deg)),) + twist_control_points
    if not math.isclose(twist_control_points[-1][0], 1.0, abs_tol=1.0e-9):
        twist_control_points = twist_control_points + ((1.0, float(stations[-1].twist_deg)),)
    wing_area_new = spanload_smoke._integrate_station_chords(stations)
    refreshed = replace(
        concept,
        twist_root_deg=float(stations[0].twist_deg),
        twist_tip_deg=float(stations[-1].twist_deg),
        twist_control_points=twist_control_points,
        spanload_a3_over_a1=a3_value,
        spanload_a5_over_a1=a5_value,
        root_chord_m=float(stations[0].chord_m),
        tip_chord_m=float(stations[-1].chord_m),
        wing_area_m2=float(wing_area_new),
        wing_loading_target_Npm2=float(
            cfg.design_gross_weight_n / max(wing_area_new, 1.0e-9)
        ),
        mean_chord_target_m=float(wing_area_new / max(float(concept.span_m), 1.0e-9)),
        dihedral_root_deg=float(stations[0].dihedral_deg),
        dihedral_tip_deg=float(stations[-1].dihedral_deg),
    )
    target_table, target_summary = spanload_smoke._target_station_records(
        cfg=cfg,
        concept=refreshed,
        stations=stations,
        design_speed_mps=design_speed_mps,
    )
    avl = spanload_smoke._run_reference_avl_case(
        cfg=cfg,
        concept=refreshed,
        stations=stations,
        output_dir=output_dir,
        design_speed_mps=design_speed_mps,
        design_mass_kg=float(cfg.mass.design_gross_mass_kg),
        status_for_ranking="outer_loading_authority_sweep",
        avl_binary=avl_binary,
        case_tag=case_tag,
        zone_airfoil_paths=zone_airfoil_paths,
    )
    if avl.get("status") != "ok":
        return {
            "case_tag": case_tag,
            "status": "avl_failed",
            "error": avl.get("error"),
            "avl_e_cdi": None,
            "diagnostic": _empty_diagnostic(),
            "geometry": _geometry_summary_from_stations(refreshed, stations),
            "target_a3_over_a1": float(a3_value),
            "target_a5_over_a1": float(a5_value),
        }
    enriched = spanload_smoke._attach_avl_to_station_table(target_table, avl)
    diagnostic = compute_outer_loading_diagnostic(
        station_table=enriched,
        stations=stations,
        eta_windows=OUTER_RATIO_WINDOWS_ETA,
        diagnostic_etas=EXPORT_DIAGNOSTIC_ETAS,
    )
    twist_gate_metrics = spanload_smoke._twist_gate_metrics(stations)
    tip_gate_summary = spanload_smoke._tip_gate_summary(
        cfg=cfg,
        concept=refreshed,
        design_speed_mps=design_speed_mps,
        stations=stations,
    )
    spanload_gate_health = spanload_smoke._spanload_gate_health(target_summary, cfg)
    return {
        "case_tag": case_tag,
        "status": "ok",
        "avl_e_cdi": avl.get("avl_e_cdi"),
        "avl_reported_e": avl.get("avl_reported_e"),
        "trim_aoa_deg": avl.get("trim_aoa_deg"),
        "trim_cl": avl.get("trim_cl"),
        "trim_cd_induced": avl.get("trim_cd_induced"),
        "geometry": _geometry_summary_from_stations(refreshed, stations),
        "target_a3_over_a1": float(a3_value),
        "target_a5_over_a1": float(a5_value),
        "diagnostic": diagnostic,
        "spanwise_table": _spanwise_export_rows(enriched),
        "twist_distribution": [
            {
                "eta": float(row.get("eta", 0.0)),
                "twist_deg": float(row.get("twist_deg", 0.0)),
            }
            for row in enriched
        ],
        "twist_gate_metrics": twist_gate_metrics,
        "tip_gate_summary": tip_gate_summary,
        "spanload_gate_health": spanload_gate_health,
    }


def _geometry_summary_from_stations(
    concept: GeometryConcept, stations: tuple[WingStation, ...]
) -> dict[str, float]:
    return {
        "span_m": float(concept.span_m),
        "wing_area_m2": float(concept.wing_area_m2),
        "aspect_ratio": float(concept.aspect_ratio),
        "root_chord_m": float(stations[0].chord_m),
        "tip_chord_m": float(stations[-1].chord_m),
        "twist_root_deg": float(stations[0].twist_deg),
        "twist_tip_deg": float(stations[-1].twist_deg),
        "twist_range_deg": float(
            max(float(s.twist_deg) for s in stations)
            - min(float(s.twist_deg) for s in stations)
        ),
        "max_abs_twist_deg": float(max(abs(float(s.twist_deg)) for s in stations)),
    }


def _empty_diagnostic() -> dict[str, Any]:
    return {
        "eta_samples": [],
        "outer_ratio_windows": [],
        "outer_underloaded": None,
    }


def _spanwise_export_rows(station_table: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in station_table:
        rows.append(
            {
                "eta": float(row.get("eta", 0.0)),
                "y_m": float(row.get("y_m", 0.0)),
                "chord_m": float(row.get("chord_m", 0.0)),
                "twist_deg": float(row.get("twist_deg", row.get("ainc_deg", 0.0))),
                "dihedral_deg": float(row.get("dihedral_deg", 0.0)),
                "reynolds": row.get("reynolds"),
                "target_local_cl": row.get("target_local_cl"),
                "avl_local_cl": row.get("avl_local_cl"),
                "target_circulation_norm": row.get("target_circulation_norm"),
                "avl_circulation_norm": row.get("avl_circulation_norm"),
                "avl_to_target_circulation_ratio": _ratio_or_none(
                    row.get("avl_circulation_norm"),
                    row.get("target_circulation_norm"),
                ),
                "target_clmax_utilization": row.get("target_clmax_utilization"),
            }
        )
    return rows


def _ratio_or_none(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator is None:
        return None
    denom = float(denominator)
    if abs(denom) <= 1.0e-9:
        return None
    return float(numerator) / denom


def compute_outer_loading_diagnostic(
    *,
    station_table: list[dict[str, Any]],
    stations: tuple[WingStation, ...],
    eta_windows: Iterable[tuple[float, float]],
    diagnostic_etas: Iterable[float],
) -> dict[str, Any]:
    if not station_table:
        return _empty_diagnostic()
    eta_samples: list[dict[str, Any]] = []
    for eta_request in diagnostic_etas:
        nearest = min(
            station_table,
            key=lambda row: abs(float(row.get("eta", 0.0)) - float(eta_request)),
        )
        ratio = _ratio_or_none(
            nearest.get("avl_circulation_norm"),
            nearest.get("target_circulation_norm"),
        )
        eta_samples.append(
            {
                "requested_eta": float(eta_request),
                "station_eta": float(nearest.get("eta", 0.0)),
                "y_m": float(nearest.get("y_m", 0.0)),
                "chord_m": float(nearest.get("chord_m", 0.0)),
                "twist_deg": float(nearest.get("twist_deg", nearest.get("ainc_deg", 0.0))),
                "reynolds": nearest.get("reynolds"),
                "target_local_cl": nearest.get("target_local_cl"),
                "avl_local_cl": nearest.get("avl_local_cl"),
                "target_circulation_norm": nearest.get("target_circulation_norm"),
                "avl_circulation_norm": nearest.get("avl_circulation_norm"),
                "avl_to_target_circulation_ratio": ratio,
                "target_clmax_utilization": nearest.get("target_clmax_utilization"),
            }
        )
    windows: list[dict[str, Any]] = []
    eta_tolerance = 1.0e-4
    for eta_lo, eta_hi in eta_windows:
        ratios = []
        worst = {"eta": None, "ratio": None}
        for row in station_table:
            eta = float(row.get("eta", 0.0))
            if (eta_lo - eta_tolerance) <= eta <= (eta_hi + eta_tolerance):
                ratio = _ratio_or_none(
                    row.get("avl_circulation_norm"),
                    row.get("target_circulation_norm"),
                )
                if ratio is None:
                    continue
                ratios.append(ratio)
                if worst["ratio"] is None or float(ratio) < float(worst["ratio"]):
                    worst = {"eta": eta, "ratio": ratio}
        if ratios:
            windows.append(
                {
                    "eta_lo": float(eta_lo),
                    "eta_hi": float(eta_hi),
                    "samples": int(len(ratios)),
                    "outer_ratio_min": float(min(ratios)),
                    "outer_ratio_mean": float(sum(ratios) / len(ratios)),
                    "outer_ratio_max": float(max(ratios)),
                    "worst_eta": worst["eta"],
                    "worst_ratio": worst["ratio"],
                }
            )
        else:
            windows.append(
                {
                    "eta_lo": float(eta_lo),
                    "eta_hi": float(eta_hi),
                    "samples": 0,
                    "outer_ratio_min": None,
                    "outer_ratio_mean": None,
                    "outer_ratio_max": None,
                    "worst_eta": None,
                    "worst_ratio": None,
                }
            )

    primary_window = windows[0] if windows else None
    outer_underloaded = (
        primary_window is not None
        and primary_window.get("outer_ratio_min") is not None
        and float(primary_window["outer_ratio_min"]) < 0.85
    )
    return {
        "eta_samples": eta_samples,
        "outer_ratio_windows": windows,
        "outer_underloaded": bool(outer_underloaded),
    }


def run_sweep(
    *,
    cfg: BirdmanConceptConfig,
    baseline: dict[str, Any],
    output_dir: Path,
    avl_binary: str | None,
    ainc_amps_deg: tuple[float, ...] = DEFAULT_AINC_AMPS_DEG,
    chord_amps: tuple[float, ...] = DEFAULT_CHORD_AMPS,
    target_outer_taper_fractions: tuple[float, ...] = DEFAULT_TARGET_OUTER_TAPER_FRACTIONS,
    run_combined: bool = True,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    concept = baseline["concept"]
    stations = baseline["stations"]
    zone_paths = baseline["zone_airfoil_paths"]
    design_speed_mps = float(baseline["design_speed_mps"])

    ainc_records: list[dict[str, Any]] = []
    chord_records: list[dict[str, Any]] = []
    target_records: list[dict[str, Any]] = []
    combined_records: list[dict[str, Any]] = []

    baseline_record = evaluate_intervention(
        cfg=cfg,
        concept=concept,
        stations=stations,
        output_dir=output_dir,
        design_speed_mps=design_speed_mps,
        avl_binary=avl_binary,
        case_tag="baseline",
        zone_airfoil_paths=zone_paths,
    )
    baseline_record["intervention"] = "baseline_reproduction"
    ainc_records.append(_record_with_intervention(baseline_record, "ainc_bump_deg", 0.0))
    chord_records.append(_record_with_intervention(baseline_record, "chord_bump_amplitude", 0.0))
    target_records.append(
        _record_with_intervention(baseline_record, "outer_taper_fraction", 0.0)
    )

    for amp in ainc_amps_deg:
        if math.isclose(float(amp), 0.0):
            continue
        new_stations = apply_outer_ainc_bump(stations=stations, amplitude_deg=float(amp))
        record = evaluate_intervention(
            cfg=cfg,
            concept=concept,
            stations=new_stations,
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            avl_binary=avl_binary,
            case_tag=f"ainc_bump_{amp:+.2f}deg",
            zone_airfoil_paths=zone_paths,
        )
        ainc_records.append(_record_with_intervention(record, "ainc_bump_deg", float(amp)))

    for amp in chord_amps:
        if math.isclose(float(amp), 0.0):
            continue
        new_stations = apply_outer_chord_redistribution(
            stations=stations,
            amplitude=float(amp),
        )
        record = evaluate_intervention(
            cfg=cfg,
            concept=concept,
            stations=new_stations,
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            avl_binary=avl_binary,
            case_tag=f"chord_bump_{amp:+.2f}",
            zone_airfoil_paths=zone_paths,
        )
        chord_records.append(_record_with_intervention(record, "chord_bump_amplitude", float(amp)))

    for fraction in target_outer_taper_fractions:
        if math.isclose(float(fraction), 0.0):
            continue
        new_a3, new_a5 = apply_outer_target_taper(
            a3_over_a1=float(concept.spanload_a3_over_a1),
            a5_over_a1=float(concept.spanload_a5_over_a1),
            outer_taper_fraction=float(fraction),
        )
        record = evaluate_intervention(
            cfg=cfg,
            concept=concept,
            stations=stations,
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            avl_binary=avl_binary,
            case_tag=f"target_taper_{fraction:+.2f}",
            zone_airfoil_paths=zone_paths,
            a3_over_a1=new_a3,
            a5_over_a1=new_a5,
        )
        target_records.append(
            _record_with_intervention(record, "outer_taper_fraction", float(fraction))
        )

    if run_combined:
        # Take a sensible Ainc + chord combo and report it as the integrated
        # intervention candidate.
        combo_ainc_amp = 1.0
        combo_chord_amp = 0.20
        combo_stations = apply_outer_chord_redistribution(
            stations=apply_outer_ainc_bump(
                stations=stations, amplitude_deg=combo_ainc_amp
            ),
            amplitude=combo_chord_amp,
        )
        record = evaluate_intervention(
            cfg=cfg,
            concept=concept,
            stations=combo_stations,
            output_dir=output_dir,
            design_speed_mps=design_speed_mps,
            avl_binary=avl_binary,
            case_tag=f"combo_ainc{combo_ainc_amp:.2f}_chord{combo_chord_amp:+.2f}",
            zone_airfoil_paths=zone_paths,
        )
        record["intervention_combo"] = {
            "ainc_bump_deg": combo_ainc_amp,
            "chord_bump_amplitude": combo_chord_amp,
        }
        combined_records.append(record)

    summary = build_sweep_summary(
        baseline_record=baseline_record,
        ainc_records=ainc_records,
        chord_records=chord_records,
        target_records=target_records,
        combined_records=combined_records,
    )
    report = {
        "schema_version": "birdman_outer_loading_authority_sweep_v1",
        "baseline": {
            "sample_index": int(baseline.get("baseline_sample_index", 0)),
            "design_speed_mps": float(design_speed_mps),
            "saved_avl_e_cdi": float(baseline.get("baseline_avl_e_cdi", 0.0)),
            "reproduced_avl_e_cdi": baseline_record.get("avl_e_cdi"),
            "reproduction_delta": (
                None
                if baseline_record.get("avl_e_cdi") is None
                else abs(
                    float(baseline_record["avl_e_cdi"])
                    - float(baseline.get("baseline_avl_e_cdi", 0.0))
                )
            ),
            "zone_airfoil_paths": {
                str(zone): str(path) for zone, path in (zone_paths or {}).items()
            },
        },
        "interventions": {
            "ainc_authority_sweep": ainc_records,
            "chord_redistribution_sweep": chord_records,
            "target_taper_sweep": target_records,
            "combined_low_order": combined_records,
        },
        "summary": summary,
    }
    report["engineering_read"] = build_engineering_read(report)
    return report


def _record_with_intervention(
    record: dict[str, Any],
    knob: str,
    value: float,
) -> dict[str, Any]:
    enriched = dict(record)
    enriched.setdefault("knob", knob)
    enriched["knob_value"] = float(value)
    return enriched


def _safe_avl_e(record: dict[str, Any]) -> float:
    value = record.get("avl_e_cdi")
    return float(value) if value is not None else float("nan")


def _window_metric(record: dict[str, Any], window_index: int, key: str) -> float | None:
    diag = record.get("diagnostic") or {}
    windows = diag.get("outer_ratio_windows") or []
    if window_index >= len(windows):
        return None
    return windows[window_index].get(key)


def build_sweep_summary(
    *,
    baseline_record: dict[str, Any],
    ainc_records: list[dict[str, Any]],
    chord_records: list[dict[str, Any]],
    target_records: list[dict[str, Any]],
    combined_records: list[dict[str, Any]],
) -> dict[str, Any]:
    def best_by_e(records: list[dict[str, Any]]) -> dict[str, Any] | None:
        ok = [record for record in records if record.get("avl_e_cdi") is not None]
        if not ok:
            return None
        return max(ok, key=lambda r: float(r["avl_e_cdi"]))

    def best_by_window(
        records: list[dict[str, Any]], window_index: int, key: str
    ) -> dict[str, Any] | None:
        ok = [
            record
            for record in records
            if _window_metric(record, window_index, key) is not None
        ]
        if not ok:
            return None
        return max(ok, key=lambda r: float(_window_metric(r, window_index, key) or 0.0))

    def deltas(record: dict[str, Any] | None) -> dict[str, Any]:
        if record is None:
            return {}
        baseline_e = _safe_avl_e(baseline_record)
        record_e = _safe_avl_e(record)
        return {
            "case_tag": record.get("case_tag"),
            "intervention_value": record.get("knob_value"),
            "knob": record.get("knob"),
            "avl_e_cdi": record.get("avl_e_cdi"),
            "avl_e_cdi_delta_vs_baseline": (
                None
                if math.isnan(record_e) or math.isnan(baseline_e)
                else float(record_e - baseline_e)
            ),
            "outer_ratio_mean_eta_0p70_to_0p95": _window_metric(
                record, 0, "outer_ratio_mean"
            ),
            "outer_ratio_min_eta_0p70_to_0p95": _window_metric(
                record, 0, "outer_ratio_min"
            ),
            "outer_ratio_mean_eta_0p80_to_0p92": _window_metric(
                record, 1, "outer_ratio_mean"
            ),
            "outer_ratio_min_eta_0p80_to_0p92": _window_metric(
                record, 1, "outer_ratio_min"
            ),
        }

    return {
        "baseline_summary": deltas(baseline_record),
        "best_ainc_by_e": deltas(best_by_e(ainc_records)),
        "best_chord_by_e": deltas(best_by_e(chord_records)),
        "best_target_taper_by_e": deltas(best_by_e(target_records)),
        "best_combined_by_e": deltas(best_by_e(combined_records)),
        "best_ainc_by_outer_ratio_mean": deltas(
            best_by_window(ainc_records, 0, "outer_ratio_mean")
        ),
        "best_chord_by_outer_ratio_mean": deltas(
            best_by_window(chord_records, 0, "outer_ratio_mean")
        ),
    }


def build_engineering_read(report: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    summary = report.get("summary") or {}
    baseline = summary.get("baseline_summary") or {}
    lines.append(
        "Baseline reproduction: "
        f"e_CDi={baseline.get('avl_e_cdi')}, "
        f"outer_ratio_mean[0.70-0.95]={baseline.get('outer_ratio_mean_eta_0p70_to_0p95')}, "
        f"outer_ratio_min[0.80-0.92]={baseline.get('outer_ratio_min_eta_0p80_to_0p92')}."
    )
    candidates = [
        ("Outer Ainc bump", summary.get("best_ainc_by_e")),
        ("Outer chord redistribution", summary.get("best_chord_by_e")),
        ("Target outer taper", summary.get("best_target_taper_by_e")),
        ("Combined low-order", summary.get("best_combined_by_e")),
    ]
    for label, candidate in candidates:
        if not candidate:
            continue
        lines.append(
            f"{label}: best at {candidate.get('knob')}={candidate.get('intervention_value')}, "
            f"e_CDi={candidate.get('avl_e_cdi')}, "
            f"outer_ratio_mean[0.70-0.95]={candidate.get('outer_ratio_mean_eta_0p70_to_0p95')}, "
            f"delta_e_vs_baseline={candidate.get('avl_e_cdi_delta_vs_baseline')}."
        )
    # Annotate gate health: which interventions break the existing twist gate.
    interventions = report.get("interventions") or {}
    ainc_records = interventions.get("ainc_authority_sweep", [])
    breaking_ainc = [
        record
        for record in ainc_records
        if record.get("twist_gate_metrics")
        and not record["twist_gate_metrics"].get("twist_physical_gates_pass", True)
    ]
    if breaking_ainc:
        breaking_amp = min(float(record["knob_value"]) for record in breaking_ainc)
        passing_ainc_amps = [
            float(record["knob_value"])
            for record in ainc_records
            if record.get("twist_gate_metrics")
            and record["twist_gate_metrics"].get("twist_physical_gates_pass", True)
            and float(record.get("knob_value") or 0.0) > 0.0
        ]
        last_safe = max(passing_ainc_amps) if passing_ainc_amps else 0.0
        lines.append(
            f"Outer Ainc bump >= {breaking_amp:.2f} deg fails the existing outer "
            f"monotonic-washout twist gate (max wash-in step > 0.60 deg). The "
            f"largest within-gate bump tested was {last_safe:.2f} deg; treat that "
            "as the current Ainc authority ceiling and consider a controlled "
            "relaxation only after the gate change is reviewed."
        )
    chord_records = interventions.get("chord_redistribution_sweep", [])
    chord_breaking = [
        record
        for record in chord_records
        if record.get("tip_gate_summary")
        and not record["tip_gate_summary"].get("tip_gates_pass", True)
    ]
    if chord_breaking:
        thresholds = [float(record["knob_value"]) for record in chord_breaking]
        lines.append(
            "Outer chord redistribution above ~"
            f"{min(thresholds):.2f} amplitude currently trips the tip gates; "
            "control the bump shape so it stays within tip protection."
        )
    target_taper_records = interventions.get("target_taper_sweep", [])
    target_taper_changes_e = any(
        record.get("avl_e_cdi") is not None
        and abs(float(record.get("avl_e_cdi", 0.0)) - float(baseline.get("avl_e_cdi") or 0.0))
        > 1.0e-6
        for record in target_taper_records
    )
    if not target_taper_changes_e:
        lines.append(
            "Target outer taper does not change AVL e_CDi (target shape change "
            "only moves the diagnostic ratio, not realised circulation); use it "
            "to keep diagnostics meaningful but never to mask underloading."
        )
    return lines


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report.get("summary") or {}
    baseline_block = report.get("baseline") or {}
    lines: list[str] = [
        "# Birdman Outer Loading Authority Sweep",
        "",
        f"- Sample index: {baseline_block.get('sample_index')}",
        f"- Design speed: {baseline_block.get('design_speed_mps')} m/s",
        f"- Saved baseline e_CDi: {baseline_block.get('saved_avl_e_cdi')}",
        f"- Reproduced baseline e_CDi: {baseline_block.get('reproduced_avl_e_cdi')}",
        f"- Reproduction delta (abs): {baseline_block.get('reproduction_delta')}",
        "",
        "## Engineering Read",
        "",
    ]
    for entry in report.get("engineering_read", []):
        lines.append(f"- {entry}")
    lines.append("")
    lines.append("## Intervention Comparison")
    lines.append("")
    lines.append(
        "| family | knob | value | e_CDi | delta e | outer_ratio_mean[0.70-0.95] | "
        "outer_ratio_min[0.70-0.95] | outer_ratio_mean[0.80-0.92] | outer_ratio_min[0.80-0.92] |"
    )
    lines.append(
        "|---|---|---:|---:|---:|---:|---:|---:|---:|"
    )

    def render_rows(family: str, records: list[dict[str, Any]]) -> None:
        for record in records:
            diagnostic = record.get("diagnostic") or {}
            windows = diagnostic.get("outer_ratio_windows") or []
            window0 = windows[0] if len(windows) >= 1 else {}
            window1 = windows[1] if len(windows) >= 2 else {}
            lines.append(
                "| "
                f"{family} | "
                f"{record.get('knob')} | "
                f"{_format_float(record.get('knob_value'), 3)} | "
                f"{_format_float(record.get('avl_e_cdi'), 4)} | "
                f"{_format_float(record.get('avl_e_cdi_delta_vs_baseline'), 4)} | "
                f"{_format_float(window0.get('outer_ratio_mean'), 3)} | "
                f"{_format_float(window0.get('outer_ratio_min'), 3)} | "
                f"{_format_float(window1.get('outer_ratio_mean'), 3)} | "
                f"{_format_float(window1.get('outer_ratio_min'), 3)} |"
            )

    interventions = report.get("interventions") or {}
    render_rows("ainc", _attach_summary_deltas(interventions.get("ainc_authority_sweep", []), summary["baseline_summary"]))
    render_rows("chord", _attach_summary_deltas(interventions.get("chord_redistribution_sweep", []), summary["baseline_summary"]))
    render_rows("target_taper", _attach_summary_deltas(interventions.get("target_taper_sweep", []), summary["baseline_summary"]))
    render_rows("combined", _attach_summary_deltas(interventions.get("combined_low_order", []), summary["baseline_summary"]))

    lines.append("")
    lines.append("## Spanwise Diagnostic for Best Combined Case")
    lines.append("")
    combined = interventions.get("combined_low_order") or []
    if combined:
        spanwise = combined[0].get("spanwise_table") or []
        lines.append(
            "| eta | y_m | chord_m | twist_deg | target_cl | avl_cl | "
            "target_circ_norm | avl_circ_norm | ratio |"
        )
        lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for row in spanwise:
            lines.append(
                "| "
                f"{_format_float(row.get('eta'), 3)} | "
                f"{_format_float(row.get('y_m'), 3)} | "
                f"{_format_float(row.get('chord_m'), 3)} | "
                f"{_format_float(row.get('twist_deg'), 3)} | "
                f"{_format_float(row.get('target_local_cl'), 3)} | "
                f"{_format_float(row.get('avl_local_cl'), 3)} | "
                f"{_format_float(row.get('target_circulation_norm'), 3)} | "
                f"{_format_float(row.get('avl_circulation_norm'), 3)} | "
                f"{_format_float(row.get('avl_to_target_circulation_ratio'), 3)} |"
            )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _attach_summary_deltas(
    records: list[dict[str, Any]],
    baseline_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    baseline_e = baseline_summary.get("avl_e_cdi")
    baseline_value = float(baseline_e) if baseline_e is not None else float("nan")
    enriched: list[dict[str, Any]] = []
    for record in records:
        avl_e = record.get("avl_e_cdi")
        delta = (
            float(avl_e) - baseline_value
            if avl_e is not None and not math.isnan(baseline_value)
            else None
        )
        enriched.append({**record, "avl_e_cdi_delta_vs_baseline": delta})
    return enriched


def _format_float(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/birdman_upstream_concept_baseline.yaml"),
    )
    parser.add_argument(
        "--baseline-export-dir",
        type=Path,
        default=Path(
            "output/birdman_mission_coupled_medium_search_20260503/top_candidate_exports/rank_01_sample_1476"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/birdman_outer_loading_authority_sweep"),
    )
    parser.add_argument("--avl-binary", default=None)
    parser.add_argument(
        "--ainc-amps-deg",
        default=",".join(f"{value:g}" for value in DEFAULT_AINC_AMPS_DEG),
    )
    parser.add_argument(
        "--chord-amps",
        default=",".join(f"{value:g}" for value in DEFAULT_CHORD_AMPS),
    )
    parser.add_argument(
        "--target-outer-taper-fractions",
        default=",".join(f"{value:g}" for value in DEFAULT_TARGET_OUTER_TAPER_FRACTIONS),
    )
    parser.add_argument("--no-combined", action="store_true")
    return parser.parse_args()


def _parse_float_tuple(text: str) -> tuple[float, ...]:
    return tuple(float(part.strip()) for part in str(text).split(",") if part.strip())


def main() -> None:
    args = parse_args()
    cfg = load_concept_config(args.config)
    baseline = load_baseline_from_export(cfg=cfg, export_dir=args.baseline_export_dir)
    report = run_sweep(
        cfg=cfg,
        baseline=baseline,
        output_dir=args.output_dir,
        avl_binary=args.avl_binary,
        ainc_amps_deg=_parse_float_tuple(args.ainc_amps_deg),
        chord_amps=_parse_float_tuple(args.chord_amps),
        target_outer_taper_fractions=_parse_float_tuple(args.target_outer_taper_fractions),
        run_combined=not args.no_combined,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "outer_loading_authority_sweep.json"
    md_path = args.output_dir / "outer_loading_authority_sweep.md"
    json_path.write_text(
        json.dumps(spanload_smoke._round(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_markdown(spanload_smoke._round(report), md_path)
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
