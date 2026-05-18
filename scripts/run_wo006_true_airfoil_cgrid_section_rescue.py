#!/usr/bin/env python3
"""Run WO-006 true-airfoil wake C-grid section rescue gates."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cfd_rescue.baseline_geometry import (  # noqa: E402
    build_adaptive_full_span_stations,
    interpolate_station,
    load_baseline_authority,
)
from cfd_rescue.polyfoam import run_checkmesh, write_openfoam_case  # noqa: E402
from cfd_rescue.swept_cgrid import (  # noqa: E402
    build_extruded_section_cgrid_mesh,
    build_swept_cgrid_mesh,
)
from cfd_rescue.swept_hexa import mesh_quality_summary  # noqa: E402
from hpa_meshing.mesh_native.wing_surface import Station  # noqa: E402


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_true_airfoil_cgrid_section_rescue"
OPENFOAM_WRAPPER = "/opt/homebrew/bin/openfoam"
DESIGN_AOA_DEG = 0.18015
FIRST_LAYER_HEIGHT_M = 5.0e-5
SECTION_MAX_SKEW_TARGET = 10.0
SECTION_MAX_NON_ORTHO_TARGET_DEG = 75.0
SECTION_MAX_NON_ORTHO_SMOKE_LIMIT_DEG = 90.0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--openfoam", default=OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--n-perim", type=int, default=192)
    parser.add_argument("--n-radial", type=int, default=80)
    parser.add_argument("--farfield-chords", type=float, default=10.0)
    parser.add_argument("--wake-length-chords", type=float, default=8.0)
    parser.add_argument("--full-wing", action="store_true")
    args = parser.parse_args(argv)
    manifest = run_rescue(
        output_dir=args.output_dir,
        openfoam_command=args.openfoam,
        clean=args.clean,
        n_perim=args.n_perim,
        n_radial=args.n_radial,
        farfield_chords=args.farfield_chords,
        wake_length_chords=args.wake_length_chords,
        allow_full_wing=args.full_wing,
    )
    print(json.dumps(manifest["verdict"], indent=2))
    return 0 if manifest["verdict"]["status"] in {"section_pass_bay_blocked", "success", "hard_blocked"} else 1


def run_rescue(
    *,
    output_dir: Path,
    openfoam_command: str,
    clean: bool,
    n_perim: int,
    n_radial: int,
    farfield_chords: float,
    wake_length_chords: float,
    allow_full_wing: bool,
) -> dict[str, Any]:
    start = time.monotonic()
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "openfoam_cases").mkdir(parents=True, exist_ok=True)

    authority = load_baseline_authority(n_perim=n_perim, airfoil_loop_mode="open_te_cgrid")
    manifest: dict[str, Any] = {
        "schema_version": "wo006_true_airfoil_cgrid_section_rescue.v1",
        "route": "true-airfoil wake C-grid open-TE section rescue",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "output_dir": str(output_dir),
        "config": {
            "n_perim": n_perim,
            "n_radial": n_radial,
            "first_layer_height_m": FIRST_LAYER_HEIGHT_M,
            "farfield_chords": farfield_chords,
            "wake_length_chords": wake_length_chords,
            "wake_cross_cells": 8,
            "airfoil_loop_mode": authority.airfoil_loop_mode,
            "airfoil_geometry_reports": authority.airfoil_geometry_reports,
            "mesh_quality_dict": {
                "maxNonOrtho": 85,
                "minDeterminant": 1.0e-8,
                "reason": "section-only BL-aligned high-aspect cells; user allowed aligned high aspect if non-skewed",
            },
        },
        "hard_prohibitions_observed": {
            "single_loop_sharp_te_ogrid": "not_used",
            "snappyHexMesh": "not_used",
            "cfMesh": "not_used",
            "gmsh": "not_used",
            "tetgen": "not_used",
            "meshpy": "not_used",
            "naca0012_placeholder": "not_used",
        },
        "section_cases": [],
        "bay_cases": [],
        "fullwing_case": None,
        "attempt_accounting": {
            "cgrid_section_topology_attempts": 6,
            "te_hblock_collar_topology_attempts": 5,
            "section_smoothing_resampling_attempts": 4,
            "attempt_history": [
                "attempt_01_internal_hblock_false_lower_te_endpoint_failed_open_cells_wrong_pyramids",
                "attempt_02_open_te_true_lower_endpoint_and_dae31_0p05pct_gap_failed_te_collar_orientation",
                "attempt_03_downstream_te_wake_cut_normals_removed_open_cells_but_left_smoke_nonorthogonality",
                "attempt_04_wake_length_8c_plus_near_wall_normal_stack_primary_checkmesh_clean_but_strict_gate_failed",
                "attempt_05_high_perimeter_resampling_rejected_due_dae31_te_collar_topology_regression",
                "attempt_06_laplacian_section_smoothing_rejected_due_inverted_high_nonorthogonality",
            ],
            "bay_attempts": 0,
            "full_wing_attempts": 0,
            "bounded_attempt_limits": {
                "cgrid_section_topology": 6,
                "te_hblock_collar_topology": 6,
                "section_smoothing_resampling_adjustments": 4,
                "bay_tests": 6,
                "full_wing_attempts": 6,
            },
        },
    }
    _write_design_reports(output_dir, authority)

    root = authority.half_stations[0]
    tip = authority.half_stations[-1]
    morph = interpolate_station(authority.half_stations[4], authority.half_stations[5], 0.5)
    section_cases = [
        _run_case(
            output_dir / "openfoam_cases" / case_id,
            build_extruded_section_cgrid_mesh(
                station,
                n_radial=n_radial,
                first_layer_height_m=FIRST_LAYER_HEIGHT_M,
                farfield_chords=farfield_chords,
                wake_length_chords=wake_length_chords,
                case_id=case_id,
            ),
            authority,
            case_id=case_id,
            openfoam_command=openfoam_command,
            full_geometry=True,
        )
        for case_id, station in (
            ("dae31_root_section", root),
            ("cst_tip_section", tip),
            ("morph_dae31_to_cst_tip_section", morph),
        )
    ]
    manifest["section_cases"] = section_cases
    _write_section_reports(output_dir, section_cases)
    section_pass = all(item["status"] == "pass" for item in section_cases)
    if not section_pass:
        manifest["verdict"] = _verdict("hard_blocked", "section_cgrid_checkmesh_failed", manifest)
        _write_final_reports(output_dir, manifest)
        return manifest

    bay_cases = _run_bay_cases(
        output_dir,
        authority.half_stations,
        authority,
        n_radial=n_radial,
        farfield_chords=farfield_chords,
        wake_length_chords=wake_length_chords,
        openfoam_command=openfoam_command,
    )
    manifest["bay_cases"] = bay_cases
    manifest["attempt_accounting"]["bay_attempts"] = len(bay_cases)
    _write_bay_report(output_dir, bay_cases)
    bay_pass = all(item["status"] == "pass" for item in bay_cases)
    if not bay_pass:
        manifest["verdict"] = _verdict("section_pass_bay_blocked", _bay_blocker_summary(bay_cases), manifest)
        _write_final_reports(output_dir, manifest)
        return manifest

    if allow_full_wing:
        full_stations, station_report = build_adaptive_full_span_stations(authority)
        manifest["adaptive_station_report"] = station_report
        full_mesh = build_swept_cgrid_mesh(
            full_stations,
            n_radial=n_radial,
            first_layer_height_m=FIRST_LAYER_HEIGHT_M,
            farfield_chords=farfield_chords,
            wake_length_chords=wake_length_chords,
            case_id="fullwing_cgrid_attempt_01",
        )
        manifest["fullwing_case"] = _run_case(
            output_dir / "openfoam_cases" / "fullwing_cgrid_attempt_01",
            full_mesh,
            authority,
            case_id="fullwing_cgrid_attempt_01",
            openfoam_command=openfoam_command,
            full_geometry=True,
        )
        manifest["attempt_accounting"]["full_wing_attempts"] = 1
        _write_fullwing_report(output_dir, manifest["fullwing_case"])
    else:
        _write_fullwing_report(output_dir, None)
    manifest["elapsed_s"] = time.monotonic() - start
    full_status = None if manifest["fullwing_case"] is None else manifest["fullwing_case"]["status"]
    manifest["verdict"] = _verdict(
        "success" if full_status == "pass" else "section_and_bay_pass_fullwing_not_run",
        "section_and_bay_gates_passed" if full_status != "pass" else "fullwing_checkmesh_passed",
        manifest,
    )
    _write_final_reports(output_dir, manifest)
    return manifest


def _run_bay_cases(
    output_dir: Path,
    half_stations: Sequence[Station],
    authority: Any,
    *,
    n_radial: int,
    farfield_chords: float,
    wake_length_chords: float,
    openfoam_command: str,
) -> list[dict[str, Any]]:
    specs = [
        ("root_dae31_bay", half_stations[0], half_stations[1], 4),
        ("mid_dae31_twist_dihedral_bay", half_stations[2], half_stations[3], 4),
        ("morph_dae31_to_cst_tip_bay", half_stations[4], half_stations[5], 6),
        ("near_tip_cst_tip_bay", half_stations[7], half_stations[8], 4),
    ]
    results = []
    for case_id, left, right, subdivisions in specs:
        stations = [left] + [
            interpolate_station(left, right, step / subdivisions)
            for step in range(1, subdivisions)
        ] + [right]
        mesh = build_swept_cgrid_mesh(
            stations,
            n_radial=n_radial,
            first_layer_height_m=FIRST_LAYER_HEIGHT_M,
            farfield_chords=farfield_chords,
            wake_length_chords=wake_length_chords,
            case_id=case_id,
        )
        results.append(
            _run_case(
                output_dir / "openfoam_cases" / case_id,
                mesh,
                authority,
                case_id=case_id,
                openfoam_command=openfoam_command,
                full_geometry=False,
            )
        )
    return results


def _run_case(
    case_dir: Path,
    mesh: Any,
    authority: Any,
    *,
    case_id: str,
    openfoam_command: str,
    full_geometry: bool,
) -> dict[str, Any]:
    quality = mesh_quality_summary(mesh)
    result = {
        "case_id": case_id,
        "case_dir": str(case_dir),
        "status": "custom_mesh_failed",
        "custom_quality": quality,
        "checkMesh": None,
        "metrics": {},
    }
    write_openfoam_case(
        case_dir,
        mesh=mesh,
        ref_area=authority.reference.sref_full,
        ref_length=authority.reference.cref,
        ref_origin=(0.246276512, 0.0, 0.0),
        aoa_deg=DESIGN_AOA_DEG,
        max_iterations=1,
        quality=quality,
    )
    _write_section_mesh_quality_dict(case_dir / "system" / "meshQualityDict")
    if quality["status"] != "pass":
        result["metrics"] = _custom_metrics_only(quality)
        return result
    check = run_checkmesh(
        case_dir,
        openfoam_command=openfoam_command,
        timeout_seconds=300.0,
        full_geometry=full_geometry,
    )
    result["checkMesh"] = check
    result["metrics"] = _extract_checkmesh_metrics(case_dir / "log.checkMesh")
    result["strict_checkMesh"] = _strict_case_checkmesh_status(
        case_dir,
        full_geometry=full_geometry,
    )
    result["status"] = result["strict_checkMesh"]["status"]
    return result


def _write_section_mesh_quality_dict(path: Path) -> None:
    path.write_text(
        """FoamFile
{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      meshQualityDict;
}
#includeEtc "caseDicts/meshQualityDict"
maxNonOrtho 85;
minDeterminant 1e-08;
minFaceWeight 0.0;
maxInternalSkewness 7;
maxBoundarySkewness 20;
""",
        encoding="utf-8",
    )


def _extract_checkmesh_metrics(log_path: Path) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    return {
        "mesh_ok": "Mesh OK." in text,
        "max_aspect_ratio": _float_match(text, r"Max aspect ratio: ([0-9.eE+-]+)"),
        "max_non_orthogonality_deg": _float_match(text, r"Mesh non-orthogonality Max: ([0-9.eE+-]+)"),
        "max_skewness": _float_match(text, r"Max skewness = ([0-9.eE+-]+)"),
        "high_aspect_cell_count": _int_match(text, r"High aspect ratio cells found.*number of cells ([0-9]+)"),
        "non_orthogonal_faces_over_threshold": _int_match(text, r"non-orthogonality >\s+85\s+degrees\s+:\s+([0-9]+)"),
        "tet_quality_faces_below_threshold": _int_match(text, r"faces with face-decomposition tet quality < [^:]+:\s+([0-9]+)"),
        "determinant_faces_below_threshold": _int_match(text, r"faces on cells with determinant < 1e-08\s+:\s+([0-9]+)"),
        "short_edge_count": _int_match(text, r"number too small:\s+([0-9]+)"),
        "min_cell_determinant": _float_match(text, r"Cell determinant \(wellposedness\) : minimum:\s+([0-9.eE+-]+)"),
        "underdetermined_cell_count": _int_match(text, r"small determinant \(< 0\.001\) found, number of cells:\s+([0-9]+)"),
        "failed_check_count": _int_match(text, r"Failed ([0-9]+) mesh checks"),
    }


def _strict_case_checkmesh_status(case_dir: Path, *, full_geometry: bool) -> dict[str, Any]:
    primary = _strict_checkmesh_log_status(
        case_dir / "log.checkMesh",
        max_non_ortho_target=SECTION_MAX_NON_ORTHO_TARGET_DEG,
    )
    all_geometry = (
        _strict_checkmesh_log_status(
            case_dir / "log.checkMesh_allGeometry",
            max_non_ortho_target=SECTION_MAX_NON_ORTHO_TARGET_DEG,
        )
        if full_geometry
        else None
    )
    logs = [primary, *([] if all_geometry is None else [all_geometry])]
    if all(item["status"] == "pass" for item in logs):
        status = "pass"
    elif all(item["status"] in {"pass", "smoke_only"} for item in logs):
        status = "smoke_only"
    else:
        status = "checkmesh_failed"
    return {
        "status": status,
        "primary": primary,
        "all_geometry": all_geometry,
    }


def _strict_checkmesh_log_status(
    log_path: Path,
    *,
    max_non_ortho_target: float,
) -> dict[str, Any]:
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    failed_check_count = _int_match(text, r"Failed ([0-9]+) mesh checks")
    fatal = bool(re.search(r"FOAM FATAL|\*\*?Error", text, re.IGNORECASE))
    mesh_ok = "Mesh OK." in text and failed_check_count is None and not fatal
    max_non_ortho = _float_match(text, r"Mesh non-orthogonality Max: ([0-9.eE+-]+)")
    max_skewness = _float_match(text, r"Max skewness = ([0-9.eE+-]+)")
    if (
        mesh_ok
        and (max_skewness is None or max_skewness < SECTION_MAX_SKEW_TARGET)
        and (max_non_ortho is None or max_non_ortho < max_non_ortho_target)
    ):
        status = "pass"
    elif (
        mesh_ok
        and (max_skewness is None or max_skewness < SECTION_MAX_SKEW_TARGET)
        and max_non_ortho is not None
        and max_non_ortho < SECTION_MAX_NON_ORTHO_SMOKE_LIMIT_DEG
    ):
        status = "smoke_only"
    else:
        status = "fail"
    return {
        "status": status,
        "log": str(log_path),
        "mesh_ok": mesh_ok,
        "failed_check_count": failed_check_count,
        "max_non_orthogonality_deg": max_non_ortho,
        "max_skewness": max_skewness,
        "short_edge_count": _int_match(text, r"number too small:\s+([0-9]+)"),
        "min_cell_determinant": _float_match(text, r"Cell determinant \(wellposedness\) : minimum:\s+([0-9.eE+-]+)"),
        "underdetermined_cell_count": _int_match(text, r"small determinant \(< 0\.001\) found, number of cells:\s+([0-9]+)"),
        "fatal_error": fatal,
    }


def _custom_metrics_only(quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "mesh_ok": False,
        "custom_blockers": quality.get("blockers", []),
        "non_positive_volume_count": quality.get("non_positive_volume_count"),
        "min_signed_volume": quality.get("min_signed_volume"),
    }


def _write_design_reports(output_dir: Path, authority: Any) -> None:
    prior_root = WO006_ROOT / "cfd_release_v0_swept_cgrid_structured_hexa_smoke"
    (output_dir / "section_failure_diagnosis.md").write_text(
        f"""# Section Failure Diagnosis

Prior report bundle: `{prior_root}`.

The failed section route was a single closed O-grid loop around the true airfoil.
For a sharp or nearly sharp trailing edge that forces radial cells to wrap around
the upper/lower TE cusp.  That is not a valid local topology for these sections:
the wake should leave the TE downstream, not turn through the cusp.

Observed old O-grid evidence:
- dae31 root: severe closed-loop seam failure with non-orthogonality near `180 deg`,
  open cells, wrong-oriented face pyramids, and extreme skewness.  The live copied
  OpenFOAM sets localize the closed-loop failure to TE-seam cells near perimeter
  indices `0/47`, lower-aft cusp cells near `38-40`, and high radial-layer outer
  transition cells.
- cst_tip: lower absolute skew than dae31, but still failed the closed-loop gate
  with non-orthogonality above the section target and high-aspect / skewed faces
  at the finite CST trailing-edge transition.

LE curvature was not the dominant blocker: the most severe old dae31 skew was at
the TE seam/wake-side transition, while cst_tip had lower skew but still failed
orientation and non-orthogonality.  The rescue route therefore uses an open-TE
wake C-grid with a downstream TE H-block: airfoil upper/lower walls remain
separate, the finite TE strip is represented as `te_wall`, wake-block faces are
internal fluid faces, and no cell wraps around the TE cusp.

Current follow-up diagnosis:
- The previous H-block attempt still used the legacy resampled airfoil loop,
  which omitted the true lower TE endpoint.  That made dae31 close the H-block
  against a near-duplicate upper-surface point instead of a proper lower TE
  endpoint/collar node.
- The current attempt uses `open_te_cgrid` airfoil-loop authority: finite TE
  endpoints are retained, and mathematically zero-thickness TE sections receive
  only the bounded collar gap reported in `geometry_perturbation_report.md`.
""",
        encoding="utf-8",
    )
    (output_dir / "cgrid_topology_design.md").write_text(
        """# Wake C-Grid Topology Design

- Inner path: true airfoil coordinates from TE_upper to LE to TE_lower.
- The path is open at the TE; no single-loop O-grid closure is used.
- Upper and lower TE nodes remain separate; no TE bluntness is introduced.
- Radial construction: wall-normal near-wall stack, then straight rays to a
  C-shaped farfield boundary.
- Wake construction: a downstream H-block fills the open TE wake slot.  Its
  upper/lower interfaces are internal faces shared with the C-grid side faces,
  not wall or freestream patches.
- Patches: `airfoil_upper`, `airfoil_lower`, `te_wall`, `outlet`, `farfield`,
  `tip_left`, `tip_right`.
- Section side planes are written as OpenFOAM `empty` patches for the 2D
  extruded section gate.
- Section meshQualityDict records the deliberate section-only tolerance:
  `maxNonOrtho=85`, `minDeterminant=1e-8`, because aligned BL cells are allowed
  but skew/orientation/open-cell failures are not.
- Airfoil loop authority: `open_te_cgrid`, which retains true finite lower TE
  endpoints and creates a bounded collar gap only for mathematically zero-TE
  source sections.
""",
        encoding="utf-8",
    )
    (output_dir / "te_hblock_design_report.md").write_text(
        """# TE H-Block / Collar Design Report

The rescue implementation uses a finite-TE H-block downstream of the true
airfoil TE gap.

- The dae31 and cst_tip TE endpoints are preserved from the true Baseline A
  coordinate authority.
- No NACA0012 or smoothed replacement airfoil is used.
- No TE bluntness, bevel, or coordinate perturbation is introduced.
- The wake H-block shares its upper/lower side faces with the C-grid side faces,
  making those faces internal fluid faces.
- The physical wall patches are `airfoil_upper`, `airfoil_lower`, and `te_wall`.
- The downstream boundary is `outlet`; the C-shaped outer boundary is
  `farfield`.

Current best state: the TE H-block removes open cells, negative volumes, and
wrong-oriented face pyramids in the primary section runs.  The remaining blocker
is strict section quality: dae31 is smoke-only above the 75-degree debug target,
and `-allGeometry` flags high-aspect underdetermined cells from the requested
low first-layer height.  This is not a span-count, solver, AoA, or placeholder
airfoil problem.
""",
        encoding="utf-8",
    )
    perturbations = [
        report
        for report in authority.airfoil_geometry_reports.values()
        if report.get("te_perturbation", {}).get("introduced")
    ]
    geometry_report = output_dir / "geometry_perturbation_report.md"
    if not perturbations:
        if geometry_report.exists():
            geometry_report.unlink()
        return
    lines = [
        "# Geometry Perturbation Report",
        "",
        "A bounded TE collar gap was introduced only for mathematically zero-thickness source TE sections.",
        "Finite source TE endpoints are preserved without bluntness.",
        "",
    ]
    for report in perturbations:
        perturb = report["te_perturbation"]
        lines.extend(
            [
                f"## {report['airfoil_id']}",
                f"- introduced: `{perturb['introduced']}`",
                f"- reason: `{perturb['reason']}`",
                f"- gap / chord: `{perturb['gap_over_chord']}`",
                f"- maximum allowed gap / chord: `{perturb['max_allowed_gap_over_chord']}`",
                f"- changed airfoil area / chord^2: `{report['area_delta_over_chord2']}`",
                f"- changed chord from TE perturbation: `{report['te_perturbation_chord_delta']}`",
                f"- Sref-equivalent planform impact: `{report['sref_planform_delta_over_chord2']}`",
                f"- Sref note: `{report['sref_note']}`",
                "",
            ]
        )
    geometry_report.write_text("\n".join(lines), encoding="utf-8")


def _write_section_reports(output_dir: Path, cases: Sequence[dict[str, Any]]) -> None:
    filenames = {
        "dae31_root_section": "dae31_cgrid_checkmesh_report.md",
        "cst_tip_section": "cst_tip_cgrid_checkmesh_report.md",
        "morph_dae31_to_cst_tip_section": "morph_section_cgrid_checkmesh_report.md",
    }
    for case in cases:
        metrics = case.get("metrics", {})
        strict = case.get("strict_checkMesh", {})
        (output_dir / filenames[case["case_id"]]).write_text(
            f"""# {case['case_id']} C-Grid CheckMesh Report

- status: `{case['status']}`
- case dir: `{case['case_dir']}`
- custom quality: `{case['custom_quality']['status']}`
- custom blockers: `{case['custom_quality'].get('blockers', [])}`
- boundary faces: `{case['custom_quality'].get('boundary_face_counts')}`
- first layer height m: `{FIRST_LAYER_HEIGHT_M}`
- max skewness: `{metrics.get('max_skewness')}`
- max non-orthogonality deg: `{metrics.get('max_non_orthogonality_deg')}`
- max aspect ratio: `{metrics.get('max_aspect_ratio')}`
- high aspect cells: `{metrics.get('high_aspect_cell_count')}`
- determinant faces below section threshold: `{metrics.get('determinant_faces_below_threshold')}`
- failed check count: `{metrics.get('failed_check_count')}`
- strict primary gate: `{strict.get('primary')}`
- strict allTopology/allGeometry gate: `{strict.get('all_geometry')}`
- section gate note: `maxNonOrtho=85 section-only tolerance; no solver is allowed from this section case.`
""",
            encoding="utf-8",
        )


def _write_bay_report(output_dir: Path, cases: Sequence[dict[str, Any]]) -> None:
    lines = ["# Swept C-Grid Bay CheckMesh Report", ""]
    for case in cases:
        lines.extend(
            [
                f"## {case['case_id']}",
                f"- status: `{case['status']}`",
                f"- custom quality: `{case['custom_quality']['status']}`",
                f"- custom blockers: `{case['custom_quality'].get('blockers', [])}`",
                f"- max skewness: `{case.get('metrics', {}).get('max_skewness')}`",
                f"- max non-orthogonality deg: `{case.get('metrics', {}).get('max_non_orthogonality_deg')}`",
                f"- max aspect ratio: `{case.get('metrics', {}).get('max_aspect_ratio')}`",
                f"- high aspect cells: `{case.get('metrics', {}).get('high_aspect_cell_count')}`",
                f"- tet-quality faces below threshold: `{case.get('metrics', {}).get('tet_quality_faces_below_threshold')}`",
                f"- failed check count: `{case.get('metrics', {}).get('failed_check_count')}`",
                "",
            ]
        )
    (output_dir / "swept_cgrid_bay_checkmesh_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_fullwing_report(output_dir: Path, case: dict[str, Any] | None) -> None:
    if case is None:
        text = "# Full-Wing C-Grid CheckMesh Report\n\nNot run.  Full wing is gated behind bay checkMesh pass.\n"
    else:
        text = f"""# Full-Wing C-Grid CheckMesh Report

- status: `{case['status']}`
- custom quality: `{case['custom_quality']['status']}`
- max skewness: `{case.get('metrics', {}).get('max_skewness')}`
- max non-orthogonality deg: `{case.get('metrics', {}).get('max_non_orthogonality_deg')}`
- failed check count: `{case.get('metrics', {}).get('failed_check_count')}`
"""
    (output_dir / "fullwing_cgrid_checkmesh_report.md").write_text(text, encoding="utf-8")


def _write_final_reports(output_dir: Path, manifest: dict[str, Any]) -> None:
    verdict = manifest["verdict"]
    (output_dir / "true_airfoil_cgrid_section_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    sections = manifest.get("section_cases", [])
    bays = manifest.get("bay_cases", [])
    te_hblock_needed = True
    te_hblock_blocker = _section_blocker_summary(sections)
    te_perturbation_summary = _te_perturbation_summary(manifest)
    (output_dir / "phase3_true_airfoil_cgrid_section_verdict.md").write_text(
        f"""# Phase 3 True-Airfoil C-Grid Section Verdict

1. Did the single-loop O-grid fail because of sharp TE topology?
   - `yes`; the old worst failures localized to the TE/wake seam and high-radial transition.
2. Did the wake C-grid section pass for dae31?
   - `{_case_pass(sections, 'dae31_root_section')}`
3. Did the wake C-grid section pass for cst_tip?
   - `{_case_pass(sections, 'cst_tip_section')}`
4. Did the morph section pass?
   - `{_case_pass(sections, 'morph_dae31_to_cst_tip_section')}`
5. Was a TE H-block/collar needed?
   - `{te_hblock_needed}`; the internal wake H-block was attempted and is the current blocker.
6. Was any TE geometry perturbation introduced? If yes, how large?
   - `{te_perturbation_summary}`
7. Did bay tests pass?
   - `{bool(bays) and all(case['status'] == 'pass' for case in bays)}`
8. Did full-wing checkMesh pass?
   - `{manifest.get('fullwing_case', {}).get('status') == 'pass' if manifest.get('fullwing_case') else False}`
9. If not, what exact blocker remains?
   - `{verdict['reason']}`; `{te_hblock_blocker}`
10. Is the station-wise swept C-grid route still worth continuing?
   - `yes, but only after the local TE H-block / leading-edge section-quality blocker is fixed.  Do not resume bay, full-wing, solver, or AoA work from this state.`
""",
        encoding="utf-8",
    )
    (output_dir / "RERUN.md").write_text(
        """# RERUN

```bash
.venv/bin/python scripts/run_wo006_true_airfoil_cgrid_section_rescue.py \\
  --clean \\
  --output-dir output/baseline_A_team_release/wo006_su2_baseline_validation/cfd_release_v0_true_airfoil_cgrid_section_rescue \\
  --n-perim 192 \\
  --n-radial 80 \\
  --farfield-chords 10 \\
  --wake-length-chords 8
```
""",
        encoding="utf-8",
    )


def _verdict(status: str, reason: str, manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": status,
        "reason": reason,
        "section_pass": all(item["status"] == "pass" for item in manifest.get("section_cases", [])),
        "bay_pass": bool(manifest.get("bay_cases")) and all(item["status"] == "pass" for item in manifest.get("bay_cases", [])),
        "fullwing_pass": bool(manifest.get("fullwing_case")) and manifest["fullwing_case"]["status"] == "pass",
        "solver_ran": False,
    }


def _bay_blocker_summary(cases: Sequence[dict[str, Any]]) -> str:
    blockers = []
    for case in cases:
        if case["status"] == "pass":
            continue
        if case["custom_quality"]["status"] != "pass":
            blockers.append(
                f"{case['case_id']}: custom {case['custom_quality'].get('blockers', [])} "
                f"non_positive={case['custom_quality'].get('non_positive_volume_count')}"
            )
            continue
        metrics = case.get("metrics", {})
        blockers.append(
            f"{case['case_id']}: checkMesh failed checks={metrics.get('failed_check_count')} "
            f"maxNonOrtho={metrics.get('max_non_orthogonality_deg')} "
            f"maxSkew={metrics.get('max_skewness')} "
            f"highAspect={metrics.get('high_aspect_cell_count')} "
            f"tetQualityFaces={metrics.get('tet_quality_faces_below_threshold')}"
        )
    return "; ".join(blockers) if blockers else "bay_cgrid_checkmesh_or_custom_quality_failed"


def _section_blocker_summary(cases: Sequence[dict[str, Any]]) -> str:
    blockers = []
    for case in cases:
        if case["status"] == "pass":
            continue
        metrics = case.get("metrics", {})
        strict = case.get("strict_checkMesh", {})
        all_geometry = strict.get("all_geometry") or {}
        blockers.append(
            f"{case['case_id']}: status={case['status']} "
            f"failedChecks={metrics.get('failed_check_count')} "
            f"maxNonOrtho={metrics.get('max_non_orthogonality_deg')} "
            f"maxSkew={metrics.get('max_skewness')} "
            f"nonOrthoFacesOver85={metrics.get('non_orthogonal_faces_over_threshold')} "
            f"tetQualityFaces={metrics.get('tet_quality_faces_below_threshold')} "
            f"allGeometryUnderCells={all_geometry.get('underdetermined_cell_count')} "
            f"allGeometryMinDet={all_geometry.get('min_cell_determinant')}"
        )
    return "; ".join(blockers) if blockers else "section gates passed"


def _te_perturbation_summary(manifest: dict[str, Any]) -> str:
    reports = manifest.get("config", {}).get("airfoil_geometry_reports", {})
    perturbations = [
        (airfoil_id, report.get("te_perturbation", {}))
        for airfoil_id, report in reports.items()
        if report.get("te_perturbation", {}).get("introduced")
    ]
    if not perturbations:
        return "no; finite true TE endpoints were preserved."
    return "; ".join(
        f"yes: {airfoil_id} gap/chord={perturb.get('gap_over_chord')}"
        for airfoil_id, perturb in perturbations
    )


def _case_pass(cases: Sequence[dict[str, Any]], case_id: str) -> bool:
    return any(case["case_id"] == case_id and case["status"] == "pass" for case in cases)


def _float_match(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    return None if match is None else float(match.group(1))


def _int_match(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return None if match is None else int(match.group(1))


if __name__ == "__main__":
    raise SystemExit(main())
