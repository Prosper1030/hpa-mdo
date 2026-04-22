from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable, Protocol

from hpa_mdo.concept.airfoil_worker import PolarQuery
from hpa_mdo.concept.config import BirdmanConceptConfig, load_concept_config
from hpa_mdo.concept.geometry import (
    GeometryConcept,
    WingStation,
    build_linear_wing_stations,
    enumerate_geometry_concepts,
)
from hpa_mdo.concept.handoff import write_selected_concept_bundle


class SpanwiseLoadLoader(Protocol):
    def __call__(
        self, concept: GeometryConcept, stations: tuple[WingStation, ...]
    ) -> dict[str, dict[str, Any]]:
        ...


class AirfoilWorker(Protocol):
    def run_queries(self, queries: list[PolarQuery]) -> list[dict[str, object]]:
        ...


AirfoilWorkerFactory = Callable[..., AirfoilWorker]


@dataclass(frozen=True)
class ConceptPipelineResult:
    summary_json_path: Path
    selected_concept_dirs: tuple[Path, ...]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_spanwise_loader(
    concept: GeometryConcept, stations: tuple[WingStation, ...]
) -> dict[str, dict[str, Any]]:
    zones = ("root", "mid1", "mid2", "tip")
    if not stations:
        return {zone: {"points": []} for zone in zones}

    zone_payload: dict[str, dict[str, Any]] = {zone: {"points": []} for zone in zones}
    for index, station in enumerate(stations):
        zone = zones[min(index * len(zones) // len(stations), len(zones) - 1)]
        zone_payload[zone]["points"].append(
            {
                "reynolds": 250000.0 + 10000.0 * index,
                "cl_target": max(0.5, 0.72 - 0.02 * index),
                "cm_target": -0.10 + 0.01 * index,
                "weight": 1.0,
                "station_y_m": station.y_m,
            }
        )
    return zone_payload


def _default_airfoil_worker_factory(**_: Any) -> AirfoilWorker:
    class _NoopWorker:
        backend_name = "python_stubbed"

        def run_queries(self, queries: list[PolarQuery]) -> list[dict[str, object]]:
            return [
                {
                    "template_id": query.template_id,
                    "reynolds": query.reynolds,
                    "cl_samples": list(query.cl_samples),
                    "roughness_mode": query.roughness_mode,
                    "status": "stubbed_ok",
                }
                for query in queries
            ]

    return _NoopWorker()


def _worker_backend(worker: AirfoilWorker) -> str:
    return str(getattr(worker, "backend_name", "python_stubbed"))


def _worker_statuses(worker_results: list[dict[str, object]]) -> tuple[str, ...]:
    statuses: list[str] = []
    for result in worker_results:
        status = result.get("status")
        statuses.append("unknown" if status is None else str(status))
    return tuple(statuses)


def _concept_to_bundle_payload(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    stations: tuple[WingStation, ...],
    zone_requirements: dict[str, dict[str, Any]],
    worker_results: list[dict[str, object]],
    worker_backend: str,
    concept_index: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    concept_config = cfg.model_dump(mode="python")
    concept_config["geometry"] = {
        "span_m": concept.span_m,
        "wing_area_m2": concept.wing_area_m2,
        "root_chord_m": concept.root_chord_m,
        "tip_chord_m": concept.tip_chord_m,
        "twist_root_deg": concept.twist_root_deg,
        "twist_tip_deg": concept.twist_tip_deg,
        "dihedral_root_deg": concept.dihedral_root_deg,
        "dihedral_tip_deg": concept.dihedral_tip_deg,
        "dihedral_exponent": concept.dihedral_exponent,
        "tail_area_m2": concept.tail_area_m2,
        "cg_xc": concept.cg_xc,
        "segment_lengths_m": list(concept.segment_lengths_m),
    }

    stations_rows = [
        {
            "y_m": station.y_m,
            "chord_m": station.chord_m,
            "twist_deg": station.twist_deg,
            "dihedral_deg": station.dihedral_deg,
        }
        for station in stations
    ]
    airfoil_templates = {
        zone_name: {
            "template_id": f"{zone_name}-seed",
            "points": zone_data.get("points", []),
            "point_count": len(zone_data.get("points", [])),
        }
        for zone_name, zone_data in zone_requirements.items()
    }
    lofting_guides = {
        "authority": "cst_coefficients",
        "stations_per_half": len(stations),
        "zone_names": list(zone_requirements.keys()),
        "interpolation_rule": "linear_in_coeff_space",
    }
    prop_assumption = {
        "blade_count": cfg.prop.blade_count,
        "diameter_m": cfg.prop.diameter_m,
        "rpm_range": [cfg.prop.rpm_min, cfg.prop.rpm_max],
        "position_mode": cfg.prop.position_mode,
        "mode": "simplified",
    }
    worker_statuses = _worker_statuses(worker_results)
    concept_summary = {
        "selected": True,
        "concept_id": f"concept-{concept_index:02d}",
        "rank": concept_index,
        "span_m": concept.span_m,
        "wing_area_m2": concept.wing_area_m2,
        "station_count": len(stations),
        "zone_count": len(zone_requirements),
        "worker_result_count": len(worker_results),
        "worker_backend": worker_backend,
        "worker_statuses": list(worker_statuses),
        "launch": {"status": "stubbed_ok"},
        "turn": {"status": "stubbed_ok"},
        "trim": {"status": "stubbed_ok"},
        "local_stall": {"status": "stubbed_ok"},
    }
    return (
        concept_config,
        stations_rows,
        airfoil_templates,
        lofting_guides,
        prop_assumption,
        concept_summary,
    )


def run_birdman_concept_pipeline(
    *,
    config_path: Path,
    output_dir: Path,
    airfoil_worker_factory: AirfoilWorkerFactory = _default_airfoil_worker_factory,
    spanwise_loader: SpanwiseLoadLoader = _default_spanwise_loader,
) -> ConceptPipelineResult:
    cfg = load_concept_config(config_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    concepts = enumerate_geometry_concepts(cfg)[: cfg.pipeline.keep_top_n]
    if len(concepts) < 3:
        raise RuntimeError("Birdman concept enumeration must yield at least 3 candidate concepts.")

    repo_root = _repo_root()
    worker = airfoil_worker_factory(project_dir=repo_root, cache_dir=output_dir / "polar_db")
    worker_backend = _worker_backend(worker)

    selected_concept_dirs: list[Path] = []
    summary_records: list[dict[str, Any]] = []
    summary_worker_statuses: list[str] = []

    for concept_index, concept in enumerate(concepts, start=1):
        stations = build_linear_wing_stations(
            concept,
            stations_per_half=cfg.pipeline.stations_per_half,
        )
        zone_requirements = spanwise_loader(concept, stations)
        worker_queries: list[PolarQuery] = []
        for zone_name, zone_data in zone_requirements.items():
            for point_index, point in enumerate(zone_data.get("points", []), start=1):
                worker_queries.append(
                    PolarQuery(
                        template_id=f"{zone_name}-template-{point_index:02d}",
                        reynolds=float(point["reynolds"]),
                        cl_samples=(float(point["cl_target"]),),
                        roughness_mode="clean",
                    )
                )

        worker_results = worker.run_queries(worker_queries)
        (
            concept_config,
            stations_rows,
            airfoil_templates,
            lofting_guides,
            prop_assumption,
            concept_summary,
        ) = _concept_to_bundle_payload(
            cfg=cfg,
            concept=concept,
            stations=stations,
            zone_requirements=zone_requirements,
            worker_results=worker_results,
            worker_backend=worker_backend,
            concept_index=concept_index,
        )
        concept_worker_statuses = list(concept_summary["worker_statuses"])
        summary_worker_statuses.extend(concept_worker_statuses)

        bundle_dir = write_selected_concept_bundle(
            output_dir=output_dir / "selected_concepts",
            concept_id=concept_summary["concept_id"],
            concept_config=concept_config,
            stations_rows=stations_rows,
            airfoil_templates=airfoil_templates,
            lofting_guides=lofting_guides,
            prop_assumption=prop_assumption,
            concept_summary=concept_summary,
            export_vsp=(
                cfg.output.export_vsp and concept_index <= cfg.output.export_vsp_for_top_n
            ),
        )
        selected_concept_dirs.append(bundle_dir)
        summary_records.append(
            {
                "concept_id": concept_summary["concept_id"],
                "bundle_dir": str(bundle_dir),
                "span_m": concept.span_m,
                "wing_area_m2": concept.wing_area_m2,
                "zone_count": len(zone_requirements),
                "worker_result_count": len(worker_results),
                "worker_backend": worker_backend,
                "worker_statuses": concept_worker_statuses,
            }
        )

    summary_json_path = output_dir / "concept_summary.json"
    summary_json_path.write_text(
        json.dumps(
            {
                "config_path": str(Path(config_path)),
                "worker_backend": worker_backend,
                "worker_statuses": summary_worker_statuses,
                "selected_concepts": summary_records,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return ConceptPipelineResult(
        summary_json_path=summary_json_path,
        selected_concept_dirs=tuple(selected_concept_dirs),
    )
