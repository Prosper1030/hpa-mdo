#!/usr/bin/env python3
"""Build a reusable full-alpha polar archive for shortlisted airfoils.

This is a Phase 6 sidecar utility.  It does not change aircraft ranking or
route gates; it only verifies shortlisted seed/CST airfoils and writes
quality-labeled database artifacts that later sidecar runs can consume.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from hpa_mdo.airfoils.database import (  # noqa: E402
    AirfoilDatabase,
    AirfoilPolarPoint,
    AirfoilRecord,
    airfoil_coordinate_path_from_record,
    default_airfoil_database,
)
from hpa_mdo.airfoils.polar_builder import (  # noqa: E402
    load_airfoil_database_artifact,
    read_airfoil_dat,
    seed_airfoil_specs,
)
from hpa_mdo.concept.airfoil_worker import (  # noqa: E402
    JuliaXFoilWorker,
    PolarQuery,
    geometry_hash_from_coordinates,
)


SOURCE = "full_polar_airfoil_archive_builder_v1"
GLOBAL_HPA_RE_GRID = (
    100_000.0,
    125_000.0,
    150_000.0,
    175_000.0,
    200_000.0,
    250_000.0,
    300_000.0,
    350_000.0,
    400_000.0,
    500_000.0,
    600_000.0,
    700_000.0,
)
DEFAULT_SEED_IDS = ("fx76mp140", "clarkysm", "dae11", "dae21", "dae31", "dae41")
ZONE_NAMES = ("root", "mid1", "mid2", "tip")


@dataclass(frozen=True)
class Candidate:
    airfoil_id: str
    name: str
    zone_origin: str
    coordinate_path: Path
    screening_source_quality: str
    source: str
    thickness_ratio: float
    max_camber: float
    cm_design: float
    safe_clmax_screening: float
    usable_clmax_screening: float
    original_record: AirfoilRecord | None = None
    manifest_metadata: dict[str, Any] | None = None


@dataclass
class BuildState:
    records: list[AirfoilRecord]
    polar_rows: list[dict[str, Any]]
    quality_rows: list[dict[str, Any]]
    coverage_rows: list[dict[str, Any]]
    gap_rows: list[dict[str, Any]]
    record_reports: dict[str, dict[str, Any]]


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    screening_dir = Path(args.screening_output_dir)
    database = load_airfoil_database_artifact(
        screening_dir / "airfoil_database.json",
        fallback_database=default_airfoil_database(),
    )
    zone_envelopes = _load_zone_envelopes(Path(args.zone_envelope_json))
    candidates = _select_shortlist(
        database=database,
        screening_dir=screening_dir,
        phase6_sidecar_dir=Path(args.phase6_sidecar_dir) if args.phase6_sidecar_dir else None,
        zone_envelopes=zone_envelopes,
        top_k_per_zone=int(args.top_k_per_zone),
        pareto_per_zone=int(args.pareto_per_zone),
        include_seed_airfoils=not args.no_seed_airfoils,
        candidate_manifest_csv=Path(args.candidate_manifest_csv) if args.candidate_manifest_csv else None,
        manifest_tier_flag=str(args.manifest_tier_flag),
    )

    alpha_samples = _float_range(float(args.alpha_min_deg), float(args.alpha_max_deg), float(args.alpha_step_deg))
    roughness_modes = _parse_csv_arg(args.roughness_modes)
    backend = "dry_run" if args.dry_run else str(args.backend)
    worker: JuliaXFoilWorker | None = None
    if backend == "julia":
        worker = JuliaXFoilWorker(
            project_dir=_REPO_ROOT,
            cache_dir=output_dir / ".cache" / "julia_xfoil_worker",
            persistent_mode=True,
            persistent_worker_count=int(args.julia_worker_count),
            xfoil_max_iter=int(args.xfoil_max_iter),
            xfoil_panel_count=int(args.panel_count),
        )
    elif backend != "dry_run":
        raise ValueError("--backend must be 'julia' or use --dry-run.")

    run_metadata = {
        "schema_version": "full_polar_run_metadata_v1",
        "source": SOURCE,
        "screening_output_dir": str(screening_dir),
        "zone_envelope_json": str(args.zone_envelope_json),
        "output_dir": str(output_dir),
        "backend": backend,
        "candidate_count": len(candidates),
        "candidate_airfoil_ids": [candidate.airfoil_id for candidate in candidates],
        "candidate_manifest_csv": str(args.candidate_manifest_csv or ""),
        "manifest_tier_flag": str(args.manifest_tier_flag),
        "resume": bool(args.resume),
        "roughness_modes": roughness_modes,
        "alpha_samples": alpha_samples,
        "args": vars(args),
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(_json_ready(run_metadata), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    state = _load_existing_state(output_dir) if args.resume else BuildState([], [], [], [], [], {})
    completed_airfoil_ids = {record.airfoil_id for record in state.records}
    try:
        for index, candidate in enumerate(candidates, start=1):
            if args.resume and candidate.airfoil_id in completed_airfoil_ids:
                print(f"[full-polar] skipping completed {candidate.airfoil_id}", flush=True)
                continue
            print(
                f"[full-polar] {index}/{len(candidates)} {candidate.airfoil_id} "
                f"zone={candidate.zone_origin}",
                flush=True,
            )
            try:
                _evaluate_candidate(
                    candidate=candidate,
                    zone_envelopes=zone_envelopes,
                    roughness_modes=roughness_modes,
                    alpha_samples=alpha_samples,
                    backend=backend,
                    worker=worker,
                    xfoil_max_iter=int(args.xfoil_max_iter),
                    panel_count=int(args.panel_count),
                    convergence_threshold=float(args.convergence_pass_rate_threshold),
                    state=state,
                )
            except Exception as exc:  # noqa: BLE001 - long batch builds must mark-and-continue.
                _mark_candidate_failed(
                    candidate=candidate,
                    exc=exc,
                    roughness_modes=roughness_modes,
                    alpha_samples=alpha_samples,
                    xfoil_max_iter=int(args.xfoil_max_iter),
                    panel_count=int(args.panel_count),
                    state=state,
                )
            completed_airfoil_ids.add(candidate.airfoil_id)
            _write_artifacts(state=state, output_dir=output_dir, args=args, zone_envelopes=zone_envelopes)
    finally:
        if worker is not None:
            worker.close()

    paths = _write_artifacts(state=state, output_dir=output_dir, args=args, zone_envelopes=zone_envelopes)
    print(
        json.dumps(
            {
                "full_polar_build_report": str(paths["full_polar_build_report_json"]),
                "record_count": len(state.records),
                "source_quality_counts": _source_quality_counts(state.records),
            },
            sort_keys=True,
        )
    )
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screening-output-dir", required=True)
    parser.add_argument("--phase6-sidecar-dir", default="")
    parser.add_argument("--zone-envelope-json", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--candidate-manifest-csv", default="")
    parser.add_argument("--manifest-tier-flag", default="tier2_recommended_reusable")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--backend", default="julia", choices=("julia", "dry_run"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top-k-per-zone", type=int, default=5)
    parser.add_argument("--pareto-per-zone", type=int, default=0)
    parser.add_argument("--roughness-modes", default="clean,rough")
    parser.add_argument("--alpha-min-deg", type=float, default=-6.0)
    parser.add_argument("--alpha-max-deg", type=float, default=18.0)
    parser.add_argument("--alpha-step-deg", type=float, default=0.5)
    parser.add_argument("--xfoil-max-iter", type=int, default=40)
    parser.add_argument("--panel-count", type=int, default=96)
    parser.add_argument("--julia-worker-count", type=int, default=4)
    parser.add_argument("--convergence-pass-rate-threshold", type=float, default=0.80)
    parser.add_argument("--no-seed-airfoils", action="store_true")
    return parser.parse_args(argv)


def _load_existing_state(output_dir: Path) -> BuildState:
    records: list[AirfoilRecord] = []
    records_path = output_dir / "airfoil_records.json"
    if records_path.is_file():
        database = load_airfoil_database_artifact(records_path)
        records = list(database.records.values())

    polar_rows = _read_csv_rows(output_dir / "polar_points.csv")
    quality_rows = _read_csv_rows(output_dir / "quality_report.csv")
    coverage_rows = _read_csv_rows(output_dir / "coverage_report.csv")
    gap_rows = _read_csv_rows(output_dir / "gap_report.csv")
    record_reports: dict[str, dict[str, Any]] = {}
    report_path = output_dir / "full_polar_build_report.json"
    if not report_path.is_file():
        report_path = output_dir / "build_report.json"
    if report_path.is_file():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        records_payload = payload.get("records", {})
        if isinstance(records_payload, Mapping):
            for airfoil_id, item in records_payload.items():
                if isinstance(item, Mapping):
                    record_reports[str(airfoil_id)] = dict(item)
    return BuildState(records, polar_rows, quality_rows, coverage_rows, gap_rows, record_reports)


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _load_zone_envelopes(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        rows = (
            payload.get("zone_envelope")
            or payload.get("zone_envelopes")
            or payload.get("rows")
            or []
        )
    else:
        rows = []
    envelopes: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        zone = str(row.get("zone_name") or row.get("zone") or "").strip()
        if zone:
            envelopes[zone] = dict(row)
    return envelopes


def _select_shortlist(
    *,
    database: AirfoilDatabase,
    screening_dir: Path,
    phase6_sidecar_dir: Path | None,
    zone_envelopes: Mapping[str, Mapping[str, Any]],
    top_k_per_zone: int,
    pareto_per_zone: int,
    include_seed_airfoils: bool,
    candidate_manifest_csv: Path | None,
    manifest_tier_flag: str,
) -> list[Candidate]:
    reasons: dict[str, str] = {}
    zone_by_airfoil: dict[str, str] = {}
    manifest_by_airfoil: dict[str, dict[str, Any]] = {}

    if candidate_manifest_csv is not None:
        for row in _read_manifest_tier_rows(candidate_manifest_csv, manifest_tier_flag):
            airfoil_id = str(row.get("airfoil_id") or "").strip()
            if not airfoil_id:
                continue
            manifest_by_airfoil.setdefault(airfoil_id, dict(row))
            reasons.setdefault(airfoil_id, str(row.get("inclusion_reason") or "phase8_manifest_tier"))
            zone = _first_zone(str(row.get("zone") or "")) or _infer_zone_from_id(airfoil_id)
            zone_by_airfoil.setdefault(airfoil_id, zone)
    else:
        for zone, airfoil_id in _read_ranked_airfoil_rows(
            screening_dir / "per_zone_top_k.csv",
            limit_per_zone=max(0, top_k_per_zone),
        ):
            reasons.setdefault(airfoil_id, "per_zone_top_k")
            zone_by_airfoil.setdefault(airfoil_id, zone)

        if pareto_per_zone > 0:
            for zone, airfoil_id in _read_ranked_airfoil_rows(
                screening_dir / "per_zone_pareto.csv",
                limit_per_zone=pareto_per_zone,
            ):
                reasons.setdefault(airfoil_id, "per_zone_pareto")
                zone_by_airfoil.setdefault(airfoil_id, zone)

        if phase6_sidecar_dir is not None:
            for zone, airfoil_id in _read_sidecar_assignment_airfoils(phase6_sidecar_dir / "sidecar_combinations.csv"):
                if airfoil_id.startswith("cst_"):
                    reasons.setdefault(airfoil_id, "phase6_sidecar_combination")
                    zone_by_airfoil.setdefault(airfoil_id, zone)

    if include_seed_airfoils:
        for airfoil_id in DEFAULT_SEED_IDS:
            reasons.setdefault(airfoil_id, "seed_reference")

    candidates: list[Candidate] = []
    seed_specs = seed_airfoil_specs()
    for airfoil_id in reasons:
        manifest_metadata = {
            **manifest_by_airfoil.get(airfoil_id, {}),
            "inclusion_reason": manifest_by_airfoil.get(airfoil_id, {}).get("inclusion_reason")
            or reasons.get(airfoil_id, ""),
        }
        record = database.records.get(airfoil_id)
        if record is not None:
            coordinate_path = _coordinate_path_from_manifest_or_record(manifest_metadata, record)
            if coordinate_path is not None:
                zone_origin = zone_by_airfoil.get(airfoil_id) or _first_zone(record.zone_hint) or _infer_zone_from_id(airfoil_id)
                candidates.append(
                    Candidate(
                        airfoil_id=record.airfoil_id,
                        name=record.name,
                        zone_origin=zone_origin,
                        coordinate_path=coordinate_path,
                        screening_source_quality=str(
                            manifest_metadata.get("screening_quality")
                            or _screening_quality(record.source_quality)
                        ),
                        source=record.source,
                        thickness_ratio=record.thickness_ratio,
                        max_camber=record.max_camber,
                        cm_design=record.cm_design,
                        safe_clmax_screening=record.safe_clmax,
                        usable_clmax_screening=record.usable_clmax,
                        original_record=record,
                        manifest_metadata=manifest_metadata,
                    )
                )
                continue
        spec = seed_specs.get(airfoil_id)
        if spec is None or not spec.coordinate_path.is_file():
            continue
        candidates.append(
            Candidate(
                airfoil_id=spec.airfoil_id,
                name=spec.name,
                zone_origin=_first_zone(spec.zone_hint) or _infer_zone_from_id(airfoil_id),
                coordinate_path=spec.coordinate_path,
                screening_source_quality="seed_reference_pending_full_polar",
                source=f"seed_airfoil:{spec.coordinate_path}",
                thickness_ratio=spec.thickness_ratio,
                max_camber=spec.max_camber,
                cm_design=spec.cm_design,
                safe_clmax_screening=0.0,
                usable_clmax_screening=0.0,
                original_record=None,
                manifest_metadata=manifest_metadata,
            )
        )

    def sort_key(candidate: Candidate) -> tuple[int, str]:
        zone_order = {zone: index for index, zone in enumerate(ZONE_NAMES)}
        return (zone_order.get(candidate.zone_origin, 99), candidate.airfoil_id)

    return sorted(_dedupe_candidates(candidates), key=sort_key)


def _read_manifest_tier_rows(path: Path, tier_flag: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Candidate manifest not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if _truthy(row.get(tier_flag)):
                rows.append(dict(row))
    return rows


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _coordinate_path_from_manifest_or_record(
    manifest_metadata: Mapping[str, Any],
    record: AirfoilRecord,
) -> Path | None:
    manifest_path = str(manifest_metadata.get("coordinate_path") or "").strip()
    if manifest_path:
        path = Path(manifest_path).expanduser()
        if not path.is_absolute():
            path = (_REPO_ROOT / path).resolve()
        if path.is_file():
            return path
    return airfoil_coordinate_path_from_record(record, repo_root=_REPO_ROOT)


def _read_ranked_airfoil_rows(path: Path, *, limit_per_zone: int) -> list[tuple[str, str]]:
    if limit_per_zone <= 0 or not path.is_file():
        return []
    rows: list[tuple[str, str]] = []
    counts: dict[str, int] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            zone = str(row.get("zone_name") or row.get("zone") or "").strip()
            airfoil_id = str(row.get("airfoil_id") or "").strip()
            if not zone or not airfoil_id:
                continue
            if counts.get(zone, 0) >= limit_per_zone:
                continue
            rows.append((zone, airfoil_id))
            counts[zone] = counts.get(zone, 0) + 1
    return rows


def _read_sidecar_assignment_airfoils(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    pairs: list[tuple[str, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("status", "")).strip() != "ok":
                continue
            label = str(row.get("assignment_label") or "")
            for item in label.split("|"):
                if ":" not in item:
                    continue
                zone, airfoil_id = item.split(":", 1)
                pairs.append((zone.strip(), airfoil_id.strip()))
    return pairs


def _evaluate_candidate(
    *,
    candidate: Candidate,
    zone_envelopes: Mapping[str, Mapping[str, Any]],
    roughness_modes: Sequence[str],
    alpha_samples: Sequence[float],
    backend: str,
    worker: JuliaXFoilWorker | None,
    xfoil_max_iter: int,
    panel_count: int,
    convergence_threshold: float,
    state: BuildState,
) -> None:
    _title, coordinates = read_airfoil_dat(candidate.coordinate_path)
    geometry_hash = geometry_hash_from_coordinates(coordinates)
    re_grid = _re_grid_for_candidate(candidate, zone_envelopes)
    cl_samples = _cl_samples_for_candidate(candidate, zone_envelopes)
    queries = [
        PolarQuery(
            template_id=candidate.airfoil_id,
            reynolds=re_value,
            cl_samples=tuple(cl_samples),
            roughness_mode=roughness_mode,
            geometry_hash=geometry_hash,
            coordinates=coordinates,
            analysis_mode="full_alpha_sweep",
            analysis_stage="phase6_full_polar",
            alpha_samples=tuple(alpha_samples),
        )
        for roughness_mode in roughness_modes
        for re_value in re_grid
    ]
    if backend == "dry_run":
        results = [_dry_run_full_polar_result(query) for query in queries]
        backend_name = "dry_run_full_polar_surrogate"
    else:
        if worker is None:
            raise ValueError("Real full-polar build requires a JuliaXFoilWorker.")
        results = worker.run_queries(queries)
        backend_name = worker.backend_name

    rows = _polar_rows_from_results(candidate, results, backend_name=backend_name)
    quality = _quality_for_candidate(
        candidate=candidate,
        rows=rows,
        zone_envelopes=zone_envelopes,
        roughness_modes=roughness_modes,
        backend=backend,
        convergence_threshold=convergence_threshold,
    )
    polar_points = [
        AirfoilPolarPoint(
            Re=float(row["Re"]),
            cl=float(row["cl"]),
            cd=float(row["cd"]),
            cm=float(row["cm"]),
            alpha_deg=float(row["alpha_deg"]),
            roughness_mode=str(row["roughness_mode"]),
        )
        for row in rows
        if _row_is_finite_converged(row) and str(row.get("branch_label")) == "prestall"
    ]
    alpha_l0, cl_alpha = _fit_linear_lift_curve(polar_points)
    cm_values = [point.cm for point in polar_points if math.isfinite(point.cm)]
    record = AirfoilRecord(
        airfoil_id=candidate.airfoil_id,
        name=candidate.name,
        source=f"{SOURCE}:{backend_name}:{candidate.coordinate_path}",
        source_quality=str(quality["source_quality"]),
        zone_hint=candidate.zone_origin,
        thickness_ratio=float(candidate.thickness_ratio),
        max_camber=float(candidate.max_camber),
        alpha_L0_deg=float(alpha_l0),
        cl_alpha_per_rad=float(cl_alpha),
        cm_design=float(np.median(cm_values)) if cm_values else float(candidate.cm_design),
        safe_clmax=float(quality.get("safe_clmax") or 0.0),
        usable_clmax=float(quality.get("usable_clmax") or 0.0),
        polar_points=tuple(polar_points),
        notes=(
            f"Full-polar Phase 6 archive record. screening_quality="
            f"{candidate.screening_source_quality}; quality_passed={quality['quality_passed']}."
        ),
        coordinate_path=str(candidate.coordinate_path),
    )
    state.records = [item for item in state.records if item.airfoil_id != record.airfoil_id]
    state.records.append(record)
    state.polar_rows = [row for row in state.polar_rows if row.get("airfoil_id") != candidate.airfoil_id]
    state.polar_rows.extend(rows)
    state.quality_rows = [row for row in state.quality_rows if row.get("airfoil_id") != candidate.airfoil_id]
    state.quality_rows.append({**quality, **_candidate_report_metadata(candidate), "airfoil_id": candidate.airfoil_id})
    state.coverage_rows = [
        row for row in state.coverage_rows if row.get("airfoil_id") != candidate.airfoil_id
    ]
    state.coverage_rows.extend(_coverage_rows(candidate, rows, zone_envelopes, quality))
    state.gap_rows = [row for row in state.gap_rows if row.get("airfoil_id") != candidate.airfoil_id]
    state.gap_rows.extend(_gap_rows(candidate, quality))
    state.record_reports[candidate.airfoil_id] = {
        **quality,
        **_candidate_report_metadata(candidate),
        "zone_origin": candidate.zone_origin,
        "coordinate_path": str(candidate.coordinate_path),
        "query_count": len(queries),
        "re_grid": re_grid,
        "cl_work_points": cl_samples,
        "roughness_modes": list(roughness_modes),
        "xfoil_max_iter": int(xfoil_max_iter),
        "panel_count": int(panel_count),
    }


def _mark_candidate_failed(
    *,
    candidate: Candidate,
    exc: Exception,
    roughness_modes: Sequence[str],
    alpha_samples: Sequence[float],
    xfoil_max_iter: int,
    panel_count: int,
    state: BuildState,
) -> None:
    message = f"{type(exc).__name__}: {exc}"
    print(f"[full-polar] failed {candidate.airfoil_id}: {message}", flush=True)
    quality = {
        "source_quality": "full_polar_failed_not_mission_grade",
        "quality_passed": False,
        "mission_grade_allowed": False,
        "issues": "worker_exception",
        "issue_count": 1,
        "convergence_pass_rate": 0.0,
        "converged_point_count": 0,
        "total_point_count": 0,
        "roughness_modes_observed": "",
        "usable_clmax": None,
        "safe_clmax": None,
        "cd_min": None,
        "cd_p90": None,
        "mean_cd": None,
        "re_min_observed": None,
        "re_max_observed": None,
        "alpha_min_observed": None,
        "alpha_max_observed": None,
        "roughness_sensitivity": None,
        "exception_message": message,
    }
    record = AirfoilRecord(
        airfoil_id=candidate.airfoil_id,
        name=candidate.name,
        source=f"{SOURCE}:failed:{candidate.coordinate_path}",
        source_quality=str(quality["source_quality"]),
        zone_hint=candidate.zone_origin,
        thickness_ratio=float(candidate.thickness_ratio),
        max_camber=float(candidate.max_camber),
        alpha_L0_deg=-2.0,
        cl_alpha_per_rad=2.0 * math.pi,
        cm_design=float(candidate.cm_design),
        safe_clmax=0.0,
        usable_clmax=0.0,
        polar_points=(),
        notes=(
            f"Full-polar build failed and was marked null-safe. "
            f"screening_quality={candidate.screening_source_quality}; exception={message}"
        ),
        coordinate_path=str(candidate.coordinate_path),
    )
    state.records = [item for item in state.records if item.airfoil_id != record.airfoil_id]
    state.records.append(record)
    state.polar_rows = [row for row in state.polar_rows if row.get("airfoil_id") != candidate.airfoil_id]
    state.quality_rows = [row for row in state.quality_rows if row.get("airfoil_id") != candidate.airfoil_id]
    state.quality_rows.append({**quality, **_candidate_report_metadata(candidate), "airfoil_id": candidate.airfoil_id})
    state.coverage_rows = [
        row for row in state.coverage_rows if row.get("airfoil_id") != candidate.airfoil_id
    ]
    state.coverage_rows.append(
        {
            "airfoil_id": candidate.airfoil_id,
            "zone_name": candidate.zone_origin,
            "coverage_passed": False,
            "source_quality": quality["source_quality"],
            "gap": "worker_exception",
            **_candidate_report_metadata(candidate),
        }
    )
    state.gap_rows = [row for row in state.gap_rows if row.get("airfoil_id") != candidate.airfoil_id]
    state.gap_rows.append(
        {
            "airfoil_id": candidate.airfoil_id,
            "zone_name": candidate.zone_origin,
            "gap": "worker_exception",
            "source_quality": quality["source_quality"],
            "exception_message": message,
            **_candidate_report_metadata(candidate),
        }
    )
    state.record_reports[candidate.airfoil_id] = {
        **quality,
        **_candidate_report_metadata(candidate),
        "zone_origin": candidate.zone_origin,
        "coordinate_path": str(candidate.coordinate_path),
        "query_count": 0,
        "re_grid": [],
        "cl_work_points": [],
        "roughness_modes": list(roughness_modes),
        "alpha_samples": list(alpha_samples),
        "xfoil_max_iter": int(xfoil_max_iter),
        "panel_count": int(panel_count),
    }


def _dry_run_full_polar_result(query: PolarQuery) -> dict[str, Any]:
    full_points: list[dict[str, Any]] = []
    re_factor = (300_000.0 / max(float(query.reynolds), 1.0)) ** 0.08
    rough_penalty = 0.0035 if query.roughness_mode in {"rough", "dirty"} else 0.0
    for alpha in query.alpha_samples:
        alpha_float = float(alpha)
        cl_linear = 0.105 * (alpha_float + 2.2)
        stall_softening = max(0.0, alpha_float - 13.0) ** 2 * 0.018
        cl = min(1.55, cl_linear - stall_softening)
        cd = 0.0105 * re_factor + rough_penalty + 0.0075 * (cl - 0.55) ** 2
        full_points.append(
            {
                "alpha_deg": alpha_float,
                "cl": float(cl),
                "cd": float(cd),
                "cdp": float(max(cd - 0.002, 0.0)),
                "cm": -0.055,
                "converged": True,
            }
        )
    polar_points = []
    for cl_target in query.cl_samples:
        best = min(full_points, key=lambda row: abs(float(row["cl"]) - float(cl_target)))
        polar_points.append(
            {
                **best,
                "cl_target": float(cl_target),
                "cl_error": float(best["cl"]) - float(cl_target),
            }
        )
    return {
        "template_id": query.template_id,
        "reynolds": query.reynolds,
        "cl_samples": list(query.cl_samples),
        "alpha_samples": list(query.alpha_samples),
        "roughness_mode": query.roughness_mode,
        "geometry_hash": query.geometry_hash,
        "analysis_mode": query.analysis_mode,
        "analysis_stage": query.analysis_stage,
        "status": "dry_run_ok",
        "polar_points": polar_points,
        "full_polar_points": full_points,
        "sweep_summary": {
            "sweep_point_count": len(full_points),
            "converged_point_count": len(full_points),
            "cl_max_observed": max((row["cl"] for row in full_points), default=None),
            "alpha_min_deg": min(query.alpha_samples) if query.alpha_samples else None,
            "alpha_max_deg": max(query.alpha_samples) if query.alpha_samples else None,
        },
    }


def _polar_rows_from_results(
    candidate: Candidate,
    results: Sequence[Mapping[str, Any]],
    *,
    backend_name: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        re_value = _finite_float(result.get("reynolds"))
        roughness_mode = str(result.get("roughness_mode", "clean"))
        status = str(result.get("status", "unknown"))
        point_payload = result.get("full_polar_points") or result.get("polar_points") or []
        if re_value is None or not isinstance(point_payload, list):
            continue
        for point in point_payload:
            if not isinstance(point, Mapping):
                continue
            row = {
                "airfoil_id": candidate.airfoil_id,
                "zone_origin": candidate.zone_origin,
                "zone": candidate.zone_origin,
                "Re": re_value,
                "roughness_mode": roughness_mode,
                "alpha_deg": _finite_float(point.get("alpha_deg")),
                "cl": _finite_float(point.get("cl")),
                "cd": _finite_float(point.get("cd")),
                "cm": _finite_float(point.get("cm")),
                "Cl": _finite_float(point.get("cl")),
                "Cd": _finite_float(point.get("cd")),
                "Cm": _finite_float(point.get("cm")),
                "converged": bool(point.get("converged", status in {"ok", "dry_run_ok"})),
                "status": status,
                "backend": backend_name,
                "warning_flags": ";".join(_point_warnings(point, status)),
                "branch_label": "unknown",
                "screening_quality": candidate.screening_source_quality,
                **_candidate_polar_metadata(candidate),
            }
            rows.append(row)
    return _label_prestall_branches(rows)


def _candidate_report_metadata(candidate: Candidate) -> dict[str, Any]:
    metadata = dict(candidate.manifest_metadata or {})
    return {
        "screening_quality": candidate.screening_source_quality,
        "archive_source_quality": metadata.get("archive_source_quality", ""),
        "actual_sidecar_query_quality": metadata.get("actual_sidecar_query_quality", ""),
        "repaired_archive_source_quality": metadata.get("repaired_archive_source_quality", ""),
        "repaired_actual_sidecar_query_quality": metadata.get("repaired_actual_sidecar_query_quality", ""),
        "repair_worthy_flag": metadata.get("repair_worthy_flag", ""),
        "inclusion_reason": metadata.get("inclusion_reason", ""),
        "source_category": metadata.get("source_category", ""),
        "candidate_role": metadata.get("candidate_role", ""),
        "generation_index": metadata.get("generation_index", ""),
    }


def _candidate_polar_metadata(candidate: Candidate) -> dict[str, Any]:
    metadata = dict(candidate.manifest_metadata or {})
    return {
        "archive_source_quality": metadata.get("archive_source_quality", ""),
        "actual_sidecar_query_quality": metadata.get("actual_sidecar_query_quality", ""),
        "inclusion_reason": metadata.get("inclusion_reason", ""),
    }


def _quality_for_candidate(
    *,
    candidate: Candidate,
    rows: Sequence[Mapping[str, Any]],
    zone_envelopes: Mapping[str, Mapping[str, Any]],
    roughness_modes: Sequence[str],
    backend: str,
    convergence_threshold: float,
) -> dict[str, Any]:
    finite_rows = [row for row in rows if _row_is_finite_converged(row)]
    total_rows = max(len(rows), 1)
    pass_rate = len(finite_rows) / total_rows
    cl_values = [float(row["cl"]) for row in finite_rows]
    cd_values = [float(row["cd"]) for row in finite_rows]
    re_values = [float(row["Re"]) for row in finite_rows]
    alpha_values = [float(row["alpha_deg"]) for row in finite_rows]
    usable_clmax = max(cl_values, default=None)
    safe_clmax = None if usable_clmax is None else 0.90 * usable_clmax - 0.05
    observed_modes = sorted({str(row.get("roughness_mode")) for row in finite_rows})
    issues: list[str] = []
    if pass_rate < convergence_threshold:
        issues.append("poor_convergence")
    if not finite_rows:
        issues.append("no_converged_full_polar_points")
    if any(value <= 0.0 for value in cd_values):
        issues.append("negative_or_zero_cd")
    if any(not math.isfinite(value) for value in cd_values):
        issues.append("nonfinite_cd")
    if usable_clmax is None or not math.isfinite(usable_clmax):
        issues.append("usable_clmax_nonfinite")
    if safe_clmax is None or not math.isfinite(safe_clmax):
        issues.append("safe_clmax_nonfinite")
    zone_issues = _zone_coverage_issues(candidate, re_values, cl_values, safe_clmax, zone_envelopes)
    issues.extend(zone_issues)
    if _has_cd_discontinuity(finite_rows):
        issues.append("discontinuous_cd")
    if not _prestall_branch_valid(finite_rows):
        issues.append("prestall_branch_invalid")
    if not candidate.coordinate_path.is_file():
        issues.append("coordinate_source_missing")

    quality_passed = not issues
    real_backend = backend == "julia"
    has_rough = "rough" in observed_modes or "dirty" in observed_modes
    if not real_backend:
        source_quality = "full_polar_candidate_not_mission_grade" if finite_rows else "full_polar_failed_not_mission_grade"
        mission_grade_allowed = False
    elif quality_passed and has_rough and "clean" in observed_modes:
        source_quality = "full_polar_mission_grade_candidate"
        mission_grade_allowed = True
    elif quality_passed:
        source_quality = "clean_only_not_full_mission_grade"
        mission_grade_allowed = False
    else:
        source_quality = "full_polar_candidate_not_mission_grade" if finite_rows else "full_polar_failed_not_mission_grade"
        mission_grade_allowed = False

    return {
        "source_quality": source_quality,
        "quality_passed": bool(quality_passed),
        "mission_grade_allowed": bool(mission_grade_allowed),
        "issues": ";".join(dict.fromkeys(issues)),
        "issue_count": len(dict.fromkeys(issues)),
        "convergence_pass_rate": float(pass_rate),
        "converged_point_count": len(finite_rows),
        "total_point_count": len(rows),
        "roughness_modes_observed": ";".join(observed_modes),
        "usable_clmax": usable_clmax,
        "safe_clmax": safe_clmax,
        "cd_min": min(cd_values, default=None),
        "cd_p90": float(np.percentile(cd_values, 90)) if cd_values else None,
        "mean_cd": float(np.mean(cd_values)) if cd_values else None,
        "re_min_observed": min(re_values, default=None),
        "re_max_observed": max(re_values, default=None),
        "alpha_min_observed": min(alpha_values, default=None),
        "alpha_max_observed": max(alpha_values, default=None),
        "roughness_sensitivity": _roughness_sensitivity(finite_rows),
    }


def _label_prestall_branches(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    labeled = [dict(row) for row in rows]
    grouped: dict[tuple[float, str], list[int]] = {}
    for index, row in enumerate(labeled):
        re_value = _finite_float(row.get("Re"))
        if re_value is None:
            continue
        grouped.setdefault((re_value, str(row.get("roughness_mode"))), []).append(index)

    for indices in grouped.values():
        finite_indices = [index for index in indices if _row_is_finite_converged(labeled[index])]
        if not finite_indices:
            continue
        max_cl_index = max(finite_indices, key=lambda index: float(labeled[index]["cl"]))
        alpha_at_max = float(labeled[max_cl_index]["alpha_deg"])
        for index in indices:
            row = labeled[index]
            alpha = _finite_float(row.get("alpha_deg"))
            if not _row_is_finite_converged(row) or alpha is None:
                row["branch_label"] = "unknown"
            elif alpha <= alpha_at_max:
                row["branch_label"] = "prestall"
            else:
                row["branch_label"] = "poststall"
    return labeled


def _write_artifacts(
    *,
    state: BuildState,
    output_dir: Path,
    args: argparse.Namespace,
    zone_envelopes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    records_sorted = sorted(state.records, key=lambda record: record.airfoil_id)
    database = AirfoilDatabase.from_records(records_sorted)
    records_payload = []
    for record in records_sorted:
        payload = record.to_dict(include_polar_points=True)
        report = state.record_reports.get(record.airfoil_id, {})
        payload["screening_quality"] = report.get("screening_quality")
        payload["archive_source_quality"] = report.get("archive_source_quality")
        payload["actual_sidecar_query_quality"] = report.get("actual_sidecar_query_quality")
        payload["inclusion_reason"] = report.get("inclusion_reason")
        payload["full_polar_quality"] = report
        records_payload.append(payload)
    db_payload = {
        "schema_version": "full_polar_airfoil_database_v1",
        "source": SOURCE,
        "records": records_payload,
    }
    airfoil_records_json = output_dir / "airfoil_records.json"
    airfoil_records_json.write_text(
        json.dumps(_json_ready(db_payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    airfoil_database_json = output_dir / "airfoil_database.json"
    airfoil_database_json.write_text(airfoil_records_json.read_text(encoding="utf-8"), encoding="utf-8")

    _write_csv(output_dir / "airfoil_records.csv", _record_csv_rows(records_sorted, state.record_reports))
    _write_csv(output_dir / "polar_points.csv", state.polar_rows)
    _write_csv(output_dir / "quality_report.csv", state.quality_rows)
    _write_csv(output_dir / "coverage_report.csv", state.coverage_rows)
    _write_csv(output_dir / "gap_report.csv", state.gap_rows)
    _write_csv(output_dir / "failed_candidates.csv", _failed_candidate_rows(state.quality_rows))

    top_k_rows, pareto_rows = _rank_records_by_zone(
        database,
        state.polar_rows,
        zone_envelopes,
        state.record_reports,
    )
    _write_csv(output_dir / "per_zone_top_k.csv", top_k_rows)
    _write_csv(output_dir / "per_zone_pareto.csv", pareto_rows)

    report = {
        "schema_version": "full_polar_build_report_v1",
        "source": SOURCE,
        "backend": "dry_run" if args.dry_run else args.backend,
        "record_count": len(records_sorted),
        "polar_point_count": len(state.polar_rows),
        "source_quality_counts": _source_quality_counts(records_sorted),
        "records": state.record_reports,
        "args": vars(args),
    }
    report_json = output_dir / "full_polar_build_report.json"
    report_json.write_text(
        json.dumps(_json_ready(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_md = output_dir / "full_polar_build_report.md"
    report_md.write_text(_build_report_markdown(report), encoding="utf-8")
    build_report_json = output_dir / "build_report.json"
    build_report_json.write_text(report_json.read_text(encoding="utf-8"), encoding="utf-8")
    build_report_md = output_dir / "build_report.md"
    build_report_md.write_text(report_md.read_text(encoding="utf-8"), encoding="utf-8")
    return {
        "airfoil_records_json": airfoil_records_json,
        "airfoil_database_json": airfoil_database_json,
        "full_polar_build_report_json": report_json,
        "full_polar_build_report_md": report_md,
        "build_report_json": build_report_json,
        "build_report_md": build_report_md,
    }


def _rank_records_by_zone(
    database: AirfoilDatabase,
    polar_rows: Sequence[Mapping[str, Any]],
    zone_envelopes: Mapping[str, Mapping[str, Any]],
    reports: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    top_rows: list[dict[str, Any]] = []
    pareto_rows: list[dict[str, Any]] = []
    for zone in ZONE_NAMES:
        envelope = zone_envelopes.get(zone, {})
        scored = []
        for record in database.records.values():
            if not _record_matches_zone(record, zone):
                continue
            rows = [
                row
                for row in polar_rows
                if row.get("airfoil_id") == record.airfoil_id
                and _row_is_finite_converged(row)
                and _row_in_envelope(row, envelope)
            ]
            if not rows:
                rows = [
                    row
                    for row in polar_rows
                    if row.get("airfoil_id") == record.airfoil_id and _row_is_finite_converged(row)
                ]
            cds = [float(row["cd"]) for row in rows]
            score = _quality_penalty(record.source_quality) + (float(np.mean(cds)) if cds else 99.0)
            scored.append((score, record, rows))
        for rank, (score, record, rows) in enumerate(sorted(scored, key=lambda item: item[0]), start=1):
            cds = [float(row["cd"]) for row in rows if _finite_float(row.get("cd")) is not None]
            report = reports.get(record.airfoil_id, {})
            row = {
                "zone_name": zone,
                "rank_in_zone": rank,
                "airfoil_id": record.airfoil_id,
                "source_quality": record.source_quality,
                "screening_quality": report.get("screening_quality", ""),
                "archive_source_quality": report.get("archive_source_quality", ""),
                "actual_sidecar_query_quality": report.get("actual_sidecar_query_quality", ""),
                "inclusion_reason": report.get("inclusion_reason", ""),
                "score": score,
                "mean_cd": float(np.mean(cds)) if cds else None,
                "cd_p90": float(np.percentile(cds, 90)) if cds else None,
                "safe_clmax": record.safe_clmax,
                "usable_clmax": record.usable_clmax,
                "alpha_L0_deg": record.alpha_L0_deg,
                "mean_cm": record.cm_design,
            }
            pareto_rows.append(row)
            if rank <= 16:
                top_rows.append(row)
    return top_rows, pareto_rows


def _record_csv_rows(
    records: Sequence[AirfoilRecord],
    reports: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        report = reports.get(record.airfoil_id, {})
        rows.append(
            {
                "airfoil_id": record.airfoil_id,
                "name": record.name,
                "zone_origin": record.zone_hint,
                "source_quality": record.source_quality,
                "screening_quality": report.get("screening_quality"),
                "archive_source_quality": report.get("archive_source_quality"),
                "actual_sidecar_query_quality": report.get("actual_sidecar_query_quality"),
                "repaired_archive_source_quality": report.get("repaired_archive_source_quality"),
                "repaired_actual_sidecar_query_quality": report.get("repaired_actual_sidecar_query_quality"),
                "repair_worthy_flag": report.get("repair_worthy_flag"),
                "inclusion_reason": report.get("inclusion_reason"),
                "source_category": report.get("source_category"),
                "candidate_role": report.get("candidate_role"),
                "generation_index": report.get("generation_index"),
                "thickness_ratio": record.thickness_ratio,
                "max_camber": record.max_camber,
                "alpha_L0_deg": record.alpha_L0_deg,
                "cl_alpha_per_rad": record.cl_alpha_per_rad,
                "cm_design": record.cm_design,
                "safe_clmax": record.safe_clmax,
                "usable_clmax": record.usable_clmax,
                "coordinate_path": record.coordinate_path,
                "polar_point_count": len(record.polar_points),
                "issue_count": report.get("issue_count"),
                "issues": report.get("issues"),
            }
        )
    return rows


def _failed_candidate_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for row in rows:
        source_quality = str(row.get("source_quality") or "")
        issues = str(row.get("issues") or "")
        if source_quality == "full_polar_failed_not_mission_grade" or "worker_exception" in issues:
            failed.append(dict(row))
    return failed


def _coverage_rows(
    candidate: Candidate,
    rows: Sequence[Mapping[str, Any]],
    zone_envelopes: Mapping[str, Mapping[str, Any]],
    quality: Mapping[str, Any],
) -> list[dict[str, Any]]:
    finite_rows = [row for row in rows if _row_is_finite_converged(row)]
    re_values = [float(row["Re"]) for row in finite_rows]
    cl_values = [float(row["cl"]) for row in finite_rows]
    output = []
    for zone in _zones_for_candidate(candidate, zone_envelopes):
        envelope = zone_envelopes.get(zone, {})
        required_cl = _required_zone_cl(envelope)
        output.append(
            {
                "airfoil_id": candidate.airfoil_id,
                "zone_name": zone,
                "re_min_required": _finite_float(envelope.get("re_min")),
                "re_max_required": _finite_float(envelope.get("re_max")),
                "cl_max_required": required_cl,
                "re_min_observed": min(re_values, default=None),
                "re_max_observed": max(re_values, default=None),
                "cl_min_observed": min(cl_values, default=None),
                "cl_max_observed": max(cl_values, default=None),
                "safe_clmax": quality.get("safe_clmax"),
                "coverage_passed": "insufficient" not in str(quality.get("issues", "")),
                "source_quality": quality.get("source_quality"),
                **_candidate_report_metadata(candidate),
            }
        )
    return output


def _gap_rows(candidate: Candidate, quality: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues = [issue for issue in str(quality.get("issues", "")).split(";") if issue]
    return [
        {
            "airfoil_id": candidate.airfoil_id,
            "zone_name": candidate.zone_origin,
            "gap": issue,
            "source_quality": quality.get("source_quality"),
            **_candidate_report_metadata(candidate),
        }
        for issue in issues
        if "insufficient" in issue or "coverage" in issue
    ]


def _zone_coverage_issues(
    candidate: Candidate,
    re_values: Sequence[float],
    cl_values: Sequence[float],
    safe_clmax: float | None,
    zone_envelopes: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    issues: list[str] = []
    for zone in _zones_for_candidate(candidate, zone_envelopes):
        envelope = zone_envelopes.get(zone, {})
        re_min_required = _finite_float(envelope.get("re_min"))
        re_max_required = _finite_float(envelope.get("re_max"))
        required_cl = _required_zone_cl(envelope)
        if re_min_required is not None and (not re_values or min(re_values) > 0.995 * re_min_required):
            issues.append("insufficient_Re_coverage")
        if re_max_required is not None and (not re_values or max(re_values) < 1.005 * re_max_required):
            issues.append("insufficient_Re_coverage")
        if required_cl is not None and (not cl_values or max(cl_values) < required_cl):
            issues.append("insufficient_zone_envelope_Cl_coverage")
        if required_cl is not None and (safe_clmax is None or safe_clmax < required_cl):
            issues.append("insufficient_safe_clmax_margin")
    return list(dict.fromkeys(issues))


def _re_grid_for_candidate(
    candidate: Candidate,
    zone_envelopes: Mapping[str, Mapping[str, Any]],
) -> list[float]:
    values = list(GLOBAL_HPA_RE_GRID)
    for zone in _zones_for_candidate(candidate, zone_envelopes):
        envelope = zone_envelopes.get(zone, {})
        for key in ("re_min", "re_p50", "re_max"):
            value = _finite_float(envelope.get(key))
            if value is not None and value > 0.0:
                values.append(value)
                if key == "re_p50":
                    values.extend([0.85 * value, 1.15 * value])
    return _unique_sorted(values)


def _cl_samples_for_candidate(
    candidate: Candidate,
    zone_envelopes: Mapping[str, Mapping[str, Any]],
) -> list[float]:
    values = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.35]
    for zone in _zones_for_candidate(candidate, zone_envelopes):
        envelope = zone_envelopes.get(zone, {})
        for key in ("cl_min", "cl_p50", "cl_p90", "cl_max", "max_avl_actual_cl", "max_fourier_target_cl"):
            value = _finite_float(envelope.get(key))
            if value is not None:
                values.append(value)
    return _unique_sorted(values)


def _zones_for_candidate(
    candidate: Candidate,
    zone_envelopes: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    zones = [zone for zone in _split_zone_hint(candidate.zone_origin) if zone in zone_envelopes]
    if zones:
        return zones
    zones = [zone for zone in _split_zone_hint(candidate.original_record.zone_hint) if zone in zone_envelopes] if candidate.original_record else []
    if zones:
        return zones
    inferred = _infer_zone_from_id(candidate.airfoil_id)
    return [inferred] if inferred in zone_envelopes else list(zone_envelopes)


def _split_zone_hint(text: str | None) -> list[str]:
    if not text:
        return []
    expanded: list[str] = []
    normalized = str(text).replace("/", ",").replace(";", ",")
    for token in normalized.split(","):
        zone = token.strip()
        if zone == "mid":
            expanded.extend(["mid1", "mid2"])
        elif zone:
            expanded.append(zone)
    return expanded


def _first_zone(text: str | None) -> str | None:
    zones = _split_zone_hint(text)
    return zones[0] if zones else None


def _infer_zone_from_id(airfoil_id: str) -> str:
    text = str(airfoil_id)
    for zone in ZONE_NAMES:
        if f"_{zone}_" in text or text.startswith(f"cst_{zone}_"):
            return zone
    if text in {"fx76mp140", "dae11"}:
        return "root"
    if text == "dae21":
        return "mid1"
    if text in {"clarkysm", "dae31", "dae41"}:
        return "tip"
    return "tip"


def _screening_quality(source_quality: str) -> str:
    if source_quality.startswith("cst_xfoil_mission_grade_candidate"):
        return "target_cl_screening_pass"
    if source_quality.startswith("cst_"):
        return source_quality
    return source_quality or "unknown"


def _record_matches_zone(record: AirfoilRecord, zone: str) -> bool:
    zones = _split_zone_hint(record.zone_hint)
    return zone in zones or not zones


def _row_in_envelope(row: Mapping[str, Any], envelope: Mapping[str, Any]) -> bool:
    re_value = _finite_float(row.get("Re"))
    cl_value = _finite_float(row.get("cl"))
    if re_value is None or cl_value is None:
        return False
    re_min = _finite_float(envelope.get("re_min"))
    re_max = _finite_float(envelope.get("re_max"))
    cl_min = _finite_float(envelope.get("cl_min"))
    cl_max = _required_zone_cl(envelope)
    return (
        (re_min is None or re_value >= 0.95 * re_min)
        and (re_max is None or re_value <= 1.05 * re_max)
        and (cl_min is None or cl_value >= cl_min - 0.1)
        and (cl_max is None or cl_value <= cl_max + 0.1)
    )


def _required_zone_cl(envelope: Mapping[str, Any]) -> float | None:
    values = [
        _finite_float(envelope.get(key))
        for key in ("cl_max", "cl_p90", "max_avl_actual_cl", "max_fourier_target_cl")
    ]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def _row_is_finite_converged(row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("converged"))
        and _finite_float(row.get("Re")) is not None
        and _finite_float(row.get("alpha_deg")) is not None
        and _finite_float(row.get("cl")) is not None
        and _finite_float(row.get("cd")) is not None
        and _finite_float(row.get("cm")) is not None
    )


def _point_warnings(point: Mapping[str, Any], status: str) -> list[str]:
    warnings: list[str] = []
    if status not in {"ok", "dry_run_ok", "mini_sweep_fallback"}:
        warnings.append(status)
    cd = _finite_float(point.get("cd"))
    if cd is None:
        warnings.append("cd_nonfinite")
    elif cd <= 0.0:
        warnings.append("cd_nonpositive")
    if not bool(point.get("converged", False)):
        warnings.append("not_converged")
    return warnings


def _has_cd_discontinuity(rows: Sequence[Mapping[str, Any]]) -> bool:
    grouped: dict[tuple[float, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (float(row["Re"]), str(row["roughness_mode"]))
        grouped.setdefault(key, []).append(row)
    for items in grouped.values():
        sorted_items = sorted(items, key=lambda row: float(row["alpha_deg"]))
        cds = np.asarray([float(row["cd"]) for row in sorted_items], dtype=float)
        if len(cds) >= 3 and float(np.nanmax(np.abs(np.diff(cds)))) > 0.08:
            return True
    return False


def _prestall_branch_valid(rows: Sequence[Mapping[str, Any]]) -> bool:
    grouped: dict[tuple[float, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = (float(row["Re"]), str(row["roughness_mode"]))
        grouped.setdefault(key, []).append(row)
    valid_groups = 0
    for items in grouped.values():
        sorted_items = sorted(items, key=lambda row: float(row["alpha_deg"]))
        cls = np.asarray([float(row["cl"]) for row in sorted_items], dtype=float)
        alphas = np.asarray([float(row["alpha_deg"]) for row in sorted_items], dtype=float)
        mask = (cls >= 0.1) & (cls <= 1.1)
        if int(np.count_nonzero(mask)) < 3:
            continue
        slopes = np.diff(cls[mask]) / np.diff(alphas[mask])
        if np.count_nonzero(slopes > 0.0) >= max(1, int(0.7 * len(slopes))):
            valid_groups += 1
    return valid_groups > 0


def _fit_linear_lift_curve(points: Sequence[AirfoilPolarPoint]) -> tuple[float, float]:
    clean = [point for point in points if point.roughness_mode == "clean"]
    if len(clean) < 2:
        clean = list(points)
    xs = np.asarray([point.alpha_deg for point in clean if math.isfinite(point.alpha_deg)], dtype=float)
    ys = np.asarray([point.cl for point in clean if math.isfinite(point.cl)], dtype=float)
    if len(xs) != len(ys) or len(xs) < 2:
        return -2.0, 2.0 * math.pi
    mask = (ys >= 0.1) & (ys <= 1.1)
    if int(np.count_nonzero(mask)) >= 2:
        xs = xs[mask]
        ys = ys[mask]
    design = np.column_stack([xs, np.ones_like(xs)])
    slope_per_deg, intercept = np.linalg.lstsq(design, ys, rcond=None)[0]
    if abs(float(slope_per_deg)) <= 1.0e-12:
        return -2.0, 2.0 * math.pi
    alpha_l0 = -float(intercept) / float(slope_per_deg)
    return alpha_l0, float(slope_per_deg) * 180.0 / math.pi


def _roughness_sensitivity(rows: Sequence[Mapping[str, Any]]) -> float | None:
    clean = [row for row in rows if str(row.get("roughness_mode")) == "clean"]
    rough = [row for row in rows if str(row.get("roughness_mode")) in {"rough", "dirty"}]
    if not clean or not rough:
        return None
    clean_mean = float(np.mean([float(row["cd"]) for row in clean]))
    rough_mean = float(np.mean([float(row["cd"]) for row in rough]))
    return rough_mean - clean_mean


def _quality_penalty(source_quality: str) -> float:
    if source_quality == "full_polar_mission_grade_candidate":
        return 0.0
    if source_quality == "clean_only_not_full_mission_grade":
        return 0.02
    if source_quality == "full_polar_candidate_not_mission_grade":
        return 0.05
    return 1.0


def _dedupe_candidates(candidates: Sequence[Candidate]) -> list[Candidate]:
    by_id: dict[str, Candidate] = {}
    for candidate in candidates:
        by_id.setdefault(candidate.airfoil_id, candidate)
    return list(by_id.values())


def _float_range(start: float, stop: float, step: float) -> list[float]:
    if step <= 0.0:
        raise ValueError("alpha step must be positive.")
    count = int(math.floor((stop - start) / step + 0.5)) + 1
    return [round(start + step * index, 6) for index in range(max(count, 1))]


def _parse_csv_arg(text: str) -> list[str]:
    values = [item.strip() for item in str(text).split(",") if item.strip()]
    return values or ["clean"]


def _unique_sorted(values: Iterable[float]) -> list[float]:
    return sorted({round(float(value), 6) for value in values if math.isfinite(float(value))})


def _finite_float(value: Any) -> float | None:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(output):
        return None
    return output


def _source_quality_counts(records: Sequence[AirfoilRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.source_quality] = counts.get(record.source_quality, 0) + 1
    return counts


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["empty"])
        writer.writeheader()
        for row in rows:
            writer.writerow(_json_ready(dict(row)))


def _build_report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Full Polar Airfoil Archive Build Report",
        "",
        f"- Source: {report.get('source')}",
        f"- Backend: {report.get('backend')}",
        f"- Record count: {report.get('record_count')}",
        f"- Polar point count: {report.get('polar_point_count')}",
        f"- Source quality counts: `{report.get('source_quality_counts')}`",
        "",
        "## Records",
        "",
    ]
    records = report.get("records", {})
    if isinstance(records, Mapping):
        for airfoil_id, item in records.items():
            if not isinstance(item, Mapping):
                continue
            lines.append(
                "- "
                f"{airfoil_id}: {item.get('source_quality')}, "
                f"mission_grade_allowed={item.get('mission_grade_allowed')}, "
                f"pass_rate={float(item.get('convergence_pass_rate') or 0.0):.3f}, "
                f"safe_clmax={item.get('safe_clmax')}, "
                f"issues={item.get('issues')}"
            )
    lines.extend(
        [
            "",
            "Screening-grade CST results remain screening evidence. Only real XFOIL/JXFoil "
            "full-alpha sweeps that pass coverage and quality checks are labeled "
            "`full_polar_mission_grade_candidate`.",
            "",
        ]
    )
    return "\n".join(lines)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
