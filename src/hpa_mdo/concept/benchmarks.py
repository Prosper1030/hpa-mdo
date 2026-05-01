from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_HPA_BENCHMARK_PATH = _REPO_ROOT / "data" / "reference_aircraft" / "hpa_benchmarks.yaml"


def _value(payload: dict[str, Any], *path: str) -> float:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise ValueError(f"Missing benchmark field: {'.'.join(path)}")
        node = node[key]
    if isinstance(node, dict):
        node = node.get("value")
    try:
        return float(node)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Benchmark field is not numeric: {'.'.join(path)}") from exc


def _validate_sources(benchmark_id: str, benchmark: dict[str, Any]) -> None:
    sources = benchmark.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError(f"Benchmark {benchmark_id!r} must define at least one source.")
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError(f"Benchmark {benchmark_id!r} has a non-dict source entry.")
        source_id = str(source.get("id", "")).strip()
        if not source_id:
            raise ValueError(f"Benchmark {benchmark_id!r} has a source without id.")
        if source_id in seen:
            raise ValueError(f"Benchmark {benchmark_id!r} repeats source id {source_id!r}.")
        seen.add(source_id)
        url = str(source.get("url", "")).strip()
        if not url.startswith(("https://", "http://")):
            raise ValueError(f"Benchmark {benchmark_id!r} source {source_id!r} has no URL.")


def _add_derived_fields(benchmark: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(benchmark)
    span_m = _value(result, "geometry", "span_m")
    wing_area_m2 = _value(result, "geometry", "wing_area_m2")
    total_mass_kg = _value(result, "mass", "total_mass_kg")
    derived = dict(result.get("derived", {}))
    derived["aspect_ratio"] = span_m**2 / wing_area_m2
    derived["wing_loading_Npm2"] = total_mass_kg * 9.80665 / wing_area_m2
    result["derived"] = derived
    return result


def load_hpa_reference_benchmarks(
    path: Path | str = DEFAULT_HPA_BENCHMARK_PATH,
) -> dict[str, dict[str, Any]]:
    """Load HPA reference aircraft benchmark data with derived SI quantities."""

    benchmark_path = Path(path)
    payload = yaml.safe_load(benchmark_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"HPA benchmark file must contain a mapping: {benchmark_path}")
    if payload.get("schema_version") != "hpa_reference_benchmarks_v1":
        raise ValueError(
            "HPA benchmark file schema_version must be hpa_reference_benchmarks_v1."
        )
    benchmarks = payload.get("benchmarks")
    if not isinstance(benchmarks, dict) or not benchmarks:
        raise ValueError("HPA benchmark file must define a non-empty benchmarks mapping.")

    loaded: dict[str, dict[str, Any]] = {}
    for benchmark_id, benchmark in benchmarks.items():
        if not isinstance(benchmark, dict):
            raise ValueError(f"Benchmark {benchmark_id!r} must be a mapping.")
        _validate_sources(str(benchmark_id), benchmark)
        loaded[str(benchmark_id)] = _add_derived_fields(benchmark)
    return loaded


__all__ = ["DEFAULT_HPA_BENCHMARK_PATH", "load_hpa_reference_benchmarks"]
