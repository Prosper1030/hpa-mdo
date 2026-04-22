from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


@dataclass(frozen=True)
class PolarQuery:
    template_id: str
    reynolds: float
    cl_samples: tuple[float, ...]
    roughness_mode: str


class JuliaXFoilWorker:
    def __init__(self, *, project_dir: Path, cache_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def cache_key(self, query: PolarQuery) -> str:
        payload = {
            "template_id": query.template_id,
            "reynolds": query.reynolds,
            "cl_samples": list(query.cl_samples),
            "roughness_mode": query.roughness_mode,
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

    def run_queries(self, queries: list[PolarQuery]) -> list[dict[str, object]]:
        julia = self._resolve_julia()
        if julia is None:
            raise RuntimeError("Julia runtime not found. Install Julia before running the XFoil worker.")

        worker_dir = self._resolve_worker_project_dir()
        request_path = self.cache_dir / "request.json"
        response_path = self.cache_dir / "response.json"

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

        parsed_results: list[dict[str, object]] = []
        for item in response_payload:
            if not isinstance(item, dict):
                raise RuntimeError("Julia XFoil worker response entries must be JSON objects.")
            parsed_results.append(item)
        return parsed_results
