"""Standalone orchestration for the structural high-fidelity validation stack.

This module intentionally sits outside the optimisation loop.  It glues the
existing STEP -> Gmsh -> CalculiX -> FRD/ParaView helpers into one callable
entry point so validation can be launched without hand-running four scripts.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

import numpy as np

from hpa_mdo.aero import LoadMapper, VSPAeroParser
from hpa_mdo.core import Aircraft, MaterialDB, load_config
from hpa_mdo.core.config import HPAConfig
from hpa_mdo.core.constants import G_STANDARD
from hpa_mdo.hifi.calculix_runner import (
    BoundaryEntry,
    LoadEntry,
    parse_inp_nodes,
    prepare_buckle_inp,
    prepare_static_inp,
    root_boundary_from_mesh,
    run_static,
    tip_node_from_mesh,
)
from hpa_mdo.hifi.frd_parser import (
    parse_buckle_eigenvalues,
    parse_displacement,
    parse_nodal_coordinates,
)
from hpa_mdo.hifi.gmsh_runner import NamedPoint, mesh_step_to_inp
from hpa_mdo.hifi.paraview_state import make_pvpython_script

REPO_ROOT = Path(__file__).resolve().parents[3]
NUMBER_RE = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?"


@dataclass(frozen=True)
class StructuralCheckSection:
    """Result of one validation sub-check."""

    status: str
    message: str
    actual: float | None = None
    expected: float | None = None
    diff_pct: float | None = None
    threshold: float | None = None
    margin: float | None = None
    artifact_path: Path | None = None
    issue_category: str | None = None
    comparability: str | None = None
    log_path: Path | None = None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class StructuralCheckResult:
    """Combined result for the structural validation run."""

    report_path: Path
    summary_json_path: Path
    overall_status: str
    summary_path: Path | None
    step_path: Path | None
    mesh_path: Path | None
    paraview_script_path: Path | None
    load_description: str
    support_description: str
    static: StructuralCheckSection
    buckle: StructuralCheckSection


@dataclass(frozen=True)
class StructuralLoadModel:
    """Loads applied to the high-fidelity validation mesh."""

    description: str
    entries: tuple[LoadEntry, ...]
    total_fz_n: float
    source_path: Path | None = None
    source_kind: str = "unknown"
    comparison_basis: str = "limited"
    comparison_note: str | None = None


def parse_optimization_summary(summary_path: str | Path) -> dict[str, float | None]:
    """Extract the metrics needed by the validation stack from a text summary.

    The parser accepts both the legacy ``optimization_summary.txt`` format and
    the current dual-beam production ``crossval_report.txt`` design report.
    """

    text = Path(summary_path).read_text(encoding="utf-8", errors="ignore")
    metrics: dict[str, float | None] = {
        "tip_deflection_m": None,
        "buckling_index": None,
    }

    tip_match = re.search(
        rf"Tip deflection\s*:\s*({NUMBER_RE})\s*mm(?:\s*\(\s*({NUMBER_RE})\s*m\s*\))?",
        text,
        flags=re.IGNORECASE,
    )
    if tip_match:
        tip_m = tip_match.group(2)
        if tip_m is not None:
            metrics["tip_deflection_m"] = float(tip_m.replace("D", "E"))
        else:
            metrics["tip_deflection_m"] = 1.0e-3 * float(tip_match.group(1).replace("D", "E"))

    buckling_match = re.search(
        rf"Buckling index\s*:\s*({NUMBER_RE})",
        text,
        flags=re.IGNORECASE,
    )
    if buckling_match:
        metrics["buckling_index"] = float(buckling_match.group(1).replace("D", "E"))

    if metrics["tip_deflection_m"] is None:
        for pattern in (
            rf"Main tip deflection \(uz, y=tip\)\s+({NUMBER_RE})\s+mm",
            rf"Tip deflection \(uz, y=[^)]+\)\s+({NUMBER_RE})\s+mm",
        ):
            report_tip_match = re.search(pattern, text, flags=re.IGNORECASE)
            if report_tip_match:
                metrics["tip_deflection_m"] = (
                    1.0e-3 * float(report_tip_match.group(1).replace("D", "E"))
                )
                break

    return metrics


def named_points_from_config(cfg: HPAConfig) -> list[NamedPoint]:
    """Derive canonical ROOT / TIP / WIRE_N points for the meshed half wing."""

    half_span = 0.5 * float(cfg.wing.span)
    points: list[NamedPoint] = [
        NamedPoint("ROOT", (0.0, 0.0, 0.0)),
        NamedPoint("TIP", (0.0, half_span, 0.0)),
    ]
    if cfg.lift_wires.enabled:
        for idx, attachment in enumerate(cfg.lift_wires.attachments, start=1):
            points.append(NamedPoint(f"WIRE_{idx}", (0.0, float(attachment.y), 0.0)))
    return points


def buckling_lambda_threshold(mdo_buckling_index: float) -> float:
    """Convert KS ``demand / critical - 1`` into the equivalent eigenvalue threshold."""

    denominator = 1.0 + float(mdo_buckling_index)
    if denominator <= 0.0:
        return float("inf")
    return 1.0 / denominator


def run_structural_check(
    *,
    config_path: str | Path,
    summary_path: str | Path | None = None,
    step_path: str | Path | None = None,
    mesh_path: str | Path | None = None,
    hifi_dir: str | Path | None = None,
    material_key: str = "carbon_fiber_hm",
    tip_load_n: float | None = None,
    generate_paraview: bool = True,
) -> StructuralCheckResult:
    """Run the available structural high-fidelity checks and write a combined report."""

    cfg = load_config(Path(config_path))
    output_dir = _resolve_repo_path(cfg.io.output_dir)
    hifi_root = _resolve_repo_path(hifi_dir) if hifi_dir is not None else output_dir / "hifi"
    hifi_root.mkdir(parents=True, exist_ok=True)

    resolved_summary = _resolve_optional_path(summary_path)
    if resolved_summary is None:
        resolved_summary = _discover_default_summary(output_dir)
    summary_metrics = (
        parse_optimization_summary(resolved_summary)
        if resolved_summary is not None and resolved_summary.exists()
        else {"tip_deflection_m": None, "buckling_index": None}
    )

    resolved_mesh = _resolve_optional_path(mesh_path)
    resolved_step = _resolve_optional_path(step_path)

    if resolved_mesh is None:
        if resolved_step is None:
            resolved_step = _discover_default_step(output_dir)
        if resolved_step is not None:
            resolved_mesh = hifi_root / f"{resolved_step.stem}.inp"
            meshed = mesh_step_to_inp(
                resolved_step,
                resolved_mesh,
                cfg,
                named_points=named_points_from_config(cfg),
            )
            if meshed is None:
                resolved_mesh = None
            else:
                resolved_mesh = Path(meshed).resolve()

    if resolved_mesh is None or not resolved_mesh.exists():
        report_path = hifi_root / "structural_check.md"
        summary_json_path = hifi_root / "structural_check.json"
        static = StructuralCheckSection(
            status="SKIP",
            message=(
                "No mesh available. Provide --mesh or create a STEP export first "
                "with scripts/vsp_to_cfd.py + scripts/hifi_mesh_step.py."
            ),
            issue_category="mesh_unavailable",
            comparability="NOT_COMPARABLE",
        )
        buckle = StructuralCheckSection(
            status="SKIP",
            message="Buckling check skipped because no CalculiX mesh was available.",
            issue_category="mesh_unavailable",
            comparability="NOT_COMPARABLE",
        )
        _write_combined_report(
            report_path,
            summary_path=resolved_summary,
            step_path=resolved_step,
            mesh_path=resolved_mesh,
            paraview_script_path=None,
            load_model=None,
            support_description="No mesh available; no structural supports were derived.",
            static=static,
            buckle=buckle,
            reference_metrics=summary_metrics,
        )
        _write_combined_summary_json(
            summary_json_path,
            summary_path=resolved_summary,
            step_path=resolved_step,
            mesh_path=resolved_mesh,
            paraview_script_path=None,
            load_model=None,
            support_description="No mesh available; no structural supports were derived.",
            static=static,
            buckle=buckle,
            reference_metrics=summary_metrics,
        )
        return StructuralCheckResult(
            report_path=report_path,
            summary_json_path=summary_json_path,
            overall_status="SKIP",
            summary_path=resolved_summary,
            step_path=resolved_step,
            mesh_path=resolved_mesh,
            paraview_script_path=None,
            load_description="No mesh available; no loads were applied.",
            support_description="No mesh available; no structural supports were derived.",
            static=static,
            buckle=buckle,
        )

    mesh_length_scale_m = _mesh_length_scale_m_per_unit(resolved_mesh, cfg)
    section_thickness_units = _representative_section_thickness_m(cfg) / mesh_length_scale_m
    material_payload = _material_payload(
        material_key,
        length_scale_m_per_unit=mesh_length_scale_m,
    )
    boundary_entries = _support_boundary_from_mesh(resolved_mesh, cfg)
    load_model = _build_load_model(
        cfg=cfg,
        output_dir=output_dir,
        mesh_path=resolved_mesh,
        step_path=resolved_step,
        explicit_tip_load_n=tip_load_n,
        mesh_length_scale_m_per_unit=mesh_length_scale_m,
    )

    static = _run_static_check(
        mesh_path=resolved_mesh,
        hifi_dir=hifi_root,
        cfg=cfg,
        material_payload=material_payload,
        expected_tip_deflection_m=summary_metrics["tip_deflection_m"],
        boundary_entries=boundary_entries,
        load_model=load_model,
        mesh_length_scale_m_per_unit=mesh_length_scale_m,
        section_thickness_units=section_thickness_units,
    )
    buckle = _run_buckle_check(
        mesh_path=resolved_mesh,
        hifi_dir=hifi_root,
        cfg=cfg,
        material_payload=material_payload,
        expected_buckling_index=summary_metrics["buckling_index"],
        boundary_entries=boundary_entries,
        load_model=load_model,
        section_thickness_units=section_thickness_units,
    )

    paraview_script_path = None
    if generate_paraview:
        frd_paths = [
            section.artifact_path
            for section in (static, buckle)
            if section.artifact_path is not None and section.artifact_path.suffix.lower() == ".frd"
        ]
        if frd_paths:
            paraview_script_path = make_pvpython_script(
                frd_paths,
                hifi_root / "visualise.py",
                span_m=float(cfg.wing.span),
            )

    report_path = hifi_root / "structural_check.md"
    summary_json_path = hifi_root / "structural_check.json"
    _write_combined_report(
        report_path,
        summary_path=resolved_summary,
        step_path=resolved_step,
        mesh_path=resolved_mesh,
        paraview_script_path=paraview_script_path,
        load_model=load_model,
        support_description=_support_description(boundary_entries, cfg),
        static=static,
        buckle=buckle,
        reference_metrics=summary_metrics,
    )
    _write_combined_summary_json(
        summary_json_path,
        summary_path=resolved_summary,
        step_path=resolved_step,
        mesh_path=resolved_mesh,
        paraview_script_path=paraview_script_path,
        load_model=load_model,
        support_description=_support_description(boundary_entries, cfg),
        static=static,
        buckle=buckle,
        reference_metrics=summary_metrics,
    )
    overall_status = _combine_status(static.status, buckle.status)
    return StructuralCheckResult(
        report_path=report_path,
        summary_json_path=summary_json_path,
        overall_status=overall_status,
        summary_path=resolved_summary,
        step_path=resolved_step,
        mesh_path=resolved_mesh,
        paraview_script_path=paraview_script_path,
        load_description=load_model.description,
        support_description=_support_description(boundary_entries, cfg),
        static=static,
        buckle=buckle,
    )


def _run_static_check(
    *,
    mesh_path: Path,
    hifi_dir: Path,
    cfg: HPAConfig,
    material_payload: dict[str, float],
    expected_tip_deflection_m: float | None,
    boundary_entries: list[BoundaryEntry],
    load_model: StructuralLoadModel,
    mesh_length_scale_m_per_unit: float,
    section_thickness_units: float,
) -> StructuralCheckSection:
    try:
        tip_node = tip_node_from_mesh(mesh_path)
    except Exception as exc:  # noqa: BLE001
        return StructuralCheckSection(
            status="WARN",
            message=f"Could not derive TIP from mesh: {exc}",
            issue_category="mesh_boundary_contract",
            comparability="NOT_COMPARABLE",
        )

    static_inp = hifi_dir / f"{mesh_path.stem}_static.inp"
    prepare_static_inp(
        mesh_path,
        static_inp,
        material_payload,
        _boundary_arg(boundary_entries),
        list(load_model.entries),
        section_thickness=section_thickness_units,
    )
    result = run_static(static_inp, cfg)
    if result.get("error"):
        issue_category, diagnostics = _diagnose_solver_result(result)
        return StructuralCheckSection(
            status="WARN",
            message=f"CalculiX static failed or was skipped: {issue_category}.",
            artifact_path=Path(result.get("log", static_inp)).resolve(),
            issue_category=issue_category,
            comparability="NOT_COMPARABLE",
            log_path=Path(result["log"]).resolve() if result.get("log") else None,
            diagnostics=diagnostics,
        )

    frd_path = Path(result["frd"]).resolve()
    disp = parse_displacement(frd_path)
    if disp.size == 0:
        return StructuralCheckSection(
            status="WARN",
            message=f"No displacement rows found in {frd_path}",
            artifact_path=frd_path,
            issue_category="solver_output",
            comparability="NOT_COMPARABLE",
        )

    matches = disp[disp[:, 0].astype(int) == int(tip_node)]
    frd_match_note = ""
    if matches.size == 0:
        matched_row, matched_distance_m = _match_tip_displacement_by_coordinates(
            mesh_path=mesh_path,
            frd_path=frd_path,
            tip_node=int(tip_node),
            displacement_rows=disp,
            mesh_length_scale_m_per_unit=mesh_length_scale_m_per_unit,
        )
        if matched_row is None:
            available_min = int(np.min(disp[:, 0])) if disp.size else None
            available_max = int(np.max(disp[:, 0])) if disp.size else None
            id_range = (
                f"{available_min}..{available_max}"
                if available_min is not None and available_max is not None
                else "unknown"
            )
            return StructuralCheckSection(
                status="WARN",
                message=(
                    f"Tip node {tip_node} not found in FRD displacement output "
                    f"(available node ids {id_range})."
                ),
                artifact_path=frd_path,
                issue_category="postprocess_mapping",
                comparability="NOT_COMPARABLE",
            )
        matches = matched_row[np.newaxis, :]
        frd_match_note = (
            f" FRD tip matched by coordinates ({matched_distance_m:.4f} m offset)."
        )

    if matches.size == 0:
        return StructuralCheckSection(
            status="WARN",
            message=f"Tip node {tip_node} not found in FRD displacement output.",
            artifact_path=frd_path,
            issue_category="postprocess_mapping",
            comparability="NOT_COMPARABLE",
        )

    tip_deflection_m = abs(float(matches[-1, 3])) * mesh_length_scale_m_per_unit
    diff_pct = _pct_diff(tip_deflection_m, expected_tip_deflection_m)
    status = "PASS" if diff_pct is not None and abs(diff_pct) <= 5.0 else "WARN"
    if expected_tip_deflection_m is None:
        status = "SKIP"
    comparability = _assess_section_comparability(
        has_reference=expected_tip_deflection_m is not None,
        load_model=load_model,
        solver_ok=True,
    )
    message = (
        f"Static tip-deflection check completed using {load_model.description}{frd_match_note}"
        if expected_tip_deflection_m is not None
        else (
            f"Static run completed with {load_model.description}{frd_match_note}, "
            "but no reference tip deflection was available."
        )
    )
    return StructuralCheckSection(
        status=status,
        message=message,
        actual=tip_deflection_m,
        expected=expected_tip_deflection_m,
        diff_pct=diff_pct,
        artifact_path=frd_path,
        issue_category=None if status in {"PASS", "SKIP"} else "result_mismatch",
        comparability=comparability,
        log_path=Path(result["log"]).resolve() if result.get("log") else None,
    )


def _run_buckle_check(
    *,
    mesh_path: Path,
    hifi_dir: Path,
    cfg: HPAConfig,
    material_payload: dict[str, float],
    expected_buckling_index: float | None,
    boundary_entries: list[BoundaryEntry],
    load_model: StructuralLoadModel,
    section_thickness_units: float,
) -> StructuralCheckSection:
    try:
        tip_node_from_mesh(mesh_path)
    except Exception as exc:  # noqa: BLE001
        return StructuralCheckSection(
            status="WARN",
            message=f"Could not derive TIP from mesh: {exc}",
            issue_category="mesh_boundary_contract",
            comparability="NOT_COMPARABLE",
        )

    buckle_inp = hifi_dir / f"{mesh_path.stem}_buckle.inp"
    prepare_buckle_inp(
        mesh_path,
        buckle_inp,
        material_payload,
        _boundary_arg(boundary_entries),
        list(load_model.entries),
        section_thickness=section_thickness_units,
    )
    result = run_static(buckle_inp, cfg)
    if result.get("error"):
        issue_category, diagnostics = _diagnose_solver_result(result)
        return StructuralCheckSection(
            status="WARN",
            message=f"CalculiX BUCKLE failed or was skipped: {issue_category}.",
            artifact_path=Path(result.get("log", buckle_inp)).resolve(),
            issue_category=issue_category,
            comparability="NOT_COMPARABLE",
            log_path=Path(result["log"]).resolve() if result.get("log") else None,
            diagnostics=diagnostics,
        )

    dat_path = Path(result["dat"]).resolve()
    frd_path = Path(result["frd"]).resolve()
    eigenvalues = parse_buckle_eigenvalues(dat_path)
    if not eigenvalues:
        return StructuralCheckSection(
            status="WARN",
            message=f"No BUCKLE eigenvalues found in {dat_path}",
            artifact_path=frd_path,
            issue_category="solver_output",
            comparability="NOT_COMPARABLE",
            log_path=Path(result["log"]).resolve() if result.get("log") else None,
        )

    lambda_1 = float(eigenvalues[0])
    threshold = (
        buckling_lambda_threshold(expected_buckling_index)
        if expected_buckling_index is not None
        else None
    )
    margin = None if threshold is None else lambda_1 - threshold
    status = "PASS" if margin is not None and margin >= 0.0 else "WARN"
    if expected_buckling_index is None:
        status = "SKIP"
    comparability = _assess_section_comparability(
        has_reference=expected_buckling_index is not None,
        load_model=load_model,
        solver_ok=True,
    )
    message = (
        f"Buckling check completed using {load_model.description}"
        if expected_buckling_index is not None
        else f"BUCKLE run completed with {load_model.description}, but no reference buckling index was available."
    )
    return StructuralCheckSection(
        status=status,
        message=message,
        actual=lambda_1,
        expected=expected_buckling_index,
        threshold=threshold,
        margin=margin,
        artifact_path=frd_path,
        issue_category=None if status in {"PASS", "SKIP"} else "result_mismatch",
        comparability=comparability,
        log_path=Path(result["log"]).resolve() if result.get("log") else None,
    )


def _material_payload(
    material_key: str,
    *,
    length_scale_m_per_unit: float = 1.0,
) -> dict[str, float]:
    materials_db = MaterialDB(REPO_ROOT / "data" / "materials.yaml")
    material = materials_db.get(material_key)
    length_scale = float(length_scale_m_per_unit)
    return {
        # CalculiX is unitless, so when the mesh coordinates are not in metres
        # we scale material properties into ``N / unit^2`` and ``kg / unit^3``.
        "E": float(material.E) * length_scale**2,
        "nu": float(material.poisson_ratio),
        "rho": float(material.density) * length_scale**3,
    }


def _resolve_repo_path(path_like: str | Path | None) -> Path:
    if path_like is None:
        raise ValueError("path_like cannot be None")
    path = Path(path_like).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (REPO_ROOT / path).resolve()


def _resolve_optional_path(path_like: str | Path | None) -> Path | None:
    if path_like is None:
        return None
    return _resolve_repo_path(path_like)


def _current_standard_output_roots(output_dir: Path) -> tuple[Path, ...]:
    sibling_production = output_dir.with_name(f"{output_dir.name}_dual_beam_production_check")
    roots: list[Path] = []
    if sibling_production.exists():
        roots.append(sibling_production.resolve())
    roots.append(output_dir.resolve())
    return tuple(roots)


def _report_export_mode(report_path: Path) -> str | None:
    if not report_path.exists():
        return None
    text = report_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"Export mode:\s*([A-Za-z0-9_]+)", text, flags=re.IGNORECASE)
    return None if match is None else match.group(1).strip().lower()


def _discover_default_summary(output_dir: Path) -> Path | None:
    for root in _current_standard_output_roots(output_dir):
        candidate = root / "ansys" / "crossval_report.txt"
        if _report_export_mode(candidate) == "dual_beam_production":
            return candidate.resolve()

    for root in _current_standard_output_roots(output_dir):
        for name in ("optimization_summary.txt", "fsi_one_way/optimization_summary.txt"):
            candidate = root / name
            if candidate.exists():
                return candidate.resolve()
    return None


def _discover_default_step(output_dir: Path) -> Path | None:
    for name in (
        "spar_jig_shape.step",
        "jig_shape.step",
        "loaded_shape.step",
        "spar_flight_shape.step",
        "wing_jig.step",
        "jig.step",
        "spar_model.step",
        "spar_geometry.step",
        "wing_cruise.step",
        "cruise.step",
    ):
        candidate = output_dir / name
        if candidate.exists():
            return candidate.resolve()
    return None


def _pct_diff(actual: float | None, expected: float | None) -> float | None:
    if actual is None or expected is None:
        return None
    if abs(expected) < 1.0e-12:
        return None
    return 100.0 * (actual - expected) / abs(expected)


def _combine_status(*statuses: str) -> str:
    if any(status == "WARN" for status in statuses):
        return "WARN"
    if any(status == "PASS" for status in statuses):
        return "PASS"
    return "SKIP"


def _combine_comparability(*levels: str | None) -> str:
    filtered = [level for level in levels if level]
    if not filtered:
        return "NOT_COMPARABLE"
    if "NOT_COMPARABLE" in filtered:
        return "NOT_COMPARABLE"
    if "LIMITED" in filtered:
        return "LIMITED"
    return "COMPARABLE"


def _assess_section_comparability(
    *,
    has_reference: bool,
    load_model: StructuralLoadModel,
    solver_ok: bool,
) -> str:
    if not solver_ok:
        return "NOT_COMPARABLE"
    if not has_reference:
        return "LIMITED"
    if load_model.comparison_basis == "direct":
        return "COMPARABLE"
    return "LIMITED"


_DIAGNOSTIC_PATTERNS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "mesh_quality",
        (
            ("opposite_normals", "opposite normals are defined"),
            ("nonpositive_jacobian", "nonpositive jacobian"),
            ("negative_jacobian", "negative jacobian"),
            ("collapsed_element", "collapsed element"),
        ),
    ),
    (
        "boundary_conditions",
        (
            ("singular_matrix", "system of equations is singular"),
            ("zero_pivot", "zero pivot"),
            ("missing_dof", "no degrees of freedom"),
            ("unconnected_node", "not connected to any active degree of freedom"),
        ),
    ),
    (
        "load_mapping",
        (
            ("unknown_nset", "nset"),
            ("unknown_elset", "elset"),
            ("cload_issue", "*cload"),
            ("dload_issue", "*dload"),
            ("load_definition", "distributed load"),
        ),
    ),
    (
        "solver_execution",
        (
            ("timed_out", "timed out"),
            ("launch_failed", "failed to start"),
            ("missing_frd", "did not produce expected frd output"),
            ("ccx_failed", "ccx failed"),
        ),
    ),
)


def _diagnose_solver_result(result: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    snippets = [
        str(result.get("error") or ""),
        str(result.get("stderr") or ""),
        str(result.get("stdout") or ""),
    ]
    text = "\n".join(part for part in snippets if part).lower()
    if not text:
        return "solver_execution", ()

    for category, patterns in _DIAGNOSTIC_PATTERNS:
        hits: list[str] = []
        for label, needle in patterns:
            count = text.count(needle.lower())
            if count > 0:
                hits.append(f"{label} x{count}")
        if hits:
            return category, tuple(hits)
    return "solver_execution", ()


def _write_combined_report(
    report_path: Path,
    *,
    summary_path: Path | None,
    step_path: Path | None,
    mesh_path: Path | None,
    paraview_script_path: Path | None,
    load_model: StructuralLoadModel | None,
    support_description: str,
    static: StructuralCheckSection,
    buckle: StructuralCheckSection,
    reference_metrics: dict[str, float | None],
) -> None:
    overall_status = _combine_status(static.status, buckle.status)
    overall_comparability = _combine_comparability(static.comparability, buckle.comparability)
    lines = [
        "# High-Fidelity Structural Check",
        "",
        f"- Overall status: {overall_status}",
        f"- Overall comparability: {overall_comparability}",
        f"- Summary input: {summary_path or '—'}",
        f"- STEP input: {step_path or '—'}",
        f"- Mesh input: {mesh_path or '—'}",
        f"- ParaView script: {paraview_script_path or '—'}",
        f"- Loads: {load_model.description if load_model is not None else '—'}",
        f"- Load source kind: {load_model.source_kind if load_model is not None else '—'}",
        f"- Load comparison basis: {load_model.comparison_basis.upper() if load_model is not None else '—'}",
        f"- Load note: {load_model.comparison_note if load_model is not None and load_model.comparison_note is not None else '—'}",
        f"- Applied total Fz [N]: {_fmt(load_model.total_fz_n if load_model is not None else None)}",
        f"- Supports: {support_description}",
        "",
        "## Reference Metrics",
        "",
        f"- Tip deflection [m]: {_fmt(reference_metrics.get('tip_deflection_m'))}",
        f"- Buckling index: {_fmt(reference_metrics.get('buckling_index'))}",
        "",
        "## Static Deflection",
        "",
        f"- Status: {static.status}",
        f"- Comparability: {static.comparability or '—'}",
        f"- Issue category: {static.issue_category or '—'}",
        f"- Diagnostics: {', '.join(static.diagnostics) if static.diagnostics else '—'}",
        f"- Message: {static.message}",
        f"- Hifi |uz_tip| [m]: {_fmt(static.actual)}",
        f"- MDO tip deflection [m]: {_fmt(static.expected)}",
        f"- Diff [%]: {_fmt(static.diff_pct)}",
        f"- Artifact: {static.artifact_path or '—'}",
        f"- Solver log: {static.log_path or '—'}",
        "",
        "## Buckling",
        "",
        f"- Status: {buckle.status}",
        f"- Comparability: {buckle.comparability or '—'}",
        f"- Issue category: {buckle.issue_category or '—'}",
        f"- Diagnostics: {', '.join(buckle.diagnostics) if buckle.diagnostics else '—'}",
        f"- Message: {buckle.message}",
        f"- lambda_1: {_fmt(buckle.actual)}",
        f"- MDO buckling index: {_fmt(buckle.expected)}",
        f"- lambda_threshold: {_fmt(buckle.threshold)}",
        f"- margin_lambda: {_fmt(buckle.margin)}",
        f"- Artifact: {buckle.artifact_path or '—'}",
        f"- Solver log: {buckle.log_path or '—'}",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


def _write_combined_summary_json(
    summary_json_path: Path,
    *,
    summary_path: Path | None,
    step_path: Path | None,
    mesh_path: Path | None,
    paraview_script_path: Path | None,
    load_model: StructuralLoadModel | None,
    support_description: str,
    static: StructuralCheckSection,
    buckle: StructuralCheckSection,
    reference_metrics: dict[str, float | None],
) -> None:
    payload = {
        "overall_status": _combine_status(static.status, buckle.status),
        "overall_comparability": _combine_comparability(static.comparability, buckle.comparability),
        "summary_path": None if summary_path is None else str(summary_path),
        "step_path": None if step_path is None else str(step_path),
        "mesh_path": None if mesh_path is None else str(mesh_path),
        "paraview_script_path": None if paraview_script_path is None else str(paraview_script_path),
        "support_description": support_description,
        "load_model": {
            "description": None if load_model is None else load_model.description,
            "total_fz_n": None if load_model is None else load_model.total_fz_n,
            "source_path": None if load_model is None or load_model.source_path is None else str(load_model.source_path),
            "source_kind": None if load_model is None else load_model.source_kind,
            "comparison_basis": None if load_model is None else load_model.comparison_basis,
            "comparison_note": None if load_model is None else load_model.comparison_note,
        },
        "reference_metrics": {
            "tip_deflection_m": reference_metrics.get("tip_deflection_m"),
            "buckling_index": reference_metrics.get("buckling_index"),
        },
        "static": _section_payload(static),
        "buckle": _section_payload(buckle),
    }
    summary_json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.6g}"


def _section_payload(section: StructuralCheckSection) -> dict[str, Any]:
    return {
        "status": section.status,
        "comparability": section.comparability,
        "issue_category": section.issue_category,
        "message": section.message,
        "actual": section.actual,
        "expected": section.expected,
        "diff_pct": section.diff_pct,
        "threshold": section.threshold,
        "margin": section.margin,
        "artifact_path": None if section.artifact_path is None else str(section.artifact_path),
        "log_path": None if section.log_path is None else str(section.log_path),
        "diagnostics": list(section.diagnostics),
    }


def _boundary_arg(boundary_entries: list[tuple[int, tuple[int, ...]]]) -> Any:
    """Adapt a canonical boundary list to the legacy CalculiX helper API."""

    if len(boundary_entries) == 1:
        return boundary_entries[0]
    return boundary_entries


def _support_boundary_from_mesh(mesh_path: Path, cfg: HPAConfig) -> list[BoundaryEntry]:
    boundary_entries = list(root_boundary_from_mesh(mesh_path))
    try:
        from hpa_mdo.hifi.gmsh_runner import parse_nset_from_inp

        nsets = parse_nset_from_inp(mesh_path)
    except Exception:
        nsets = {}

    if cfg.lift_wires.enabled:
        for idx, attachment in enumerate(cfg.lift_wires.attachments, start=1):
            nset_name = f"WIRE_{idx}"
            if nset_name in nsets and nsets[nset_name]:
                boundary_entries.extend((int(node_id), (3,)) for node_id in nsets[nset_name])
                continue
            node_id = _nearest_node_for_spanwise_y(
                mesh_path,
                float(attachment.y),
                cfg,
            )
            boundary_entries.append((node_id, (3,)))
    return _merge_boundary_entries(boundary_entries)


def _merge_boundary_entries(entries: list[BoundaryEntry]) -> list[BoundaryEntry]:
    merged: dict[int, set[int]] = {}
    for node_id, dofs in entries:
        merged.setdefault(int(node_id), set()).update(int(dof) for dof in dofs)
    return [
        (node_id, tuple(sorted(dofs)))
        for node_id, dofs in sorted(merged.items())
    ]


def _support_description(boundary_entries: list[BoundaryEntry], cfg: HPAConfig) -> str:
    root_count = sum(1 for _node_id, dofs in boundary_entries if tuple(sorted(dofs)) == (1, 2, 3))
    wire_count = sum(1 for _node_id, dofs in boundary_entries if tuple(sorted(dofs)) == (3,))
    if cfg.lift_wires.enabled:
        return f"ROOT clamp nodes={root_count}; wire U3 supports={wire_count}"
    return f"ROOT clamp nodes={root_count}; no wire supports"


def _build_load_model(
    *,
    cfg: HPAConfig,
    output_dir: Path,
    mesh_path: Path,
    step_path: Path | None,
    explicit_tip_load_n: float | None,
    mesh_length_scale_m_per_unit: float,
) -> StructuralLoadModel:
    if explicit_tip_load_n is not None:
        tip_node = tip_node_from_mesh(mesh_path)
        load_n = float(explicit_tip_load_n)
        return StructuralLoadModel(
            description=f"explicit tip load ({load_n:.6g} N at node {tip_node})",
            entries=((tip_node, 3, load_n),),
            total_fz_n=load_n,
            source_kind="explicit_tip_load",
            comparison_basis="limited",
            comparison_note="Explicit tip loads are useful for controlled spot-checks, but not a direct like-for-like MDO load replay.",
        )

    source_candidates = _default_spar_csv_candidates(output_dir=output_dir, step_path=step_path)

    for csv_path in source_candidates:
        load_model = _load_model_from_spar_csv(
            csv_path=csv_path,
            mesh_path=mesh_path,
            cfg=cfg,
            mesh_length_scale_m_per_unit=mesh_length_scale_m_per_unit,
        )
        if load_model is not None:
            return load_model

    load_model = _load_model_from_vsp(
        cfg=cfg,
        mesh_path=mesh_path,
        mesh_length_scale_m_per_unit=mesh_length_scale_m_per_unit,
    )
    if load_model is not None:
        return load_model

    tip_node = tip_node_from_mesh(mesh_path)
    load_n = -0.5 * float(cfg.weight.max_takeoff_kg) * G_STANDARD
    return StructuralLoadModel(
        description=f"default tip load fallback ({load_n:.6g} N at node {tip_node})",
        entries=((tip_node, 3, load_n),),
        total_fz_n=load_n,
        source_kind="default_tip_load",
        comparison_basis="limited",
        comparison_note="No spar CSV or VSPAero load trace was found, so the structural check fell back to a coarse tip-load surrogate.",
    )


def _default_spar_csv_candidates(*, output_dir: Path, step_path: Path | None) -> list[Path]:
    source_hint = "" if step_path is None else step_path.stem.lower()
    candidates: list[Path] = []
    root_candidates = _current_standard_output_roots(output_dir)
    root_first = "jig" in source_hint or "spar" in source_hint

    ordered_roots = root_candidates if root_first else tuple(reversed(root_candidates))
    for root in ordered_roots:
        candidates.append(root / "ansys" / "spar_data.csv")
    for root in ordered_roots:
        candidates.append(root / "fsi_one_way" / "ansys" / "spar_data.csv")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _load_model_from_spar_csv(
    *,
    csv_path: Path,
    mesh_path: Path,
    cfg: HPAConfig,
    mesh_length_scale_m_per_unit: float,
) -> StructuralLoadModel | None:
    if not csv_path.exists():
        return None

    y_stations_m: list[float] = []
    fz_nodal: list[float] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"Y_Position_m", "Main_FZ_N", "Rear_FZ_N"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            return None
        for row in reader:
            try:
                y_m = float(row["Y_Position_m"])
                main_fz = float(row["Main_FZ_N"])
                rear_fz = float(row["Rear_FZ_N"])
            except (TypeError, ValueError):
                continue
            y_stations_m.append(y_m)
            fz_nodal.append(main_fz + rear_fz)

    if not y_stations_m:
        return None

    entries = _map_spanwise_forces_to_mesh(
        mesh_path=mesh_path,
        cfg=cfg,
        y_stations_m=np.asarray(y_stations_m, dtype=float),
        force_z_n=np.asarray(fz_nodal, dtype=float),
        mesh_length_scale_m_per_unit=mesh_length_scale_m_per_unit,
    )
    if not entries:
        return None

    total_fz_n = float(np.sum(fz_nodal))
    return StructuralLoadModel(
        description=(
            f"distributed nodal Fz from {_display_path(csv_path)} "
            f"({len(entries)} mesh nodes, total {total_fz_n:.3f} N)"
        ),
        entries=tuple(entries),
        total_fz_n=total_fz_n,
        source_path=csv_path,
        source_kind="spar_csv",
        comparison_basis="direct",
        comparison_note="Distributed spar loads came from a generated spanwise load table, which is the most comparable local replay currently available.",
    )


def _load_model_from_vsp(
    *,
    cfg: HPAConfig,
    mesh_path: Path,
    mesh_length_scale_m_per_unit: float,
) -> StructuralLoadModel | None:
    if cfg.io.vsp_lod is None or cfg.io.vsp_polar is None:
        return None
    if not Path(cfg.io.vsp_lod).exists() or not Path(cfg.io.vsp_polar).exists():
        return None

    aircraft = Aircraft.from_config(cfg)
    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
    cases = parser.parse()
    if not cases:
        return None

    mapper = LoadMapper()
    target_weight = aircraft.weight_N
    best_loads: dict[str, Any] | None = None
    best_residual = float("inf")

    for case in cases:
        mapped = mapper.map_loads(
            case,
            aircraft.wing.y,
            actual_velocity=cfg.flight.velocity,
            actual_density=cfg.flight.air_density,
        )
        residual = abs(2.0 * float(mapped["total_lift"]) - target_weight)
        if residual < best_residual:
            best_residual = residual
            best_loads = mapped

    if best_loads is None:
        return None

    design_case = cfg.structural_load_cases()[0]
    scaled = LoadMapper.apply_load_factor(best_loads, design_case.aero_scale)
    node_spacings = _node_spacings(np.asarray(scaled["y"], dtype=float))
    fz_nodal = np.asarray(scaled["lift_per_span"], dtype=float) * node_spacings
    entries = _map_spanwise_forces_to_mesh(
        mesh_path=mesh_path,
        cfg=cfg,
        y_stations_m=np.asarray(scaled["y"], dtype=float),
        force_z_n=fz_nodal,
        mesh_length_scale_m_per_unit=mesh_length_scale_m_per_unit,
    )
    if not entries:
        return None

    total_fz_n = float(np.sum(fz_nodal))
    return StructuralLoadModel(
        description=(
            f"distributed lift from VSPAero ({len(entries)} mesh nodes, "
            f"total {total_fz_n:.3f} N)"
        ),
        entries=tuple(entries),
        total_fz_n=total_fz_n,
        source_path=Path(cfg.io.vsp_lod),
        source_kind="vsp_aero",
        comparison_basis="limited",
        comparison_note="VSPAero-derived loads are useful when spar CSV is absent, but they are a looser comparison contract than the generated structural load export.",
    )


def _map_spanwise_forces_to_mesh(
    *,
    mesh_path: Path,
    cfg: HPAConfig,
    y_stations_m: np.ndarray,
    force_z_n: np.ndarray,
    mesh_length_scale_m_per_unit: float,
) -> list[LoadEntry]:
    nodes = parse_inp_nodes(mesh_path)
    if nodes.size == 0:
        return []

    force_by_node: dict[int, float] = {}
    for y_m, force_n in zip(y_stations_m, force_z_n, strict=True):
        if abs(float(force_n)) <= 1.0e-12:
            continue
        node_id = _nearest_node_for_spanwise_y(
            mesh_path,
            float(y_m),
            cfg,
            mesh_nodes=nodes,
            mesh_length_scale_m_per_unit=mesh_length_scale_m_per_unit,
        )
        force_by_node[node_id] = force_by_node.get(node_id, 0.0) + float(force_n)

    return [
        (node_id, 3, magnitude)
        for node_id, magnitude in sorted(force_by_node.items())
        if abs(magnitude) > 1.0e-9
    ]


def _nearest_node_for_spanwise_y(
    mesh_path: Path,
    y_target_m: float,
    cfg: HPAConfig,
    *,
    mesh_nodes: np.ndarray | None = None,
    mesh_length_scale_m_per_unit: float | None = None,
) -> int:
    nodes = parse_inp_nodes(mesh_path) if mesh_nodes is None else mesh_nodes
    if mesh_length_scale_m_per_unit is None:
        mesh_length_scale_m_per_unit = _mesh_length_scale_m_per_unit(mesh_path, cfg, mesh_nodes=nodes)

    y_coords = np.asarray(nodes[:, 2], dtype=float)
    x_coords = np.asarray(nodes[:, 1], dtype=float)
    z_coords = np.asarray(nodes[:, 3], dtype=float)
    y_target_units = float(y_target_m) / float(mesh_length_scale_m_per_unit)
    delta_y = np.abs(y_coords - y_target_units)
    min_delta = float(np.min(delta_y))
    band = max(min_delta + 1.0e-12, 0.25 * np.median(np.diff(np.unique(np.sort(y_coords)))) if len(np.unique(y_coords)) > 1 else min_delta + 1.0)
    candidate_mask = delta_y <= band
    candidate_indices = np.where(candidate_mask)[0]
    if candidate_indices.size == 0:
        candidate_indices = np.asarray([int(np.argmin(delta_y))], dtype=int)
    x_ref = float(np.median(x_coords[candidate_indices]))
    z_ref = float(np.median(z_coords[candidate_indices]))
    distance = delta_y[candidate_indices] + 1.0e-6 * (
        np.abs(x_coords[candidate_indices] - x_ref) + np.abs(z_coords[candidate_indices] - z_ref)
    )
    best_idx = int(candidate_indices[int(np.argmin(distance))])
    return int(nodes[best_idx, 0])


def _mesh_length_scale_m_per_unit(
    mesh_path: Path,
    cfg: HPAConfig,
    *,
    mesh_nodes: np.ndarray | None = None,
) -> float:
    nodes = parse_inp_nodes(mesh_path) if mesh_nodes is None else mesh_nodes
    if nodes.size == 0:
        return 1.0
    y_coords = np.asarray(nodes[:, 2], dtype=float)
    mesh_half_span_units = float(np.max(np.abs(y_coords)))
    if mesh_half_span_units <= 0.0:
        return 1.0
    return float(cfg.half_span) / mesh_half_span_units


def _node_spacings(y_nodes: np.ndarray) -> np.ndarray:
    dy = np.diff(y_nodes)
    if dy.size == 0:
        return np.ones_like(y_nodes)
    out = np.zeros(len(y_nodes), dtype=float)
    out[0] = dy[0] / 2.0
    out[-1] = dy[-1] / 2.0
    for idx in range(1, len(y_nodes) - 1):
        out[idx] = 0.5 * (dy[idx - 1] + dy[idx])
    return out


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _representative_section_thickness_m(cfg: HPAConfig) -> float:
    thicknesses = [float(cfg.main_spar.min_wall_thickness)]
    if cfg.rear_spar.enabled:
        thicknesses.append(float(cfg.rear_spar.min_wall_thickness))
    return float(np.mean(thicknesses))


def _match_tip_displacement_by_coordinates(
    *,
    mesh_path: Path,
    frd_path: Path,
    tip_node: int,
    displacement_rows: np.ndarray,
    mesh_length_scale_m_per_unit: float,
) -> tuple[np.ndarray | None, float | None]:
    mesh_nodes = parse_inp_nodes(mesh_path)
    tip_rows = mesh_nodes[mesh_nodes[:, 0].astype(int) == int(tip_node)]
    if tip_rows.size == 0:
        return None, None

    frd_nodes = parse_nodal_coordinates(frd_path)
    if frd_nodes.size == 0:
        return None, None

    target_xyz = tip_rows[-1, 1:4]
    distances = np.linalg.norm(frd_nodes[:, 1:4] - target_xyz, axis=1)
    nearest_idx = int(np.argmin(distances))
    nearest_node = int(frd_nodes[nearest_idx, 0])
    matches = displacement_rows[displacement_rows[:, 0].astype(int) == nearest_node]
    if matches.size == 0:
        return None, None

    return matches[-1], float(distances[nearest_idx]) * mesh_length_scale_m_per_unit
