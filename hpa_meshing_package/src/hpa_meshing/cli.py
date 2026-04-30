from __future__ import annotations

import argparse
from pathlib import Path
import json
import yaml

from .schema import MeshJobConfig, BatchManifest
from .component_family_smoke_matrix import (
    build_component_family_route_smoke_matrix,
    write_component_family_route_smoke_matrix_report,
)
from .fairing_solid_mesh_handoff_smoke import (
    build_fairing_solid_mesh_handoff_smoke_report,
    write_fairing_solid_mesh_handoff_smoke_report,
)
from .fairing_solid_real_geometry_smoke import (
    build_fairing_solid_real_geometry_smoke_report,
    write_fairing_solid_real_geometry_smoke_report,
)
from .fairing_solid_real_mesh_handoff_probe import (
    build_fairing_solid_real_mesh_handoff_probe_report,
    write_fairing_solid_real_mesh_handoff_probe_report,
)
from .fairing_solid_real_su2_handoff_probe import (
    build_fairing_solid_real_su2_handoff_probe_report,
    write_fairing_solid_real_su2_handoff_probe_report,
)
from .fairing_solid_su2_handoff_smoke import (
    build_fairing_solid_su2_handoff_smoke_report,
    write_fairing_solid_su2_handoff_smoke_report,
)
from .main_wing_mesh_handoff_smoke import (
    build_main_wing_mesh_handoff_smoke_report,
    write_main_wing_mesh_handoff_smoke_report,
)
from .main_wing_real_mesh_handoff_probe import (
    build_main_wing_real_mesh_handoff_probe_report,
    write_main_wing_real_mesh_handoff_probe_report,
)
from .main_wing_su2_handoff_smoke import (
    build_main_wing_su2_handoff_smoke_report,
    write_main_wing_su2_handoff_smoke_report,
)
from .main_wing_esp_rebuilt_geometry_smoke import (
    build_main_wing_esp_rebuilt_geometry_smoke_report,
    write_main_wing_esp_rebuilt_geometry_smoke_report,
)
from .tail_wing_mesh_handoff_smoke import (
    build_tail_wing_mesh_handoff_smoke_report,
    write_tail_wing_mesh_handoff_smoke_report,
)
from .tail_wing_su2_handoff_smoke import (
    build_tail_wing_su2_handoff_smoke_report,
    write_tail_wing_su2_handoff_smoke_report,
)
from .tail_wing_esp_rebuilt_geometry_smoke import (
    build_tail_wing_esp_rebuilt_geometry_smoke_report,
    write_tail_wing_esp_rebuilt_geometry_smoke_report,
)
from .tail_wing_real_mesh_handoff_probe import (
    build_tail_wing_real_mesh_handoff_probe_report,
    write_tail_wing_real_mesh_handoff_probe_report,
)
from .tail_wing_surface_mesh_probe import (
    build_tail_wing_surface_mesh_probe_report,
    write_tail_wing_surface_mesh_probe_report,
)
from .tail_wing_solidification_probe import (
    build_tail_wing_solidification_probe_report,
    write_tail_wing_solidification_probe_report,
)
from .tail_wing_explicit_volume_route_probe import (
    build_tail_wing_explicit_volume_route_probe_report,
    write_tail_wing_explicit_volume_route_probe_report,
)
from .frozen_baseline import evaluate_shell_v3_baseline_regression, run_shell_v3_baseline_cfd
from .pipeline import run_job, validate_geometry_only
from .mesh_study import run_mesh_study
from .route_readiness import (
    build_component_family_route_readiness,
    write_component_family_route_readiness_report,
)
from .shell_v3_refinement_study import run_shell_v3_refinement_study
from .shell_v4_half_wing_bl_mesh_macsafe import (
    _default_real_main_wing_source_path,
    _run_shell_v4_bl_candidate_parameter_sweep_focused,
    run_shell_v4_half_wing_bl_mesh_macsafe,
)


def _load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_run(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.config))
    raw["component"] = args.component or raw.get("component")
    raw["geometry"] = args.geometry or raw.get("geometry")
    raw["geometry_provider"] = args.geometry_provider or raw.get("geometry_provider")
    raw["out_dir"] = args.out or raw.get("out_dir")
    config = MeshJobConfig.model_validate(raw)
    result = run_job(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_validate_geometry(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.config)) if args.config else {}
    raw["component"] = args.component or raw.get("component")
    raw["geometry"] = args.geometry or raw.get("geometry")
    raw["geometry_provider"] = args.geometry_provider or raw.get("geometry_provider")
    raw["out_dir"] = args.out or raw.get("out_dir", "out/validate")
    config = MeshJobConfig.model_validate(raw)
    result = validate_geometry_only(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_batch(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.manifest))
    manifest = BatchManifest.model_validate(raw)
    results = [run_job(job) for job in manifest.jobs]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r.get("status") == "success" for r in results) else 2


def cmd_mesh_study(args: argparse.Namespace) -> int:
    raw = _load_yaml(Path(args.config))
    raw["component"] = args.component or raw.get("component")
    raw["geometry"] = args.geometry or raw.get("geometry")
    raw["geometry_provider"] = args.geometry_provider or raw.get("geometry_provider")
    raw["out_dir"] = args.out or raw.get("out_dir")
    config = MeshJobConfig.model_validate(raw)
    result = run_mesh_study(config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict", {}).get("verdict") != "insufficient" else 2


def cmd_baseline_freeze(args: argparse.Namespace) -> int:
    result = evaluate_shell_v3_baseline_regression(
        Path(args.baseline_manifest),
        mesh_handoff_path=None if args.mesh_handoff is None else Path(args.mesh_handoff),
    )
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "pass" else 2


def cmd_baseline_cfd(args: argparse.Namespace) -> int:
    result = run_shell_v3_baseline_cfd(
        Path(args.baseline_manifest),
        out_dir=Path(args.out),
        mesh_handoff_path=None if args.mesh_handoff is None else Path(args.mesh_handoff),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_shell_v3_refinement_study(args: argparse.Namespace) -> int:
    result = run_shell_v3_refinement_study(
        Path(args.baseline_manifest),
        out_dir=Path(args.out),
        mesh_handoff_path=None if args.mesh_handoff is None else Path(args.mesh_handoff),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_shell_v4_half_wing_bl_mesh_macsafe(args: argparse.Namespace) -> int:
    if args.run_bl_candidate_sweep_focused:
        result = _run_shell_v4_bl_candidate_parameter_sweep_focused(
            out_dir=Path(args.out),
            source_path=_default_real_main_wing_source_path(),
            component="main_wing",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "written" else 2

    result = run_shell_v4_half_wing_bl_mesh_macsafe(
        out_dir=Path(args.out),
        study_level=args.study_level,
        run_su2=not args.skip_su2,
        allow_swap_risk=args.allow_swap_risk,
        topology_compiler_gate="plan_only" if args.topology_compiler_plan_only else "off",
        bl_candidate_apply_gate=(
            "stage_with_termination_guard_8_to_7_focused"
            if args.apply_bl_stage_with_termination_guard_8_to_7_focused
            else "stageback_plus_truncation_focused"
            if args.apply_bl_stageback_plus_truncation_focused
            else "off"
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 2


def cmd_route_readiness(args: argparse.Namespace) -> int:
    write_component_family_route_readiness_report(Path(args.out))
    report = build_component_family_route_readiness()
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def cmd_component_family_smoke_matrix(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    write_component_family_route_smoke_matrix_report(out_dir)
    report = build_component_family_route_smoke_matrix(out_dir)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.report_status == "completed" else 2


def cmd_fairing_solid_mesh_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_fairing_solid_mesh_handoff_smoke_report(out_dir)
    write_fairing_solid_mesh_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.smoke_status == "mesh_handoff_pass" else 2


def cmd_fairing_solid_real_geometry_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_fairing_solid_real_geometry_smoke_report(
        out_dir,
        source_path=source_path,
    )
    write_fairing_solid_real_geometry_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.geometry_smoke_status == "geometry_smoke_pass" else 2


def cmd_fairing_solid_real_mesh_handoff_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_fairing_solid_real_mesh_handoff_probe_report(
        out_dir,
        source_path=source_path,
        timeout_seconds=float(args.timeout_seconds),
    )
    write_fairing_solid_real_mesh_handoff_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status in {
        "mesh_handoff_pass",
        "mesh_handoff_blocked",
        "mesh_handoff_timeout",
    } else 2


def cmd_fairing_solid_su2_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_fairing_solid_su2_handoff_smoke_report(out_dir)
    write_fairing_solid_su2_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def cmd_fairing_solid_real_su2_handoff_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    source_mesh_probe_report_path = (
        None
        if args.source_mesh_probe_report is None
        else Path(args.source_mesh_probe_report)
    )
    report = build_fairing_solid_real_su2_handoff_probe_report(
        out_dir,
        source_path=source_path,
        timeout_seconds=float(args.timeout_seconds),
        source_mesh_probe_report_path=source_mesh_probe_report_path,
    )
    write_fairing_solid_real_su2_handoff_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def cmd_main_wing_mesh_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_main_wing_mesh_handoff_smoke_report(out_dir)
    write_main_wing_mesh_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.smoke_status == "mesh_handoff_pass" else 2


def cmd_main_wing_esp_rebuilt_geometry_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_main_wing_esp_rebuilt_geometry_smoke_report(
        out_dir,
        source_path=source_path,
    )
    write_main_wing_esp_rebuilt_geometry_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.geometry_smoke_status == "geometry_smoke_pass" else 2


def cmd_main_wing_real_mesh_handoff_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_main_wing_real_mesh_handoff_probe_report(
        out_dir,
        source_path=source_path,
        timeout_seconds=float(args.timeout_seconds),
    )
    write_main_wing_real_mesh_handoff_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status in {"mesh_handoff_pass", "mesh_handoff_blocked", "mesh_handoff_timeout"} else 2


def cmd_tail_wing_mesh_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_tail_wing_mesh_handoff_smoke_report(out_dir)
    write_tail_wing_mesh_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.smoke_status == "mesh_handoff_pass" else 2


def cmd_tail_wing_su2_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_tail_wing_su2_handoff_smoke_report(out_dir)
    write_tail_wing_su2_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def cmd_tail_wing_esp_rebuilt_geometry_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_esp_rebuilt_geometry_smoke_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_esp_rebuilt_geometry_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.geometry_smoke_status == "geometry_smoke_pass" else 2


def cmd_tail_wing_real_mesh_handoff_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_real_mesh_handoff_probe_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_real_mesh_handoff_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status in {"mesh_handoff_pass", "mesh_handoff_blocked"} else 2


def cmd_tail_wing_surface_mesh_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_surface_mesh_probe_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_surface_mesh_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.probe_status == "surface_mesh_pass" else 2


def cmd_tail_wing_solidification_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_solidification_probe_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_solidification_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.solidification_status in {"solidified", "no_volume_created"} else 2


def cmd_tail_wing_explicit_volume_route_probe(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    source_path = None if args.source is None else Path(args.source)
    report = build_tail_wing_explicit_volume_route_probe_report(
        out_dir,
        source_path=source_path,
    )
    write_tail_wing_explicit_volume_route_probe_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.route_probe_status in {
        "explicit_volume_route_candidate",
        "explicit_volume_route_blocked",
    } else 2


def cmd_main_wing_su2_handoff_smoke(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    report = build_main_wing_su2_handoff_smoke_report(out_dir)
    write_main_wing_su2_handoff_smoke_report(out_dir, report=report)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.materialization_status == "su2_handoff_written" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hpa-mesh")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--component", type=str)
    run.add_argument("--geometry", type=str)
    run.add_argument("--geometry-provider", type=str)
    run.add_argument("--config", type=str, required=True)
    run.add_argument("--out", type=str)
    run.set_defaults(func=cmd_run)

    val = sub.add_parser("validate-geometry")
    val.add_argument("--component", type=str, required=True)
    val.add_argument("--geometry", type=str, required=True)
    val.add_argument("--geometry-provider", type=str)
    val.add_argument("--config", type=str)
    val.add_argument("--out", type=str)
    val.set_defaults(func=cmd_validate_geometry)

    batch = sub.add_parser("batch")
    batch.add_argument("--manifest", type=str, required=True)
    batch.set_defaults(func=cmd_batch)

    mesh_study = sub.add_parser("mesh-study")
    mesh_study.add_argument("--component", type=str)
    mesh_study.add_argument("--geometry", type=str)
    mesh_study.add_argument("--geometry-provider", type=str)
    mesh_study.add_argument("--config", type=str, required=True)
    mesh_study.add_argument("--out", type=str)
    mesh_study.set_defaults(func=cmd_mesh_study)

    baseline_freeze = sub.add_parser("baseline-freeze")
    baseline_freeze.add_argument("--baseline-manifest", type=str, required=True)
    baseline_freeze.add_argument("--mesh-handoff", type=str)
    baseline_freeze.add_argument("--out", type=str)
    baseline_freeze.set_defaults(func=cmd_baseline_freeze)

    baseline_cfd = sub.add_parser("baseline-cfd")
    baseline_cfd.add_argument("--baseline-manifest", type=str, required=True)
    baseline_cfd.add_argument("--mesh-handoff", type=str)
    baseline_cfd.add_argument("--out", type=str, required=True)
    baseline_cfd.set_defaults(func=cmd_baseline_cfd)

    refinement = sub.add_parser("shell-v3-refinement-study")
    refinement.add_argument("--baseline-manifest", type=str, required=True)
    refinement.add_argument("--mesh-handoff", type=str)
    refinement.add_argument("--out", type=str, required=True)
    refinement.set_defaults(func=cmd_shell_v3_refinement_study)

    shell_v4 = sub.add_parser("shell-v4-half-wing-bl-mesh-macsafe")
    shell_v4.add_argument("--out", type=str, required=True)
    shell_v4.add_argument(
        "--study-level",
        type=str,
        default="BL_macsafe_baseline",
        choices=["BL_macsafe_baseline", "BL_macsafe_upper"],
    )
    shell_v4.add_argument("--skip-su2", action="store_true")
    shell_v4.add_argument("--allow-swap-risk", action="store_true")
    shell_v4.add_argument("--topology-compiler-plan-only", action="store_true")
    shell_v4.add_argument("--apply-bl-stageback-plus-truncation-focused", action="store_true")
    shell_v4.add_argument("--apply-bl-stage-with-termination-guard-8-to-7-focused", action="store_true")
    shell_v4.add_argument("--run-bl-candidate-sweep-focused", action="store_true")
    shell_v4.set_defaults(func=cmd_shell_v4_half_wing_bl_mesh_macsafe)

    readiness = sub.add_parser("route-readiness")
    readiness.add_argument("--out", type=str, required=True)
    readiness.set_defaults(func=cmd_route_readiness)

    smoke_matrix = sub.add_parser("component-family-smoke-matrix")
    smoke_matrix.add_argument("--out", type=str, required=True)
    smoke_matrix.set_defaults(func=cmd_component_family_smoke_matrix)

    fairing_smoke = sub.add_parser("fairing-solid-mesh-handoff-smoke")
    fairing_smoke.add_argument("--out", type=str, required=True)
    fairing_smoke.set_defaults(func=cmd_fairing_solid_mesh_handoff_smoke)

    fairing_real_geometry_smoke = sub.add_parser("fairing-solid-real-geometry-smoke")
    fairing_real_geometry_smoke.add_argument("--out", type=str, required=True)
    fairing_real_geometry_smoke.add_argument("--source", type=str)
    fairing_real_geometry_smoke.set_defaults(func=cmd_fairing_solid_real_geometry_smoke)

    fairing_real_mesh_probe = sub.add_parser("fairing-solid-real-mesh-handoff-probe")
    fairing_real_mesh_probe.add_argument("--out", type=str, required=True)
    fairing_real_mesh_probe.add_argument("--source", type=str)
    fairing_real_mesh_probe.add_argument("--timeout-seconds", type=float, default=60.0)
    fairing_real_mesh_probe.set_defaults(func=cmd_fairing_solid_real_mesh_handoff_probe)

    fairing_su2_smoke = sub.add_parser("fairing-solid-su2-handoff-smoke")
    fairing_su2_smoke.add_argument("--out", type=str, required=True)
    fairing_su2_smoke.set_defaults(func=cmd_fairing_solid_su2_handoff_smoke)

    fairing_real_su2_probe = sub.add_parser("fairing-solid-real-su2-handoff-probe")
    fairing_real_su2_probe.add_argument("--out", type=str, required=True)
    fairing_real_su2_probe.add_argument("--source", type=str)
    fairing_real_su2_probe.add_argument("--timeout-seconds", type=float, default=60.0)
    fairing_real_su2_probe.add_argument("--source-mesh-probe-report", type=str)
    fairing_real_su2_probe.set_defaults(func=cmd_fairing_solid_real_su2_handoff_probe)

    main_wing_smoke = sub.add_parser("main-wing-mesh-handoff-smoke")
    main_wing_smoke.add_argument("--out", type=str, required=True)
    main_wing_smoke.set_defaults(func=cmd_main_wing_mesh_handoff_smoke)

    main_wing_esp_geometry_smoke = sub.add_parser("main-wing-esp-rebuilt-geometry-smoke")
    main_wing_esp_geometry_smoke.add_argument("--out", type=str, required=True)
    main_wing_esp_geometry_smoke.add_argument("--source", type=str)
    main_wing_esp_geometry_smoke.set_defaults(func=cmd_main_wing_esp_rebuilt_geometry_smoke)

    main_wing_real_mesh_probe = sub.add_parser("main-wing-real-mesh-handoff-probe")
    main_wing_real_mesh_probe.add_argument("--out", type=str, required=True)
    main_wing_real_mesh_probe.add_argument("--source", type=str)
    main_wing_real_mesh_probe.add_argument("--timeout-seconds", type=float, default=45.0)
    main_wing_real_mesh_probe.set_defaults(func=cmd_main_wing_real_mesh_handoff_probe)

    tail_wing_smoke = sub.add_parser("tail-wing-mesh-handoff-smoke")
    tail_wing_smoke.add_argument("--out", type=str, required=True)
    tail_wing_smoke.set_defaults(func=cmd_tail_wing_mesh_handoff_smoke)

    tail_wing_su2_smoke = sub.add_parser("tail-wing-su2-handoff-smoke")
    tail_wing_su2_smoke.add_argument("--out", type=str, required=True)
    tail_wing_su2_smoke.set_defaults(func=cmd_tail_wing_su2_handoff_smoke)

    tail_wing_esp_geometry_smoke = sub.add_parser("tail-wing-esp-rebuilt-geometry-smoke")
    tail_wing_esp_geometry_smoke.add_argument("--out", type=str, required=True)
    tail_wing_esp_geometry_smoke.add_argument("--source", type=str)
    tail_wing_esp_geometry_smoke.set_defaults(func=cmd_tail_wing_esp_rebuilt_geometry_smoke)

    tail_wing_real_mesh_probe = sub.add_parser("tail-wing-real-mesh-handoff-probe")
    tail_wing_real_mesh_probe.add_argument("--out", type=str, required=True)
    tail_wing_real_mesh_probe.add_argument("--source", type=str)
    tail_wing_real_mesh_probe.set_defaults(func=cmd_tail_wing_real_mesh_handoff_probe)

    tail_wing_surface_mesh_probe = sub.add_parser("tail-wing-surface-mesh-probe")
    tail_wing_surface_mesh_probe.add_argument("--out", type=str, required=True)
    tail_wing_surface_mesh_probe.add_argument("--source", type=str)
    tail_wing_surface_mesh_probe.set_defaults(func=cmd_tail_wing_surface_mesh_probe)

    tail_wing_solidification_probe = sub.add_parser("tail-wing-solidification-probe")
    tail_wing_solidification_probe.add_argument("--out", type=str, required=True)
    tail_wing_solidification_probe.add_argument("--source", type=str)
    tail_wing_solidification_probe.set_defaults(func=cmd_tail_wing_solidification_probe)

    tail_wing_explicit_volume_route_probe = sub.add_parser(
        "tail-wing-explicit-volume-route-probe"
    )
    tail_wing_explicit_volume_route_probe.add_argument("--out", type=str, required=True)
    tail_wing_explicit_volume_route_probe.add_argument("--source", type=str)
    tail_wing_explicit_volume_route_probe.set_defaults(
        func=cmd_tail_wing_explicit_volume_route_probe
    )

    main_wing_su2_smoke = sub.add_parser("main-wing-su2-handoff-smoke")
    main_wing_su2_smoke.add_argument("--out", type=str, required=True)
    main_wing_su2_smoke.set_defaults(func=cmd_main_wing_su2_handoff_smoke)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
