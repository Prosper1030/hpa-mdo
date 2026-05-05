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

from hpa_mdo.airfoils.polar_builder import (  # noqa: E402
    PolarBuildConfig,
    build_seed_airfoil_database,
    seed_airfoil_specs,
    write_polar_build_artifacts,
)
from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker  # noqa: E402


def _float_tuple(text: str) -> tuple[float, ...]:
    if not text.strip():
        return tuple()
    return tuple(float(item.strip()) for item in text.split(",") if item.strip())


def _str_tuple(text: str) -> tuple[str, ...]:
    if not text.strip():
        return tuple()
    return tuple(item.strip() for item in text.split(",") if item.strip())


def _load_zone_envelopes(path: Path | None) -> list[dict]:
    if path is None:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("zone_envelope", payload.get("zone_envelopes", []))
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
    raise ValueError("Zone envelope JSON must be a list or contain zone_envelope rows.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build seed-airfoil polar database artifacts for the Birdman sidecar route."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "output" / "airfoil_polars" / "seed_airfoils",
    )
    parser.add_argument(
        "--backend",
        choices=("julia", "dry-run"),
        default="julia",
        help="Use julia for real XFoil.jl runs, or dry-run for deterministic CI artifacts.",
    )
    parser.add_argument(
        "--airfoil-id",
        action="append",
        default=None,
        help="Limit to one or more seed airfoils. Defaults to all seed airfoils.",
    )
    parser.add_argument("--re-grid", default=None, help="Comma-separated Reynolds grid.")
    parser.add_argument("--cl-grid", default=None, help="Comma-separated Cl sample grid.")
    parser.add_argument(
        "--roughness-modes",
        default="clean,rough",
        help="Comma-separated roughness modes, usually clean,rough.",
    )
    parser.add_argument(
        "--re-robustness-factors",
        default="0.85,1.0,1.15",
        help="Comma-separated Re multipliers used when deriving grid from zone envelopes.",
    )
    parser.add_argument("--xfoil-max-iter", type=int, default=80)
    parser.add_argument("--panel-count", type=int, default=120)
    parser.add_argument("--timeout-s", type=float, default=60.0)
    parser.add_argument("--convergence-pass-rate-threshold", type=float, default=0.80)
    parser.add_argument(
        "--zone-envelope-json",
        type=Path,
        default=None,
        help="Optional Phase 4 zone_envelope.json or raw zone envelope list.",
    )
    parser.add_argument(
        "--julia-worker-count",
        type=int,
        default=None,
        help="Persistent Julia/XFoil worker count when --backend=julia.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_kwargs = {
        "roughness_modes": _str_tuple(args.roughness_modes),
        "re_robustness_factors": _float_tuple(args.re_robustness_factors),
        "xfoil_max_iter": int(args.xfoil_max_iter),
        "panel_count": int(args.panel_count),
        "timeout_s": float(args.timeout_s),
        "convergence_pass_rate_threshold": float(args.convergence_pass_rate_threshold),
    }
    if args.re_grid is not None:
        config_kwargs["re_grid"] = _float_tuple(args.re_grid)
    if args.cl_grid is not None:
        config_kwargs["cl_grid"] = _float_tuple(args.cl_grid)
    config = PolarBuildConfig(**config_kwargs)

    specs = seed_airfoil_specs()
    if args.airfoil_id:
        requested = {str(airfoil_id) for airfoil_id in args.airfoil_id}
        missing = sorted(requested - set(specs))
        if missing:
            raise SystemExit(f"Unknown seed airfoil ids: {', '.join(missing)}")
        specs = {airfoil_id: specs[airfoil_id] for airfoil_id in specs if airfoil_id in requested}

    output_dir = Path(args.output_dir).expanduser().resolve()
    cache_dir = output_dir / ".cache"
    zone_envelopes = _load_zone_envelopes(args.zone_envelope_json)
    worker = None
    backend = "dry_run" if args.backend == "dry-run" else "worker"
    if args.backend == "julia":
        worker = JuliaXFoilWorker(
            project_dir=REPO_ROOT,
            cache_dir=cache_dir / "julia_xfoil_worker",
            persistent_worker_count=args.julia_worker_count,
            xfoil_max_iter=int(config.xfoil_max_iter),
            xfoil_panel_count=int(config.panel_count),
        )
    try:
        result = build_seed_airfoil_database(
            config=config,
            airfoil_specs=specs,
            zone_envelopes=zone_envelopes,
            backend=backend,
            worker=worker,
            cache_dir=cache_dir / "polar_builder",
        )
    finally:
        if worker is not None:
            worker.close()
    paths = write_polar_build_artifacts(result, output_dir)
    print(
        json.dumps(
            {
                "airfoil_database_json": str(paths["airfoil_database_json"]),
                "airfoil_database_csv": str(paths["airfoil_database_csv"]),
                "build_report_json": str(paths["build_report_json"]),
                "build_report_md": str(paths["build_report_md"]),
                "source_quality_counts": result.report["source_quality_counts"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
