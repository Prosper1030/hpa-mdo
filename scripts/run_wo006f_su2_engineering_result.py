#!/usr/bin/env python3
"""Package the WO-006F SU2 engineering-result recovery campaign.

The script does not run SU2. It audits the campaign attempts already present in
the WO-006F output folder and writes the short verdict/report artifacts that a
future worker or reviewer can use without replaying every solver log.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "wo006f_su2_engineering_result"
)
GEOMETRY_MANIFEST = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "production_inspection"
    / "current_avl_compromise_conservative_closed"
    / "geometry_manifest.json"
)
AVL_RECHECK_CSV = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "current_avl_compromise_conservative_closed_tier2_airfoil"
    / "tier2_loaded_shape_selected_avl_recheck.csv"
)
VSPAERO_PANEL_REFERENCE = (
    REPO_ROOT
    / "hpa_meshing_package"
    / "docs"
    / "reports"
    / "main_wing_vspaero_panel_reference_probe"
    / "main_wing_vspaero_panel_reference_probe.v1.json"
)
R3_HIGH_MESH_REPORT = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "wo006r3_surface_topology_repair"
    / "high_mesh_no_bl_wing_h_0p12_probe"
    / "mesh_native_faceted_su2_smoke_report.json"
)
R6_FINAL_GATE = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "wo006r6_core_interface_repair"
    / "final_handoff_gate.json"
)
R6_CORE_SUMMARY = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "wo006r6_core_interface_repair"
    / "core_probe_summary.json"
)
R6_BL_SUMMARY = (
    REPO_ROOT
    / "output"
    / "baseline_A_team_release"
    / "wo006_su2_baseline_validation"
    / "wo006r6_core_interface_repair"
    / "owned_bl_block_writer_probe.json"
)

CURRENT_DESIGN_MASS_KG = 98.5
PIPELINE_FULL_SPAN_M = 34.332286
PIPELINE_HALF_SPAN_M = 17.166143
PHYSICAL_CL_MIN = 0.9
PHYSICAL_CL_MAX = 1.5
PHYSICAL_CD_MIN = 0.0
PHYSICAL_CD_MAX_FOR_LOW_CONFIDENCE = 0.09


@dataclass(frozen=True)
class AttemptDefinition:
    attempt_id: str
    route: str
    mesh_family: str
    solver_family: str
    boundary_layer_status: str
    purpose: str


ATTEMPTS: tuple[AttemptDefinition, ...] = (
    AttemptDefinition(
        "attempt_01_high_mesh_no_bl_inc_ns_cfl0p5",
        "R3 high-mesh no-BL incompressible Navier-Stokes at alpha 0",
        "R3 current-GO no-BL 0.12 m faceted tet mesh",
        "INC_NAVIER_STOKES laminar",
        "none",
        "check whether the readable high-mesh no-BL route can recover lift",
    ),
    AttemptDefinition(
        "attempt_02_medium_no_bl_inc_ns_alpha5_zpos",
        "medium no-BL incompressible Navier-Stokes at +5 deg velocity vector",
        "R3 current-GO no-BL 0.15 m faceted tet mesh",
        "INC_NAVIER_STOKES laminar",
        "none",
        "check lift sign/magnitude by changing the freestream vector convention",
    ),
    AttemptDefinition(
        "attempt_03_medium_no_bl_inc_euler_alpha5_zpos",
        "medium no-BL incompressible Euler at +5 deg velocity vector",
        "R3 current-GO no-BL 0.15 m faceted tet mesh",
        "INC_EULER slip wall",
        "none",
        "separate pressure/inflow convention from no-slip drag contamination",
    ),
    AttemptDefinition(
        "attempt_04_medium_no_bl_inc_rans_sa_wallfn_alpha5_zpos",
        "medium no-BL incompressible RANS SA with wall functions",
        "R3 current-GO no-BL 0.15 m faceted tet mesh",
        "INC_RANS SA",
        "wall function on a no-BL mesh",
        "test whether a wall-function shortcut can run before BL topology exists",
    ),
    AttemptDefinition(
        "attempt_05_medium_compressible_euler_alpha5",
        "medium no-BL compressible Euler low-Mach shortcut",
        "R3 current-GO no-BL 0.15 m faceted tet mesh",
        "EULER compressible",
        "none",
        "test a compressible low-Mach fallback",
    ),
    AttemptDefinition(
        "attempt_06_medium_no_bl_inc_rans_sa_alpha5_zpos_no_wallfn",
        "medium no-BL incompressible RANS SA without wall functions",
        "R3 current-GO no-BL 0.15 m faceted tet mesh",
        "INC_RANS SA",
        "none",
        "remove the invalid wall-function shortcut and check if RANS can run",
    ),
    AttemptDefinition(
        "attempt_07_openvsp_gmsh_current_vsp",
        "OpenVSP STEP/STL export plus repo Gmsh external-flow generator",
        "current production-inspection VSP3 STEP/STL",
        "not reached",
        "none",
        "test a route independent of the mesh-native R6 BL/core path",
    ),
    AttemptDefinition(
        "attempt_08_medium_no_bl_inc_euler_alpha5_zpos_low_cfl",
        "medium no-BL incompressible Euler at lower CFL",
        "R3 current-GO no-BL 0.15 m faceted tet mesh",
        "INC_EULER slip wall",
        "none",
        "check whether the inviscid pressure convention can settle with damping",
    ),
    AttemptDefinition(
        "attempt_09_openvsp_native_cfdmesh",
        "OpenVSP native CFDMesh Gmsh/STL export",
        "current production-inspection VSP3 CFDMesh",
        "not reached",
        "none",
        "test OpenVSP's own CFDMesh path",
    ),
    AttemptDefinition(
        "attempt_10_r6_two_zone_multizone_probe",
        "R6 BL/core two-zone SU2 multizone probe",
        "R6 owned BL block plus preserved-interface core probe",
        "INC_NAVIER_STOKES multizone",
        "owned BL block present, core quality failed",
        "test whether official SU2 multizone can avoid the merged writer bottleneck",
    ),
)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _norm_key(value: str) -> str:
    return value.strip().strip('"').upper().replace(" ", "")


def _lookup_float(row: Mapping[str, str], *names: str) -> float | None:
    normalized = {_norm_key(key): value for key, value in row.items()}
    for name in names:
        raw = normalized.get(_norm_key(name))
        if raw is None or raw == "":
            continue
        try:
            return float(str(raw).strip())
        except ValueError:
            continue
    return None


def _load_history_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _iter_history_paths(case_dir: Path) -> Iterable[Path]:
    for name in ("history.csv", "history.dat", "main_multizone.csv", "history_0.csv", "history_1.csv"):
        path = case_dir / name
        if path.exists():
            yield path


def _final_metrics_from_history(case_dir: Path) -> dict[str, Any]:
    histories: list[dict[str, Any]] = []
    final_with_coeffs: dict[str, Any] | None = None
    best_positive_window: dict[str, Any] | None = None
    for history_path in _iter_history_paths(case_dir):
        rows = _load_history_rows(history_path)
        if not rows:
            continue
        final = rows[-1]
        final_metrics = {
            "history_file": history_path.name,
            "row_count": len(rows),
            "final_iteration": _lookup_float(final, "INNER_ITER", "OUTER_ITER", "ITER"),
            "final_cl": _lookup_float(final, "CL", "LIFT"),
            "final_cd": _lookup_float(final, "CD", "DRAG"),
            "final_cmy": _lookup_float(final, "CMY", "CM"),
            "final_ceff": _lookup_float(final, "CEFF"),
        }
        histories.append(final_metrics)
        if final_metrics["final_cl"] is not None and final_metrics["final_cd"] is not None:
            final_with_coeffs = final_metrics
        for row in rows:
            cl = _lookup_float(row, "CL", "LIFT")
            cd = _lookup_float(row, "CD", "DRAG")
            iteration = _lookup_float(row, "INNER_ITER", "OUTER_ITER", "ITER")
            if cl is None or cd is None:
                continue
            if PHYSICAL_CL_MIN <= cl <= PHYSICAL_CL_MAX and 0.0 < cd <= 0.12:
                best_positive_window = {
                    "history_file": history_path.name,
                    "iteration": iteration,
                    "cl": cl,
                    "cd": cd,
                }
    return {
        "histories": histories,
        "final_with_coefficients": final_with_coeffs,
        "best_positive_window": best_positive_window,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _solver_status(case_dir: Path) -> tuple[str, list[str]]:
    log = _read_text(case_dir / "solver.log")
    notes: list[str] = []
    if not log:
        return "not_run_or_no_log", notes
    if "Exit Success" in log:
        status = "exit_success"
    elif "Error Exit" in log:
        status = "error_exit"
    elif "Divergence detected" in log or "NaN" in log:
        status = "diverged"
    elif "SIGINT" in log or "Interrupted" in log:
        status = "interrupted"
    else:
        status = "incomplete_or_interrupted"
    if "Maximum number of iterations reached" in log:
        notes.append("max_iterations_reached_before_convergence")
    if "Cauchy[CD]" in log:
        match = re.search(r"Cauchy\[CD\]\|\s*([0-9.eE+-]+)\|\s*<\s*([0-9.eE+-]+)", log)
        if match:
            notes.append(f"cauchy_cd={match.group(1)}_criterion={match.group(2)}")
    if "wall coefficients (y+)" in log:
        notes.append("wall_function_yplus_warnings")
    if "PLC Error" in log:
        notes.append("gmsh_plc_error")
    if "Invalid boundary mesh" in log:
        notes.append("invalid_boundary_mesh")
    if "non-positive" in log.lower():
        notes.append("non_positive_mesh_warning")
    return status, notes


def _case_classification(metrics: Mapping[str, Any], solver_status: str, notes: list[str]) -> str:
    final = metrics.get("final_with_coefficients")
    if not isinstance(final, Mapping):
        if solver_status == "exit_success":
            return "solver_or_mesh_probe_no_coefficients"
        return "no_usable_su2_coefficients"
    cl = final.get("final_cl")
    cd = final.get("final_cd")
    if not isinstance(cl, (int, float)) or not isinstance(cd, (int, float)):
        return "no_usable_su2_coefficients"
    if cd <= 0.0:
        return "reject_negative_drag"
    if cl < PHYSICAL_CL_MIN:
        return "reject_lift_below_operating_point"
    if cl > PHYSICAL_CL_MAX:
        return "reject_lift_above_sanity_band"
    if cd > PHYSICAL_CD_MAX_FOR_LOW_CONFIDENCE:
        return "reject_drag_far_above_sanity_bounds"
    if "max_iterations_reached_before_convergence" in notes:
        return "positive_physical_window_but_not_converged"
    return "candidate_low_confidence_physical"


def build_attempt_summaries(output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for definition in ATTEMPTS:
        case_dir = output_dir / definition.attempt_id
        metrics = _final_metrics_from_history(case_dir)
        solver_status, notes = _solver_status(case_dir)
        classification = _case_classification(metrics, solver_status, notes)
        final = metrics.get("final_with_coefficients") or {}
        rows.append(
            {
                "attempt_id": definition.attempt_id,
                "route": definition.route,
                "mesh_family": definition.mesh_family,
                "solver_family": definition.solver_family,
                "boundary_layer_status": definition.boundary_layer_status,
                "purpose": definition.purpose,
                "case_dir": str(case_dir),
                "case_dir_exists": case_dir.exists(),
                "solver_status": solver_status,
                "classification": classification,
                "final_iteration": final.get("final_iteration"),
                "final_cl": final.get("final_cl"),
                "final_cd": final.get("final_cd"),
                "final_cmy": final.get("final_cmy"),
                "best_positive_window": metrics.get("best_positive_window"),
                "notes": notes,
            }
        )
    return rows


def _write_csv(path: Path, rows: list[Mapping[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(row.get(key), sort_keys=True)
                        if isinstance(row.get(key), (dict, list))
                        else row.get(key)
                    )
                    for key in fieldnames
                }
            )


def _read_avl_conservative_best() -> dict[str, Any]:
    if not AVL_RECHECK_CSV.exists():
        return {}
    with AVL_RECHECK_CSV.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row.get("selected_role") == "conservative_best":
            return {
                "source": str(AVL_RECHECK_CSV),
                "alpha_deg": float(row["alpha_deg"]),
                "cl": float(row["CL"]),
                "cd_total": float(row["CD_total"]),
                "cdi": float(row["CDi"]),
                "profile_cd": float(row["profile_cd"]),
                "status": row.get("status"),
            }
    return {}


def _first_number(mapping: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _read_vspaero_reference() -> dict[str, Any]:
    payload = _read_json(VSPAERO_PANEL_REFERENCE)
    if not isinstance(payload, dict):
        return {}
    coeffs = payload.get("selected_case")
    if not isinstance(coeffs, Mapping):
        coeffs = payload.get("coefficients")
    if not isinstance(coeffs, Mapping):
        coeffs = payload.get("final_coefficients")
    refs = payload.get("reference_values") if isinstance(payload, dict) else None
    if not isinstance(coeffs, Mapping):
        return {}
    return {
        "source": str(VSPAERO_PANEL_REFERENCE),
        "cl": _first_number(coeffs, "CLtot", "cl"),
        "cd_total": _first_number(coeffs, "CDtot", "cd"),
        "ld": _first_number(coeffs, "E", "L/D", "l_over_d"),
        "reference_values": refs if isinstance(refs, Mapping) else {},
        "caveat": "old/lower-order panel sanity reference; not SU2 replacement",
    }


def build_force_reference_audit() -> dict[str, Any]:
    geometry = _read_json(GEOMETRY_MANIFEST)
    return {
        "schema_version": "wo006f_force_reference_audit.v1",
        "current_authority": {
            "design_gross_mass_kg": CURRENT_DESIGN_MASS_KG,
            "full_span_m": PIPELINE_FULL_SPAN_M,
            "half_span_m": PIPELINE_HALF_SPAN_M,
            "sref_m2": geometry.get("Sref"),
            "cref_m": geometry.get("Cref"),
            "bref_m": geometry.get("Bref"),
            "geometry_manifest": str(GEOMETRY_MANIFEST),
        },
        "blocked_legacy_values": {
            "legacy_106p828608kg": "blocked_not_current_truth",
            "legacy_16p5m_half_span": "blocked_not_current_pipeline_truth",
        },
        "su2_runtime_convention": {
            "system_measurements": "SI",
            "velocity_mps": 6.5,
            "density_kgpm3": 1.225,
            "dynamic_viscosity_pa_s": 1.7894e-5,
            "wall_marker": "wing_wall",
            "farfield_marker": "farfield",
            "no_slip_wall": "MARKER_HEATFLUX=(wing_wall,0.0)",
            "force_reference": "REF_AREA=Sref, REF_LENGTH=Cref, moment origin from current pipeline",
        },
        "acceptance_logic": {
            "positive_drag_required": True,
            "operating_point_cl_band": [PHYSICAL_CL_MIN, PHYSICAL_CL_MAX],
            "low_confidence_cd_upper_sanity": PHYSICAL_CD_MAX_FOR_LOW_CONFIDENCE,
            "negative_cd": "reject",
            "no_bl_drag": "not_result_ready",
            "multizone_probe": "route_evidence_until_force_coefficients_and_quality_gate_pass",
        },
    }


def build_mesh_quality_audit() -> dict[str, Any]:
    r3 = _read_json(R3_HIGH_MESH_REPORT)
    r6_gate = _read_json(R6_FINAL_GATE)
    r6_core = _read_json(R6_CORE_SUMMARY)
    r6_bl = _read_json(R6_BL_SUMMARY)
    return {
        "schema_version": "wo006f_mesh_quality_audit.v1",
        "r3_high_mesh_no_bl": {
            "source": str(R3_HIGH_MESH_REPORT),
            "volume_element_count": r3.get("volume_element_count")
            or r3.get("mesh", {}).get("volume_element_count"),
            "node_count": r3.get("node_count") or r3.get("mesh", {}).get("node_count"),
            "marker_audit": r3.get("marker_audit") or r3.get("su2_marker_audit"),
            "interpretation": "readable no-BL tet handoff; not wall-resolved drag evidence",
        },
        "r6_owned_bl_block": {
            "source": str(R6_BL_SUMMARY),
            "volume_element_count": r6_bl.get("volume_element_count"),
            "marker_summary": r6_bl.get("marker_summary"),
            "block_quality": r6_bl.get("block_quality"),
            "interpretation": "owned near-wall BL block exists and has positive cells, but is not a complete farfield CFD domain",
        },
        "r6_preserved_core": {
            "source": str(R6_CORE_SUMMARY),
            "volume_element_count": r6_core.get("volume_element_count"),
            "quality_metrics": r6_core.get("quality_metrics"),
            "mesh_quality_gate": r6_core.get("mesh_quality_gate"),
            "bl_block_coupling": r6_core.get("bl_block_coupling"),
            "interpretation": "core zone can be meshed and preserved, but current quality/coupling fail blocks a credible result",
        },
        "r6_final_handoff_gate": r6_gate,
    }


def build_sanity_comparison(attempts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    avl = _read_avl_conservative_best()
    if avl:
        rows.extend(
            [
                {
                    "case": "AVL conservative_best induced CDi",
                    "cl": avl["cl"],
                    "cd": avl["cdi"],
                    "role": "avl_induced_sanity_bound",
                },
                {
                    "case": "Tier2 XFOIL/profile proxy CD",
                    "cl": avl["cl"],
                    "cd": avl["profile_cd"],
                    "role": "xfoil_profile_proxy_sanity_bound",
                },
                {
                    "case": "AVL plus Tier2 profile proxy CD_total",
                    "cl": avl["cl"],
                    "cd": avl["cd_total"],
                    "role": "combined_sanity_bound",
                },
            ]
        )
    vspaero = _read_vspaero_reference()
    if vspaero:
        rows.append(
            {
                "case": "VSPAERO panel reference",
                "cl": vspaero.get("cl"),
                "cd": vspaero.get("cd_total"),
                "role": "lower_order_panel_sanity_bound",
            }
        )
    for attempt in attempts:
        rows.append(
            {
                "case": attempt["attempt_id"],
                "cl": attempt.get("final_cl"),
                "cd": attempt.get("final_cd"),
                "role": attempt.get("classification"),
            }
        )
        window = attempt.get("best_positive_window")
        if isinstance(window, Mapping):
            rows.append(
                {
                    "case": f"{attempt['attempt_id']} transient positive window",
                    "cl": window.get("cl"),
                    "cd": window.get("cd"),
                    "role": "transient_not_final",
                }
            )
    return rows


def choose_verdict(attempts: list[Mapping[str, Any]]) -> str:
    classes = {str(row.get("classification")) for row in attempts}
    if "candidate_low_confidence_physical" in classes:
        return "wo006f_su2_result_low_confidence_but_physical"
    multizone_open = any(row.get("attempt_id") == "attempt_10_r6_two_zone_multizone_probe" and row.get("solver_status") == "exit_success" for row in attempts)
    if multizone_open:
        return "wo006f_campaign_incomplete"
    return "wo006f_su2_route_proven_not_currently_achievable"


def build_campaign_summary(output_dir: Path) -> dict[str, Any]:
    attempts = build_attempt_summaries(output_dir)
    verdict = choose_verdict(attempts)
    return {
        "schema_version": "wo006f_su2_engineering_result.v1",
        "verdict": verdict,
        "authority": build_force_reference_audit()["current_authority"],
        "su2_physical_cl_cd_produced": False,
        "route_that_worked": None,
        "route_evidence": {
            "no_bl_rans": "attempt_06 produced positive drag and operating-point lift, but CD=0.556 is far above AVL/Tier2-profile/VSPAERO sanity bounds and the run did not converge",
            "low_cfl_euler": "attempt_08 passed through a plausible positive window, then drifted into negative drag before completion",
            "openvsp_gmsh": "attempt_07 failed STEP/OCC and STL fallback meshing with PLC/overlapping-facet errors",
            "openvsp_native_cfdmesh": "attempt_09 did not produce a usable exported mesh artifact in this run",
            "r6_multizone": "attempt_10 launched as official SU2 fluid-fluid multizone, but only as a probe; core quality/coupling and force-output gates remain blocked",
        },
        "attempts": attempts,
        "mesh_quality": build_mesh_quality_audit(),
        "force_reference_audit": build_force_reference_audit(),
        "sanity_comparison": build_sanity_comparison(attempts),
        "engineering_interpretation": (
            "WO-006F did not produce an engineering-credible SU2 aerodynamic result. "
            "The useful new evidence is that a damped RANS no-BL setup can run and recover lift "
            "with positive drag, but its drag is physically too large against the AVL/Tier2 "
            "profile-proxy and VSPAERO sanity envelope; and that an official SU2 multizone "
            "BL/core route can launch, so the next repair, with the data-authority "
            "checker still as prerequisite, should focus on R6 core quality, "
            "wake/span-cap closure, and multizone/merged-force coefficient ownership."
        ),
    }


def _markdown_table(rows: list[Mapping[str, Any]], columns: list[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, float):
                values.append(f"{value:.6g}")
            elif value is None:
                values.append("")
            else:
                values.append(str(value).replace("\n", " "))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def write_report(output_dir: Path, summary: Mapping[str, Any]) -> None:
    attempts = list(summary["attempts"])
    lines = [
        "# WO-006F SU2 Engineering Result Campaign",
        "",
        f"Verdict: `{summary['verdict']}`",
        "",
        "## Short Read",
        "",
        "- SU2 did not produce a final physically credible CL/CD pair for Baseline A calibration.",
        "- Best final sign-correct run: `attempt_06`, `CL=1.289421542`, `CD=0.5555196327`, exit success but not converged and drag is far too high.",
        "- Sanity bounds are AVL/Tier2 profile-proxy `CL=1.16853`, `CD_total=0.0260200` plus old VSPAERO panel `CL=1.28765`, `CD=0.0450681`; `attempt_06` is roughly 12-21x too draggy.",
        "- Best transient sanity moment: `attempt_08` briefly crossed the operating CL band with positive drag, but the same run drifted to negative drag and was interrupted.",
        "- New route evidence: `attempt_10` proves SU2 fluid-fluid multizone can launch with R6 BL/core probe files after adding `MARKER_FLUID_INTERFACE`; it is not yet force/coefficient evidence.",
        "",
        "## Attempt Summary",
        "",
        *_markdown_table(
            attempts,
            ["attempt_id", "solver_status", "classification", "final_iteration", "final_cl", "final_cd"],
        ),
        "",
        "## Engineering Caveats",
        "",
        "- No-BL tet meshes cannot provide wall-shear/profile-drag truth for this low-Re HPA wing.",
        "- Wall-function RANS on the no-BL mesh produced y+ warnings and NaN divergence.",
        "- OpenVSP/Gmsh alternatives are not yet robust against current thin-wing topology defects.",
        "- R6 owned BL topology is promising, but preserved-core quality has non-positive elements and wake/span-cap coupling remains incomplete.",
        "- A passing software test or SU2 exit code is not aerodynamic sign-off.",
        "",
        "## Next Repair",
        "",
        "Start from the R6 BL/core artifacts, not the no-BL coefficient loop. The highest-value path is either:",
        "",
        "- repair preserved-core quality plus wake/span-cap coupling, then write a merged mixed-element SU2 handoff; or",
        "- formalize the multizone route with clean BL/core zone interfaces, force-output ownership, and a core mesh that passes quality gates.",
        "",
    ]
    (output_dir / "wo006f_su2_engineering_result_report.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def write_reviewer_prompt(output_dir: Path, summary: Mapping[str, Any]) -> None:
    prompt = f"""Review WO-006F in /Volumes/Samsung SSD/hpa-mdo.

Read:
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006f_su2_engineering_result/campaign_summary.json
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006f_su2_engineering_result/wo006f_su2_engineering_result_report.md
- output/baseline_A_team_release/wo006_su2_baseline_validation/wo006r6_core_interface_repair/

Verdict to audit: {summary['verdict']}

Questions:
1. Is the rejection of attempt_06 as drag-credible justified despite positive CL/CD?
2. Is attempt_10 enough to treat SU2 multizone as an open repair route?
3. What is the smallest next patch: merged mixed-element writer repair, multizone force-output ownership, or preserved-core quality first?

Respect authority: 98.5 kg, full span 34.332286 m, half span 17.166143 m, current pipeline Sref/Cref/Bref. Treat 106.828608 kg as suspect P1 screening aggregate only and 16.5 m as local/splice screening only.
"""
    (output_dir / "reviewer_prompt.md").write_text(prompt, encoding="utf-8")


def write_official_sources(output_dir: Path) -> None:
    lines = [
        "# Official Sources Used",
        "",
        "- SU2 incompressible turbulent NACA0012 tutorial: https://github.com/su2code/Tutorials/blob/master/incompressible_flow/Inc_Turbulent_NACA0012/turb_naca0012.cfg",
        "- SU2 markers and boundary conditions: https://su2code.github.io/docs_v7/Markers-and-BC/",
        "- SU2 multizone documentation: https://su2code.github.io/docs_v7/Multizone/",
        "- SU2 mesh-file format documentation: https://su2code.github.io/docs_v7/Mesh-File/",
        "- Gmsh reference manual: https://gmsh.info/doc/texinfo/gmsh.html",
        "- OpenVSP CFDMesh API docs: https://openvsp.org/api_docs/latest/group___c_f_d_mesh.html",
        "- OpenVSP Python API docs: https://openvsp.org/pyapi_docs/latest/openvsp.html",
        "",
        "The SU2/Gmsh/OpenVSP docs were used only to audit valid route semantics; they do not by themselves make the current coefficients credible.",
        "",
    ]
    (output_dir / "official_sources.md").write_text("\n".join(lines), encoding="utf-8")


def write_artifacts(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = build_campaign_summary(output_dir)
    _write_json(output_dir / "campaign_summary.json", summary)
    _write_json(output_dir / "force_reference_audit.json", summary["force_reference_audit"])
    _write_json(output_dir / "mesh_quality_audit.json", summary["mesh_quality"])
    _write_csv(
        output_dir / "attempts_summary.csv",
        list(summary["attempts"]),
        [
            "attempt_id",
            "route",
            "solver_status",
            "classification",
            "final_iteration",
            "final_cl",
            "final_cd",
            "boundary_layer_status",
            "notes",
        ],
    )
    _write_csv(
        output_dir / "sanity_comparison.csv",
        list(summary["sanity_comparison"]),
        ["case", "cl", "cd", "role"],
    )
    write_report(output_dir, summary)
    write_reviewer_prompt(output_dir, summary)
    write_official_sources(output_dir)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    summary = write_artifacts(args.output_dir)
    print(json.dumps({"verdict": summary["verdict"], "output_dir": str(args.output_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
