#!/usr/bin/env python3
"""Standalone shadow-mode mission drag budget evaluator.

Reads an existing concept_ranked_pool.json, attaches drag budget evaluation
to every candidate, and writes:

    <output-dir>/mission_drag_budget_shadow.csv
    <output-dir>/mission_drag_budget_shadow_summary.json

This script never modifies the ranked pool or any pipeline outputs.  It is
safe to run at any time after a concept pipeline run completes.

Usage example
-------------
    python scripts/run_mission_drag_budget_shadow_on_candidates.py \\
        --ranked-pool output/birdman_oswald_fourier_smoke_20260502/concept_ranked_pool.json \\
        --budget-config configs/mission_drag_budget_example.yaml \\
        --output-dir output/birdman_oswald_fourier_smoke_20260502
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from hpa_mdo.mission.drag_budget_shadow import (  # noqa: E402
    SHADOW_CSV_FILENAME,
    SHADOW_SUMMARY_JSON_FILENAME,
    run_shadow_on_ranked_pool_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Shadow-mode mission drag budget evaluation on concept candidates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--ranked-pool",
        required=True,
        type=Path,
        help="Path to concept_ranked_pool.json produced by the concept pipeline.",
    )
    parser.add_argument(
        "--budget-config",
        default=str(REPO_ROOT / "configs" / "mission_drag_budget_example.yaml"),
        type=Path,
        help="Path to the mission_drag_budget YAML config. "
        "Defaults to configs/mission_drag_budget_example.yaml.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for shadow files. Defaults to the same directory as --ranked-pool.",
    )
    parser.add_argument(
        "--reserve-mode",
        choices=("target", "boundary"),
        default="target",
        help="Which CDA_nonwing reserve to use for CD0_total estimation (default: target).",
    )
    parser.add_argument(
        "--no-auto-rider-curve",
        action="store_true",
        help="Disable automatic rider curve loading from the concept config. "
        "When set, mission power margin will be None for all candidates.",
    )
    args = parser.parse_args()

    ranked_pool_path = args.ranked_pool.expanduser().resolve()
    if not ranked_pool_path.exists():
        print(f"[error] ranked-pool not found: {ranked_pool_path}", file=sys.stderr)
        return 1

    budget_config_path = args.budget_config.expanduser().resolve()
    if not budget_config_path.exists():
        print(f"[error] budget-config not found: {budget_config_path}", file=sys.stderr)
        return 1

    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else ranked_pool_path.parent
    )

    print(f"[shadow] ranked pool  : {ranked_pool_path}")
    print(f"[shadow] budget config: {budget_config_path}")
    print(f"[shadow] output dir   : {output_dir}")
    print(f"[shadow] reserve mode : {args.reserve_mode}")
    print(f"[shadow] auto rider   : {not args.no_auto_rider_curve}")

    summary = run_shadow_on_ranked_pool_json(
        ranked_pool_json_path=ranked_pool_path,
        budget_config_path=budget_config_path,
        output_dir=output_dir,
        reserve_mode=args.reserve_mode,
        auto_load_rider_curve=not args.no_auto_rider_curve,
    )

    csv_path = output_dir / SHADOW_CSV_FILENAME
    summary_path = output_dir / SHADOW_SUMMARY_JSON_FILENAME

    print()
    print(f"[shadow] total candidates     : {summary['total_candidates']}")
    print(f"[shadow] evaluated            : {summary['evaluated_candidates']}")
    print(f"[shadow] missing inputs       : {summary['missing_input_candidates']}")
    print(f"[shadow] count by band        : {summary['count_by_drag_budget_band']}")
    print(f"[shadow] power passed         : {summary['count_power_passed']}")
    print(f"[shadow] robust passed        : {summary['count_robust_passed']}")
    print(f"[shadow] best cd0_total_est   : {summary.get('best_cd0_total_est')}")
    print(f"[shadow] best margin cand     : {summary.get('best_margin_candidate_id')}")
    print()
    print(f"[shadow] output CSV    → {csv_path}")
    print(f"[shadow] output summary→ {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
