from __future__ import annotations

import pytest

from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker, PolarQuery


def test_worker_cache_key_is_stable_for_identical_query(tmp_path):
    worker = JuliaXFoilWorker(project_dir=tmp_path, cache_dir=tmp_path / "cache")
    query = PolarQuery(
        template_id="root-v1",
        reynolds=350000.0,
        cl_samples=(0.70, 0.75, 0.80),
        roughness_mode="clean",
    )

    assert worker.cache_key(query) == worker.cache_key(query)


def test_worker_raises_clear_error_when_julia_runtime_is_missing(tmp_path, monkeypatch):
    worker = JuliaXFoilWorker(project_dir=tmp_path, cache_dir=tmp_path / "cache")
    monkeypatch.setattr(worker, "_resolve_julia", lambda: None)

    with pytest.raises(RuntimeError, match="Julia runtime not found"):
        worker.run_queries([])
