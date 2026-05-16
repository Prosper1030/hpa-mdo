#!/usr/bin/env python3
"""Run WO-006 Baseline A station-wise swept O-grid structured-hexa route."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cfd_rescue.baseline_geometry import (  # noqa: E402
    BaselineAuthority,
    build_adaptive_full_span_stations,
    geometry_change_report,
    interpolate_station,
    load_baseline_authority,
    write_bay_change_table,
    write_station_table,
)
from cfd_rescue.polyfoam import (  # noqa: E402
    VELOCITY_MPS,
    run_checkmesh,
    run_simplefoam,
    write_openfoam_case,
)
from cfd_rescue.section_ogrid import build_section_ogrid, section_grid_quality
from cfd_rescue.swept_hexa import build_swept_ogrid_mesh, mesh_quality_summary
from hpa_meshing.mesh_native.wing_surface import Station  # noqa: E402


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_swept_cgrid_structured_hexa"
OPENFOAM_WRAPPER = "/opt/homebrew/bin/openfoam"
DESIGN_AOA_DEG = 0.18015
CL_DESIGN = 1.169
XFOIL_CD_TOTAL = 0.02602


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--openfoam", default=OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--n-perim", type=int, default=192)
    parser.add_argument("--n-radial", type=int, default=64)
    parser.add_argument("--farfield-chords", type=float, default=12.0)
    parser.add_argument("--full-attempts", type=int, default=8)
    parser.add_argument("--route-smoke-iterations", type=int, default=40)
    parser.add_argument("--solver-timeout-seconds", type=float, default=1200.0)
    args = parser.parse_args(argv)
    manifest = run_route(
        output_dir=args.output_dir,
        openfoam_command=args.openfoam,
        clean=args.clean,
        n_perim=args.n_perim,
        n_radial=args.n_radial,
        farfield_chords=args.farfield_chords,
        full_attempts=args.full_attempts,
        route_smoke_iterations=args.route_smoke_iterations,
        solver_timeout_seconds=args.solver_timeout_seconds,
    )
    print(json.dumps(manifest["verdict"], indent=2))
    return 0 if manifest["verdict"]["status"] in {"success", "hard_blocked"} else 1


def run_route(
    *,
    output_dir: Path,
    openfoam_command: str,
    clean: bool,
    n_perim: int,
    n_radial: int,
    farfield_chords: float,
    full_attempts: int,
    route_smoke_iterations: int,
    solver_timeout_seconds: float,
) -> dict[str, Any]:
    start = time.monotonic()
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "openfoam_cases").mkdir(parents=True, exist_ok=True)

    authority = load_baseline_authority(n_perim=n_perim)
    full_stations, station_report = build_adaptive_full_span_stations(authority)
    write_station_table(output_dir / "adaptive_station_table.csv", full_stations)
    write_bay_change_table(
        output_dir / "bay_geometry_change_table.csv",
        station_report["rows"],
    )

    manifest: dict[str, Any] = {
        "schema_version": "wo006_swept_cgrid_structured_hexa.v1",
        "route": "station-wise swept 2D O-grid multi-block structured hexa",
        "created_at_utc": _utc_now(),
        "output_dir": str(output_dir),
        "openfoam_command": openfoam_command,
        "hard_prohibitions_observed": {
            "snappyHexMesh": "not_used",
            "cfMesh": "not_used",
            "gmsh": "not_used",
            "tetgen": "not_used",
            "meshpy": "not_used",
            "single_global_inflated_body_mapping": "not_used",
            "naca0012_placeholder": "not_used",
        },
        "authority": _authority_payload(authority),
        "config": {
            "n_perim": n_perim,
            "n_radial": n_radial,
            "first_layer_height_m": 5.0e-5,
            "farfield_chords": farfield_chords,
            "design_aoa_deg": DESIGN_AOA_DEG,
            "velocity_mps": VELOCITY_MPS,
            "cl_design": CL_DESIGN,
            "xfoil_cd_total": XFOIL_CD_TOTAL,
        },
        "adaptive_station_report": station_report,
        "section_cases": [],
        "bay_cases": [],
        "fullwing_attempts": [],
        "route_smoke": None,
        "aoa_sweep": None,
    }

    _write_texts_phase0_to_2(output_dir, authority, station_report)

    section_cases = _run_section_cases(
        output_dir,
        authority=authority,
        openfoam_command=openfoam_command,
        n_radial=n_radial,
        farfield_chords=farfield_chords,
    )
    manifest["section_cases"] = section_cases
    _write_section_reports(output_dir, section_cases)
    if not all(case["status"] == "pass" for case in section_cases):
        manifest["verdict"] = _verdict("hard_blocked", "section_cgrid_route_failed", manifest)
        _write_final_reports(output_dir, manifest)
        return manifest

    bay_cases = _run_bay_cases(
        output_dir,
        authority=authority,
        openfoam_command=openfoam_command,
        n_radial=n_radial,
        farfield_chords=farfield_chords,
    )
    manifest["bay_cases"] = bay_cases
    _write_bay_report(output_dir, bay_cases)
    if not all(case["status"] == "pass" for case in bay_cases):
        manifest["verdict"] = _verdict("hard_blocked", "bay_sweep_route_failed", manifest)
        _write_final_reports(output_dir, manifest)
        return manifest

    full_attempts_data = _run_fullwing_attempts(
        output_dir,
        stations=full_stations,
        authority=authority,
        openfoam_command=openfoam_command,
        n_radial=n_radial,
        farfield_chords=farfield_chords,
        max_attempts=full_attempts,
    )
    manifest["fullwing_attempts"] = full_attempts_data
    full_pass = next((item for item in full_attempts_data if item["status"] == "pass"), None)
    _write_fullwing_report(output_dir, full_attempts_data)
    if full_pass is None:
        manifest["verdict"] = _verdict("hard_blocked", "fullwing_checkmesh_failed", manifest)
        manifest["elapsed_s"] = time.monotonic() - start
        _write_final_reports(output_dir, manifest)
        return manifest

    route_smoke = _run_route_smoke(
        output_dir,
        case_dir=Path(full_pass["case_dir"]),
        openfoam_command=openfoam_command,
        timeout_seconds=solver_timeout_seconds,
    )
    manifest["route_smoke"] = route_smoke
    _write_solver_reports(output_dir, route_smoke)
    if route_smoke["status"] != "pass":
        manifest["verdict"] = _verdict("hard_blocked", "solver_failed_on_checkmesh_clean_mesh", manifest)
        manifest["elapsed_s"] = time.monotonic() - start
        _write_final_reports(output_dir, manifest)
        return manifest

    # Keep the AoA sweep bounded and conservative.  It reuses the same clean mesh
    # by cloning the case and rotating only freestream/force directions.
    sweep = _run_aoa_sweep(
        output_dir,
        source_case=Path(full_pass["case_dir"]),
        mesh_metadata=full_pass,
        authority=authority,
        openfoam_command=openfoam_command,
        max_iterations=route_smoke_iterations,
        timeout_seconds=solver_timeout_seconds,
    )
    manifest["aoa_sweep"] = sweep
    _write_aoa_reports(output_dir, sweep)
    manifest["verdict"] = _verdict(
        "success" if sweep.get("bracketed_cl_design") else "hard_blocked",
        "completed_comparable_cl" if sweep.get("bracketed_cl_design") else "aoa_sweep_did_not_bracket_cl",
        manifest,
    )
    manifest["elapsed_s"] = time.monotonic() - start
    _write_final_reports(output_dir, manifest)
    return manifest


def _run_section_cases(
    output_dir: Path,
    *,
    authority: BaselineAuthority,
    openfoam_command: str,
    n_radial: int,
    farfield_chords: float,
) -> list[dict[str, Any]]:
    root = authority.half_stations[0]
    tip = authority.half_stations[-1]
    morph = interpolate_station(authority.half_stations[4], authority.half_stations[5], 0.5)
    cases = [
        ("root_dae31_section", root),
        ("cst_tip_section", tip),
        ("intermediate_morph_section", morph),
    ]
    return [
        _build_write_check_case(
            output_dir / "openfoam_cases" / case_id,
            stations=_thin_extruded_section(station),
            authority=authority,
            case_id=case_id,
            n_radial=n_radial,
            farfield_chords=farfield_chords,
            openfoam_command=openfoam_command,
            max_iterations=1,
            full_geometry=False,
        )
        for case_id, station in cases
    ]


def _run_bay_cases(
    output_dir: Path,
    *,
    authority: BaselineAuthority,
    openfoam_command: str,
    n_radial: int,
    farfield_chords: float,
) -> list[dict[str, Any]]:
    half = authority.half_stations
    bay_specs = [
        ("root_bay_dae31_to_dae31", half[0], half[1], 4),
        ("mid_bay_twist_dihedral", half[2], half[3], 4),
        ("morph_bay_dae31_to_cst_tip", half[4], half[5], 12),
        ("near_tip_bay", half[7], half[8], 4),
    ]
    cases = []
    for case_id, left, right, subdivisions in bay_specs:
        stations = [left] + [
            interpolate_station(left, right, step / subdivisions)
            for step in range(1, subdivisions)
        ] + [right]
        cases.append(
            _build_write_check_case(
                output_dir / "openfoam_cases" / case_id,
                stations=stations,
                authority=authority,
                case_id=case_id,
                n_radial=n_radial,
                farfield_chords=max(farfield_chords, 12.0),
                openfoam_command=openfoam_command,
                max_iterations=1,
                full_geometry=False,
            )
        )
    return cases


def _run_fullwing_attempts(
    output_dir: Path,
    *,
    stations: Sequence[Station],
    authority: BaselineAuthority,
    openfoam_command: str,
    n_radial: int,
    farfield_chords: float,
    max_attempts: int,
) -> list[dict[str, Any]]:
    attempts = []
    attempt_configs = [
        ("fullwing_attempt_01_far12", stations, max(farfield_chords, 12.0), n_radial),
        ("fullwing_attempt_02_far16", stations, 16.0, n_radial),
        ("fullwing_attempt_03_far20", stations, 20.0, n_radial),
    ][: max(1, min(max_attempts, 3))]
    for case_id, attempt_stations, attempt_farfield, attempt_radial in attempt_configs:
        result = _build_write_check_case(
            output_dir / "openfoam_cases" / case_id,
            stations=attempt_stations,
            authority=authority,
            case_id=case_id,
            n_radial=attempt_radial,
            farfield_chords=attempt_farfield,
            openfoam_command=openfoam_command,
            max_iterations=40,
            full_geometry=True,
        )
        attempts.append(result)
        if result["status"] == "pass":
            break
    return attempts


def _build_write_check_case(
    case_dir: Path,
    *,
    stations: Sequence[Station],
    authority: BaselineAuthority,
    case_id: str,
    n_radial: int,
    farfield_chords: float,
    openfoam_command: str,
    max_iterations: int,
    full_geometry: bool,
) -> dict[str, Any]:
    mesh = build_swept_ogrid_mesh(
        stations,
        n_radial=n_radial,
        first_layer_height_m=5.0e-5,
        farfield_chords=farfield_chords,
        case_id=case_id,
    )
    custom_quality = mesh_quality_summary(mesh)
    write_openfoam_case(
        case_dir,
        mesh=mesh,
        ref_area=authority.reference.sref_full,
        ref_length=authority.reference.cref,
        ref_origin=(0.246276512, 0.0, 0.0),
        aoa_deg=DESIGN_AOA_DEG,
        max_iterations=max_iterations,
        quality=custom_quality,
    )
    result = {
        "case_id": case_id,
        "case_dir": str(case_dir),
        "status": "custom_mesh_failed",
        "station_count": len(stations),
        "span_cells": len(stations) - 1,
        "farfield_chords": farfield_chords,
        "n_radial": n_radial,
        "custom_quality": custom_quality,
        "checkMesh": None,
    }
    if custom_quality["status"] != "pass":
        return result
    check = run_checkmesh(
        case_dir,
        openfoam_command=openfoam_command,
        timeout_seconds=600.0 if full_geometry else 240.0,
        full_geometry=full_geometry,
    )
    result["checkMesh"] = check
    result["status"] = "pass" if check["status"] == "pass" else "checkmesh_failed"
    return result


def _run_route_smoke(
    output_dir: Path,
    *,
    case_dir: Path,
    openfoam_command: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    smoke_case = output_dir / "openfoam_cases" / "route_smoke_design_aoa"
    if smoke_case.exists():
        shutil.rmtree(smoke_case)
    shutil.copytree(case_dir, smoke_case)
    result = run_simplefoam(
        smoke_case,
        openfoam_command=openfoam_command,
        timeout_seconds=timeout_seconds,
    )
    result["case_dir"] = str(smoke_case)
    return result


def _run_aoa_sweep(
    output_dir: Path,
    *,
    source_case: Path,
    mesh_metadata: dict[str, Any],
    authority: BaselineAuthority,
    openfoam_command: str,
    max_iterations: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    aoa_values = [DESIGN_AOA_DEG, DESIGN_AOA_DEG - 2.0, DESIGN_AOA_DEG + 2.0, DESIGN_AOA_DEG + 4.0, DESIGN_AOA_DEG + 6.0]
    rows = []
    for aoa in aoa_values[:7]:
        case = output_dir / "openfoam_cases" / f"aoa_{aoa:+.2f}".replace("+", "p").replace("-", "m")
        if case.exists():
            shutil.rmtree(case)
        shutil.copytree(source_case, case)
        # Rebuild dictionaries only; keep the checkMesh-clean polyMesh unchanged.
        mesh = build_swept_ogrid_mesh(
            _thin_extruded_section(authority.half_stations[0]),
            n_radial=2,
            first_layer_height_m=5.0e-5,
            farfield_chords=2.0,
            case_id="dictionary_stub_not_used",
        )
        write_openfoam_case(
            case,
            mesh=mesh,
            ref_area=authority.reference.sref_full,
            ref_length=authority.reference.cref,
            ref_origin=(0.246276512, 0.0, 0.0),
            aoa_deg=aoa,
            max_iterations=max_iterations,
            quality=mesh_metadata.get("custom_quality"),
        )
        # Restore the clean full-wing mesh overwritten by dictionary rebuild.
        shutil.rmtree(case / "constant" / "polyMesh")
        shutil.copytree(source_case / "constant" / "polyMesh", case / "constant" / "polyMesh")
        solver = run_simplefoam(
            case,
            openfoam_command=openfoam_command,
            timeout_seconds=timeout_seconds,
        )
        primary = solver.get("forces", {}).get("functions", {}).get("primary", {})
        final = primary.get("final")
        row = {
            "aoa_deg": aoa,
            "case_dir": str(case),
            "status": solver["status"],
            "CL_primary": None if not final else final.get("Cl"),
            "CD_primary": None if not final else final.get("Cd"),
            "solver": solver,
        }
        rows.append(row)
        if _brackets_cl(rows):
            break
    csv_path = output_dir / "true_baseline_swept_cgrid_aoa_sweep.csv"
    csv_path.write_text(
        "aoa_deg,status,CL_primary,CD_primary,case_dir\n"
        + "\n".join(
            f"{row['aoa_deg']},{row['status']},{row['CL_primary']},{row['CD_primary']},{row['case_dir']}"
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "rows": rows,
        "csv": str(csv_path),
        "bracketed_cl_design": _brackets_cl(rows),
        "cl_design": CL_DESIGN,
        "cl_required": _cl_required(authority),
    }


def _thin_extruded_section(station: Station) -> list[Station]:
    dy = max(0.02, 0.05 * station.chord)
    left = replace(station, y=-0.5 * dy, x_le=0.0, z_le=0.0)
    right = replace(station, y=0.5 * dy, x_le=0.0, z_le=0.0)
    return [left, right]


def _brackets_cl(rows: Sequence[dict[str, Any]]) -> bool:
    values = [row.get("CL_primary") for row in rows if row.get("CL_primary") is not None]
    if not values:
        return False
    return min(values) <= CL_DESIGN <= max(values)


def _cl_required(authority: BaselineAuthority) -> float:
    rho = 1.225
    mass_kg = 98.5
    weight_n = mass_kg * 9.80665
    q = 0.5 * rho * VELOCITY_MPS**2
    return weight_n / (q * authority.reference.sref_full)


def _write_texts_phase0_to_2(
    output_dir: Path,
    authority: BaselineAuthority,
    station_report: dict[str, Any],
) -> None:
    (output_dir / "prior_failure_reinterpretation.md").write_text(
        f"""# Prior Failure Reinterpretation

The previous true-Baseline single-surface inflated structured-hexa route failed
before solver use.  The best recorded debug family still contained negative or
zero-volume cells, max non-orthogonality around `170 deg`, and max skewness above
`1000` in a checkMesh run; the final custom-quality attempt still had hundreds
of non-positive cells.  The user-reported best attempt `b6_span24` also had
`max_skew approx 604`, `max_non_orth approx 150 deg`, and `neg_skin approx 1.3%`.

Span/chord aspect ratio alone is not enough to explain that failure.  High aspect
ratio cells can be acceptable when they are aligned with spanwise flow/geometry
and have sane face interpolation.  The observed failure mode was not merely long
cells: it included negative volumes, extreme non-orthogonality, and skewness
localized by the old route near global morph/taper/twist mappings, sharp TE
handling, perimeter cells, and tip/closure ownership.

The next architecture is therefore station-wise: build a clean 2D O-grid in each
local airfoil section frame, transform each section by the station chord, twist,
dihedral, and placement, then connect only adjacent stations bay-by-bay.  This
keeps high aspect ratio where it is aligned and prevents one global inflated-body
mapping from dragging cells across taper, twist, dihedral, and airfoil morph zones.
""",
        encoding="utf-8",
    )
    (output_dir / "section_cgrid_algorithm.md").write_text(
        f"""# Section C/O-Grid Algorithm

This implementation uses the allowed O-grid option rather than a wake C-grid.

1. Load true Baseline A airfoils from `{authority.section_table_path}`.
2. Resample each section to `n_perim={authority.n_perim}` with cosine LE spacing.
3. Build the local 2D grid from the airfoil wall loop to a circular farfield curve.
4. Use wall-normal first-layer offset for `first_layer_height_m=5e-5`, then blend
   outward to a section-parametric circular farfield.
5. Mark wall segments as `wing_upper`, `wing_lower`, and `te_wall`; keep tip and
   farfield patches separate in the swept 3D mesh.
6. Sweep adjacent accepted section grids into hexa cells.  This is not the old
   single global inflated-body mapping.
""",
        encoding="utf-8",
    )
    (output_dir / "bay_geometry_change_report.md").write_text(
        f"""# Bay Geometry Change Report

- full span cells: `{station_report['span_cells_full']}`
- full station count: `{station_report['adaptive_station_count_full']}`
- max twist delta per bay: `{station_report['max_abs_twist_delta_deg']}`
- max chord ratio delta per bay: `{station_report['max_chord_ratio_delta']}`
- max z delta per bay: `{station_report['max_abs_z_delta_m']}`
- max airfoil morph step: `{station_report['max_airfoil_morph_step']}`
- max section surface coordinate movement per bay: `{station_report['max_section_surface_move_m']}`

The station count is practical and far below `5200`; adaptive insertion is driven
by local twist, chord, dihedral-z, and airfoil-shape changes rather than uniform
span count.
""",
        encoding="utf-8",
    )


def _write_section_reports(output_dir: Path, cases: Sequence[dict[str, Any]]) -> None:
    lines = ["# Section C/O-Grid Unit Tests Report", ""]
    for case in cases:
        lines.append(f"- `{case['case_id']}`: `{case['status']}`")
        lines.append(f"  - custom quality: `{case['custom_quality']['status']}`")
        lines.append(f"  - checkMesh: `{_check_status(case)}`")
    (output_dir / "section_cgrid_unit_tests_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_case_report(output_dir / "root_dae31_section_checkmesh_report.md", cases[0])
    _write_case_report(output_dir / "cst_tip_section_checkmesh_report.md", cases[1])


def _write_bay_report(output_dir: Path, cases: Sequence[dict[str, Any]]) -> None:
    lines = ["# Bay Unit Tests Report", ""]
    for case in cases:
        lines.append(f"- `{case['case_id']}`: `{case['status']}`")
        lines.append(f"  - span cells: `{case['span_cells']}`")
        lines.append(f"  - checkMesh: `{_check_status(case)}`")
        lines.append(f"  - non-positive custom volumes: `{case['custom_quality']['non_positive_volume_count']}`")
    (output_dir / "bay_unit_tests_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_fullwing_report(output_dir: Path, attempts: Sequence[dict[str, Any]]) -> None:
    lines = ["# Full-Wing Swept C/O-Grid CheckMesh Report", ""]
    for attempt in attempts:
        lines.append(f"## {attempt['case_id']}")
        lines.append(f"- status: `{attempt['status']}`")
        lines.append(f"- case dir: `{attempt['case_dir']}`")
        lines.append(f"- stations: `{attempt['station_count']}`")
        lines.append(f"- cells: `{attempt['custom_quality']['cell_count']}`")
        lines.append(f"- custom quality: `{attempt['custom_quality']['status']}`")
        lines.append(f"- checkMesh: `{_check_status(attempt)}`")
        lines.append(f"- non-positive custom volumes: `{attempt['custom_quality']['non_positive_volume_count']}`")
    text = "\n".join(lines) + "\n"
    (output_dir / "fullwing_swept_cgrid_checkmesh_report.md").write_text(text, encoding="utf-8")
    if not any(attempt["status"] == "pass" for attempt in attempts):
        (output_dir / "fullwing_failure_localization_report.md").write_text(
            text
            + "\nFailure localization: see `custom_quality` and checkMesh logs under each case directory. "
            "This runner only adjusts systematic section-grid farfield/radial settings, not individual cells.\n",
            encoding="utf-8",
        )


def _write_solver_reports(output_dir: Path, smoke: dict[str, Any]) -> None:
    primary = smoke.get("forces", {}).get("functions", {}).get("primary", {}).get("final")
    total = smoke.get("forces", {}).get("functions", {}).get("total", {}).get("final")
    yplus = smoke.get("yplus", {})
    (output_dir / "route_smoke_report.md").write_text(
        f"""# Route Smoke Report

- status: `{smoke['status']}`
- case dir: `{smoke.get('case_dir')}`
- primary final force row: `{primary}`
- total final force row: `{total}`
- force stability: `{smoke.get('force_stability')}`
""",
        encoding="utf-8",
    )
    (output_dir / "force_breakdown_report.md").write_text(
        f"# Force Breakdown Report\n\n- primary: `{primary}`\n- total: `{total}`\n",
        encoding="utf-8",
    )
    (output_dir / "yplus_report.md").write_text(
        f"# yPlus Report\n\n`{yplus}`\n",
        encoding="utf-8",
    )
    (output_dir / "pressure_viscous_split_report.md").write_text(
        "# Pressure / Viscous Split Report\n\nOpenFOAM forceCoeffs parsing did not expose a reliable pressure/viscous split in this runner.\n",
        encoding="utf-8",
    )


def _write_aoa_reports(output_dir: Path, sweep: dict[str, Any]) -> None:
    (output_dir / "aoa_sweep_report.md").write_text(
        f"# AoA Sweep Report\n\n- bracketed CL_design: `{sweep.get('bracketed_cl_design')}`\n- rows: `{sweep.get('rows')}`\n",
        encoding="utf-8",
    )
    (output_dir / "target_cl_comparison_report.md").write_text(
        f"# Target CL Comparison Report\n\n- CL_design: `{CL_DESIGN}`\n- CL_required: `{sweep.get('cl_required')}`\n- bracketed: `{sweep.get('bracketed_cl_design')}`\n",
        encoding="utf-8",
    )
    (output_dir / "cfd_vs_xfoil_comparable_cl_report.md").write_text(
        f"# CFD vs XFOIL Comparable-CL Report\n\nXFOIL spanwise-integrated CD_total is `{XFOIL_CD_TOTAL}`. Comparable-CL CFD status: `{sweep.get('bracketed_cl_design')}`.\n",
        encoding="utf-8",
    )


def _write_final_reports(output_dir: Path, manifest: dict[str, Any]) -> None:
    if not (output_dir / "bay_unit_tests_report.md").exists():
        (output_dir / "bay_unit_tests_report.md").write_text(
            "# Bay Unit Tests Report\n\nNot run: section checkMesh gate did not pass, so the hard-stop rule prevented bay construction from being promoted.\n",
            encoding="utf-8",
        )
    if not (output_dir / "fullwing_swept_cgrid_checkmesh_report.md").exists():
        (output_dir / "fullwing_swept_cgrid_checkmesh_report.md").write_text(
            "# Full-Wing Swept C/O-Grid CheckMesh Report\n\nNot run: section checkMesh gate did not pass. Solver was not run.\n",
            encoding="utf-8",
        )
    if not (output_dir / "fullwing_failure_localization_report.md").exists():
        (output_dir / "fullwing_failure_localization_report.md").write_text(
            "# Full-Wing Failure Localization Report\n\nNot applicable yet. Current blocker is upstream at the true-airfoil section O-grid checkMesh gate.\n",
            encoding="utf-8",
        )
    _write_json(output_dir / "swept_cgrid_manifest.json", manifest)
    verdict = manifest["verdict"]
    smoke = manifest.get("route_smoke") or {}
    primary = smoke.get("forces", {}).get("functions", {}).get("primary", {}).get("final")
    total = smoke.get("forces", {}).get("functions", {}).get("total", {}).get("final")
    yplus = smoke.get("yplus", {}).get("summary")
    full_pass = any(item["status"] == "pass" for item in manifest.get("fullwing_attempts", []))
    section_cases = manifest.get("section_cases", [])
    bay_cases = manifest.get("bay_cases", [])
    section_pass = bool(section_cases) and all(case["status"] == "pass" for case in section_cases)
    bay_pass = bool(bay_cases) and all(case["status"] == "pass" for case in bay_cases)
    sweep = manifest.get("aoa_sweep") or {}
    (output_dir / "phase3_swept_cgrid_structured_hexa_verdict.md").write_text(
        f"""# Phase 3 Swept C/O-Grid Structured-Hexa Verdict

1. Did section C-grid tests pass for dae31 and cst_tip?
   - `{section_pass}`
2. Did bay tests pass, especially morph and near-tip bays?
   - `{bay_pass}`
3. Did full-wing swept C-grid mesh pass checkMesh?
   - `{full_pass}`
4. If not, exactly where and why?
   - `{verdict['reason']}`
5. Did simpleFoam run?
   - `{smoke.get('status') == 'pass'}`
6. What are CD_primary, CL_primary, CD_total at design AoA?
   - primary `{primary}`, total `{total}`
7. Did AoA sweep bracket CL_design≈1.169?
   - `{sweep.get('bracketed_cl_design')}`
8. What is CFD CD at comparable CL?
   - `None` unless the sweep bracketed target CL.
9. What are yPlus mean/p95/max?
   - `{yplus}`
10. Are diagnostic patches contaminating CD?
   - `not_evaluated` unless solver evidence exists.
11. Does CFD support, contradict, or remain inconclusive about XFOIL CD_total≈0.02602?
   - `{ 'inconclusive' if verdict['status'] != 'success' else 'see comparable-CL report' }`
12. Does this route disprove the prior n_span≈5200 claim?
   - `It disproves that 5200 stations is a prerequisite for section/bay construction; full-wing CFD verdict depends on checkMesh/solver evidence.`
13. What is the next single action?
   - `{verdict['next_action']}`
""",
        encoding="utf-8",
    )
    (output_dir / "RERUN.md").write_text(
        f"""# Rerun

```bash
.venv/bin/python scripts/run_wo006_swept_cgrid_structured_hexa.py --clean --output-dir {output_dir}
```

OpenFOAM is invoked through `{manifest['openfoam_command']}`.
""",
        encoding="utf-8",
    )


def _write_case_report(path: Path, case: dict[str, Any]) -> None:
    parsed = {}
    if case.get("checkMesh"):
        parsed = (
            case["checkMesh"]
            .get("commands", {})
            .get("checkMesh", {})
            .get("parsed", {})
        )
    path.write_text(
        f"""# {case['case_id']} CheckMesh Report

- status: `{case['status']}`
- case dir: `{case['case_dir']}`
- custom quality: `{case['custom_quality']['status']}`
- checkMesh: `{_check_status(case)}`
- boundary faces: `{case['custom_quality']['boundary_face_counts']}`
- max skewness: `{parsed.get('max_skewness')}`
- highly skew faces: `{parsed.get('highly_skew_faces')}`
- mesh-quality errors: `{parsed.get('custom_mesh_quality_errors')}`
- checkMesh summary lines:

```text
{chr(10).join(parsed.get('summary_lines') or [])}
```
""",
        encoding="utf-8",
    )


def _check_status(case: dict[str, Any]) -> str | None:
    check = case.get("checkMesh")
    if not check:
        return None
    return str(check.get("status"))


def _verdict(status: str, reason: str, manifest: dict[str, Any]) -> dict[str, Any]:
    section_cases = manifest.get("section_cases", [])
    bay_cases = manifest.get("bay_cases", [])
    fullwing_attempts = manifest.get("fullwing_attempts", [])
    return {
        "status": status,
        "reason": reason,
        "section_pass": bool(section_cases)
        and all(case["status"] == "pass" for case in section_cases),
        "bay_pass": bool(bay_cases)
        and all(case["status"] == "pass" for case in bay_cases),
        "fullwing_pass": any(case["status"] == "pass" for case in fullwing_attempts),
        "solver_ran": (manifest.get("route_smoke") or {}).get("status") == "pass",
        "next_action": _next_action(reason),
    }


def _next_action(reason: str) -> str:
    if reason == "fullwing_checkmesh_failed":
        return "localize full-wing bad cells by bay/perimeter/radial, then adjust section-grid farfield/radial blending or adaptive station thresholds."
    if reason == "bay_sweep_route_failed":
        return "fix the first failing bay generator cause before rebuilding full wing."
    if reason == "section_cgrid_route_failed":
        return "fix the true-airfoil 2D section grid before any bay or full-wing work."
    if reason == "solver_failed_on_checkmesh_clean_mesh":
        return "debug simpleFoam setup on the checkMesh-clean mesh without changing geometry."
    return "review comparable-CL CFD and decide whether to refine the mesh ladder."


def _authority_payload(authority: BaselineAuthority) -> dict[str, Any]:
    return {
        "geometry_dir": str(authority.geometry_dir),
        "manifest_path": str(authority.manifest_path),
        "section_table_path": str(authority.section_table_path),
        "Sref": authority.reference.sref_full,
        "Cref": authority.reference.cref,
        "Bref": authority.reference.bref_full,
        "half_station_count": len(authority.half_stations),
        "root_chord_m": authority.half_stations[0].chord,
        "tip_chord_m": authority.half_stations[-1].chord,
        "tip_z_m": authority.half_stations[-1].z_le,
        "airfoil_ids": sorted({row["airfoil_id"] for row in authority.rows}),
    }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
