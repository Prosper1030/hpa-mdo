"""Standalone orchestration for the structural high-fidelity validation stack.

This module intentionally sits outside the optimisation loop.  It glues the
existing STEP -> Gmsh -> CalculiX -> FRD/ParaView helpers into one callable
entry point so validation can be launched without hand-running four scripts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from hpa_mdo.core import MaterialDB, load_config
from hpa_mdo.core.config import HPAConfig
from hpa_mdo.core.constants import G_STANDARD
from hpa_mdo.hifi.calculix_runner import (
    prepare_buckle_inp,
    prepare_static_inp,
    root_boundary_from_mesh,
    run_static,
    tip_node_from_mesh,
)
from hpa_mdo.hifi.frd_parser import parse_buckle_eigenvalues, parse_displacement
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


@dataclass(frozen=True)
class StructuralCheckResult:
    """Combined result for the structural validation run."""

    report_path: Path
    overall_status: str
    summary_path: Path | None
    step_path: Path | None
    mesh_path: Path | None
    paraview_script_path: Path | None
    static: StructuralCheckSection
    buckle: StructuralCheckSection


def parse_optimization_summary(summary_path: str | Path) -> dict[str, float | None]:
    """Extract the metrics needed by the validation stack from a text summary."""

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
        candidate = output_dir / "optimization_summary.txt"
        resolved_summary = candidate if candidate.exists() else None
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
        static = StructuralCheckSection(
            status="SKIP",
            message=(
                "No mesh available. Provide --mesh or create a STEP export first "
                "with scripts/vsp_to_cfd.py + scripts/hifi_mesh_step.py."
            ),
        )
        buckle = StructuralCheckSection(
            status="SKIP",
            message="Buckling check skipped because no CalculiX mesh was available.",
        )
        _write_combined_report(
            report_path,
            summary_path=resolved_summary,
            step_path=resolved_step,
            mesh_path=resolved_mesh,
            paraview_script_path=None,
            static=static,
            buckle=buckle,
            reference_metrics=summary_metrics,
        )
        return StructuralCheckResult(
            report_path=report_path,
            overall_status="SKIP",
            summary_path=resolved_summary,
            step_path=resolved_step,
            mesh_path=resolved_mesh,
            paraview_script_path=None,
            static=static,
            buckle=buckle,
        )

    material_payload = _material_payload(material_key)
    load_n = (
        float(tip_load_n)
        if tip_load_n is not None
        else -0.5 * float(cfg.weight.max_takeoff_kg) * G_STANDARD
    )

    static = _run_static_check(
        mesh_path=resolved_mesh,
        hifi_dir=hifi_root,
        cfg=cfg,
        material_payload=material_payload,
        expected_tip_deflection_m=summary_metrics["tip_deflection_m"],
        tip_load_n=load_n,
    )
    buckle = _run_buckle_check(
        mesh_path=resolved_mesh,
        hifi_dir=hifi_root,
        cfg=cfg,
        material_payload=material_payload,
        expected_buckling_index=summary_metrics["buckling_index"],
        tip_load_n=load_n,
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
    _write_combined_report(
        report_path,
        summary_path=resolved_summary,
        step_path=resolved_step,
        mesh_path=resolved_mesh,
        paraview_script_path=paraview_script_path,
        static=static,
        buckle=buckle,
        reference_metrics=summary_metrics,
    )
    overall_status = _combine_status(static.status, buckle.status)
    return StructuralCheckResult(
        report_path=report_path,
        overall_status=overall_status,
        summary_path=resolved_summary,
        step_path=resolved_step,
        mesh_path=resolved_mesh,
        paraview_script_path=paraview_script_path,
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
    tip_load_n: float,
) -> StructuralCheckSection:
    try:
        root_boundary = root_boundary_from_mesh(mesh_path)
        tip_node = tip_node_from_mesh(mesh_path)
    except Exception as exc:  # noqa: BLE001
        return StructuralCheckSection(
            status="WARN",
            message=f"Could not derive ROOT/TIP from mesh: {exc}",
        )

    static_inp = hifi_dir / f"{mesh_path.stem}_static.inp"
    prepare_static_inp(
        mesh_path,
        static_inp,
        material_payload,
        _boundary_arg(root_boundary),
        [(tip_node, 3, tip_load_n)],
    )
    result = run_static(static_inp, cfg)
    if result.get("error"):
        return StructuralCheckSection(
            status="WARN",
            message=f"CalculiX static failed or was skipped: {result['error']}",
            artifact_path=static_inp,
        )

    frd_path = Path(result["frd"]).resolve()
    disp = parse_displacement(frd_path)
    if disp.size == 0:
        return StructuralCheckSection(
            status="WARN",
            message=f"No displacement rows found in {frd_path}",
            artifact_path=frd_path,
        )

    matches = disp[disp[:, 0].astype(int) == int(tip_node)]
    if matches.size == 0:
        return StructuralCheckSection(
            status="WARN",
            message=f"Tip node {tip_node} not found in FRD displacement output.",
            artifact_path=frd_path,
        )

    tip_deflection_m = abs(float(matches[-1, 3]))
    diff_pct = _pct_diff(tip_deflection_m, expected_tip_deflection_m)
    status = "PASS" if diff_pct is not None and abs(diff_pct) <= 5.0 else "WARN"
    if expected_tip_deflection_m is None:
        status = "SKIP"
    message = (
        "Static tip-deflection check completed."
        if expected_tip_deflection_m is not None
        else "Static run completed, but no reference tip deflection was available."
    )
    return StructuralCheckSection(
        status=status,
        message=message,
        actual=tip_deflection_m,
        expected=expected_tip_deflection_m,
        diff_pct=diff_pct,
        artifact_path=frd_path,
    )


def _run_buckle_check(
    *,
    mesh_path: Path,
    hifi_dir: Path,
    cfg: HPAConfig,
    material_payload: dict[str, float],
    expected_buckling_index: float | None,
    tip_load_n: float,
) -> StructuralCheckSection:
    try:
        root_boundary = root_boundary_from_mesh(mesh_path)
        tip_node = tip_node_from_mesh(mesh_path)
    except Exception as exc:  # noqa: BLE001
        return StructuralCheckSection(
            status="WARN",
            message=f"Could not derive ROOT/TIP from mesh: {exc}",
        )

    buckle_inp = hifi_dir / f"{mesh_path.stem}_buckle.inp"
    prepare_buckle_inp(
        mesh_path,
        buckle_inp,
        material_payload,
        _boundary_arg(root_boundary),
        [(tip_node, 3, tip_load_n)],
    )
    result = run_static(buckle_inp, cfg)
    if result.get("error"):
        return StructuralCheckSection(
            status="WARN",
            message=f"CalculiX BUCKLE failed or was skipped: {result['error']}",
            artifact_path=buckle_inp,
        )

    dat_path = Path(result["dat"]).resolve()
    frd_path = Path(result["frd"]).resolve()
    eigenvalues = parse_buckle_eigenvalues(dat_path)
    if not eigenvalues:
        return StructuralCheckSection(
            status="WARN",
            message=f"No BUCKLE eigenvalues found in {dat_path}",
            artifact_path=frd_path,
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
    message = (
        "Buckling check completed."
        if expected_buckling_index is not None
        else "BUCKLE run completed, but no reference buckling index was available."
    )
    return StructuralCheckSection(
        status=status,
        message=message,
        actual=lambda_1,
        expected=expected_buckling_index,
        threshold=threshold,
        margin=margin,
        artifact_path=frd_path,
    )


def _material_payload(material_key: str) -> dict[str, float]:
    materials_db = MaterialDB(REPO_ROOT / "data" / "materials.yaml")
    material = materials_db.get(material_key)
    return {
        "E": float(material.E),
        "nu": float(material.poisson_ratio),
        "rho": float(material.density),
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


def _discover_default_step(output_dir: Path) -> Path | None:
    for name in ("wing_cruise.step", "cruise.step", "wing_jig.step", "jig.step"):
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


def _write_combined_report(
    report_path: Path,
    *,
    summary_path: Path | None,
    step_path: Path | None,
    mesh_path: Path | None,
    paraview_script_path: Path | None,
    static: StructuralCheckSection,
    buckle: StructuralCheckSection,
    reference_metrics: dict[str, float | None],
) -> None:
    overall_status = _combine_status(static.status, buckle.status)
    lines = [
        "# High-Fidelity Structural Check",
        "",
        f"- Overall status: {overall_status}",
        f"- Summary input: {summary_path or '—'}",
        f"- STEP input: {step_path or '—'}",
        f"- Mesh input: {mesh_path or '—'}",
        f"- ParaView script: {paraview_script_path or '—'}",
        "",
        "## Reference Metrics",
        "",
        f"- Tip deflection [m]: {_fmt(reference_metrics.get('tip_deflection_m'))}",
        f"- Buckling index: {_fmt(reference_metrics.get('buckling_index'))}",
        "",
        "## Static Deflection",
        "",
        f"- Status: {static.status}",
        f"- Message: {static.message}",
        f"- Hifi |uz_tip| [m]: {_fmt(static.actual)}",
        f"- MDO tip deflection [m]: {_fmt(static.expected)}",
        f"- Diff [%]: {_fmt(static.diff_pct)}",
        f"- Artifact: {static.artifact_path or '—'}",
        "",
        "## Buckling",
        "",
        f"- Status: {buckle.status}",
        f"- Message: {buckle.message}",
        f"- lambda_1: {_fmt(buckle.actual)}",
        f"- MDO buckling index: {_fmt(buckle.expected)}",
        f"- lambda_threshold: {_fmt(buckle.threshold)}",
        f"- margin_lambda: {_fmt(buckle.margin)}",
        f"- Artifact: {buckle.artifact_path or '—'}",
        "",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")


def _fmt(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.6g}"


def _boundary_arg(boundary_entries: list[tuple[int, tuple[int, ...]]]) -> Any:
    """Adapt a canonical boundary list to the legacy CalculiX helper API."""

    if len(boundary_entries) == 1:
        return boundary_entries[0]
    return boundary_entries
