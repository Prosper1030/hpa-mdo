from __future__ import annotations

import json
from pathlib import Path

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
        worker.run_queries(
            [
                PolarQuery(
                    template_id="root-v1",
                    reynolds=350000.0,
                    cl_samples=(0.7,),
                    roughness_mode="clean",
                )
            ]
        )


@pytest.mark.parametrize("project_dir_kind", ["repo_root", "worker_dir"])
def test_worker_resolves_worker_path_from_repo_root_or_worker_dir(
    tmp_path, monkeypatch, project_dir_kind
):
    repo_root = tmp_path / "repo"
    worker_dir = repo_root / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    if project_dir_kind == "repo_root":
        project_dir = repo_root
    else:
        project_dir = worker_dir

    cache_dir = tmp_path / "cache"
    worker = JuliaXFoilWorker(project_dir=project_dir, cache_dir=cache_dir)
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    called = {}

    def fake_run(cmd, check, cwd):
        called["cmd"] = cmd
        called["check"] = check
        called["cwd"] = cwd
        response_path = Path(cmd[-1])
        response_path.write_text(
            json.dumps(
                [
                    {
                        "template_id": "root-v1",
                        "reynolds": 350000.0,
                        "cl_samples": [0.7],
                        "roughness_mode": "clean",
                        "status": "stubbed_ok",
                    }
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    result = worker.run_queries(
        [
            PolarQuery(
                template_id="root-v1",
                reynolds=350000.0,
                cl_samples=(0.7,),
                roughness_mode="clean",
            )
        ]
    )

    assert called["check"] is True
    assert called["cwd"] == project_dir
    assert called["cmd"][0] == "/opt/julia/bin/julia"
    expected_worker_project = worker_dir
    assert called["cmd"][1] == f"--project={expected_worker_project}"
    assert called["cmd"][2] == str(expected_worker_project / "xfoil_worker.jl")
    assert Path(called["cmd"][3]).parent == cache_dir
    assert Path(called["cmd"][4]).parent == cache_dir
    assert Path(called["cmd"][3]).name != "request.json"
    assert Path(called["cmd"][4]).name != "response.json"
    assert result == [
        {
            "template_id": "root-v1",
            "reynolds": 350000.0,
            "cl_samples": [0.7],
            "roughness_mode": "clean",
            "status": "stubbed_ok",
        }
    ]


def test_worker_fails_fast_when_worker_project_cannot_be_resolved(tmp_path, monkeypatch):
    worker = JuliaXFoilWorker(project_dir=tmp_path / "repo", cache_dir=tmp_path / "cache")
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    with pytest.raises(RuntimeError, match="Unable to resolve Julia XFoil worker project"):
        worker.run_queries(
            [
                PolarQuery(
                    template_id="root-v1",
                    reynolds=350000.0,
                    cl_samples=(0.7,),
                    roughness_mode="clean",
                )
            ]
        )


def test_worker_uses_per_query_cache_and_allows_full_cache_hits_without_julia(
    tmp_path, monkeypatch
):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(project_dir=tmp_path / "repo", cache_dir=tmp_path / "cache")
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    query = PolarQuery(
        template_id="root-v1",
        reynolds=350000.0,
        cl_samples=(0.7,),
        roughness_mode="clean",
    )
    calls = {"count": 0}

    def fake_run(cmd, check, cwd):
        calls["count"] += 1
        Path(cmd[4]).write_text(
            json.dumps(
                [
                    {
                        "template_id": "root-v1",
                        "reynolds": 350000.0,
                        "cl_samples": [0.7],
                        "roughness_mode": "clean",
                        "status": "stubbed_ok",
                    }
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    first_result = worker.run_queries([query])
    assert calls["count"] == 1

    def fail_run(cmd, check, cwd):
        raise AssertionError("subprocess.run should not be called for cache hits")

    monkeypatch.setattr(worker, "_resolve_julia", lambda: None)
    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fail_run)
    second_result = worker.run_queries([query])

    assert second_result == first_result
    assert (worker.cache_dir / f"{worker.cache_key(query)}.json").is_file()


@pytest.mark.parametrize(
    ("response_payload", "error_match"),
    [
        (
            [],
            "returned 0 results for 1 uncached queries",
        ),
        (
            [
                {
                    "template_id": "tip-v9",
                    "reynolds": 350000.0,
                    "cl_samples": [0.7],
                    "roughness_mode": "clean",
                    "status": "stubbed_ok",
                }
            ],
            "did not match requested query identity",
        ),
    ],
)
def test_worker_fails_fast_when_julia_response_does_not_match_uncached_queries(
    tmp_path, monkeypatch, response_payload, error_match
):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(project_dir=tmp_path / "repo", cache_dir=tmp_path / "cache")
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    def fake_run(cmd, check, cwd):
        Path(cmd[4]).write_text(json.dumps(response_payload), encoding="utf-8")

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match=error_match):
        worker.run_queries(
            [
                PolarQuery(
                    template_id="root-v1",
                    reynolds=350000.0,
                    cl_samples=(0.7,),
                    roughness_mode="clean",
                )
            ]
        )


def test_worker_rejects_response_with_wrong_cl_samples_identity(tmp_path, monkeypatch):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(project_dir=tmp_path / "repo", cache_dir=tmp_path / "cache")
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    def fake_run(cmd, check, cwd):
        Path(cmd[4]).write_text(
            json.dumps(
                [
                    {
                        "template_id": "root-v1",
                        "reynolds": 350000.0,
                        "cl_samples": [0.8],
                        "roughness_mode": "clean",
                        "status": "stubbed_ok",
                    }
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="did not match requested query identity"):
        worker.run_queries(
            [
                PolarQuery(
                    template_id="root-v1",
                    reynolds=350000.0,
                    cl_samples=(0.7,),
                    roughness_mode="clean",
                )
            ]
        )
