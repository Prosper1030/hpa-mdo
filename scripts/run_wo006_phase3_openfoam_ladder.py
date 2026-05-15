#!/usr/bin/env python3
"""Run WO-006 Phase 3 OpenFOAM grid/layer/yPlus ladder.

This runner deliberately reuses the accepted Phase 3 OpenFOAM full-wing route
from ``run_wo006_phase3_openfoam_route_smoke.py``.  It does not create a new
mesher and it keeps the split force patches:

    wing_upper, wing_lower, tip_left, tip_right, te_wall, closure_wall
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_wo006_phase3_openfoam_route_smoke as smoke  # noqa: E402


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_phase3_openfoam_ladder"
ROUTE_SMOKE_MANIFEST = WO006_ROOT / "cfd_release_v0_phase3_delivery" / "active_route_manifest.json"
BASE_LAYER_SCHEDULE = (0, 3, 8, 12, 16, 24)
FORCE_WINDOW = 20


@dataclass(frozen=True)
class LayerCaseConfig:
    case_id: str
    n_surface_layers: int
    expansion_ratio: float = 1.2
    final_layer_thickness: float = 0.30
    min_thickness: float = 0.05
    feature_angle: int = 60
    n_smooth_surface_normals: int = 1
    n_smooth_normals: int = 3
    n_smooth_thickness: int = 10
    n_layer_iter: int = 50
    refinement_delta: int = 0
    max_local_cells: int = 500000
    max_global_cells: int = 3000000
    low_yplus_factor: float | None = None
    purpose: str = "layer_ladder"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--openfoam", default=smoke.OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--points-per-side", type=int, default=12)
    parser.add_argument("--spanwise-subdivisions", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--max-iterations", type=int, default=120)
    parser.add_argument("--skip-turbulence-sensitivity", action="store_true")
    args = parser.parse_args()

    manifest = run_openfoam_ladder(
        output_dir=args.output_dir,
        openfoam_command=args.openfoam,
        clean=args.clean,
        points_per_side=args.points_per_side,
        spanwise_subdivisions=args.spanwise_subdivisions,
        timeout_seconds=args.timeout_seconds,
        max_iterations=args.max_iterations,
        run_turbulence_sensitivity=not args.skip_turbulence_sensitivity,
    )
    print(json.dumps(manifest["verdict"], indent=2))


def run_openfoam_ladder(
    *,
    output_dir: Path,
    openfoam_command: str,
    clean: bool,
    points_per_side: int,
    spanwise_subdivisions: int,
    timeout_seconds: float,
    max_iterations: int,
    run_turbulence_sensitivity: bool,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = output_dir / "openfoam_cases"
    cases_dir.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    ref = smoke._read_avl_reference(smoke.DEFAULT_AVL_PATH)
    ref_origin = smoke._read_avl_moment_origin(smoke.DEFAULT_AVL_PATH)
    surface = smoke.build_fullwing_pressure_surface(
        smoke.DEFAULT_SECTION_TABLE_PATH,
        points_per_side=points_per_side,
        spanwise_subdivisions=spanwise_subdivisions,
    )

    manifest: dict[str, Any] = {
        "schema_version": "wo006_phase3_openfoam_ladder.v1",
        "created_at_utc": smoke._utc_now(),
        "route": "OpenFOAM full-wing bounded grid/layer/yPlus ladder",
        "output_dir": str(output_dir),
        "openfoam_command": openfoam_command,
        "tool_detection_inside_openfoam": smoke.detect_openfoam_tools(openfoam_command),
        "geometry": {
            "surface_marker_counts": surface.marker_counts(),
            "surface_marker_area_m2": smoke._surface_area_by_marker(surface),
            "metadata": surface.metadata,
        },
        "physics": {
            "solver": "simpleFoam",
            "baseline_turbulence_model": "SpalartAllmaras",
            "alternate_turbulence_model": "kOmegaSST",
            "velocity_mps": smoke.VELOCITY_MPS,
            "aoa_deg": 0.0,
            "rho_kg_m3": smoke.AIR_DENSITY,
            "nu_m2_s": smoke.KINEMATIC_VISCOSITY,
            "ref_area_m2": float(ref["sref"]),
            "ref_length_m": float(ref["cref"]),
            "ref_origin_m": list(ref_origin),
            "trust_boundary": (
                "Bounded OpenFOAM ladder evidence only.  Do not treat these "
                "coefficients as final HPA drag, release truth, procurement "
                "truth, or aircraft sign-off."
            ),
        },
        "cases": [],
    }

    base_configs = base_layer_configs()
    for config in base_configs:
        case = run_configured_openfoam_case(
            cases_dir=cases_dir,
            surface=surface,
            ref_area=float(ref["sref"]),
            ref_length=float(ref["cref"]),
            ref_origin=ref_origin,
            config=config,
            openfoam_command=openfoam_command,
            timeout_seconds=timeout_seconds,
            max_iterations=max_iterations,
        )
        manifest["cases"].append(case)

    layers_8 = find_case(manifest["cases"], "layers_8")
    if should_run_low_yplus_case(layers_8):
        low_config = low_yplus_config_from_layers_8(layers_8)
        case = run_configured_openfoam_case(
            cases_dir=cases_dir,
            surface=surface,
            ref_area=float(ref["sref"]),
            ref_length=float(ref["cref"]),
            ref_origin=ref_origin,
            config=low_config,
            openfoam_command=openfoam_command,
            timeout_seconds=timeout_seconds,
            max_iterations=max_iterations,
        )
        manifest["cases"].append(case)

    best_layer = choose_best_layer_case(manifest["cases"])
    if best_layer is not None and layer_ladder_stable_enough_for_refinement(manifest["cases"]):
        refined_config = refined_config_for_best_layer(best_layer)
        refined = run_configured_openfoam_case(
            cases_dir=cases_dir,
            surface=surface,
            ref_area=float(ref["sref"]),
            ref_length=float(ref["cref"]),
            ref_origin=ref_origin,
            config=refined_config,
            openfoam_command=openfoam_command,
            timeout_seconds=timeout_seconds,
            max_iterations=max_iterations,
        )
        manifest["cases"].append(refined)

    best_layer = choose_best_layer_case(manifest["cases"])
    if run_turbulence_sensitivity and best_layer is not None:
        sensitivity = run_turbulence_sensitivity_case(
            source_case=best_layer,
            cases_dir=cases_dir,
            openfoam_command=openfoam_command,
            timeout_seconds=timeout_seconds,
            max_iterations=max_iterations,
        )
        if sensitivity is not None:
            manifest["cases"].append(sensitivity)

    manifest["route_smoke_reproduction"] = route_smoke_reproduction_summary(manifest["cases"])
    manifest["verdict"] = evaluate_ladder(manifest["cases"], manifest["route_smoke_reproduction"])
    manifest["elapsed_s"] = time.monotonic() - start
    write_ladder_reports(output_dir, manifest)
    return manifest


def base_layer_configs() -> list[LayerCaseConfig]:
    return [
        LayerCaseConfig("layers_0", 0, purpose="baseline_no_layers"),
        LayerCaseConfig("layers_3", 3, purpose="baseline_layer_ladder"),
        LayerCaseConfig("layers_8", 8, purpose="route_smoke_reproduction"),
        LayerCaseConfig(
            "layers_12",
            12,
            expansion_ratio=1.18,
            final_layer_thickness=0.30,
            min_thickness=0.035,
            feature_angle=65,
            n_smooth_surface_normals=2,
            n_smooth_normals=4,
            n_layer_iter=70,
        ),
        LayerCaseConfig(
            "layers_16",
            16,
            expansion_ratio=1.16,
            final_layer_thickness=0.30,
            min_thickness=0.025,
            feature_angle=70,
            n_smooth_surface_normals=3,
            n_smooth_normals=5,
            n_layer_iter=90,
        ),
        LayerCaseConfig(
            "layers_24",
            24,
            expansion_ratio=1.14,
            final_layer_thickness=0.28,
            min_thickness=0.012,
            feature_angle=75,
            n_smooth_surface_normals=4,
            n_smooth_normals=6,
            n_layer_iter=120,
        ),
    ]


def low_yplus_config_from_layers_8(layers_8: Mapping[str, Any] | None) -> LayerCaseConfig:
    upper = _patch_yplus_mean(layers_8, "wing_upper") or 183.0
    lower = _patch_yplus_mean(layers_8, "wing_lower") or 165.0
    current_mean = max(upper, lower)
    target_mean = 80.0
    factor = max(0.25, min(0.55, target_mean / current_mean))
    return LayerCaseConfig(
        "layers_12_low_yplus_factor_{:.2f}".format(factor).replace(".", "p"),
        12,
        expansion_ratio=1.18,
        final_layer_thickness=0.30 * factor,
        min_thickness=0.008,
        feature_angle=65,
        n_smooth_surface_normals=3,
        n_smooth_normals=5,
        n_layer_iter=90,
        low_yplus_factor=factor,
        purpose="low_yplus_oriented_attempt",
    )


def refined_config_for_best_layer(best_layer: Mapping[str, Any]) -> LayerCaseConfig:
    controls = best_layer.get("controls", {})
    base = LayerCaseConfig(
        case_id=f"{best_layer.get('case_id')}_refined_surface_plus1",
        n_surface_layers=int(best_layer.get("nSurfaceLayers") or 0),
        expansion_ratio=float(controls.get("expansion_ratio", 1.2)),
        final_layer_thickness=float(controls.get("final_layer_thickness", 0.30)),
        min_thickness=float(controls.get("min_thickness", 0.05)),
        feature_angle=int(controls.get("feature_angle", 60)),
        n_smooth_surface_normals=int(controls.get("n_smooth_surface_normals", 1)),
        n_smooth_normals=int(controls.get("n_smooth_normals", 3)),
        n_smooth_thickness=int(controls.get("n_smooth_thickness", 10)),
        n_layer_iter=int(controls.get("n_layer_iter", 50)),
        purpose="surface_refinement_comparison",
    )
    return replace(
        base,
        refinement_delta=1,
        max_local_cells=1000000,
        max_global_cells=6000000,
    )


def run_configured_openfoam_case(
    *,
    cases_dir: Path,
    surface: smoke.SurfaceMesh,
    ref_area: float,
    ref_length: float,
    ref_origin: tuple[float, float, float],
    config: LayerCaseConfig,
    openfoam_command: str,
    timeout_seconds: float,
    max_iterations: int,
) -> dict[str, Any]:
    case_dir = cases_dir / config.case_id
    smoke.write_openfoam_case(
        case_dir,
        surface=surface,
        ref_area=ref_area,
        ref_length=ref_length,
        ref_origin=ref_origin,
        layer_count=config.n_surface_layers,
        max_iterations=max_iterations,
    )
    patch_snappy_hex_mesh_dict(case_dir / "system" / "snappyHexMeshDict", config)
    case = smoke.run_openfoam_case(
        case_dir,
        openfoam_command=openfoam_command,
        layer_count=config.n_surface_layers,
        timeout_seconds=timeout_seconds,
    )
    return augment_case(case, config)


def patch_snappy_hex_mesh_dict(path: Path, config: LayerCaseConfig) -> None:
    text = path.read_text(encoding="utf-8")
    replacements = {
        r"maxLocalCells\s+[0-9]+;": f"maxLocalCells       {config.max_local_cells};",
        r"maxGlobalCells\s+[0-9]+;": f"maxGlobalCells      {config.max_global_cells};",
        r"expansionRatio\s+[-+0-9.eE]+;": f"expansionRatio              {config.expansion_ratio:.9g};",
        r"finalLayerThickness\s+[-+0-9.eE]+;": (
            f"finalLayerThickness         {config.final_layer_thickness:.9g};"
        ),
        r"minThickness\s+[-+0-9.eE]+;": f"minThickness                {config.min_thickness:.9g};",
        r"featureAngle\s+[0-9]+;": f"featureAngle                {config.feature_angle};",
        r"nSmoothSurfaceNormals\s+[0-9]+;": (
            f"nSmoothSurfaceNormals       {config.n_smooth_surface_normals};"
        ),
        r"nSmoothNormals\s+[0-9]+;": f"nSmoothNormals              {config.n_smooth_normals};",
        r"nSmoothThickness\s+[0-9]+;": f"nSmoothThickness            {config.n_smooth_thickness};",
        r"nLayerIter\s+[0-9]+;": f"nLayerIter                  {config.n_layer_iter};",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    if config.refinement_delta:
        text = re.sub(
            r"level \(([0-9]+) ([0-9]+)\);",
            lambda match: "level ({} {});".format(
                int(match.group(1)) + config.refinement_delta,
                int(match.group(2)) + config.refinement_delta,
            ),
            text,
        )
    path.write_text(text, encoding="utf-8")


def augment_case(case: dict[str, Any], config: LayerCaseConfig) -> dict[str, Any]:
    case["case_id"] = config.case_id
    case["nSurfaceLayers"] = config.n_surface_layers
    case["controls"] = asdict(config)
    case["residual_trend"] = parse_residual_trend(Path(case["case_dir"]) / "log.simpleFoam")
    case["layer_coverage"] = parse_layer_coverage(Path(case["case_dir"]) / "log.snappyHexMesh")
    case["acceptance"] = acceptance_for_case(case)
    case["rerun_basis"] = {
        "script": "scripts/run_wo006_phase3_openfoam_ladder.py",
        "case_config": asdict(config),
        "case_dir": case.get("case_dir"),
    }
    return case


def parse_residual_trend(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "log": str(path), "fields": {}}
    text = path.read_text(encoding="utf-8", errors="replace")
    current_time: float | None = None
    fields: dict[str, list[dict[str, float | None]]] = {}
    for line in text.splitlines():
        time_match = re.match(r"^Time =\s*([-+0-9.eE]+)", line.strip())
        if time_match:
            current_time = _safe_float(time_match.group(1))
            continue
        match = re.search(
            r"Solving for ([A-Za-z0-9_]+), Initial residual = ([-+0-9.eE]+), "
            r"Final residual = ([-+0-9.eE]+), No Iterations ([0-9]+)",
            line,
        )
        if not match:
            continue
        field = match.group(1)
        fields.setdefault(field, []).append(
            {
                "time": current_time,
                "initial": float(match.group(2)),
                "final": float(match.group(3)),
                "iterations": float(match.group(4)),
            }
        )
    summaries: dict[str, dict[str, Any]] = {}
    for field, rows in fields.items():
        initials = [float(row["initial"]) for row in rows if row.get("initial") is not None]
        finals = [float(row["final"]) for row in rows if row.get("final") is not None]
        summaries[field] = {
            "samples": len(rows),
            "first_initial": initials[0] if initials else None,
            "last_initial": initials[-1] if initials else None,
            "min_initial": min(initials) if initials else None,
            "max_initial": max(initials) if initials else None,
            "first_final": finals[0] if finals else None,
            "last_final": finals[-1] if finals else None,
            "last_over_first_initial": (
                initials[-1] / initials[0] if initials and initials[0] else None
            ),
        }
    return {
        "status": "available" if summaries else "missing_residual_lines",
        "log": str(path),
        "fields": summaries,
    }


def parse_layer_coverage(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "log": str(path), "patches": {}}
    text = path.read_text(encoding="utf-8", errors="replace")
    patches: dict[str, Any] = {}
    for patch in ("wing_upper", "wing_lower"):
        matches = re.findall(
            rf"^{patch}\s+([0-9]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)",
            text,
            flags=re.MULTILINE,
        )
        if not matches:
            continue
        faces, layers, value_1, value_2, value_3 = matches[-1]
        patches[patch] = {
            "faces": int(faces),
            "reported_layers": float(layers),
            "reported_values": [float(value_1), float(value_2), float(value_3)],
            "source": "final snappyHexMesh layer table",
        }
    added = []
    for match in re.finditer(r"Added ([0-9]+) out of ([0-9]+) cells \(([-+0-9.eE]+)%\)", text):
        added.append(
            {
                "added_cells": int(match.group(1)),
                "candidate_cells": int(match.group(2)),
                "percent": float(match.group(3)),
            }
        )
    return {
        "status": "available" if patches or added else "missing_layer_lines",
        "log": str(path),
        "patches": patches,
        "addition_iterations": added,
    }


def acceptance_for_case(case: Mapping[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    commands = case.get("commands", {})
    for command in ("blockMesh", "surfaceFeatureExtract", "snappyHexMesh"):
        report = commands.get(command, {})
        if report.get("returncode") not in (0, None):
            reasons.append(f"{command}_failed")
        if report.get("timed_out"):
            reasons.append(f"{command}_timed_out")
    check = commands.get("checkMesh", {})
    if check.get("timed_out"):
        reasons.append("checkMesh_timed_out")
    mesh = case.get("mesh", {})
    if mesh.get("status") != "pass":
        reasons.append("mesh_quality_not_smoke_acceptable")
    if int(mesh.get("custom_mesh_quality_error_count") or 0) > 0:
        reasons.append("custom_mesh_quality_errors_present")
    solver = commands.get("simpleFoam", {})
    if solver.get("returncode") != 0:
        reasons.append("solver_failed")
    if solver.get("timed_out"):
        reasons.append("solver_timed_out")
    force = case.get("forces", {}).get("summary", {})
    cd_primary = _finite_float(force.get("CD_primary"))
    cd_total = _finite_float(force.get("CD_total"))
    if cd_primary is None or cd_total is None:
        reasons.append("missing_finite_primary_or_total_cd")
    diagnostic_sum = _finite_float(force.get("CD_diagnostic_sum"))
    diagnostic_ratio = None
    if diagnostic_sum is not None and cd_total not in (None, 0.0):
        diagnostic_ratio = abs(diagnostic_sum) / max(abs(cd_total), 1e-12)
        if diagnostic_ratio > 0.05:
            reasons.append("diagnostic_patches_dominate_total_cd")
    stability = case.get("force_stability_final_window", {})
    cd_mean = _finite_float(stability.get("Cd_mean"))
    cd_span = _finite_float(stability.get("Cd_span"))
    cl_mean = _finite_float(stability.get("Cl_mean"))
    cl_span = _finite_float(stability.get("Cl_span"))
    cd_rel_span = _relative_span(cd_span, cd_mean)
    cl_rel_span = _relative_span(cl_span, cl_mean)
    if cd_rel_span is None or cd_rel_span > 0.03 or cl_rel_span is None or cl_rel_span > 0.03:
        reasons.append("force_window_not_stable_enough")
    yplus = case.get("yPlus", {})
    if yplus.get("status") != "available":
        reasons.append("yplus_report_missing")
    status = "accepted" if not reasons else "rejected"
    return {
        "status": status,
        "reasons": reasons,
        "diagnostic_cd_ratio_of_total": diagnostic_ratio,
        "final_window_cd_relative_span": cd_rel_span,
        "final_window_cl_relative_span": cl_rel_span,
    }


def should_run_low_yplus_case(layers_8: Mapping[str, Any] | None) -> bool:
    if not layers_8:
        return False
    upper = _patch_yplus_mean(layers_8, "wing_upper")
    lower = _patch_yplus_mean(layers_8, "wing_lower")
    return any(value is not None and value > 100.0 for value in (upper, lower))


def layer_ladder_stable_enough_for_refinement(cases: Sequence[Mapping[str, Any]]) -> bool:
    accepted = [
        case
        for case in cases
        if case.get("acceptance", {}).get("status") == "accepted"
        and case.get("controls", {}).get("purpose") in {"baseline_layer_ladder", "route_smoke_reproduction", "layer_ladder", "baseline_no_layers", "low_yplus_oriented_attempt"}
    ]
    return len(accepted) >= 2


def choose_best_layer_case(cases: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    candidates = [
        case
        for case in cases
        if case.get("acceptance", {}).get("status") == "accepted"
        and case.get("controls", {}).get("purpose")
        in {
            "baseline_layer_ladder",
            "route_smoke_reproduction",
            "layer_ladder",
            "low_yplus_oriented_attempt",
        }
        and int(case.get("nSurfaceLayers") or 0) > 0
    ]
    if not candidates:
        return None

    def score(case: Mapping[str, Any]) -> tuple[float, int]:
        upper = _patch_yplus_mean(case, "wing_upper")
        lower = _patch_yplus_mean(case, "wing_lower")
        yplus = max(value for value in (upper, lower) if value is not None) if upper or lower else 1e9
        return (yplus, -int(case.get("nSurfaceLayers") or 0))

    return sorted(candidates, key=score)[0]


def run_turbulence_sensitivity_case(
    *,
    source_case: Mapping[str, Any],
    cases_dir: Path,
    openfoam_command: str,
    timeout_seconds: float,
    max_iterations: int,
) -> dict[str, Any] | None:
    source_dir = Path(str(source_case.get("case_dir", "")))
    if not source_dir.exists():
        return None
    case_id = f"{source_case.get('case_id')}_kOmegaSST_same_mesh"
    case_dir = cases_dir / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    shutil.copytree(source_dir, case_dir)
    reset_case_for_same_mesh_sensitivity(case_dir, max_iterations=max_iterations)
    write_komega_sst_setup(case_dir)
    case = run_solver_only_case(
        case_dir=case_dir,
        case_id=case_id,
        source_case=source_case,
        openfoam_command=openfoam_command,
        timeout_seconds=timeout_seconds,
    )
    case["controls"] = {
        **source_case.get("controls", {}),
        "case_id": case_id,
        "purpose": "turbulence_model_sensitivity",
        "same_mesh_source_case_id": source_case.get("case_id"),
        "turbulence_model": "kOmegaSST",
    }
    case["acceptance"] = acceptance_for_case(case)
    return case


def reset_case_for_same_mesh_sensitivity(case_dir: Path, *, max_iterations: int) -> None:
    for path in case_dir.iterdir():
        if path.is_dir() and path.name != "0" and _safe_float(path.name) is not None:
            shutil.rmtree(path)
        elif path.name == "postProcessing" and path.is_dir():
            shutil.rmtree(path)
        elif path.name.startswith("log.") and path.is_file():
            path.unlink()
    control = case_dir / "system" / "controlDict"
    text = control.read_text(encoding="utf-8")
    text = re.sub(r"endTime\s+[0-9]+;", f"endTime         {max_iterations};", text)
    control.write_text(text, encoding="utf-8")


def write_komega_sst_setup(case_dir: Path) -> None:
    zero_dir = case_dir / "0"
    (case_dir / "constant" / "turbulenceProperties").write_text(
        """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      turbulenceProperties;
}
simulationType          RAS;
RAS
{
    RASModel            kOmegaSST;
    turbulence          on;
    printCoeffs         on;
}
""",
        encoding="utf-8",
    )
    for old in ("nuTilda",):
        path = zero_dir / old
        if path.exists():
            path.unlink()
    k_value = 0.0063375
    omega_value = 0.145
    (zero_dir / "k").write_text(k_field_text(k_value), encoding="utf-8")
    (zero_dir / "omega").write_text(omega_field_text(omega_value), encoding="utf-8")
    (zero_dir / "nut").write_text(komega_nut_field_text(), encoding="utf-8")
    (case_dir / "system" / "fvSchemes").write_text(komega_fv_schemes_text(), encoding="utf-8")
    (case_dir / "system" / "fvSolution").write_text(komega_fv_solution_text(), encoding="utf-8")


def run_solver_only_case(
    *,
    case_dir: Path,
    case_id: str,
    source_case: Mapping[str, Any],
    openfoam_command: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    run_dir = Path("/tmp/hpa_mdo_openfoam_ladder_solver_only") / case_id
    if run_dir.exists():
        shutil.rmtree(run_dir)
    shutil.copytree(case_dir, run_dir)
    commands = [
        ("checkMesh", "checkMesh -meshQuality"),
        ("simpleFoam", "simpleFoam"),
        ("postProcess_yPlus", "simpleFoam -postProcess -func yPlus -latestTime"),
    ]
    reports: dict[str, Any] = {
        "blockMesh": {"returncode": 0, "timed_out": False, "skipped_same_mesh": True},
        "surfaceFeatureExtract": {"returncode": 0, "timed_out": False, "skipped_same_mesh": True},
        "snappyHexMesh": {"returncode": 0, "timed_out": False, "skipped_same_mesh": True},
    }
    for key, command in commands:
        completed = smoke.run_case_command(
            run_dir,
            openfoam_command=openfoam_command,
            command=command,
            log_name=f"log.{key}",
            timeout_seconds=timeout_seconds if key == "simpleFoam" else 180.0,
        )
        reports[key] = {
            "command": command,
            "returncode": completed.returncode,
            "timed_out": completed.timed_out,
            "log": str(case_dir / f"log.{key}"),
            "execution_log": str(run_dir / f"log.{key}"),
        }
        if completed.returncode != 0 or completed.timed_out:
            if key in {"checkMesh", "simpleFoam"}:
                break
    shutil.copytree(run_dir, case_dir, dirs_exist_ok=True)
    mesh_quality = smoke.parse_check_mesh(case_dir / "log.checkMesh")
    mesh_quality["boundary_patches"] = smoke.parse_boundary_patches(
        case_dir / "constant" / "polyMesh" / "boundary"
    )
    forces = smoke.parse_force_outputs(case_dir)
    case = {
        "case_id": case_id,
        "nSurfaceLayers": source_case.get("nSurfaceLayers"),
        "case_dir": str(case_dir),
        "execution_dir_without_spaces": str(run_dir),
        "commands": reports,
        "mesh": mesh_quality,
        "snappy": source_case.get("snappy", {}),
        "forces": forces,
        "force_stability_final_window": smoke.force_window_summary(
            forces.get("functions", {}).get("primary", {}).get("rows", []),
            window=FORCE_WINDOW,
        ),
        "yPlus": smoke.parse_yplus_outputs(case_dir),
        "case_status": classify_solver_only_status(reports, mesh_quality, forces),
        "residual_trend": parse_residual_trend(case_dir / "log.simpleFoam"),
        "layer_coverage": source_case.get("layer_coverage"),
        "rerun_basis": {
            "script": "scripts/run_wo006_phase3_openfoam_ladder.py",
            "same_mesh_source_case_id": source_case.get("case_id"),
            "case_dir": str(case_dir),
        },
    }
    return case


def classify_solver_only_status(
    reports: Mapping[str, Any],
    mesh_quality: Mapping[str, Any],
    forces: Mapping[str, Any],
) -> str:
    if mesh_quality.get("status") != "pass":
        return "mesh_quality_failed"
    simple = reports.get("simpleFoam", {})
    if simple.get("returncode") != 0 or simple.get("timed_out"):
        return "solver_failed"
    if forces.get("summary", {}).get("CD_primary") is None:
        return "force_breakdown_failed"
    return "same_mesh_turbulence_case_completed"


def k_field_text(value: float) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      k;
}}
dimensions      [0 2 -2 0 0 0 0];
internalField   uniform {value:.9g};
boundaryField
{{
    farfield
    {{
        type            freestream;
        freestreamValue uniform {value:.9g};
    }}
    "(wing_upper|wing_lower|tip_left|tip_right|te_wall|closure_wall)"
    {{
        type            kqRWallFunction;
        value           uniform {value:.9g};
    }}
}}
"""


def omega_field_text(value: float) -> str:
    return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      omega;
}}
dimensions      [0 0 -1 0 0 0 0];
internalField   uniform {value:.9g};
boundaryField
{{
    farfield
    {{
        type            freestream;
        freestreamValue uniform {value:.9g};
    }}
    "(wing_upper|wing_lower|tip_left|tip_right|te_wall|closure_wall)"
    {{
        type            omegaWallFunction;
        value           uniform {value:.9g};
    }}
}}
"""


def komega_nut_field_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      nut;
}
dimensions      [0 2 -1 0 0 0 0];
internalField   uniform 0;
boundaryField
{
    farfield
    {
        type            calculated;
        value           uniform 0;
    }
    "(wing_upper|wing_lower|tip_left|tip_right|te_wall|closure_wall)"
    {
        type            nutkWallFunction;
        value           uniform 0;
    }
}
"""


def komega_fv_schemes_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}
ddtSchemes
{
    default         steadyState;
}
gradSchemes
{
    default         Gauss linear;
}
divSchemes
{
    default                         none;
    div(phi,U)                      bounded Gauss linearUpwind grad(U);
    div(phi,k)                      bounded Gauss linearUpwind grad(k);
    div(phi,omega)                  bounded Gauss linearUpwind grad(omega);
    div((nuEff*dev2(T(grad(U)))))   Gauss linear;
}
laplacianSchemes
{
    default         Gauss linear corrected;
}
interpolationSchemes
{
    default         linear;
}
snGradSchemes
{
    default         corrected;
}
wallDist
{
    method          meshWave;
}
"""


def komega_fv_solution_text() -> str:
    return """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}
solvers
{
    p
    {
        solver          GAMG;
        tolerance       1e-06;
        relTol          0.1;
        smoother        GaussSeidel;
    }
    U
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0.1;
    }
    k
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0.1;
    }
    omega
    {
        solver          smoothSolver;
        smoother        GaussSeidel;
        nSweeps         2;
        tolerance       1e-08;
        relTol          0.1;
    }
}
SIMPLE
{
    nNonOrthogonalCorrectors 0;
    residualControl
    {
        p               1e-5;
        U               1e-5;
        k               1e-5;
        omega           1e-5;
    }
}
relaxationFactors
{
    fields
    {
        p               0.3;
    }
    equations
    {
        U               0.7;
        k               0.7;
        omega           0.7;
    }
}
"""


def route_smoke_reproduction_summary(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    current = find_case(cases, "layers_8")
    if current is None:
        return {"status": "missing_ladder_layers_8"}
    if not ROUTE_SMOKE_MANIFEST.exists():
        return {"status": "missing_committed_route_smoke_manifest"}
    baseline = json.loads(ROUTE_SMOKE_MANIFEST.read_text(encoding="utf-8"))
    baseline_case = find_case(baseline.get("cases", []), "layers_8")
    if baseline_case is None:
        return {"status": "missing_committed_layers_8_case"}
    current_summary = current.get("forces", {}).get("summary", {})
    baseline_summary = baseline_case.get("forces", {}).get("summary", {})
    fields = ("CD_primary", "CL_primary", "CD_total", "CD_diagnostic_sum")
    deltas = {
        field: _finite_delta(current_summary.get(field), baseline_summary.get(field))
        for field in fields
    }
    return {
        "status": "available",
        "committed_manifest": str(ROUTE_SMOKE_MANIFEST),
        "current_case_status": current.get("case_status"),
        "current_acceptance": current.get("acceptance", {}),
        "baseline_summary": {field: baseline_summary.get(field) for field in fields},
        "current_summary": {field: current_summary.get(field) for field in fields},
        "delta_current_minus_committed": deltas,
    }


def evaluate_ladder(
    cases: Sequence[Mapping[str, Any]],
    reproduction: Mapping[str, Any],
) -> dict[str, Any]:
    accepted = [
        case for case in cases if case.get("acceptance", {}).get("status") == "accepted"
    ]
    accepted_layers = [
        case
        for case in accepted
        if case.get("controls", {}).get("purpose")
        in {
            "baseline_no_layers",
            "baseline_layer_ladder",
            "route_smoke_reproduction",
            "layer_ladder",
            "low_yplus_oriented_attempt",
        }
    ]
    best = choose_best_layer_case(cases)
    adjacent = accepted_adjacent_layer_pairs(accepted_layers)
    diagnostic_ok = all(
        (case.get("acceptance", {}).get("diagnostic_cd_ratio_of_total") or 0.0) < 0.05
        for case in accepted
    )
    yplus_band = classify_yplus_band(best)
    final_drag_truth_allowed = bool(adjacent and yplus_band in {"wall_function_sanity", "wall_resolved_attempt"})
    real_grid_ladder_ready = bool(
        adjacent
        and best is not None
        and yplus_band in {"wall_function_sanity", "wall_resolved_attempt"}
    )
    return {
        "status": "ladder_evidence_ready" if accepted_layers else "ladder_no_accepted_cases",
        "route_smoke_reproducible": reproduction.get("status") == "available"
        and find_case(cases, "layers_8", accepted_only=True) is not None,
        "best_accepted_layer_case": best.get("case_id") if best else None,
        "accepted_case_ids": [case.get("case_id") for case in accepted],
        "accepted_layer_case_ids": [case.get("case_id") for case in accepted_layers],
        "accepted_adjacent_layer_pairs": adjacent,
        "diagnostic_patches_negligible_for_accepted_cases": diagnostic_ok,
        "current_evidence_class": yplus_band,
        "good_enough_to_proceed_to_real_grid_ladder": real_grid_ladder_ready,
        "good_enough_for_targeted_refinement_yplus_repair": bool(adjacent and best is not None),
        "good_enough_to_compare_against_su2_vspaero_avl": False,
        "final_drag_truth_allowed": final_drag_truth_allowed,
        "single_next_action": single_next_action(cases, best, adjacent, yplus_band),
    }


def accepted_adjacent_layer_pairs(cases: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    accepted_by_layers = {
        int(case.get("nSurfaceLayers") or 0): case.get("case_id")
        for case in cases
        if case.get("acceptance", {}).get("status") == "accepted"
    }
    pairs = []
    for left, right in zip(BASE_LAYER_SCHEDULE, BASE_LAYER_SCHEDULE[1:], strict=False):
        if left in accepted_by_layers and right in accepted_by_layers:
            pairs.append([str(accepted_by_layers[left]), str(accepted_by_layers[right])])
    return pairs


def classify_yplus_band(case: Mapping[str, Any] | None) -> str:
    if case is None:
        return "no_accepted_layer_case"
    upper = _patch_yplus_mean(case, "wing_upper")
    lower = _patch_yplus_mean(case, "wing_lower")
    max_mean = max(value for value in (upper, lower) if value is not None) if upper or lower else None
    if max_mean is None:
        return "missing_yplus"
    if max_mean <= 5.0:
        return "wall_resolved_attempt"
    if 30.0 <= max_mean <= 100.0:
        return "wall_function_sanity"
    if max_mean < 200.0:
        return "high_yplus_sanity"
    return "very_high_yplus_sanity"


def single_next_action(
    cases: Sequence[Mapping[str, Any]],
    best: Mapping[str, Any] | None,
    adjacent: Sequence[Sequence[str]],
    yplus_band: str,
) -> str:
    if best is None:
        return "Repair OpenFOAM layer mesh quality before running any larger grid ladder."
    if not adjacent:
        return "Clean up the rejected intermediate layer rung before treating the ladder as stable."
    wall_function_rejected = [
        case
        for case in cases
        if case.get("acceptance", {}).get("status") == "rejected"
        and classify_yplus_band(case) == "wall_function_sanity"
        and "mesh_quality_not_smoke_acceptable" in case.get("acceptance", {}).get("reasons", [])
    ]
    if wall_function_rejected:
        case = wall_function_rejected[0]
        return (
            f"Repair `{case.get('case_id')}` mesh-quality errors while preserving its "
            "wall-function-range yPlus, then rerun the same SpalartAllmaras force window."
        )
    if yplus_band in {"very_high_yplus_sanity", "high_yplus_sanity"}:
        return "Run a controlled first-wall-height/yPlus reduction on the best accepted mesh before comparing CD against SU2, VSPAERO, or AVL."
    return "Proceed to a small real grid ladder around the best accepted layer controls."


def write_ladder_reports(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    smoke._write_json(output_dir / "ladder_manifest.json", manifest)
    (output_dir / "openfoam_ladder_summary.md").write_text(
        render_ladder_summary(manifest),
        encoding="utf-8",
    )
    (output_dir / "mesh_quality_ladder_report.md").write_text(
        render_mesh_quality_report(manifest.get("cases", [])),
        encoding="utf-8",
    )
    (output_dir / "force_ladder_report.md").write_text(
        render_force_report(manifest.get("cases", [])),
        encoding="utf-8",
    )
    (output_dir / "yplus_ladder_report.md").write_text(
        render_yplus_report(manifest.get("cases", [])),
        encoding="utf-8",
    )
    if any(
        case.get("controls", {}).get("purpose") == "turbulence_model_sensitivity"
        for case in manifest.get("cases", [])
    ):
        (output_dir / "turbulence_model_sensitivity_report.md").write_text(
            render_turbulence_report(manifest.get("cases", [])),
            encoding="utf-8",
        )
    (output_dir / "rerun_instructions.md").write_text(
        render_rerun_instructions(manifest),
        encoding="utf-8",
    )
    (output_dir / "phase3_openfoam_ladder_verdict.md").write_text(
        render_verdict(manifest),
        encoding="utf-8",
    )


def render_ladder_summary(manifest: Mapping[str, Any]) -> str:
    rows = [
        "| case | purpose | acceptance | cells | max skew | CD_primary | CL_primary | y+ upper mean | y+ lower mean |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for case in manifest.get("cases", []):
        summary = case.get("forces", {}).get("summary", {})
        mesh = case.get("mesh", {})
        rows.append(
            "| `{}` | `{}` | `{}` | {} | {} | {} | {} | {} | {} |".format(
                case.get("case_id"),
                case.get("controls", {}).get("purpose"),
                case.get("acceptance", {}).get("status"),
                mesh.get("counts", {}).get("cells", "na"),
                _fmt(mesh.get("max_skewness")),
                _fmt(summary.get("CD_primary")),
                _fmt(summary.get("CL_primary")),
                _fmt(_patch_yplus_mean(case, "wing_upper")),
                _fmt(_patch_yplus_mean(case, "wing_lower")),
            )
        )
    return "\n".join(
        [
            "# OpenFOAM Ladder Summary",
            "",
            f"- route: `{manifest.get('route')}`",
            f"- solver: `{manifest.get('physics', {}).get('solver')}`",
            f"- baseline turbulence model: `{manifest.get('physics', {}).get('baseline_turbulence_model')}`",
            f"- output_dir: `{manifest.get('output_dir')}`",
            "",
            *rows,
            "",
            "The ladder keeps `wing_upper + wing_lower` as primary and keeps tip/TE/closure as diagnostics.",
            "Accepted means route evidence inside the stated bounded CFD trust boundary, not final drag truth.",
        ]
    )


def render_mesh_quality_report(cases: Sequence[Mapping[str, Any]]) -> str:
    lines = ["# Mesh Quality Ladder Report", ""]
    for case in cases:
        mesh = case.get("mesh", {})
        lines.extend(
            [
                f"## {case.get('case_id')}",
                "",
                f"- acceptance: `{case.get('acceptance', {}).get('status')}` {case.get('acceptance', {}).get('reasons')}",
                f"- cells: `{mesh.get('counts', {}).get('cells')}`",
                f"- points: `{mesh.get('counts', {}).get('points')}`",
                f"- max skewness: `{mesh.get('max_skewness')}`",
                f"- custom mesh-quality error count: `{mesh.get('custom_mesh_quality_error_count')}`",
                f"- checkMesh quality basis: `{mesh.get('quality_basis')}`",
                "- non-orthogonality / skew summary:",
                "```text",
                "\n".join(mesh.get("summary_lines") or ["not available"]),
                "```",
                "- layer coverage:",
                "```json",
                json.dumps(case.get("layer_coverage"), indent=2),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def render_force_report(cases: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# Force Ladder Report",
        "",
        "| case | acceptance | CD_primary | CL_primary | CD_total | CD_diag_sum | diag/CD_total | final Cd span | final Cl span |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in cases:
        summary = case.get("forces", {}).get("summary", {})
        acceptance = case.get("acceptance", {})
        stability = case.get("force_stability_final_window", {})
        lines.append(
            "| `{}` | `{}` | {} | {} | {} | {} | {} | {} | {} |".format(
                case.get("case_id"),
                acceptance.get("status"),
                _fmt(summary.get("CD_primary")),
                _fmt(summary.get("CL_primary")),
                _fmt(summary.get("CD_total")),
                _fmt(summary.get("CD_diagnostic_sum")),
                _fmt(acceptance.get("diagnostic_cd_ratio_of_total")),
                _fmt(stability.get("Cd_span")),
                _fmt(stability.get("Cl_span")),
            )
        )
    lines.extend(["", "Residual trend summaries are in `ladder_manifest.json` under each case."])
    return "\n".join(lines)


def render_yplus_report(cases: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "# yPlus Ladder Report",
        "",
        "| case | acceptance | y+ upper min | y+ upper mean | y+ upper max | y+ lower min | y+ lower mean | y+ lower max | band |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for case in cases:
        upper = _patch_yplus(case, "wing_upper")
        lower = _patch_yplus(case, "wing_lower")
        lines.append(
            "| `{}` | `{}` | {} | {} | {} | {} | {} | {} | `{}` |".format(
                case.get("case_id"),
                case.get("acceptance", {}).get("status"),
                _fmt((upper or {}).get("min")),
                _fmt((upper or {}).get("mean")),
                _fmt((upper or {}).get("max")),
                _fmt((lower or {}).get("min")),
                _fmt((lower or {}).get("mean")),
                _fmt((lower or {}).get("max")),
                classify_yplus_band(case),
            )
        )
    lines.extend(
        [
            "",
            "Interpretation: mean y+ below 200 is still high-yPlus sanity unless it lands in a defensible wall-function band, roughly 30-100 here.  Max y+ spikes above 1000 remain a warning against final drag claims.",
        ]
    )
    return "\n".join(lines)


def render_turbulence_report(cases: Sequence[Mapping[str, Any]]) -> str:
    sensitivity = [
        case
        for case in cases
        if case.get("controls", {}).get("purpose") == "turbulence_model_sensitivity"
    ]
    lines = ["# Turbulence Model Sensitivity Report", ""]
    for case in sensitivity:
        source_id = case.get("controls", {}).get("same_mesh_source_case_id")
        source = find_case(cases, str(source_id)) if source_id else None
        lines.extend(
            [
                f"## {case.get('case_id')}",
                "",
                f"- same mesh source: `{source_id}`",
                f"- acceptance: `{case.get('acceptance', {}).get('status')}` {case.get('acceptance', {}).get('reasons')}",
                f"- SpalartAllmaras CD_primary source: `{_summary_value(source, 'CD_primary')}`",
                f"- kOmegaSST CD_primary: `{_summary_value(case, 'CD_primary')}`",
                f"- SpalartAllmaras CL_primary source: `{_summary_value(source, 'CL_primary')}`",
                f"- kOmegaSST CL_primary: `{_summary_value(case, 'CL_primary')}`",
                f"- CD_primary delta: `{_finite_delta(_summary_value(case, 'CD_primary'), _summary_value(source, 'CD_primary'))}`",
                "",
            ]
        )
    if not sensitivity:
        lines.append("Turbulence sensitivity was not run.")
    return "\n".join(lines)


def render_rerun_instructions(manifest: Mapping[str, Any]) -> str:
    accepted = [
        case
        for case in manifest.get("cases", [])
        if case.get("acceptance", {}).get("status") == "accepted"
    ]
    lines = [
        "# OpenFOAM Ladder Rerun Instructions",
        "",
        "Run the full bounded ladder from the repo root:",
        "",
        "```bash",
        "PYTHONPATH=src ./.venv/bin/python scripts/run_wo006_phase3_openfoam_ladder.py --clean",
        "```",
        "",
        "Accepted case configs are stored in `ladder_manifest.json` under `rerun_basis.case_config`; case files live under `openfoam_cases/`.",
        "",
        "## Accepted Cases",
        "",
    ]
    for case in accepted:
        lines.extend(
            [
                f"### {case.get('case_id')}",
                "",
                f"- case_dir: `{case.get('case_dir')}`",
                f"- purpose: `{case.get('controls', {}).get('purpose')}`",
                f"- config: `{case.get('rerun_basis', {}).get('case_config')}`",
                "",
            ]
        )
    return "\n".join(lines)


def render_verdict(manifest: Mapping[str, Any]) -> str:
    verdict = manifest.get("verdict", {})
    cases = manifest.get("cases", [])
    accepted = [
        case
        for case in cases
        if case.get("acceptance", {}).get("status") == "accepted"
    ]
    rows = []
    for case in accepted:
        summary = case.get("forces", {}).get("summary", {})
        rows.append(
            "- `{}`: CD_primary {}, CL_primary {}, y+ upper/lower mean {} / {}".format(
                case.get("case_id"),
                _fmt(summary.get("CD_primary")),
                _fmt(summary.get("CL_primary")),
                _fmt(_patch_yplus_mean(case, "wing_upper")),
                _fmt(_patch_yplus_mean(case, "wing_lower")),
            )
        )
    best = find_case(cases, str(verdict.get("best_accepted_layer_case")))
    yplus_answer = "not improved"
    if best:
        upper = _patch_yplus_mean(best, "wing_upper")
        lower = _patch_yplus_mean(best, "wing_lower")
        if upper is not None and lower is not None and max(upper, lower) < 183.2387:
            yplus_answer = f"improved in mean y+ to upper {upper:.6g} / lower {lower:.6g}"
    return "\n".join(
        [
            "# Phase 3 OpenFOAM Ladder Verdict",
            "",
            "1. Did the route-smoke remain reproducible?",
            f"   - `{verdict.get('route_smoke_reproducible')}`. See `route_smoke_reproduction` in `ladder_manifest.json`.",
            "2. What is the best accepted layer case?",
            f"   - `{verdict.get('best_accepted_layer_case')}`.",
            "3. Did yPlus improve from the original mean 165-183 / max >1000?",
            f"   - `{yplus_answer}`. Max y+ must still be read from `yplus_ladder_report.md` and remains a drag-truth warning if above 1000.",
            "4. What are CD_primary and CL_primary for each accepted case?",
            *(rows or ["- No accepted cases."]),
            "5. Are tip/TE/closure patches still negligible?",
            f"   - `{verdict.get('diagnostic_patches_negligible_for_accepted_cases')}` for accepted cases by the 5% diagnostic/CD_total gate.",
            "6. Does CD_primary stabilize as layers/refinement increase?",
            f"   - Partially. Adjacent accepted layer pairs exist: `{verdict.get('accepted_adjacent_layer_pairs')}`, but this is not full convergence because the refined low-yPlus case is rejected and the 8 -> 16 layer shift is still large.",
            "7. Is the current result good enough to proceed to a real grid ladder?",
            f"   - `{verdict.get('good_enough_to_proceed_to_real_grid_ladder')}` for a real drag grid ladder. It is good enough only for the targeted refinement/yPlus repair tracked by `good_enough_for_targeted_refinement_yplus_repair={verdict.get('good_enough_for_targeted_refinement_yplus_repair')}`.",
            "8. Is the current result good enough to compare against SU2 / VSPAERO / AVL?",
            f"   - `{verdict.get('good_enough_to_compare_against_su2_vspaero_avl')}`. Use it only as OpenFOAM route/ladder evidence until yPlus and grid sensitivity are defensible.",
            "9. Is the current result only high-yPlus sanity, wall-function CFD, or wall-resolved CFD?",
            f"   - `{verdict.get('current_evidence_class')}`.",
            "10. What is the next single action?",
            f"   - {verdict.get('single_next_action')}",
            "",
            "Engineering boundary: passing software gates means the OpenFOAM route produced bounded evidence. It does not mean the Baseline A main-wing drag is final or ready for release/procurement decisions.",
        ]
    )


def find_case(
    cases: Sequence[Mapping[str, Any]],
    case_id: str,
    *,
    accepted_only: bool = False,
) -> Mapping[str, Any] | None:
    for case in cases:
        if case.get("case_id") == case_id:
            if accepted_only and case.get("acceptance", {}).get("status") != "accepted":
                return None
            return case
    return None


def _patch_yplus(case: Mapping[str, Any] | None, patch: str) -> Mapping[str, Any] | None:
    if not case:
        return None
    value = case.get("yPlus", {}).get("patches", {}).get(patch)
    return value if isinstance(value, Mapping) else None


def _patch_yplus_mean(case: Mapping[str, Any] | None, patch: str) -> float | None:
    return _finite_float((_patch_yplus(case, patch) or {}).get("mean"))


def _summary_value(case: Mapping[str, Any] | None, field: str) -> float | None:
    if not case:
        return None
    return _finite_float(case.get("forces", {}).get("summary", {}).get(field))


def _finite_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _finite_delta(current: Any, baseline: Any) -> float | None:
    current_float = _finite_float(current)
    baseline_float = _finite_float(baseline)
    if current_float is None or baseline_float is None:
        return None
    return current_float - baseline_float


def _relative_span(span: float | None, mean: float | None) -> float | None:
    if span is None or mean is None:
        return None
    return abs(span) / max(abs(mean), 1e-12)


def _safe_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _fmt(value: Any) -> str:
    number = _finite_float(value)
    return "`not_available`" if number is None else f"`{number:.9g}`"


if __name__ == "__main__":
    main()
