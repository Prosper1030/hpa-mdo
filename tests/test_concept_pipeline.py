from __future__ import annotations

import json
from pathlib import Path
import subprocess

from hpa_mdo.concept.pipeline import run_birdman_concept_pipeline


def test_pipeline_writes_ranked_concept_summary(tmp_path: Path) -> None:
    factory_calls: list[dict[str, object]] = []
    loader_calls: list[tuple[str, int]] = []

    class FakeWorker:
        backend_name = "test_stub"

        def run_queries(self, queries):
            return [
                {"status": "ok", "polar_points": [], "template_id": query.template_id}
                for query in queries
            ]

    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **kwargs: factory_calls.append(kwargs) or FakeWorker(),
        spanwise_loader=lambda concept, stations: loader_calls.append((concept.span_m, len(stations)))
        or {
            "root": {
                "points": [
                    {
                        "reynolds": 350000.0,
                        "cl_target": 0.75,
                        "cm_target": -0.10,
                        "weight": 1.0,
                    }
                ]
            },
            "mid1": {
                "points": [
                    {
                        "reynolds": 300000.0,
                        "cl_target": 0.72,
                        "cm_target": -0.09,
                        "weight": 1.0,
                    }
                ]
            },
            "mid2": {
                "points": [
                    {
                        "reynolds": 250000.0,
                        "cl_target": 0.68,
                        "cm_target": -0.08,
                        "weight": 1.0,
                    }
                ]
            },
            "tip": {
                "points": [
                    {
                        "reynolds": 200000.0,
                        "cl_target": 0.62,
                        "cm_target": -0.07,
                        "weight": 1.0,
                    }
                ]
            },
        },
    )

    assert result.summary_json_path.exists()
    assert 3 <= len(result.selected_concept_dirs) <= 5
    assert factory_calls
    assert factory_calls[0]["project_dir"] == Path(__file__).resolve().parents[1]
    assert factory_calls[0]["cache_dir"] == tmp_path / "polar_db"
    assert len(loader_calls) == len(result.selected_concept_dirs)

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert summary["worker_backend"] == "test_stub"
    assert summary["worker_statuses"]
    assert all(status == "ok" for status in summary["worker_statuses"])
    assert summary["selected_concepts"][0]["worker_backend"] == "test_stub"
    assert summary["selected_concepts"][0]["worker_statuses"] == ["ok", "ok", "ok", "ok"]


def test_cli_smoke_writes_summary(tmp_path: Path) -> None:
    output_dir = tmp_path / "smoke"
    subprocess.run(
        [
            "../../.venv/bin/python",
            "scripts/birdman_upstream_concept_design.py",
            "--config",
            "configs/birdman_upstream_concept_baseline.yaml",
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    summary = json.loads((output_dir / "concept_summary.json").read_text(encoding="utf-8"))
    assert summary["worker_backend"] == "cli_stubbed"
    assert summary["selected_concepts"]
