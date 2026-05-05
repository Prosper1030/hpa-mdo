#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from hpa_mdo.airfoils.cst_database_builder import (  # noqa: E402
    CSTZoneSearchConfig,
    build_cst_zone_airfoil_database,
)
from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker  # noqa: E402


class DryRunWorker:
    backend_name = "dry_run_xfoil_surrogate"

    def run_queries(self, queries):
        results = []
        for query in queries:
            points = []
            rough_penalty = 0.003 if query.roughness_mode != "clean" else 0.0
            for cl in query.cl_samples:
                cl_value = float(cl)
                points.append(
                    {
                        "alpha_deg": -2.0 + 8.4 * cl_value,
                        "cl": cl_value,
                        "cd": 0.011 + rough_penalty + 0.006 * (cl_value - 0.75) ** 2,
                        "cm": -0.07,
                        "converged": True,
                    }
                )
            results.append(
                {
                    "template_id": query.template_id,
                    "reynolds": query.reynolds,
                    "cl_samples": list(query.cl_samples),
                    "roughness_mode": query.roughness_mode,
                    "geometry_hash": query.geometry_hash,
                    "analysis_mode": query.analysis_mode,
                    "analysis_stage": query.analysis_stage,
                    "status": "stubbed_ok",
                    "polar_points": points,
                    "sweep_summary": {
                        "converged_point_count": len(points),
                        "sweep_point_count": len(points),
                        "cl_max_observed": max(query.cl_samples) if points else None,
                    },
                }
            )
        return results


def _float_tuple(text: str) -> tuple[float, ...]:
    if not text.strip():
        return tuple()
    return tuple(float(item.strip()) for item in text.split(",") if item.strip())


def _str_tuple(text: str) -> tuple[str, ...]:
    if not text.strip():
        return tuple()
    return tuple(item.strip() for item in text.split(",") if item.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an offline zone-specific CST/XFOIL airfoil database."
    )
    parser.add_argument("--zone-envelope-json", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "output" / "airfoil_db" / "overnight_cst_zone_search",
    )
    parser.add_argument("--backend", choices=("julia", "dry-run"), default="julia")
    parser.add_argument("--population-size-per-zone", type=int, default=128)
    parser.add_argument("--generations", type=int, default=8)
    parser.add_argument("--nsga-parent-count", type=int, default=64)
    parser.add_argument("--mutation-scale", type=float, default=0.06)
    parser.add_argument(
        "--sample-count-per-zone",
        type=int,
        default=None,
        help="Deprecated alias for --population-size-per-zone.",
    )
    parser.add_argument("--coarse-score-count", type=int, default=96)
    parser.add_argument("--robust-score-count", type=int, default=24)
    parser.add_argument("--top-k-per-zone", type=int, default=8)
    parser.add_argument("--re-robustness-factors", default="0.85,1.0,1.15")
    parser.add_argument("--roughness-modes", default="clean,rough")
    parser.add_argument("--panel-count", type=int, default=96)
    parser.add_argument("--xfoil-max-iter", type=int, default=40)
    parser.add_argument("--convergence-pass-rate-threshold", type=float, default=0.80)
    parser.add_argument("--required-stall-margin-cl", type=float, default=0.03)
    parser.add_argument("--cl-coverage-margin", type=float, default=0.25)
    parser.add_argument("--random-seed", type=int, default=17)
    parser.add_argument("--max-oversample-factor", type=int, default=8)
    parser.add_argument("--julia-worker-count", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config = CSTZoneSearchConfig(
        population_size_per_zone=int(args.population_size_per_zone),
        generations=int(args.generations),
        nsga_parent_count=int(args.nsga_parent_count),
        mutation_scale=float(args.mutation_scale),
        sample_count_per_zone=(
            None if args.sample_count_per_zone is None else int(args.sample_count_per_zone)
        ),
        coarse_score_count=int(args.coarse_score_count),
        robust_score_count=int(args.robust_score_count),
        top_k_per_zone=int(args.top_k_per_zone),
        re_robustness_factors=_float_tuple(args.re_robustness_factors),
        roughness_modes=_str_tuple(args.roughness_modes),
        panel_count=int(args.panel_count),
        xfoil_max_iter=int(args.xfoil_max_iter),
        convergence_pass_rate_threshold=float(args.convergence_pass_rate_threshold),
        required_stall_margin_cl=float(args.required_stall_margin_cl),
        cl_coverage_margin=float(args.cl_coverage_margin),
        random_seed=int(args.random_seed),
        max_oversample_factor=int(args.max_oversample_factor),
    )
    worker = None
    if args.backend == "dry-run":
        worker = DryRunWorker()
    else:
        worker = JuliaXFoilWorker(
            project_dir=REPO_ROOT,
            cache_dir=output_dir / ".cache" / "julia_xfoil_worker",
            persistent_worker_count=args.julia_worker_count,
            xfoil_max_iter=int(config.xfoil_max_iter),
            xfoil_panel_count=int(config.panel_count),
        )
    try:
        def progress(event: dict[str, object]) -> None:
            print(json.dumps(event, sort_keys=True), flush=True)

        result = build_cst_zone_airfoil_database(
            zone_envelope_path=Path(args.zone_envelope_json),
            output_dir=output_dir,
            config=config,
            worker=worker,
            progress_callback=progress,
        )
    finally:
        close = getattr(worker, "close", None)
        if callable(close):
            close()
    print(
        json.dumps(
            {
                "airfoil_database_json": str(result.paths["airfoil_database_json"]),
                "airfoil_database_csv": str(result.paths["airfoil_database_csv"]),
                "build_report_json": str(result.paths["build_report_json"]),
                "build_report_md": str(result.paths["build_report_md"]),
                "source_quality_counts": result.report["source_quality_counts"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
