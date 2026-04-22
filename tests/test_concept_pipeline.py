from __future__ import annotations

import json
from pathlib import Path
import subprocess

import yaml

from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker
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
    assert "launch" in summary["selected_concepts"][0]
    assert "turn" in summary["selected_concepts"][0]
    assert "trim" in summary["selected_concepts"][0]
    assert "local_stall" in summary["selected_concepts"][0]
    assert isinstance(summary["selected_concepts"][0]["launch"]["cl_required"], float)
    assert isinstance(summary["selected_concepts"][0]["turn"]["required_cl"], float)
    assert isinstance(summary["selected_concepts"][0]["trim"]["margin_deg"], float)
    assert isinstance(summary["selected_concepts"][0]["local_stall"]["min_margin"], float)


def test_pipeline_emits_all_required_mvp_artifacts(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {"status": "stubbed_ok", "polar_points": [], "template_id": query.template_id}
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
            "root": {"points": []},
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    bundle = result.selected_concept_dirs[0]
    airfoil_templates = json.loads((bundle / "airfoil_templates.json").read_text(encoding="utf-8"))
    prop_assumption = json.loads((bundle / "prop_assumption.json").read_text(encoding="utf-8"))
    concept_summary = json.loads((bundle / "concept_summary.json").read_text(encoding="utf-8"))

    assert (bundle / "concept_config.yaml").exists()
    assert (bundle / "stations.csv").exists()
    assert (bundle / "airfoil_templates.json").exists()
    assert (bundle / "lofting_guides.json").exists()
    assert (bundle / "prop_assumption.json").exists()
    assert (bundle / "concept_summary.json").exists()
    assert set(airfoil_templates) == {"root", "mid1", "mid2", "tip"}
    assert all("template_id" in payload for payload in airfoil_templates.values())
    assert all("points" in payload for payload in airfoil_templates.values())
    assert prop_assumption["blade_count"] == 2
    assert prop_assumption["diameter_m"] == 3.0
    assert prop_assumption["rpm_range"] == [100.0, 160.0]
    assert concept_summary["selected"] is True
    assert concept_summary["launch"]["status"] in {
        "ok",
        "launch_cl_insufficient",
        "trim_margin_insufficient",
    }
    assert concept_summary["turn"]["status"] in {
        "ok",
        "stall_margin_insufficient",
        "trim_not_feasible",
    }
    assert concept_summary["trim"]["status"] in {"ok", "trim_margin_insufficient"}
    assert concept_summary["local_stall"]["status"] in {"ok", "stall_margin_insufficient"}
    assert isinstance(concept_summary["launch"]["cl_required"], float)
    assert isinstance(concept_summary["turn"]["required_cl"], float)
    assert isinstance(concept_summary["trim"]["margin_deg"], float)
    assert isinstance(concept_summary["local_stall"]["min_margin"], float)


def test_pipeline_default_worker_factory_uses_stubbed_ok_statuses(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        spanwise_loader=lambda concept, stations: {
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
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert summary["worker_backend"] == "python_stubbed"
    assert summary["worker_statuses"]
    assert all(status == "stubbed_ok" for status in summary["worker_statuses"])
    assert all(
        item["worker_statuses"] == ["stubbed_ok"]
        for item in summary["selected_concepts"]
    )
    assert all("launch" in item and "turn" in item for item in summary["selected_concepts"])


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


def test_real_worker_backend_surfaces_as_julia_xfoil_without_running_julia(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    factory_calls: list[dict[str, object]] = []

    result = run_birdman_concept_pipeline(
        config_path=repo_root / "configs" / "birdman_upstream_concept_baseline.yaml",
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **kwargs: factory_calls.append(kwargs)
        or JuliaXFoilWorker(**kwargs),
        spanwise_loader=lambda concept, stations: {"root": {"points": []}},
    )

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert factory_calls[0]["project_dir"] == repo_root
    assert summary["worker_backend"] == "julia_xfoil"
    assert all(item["worker_backend"] == "julia_xfoil" for item in summary["selected_concepts"])
    assert summary["worker_statuses"] == []


def test_pipeline_respects_yaml_controls_for_station_count_prop_and_vsp_exports(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "birdman_upstream_concept_baseline.yaml"
    payload = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    payload["pipeline"]["stations_per_half"] = 9
    payload["pipeline"]["keep_top_n"] = 3
    payload["output"]["export_vsp"] = True
    payload["output"]["export_vsp_for_top_n"] = 2
    payload["prop"]["blade_count"] = 3
    payload["prop"]["diameter_m"] = 3.4
    payload["prop"]["rpm_min"] = 90.0
    payload["prop"]["rpm_max"] = 155.0

    custom_cfg = tmp_path / "concept.yaml"
    custom_cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    result = run_birdman_concept_pipeline(
        config_path=custom_cfg,
        output_dir=tmp_path / "out",
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [
                    {"status": "ok", "polar_points": [], "template_id": query.template_id}
                    for query in queries
                ],
            },
        )(),
        spanwise_loader=lambda concept, stations: {
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
            "mid1": {"points": []},
            "mid2": {"points": []},
            "tip": {"points": []},
        },
    )

    assert len(result.selected_concept_dirs) == 3

    first_bundle = result.selected_concept_dirs[0]
    third_bundle = result.selected_concept_dirs[2]

    stations_csv = (first_bundle / "stations.csv").read_text(encoding="utf-8").strip().splitlines()
    assert len(stations_csv) == 10  # header + 9 stations
    assert stations_csv[0].split(",") == ["y_m", "chord_m", "twist_deg", "dihedral_deg"]

    prop_assumption = json.loads((first_bundle / "prop_assumption.json").read_text(encoding="utf-8"))
    assert prop_assumption["blade_count"] == 3
    assert prop_assumption["diameter_m"] == 3.4
    assert prop_assumption["rpm_range"] == [90.0, 155.0]

    assert (first_bundle / "concept_openvsp.vspscript").exists()
    assert (first_bundle / "concept_openvsp_metadata.json").exists()
    assert (third_bundle / "concept_openvsp.vspscript").exists() is False


def test_pipeline_writes_dihedral_geometry_into_bundle_and_vsp_preview(tmp_path: Path) -> None:
    result = run_birdman_concept_pipeline(
        config_path=Path("configs/birdman_upstream_concept_baseline.yaml"),
        output_dir=tmp_path,
        airfoil_worker_factory=lambda **_: type(
            "FakeWorker",
            (),
            {
                "backend_name": "test_stub",
                "run_queries": lambda self, queries: [],
            },
        )(),
        spanwise_loader=lambda concept, stations: {"root": {"points": []}},
    )

    bundle = result.selected_concept_dirs[0]
    concept_cfg = yaml.safe_load((bundle / "concept_config.yaml").read_text(encoding="utf-8"))
    stations_csv = (bundle / "stations.csv").read_text(encoding="utf-8")

    assert concept_cfg["geometry"]["dihedral_root_deg"] == 0.0
    assert concept_cfg["geometry"]["dihedral_tip_deg"] == 4.0
    assert concept_cfg["geometry"]["dihedral_exponent"] == 1.0
    assert "dihedral_deg" in stations_csv.splitlines()[0]
