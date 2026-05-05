"""Offline CST/NSGA/XFOIL airfoil database builder for sidecar studies.

The builder is deliberately outside the aircraft ranking route.  It uses
Sobol only to create the first seedless CST population, then runs an
NSGA2-style constrained Pareto loop with the existing CST variation operators
and XFOIL worker.  Every exported record remains quality-labeled.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from hpa_mdo.airfoils.database import (
    AirfoilDatabase,
    AirfoilPolarPoint,
    AirfoilRecord,
    ZoneEnvelope,
)
from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    analyze_cst_geometry,
    generate_cst_coordinates,
    sample_feasible_seedless_cst_sobol,
    validate_seedless_cst_template,
)
from hpa_mdo.concept.airfoil_nsga import generate_seedless_nsga2_offspring
from hpa_mdo.concept.airfoil_pareto import (
    AirfoilParetoCandidate,
    rank_constrained_pareto_candidates,
    select_nsga2_survivors,
)
from hpa_mdo.concept.airfoil_selection import (
    _default_seedless_cst_bounds,
    _seedless_constraints_for_zone,
)
from hpa_mdo.concept.airfoil_worker import PolarQuery, geometry_hash_from_coordinates


CST_DATABASE_SOURCE = "offline_cst_zone_nsga_xfoil_database_builder_v1"
_ZONE_ORDER = ("root", "mid1", "mid2", "tip")


@dataclass(frozen=True)
class CSTZoneSearchConfig:
    population_size_per_zone: int = 128
    generations: int = 8
    nsga_parent_count: int = 64
    mutation_scale: float = 0.06
    sample_count_per_zone: int | None = None
    coarse_score_count: int = 96
    robust_score_count: int = 24
    top_k_per_zone: int = 8
    re_robustness_factors: tuple[float, ...] = (0.85, 1.00, 1.15)
    roughness_modes: tuple[str, ...] = ("clean", "rough")
    panel_count: int = 96
    xfoil_max_iter: int = 40
    convergence_pass_rate_threshold: float = 0.80
    required_stall_margin_cl: float = 0.03
    cl_coverage_margin: float = 0.25
    random_seed: int | None = 17
    max_oversample_factor: int = 8
    source_quality_policy: str = "require_real_worker_and_quality_pass"


@dataclass(frozen=True)
class CSTZoneSearchResult:
    airfoil_database: AirfoilDatabase
    report: dict[str, Any]
    paths: dict[str, Path]


@dataclass(frozen=True)
class _ResumeState:
    completed_zone_names: frozenset[str]
    records: tuple[AirfoilRecord, ...]
    polar_rows: tuple[dict[str, Any], ...]
    per_zone_rows: tuple[dict[str, Any], ...]
    top_k_rows: tuple[dict[str, Any], ...]
    failed_rows: tuple[dict[str, Any], ...]
    geometry_rejection_rows: tuple[dict[str, Any], ...]
    coverage_rows: tuple[dict[str, Any], ...]
    report_zones: dict[str, Any]


def load_zone_envelopes_from_artifact(path: Path) -> tuple[ZoneEnvelope, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        rows = payload.get("zone_envelope", payload.get("zone_envelopes", []))
    else:
        raise ValueError("zone envelope artifact must be a JSON object or list.")

    envelopes: list[ZoneEnvelope] = []
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        zone_name = str(item.get("zone_name", item.get("zone", ""))).strip()
        if not zone_name:
            continue
        envelopes.append(
            ZoneEnvelope(
                zone_name=zone_name,
                eta_min=float(item.get("eta_min", 0.0)),
                eta_max=float(item.get("eta_max", 1.0)),
                re_min=_finite_float(item.get("re_min")),
                re_max=_finite_float(item.get("re_max")),
                re_p50=_finite_float(item.get("re_p50")),
                cl_min=_finite_float(item.get("cl_min")),
                cl_max=_finite_float(item.get("cl_max")),
                cl_p50=_finite_float(item.get("cl_p50")),
                cl_p90=_finite_float(item.get("cl_p90")),
                max_avl_actual_cl=_finite_float(item.get("max_avl_actual_cl")),
                max_fourier_target_cl=_finite_float(item.get("max_fourier_target_cl")),
                target_vs_actual_cl_delta=_finite_float(item.get("target_vs_actual_cl_delta")),
                current_airfoil_id=(
                    None
                    if item.get("current_airfoil_id") is None
                    else str(item.get("current_airfoil_id"))
                ),
                current_stall_margin=_finite_float(item.get("current_stall_margin")),
                current_profile_cd_estimate=_finite_float(item.get("current_profile_cd_estimate")),
                source=str(item.get("source", "loaded_dihedral_avl")),
            )
        )
    return tuple(
        sorted(
            envelopes,
            key=lambda envelope: (
                _ZONE_ORDER.index(envelope.zone_name)
                if envelope.zone_name in _ZONE_ORDER
                else 99
            ),
        )
    )


def _empty_resume_state() -> _ResumeState:
    return _ResumeState(
        completed_zone_names=frozenset(),
        records=tuple(),
        polar_rows=tuple(),
        per_zone_rows=tuple(),
        top_k_rows=tuple(),
        failed_rows=tuple(),
        geometry_rejection_rows=tuple(),
        coverage_rows=tuple(),
        report_zones={},
    )


def _load_resume_state(
    output: Path,
    *,
    config: CSTZoneSearchConfig,
    requested_zone_names: frozenset[str],
    forced_zone_names: frozenset[str] = frozenset(),
) -> _ResumeState:
    report_path = output / "build_report.json"
    database_path = output / "airfoil_database.json"
    if not report_path.is_file() or not database_path.is_file():
        return _empty_resume_state()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    raw_zones = report.get("zones", {}) if isinstance(report, Mapping) else {}
    completed_zone_names = frozenset(
        zone_name
        for zone_name, zone_report in raw_zones.items()
        if zone_name in requested_zone_names
        and zone_name not in forced_zone_names
        and _resume_zone_is_complete(zone_report, config=config)
    )
    if not completed_zone_names:
        return _empty_resume_state()

    database_payload = json.loads(database_path.read_text(encoding="utf-8"))
    records = tuple(
        record
        for record in (
            _airfoil_record_from_dict(item)
            for item in database_payload.get("records", [])
            if isinstance(item, Mapping)
        )
        if record.zone_hint in completed_zone_names
    )
    report_zones = {
        zone_name: {
            **dict(raw_zones[zone_name]),
            "resume_status": "skipped_complete_zone",
        }
        for zone_name in completed_zone_names
        if zone_name in raw_zones
    }
    return _ResumeState(
        completed_zone_names=completed_zone_names,
        records=records,
        polar_rows=tuple(_read_zone_csv_rows(output / "airfoil_database.csv", completed_zone_names)),
        per_zone_rows=tuple(_read_zone_csv_rows(output / "per_zone_pareto.csv", completed_zone_names)),
        top_k_rows=tuple(_read_zone_csv_rows(output / "per_zone_top_k.csv", completed_zone_names)),
        failed_rows=tuple(_read_zone_csv_rows(output / "failed_candidates.csv", completed_zone_names)),
        geometry_rejection_rows=tuple(
            _read_zone_csv_rows(output / "geometry_rejections.csv", completed_zone_names)
        ),
        coverage_rows=tuple(_read_zone_csv_rows(output / "coverage_report.csv", completed_zone_names)),
        report_zones=report_zones,
    )


def _resume_zone_is_complete(zone_report: object, *, config: CSTZoneSearchConfig) -> bool:
    if not isinstance(zone_report, Mapping):
        return False
    generation_summaries = zone_report.get("generation_summaries", [])
    if not isinstance(generation_summaries, list):
        return False
    expected_generations = _generation_count(config)
    expected_evaluated = _population_size(config) * expected_generations
    return (
        len(generation_summaries) >= expected_generations
        and int(zone_report.get("evaluated_candidate_count", 0)) >= expected_evaluated
    )


def _airfoil_record_from_dict(item: Mapping[str, Any]) -> AirfoilRecord:
    polar_points = tuple(
        AirfoilPolarPoint(
            Re=float(point.get("Re")),
            cl=float(point.get("cl")),
            cd=float(point.get("cd")),
            cm=float(point.get("cm")),
            alpha_deg=float(point.get("alpha_deg")),
            roughness_mode=str(point.get("roughness_mode", "clean")),
        )
        for point in item.get("polar_points", [])
        if isinstance(point, Mapping)
    )
    return AirfoilRecord(
        airfoil_id=str(item["airfoil_id"]),
        name=str(item.get("name", item["airfoil_id"])),
        source=str(item.get("source", CST_DATABASE_SOURCE)),
        source_quality=str(item["source_quality"]),
        zone_hint=str(item["zone_hint"]),
        thickness_ratio=float(item.get("thickness_ratio", 0.0)),
        max_camber=float(item.get("max_camber", 0.0)),
        alpha_L0_deg=float(item.get("alpha_L0_deg", 0.0)),
        cl_alpha_per_rad=float(item.get("cl_alpha_per_rad", 2.0 * math.pi)),
        cm_design=float(item.get("cm_design", 0.0)),
        safe_clmax=float(item.get("safe_clmax", float("nan"))),
        usable_clmax=float(item.get("usable_clmax", float("nan"))),
        polar_points=polar_points,
        notes=str(item.get("notes", "")),
        coordinate_path=(
            None if item.get("coordinate_path") is None else str(item.get("coordinate_path"))
        ),
    )


def _read_zone_csv_rows(path: Path, zone_names: frozenset[str]) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            dict(row)
            for row in csv.DictReader(handle)
            if str(row.get("zone_name", "")) in zone_names
        ]


def zone_work_points_from_envelope(envelope: ZoneEnvelope) -> tuple[dict[str, Any], ...]:
    re_min = _first_finite(envelope.re_min, envelope.re_p50, envelope.re_max, 250_000.0)
    re_p50 = _first_finite(envelope.re_p50, envelope.re_min, envelope.re_max, 250_000.0)
    re_max = _first_finite(envelope.re_max, envelope.re_p50, envelope.re_min, 250_000.0)
    cl_min = _first_finite(envelope.cl_min, envelope.cl_p50, envelope.cl_max, 0.5)
    cl_p50 = _first_finite(envelope.cl_p50, envelope.cl_min, envelope.cl_max, 0.7)
    cl_p90 = _first_finite(envelope.cl_p90, envelope.cl_max, envelope.cl_p50, 0.9)
    cl_max = _first_finite(envelope.cl_max, envelope.max_avl_actual_cl, envelope.cl_p90, 1.0)
    raw = (
        ("min", re_min, cl_min, 0.8),
        ("p50", re_p50, cl_p50, 1.0),
        ("p90", re_p50, cl_p90, 1.1),
        ("max", re_max, cl_max, 1.2),
    )
    points: list[dict[str, Any]] = []
    seen: set[tuple[float, float]] = set()
    for label, re_value, cl_value, weight in raw:
        key = (round(float(re_value), 3), round(float(cl_value), 4))
        if key in seen:
            continue
        seen.add(key)
        points.append(
            {
                "zone_name": envelope.zone_name,
                "label": label,
                "reynolds": float(re_value),
                "cl_target": float(cl_value),
                "weight": float(weight),
                "source": envelope.source,
            }
        )
    return tuple(points)


def build_cst_zone_airfoil_database(
    *,
    zone_envelope_path: Path,
    output_dir: Path,
    config: CSTZoneSearchConfig,
    worker: Any,
    progress_callback: Any | None = None,
    resume: bool = False,
    force_zones: Sequence[str] = (),
) -> CSTZoneSearchResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    coordinate_dir = output / "coordinates"
    coordinate_dir.mkdir(parents=True, exist_ok=True)
    envelopes = load_zone_envelopes_from_artifact(zone_envelope_path)
    if not envelopes:
        raise ValueError("No zone envelopes were available for CST database build.")
    requested_zone_names = frozenset(str(envelope.zone_name) for envelope in envelopes)
    forced_zone_names = frozenset(str(zone_name).strip() for zone_name in force_zones if str(zone_name).strip())
    resume_state = (
        _load_resume_state(
            output,
            config=config,
            requested_zone_names=requested_zone_names,
            forced_zone_names=forced_zone_names,
        )
        if resume
        else _empty_resume_state()
    )

    records: list[AirfoilRecord] = list(resume_state.records)
    all_polar_rows: list[dict[str, Any]] = list(resume_state.polar_rows)
    per_zone_rows: list[dict[str, Any]] = list(resume_state.per_zone_rows)
    top_k_rows: list[dict[str, Any]] = list(resume_state.top_k_rows)
    failed_rows: list[dict[str, Any]] = list(resume_state.failed_rows)
    geometry_rejection_rows: list[dict[str, Any]] = list(resume_state.geometry_rejection_rows)
    coverage_rows: list[dict[str, Any]] = list(resume_state.coverage_rows)
    report_zones: dict[str, Any] = dict(resume_state.report_zones)

    _write_run_metadata(
        output,
        config=config,
        zone_envelope_path=zone_envelope_path,
        status="running",
        extra={
            "resume": bool(resume),
            "force_zones": sorted(forced_zone_names),
            "completed_zones": list(report_zones),
        },
    )
    for zone_index, envelope in enumerate(envelopes):
        zone_name = str(envelope.zone_name)
        if zone_name in resume_state.completed_zone_names:
            _emit_progress(
                progress_callback,
                "zone_skipped_resume",
                zone_name=zone_name,
                zone_index=zone_index,
                reason="completed_zone_present_in_existing_artifacts",
            )
            continue
        _emit_progress(progress_callback, "zone_start", zone_name=zone_name, zone_index=zone_index)
        work_points = zone_work_points_from_envelope(envelope)
        population_size = _population_size(config)
        generation_count = _generation_count(config)
        initial_population, rejections = _generate_initial_population(
            zone_name=zone_name,
            config=config,
            zone_index=zone_index,
            candidate_count=population_size,
        )
        geometry_rejection_rows.extend(rejections)

        current_population = tuple(initial_population)
        zone_results: list[dict[str, Any]] = []
        generation_summaries: list[dict[str, Any]] = []
        final_generation_index = -1
        for generation_index in range(generation_count):
            final_generation_index = generation_index
            _emit_progress(
                progress_callback,
                "generation_start",
                zone_name=zone_name,
                generation_index=generation_index,
                population_count=len(current_population),
            )
            generation_results = _evaluate_candidates(
                zone_name=zone_name,
                candidates=current_population,
                envelope=envelope,
                work_points=work_points,
                config=config,
                worker=worker,
                backend_name=str(getattr(worker, "backend_name", "unknown_worker")),
                stage=f"nsga_generation_{generation_index}",
            )
            zone_results.extend(generation_results)
            generation_summaries.append(_generation_summary(generation_index, generation_results))
            ranked_results = _rank_zone_results(zone_results)
            _write_partial_checkpoint(
                output,
                config=config,
                zone_envelope_path=zone_envelope_path,
                coordinate_dir=coordinate_dir,
                completed_records=records,
                completed_polar_rows=all_polar_rows,
                completed_per_zone_rows=per_zone_rows,
                completed_top_k_rows=top_k_rows,
                completed_failed_rows=failed_rows,
                completed_coverage_rows=coverage_rows,
                geometry_rejection_rows=geometry_rejection_rows,
                envelopes=envelopes,
                report_zones={
                    **report_zones,
                    zone_name: _zone_report(
                        envelope=envelope,
                        initial_population_count=len(initial_population),
                        evaluated_results=ranked_results,
                        rejections=rejections,
                        generation_summaries=generation_summaries,
                        work_points=work_points,
                        generation_count=generation_count,
                    ),
                },
                zone_results=ranked_results,
                status="partial",
            )
            _emit_progress(
                progress_callback,
                "generation_done",
                zone_name=zone_name,
                generation_index=generation_index,
                evaluated_candidate_count=len(generation_results),
                total_zone_evaluated_count=len(zone_results),
                mission_grade_count=generation_summaries[-1]["mission_grade_candidate_count"],
            )
            if generation_index >= generation_count - 1:
                break
            survivors = _select_survivor_templates(
                ranked_results,
                survivor_count=min(max(2, int(config.nsga_parent_count)), len(ranked_results)),
            )
            if len(survivors) < 2:
                _emit_progress(
                    progress_callback,
                    "nsga_offspring_blocked",
                    zone_name=zone_name,
                    generation_index=generation_index,
                    reason="fewer_than_two_survivors",
                )
                break
            current_population = _generate_nsga_offspring(
                zone_name=zone_name,
                parents=survivors,
                config=config,
                zone_index=zone_index,
                generation_index=generation_index + 1,
                offspring_count=population_size,
            )
            if not current_population:
                _emit_progress(
                    progress_callback,
                    "nsga_offspring_blocked",
                    zone_name=zone_name,
                    generation_index=generation_index,
                    reason="offspring_generation_failed",
                )
                break

        ranked_zone_results = _rank_zone_results(zone_results)
        zone_records = [
            _record_from_candidate_result(item, coordinate_dir=coordinate_dir)
            for item in ranked_zone_results
        ]
        for rank, (record, item) in enumerate(zip(zone_records, ranked_zone_results, strict=True), start=1):
            records.append(record)
            all_polar_rows.extend(_polar_rows_for_record(record, item))
            row = _summary_row(record, item, rank=rank)
            per_zone_rows.append(row)
            coverage_rows.append(_coverage_row(record, item))
            if record.source_quality == "cst_xfoil_failed_not_mission_grade":
                failed_rows.append(row)
            if rank <= int(config.top_k_per_zone):
                top_k_rows.append(row)
        report_zones[zone_name] = _zone_report(
            envelope=envelope,
            initial_population_count=len(initial_population),
            evaluated_results=ranked_zone_results,
            rejections=rejections,
            generation_summaries=generation_summaries,
            work_points=work_points,
            generation_count=final_generation_index + 1,
        )
        database = AirfoilDatabase.from_records(records)
        report = _build_report(
            config=config,
            envelopes=envelopes,
            report_zones=report_zones,
            records=records,
            status="partial",
        )
        _write_artifacts(
            output,
            database=database,
            report=report,
            polar_rows=all_polar_rows,
            per_zone_rows=per_zone_rows,
            top_k_rows=top_k_rows,
            failed_rows=failed_rows,
            geometry_rejection_rows=geometry_rejection_rows,
            coverage_rows=coverage_rows,
        )
        _write_run_metadata(
            output,
            config=config,
            zone_envelope_path=zone_envelope_path,
            status="partial",
            extra={"completed_zones": list(report_zones)},
        )
        _emit_progress(
            progress_callback,
            "zone_done",
            zone_name=zone_name,
            evaluated_candidate_count=len(ranked_zone_results),
            mission_grade_count=report_zones[zone_name]["mission_grade_candidate_count"],
        )

    database = AirfoilDatabase.from_records(records)
    report = _build_report(
        config=config,
        envelopes=envelopes,
        report_zones=report_zones,
        records=records,
        status="complete",
    )
    paths = _write_artifacts(
        output,
        database=database,
        report=report,
        polar_rows=all_polar_rows,
        per_zone_rows=per_zone_rows,
        top_k_rows=top_k_rows,
        failed_rows=failed_rows,
        geometry_rejection_rows=geometry_rejection_rows,
        coverage_rows=coverage_rows,
    )
    _write_run_metadata(
        output,
        config=config,
        zone_envelope_path=zone_envelope_path,
        status="complete",
        extra={"completed_zones": list(report_zones), "paths": _stringify_paths(paths)},
    )
    _emit_progress(progress_callback, "build_done", record_count=len(records))
    return CSTZoneSearchResult(airfoil_database=database, report=report, paths=paths)


def _write_partial_checkpoint(
    output: Path,
    *,
    config: CSTZoneSearchConfig,
    zone_envelope_path: Path,
    coordinate_dir: Path,
    completed_records: Sequence[AirfoilRecord],
    completed_polar_rows: Sequence[Mapping[str, Any]],
    completed_per_zone_rows: Sequence[Mapping[str, Any]],
    completed_top_k_rows: Sequence[Mapping[str, Any]],
    completed_failed_rows: Sequence[Mapping[str, Any]],
    completed_coverage_rows: Sequence[Mapping[str, Any]],
    geometry_rejection_rows: Sequence[Mapping[str, Any]],
    envelopes: Sequence[ZoneEnvelope],
    report_zones: Mapping[str, Any],
    zone_results: Sequence[Mapping[str, Any]],
    status: str,
) -> None:
    zone_records = [
        _record_from_candidate_result(item, coordinate_dir=coordinate_dir)
        for item in zone_results
    ]
    zone_summary_rows = [
        _summary_row(record, item, rank=rank)
        for rank, (record, item) in enumerate(zip(zone_records, zone_results, strict=True), start=1)
    ]
    zone_polar_rows = [
        row
        for record, item in zip(zone_records, zone_results, strict=True)
        for row in _polar_rows_for_record(record, item)
    ]
    zone_coverage_rows = [
        _coverage_row(record, item)
        for record, item in zip(zone_records, zone_results, strict=True)
    ]
    database = AirfoilDatabase.from_records((*completed_records, *zone_records))
    report = _build_report(
        config=config,
        envelopes=envelopes,
        report_zones=report_zones,
        records=database.records.values(),
        status=status,
    )
    _write_artifacts(
        output,
        database=database,
        report=report,
        polar_rows=[*completed_polar_rows, *zone_polar_rows],
        per_zone_rows=[*completed_per_zone_rows, *zone_summary_rows],
        top_k_rows=[
            *completed_top_k_rows,
            *[
                row
                for row in zone_summary_rows
                if int(row["rank_in_zone"]) <= int(config.top_k_per_zone)
            ],
        ],
        failed_rows=[
            *completed_failed_rows,
            *[
                row
                for row in zone_summary_rows
                if row["source_quality"] == "cst_xfoil_failed_not_mission_grade"
            ],
        ],
        geometry_rejection_rows=geometry_rejection_rows,
        coverage_rows=[*completed_coverage_rows, *zone_coverage_rows],
    )
    active_zone = next(reversed(report_zones)) if report_zones else None
    active_report = report_zones.get(active_zone, {}) if active_zone else {}
    generation_summaries = active_report.get("generation_summaries", [])
    active_generation = (
        generation_summaries[-1].get("generation_index")
        if isinstance(generation_summaries, list) and generation_summaries
        else None
    )
    _write_run_metadata(
        output,
        config=config,
        zone_envelope_path=zone_envelope_path,
        status=status,
        extra={
            "completed_zones": [
                zone
                for zone, item in report_zones.items()
                if zone != active_zone or item.get("status") == "complete"
            ],
            "active_zone": active_zone,
            "active_generation": active_generation,
        },
    )


def _generate_initial_population(
    *,
    zone_name: str,
    config: CSTZoneSearchConfig,
    zone_index: int,
    candidate_count: int,
) -> tuple[tuple[CSTAirfoilTemplate, ...], list[dict[str, Any]]]:
    constraints = _zone_constraints(zone_name)
    raw = sample_feasible_seedless_cst_sobol(
        zone_name=zone_name,
        sample_count=int(candidate_count),
        bounds=_default_seedless_cst_bounds(zone_name),
        constraints=constraints,
        random_seed=None if config.random_seed is None else int(config.random_seed) + 101 * zone_index,
        max_oversample_factor=int(config.max_oversample_factor),
    )
    valid: list[CSTAirfoilTemplate] = []
    rejections: list[dict[str, Any]] = []
    for candidate in raw:
        outcome = validate_seedless_cst_template(candidate, constraints=constraints)
        if outcome.valid:
            valid.append(candidate)
        else:
            rejections.append(
                {
                    "zone_name": zone_name,
                    "candidate_role": candidate.candidate_role,
                    "rejection_reason": outcome.reason,
                }
            )
    return tuple(valid), rejections


def _evaluate_candidates(
    *,
    zone_name: str,
    candidates: Sequence[CSTAirfoilTemplate],
    envelope: ZoneEnvelope,
    work_points: Sequence[Mapping[str, Any]],
    config: CSTZoneSearchConfig,
    worker: Any,
    backend_name: str,
    stage: str,
) -> list[dict[str, Any]]:
    queries: list[PolarQuery] = []
    query_to_candidate: dict[str, CSTAirfoilTemplate] = {}
    re_samples = _re_samples_for_envelope(envelope, config=config)
    cl_samples = _cl_samples_for_envelope(envelope, config=config)
    for candidate in candidates:
        coordinates = generate_cst_coordinates(candidate)
        geometry_hash = geometry_hash_from_coordinates(coordinates)
        airfoil_id = _airfoil_id(zone_name, candidate, geometry_hash)
        for re_value in re_samples:
            for roughness_mode in config.roughness_modes:
                template_id = f"{airfoil_id}__{stage}__re{float(re_value):.0f}__{roughness_mode}"
                queries.append(
                    PolarQuery(
                        template_id=template_id,
                        reynolds=float(re_value),
                        cl_samples=cl_samples,
                        roughness_mode=str(roughness_mode),
                        geometry_hash=geometry_hash,
                        coordinates=coordinates,
                        analysis_mode="screening_target_cl",
                        analysis_stage=f"cst_zone_{stage}",
                    )
                )
                query_to_candidate[template_id] = candidate
    if not queries:
        return []
    worker_results = worker.run_queries(queries)
    grouped: dict[str, list[dict[str, Any]]] = {}
    template_by_airfoil_id: dict[str, CSTAirfoilTemplate] = {}
    for result in worker_results:
        template_id = str(result.get("template_id", ""))
        candidate = query_to_candidate.get(template_id)
        if candidate is None:
            continue
        airfoil_id = template_id.split("__", 1)[0]
        grouped.setdefault(airfoil_id, []).append(dict(result))
        template_by_airfoil_id[airfoil_id] = candidate

    evaluated: list[dict[str, Any]] = []
    for airfoil_id, results in grouped.items():
        evaluated.append(
            _candidate_result(
                airfoil_id=airfoil_id,
                zone_name=zone_name,
                template=template_by_airfoil_id[airfoil_id],
                envelope=envelope,
                work_points=work_points,
                worker_results=results,
                expected_query_count=len(re_samples) * len(config.roughness_modes),
                backend_name=backend_name,
                config=config,
                stage=stage,
            )
        )
    return evaluated


def _candidate_result(
    *,
    airfoil_id: str,
    zone_name: str,
    template: CSTAirfoilTemplate,
    envelope: ZoneEnvelope,
    work_points: Sequence[Mapping[str, Any]],
    worker_results: Sequence[Mapping[str, Any]],
    expected_query_count: int,
    backend_name: str,
    config: CSTZoneSearchConfig,
    stage: str,
) -> dict[str, Any]:
    polar_points: list[AirfoilPolarPoint] = []
    success_results = 0
    for result in worker_results:
        status = str(result.get("status", "unknown"))
        if status in {"ok", "mini_sweep_fallback", "stubbed_ok"}:
            success_results += 1
        re_value = _finite_float(result.get("reynolds"))
        roughness_mode = str(result.get("roughness_mode", "clean"))
        for point in result.get("polar_points", []) or []:
            if not isinstance(point, Mapping):
                continue
            cl = _finite_float(point.get("cl"))
            cd = _finite_float(point.get("cd"))
            cm = _finite_float(point.get("cm"))
            alpha = _finite_float(point.get("alpha_deg"))
            converged = bool(point.get("converged", status in {"ok", "mini_sweep_fallback", "stubbed_ok"}))
            if re_value is None or cl is None or cd is None or cm is None or alpha is None or not converged:
                continue
            polar_points.append(
                AirfoilPolarPoint(
                    Re=float(re_value),
                    cl=float(cl),
                    cd=float(cd),
                    cm=float(cm),
                    alpha_deg=float(alpha),
                    roughness_mode=roughness_mode,
                )
            )

    finite_positive = [
        point
        for point in polar_points
        if math.isfinite(point.cd) and point.cd > 0.0 and math.isfinite(point.cl)
    ]
    total_expected_points = max(
        1,
        int(expected_query_count) * len(_cl_samples_for_envelope(envelope, config=config)),
    )
    pass_rate = len(finite_positive) / total_expected_points
    usable_clmax = max((point.cl for point in finite_positive), default=float("nan"))
    safe_clmax = 0.90 * usable_clmax - 0.05 if math.isfinite(usable_clmax) else float("nan")
    required_cl = _first_finite(envelope.cl_max, envelope.max_avl_actual_cl, envelope.cl_p90, 0.0)
    coverage_failed = not _coverage_passes(finite_positive, work_points)
    cd_values = [point.cd for point in finite_positive]
    cm_values = [point.cm for point in finite_positive if math.isfinite(point.cm)]
    alpha_l0, cl_alpha = _linear_lift_curve_estimate(finite_positive)

    issues: list[str] = []
    if pass_rate < float(config.convergence_pass_rate_threshold):
        issues.append("convergence_pass_rate_below_threshold")
    if len(finite_positive) != len(polar_points):
        issues.append("cd_nonfinite_or_nonpositive")
    if not math.isfinite(usable_clmax):
        issues.append("usable_clmax_nonfinite")
    if safe_clmax < float(required_cl) + float(config.required_stall_margin_cl):
        issues.append("required_cl_stall_margin_not_met")
    if coverage_failed:
        issues.append("zone_envelope_coverage_not_met")
    if len(worker_results) < int(expected_query_count) or success_results < int(expected_query_count):
        issues.append("missing_worker_conditions")

    real_xfoil_backend = str(backend_name) not in {
        "dry_run",
        "dry_run_xfoil_surrogate",
        "stub",
        "stubbed",
    }
    if "cd_nonfinite_or_nonpositive" in issues or not finite_positive:
        source_quality = "cst_xfoil_failed_not_mission_grade"
    elif not real_xfoil_backend or issues:
        source_quality = "cst_xfoil_candidate_not_mission_grade"
    else:
        source_quality = "cst_xfoil_mission_grade_candidate"

    mean_cd = float(np.mean(cd_values)) if cd_values else float("inf")
    cd_p90 = float(np.percentile(np.asarray(cd_values, dtype=float), 90.0)) if cd_values else float("inf")
    mean_cm = float(np.mean(cm_values)) if cm_values else 0.0
    roughness_sensitivity = _roughness_sensitivity(finite_positive)
    stall_margin_cl = safe_clmax - float(required_cl) if math.isfinite(safe_clmax) else float("nan")
    score = (
        mean_cd
        + 0.35 * max(0.0, cd_p90 - mean_cd)
        + 0.006 * abs(mean_cm)
        + 0.02 * max(0.0, -stall_margin_cl)
        + 0.10 * max(0.0, 1.0 - pass_rate)
        + 0.25 * roughness_sensitivity
        + 0.003 * max(0.0, abs(alpha_l0) - 6.0)
    )
    if source_quality != "cst_xfoil_mission_grade_candidate":
        score += 0.05

    try:
        geometry_metrics = asdict(analyze_cst_geometry(template))
    except ValueError as exc:
        geometry_metrics = {"error": str(exc)}

    return {
        "airfoil_id": airfoil_id,
        "zone_name": zone_name,
        "template": template,
        "polar_points": tuple(finite_positive),
        "source_quality": source_quality,
        "issues": issues,
        "pass_rate": pass_rate,
        "pass_rate_threshold": float(config.convergence_pass_rate_threshold),
        "coverage_failed": bool(coverage_failed),
        "worker_success_count": success_results,
        "worker_condition_count": expected_query_count,
        "mean_cd": mean_cd,
        "cd_p90": cd_p90,
        "mean_cm": mean_cm,
        "usable_clmax": usable_clmax,
        "safe_clmax": safe_clmax,
        "required_cl": required_cl,
        "stall_margin_cl": stall_margin_cl,
        "roughness_sensitivity": roughness_sensitivity,
        "alpha_L0_deg": alpha_l0,
        "cl_alpha_per_rad": cl_alpha,
        "score": score,
        "geometry_metrics": geometry_metrics,
        "stage": stage,
        "backend_name": backend_name,
    }


def _record_from_candidate_result(item: Mapping[str, Any], *, coordinate_dir: Path) -> AirfoilRecord:
    template = item["template"]
    coordinates = generate_cst_coordinates(template)
    coordinate_path = coordinate_dir / f"{item['airfoil_id']}.dat"
    _write_airfoil_dat(coordinate_path, name=str(item["airfoil_id"]), coordinates=coordinates)
    polar_points = tuple(item.get("polar_points", ()))
    return AirfoilRecord(
        airfoil_id=str(item["airfoil_id"]),
        name=str(item["airfoil_id"]),
        source=f"{CST_DATABASE_SOURCE}:{coordinate_path}",
        source_quality=str(item.get("source_quality")),
        zone_hint=str(item.get("zone_name")),
        thickness_ratio=float(item.get("geometry_metrics", {}).get("max_thickness_ratio", 0.0)),
        max_camber=float(item.get("geometry_metrics", {}).get("max_camber_ratio", 0.0)),
        alpha_L0_deg=float(item.get("alpha_L0_deg", -2.0)),
        cl_alpha_per_rad=float(item.get("cl_alpha_per_rad", 2.0 * math.pi)),
        cm_design=float(item.get("mean_cm", 0.0)),
        safe_clmax=_finite_or_zero(item.get("safe_clmax")),
        usable_clmax=_finite_or_zero(item.get("usable_clmax")),
        polar_points=polar_points,
        notes=f"Offline CST/NSGA zone candidate; issues={item.get('issues', [])}.",
        coordinate_path=str(coordinate_path),
    )


def _rank_zone_results(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_airfoil_id = {str(item["airfoil_id"]): dict(item) for item in results}
    pareto_candidates = tuple(
        _pareto_candidate_from_result(item) for item in by_airfoil_id.values()
    )
    ranked = rank_constrained_pareto_candidates(pareto_candidates)
    rank_by_id = {entry.candidate.candidate_role: entry for entry in ranked}
    return sorted(
        by_airfoil_id.values(),
        key=lambda item: (
            rank_by_id[str(item["airfoil_id"])].rank,
            -rank_by_id[str(item["airfoil_id"])].crowding_distance,
            rank_by_id[str(item["airfoil_id"])].total_constraint_violation,
            float(item.get("score", float("inf"))),
            str(item["airfoil_id"]),
        ),
    )


def _pareto_candidate_from_result(item: Mapping[str, Any]) -> AirfoilParetoCandidate:
    alpha_l0 = _finite_float(item.get("alpha_L0_deg"))
    alpha_l0_penalty = 0.0 if alpha_l0 is None else max(0.0, abs(alpha_l0) - 6.0)
    return AirfoilParetoCandidate(
        candidate_role=str(item["airfoil_id"]),
        objectives={
            "mean_cd": float(item.get("mean_cd", float("inf"))),
            "cd_p90": float(item.get("cd_p90", float("inf"))),
            "negative_stall_margin": -float(item.get("stall_margin_cl", -float("inf"))),
            "roughness_sensitivity": float(item.get("roughness_sensitivity", float("inf"))),
            "abs_cm": abs(float(item.get("mean_cm", 0.0))),
            "alpha_l0_penalty": float(alpha_l0_penalty),
            "convergence_gap": max(0.0, 1.0 - float(item.get("pass_rate", 0.0))),
        },
        constraint_violations={
            "quality": 0.0
            if item.get("source_quality") == "cst_xfoil_mission_grade_candidate"
            else 1.0,
            "pass_rate": max(
                0.0,
                float(item.get("pass_rate_threshold", 0.0)) - float(item.get("pass_rate", 0.0)),
            ),
            "stall_margin": max(0.0, -float(item.get("stall_margin_cl", -1.0))),
            "coverage": 1.0 if item.get("coverage_failed") else 0.0,
        },
    )


def _select_survivor_templates(
    ranked_results: Sequence[Mapping[str, Any]], *, survivor_count: int
) -> tuple[CSTAirfoilTemplate, ...]:
    result_by_id = {str(item["airfoil_id"]): item for item in ranked_results}
    survivors = select_nsga2_survivors(
        tuple(_pareto_candidate_from_result(item) for item in ranked_results),
        survivor_count=int(survivor_count),
    )
    templates: list[CSTAirfoilTemplate] = []
    for survivor in survivors:
        template = result_by_id.get(survivor.candidate_role, {}).get("template")
        if isinstance(template, CSTAirfoilTemplate):
            templates.append(template)
    return tuple(templates)


def _generate_nsga_offspring(
    *,
    zone_name: str,
    parents: tuple[CSTAirfoilTemplate, ...],
    config: CSTZoneSearchConfig,
    zone_index: int,
    generation_index: int,
    offspring_count: int,
) -> tuple[CSTAirfoilTemplate, ...]:
    count = int(offspring_count)
    while count > 0:
        try:
            return generate_seedless_nsga2_offspring(
                zone_name=zone_name,
                parents=parents,
                bounds=_default_seedless_cst_bounds(zone_name),
                constraints=_zone_constraints(zone_name),
                offspring_count=count,
                generation_index=generation_index,
                random_seed=(
                    None
                    if config.random_seed is None
                    else int(config.random_seed) + 1009 * int(generation_index) + 37 * int(zone_index)
                ),
                mutation_scale=float(config.mutation_scale),
                max_attempts_per_child=120,
            )
        except ValueError:
            count //= 2
    return ()


def _write_artifacts(
    output: Path,
    *,
    database: AirfoilDatabase,
    report: Mapping[str, Any],
    polar_rows: Sequence[Mapping[str, Any]],
    per_zone_rows: Sequence[Mapping[str, Any]],
    top_k_rows: Sequence[Mapping[str, Any]],
    failed_rows: Sequence[Mapping[str, Any]],
    geometry_rejection_rows: Sequence[Mapping[str, Any]],
    coverage_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Path]:
    paths = {
        "airfoil_database_json": output / "airfoil_database.json",
        "airfoil_database_csv": output / "airfoil_database.csv",
        "per_zone_pareto_csv": output / "per_zone_pareto.csv",
        "per_zone_top_k_csv": output / "per_zone_top_k.csv",
        "build_report_json": output / "build_report.json",
        "build_report_md": output / "build_report.md",
        "failed_candidates_csv": output / "failed_candidates.csv",
        "geometry_rejections_csv": output / "geometry_rejections.csv",
        "coverage_report_csv": output / "coverage_report.csv",
    }
    payload = {
        "schema_version": "airfoil_database_cst_zone_nsga_xfoil_v1",
        "source": CST_DATABASE_SOURCE,
        "build_report": report,
        "records": [
            record.to_dict(include_polar_points=True)
            for record in database.records.values()
        ],
    }
    paths["airfoil_database_json"].write_text(
        json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_csv(paths["airfoil_database_csv"], polar_rows, default_fields=_polar_fields())
    _write_csv(paths["per_zone_pareto_csv"], per_zone_rows, default_fields=_summary_fields())
    _write_csv(paths["per_zone_top_k_csv"], top_k_rows, default_fields=_summary_fields())
    _write_csv(paths["failed_candidates_csv"], failed_rows, default_fields=_summary_fields())
    _write_csv(
        paths["geometry_rejections_csv"],
        geometry_rejection_rows,
        default_fields=("zone_name", "candidate_role", "rejection_reason"),
    )
    _write_csv(paths["coverage_report_csv"], coverage_rows, default_fields=_coverage_fields())
    paths["build_report_json"].write_text(
        json.dumps(_json_ready(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["build_report_md"].write_text(_build_report_md(report), encoding="utf-8")
    return paths


def _build_report(
    *,
    config: CSTZoneSearchConfig,
    envelopes: Sequence[ZoneEnvelope],
    report_zones: Mapping[str, Any],
    records: Sequence[AirfoilRecord],
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": "cst_zone_nsga_xfoil_build_report_v1",
        "source": CST_DATABASE_SOURCE,
        "status": status,
        "config": asdict(config),
        "zone_count": len(envelopes),
        "record_count": len(records),
        "source_quality_counts": _source_quality_counts(records),
        "zones": dict(report_zones),
    }


def _zone_report(
    *,
    envelope: ZoneEnvelope,
    initial_population_count: int,
    evaluated_results: Sequence[Mapping[str, Any]],
    rejections: Sequence[Mapping[str, Any]],
    generation_summaries: Sequence[Mapping[str, Any]],
    work_points: Sequence[Mapping[str, Any]],
    generation_count: int,
) -> dict[str, Any]:
    return {
        "status": "complete"
        if len(generation_summaries) >= int(generation_count)
        else "partial",
        "source": envelope.source,
        "search_mode": "nsga2_seedless_sobol_initial_population",
        "initial_population_count": int(initial_population_count),
        "population_size_per_zone": int(initial_population_count),
        "generation_count": int(generation_count),
        "evaluated_candidate_count": len(evaluated_results),
        "generated_candidate_count": int(initial_population_count),
        "geometry_valid_candidate_count": int(initial_population_count),
        "geometry_rejection_count": len(rejections),
        "coarse_evaluated_candidate_count": len(evaluated_results),
        "xfoil_evaluated_candidate_count": len(evaluated_results),
        "mission_grade_candidate_count": sum(
            1
            for item in evaluated_results
            if item.get("source_quality") == "cst_xfoil_mission_grade_candidate"
        ),
        "generation_summaries": list(generation_summaries),
        "work_points": list(work_points),
    }


def _summary_row(record: AirfoilRecord, item: Mapping[str, Any], *, rank: int) -> dict[str, Any]:
    return {
        "zone_name": item.get("zone_name"),
        "rank_in_zone": int(rank),
        "airfoil_id": record.airfoil_id,
        "source_quality": record.source_quality,
        "score": item.get("score"),
        "mean_cd": item.get("mean_cd"),
        "cd_p90": item.get("cd_p90"),
        "safe_clmax": item.get("safe_clmax"),
        "usable_clmax": item.get("usable_clmax"),
        "stall_margin_cl": item.get("stall_margin_cl"),
        "mean_cm": item.get("mean_cm"),
        "alpha_L0_deg": item.get("alpha_L0_deg"),
        "roughness_sensitivity": item.get("roughness_sensitivity"),
        "convergence_pass_rate": item.get("pass_rate"),
        "issue_count": len(item.get("issues", [])),
        "issues": ";".join(str(issue) for issue in item.get("issues", [])),
    }


def _coverage_row(record: AirfoilRecord, item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "zone_name": item.get("zone_name"),
        "airfoil_id": record.airfoil_id,
        "source_quality": record.source_quality,
        "required_cl": item.get("required_cl"),
        "usable_clmax": item.get("usable_clmax"),
        "safe_clmax": item.get("safe_clmax"),
        "stall_margin_cl": item.get("stall_margin_cl"),
        "convergence_pass_rate": item.get("pass_rate"),
        "worker_success_count": item.get("worker_success_count"),
        "worker_condition_count": item.get("worker_condition_count"),
        "coverage_failed": item.get("coverage_failed"),
        "issues": ";".join(str(issue) for issue in item.get("issues", [])),
    }


def _polar_rows_for_record(record: AirfoilRecord, item: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "airfoil_id": record.airfoil_id,
            "zone_name": item.get("zone_name"),
            "source_quality": record.source_quality,
            "Re": point.Re,
            "roughness_mode": point.roughness_mode,
            "alpha_deg": point.alpha_deg,
            "cl": point.cl,
            "cd": point.cd,
            "cm": point.cm,
        }
        for point in record.polar_points
    ]


def _generation_summary(generation_index: int, results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "generation_index": int(generation_index),
        "evaluated_candidate_count": len(results),
        "mission_grade_candidate_count": sum(
            1
            for item in results
            if item.get("source_quality") == "cst_xfoil_mission_grade_candidate"
        ),
        "not_mission_grade_candidate_count": sum(
            1
            for item in results
            if item.get("source_quality") == "cst_xfoil_candidate_not_mission_grade"
        ),
        "failed_candidate_count": sum(
            1
            for item in results
            if item.get("source_quality") == "cst_xfoil_failed_not_mission_grade"
        ),
    }


def _coverage_passes(points: Sequence[AirfoilPolarPoint], work_points: Sequence[Mapping[str, Any]]) -> bool:
    if not points:
        return False
    observed_re = [point.Re for point in points]
    observed_cl = [point.cl for point in points]
    for work_point in work_points:
        re_value = _finite_float(work_point.get("reynolds"))
        cl_value = _finite_float(work_point.get("cl_target"))
        if re_value is None or cl_value is None:
            continue
        if min(observed_re) > float(re_value) * 1.02 or max(observed_re) < float(re_value) * 0.98:
            return False
        if min(observed_cl) > float(cl_value) + 0.02 or max(observed_cl) < float(cl_value) - 0.02:
            return False
    return True


def _roughness_sensitivity(points: Sequence[AirfoilPolarPoint]) -> float:
    clean = [point.cd for point in points if point.roughness_mode == "clean"]
    rough = [point.cd for point in points if point.roughness_mode != "clean"]
    if not clean or not rough:
        return 0.0
    return max(0.0, float(np.mean(rough)) - float(np.mean(clean)))


def _cl_samples_for_envelope(envelope: ZoneEnvelope, *, config: CSTZoneSearchConfig) -> tuple[float, ...]:
    values = [
        _first_finite(envelope.cl_min, envelope.cl_p50, 0.4),
        _first_finite(envelope.cl_p50, envelope.cl_min, 0.7),
        _first_finite(envelope.cl_p90, envelope.cl_max, 0.9),
        _first_finite(envelope.cl_max, envelope.max_avl_actual_cl, envelope.cl_p90, 1.0),
    ]
    if str(envelope.zone_name) == "tip":
        fourier_cl_max = _finite_float(envelope.max_fourier_target_cl)
        if fourier_cl_max is not None:
            values.append(float(fourier_cl_max))
    high = max(values) + float(config.cl_coverage_margin)
    low = max(0.05, min(values) - 0.05)
    grid = {round(float(value), 2) for value in values}
    for index in range(max(1, int(math.ceil((high - low) / 0.10))) + 1):
        grid.add(round(low + 0.10 * index, 2))
    grid.add(round(high, 2))
    return tuple(sorted(value for value in grid if math.isfinite(value) and value > 0.0))


def _re_samples_for_envelope(envelope: ZoneEnvelope, *, config: CSTZoneSearchConfig) -> tuple[float, ...]:
    base_re = _first_finite(envelope.re_p50, envelope.re_min, envelope.re_max, 250_000.0)
    values = [float(base_re) * float(factor) for factor in config.re_robustness_factors]
    if str(envelope.zone_name) == "tip":
        for re_value in (envelope.re_min, envelope.re_p50, envelope.re_max):
            finite_value = _finite_float(re_value)
            if finite_value is not None:
                values.append(float(finite_value))
    return tuple(
        sorted(
            {
                round(float(value), 6)
                for value in values
                if math.isfinite(float(value)) and float(value) > 0.0
            }
        )
    )


def _linear_lift_curve_estimate(points: Sequence[AirfoilPolarPoint]) -> tuple[float, float]:
    clean = [point for point in points if point.roughness_mode == "clean"]
    if len(clean) < 2:
        clean = list(points)
    if len(clean) < 2:
        return -2.0, 2.0 * math.pi
    xs = np.asarray([point.alpha_deg for point in clean], dtype=float)
    ys = np.asarray([point.cl for point in clean], dtype=float)
    slope_per_deg, intercept = np.polyfit(xs, ys, deg=1)
    if abs(float(slope_per_deg)) <= 1.0e-12:
        return -2.0, 2.0 * math.pi
    return -float(intercept) / float(slope_per_deg), float(slope_per_deg) * 180.0 / math.pi


def _zone_constraints(zone_name: str):
    return _seedless_constraints_for_zone(
        _zone_min_thickness_ratio(zone_name),
        seedless_te_thickness_min=0.0010,
    )


def _population_size(config: CSTZoneSearchConfig) -> int:
    if config.sample_count_per_zone is not None:
        return max(1, int(config.sample_count_per_zone))
    return max(1, int(config.population_size_per_zone))


def _generation_count(config: CSTZoneSearchConfig) -> int:
    return max(1, int(config.generations))


def _airfoil_id(zone_name: str, candidate: CSTAirfoilTemplate, geometry_hash: str) -> str:
    return f"cst_{zone_name}_{candidate.candidate_role}_{geometry_hash[:8]}"


def _zone_min_thickness_ratio(zone_name: str) -> float:
    return {"root": 0.14, "mid1": 0.13, "mid2": 0.11, "tip": 0.10}.get(zone_name, 0.11)


def _write_airfoil_dat(path: Path, *, name: str, coordinates: Sequence[tuple[float, float]]) -> None:
    lines = [str(name)]
    lines.extend(f"{float(x): .8f} {float(y): .8f}" for x, y in coordinates)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], *, default_fields: Sequence[str]) -> None:
    fields = list(rows[0].keys()) if rows else list(default_fields)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(_json_ready(dict(row)))


def _write_run_metadata(
    output: Path,
    *,
    config: CSTZoneSearchConfig,
    zone_envelope_path: Path,
    status: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    payload = {
        "source": CST_DATABASE_SOURCE,
        "status": status,
        "zone_envelope_path": str(Path(zone_envelope_path)),
        "config": asdict(config),
    }
    if extra:
        payload.update(dict(extra))
    (output / "run_metadata.json").write_text(
        json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _emit_progress(callback: Any | None, event: str, **payload: Any) -> None:
    if callback is not None:
        callback({"event": event, **payload})


def _build_report_md(report: Mapping[str, Any]) -> str:
    lines = [
        "# CST Zone NSGA/XFOIL Airfoil Database Build Report",
        "",
        f"- Status: {report.get('status')}",
        f"- Source: {report.get('source')}",
        f"- Records: {report.get('record_count')}",
        f"- Source quality counts: `{report.get('source_quality_counts')}`",
        "",
        "## Zones",
        "",
    ]
    zones = report.get("zones", {})
    if isinstance(zones, Mapping):
        for zone_name, item in zones.items():
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "- "
                f"{zone_name}: initial {item.get('initial_population_count')}, "
                f"generations {item.get('generation_count')}, "
                f"XFOIL-evaluated {item.get('xfoil_evaluated_candidate_count')}, "
                f"mission-grade {item.get('mission_grade_candidate_count')}"
            )
    lines.extend(
        [
            "",
            "All records are sidecar/offline only. Failed, sparse, or nonphysical polars are not mission-grade.",
            "",
        ]
    )
    return "\n".join(lines)


def _source_quality_counts(records: Sequence[AirfoilRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.source_quality] = counts.get(record.source_quality, 0) + 1
    return counts


def _summary_fields() -> tuple[str, ...]:
    return (
        "zone_name",
        "rank_in_zone",
        "airfoil_id",
        "source_quality",
        "score",
        "mean_cd",
        "cd_p90",
        "safe_clmax",
        "usable_clmax",
        "stall_margin_cl",
        "mean_cm",
        "alpha_L0_deg",
        "roughness_sensitivity",
        "convergence_pass_rate",
        "issue_count",
        "issues",
    )


def _polar_fields() -> tuple[str, ...]:
    return ("airfoil_id", "zone_name", "source_quality", "Re", "roughness_mode", "alpha_deg", "cl", "cd", "cm")


def _coverage_fields() -> tuple[str, ...]:
    return (
        "zone_name",
        "airfoil_id",
        "source_quality",
        "required_cl",
        "usable_clmax",
        "safe_clmax",
        "stall_margin_cl",
        "convergence_pass_rate",
        "worker_success_count",
        "worker_condition_count",
        "coverage_failed",
        "issues",
    )


def _stringify_paths(paths: Mapping[str, Path]) -> dict[str, str]:
    return {key: str(value) for key, value in paths.items()}


def _first_finite(*values: Any) -> float:
    for value in values:
        parsed = _finite_float(value)
        if parsed is not None:
            return float(parsed)
    return float("nan")


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    return None


def _finite_or_zero(value: Any) -> float:
    parsed = _finite_float(value)
    return float(parsed) if parsed is not None else 0.0


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    return value
