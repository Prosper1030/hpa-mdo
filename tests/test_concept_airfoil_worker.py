from __future__ import annotations

import io
import json
from pathlib import Path
import shutil

import pytest

from hpa_mdo.concept.airfoil_worker import (
    JuliaXFoilWorker,
    PolarQuery,
    geometry_hash_from_coordinates,
)


def _sample_query(**overrides) -> PolarQuery:
    coordinates = (
        (1.0, 0.0),
        (0.5, 0.05),
        (0.0, 0.0),
        (0.5, -0.05),
        (1.0, 0.0),
    )
    payload = {
        "template_id": "root-v1",
        "reynolds": 350000.0,
        "cl_samples": (0.70, 0.75, 0.80),
        "roughness_mode": "clean",
        "geometry_hash": geometry_hash_from_coordinates(coordinates),
        "coordinates": coordinates,
    }
    payload.update(overrides)
    return PolarQuery(**payload)


def test_worker_reuses_persistent_julia_process_across_uncached_batches(
    tmp_path, monkeypatch
):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=True,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    spawn_count = {"value": 0}

    class _FakeStdout:
        def __init__(self, process):
            self._process = process

        def readline(self):
            payload = self._process.pending_response
            self._process.pending_response = ""
            return payload

    class _FakeStdin:
        def __init__(self, process):
            self._process = process
            self._buffer = ""

        def write(self, text):
            self._buffer += text
            return len(text)

        def flush(self):
            payload = json.loads(self._buffer)
            self._buffer = ""
            response = []
            for query in payload:
                response.append(
                    {
                        "template_id": query["template_id"],
                        "reynolds": query["reynolds"],
                        "cl_samples": query["cl_samples"],
                        "roughness_mode": query["roughness_mode"],
                        "geometry_hash": query["geometry_hash"],
                        "status": "ok",
                        "polar_points": [
                            {
                                "cl_target": query["cl_samples"][0],
                                "alpha_deg": 4.2,
                                "cl": query["cl_samples"][0],
                                "cd": 0.021,
                                "cm": -0.08,
                                "converged": True,
                            }
                        ],
                    }
                )
            self._process.pending_response = json.dumps(response) + "\n"

        def close(self):
            self._process.stdin_closed = True

    class _FakeProcess:
        def __init__(self):
            self.stdin_closed = False
            self.pending_response = ""
            self.stdin = _FakeStdin(self)
            self.stdout = _FakeStdout(self)
            self.stderr = io.StringIO("")
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

    def fake_popen(cmd, cwd, stdin, stdout, stderr, text):
        spawn_count["value"] += 1
        return _FakeProcess()

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.Popen", fake_popen)

    query1 = _sample_query(template_id="root-v1", cl_samples=(0.7,))
    query2 = _sample_query(
        template_id="root-v2",
        cl_samples=(0.8,),
        coordinates=((1.0, 0.0), (0.5, 0.06), (0.0, 0.0), (0.5, -0.04), (1.0, 0.0)),
        geometry_hash=geometry_hash_from_coordinates(
            ((1.0, 0.0), (0.5, 0.06), (0.0, 0.0), (0.5, -0.04), (1.0, 0.0))
        ),
    )

    first = worker.run_queries([query1])
    second = worker.run_queries([query2])

    assert first[0]["status"] == "ok"
    assert second[0]["status"] == "ok"
    assert spawn_count["value"] == 1


def test_worker_close_terminates_persistent_julia_process(tmp_path, monkeypatch):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=True,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    closed = {"terminated": 0, "stdin_closed": 0}

    class _FakeStdout:
        def readline(self):
            return json.dumps(
                [
                    {
                        "template_id": "root-v1",
                        "reynolds": 350000.0,
                        "cl_samples": [0.7],
                        "roughness_mode": "clean",
                        "geometry_hash": _sample_query(cl_samples=(0.7,)).geometry_hash,
                        "status": "ok",
                        "polar_points": [{"cl_target": 0.7, "alpha_deg": 4.2, "cl": 0.7}],
                    }
                ]
            ) + "\n"

    class _FakeStdin:
        def write(self, text):
            return len(text)

        def flush(self):
            return None

        def close(self):
            closed["stdin_closed"] += 1

    class _FakeProcess:
        def __init__(self):
            self.stdin = _FakeStdin()
            self.stdout = _FakeStdout()
            self.stderr = io.StringIO("")
            self.returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

        def terminate(self):
            closed["terminated"] += 1
            self.returncode = 0

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(
        "hpa_mdo.concept.airfoil_worker.subprocess.Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )

    worker.run_queries([_sample_query(cl_samples=(0.7,))])
    worker.close()

    assert closed["stdin_closed"] == 1
    assert closed["terminated"] == 1


def test_worker_cache_key_is_stable_for_identical_query(tmp_path):
    worker = JuliaXFoilWorker(project_dir=tmp_path, cache_dir=tmp_path / "cache")
    query = _sample_query()

    assert worker.cache_key(query) == worker.cache_key(query)


def test_worker_cache_key_ignores_template_id_for_physically_identical_query(tmp_path):
    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )

    assert worker.cache_key(_sample_query(template_id="root-v1")) == worker.cache_key(
        _sample_query(template_id="tip-v9")
    )


def test_worker_cache_key_changes_when_geometry_hash_changes(tmp_path):
    worker = JuliaXFoilWorker(project_dir=tmp_path, cache_dir=tmp_path / "cache")

    assert worker.cache_key(_sample_query()) != worker.cache_key(
        _sample_query(
            coordinates=(
                (1.0, 0.0),
                (0.5, 0.06),
                (0.0, 0.0),
                (0.5, -0.04),
                (1.0, 0.0),
            ),
            geometry_hash=geometry_hash_from_coordinates(
                (
                    (1.0, 0.0),
                    (0.5, 0.06),
                    (0.0, 0.0),
                    (0.5, -0.04),
                    (1.0, 0.0),
                )
            ),
        )
    )


def test_worker_raises_clear_error_when_julia_runtime_is_missing(tmp_path, monkeypatch):
    worker = JuliaXFoilWorker(project_dir=tmp_path, cache_dir=tmp_path / "cache")
    monkeypatch.setattr(worker, "_resolve_julia", lambda: None)

    with pytest.raises(RuntimeError, match="Julia runtime not found"):
        worker.run_queries([_sample_query(cl_samples=(0.7,))])


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
    worker = JuliaXFoilWorker(
        project_dir=project_dir,
        cache_dir=cache_dir,
        persistent_mode=False,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")
    query = _sample_query(cl_samples=(0.7,))

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
                            "geometry_hash": query.geometry_hash,
                            "status": "ok",
                        "polar_points": [
                            {
                                "cl_target": 0.7,
                                "alpha_deg": 4.2,
                                "cl": 0.701,
                                "cd": 0.021,
                                "cdp": 0.015,
                                "cm": -0.08,
                                "converged": True,
                            }
                        ],
                    }
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    result = worker.run_queries([query])

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
            "geometry_hash": query.geometry_hash,
            "status": "ok",
            "polar_points": [
                {
                    "cl_target": 0.7,
                    "alpha_deg": 4.2,
                    "cl": 0.701,
                    "cd": 0.021,
                    "cdp": 0.015,
                    "cm": -0.08,
                    "converged": True,
                }
            ],
        }
    ]


def test_worker_fails_fast_when_worker_project_cannot_be_resolved(tmp_path, monkeypatch):
    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    with pytest.raises(RuntimeError, match="Unable to resolve Julia XFoil worker project"):
        worker.run_queries([_sample_query(cl_samples=(0.7,))])


def test_worker_uses_per_query_cache_and_allows_full_cache_hits_without_julia(
    tmp_path, monkeypatch
):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    query = _sample_query(cl_samples=(0.7,))
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
                        "geometry_hash": query.geometry_hash,
                        "status": "ok",
                        "polar_points": [{"cl_target": 0.7, "alpha_deg": 4.2, "cl": 0.701}],
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


def test_worker_reuses_physical_cache_for_different_template_id(tmp_path, monkeypatch):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    query_a = _sample_query(template_id="root-v1", cl_samples=(0.7,))
    query_b = _sample_query(template_id="tip-v9", cl_samples=(0.7,))
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
                        "geometry_hash": query_a.geometry_hash,
                        "status": "ok",
                        "polar_points": [{"cl_target": 0.7, "alpha_deg": 4.2, "cl": 0.701}],
                    }
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    first_result = worker.run_queries([query_a])
    second_result = worker.run_queries([query_b])

    assert calls["count"] == 1
    assert first_result[0]["template_id"] == "root-v1"
    assert second_result[0]["template_id"] == "tip-v9"


def test_worker_deduplicates_physically_identical_queries_within_single_run(tmp_path, monkeypatch):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    query_a = _sample_query(template_id="root-v1", cl_samples=(0.7,))
    query_b = _sample_query(template_id="mid1-v2", cl_samples=(0.7,))
    calls = {"count": 0}

    def fake_run(cmd, check, cwd):
        calls["count"] += 1
        request_payload = json.loads(Path(cmd[3]).read_text(encoding="utf-8"))
        assert len(request_payload) == 1
        Path(cmd[4]).write_text(
            json.dumps(
                [
                    {
                        "template_id": "root-v1",
                        "reynolds": 350000.0,
                        "cl_samples": [0.7],
                        "roughness_mode": "clean",
                        "geometry_hash": query_a.geometry_hash,
                        "status": "ok",
                        "polar_points": [{"cl_target": 0.7, "alpha_deg": 4.2, "cl": 0.701}],
                    }
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    results = worker.run_queries([query_a, query_b])

    assert calls["count"] == 1
    assert [item["template_id"] for item in results] == ["root-v1", "mid1-v2"]


def test_worker_preserves_sweep_summary_through_cache_round_trip(tmp_path, monkeypatch):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    query = _sample_query(cl_samples=(0.7,))

    def fake_run(cmd, check, cwd):
        Path(cmd[4]).write_text(
            json.dumps(
                [
                    {
                        "template_id": "root-v1",
                        "reynolds": 350000.0,
                        "cl_samples": [0.7],
                        "roughness_mode": "clean",
                        "geometry_hash": query.geometry_hash,
                        "status": "ok",
                        "polar_points": [
                            {
                                "cl_target": 0.7,
                                "alpha_deg": 4.2,
                                "cl": 0.701,
                                "cd": 0.021,
                                "cdp": 0.015,
                                "cm": -0.08,
                                "converged": True,
                            }
                        ],
                        "sweep_summary": {
                            "sweep_point_count": 41,
                            "converged_point_count": 30,
                            "alpha_min_deg": -4.0,
                            "alpha_max_deg": 16.0,
                            "alpha_step_deg": 0.5,
                            "usable_polar_points": True,
                            "cl_max_observed": 1.26,
                            "alpha_at_cl_max_deg": 12.5,
                            "last_converged_alpha_deg": 12.5,
                            "clmax_is_lower_bound": True,
                            "first_pass_observed_clmax_proxy": 1.26,
                            "first_pass_observed_clmax_proxy_alpha_deg": 12.5,
                            "first_pass_observed_clmax_proxy_cd": 0.028,
                            "first_pass_observed_clmax_proxy_cdp": 0.020,
                            "first_pass_observed_clmax_proxy_cm": -0.11,
                            "first_pass_observed_clmax_proxy_index": 33,
                            "first_pass_observed_clmax_proxy_at_sweep_edge": False,
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    first_result = worker.run_queries([query])
    monkeypatch.setattr(worker, "_resolve_julia", lambda: None)
    monkeypatch.setattr(
        "hpa_mdo.concept.airfoil_worker.subprocess.run",
        lambda *args, **kwargs: pytest.fail("subprocess.run should not be called for cache hits"),
    )
    second_result = worker.run_queries([query])

    assert second_result == first_result
    sweep_summary = first_result[0]["sweep_summary"]
    assert sweep_summary["cl_max_observed"] == pytest.approx(1.26)
    assert sweep_summary["alpha_at_cl_max_deg"] == pytest.approx(12.5)
    assert sweep_summary["clmax_is_lower_bound"] is True
    assert sweep_summary["alpha_step_deg"] == pytest.approx(0.5)


def test_worker_preserves_airfoil_feedback_fields_through_cache_round_trip(
    tmp_path, monkeypatch
):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    query = _sample_query(cl_samples=(0.7,))
    response_payload = [
        {
            "template_id": "root-v1",
            "reynolds": 350000.0,
            "cl_samples": [0.7],
            "roughness_mode": "clean",
            "geometry_hash": query.geometry_hash,
            "status": "ok",
            "polar_points": [
                {
                    "cl_target": 0.7,
                    "alpha_deg": 4.2,
                    "cl": 0.701,
                    "cd": 0.021,
                    "cm": -0.08,
                    "converged": True,
                }
            ],
            "airfoil_feedback": {
                "source": "real_polar",
                "conservative": True,
                "first_usable_cl_max_proxy": 0.92,
                "near_target_point": {
                    "cl": 0.701,
                    "cd": 0.021,
                    "cm": -0.08,
                },
            },
            "safety_basis": "airfoil_real_polar",
        }
    ]

    def fake_run(cmd, check, cwd):
        Path(cmd[4]).write_text(json.dumps(response_payload), encoding="utf-8")

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    first_result = worker.run_queries([query])
    monkeypatch.setattr(worker, "_resolve_julia", lambda: None)
    monkeypatch.setattr(
        "hpa_mdo.concept.airfoil_worker.subprocess.run",
        lambda *args, **kwargs: pytest.fail("subprocess.run should not be called for cache hits"),
    )
    second_result = worker.run_queries([query])

    assert second_result == first_result
    assert first_result[0]["airfoil_feedback"]["source"] == "real_polar"
    assert first_result[0]["airfoil_feedback"]["conservative"] is True
    assert first_result[0]["airfoil_feedback"]["first_usable_cl_max_proxy"] == pytest.approx(0.92)
    assert first_result[0]["airfoil_feedback"]["near_target_point"]["cm"] == pytest.approx(-0.08)
    assert first_result[0]["polar_points"][0]["cd"] == pytest.approx(0.021)
    assert first_result[0]["safety_basis"] == "airfoil_real_polar"
    assert json.loads((worker.cache_dir / f"{worker.cache_key(query)}.json").read_text(encoding="utf-8")) == first_result[0]


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
                    "geometry_hash": "geom-root-v1",
                    "status": "ok",
                    "polar_points": [],
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

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    def fake_run(cmd, check, cwd):
        Path(cmd[4]).write_text(json.dumps(response_payload), encoding="utf-8")

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match=error_match):
        worker.run_queries(
            [
                _sample_query(cl_samples=(0.7,))
            ]
        )


def test_worker_rejects_response_with_wrong_cl_samples_identity(tmp_path, monkeypatch):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )
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
                        "geometry_hash": "geom-root-v1",
                        "status": "ok",
                        "polar_points": [],
                    }
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="did not match requested query identity"):
        worker.run_queries(
            [
                _sample_query(cl_samples=(0.7,))
            ]
        )


def test_worker_rejects_response_with_wrong_geometry_hash_identity(tmp_path, monkeypatch):
    worker_dir = tmp_path / "repo" / "tools" / "julia" / "xfoil_worker"
    worker_dir.mkdir(parents=True)
    (worker_dir / "Project.toml").write_text("name = \"BirdmanXFoilWorker\"\n", encoding="utf-8")

    worker = JuliaXFoilWorker(
        project_dir=tmp_path / "repo",
        cache_dir=tmp_path / "cache",
        persistent_mode=False,
    )
    monkeypatch.setattr(worker, "_resolve_julia", lambda: "/opt/julia/bin/julia")

    def fake_run(cmd, check, cwd):
        Path(cmd[4]).write_text(
            json.dumps(
                [
                    {
                        "template_id": "root-v1",
                        "reynolds": 350000.0,
                        "cl_samples": [0.7],
                        "roughness_mode": "clean",
                        "geometry_hash": "geom-root-v2",
                        "status": "ok",
                        "polar_points": [],
                    }
                ]
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("hpa_mdo.concept.airfoil_worker.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="did not match requested query identity"):
        worker.run_queries([_sample_query(cl_samples=(0.7,))])


def test_worker_rejects_query_with_geometry_hash_that_does_not_match_coordinates(tmp_path):
    worker = JuliaXFoilWorker(project_dir=tmp_path, cache_dir=tmp_path / "cache")

    with pytest.raises(RuntimeError, match="geometry_hash did not match"):
        worker.cache_key(
            _sample_query(
                geometry_hash="bad-hash",
            )
        )


@pytest.mark.skipif(shutil.which("julia") is None, reason="Julia runtime not available")
def test_real_julia_worker_returns_geometry_hash_and_polar_points(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    worker = JuliaXFoilWorker(project_dir=repo_root, cache_dir=tmp_path / "cache")

    result = worker.run_queries([_sample_query(cl_samples=(0.7,))])

    assert result[0]["status"] == "ok"
    assert result[0]["geometry_hash"] == _sample_query(cl_samples=(0.7,)).geometry_hash
    assert result[0]["polar_points"]
