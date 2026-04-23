from __future__ import annotations

import atexit
from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

_CACHE_SCHEMA_VERSION = 2
_SUCCESS_STATUSES = frozenset({"ok", "stubbed_ok", "mini_sweep_fallback"})
_NEGATIVE_CACHE_STATUSES = frozenset({"analysis_failed"})
_CACHEABLE_STATUSES = _SUCCESS_STATUSES | _NEGATIVE_CACHE_STATUSES


@dataclass(frozen=True)
class PolarQuery:
    template_id: str
    reynolds: float
    cl_samples: tuple[float, ...]
    roughness_mode: str
    geometry_hash: str
    coordinates: tuple[tuple[float, float], ...]
    analysis_mode: str = "full_alpha_sweep"
    analysis_stage: str = "screening"


def _normalize_coordinates(
    coordinates: object,
) -> tuple[tuple[float, float], ...]:
    if not isinstance(coordinates, list | tuple):
        raise RuntimeError("Airfoil coordinates must be a JSON-compatible array of [x, y] pairs.")

    normalized: list[tuple[float, float]] = []
    for point in coordinates:
        if not isinstance(point, list | tuple) or len(point) != 2:
            raise RuntimeError("Airfoil coordinates entries must be [x, y] pairs.")
        x_value, y_value = point
        if not isinstance(x_value, int | float) or not isinstance(y_value, int | float):
            raise RuntimeError("Airfoil coordinates entries must be numeric.")
        normalized.append((float(x_value), float(y_value)))

    if len(normalized) < 3:
        raise RuntimeError("Airfoil coordinates must contain at least three points.")
    return tuple(normalized)


def geometry_hash_from_coordinates(coordinates: object) -> str:
    normalized = _normalize_coordinates(coordinates)
    encoded = json.dumps(normalized, sort_keys=False, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


class JuliaXFoilWorker:
    backend_name = "julia_xfoil"

    def __init__(
        self,
        *,
        project_dir: Path,
        cache_dir: Path,
        persistent_mode: bool = True,
        persistent_worker_count: int | None = None,
    ) -> None:
        self.project_dir = Path(project_dir)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.persistent_mode = bool(persistent_mode)
        self._persistent_worker_count = persistent_worker_count
        self._persistent_processes: list[subprocess.Popen[str]] = []
        self._atexit_close_registered = False
        if self.persistent_mode:
            atexit.register(self.close)
            self._atexit_close_registered = True

    def cache_key(self, query: PolarQuery) -> str:
        payload = {
            "cache_schema_version": _CACHE_SCHEMA_VERSION,
            "reynolds": query.reynolds,
            "cl_samples": list(query.cl_samples),
            "roughness_mode": query.roughness_mode,
            "geometry_hash": self._validated_geometry_hash(query),
            "analysis_mode": query.analysis_mode,
            "analysis_stage": query.analysis_stage,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def _resolve_julia(self) -> str | None:
        return shutil.which("julia")

    def _resolve_worker_project_dir(self) -> Path:
        direct_dir = self.project_dir
        direct_project = direct_dir / "Project.toml"
        if direct_project.is_file():
            return direct_dir

        nested_dir = direct_dir / "tools" / "julia" / "xfoil_worker"
        nested_project = nested_dir / "Project.toml"
        if nested_project.is_file():
            return nested_dir

        raise RuntimeError(
            "Unable to resolve Julia XFoil worker project. "
            "Expected either project_dir itself or project_dir/tools/julia/xfoil_worker "
            "to contain Project.toml."
        )

    def _positive_cache_path(self, query: PolarQuery) -> Path:
        return (
            self.cache_dir
            / query.analysis_mode
            / query.analysis_stage
            / f"{self.cache_key(query)}.json"
        )

    def _negative_cache_path(self, query: PolarQuery) -> Path:
        return (
            self.cache_dir
            / "negative"
            / query.analysis_mode
            / query.analysis_stage
            / f"{self.cache_key(query)}.json"
        )

    def _normalize_cl_samples(self, cl_samples: object) -> tuple[float, ...]:
        if not isinstance(cl_samples, list | tuple):
            raise RuntimeError("Julia XFoil worker identity requires cl_samples as a JSON array.")

        normalized_samples: list[float] = []
        for value in cl_samples:
            if not isinstance(value, int | float):
                raise RuntimeError("Julia XFoil worker cl_samples entries must be numeric.")
            normalized_samples.append(float(value))
        return tuple(normalized_samples)

    def _validated_geometry_hash(self, query: PolarQuery) -> str:
        derived_hash = geometry_hash_from_coordinates(query.coordinates)
        if query.geometry_hash != derived_hash:
            raise RuntimeError(
                "PolarQuery geometry_hash did not match the provided airfoil coordinates."
            )
        return derived_hash

    def _query_identity(
        self,
        query: PolarQuery,
    ) -> tuple[str, float, tuple[float, ...], str, str, str, str]:
        return (
            query.template_id,
            *self._physical_query_identity(query),
        )

    def _physical_query_identity(
        self,
        query: PolarQuery,
    ) -> tuple[float, tuple[float, ...], str, str, str, str]:
        return (
            float(query.reynolds),
            tuple(float(value) for value in query.cl_samples),
            query.roughness_mode,
            self._validated_geometry_hash(query),
            query.analysis_mode,
            query.analysis_stage,
        )

    def _result_identity(
        self,
        result: dict[str, object],
    ) -> tuple[str, float, tuple[float, ...], str, str, str, str]:
        template_id = result.get("template_id")
        return (
            self._result_template_id(result),
            *self._physical_result_identity(result),
        )

    def _result_template_id(self, result: dict[str, object]) -> str:
        template_id = result.get("template_id")
        reynolds = result.get("reynolds")
        cl_samples = result.get("cl_samples")
        roughness_mode = result.get("roughness_mode")
        geometry_hash = result.get("geometry_hash")
        if not isinstance(template_id, str):
            raise RuntimeError("Julia XFoil worker response is missing a valid template_id.")
        if not isinstance(roughness_mode, str):
            raise RuntimeError("Julia XFoil worker response is missing a valid roughness_mode.")
        if not isinstance(geometry_hash, str):
            raise RuntimeError("Julia XFoil worker response is missing a valid geometry_hash.")
        if not isinstance(reynolds, int | float):
            raise RuntimeError("Julia XFoil worker response is missing a valid reynolds value.")
        return template_id

    def _physical_result_identity(
        self,
        result: dict[str, object],
    ) -> tuple[float, tuple[float, ...], str, str, str, str]:
        reynolds = result.get("reynolds")
        cl_samples = result.get("cl_samples")
        roughness_mode = result.get("roughness_mode")
        geometry_hash = result.get("geometry_hash")
        analysis_mode = result.get("analysis_mode", "full_alpha_sweep")
        analysis_stage = result.get("analysis_stage", "screening")
        if not isinstance(roughness_mode, str):
            raise RuntimeError("Julia XFoil worker response is missing a valid roughness_mode.")
        if not isinstance(geometry_hash, str):
            raise RuntimeError("Julia XFoil worker response is missing a valid geometry_hash.")
        if not isinstance(reynolds, int | float):
            raise RuntimeError("Julia XFoil worker response is missing a valid reynolds value.")
        if not isinstance(analysis_mode, str):
            raise RuntimeError("Julia XFoil worker response is missing a valid analysis_mode.")
        if not isinstance(analysis_stage, str):
            raise RuntimeError("Julia XFoil worker response is missing a valid analysis_stage.")
        return (
            float(reynolds),
            self._normalize_cl_samples(cl_samples),
            roughness_mode,
            geometry_hash,
            analysis_mode,
            analysis_stage,
        )

    def _load_cached_result(self, query: PolarQuery) -> dict[str, object] | None:
        cache_candidates = (
            self._positive_cache_path(query),
            self._negative_cache_path(query),
        )
        cache_path = next((path for path in cache_candidates if path.is_file()), None)
        if cache_path is None:
            return None

        cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
        if not isinstance(cached_payload, dict):
            raise RuntimeError("Julia XFoil worker cache entries must be JSON objects.")
        if self._physical_result_identity(cached_payload) != self._physical_query_identity(query):
            raise RuntimeError("Julia XFoil worker cache entry did not match requested query identity.")
        return self._validate_cacheable_status(self._materialize_result_for_query(cached_payload, query))

    def _write_cached_result(self, query: PolarQuery, result: dict[str, object]) -> None:
        serialized_result = self._materialize_result_for_query(result, query)
        cache_path = self._cache_path_for_status(query, str(serialized_result.get("status", "unknown")))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(serialized_result, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def _cache_path_for_status(self, query: PolarQuery, status: str) -> Path:
        if status in _SUCCESS_STATUSES:
            return self._positive_cache_path(query)
        if status in _NEGATIVE_CACHE_STATUSES:
            return self._negative_cache_path(query)
        raise RuntimeError(
            "Julia/XFoil worker returned a non-cacheable status: "
            f"{status!r}. Expected one of {sorted(_CACHEABLE_STATUSES)!r}."
        )

    def _validate_cacheable_status(self, result: dict[str, object]) -> dict[str, object]:
        status = result.get("status")
        if status not in _CACHEABLE_STATUSES:
            raise RuntimeError(
                "Julia/XFoil worker returned a non-cacheable status: "
                f"{status!r}. Expected one of {sorted(_CACHEABLE_STATUSES)!r}."
            )
        return result

    def _materialize_result_for_query(
        self,
        result: dict[str, object],
        query: PolarQuery,
    ) -> dict[str, object]:
        materialized = dict(result)
        materialized["template_id"] = query.template_id
        materialized["reynolds"] = float(query.reynolds)
        materialized["cl_samples"] = list(float(value) for value in query.cl_samples)
        materialized["roughness_mode"] = query.roughness_mode
        materialized["geometry_hash"] = self._validated_geometry_hash(query)
        materialized["analysis_mode"] = query.analysis_mode
        materialized["analysis_stage"] = query.analysis_stage
        return materialized

    def _build_scratch_paths(self) -> tuple[Path, Path]:
        token = uuid4().hex
        return (
            self.cache_dir / f"request_{token}.json",
            self.cache_dir / f"response_{token}.json",
        )

    def _persistent_stderr_text(self, process: subprocess.Popen[str] | None = None) -> str:
        process = process or (self._persistent_processes[0] if self._persistent_processes else None)
        if process is None or process.stderr is None:
            return ""
        try:
            return process.stderr.read()
        except Exception:
            return ""

    def _spawn_persistent_process(self) -> subprocess.Popen[str]:
        julia = self._resolve_julia()
        if julia is None:
            raise RuntimeError(
                "Julia runtime not found. Install Julia before running the XFoil worker."
            )

        worker_dir = self._resolve_worker_project_dir()
        return subprocess.Popen(
            [
                julia,
                f"--project={worker_dir}",
                str(worker_dir / "xfoil_worker.jl"),
                "--stdio",
            ],
            cwd=self.project_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _persistent_worker_pool_size(self, query_count: int) -> int:
        if query_count < 1:
            return 0
        if query_count == 1:
            return 1

        configured = self._persistent_worker_count
        if configured is not None:
            if configured < 1:
                raise ValueError("persistent_worker_count must be at least 1.")
            return min(query_count, configured)

        cpu_count = os.cpu_count() or 1
        return min(query_count, max(2, cpu_count))

    def _ensure_persistent_processes(
        self,
        count: int,
    ) -> list[subprocess.Popen[str]]:
        if count < 1:
            raise ValueError("count must be at least 1.")

        processes = self._persistent_processes
        for index, process in enumerate(processes):
            if process.poll() is not None:
                processes[index] = self._spawn_persistent_process()

        while len(processes) < count:
            processes.append(self._spawn_persistent_process())

        return processes[:count]

    def _run_uncached_queries_with_process(
        self,
        process: subprocess.Popen[str],
        queries: list[PolarQuery],
    ) -> list[dict[str, object]]:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Persistent Julia XFoil worker is missing stdin/stdout pipes.")

        request_payload = [asdict(query) for query in queries]
        try:
            process.stdin.write(json.dumps(request_payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except BrokenPipeError as exc:
            stderr_text = self._persistent_stderr_text(process).strip()
            self.close()
            raise RuntimeError(
                "Persistent Julia XFoil worker stdin closed unexpectedly."
                + (f" Stderr: {stderr_text}" if stderr_text else "")
            ) from exc

        response_line = process.stdout.readline()
        if response_line == "":
            stderr_text = self._persistent_stderr_text(process).strip()
            return_code = process.poll()
            self.close()
            raise RuntimeError(
                "Persistent Julia XFoil worker exited before returning a response."
                + (f" Return code: {return_code}." if return_code is not None else "")
                + (f" Stderr: {stderr_text}" if stderr_text else "")
            )

        response_payload = json.loads(response_line)
        if not isinstance(response_payload, list):
            raise RuntimeError("Persistent Julia XFoil worker response must be a JSON array.")
        if len(response_payload) != len(queries):
            raise RuntimeError(
                "Persistent Julia XFoil worker returned "
                f"{len(response_payload)} results for {len(queries)} uncached queries."
            )
        return response_payload

    def _run_uncached_queries_one_shot(self, queries: list[PolarQuery]) -> list[dict[str, object]]:
        julia = self._resolve_julia()
        if julia is None:
            raise RuntimeError(
                "Julia runtime not found. Install Julia before running the XFoil worker."
            )

        worker_dir = self._resolve_worker_project_dir()
        request_path, response_path = self._build_scratch_paths()
        request_payload = [asdict(query) for query in queries]
        request_path.write_text(
            json.dumps(request_payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

        subprocess.run(
            [
                julia,
                f"--project={worker_dir}",
                str(worker_dir / "xfoil_worker.jl"),
                str(request_path),
                str(response_path),
            ],
            check=True,
            cwd=self.project_dir,
        )

        response_payload = json.loads(response_path.read_text(encoding="utf-8"))
        if not isinstance(response_payload, list):
            raise RuntimeError("Julia XFoil worker response must be a JSON array.")
        if len(response_payload) != len(queries):
            raise RuntimeError(
                "Julia XFoil worker returned "
                f"{len(response_payload)} results for {len(queries)} uncached queries."
            )
        return response_payload

    def _run_uncached_queries_persistent(
        self,
        queries: list[PolarQuery],
    ) -> list[dict[str, object]]:
        if not queries:
            return []

        worker_count = self._persistent_worker_pool_size(len(queries))
        processes = self._ensure_persistent_processes(worker_count)

        chunked_queries: list[list[PolarQuery]] = [[] for _ in range(worker_count)]
        chunk_positions: list[list[int]] = [[] for _ in range(worker_count)]
        for index, query in enumerate(queries):
            slot = index % worker_count
            chunked_queries[slot].append(query)
            chunk_positions[slot].append(index)

        chunk_results: list[list[dict[str, object]] | None] = [None] * worker_count
        try:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(
                        self._run_uncached_queries_with_process,
                        processes[slot],
                        chunked_queries[slot],
                    ): slot
                    for slot in range(worker_count)
                    if chunked_queries[slot]
                }
                for future in as_completed(futures):
                    slot = futures[future]
                    chunk_results[slot] = future.result()
        except Exception:
            self.close()
            raise

        responses: list[dict[str, object] | None] = [None] * len(queries)
        for slot, items in enumerate(chunk_results):
            if items is None:
                continue
            positions = chunk_positions[slot]
            if len(items) != len(positions):
                raise RuntimeError(
                    "Persistent Julia XFoil worker returned an unexpected number of chunk results."
                )
            for index, item in zip(positions, items, strict=True):
                responses[index] = item

        finalized_responses: list[dict[str, object]] = []
        for item in responses:
            if item is None:
                raise RuntimeError(
                    "Persistent Julia XFoil worker did not populate all uncached query results."
                )
            finalized_responses.append(item)
        return finalized_responses

    def close(self) -> None:
        processes = self._persistent_processes
        if not processes:
            return

        self._persistent_processes = []
        try:
            for process in processes:
                if process.stdin is not None:
                    try:
                        process.stdin.close()
                    except Exception:
                        pass
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5.0)
        finally:
            for process in processes:
                if process.stdout is not None:
                    try:
                        process.stdout.close()
                    except Exception:
                        pass
                if process.stderr is not None:
                    try:
                        process.stderr.close()
                    except Exception:
                        pass

    def run_queries(self, queries: list[PolarQuery]) -> list[dict[str, object]]:
        resolved_results: list[dict[str, object] | None] = [None] * len(queries)
        uncached_queries: list[PolarQuery] = []
        uncached_groups: dict[str, list[tuple[int, PolarQuery]]] = {}

        for index, query in enumerate(queries):
            cached_result = self._load_cached_result(query)
            if cached_result is not None:
                resolved_results[index] = cached_result
                continue
            cache_key = self.cache_key(query)
            if cache_key not in uncached_groups:
                uncached_queries.append(query)
                uncached_groups[cache_key] = []
            uncached_groups[cache_key].append((index, query))

        if uncached_queries:
            response_payload = (
                self._run_uncached_queries_persistent(uncached_queries)
                if self.persistent_mode
                else self._run_uncached_queries_one_shot(uncached_queries)
            )

            for query, item in zip(uncached_queries, response_payload):
                if not isinstance(item, dict):
                    raise RuntimeError("Julia XFoil worker response entries must be JSON objects.")
                if self._result_identity(item) != self._query_identity(query):
                    raise RuntimeError(
                        "Julia XFoil worker response entry did not match requested query identity."
                    )
                validated_item = self._validate_cacheable_status(item)
                self._write_cached_result(query, validated_item)
                for index, duplicate_query in uncached_groups[self.cache_key(query)]:
                    resolved_results[index] = self._materialize_result_for_query(
                        validated_item,
                        duplicate_query,
                    )

        finalized_results: list[dict[str, object]] = []
        for item in resolved_results:
            if item is None:
                raise RuntimeError("Julia XFoil worker did not populate all requested query results.")
            finalized_results.append(item)
        return finalized_results
