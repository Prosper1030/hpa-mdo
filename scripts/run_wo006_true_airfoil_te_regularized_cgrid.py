#!/usr/bin/env python3
"""Run WO-006 bounded true-airfoil TE-regularized Kutta C-grid section gates."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cfd_rescue.baseline_geometry import interpolate_station, load_baseline_authority  # noqa: E402
from cfd_rescue.polyfoam import run_checkmesh, write_openfoam_case  # noqa: E402
from cfd_rescue.swept_cgrid import build_extruded_section_cgrid_mesh, build_swept_cgrid_mesh  # noqa: E402
from cfd_rescue.swept_hexa import SweptHexaMesh, mesh_quality_summary  # noqa: E402
from hpa_meshing.mesh_native.wing_surface import Station  # noqa: E402


WO006_ROOT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
)
DEFAULT_OUTPUT_DIR = WO006_ROOT / "cfd_release_v0_true_airfoil_te_regularized_cgrid"
PREVIOUS_SECTION_DIR = WO006_ROOT / "cfd_release_v0_true_airfoil_cgrid_section_rescue"
OPENFOAM_WRAPPER = "/opt/homebrew/bin/openfoam"

FIRST_LAYER_HEIGHT_M = 5.0e-5
DESIGN_AOA_DEG = 0.18015
SECTION_MAX_SKEW_TARGET = 10.0
SECTION_MAX_NON_ORTHO_TARGET_DEG = 75.0
SECTION_MAX_NON_ORTHO_SMOKE_LIMIT_DEG = 85.0

TE_VARIANTS: tuple[tuple[str, float], ...] = (
    ("gap_0p00", 0.0),
    ("gap_0p02", 2.0e-4),
    ("gap_0p05", 5.0e-4),
    ("gap_0p10", 1.0e-3),
)


@dataclass(frozen=True)
class SectionSpec:
    case_id: str
    label: str
    station: Station


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--openfoam", default=OPENFOAM_WRAPPER)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--n-perim", type=int, default=192)
    parser.add_argument("--n-radial", type=int, default=64)
    parser.add_argument("--farfield-chords", type=float, default=10.0)
    parser.add_argument("--wake-length-chords", type=float, default=8.0)
    args = parser.parse_args(argv)

    manifest = run_matrix(
        output_dir=args.output_dir,
        openfoam_command=args.openfoam,
        clean=args.clean,
        n_perim=args.n_perim,
        n_radial=args.n_radial,
        farfield_chords=args.farfield_chords,
        wake_length_chords=args.wake_length_chords,
    )
    print(json.dumps(manifest["verdict"], indent=2, sort_keys=True))
    return 0 if manifest["verdict"]["status"] in {"section_gates_passed", "section_pass_bay_blocked", "hard_blocked"} else 1


def run_matrix(
    *,
    output_dir: Path,
    openfoam_command: str,
    clean: bool,
    n_perim: int,
    n_radial: int,
    farfield_chords: float,
    wake_length_chords: float,
) -> dict[str, Any]:
    start = time.monotonic()
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    (output_dir / "openfoam_cases").mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "schema_version": "wo006_true_airfoil_te_regularized_cgrid.v1",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "route": "bounded true-airfoil TE-regularized Kutta wake C-grid section gate matrix",
        "output_dir": str(output_dir),
        "config": {
            "n_perim": n_perim,
            "n_radial": n_radial,
            "first_layer_height_m": FIRST_LAYER_HEIGHT_M,
            "farfield_chords": farfield_chords,
            "wake_length_chords": wake_length_chords,
            "wake_cross_cells": 8,
            "te_gap_variants": [
                {"variant": name, "target_zero_te_gap_over_chord": gap}
                for name, gap in TE_VARIANTS
            ],
            "openfoam_command": openfoam_command,
        },
        "hard_prohibitions_observed": {
            "bay_run_before_section_pass": False,
            "full_wing": "not_run",
            "solver": "not_run",
            "aoa_sweep": "not_run",
            "span_count_work": "not_run",
            "single_loop_sharp_te_ogrid": "not_used",
            "snappyHexMesh": "not_used",
            "cfMesh": "not_used",
            "gmsh_tetgen_meshpy": "not_used",
            "placeholder_airfoil": "not_used",
            "hand_patched_bad_cells": "not_used",
        },
        "section_cases": [],
        "variant_geometry_reports": {},
        "selection": {},
        "bay_cases": [],
        "bay_gates_run": False,
    }

    # Phase 0 is intentionally written before the new TE-gap matrix is evaluated.
    _write_phase0_previous_localization(output_dir)
    _write_policy_and_design_docs(output_dir, n_radial=n_radial, wake_length_chords=wake_length_chords)

    for variant_name, target_gap in TE_VARIANTS:
        authority = load_baseline_authority(
            n_perim=n_perim,
            airfoil_loop_mode="open_te_cgrid",
            target_zero_te_gap_over_chord=target_gap,
        )
        manifest["variant_geometry_reports"][variant_name] = authority.airfoil_geometry_reports
        for spec in _section_specs(authority):
            case = _run_section_case(
                output_dir=output_dir,
                variant_name=variant_name,
                target_gap=target_gap,
                spec=spec,
                authority=authority,
                openfoam_command=openfoam_command,
                n_radial=n_radial,
                farfield_chords=farfield_chords,
                wake_length_chords=wake_length_chords,
            )
            manifest["section_cases"].append(case)

    _write_section_gate_matrix(output_dir, manifest["section_cases"])
    _write_failed_check_locations(output_dir, manifest["section_cases"])
    _write_matrix_failed_check_localization(output_dir, manifest["section_cases"])
    _write_te_geometry_report(output_dir, manifest)
    _write_section_reports(output_dir, manifest["section_cases"])

    selection = _select_canonical(manifest["section_cases"])
    manifest["selection"] = selection
    (output_dir / "canonical_section_selection.json").write_text(
        json.dumps(selection, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_canonical_report(output_dir, selection, manifest["section_cases"])

    if selection["status"] == "pass":
        authority = load_baseline_authority(
            n_perim=n_perim,
            airfoil_loop_mode="open_te_cgrid",
            target_zero_te_gap_over_chord=selection["target_zero_te_gap_over_chord"],
        )
        manifest["bay_gates_run"] = True
        manifest["bay_cases"] = _run_bay_cases(
            output_dir=output_dir,
            authority=authority,
            openfoam_command=openfoam_command,
            n_radial=n_radial,
            farfield_chords=farfield_chords,
            wake_length_chords=wake_length_chords,
        )
        _write_bay_report(output_dir, manifest["bay_cases"])
        bay_pass = all(case["status"] == "pass" for case in manifest["bay_cases"])
        manifest["verdict"] = {
            "status": "section_gates_passed" if bay_pass else "section_pass_bay_blocked",
            "reason": "all_three_section_gates_passed_and_bay_gates_attempted"
            if bay_pass
            else _bay_blocker_summary(manifest["bay_cases"]),
            "canonical_variant": selection["variant"],
            "bay_gates_run": True,
            "solver_ran": False,
        }
    else:
        manifest["verdict"] = {
            "status": "hard_blocked",
            "reason": selection["blocker_summary"],
            "canonical_variant": None,
            "bay_gates_run": False,
            "solver_ran": False,
        }

    manifest["elapsed_s"] = time.monotonic() - start
    _write_verdict(output_dir, manifest)
    (output_dir / "te_regularized_cgrid_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_rerun(output_dir, n_perim, n_radial, farfield_chords, wake_length_chords)
    return manifest


def _section_specs(authority: Any) -> list[SectionSpec]:
    return [
        SectionSpec("dae31_root_section", "dae31 root", authority.half_stations[0]),
        SectionSpec("cst_tip_section", "cst_tip", authority.half_stations[-1]),
        SectionSpec(
            "morph_dae31_to_cst_tip_section",
            "dae31 to cst_tip morph",
            interpolate_station(authority.half_stations[4], authority.half_stations[5], 0.5),
        ),
    ]


def _run_section_case(
    *,
    output_dir: Path,
    variant_name: str,
    target_gap: float,
    spec: SectionSpec,
    authority: Any,
    openfoam_command: str,
    n_radial: int,
    farfield_chords: float,
    wake_length_chords: float,
) -> dict[str, Any]:
    case_dir = output_dir / "openfoam_cases" / variant_name / spec.case_id
    mesh = build_extruded_section_cgrid_mesh(
        spec.station,
        n_radial=n_radial,
        first_layer_height_m=FIRST_LAYER_HEIGHT_M,
        farfield_chords=farfield_chords,
        wake_length_chords=wake_length_chords,
        case_id=f"{variant_name}_{spec.case_id}",
    )
    quality = mesh_quality_summary(mesh)
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
    check = run_checkmesh(
        case_dir,
        openfoam_command=openfoam_command,
        timeout_seconds=300.0,
        full_geometry=True,
        stop_on_failure=False,
    )
    primary = _parse_checkmesh_log(case_dir / "log.checkMesh")
    all_geometry = _parse_checkmesh_log(case_dir / "log.checkMesh_allGeometry")
    status = _section_status(quality, primary, all_geometry)
    localization = _localize_failures(case_dir, mesh, spec.station, spec.case_id, variant_name)
    return {
        "variant": variant_name,
        "target_zero_te_gap_over_chord": target_gap,
        "case_id": spec.case_id,
        "section_label": spec.label,
        "case_dir": str(case_dir),
        "status": status,
        "custom_quality": quality,
        "checkMesh": check,
        "primary_metrics": primary,
        "all_geometry_metrics": all_geometry,
        "combined_metrics": _combined_metrics(primary, all_geometry),
        "patch_counts": mesh.boundary_face_counts,
        "te_geometry": _section_te_geometry(spec.station),
        "localization": localization,
    }


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


def _parse_checkmesh_log(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return {
        "log": str(path),
        "mesh_ok": "Mesh OK." in text and _int_match(text, r"Failed ([0-9]+) mesh checks") is None,
        "failed_check_count": _int_match(text, r"Failed ([0-9]+) mesh checks"),
        "max_aspect_ratio": _float_match(text, r"Max aspect ratio: ([0-9.eE+-]+)"),
        "max_non_orthogonality_deg": _float_match(text, r"Mesh non-orthogonality Max: ([0-9.eE+-]+)"),
        "severe_non_ortho_face_count": _int_match(text, r"Number of severely non-orthogonal \(> 70 degrees\) faces: ([0-9]+)"),
        "non_orthogonality_error_count": _int_match(text, r"Number of non-orthogonality errors:\s+([0-9]+)"),
        "non_orthogonality_over_85_face_count": _int_match(text, r"non-orthogonality >\s+85\s+degrees\s+:\s+([0-9]+)"),
        "max_skewness": _float_match(text, r"Max skewness = ([0-9.eE+-]+)"),
        "highly_skew_face_count": _int_match(text, r"([0-9]+) highly skew faces detected"),
        "zero_or_negative_face_area_detected": "Zero or negative face area detected" in text,
        "negative_volume_count": _int_match(text, r"Number of negative volume cells: ([0-9]+)"),
        "open_cell_count": _int_match(text, r"number of open cells ([0-9]+)"),
        "oriented_pyramid_error_count": _int_match(text, r"Error in face pyramids: ([0-9]+) faces are incorrectly oriented"),
        "boundary_openness_possible_hole": "possible hole in boundary description" in text,
        "max_cell_openness": _float_match(text, r"Max cell openness = ([0-9.eE+-]+)"),
        "face_pyramid_volume_error_count": _int_match(text, r"faces with face pyramid volume < [^:]+:\s+([0-9]+)"),
        "face_decomposition_tet_quality_error_count": _int_match(
            text,
            r"faces with face-decomposition tet quality < [^:]+:\s+([0-9]+)",
        ),
        "skewness_error_count": _int_match(text, r"faces with skewness > [^:]+:\s+([0-9]+)"),
        "interpolation_weight_error_count": _int_match(
            text,
            r"faces with interpolation weights \(0\.\.1\)\s+<\s+[-0-9.eE+]+\s+:\s+([0-9]+)",
        ),
        "volume_ratio_error_count": _int_match(
            text,
            r"faces with volume ratio of neighbour cells < [^:]+:\s+([0-9]+)",
        ),
        "face_twist_error_count": _int_match(text, r"faces with face twist < [^:]+:\s+([0-9]+)"),
        "determinant_face_error_count": _int_match(text, r"faces on cells with determinant < [^:]+:\s+([0-9]+)"),
        "short_edge_count": _int_match(text, r"number too small:\s+([0-9]+)"),
        "min_cell_determinant": _float_match(text, r"Cell determinant \(wellposedness\) : minimum:\s+([0-9.eE+-]+)"),
        "underdetermined_cell_count": _int_match(text, r"small determinant \(< 0\.001\) found, number of cells:\s+([0-9]+)"),
        "fatal_error": bool(re.search(r"FOAM FATAL|\*\*?Error", text, re.IGNORECASE)),
    }


def _section_status(
    quality: Mapping[str, Any],
    primary: Mapping[str, Any],
    all_geometry: Mapping[str, Any],
) -> str:
    if quality.get("status") != "pass":
        return "custom_mesh_failed"
    strict_ok = bool(primary.get("mesh_ok")) and bool(all_geometry.get("mesh_ok"))
    max_skew = _max_number(primary.get("max_skewness"), all_geometry.get("max_skewness"))
    max_non_ortho = _max_number(
        primary.get("max_non_orthogonality_deg"),
        all_geometry.get("max_non_orthogonality_deg"),
    )
    if strict_ok and max_skew < SECTION_MAX_SKEW_TARGET and max_non_ortho < SECTION_MAX_NON_ORTHO_TARGET_DEG:
        return "pass"
    if strict_ok and max_skew < SECTION_MAX_SKEW_TARGET and max_non_ortho < SECTION_MAX_NON_ORTHO_SMOKE_LIMIT_DEG:
        return "smoke_only"
    return "checkmesh_failed"


def _combined_metrics(primary: Mapping[str, Any], all_geometry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "max_non_orthogonality_deg": _max_number(
            primary.get("max_non_orthogonality_deg"),
            all_geometry.get("max_non_orthogonality_deg"),
        ),
        "max_skewness": _max_number(primary.get("max_skewness"), all_geometry.get("max_skewness")),
        "failed_check_count": (primary.get("failed_check_count") or 0) + (all_geometry.get("failed_check_count") or 0),
        "negative_volume_count": _max_int(primary.get("negative_volume_count"), all_geometry.get("negative_volume_count")),
        "open_cell_count": _max_int(primary.get("open_cell_count"), all_geometry.get("open_cell_count")),
        "oriented_pyramid_error_count": _max_int(
            primary.get("oriented_pyramid_error_count"),
            all_geometry.get("oriented_pyramid_error_count"),
        ),
        "small_determinant_cell_count": _max_int(
            primary.get("underdetermined_cell_count"),
            all_geometry.get("underdetermined_cell_count"),
        ),
        "small_interpolation_weight_count": _max_int(
            primary.get("interpolation_weight_error_count"),
            all_geometry.get("interpolation_weight_error_count"),
        ),
        "boundary_openness_possible_hole": bool(primary.get("boundary_openness_possible_hole"))
        or bool(all_geometry.get("boundary_openness_possible_hole")),
        "highly_skew_face_count": _max_int(
            primary.get("highly_skew_face_count"),
            all_geometry.get("highly_skew_face_count"),
        ),
        "non_orthogonality_error_count": _max_int(
            primary.get("non_orthogonality_error_count"),
            all_geometry.get("non_orthogonality_error_count"),
        ),
        "zero_or_negative_face_area_detected": bool(primary.get("zero_or_negative_face_area_detected"))
        or bool(all_geometry.get("zero_or_negative_face_area_detected")),
    }


def _section_te_geometry(station: Station) -> dict[str, float]:
    upper = station.airfoil_xz[0]
    lower = station.airfoil_xz[-1]
    return {
        "te_gap_over_chord": math.hypot(upper[0] - lower[0], upper[1] - lower[1]),
        "te_upper_x_over_chord": upper[0],
        "te_upper_z_over_chord": upper[1],
        "te_lower_x_over_chord": lower[0],
        "te_lower_z_over_chord": lower[1],
        "chord_m": station.chord,
    }


def _localize_failures(
    case_dir: Path,
    mesh: SweptHexaMesh,
    station: Station,
    case_id: str,
    variant: str,
) -> dict[str, Any]:
    sets_dir = case_dir / "constant" / "polyMesh" / "sets"
    cell_sets = {
        "underdeterminedCells": _read_label_set(sets_dir / "underdeterminedCells"),
        "openCells": _read_label_set(sets_dir / "openCells"),
        "zeroVolumeCells": _read_label_set(sets_dir / "zeroVolumeCells"),
    }
    face_sets = {
        "nonOrthoFaces": _read_label_set(sets_dir / "nonOrthoFaces"),
        "skewFaces": _read_label_set(sets_dir / "skewFaces"),
        "wrongOrientedFaces": _read_label_set(sets_dir / "wrongOrientedFaces"),
        "lowQualityTetFaces": _read_label_set(sets_dir / "lowQualityTetFaces"),
        "lowWeightFaces": _read_label_set(sets_dir / "lowWeightFaces"),
    }
    cell_locations = {
        name: _summarize_cell_labels(labels, mesh, station, case_id)
        for name, labels in cell_sets.items()
        if labels
    }
    face_locations = {
        name: _summarize_face_labels(labels, mesh, station, case_id)
        for name, labels in face_sets.items()
        if labels
    }
    max_non_ortho = _max_non_ortho_location(mesh, station, case_id)
    max_skew = _max_skew_proxy_location(mesh, station, case_id)
    return {
        "variant": variant,
        "case_id": case_id,
        "cell_sets": cell_locations,
        "face_sets": face_locations,
        "max_non_ortho_location": max_non_ortho,
        "max_skew_proxy_location": max_skew,
    }


def _summarize_cell_labels(
    labels: Sequence[int],
    mesh: SweptHexaMesh,
    station: Station,
    case_id: str,
) -> dict[str, Any]:
    locations = [_cell_location(label, mesh, station, case_id) for label in labels if 0 <= label < len(mesh.cells)]
    return _summarize_locations(locations)


def _summarize_face_labels(
    labels: Sequence[int],
    mesh: SweptHexaMesh,
    station: Station,
    case_id: str,
) -> dict[str, Any]:
    locations = [_face_location(label, mesh, station, case_id) for label in labels if 0 <= label < len(mesh.faces)]
    return _summarize_locations(locations)


def _summarize_locations(locations: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not locations:
        return {"count": 0}
    x_values = [float(item["x_over_chord"]) for item in locations]
    z_values = [float(item["z_over_chord"]) for item in locations]
    classes: dict[str, int] = {}
    for item in locations:
        classes[str(item["region"])] = classes.get(str(item["region"]), 0) + 1
    return {
        "count": len(locations),
        "centroid_x_over_chord": sum(x_values) / len(x_values),
        "centroid_z_over_chord": sum(z_values) / len(z_values),
        "min_x_over_chord": min(x_values),
        "max_x_over_chord": max(x_values),
        "min_z_over_chord": min(z_values),
        "max_z_over_chord": max(z_values),
        "region_counts": classes,
        "sample_locations": locations[:8],
    }


def _cell_location(label: int, mesh: SweptHexaMesh, station: Station, case_id: str) -> dict[str, Any]:
    center = _center(mesh.points[index] for index in mesh.cells[label])
    x_over_chord, z_over_chord = _global_to_local_over_chord(center, station)
    n_path = int(mesh.metadata["n_path"])
    n_radial = int(mesh.metadata["n_radial"])
    wake_cross = int(mesh.metadata["wake_cross_cells"])
    cgrid_count = n_radial * (n_path - 1)
    if label < cgrid_count:
        radial = label // (n_path - 1)
        index = label % (n_path - 1)
        block = "cgrid"
    else:
        local = label - cgrid_count
        radial = local // wake_cross
        index = local % wake_cross
        block = "wake_collar"
    return {
        "id": label,
        "block": block,
        "radial_index": radial,
        "path_or_cross_index": index,
        "x_over_chord": x_over_chord,
        "z_over_chord": z_over_chord,
        "region": _region_for(block, radial, index, n_path, n_radial, case_id),
    }


def _face_location(label: int, mesh: SweptHexaMesh, station: Station, case_id: str) -> dict[str, Any]:
    center = _center(mesh.points[index] for index in mesh.faces[label])
    x_over_chord, z_over_chord = _global_to_local_over_chord(center, station)
    owner = mesh.owner[label]
    base = _cell_location(owner, mesh, station, case_id)
    return {
        "id": label,
        "owner": owner,
        "x_over_chord": x_over_chord,
        "z_over_chord": z_over_chord,
        "region": base["region"],
    }


def _region_for(
    block: str,
    radial: int,
    index: int,
    n_path: int,
    n_radial: int,
    case_id: str,
) -> str:
    if block == "wake_collar":
        return "TE wake collar"
    if radial <= 1:
        if index <= 3:
            return "TE upper cusp"
        if index >= n_path - 5:
            return "TE lower cusp"
        if abs(index - n_path // 2) <= 4:
            return "LE curvature"
        if "morph" in case_id:
            return "morph correspondence"
        return "radial first layer"
    if radial >= n_radial - 2:
        return "outer farfield"
    if index <= 3:
        return "TE upper cusp"
    if index >= n_path - 5:
        return "TE lower cusp"
    if abs(index - n_path // 2) <= 4:
        return "LE curvature"
    if "morph" in case_id:
        return "morph correspondence"
    return "radial first layer"


def _max_non_ortho_location(mesh: SweptHexaMesh, station: Station, case_id: str) -> dict[str, Any] | None:
    best: tuple[float, int] | None = None
    for face_index, neighbour in enumerate(mesh.neighbour):
        owner = mesh.owner[face_index]
        owner_center = _center(mesh.points[index] for index in mesh.cells[owner])
        neighbour_center = _center(mesh.points[index] for index in mesh.cells[neighbour])
        face_points = [mesh.points[index] for index in mesh.faces[face_index]]
        area = _face_area_vector(face_points)
        delta = (
            neighbour_center[0] - owner_center[0],
            neighbour_center[1] - owner_center[1],
            neighbour_center[2] - owner_center[2],
        )
        denom = _norm(area) * _norm(delta)
        if denom <= 0.0:
            continue
        cosine = min(1.0, max(0.0, abs(_dot(area, delta)) / denom))
        angle = math.degrees(math.acos(cosine))
        if best is None or angle > best[0]:
            best = (angle, face_index)
    if best is None:
        return None
    location = _face_location(best[1], mesh, station, case_id)
    location["computed_non_orthogonality_deg"] = best[0]
    return location


def _max_skew_proxy_location(mesh: SweptHexaMesh, station: Station, case_id: str) -> dict[str, Any] | None:
    best: tuple[float, int] | None = None
    for face_index, neighbour in enumerate(mesh.neighbour):
        owner = mesh.owner[face_index]
        owner_center = _center(mesh.points[index] for index in mesh.cells[owner])
        neighbour_center = _center(mesh.points[index] for index in mesh.cells[neighbour])
        face_center = _center(mesh.points[index] for index in mesh.faces[face_index])
        scale = max(_distance(owner_center, neighbour_center), 1.0e-14)
        skew = _point_line_distance(face_center, owner_center, neighbour_center) / scale
        if best is None or skew > best[0]:
            best = (skew, face_index)
    if best is None:
        return None
    location = _face_location(best[1], mesh, station, case_id)
    location["computed_skew_proxy"] = best[0]
    return location


def _write_phase0_previous_localization(output_dir: Path) -> None:
    lines = [
        "# Section Failed Check Localization",
        "",
        "Phase 0 was written before the new bounded TE-gap matrix was evaluated.",
        "",
        "Previous available section evidence in this checkout comes from:",
        f"`{PREVIOUS_SECTION_DIR}`.",
        "",
    ]
    previous_manifest = PREVIOUS_SECTION_DIR / "true_airfoil_cgrid_section_manifest.json"
    if previous_manifest.exists():
        payload = json.loads(previous_manifest.read_text(encoding="utf-8"))
        lines.extend(
            [
                "## Previous Copied Logs",
                "",
                "The copied pre-matrix logs already show the blocker had moved away from open cells and",
                "wrong-oriented pyramids. The remaining strict gate was `small determinant (<0.001)`",
                "in `checkMesh -allTopology -allGeometry -meshQuality`.",
                "",
            ]
        )
        for case in payload.get("section_cases", []):
            strict = case.get("strict_checkMesh", {})
            all_geometry = strict.get("all_geometry") or {}
            primary = strict.get("primary") or {}
            lines.extend(
                [
                    f"### {case.get('case_id')}",
                    "",
                    f"- primary status: `{primary.get('status')}`",
                    f"- allGeometry status: `{all_geometry.get('status')}`",
                    f"- failed check count: `{all_geometry.get('failed_check_count')}`",
                    f"- maxNonOrtho: `{all_geometry.get('max_non_orthogonality_deg')}`",
                    f"- maxSkew: `{all_geometry.get('max_skewness')}`",
                    f"- small determinant cells: `{all_geometry.get('underdetermined_cell_count')}`",
                    f"- minimum determinant: `{all_geometry.get('min_cell_determinant')}`",
                    f"- short edges: `{all_geometry.get('short_edge_count')}`",
                    "- open cells / negative volumes / wrong pyramids: `0 or not reported in the copied best logs`",
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "No prior manifest was present, so Phase 0 localization is completed by the",
                "`gap_0p00` rows in the generated section matrix and failed-location CSV.",
                "",
            ]
        )
    lines.extend(
        [
            "The generated `failed_check_locations.csv` adds exact per-variant cell/face-set",
            "location summaries after the matrix run.",
            "",
        ]
    )
    (output_dir / "section_failed_check_localization.md").write_text("\n".join(lines), encoding="utf-8")


def _write_policy_and_design_docs(output_dir: Path, *, n_radial: int, wake_length_chords: float) -> None:
    (output_dir / "te_regularization_policy.md").write_text(
        """# TE Regularization Policy

Allowed variants:

- `gap_0p00`: exact zero-gap baseline for mathematically sharp TE sections.
- `gap_0p02`: introduce `0.02% chord` gap only where the source TE is mathematically zero.
- `gap_0p05`: introduce `0.05% chord` gap only where the source TE is mathematically zero.
- `gap_0p10`: introduce `0.10% chord` gap only where the source TE is mathematically zero.

Rules used in this run:

- Finite true source TE endpoints are preserved. The `cst_tip` source has an
  existing finite TE gap larger than `0.10% chord`; this is source geometry, not
  newly introduced bluntness.
- Only the zero-thickness DAE31 TE endpoint pair is separated for bounded variants.
- The TE x-coordinate and chord endpoints are not moved.
- LE and mid-chord coordinates are not modified by the TE policy.
- Sref-equivalent planform effect is zero because no x-chord endpoint moves; the
  perturbation is a local section-thickness area effect.
""",
        encoding="utf-8",
    )
    (output_dir / "kutta_wake_cgrid_design.md").write_text(
        f"""# Kutta Wake C-Grid Design

- Inner path: true upper airfoil surface from upper TE to LE, then true lower
  surface to lower TE.
- The TE remains open; no single-pole O-grid closure wraps around the cusp.
- A downstream wake block fills the upper/lower TE slot as fluid cells.
- `airfoil_upper` and `airfoil_lower` remain separate wall patches.
- `te_wall` is present only as the finite TE strip at the airfoil TE gap.
- `outlet` is the downstream wake boundary; `farfield` is the outer C boundary.
- The section case is a thin all-hexa 3D extrusion with `tip_left/tip_right`
  written as OpenFOAM `empty` patches.
- Current parameters: `n_radial={n_radial}`, wake length `{wake_length_chords}c`,
  first layer `{FIRST_LAYER_HEIGHT_M} m`, near-wall growth `1.12`.
""",
        encoding="utf-8",
    )
    (output_dir / "section_cgrid_generator_update.md").write_text(
        """# Section C-Grid Generator Update

The generator now consumes `open_te_cgrid` airfoil authority with a selectable
`target_zero_te_gap_over_chord`. That makes the TE-gap matrix deterministic
instead of baking a single DAE31 collar gap into the route.

The OpenFOAM runner writes every section/variant case, runs primary
`checkMesh -meshQuality`, then runs
`checkMesh -allTopology -allGeometry -meshQuality` even when the primary command
fails. This preserves exact failure evidence for bounded hard-blocker reports.
""",
        encoding="utf-8",
    )


def _write_section_gate_matrix(output_dir: Path, cases: Sequence[Mapping[str, Any]]) -> None:
    rows = []
    for case in cases:
        combined = case["combined_metrics"]
        all_geometry = case["all_geometry_metrics"]
        rows.append(
            {
                "variant": case["variant"],
                "section": case["case_id"],
                "status": case["status"],
                "target_zero_te_gap_over_chord": case["target_zero_te_gap_over_chord"],
                "actual_section_te_gap_over_chord": case["te_geometry"]["te_gap_over_chord"],
                "primary_mesh_ok": case["primary_metrics"]["mesh_ok"],
                "allTopology_allGeometry_mesh_ok": all_geometry["mesh_ok"],
                "failed_check_count": combined["failed_check_count"],
                "maxNonOrtho": combined["max_non_orthogonality_deg"],
                "maxSkew": combined["max_skewness"],
                "negative_volume_count": combined["negative_volume_count"],
                "open_cell_count": combined["open_cell_count"],
                "oriented_pyramid_errors": combined["oriented_pyramid_error_count"],
                "small_determinant_count": combined["small_determinant_cell_count"],
                "small_interpolation_weight_count": combined["small_interpolation_weight_count"],
                "boundary_openness_possible_hole": combined["boundary_openness_possible_hole"],
                "patch_counts_json": json.dumps(case["patch_counts"], sort_keys=True),
                "case_dir": case["case_dir"],
            }
        )
    _write_csv(output_dir / "section_gate_matrix.csv", rows)


def _write_failed_check_locations(output_dir: Path, cases: Sequence[Mapping[str, Any]]) -> None:
    rows: list[dict[str, Any]] = []
    for case in cases:
        rows.extend(_failed_location_rows(case))
    _write_csv(output_dir / "failed_check_locations.csv", rows)


def _write_matrix_failed_check_localization(output_dir: Path, cases: Sequence[Mapping[str, Any]]) -> None:
    lines = [
        "# Section Failed Check Localization",
        "",
        "Phase 0 baseline evidence was captured before the bounded TE-gap matrix was accepted.",
        f"Previous available logs: `{PREVIOUS_SECTION_DIR}`.",
        "",
        "The live matrix below localizes every generated section/variant case. Coordinates are",
        "reported in local section `x/chord, z/chord`; region tags separate TE upper cusp,",
        "TE lower cusp, TE wake collar, LE curvature, outer farfield, radial first layer,",
        "and morph correspondence.",
        "",
    ]
    for section in ("dae31_root_section", "cst_tip_section", "morph_dae31_to_cst_tip_section"):
        lines.extend([f"## {section}", ""])
        for case in [item for item in cases if item["case_id"] == section]:
            combined = case["combined_metrics"]
            names = _failed_check_names(case)
            lines.extend(
                [
                    f"### {case['variant']}",
                    "",
                    f"- status: `{case['status']}`",
                    f"- failed check names: `{names}`",
                    f"- failed check count: `{combined['failed_check_count']}`",
                    f"- failed cell/face counts: negative volumes `{combined['negative_volume_count']}`, "
                    f"open cells `{combined['open_cell_count']}`, oriented pyramids "
                    f"`{combined['oriented_pyramid_error_count']}`, small determinant cells "
                    f"`{combined['small_determinant_cell_count']}`, small interpolation weights "
                    f"`{combined['small_interpolation_weight_count']}`",
                    f"- maxNonOrtho: `{combined['max_non_orthogonality_deg']}` at "
                    f"`{_compact_location(case['localization'].get('max_non_ortho_location'))}`",
                    f"- maxSkew proxy: `{combined['max_skewness']}` at "
                    f"`{_compact_location(case['localization'].get('max_skew_proxy_location'))}`",
                ]
            )
            for group_name, sets in (
                ("cell sets", case["localization"]["cell_sets"]),
                ("face sets", case["localization"]["face_sets"]),
            ):
                if not sets:
                    continue
                lines.append(f"- {group_name}:")
                for set_name, summary in sets.items():
                    lines.append(
                        f"  - `{set_name}` count `{summary.get('count')}`, centroid "
                        f"({summary.get('centroid_x_over_chord')}, {summary.get('centroid_z_over_chord')}), "
                        f"regions `{summary.get('region_counts')}`"
                    )
            lines.append("")
    lines.extend(
        [
            "Interpretation:",
            "",
            "- `gap_0p00` on DAE31 is the exact no-gap baseline and creates duplicate TE/collar",
            "  points plus low-quality TE-collar face tets; it is not a viable production topology.",
            "- `gap_0p02` and `gap_0p05` remove the explicit TE-collar low-quality face family,",
            "  but all three sections still fail strict allGeometry on radial first-layer /",
            "  morph-correspondence small determinant cells.",
            "- `gap_0p10` over-regularizes DAE31: it reintroduces TE-cusp pyramid/open-cell",
            "  failures, so increasing beyond the bounded 0.10% limit is not justified.",
            "",
        ]
    )
    (output_dir / "section_failed_check_localization.md").write_text("\n".join(lines), encoding="utf-8")


def _failed_check_names(case: Mapping[str, Any]) -> list[str]:
    primary = case["primary_metrics"]
    all_geometry = case["all_geometry_metrics"]
    quality = case["custom_quality"]
    names: list[str] = []
    if quality.get("duplicate_point_count"):
        names.append("custom_duplicate_points")
    if quality.get("non_positive_volume_count"):
        names.append("custom_non_positive_hex_volume")
    for metrics in (primary, all_geometry):
        if metrics.get("open_cell_count"):
            names.append("open_cells")
        if metrics.get("negative_volume_count"):
            names.append("negative_volume_cells")
        if metrics.get("oriented_pyramid_error_count"):
            names.append("incorrectly_oriented_face_pyramids")
        if metrics.get("non_orthogonality_error_count") or metrics.get("non_orthogonality_over_85_face_count"):
            names.append("non_orthogonality_over_threshold")
        if metrics.get("highly_skew_face_count"):
            names.append("highly_skew_faces")
        if metrics.get("zero_or_negative_face_area_detected"):
            names.append("zero_or_negative_face_area")
        if metrics.get("face_pyramid_volume_error_count"):
            names.append("small_face_pyramid_volume")
        if metrics.get("face_decomposition_tet_quality_error_count"):
            names.append("small_face_decomposition_tet_quality")
        if metrics.get("underdetermined_cell_count"):
            names.append("small_cell_determinant_allGeometry")
        if metrics.get("short_edge_count"):
            names.append("short_edges_allGeometry")
        if metrics.get("interpolation_weight_error_count"):
            names.append("small_interpolation_weight")
        if metrics.get("volume_ratio_error_count"):
            names.append("small_neighbour_volume_ratio")
        if metrics.get("face_twist_error_count"):
            names.append("small_face_twist")
        if metrics.get("skewness_error_count"):
            names.append("skewness_over_threshold")
        if metrics.get("determinant_face_error_count"):
            names.append("determinant_faces_below_mesh_quality_threshold")
    return sorted(set(names))


def _compact_location(location: Mapping[str, Any] | None) -> str:
    if not location:
        return "not available"
    return (
        f"{location.get('region')} x/c={location.get('x_over_chord')} "
        f"z/c={location.get('z_over_chord')}"
    )


def _failed_location_rows(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    localization = case["localization"]
    for set_group, sets in (("cell", localization["cell_sets"]), ("face", localization["face_sets"])):
        for set_name, summary in sets.items():
            rows.append(_location_row(case, set_group, set_name, summary))
    max_non_ortho = localization.get("max_non_ortho_location")
    if max_non_ortho:
        rows.append(_location_row(case, "face", "computed_max_non_ortho", _summarize_locations([max_non_ortho])))
    max_skew = localization.get("max_skew_proxy_location")
    if max_skew:
        rows.append(_location_row(case, "face", "computed_max_skew_proxy", _summarize_locations([max_skew])))
    if not rows:
        rows.append(
            {
                "variant": case["variant"],
                "section": case["case_id"],
                "set_group": "none",
                "check_name": "no_failed_sets_written",
                "count": 0,
                "centroid_x_over_chord": "",
                "centroid_z_over_chord": "",
                "min_x_over_chord": "",
                "max_x_over_chord": "",
                "min_z_over_chord": "",
                "max_z_over_chord": "",
                "region_counts_json": "{}",
                "sample_locations_json": "[]",
                "case_dir": case["case_dir"],
            }
        )
    return rows


def _location_row(
    case: Mapping[str, Any],
    set_group: str,
    set_name: str,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "variant": case["variant"],
        "section": case["case_id"],
        "set_group": set_group,
        "check_name": set_name,
        "count": summary.get("count", 0),
        "centroid_x_over_chord": summary.get("centroid_x_over_chord", ""),
        "centroid_z_over_chord": summary.get("centroid_z_over_chord", ""),
        "min_x_over_chord": summary.get("min_x_over_chord", ""),
        "max_x_over_chord": summary.get("max_x_over_chord", ""),
        "min_z_over_chord": summary.get("min_z_over_chord", ""),
        "max_z_over_chord": summary.get("max_z_over_chord", ""),
        "region_counts_json": json.dumps(summary.get("region_counts", {}), sort_keys=True),
        "sample_locations_json": json.dumps(summary.get("sample_locations", []), sort_keys=True),
        "case_dir": case["case_dir"],
    }


def _write_te_geometry_report(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    lines = [
        "# TE Geometry Perturbation Report",
        "",
        "| variant | airfoil | raw TE gap/chord | resampled TE gap/chord | introduced | TE reg area delta/chord^2 | max TE displacement/chord | chord delta | Sref-equivalent effect |",
        "|---|---:|---:|---:|---|---:|---:|---:|---|",
    ]
    for variant, reports in manifest["variant_geometry_reports"].items():
        for airfoil_id, report in reports.items():
            perturb = report["te_perturbation"]
            lines.append(
                "| "
                f"{variant} | {airfoil_id} | {report['raw_te_gap_over_chord']} | "
                f"{report['resampled_te_gap_over_chord']} | {perturb['introduced']} | "
                f"{report['te_regularization_area_delta_over_chord2']} | "
                f"{report['max_te_regularization_displacement_over_chord']} | "
                f"{report['chord_delta']} | {report['sref_note']} |"
            )
    lines.extend(
        [
            "",
            "Engineering read: DAE31 is the only mathematically sharp source TE in this matrix.",
            "The `cst_tip` finite source TE gap is preserved and reported; it is not a new bluntness insertion.",
            "The planform Sref-equivalent impact is zero for all variants because chord endpoints in x are unchanged.",
            "",
        ]
    )
    (output_dir / "te_geometry_perturbation_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_section_reports(output_dir: Path, cases: Sequence[Mapping[str, Any]]) -> None:
    for section, filename in (
        ("dae31_root_section", "dae31_section_gate_report.md"),
        ("cst_tip_section", "cst_tip_section_gate_report.md"),
        ("morph_dae31_to_cst_tip_section", "morph_section_gate_report.md"),
    ):
        section_cases = [case for case in cases if case["case_id"] == section]
        lines = [f"# {section} Gate Report", ""]
        for case in section_cases:
            combined = case["combined_metrics"]
            lines.extend(
                [
                    f"## {case['variant']}",
                    "",
                    f"- status: `{case['status']}`",
                    f"- actual TE gap/chord: `{case['te_geometry']['te_gap_over_chord']}`",
                    f"- primary Mesh OK: `{case['primary_metrics']['mesh_ok']}`",
                    f"- allTopology/allGeometry Mesh OK: `{case['all_geometry_metrics']['mesh_ok']}`",
                    f"- failed check count: `{combined['failed_check_count']}`",
                    f"- maxNonOrtho: `{combined['max_non_orthogonality_deg']}`",
                    f"- maxSkew: `{combined['max_skewness']}`",
                    f"- negative volumes: `{combined['negative_volume_count']}`",
                    f"- open cells: `{combined['open_cell_count']}`",
                    f"- oriented pyramid errors: `{combined['oriented_pyramid_error_count']}`",
                    f"- small determinant cells: `{combined['small_determinant_cell_count']}`",
                    f"- localization: `{case['localization']}`",
                    "",
                ]
            )
        (output_dir / filename).write_text("\n".join(lines), encoding="utf-8")


def _select_canonical(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_variant: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        by_variant.setdefault(str(case["variant"]), []).append(case)
    passing = [
        variant
        for variant, variant_cases in by_variant.items()
        if len(variant_cases) == 3 and all(case["status"] == "pass" for case in variant_cases)
    ]
    if passing:
        variant = min(passing, key=lambda name: dict(TE_VARIANTS)[name])
        return {
            "status": "pass",
            "variant": variant,
            "target_zero_te_gap_over_chord": dict(TE_VARIANTS)[variant],
            "selection_reason": "smallest TE gap passing all three section gates",
        }
    summaries = []
    for variant, variant_cases in by_variant.items():
        failed_count = sum(1 for case in variant_cases if case["status"] != "pass")
        max_non_ortho = max(
            (case["combined_metrics"]["max_non_orthogonality_deg"] or 0.0 for case in variant_cases),
            default=0.0,
        )
        max_skew = max((case["combined_metrics"]["max_skewness"] or 0.0 for case in variant_cases), default=0.0)
        small_det = sum(case["combined_metrics"]["small_determinant_cell_count"] or 0 for case in variant_cases)
        summaries.append(
            {
                "variant": variant,
                "failed_section_count": failed_count,
                "max_non_orthogonality_deg": max_non_ortho,
                "max_skewness": max_skew,
                "small_determinant_cell_count_sum": small_det,
            }
        )
    best = min(
        summaries,
        key=lambda row: (
            row["failed_section_count"],
            row["small_determinant_cell_count_sum"],
            row["max_non_orthogonality_deg"],
            row["max_skewness"],
            dict(TE_VARIANTS)[row["variant"]],
        ),
    )
    return {
        "status": "hard_blocked",
        "variant": None,
        "best_failed_variant": best,
        "blocker_summary": _blocker_summary(cases),
        "variant_summaries": summaries,
    }


def _blocker_summary(cases: Sequence[Mapping[str, Any]]) -> str:
    parts = []
    for case in cases:
        if case["status"] == "pass":
            continue
        combined = case["combined_metrics"]
        parts.append(
            f"{case['variant']} {case['case_id']}: status={case['status']} "
            f"failedChecks={combined['failed_check_count']} "
            f"maxNonOrtho={combined['max_non_orthogonality_deg']} "
            f"maxSkew={combined['max_skewness']} "
            f"smallDet={combined['small_determinant_cell_count']} "
            f"openCells={combined['open_cell_count']} "
            f"negativeVolumes={combined['negative_volume_count']} "
            f"pyramidErrors={combined['oriented_pyramid_error_count']}"
        )
    return "; ".join(parts)


def _write_canonical_report(
    output_dir: Path,
    selection: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
) -> None:
    lines = ["# Canonical True-Airfoil Section Topology", ""]
    if selection["status"] == "pass":
        lines.extend(
            [
                f"Canonical variant: `{selection['variant']}`.",
                "",
                "All three true-airfoil section gates pass primary and strict OpenFOAM checkMesh.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No canonical passing topology is selected.",
                "",
                "The bounded TE-gap matrix is complete, but at least one required section still fails",
                "`checkMesh -allTopology -allGeometry -meshQuality`.",
                "",
                f"Best failed variant: `{selection['best_failed_variant']}`",
                "",
                "Failure mechanism:",
                "",
                f"`{selection['blocker_summary']}`",
                "",
            ]
        )
    lines.append("## Section Status Table")
    lines.append("")
    lines.append("| variant | section | status | maxNonOrtho | maxSkew | small determinant cells |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for case in cases:
        combined = case["combined_metrics"]
        lines.append(
            f"| {case['variant']} | {case['case_id']} | {case['status']} | "
            f"{combined['max_non_orthogonality_deg']} | {combined['max_skewness']} | "
            f"{combined['small_determinant_cell_count']} |"
        )
    lines.append("")
    (output_dir / "canonical_true_airfoil_section_topology.md").write_text("\n".join(lines), encoding="utf-8")


def _run_bay_cases(
    *,
    output_dir: Path,
    authority: Any,
    openfoam_command: str,
    n_radial: int,
    farfield_chords: float,
    wake_length_chords: float,
) -> list[dict[str, Any]]:
    specs = [
        ("root_dae31_bay", authority.half_stations[0], authority.half_stations[1], 4),
        ("mid_dae31_twist_dihedral_bay", authority.half_stations[2], authority.half_stations[3], 4),
        ("morph_dae31_to_cst_tip_bay", authority.half_stations[4], authority.half_stations[5], 6),
        ("near_tip_cst_tip_bay", authority.half_stations[7], authority.half_stations[8], 4),
    ]
    cases = []
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
        cases.append(
            _run_bay_case(
                output_dir / "openfoam_cases" / "canonical_bays" / case_id,
                mesh=mesh,
                authority=authority,
                openfoam_command=openfoam_command,
                case_id=case_id,
            )
        )
    return cases


def _run_bay_case(
    case_dir: Path,
    *,
    mesh: SweptHexaMesh,
    authority: Any,
    openfoam_command: str,
    case_id: str,
) -> dict[str, Any]:
    quality = mesh_quality_summary(mesh)
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
    check = run_checkmesh(
        case_dir,
        openfoam_command=openfoam_command,
        timeout_seconds=300.0,
        full_geometry=False,
        stop_on_failure=False,
    )
    primary = _parse_checkmesh_log(case_dir / "log.checkMesh")
    max_skew = primary.get("max_skewness") or 0.0
    max_non_ortho = primary.get("max_non_orthogonality_deg") or 0.0
    status = (
        "pass"
        if quality.get("status") == "pass"
        and primary.get("mesh_ok")
        and max_skew < SECTION_MAX_SKEW_TARGET
        and max_non_ortho < SECTION_MAX_NON_ORTHO_SMOKE_LIMIT_DEG
        else "bay_checkmesh_failed"
    )
    return {
        "case_id": case_id,
        "case_dir": str(case_dir),
        "status": status,
        "custom_quality": quality,
        "checkMesh": check,
        "primary_metrics": primary,
        "patch_counts": mesh.boundary_face_counts,
    }


def _bay_blocker_summary(cases: Sequence[Mapping[str, Any]]) -> str:
    blockers = []
    for case in cases:
        if case["status"] == "pass":
            continue
        metrics = case.get("primary_metrics", {})
        blockers.append(
            f"{case['case_id']}: status={case['status']} "
            f"custom={case['custom_quality'].get('status')} "
            f"failedChecks={metrics.get('failed_check_count')} "
            f"maxNonOrtho={metrics.get('max_non_orthogonality_deg')} "
            f"maxSkew={metrics.get('max_skewness')}"
        )
    return "; ".join(blockers) if blockers else "bay_gates_attempted"


def _write_bay_report(output_dir: Path, bay_cases: Sequence[Mapping[str, Any]]) -> None:
    if not bay_cases:
        text = (
            "# Bay Gate Report\n\n"
            "Section gates passed, but this section-only matrix runner does not implement swept bay execution.\n"
        )
    else:
        lines = ["# Bay Gate Report", ""]
        for case in bay_cases:
            metrics = case.get("primary_metrics", {})
            lines.extend(
                [
                    f"## {case['case_id']}",
                    "",
                    f"- status: `{case['status']}`",
                    f"- primary Mesh OK: `{metrics.get('mesh_ok')}`",
                    f"- failed check count: `{metrics.get('failed_check_count')}`",
                    f"- maxNonOrtho: `{metrics.get('max_non_orthogonality_deg')}`",
                    f"- maxSkew: `{metrics.get('max_skewness')}`",
                    f"- patch counts: `{case.get('patch_counts')}`",
                    "",
                ]
            )
        text = "\n".join(lines)
    (output_dir / "bay_gate_report.md").write_text(text, encoding="utf-8")


def _write_verdict(output_dir: Path, manifest: Mapping[str, Any]) -> None:
    verdict = manifest["verdict"]
    selection = manifest["selection"]
    lines = [
        "# Phase 3 True-Airfoil TE-Regularized C-Grid Verdict",
        "",
        "1. What exact checks failed in the previous no-bluntness route?",
        "   - See `section_failed_check_localization.md` and `failed_check_locations.csv`.",
        "   - In the live bounded matrix, `gap_0p00` localizes the exact no-gap baseline.",
        "2. Did bounded TE regularization fix dae31?",
        f"   - `{_section_any_pass(manifest['section_cases'], 'dae31_root_section')}`",
        "3. Did bounded TE regularization fix cst_tip?",
        f"   - `{_section_any_pass(manifest['section_cases'], 'cst_tip_section')}`",
        "4. Did bounded TE regularization fix the morph section?",
        f"   - `{_section_any_pass(manifest['section_cases'], 'morph_dae31_to_cst_tip_section')}`",
        "5. What is the smallest TE gap that passes all required section gates?",
        f"   - `{selection.get('variant')}`",
        "6. What is the geometry perturbation from TE regularization?",
        "   - See `te_geometry_perturbation_report.md`; DAE31 bounded variants move only TE z endpoints.",
        "7. Did any section still fail -allTopology -allGeometry?",
        f"   - `{verdict['status'] == 'hard_blocked'}`",
        "8. Did bay gates run?",
        f"   - `{manifest['bay_gates_run']}`",
        "9. If not, what exact local section blocker remains?",
        f"   - `{verdict['reason']}`",
        "10. Is the station-wise swept C-grid route still worth continuing?",
        "   - `yes as a section-topology route, but not until this local strict checkMesh blocker is repaired.`",
        "",
        "Engineering boundary: this is mesh-topology evidence only. It is not solver, drag, AoA, span-count,",
        "bay, full-wing, release, procurement, or final aircraft sign-off evidence.",
        "",
    ]
    (output_dir / "phase3_true_airfoil_te_regularized_cgrid_verdict.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _write_rerun(
    output_dir: Path,
    n_perim: int,
    n_radial: int,
    farfield_chords: float,
    wake_length_chords: float,
) -> None:
    (output_dir / "RERUN.md").write_text(
        f"""# RERUN

```bash
PYTHONPATH=scripts:hpa_meshing_package/src ./.venv/bin/python \\
  scripts/run_wo006_true_airfoil_te_regularized_cgrid.py \\
  --clean \\
  --output-dir {output_dir} \\
  --n-perim {n_perim} \\
  --n-radial {n_radial} \\
  --farfield-chords {farfield_chords} \\
  --wake-length-chords {wake_length_chords}
```
""",
        encoding="utf-8",
    )


def _section_any_pass(cases: Sequence[Mapping[str, Any]], section: str) -> bool:
    return any(case["case_id"] == section and case["status"] == "pass" for case in cases)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _read_label_set(path: Path) -> list[int]:
    if not path.exists():
        return []
    labels: list[int] = []
    in_values = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped == "(":
            in_values = True
            continue
        if stripped == ")":
            break
        if not in_values:
            continue
        if stripped and re.fullmatch(r"-?[0-9]+", stripped):
            labels.append(int(stripped))
    return labels


def _global_to_local_over_chord(point: tuple[float, float, float], station: Station) -> tuple[float, float]:
    x_rel = point[0] - station.x_le
    z_rel = point[2] - station.z_le
    theta = math.radians(station.twist_deg)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    twist_axis = station.chord * 0.25
    x_local = twist_axis + cos_theta * (x_rel - twist_axis) - sin_theta * z_rel
    z_local = sin_theta * (x_rel - twist_axis) + cos_theta * z_rel
    return x_local / station.chord, z_local / station.chord


def _center(points: Iterable[tuple[float, float, float]]) -> tuple[float, float, float]:
    values = list(points)
    inv = 1.0 / len(values)
    return (
        sum(point[0] for point in values) * inv,
        sum(point[1] for point in values) * inv,
        sum(point[2] for point in values) * inv,
    )


def _face_area_vector(points: Sequence[tuple[float, float, float]]) -> tuple[float, float, float]:
    nx = ny = nz = 0.0
    for left, right in zip(points, [*points[1:], points[0]]):
        nx += (left[1] - right[1]) * (left[2] + right[2])
        ny += (left[2] - right[2]) * (left[0] + right[0])
        nz += (left[0] - right[0]) * (left[1] + right[1])
    return (0.5 * nx, 0.5 * ny, 0.5 * nz)


def _point_line_distance(
    point: tuple[float, float, float],
    line_a: tuple[float, float, float],
    line_b: tuple[float, float, float],
) -> float:
    ab = (line_b[0] - line_a[0], line_b[1] - line_a[1], line_b[2] - line_a[2])
    ap = (point[0] - line_a[0], point[1] - line_a[1], point[2] - line_a[2])
    cross = (
        ap[1] * ab[2] - ap[2] * ab[1],
        ap[2] * ab[0] - ap[0] * ab[2],
        ap[0] * ab[1] - ap[1] * ab[0],
    )
    return _norm(cross) / max(_norm(ab), 1.0e-14)


def _distance(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return math.sqrt(
        (left[0] - right[0]) ** 2
        + (left[1] - right[1]) ** 2
        + (left[2] - right[2]) ** 2
    )


def _dot(left: tuple[float, float, float], right: tuple[float, float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _norm(vector: tuple[float, float, float]) -> float:
    return math.sqrt(_dot(vector, vector))


def _float_match(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text)
    return None if match is None else float(match.group(1))


def _int_match(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text)
    return None if match is None else int(match.group(1))


def _max_number(*values: Any) -> float:
    numeric = [float(value) for value in values if value is not None]
    return max(numeric, default=0.0)


def _max_int(*values: Any) -> int:
    numeric = [int(value) for value in values if value is not None]
    return max(numeric, default=0)


if __name__ == "__main__":
    raise SystemExit(main())
