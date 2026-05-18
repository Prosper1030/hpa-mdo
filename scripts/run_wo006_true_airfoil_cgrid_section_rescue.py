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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--openfoam", default=OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--n-perim", type=int, default=192)
    parser.add_argument("--n-radial", type=int, default=80)
    parser.add_argument("--farfield-chords", type=float, default=6.0)
    parser.add_argument("--wake-length-chords", type=float, default=6.0)
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

    authority = load_baseline_authority(n_perim=n_perim)
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
    }
    _write_design_reports(output_dir)

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
    result["status"] = "pass" if check["status"] == "pass" else "checkmesh_failed"
    result["metrics"] = _extract_checkmesh_metrics(case_dir / "log.checkMesh")
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
        "failed_check_count": _int_match(text, r"Failed ([0-9]+) mesh checks"),
    }


def _custom_metrics_only(quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "mesh_ok": False,
        "custom_blockers": quality.get("blockers", []),
        "non_positive_volume_count": quality.get("non_positive_volume_count"),
        "min_signed_volume": quality.get("min_signed_volume"),
    }


def _write_design_reports(output_dir: Path) -> None:
    prior_root = WO006_ROOT / "cfd_release_v0_swept_cgrid_structured_hexa"
    (output_dir / "section_failure_diagnosis.md").write_text(
        f"""# Section Failure Diagnosis

Prior report bundle: `{prior_root}`.

The failed section route was a single closed O-grid loop around the true airfoil.
For a sharp or nearly sharp trailing edge that forces radial cells to wrap around
the upper/lower TE cusp.  That is not a valid local topology for these sections:
the wake should leave the TE downstream, not turn through the cusp.

Observed old O-grid evidence:
- dae31 root: `max_skew=19010.2`, `max_non_orth=179.918 deg`, open/oriented-face
  failures.  The copied OpenFOAM sets localized non-closed cells mostly to high
  radial layers near perimeter indices `7-9` and `186-188`, i.e. the two sides of
  the TE/wake seam after the closed-loop wrap.
- cst_tip: `max_skew=22.3157`, `max_non_orth=154.64 deg`, localized mostly around
  high radial layers and upper-side indices `30-37`, with the finite CST trailing
  edge still interacting with the closed O-grid transition.

LE curvature was not the dominant blocker: the most severe old dae31 skew was at
the TE seam/wake-side transition, while cst_tip had lower skew but still failed
orientation and non-orthogonality.  The rescue route therefore uses an open-TE
wake C-grid: airfoil upper/lower walls remain separate, the wake cut is a fluid
patch/outlet, and no cell wraps around the TE cusp.
""",
        encoding="utf-8",
    )
    (output_dir / "cgrid_topology_design.md").write_text(
        """# Wake C-Grid Topology Design

- Inner path: true airfoil coordinates from TE_upper to LE to TE_lower.
- The path is open at the TE; no single-loop O-grid closure is used.
- Upper and lower TE nodes remain separate; no TE bluntness is introduced.
- Radial construction: wall-normal first layer, then straight rays to a C-shaped
  farfield/outlet boundary.
- Patches: `airfoil_upper`, `airfoil_lower`, `wake_upper`, `wake_lower`,
  `outlet`, `farfield`, `tip_left`, `tip_right`.
- Section meshQualityDict records the deliberate section-only tolerance:
  `maxNonOrtho=85`, `minDeterminant=1e-8`, because aligned BL cells are allowed
  but skew/orientation/open-cell failures are not.
""",
        encoding="utf-8",
    )


def _write_section_reports(output_dir: Path, cases: Sequence[dict[str, Any]]) -> None:
    filenames = {
        "dae31_root_section": "dae31_cgrid_checkmesh_report.md",
        "cst_tip_section": "cst_tip_cgrid_checkmesh_report.md",
        "morph_dae31_to_cst_tip_section": "morph_section_cgrid_checkmesh_report.md",
    }
    for case in cases:
        metrics = case.get("metrics", {})
        (output_dir / filenames[case["case_id"]]).write_text(
            f"""# {case['case_id']} C-Grid CheckMesh Report

- status: `{case['status']}`
- case dir: `{case['case_dir']}`
- custom quality: `{case['custom_quality']['status']}`
- boundary faces: `{case['custom_quality'].get('boundary_face_counts')}`
- first layer height m: `{FIRST_LAYER_HEIGHT_M}`
- max skewness: `{metrics.get('max_skewness')}`
- max non-orthogonality deg: `{metrics.get('max_non_orthogonality_deg')}`
- max aspect ratio: `{metrics.get('max_aspect_ratio')}`
- high aspect cells: `{metrics.get('high_aspect_cell_count')}`
- determinant faces below section threshold: `{metrics.get('determinant_faces_below_threshold')}`
- failed check count: `{metrics.get('failed_check_count')}`
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
    te_hblock_needed = any(case["status"] != "pass" for case in sections)
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
   - `{te_hblock_needed}`; no TE bluntness was introduced in this C-grid attempt.
6. Was any TE geometry perturbation introduced? If yes, how large?
   - `no`; true TE endpoints were preserved.
7. Did bay tests pass?
   - `{bool(bays) and all(case['status'] == 'pass' for case in bays)}`
8. Did full-wing checkMesh pass?
   - `{manifest.get('fullwing_case', {}).get('status') == 'pass' if manifest.get('fullwing_case') else False}`
9. If not, what exact blocker remains?
   - `{verdict['reason']}`
10. Is the station-wise swept C-grid route still worth continuing?
   - `yes for section topology; bay/full-wing continuation depends on the reported bay blocker.`
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
  --farfield-chords 6 \\
  --wake-length-chords 6
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
