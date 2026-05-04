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
from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker  # noqa: E402
from hpa_mdo.concept.avl_loader import build_avl_backed_spanwise_loader  # noqa: E402
from hpa_mdo.concept.config import load_concept_config  # noqa: E402
from hpa_mdo.mission.drag_budget_shadow import (  # noqa: E402
    SHADOW_CSV_FILENAME,
    SHADOW_SUMMARY_JSON_FILENAME,
    run_shadow_on_ranked_pool_json,
)


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
            results = []
            for query in queries:
                is_nsga_child = "nsga2_" in query.template_id
                mean_cd = 0.0105 if is_nsga_child else 0.0120
                mean_cm = -0.055
                usable_clmax = 1.45 if is_nsga_child else 1.35
                polar_points = [
                    {
                        "cl": float(cl),
                        "cd": mean_cd + 0.002 * (float(cl) - 0.70) ** 2,
                        "cm": mean_cm,
                    }
                    for cl in query.cl_samples
                ]
                results.append(
                    {
                        "template_id": query.template_id,
                        "reynolds": query.reynolds,
                        "cl_samples": list(query.cl_samples),
                        "roughness_mode": query.roughness_mode,
                        "status": "stubbed_ok",
                        "mean_cd": mean_cd,
                        "mean_cm": mean_cm,
                        "usable_clmax": usable_clmax,
                        "polar_points": polar_points,
                    }
                )
            return results

    return _FakeWorker()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Birdman upstream concept design smoke.")
    parser.add_argument("--config", required=True, help="Path to the concept YAML config.")
    parser.add_argument("--output-dir", required=True, help="Directory for generated artifacts.")
    parser.add_argument(
        "--worker-mode",
        choices=("julia", "stubbed"),
        default="julia",
        help="Choose the airfoil-worker backend for the concept smoke run.",
    )
    parser.add_argument(
        "--julia-worker-count",
        type=int,
        default=None,
        help="Override the persistent Julia/XFoil worker count for this run.",
    )
    parser.add_argument(
        "--enable-mission-drag-budget-shadow",
        action="store_true",
        help="After the pipeline completes, run shadow-mode mission drag budget "
        "evaluation on all candidates and write mission_drag_budget_shadow.csv "
        "and mission_drag_budget_shadow_summary.json to the output directory.",
    )
    parser.add_argument(
        "--drag-budget-config",
        default=str(REPO_ROOT / "configs" / "mission_drag_budget_example.yaml"),
        help="Path to the mission_drag_budget YAML config for shadow evaluation. "
        "Only used when --enable-mission-drag-budget-shadow is set.",
    )
    args = parser.parse_args()

    airfoil_worker_factory = (
        JuliaXFoilWorker if args.worker_mode == "julia" else _cli_airfoil_worker_factory
    )
    cfg = load_concept_config(Path(args.config).expanduser().resolve())
    spanwise_loader = build_avl_backed_spanwise_loader(
        cfg=cfg,
        working_root=Path(args.output_dir).expanduser().resolve() / "avl_cases",
        fallback_loader=_cli_spanwise_loader,
    )

    output_dir = Path(args.output_dir).expanduser().resolve()
    run_birdman_concept_pipeline(
        config_path=Path(args.config).expanduser().resolve(),
        output_dir=output_dir,
        airfoil_worker_factory=airfoil_worker_factory,
        spanwise_loader=spanwise_loader,
        polar_worker_count_override=args.julia_worker_count,
    )

    if args.enable_mission_drag_budget_shadow:
        ranked_pool_path = output_dir / "concept_ranked_pool.json"
        budget_config_path = Path(args.drag_budget_config).expanduser().resolve()
        if not ranked_pool_path.exists():
            print(
                f"[shadow] WARNING: ranked pool not found at {ranked_pool_path}, "
                "skipping shadow evaluation.",
                file=sys.stderr,
            )
        elif not budget_config_path.exists():
            print(
                f"[shadow] WARNING: budget config not found at {budget_config_path}, "
                "skipping shadow evaluation.",
                file=sys.stderr,
            )
        else:
            print(f"[shadow] Running mission drag budget shadow evaluation…")
            try:
                summary = run_shadow_on_ranked_pool_json(
                    ranked_pool_json_path=ranked_pool_path,
                    budget_config_path=budget_config_path,
                    output_dir=output_dir,
                )
                print(
                    f"[shadow] evaluated {summary['evaluated_candidates']}/"
                    f"{summary['total_candidates']} candidates, "
                    f"bands={summary['count_by_drag_budget_band']}"
                )
                print(f"[shadow] → {output_dir / SHADOW_CSV_FILENAME}")
                print(f"[shadow] → {output_dir / SHADOW_SUMMARY_JSON_FILENAME}")
            except Exception as exc:
                print(f"[shadow] ERROR during shadow evaluation: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
