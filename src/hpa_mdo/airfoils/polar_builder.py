"""Seed-airfoil polar generation and AirfoilDatabase ingestion.

The builder is intentionally separate from the optimizer route.  It can use
the existing Julia/XFoil worker when supplied, but tests and CI can run the
same artifact/quality path through a deterministic dry-run backend.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from hpa_mdo.airfoils.database import (
    AirfoilDatabase,
    AirfoilPolarPoint,
    AirfoilRecord,
)
from hpa_mdo.concept.airfoil_worker import PolarQuery, geometry_hash_from_coordinates


_REPO_ROOT = Path(__file__).resolve().parents[3]
POLAR_BUILDER_SOURCE = "seed_airfoil_polar_builder_v1"
DEFAULT_HPA_SEED_RE_GRID = (
    150_000.0,
    175_000.0,
    200_000.0,
    250_000.0,
    300_000.0,
    350_000.0,
    400_000.0,
    500_000.0,
    600_000.0,
)
DEFAULT_HPA_SEED_CL_GRID = tuple(round(0.20 + 0.05 * index, 2) for index in range(24))


@dataclass(frozen=True)
class PolarBuildConfig:
    re_grid: tuple[float, ...] = DEFAULT_HPA_SEED_RE_GRID
    cl_grid: tuple[float, ...] = DEFAULT_HPA_SEED_CL_GRID
    roughness_modes: tuple[str, ...] = ("clean", "rough")
    re_robustness_factors: tuple[float, ...] = (0.85, 1.00, 1.15)
    xfoil_max_iter: int = 80
    panel_count: int = 120
    timeout_s: float = 60.0
    convergence_pass_rate_threshold: float = 0.80
    source_quality_policy: str = "require_real_worker_and_quality_pass"
    analysis_mode: str = "screening_target_cl"


@dataclass(frozen=True)
class SeedAirfoilSpec:
    airfoil_id: str
    name: str
    coordinate_path: Path
    zone_hint: str
    thickness_ratio: float
    max_camber: float
    cm_design: float
    notes: str = ""


@dataclass(frozen=True)
class PolarBuildResult:
    airfoil_database: AirfoilDatabase
    report: dict[str, Any]
    polar_rows_by_airfoil: dict[str, list[dict[str, Any]]]


def seed_airfoil_specs() -> dict[str, SeedAirfoilSpec]:
    return {
        "fx76mp140": SeedAirfoilSpec(
            airfoil_id="fx76mp140",
            name="FX 76-MP-140",
            coordinate_path=_REPO_ROOT / "data" / "airfoils" / "fx76mp140.dat",
            zone_hint="root,mid1",
            thickness_ratio=0.140,
            max_camber=0.055,
            cm_design=-0.190,
            notes="Current fixed-seed root/mid1 airfoil.",
        ),
        "clarkysm": SeedAirfoilSpec(
            airfoil_id="clarkysm",
            name="ClarkY smoothed",
            coordinate_path=_REPO_ROOT / "data" / "airfoils" / "clarkysm.dat",
            zone_hint="mid2,tip",
            thickness_ratio=0.117,
            max_camber=0.035,
            cm_design=-0.075,
            notes="Current fixed-seed mid2/tip airfoil.",
        ),
        "dae11": _dae_spec("dae11", "DAE11", "root", 0.142, 0.040, -0.090),
        "dae21": _dae_spec("dae21", "DAE21", "mid", 0.128, 0.037, -0.083),
        "dae31": _dae_spec("dae31", "DAE31", "tip", 0.119, 0.035, -0.075),
        "dae41": _dae_spec("dae41", "DAE41", "tip", 0.105, 0.030, -0.065),
    }


def build_seed_airfoil_database(
    *,
    config: PolarBuildConfig,
    airfoil_specs: Mapping[str, SeedAirfoilSpec] | None = None,
    zone_envelopes: Sequence[Mapping[str, Any]] | None = None,
    backend: str = "dry_run",
    worker: Any | None = None,
    cache_dir: Path | None = None,
) -> PolarBuildResult:
    specs = dict(seed_airfoil_specs() if airfoil_specs is None else airfoil_specs)
    re_grid, cl_grid = derive_re_cl_grid(zone_envelopes=zone_envelopes, config=config)
    cache_root = Path(cache_dir or (_REPO_ROOT / "output" / "airfoil_polars" / ".cache"))
    cache_root.mkdir(parents=True, exist_ok=True)
    backend_name = _backend_name(backend=backend, worker=worker)
    records: list[AirfoilRecord] = []
    polar_rows_by_airfoil: dict[str, list[dict[str, Any]]] = {}
    report_airfoils: dict[str, Any] = {}

    for airfoil_id, spec in specs.items():
        title, coordinates = read_airfoil_dat(spec.coordinate_path)
        geometry_hash = geometry_hash_from_coordinates(coordinates)
        queries = [
            PolarQuery(
                template_id=str(airfoil_id),
                reynolds=float(re_value),
                cl_samples=tuple(float(value) for value in cl_grid),
                roughness_mode=str(roughness_mode),
                geometry_hash=geometry_hash,
                coordinates=coordinates,
                analysis_mode=str(config.analysis_mode),
                analysis_stage="seed_airfoil_polar_builder",
            )
            for roughness_mode in config.roughness_modes
            for re_value in re_grid
        ]
        results = _run_queries_with_cache(
            queries=queries,
            backend=backend,
            backend_name=backend_name,
            worker=worker,
            config=config,
            cache_dir=cache_root,
        )
        record, rows, quality = _record_from_results(
            spec=spec,
            dat_title=title,
            results=results,
            backend_name=backend_name,
            config=config,
            requested_cl_grid=cl_grid,
        )
        records.append(record)
        polar_rows_by_airfoil[str(airfoil_id)] = rows
        report_airfoils[str(airfoil_id)] = quality

    database = AirfoilDatabase.from_records(records)
    report = {
        "schema_version": "seed_airfoil_polar_build_report_v1",
        "source": POLAR_BUILDER_SOURCE,
        "backend": backend_name,
        "config": asdict(config),
        "re_grid": list(re_grid),
        "cl_grid": list(cl_grid),
        "airfoil_count": len(records),
        "airfoils": report_airfoils,
        "source_quality_counts": _source_quality_counts(records),
    }
    return PolarBuildResult(
        airfoil_database=database,
        report=report,
        polar_rows_by_airfoil=polar_rows_by_airfoil,
    )


def write_polar_build_artifacts(
    result: PolarBuildResult,
    output_dir: Path,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    records_payload = [
        record.to_dict(include_polar_points=True)
        for record in result.airfoil_database.records.values()
    ]
    db_payload = {
        "schema_version": "airfoil_database_seed_polars_v1",
        "source": POLAR_BUILDER_SOURCE,
        "build_report": result.report,
        "records": records_payload,
    }
    database_json = output / "airfoil_database.json"
    database_json.write_text(
        json.dumps(_json_ready(db_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    database_csv = output / "airfoil_database.csv"
    polar_rows = _all_polar_rows(result)
    with database_csv.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = list(polar_rows[0].keys()) if polar_rows else _polar_csv_fields()
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(_json_ready(polar_rows))
    per_airfoil_paths: dict[str, Path] = {}
    for airfoil_id, rows in result.polar_rows_by_airfoil.items():
        path = output / f"{airfoil_id}_polar.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = list(rows[0].keys()) if rows else _polar_csv_fields()
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(_json_ready(rows))
        per_airfoil_paths[airfoil_id] = path
    build_report_json = output / "build_report.json"
    build_report_json.write_text(
        json.dumps(_json_ready(result.report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    build_report_md = output / "build_report.md"
    build_report_md.write_text(_build_report_markdown(result.report), encoding="utf-8")
    paths: dict[str, Path] = {
        "airfoil_database_json": database_json,
        "airfoil_database_csv": database_csv,
        "build_report_json": build_report_json,
        "build_report_md": build_report_md,
    }
    for airfoil_id, path in per_airfoil_paths.items():
        paths[f"{airfoil_id}_polar_csv"] = path
    return paths


def load_airfoil_database_artifact(
    path: Path,
    *,
    fallback_database: AirfoilDatabase | None = None,
) -> AirfoilDatabase:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Airfoil database artifact must be a JSON object.")
    records_payload = payload.get("records")
    if not isinstance(records_payload, list):
        raise ValueError("Airfoil database artifact is missing records.")
    loaded_records = [_record_from_payload(item) for item in records_payload]
    records = {}
    if fallback_database is not None:
        records.update(fallback_database.records)
    records.update({record.airfoil_id: record for record in loaded_records})
    return AirfoilDatabase(records)


def derive_re_cl_grid(
    *,
    zone_envelopes: Sequence[Mapping[str, Any]] | None,
    config: PolarBuildConfig,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    if not zone_envelopes:
        return _unique_sorted(config.re_grid), _unique_sorted(config.cl_grid)
    re_values: list[float] = []
    cl_values: list[float] = []
    for envelope in zone_envelopes:
        if not isinstance(envelope, Mapping):
            continue
        for key in ("re_min", "re_max", "re_p50"):
            value = _finite_float(envelope.get(key))
            if value is None or value <= 0.0:
                continue
            for factor in config.re_robustness_factors:
                re_values.append(float(value) * float(factor))
        for key in ("cl_min", "cl_max", "cl_p50", "cl_p90", "max_avl_actual_cl", "max_fourier_target_cl"):
            value = _finite_float(envelope.get(key))
            if value is not None:
                cl_values.append(float(value))
    if not re_values:
        re_values.extend(config.re_grid)
    if not cl_values:
        cl_values.extend(config.cl_grid)
    cl_min = max(0.0, min(cl_values) - 0.10)
    cl_max = max(cl_values) + 0.10
    cl_grid = tuple(round(value, 2) for value in np.arange(cl_min, cl_max + 1.0e-9, 0.05))
    return _unique_sorted(re_values), _unique_sorted(cl_grid)


def read_airfoil_dat(path: Path) -> tuple[str, tuple[tuple[float, float], ...]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    title = Path(path).stem
    coordinates: list[tuple[float, float]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) < 2:
            title = stripped
            continue
        try:
            coordinates.append((float(parts[0]), float(parts[1])))
        except ValueError:
            title = stripped
    if len(coordinates) < 3:
        raise ValueError(f"Airfoil coordinate file has too few points: {path}")
    return title, tuple(coordinates)


def _dae_spec(
    airfoil_id: str,
    name: str,
    zone_hint: str,
    thickness_ratio: float,
    max_camber: float,
    cm_design: float,
) -> SeedAirfoilSpec:
    return SeedAirfoilSpec(
        airfoil_id=airfoil_id,
        name=name,
        coordinate_path=(
            _REPO_ROOT
            / "docs"
            / "research"
            / "historical_airfoil_cst_coverage"
            / "airfoils"
            / f"{airfoil_id}.dat"
        ),
        zone_hint=zone_hint,
        thickness_ratio=float(thickness_ratio),
        max_camber=float(max_camber),
        cm_design=float(cm_design),
        notes="Historical DAE-family seed airfoil.",
    )


def _run_queries_with_cache(
    *,
    queries: Sequence[PolarQuery],
    backend: str,
    backend_name: str,
    worker: Any | None,
    config: PolarBuildConfig,
    cache_dir: Path,
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any] | None] = [None] * len(queries)
    uncached: list[PolarQuery] = []
    uncached_positions: list[int] = []
    for index, query in enumerate(queries):
        cache_path = _query_cache_path(query, backend_name=backend_name, config=config, cache_dir=cache_dir)
        if cache_path.is_file():
            resolved[index] = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            uncached.append(query)
            uncached_positions.append(index)
    if uncached:
        if backend == "dry_run":
            responses = [_dry_run_result(query) for query in uncached]
        elif backend == "worker":
            if worker is None:
                raise ValueError("backend='worker' requires a worker instance.")
            responses = worker.run_queries(list(uncached))
        else:
            raise ValueError("backend must be 'dry_run' or 'worker'.")
        for query, position, response in zip(uncached, uncached_positions, responses, strict=True):
            payload = dict(response)
            payload.setdefault("template_id", query.template_id)
            payload.setdefault("reynolds", query.reynolds)
            payload.setdefault("cl_samples", list(query.cl_samples))
            payload.setdefault("roughness_mode", query.roughness_mode)
            payload.setdefault("geometry_hash", query.geometry_hash)
            payload.setdefault("analysis_mode", query.analysis_mode)
            payload.setdefault("analysis_stage", query.analysis_stage)
            payload["builder_backend"] = backend_name
            cache_path = _query_cache_path(query, backend_name=backend_name, config=config, cache_dir=cache_dir)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(_json_ready(payload), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            resolved[position] = payload
    return [dict(item) for item in resolved if item is not None]


def _record_from_results(
    *,
    spec: SeedAirfoilSpec,
    dat_title: str,
    results: Sequence[Mapping[str, Any]],
    backend_name: str,
    config: PolarBuildConfig,
    requested_cl_grid: Sequence[float],
) -> tuple[AirfoilRecord, list[dict[str, Any]], dict[str, Any]]:
    polar_points: list[AirfoilPolarPoint] = []
    rows: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    for result in results:
        status = str(result.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        re_value = _finite_float(result.get("reynolds"))
        roughness_mode = str(result.get("roughness_mode", "clean"))
        if re_value is None:
            continue
        for point in result.get("polar_points", []) or []:
            if not isinstance(point, Mapping):
                continue
            cl = _finite_float(point.get("cl"))
            cd = _finite_float(point.get("cd"))
            cm = _finite_float(point.get("cm"))
            alpha = _finite_float(point.get("alpha_deg"))
            converged = bool(point.get("converged", status in {"ok", "mini_sweep_fallback", "stubbed_ok"}))
            row = {
                "airfoil_id": spec.airfoil_id,
                "name": spec.name,
                "Re": re_value,
                "roughness_mode": roughness_mode,
                "alpha_deg": alpha,
                "cl": cl,
                "cd": cd,
                "cm": cm,
                "converged": converged,
                "status": status,
                "backend": backend_name,
            }
            rows.append(row)
            if cl is None or cd is None or cm is None or alpha is None or not converged:
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
    quality = _quality_report(
        spec=spec,
        rows=rows,
        backend_name=backend_name,
        config=config,
        requested_cl_grid=requested_cl_grid,
        status_counts=status_counts,
    )
    source_quality = str(quality["source_quality"])
    alpha_l0, cl_alpha = _linear_lift_curve_estimate(polar_points)
    usable_clmax = quality["usable_clmax"]
    safe_clmax = None if usable_clmax is None else 0.90 * float(usable_clmax) - 0.05
    cm_values = [point.cm for point in polar_points if math.isfinite(point.cm)]
    record = AirfoilRecord(
        airfoil_id=str(spec.airfoil_id),
        name=str(spec.name),
        source=(
            f"{POLAR_BUILDER_SOURCE}:{backend_name}:"
            f"{Path(spec.coordinate_path).as_posix()}"
        ),
        source_quality=source_quality,
        zone_hint=str(spec.zone_hint),
        thickness_ratio=float(spec.thickness_ratio),
        max_camber=float(spec.max_camber),
        alpha_L0_deg=float(alpha_l0),
        cl_alpha_per_rad=float(cl_alpha),
        cm_design=float(np.median(cm_values)) if cm_values else float(spec.cm_design),
        safe_clmax=float(safe_clmax) if safe_clmax is not None else 0.0,
        usable_clmax=float(usable_clmax) if usable_clmax is not None else 0.0,
        polar_points=tuple(polar_points),
        notes=(
            f"{spec.notes} Generated from {dat_title}; "
            f"quality_passed={quality['quality_passed']}."
        ),
    )
    return record, rows, quality


def _quality_report(
    *,
    spec: SeedAirfoilSpec,
    rows: Sequence[Mapping[str, Any]],
    backend_name: str,
    config: PolarBuildConfig,
    requested_cl_grid: Sequence[float],
    status_counts: Mapping[str, int],
) -> dict[str, Any]:
    finite_rows = [
        row
        for row in rows
        if bool(row.get("converged"))
        and _finite_float(row.get("cl")) is not None
        and _finite_float(row.get("cd")) is not None
        and _finite_float(row.get("cm")) is not None
        and _finite_float(row.get("alpha_deg")) is not None
    ]
    total_rows = max(len(rows), 1)
    pass_rate = len(finite_rows) / total_rows
    cd_values = [_finite_float(row.get("cd")) for row in finite_rows]
    cl_values = [_finite_float(row.get("cl")) for row in finite_rows]
    roughness_modes = sorted(
        {
            str(row.get("roughness_mode"))
            for row in finite_rows
            if isinstance(row.get("roughness_mode"), str)
        }
    )
    enough_work_points = _enough_work_point_coverage(finite_rows, requested_cl_grid)
    usable_clmax = max((float(value) for value in cl_values if value is not None), default=None)
    issues: list[str] = []
    if pass_rate < float(config.convergence_pass_rate_threshold):
        issues.append("convergence_pass_rate_below_threshold")
    if not enough_work_points:
        issues.append("insufficient_cl_work_point_coverage")
    if not cd_values or any(value is None or not math.isfinite(value) for value in cd_values):
        issues.append("cd_nonfinite")
    if any(value is not None and value <= 0.0 for value in cd_values):
        issues.append("cd_nonphysical_nonpositive")
    if usable_clmax is None or not math.isfinite(float(usable_clmax)):
        issues.append("usable_clmax_nonfinite")
    if not Path(spec.coordinate_path).is_file():
        issues.append("coordinate_source_missing")
    if not backend_name:
        issues.append("backend_metadata_missing")
    quality_passed = not issues
    real_xfoil_backend = backend_name not in {"dry_run_xfoil_surrogate", "dry_run"}
    if quality_passed and real_xfoil_backend:
        if "clean" in roughness_modes and "rough" in roughness_modes:
            source_quality = "xfoil_mission_grade_candidate"
        else:
            source_quality = "xfoil_generated_clean_only"
    else:
        source_quality = "xfoil_incomplete_not_mission_grade"
    return {
        "airfoil_id": spec.airfoil_id,
        "source_quality": source_quality,
        "quality_passed": bool(quality_passed),
        "mission_grade_allowed": bool(quality_passed and real_xfoil_backend),
        "issues": issues,
        "convergence_pass_rate": pass_rate,
        "converged_point_count": len(finite_rows),
        "total_point_count": len(rows),
        "roughness_modes": roughness_modes,
        "usable_clmax": usable_clmax,
        "safe_clmax": None if usable_clmax is None else 0.90 * float(usable_clmax) - 0.05,
        "status_counts": dict(status_counts),
    }


def _enough_work_point_coverage(
    finite_rows: Sequence[Mapping[str, Any]],
    requested_cl_grid: Sequence[float],
) -> bool:
    if len(finite_rows) < 3:
        return False
    observed = [_finite_float(row.get("cl")) for row in finite_rows]
    observed = [float(value) for value in observed if value is not None]
    if not observed:
        return False
    representative = [min(requested_cl_grid), np.median(requested_cl_grid), max(requested_cl_grid)]
    return all(min(abs(value - target) for value in observed) <= 0.075 for target in representative)


def _linear_lift_curve_estimate(
    points: Sequence[AirfoilPolarPoint],
) -> tuple[float, float]:
    clean = [
        point
        for point in points
        if point.roughness_mode == "clean"
        and math.isfinite(point.cl)
        and math.isfinite(point.alpha_deg)
    ]
    if len(clean) < 2:
        clean = [point for point in points if math.isfinite(point.cl) and math.isfinite(point.alpha_deg)]
    if len(clean) < 2:
        return -2.0, 2.0 * math.pi
    xs = np.asarray([point.alpha_deg for point in clean], dtype=float)
    ys = np.asarray([point.cl for point in clean], dtype=float)
    mask = (ys >= 0.1) & (ys <= 1.1)
    if np.count_nonzero(mask) >= 2:
        xs = xs[mask]
        ys = ys[mask]
    slope_per_deg, intercept = np.polyfit(xs, ys, deg=1)
    if abs(float(slope_per_deg)) <= 1.0e-12:
        return -2.0, 2.0 * math.pi
    alpha_l0 = -float(intercept) / float(slope_per_deg)
    cl_alpha_per_rad = float(slope_per_deg) * 180.0 / math.pi
    return alpha_l0, cl_alpha_per_rad


def _dry_run_result(query: PolarQuery) -> dict[str, Any]:
    polar_points = []
    for cl_value in query.cl_samples:
        cl = float(cl_value)
        rough_penalty = 0.003 if query.roughness_mode in {"rough", "dirty"} else 0.0
        polar_points.append(
            {
                "alpha_deg": -2.25 + 8.8 * cl,
                "cl": cl,
                "cd": 0.0105 + rough_penalty + 0.008 * (cl - 0.72) ** 2,
                "cm": -0.07,
                "converged": True,
            }
        )
    return {
        "template_id": query.template_id,
        "reynolds": query.reynolds,
        "cl_samples": list(query.cl_samples),
        "roughness_mode": query.roughness_mode,
        "geometry_hash": query.geometry_hash,
        "analysis_mode": query.analysis_mode,
        "analysis_stage": query.analysis_stage,
        "status": "dry_run_ok",
        "polar_points": polar_points,
        "sweep_summary": {
            "converged_point_count": len(polar_points),
            "sweep_point_count": len(polar_points),
            "cl_max_observed": max(query.cl_samples) if query.cl_samples else None,
        },
    }


def _query_cache_path(
    query: PolarQuery,
    *,
    backend_name: str,
    config: PolarBuildConfig,
    cache_dir: Path,
) -> Path:
    payload = {
        "airfoil_id": query.template_id,
        "reynolds": float(query.reynolds),
        "cl_samples": list(query.cl_samples),
        "roughness_mode": query.roughness_mode,
        "geometry_hash": query.geometry_hash,
        "analysis_mode": query.analysis_mode,
        "analysis_stage": query.analysis_stage,
        "backend_name": backend_name,
        "xfoil_max_iter": int(config.xfoil_max_iter),
        "panel_count": int(config.panel_count),
        "source_quality_policy": str(config.source_quality_policy),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return cache_dir / str(query.template_id) / f"{digest}.json"


def _backend_name(*, backend: str, worker: Any | None) -> str:
    if backend == "dry_run":
        return "dry_run_xfoil_surrogate"
    if backend == "worker":
        return str(getattr(worker, "backend_name", "xfoil_worker"))
    raise ValueError("backend must be 'dry_run' or 'worker'.")


def _record_from_payload(payload: Mapping[str, Any]) -> AirfoilRecord:
    polar_payload = payload.get("polar_points", [])
    polar_points = tuple(
        AirfoilPolarPoint(
            Re=float(point["Re"]),
            cl=float(point["cl"]),
            cd=float(point["cd"]),
            cm=float(point["cm"]),
            alpha_deg=float(point["alpha_deg"]),
            roughness_mode=str(point.get("roughness_mode", "clean")),
        )
        for point in polar_payload
        if isinstance(point, Mapping)
    )
    return AirfoilRecord(
        airfoil_id=str(payload["airfoil_id"]),
        name=str(payload["name"]),
        source=str(payload["source"]),
        source_quality=str(payload["source_quality"]),
        zone_hint=str(payload.get("zone_hint", "")),
        thickness_ratio=float(payload.get("thickness_ratio", 0.0)),
        max_camber=float(payload.get("max_camber", 0.0)),
        alpha_L0_deg=float(payload.get("alpha_L0_deg", 0.0)),
        cl_alpha_per_rad=float(payload.get("cl_alpha_per_rad", 2.0 * math.pi)),
        cm_design=float(payload.get("cm_design", 0.0)),
        safe_clmax=float(payload.get("safe_clmax", 0.0)),
        usable_clmax=float(payload.get("usable_clmax", 0.0)),
        polar_points=polar_points,
        notes=str(payload.get("notes", "")),
    )


def _all_polar_rows(result: PolarBuildResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for airfoil_id, airfoil_rows in result.polar_rows_by_airfoil.items():
        record = result.airfoil_database.records[airfoil_id]
        for row in airfoil_rows:
            rows.append(
                {
                    **row,
                    "record_source_quality": record.source_quality,
                    "record_source": record.source,
                }
            )
    return rows


def _polar_csv_fields() -> list[str]:
    return [
        "airfoil_id",
        "name",
        "Re",
        "roughness_mode",
        "alpha_deg",
        "cl",
        "cd",
        "cm",
        "converged",
        "status",
        "backend",
        "record_source_quality",
        "record_source",
    ]


def _build_report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Seed Airfoil Polar Build Report",
        "",
        f"- Source: {report.get('source')}",
        f"- Backend: {report.get('backend')}",
        f"- Airfoil count: {report.get('airfoil_count')}",
        f"- Source quality counts: `{report.get('source_quality_counts')}`",
        "",
        "## Airfoils",
        "",
    ]
    airfoils = report.get("airfoils", {})
    if isinstance(airfoils, Mapping):
        for airfoil_id, item in airfoils.items():
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "- "
                f"{airfoil_id}: {item.get('source_quality')}, "
                f"pass rate {float(item.get('convergence_pass_rate') or 0.0):.3f}, "
                f"usable Clmax {item.get('usable_clmax')}, "
                f"issues {item.get('issues')}"
            )
    lines.append("")
    lines.append(
        "Dry-run artifacts and incomplete XFOIL builds are not mission-grade; "
        "sidecar evidence should only be promoted when source_quality is an XFOIL generated candidate."
    )
    lines.append("")
    return "\n".join(lines)


def _source_quality_counts(records: Sequence[AirfoilRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.source_quality] = counts.get(record.source_quality, 0) + 1
    return counts


def _unique_sorted(values: Sequence[float]) -> tuple[float, ...]:
    return tuple(sorted({round(float(value), 6) for value in values if math.isfinite(float(value))}))


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
