"""Offline CST/XFOIL airfoil database builder for zone sidecar studies.

This module intentionally stays outside the main optimizer route.  It samples
zone-level CST candidates, evaluates a capped subset with the existing XFOIL
worker, writes checkpointed database artifacts, and keeps every result
quality-labeled for later sidecar use.
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
from hpa_mdo.concept.airfoil_selection import (
    _default_seedless_cst_bounds,
    _seedless_constraints_for_zone,
)
from hpa_mdo.concept.airfoil_worker import PolarQuery, geometry_hash_from_coordinates


CST_DATABASE_SOURCE = "offline_cst_zone_xfoil_database_builder_v1"
_ZONE_ORDER = ("root", "mid1", "mid2", "tip")


@dataclass(frozen=True)
class CSTZoneSearchConfig:
    sample_count_per_zone: int = 512
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


def load_zone_envelopes_from_artifact(path: Path) -> tuple[ZoneEnvelope, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows: Any
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
                target_vs_actual_cl_delta=_finite_float(
                    item.get("target_vs_actual_cl_delta")
                ),
                current_airfoil_id=(
                    None
                    if item.get("current_airfoil_id") is None
                    else str(item.get("current_airfoil_id"))
                ),
                current_stall_margin=_finite_float(item.get("current_stall_margin")),
                current_profile_cd_estimate=_finite_float(
                    item.get("current_profile_cd_estimate")
                ),
                source=str(item.get("source", "loaded_dihedral_avl")),
            )
        )
    return tuple(sorted(envelopes, key=lambda envelope: _ZONE_ORDER.index(envelope.zone_name) if envelope.zone_name in _ZONE_ORDER else 99))


def zone_work_points_from_envelope(envelope: ZoneEnvelope) -> tuple[dict[str, Any], ...]:
    re_min = _first_finite(envelope.re_min, envelope.re_p50, envelope.re_max, 250_000.0)
    re_p50 = _first_finite(envelope.re_p50, envelope.re_min, envelope.re_max, 250_000.0)
    re_max = _first_finite(envelope.re_max, envelope.re_p50, envelope.re_min, 250_000.0)
    cl_min = _first_finite(envelope.cl_min, envelope.cl_p50, envelope.cl_max, 0.5)
    cl_p50 = _first_finite(envelope.cl_p50, envelope.cl_min, envelope.cl_max, 0.7)
    cl_p90 = _first_finite(envelope.cl_p90, envelope.cl_max, envelope.cl_p50, 0.9)
    cl_max = _first_finite(
        envelope.cl_max,
        envelope.max_avl_actual_cl,
        envelope.cl_p90,
        1.0,
    )
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
) -> CSTZoneSearchResult:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    coordinate_dir = output / "coordinates"
    coordinate_dir.mkdir(parents=True, exist_ok=True)
    envelopes = load_zone_envelopes_from_artifact(zone_envelope_path)
    if not envelopes:
        raise ValueError("No zone envelopes were available for CST database build.")

    records: list[AirfoilRecord] = []
    all_polar_rows: list[dict[str, Any]] = []
    per_zone_rows: list[dict[str, Any]] = []
    top_k_rows: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    geometry_rejection_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    report_zones: dict[str, Any] = {}

    _write_run_metadata(
        output,
        config=config,
        zone_envelope_path=zone_envelope_path,
        status="running",
    )
    for zone_index, envelope in enumerate(envelopes):
        zone_name = str(envelope.zone_name)
        work_points = zone_work_points_from_envelope(envelope)
        candidates, rejections = _generate_zone_candidates(
            zone_name=zone_name,
            config=config,
            zone_index=zone_index,
        )
        geometry_rejection_rows.extend(rejections)
        coarse_candidates = _select_geometry_prescreen(
            zone_name=zone_name,
            candidates=candidates,
            envelope=envelope,
            limit=config.coarse_score_count,
        )
        coarse_results = _evaluate_candidates(
            zone_name=zone_name,
            candidates=coarse_candidates,
            envelope=envelope,
            work_points=work_points,
            config=config,
            worker=worker,
            backend_name=str(getattr(worker, "backend_name", "unknown_worker")),
            stage="coarse",
            robust=False,
        )
        robust_candidates = tuple(
            item["template"]
            for item in sorted(
                coarse_results,
                key=lambda item: (
                    float(item.get("score", float("inf"))),
                    str(item["template"].candidate_role),
                ),
            )[: max(0, int(config.robust_score_count))]
        )
        robust_results = _evaluate_candidates(
            zone_name=zone_name,
            candidates=robust_candidates,
            envelope=envelope,
            work_points=work_points,
            config=config,
            worker=worker,
            backend_name=str(getattr(worker, "backend_name", "unknown_worker")),
            stage="robust",
            robust=True,
        )
        robust_results = sorted(
            robust_results,
            key=lambda item: (
                str(item.get("source_quality")) != "cst_xfoil_mission_grade_candidate",
                float(item.get("score", float("inf"))),
                str(item["template"].candidate_role),
            ),
        )
        for rank, item in enumerate(robust_results, start=1):
            record = _record_from_candidate_result(
                item,
                coordinate_dir=coordinate_dir,
            )
            records.append(record)
            all_polar_rows.extend(_polar_rows_for_record(record, item))
            row = _summary_row(record, item, rank=rank)
            per_zone_rows.append(row)
            coverage_rows.append(_coverage_row(record, item))
            if record.source_quality == "cst_xfoil_failed_not_mission_grade":
                failed_rows.append(row)
        top_k_rows.extend(
            row for row in per_zone_rows if row["zone_name"] == zone_name
        )
        top_k_rows = [
            row
            for row in top_k_rows
            if int(row["rank_in_zone"]) <= int(config.top_k_per_zone)
        ]
        report_zones[zone_name] = {
            "source": envelope.source,
            "generated_candidate_count": int(config.sample_count_per_zone),
            "geometry_valid_candidate_count": len(candidates),
            "geometry_rejection_count": len(rejections),
            "coarse_evaluated_candidate_count": len(coarse_candidates),
            "xfoil_evaluated_candidate_count": len(robust_results),
            "mission_grade_candidate_count": sum(
                1
                for item in robust_results
                if item.get("source_quality") == "cst_xfoil_mission_grade_candidate"
            ),
            "work_points": list(work_points),
        }
        database = AirfoilDatabase.from_records(records)
        report = _build_report(
            config=config,
            envelopes=envelopes,
            report_zones=report_zones,
            records=records,
            status="partial",
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
            status="partial",
            extra={"completed_zones": list(report_zones)},
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
    return CSTZoneSearchResult(airfoil_database=database, report=report, paths=paths)


def _generate_zone_candidates(
    *,
    zone_name: str,
    config: CSTZoneSearchConfig,
    zone_index: int,
) -> tuple[tuple[CSTAirfoilTemplate, ...], list[dict[str, Any]]]:
    zone_min_tc = _zone_min_thickness_ratio(zone_name)
    constraints = _seedless_constraints_for_zone(
        zone_min_tc,
        seedless_te_thickness_min=0.0010,
    )
    raw = sample_feasible_seedless_cst_sobol(
        zone_name=zone_name,
        sample_count=int(config.sample_count_per_zone),
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


def _select_geometry_prescreen(
    *,
    zone_name: str,
    candidates: Sequence[CSTAirfoilTemplate],
    envelope: ZoneEnvelope,
    limit: int,
) -> tuple[CSTAirfoilTemplate, ...]:
    scored: list[tuple[float, CSTAirfoilTemplate]] = []
    target_tc = _zone_target_thickness_ratio(zone_name)
    target_cl = _first_finite(envelope.cl_max, envelope.max_avl_actual_cl, envelope.cl_p90, 1.0)
    for candidate in candidates:
        try:
            metrics = analyze_cst_geometry(candidate)
        except ValueError:
            continue
        score = (
            abs(metrics.max_thickness_ratio - target_tc)
            + 0.006 * float(metrics.curvature_reversal_count)
            + 0.20 * max(0.0, float(target_cl) - 1.15)
            + 0.15 * metrics.max_camber_ratio
        )
        if zone_name in {"root", "mid1"}:
            score -= 0.35 * metrics.max_thickness_ratio
        else:
            score += 0.18 * abs(metrics.max_thickness_ratio - target_tc)
        scored.append((float(score), candidate))
    scored.sort(key=lambda item: (item[0], item[1].candidate_role))
    return tuple(candidate for _, candidate in scored[: max(0, int(limit))])


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
    robust: bool,
) -> list[dict[str, Any]]:
    queries: list[PolarQuery] = []
    query_to_candidate: dict[str, CSTAirfoilTemplate] = {}
    factors = tuple(config.re_robustness_factors) if robust else (1.0,)
    roughness_modes = tuple(config.roughness_modes) if robust else ("clean",)
    base_re = _first_finite(envelope.re_p50, envelope.re_min, envelope.re_max, 250_000.0)
    cl_samples = _cl_samples_for_envelope(envelope, config=config)
    for candidate in candidates:
        coordinates = generate_cst_coordinates(candidate)
        geometry_hash = geometry_hash_from_coordinates(coordinates)
        airfoil_id = _airfoil_id(zone_name, candidate, geometry_hash)
        for factor in factors:
            for roughness_mode in roughness_modes:
                template_id = f"{airfoil_id}__{stage}__re{factor:.3f}__{roughness_mode}"
                query = PolarQuery(
                    template_id=template_id,
                    reynolds=float(base_re) * float(factor),
                    cl_samples=cl_samples,
                    roughness_mode=str(roughness_mode),
                    geometry_hash=geometry_hash,
                    coordinates=coordinates,
                    analysis_mode="screening_target_cl",
                    analysis_stage=f"cst_zone_{stage}",
                )
                queries.append(query)
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
        candidate = template_by_airfoil_id[airfoil_id]
        evaluated.append(
            _candidate_result(
                airfoil_id=airfoil_id,
                zone_name=zone_name,
                template=candidate,
                envelope=envelope,
                work_points=work_points,
                worker_results=results,
                expected_query_count=sum(
                    1
                    for query in queries
                    if query.template_id.startswith(f"{airfoil_id}__")
                ),
                backend_name=backend_name,
                config=config,
                stage=stage,
                robust=robust,
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
    robust: bool,
) -> dict[str, Any]:
    polar_points: list[AirfoilPolarPoint] = []
    raw_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
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
            row = {
                "airfoil_id": airfoil_id,
                "zone_name": zone_name,
                "candidate_role": template.candidate_role,
                "stage": stage,
                "Re": re_value,
                "roughness_mode": roughness_mode,
                "alpha_deg": alpha,
                "cl": cl,
                "cd": cd,
                "cm": cm,
                "converged": converged,
                "status": status,
            }
            raw_rows.append(row)
            if (
                re_value is None
                or cl is None
                or cd is None
                or cm is None
                or alpha is None
                or not converged
            ):
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
    total_expected_points = max(1, int(expected_query_count) * len(_cl_samples_for_envelope(envelope, config=config)))
    pass_rate = len(finite_positive) / total_expected_points
    usable_clmax = max((point.cl for point in finite_positive), default=float("nan"))
    safe_clmax = 0.90 * usable_clmax - 0.05 if math.isfinite(usable_clmax) else float("nan")
    required_cl = _first_finite(envelope.cl_max, envelope.max_avl_actual_cl, envelope.cl_p90, 0.0)
    cd_values = [point.cd for point in finite_positive]
    cm_values = [point.cm for point in finite_positive if math.isfinite(point.cm)]
    issues: list[str] = []
    if pass_rate < float(config.convergence_pass_rate_threshold):
        issues.append("convergence_pass_rate_below_threshold")
    if len(finite_positive) != len(polar_points):
        issues.append("cd_nonfinite_or_nonpositive")
    if not math.isfinite(usable_clmax):
        issues.append("usable_clmax_nonfinite")
    if safe_clmax < float(required_cl) + float(config.required_stall_margin_cl):
        issues.append("required_cl_stall_margin_not_met")
    if not _coverage_passes(finite_positive, work_points):
        issues.append("zone_envelope_coverage_not_met")
    if len(worker_results) < int(expected_query_count):
        issues.append("missing_worker_conditions")
    real_xfoil_backend = str(backend_name) not in {
        "dry_run",
        "dry_run_xfoil_surrogate",
        "stub",
        "stubbed",
    }
    if any("cd_nonfinite_or_nonpositive" == issue for issue in issues):
        source_quality = "cst_xfoil_failed_not_mission_grade"
    elif not finite_positive:
        source_quality = "cst_xfoil_failed_not_mission_grade"
    elif not real_xfoil_backend:
        source_quality = "cst_xfoil_candidate_not_mission_grade"
    elif issues:
        source_quality = "cst_xfoil_candidate_not_mission_grade"
    else:
        source_quality = "cst_xfoil_mission_grade_candidate"
    mean_cd = float(np.mean(cd_values)) if cd_values else float("inf")
    cd_p90 = float(np.percentile(np.asarray(cd_values, dtype=float), 90.0)) if cd_values else float("inf")
    mean_cm = float(np.mean(cm_values)) if cm_values else 0.0
    rough_sensitivity = _roughness_sensitivity(finite_positive)
    score = (
        mean_cd
        + 0.35 * max(0.0, cd_p90 - mean_cd)
        + 0.006 * abs(mean_cm)
        + 0.02 * max(0.0, float(required_cl) - safe_clmax)
        + 0.10 * max(0.0, 1.0 - pass_rate)
        + 0.25 * rough_sensitivity
    )
    if source_quality != "cst_xfoil_mission_grade_candidate":
        score += 0.05
    try:
        geometry_metrics = asdict(analyze_cst_geometry(template))
    except ValueError as exc:
        geometry_metrics = {"error": str(exc)}
        warnings.append("geometry_metrics_unavailable")
    return {
        "airfoil_id": airfoil_id,
        "zone_name": zone_name,
        "template": template,
        "worker_results": [dict(item) for item in worker_results],
        "raw_rows": raw_rows,
        "polar_points": tuple(finite_positive),
        "source_quality": source_quality,
        "issues": issues,
        "warnings": warnings,
        "pass_rate": pass_rate,
        "worker_success_count": success_results,
        "worker_condition_count": expected_query_count,
        "mean_cd": mean_cd,
        "cd_p90": cd_p90,
        "mean_cm": mean_cm,
        "usable_clmax": usable_clmax,
        "safe_clmax": safe_clmax,
        "required_cl": required_cl,
        "stall_margin_cl": safe_clmax - float(required_cl) if math.isfinite(safe_clmax) else float("nan"),
        "roughness_sensitivity": rough_sensitivity,
        "score": score,
        "geometry_metrics": geometry_metrics,
        "stage": stage,
        "backend_name": backend_name,
        "robust": robust,
    }


def _record_from_candidate_result(
    item: Mapping[str, Any],
    *,
    coordinate_dir: Path,
) -> AirfoilRecord:
    template = item["template"]
    coordinates = generate_cst_coordinates(template)
    coordinate_path = coordinate_dir / f"{item['airfoil_id']}.dat"
    _write_airfoil_dat(coordinate_path, name=str(item["airfoil_id"]), coordinates=coordinates)
    polar_points = tuple(item.get("polar_points", ()))
    alpha_l0, cl_alpha = _linear_lift_curve_estimate(polar_points)
    return AirfoilRecord(
        airfoil_id=str(item["airfoil_id"]),
        name=str(item["airfoil_id"]),
        source=f"{CST_DATABASE_SOURCE}:{coordinate_path}",
        source_quality=str(item.get("source_quality")),
        zone_hint=str(item.get("zone_name")),
        thickness_ratio=float(item.get("geometry_metrics", {}).get("max_thickness_ratio", 0.0)),
        max_camber=float(item.get("geometry_metrics", {}).get("max_camber_ratio", 0.0)),
        alpha_L0_deg=float(alpha_l0),
        cl_alpha_per_rad=float(cl_alpha),
        cm_design=float(item.get("mean_cm", 0.0)),
        safe_clmax=float(item.get("safe_clmax", 0.0)) if math.isfinite(float(item.get("safe_clmax", 0.0))) else 0.0,
        usable_clmax=float(item.get("usable_clmax", 0.0)) if math.isfinite(float(item.get("usable_clmax", 0.0))) else 0.0,
        polar_points=polar_points,
        notes=(
            f"Offline CST zone candidate; issues={item.get('issues', [])}; "
            f"warnings={item.get('warnings', [])}."
        ),
    )


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
    db_payload = {
        "schema_version": "airfoil_database_cst_zone_xfoil_v1",
        "source": CST_DATABASE_SOURCE,
        "build_report": report,
        "records": [
            record.to_dict(include_polar_points=True)
            for record in database.records.values()
        ],
    }
    paths["airfoil_database_json"].write_text(
        json.dumps(_json_ready(db_payload), indent=2, sort_keys=True) + "\n",
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
        "schema_version": "cst_zone_xfoil_build_report_v1",
        "source": CST_DATABASE_SOURCE,
        "status": status,
        "config": asdict(config),
        "zone_count": len(envelopes),
        "record_count": len(records),
        "source_quality_counts": _source_quality_counts(records),
        "zones": dict(report_zones),
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
        "issues": ";".join(str(issue) for issue in item.get("issues", [])),
    }


def _polar_rows_for_record(record: AirfoilRecord, item: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for point in record.polar_points:
        rows.append(
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
        )
    return rows


def _coverage_passes(
    points: Sequence[AirfoilPolarPoint],
    work_points: Sequence[Mapping[str, Any]],
) -> bool:
    if not points:
        return False
    observed_re = [point.Re for point in points]
    observed_cl = [point.cl for point in points]
    if not observed_re or not observed_cl:
        return False
    for work_point in work_points:
        re_value = _finite_float(work_point.get("reynolds"))
        cl_value = _finite_float(work_point.get("cl_target"))
        if re_value is None or cl_value is None:
            continue
        re_span_ok = min(observed_re) <= float(re_value) * 1.02 and max(observed_re) >= float(re_value) * 0.98
        cl_span_ok = min(observed_cl) <= float(cl_value) + 0.02 and max(observed_cl) >= float(cl_value) - 0.02
        if not (re_span_ok and cl_span_ok):
            return False
    return True


def _roughness_sensitivity(points: Sequence[AirfoilPolarPoint]) -> float:
    clean = [point.cd for point in points if point.roughness_mode == "clean"]
    rough = [point.cd for point in points if point.roughness_mode != "clean"]
    if not clean or not rough:
        return 0.0
    return max(0.0, float(np.mean(rough)) - float(np.mean(clean)))


def _cl_samples_for_envelope(
    envelope: ZoneEnvelope,
    *,
    config: CSTZoneSearchConfig,
) -> tuple[float, ...]:
    values = [
        _first_finite(envelope.cl_min, envelope.cl_p50, 0.4),
        _first_finite(envelope.cl_p50, envelope.cl_min, 0.7),
        _first_finite(envelope.cl_p90, envelope.cl_max, 0.9),
        _first_finite(envelope.cl_max, envelope.max_avl_actual_cl, envelope.cl_p90, 1.0),
    ]
    high = max(values) + float(config.cl_coverage_margin)
    low = max(0.05, min(values) - 0.05)
    grid = {round(float(value), 2) for value in values}
    step_count = max(1, int(math.ceil((high - low) / 0.10)))
    for index in range(step_count + 1):
        grid.add(round(low + 0.10 * index, 2))
    grid.add(round(high, 2))
    return tuple(sorted(value for value in grid if math.isfinite(value) and value > 0.0))


def _airfoil_id(zone_name: str, candidate: CSTAirfoilTemplate, geometry_hash: str) -> str:
    return f"cst_{zone_name}_{candidate.candidate_role}_{geometry_hash[:8]}"


def _zone_min_thickness_ratio(zone_name: str) -> float:
    return {
        "root": 0.14,
        "mid1": 0.13,
        "mid2": 0.11,
        "tip": 0.10,
    }.get(zone_name, 0.11)


def _zone_target_thickness_ratio(zone_name: str) -> float:
    return {
        "root": 0.155,
        "mid1": 0.140,
        "mid2": 0.120,
        "tip": 0.108,
    }.get(zone_name, 0.12)


def _linear_lift_curve_estimate(
    points: Sequence[AirfoilPolarPoint],
) -> tuple[float, float]:
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


def _write_airfoil_dat(
    path: Path,
    *,
    name: str,
    coordinates: Sequence[tuple[float, float]],
) -> None:
    lines = [str(name)]
    lines.extend(f"{float(x): .8f} {float(y): .8f}" for x, y in coordinates)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    default_fields: Sequence[str],
) -> None:
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


def _build_report_md(report: Mapping[str, Any]) -> str:
    lines = [
        "# CST Zone Airfoil Database Build Report",
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
                f"{zone_name}: generated {item.get('generated_candidate_count')}, "
                f"geometry-valid {item.get('geometry_valid_candidate_count')}, "
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
        "roughness_sensitivity",
        "convergence_pass_rate",
        "issue_count",
        "issues",
    )


def _polar_fields() -> tuple[str, ...]:
    return (
        "airfoil_id",
        "zone_name",
        "source_quality",
        "Re",
        "roughness_mode",
        "alpha_deg",
        "cl",
        "cd",
        "cm",
    )


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
