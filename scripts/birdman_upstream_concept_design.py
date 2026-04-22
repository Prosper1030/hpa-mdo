#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


from hpa_mdo.concept.pipeline import run_birdman_concept_pipeline  # noqa: E402


def _cli_spanwise_loader(concept, stations):
    zones = ("root", "mid1", "mid2", "tip")
    if not stations:
        return {zone: {"points": []} for zone in zones}

    payload = {zone: {"points": []} for zone in zones}
    for index, station in enumerate(stations):
        zone = zones[min(index * len(zones) // len(stations), len(zones) - 1)]
        payload[zone]["points"].append(
            {
                "reynolds": 260000.0 + 5000.0 * index,
                "cl_target": max(0.5, 0.70 - 0.015 * index),
                "cm_target": -0.10 + 0.01 * index,
                "weight": 1.0,
                "station_y_m": station.y_m,
            }
        )
    return payload


def _cli_airfoil_worker_factory(**kwargs):
    class _FakeWorker:
        backend_name = "cli_stubbed"

        def run_queries(self, queries):
            return [
                {
                    "template_id": query.template_id,
                    "reynolds": query.reynolds,
                    "cl_samples": list(query.cl_samples),
                    "roughness_mode": query.roughness_mode,
                    "status": "cli_stubbed",
                }
                for query in queries
            ]

    return _FakeWorker()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Birdman upstream concept design smoke.")
    parser.add_argument("--config", required=True, help="Path to the concept YAML config.")
    parser.add_argument("--output-dir", required=True, help="Directory for generated artifacts.")
    args = parser.parse_args()

    run_birdman_concept_pipeline(
        config_path=Path(args.config).expanduser().resolve(),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        airfoil_worker_factory=_cli_airfoil_worker_factory,
        spanwise_loader=_cli_spanwise_loader,
    )


if __name__ == "__main__":
    main()
