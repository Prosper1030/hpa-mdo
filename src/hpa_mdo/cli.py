"""Console entry point for the HPA optimization pipeline."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_run_optimization_module():
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "run_optimization.py"
    spec = importlib.util.spec_from_file_location(
        "hpa_mdo._run_optimization_script",
        script_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load optimization script: {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    module = _load_run_optimization_module()
    module.cli()
