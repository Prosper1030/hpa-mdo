import json
import os
from pathlib import Path
import subprocess
import sys

from hpa_meshing.cli import build_parser


def test_parser_builds():
    parser = build_parser()
    assert parser.prog == "hpa-mesh"


def test_parser_supports_mesh_study_command():
    parser = build_parser()
    args = parser.parse_args(["mesh-study", "--config", "configs/demo.yaml"])
    assert args.command == "mesh-study"
    assert args.config == "configs/demo.yaml"


def test_parser_supports_baseline_freeze_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "baseline-freeze",
            "--baseline-manifest",
            "artifacts/baseline.json",
            "--out",
            "artifacts/regression.json",
        ]
    )
    assert args.command == "baseline-freeze"
    assert args.baseline_manifest == "artifacts/baseline.json"
    assert args.out == "artifacts/regression.json"


def test_parser_supports_baseline_cfd_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "baseline-cfd",
            "--baseline-manifest",
            "artifacts/baseline.json",
            "--out",
            "artifacts/su2_route",
        ]
    )
    assert args.command == "baseline-cfd"
    assert args.baseline_manifest == "artifacts/baseline.json"
    assert args.out == "artifacts/su2_route"


def test_parser_supports_shell_v3_refinement_study_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "shell-v3-refinement-study",
            "--baseline-manifest",
            "artifacts/baseline.json",
            "--out",
            "artifacts/refinement",
        ]
    )
    assert args.command == "shell-v3-refinement-study"
    assert args.baseline_manifest == "artifacts/baseline.json"
    assert args.out == "artifacts/refinement"


def test_parser_supports_shell_v4_half_wing_bl_mesh_macsafe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "shell-v4-half-wing-bl-mesh-macsafe",
            "--out",
            "artifacts/shell_v4",
            "--study-level",
            "BL_macsafe_upper",
            "--skip-su2",
            "--topology-compiler-plan-only",
        ]
    )
    assert args.command == "shell-v4-half-wing-bl-mesh-macsafe"
    assert args.out == "artifacts/shell_v4"
    assert args.study_level == "BL_macsafe_upper"
    assert args.skip_su2 is True
    assert args.topology_compiler_plan_only is True


def test_python_m_cli_runs_validate_geometry(tmp_path: Path):
    geometry = tmp_path / "wing.step"
    geometry.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    out_dir = tmp_path / "out"
    package_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hpa_meshing.cli",
            "validate-geometry",
            "--component",
            "main_wing",
            "--geometry",
            str(geometry),
            "--out",
            str(out_dir),
        ],
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["geometry_family"] == "thin_sheet_lifting_surface"
    assert (out_dir / "report.json").exists()


def test_python_m_cli_reports_experimental_provider_status(tmp_path: Path):
    geometry = tmp_path / "assembly.vsp3"
    geometry.write_text("<vsp3/>", encoding="utf-8")
    out_dir = tmp_path / "out"
    runtime_free_path = tmp_path / "bin"
    runtime_free_path.mkdir()
    package_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env["PATH"] = str(runtime_free_path)
    env.pop("ESP_ROOT", None)
    env.pop("CASROOT", None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hpa_meshing.cli",
            "validate-geometry",
            "--component",
            "aircraft_assembly",
            "--geometry",
            str(geometry),
            "--geometry-provider",
            "esp_rebuilt",
            "--out",
            str(out_dir),
        ],
        cwd=package_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["failure_code"] == "geometry_provider_not_materialized"
    assert payload["geometry_provider"] == "esp_rebuilt"
    assert payload["provider"]["provider_stage"] == "experimental"
    assert payload["provider"]["status"] == "failed"
    assert payload["provider"]["provenance"]["failure_code"] == "esp_runtime_missing"
    assert payload["provider"]["provenance"]["runtime"]["available"] is False
