from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys
import yaml

from .schema import MeshJobConfig, BatchManifest
from .pipeline import run_job, validate_geometry_only


def _load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_run(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.config))
    raw["component"] = args.component or raw.get("component")
    raw["geometry"] = args.geometry or raw.get("geometry")
    raw["geometry_provider"] = args.geometry_provider or raw.get("geometry_provider")
    raw["out_dir"] = args.out or raw.get("out_dir")
    config = MeshJobConfig.model_validate(raw)
    result = run_job(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_validate_geometry(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.config)) if args.config else {}
    raw["component"] = args.component or raw.get("component")
    raw["geometry"] = args.geometry or raw.get("geometry")
    raw["geometry_provider"] = args.geometry_provider or raw.get("geometry_provider")
    raw["out_dir"] = args.out or raw.get("out_dir", "out/validate")
    config = MeshJobConfig.model_validate(raw)
    result = validate_geometry_only(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_batch(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.manifest))
    manifest = BatchManifest.model_validate(raw)
    results = [run_job(job) for job in manifest.jobs]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r.get("status") == "success" for r in results) else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hpa-mesh")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--component", type=str)
    run.add_argument("--geometry", type=str)
    run.add_argument("--geometry-provider", type=str)
    run.add_argument("--config", type=str, required=True)
    run.add_argument("--out", type=str)
    run.set_defaults(func=cmd_run)

    val = sub.add_parser("validate-geometry")
    val.add_argument("--component", type=str, required=True)
    val.add_argument("--geometry", type=str, required=True)
    val.add_argument("--geometry-provider", type=str)
    val.add_argument("--config", type=str)
    val.add_argument("--out", type=str)
    val.set_defaults(func=cmd_validate_geometry)

    batch = sub.add_parser("batch")
    batch.add_argument("--manifest", type=str, required=True)
    batch.set_defaults(func=cmd_batch)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
