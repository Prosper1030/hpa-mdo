#!/usr/bin/env python3
"""Screen the current pathfinder tail contract v0 without solving trim."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from hpa_mdo.aero.tail_contract import screen_tail_contract


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/current_pathfinder_tail_contract_v0.yaml"),
        help="Tail contract YAML to screen.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("docs/reports/2026-05-09_tail_contract_v0_screening.json"),
        help="JSON screening artifact to write.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8")) or {}
    if not isinstance(contract, dict):
        raise TypeError("tail contract YAML must contain a mapping at the top level.")

    result: dict[str, Any] = screen_tail_contract(contract)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {args.output_json}")
    print(f"status: {result['status']}")


if __name__ == "__main__":
    main()
