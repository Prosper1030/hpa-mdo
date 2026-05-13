#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "baseline_A_team_release" / "wo006_su2_baseline_validation"
DEFAULT_AUTHORITY_TABLE = (
    REPO_ROOT / "output" / "baseline_A_team_release" / "data_authority_table.csv"
)
DEFAULT_GEOMETRY_MANIFEST = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "final_candidate_package"
    / "geometry_exports"
    / "production_inspection"
    / "current_avl_compromise_conservative_closed"
    / "geometry_manifest.json"
)
DEFAULT_SELECTED_AVL_RECHECK = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "current_avl_compromise_conservative_closed_tier2_airfoil"
    / "tier2_loaded_shape_selected_avl_recheck.csv"
)
DEFAULT_CLOSURE_SUMMARY = (
    REPO_ROOT
    / "output"
    / "go_mode_main_wing_candidate"
    / "current_avl_compromise_conservative_closed_closure"
    / "aero_structure_closure_summary.csv"
)
DEFAULT_MESH_PROBES = (
    DEFAULT_OUTPUT_DIR / "smoke" / "current_pathfinder_mesh_handoff" / "main_wing_real_mesh_handoff_probe.v1.json",
    DEFAULT_OUTPUT_DIR
    / "smoke"
    / "current_pathfinder_mesh_handoff_coarse_sensitivity"
    / "main_wing_real_mesh_handoff_probe.v1.json",
)
DEFAULT_SU2_HANDOFF_PROBE = (
    DEFAULT_OUTPUT_DIR
    / "smoke"
    / "current_pathfinder_su2_handoff_blocked"
    / "main_wing_real_su2_handoff_probe.v1.json"
)

REOPEN_APPROACH_PCT = 5.0
REOPEN_EXCEEDED_PCT = 8.0


def _read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct_delta(candidate: float | None, reference: float | None) -> float | None:
    if candidate is None or reference in (None, 0.0):
        return None
    return (candidate - float(reference)) / float(reference) * 100.0


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.10g}"


def _authority_value(rows: list[dict[str, str]], authority_id: str) -> float:
    for row in rows:
        if row.get("authority_id") == authority_id:
            value = _float_or_none(row.get("important_number"))
            if value is None:
                raise ValueError(f"Authority row {authority_id} has no numeric value")
            return value
    raise ValueError(f"Authority row {authority_id} not found")


def _data_authority(authority_table_path: Path) -> dict[str, Any]:
    rows = _read_csv_rows(authority_table_path)
    return {
        "authority_table_path": str(authority_table_path),
        "design_gross_mass_kg": _authority_value(rows, "design_gross_mass_98p5"),
        "pipeline_full_span_m": _authority_value(rows, "pipeline_full_span_34p332286"),
        "pipeline_half_span_m": _authority_value(rows, "pipeline_half_span_17p166143"),
        "authority_note": (
            "WO-006 is bounded aero calibration only; it is not release, "
            "RFQ/procurement, structural, or final aircraft sign-off truth."
        ),
    }


def _selected_model_row(selected_avl_recheck_path: Path) -> dict[str, str]:
    rows = _read_csv_rows(selected_avl_recheck_path)
    for row in rows:
        if row.get("selected_role") == "conservative_best":
            return row
    raise ValueError("conservative_best row not found in selected AVL recheck CSV")


def _closure_row(closure_summary_path: Path) -> dict[str, str]:
    rows = _read_csv_rows(closure_summary_path)
    for row in rows:
        if row.get("selected_role") == "conservative_best":
            return row
    return {}


def _solver_report_is_usable(report: dict[str, Any]) -> bool:
    return (
        report.get("solver_execution_status") == "solver_executed"
        and report.get("convergence_gate_status") == "pass"
        and not report.get("blocking_reasons")
    )


def _select_solver_report(paths: list[Path]) -> tuple[dict[str, Any] | None, Path | None, bool]:
    reports: list[tuple[dict[str, Any], Path]] = []
    for path in paths:
        payload = _read_json(path)
        if payload is not None:
            reports.append((payload, path))
    for report, path in reports:
        if _solver_report_is_usable(report):
            return report, path, True
    if reports:
        return reports[-1][0], reports[-1][1], False
    return None, None, False


def _su2_status(
    *,
    solver_report: dict[str, Any] | None,
    solver_usable: bool,
    su2_handoff: dict[str, Any] | None,
    mesh_probes: list[dict[str, Any]],
) -> str:
    if solver_report is not None:
        return "su2_solver_usable" if solver_usable else "su2_solver_not_usable"
    if su2_handoff and su2_handoff.get("materialization_status") != "su2_handoff_written":
        return "su2_unavailable_mesh_blocked"
    if any(probe.get("mesh_handoff_status") == "missing" for probe in mesh_probes):
        return "su2_unavailable_mesh_blocked"
    return "su2_not_run"


def _build_delta_rows(
    *,
    selected_row: dict[str, str],
    closure_row: dict[str, str],
    solver_report: dict[str, Any] | None,
    solver_report_path: Path | None,
    solver_usable: bool,
    su2_status: str,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    model_cd_total = _float_or_none(selected_row.get("CD_total"))
    model_power = _float_or_none(selected_row.get("P_crank"))
    su2_coeffs = (
        solver_report.get("final_coefficients", {})
        if isinstance(solver_report, dict)
        else {}
    )
    su2_cl = _float_or_none(su2_coeffs.get("cl") if isinstance(su2_coeffs, dict) else None)
    su2_cd = _float_or_none(su2_coeffs.get("cd") if isinstance(su2_coeffs, dict) else None)
    su2_power = None
    if model_power is not None and model_cd_total not in (None, 0.0) and su2_cd is not None:
        su2_power = model_power * su2_cd / float(model_cd_total)

    rows = [
        {
            "model_or_case": "avl_loaded_shape_conservative_best",
            "status": str(selected_row.get("status", "available")),
            "source_path": "",
            "cl": _format_number(_float_or_none(selected_row.get("CL"))),
            "cd": "",
            "cdi": _format_number(_float_or_none(selected_row.get("CDi"))),
            "profile_cd": "",
            "cd0_total": "",
            "cd_total": "",
            "p_crank_w": "",
            "p_crank_conservative_w": "",
            "delta_cl_vs_su2": _format_number(_pct_delta(_float_or_none(selected_row.get("CL")), su2_cl)),
            "delta_cd_total_vs_su2_pct": "",
            "delta_cdi_vs_su2_pct": "",
            "delta_profile_cd_vs_su2_pct": "",
            "delta_power_vs_su2_pct": "",
            "notes": "AVL loaded-shape screening reference; no SU2 split for CDi.",
        },
        {
            "model_or_case": "tier2_xfoil_profile_drag",
            "status": str(selected_row.get("profile_source_quality", "available")),
            "source_path": "",
            "cl": "",
            "cd": "",
            "cdi": "",
            "profile_cd": _format_number(_float_or_none(selected_row.get("profile_cd"))),
            "cd0_total": _format_number(_float_or_none(selected_row.get("CD0_total"))),
            "cd_total": "",
            "p_crank_w": "",
            "p_crank_conservative_w": "",
            "delta_cl_vs_su2": "",
            "delta_cd_total_vs_su2_pct": "",
            "delta_cdi_vs_su2_pct": "",
            "delta_profile_cd_vs_su2_pct": "",
            "delta_power_vs_su2_pct": "",
            "notes": "XFOIL/Tier2 profile source; SU2 smoke does not provide profile/induced split.",
        },
        {
            "model_or_case": "closure_proxy_conservative_best",
            "status": str(closure_row.get("closure_status", "available")),
            "source_path": "",
            "cl": _format_number(_float_or_none(selected_row.get("CL"))),
            "cd": "",
            "cdi": _format_number(_float_or_none(selected_row.get("CDi"))),
            "profile_cd": _format_number(_float_or_none(selected_row.get("profile_cd"))),
            "cd0_total": _format_number(_float_or_none(selected_row.get("CD0_total"))),
            "cd_total": _format_number(model_cd_total),
            "p_crank_w": _format_number(model_power),
            "p_crank_conservative_w": _format_number(_float_or_none(selected_row.get("P_crank_conservative"))),
            "delta_cl_vs_su2": _format_number(_pct_delta(_float_or_none(selected_row.get("CL")), su2_cl)),
            "delta_cd_total_vs_su2_pct": _format_number(_pct_delta(model_cd_total, su2_cd)),
            "delta_cdi_vs_su2_pct": "",
            "delta_profile_cd_vs_su2_pct": "",
            "delta_power_vs_su2_pct": _format_number(_pct_delta(model_power, su2_power)),
            "notes": "Current screening proxy from AVL induced drag plus Tier2 profile drag.",
        },
        {
            "model_or_case": "fourier_avl_trace",
            "status": "not_promoted_current_trace",
            "source_path": "",
            "cl": "",
            "cd": "",
            "cdi": "",
            "profile_cd": "",
            "cd0_total": "",
            "cd_total": "",
            "p_crank_w": "",
            "p_crank_conservative_w": "",
            "delta_cl_vs_su2": "",
            "delta_cd_total_vs_su2_pct": "",
            "delta_cdi_vs_su2_pct": "",
            "delta_profile_cd_vs_su2_pct": "",
            "delta_power_vs_su2_pct": "",
            "notes": "Fourier-AVL tooling exists, but this checkout lacks a promoted current Stage-0-to-pathfinder trace.",
        },
        {
            "model_or_case": "current_pathfinder_su2",
            "status": su2_status,
            "source_path": "" if solver_report_path is None else str(solver_report_path),
            "cl": _format_number(su2_cl),
            "cd": _format_number(su2_cd),
            "cdi": "",
            "profile_cd": "",
            "cd0_total": "",
            "cd_total": _format_number(su2_cd),
            "p_crank_w": _format_number(su2_power),
            "p_crank_conservative_w": "",
            "delta_cl_vs_su2": "",
            "delta_cd_total_vs_su2_pct": "",
            "delta_cdi_vs_su2_pct": "",
            "delta_profile_cd_vs_su2_pct": "",
            "delta_power_vs_su2_pct": "",
            "notes": "SU2 integrated coefficients only; no CDi/profile decomposition in this bounded artifact.",
        },
    ]
    metrics = {
        "su2_cl": su2_cl,
        "su2_cd": su2_cd,
        "su2_power_w": su2_power,
        "model_cd_total": model_cd_total,
        "model_power_w": model_power,
        "su2_cd_delta_pct_vs_model": _pct_delta(su2_cd, model_cd_total),
        "su2_power_delta_pct_vs_model": _pct_delta(su2_power, model_power),
        "solver_usable": solver_usable,
    }
    return rows, metrics


def _build_reopen_risk(
    *,
    verdict: str,
    su2_status: str,
    metrics: dict[str, Any],
    mesh_probes: list[dict[str, Any]],
    su2_handoff: dict[str, Any] | None,
) -> dict[str, Any]:
    if not metrics.get("solver_usable"):
        return {
            "verdict": verdict,
            "reopen_trigger_status": "not_evaluated",
            "max_drag_or_power_delta_pct": None,
            "trigger_band_pct": [REOPEN_APPROACH_PCT, REOPEN_EXCEEDED_PCT],
            "reason": "Current pathfinder SU2 is not usable for aerodynamic deltas.",
            "blocking_reasons": _collect_blockers(mesh_probes, su2_handoff),
            "allowed_use": "route fix planning and bounded calibration setup only",
            "disallowed_use": [
                "release truth",
                "RFQ/procurement truth",
                "structural blocker pass/fail",
                "final aircraft sign-off",
            ],
        }
    deltas = [
        abs(value)
        for value in (
            metrics.get("su2_cd_delta_pct_vs_model"),
            metrics.get("su2_power_delta_pct_vs_model"),
        )
        if isinstance(value, (int, float))
    ]
    max_delta = max(deltas) if deltas else None
    if max_delta is not None and max_delta >= REOPEN_EXCEEDED_PCT:
        status = "exceeded"
        reason = "SU2 drag/power delta exceeds the Baseline A reopen trigger scale."
    elif max_delta is not None and max_delta >= REOPEN_APPROACH_PCT:
        status = "approached"
        reason = "SU2 drag/power delta approaches the Baseline A reopen trigger scale."
    else:
        status = "not_approached"
        reason = "Usable bounded SU2 deltas stay below the reopen trigger scale."
    return {
        "verdict": verdict,
        "reopen_trigger_status": status,
        "max_drag_or_power_delta_pct": max_delta,
        "trigger_band_pct": [REOPEN_APPROACH_PCT, REOPEN_EXCEEDED_PCT],
        "reason": reason,
        "su2_status": su2_status,
        "allowed_use": "bounded aero calibration only",
        "disallowed_use": [
            "release truth",
            "RFQ/procurement truth",
            "structural blocker pass/fail",
            "final aircraft sign-off",
        ],
    }


def _collect_blockers(
    mesh_probes: list[dict[str, Any]], su2_handoff: dict[str, Any] | None
) -> list[str]:
    blockers: list[str] = []
    for probe in mesh_probes:
        for reason in probe.get("blocking_reasons", []) or []:
            if isinstance(reason, str) and reason not in blockers:
                blockers.append(reason)
    if su2_handoff:
        for reason in su2_handoff.get("blocking_reasons", []) or []:
            if isinstance(reason, str) and reason not in blockers:
                blockers.append(reason)
    return blockers


def _verdict(*, solver_usable: bool, su2_status: str, metrics: dict[str, Any]) -> str:
    if not solver_usable:
        return "su2_baseline_needs_fix"
    max_delta = max(
        abs(value)
        for value in (
            metrics.get("su2_cd_delta_pct_vs_model"),
            metrics.get("su2_power_delta_pct_vs_model"),
        )
        if isinstance(value, (int, float))
    )
    if max_delta >= REOPEN_EXCEEDED_PCT:
        return "su2_baseline_reopen_risk"
    if su2_status == "su2_solver_usable":
        return "su2_baseline_calibration_usable"
    return "su2_baseline_needs_fix"


def _write_delta_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "model_or_case",
        "status",
        "source_path",
        "cl",
        "cd",
        "cdi",
        "profile_cd",
        "cd0_total",
        "cd_total",
        "p_crank_w",
        "p_crank_conservative_w",
        "delta_cl_vs_su2",
        "delta_cd_total_vs_su2_pct",
        "delta_cdi_vs_su2_pct",
        "delta_profile_cd_vs_su2_pct",
        "delta_power_vs_su2_pct",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(
    *,
    verdict: str,
    data_authority: dict[str, Any],
    geometry: dict[str, Any],
    su2_status: str,
    metrics: dict[str, Any],
    blockers: list[str],
    reopen_risk: dict[str, Any],
) -> str:
    lines = [
        "# WO-006 SU2 Baseline Validation",
        "",
        f"Verdict: `{verdict}`",
        "",
        "This is bounded main-wing SU2 aero calibration evidence only. It is not release truth, not RFQ/procurement truth, not structural sign-off, and not final aircraft sign-off.",
        "",
        "## Data Authority",
        "",
        f"- Design gross mass authority: `{data_authority['design_gross_mass_kg']} kg`.",
        f"- Current pipeline span authority: `{data_authority['pipeline_full_span_m']} m` full span / `{data_authority['pipeline_half_span_m']} m` half-span.",
        "- Any sensitivity case must be labeled as sensitivity; this package does not replace the authority table.",
        "",
        "## Geometry Basis",
        "",
        f"- Candidate: `{geometry.get('case_name', 'current_avl_compromise_conservative_closed')}`.",
        f"- Geometry source: `{geometry.get('source_geometry', 'unknown')}`.",
        f"- Sref / Bref / Cref: `{geometry.get('Sref')}` / `{geometry.get('Bref')}` / `{geometry.get('Cref')}`.",
        f"- Loaded tip Z: `{geometry.get('loaded_tip_z_m')}` m.",
        "",
        "## SU2 Status",
        "",
        f"- Current pathfinder SU2 status: `{su2_status}`.",
    ]
    if metrics.get("solver_usable"):
        lines.extend(
            [
                f"- SU2 CL / CD: `{metrics.get('su2_cl')}` / `{metrics.get('su2_cd')}`.",
                f"- CD delta vs closure proxy: `{metrics.get('su2_cd_delta_pct_vs_model'):.3f}%`.",
                f"- Power proxy delta vs closure proxy: `{metrics.get('su2_power_delta_pct_vs_model'):.3f}%`.",
            ]
        )
    else:
        lines.append("- No current-pathfinder SU2 CL/CD delta is usable because the mesh/SU2 handoff did not reach a solver case.")
    if blockers:
        lines.extend(["", "## Current Blockers", ""])
        lines.extend(f"- `{reason}`" for reason in blockers)
    lines.extend(
        [
            "",
            "## Aero Deltas",
            "",
            "- AVL loaded-shape reference remains the current screening aerodynamic model.",
            "- Tier2/XFOIL profile drag remains the current profile-drag estimate.",
            "- SU2 did not produce a current-pathfinder integrated CL/CD in this run, so CDi/profile split cannot be calibrated yet.",
            "- Fourier-AVL tooling exists, but this checkout still lacks a promoted current Stage-0-to-pathfinder trace for WO-006 comparison.",
            "",
            "## Reopen Risk",
            "",
            f"- Reopen trigger status: `{reopen_risk['reopen_trigger_status']}`.",
            f"- Trigger band: `{REOPEN_APPROACH_PCT:.0f}-{REOPEN_EXCEEDED_PCT:.0f}%` drag/power delta.",
            f"- Reason: {reopen_risk['reason']}",
            "",
            "## Engineering Caveats",
            "",
            "- Mesh timeout or boundary topology failure is route evidence, not aerodynamic evidence.",
            "- A passing Python test or generated report does not validate CFD convergence, aircraft performance, structure, C04, spar, rib, tail, or procurement.",
            "- The current result should drive a bounded meshing/SU2 route repair before any drag or power conclusion.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def build_wo006_artifacts(
    *,
    output_dir: Path,
    authority_table_path: Path,
    geometry_manifest_path: Path,
    selected_avl_recheck_path: Path,
    closure_summary_path: Path,
    mesh_probe_paths: list[Path],
    su2_handoff_probe_path: Path | None,
    solver_report_paths: list[Path],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    data_authority = _data_authority(authority_table_path)
    geometry = _read_json(geometry_manifest_path) or {}
    selected_row = _selected_model_row(selected_avl_recheck_path)
    closure = _closure_row(closure_summary_path)
    mesh_probes = [
        payload for payload in (_read_json(path) for path in mesh_probe_paths) if payload
    ]
    su2_handoff = _read_json(su2_handoff_probe_path)
    solver_report, solver_report_path, solver_usable = _select_solver_report(solver_report_paths)
    su2_status = _su2_status(
        solver_report=solver_report,
        solver_usable=solver_usable,
        su2_handoff=su2_handoff,
        mesh_probes=mesh_probes,
    )
    delta_rows, metrics = _build_delta_rows(
        selected_row=selected_row,
        closure_row=closure,
        solver_report=solver_report,
        solver_report_path=solver_report_path,
        solver_usable=solver_usable,
        su2_status=su2_status,
    )
    verdict = _verdict(
        solver_usable=solver_usable,
        su2_status=su2_status,
        metrics=metrics,
    )
    blockers = _collect_blockers(mesh_probes, su2_handoff)
    reopen_risk = _build_reopen_risk(
        verdict=verdict,
        su2_status=su2_status,
        metrics=metrics,
        mesh_probes=mesh_probes,
        su2_handoff=su2_handoff,
    )
    manifest = {
        "schema_version": "wo006_su2_baseline_validation.v1",
        "verdict": verdict,
        "data_authority": data_authority,
        "geometry_basis": {
            "path": str(geometry_manifest_path),
            "case_name": geometry.get("case_name"),
            "Sref": geometry.get("Sref"),
            "Bref": geometry.get("Bref"),
            "Cref": geometry.get("Cref"),
            "computed_span_m": geometry.get("computed_span_m"),
            "loaded_tip_z_m": geometry.get("loaded_tip_z_m"),
            "source_geometry": geometry.get("source_geometry"),
        },
        "model_sources": {
            "selected_avl_recheck_csv": str(selected_avl_recheck_path),
            "closure_summary_csv": str(closure_summary_path),
        },
        "mesh_probes": [
            {
                "path": str(path),
                "probe_status": payload.get("probe_status"),
                "mesh_handoff_status": payload.get("mesh_handoff_status"),
                "failure_code": payload.get("failure_code"),
                "error": payload.get("error"),
                "probe_global_min_size": payload.get("probe_global_min_size"),
                "probe_global_max_size": payload.get("probe_global_max_size"),
                "volume_element_count": payload.get("volume_element_count"),
                "blocking_reasons": payload.get("blocking_reasons", []),
            }
            for path, payload in zip(mesh_probe_paths, mesh_probes)
        ],
        "su2_handoff_probe": None
        if su2_handoff is None
        else {
            "path": None if su2_handoff_probe_path is None else str(su2_handoff_probe_path),
            "materialization_status": su2_handoff.get("materialization_status"),
            "su2_contract": su2_handoff.get("su2_contract"),
            "source_mesh_handoff_status": su2_handoff.get("source_mesh_handoff_status"),
            "volume_element_count": su2_handoff.get("volume_element_count"),
            "blocking_reasons": su2_handoff.get("blocking_reasons", []),
            "error": su2_handoff.get("error"),
        },
        "selected_solver_report": None
        if solver_report is None
        else {
            "path": None if solver_report_path is None else str(solver_report_path),
            "solver_execution_status": solver_report.get("solver_execution_status"),
            "convergence_gate_status": solver_report.get("convergence_gate_status"),
            "run_status": solver_report.get("run_status"),
            "final_iteration": solver_report.get("final_iteration"),
            "observed_velocity_mps": solver_report.get("observed_velocity_mps"),
            "runtime_max_iterations": solver_report.get("runtime_max_iterations"),
            "final_coefficients": solver_report.get("final_coefficients", {}),
            "blocking_reasons": solver_report.get("blocking_reasons", []),
        },
        "su2_status": su2_status,
        "metrics": metrics,
        "limitations": [
            "bounded_aero_calibration_only",
            "not_release_truth",
            "not_rfq_or_procurement_truth",
            "not_structural_signoff",
            "not_final_aircraft_signoff",
        ],
    }

    _write_delta_csv(output_dir / "aero_model_delta_table.csv", delta_rows)
    (output_dir / "su2_case_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "baseline_A_reopen_risk_from_su2.json").write_text(
        json.dumps(reopen_risk, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "su2_baseline_validation.md").write_text(
        _render_markdown(
            verdict=verdict,
            data_authority=data_authority,
            geometry=geometry,
            su2_status=su2_status,
            metrics=metrics,
            blockers=blockers,
            reopen_risk=reopen_risk,
        ),
        encoding="utf-8",
    )
    return {
        "verdict": verdict,
        "data_authority": data_authority,
        "su2_status": su2_status,
        "metrics": metrics,
        "reopen_risk": reopen_risk,
        "manifest": manifest,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--authority-table", type=Path, default=DEFAULT_AUTHORITY_TABLE)
    parser.add_argument("--geometry-manifest", type=Path, default=DEFAULT_GEOMETRY_MANIFEST)
    parser.add_argument("--selected-avl-recheck", type=Path, default=DEFAULT_SELECTED_AVL_RECHECK)
    parser.add_argument("--closure-summary", type=Path, default=DEFAULT_CLOSURE_SUMMARY)
    parser.add_argument(
        "--mesh-probe",
        type=Path,
        action="append",
        default=[],
        help="Current pathfinder mesh probe JSON. May be repeated.",
    )
    parser.add_argument("--su2-handoff-probe", type=Path, default=DEFAULT_SU2_HANDOFF_PROBE)
    parser.add_argument(
        "--solver-report",
        type=Path,
        action="append",
        default=[],
        help="Current pathfinder solver smoke report JSON. May be repeated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mesh_probes = args.mesh_probe or [path for path in DEFAULT_MESH_PROBES if path.exists()]
    result = build_wo006_artifacts(
        output_dir=args.out,
        authority_table_path=args.authority_table,
        geometry_manifest_path=args.geometry_manifest,
        selected_avl_recheck_path=args.selected_avl_recheck,
        closure_summary_path=args.closure_summary,
        mesh_probe_paths=mesh_probes,
        su2_handoff_probe_path=args.su2_handoff_probe,
        solver_report_paths=args.solver_report,
    )
    print(json.dumps({"verdict": result["verdict"], "su2_status": result["su2_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
