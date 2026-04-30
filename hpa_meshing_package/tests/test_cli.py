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
            "--apply-bl-stageback-plus-truncation-focused",
            "--apply-bl-stage-with-termination-guard-8-to-7-focused",
            "--run-bl-candidate-sweep-focused",
        ]
    )
    assert args.command == "shell-v4-half-wing-bl-mesh-macsafe"
    assert args.out == "artifacts/shell_v4"
    assert args.study_level == "BL_macsafe_upper"
    assert args.skip_su2 is True
    assert args.topology_compiler_plan_only is True
    assert args.apply_bl_stageback_plus_truncation_focused is True
    assert args.apply_bl_stage_with_termination_guard_8_to_7_focused is True
    assert args.run_bl_candidate_sweep_focused is True

    default_args = parser.parse_args(
        [
            "shell-v4-half-wing-bl-mesh-macsafe",
            "--out",
            "artifacts/shell_v4",
        ]
    )
    assert default_args.apply_bl_stageback_plus_truncation_focused is False
    assert default_args.apply_bl_stage_with_termination_guard_8_to_7_focused is False
    assert default_args.run_bl_candidate_sweep_focused is False


def test_parser_supports_route_readiness_command():
    parser = build_parser()
    args = parser.parse_args(["route-readiness", "--out", "artifacts/route_readiness"])

    assert args.command == "route-readiness"
    assert args.out == "artifacts/route_readiness"


def test_parser_supports_component_family_smoke_matrix_command():
    parser = build_parser()
    args = parser.parse_args(
        ["component-family-smoke-matrix", "--out", "artifacts/route_smoke"]
    )

    assert args.command == "component-family-smoke-matrix"
    assert args.out == "artifacts/route_smoke"


def test_parser_supports_fairing_solid_mesh_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["fairing-solid-mesh-handoff-smoke", "--out", "artifacts/fairing_smoke"]
    )

    assert args.command == "fairing-solid-mesh-handoff-smoke"
    assert args.out == "artifacts/fairing_smoke"


def test_parser_supports_fairing_solid_real_geometry_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "fairing-solid-real-geometry-smoke",
            "--out",
            "artifacts/fairing_real_geometry_smoke",
            "--source",
            "fairing.vsp3",
        ]
    )

    assert args.command == "fairing-solid-real-geometry-smoke"
    assert args.out == "artifacts/fairing_real_geometry_smoke"
    assert args.source == "fairing.vsp3"


def test_parser_supports_fairing_solid_real_mesh_handoff_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "fairing-solid-real-mesh-handoff-probe",
            "--out",
            "artifacts/fairing_real_mesh_probe",
            "--source",
            "fairing.vsp3",
            "--timeout-seconds",
            "30",
        ]
    )

    assert args.command == "fairing-solid-real-mesh-handoff-probe"
    assert args.out == "artifacts/fairing_real_mesh_probe"
    assert args.source == "fairing.vsp3"
    assert args.timeout_seconds == 30.0


def test_parser_supports_main_wing_mesh_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["main-wing-mesh-handoff-smoke", "--out", "artifacts/main_wing_smoke"]
    )

    assert args.command == "main-wing-mesh-handoff-smoke"
    assert args.out == "artifacts/main_wing_smoke"


def test_parser_supports_main_wing_esp_rebuilt_geometry_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-esp-rebuilt-geometry-smoke",
            "--out",
            "artifacts/main_wing_esp_geometry_smoke",
        ]
    )

    assert args.command == "main-wing-esp-rebuilt-geometry-smoke"
    assert args.out == "artifacts/main_wing_esp_geometry_smoke"


def test_parser_supports_main_wing_real_mesh_handoff_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "main-wing-real-mesh-handoff-probe",
            "--out",
            "artifacts/main_wing_real_mesh_probe",
        ]
    )

    assert args.command == "main-wing-real-mesh-handoff-probe"
    assert args.out == "artifacts/main_wing_real_mesh_probe"


def test_parser_supports_tail_wing_mesh_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["tail-wing-mesh-handoff-smoke", "--out", "artifacts/tail_wing_smoke"]
    )

    assert args.command == "tail-wing-mesh-handoff-smoke"
    assert args.out == "artifacts/tail_wing_smoke"


def test_parser_supports_tail_wing_su2_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["tail-wing-su2-handoff-smoke", "--out", "artifacts/tail_wing_su2_smoke"]
    )

    assert args.command == "tail-wing-su2-handoff-smoke"
    assert args.out == "artifacts/tail_wing_su2_smoke"


def test_parser_supports_tail_wing_esp_rebuilt_geometry_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-esp-rebuilt-geometry-smoke",
            "--out",
            "artifacts/tail_wing_esp_geometry_smoke",
        ]
    )

    assert args.command == "tail-wing-esp-rebuilt-geometry-smoke"
    assert args.out == "artifacts/tail_wing_esp_geometry_smoke"


def test_parser_supports_tail_wing_real_mesh_handoff_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-real-mesh-handoff-probe",
            "--out",
            "artifacts/tail_wing_real_mesh_probe",
        ]
    )

    assert args.command == "tail-wing-real-mesh-handoff-probe"
    assert args.out == "artifacts/tail_wing_real_mesh_probe"


def test_parser_supports_tail_wing_surface_mesh_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-surface-mesh-probe",
            "--out",
            "artifacts/tail_wing_surface_mesh_probe",
        ]
    )

    assert args.command == "tail-wing-surface-mesh-probe"
    assert args.out == "artifacts/tail_wing_surface_mesh_probe"


def test_parser_supports_tail_wing_solidification_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-solidification-probe",
            "--out",
            "artifacts/tail_wing_solidification_probe",
        ]
    )

    assert args.command == "tail-wing-solidification-probe"
    assert args.out == "artifacts/tail_wing_solidification_probe"


def test_parser_supports_tail_wing_explicit_volume_route_probe_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "tail-wing-explicit-volume-route-probe",
            "--out",
            "artifacts/tail_wing_explicit_volume_route_probe",
        ]
    )

    assert args.command == "tail-wing-explicit-volume-route-probe"
    assert args.out == "artifacts/tail_wing_explicit_volume_route_probe"


def test_parser_supports_main_wing_su2_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        ["main-wing-su2-handoff-smoke", "--out", "artifacts/main_wing_su2_smoke"]
    )

    assert args.command == "main-wing-su2-handoff-smoke"
    assert args.out == "artifacts/main_wing_su2_smoke"


def test_parser_supports_fairing_solid_su2_handoff_smoke_command():
    parser = build_parser()
    args = parser.parse_args(
        [
            "fairing-solid-su2-handoff-smoke",
            "--out",
            "artifacts/fairing_su2_smoke",
        ]
    )

    assert args.command == "fairing-solid-su2-handoff-smoke"
    assert args.out == "artifacts/fairing_su2_smoke"


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


def test_python_m_cli_writes_route_readiness_report(tmp_path: Path):
    out_dir = tmp_path / "readiness"
    package_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hpa_meshing.cli",
            "route-readiness",
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
    assert payload["primary_decision"] == "switch_to_component_family_route_architecture"
    assert (out_dir / "component_family_route_readiness.v1.json").exists()
    assert (out_dir / "component_family_route_readiness.v1.md").exists()


def test_python_m_cli_writes_component_family_smoke_matrix_report(tmp_path: Path):
    out_dir = tmp_path / "smoke"
    package_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "hpa_meshing.cli",
            "component-family-smoke-matrix",
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
    assert payload["execution_mode"] == "pre_mesh_dispatch_smoke"
    assert payload["no_gmsh_execution"] is True
    assert (out_dir / "component_family_route_smoke_matrix.v1.json").exists()
    assert (out_dir / "component_family_route_smoke_matrix.v1.md").exists()
