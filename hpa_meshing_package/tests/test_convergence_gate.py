from __future__ import annotations

import csv
import json
from pathlib import Path

from hpa_meshing.convergence import (
    build_overall_convergence_gate,
    evaluate_iterative_gate,
    evaluate_mesh_gate,
)


def _write_history(path: Path, rows: list[dict[str, float]]) -> None:
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def _valid_mesh_handoff(tmp_path: Path) -> dict[str, object]:
    mesh_path = tmp_path / "mesh.msh"
    mesh_path.write_text("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n", encoding="utf-8")
    marker_summary_path = tmp_path / "marker_summary.json"
    mesh_metadata_path = tmp_path / "mesh_metadata.json"
    marker_summary = {
        "aircraft": {
            "exists": True,
            "physical_name": "aircraft",
            "dimension": 2,
            "entity_count": 38,
            "element_count": 180,
        },
        "farfield": {
            "exists": True,
            "physical_name": "farfield",
            "dimension": 2,
            "entity_count": 6,
            "element_count": 3836,
        },
    }
    handoff = {
        "contract": "mesh_handoff.v1",
        "route_stage": "baseline",
        "backend": "gmsh",
        "backend_capability": "sheet_aircraft_assembly_meshing",
        "meshing_route": "gmsh_thin_sheet_aircraft_assembly",
        "geometry_family": "thin_sheet_aircraft_assembly",
        "geometry_source": "provider_generated",
        "geometry_provider": "openvsp_surface_intersection",
        "source_path": str(tmp_path / "demo.vsp3"),
        "normalized_geometry_path": str(tmp_path / "normalized.stp"),
        "units": "m",
        "mesh_format": "msh",
        "body_bounds": {
            "x_min": 0.0,
            "x_max": 5.7,
            "y_min": -16.4,
            "y_max": 16.4,
            "z_min": -0.7,
            "z_max": 1.7,
        },
        "farfield_bounds": {
            "x_min": -28.5,
            "x_max": 74.1,
            "y_min": -280.0,
            "y_max": 280.0,
            "z_min": -19.9,
            "z_max": 20.9,
        },
        "mesh_stats": {
            "mesh_dim": 3,
            "node_count": 4290,
            "element_count": 24618,
            "surface_element_count": 4016,
            "volume_element_count": 20178,
        },
        "marker_summary": marker_summary,
        "physical_groups": {
            "fluid": {
                "exists": True,
                "physical_name": "fluid",
                "dimension": 3,
                "entity_count": 1,
                "element_count": 20178,
            },
            "aircraft": {
                "exists": True,
                "physical_name": "aircraft",
                "dimension": 2,
                "entity_count": 38,
                "element_count": 180,
            },
            "farfield": {
                "exists": True,
                "physical_name": "farfield",
                "dimension": 2,
                "entity_count": 6,
                "element_count": 3836,
            },
        },
        "artifacts": {
            "mesh": str(mesh_path),
            "mesh_metadata": str(mesh_metadata_path),
            "marker_summary": str(marker_summary_path),
        },
        "provenance": {"route_provenance": "geometry_family_registry"},
        "unit_normalization": {"units": "m"},
    }
    marker_summary_path.write_text(json.dumps(marker_summary), encoding="utf-8")
    mesh_metadata_path.write_text(json.dumps(handoff), encoding="utf-8")
    return handoff


def test_evaluate_mesh_gate_passes_complete_baseline_handoff(tmp_path: Path):
    gate = evaluate_mesh_gate(_valid_mesh_handoff(tmp_path))

    assert gate.status == "pass"
    assert gate.checks["mesh_handoff_complete"].status == "pass"
    assert gate.checks["required_markers_and_groups"].status == "pass"
    assert gate.checks["element_counts"].status == "pass"


def test_evaluate_mesh_gate_fails_when_baseline_artifacts_are_incomplete(tmp_path: Path):
    handoff = _valid_mesh_handoff(tmp_path)
    handoff["route_stage"] = "placeholder"
    handoff["physical_groups"] = {"aircraft": handoff["physical_groups"]["aircraft"]}

    gate = evaluate_mesh_gate(handoff)

    assert gate.status == "fail"
    assert gate.checks["mesh_handoff_complete"].status == "fail"
    assert gate.checks["required_markers_and_groups"].status == "fail"


def test_evaluate_iterative_gate_passes_when_tail_is_stable(tmp_path: Path):
    history_path = tmp_path / "history.csv"
    rows = []
    for iteration in range(30):
        rows.append(
            {
                "Inner_Iter": iteration,
                "rms[P]": -2.0 - 0.08 * iteration,
                "rms[U]": -2.1 - 0.06 * iteration,
                "CL": 0.12 + (0.02 / (iteration + 1)),
                "CD": 0.03 + (0.01 / (iteration + 1)),
                "CMy": -0.004 - (0.002 / (iteration + 1)),
            }
        )
    _write_history(history_path, rows)

    gate = evaluate_iterative_gate(history_path, min_iterations=20, tail_window=10)

    assert gate.status == "pass"
    assert gate.checks["history_rows"].status == "pass"
    assert gate.checks["residual_trend"].status == "pass"
    assert gate.checks["coefficient_stability"].status == "pass"


def test_evaluate_iterative_gate_warns_when_residuals_stall_but_tail_is_stable(tmp_path: Path):
    history_path = tmp_path / "history.csv"
    rows = []
    for iteration in range(30):
        rows.append(
            {
                "Inner_Iter": iteration,
                "rms[P]": -2.0 + 0.01 * iteration,
                "rms[U]": -2.1 + 0.01 * iteration,
                "CL": 0.12 + (0.0004 if iteration < 20 else 0.000001 * (29 - iteration)),
                "CD": 0.03 + (0.0003 if iteration < 20 else 0.000001 * (29 - iteration)),
                "CMy": -0.004 + (0.0002 if iteration < 20 else 0.000001 * (iteration - 29)),
            }
        )
    _write_history(history_path, rows)

    gate = evaluate_iterative_gate(history_path, min_iterations=20, tail_window=10)

    assert gate.status == "warn"
    assert gate.checks["residual_trend"].status == "warn"
    assert gate.checks["coefficient_stability"].status == "pass"


def test_evaluate_iterative_gate_uses_post_startup_window_for_residual_trend(tmp_path: Path):
    history_path = tmp_path / "history.csv"
    rows = []
    for iteration in range(40):
        if iteration == 0:
            rms_p = -2.6
            rms_u = -2.7
            rms_v = -2.8
            rms_w = -2.65
        else:
            rms_p = -0.55 - 0.04 * iteration
            rms_u = -0.60 - 0.035 * iteration
            rms_v = -0.72 - 0.038 * iteration
            rms_w = -0.58 - 0.036 * iteration
        rows.append(
            {
                "Inner_Iter": iteration,
                "rms[P]": rms_p,
                "rms[U]": rms_u,
                "rms[V]": rms_v,
                "rms[W]": rms_w,
                "CL": 0.12 + (0.02 / (iteration + 1)),
                "CD": 0.03 + (0.01 / (iteration + 1)),
                "CMy": -0.004 - (0.002 / (iteration + 1)),
            }
        )
    _write_history(history_path, rows)

    gate = evaluate_iterative_gate(history_path, min_iterations=20, tail_window=10)

    assert gate.status == "pass"
    assert gate.checks["residual_trend"].status == "pass"
    assert gate.checks["coefficient_stability"].status == "pass"


def test_evaluate_iterative_gate_fails_when_coefficients_are_still_drifting(tmp_path: Path):
    history_path = tmp_path / "history.csv"
    rows = []
    for iteration in range(25):
        rows.append(
            {
                "Inner_Iter": iteration,
                "rms[P]": -2.0 - 0.05 * iteration,
                "rms[U]": -2.1 - 0.04 * iteration,
                "CL": 0.12 + 0.002 * iteration,
                "CD": 0.03 + 0.001 * iteration,
                "CMy": -0.004 - 0.001 * iteration,
            }
        )
    _write_history(history_path, rows)

    gate = evaluate_iterative_gate(history_path, min_iterations=20, tail_window=10)

    assert gate.status == "fail"
    assert gate.checks["coefficient_stability"].status == "fail"


def test_build_overall_convergence_gate_maps_status_to_comparability():
    overall = build_overall_convergence_gate(
        mesh_gate_status="pass",
        iterative_gate_status="warn",
        reference_gate_status="pass",
        force_surface_gate_status="pass",
    )

    assert overall.status == "warn"
    assert overall.comparability_level == "run_only"
    assert overall.checks["iterative_gate"].status == "warn"
